"""Authentication middleware for FileGuard API.

Validates Bearer tokens on every incoming request and attaches a ``TenantConfig``
object to ``request.state.tenant`` for downstream use.

Two authentication paths are supported:
  - **API key** — the raw key is bcrypt-checked against the stored hash.
  - **OAuth 2.0 client credentials** — a signed JWT is verified against the
    tenant's JWKS endpoint.

Responses:
  - ``401 Unauthorized`` — no token, malformed token, or bad signature.
  - ``403 Forbidden`` — token is valid but the tenant is not recognised.
"""
from __future__ import annotations

import logging
from typing import Callable

import bcrypt
import httpx
import jwt
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from fileguard.schemas.tenant import TenantConfig

logger = logging.getLogger(__name__)

# Paths that bypass authentication entirely
_PUBLIC_PATHS: frozenset[str] = frozenset({"/healthz", "/v1/openapi.json", "/v1/docs"})

# Simple in-process JWKS cache: {jwks_url: {kid: public_key}}
_JWKS_CACHE: dict[str, dict[str, object]] = {}


async def _fetch_jwks(jwks_url: str) -> dict[str, object]:
    """Fetch and cache a JWKS endpoint, returning a kid→key mapping."""
    if jwks_url in _JWKS_CACHE:
        return _JWKS_CACHE[jwks_url]

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(jwks_url)
        response.raise_for_status()
        data = response.json()

    keys: dict[str, object] = {}
    for jwk in data.get("keys", []):
        kid = jwk.get("kid", "default")
        keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)  # type: ignore[attr-defined]

    _JWKS_CACHE[jwks_url] = keys
    return keys


async def _load_tenant_by_api_key(raw_key: str) -> TenantConfig | None:
    """Look up a tenant whose api_key_hash matches *raw_key*.

    In a full implementation this queries the database. This stub is replaced
    once the database session and ORM models are available (task-fileguard-feat-project-setup).
    """
    # TODO(task-fileguard-feat-project-setup): Replace with database lookup
    # e.g.: session.execute(select(TenantConfigModel))
    raise NotImplementedError(
        "_load_tenant_by_api_key requires database integration (task-fileguard-feat-project-setup)"
    )


async def _load_tenant_by_client_id(client_id: str) -> TenantConfig | None:
    """Look up a tenant by OAuth client ID.

    In a full implementation this queries the database. This stub is replaced
    once the database session and ORM models are available (task-fileguard-feat-project-setup).
    """
    # TODO(task-fileguard-feat-project-setup): Replace with database lookup
    raise NotImplementedError(
        "_load_tenant_by_client_id requires database integration (task-fileguard-feat-project-setup)"
    )


def _check_api_key(raw_key: str, hashed: str) -> bool:
    """Return True if *raw_key* matches the bcrypt *hashed* value."""
    return bcrypt.checkpw(raw_key.encode(), hashed.encode())


async def _verify_api_key(raw_key: str) -> TenantConfig | None:
    tenant = await _load_tenant_by_api_key(raw_key)
    if tenant is None:
        return None
    if not tenant.has_api_key_auth():
        return None
    assert tenant.api_key_hash is not None  # guaranteed by has_api_key_auth()
    if not _check_api_key(raw_key, tenant.api_key_hash):
        return None
    return tenant


async def _verify_jwt(token: str) -> TenantConfig | None:
    """Decode and verify a JWT; return the matching tenant or None."""
    try:
        # Decode header only to extract kid and determine issuer
        unverified = jwt.decode(token, options={"verify_signature": False})
        client_id: str = unverified.get("sub") or unverified.get("client_id", "")
    except jwt.DecodeError:
        return None

    tenant = await _load_tenant_by_client_id(client_id)
    if tenant is None or not tenant.has_oauth_auth():
        return None

    assert tenant.jwks_url is not None  # guaranteed by has_oauth_auth()
    try:
        keys = await _fetch_jwks(str(tenant.jwks_url))
    except Exception:
        logger.exception("Failed to fetch JWKS from %s", tenant.jwks_url)
        return None

    header = jwt.get_unverified_header(token)
    kid = header.get("kid", "default")
    public_key = keys.get(kid)
    if public_key is None:
        return None

    try:
        jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=tenant.audience,
        )
    except jwt.PyJWTError:
        return None

    return tenant


class AuthMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that authenticates every request via Bearer token.

    On success, ``request.state.tenant`` is set to the resolved ``TenantConfig``.
    On failure, the request is short-circuited with a 401 or 403 response.
    """

    def __init__(self, app: ASGIApp, public_paths: frozenset[str] = _PUBLIC_PATHS) -> None:
        super().__init__(app)
        self._public_paths = public_paths

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self._public_paths:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        raw_token = auth_header[7:]  # strip "Bearer "

        tenant: TenantConfig | None = None
        # Determine token type: JWTs contain two dots; API keys do not
        if raw_token.count(".") == 2:
            tenant = await _verify_jwt(raw_token)
        else:
            tenant = await _verify_api_key(raw_token)

        if tenant is None:
            return JSONResponse(
                status_code=403,
                content={"detail": "Tenant not found or credentials invalid"},
            )

        request.state.tenant = tenant
        return await call_next(request)
