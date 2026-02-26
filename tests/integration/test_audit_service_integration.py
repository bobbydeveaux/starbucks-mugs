"""Integration tests for AuditService with a real SQLAlchemy async session.

These tests use an **in-memory SQLite** database (via ``aiosqlite`` + ``StaticPool``)
so that no PostgreSQL server is required.  They exercise the full SQLAlchemy ORM
lifecycle: ``add`` -> ``flush`` -> SELECT query -> HMAC verification.

Test scope
----------
- Full write -> flush persistence cycle via the real ORM
- HMAC integrity: signature computed before flush verifies correctly after read-back
- Append-only guard: SQLAlchemy ``before_update`` / ``before_delete`` hooks raise
  ``RuntimeError`` when mutation is attempted
- SIEM forwarding integration via ``httpx`` mock transport: real HTTP request /
  response lifecycle without any external network calls

Database compatibility note
----------------------------
SQLAlchemy transparently maps PostgreSQL-specific column types (``JSONB``,
``UUID``) to SQLite-compatible storage.  Named ``Enum`` types become ``VARCHAR``
check constraints.  ``server_default`` expressions (``gen_random_uuid()``,
``now()``) are included in DDL but never evaluated here because the test
fixtures always supply explicit values in their ORM objects.

``StaticPool`` is used so all SQLAlchemy connections share the same underlying
``aiosqlite`` connection and therefore the same in-memory database.
"""
from __future__ import annotations

import uuid
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from fileguard.db.base import Base
from fileguard.models.scan_event import ScanEvent
from fileguard.models.tenant_config import TenantConfig as TenantConfigModel

# Ensure all ORM models are registered with Base.metadata so create_all is complete
import fileguard.models  # noqa: F401

from fileguard.services.audit import AuditService


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SIGNING_KEY = "integration-test-signing-key-secure!!"


# ---------------------------------------------------------------------------
# Session-scoped engine: schema is created once per test session
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Async SQLite in-memory engine.  ``StaticPool`` keeps all connections in
    the same underlying DB so the schema persists across the fixture lifetime."""
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
    """Function-scoped session that rolls back all changes after each test."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        try:
            await sess.rollback()
        except Exception:
            pass


@pytest_asyncio.fixture
async def tenant(session: AsyncSession) -> TenantConfigModel:
    """Insert a minimal TenantConfig row into the session."""
    row = TenantConfigModel(
        id=uuid.uuid4(),
        api_key_hash="$2b$12$placeholder_hash",
        rate_limit_rpm=100,
    )
    session.add(row)
    await session.flush()
    return row


@pytest.fixture
def service() -> AuditService:
    return AuditService(signing_key=SIGNING_KEY)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _scan_kwargs(tenant_id: uuid.UUID, **overrides) -> dict:
    """Return default kwargs for AuditService.log_scan_event."""
    defaults = dict(
        tenant_id=tenant_id,
        file_hash="a" * 64,
        file_name="test.pdf",
        file_size_bytes=4096,
        mime_type="application/pdf",
        status="clean",
        action_taken="pass",
        findings=[],
        scan_duration_ms=300,
    )
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------


