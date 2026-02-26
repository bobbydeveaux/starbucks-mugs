"""Google Cloud Data Loss Prevention (DLP) PII detection adapter.

:class:`GoogleDLPAdapter` sends file content to the Google Cloud DLP
``InspectContent`` API and normalises the response into :class:`Finding`
objects compatible with the FileGuard scan pipeline.

**Cloud backend selection**

This adapter is selected when ``pii_backend = "google_dlp"`` is set in the
tenant's ``custom_patterns`` config.  It supplements or replaces the local
regex scanner (:class:`~fileguard.core.pii_detector.PIIDetector`) depending
on the tenant disposition rules.

**Fail-secure contract**

If the DLP API is unreachable, returns an unexpected error, or the call times
out, :meth:`scan` raises :class:`~fileguard.core.av_adapter.AVEngineError`.
Callers **must not** treat an exception from this method as a clean result;
they must apply fail-secure disposition (block / surface an error code).

**Credential configuration**

Google Cloud credentials are resolved from the environment using
Application Default Credentials (ADC), or by passing an explicit service
account key path via the ``GOOGLE_DLP_CREDENTIALS_FILE`` environment variable.

Usage::

    from fileguard.core.adapters.dlp_adapter import GoogleDLPAdapter

    adapter = GoogleDLPAdapter(project_id="my-gcp-project")
    findings = await adapter.scan(pdf_bytes, mime_type="application/pdf")
    for finding in findings:
        print(finding.category, finding.severity)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fileguard.core.av_adapter import AVEngineError
from fileguard.engines.base import Finding, FindingSeverity, FindingType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DLP info-type → Finding severity mapping
# ---------------------------------------------------------------------------

# Info types that warrant HIGH severity — directly identifiable personal data.
_HIGH_SEVERITY_TYPES: frozenset[str] = frozenset({
    "UK_NATIONAL_INSURANCE_NUMBER",
    "UK_NHS_NUMBER",
    "UK_DRIVERS_LICENCE_NUMBER",
    "UK_TAXPAYER_REFERENCE",
    "PASSPORT",
    "PERSON_NAME",
    "DATE_OF_BIRTH",
    "CREDIT_CARD_NUMBER",
    "IBAN_CODE",
    "SWIFT_CODE",
    "US_SOCIAL_SECURITY_NUMBER",
    "US_INDIVIDUAL_TAXPAYER_IDENTIFICATION_NUMBER",
})

# Info types that warrant MEDIUM severity — indirectly identifiable data.
_MEDIUM_SEVERITY_TYPES: frozenset[str] = frozenset({
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "UK_POSTAL_CODE",
    "IP_ADDRESS",
    "MAC_ADDRESS",
    "STREET_ADDRESS",
})

# All other DLP findings default to LOW severity.


def _severity_for_info_type(info_type_name: str) -> FindingSeverity:
    """Map a DLP info type name to a :class:`FindingSeverity` value.

    Args:
        info_type_name: The canonical DLP info type name
            (e.g. ``"EMAIL_ADDRESS"``, ``"UK_NHS_NUMBER"``).

    Returns:
        :data:`FindingSeverity.HIGH` for directly identifiable data,
        :data:`FindingSeverity.MEDIUM` for indirectly identifiable data,
        :data:`FindingSeverity.LOW` for all other types.
    """
    if info_type_name in _HIGH_SEVERITY_TYPES:
        return FindingSeverity.HIGH
    if info_type_name in _MEDIUM_SEVERITY_TYPES:
        return FindingSeverity.MEDIUM
    return FindingSeverity.LOW


# ---------------------------------------------------------------------------
# DLP likelihood → minimum likelihood filter
# ---------------------------------------------------------------------------

# Map string likelihood names to integer ranks for comparison.
_LIKELIHOOD_RANK: dict[str, int] = {
    "LIKELIHOOD_UNSPECIFIED": 0,
    "VERY_UNLIKELY": 1,
    "UNLIKELY": 2,
    "POSSIBLE": 3,
    "LIKELY": 4,
    "VERY_LIKELY": 5,
}


def _likelihood_rank(name: str) -> int:
    """Return the numeric rank of a DLP likelihood string."""
    return _LIKELIHOOD_RANK.get(name, 0)


# ---------------------------------------------------------------------------
# MIME type → DLP ByteContentItem type mapping
# ---------------------------------------------------------------------------

_MIME_TO_DLP_TYPE: dict[str, str] = {
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "WORD_DOCUMENT",
    "application/msword": "WORD_DOCUMENT",
    "text/csv": "CSV",
    "application/csv": "CSV",
    "application/json": "TEXT_UTF8",
    "text/json": "TEXT_UTF8",
    "text/plain": "TEXT_UTF8",
    "text/x-plain": "TEXT_UTF8",
    "image/jpeg": "IMAGE_JPEG",
    "image/png": "IMAGE_PNG",
    "image/gif": "IMAGE_GIF",
    "image/bmp": "IMAGE_BMP",
    "image/svg+xml": "SVG",
}

_DEFAULT_DLP_TYPE = "BYTES_TYPE_UNSPECIFIED"

# Default info types to inspect when none are explicitly provided.
_DEFAULT_INFO_TYPES: tuple[str, ...] = (
    "UK_NATIONAL_INSURANCE_NUMBER",
    "UK_NHS_NUMBER",
    "UK_TAXPAYER_REFERENCE",
    "PERSON_NAME",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "UK_POSTAL_CODE",
    "DATE_OF_BIRTH",
    "CREDIT_CARD_NUMBER",
    "PASSPORT",
    "IBAN_CODE",
    "IP_ADDRESS",
    "STREET_ADDRESS",
)


class GoogleDLPAdapter:
    """Google Cloud DLP adapter for PII detection.

    Sends file bytes to the Google Cloud DLP ``InspectContent`` API and
    translates the response into :class:`~fileguard.engines.base.Finding`
    objects with ``type=FindingType.PII``.

    The adapter is thread-safe: the ``google-cloud-dlp`` client is stateless
    beyond the RPC channel, which is safe for concurrent use.

    Args:
        project_id: GCP project ID that owns the DLP service quota.
            Required.
        info_types: List of DLP info type names to inspect for
            (e.g. ``["EMAIL_ADDRESS", "UK_NHS_NUMBER"]``).  Defaults to a
            curated UK-focused set (see :data:`_DEFAULT_INFO_TYPES`).
        min_likelihood: Minimum DLP likelihood level to report.  Findings
            below this threshold are silently filtered.  Must be one of:
            ``"POSSIBLE"``, ``"LIKELY"`` (default), ``"VERY_LIKELY"``.
        timeout: RPC timeout in seconds.  Defaults to ``30.0``.
        credentials_file: Optional path to a Google service account JSON key
            file.  When ``None``, Application Default Credentials are used.

    Example::

        adapter = GoogleDLPAdapter(project_id="my-project")
        findings = await adapter.scan(text_bytes, "text/plain")
        print(f"Found {len(findings)} PII findings")
    """

    def __init__(
        self,
        project_id: str,
        info_types: Optional[list[str]] = None,
        min_likelihood: str = "LIKELY",
        timeout: float = 30.0,
        credentials_file: Optional[str] = None,
    ) -> None:
        self._project_id = project_id
        self._info_types = list(info_types) if info_types else list(_DEFAULT_INFO_TYPES)
        self._min_likelihood = min_likelihood
        self._min_likelihood_rank = _likelihood_rank(min_likelihood)
        self._timeout = timeout
        self._credentials_file = credentials_file
        self._client = self._build_client()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scan(self, data: bytes, mime_type: str = "text/plain") -> list[Finding]:
        """Detect PII in *data* using the Google Cloud DLP API.

        The method dispatches the blocking RPC to a thread-pool executor so
        the asyncio event loop is not blocked.

        Args:
            data: Raw file bytes to inspect.
            mime_type: MIME type of the content.  Used to select the correct
                DLP ``ByteContentItem`` type; unknown types fall back to
                ``BYTES_TYPE_UNSPECIFIED``.

        Returns:
            List of :class:`~fileguard.engines.base.Finding` objects with
            ``type=FindingType.PII`` and ``match="[REDACTED]"``.  Returns an
            empty list when no PII is found above the configured likelihood
            threshold.

        Raises:
            :class:`~fileguard.core.av_adapter.AVEngineError`: If the DLP API
                is unreachable, returns an error, or the call times out.
                Callers must treat this as a scan failure and apply
                fail-secure disposition.
        """
        if not data:
            logger.debug("GoogleDLPAdapter.scan: empty content, skipping DLP call")
            return []

        loop = asyncio.get_running_loop()
        try:
            findings = await loop.run_in_executor(
                None,
                self._inspect_sync,
                data,
                mime_type,
            )
        except AVEngineError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AVEngineError(
                f"GoogleDLPAdapter: unexpected error during scan: {exc}"
            ) from exc

        return findings

    async def is_available(self) -> bool:
        """Return ``True`` if the DLP API is reachable.

        Attempts a lightweight ``list_info_types`` call to verify connectivity.
        All exceptions are suppressed; the method always returns ``True`` or
        ``False``.

        Returns:
            ``True`` if the DLP service responded, ``False`` on any error.
        """
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._ping_sync)
            return True
        except Exception:  # noqa: BLE001
            return False

    def adapter_name(self) -> str:
        """Return the adapter identifier ``"google_dlp"``."""
        return "google_dlp"

    # ------------------------------------------------------------------
    # Synchronous helpers (executed in thread-pool)
    # ------------------------------------------------------------------

    def _build_client(self) -> object:
        """Construct the DLP API client.

        Returns a ``google.cloud.dlp_v2.DlpServiceClient`` instance.
        Credentials are resolved from Application Default Credentials unless a
        key file path is provided.

        Raises:
            ImportError: If the ``google-cloud-dlp`` package is not installed.
        """
        try:
            import google.cloud.dlp_v2 as dlp  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "google-cloud-dlp is required for GoogleDLPAdapter. "
                "Install it with: pip install google-cloud-dlp"
            ) from exc

        if self._credentials_file:
            from google.oauth2 import service_account  # type: ignore[import]
            credentials = service_account.Credentials.from_service_account_file(
                self._credentials_file
            )
            return dlp.DlpServiceClient(credentials=credentials)

        return dlp.DlpServiceClient()

    def _inspect_sync(self, data: bytes, mime_type: str) -> list[Finding]:
        """Synchronous DLP ``InspectContent`` call executed in a thread pool.

        Args:
            data: Raw file bytes.
            mime_type: MIME type of the content.

        Returns:
            List of normalised :class:`Finding` objects.

        Raises:
            :class:`~fileguard.core.av_adapter.AVEngineError`: On any API
                error or timeout.
        """
        try:
            import google.cloud.dlp_v2 as dlp  # type: ignore[import]
            from google.api_core.exceptions import GoogleAPIError  # type: ignore[import]
        except ImportError as exc:
            raise AVEngineError(
                "google-cloud-dlp is not installed; cannot run DLP scan"
            ) from exc

        dlp_type = _MIME_TO_DLP_TYPE.get(
            mime_type.split(";")[0].strip().lower(),
            _DEFAULT_DLP_TYPE,
        )

        inspect_config = {
            "info_types": [{"name": t} for t in self._info_types],
            "include_quote": False,  # Never include actual PII values
            "min_likelihood": self._min_likelihood,
        }

        item = {
            "byte_item": {
                "type_": dlp_type,
                "data": data,
            }
        }

        parent = f"projects/{self._project_id}"

        try:
            response = self._client.inspect_content(  # type: ignore[attr-defined]
                request={"parent": parent, "inspect_config": inspect_config, "item": item},
                timeout=self._timeout,
            )
        except GoogleAPIError as exc:
            raise AVEngineError(
                f"Google DLP API error: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise AVEngineError(
                f"Google DLP scan failed: {exc}"
            ) from exc

        return self._parse_response(response)

    def _parse_response(self, response: object) -> list[Finding]:
        """Parse a DLP ``InspectContentResponse`` into :class:`Finding` objects.

        Args:
            response: The ``InspectContentResponse`` returned by the DLP API.

        Returns:
            Normalised list of :class:`Finding` objects.  PII findings always
            have ``match="[REDACTED]"`` — the actual matched text is never
            stored.
        """
        findings: list[Finding] = []

        result = getattr(response, "result", None)
        if result is None:
            return findings

        dlp_findings = getattr(result, "findings", [])

        for dlp_finding in dlp_findings:
            info_type = getattr(dlp_finding, "info_type", None)
            if info_type is None:
                continue

            category = getattr(info_type, "name", "UNKNOWN")

            # Filter by minimum likelihood (belt-and-braces — the API already
            # filters, but we double-check in case the server returns extras).
            likelihood_obj = getattr(dlp_finding, "likelihood", None)
            likelihood_name = (
                likelihood_obj.name if likelihood_obj is not None else "LIKELIHOOD_UNSPECIFIED"
            )
            if _likelihood_rank(likelihood_name) < self._min_likelihood_rank:
                continue

            # Extract byte offset from location information.
            offset = 0
            location = getattr(dlp_finding, "location", None)
            if location is not None:
                byte_range = getattr(location, "byte_range", None)
                if byte_range is not None:
                    offset = int(getattr(byte_range, "start", 0))

            severity = _severity_for_info_type(category)

            findings.append(
                Finding(
                    type=FindingType.PII,
                    category=category,
                    severity=severity,
                    offset=offset,
                    match="[REDACTED]",
                )
            )

            logger.debug(
                "GoogleDLPAdapter: found %s at offset %d (severity=%s)",
                category,
                offset,
                severity.value,
            )

        logger.info(
            "GoogleDLPAdapter: inspection complete, %d findings above threshold",
            len(findings),
        )
        return findings

    def _ping_sync(self) -> None:
        """Blocking health-check via the DLP ``list_info_types`` call.

        Raises:
            Exception: Propagated from the DLP client; suppressed by
                :meth:`is_available`.
        """
        try:
            import google.cloud.dlp_v2 as dlp  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError("google-cloud-dlp not installed") from exc

        self._client.list_info_types(  # type: ignore[attr-defined]
            request={"language_code": "en-GB"},
            timeout=10.0,
        )
