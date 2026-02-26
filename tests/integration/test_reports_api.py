"""Integration tests for GET /v1/reports and GET /v1/reports/{id}/download.

Test coverage
-------------
* List endpoint (GET /v1/reports):
  - Returns 200 with an empty item list when no reports exist
  - Returns all reports for the authenticated tenant
  - Pagination: page / page_size query params slice correctly
  - ``format`` query param filters by report format
  - ``start_date`` / ``end_date`` query params filter by period
  - Cross-tenant isolation: reports from other tenants are never returned

* Download endpoint (GET /v1/reports/{id}/download):
  - Returns 200 with Content-Type application/pdf for a PDF report
  - Returns 200 with Content-Type application/json for a JSON report
  - Format selection via ``format`` query param overrides stored format
  - Format selection via ``Accept`` header overrides stored format
  - Returns 404 for an unknown report ID
  - Returns 404 for a report belonging to another tenant (cross-tenant isolation)
  - Returns 404 when the file stored at file_uri does not exist on disk

All tests use an in-memory SQLite database (aiosqlite + StaticPool) so no
external services are required.  ``httpx.AsyncClient`` with ``ASGITransport``
is used so the async session and HTTP requests share the same event loop.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from fileguard.api.handlers.reports import router as reports_router
from fileguard.db.base import Base
from fileguard.db.session import get_db
from fileguard.models.compliance_report import ComplianceReport
from fileguard.models.tenant_config import TenantConfig as TenantConfigModel
from fileguard.schemas.tenant import TenantConfig

# Ensure all ORM models are registered before schema creation
import fileguard.models  # noqa: F401


# ---------------------------------------------------------------------------
# In-memory SQLite engine + session fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="module")
async def engine():
    """Module-scoped in-memory SQLite engine; schema created once per module."""
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Function-scoped session; rolls back all changes after each test."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        try:
            await sess.rollback()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _insert_tenant(session: AsyncSession) -> TenantConfigModel:
    """Insert and flush a minimal TenantConfig row."""
    row = TenantConfigModel(
        id=uuid.uuid4(),
        api_key_hash="$2b$12$placeholder",
        rate_limit_rpm=100,
    )
    session.add(row)
    await session.flush()
    return row


async def _insert_report(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    format: str = "json",
    file_uri: str = "/tmp/report.json",
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    generated_at: datetime | None = None,
) -> ComplianceReport:
    """Insert and flush a ComplianceReport row."""
    now = datetime.now(tz=timezone.utc)
    report = ComplianceReport(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        period_start=period_start or now.replace(day=1),
        period_end=period_end or now,
        format=format,
        file_uri=file_uri,
        generated_at=generated_at or now,
    )
    session.add(report)
    await session.flush()
    return report


# ---------------------------------------------------------------------------
# Minimal FastAPI app factory with stub auth middleware
# ---------------------------------------------------------------------------


class _StubAuthMiddleware(BaseHTTPMiddleware):
    """Injects a fake ``request.state.tenant`` without any real DB lookup."""

    def __init__(self, app: ASGIApp, tenant: TenantConfig) -> None:
        super().__init__(app)
        self._tenant = tenant

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        request.state.tenant = self._tenant
        return await call_next(request)


def _build_app(tenant: TenantConfig, session_override: AsyncSession) -> FastAPI:
    """Return a minimal FastAPI app wired with the reports router.

    The ``get_db`` dependency is overridden with the provided in-memory
    SQLite session so every handler runs within the test transaction.
    """
    application = FastAPI()
    application.include_router(reports_router)
    application.add_middleware(_StubAuthMiddleware, tenant=tenant)

    async def _override_get_db():
        yield session_override

    application.dependency_overrides[get_db] = _override_get_db
    return application


def _make_tenant_schema(orm_row: TenantConfigModel) -> TenantConfig:
    return TenantConfig.model_validate(orm_row)


def _async_client(app: FastAPI) -> httpx.AsyncClient:
    """Return an AsyncClient bound to *app* via ASGITransport."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


# ---------------------------------------------------------------------------
# GET /v1/reports — list endpoint
# ---------------------------------------------------------------------------


