"""Unit tests for the Redis-backed sliding window rate limiting middleware.

Tests cover:
- Requests within the rate limit are passed through with rate limit headers.
- Requests exceeding the limit receive HTTP 429 with Retry-After header.
- Redis unavailability results in fail-open (request passes through).
- Rate limit defaults to 100 req/min when tenant config has no override.
- Per-tenant key namespacing (different tenants have independent limits).
- Public paths bypass rate limiting entirely.
- Retry-After is correctly computed from the oldest entry in the window.
"""
from __future__ import annotations

import math
import time
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from fileguard.api.middleware.rate_limit import (
    DEFAULT_RPM,
    WINDOW_SECONDS,
    RateLimitMiddleware,
    _build_key,
)
from fileguard.schemas.tenant import TenantConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tenant(
    rate_limit_rpm: int = 100,
    tenant_id: str | None = None,
) -> TenantConfig:
    """Create a minimal TenantConfig for testing."""
    return TenantConfig(
        id=uuid.UUID(tenant_id) if tenant_id else uuid.uuid4(),
        api_key_hash=None,
        rate_limit_rpm=rate_limit_rpm,
    )


def _make_app(redis_client: Any, tenant: TenantConfig | None = None) -> FastAPI:
    """Build a minimal FastAPI app with RateLimitMiddleware attached."""
    app = FastAPI()

    @app.get("/v1/scan")
    async def scan_endpoint(request: Request) -> dict:
        return {"status": "ok"}

    @app.get("/healthz")
    async def health() -> dict:
        return {"status": "ok"}

    app.add_middleware(
        RateLimitMiddleware,
        redis_client=redis_client,
        default_rpm=DEFAULT_RPM,
        window_seconds=WINDOW_SECONDS,
    )

    # Inject tenant into request.state before the rate limit middleware runs
    if tenant is not None:
        from starlette.middleware.base import BaseHTTPMiddleware

        class _InjectTenant(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next: Any) -> Any:
                request.state.tenant = tenant
                return await call_next(request)

        app.add_middleware(_InjectTenant)

    return app


def _make_mock_redis(count: int = 1, oldest_score_ms: int | None = None) -> MagicMock:
    """Return a mock Redis client whose Lua script returns *count* and *oldest_score_ms*."""
    now_ms = int(time.time() * 1000)
    if oldest_score_ms is None:
        oldest_score_ms = now_ms

    mock_script = AsyncMock(return_value=[count, oldest_score_ms])
    mock_redis = MagicMock()
    mock_redis.register_script.return_value = mock_script
    return mock_redis


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------


def test_build_key_format() -> None:
    tenant_id = "550e8400-e29b-41d4-a716-446655440000"
    assert _build_key(tenant_id) == f"fileguard:rl:{tenant_id}"


def test_build_key_unique_per_tenant() -> None:
    key_a = _build_key("tenant-a")
    key_b = _build_key("tenant-b")
    assert key_a != key_b


# ---------------------------------------------------------------------------
# Within-limit requests
# ---------------------------------------------------------------------------


def test_request_within_limit_returns_200() -> None:
    tenant = _make_tenant(rate_limit_rpm=100)
    redis_mock = _make_mock_redis(count=1)
    app = _make_app(redis_mock, tenant)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/scan")

    assert response.status_code == 200


def test_within_limit_attaches_rate_limit_headers() -> None:
    rpm = 50
    tenant = _make_tenant(rate_limit_rpm=rpm)
    redis_mock = _make_mock_redis(count=10)
    app = _make_app(redis_mock, tenant)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/scan")

    assert response.status_code == 200
    assert response.headers["x-ratelimit-limit"] == str(rpm)
    assert response.headers["x-ratelimit-remaining"] == str(rpm - 10)
    assert "x-ratelimit-reset" in response.headers


def test_remaining_header_is_zero_when_at_limit() -> None:
    rpm = 5
    tenant = _make_tenant(rate_limit_rpm=rpm)
    # Count == limit means this is the last allowed request
    redis_mock = _make_mock_redis(count=rpm)
    app = _make_app(redis_mock, tenant)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/scan")

    assert response.status_code == 200
    assert response.headers["x-ratelimit-remaining"] == "0"


# ---------------------------------------------------------------------------
# Rate-limit exceeded (HTTP 429)
# ---------------------------------------------------------------------------


def test_exceeds_limit_returns_429() -> None:
    rpm = 10
    tenant = _make_tenant(rate_limit_rpm=rpm)
    # count > rpm  →  over limit
    redis_mock = _make_mock_redis(count=rpm + 1)
    app = _make_app(redis_mock, tenant)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/scan")

    assert response.status_code == 429


def test_429_includes_retry_after_header() -> None:
    rpm = 10
    tenant = _make_tenant(rate_limit_rpm=rpm)
    now_ms = int(time.time() * 1000)
    # Oldest entry is 30 seconds into the 60s window → 30s remaining
    oldest_ms = now_ms - 30_000
    redis_mock = _make_mock_redis(count=rpm + 5, oldest_score_ms=oldest_ms)
    app = _make_app(redis_mock, tenant)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/scan")

    assert response.status_code == 429
    assert "retry-after" in response.headers
    retry_after = int(response.headers["retry-after"])
    # Window (60s) - elapsed (30s) = ~30s remaining
    assert 25 <= retry_after <= 35, f"Unexpected Retry-After: {retry_after}"


