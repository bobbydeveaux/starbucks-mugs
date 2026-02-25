"""Unit tests for fileguard/services/audit.py (AuditService).

All tests are fully offline — database writes and HTTP calls are replaced by
``unittest.mock`` patches so no external services are required.

Test categories
---------------
- HMAC computation and canonical message format
- HMAC verification (valid and tampered events)
- scan event creation (fields, signature, flush, SIEM branch)
- SIEM payload and header construction
- SIEM forwarding: success, HTTP error, network error, missing endpoint
- Edge cases: empty findings, missing token, unknown SIEM type
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fileguard.services.audit import AuditService, _SIEM_TYPE_SPLUNK, _SIEM_TYPE_WATCHTOWER


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

SIGNING_KEY = "test-signing-key-32-chars-minimum!!"


def _make_service(http_client: Any = None) -> AuditService:
    return AuditService(signing_key=SIGNING_KEY, http_client=http_client)


def _make_mock_session() -> AsyncMock:
    """Return a mock async SQLAlchemy session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def _make_scan_event(
    *,
    event_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    file_hash: str = "abc123def456" * 4,  # 48-char hex
    status: str = "clean",
    action_taken: str = "pass",
    created_at: datetime | None = None,
    findings: list | None = None,
    hmac_signature: str = "",
) -> MagicMock:
    """Return a mock ScanEvent ORM instance."""
    event = MagicMock()
    event.id = event_id or uuid.uuid4()
    event.tenant_id = tenant_id or uuid.uuid4()
    event.file_hash = file_hash
    event.file_name = "test.pdf"
    event.file_size_bytes = 1024
    event.mime_type = "application/pdf"
    event.status = status
    event.action_taken = action_taken
    event.findings = findings if findings is not None else []
    event.scan_duration_ms = 500
    event.created_at = created_at or datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    event.hmac_signature = hmac_signature
    return event


def _expected_hmac(
    event_id: uuid.UUID,
    file_hash: str,
    status: str,
    action_taken: str,
    created_at: datetime,
) -> str:
    """Replicate the canonical HMAC computation for assertion purposes."""
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
        SIGNING_KEY.encode(),
        canonical.encode(),
        hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# HMAC computation
# ---------------------------------------------------------------------------


class TestComputeHmac:
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
        expected = _expected_hmac(event_id, file_hash, status, action_taken, created_at)
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
# HMAC verification
# ---------------------------------------------------------------------------


class TestVerifyHmac:
    def test_valid_event_returns_true(self) -> None:
        service = _make_service()
        event_id = uuid.uuid4()
        file_hash = "deadbeef" * 8
        status = "clean"
        action_taken = "pass"
        created_at = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        signature = service._compute_hmac(
            event_id=event_id,
            file_hash=file_hash,
            status=status,
            action_taken=action_taken,
            created_at=created_at,
        )
        event = _make_scan_event(
            event_id=event_id,
            file_hash=file_hash,
            status=status,
            action_taken=action_taken,
            created_at=created_at,
            hmac_signature=signature,
        )
        assert service.verify_hmac(event) is True

    def test_tampered_file_hash_returns_false(self) -> None:
        service = _make_service()
        event_id = uuid.uuid4()
        created_at = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        # Sign with original hash
        signature = service._compute_hmac(
            event_id=event_id,
            file_hash="original-hash",
            status="clean",
            action_taken="pass",
            created_at=created_at,
        )
        # Build event with a *tampered* hash but original signature
        event = _make_scan_event(
            event_id=event_id,
            file_hash="tampered-hash",
            status="clean",
            action_taken="pass",
            created_at=created_at,
            hmac_signature=signature,
        )
        assert service.verify_hmac(event) is False

    def test_tampered_status_returns_false(self) -> None:
        service = _make_service()
        event_id = uuid.uuid4()
        created_at = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        signature = service._compute_hmac(
            event_id=event_id,
            file_hash="hash",
            status="clean",
            action_taken="pass",
            created_at=created_at,
        )
        event = _make_scan_event(
            event_id=event_id,
            file_hash="hash",
            status="flagged",  # tampered
            action_taken="pass",
            created_at=created_at,
            hmac_signature=signature,
        )
        assert service.verify_hmac(event) is False

    def test_tampered_action_taken_returns_false(self) -> None:
        service = _make_service()
        event_id = uuid.uuid4()
        created_at = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        signature = service._compute_hmac(
            event_id=event_id,
            file_hash="hash",
            status="flagged",
            action_taken="quarantine",
            created_at=created_at,
        )
        event = _make_scan_event(
            event_id=event_id,
            file_hash="hash",
            status="flagged",
            action_taken="pass",  # tampered
            created_at=created_at,
            hmac_signature=signature,
        )
        assert service.verify_hmac(event) is False

    def test_wrong_signing_key_returns_false(self) -> None:
        signer = AuditService(signing_key="correct-key")
        verifier = AuditService(signing_key="wrong-key")
        event_id = uuid.uuid4()
        created_at = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        signature = signer._compute_hmac(
            event_id=event_id,
            file_hash="hash",
            status="clean",
            action_taken="pass",
            created_at=created_at,
        )
        event = _make_scan_event(
            event_id=event_id,
            file_hash="hash",
            status="clean",
            action_taken="pass",
            created_at=created_at,
            hmac_signature=signature,
        )
        assert verifier.verify_hmac(event) is False


