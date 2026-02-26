"""Unit tests for fileguard/core/adapters/aws_macie_adapter.py.

All tests are fully offline — boto3 is mocked at module level via
``patch("fileguard.core.adapters.aws_macie_adapter.boto3", ...)`` and
``patch("fileguard.core.adapters.aws_macie_adapter.ClientError", ...)``
so no real AWS credentials or API calls are required.

Coverage:
* backend_name() returns "aws_macie"
* Constructor stores configuration correctly (region, credentials, timeout)
* inspect() returns empty list for empty text (no API call)
* inspect() maps Comprehend entities to PIIFinding objects correctly
* inspect() maps known entity types to correct categories and severities
* inspect() maps unknown entity types using lowercase name + "medium" severity
* inspect() computes byte offsets correctly for ASCII text
* inspect() re-raises CloudPIIBackendError from _inspect_sync
* inspect() returns empty list when Comprehend returns no entities
* is_available() returns True when ping succeeds
* is_available() returns False on any exception (never raises)
* scan() appends findings to ScanContext.findings
* scan() is a no-op when extracted_text is None
* scan() is a no-op when extracted_text is empty string
* scan() appends error to context.errors on CloudPIIBackendError
* scan() preserves pre-existing findings
* _chunk_text() returns single chunk for text under limit
* _chunk_text() splits large text into multiple chunks
* _chunk_text() preserves correct chunk offsets
* _inspect_sync() raises CloudPIIBackendError on ClientError
* _inspect_sync() raises CloudPIIBackendError on BotoCoreError
* _inspect_sync() raises CloudPIIBackendError when boto3 not installed
* _ping_sync() does not raise on AccessDeniedException
* _get_comprehend_client() passes explicit credentials to boto3
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import fileguard.core.adapters.aws_macie_adapter as _macie_module
from fileguard.core.adapters.aws_macie_adapter import (
    AWSMacieAdapter,
    _COMPREHEND_ENTITY_MAP,
    _COMPREHEND_MAX_BYTES,
)
from fileguard.core.adapters.cloud_pii_adapter import CloudPIIBackendError
from fileguard.core.pii_detector import PIIFinding
from fileguard.core.scan_context import ScanContext

# ---------------------------------------------------------------------------
# Fake exception classes (used to simulate ClientError / BotoCoreError)
# ---------------------------------------------------------------------------


class FakeClientError(Exception):
    """Simulated botocore ClientError with the expected response structure."""

    def __init__(self, code: str = "ServiceUnavailableException", message: str = "Service error"):
        self.response = {"Error": {"Code": code, "Message": message}}
        super().__init__(message)


class FakeBotoCoreError(Exception):
    """Simulated botocore BotoCoreError."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(**kwargs: Any) -> AWSMacieAdapter:
    return AWSMacieAdapter(**kwargs)


def _make_comprehend_entity(
    entity_type: str = "EMAIL",
    begin_offset: int = 0,
    end_offset: int = 16,
    score: float = 0.99,
) -> dict:
    """Build a mock Comprehend PII entity dict."""
    return {
        "Type": entity_type,
        "BeginOffset": begin_offset,
        "EndOffset": end_offset,
        "Score": score,
    }


def _make_comprehend_response(entities: list[dict]) -> dict:
    """Build a mock Comprehend detect_pii_entities response."""
    return {"Entities": entities}


def _make_ctx(text: str | None) -> ScanContext:
    ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
    ctx.extracted_text = text
    return ctx


def _run_inspect_sync(
    adapter: AWSMacieAdapter,
    text: str,
    entities: list[dict],
) -> list[PIIFinding]:
    """Run _inspect_sync with a mocked boto3 client."""
    mock_client = MagicMock()
    mock_client.detect_pii_entities.return_value = _make_comprehend_response(entities)
    with patch.object(adapter, "_get_comprehend_client", return_value=mock_client):
        return adapter._inspect_sync(text)


# ---------------------------------------------------------------------------
# backend_name
# ---------------------------------------------------------------------------


