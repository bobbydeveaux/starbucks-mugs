"""Redis-backed sliding window rate limiting middleware.

Enforces per-tenant request-rate limits using a **sorted-set sliding window**
stored in Redis. Each request timestamp is recorded with the tenant's key; old
entries outside the window are pruned atomically before the count is checked.

The algorithm is implemented with a single Lua script so that the ZREMRANGEBYSCORE,
ZADD, ZCARD, and EXPIRE calls execute as one atomic Redis operation, preventing
races between concurrent requests from the same tenant.

Behaviour
---------
- Rate limit defaults to 100 req/min; per-tenant overrides come from
  ``request.state.tenant.rate_limit_rpm`` (populated by :mod:`auth` middleware).
- Exceeding the limit returns **HTTP 429** with a ``Retry-After`` header
  indicating when the oldest request in the window will expire.
- If Redis is **unavailable** the middleware logs a warning and passes the request
  through (fail-open for rate limiting only — scan failures remain fail-secure).

Redis key format
----------------
``fileguard:rl:{tenant_id}``

Each entry is a member of a sorted set where the score is the request timestamp
in milliseconds (Unix epoch), allowing efficient range-based pruning.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# Public constants — used by tests and by RateLimitMiddleware defaults.
# These match the project-wide defaults defined in fileguard.config.Settings.
DEFAULT_RPM: int = 100
WINDOW_SECONDS: int = 60

# Lua script for atomic sliding window check.
#
# KEYS[1] = sorted set key  (e.g. "fileguard:rl:tenant-uuid")
# ARGV[1] = current time in milliseconds (integer string)
# ARGV[2] = window duration in milliseconds (integer string)
# ARGV[3] = unique member for this request (e.g. "{timestamp}-{id}")
# ARGV[4] = maximum allowed requests in the window
#
# Returns a two-element array:
#   [0] = current request count (after adding this request)
#   [1] = score (ms timestamp) of the oldest entry in the window
#
_SLIDING_WINDOW_LUA = """
local key        = KEYS[1]
local now_ms     = tonumber(ARGV[1])
local window_ms  = tonumber(ARGV[2])
local member     = ARGV[3]
local limit      = tonumber(ARGV[4])

-- Remove entries older than the window
redis.call('ZREMRANGEBYSCORE', key, 0, now_ms - window_ms)

-- Add this request with the current timestamp as score
redis.call('ZADD', key, now_ms, member)

-- Count entries in the window
local count = redis.call('ZCARD', key)

-- Refresh TTL so orphaned keys don't accumulate
redis.call('EXPIRE', key, math.ceil(window_ms / 1000) + 1)

-- Oldest entry score (for Retry-After calculation)
local oldest_range = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local oldest_score = now_ms
if #oldest_range == 2 then
    oldest_score = tonumber(oldest_range[2])
end

return {count, oldest_score}
"""

_KEY_PREFIX = "fileguard:rl"


def _build_key(tenant_id: str) -> str:
    """Return the Redis sorted-set key for a given tenant."""
    return f"{_KEY_PREFIX}:{tenant_id}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiting middleware backed by Redis sorted sets.

    Must be registered **after** :class:`~fileguard.api.middleware.auth.AuthMiddleware`
    so that ``request.state.tenant`` is already populated when this middleware runs.

    Parameters
    ----------
    app:
        The ASGI application to wrap.
    redis_client:
        An async Redis client instance. If ``None`` the middleware operates in
        pass-through mode (useful for local development without Redis).
    default_rpm:
        Fallback requests-per-minute limit used when the tenant config does not
        provide an override. Defaults to 100.
    window_seconds:
        Sliding window duration in seconds. Defaults to 60.
    public_paths:
        Set of URL paths that bypass rate limiting (e.g. health check, docs).
    """

    def __init__(
        self,
        app: ASGIApp,
        redis_client: Redis | None,
        default_rpm: int = DEFAULT_RPM,
        window_seconds: int = WINDOW_SECONDS,
        public_paths: frozenset[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._redis = redis_client
        self._default_rpm = default_rpm
        self._window_ms = window_seconds * 1000
        self._public_paths: frozenset[str] = public_paths or frozenset(
            {"/healthz", "/v1/openapi.json", "/v1/docs"}
        )
        # Pre-register the Lua script with the client so it is loaded once
        self._script: object | None = None
        if self._redis is not None:
            self._script = self._redis.register_script(_SLIDING_WINDOW_LUA)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self._public_paths:
            return await call_next(request)

        tenant = getattr(request.state, "tenant", None)
        if tenant is None:
            # Auth middleware has not set a tenant — pass through and let the
            # auth middleware's own error response handle the unauthenticated case.
            return await call_next(request)

        tenant_id = str(tenant.id)
        rpm_limit: int = getattr(tenant, "rate_limit_rpm", None) or self._default_rpm

        if self._redis is None:
            logger.warning(
                "Redis unavailable (client is None); rate limiting disabled for tenant %s",
                tenant_id,
            )
            return await call_next(request)

        now_ms = int(time.time() * 1000)
        # Unique member prevents collisions when multiple requests from the same
        # tenant arrive within the same millisecond.
        member = f"{now_ms}-{id(request)}"
        key = _build_key(tenant_id)

        try:
            result = await self._script(  # type: ignore[misc]
                keys=[key],
                args=[now_ms, self._window_ms, member, rpm_limit],
            )
            count: int = int(result[0])
            oldest_score_ms: int = int(result[1])
        except RedisError as exc:
            logger.warning(
                "Redis error during rate limit check for tenant %s; allowing request: %s",
                tenant_id,
                exc,
            )
            return await call_next(request)

        if count > rpm_limit:
            # How long until the oldest entry exits the window
            retry_after_ms = max(0, oldest_score_ms + self._window_ms - now_ms)
            retry_after_seconds = math.ceil(retry_after_ms / 1000)
            reset_epoch = math.ceil((oldest_score_ms + self._window_ms) / 1000)

            logger.info(
                "Rate limit exceeded for tenant %s: %d/%d requests in window",
                tenant_id,
                count,
                rpm_limit,
            )

            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded",
                    "limit": rpm_limit,
                    "window_seconds": self._window_ms // 1000,
                    "retry_after_seconds": retry_after_seconds,
                },
                headers={
                    "Retry-After": str(retry_after_seconds),
                    "X-RateLimit-Limit": str(rpm_limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_epoch),
                },
            )

        # Request is within limit — set informational rate-limit headers
        remaining = max(0, rpm_limit - count)
        reset_epoch = math.ceil((oldest_score_ms + self._window_ms) / 1000)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(rpm_limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_epoch)
        return response
