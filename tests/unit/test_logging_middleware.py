"""Unit tests for fileguard/api/middleware/logging.py.

Tests are fully offline — no database or Redis connections are required.

Coverage targets:
* Correlation ID extracted from X-Correlation-ID header when present.
* Correlation ID extracted from X-Request-ID header when X-Correlation-ID is absent.
* Fresh UUID v4 generated when no correlation header is present.
* Correlation ID stored on request.state.correlation_id.
* Correlation ID echoed in X-Correlation-ID response header.
* Structured JSON log entry emitted at INFO level after each request.
* Log entry contains all required fields: event, correlation_id, tenant_id,
  method, path, status_code, duration_ms.
* tenant_id is populated from request.state.tenant when available.
* tenant_id is null when no tenant is attached (public / unauthenticated paths).
* duration_ms is a non-negative number.
"""

from __future__ import annotations

import json
import logging
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

from fileguard.api.middleware.logging import RequestLoggingMiddleware


# ---------------------------------------------------------------------------
# App factory helpers
# ---------------------------------------------------------------------------


def _make_app(inject_tenant: Any = None) -> FastAPI:
    """Build a minimal FastAPI app with RequestLoggingMiddleware.

    If *inject_tenant* is provided, a thin middleware layer sets
    ``request.state.tenant`` before the logging middleware reads it,
    simulating what AuthMiddleware would do in production.
    """
    app = FastAPI()

    @app.get("/v1/scan")
    async def scan(request: Request) -> dict:
        # Expose correlation_id from state so tests can assert on it
        corr_id = getattr(request.state, "correlation_id", None)
        return {"correlation_id": corr_id}

    @app.get("/healthz")
    async def health() -> dict:
        return {"status": "ok"}

    # Register RequestLoggingMiddleware as the outermost layer.
    # In Starlette, add_middleware in reverse order means the LAST one added
    # becomes the outermost (runs first).
    if inject_tenant is not None:
        class _InjectTenant(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next: Any) -> Any:
                request.state.tenant = inject_tenant
                return await call_next(request)

        app.add_middleware(_InjectTenant)

    app.add_middleware(RequestLoggingMiddleware)
    return app


def _make_tenant(tenant_id: str | None = None) -> SimpleNamespace:
    """Return a minimal tenant-like object with an ``id`` attribute."""
    return SimpleNamespace(id=uuid.UUID(tenant_id) if tenant_id else uuid.uuid4())


# ---------------------------------------------------------------------------
# Correlation ID extraction
# ---------------------------------------------------------------------------


class TestCorrelationIdExtraction:
    def test_uses_x_correlation_id_header_when_present(self, caplog: Any) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        expected_id = "my-custom-correlation-id"

        with caplog.at_level(logging.INFO, logger="fileguard.api.middleware.logging"):
            response = client.get(
                "/healthz",
                headers={"X-Correlation-ID": expected_id},
            )

        assert response.status_code == 200
        assert response.headers["x-correlation-id"] == expected_id

    def test_uses_x_request_id_header_when_no_correlation_id(self, caplog: Any) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        expected_id = "req-fallback-id-123"

        with caplog.at_level(logging.INFO, logger="fileguard.api.middleware.logging"):
            response = client.get(
                "/healthz",
                headers={"X-Request-ID": expected_id},
            )

        assert response.headers["x-correlation-id"] == expected_id

    def test_x_correlation_id_takes_priority_over_x_request_id(self) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            "/healthz",
            headers={
                "X-Correlation-ID": "primary-id",
                "X-Request-ID": "secondary-id",
            },
        )

        assert response.headers["x-correlation-id"] == "primary-id"

    def test_generates_uuid_when_no_correlation_header(self) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/healthz")

        corr_id = response.headers.get("x-correlation-id", "")
        assert len(corr_id) > 0
        # Should be a valid UUID
        parsed = uuid.UUID(corr_id)
        assert str(parsed) == corr_id

    def test_each_request_gets_unique_generated_id(self) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        ids = {client.get("/healthz").headers["x-correlation-id"] for _ in range(5)}
        assert len(ids) == 5


# ---------------------------------------------------------------------------
# request.state.correlation_id
# ---------------------------------------------------------------------------