class TestBackendName:
    def test_returns_aws_macie(self) -> None:
        assert _make_adapter().backend_name() == "aws_macie"


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_default_region_is_eu_west_2(self) -> None:
        adapter = _make_adapter()
        assert adapter._region_name == "eu-west-2"

    def test_custom_region_stored(self) -> None:
        adapter = _make_adapter(region_name="us-east-1")
        assert adapter._region_name == "us-east-1"

    def test_explicit_access_key_stored(self) -> None:
        adapter = _make_adapter(aws_access_key_id="AKIAEXAMPLE")
        assert adapter._aws_access_key_id == "AKIAEXAMPLE"

    def test_explicit_secret_key_stored(self) -> None:
        adapter = _make_adapter(aws_secret_access_key="secretkey")
        assert adapter._aws_secret_access_key == "secretkey"

    def test_session_token_stored(self) -> None:
        adapter = _make_adapter(aws_session_token="session123")
        assert adapter._aws_session_token == "session123"

    def test_default_timeout(self) -> None:
        adapter = _make_adapter()
        assert adapter._timeout == 30.0

    def test_custom_timeout_stored(self) -> None:
        adapter = _make_adapter(timeout=15.0)
        assert adapter._timeout == 15.0

    def test_no_credentials_by_default(self) -> None:
        adapter = _make_adapter()
        assert adapter._aws_access_key_id is None
        assert adapter._aws_secret_access_key is None
        assert adapter._aws_session_token is None


# ---------------------------------------------------------------------------
# _chunk_text()
# ---------------------------------------------------------------------------


class TestChunkText:
    def test_short_text_returns_single_chunk(self) -> None:
        text = "Hello, world!"
        chunks = AWSMacieAdapter._chunk_text(text, max_bytes=1000)
        assert len(chunks) == 1
        assert chunks[0] == (text, 0)

    def test_single_chunk_offset_is_zero(self) -> None:
        text = "Some short text"
        chunks = AWSMacieAdapter._chunk_text(text, max_bytes=1000)
        assert chunks[0][1] == 0

    def test_large_text_is_chunked(self) -> None:
        word = "word "
        text = word * 100  # 500 chars
        chunks = AWSMacieAdapter._chunk_text(text, max_bytes=50)
        assert len(chunks) > 1

    def test_each_chunk_fits_within_limit(self) -> None:
        # 20-char words + space = 21 bytes each
        word = "w" * 20 + " "
        text = word * 50
        max_bytes = 100
        chunks = AWSMacieAdapter._chunk_text(text, max_bytes=max_bytes)
        # Each chunk must not exceed a single overflow word beyond the limit
        for chunk_text, _ in chunks:
            assert len(chunk_text.encode("utf-8")) <= max_bytes + 25

    def test_chunk_offsets_are_non_decreasing(self) -> None:
        word = "w" * 20 + " "
        text = word * 20
        chunks = AWSMacieAdapter._chunk_text(text, max_bytes=50)
        offsets = [offset for _, offset in chunks]
        assert offsets == sorted(offsets)

    def test_reconstructed_content_covers_original(self) -> None:
        """All words from the original text appear across the chunks."""
        words = ["alpha", "beta", "gamma", "delta", "epsilon"]
        text = " ".join(words)
        chunks = AWSMacieAdapter._chunk_text(text, max_bytes=10)
        combined = " ".join(chunk_text for chunk_text, _ in chunks)
        for word in words:
            assert word in combined


# ---------------------------------------------------------------------------
# inspect() — empty text short-circuit
# ---------------------------------------------------------------------------


class TestInspectEmptyText:
    @pytest.mark.asyncio
    async def test_empty_string_returns_empty_list(self) -> None:
        adapter = _make_adapter()
        with patch.object(adapter, "_inspect_sync") as mock_sync:
            result = await adapter.inspect("")
        assert result == []
        mock_sync.assert_not_called()


# ---------------------------------------------------------------------------
# inspect() — successful responses (via mocked _inspect_sync)
# ---------------------------------------------------------------------------


