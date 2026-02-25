"""Authentication middleware for the FileGuard API.

Two bearer-token authentication paths are supported:

1. **API key** – the token is a raw (non-JWT) string.  The middleware hashes
   the presented value with bcrypt and compares it to the stored
   ``api_key_hash`` on the matching TenantConfig row.

2. **OAuth 2.0 JWT** – the token is a compact JWT (three Base64URL-encoded
   segments separated by dots).  The middleware verifies the signature against
   the public keys fetched from the tenant's ``jwks_url`` and checks that the
   ``aud`` claim matches ``client_id``.

On success the validated :class:`~fileguard.schemas.tenant.TenantConfig` is
attached to ``request.state.tenant`` for downstream handlers and middleware
to consume.

HTTP responses on failure:

* ``401 Unauthorized`` – no ``Authorization`` header, malformed/invalid token.
* ``403 Forbidden`` – valid token format but no matching tenant record.
"""

import logging
import time
from typing import Any

import bcrypt
import httpx
from jose import JWTError, jwk, jwt
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from fileguard.db.session import AsyncSessionLocal
from fileguard.models.tenant_config import TenantConfig as TenantConfigModel
from fileguard.schemas.tenant import TenantConfig

logger = logging.getLogger(__name__)

# Paths that bypass authentication (health / readiness endpoints)
_UNAUTHENTICATED_PATHS: frozenset[str] = frozenset({"/healthz", "/v1/docs", "/v1/openapi.json"})

# Simple in-process JWKS cache: maps jwks_url -> (keys_list, expiry_timestamp)
_jwks_cache: dict[str, tuple[list[dict[str, Any]], float]] = {}
_JWKS_CACHE_TTL_SECONDS: float = 300.0  # 5 minutes


def _is_jwt(token: str) -> bool:
    """Return True if *token* looks like a compact JWT (three dot-separated parts)."""
    parts = token.split(".")
    return len(parts) == 3


async def _fetch_jwks(jwks_url: str) -> list[dict[str, Any]]:
    """Fetch and cache the JWKS for *jwks_url*.

    Uses a simple in-process TTL cache to avoid hitting the JWKS endpoint on
    every request.  The cache is intentionally not shared across processes; a
    short TTL is sufficient because key rotations are infrequent.
    """
    now = time.monotonic()
    cached = _jwks_cache.get(jwks_url)
    if cached is not None:
        keys, expiry = cached
        if now < expiry:
            return keys

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(jwks_url)
        response.raise_for_status()
        data = response.json()

    keys: list[dict[str, Any]] = data.get("keys", [])
    _jwks_cache[jwks_url] = (keys, now + _JWKS_CACHE_TTL_SECONDS)
    return keys


async def _verify_jwt(token: str, tenant_row: TenantConfigModel) -> bool:
    """Verify an OAuth 2.0 JWT against the tenant's JWKS.

    Returns ``True`` if the signature is valid and the ``aud`` claim matches
    ``tenant_row.client_id``; ``False`` otherwise.
    """
    if not tenant_row.jwks_url or not tenant_row.client_id:
        return False

    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        keys = await _fetch_jwks(str(tenant_row.jwks_url))

        # Select the matching key by ``kid`` if present, otherwise try all keys
        matching_keys = [k for k in keys if kid is None or k.get("kid") == kid]
        if not matching_keys:
            logger.warning("No matching JWK found for kid=%s", kid)
            return False

        for key_data in matching_keys:
            try:
                public_key = jwk.construct(key_data)
                jwt.decode(
                    token,
                    public_key,
                    algorithms=[key_data.get("alg", "RS256")],
                    audience=tenant_row.client_id,
                )
                return True
            except JWTError:
                continue

        return False

    except (JWTError, httpx.HTTPError, ValueError) as exc:
        logger.warning("JWT verification failed: %s", exc)
        return False


def _verify_api_key(token: str, api_key_hash: str) -> bool:
    """Return ``True`` if *token* matches *api_key_hash* via bcrypt."""
    try:
        return bcrypt.checkpw(token.encode(), api_key_hash.encode())
    except Exception as exc:
        logger.warning("bcrypt comparison failed: %s", exc)
        return False


async def _load_tenant_for_jwt(token: str) -> TenantConfigModel | None:
    """Look up the tenant whose ``client_id`` matches the JWT ``aud`` claim.

    Returns ``None`` if the ``aud`` claim is missing or no matching tenant
    exists.
    """
    try:
        claims = jwt.get_unverified_claims(token)
        aud = claims.get("aud")
        if not aud:
            return None
        # ``aud`` may be a list; normalise to string for comparison
        if isinstance(aud, list):
            aud = aud[0] if aud else None
        if not aud:
            return None
    except JWTError:
        return None

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TenantConfigModel).where(TenantConfigModel.client_id == aud)
        )
        return result.scalar_one_or_none()


async def _load_tenant_for_api_key(token: str) -> TenantConfigModel | None:
    """Return the *first* tenant whose ``api_key_hash`` matches *token* via bcrypt.

    Because bcrypt comparison is O(n) in the number of tenants, this approach
    is only practical for small tenant counts.  Production deployments should
    store a fast lookup index (e.g., a prefix of the hash) alongside the full
    hash to narrow candidates before the bcrypt check.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TenantConfigModel).where(TenantConfigModel.api_key_hash.is_not(None))
        )
        rows = result.scalars().all()

    for row in rows:
        if _verify_api_key(token, row.api_key_hash):  # type: ignore[arg-type]
            return row
    return None


def _json_401(detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=401)


def _json_403(detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=403)


class AuthMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces bearer-token authentication.

    Attaches a validated :class:`~fileguard.schemas.tenant.TenantConfig`
    to ``request.state.tenant`` on success.  Paths listed in
    :data:`_UNAUTHENTICATED_PATHS` bypass authentication entirely.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:  # type: ignore[override]
        if request.url.path in _UNAUTHENTICATED_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _json_401("Missing or invalid Authorization header")

        token = auth_header[len("Bearer "):]
        if not token:
            return _json_401("Empty bearer token")

        tenant_row: TenantConfigModel | None = None
        authenticated = False

        if _is_jwt(token):
            # OAuth 2.0 path: look up tenant by aud claim, then verify signature
            tenant_row = await _load_tenant_for_jwt(token)
            if tenant_row is None:
                return _json_403("Unrecognised tenant")
            authenticated = await _verify_jwt(token, tenant_row)
            if not authenticated:
                return _json_401("Invalid or expired JWT")
        else:
            # API key path: scan tenants for bcrypt match
            tenant_row = await _load_tenant_for_api_key(token)
            if tenant_row is None:
                return _json_403("Unrecognised tenant")
            authenticated = True  # match found by _load_tenant_for_api_key

        request.state.tenant = TenantConfig.model_validate(tenant_row)
        logger.info(
            "Authenticated tenant=%s path=%s",
            request.state.tenant.id,
            request.url.path,
        )
        return await call_next(request)
