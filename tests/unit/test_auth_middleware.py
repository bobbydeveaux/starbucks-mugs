"""Unit tests for fileguard/api/middleware/auth.py and fileguard/schemas/tenant.py.

All tests are fully offline – database and JWKS fetches are replaced by
``unittest.mock`` patches so no external services are required.
"""

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import bcrypt
import pytest
from httpx import HTTPStatusError, Request as HttpxRequest, Response as HttpxResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from fileguard.api.middleware.auth import (
    AuthMiddleware,
    _is_jwt,
    _verify_api_key,
)
from fileguard.schemas.tenant import TenantConfig


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_tenant_row(
    *,
    api_key_hash: str | None = None,
    jwks_url: str | None = None,
    client_id: str | None = None,
    rate_limit_rpm: int = 100,
) -> MagicMock:
    """Return a mock ORM TenantConfig row."""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.api_key_hash = api_key_hash
    row.jwks_url = jwks_url
    row.client_id = client_id
    row.rate_limit_rpm = rate_limit_rpm
    row.disposition_rules = None
    row.custom_patterns = None
    row.webhook_url = None
    row.siem_config = None
    return row


def _hash_key(raw: str) -> str:
    return bcrypt.hashpw(raw.encode(), bcrypt.gensalt()).decode()


def _build_app() -> Starlette:
    """Minimal Starlette app wrapped with AuthMiddleware for integration tests."""

    async def protected(request: Request) -> PlainTextResponse:
        tenant_id = str(request.state.tenant.id)
        return PlainTextResponse(f"ok:{tenant_id}")

    app = Starlette(routes=[Route("/protected", protected)])
    app.add_middleware(AuthMiddleware)
    return app


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

class TestIsJwt:
    def test_three_parts_is_jwt(self) -> None:
        assert _is_jwt("a.b.c") is True

    def test_two_parts_not_jwt(self) -> None:
        assert _is_jwt("a.b") is False

    def test_opaque_string_not_jwt(self) -> None:
        assert _is_jwt("supersecretapikey123") is False

    def test_four_parts_not_jwt(self) -> None:
        # JWE would have 5 parts; 4 is neither JWT nor JWE
        assert _is_jwt("a.b.c.d") is False


class TestVerifyApiKey:
    def test_correct_key_returns_true(self) -> None:
        raw = "my-secret-key"
        hashed = _hash_key(raw)
        assert _verify_api_key(raw, hashed) is True

    def test_wrong_key_returns_false(self) -> None:
        raw = "correct-key"
        hashed = _hash_key(raw)
        assert _verify_api_key("wrong-key", hashed) is False

    def test_malformed_hash_returns_false(self) -> None:
        assert _verify_api_key("some-key", "not-a-valid-bcrypt-hash") is False


# ---------------------------------------------------------------------------
# TenantConfig schema validation
# ---------------------------------------------------------------------------

class TestTenantConfigSchema:
    def test_valid_minimal(self) -> None:
        tc = TenantConfig(id=uuid.uuid4())
        assert tc.rate_limit_rpm == 100
        assert tc.api_key_hash is None
        assert tc.jwks_url is None
        assert tc.client_id is None

    def test_all_fields(self) -> None:
        tenant_id = uuid.uuid4()
        tc = TenantConfig(
            id=tenant_id,
            api_key_hash="$2b$12$xxx",
            jwks_url="https://auth.example.com/.well-known/jwks.json",
            client_id="my-client",
            rate_limit_rpm=200,
        )
        assert tc.id == tenant_id
        assert tc.rate_limit_rpm == 200
        assert tc.client_id == "my-client"

    def test_negative_rate_limit_rejected(self) -> None:
        with pytest.raises(Exception):
            TenantConfig(id=uuid.uuid4(), rate_limit_rpm=-1)

    def test_from_orm_row(self) -> None:
        row = _make_tenant_row(api_key_hash=_hash_key("k"), rate_limit_rpm=50)
        tc = TenantConfig.model_validate(row)
        assert tc.id == row.id
        assert tc.rate_limit_rpm == 50


# ---------------------------------------------------------------------------
# Integration tests via TestClient
# ---------------------------------------------------------------------------