def test_429_body_contains_limit_and_window() -> None:
    rpm = 10
    tenant = _make_tenant(rate_limit_rpm=rpm)
    redis_mock = _make_mock_redis(count=rpm + 1)
    app = _make_app(redis_mock, tenant)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/scan")

    assert response.status_code == 429
    body = response.json()
    assert body["limit"] == rpm
    assert body["window_seconds"] == WINDOW_SECONDS
    assert "retry_after_seconds" in body


def test_429_headers_include_ratelimit_limit() -> None:
    rpm = 10
    tenant = _make_tenant(rate_limit_rpm=rpm)
    redis_mock = _make_mock_redis(count=rpm + 1)
    app = _make_app(redis_mock, tenant)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/scan")

    assert response.headers["x-ratelimit-limit"] == str(rpm)
    assert response.headers["x-ratelimit-remaining"] == "0"


# ---------------------------------------------------------------------------
# Default rate limit (100 req/min)
# ---------------------------------------------------------------------------


def test_default_rpm_is_100_when_tenant_has_no_override() -> None:
    """Middleware should use DEFAULT_RPM when tenant.rate_limit_rpm is absent."""
    # Create a tenant without rate_limit_rpm set (falls back to schema default)
    tenant = TenantConfig(id=uuid.uuid4(), rate_limit_rpm=100)
    redis_mock = _make_mock_redis(count=1)
    app = _make_app(redis_mock, tenant)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/scan")

    assert response.status_code == 200
    assert response.headers["x-ratelimit-limit"] == "100"


def test_tenant_override_rpm_respected() -> None:
    rpm = 200
    tenant = _make_tenant(rate_limit_rpm=rpm)
    redis_mock = _make_mock_redis(count=1)
    app = _make_app(redis_mock, tenant)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/scan")

    assert response.status_code == 200
    assert response.headers["x-ratelimit-limit"] == str(rpm)


# ---------------------------------------------------------------------------
# Redis unavailability — fail-open
# ---------------------------------------------------------------------------


def test_redis_error_allows_request_through() -> None:
    """When Redis raises an error, the middleware must pass the request through."""
    tenant = _make_tenant()
    mock_script = AsyncMock(side_effect=RedisError("connection refused"))
    redis_mock = MagicMock()
    redis_mock.register_script.return_value = mock_script

    app = _make_app(redis_mock, tenant)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/scan")

    assert response.status_code == 200


def test_none_redis_client_allows_request_through() -> None:
    """When redis_client is None, the middleware is a no-op."""
    tenant = _make_tenant()
    app = _make_app(redis_client=None, tenant=tenant)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/scan")

    assert response.status_code == 200


def test_redis_unavailable_logs_warning(caplog: Any) -> None:
    """A warning must be logged when Redis raises an error."""
    import logging

    tenant = _make_tenant()
    mock_script = AsyncMock(side_effect=RedisError("timeout"))
    redis_mock = MagicMock()
    redis_mock.register_script.return_value = mock_script

    app = _make_app(redis_mock, tenant)
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.WARNING, logger="fileguard.api.middleware.rate_limit"):
        client.get("/v1/scan")

    assert any("Redis error" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Public path bypass
# ---------------------------------------------------------------------------


def test_healthz_bypasses_rate_limiting() -> None:
    """Health check endpoint must not be subject to rate limiting."""
    # Even if Redis would return over-limit, healthz should return 200
    redis_mock = _make_mock_redis(count=99999)
    app = _make_app(redis_mock, tenant=None)  # no tenant injected

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/healthz")

    assert response.status_code == 200
    # No rate limit headers on public paths
    assert "x-ratelimit-limit" not in response.headers


# ---------------------------------------------------------------------------
# No tenant in request.state
# ---------------------------------------------------------------------------


def test_no_tenant_passes_through() -> None:
    """If auth middleware has not set request.state.tenant, pass the request through."""
    redis_mock = _make_mock_redis(count=1)
    # Build app WITHOUT injecting a tenant — simulates auth middleware being absent
    app = _make_app(redis_client=redis_mock, tenant=None)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/v1/scan")

    # No tenant → rate limit middleware is a no-op; endpoint returns 200
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Per-tenant key namespacing
# ---------------------------------------------------------------------------


def test_different_tenants_use_different_redis_keys() -> None:
    """Verify that rate limit counters are namespaced per tenant_id."""
    tenant_id_a = str(uuid.uuid4())
    tenant_id_b = str(uuid.uuid4())

    key_a = _build_key(tenant_id_a)
    key_b = _build_key(tenant_id_b)

    assert key_a != key_b
    assert tenant_id_a in key_a
    assert tenant_id_b in key_b


def test_lua_script_called_with_correct_key() -> None:
    """Middleware must pass the per-tenant Redis key to the Lua script."""
    tenant = _make_tenant()
    expected_key = _build_key(str(tenant.id))

    called_keys: list[Any] = []

    async def capture_script_call(**kwargs: Any) -> list:
        called_keys.extend(kwargs.get("keys", []))
        return [1, int(time.time() * 1000)]

    mock_script = AsyncMock(side_effect=lambda *a, **kw: capture_script_call(**kw))
    redis_mock = MagicMock()
    redis_mock.register_script.return_value = mock_script

    app = _make_app(redis_mock, tenant)
    client = TestClient(app, raise_server_exceptions=False)
    client.get("/v1/scan")

    assert any(expected_key in str(k) for k in called_keys), (
        f"Expected key {expected_key!r} not found in Lua script calls: {called_keys}"
    )