class TestListReports:
    """Tests for GET /v1/reports."""

    async def test_empty_list_when_no_reports(self, session: AsyncSession) -> None:
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)
        app = _build_app(tenant, session)

        async with _async_client(app) as client:
            response = await client.get("/v1/reports")

        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["page"] == 1
        assert body["page_size"] == 20

    async def test_returns_reports_for_tenant(self, session: AsyncSession) -> None:
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)

        r1 = await _insert_report(session, tenant_row.id, format="json")
        r2 = await _insert_report(session, tenant_row.id, format="pdf")

        app = _build_app(tenant, session)
        async with _async_client(app) as client:
            response = await client.get("/v1/reports")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        returned_ids = {item["id"] for item in body["items"]}
        assert str(r1.id) in returned_ids
        assert str(r2.id) in returned_ids

    async def test_pagination_page_size(self, session: AsyncSession) -> None:
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)

        for _ in range(5):
            await _insert_report(session, tenant_row.id)

        app = _build_app(tenant, session)
        async with _async_client(app) as client:
            response = await client.get(
                "/v1/reports", params={"page": 1, "page_size": 3}
            )

        body = response.json()
        assert response.status_code == 200
        assert body["total"] == 5
        assert len(body["items"]) == 3
        assert body["page"] == 1
        assert body["page_size"] == 3

    async def test_pagination_second_page(self, session: AsyncSession) -> None:
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)

        for _ in range(5):
            await _insert_report(session, tenant_row.id)

        app = _build_app(tenant, session)
        async with _async_client(app) as client:
            p1 = (
                await client.get("/v1/reports", params={"page": 1, "page_size": 3})
            ).json()
            p2 = (
                await client.get("/v1/reports", params={"page": 2, "page_size": 3})
            ).json()

        assert len(p1["items"]) == 3
        assert len(p2["items"]) == 2
        ids_p1 = {item["id"] for item in p1["items"]}
        ids_p2 = {item["id"] for item in p2["items"]}
        assert ids_p1.isdisjoint(ids_p2), "Pages must not share items"

    async def test_format_filter(self, session: AsyncSession) -> None:
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)

        await _insert_report(session, tenant_row.id, format="pdf")
        await _insert_report(session, tenant_row.id, format="json")

        app = _build_app(tenant, session)
        async with _async_client(app) as client:
            response = await client.get("/v1/reports", params={"format": "pdf"})

        body = response.json()
        assert response.status_code == 200
        assert body["total"] == 1
        assert body["items"][0]["format"] == "pdf"

    async def test_cross_tenant_isolation(self, session: AsyncSession) -> None:
        """Reports from another tenant must never appear in the list."""
        tenant_a = await _insert_tenant(session)
        tenant_b = await _insert_tenant(session)

        await _insert_report(session, tenant_a.id, format="json")
        await _insert_report(session, tenant_b.id, format="json")

        tenant_a_schema = _make_tenant_schema(tenant_a)
        app = _build_app(tenant_a_schema, session)

        async with _async_client(app) as client:
            response = await client.get("/v1/reports")

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["tenant_id"] == str(tenant_a.id)

    async def test_start_date_filter(self, session: AsyncSession) -> None:
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)

        early = datetime(2025, 1, 1, tzinfo=timezone.utc)
        late = datetime(2026, 1, 1, tzinfo=timezone.utc)

        await _insert_report(
            session,
            tenant_row.id,
            period_start=early,
            period_end=early.replace(month=2),
        )
        await _insert_report(
            session,
            tenant_row.id,
            period_start=late,
            period_end=late.replace(month=2),
        )

        app = _build_app(tenant, session)
        async with _async_client(app) as client:
            response = await client.get(
                "/v1/reports", params={"start_date": "2025-07-01"}
            )

        body = response.json()
        assert response.status_code == 200
        assert body["total"] == 1
        assert body["items"][0]["period_start"].startswith("2026")

    async def test_invalid_start_date_returns_422(self, session: AsyncSession) -> None:
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)
        app = _build_app(tenant, session)

        async with _async_client(app) as client:
            response = await client.get(
                "/v1/reports", params={"start_date": "not-a-date"}
            )

        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/reports/{id}/download — download endpoint
# ---------------------------------------------------------------------------