# ---------------------------------------------------------------------------
# log_scan_event — DB interaction
# ---------------------------------------------------------------------------


class TestLogScanEvent:
    @pytest.fixture
    def service(self) -> AuditService:
        return _make_service()

    @pytest.fixture
    def session(self) -> AsyncMock:
        return _make_mock_session()

    async def test_returns_scan_event_instance(
        self, service: AuditService, session: AsyncMock
    ) -> None:
        from fileguard.models.scan_event import ScanEvent

        result = await service.log_scan_event(
            session=session,
            tenant_id=uuid.uuid4(),
            file_hash="aabbccdd" * 8,
            file_name="sample.docx",
            file_size_bytes=2048,
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            status="clean",
            action_taken="pass",
            findings=[],
            scan_duration_ms=300,
        )
        assert isinstance(result, ScanEvent)

    async def test_session_add_called_once(
        self, service: AuditService, session: AsyncMock
    ) -> None:
        await service.log_scan_event(
            session=session,
            tenant_id=uuid.uuid4(),
            file_hash="aabbccdd" * 8,
            file_name="doc.pdf",
            file_size_bytes=512,
            mime_type="application/pdf",
            status="flagged",
            action_taken="quarantine",
            findings=[],
            scan_duration_ms=800,
        )
        session.add.assert_called_once()

    async def test_session_flush_called(
        self, service: AuditService, session: AsyncMock
    ) -> None:
        await service.log_scan_event(
            session=session,
            tenant_id=uuid.uuid4(),
            file_hash="aabbccdd" * 8,
            file_name="doc.pdf",
            file_size_bytes=512,
            mime_type="application/pdf",
            status="rejected",
            action_taken="block",
            findings=[],
            scan_duration_ms=200,
        )
        session.flush.assert_awaited_once()

    async def test_event_fields_are_set_correctly(
        self, service: AuditService, session: AsyncMock
    ) -> None:
        tenant_id = uuid.uuid4()
        file_hash = "cafebabe" * 8
        findings = [{"type": "pii", "category": "NHS_NUMBER", "severity": "high"}]

        result = await service.log_scan_event(
            session=session,
            tenant_id=tenant_id,
            file_hash=file_hash,
            file_name="report.pdf",
            file_size_bytes=10240,
            mime_type="application/pdf",
            status="flagged",
            action_taken="quarantine",
            findings=findings,
            scan_duration_ms=1500,
        )

        assert result.tenant_id == tenant_id
        assert result.file_hash == file_hash
        assert result.file_name == "report.pdf"
        assert result.file_size_bytes == 10240
        assert result.mime_type == "application/pdf"
        assert result.status == "flagged"
        assert result.action_taken == "quarantine"
        assert result.findings == findings
        assert result.scan_duration_ms == 1500

    async def test_hmac_signature_is_populated(
        self, service: AuditService, session: AsyncMock
    ) -> None:
        result = await service.log_scan_event(
            session=session,
            tenant_id=uuid.uuid4(),
            file_hash="beefdead" * 8,
            file_name="img.png",
            file_size_bytes=256,
            mime_type="image/png",
            status="clean",
            action_taken="pass",
            findings=[],
            scan_duration_ms=100,
        )
        assert result.hmac_signature
        assert len(result.hmac_signature) == 64  # SHA-256 hex

    async def test_hmac_signature_is_valid(
        self, service: AuditService, session: AsyncMock
    ) -> None:
        result = await service.log_scan_event(
            session=session,
            tenant_id=uuid.uuid4(),
            file_hash="deadbeef" * 8,
            file_name="data.csv",
            file_size_bytes=4096,
            mime_type="text/csv",
            status="flagged",
            action_taken="quarantine",
            findings=[],
            scan_duration_ms=600,
        )
        assert service.verify_hmac(result) is True

    async def test_unique_id_generated_for_each_call(
        self, service: AuditService, session: AsyncMock
    ) -> None:
        result1 = await service.log_scan_event(
            session=session,
            tenant_id=uuid.uuid4(),
            file_hash="aaaa" * 16,
            file_name="a.txt",
            file_size_bytes=10,
            mime_type="text/plain",
            status="clean",
            action_taken="pass",
            findings=[],
            scan_duration_ms=50,
        )
        result2 = await service.log_scan_event(
            session=session,
            tenant_id=uuid.uuid4(),
            file_hash="bbbb" * 16,
            file_name="b.txt",
            file_size_bytes=20,
            mime_type="text/plain",
            status="clean",
            action_taken="pass",
            findings=[],
            scan_duration_ms=50,
        )
        assert result1.id != result2.id

    async def test_created_at_is_set_with_timezone(
        self, service: AuditService, session: AsyncMock
    ) -> None:
        result = await service.log_scan_event(
            session=session,
            tenant_id=uuid.uuid4(),
            file_hash="cccc" * 16,
            file_name="c.zip",
            file_size_bytes=8192,
            mime_type="application/zip",
            status="rejected",
            action_taken="block",
            findings=[],
            scan_duration_ms=2000,
        )
        assert result.created_at is not None
        assert result.created_at.tzinfo is not None

    async def test_empty_findings_accepted(
        self, service: AuditService, session: AsyncMock
    ) -> None:
        result = await service.log_scan_event(
            session=session,
            tenant_id=uuid.uuid4(),
            file_hash="dddd" * 16,
            file_name="empty.txt",
            file_size_bytes=0,
            mime_type="text/plain",
            status="clean",
            action_taken="pass",
            findings=[],
            scan_duration_ms=10,
        )
        assert result.findings == []

    async def test_siem_forwarding_skipped_when_no_config(
        self, service: AuditService, session: AsyncMock
    ) -> None:
        with patch.object(service, "_forward_to_siem") as mock_forward:
            await service.log_scan_event(
                session=session,
                tenant_id=uuid.uuid4(),
                file_hash="eeee" * 16,
                file_name="x.pdf",
                file_size_bytes=100,
                mime_type="application/pdf",
                status="clean",
                action_taken="pass",
                findings=[],
                scan_duration_ms=200,
                siem_config=None,
            )
        mock_forward.assert_not_called()

    async def test_siem_forwarding_called_when_config_present(
        self, service: AuditService, session: AsyncMock
    ) -> None:
        siem_config = {
            "type": "splunk",
            "endpoint": "https://splunk.example.com/services/collector",
            "token": "splunk-hec-token",
        }
        with patch.object(service, "_forward_to_siem", new_callable=AsyncMock) as mock_forward:
            await service.log_scan_event(
                session=session,
                tenant_id=uuid.uuid4(),
                file_hash="ffff" * 16,
                file_name="y.pdf",
                file_size_bytes=200,
                mime_type="application/pdf",
                status="flagged",
                action_taken="quarantine",
                findings=[],
                scan_duration_ms=400,
                siem_config=siem_config,
            )
        mock_forward.assert_awaited_once()
        # First positional arg is the event, second is siem_config
        call_kwargs = mock_forward.call_args
        assert call_kwargs.args[1] is siem_config


# ---------------------------------------------------------------------------
# SIEM payload and header construction (static methods)
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
# SIEM forwarding — _forward_to_siem
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
        import logging

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
        import logging

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
        import logging

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
        event = _make_scan_event(event_id=event_id)

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
# AuditService constructor
# ---------------------------------------------------------------------------


class TestAuditServiceInit:
    def test_signing_key_is_bytes(self) -> None:
        service = AuditService(signing_key="my-key")
        assert isinstance(service._signing_key, bytes)

    def test_http_client_stored_when_provided(self) -> None:
        client = MagicMock()
        service = AuditService(signing_key="key", http_client=client)
        assert service._http_client is client

    def test_http_client_none_by_default(self) -> None:
        service = AuditService(signing_key="key")
        assert service._http_client is None