class TestInspectSuccess:
    @pytest.mark.asyncio
    async def test_inspect_returns_findings_from_inspect_sync(self) -> None:
        adapter = _make_adapter()
        expected = [
            PIIFinding(type="pii", category="EMAIL", severity="medium",
                       match="a@b.com", offset=0)
        ]
        with patch.object(adapter, "_inspect_sync", return_value=expected):
            result = await adapter.inspect("a@b.com")
        assert result == expected

    @pytest.mark.asyncio
    async def test_cloud_pii_backend_error_propagated(self) -> None:
        adapter = _make_adapter()
        error = CloudPIIBackendError("Comprehend unavailable")
        with patch.object(adapter, "_inspect_sync", side_effect=error):
            with pytest.raises(CloudPIIBackendError) as exc_info:
                await adapter.inspect("some text")
        assert exc_info.value is error


# ---------------------------------------------------------------------------
# _inspect_sync() — entity mapping with mocked client
# ---------------------------------------------------------------------------


class TestInspectSync:
    def test_email_entity_returns_finding(self) -> None:
        adapter = _make_adapter()
        text = "Email: alice@example.com"
        entity = _make_comprehend_entity("EMAIL", begin_offset=7, end_offset=24)
        findings = _run_inspect_sync(adapter, text, [entity])

        assert len(findings) == 1
        assert findings[0].category == "EMAIL"
        assert findings[0].severity == "medium"
        assert findings[0].match == "alice@example.com"
        assert findings[0].type == "pii"

    def test_ssn_entity_returns_critical_finding(self) -> None:
        adapter = _make_adapter()
        text = "SSN: 123-45-6789"
        entity = _make_comprehend_entity("SSN", begin_offset=5, end_offset=16)
        findings = _run_inspect_sync(adapter, text, [entity])

        assert findings[0].category == "SSN"
        assert findings[0].severity == "critical"

    def test_credit_card_entity_returns_critical_finding(self) -> None:
        adapter = _make_adapter()
        text = "Card: 4111 1111 1111 1111"
        entity = _make_comprehend_entity("CREDIT_DEBIT_NUMBER", begin_offset=6, end_offset=25)
        findings = _run_inspect_sync(adapter, text, [entity])

        assert findings[0].category == "CREDIT_CARD"
        assert findings[0].severity == "critical"

    def test_password_entity_returns_critical_finding(self) -> None:
        adapter = _make_adapter()
        text = "Password: s3cr3t!"
        entity = _make_comprehend_entity("PASSWORD", begin_offset=10, end_offset=17)
        findings = _run_inspect_sync(adapter, text, [entity])

        assert findings[0].category == "PASSWORD"
        assert findings[0].severity == "critical"

    def test_name_entity_returns_medium_finding(self) -> None:
        adapter = _make_adapter()
        text = "Name: John Smith"
        entity = _make_comprehend_entity("NAME", begin_offset=6, end_offset=16)
        findings = _run_inspect_sync(adapter, text, [entity])

        assert findings[0].category == "PERSON_NAME"
        assert findings[0].severity == "medium"

    def test_unknown_entity_type_uses_lowercase_category(self) -> None:
        adapter = _make_adapter()
        text = "CUSTOM: val"
        entity = _make_comprehend_entity("CUSTOM_ENTITY_TYPE", begin_offset=8, end_offset=11)
        findings = _run_inspect_sync(adapter, text, [entity])

        assert findings[0].category == "custom_entity_type"
        assert findings[0].severity == "medium"

    def test_no_entities_returns_empty_list(self) -> None:
        adapter = _make_adapter()
        findings = _run_inspect_sync(adapter, "No PII here", [])
        assert findings == []

    def test_multiple_entities_returned(self) -> None:
        adapter = _make_adapter()
        text = "alice@example.com 07700 900123"
        entities = [
            _make_comprehend_entity("EMAIL", begin_offset=0, end_offset=17),
            _make_comprehend_entity("PHONE", begin_offset=18, end_offset=30),
        ]
        findings = _run_inspect_sync(adapter, text, entities)

        assert len(findings) == 2
        cats = {f.category for f in findings}
        assert "EMAIL" in cats
        assert "PHONE" in cats

    def test_matched_text_extracted_from_chunk(self) -> None:
        adapter = _make_adapter()
        text = "Email: alice@example.com"
        entity = _make_comprehend_entity("EMAIL", begin_offset=7, end_offset=24)
        findings = _run_inspect_sync(adapter, text, [entity])
        assert findings[0].match == "alice@example.com"

    def test_raises_backend_error_when_boto3_not_installed(self) -> None:
        adapter = _make_adapter()
        with patch.object(_macie_module, "_HAS_BOTO3", False):
            with patch.object(_macie_module, "boto3", None):
                with pytest.raises(CloudPIIBackendError, match="boto3"):
                    adapter._inspect_sync("some text")

    def test_client_error_raises_backend_error(self) -> None:
        adapter = _make_adapter()
        mock_client = MagicMock()
        # Patch ClientError at module level so the except clause catches it
        fake_error = FakeClientError("ThrottlingException", "Rate limit exceeded")
        mock_client.detect_pii_entities.side_effect = fake_error

        with patch.object(adapter, "_get_comprehend_client", return_value=mock_client):
            with patch.object(_macie_module, "ClientError", FakeClientError):
                with pytest.raises(CloudPIIBackendError, match="ThrottlingException"):
                    adapter._inspect_sync("some text")

    def test_botocore_error_raises_backend_error(self) -> None:
        adapter = _make_adapter()
        mock_client = MagicMock()
        mock_client.detect_pii_entities.side_effect = FakeBotoCoreError("Connection failed")

        with patch.object(adapter, "_get_comprehend_client", return_value=mock_client):
            # Patch BotoCoreError at module level to make the except clause match
            with patch.object(_macie_module, "BotoCoreError", FakeBotoCoreError):
                with pytest.raises(CloudPIIBackendError, match="connection error"):
                    adapter._inspect_sync("some text")


