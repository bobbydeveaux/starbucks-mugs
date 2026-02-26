"""Unit tests for fileguard/core/adapters/dlp_adapter.py (GoogleDLPAdapter).

All tests run fully offline — Google Cloud DLP API calls are replaced by
``unittest.mock`` patches so no GCP credentials or network access are needed.

Coverage targets
----------------
* Empty content returns an empty findings list without calling the DLP API.
* Clean content (no findings) returns an empty list.
* Single PII finding is normalised to a Finding with [REDACTED] match.
* Multiple findings of different info types are all returned.
* Severity mapping: HIGH for NHS number, MEDIUM for email, LOW for unknown.
* Findings below the min_likelihood threshold are filtered out.
* GoogleAPIError raises AVEngineError (fail-secure).
* Generic exception during inspect raises AVEngineError.
* is_available() returns True when list_info_types succeeds.
* is_available() returns False when list_info_types raises.
* adapter_name() returns "google_dlp".
* FindingType is PII for all returned findings.
* Byte offset is extracted from location.byte_range.start when present.
* Missing location defaults offset to 0.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import os
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-chars!!")

from fileguard.core.adapters.dlp_adapter import (
    GoogleDLPAdapter,
    _severity_for_info_type,
    _likelihood_rank,
)
from fileguard.core.av_adapter import AVEngineError
from fileguard.engines.base import FindingSeverity, FindingType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dlp_finding(
    info_type_name: str = "EMAIL_ADDRESS",
    likelihood: str = "LIKELY",
    byte_start: int = 0,
    has_location: bool = True,
) -> MagicMock:
    """Build a mock DLP Finding proto-like object."""
    finding = MagicMock()

    # info_type
    info_type = MagicMock()
    info_type.name = info_type_name
    finding.info_type = info_type

    # likelihood
    likelihood_obj = MagicMock()
    likelihood_obj.name = likelihood
    finding.likelihood = likelihood_obj

    # location / byte_range
    if has_location:
        byte_range = MagicMock()
        byte_range.start = byte_start
        location = MagicMock()
        location.byte_range = byte_range
        finding.location = location
    else:
        finding.location = None

    return finding


def _make_inspect_response(dlp_findings: list[MagicMock]) -> MagicMock:
    """Build a mock DLP InspectContentResponse."""
    result = MagicMock()
    result.findings = dlp_findings
    response = MagicMock()
    response.result = result
    return response


def _make_adapter(
    min_likelihood: str = "LIKELY",
    info_types: list[str] | None = None,
) -> GoogleDLPAdapter:
    """Construct a GoogleDLPAdapter with a mocked DLP client."""
    with patch("fileguard.core.adapters.dlp_adapter.GoogleDLPAdapter._build_client") as mock_build:
        mock_build.return_value = MagicMock()
        adapter = GoogleDLPAdapter(
            project_id="test-project",
            min_likelihood=min_likelihood,
            info_types=info_types,
        )
    return adapter


# ---------------------------------------------------------------------------
# Severity mapping unit tests
# ---------------------------------------------------------------------------


class TestSeverityMapping:
    def test_nhs_number_is_high(self) -> None:
        assert _severity_for_info_type("UK_NHS_NUMBER") == FindingSeverity.HIGH

    def test_ni_number_is_high(self) -> None:
        assert _severity_for_info_type("UK_NATIONAL_INSURANCE_NUMBER") == FindingSeverity.HIGH

    def test_credit_card_is_high(self) -> None:
        assert _severity_for_info_type("CREDIT_CARD_NUMBER") == FindingSeverity.HIGH

    def test_email_is_medium(self) -> None:
        assert _severity_for_info_type("EMAIL_ADDRESS") == FindingSeverity.MEDIUM

    def test_phone_is_medium(self) -> None:
        assert _severity_for_info_type("PHONE_NUMBER") == FindingSeverity.MEDIUM

    def test_postcode_is_medium(self) -> None:
        assert _severity_for_info_type("UK_POSTAL_CODE") == FindingSeverity.MEDIUM

    def test_unknown_type_is_low(self) -> None:
        assert _severity_for_info_type("SOME_UNKNOWN_TYPE") == FindingSeverity.LOW


class TestLikelihoodRank:
    def test_very_likely_highest(self) -> None:
        assert _likelihood_rank("VERY_LIKELY") > _likelihood_rank("LIKELY")

    def test_likely_above_possible(self) -> None:
        assert _likelihood_rank("LIKELY") > _likelihood_rank("POSSIBLE")

    def test_unknown_returns_zero(self) -> None:
        assert _likelihood_rank("GARBAGE") == 0


# ---------------------------------------------------------------------------
# GoogleDLPAdapter — empty content
# ---------------------------------------------------------------------------


class TestGoogleDLPAdapterEmptyContent:
    @pytest.mark.asyncio
    async def test_empty_bytes_returns_empty_list(self) -> None:
        """Empty bytes returns [] without calling the DLP API."""
        adapter = _make_adapter()
        # The client should never be invoked for empty content.
        findings = await adapter.scan(b"", "text/plain")
        assert findings == []
        adapter._client.inspect_content.assert_not_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# GoogleDLPAdapter — clean content
# ---------------------------------------------------------------------------


class TestGoogleDLPAdapterClean:
    @pytest.mark.asyncio
    async def test_no_findings_returns_empty_list(self) -> None:
        """DLP response with no findings returns an empty list."""
        adapter = _make_adapter()
        response = _make_inspect_response([])
        adapter._client.inspect_content.return_value = response  # type: ignore[attr-defined]

        findings = await adapter.scan(b"Hello, world!", "text/plain")

        assert findings == []

    @pytest.mark.asyncio
    async def test_none_result_returns_empty_list(self) -> None:
        """DLP response with result=None returns an empty list."""
        adapter = _make_adapter()
        response = MagicMock()
        response.result = None
        adapter._client.inspect_content.return_value = response  # type: ignore[attr-defined]

        findings = await adapter.scan(b"No PII here", "text/plain")
        assert findings == []


# ---------------------------------------------------------------------------
# GoogleDLPAdapter — PII findings
# ---------------------------------------------------------------------------


class TestGoogleDLPAdapterFindings:
    @pytest.mark.asyncio
    async def test_single_email_finding(self) -> None:
        """A single email address finding is normalised correctly."""
        adapter = _make_adapter()
        dlp_finding = _make_dlp_finding(
            info_type_name="EMAIL_ADDRESS",
            likelihood="LIKELY",
            byte_start=42,
        )
        response = _make_inspect_response([dlp_finding])
        adapter._client.inspect_content.return_value = response  # type: ignore[attr-defined]

        findings = await adapter.scan(b"Contact: user@example.com", "text/plain")

        assert len(findings) == 1
        f = findings[0]
        assert f.type == FindingType.PII
        assert f.category == "EMAIL_ADDRESS"
        assert f.severity == FindingSeverity.MEDIUM
        assert f.offset == 42
        assert f.match == "[REDACTED]"

    @pytest.mark.asyncio
    async def test_nhs_number_finding_is_high_severity(self) -> None:
        """NHS number findings are mapped to HIGH severity."""
        adapter = _make_adapter()
        dlp_finding = _make_dlp_finding(
            info_type_name="UK_NHS_NUMBER",
            likelihood="VERY_LIKELY",
            byte_start=0,
        )
        response = _make_inspect_response([dlp_finding])
        adapter._client.inspect_content.return_value = response  # type: ignore[attr-defined]

        findings = await adapter.scan(b"NHS: 943 476 5919", "text/plain")
        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.HIGH

    @pytest.mark.asyncio
    async def test_multiple_findings_all_returned(self) -> None:
        """Multiple DLP findings are all present in the output."""
        adapter = _make_adapter()
        dlp_findings = [
            _make_dlp_finding("EMAIL_ADDRESS", "LIKELY", 10),
            _make_dlp_finding("UK_NHS_NUMBER", "VERY_LIKELY", 50),
            _make_dlp_finding("PHONE_NUMBER", "LIKELY", 100),
        ]
        response = _make_inspect_response(dlp_findings)
        adapter._client.inspect_content.return_value = response  # type: ignore[attr-defined]

        findings = await adapter.scan(b"some document with PII", "text/plain")
        assert len(findings) == 3

    @pytest.mark.asyncio
    async def test_missing_location_defaults_offset_to_zero(self) -> None:
        """When DLP finding has no location, offset defaults to 0."""
        adapter = _make_adapter()
        dlp_finding = _make_dlp_finding(
            info_type_name="PERSON_NAME",
            likelihood="LIKELY",
            has_location=False,
        )
        response = _make_inspect_response([dlp_finding])
        adapter._client.inspect_content.return_value = response  # type: ignore[attr-defined]

        findings = await adapter.scan(b"John Smith lives here", "text/plain")
        assert len(findings) == 1
        assert findings[0].offset == 0

    @pytest.mark.asyncio
    async def test_match_is_always_redacted(self) -> None:
        """The match field is always '[REDACTED]' — never the actual PII."""
        adapter = _make_adapter()
        dlp_finding = _make_dlp_finding("EMAIL_ADDRESS", "LIKELY")
        response = _make_inspect_response([dlp_finding])
        adapter._client.inspect_content.return_value = response  # type: ignore[attr-defined]

        findings = await adapter.scan(b"user@example.com", "text/plain")
        assert all(f.match == "[REDACTED]" for f in findings)


# ---------------------------------------------------------------------------
# GoogleDLPAdapter — likelihood filtering
# ---------------------------------------------------------------------------


class TestGoogleDLPAdapterLikelihoodFilter:
    @pytest.mark.asyncio
    async def test_finding_below_threshold_is_filtered(self) -> None:
        """Findings with likelihood below min_likelihood are discarded."""
        adapter = _make_adapter(min_likelihood="LIKELY")
        # POSSIBLE is below LIKELY
        dlp_finding = _make_dlp_finding(
            info_type_name="EMAIL_ADDRESS",
            likelihood="POSSIBLE",
        )
        response = _make_inspect_response([dlp_finding])
        adapter._client.inspect_content.return_value = response  # type: ignore[attr-defined]

        findings = await adapter.scan(b"maybe an email", "text/plain")
        assert findings == []

    @pytest.mark.asyncio
    async def test_finding_at_threshold_is_included(self) -> None:
        """Findings at exactly min_likelihood are included."""
        adapter = _make_adapter(min_likelihood="LIKELY")
        dlp_finding = _make_dlp_finding(
            info_type_name="EMAIL_ADDRESS",
            likelihood="LIKELY",
        )
        response = _make_inspect_response([dlp_finding])
        adapter._client.inspect_content.return_value = response  # type: ignore[attr-defined]

        findings = await adapter.scan(b"user@example.com", "text/plain")
        assert len(findings) == 1

    @pytest.mark.asyncio
    async def test_finding_above_threshold_is_included(self) -> None:
        """Findings above min_likelihood are included."""
        adapter = _make_adapter(min_likelihood="LIKELY")
        dlp_finding = _make_dlp_finding(
            info_type_name="EMAIL_ADDRESS",
            likelihood="VERY_LIKELY",
        )
        response = _make_inspect_response([dlp_finding])
        adapter._client.inspect_content.return_value = response  # type: ignore[attr-defined]

        findings = await adapter.scan(b"user@example.com", "text/plain")
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# GoogleDLPAdapter — error handling (fail-secure)
# ---------------------------------------------------------------------------


class TestGoogleDLPAdapterErrorHandling:
    @pytest.mark.asyncio
    async def test_google_api_error_raises_av_engine_error(self) -> None:
        """GoogleAPIError from DLP client is re-raised as AVEngineError."""
        adapter = _make_adapter()

        try:
            from google.api_core.exceptions import GoogleAPIError  # type: ignore[import]
            api_error = GoogleAPIError("Service unavailable")
        except ImportError:
            # If google-cloud-dlp is not installed, create a generic exception
            # and patch the import check.
            api_error = RuntimeError("Service unavailable")

        adapter._client.inspect_content.side_effect = api_error  # type: ignore[attr-defined]

        with pytest.raises(AVEngineError):
            await adapter.scan(b"some content", "text/plain")

    @pytest.mark.asyncio
    async def test_generic_exception_raises_av_engine_error(self) -> None:
        """Unexpected exceptions during scan are wrapped in AVEngineError."""
        adapter = _make_adapter()
        adapter._client.inspect_content.side_effect = RuntimeError("boom")  # type: ignore[attr-defined]

        with pytest.raises(AVEngineError):
            await adapter.scan(b"some content", "text/plain")


# ---------------------------------------------------------------------------
# GoogleDLPAdapter — is_available
# ---------------------------------------------------------------------------


class TestGoogleDLPAdapterIsAvailable:
    @pytest.mark.asyncio
    async def test_returns_true_when_api_responds(self) -> None:
        """is_available() returns True when list_info_types succeeds."""
        adapter = _make_adapter()
        adapter._client.list_info_types.return_value = MagicMock()  # type: ignore[attr-defined]

        result = await adapter.is_available()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_api_error(self) -> None:
        """is_available() returns False when list_info_types raises."""
        adapter = _make_adapter()
        adapter._client.list_info_types.side_effect = RuntimeError("refused")  # type: ignore[attr-defined]

        result = await adapter.is_available()
        assert result is False


# ---------------------------------------------------------------------------
# GoogleDLPAdapter — adapter_name
# ---------------------------------------------------------------------------


class TestGoogleDLPAdapterName:
    def test_adapter_name_is_google_dlp(self) -> None:
        adapter = _make_adapter()
        assert adapter.adapter_name() == "google_dlp"