class TestCorrelationIdOnRequestState:
    def test_correlation_id_set_on_request_state(self) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        expected_id = "state-test-corr-id"

        response = client.get(
            "/v1/scan",
            headers={"X-Correlation-ID": expected_id},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["correlation_id"] == expected_id

    def test_generated_id_also_set_on_request_state(self) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/v1/scan")

        assert response.status_code == 200
        body = response.json()
        state_corr_id = body["correlation_id"]
        response_corr_id = response.headers["x-correlation-id"]
        # Both must be present and equal
        assert state_corr_id is not None
        assert state_corr_id == response_corr_id


# ---------------------------------------------------------------------------
# Structured log entry — required fields
# ---------------------------------------------------------------------------


class TestStructuredLogEntry:
    def test_log_contains_event_field(self, caplog: Any) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.INFO, logger="fileguard.api.middleware.logging"):
            client.get("/healthz")

        records = [r for r in caplog.records if r.name == "fileguard.api.middleware.logging"]
        assert records, "No log record emitted by RequestLoggingMiddleware"
        entry = json.loads(records[-1].message)
        assert entry["event"] == "http_request"

    def test_log_contains_correlation_id(self, caplog: Any) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        corr_id = "log-test-corr-id"

        with caplog.at_level(logging.INFO, logger="fileguard.api.middleware.logging"):
            client.get("/healthz", headers={"X-Correlation-ID": corr_id})

        records = [r for r in caplog.records if r.name == "fileguard.api.middleware.logging"]
        entry = json.loads(records[-1].message)
        assert entry["correlation_id"] == corr_id

    def test_log_contains_method(self, caplog: Any) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.INFO, logger="fileguard.api.middleware.logging"):
            client.get("/healthz")

        records = [r for r in caplog.records if r.name == "fileguard.api.middleware.logging"]
        entry = json.loads(records[-1].message)
        assert entry["method"] == "GET"

    def test_log_contains_path(self, caplog: Any) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.INFO, logger="fileguard.api.middleware.logging"):
            client.get("/healthz")

        records = [r for r in caplog.records if r.name == "fileguard.api.middleware.logging"]
        entry = json.loads(records[-1].message)
        assert entry["path"] == "/healthz"

    def test_log_contains_status_code(self, caplog: Any) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.INFO, logger="fileguard.api.middleware.logging"):
            client.get("/healthz")

        records = [r for r in caplog.records if r.name == "fileguard.api.middleware.logging"]
        entry = json.loads(records[-1].message)
        assert entry["status_code"] == 200

    def test_log_contains_duration_ms(self, caplog: Any) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.INFO, logger="fileguard.api.middleware.logging"):
            client.get("/healthz")

        records = [r for r in caplog.records if r.name == "fileguard.api.middleware.logging"]
        entry = json.loads(records[-1].message)
        assert "duration_ms" in entry
        assert isinstance(entry["duration_ms"], (int, float))
        assert entry["duration_ms"] >= 0

    def test_log_contains_all_required_fields(self, caplog: Any) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.INFO, logger="fileguard.api.middleware.logging"):
            client.get("/healthz")

        records = [r for r in caplog.records if r.name == "fileguard.api.middleware.logging"]
        assert records, "No log record emitted"
        entry = json.loads(records[-1].message)
        for field in ("event", "correlation_id", "tenant_id", "method", "path", "status_code", "duration_ms"):
            assert field in entry, f"Missing field: {field}"

    def test_log_emitted_exactly_once_per_request(self, caplog: Any) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.INFO, logger="fileguard.api.middleware.logging"):
            client.get("/healthz")

        records = [r for r in caplog.records if r.name == "fileguard.api.middleware.logging"]
        assert len(records) == 1


# ---------------------------------------------------------------------------
# Tenant context in log entry
# ---------------------------------------------------------------------------


class TestTenantContextInLog:
    def test_log_contains_tenant_id_when_tenant_is_set(self, caplog: Any) -> None:
        tenant = _make_tenant()
        app = _make_app(inject_tenant=tenant)
        client = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.INFO, logger="fileguard.api.middleware.logging"):
            client.get("/v1/scan")

        records = [r for r in caplog.records if r.name == "fileguard.api.middleware.logging"]
        entry = json.loads(records[-1].message)
        assert entry["tenant_id"] == str(tenant.id)

    def test_log_tenant_id_is_null_when_no_tenant(self, caplog: Any) -> None:
        app = _make_app(inject_tenant=None)
        client = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.INFO, logger="fileguard.api.middleware.logging"):
            client.get("/healthz")

        records = [r for r in caplog.records if r.name == "fileguard.api.middleware.logging"]
        entry = json.loads(records[-1].message)
        assert entry["tenant_id"] is None

    def test_log_tenant_id_matches_specific_uuid(self, caplog: Any) -> None:
        specific_id = "550e8400-e29b-41d4-a716-446655440000"
        tenant = _make_tenant(tenant_id=specific_id)
        app = _make_app(inject_tenant=tenant)
        client = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.INFO, logger="fileguard.api.middleware.logging"):
            client.get("/v1/scan")

        records = [r for r in caplog.records if r.name == "fileguard.api.middleware.logging"]
        entry = json.loads(records[-1].message)
        assert entry["tenant_id"] == specific_id


# ---------------------------------------------------------------------------
# Response header propagation
# ---------------------------------------------------------------------------


class TestResponseHeaderPropagation:
    def test_x_correlation_id_header_present_in_response(self) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/healthz")

        assert "x-correlation-id" in response.headers

    def test_response_echoes_incoming_correlation_id(self) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)
        incoming = "echo-this-back"

        response = client.get("/healthz", headers={"X-Correlation-ID": incoming})

        assert response.headers["x-correlation-id"] == incoming

    def test_response_echoes_generated_correlation_id(self) -> None:
        app = _make_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/healthz")

        echoed = response.headers.get("x-correlation-id", "")
        assert len(echoed) > 0
        # Must be a valid UUID (auto-generated)
        uuid.UUID(echoed)