# ---------------------------------------------------------------------------
# _inspect_sync() — byte offset calculation
# ---------------------------------------------------------------------------


class TestInspectByteOffset:
    def test_byte_offset_for_ascii_text(self) -> None:
        adapter = _make_adapter()
        text = "Email: alice@example.com"
        entity = _make_comprehend_entity("EMAIL", begin_offset=7, end_offset=24)
        findings = _run_inspect_sync(adapter, text, [entity])

        # ASCII: char offsets == byte offsets
        assert findings[0].offset == 7

    def test_byte_offset_is_integer(self) -> None:
        adapter = _make_adapter()
        text = "Test email@test.com"
        entity = _make_comprehend_entity("EMAIL", begin_offset=5, end_offset=19)
        findings = _run_inspect_sync(adapter, text, [entity])

        assert isinstance(findings[0].offset, int)


# ---------------------------------------------------------------------------
# is_available() — connectivity check
# ---------------------------------------------------------------------------


class TestIsAvailable:
    @pytest.mark.asyncio
    async def test_returns_true_when_ping_succeeds(self) -> None:
        adapter = _make_adapter()
        with patch.object(adapter, "_ping_sync"):
            result = await adapter.is_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self) -> None:
        adapter = _make_adapter()
        with patch.object(adapter, "_ping_sync", side_effect=RuntimeError("connection error")):
            result = await adapter.is_available()
        assert result is False

    @pytest.mark.asyncio
    async def test_never_raises(self) -> None:
        adapter = _make_adapter()
        with patch.object(adapter, "_ping_sync", side_effect=Exception("any error")):
            result = await adapter.is_available()
        assert isinstance(result, bool)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_cloud_pii_backend_error(self) -> None:
        adapter = _make_adapter()
        with patch.object(
            adapter, "_ping_sync",
            side_effect=CloudPIIBackendError("boto3 not installed")
        ):
            result = await adapter.is_available()
        assert result is False


# ---------------------------------------------------------------------------
# _ping_sync() — access denied treated as available
# ---------------------------------------------------------------------------


