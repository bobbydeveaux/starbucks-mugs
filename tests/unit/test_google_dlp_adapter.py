"""Unit tests for fileguard/core/adapters/google_dlp_adapter.py.

All tests are fully offline — the ``google.cloud.dlp_v2`` module is mocked at
module level via ``patch("fileguard.core.adapters.google_dlp_adapter.dlp_v2", ...)``
so no real GCP credentials or API calls are required.

Coverage:
* backend_name() returns "google_dlp"
* Constructor stores configuration correctly
* inspect() returns empty list for empty text (no API call)
* inspect() maps DLP findings to PIIFinding objects correctly
* inspect() maps known infoTypes to correct categories and severities
* inspect() maps unknown infoTypes using lowercase name
* inspect() sets byte offset from DLP finding location
* inspect() sets offset=-1 when DLP provides no byte range
* inspect() raises CloudPIIBackendError on API error
* inspect() re-raises CloudPIIBackendError from _inspect_sync
* is_available() returns True when list_info_types succeeds
* is_available() returns False on any exception (never raises)
* scan() appends findings to ScanContext.findings
* scan() skips API call when extracted_text is None
* scan() skips API call when extracted_text is empty string
* scan() appends error to context.errors on CloudPIIBackendError
* scan() preserves pre-existing findings
* _parent() builds correct parent path for global location
* _parent() builds correct parent path for regional location
* _inspect_sync() raises CloudPIIBackendError when SDK not installed
* PIIFinding type, category, severity, match, offset populated correctly
* Info type → category/severity parametrized coverage
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import fileguard.core.adapters.google_dlp_adapter as _dlp_module
from fileguard.core.adapters.cloud_pii_adapter import CloudPIIBackendError
from fileguard.core.adapters.google_dlp_adapter import (
    GoogleDLPAdapter,
    _DEFAULT_INFO_TYPES,
    _DLP_INFO_TYPE_MAP,
)
from fileguard.core.pii_detector import PIIFinding
from fileguard.core.scan_context import ScanContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter(**kwargs: Any) -> GoogleDLPAdapter:
    return GoogleDLPAdapter(project_id="test-project", **kwargs)


def _make_dlp_finding(
    info_type_name: str = "EMAIL_ADDRESS",
    likelihood_name: str = "LIKELY",
    quote: str = "alice@example.com",
    byte_start: int | None = 10,
) -> MagicMock:
    """Build a mock DLP Finding proto object."""
    finding = MagicMock()
    finding.info_type.name = info_type_name
    finding.likelihood.name = likelihood_name
    finding.quote = quote

    if byte_start is not None:
        location_mock = MagicMock()
        location_mock.byte_range.start = byte_start
        finding.location = location_mock
    else:
        finding.location = None

    return finding


def _make_dlp_response(findings: list[MagicMock]) -> MagicMock:
    """Build a mock DLP inspect_content response."""
    response = MagicMock()
    response.result.findings = findings
    return response


def _make_ctx(text: str | None) -> ScanContext:
    ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
    ctx.extracted_text = text
    return ctx


def _run_inspect_sync(
    adapter: GoogleDLPAdapter,
    text: str,
    dlp_findings: list[MagicMock],
) -> list[PIIFinding]:
    """Run _inspect_sync with a fully mocked DLP client and SDK.

    Patches ``_HAS_GOOGLE_DLP=True`` so the SDK-unavailable guard passes,
    and patches ``_get_client`` so no real DLP client is constructed.
    """
    mock_client = MagicMock()
    mock_client.inspect_content.return_value = _make_dlp_response(dlp_findings)

    with patch.object(adapter, "_get_client", return_value=mock_client):
        with patch.object(_dlp_module, "_HAS_GOOGLE_DLP", True):
            return adapter._inspect_sync(text)


# ---------------------------------------------------------------------------
# backend_name
# ---------------------------------------------------------------------------


class TestBackendName:
    def test_returns_google_dlp(self) -> None:
        assert _make_adapter().backend_name() == "google_dlp"


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_project_id_stored(self) -> None:
        adapter = _make_adapter()
        assert adapter._project_id == "test-project"

    def test_default_location_is_global(self) -> None:
        adapter = _make_adapter()
        assert adapter._location == "global"

    def test_custom_location_stored(self) -> None:
        adapter = _make_adapter(location="europe-west2")
        assert adapter._location == "europe-west2"

    def test_default_info_types_are_set(self) -> None:
        adapter = _make_adapter()
        assert adapter._info_types == list(_DEFAULT_INFO_TYPES)

    def test_custom_info_types_stored(self) -> None:
        custom = ["EMAIL_ADDRESS", "PHONE_NUMBER"]
        adapter = _make_adapter(info_types=custom)
        assert adapter._info_types == custom

    def test_default_min_likelihood_is_likely(self) -> None:
        adapter = _make_adapter()
        assert adapter._min_likelihood == "LIKELY"

    def test_custom_min_likelihood_stored(self) -> None:
        adapter = _make_adapter(min_likelihood="POSSIBLE")
        assert adapter._min_likelihood == "POSSIBLE"

    def test_default_timeout(self) -> None:
        adapter = _make_adapter()
        assert adapter._timeout == 30.0

    def test_custom_timeout_stored(self) -> None:
        adapter = _make_adapter(timeout=10.0)
        assert adapter._timeout == 10.0


# ---------------------------------------------------------------------------
# _parent()
# ---------------------------------------------------------------------------


class TestParent:
    def test_global_location(self) -> None:
        adapter = _make_adapter(location="global")
        assert adapter._parent() == "projects/test-project"

    def test_regional_location(self) -> None:
        adapter = _make_adapter(location="europe-west2")
        assert adapter._parent() == "projects/test-project/locations/europe-west2"


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

    @pytest.mark.asyncio
    async def test_empty_string_makes_no_api_call(self) -> None:
        adapter = _make_adapter()
        with patch.object(adapter, "_get_client") as mock_client:
            await adapter.inspect("")
        mock_client.assert_not_called()


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
    async def test_empty_findings_returned_when_no_match(self) -> None:
        adapter = _make_adapter()
        with patch.object(adapter, "_inspect_sync", return_value=[]):
            result = await adapter.inspect("no pii here")
        assert result == []

    @pytest.mark.asyncio
    async def test_cloud_pii_backend_error_propagated(self) -> None:
        adapter = _make_adapter()
        error = CloudPIIBackendError("DLP API failed")
        with patch.object(adapter, "_inspect_sync", side_effect=error):
            with pytest.raises(CloudPIIBackendError) as exc_info:
                await adapter.inspect("some text")
        assert exc_info.value is error


# ---------------------------------------------------------------------------
# _inspect_sync() — with mocked DLP client
# ---------------------------------------------------------------------------


class TestInspectSync:
    def test_email_finding_returned(self) -> None:
        adapter = _make_adapter()
        dlp_finding = _make_dlp_finding(
            info_type_name="EMAIL_ADDRESS",
            likelihood_name="LIKELY",
            quote="alice@example.com",
            byte_start=10,
        )
        findings = _run_inspect_sync(adapter, "Contact alice@example.com", [dlp_finding])

        assert len(findings) == 1
        assert findings[0].category == "EMAIL"
        assert findings[0].severity == "medium"
        assert findings[0].match == "alice@example.com"
        assert findings[0].offset == 10
        assert findings[0].type == "pii"

    def test_ni_number_finding_returned(self) -> None:
        adapter = _make_adapter()
        dlp_finding = _make_dlp_finding(
            info_type_name="UK_NATIONAL_INSURANCE_NUMBER",
            likelihood_name="VERY_LIKELY",
            quote="AB123456C",
            byte_start=4,
        )
        findings = _run_inspect_sync(adapter, "NI: AB123456C", [dlp_finding])

        assert len(findings) == 1
        assert findings[0].category == "NI_NUMBER"
        assert findings[0].severity == "high"

    def test_nhs_number_finding_returned(self) -> None:
        adapter = _make_adapter()
        dlp_finding = _make_dlp_finding(
            info_type_name="UK_NATIONAL_HEALTH_SERVICE_NUMBER",
            likelihood_name="LIKELY",
            quote="943 476 5919",
            byte_start=5,
        )
        findings = _run_inspect_sync(adapter, "NHS: 943 476 5919", [dlp_finding])

        assert findings[0].category == "NHS_NUMBER"
        assert findings[0].severity == "high"

    def test_multiple_findings_returned(self) -> None:
        adapter = _make_adapter()
        dlp_findings = [
            _make_dlp_finding("EMAIL_ADDRESS", "LIKELY", "a@b.com", 0),
            _make_dlp_finding("PHONE_NUMBER", "LIKELY", "07700 900123", 10),
        ]
        findings = _run_inspect_sync(adapter, "a@b.com 07700 900123", dlp_findings)

        assert len(findings) == 2
        cats = {f.category for f in findings}
        assert "EMAIL" in cats
        assert "PHONE" in cats

    def test_no_findings_returns_empty_list(self) -> None:
        adapter = _make_adapter()
        findings = _run_inspect_sync(adapter, "No PII here at all", [])
        assert findings == []

    def test_unknown_info_type_uses_lowercase_name(self) -> None:
        adapter = _make_adapter()
        dlp_finding = _make_dlp_finding(
            info_type_name="CUSTOM_IDENTIFIER_XYZ",
            likelihood_name="LIKELY",
            quote="XYZ-12345",
            byte_start=0,
        )
        findings = _run_inspect_sync(adapter, "XYZ-12345", [dlp_finding])

        assert len(findings) == 1
        assert findings[0].category == "custom_identifier_xyz"

    def test_raises_backend_error_when_sdk_not_installed(self) -> None:
        adapter = _make_adapter()
        with patch.object(_dlp_module, "_HAS_GOOGLE_DLP", False):
            with patch.object(_dlp_module, "dlp_v2", None):
                with pytest.raises(CloudPIIBackendError, match="google-cloud-dlp"):
                    adapter._inspect_sync("some text")

    def test_api_error_raises_backend_error(self) -> None:
        adapter = _make_adapter()
        mock_client = MagicMock()
        mock_client.inspect_content.side_effect = RuntimeError("API failure")

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with patch.object(_dlp_module, "_HAS_GOOGLE_DLP", True):
                with pytest.raises(CloudPIIBackendError):
                    adapter._inspect_sync("some text")

    def test_inspect_content_called_with_correct_parent(self) -> None:
        adapter = _make_adapter(location="europe-west2")
        mock_client = MagicMock()
        mock_client.inspect_content.return_value = _make_dlp_response([])

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with patch.object(_dlp_module, "_HAS_GOOGLE_DLP", True):
                adapter._inspect_sync("text")

        call_kwargs = mock_client.inspect_content.call_args
        parent = call_kwargs.kwargs["request"]["parent"]
        assert parent == "projects/test-project/locations/europe-west2"


# ---------------------------------------------------------------------------
# _inspect_sync() — byte offset mapping
# ---------------------------------------------------------------------------


class TestInspectByteOffset:
    def test_offset_set_from_dlp_byte_range(self) -> None:
        adapter = _make_adapter()
        dlp_finding = _make_dlp_finding(byte_start=42)
        findings = _run_inspect_sync(adapter, "some text", [dlp_finding])
        assert findings[0].offset == 42

    def test_offset_minus_one_when_location_is_none(self) -> None:
        adapter = _make_adapter()
        dlp_finding = _make_dlp_finding(byte_start=None)
        findings = _run_inspect_sync(adapter, "some text", [dlp_finding])
        assert findings[0].offset == -1


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
    async def test_returns_false_when_sdk_not_installed(self) -> None:
        adapter = _make_adapter()
        with patch.object(
            adapter, "_ping_sync",
            side_effect=CloudPIIBackendError("google-cloud-dlp not installed")
        ):
            result = await adapter.is_available()
        assert result is False


# ---------------------------------------------------------------------------
# _get_client() — SDK availability
# ---------------------------------------------------------------------------


class TestGetClient:
    def test_raises_backend_error_when_sdk_not_installed(self) -> None:
        adapter = _make_adapter()
        with patch.object(_dlp_module, "_HAS_GOOGLE_DLP", False):
            with patch.object(_dlp_module, "dlp_v2", None):
                with pytest.raises(CloudPIIBackendError, match="google-cloud-dlp"):
                    adapter._get_client()

    def test_calls_dlp_client_constructor(self) -> None:
        adapter = _make_adapter()
        mock_dlp = MagicMock()

        with patch.object(_dlp_module, "_HAS_GOOGLE_DLP", True):
            with patch.object(_dlp_module, "dlp_v2", mock_dlp):
                adapter._get_client()

        mock_dlp.DlpServiceClient.assert_called_once()

    def test_passes_credentials_when_provided(self) -> None:
        fake_creds = MagicMock()
        adapter = _make_adapter(credentials=fake_creds)
        mock_dlp = MagicMock()

        with patch.object(_dlp_module, "_HAS_GOOGLE_DLP", True):
            with patch.object(_dlp_module, "dlp_v2", mock_dlp):
                adapter._get_client()

        mock_dlp.DlpServiceClient.assert_called_once_with(credentials=fake_creds)

    def test_no_credentials_when_not_provided(self) -> None:
        adapter = _make_adapter()  # no credentials
        mock_dlp = MagicMock()

        with patch.object(_dlp_module, "_HAS_GOOGLE_DLP", True):
            with patch.object(_dlp_module, "dlp_v2", mock_dlp):
                adapter._get_client()

        # Called with no kwargs (no credentials)
        mock_dlp.DlpServiceClient.assert_called_once_with()


# ---------------------------------------------------------------------------
# scan() — ScanContext pipeline integration
# ---------------------------------------------------------------------------


class TestScanContextIntegration:
    @pytest.mark.asyncio
    async def test_findings_appended_to_context(self) -> None:
        adapter = _make_adapter()
        ctx = _make_ctx("Email: alice@example.com")

        mock_finding = PIIFinding(
            type="pii", category="EMAIL", severity="medium",
            match="alice@example.com", offset=7
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

        with patch.object(adapter, "inspect", side_effect=CloudPIIBackendError("DLP unavailable")):
            await adapter.scan(ctx)

        assert len(ctx.errors) == 1
        assert "DLP unavailable" in ctx.errors[0]

    @pytest.mark.asyncio
    async def test_no_findings_added_when_backend_error(self) -> None:
        adapter = _make_adapter()
        ctx = _make_ctx("some text")

        with patch.object(adapter, "inspect", side_effect=CloudPIIBackendError("DLP unavailable")):
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
# PIIFinding structure
# ---------------------------------------------------------------------------


class TestPIIFindingStructure:
    def test_finding_type_is_pii(self) -> None:
        adapter = _make_adapter()
        dlp_finding = _make_dlp_finding(
            info_type_name="EMAIL_ADDRESS",
            quote="test@example.com",
            byte_start=0,
        )
        findings = _run_inspect_sync(adapter, "test@example.com", [dlp_finding])
        assert findings[0].type == "pii"

    def test_finding_is_a_piifinding(self) -> None:
        adapter = _make_adapter()
        dlp_finding = _make_dlp_finding(
            info_type_name="EMAIL_ADDRESS",
            quote="test@example.com",
            byte_start=0,
        )
        findings = _run_inspect_sync(adapter, "test@example.com", [dlp_finding])
        assert isinstance(findings[0], PIIFinding)


# ---------------------------------------------------------------------------
# Info type mapping coverage
# ---------------------------------------------------------------------------


class TestInfoTypeMapping:
    """Verify each entry in _DLP_INFO_TYPE_MAP is correctly mapped."""

    @pytest.mark.parametrize("info_type,expected_category,expected_severity", [
        ("UK_NATIONAL_INSURANCE_NUMBER", "NI_NUMBER", "high"),
        ("UK_NATIONAL_HEALTH_SERVICE_NUMBER", "NHS_NUMBER", "high"),
        ("EMAIL_ADDRESS", "EMAIL", "medium"),
        ("PHONE_NUMBER", "PHONE", "medium"),
        ("UK_POSTAL_CODE", "POSTCODE", "low"),
        ("CREDIT_CARD_NUMBER", "CREDIT_CARD", "critical"),
        ("DATE_OF_BIRTH", "DATE_OF_BIRTH", "high"),
        ("PASSPORT", "PASSPORT", "high"),
        ("IP_ADDRESS", "IP_ADDRESS", "low"),
    ])
    def test_info_type_mapping(
        self, info_type: str, expected_category: str, expected_severity: str
    ) -> None:
        adapter = _make_adapter()
        dlp_finding = _make_dlp_finding(
            info_type_name=info_type,
            likelihood_name="LIKELY",
            quote="matched_text",
            byte_start=0,
        )
        findings = _run_inspect_sync(adapter, "matched_text", [dlp_finding])

        assert len(findings) == 1
        assert findings[0].category == expected_category
        assert findings[0].severity == expected_severity