class TestAuthMiddlewareNoAuthHeader:
    def setup_method(self) -> None:
        self.client = TestClient(_build_app(), raise_server_exceptions=False)

    def test_missing_header_returns_401(self) -> None:
        response = self.client.get("/protected")
        assert response.status_code == 401
        assert "detail" in response.json()

    def test_wrong_scheme_returns_401(self) -> None:
        response = self.client.get("/protected", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert response.status_code == 401

    def test_empty_bearer_returns_401(self) -> None:
        response = self.client.get("/protected", headers={"Authorization": "Bearer "})
        assert response.status_code == 401


class TestAuthMiddlewareApiKey:
    RAW_KEY = "test-api-key-abc123"

    def setup_method(self) -> None:
        self.app = _build_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.hashed = _hash_key(self.RAW_KEY)

    def _patch_load(self, row: Any) -> Any:
        return patch(
            "fileguard.api.middleware.auth._load_tenant_for_api_key",
            new_callable=AsyncMock,
            return_value=row,
        )

    def test_valid_api_key_returns_200(self) -> None:
        row = _make_tenant_row(api_key_hash=self.hashed)
        with self._patch_load(row):
            response = self.client.get(
                "/protected",
                headers={"Authorization": f"Bearer {self.RAW_KEY}"},
            )
        assert response.status_code == 200
        assert response.text.startswith("ok:")

    def test_unknown_api_key_returns_403(self) -> None:
        with self._patch_load(None):
            response = self.client.get(
                "/protected",
                headers={"Authorization": "Bearer unknown-key"},
            )
        assert response.status_code == 403

    def test_tenant_attached_to_state(self) -> None:
        row = _make_tenant_row(api_key_hash=self.hashed)
        with self._patch_load(row):
            response = self.client.get(
                "/protected",
                headers={"Authorization": f"Bearer {self.RAW_KEY}"},
            )
        assert response.status_code == 200
        tenant_id_in_body = response.text.split(":")[1]
        assert tenant_id_in_body == str(row.id)


class TestAuthMiddlewareJwt:
    """Tests for the OAuth 2.0 JWT path using mocked helpers."""

    # A syntactically valid three-part token (content is not checked because
    # verification functions are patched).
    FAKE_JWT = "header.payload.signature"

    def setup_method(self) -> None:
        self.app = _build_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def _patch_load(self, row: Any) -> Any:
        return patch(
            "fileguard.api.middleware.auth._load_tenant_for_jwt",
            new_callable=AsyncMock,
            return_value=row,
        )

    def _patch_verify(self, result: bool) -> Any:
        return patch(
            "fileguard.api.middleware.auth._verify_jwt",
            new_callable=AsyncMock,
            return_value=result,
        )

    def test_valid_jwt_returns_200(self) -> None:
        row = _make_tenant_row(jwks_url="https://auth.example.com/.well-known/jwks.json", client_id="cid")
        with self._patch_load(row), self._patch_verify(True):
            response = self.client.get(
                "/protected",
                headers={"Authorization": f"Bearer {self.FAKE_JWT}"},
            )
        assert response.status_code == 200

    def test_invalid_jwt_signature_returns_401(self) -> None:
        row = _make_tenant_row(jwks_url="https://auth.example.com/.well-known/jwks.json", client_id="cid")
        with self._patch_load(row), self._patch_verify(False):
            response = self.client.get(
                "/protected",
                headers={"Authorization": f"Bearer {self.FAKE_JWT}"},
            )
        assert response.status_code == 401

    def test_unknown_tenant_for_jwt_returns_403(self) -> None:
        with self._patch_load(None):
            response = self.client.get(
                "/protected",
                headers={"Authorization": f"Bearer {self.FAKE_JWT}"},
            )
        assert response.status_code == 403


class TestHealthzBypassesAuth:
    def setup_method(self) -> None:
        async def healthz(request: Request) -> PlainTextResponse:
            return PlainTextResponse("ok")

        app = Starlette(routes=[Route("/healthz", healthz)])
        app.add_middleware(AuthMiddleware)
        self.client = TestClient(app)

    def test_healthz_returns_200_without_auth(self) -> None:
        response = self.client.get("/healthz")
        assert response.status_code == 200
        assert response.text == "ok"