class TestPingSyncAccessDenied:
    def test_access_denied_does_not_raise(self) -> None:
        adapter = _make_adapter()
        access_denied = FakeClientError("AccessDeniedException", "Access denied")
        mock_client = MagicMock()
        mock_client.list_pii_entities_detection_jobs.side_effect = access_denied

        with patch.object(adapter, "_get_comprehend_client", return_value=mock_client):
            with patch.object(_macie_module, "ClientError", FakeClientError):
                # AccessDeniedException means creds are valid — should NOT raise
                adapter._ping_sync()  # no exception expected

    def test_non_access_error_raises_runtime_error(self) -> None:
        adapter = _make_adapter()
        throttling = FakeClientError("ThrottlingException", "Too many requests")
        mock_client = MagicMock()
        mock_client.list_pii_entities_detection_jobs.side_effect = throttling

        with patch.object(adapter, "_get_comprehend_client", return_value=mock_client):
            with patch.object(_macie_module, "ClientError", FakeClientError):
                with pytest.raises(RuntimeError, match="ThrottlingException"):
                    adapter._ping_sync()


# ---------------------------------------------------------------------------
# _get_comprehend_client() — boto3 not installed
# ---------------------------------------------------------------------------


class TestGetComprehendClient:
    def test_raises_backend_error_when_boto3_not_installed(self) -> None:
        adapter = _make_adapter()
        with patch.object(_macie_module, "_HAS_BOTO3", False):
            with patch.object(_macie_module, "boto3", None):
                with pytest.raises(CloudPIIBackendError, match="boto3"):
                    adapter._get_comprehend_client()

    def test_boto3_client_called_with_region(self) -> None:
        adapter = _make_adapter(region_name="us-east-1")
        mock_boto3 = MagicMock()
        mock_config = MagicMock()
        mock_boto3.client.return_value = MagicMock()

        with patch.object(_macie_module, "_HAS_BOTO3", True):
            with patch.object(_macie_module, "boto3", mock_boto3):
                with patch.object(_macie_module, "Config", return_value=mock_config):
                    adapter._get_comprehend_client()

        call_kwargs = mock_boto3.client.call_args.kwargs
        assert call_kwargs["service_name"] == "comprehend"
        assert call_kwargs["region_name"] == "us-east-1"

    def test_explicit_credentials_passed_to_boto3(self) -> None:
        adapter = _make_adapter(
            aws_access_key_id="AKIA123",
            aws_secret_access_key="secret456",
        )
        mock_boto3 = MagicMock()
        mock_config = MagicMock()

        with patch.object(_macie_module, "_HAS_BOTO3", True):
            with patch.object(_macie_module, "boto3", mock_boto3):
                with patch.object(_macie_module, "Config", return_value=mock_config):
                    adapter._get_comprehend_client()

        call_kwargs = mock_boto3.client.call_args.kwargs
        assert call_kwargs.get("aws_access_key_id") == "AKIA123"
        assert call_kwargs.get("aws_secret_access_key") == "secret456"


# ---------------------------------------------------------------------------
# scan() — ScanContext pipeline integration
# ---------------------------------------------------------------------------


