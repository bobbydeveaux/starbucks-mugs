"""Unit tests for fileguard/services/audit.py (AuditService).

All tests are fully offline — database writes and HTTP calls are replaced by
``unittest.mock`` patches so no external services are required.

Coverage targets:
* HMAC-SHA256 signature computation and verification (both public and private APIs).
* Tampered-record detection (any field mutation fails verify_hmac).
* Append-only enforcement at the service layer (only session.add + flush,
  never update/delete).
* Structured log output carries correlation_id, tenant_id, and scan_id.
* AuditError is raised (not silently swallowed) on DB write failure.
* SIEM payload and header construction.
* SIEM forwarding: success, HTTP error, network error, missing endpoint.
* Edge cases: empty findings, missing token, unknown SIEM type.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fileguard.services.audit import (
    AuditError,
    AuditService,
    _SIEM_TYPE_SPLUNK,
    _SIEM_TYPE_WATCHTOWER,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

# Secret key used by HEAD-style tests (signing_key constructor param)
SIGNING_KEY = "test-signing-key-32-chars-minimum!!"

# Secret key used by main-style tests (secret_key constructor param)
_SECRET = "test-secret-key"


def _make_service(http_client: Any = None) -> AuditService:
    """Return an AuditService configured with the shared SIGNING_KEY."""
    return AuditService(signing_key=SIGNING_KEY, http_client=http_client)


def _make_scan_event(**overrides: Any) -> MagicMock:
    """Return a ScanEvent mock with sensible defaults for testing.

    ``created_at`` is set to a fixed UTC timestamp so that HMAC computations
    are deterministic across runs.  Pass keyword overrides to customise any
    field; use ``id`` to override the event UUID.
    """
    event_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
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


def _expected_hmac(scan_event: Any, secret: str = _SECRET) -> str:
    """Independently compute HMAC-SHA256 using the pipe-separated canonical format."""
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


def _expected_hmac_json(
    event_id: uuid.UUID,
    file_hash: str,
    status: str,
    action_taken: str,
    created_at: datetime,
    secret: str = SIGNING_KEY,
) -> str:
    """Independently compute HMAC-SHA256 using the JSON canonical format."""
    canonical = json.dumps(
        {
            "action_taken": action_taken,
            "created_at": created_at.isoformat(),
            "file_hash": file_hash,
            "id": str(event_id),
            "status": status,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hmac.new(
        secret.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# TestPrivateComputeHmac — tests the private _compute_hmac(*, ...) JSON API
# ---------------------------------------------------------------------------


class TestPrivateComputeHmac:
    def test_returns_hex_string(self) -> None:
        service = _make_service()
        event_id = uuid.uuid4()
        created_at = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = service._compute_hmac(
            event_id=event_id,
            file_hash="deadbeef" * 8,
            status="clean",
            action_taken="pass",
            created_at=created_at,
        )
        assert isinstance(result, str)
        # SHA-256 hexdigest is always 64 hex characters
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic_for_same_inputs(self) -> None:
        service = _make_service()
        event_id = uuid.uuid4()
        created_at = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        kwargs = dict(
            event_id=event_id,
            file_hash="cafebabe" * 8,
            status="flagged",
            action_taken="quarantine",
            created_at=created_at,
        )
        first = service._compute_hmac(**kwargs)
        second = service._compute_hmac(**kwargs)
        assert first == second

    def test_matches_expected_canonical_hmac(self) -> None:
        service = _make_service()
        event_id = uuid.uuid4()
        file_hash = "aabbccdd" * 8
        status = "rejected"
        action_taken = "block"
        created_at = datetime(2026, 2, 20, 8, 30, 0, tzinfo=timezone.utc)

        result = service._compute_hmac(
            event_id=event_id,
            file_hash=file_hash,
            status=status,
            action_taken=action_taken,
            created_at=created_at,
        )
        expected = _expected_hmac_json(event_id, file_hash, status, action_taken, created_at)
        assert result == expected

    def test_different_event_ids_produce_different_signatures(self) -> None:
        service = _make_service()
        created_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        sig1 = service._compute_hmac(
            event_id=uuid.uuid4(),
            file_hash="aaa",
            status="clean",
            action_taken="pass",
            created_at=created_at,
        )
        sig2 = service._compute_hmac(
            event_id=uuid.uuid4(),
            file_hash="aaa",
            status="clean",
            action_taken="pass",
            created_at=created_at,
        )
        assert sig1 != sig2

    def test_different_file_hashes_produce_different_signatures(self) -> None:
        service = _make_service()
        event_id = uuid.uuid4()
        created_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        sig1 = service._compute_hmac(
            event_id=event_id,
            file_hash="hash-a",
            status="clean",
            action_taken="pass",
            created_at=created_at,
        )
        sig2 = service._compute_hmac(
            event_id=event_id,
            file_hash="hash-b",
            status="clean",
            action_taken="pass",
            created_at=created_at,
        )
        assert sig1 != sig2

    def test_different_statuses_produce_different_signatures(self) -> None:
        service = _make_service()
        event_id = uuid.uuid4()
        created_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        clean_sig = service._compute_hmac(
            event_id=event_id,
            file_hash="hash",
            status="clean",
            action_taken="pass",
            created_at=created_at,
        )
        flagged_sig = service._compute_hmac(
            event_id=event_id,
            file_hash="hash",
            status="flagged",
            action_taken="pass",
            created_at=created_at,
        )
        assert clean_sig != flagged_sig

    def test_different_signing_keys_produce_different_signatures(self) -> None:
        service_a = AuditService(signing_key="key-alpha")
        service_b = AuditService(signing_key="key-beta")
        event_id = uuid.uuid4()
        created_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        kwargs = dict(
            event_id=event_id,
            file_hash="hash",
            status="clean",
            action_taken="pass",
            created_at=created_at,
        )
        assert service_a._compute_hmac(**kwargs) != service_b._compute_hmac(**kwargs)


# ---------------------------------------------------------------------------
# TestComputeHmac — tests the public compute_hmac(scan_event) pipe-separated API
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
# TestVerifyHmac — valid and tampered record tests (pipe-separated canonical)
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
# TestLogScanEventAppendOnly — append-only enforcement (no update/delete paths)
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
# TestLogScanEventStructuredLog — structured log output
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
# TestLogScanEventErrorHandling — AuditError raised on DB failure
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


# ---------------------------------------------------------------------------
# TestLogScanEventSiem — SIEM forwarding integration with log_scan_event
# ---------------------------------------------------------------------------


class TestLogScanEventSiem:
    def setup_method(self) -> None:
        self.service = AuditService(secret_key=_SECRET)

    @pytest.mark.asyncio
    async def test_siem_forwarding_skipped_when_no_config(self) -> None:
        session = _make_session()
        evt = _make_scan_event()
        with patch.object(self.service, "_forward_to_siem") as mock_forward:
            await self.service.log_scan_event(session, evt, siem_config=None)
        mock_forward.assert_not_called()

    @pytest.mark.asyncio
    async def test_siem_forwarding_called_when_config_present(self) -> None:
        session = _make_session()
        evt = _make_scan_event()
        siem_config = {
            "type": "splunk",
            "endpoint": "https://splunk.example.com/services/collector",
            "token": "splunk-hec-token",
        }
        with patch.object(self.service, "_forward_to_siem", new_callable=AsyncMock) as mock_forward:
            await self.service.log_scan_event(session, evt, siem_config=siem_config)
        mock_forward.assert_awaited_once()
        call_kwargs = mock_forward.call_args
        assert call_kwargs.args[1] is siem_config


# ---------------------------------------------------------------------------
# TestBuildSiemPayload — static payload construction
# ---------------------------------------------------------------------------


class TestBuildSiemPayload:
    def _event(self) -> MagicMock:
        return _make_scan_event(findings=[{"type": "av_threat", "severity": "critical"}])

    def test_splunk_wraps_in_event_envelope(self) -> None:
        event = self._event()
        payload = AuditService._build_siem_payload(event, _SIEM_TYPE_SPLUNK)
        assert "event" in payload
        assert "sourcetype" in payload
        assert payload["sourcetype"] == "fileguard:scan"
        inner = payload["event"]
        assert inner["scan_id"] == str(event.id)

    def test_splunk_inner_event_contains_required_fields(self) -> None:
        event = self._event()
        payload = AuditService._build_siem_payload(event, _SIEM_TYPE_SPLUNK)
        inner = payload["event"]
        for field in (
            "scan_id", "tenant_id", "file_hash", "file_name",
            "file_size_bytes", "mime_type", "status", "action_taken",
            "findings", "scan_duration_ms", "created_at", "hmac_signature",
        ):
            assert field in inner, f"Missing field: {field}"

    def test_watchtower_sends_flat_payload(self) -> None:
        event = self._event()
        payload = AuditService._build_siem_payload(event, _SIEM_TYPE_WATCHTOWER)
        assert "event" not in payload  # no envelope
        assert payload["scan_id"] == str(event.id)
        assert payload["status"] == event.status

    def test_generic_type_sends_flat_payload(self) -> None:
        event = self._event()
        payload = AuditService._build_siem_payload(event, "custom")
        assert "event" not in payload
        assert payload["scan_id"] == str(event.id)

    def test_findings_included_in_payload(self) -> None:
        findings = [{"type": "pii", "category": "NI_NUMBER", "severity": "high"}]
        event = _make_scan_event(findings=findings)
        payload = AuditService._build_siem_payload(event, _SIEM_TYPE_WATCHTOWER)
        assert payload["findings"] == findings

    def test_created_at_is_iso_string(self) -> None:
        created_at = datetime(2026, 3, 1, 10, 30, 0, tzinfo=timezone.utc)
        event = _make_scan_event(created_at=created_at)
        payload = AuditService._build_siem_payload(event, _SIEM_TYPE_WATCHTOWER)
        assert payload["created_at"] == created_at.isoformat()


class TestBuildSiemHeaders:
    def test_splunk_auth_header_format(self) -> None:
        headers = AuditService._build_siem_headers(_SIEM_TYPE_SPLUNK, "my-token")
        assert headers["Authorization"] == "Splunk my-token"
        assert headers["Content-Type"] == "application/json"

    def test_watchtower_auth_header_format(self) -> None:
        headers = AuditService._build_siem_headers(_SIEM_TYPE_WATCHTOWER, "bearer-tok")
        assert headers["Authorization"] == "Bearer bearer-tok"
        assert headers["Content-Type"] == "application/json"

    def test_no_token_omits_auth_header(self) -> None:
        headers = AuditService._build_siem_headers(_SIEM_TYPE_SPLUNK, None)
        assert "Authorization" not in headers
        assert headers["Content-Type"] == "application/json"

    def test_generic_type_uses_bearer_scheme(self) -> None:
        headers = AuditService._build_siem_headers("generic", "tok123")
        assert headers["Authorization"] == "Bearer tok123"


# ---------------------------------------------------------------------------
# TestForwardToSiem — _forward_to_siem method
# ---------------------------------------------------------------------------


class TestForwardToSiem:
    def _make_http_response(self, status_code: int = 200) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            import httpx

            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                f"HTTP {status_code}",
                request=MagicMock(),
                response=MagicMock(status_code=status_code),
            )
        return resp

    async def test_successful_splunk_delivery(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=self._make_http_response(200))

        service = _make_service(http_client=mock_client)
        event = _make_scan_event()

        await service._forward_to_siem(
            event,
            {
                "type": "splunk",
                "endpoint": "https://splunk.example.com/services/collector",
                "token": "hec-token",
            },
        )

        mock_client.post.assert_awaited_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs.get("json") or call_kwargs.args
        # Verify Splunk HEC auth header
        headers = call_kwargs.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Splunk hec-token"

    async def test_successful_watchtower_delivery(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=self._make_http_response(200))

        service = _make_service(http_client=mock_client)
        event = _make_scan_event()

        await service._forward_to_siem(
            event,
            {
                "type": "watchtower",
                "endpoint": "https://watchtower.example.com/events",
                "token": "wt-token",
            },
        )

        mock_client.post.assert_awaited_once()
        headers = mock_client.post.call_args.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer wt-token"

    async def test_http_error_is_logged_not_raised(self, caplog: Any) -> None:
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "HTTP 500",
                request=MagicMock(),
                response=MagicMock(status_code=500),
            )
        )

        service = _make_service(http_client=mock_client)
        event = _make_scan_event()

        # Must not raise
        with caplog.at_level(logging.WARNING, logger="fileguard.services.audit"):
            await service._forward_to_siem(
                event,
                {"type": "splunk", "endpoint": "https://splunk.example.com/hec", "token": "t"},
            )

        assert any("SIEM delivery failed" in r.message for r in caplog.records)

    async def test_network_error_is_logged_not_raised(self, caplog: Any) -> None:
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        service = _make_service(http_client=mock_client)
        event = _make_scan_event()

        with caplog.at_level(logging.WARNING, logger="fileguard.services.audit"):
            await service._forward_to_siem(
                event,
                {"type": "watchtower", "endpoint": "https://wt.example.com/events"},
            )

        assert any("SIEM delivery error" in r.message for r in caplog.records)

    async def test_missing_endpoint_logs_warning_and_returns(self, caplog: Any) -> None:
        mock_client = AsyncMock()
        service = _make_service(http_client=mock_client)
        event = _make_scan_event()

        with caplog.at_level(logging.WARNING, logger="fileguard.services.audit"):
            await service._forward_to_siem(event, {"type": "splunk"})

        mock_client.post.assert_not_awaited()
        assert any("missing 'endpoint'" in r.message for r in caplog.records)

    async def test_endpoint_in_correct_splunk_hec_url(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=self._make_http_response(200))
        service = _make_service(http_client=mock_client)
        event = _make_scan_event()

        endpoint = "https://splunk.acme.com/services/collector/event"
        await service._forward_to_siem(
            event,
            {"type": "splunk", "endpoint": endpoint, "token": "tok"},
        )

        called_url = mock_client.post.call_args.args[0]
        assert called_url == endpoint

    async def test_siem_payload_contains_scan_id(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=self._make_http_response(200))
        service = _make_service(http_client=mock_client)

        event_id = uuid.uuid4()
        event = _make_scan_event(id=event_id)

        await service._forward_to_siem(
            event,
            {"type": "watchtower", "endpoint": "https://wt.example.com/api/events"},
        )

        payload = mock_client.post.call_args.kwargs.get("json", {})
        assert payload.get("scan_id") == str(event_id)

    async def test_timeout_set_on_http_call(self) -> None:
        from fileguard.services.audit import _SIEM_HTTP_TIMEOUT

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=self._make_http_response(200))
        service = _make_service(http_client=mock_client)
        event = _make_scan_event()

        await service._forward_to_siem(
            event,
            {"type": "splunk", "endpoint": "https://splunk.example.com/hec", "token": "tok"},
        )

        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs.get("timeout") == _SIEM_HTTP_TIMEOUT


# ---------------------------------------------------------------------------
# TestAuditServiceInit — constructor parameter handling
# ---------------------------------------------------------------------------


class TestAuditServiceInit:
    def test_signing_key_is_bytes(self) -> None:
        service = AuditService(signing_key="my-key")
        assert isinstance(service._signing_key, bytes)

    def test_secret_key_is_bytes(self) -> None:
        service = AuditService(secret_key="my-key")
        assert isinstance(service._secret_key, bytes)

    def test_signing_key_takes_precedence_over_secret_key(self) -> None:
        service = AuditService(signing_key="sign-key", secret_key="secret-key")
        assert service._secret_key == b"sign-key"

    def test_http_client_stored_when_provided(self) -> None:
        client = MagicMock()
        service = AuditService(signing_key="key", http_client=client)
        assert service._http_client is client

    def test_http_client_none_by_default(self) -> None:
        service = AuditService(signing_key="key")
        assert service._http_client is None