class TestPersistence:
    async def test_event_is_returned(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        event = await service.log_scan_event(session=session, **_scan_kwargs(tenant.id))
        assert isinstance(event, ScanEvent)
        assert event.id is not None

    async def test_event_is_queryable_after_flush(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        event = await service.log_scan_event(session=session, **_scan_kwargs(tenant.id))

        result = await session.execute(select(ScanEvent).where(ScanEvent.id == event.id))
        fetched = result.scalar_one_or_none()
        assert fetched is not None

    async def test_all_fields_persisted(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        file_hash = "b" * 64
        findings = [{"type": "pii", "category": "NHS_NUMBER", "severity": "high"}]
        event = await service.log_scan_event(
            session=session,
            **_scan_kwargs(
                tenant.id,
                file_hash=file_hash,
                file_name="report.docx",
                file_size_bytes=8192,
                mime_type="application/octet-stream",
                status="flagged",
                action_taken="quarantine",
                findings=findings,
                scan_duration_ms=1500,
            ),
        )

        assert event.tenant_id == tenant.id
        assert event.file_hash == file_hash
        assert event.file_name == "report.docx"
        assert event.file_size_bytes == 8192
        assert event.status == "flagged"
        assert event.action_taken == "quarantine"
        assert event.findings == findings
        assert event.scan_duration_ms == 1500

    async def test_multiple_events_stored_independently(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        e1 = await service.log_scan_event(
            session=session, **_scan_kwargs(tenant.id, file_hash="c" * 64)
        )
        e2 = await service.log_scan_event(
            session=session, **_scan_kwargs(tenant.id, file_hash="d" * 64)
        )
        assert e1.id != e2.id
        assert e1.file_hash != e2.file_hash

    async def test_created_at_has_timezone(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        event = await service.log_scan_event(session=session, **_scan_kwargs(tenant.id))
        assert event.created_at.tzinfo is not None

    async def test_hmac_signature_is_64_hex_chars(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        event = await service.log_scan_event(session=session, **_scan_kwargs(tenant.id))
        assert len(event.hmac_signature) == 64
        assert all(c in "0123456789abcdef" for c in event.hmac_signature)


# ---------------------------------------------------------------------------
# HMAC integrity round-trip
# ---------------------------------------------------------------------------


class TestHmacIntegrity:
    async def test_hmac_verifies_after_flush(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        event = await service.log_scan_event(
            session=session,
            **_scan_kwargs(tenant.id, status="flagged", action_taken="quarantine"),
        )
        assert service.verify_hmac(event) is True

    async def test_hmac_detects_status_tampering(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        event = await service.log_scan_event(session=session, **_scan_kwargs(tenant.id))

        original_status = event.status
        event.status = "rejected"  # simulate tampering without updating HMAC
        assert service.verify_hmac(event) is False
        event.status = original_status  # restore

    async def test_hmac_detects_action_taken_tampering(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        event = await service.log_scan_event(
            session=session,
            **_scan_kwargs(tenant.id, status="flagged", action_taken="quarantine"),
        )
        event.action_taken = "pass"  # tamper
        assert service.verify_hmac(event) is False
        event.action_taken = "quarantine"

    async def test_hmac_unique_per_event(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        e1 = await service.log_scan_event(
            session=session, **_scan_kwargs(tenant.id, file_hash="e" * 64)
        )
        e2 = await service.log_scan_event(
            session=session, **_scan_kwargs(tenant.id, file_hash="f" * 64)
        )
        assert e1.hmac_signature != e2.hmac_signature

    async def test_all_events_have_valid_hmac(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        events = [
            await service.log_scan_event(
                session=session, **_scan_kwargs(tenant.id, file_hash=f"{i:064d}")
            )
            for i in range(5)
        ]
        for event in events:
            assert service.verify_hmac(event), f"HMAC invalid for scan_id={event.id}"


# ---------------------------------------------------------------------------
# Append-only guard (SQLAlchemy ORM event hooks on ScanEvent)
# ---------------------------------------------------------------------------


class TestAppendOnlyGuard:
    async def test_update_raises_runtime_error(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        """Mutating a ScanEvent field then flushing must raise RuntimeError."""
        event = await service.log_scan_event(session=session, **_scan_kwargs(tenant.id))

        event.scan_duration_ms = 99999  # triggers before_update hook on flush
        with pytest.raises(RuntimeError, match="append-only"):
            await session.flush()

    async def test_delete_raises_runtime_error(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        """Deleting a ScanEvent must raise RuntimeError on flush."""
        event = await service.log_scan_event(session=session, **_scan_kwargs(tenant.id))

        await session.delete(event)
        with pytest.raises(RuntimeError, match="append-only"):
            await session.flush()


# ---------------------------------------------------------------------------
# Query patterns
# ---------------------------------------------------------------------------


class TestQueryPatterns:
    async def test_filter_by_tenant(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        for i in range(3):
            await service.log_scan_event(
                session=session, **_scan_kwargs(tenant.id, file_hash=f"{i:064d}")
            )

        result = await session.execute(
            select(ScanEvent).where(ScanEvent.tenant_id == tenant.id)
        )
        rows = result.scalars().all()
        assert len(rows) == 3

    async def test_filter_by_status(
        self, service: AuditService, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        await service.log_scan_event(
            session=session,
            **_scan_kwargs(tenant.id, status="clean", action_taken="pass", file_hash="g" * 64),
        )
        await service.log_scan_event(
            session=session,
            **_scan_kwargs(
                tenant.id, status="flagged", action_taken="quarantine", file_hash="h" * 64
            ),
        )

        result = await session.execute(
            select(ScanEvent).where(
                ScanEvent.tenant_id == tenant.id, ScanEvent.status == "flagged"
            )
        )
        flagged = result.scalars().all()
        assert len(flagged) == 1
        assert flagged[0].status == "flagged"


# ---------------------------------------------------------------------------
# SIEM forwarding integration via httpx mock transport
# ---------------------------------------------------------------------------


class _RecordingTransport(httpx.AsyncBaseTransport):
    """Async httpx transport that records requests and returns a canned response."""

    def __init__(self, status_code: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self._status_code = status_code

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status_code, json={"text": "Success"})


class TestSiemForwarding:
    @pytest_asyncio.fixture
    async def transport(self) -> _RecordingTransport:
        return _RecordingTransport(status_code=200)

    @pytest_asyncio.fixture
    async def siem_service(self, transport: _RecordingTransport) -> AuditService:
        client = httpx.AsyncClient(transport=transport)
        return AuditService(signing_key=SIGNING_KEY, http_client=client)

    async def test_siem_receives_request_on_log(
        self,
        siem_service: AuditService,
        session: AsyncSession,
        tenant: TenantConfigModel,
        transport: _RecordingTransport,
    ) -> None:
        siem_cfg = {
            "type": "splunk",
            "endpoint": "https://splunk.example.com/services/collector",
            "token": "hec-token",
        }
        await siem_service.log_scan_event(
            session=session, siem_config=siem_cfg, **_scan_kwargs(tenant.id)
        )
        assert len(transport.requests) == 1

    async def test_siem_request_hits_correct_endpoint(
        self,
        siem_service: AuditService,
        session: AsyncSession,
        tenant: TenantConfigModel,
        transport: _RecordingTransport,
    ) -> None:
        endpoint = "https://splunk.example.com/services/collector/event"
        siem_cfg = {"type": "splunk", "endpoint": endpoint, "token": "tok"}
        await siem_service.log_scan_event(
            session=session, siem_config=siem_cfg, **_scan_kwargs(tenant.id)
        )
        assert str(transport.requests[0].url) == endpoint

    async def test_siem_splunk_auth_header(
        self,
        siem_service: AuditService,
        session: AsyncSession,
        tenant: TenantConfigModel,
        transport: _RecordingTransport,
    ) -> None:
        siem_cfg = {
            "type": "splunk",
            "endpoint": "https://splunk.example.com/services/collector",
            "token": "my-hec-token",
        }
        await siem_service.log_scan_event(
            session=session, siem_config=siem_cfg, **_scan_kwargs(tenant.id)
        )
        req = transport.requests[0]
        assert req.headers.get("authorization") == "Splunk my-hec-token"

    async def test_siem_payload_contains_scan_id(
        self,
        siem_service: AuditService,
        session: AsyncSession,
        tenant: TenantConfigModel,
        transport: _RecordingTransport,
    ) -> None:
        import json as _json

        siem_cfg = {"type": "watchtower", "endpoint": "https://wt.example.com/api/events"}
        event = await siem_service.log_scan_event(
            session=session, siem_config=siem_cfg, **_scan_kwargs(tenant.id)
        )
        body = _json.loads(transport.requests[0].content)
        assert body["scan_id"] == str(event.id)

    async def test_siem_not_called_without_config(
        self,
        siem_service: AuditService,
        session: AsyncSession,
        tenant: TenantConfigModel,
        transport: _RecordingTransport,
    ) -> None:
        await siem_service.log_scan_event(
            session=session, siem_config=None, **_scan_kwargs(tenant.id)
        )
        assert len(transport.requests) == 0

    async def test_siem_500_does_not_propagate(
        self, session: AsyncSession, tenant: TenantConfigModel
    ) -> None:
        """A 500 SIEM response must not raise from log_scan_event."""
        transport = _RecordingTransport(status_code=500)
        client = httpx.AsyncClient(transport=transport)
        svc = AuditService(signing_key=SIGNING_KEY, http_client=client)

        siem_cfg = {
            "type": "splunk",
            "endpoint": "https://splunk.example.com/hec",
            "token": "tok",
        }
        event = await svc.log_scan_event(
            session=session, siem_config=siem_cfg, **_scan_kwargs(tenant.id)
        )
        assert event is not None

    async def test_multiple_events_each_trigger_siem(
        self,
        siem_service: AuditService,
        session: AsyncSession,
        tenant: TenantConfigModel,
        transport: _RecordingTransport,
    ) -> None:
        siem_cfg = {"type": "watchtower", "endpoint": "https://wt.example.com/api/events"}
        for i in range(3):
            await siem_service.log_scan_event(
                session=session,
                siem_config=siem_cfg,
                **_scan_kwargs(tenant.id, file_hash=f"{i:064d}"),
            )
        assert len(transport.requests) == 3
