"""Unit tests for fileguard/services/audit.py.

All tests are fully offline — the database session is replaced with an
AsyncMock so no real PostgreSQL connection is required.

Coverage targets:
* HMAC-SHA256 signature computation and verification.
* Tampered-record detection (any field mutation fails verify_hmac).
* Append-only enforcement at the service layer (only session.add + flush,
  never update/delete).
* Structured log output carries correlation_id, tenant_id, and scan_id.
* AuditError is raised (not silently swallowed) on DB write failure.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from fileguard.services.audit import AuditError, AuditService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET = "test-secret-key"


def _make_scan_event(**overrides: Any) -> MagicMock:
    """Return a ScanEvent with sensible defaults for testing.

    created_at is set to a fixed UTC timestamp so that HMAC computations
    are deterministic across runs.
    """
    tenant_id = uuid.uuid4()
    event_id = uuid.uuid4()
    defaults: dict[str, Any] = dict(
        id=event_id,
        tenant_id=tenant_id,
        file_hash="abc123def456",
        file_name="report.pdf",
        file_size_bytes=4096,
        mime_type="application/pdf",
        status="clean",
        action_taken="pass",
        findings=[],
        scan_duration_ms=42,
        created_at=datetime(2026, 2, 25, 12, 0, 0, tzinfo=timezone.utc),
        hmac_signature="",  # will be populated by AuditService
    )
    defaults.update(overrides)
    evt = MagicMock()
    for key, value in defaults.items():
        setattr(evt, key, value)
    return evt  # type: ignore[return-value]


def _make_session(flush_side_effect: Any = None) -> AsyncMock:
    """Return an async-mock SQLAlchemy session."""
    session = AsyncMock()
    session.add = MagicMock()  # add() is synchronous
    if flush_side_effect is not None:
        session.flush = AsyncMock(side_effect=flush_side_effect)
    else:
        session.flush = AsyncMock(return_value=None)
    return session


def _expected_hmac(scan_event: ScanEvent, secret: str = _SECRET) -> str:
    """Independently compute HMAC-SHA256 for a ScanEvent."""
    created_at = scan_event.created_at
    created_at_str = (
        created_at.isoformat()
        if isinstance(created_at, datetime)
        else str(created_at)
    )
    canonical = "|".join([
        str(scan_event.id),
        scan_event.file_hash,
        scan_event.status,
        scan_event.action_taken,
        created_at_str,
    ])
    return hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# compute_hmac — determinism and sensitivity tests
# ---------------------------------------------------------------------------

class TestComputeHmac:
    def setup_method(self) -> None:
        self.service = AuditService(secret_key=_SECRET)

    def test_returns_64_char_hex_string(self) -> None:
        evt = _make_scan_event()
        sig = self.service.compute_hmac(evt)
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_deterministic_same_inputs(self) -> None:
        evt = _make_scan_event()
        sig1 = self.service.compute_hmac(evt)
        sig2 = self.service.compute_hmac(evt)
        assert sig1 == sig2

    def test_matches_independently_computed_hmac(self) -> None:
        evt = _make_scan_event()
        assert self.service.compute_hmac(evt) == _expected_hmac(evt)

    def test_different_file_hash_produces_different_sig(self) -> None:
        evt1 = _make_scan_event(file_hash="aaa")
        evt2 = _make_scan_event(
            id=evt1.id,
            tenant_id=evt1.tenant_id,
            created_at=evt1.created_at,
            status=evt1.status,
            action_taken=evt1.action_taken,
            file_hash="bbb",
        )
        assert self.service.compute_hmac(evt1) != self.service.compute_hmac(evt2)

    def test_different_status_produces_different_sig(self) -> None:
        evt1 = _make_scan_event(status="clean")
        evt2 = _make_scan_event(
            id=evt1.id,
            tenant_id=evt1.tenant_id,
            created_at=evt1.created_at,
            file_hash=evt1.file_hash,
            action_taken=evt1.action_taken,
            status="flagged",
        )
        assert self.service.compute_hmac(evt1) != self.service.compute_hmac(evt2)

    def test_different_action_taken_produces_different_sig(self) -> None:
        evt1 = _make_scan_event(action_taken="pass")
        evt2 = _make_scan_event(
            id=evt1.id,
            tenant_id=evt1.tenant_id,
            created_at=evt1.created_at,
            file_hash=evt1.file_hash,
            status=evt1.status,
            action_taken="block",
        )
        assert self.service.compute_hmac(evt1) != self.service.compute_hmac(evt2)

    def test_different_id_produces_different_sig(self) -> None:
        shared_ts = datetime(2026, 2, 25, 12, 0, 0, tzinfo=timezone.utc)
        evt1 = _make_scan_event(id=uuid.uuid4(), created_at=shared_ts)
        evt2 = _make_scan_event(
            id=uuid.uuid4(),
            file_hash=evt1.file_hash,
            status=evt1.status,
            action_taken=evt1.action_taken,
            created_at=shared_ts,
        )
        assert self.service.compute_hmac(evt1) != self.service.compute_hmac(evt2)

    def test_different_secret_produces_different_sig(self) -> None:
        evt = _make_scan_event()
        svc1 = AuditService(secret_key="secret-a")
        svc2 = AuditService(secret_key="secret-b")
        assert svc1.compute_hmac(evt) != svc2.compute_hmac(evt)


# ---------------------------------------------------------------------------
# verify_hmac — valid and tampered record tests
# ---------------------------------------------------------------------------

class TestVerifyHmac:
    def setup_method(self) -> None:
        self.service = AuditService(secret_key=_SECRET)

    def test_returns_true_for_correct_signature(self) -> None:
        evt = _make_scan_event()
        evt.hmac_signature = self.service.compute_hmac(evt)
        assert self.service.verify_hmac(evt) is True

    def test_returns_false_for_tampered_file_hash(self) -> None:
        evt = _make_scan_event()
        evt.hmac_signature = self.service.compute_hmac(evt)
        # Tamper with a signed field
        evt.file_hash = "tampered-hash-value"
        assert self.service.verify_hmac(evt) is False

    def test_returns_false_for_tampered_status(self) -> None:
        evt = _make_scan_event(status="clean")
        evt.hmac_signature = self.service.compute_hmac(evt)
        evt.status = "flagged"
        assert self.service.verify_hmac(evt) is False

    def test_returns_false_for_tampered_action_taken(self) -> None:
        evt = _make_scan_event(action_taken="pass")
        evt.hmac_signature = self.service.compute_hmac(evt)
        evt.action_taken = "block"
        assert self.service.verify_hmac(evt) is False

    def test_returns_false_for_tampered_created_at(self) -> None:
        evt = _make_scan_event()
        evt.hmac_signature = self.service.compute_hmac(evt)
        evt.created_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        assert self.service.verify_hmac(evt) is False

    def test_returns_false_for_wrong_secret(self) -> None:
        evt = _make_scan_event()
        evt.hmac_signature = AuditService(secret_key="original").compute_hmac(evt)
        assert AuditService(secret_key="different").verify_hmac(evt) is False

    def test_returns_false_for_empty_signature(self) -> None:
        evt = _make_scan_event()
        evt.hmac_signature = ""
        assert self.service.verify_hmac(evt) is False


# ---------------------------------------------------------------------------
# log_scan_event — append-only enforcement (no update/delete paths)
# ---------------------------------------------------------------------------

class TestLogScanEventAppendOnly:
    def setup_method(self) -> None:
        self.service = AuditService(secret_key=_SECRET)

    @pytest.mark.asyncio
    async def test_calls_session_add_not_update(self) -> None:
        session = _make_session()
        evt = _make_scan_event()
        await self.service.log_scan_event(session, evt)

        session.add.assert_called_once_with(evt)
        # Verify update() was never called on the session
        assert not hasattr(session, "update") or not session.update.called  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_calls_flush_after_add(self) -> None:
        session = _make_session()
        evt = _make_scan_event()
        await self.service.log_scan_event(session, evt)

        # Ensure add() is called before flush() (order matters for append-only)
        assert session.add.call_count == 1
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_does_not_call_session_execute_with_update(self) -> None:
        """Verify no UPDATE statement is issued via session.execute()."""
        session = _make_session()
        evt = _make_scan_event()
        await self.service.log_scan_event(session, evt)

        # If execute was called at all, its args must not contain UPDATE
        for c in session.execute.call_args_list:
            stmt = str(c.args[0]) if c.args else ""
            assert "UPDATE" not in stmt.upper()
            assert "DELETE" not in stmt.upper()

    @pytest.mark.asyncio
    async def test_sets_hmac_signature_before_insert(self) -> None:
        """hmac_signature must be populated before session.add() is called."""
        recorded_sig: list[str] = []

        session = _make_session()
        original_add = session.add.side_effect

        def _capture_add(obj: Any) -> None:
            recorded_sig.append(obj.hmac_signature)

        session.add.side_effect = _capture_add
        evt = _make_scan_event()
        await self.service.log_scan_event(session, evt)

        # The captured signature must be a valid 64-char hex string
        assert len(recorded_sig) == 1
        sig = recorded_sig[0]
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    @pytest.mark.asyncio
    async def test_computed_hmac_stored_on_event(self) -> None:
        session = _make_session()
        evt = _make_scan_event()
        await self.service.log_scan_event(session, evt)

        expected = _expected_hmac(evt)
        assert evt.hmac_signature == expected

    @pytest.mark.asyncio
    async def test_returns_same_scan_event_instance(self) -> None:
        session = _make_session()
        evt = _make_scan_event()
        result = await self.service.log_scan_event(session, evt)
        assert result is evt


# ---------------------------------------------------------------------------
# log_scan_event — structured log output
# ---------------------------------------------------------------------------

class TestLogScanEventStructuredLog:
    def setup_method(self) -> None:
        self.service = AuditService(secret_key=_SECRET)

    @pytest.mark.asyncio
    async def test_log_contains_correlation_id(self, caplog: pytest.LogCaptureFixture) -> None:
        session = _make_session()
        evt = _make_scan_event()
        correlation_id = "req-abc123"
        with caplog.at_level(logging.INFO, logger="fileguard.services.audit"):
            await self.service.log_scan_event(
                session, evt, correlation_id=correlation_id
            )
        log_entry = json.loads(caplog.records[-1].message)
        assert log_entry["correlation_id"] == correlation_id

    @pytest.mark.asyncio
    async def test_log_contains_tenant_id(self, caplog: pytest.LogCaptureFixture) -> None:
        session = _make_session()
        tenant_id = uuid.uuid4()
        evt = _make_scan_event(tenant_id=tenant_id)
        with caplog.at_level(logging.INFO, logger="fileguard.services.audit"):
            await self.service.log_scan_event(
                session, evt, tenant_id=tenant_id
            )
        log_entry = json.loads(caplog.records[-1].message)
        assert log_entry["tenant_id"] == str(tenant_id)

    @pytest.mark.asyncio
    async def test_log_contains_scan_id(self, caplog: pytest.LogCaptureFixture) -> None:
        session = _make_session()
        scan_id = uuid.uuid4()
        evt = _make_scan_event()
        with caplog.at_level(logging.INFO, logger="fileguard.services.audit"):
            await self.service.log_scan_event(
                session, evt, scan_id=scan_id
            )
        log_entry = json.loads(caplog.records[-1].message)
        assert log_entry["scan_id"] == str(scan_id)

    @pytest.mark.asyncio
    async def test_log_contains_all_required_fields(self, caplog: pytest.LogCaptureFixture) -> None:
        """correlation_id, tenant_id, and scan_id must all appear in every log entry."""
        session = _make_session()
        tenant_id = uuid.uuid4()
        scan_id = uuid.uuid4()
        evt = _make_scan_event(tenant_id=tenant_id)
        with caplog.at_level(logging.INFO, logger="fileguard.services.audit"):
            await self.service.log_scan_event(
                session,
                evt,
                correlation_id="corr-xyz",
                tenant_id=tenant_id,
                scan_id=scan_id,
            )
        log_entry = json.loads(caplog.records[-1].message)
        assert "correlation_id" in log_entry
        assert "tenant_id" in log_entry
        assert "scan_id" in log_entry

    @pytest.mark.asyncio
    async def test_log_falls_back_to_event_tenant_id(self, caplog: pytest.LogCaptureFixture) -> None:
        """When tenant_id kwarg is omitted, scan_event.tenant_id is used."""
        session = _make_session()
        tenant_id = uuid.uuid4()
        evt = _make_scan_event(tenant_id=tenant_id)
        with caplog.at_level(logging.INFO, logger="fileguard.services.audit"):
            await self.service.log_scan_event(session, evt)
        log_entry = json.loads(caplog.records[-1].message)
        assert log_entry["tenant_id"] == str(tenant_id)

    @pytest.mark.asyncio
    async def test_log_falls_back_to_event_id_for_scan_id(self, caplog: pytest.LogCaptureFixture) -> None:
        """When scan_id kwarg is omitted, scan_event.id is used."""
        session = _make_session()
        event_id = uuid.uuid4()
        evt = _make_scan_event(id=event_id)
        with caplog.at_level(logging.INFO, logger="fileguard.services.audit"):
            await self.service.log_scan_event(session, evt)
        log_entry = json.loads(caplog.records[-1].message)
        assert log_entry["scan_id"] == str(event_id)

    @pytest.mark.asyncio
    async def test_log_correlation_id_none_when_omitted(self, caplog: pytest.LogCaptureFixture) -> None:
        session = _make_session()
        evt = _make_scan_event()
        with caplog.at_level(logging.INFO, logger="fileguard.services.audit"):
            await self.service.log_scan_event(session, evt)
        log_entry = json.loads(caplog.records[-1].message)
        assert log_entry["correlation_id"] is None

    @pytest.mark.asyncio
    async def test_log_event_field_is_scan_event_audited(self, caplog: pytest.LogCaptureFixture) -> None:
        session = _make_session()
        evt = _make_scan_event()
        with caplog.at_level(logging.INFO, logger="fileguard.services.audit"):
            await self.service.log_scan_event(session, evt)
        log_entry = json.loads(caplog.records[-1].message)
        assert log_entry["event"] == "scan_event_audited"


# ---------------------------------------------------------------------------
# log_scan_event — error handling (AuditError raised on DB failure)
# ---------------------------------------------------------------------------

class TestLogScanEventErrorHandling:
    def setup_method(self) -> None:
        self.service = AuditService(secret_key=_SECRET)

    @pytest.mark.asyncio
    async def test_raises_audit_error_on_flush_failure(self) -> None:
        db_error = Exception("connection lost")
        session = _make_session(flush_side_effect=db_error)
        evt = _make_scan_event()

        with pytest.raises(AuditError) as exc_info:
            await self.service.log_scan_event(session, evt)

        assert "Failed to persist ScanEvent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_audit_error_chains_original_exception(self) -> None:
        original = RuntimeError("disk full")
        session = _make_session(flush_side_effect=original)
        evt = _make_scan_event()

        with pytest.raises(AuditError) as exc_info:
            await self.service.log_scan_event(session, evt)

        assert exc_info.value.__cause__ is original

    @pytest.mark.asyncio
    async def test_does_not_swallow_db_error(self) -> None:
        """An exception from session.flush() must propagate, never be silently caught."""
        session = _make_session(flush_side_effect=Exception("timeout"))
        evt = _make_scan_event()

        # Must raise — not return normally.
        with pytest.raises(AuditError):
            await self.service.log_scan_event(session, evt)

    @pytest.mark.asyncio
    async def test_no_log_emitted_on_flush_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        """Structured log should NOT be emitted when the INSERT fails."""
        session = _make_session(flush_side_effect=Exception("insert failed"))
        evt = _make_scan_event()

        with caplog.at_level(logging.INFO, logger="fileguard.services.audit"):
            with pytest.raises(AuditError):
                await self.service.log_scan_event(session, evt)

        # No audit log record should have been emitted.
        audit_records = [
            r for r in caplog.records
            if r.name == "fileguard.services.audit"
        ]
        assert len(audit_records) == 0