class TestDownloadReport:
    """Tests for GET /v1/reports/{report_id}/download."""

    async def test_download_json_report(self, session: AsyncSession) -> None:
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)

        payload = json.dumps(
            {"file_count": 42, "verdict_breakdown": {"clean": 40, "flagged": 2}}
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write(payload)
            tmp_path = f.name

        try:
            report = await _insert_report(
                session, tenant_row.id, format="json", file_uri=tmp_path
            )
            app = _build_app(tenant, session)

            async with _async_client(app) as client:
                response = await client.get(f"/v1/reports/{report.id}/download")

            assert response.status_code == 200
            assert "application/json" in response.headers["content-type"]
            assert json.loads(response.content) == json.loads(payload)
        finally:
            os.unlink(tmp_path)

    async def test_download_pdf_report(self, session: AsyncSession) -> None:
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)

        pdf_content = b"%PDF-1.4 fake pdf content"
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_content)
            tmp_path = f.name

        try:
            report = await _insert_report(
                session, tenant_row.id, format="pdf", file_uri=tmp_path
            )
            app = _build_app(tenant, session)

            async with _async_client(app) as client:
                response = await client.get(f"/v1/reports/{report.id}/download")

            assert response.status_code == 200
            assert response.headers["content-type"] == "application/pdf"
            assert response.content == pdf_content
        finally:
            os.unlink(tmp_path)

    async def test_format_query_param_overrides_stored_format(
        self, session: AsyncSession
    ) -> None:
        """format=json query param forces JSON Content-Type regardless of stored format."""
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)

        json_payload = b'{"file_count": 1}'
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(json_payload)
            tmp_path = f.name

        try:
            report = await _insert_report(
                session, tenant_row.id, format="pdf", file_uri=tmp_path
            )
            app = _build_app(tenant, session)

            async with _async_client(app) as client:
                response = await client.get(
                    f"/v1/reports/{report.id}/download",
                    params={"format": "json"},
                )

            assert response.status_code == 200
            assert "application/json" in response.headers["content-type"]
        finally:
            os.unlink(tmp_path)

    async def test_accept_header_selects_pdf(self, session: AsyncSession) -> None:
        """Accept: application/pdf header overrides stored format."""
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)

        pdf_content = b"%PDF-fake"
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_content)
            tmp_path = f.name

        try:
            report = await _insert_report(
                session, tenant_row.id, format="json", file_uri=tmp_path
            )
            app = _build_app(tenant, session)

            async with _async_client(app) as client:
                response = await client.get(
                    f"/v1/reports/{report.id}/download",
                    headers={"Accept": "application/pdf"},
                )

            assert response.status_code == 200
            assert response.headers["content-type"] == "application/pdf"
        finally:
            os.unlink(tmp_path)

    async def test_accept_header_selects_json(self, session: AsyncSession) -> None:
        """Accept: application/json header overrides stored format."""
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)

        json_content = b'{"file_count": 5}'
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(json_content)
            tmp_path = f.name

        try:
            report = await _insert_report(
                session, tenant_row.id, format="pdf", file_uri=tmp_path
            )
            app = _build_app(tenant, session)

            async with _async_client(app) as client:
                response = await client.get(
                    f"/v1/reports/{report.id}/download",
                    headers={"Accept": "application/json"},
                )

            assert response.status_code == 200
            assert "application/json" in response.headers["content-type"]
        finally:
            os.unlink(tmp_path)

    async def test_unknown_report_id_returns_404(self, session: AsyncSession) -> None:
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)
        app = _build_app(tenant, session)

        async with _async_client(app) as client:
            response = await client.get(f"/v1/reports/{uuid.uuid4()}/download")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    async def test_cross_tenant_isolation_returns_404(
        self, session: AsyncSession
    ) -> None:
        """A report belonging to tenant B must return 404 when fetched as tenant A."""
        tenant_a = await _insert_tenant(session)
        tenant_b = await _insert_tenant(session)

        json_content = b'{"file_count": 0}'
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(json_content)
            tmp_path = f.name

        try:
            report_b = await _insert_report(
                session, tenant_b.id, format="json", file_uri=tmp_path
            )
            tenant_a_schema = _make_tenant_schema(tenant_a)
            app = _build_app(tenant_a_schema, session)

            async with _async_client(app) as client:
                response = await client.get(f"/v1/reports/{report_b.id}/download")

            assert response.status_code == 404
        finally:
            os.unlink(tmp_path)

    async def test_missing_file_returns_404(self, session: AsyncSession) -> None:
        """If the file_uri points to a non-existent file, return 404."""
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)

        report = await _insert_report(
            session,
            tenant_row.id,
            format="json",
            file_uri="/tmp/this-file-does-not-exist-99999.json",
        )
        app = _build_app(tenant, session)

        async with _async_client(app) as client:
            response = await client.get(f"/v1/reports/{report.id}/download")

        assert response.status_code == 404

    async def test_content_disposition_header_present(
        self, session: AsyncSession
    ) -> None:
        """Download response must include a Content-Disposition attachment header."""
        tenant_row = await _insert_tenant(session)
        tenant = _make_tenant_schema(tenant_row)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("{}")
            tmp_path = f.name

        try:
            report = await _insert_report(
                session, tenant_row.id, format="json", file_uri=tmp_path
            )
            app = _build_app(tenant, session)

            async with _async_client(app) as client:
                response = await client.get(f"/v1/reports/{report.id}/download")

            assert response.status_code == 200
            disposition = response.headers.get("content-disposition", "")
            assert "attachment" in disposition
            assert str(report.id) in disposition
        finally:
            os.unlink(tmp_path)