class TestScanContextIntegration:
    @pytest.mark.asyncio
    async def test_findings_appended_to_context(self) -> None:
        adapter = _make_adapter()
        ctx = _make_ctx("alice@example.com")

        mock_finding = PIIFinding(
            type="pii", category="EMAIL", severity="medium",
            match="alice@example.com", offset=0
        )
        with patch.object(adapter, "inspect", return_value=[mock_finding]):
            await adapter.scan(ctx)

        assert mock_finding in ctx.findings

    @pytest.mark.asyncio
    async def test_skips_when_extracted_text_is_none(self) -> None:
        adapter = _make_adapter()
        ctx = _make_ctx(None)

        with patch.object(adapter, "inspect") as mock_inspect:
            await adapter.scan(ctx)

        mock_inspect.assert_not_called()
        assert ctx.findings == []

    @pytest.mark.asyncio
    async def test_skips_when_extracted_text_is_empty(self) -> None:
        adapter = _make_adapter()
        ctx = _make_ctx("")

        with patch.object(adapter, "inspect") as mock_inspect:
            await adapter.scan(ctx)

        mock_inspect.assert_not_called()
        assert ctx.findings == []

    @pytest.mark.asyncio
    async def test_preserves_preexisting_findings(self) -> None:
        adapter = _make_adapter()
        ctx = _make_ctx("alice@example.com")
        sentinel = object()
        ctx.findings.append(sentinel)

        new_finding = PIIFinding(
            type="pii", category="EMAIL", severity="medium",
            match="alice@example.com", offset=0
        )
        with patch.object(adapter, "inspect", return_value=[new_finding]):
            await adapter.scan(ctx)

        assert sentinel in ctx.findings
        assert new_finding in ctx.findings

    @pytest.mark.asyncio
    async def test_error_appended_to_context_errors_on_failure(self) -> None:
        adapter = _make_adapter()
        ctx = _make_ctx("some text")

        with patch.object(
            adapter, "inspect",
            side_effect=CloudPIIBackendError("Comprehend unavailable")
        ):
            await adapter.scan(ctx)

        assert len(ctx.errors) == 1
        assert "Comprehend unavailable" in ctx.errors[0]

    @pytest.mark.asyncio
    async def test_no_findings_on_backend_error(self) -> None:
        adapter = _make_adapter()
        ctx = _make_ctx("some text")

        with patch.object(adapter, "inspect", side_effect=CloudPIIBackendError("unavailable")):
            await adapter.scan(ctx)

        assert ctx.findings == []

    @pytest.mark.asyncio
    async def test_scan_id_preserved(self) -> None:
        adapter = _make_adapter()
        ctx = _make_ctx("alice@example.com")
        original_scan_id = ctx.scan_id

        with patch.object(adapter, "inspect", return_value=[]):
            await adapter.scan(ctx)

        assert ctx.scan_id == original_scan_id


# ---------------------------------------------------------------------------
# Entity type mapping parametrized coverage
# ---------------------------------------------------------------------------


class TestEntityTypeMapping:
    @pytest.mark.parametrize("entity_type,expected_category,expected_severity", [
        ("NAME", "PERSON_NAME", "medium"),
        ("EMAIL", "EMAIL", "medium"),
        ("PHONE", "PHONE", "medium"),
        ("SSN", "SSN", "critical"),
        ("CREDIT_DEBIT_NUMBER", "CREDIT_CARD", "critical"),
        ("PASSWORD", "PASSWORD", "critical"),
        ("PASSPORT_NUMBER", "PASSPORT", "high"),
        ("BANK_ACCOUNT_NUMBER", "BANK_ACCOUNT", "high"),
        ("IP_ADDRESS", "IP_ADDRESS", "low"),
        ("URL", "URL", "low"),
        ("DATE_TIME", "DATE", "low"),
        ("AGE", "AGE", "low"),
    ])
    def test_entity_type_mapping(
        self, entity_type: str, expected_category: str, expected_severity: str
    ) -> None:
        adapter = _make_adapter()
        text = "matched_text extra"
        entity = _make_comprehend_entity(entity_type, begin_offset=0, end_offset=12)
        findings = _run_inspect_sync(adapter, text, [entity])

        assert len(findings) == 1
        assert findings[0].category == expected_category
        assert findings[0].severity == expected_severity


# ---------------------------------------------------------------------------
# PIIFinding structure
# ---------------------------------------------------------------------------


class TestPIIFindingStructure:
    def test_finding_type_is_pii(self) -> None:
        adapter = _make_adapter()
        text = "test@example.com"
        entity = _make_comprehend_entity("EMAIL", 0, 16)
        findings = _run_inspect_sync(adapter, text, [entity])
        assert findings[0].type == "pii"

    def test_finding_is_piifinding_instance(self) -> None:
        adapter = _make_adapter()
        text = "test@example.com"
        entity = _make_comprehend_entity("EMAIL", 0, 16)
        findings = _run_inspect_sync(adapter, text, [entity])
        assert isinstance(findings[0], PIIFinding)
