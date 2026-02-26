"""Google Cloud DLP backend adapter for cloud-native PII detection.

:class:`GoogleDLPAdapter` integrates Google Cloud Data Loss Prevention (DLP)
API v2 into the FileGuard scan pipeline as a configurable cloud PII detection
backend.  It submits extracted document text to the DLP ``projects.content.inspect``
endpoint and maps the response into standard
:class:`~fileguard.core.pii_detector.PIIFinding` objects.

**API used:** ``google.cloud.dlp_v2.DlpServiceClient.inspect_content``

**Design notes**

* All API calls are executed in a thread-pool executor to avoid blocking the
  asyncio event loop.
* The adapter is stateless after construction; the same instance may be used
  concurrently from multiple asyncio tasks.
* Empty input text short-circuits before making any API call.
* :meth:`is_available` makes a lightweight ``list_info_types`` call to verify
  credentials and connectivity; all exceptions are suppressed.
* The DLP ``min_likelihood`` filter prevents low-confidence matches from
  producing noisy findings; defaults to ``LIKELY``.

**Authentication:** Uses Application Default Credentials (ADC) by default.
Pass explicit ``credentials`` to the constructor for service-account key
injection or workload-identity override.

Usage::

    from fileguard.core.adapters.google_dlp_adapter import GoogleDLPAdapter

    adapter = GoogleDLPAdapter(project_id="my-gcp-project")
    findings = await adapter.inspect("Patient NI: AB123456C, NHS: 943 476 5919")
    for f in findings:
        print(f.category, f.severity, f.match)

    # Pipeline integration
    await adapter.scan(context)   # appends findings to context.findings
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Sequence

from fileguard.core.adapters.cloud_pii_adapter import CloudPIIAdapter, CloudPIIBackendError
from fileguard.core.pii_detector import PIIFinding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional Google Cloud DLP SDK import
# ---------------------------------------------------------------------------
# Imported at module level so tests can patch these names via
# `patch("fileguard.core.adapters.google_dlp_adapter.dlp_v2", ...)`.
# When the SDK is not installed, `dlp_v2` and `GoogleAPICallError` are set to
# None and CloudPIIBackendError is raised at call time.

try:
    from google.api_core.exceptions import GoogleAPICallError  # type: ignore[import]
    from google.cloud import dlp_v2  # type: ignore[import]
    _HAS_GOOGLE_DLP = True
except ImportError:
    dlp_v2 = None  # type: ignore[assignment]
    GoogleAPICallError = None  # type: ignore[assignment,misc]
    _HAS_GOOGLE_DLP = False


# ---------------------------------------------------------------------------
# DLP infoType → (category, severity) mapping
# ---------------------------------------------------------------------------

# Mapping from Google DLP infoType names to FileGuard category labels and
# severity levels.  infoTypes not in this map are reported with their
# original DLP name in lowercase as category and severity "medium".
_DLP_INFO_TYPE_MAP: dict[str, tuple[str, str]] = {
    "UK_NATIONAL_INSURANCE_NUMBER": ("NI_NUMBER", "high"),
    "UK_NATIONAL_HEALTH_SERVICE_NUMBER": ("NHS_NUMBER", "high"),
    "EMAIL_ADDRESS": ("EMAIL", "medium"),
    "PHONE_NUMBER": ("PHONE", "medium"),
    "UK_POSTAL_CODE": ("POSTCODE", "low"),
    "PERSON_NAME": ("PERSON_NAME", "medium"),
    "DATE_OF_BIRTH": ("DATE_OF_BIRTH", "high"),
    "PASSPORT": ("PASSPORT", "high"),
    "UK_DRIVERS_LICENSE_NUMBER": ("DRIVERS_LICENSE", "high"),
    "CREDIT_CARD_NUMBER": ("CREDIT_CARD", "critical"),
    "IBAN_CODE": ("IBAN", "high"),
    "SWIFT_CODE": ("SWIFT_CODE", "medium"),
    "IP_ADDRESS": ("IP_ADDRESS", "low"),
    "MAC_ADDRESS": ("MAC_ADDRESS", "low"),
    "GENDER": ("GENDER", "low"),
    "ETHNIC_GROUP": ("ETHNIC_GROUP", "high"),
    "MEDICAL_RECORD_NUMBER": ("MEDICAL_RECORD", "high"),
    "URL": ("URL", "low"),
    "LOCATION": ("LOCATION", "medium"),
    "ORGANIZATION_NAME": ("ORGANIZATION_NAME", "low"),
}

# DLP likelihood values ordered from lowest to highest confidence.
# See: https://cloud.google.com/dlp/docs/likelihood
_LIKELIHOOD_TO_SEVERITY: dict[str, str] = {
    "VERY_UNLIKELY": "low",
    "UNLIKELY": "low",
    "POSSIBLE": "medium",
    "LIKELY": "high",
    "VERY_LIKELY": "high",
}

# Default infoTypes to request when none are specified explicitly.
# These align with the FileGuard UK-focused pattern set plus common globals.
_DEFAULT_INFO_TYPES: list[str] = [
    "UK_NATIONAL_INSURANCE_NUMBER",
    "UK_NATIONAL_HEALTH_SERVICE_NUMBER",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "UK_POSTAL_CODE",
    "PERSON_NAME",
    "DATE_OF_BIRTH",
    "PASSPORT",
    "CREDIT_CARD_NUMBER",
    "IBAN_CODE",
    "IP_ADDRESS",
]


class GoogleDLPAdapter(CloudPIIAdapter):
    """Google Cloud DLP adapter for cloud-native PII detection.

    Submits extracted text to the Google Cloud DLP ``inspect_content`` API
    and maps the response into :class:`~fileguard.core.pii_detector.PIIFinding`
    objects compatible with the FileGuard pipeline.

    Args:
        project_id: GCP project ID under which DLP API calls are billed.
        location: DLP processing location.  Use ``"global"`` for the default
            global endpoint or a regional location (e.g. ``"europe-west2"``)
            for data-residency requirements.  Defaults to ``"global"``.
        info_types: List of DLP infoType names to inspect for.  When
            ``None``, a default set covering UK PII plus common globals is
            used.  See :data:`_DEFAULT_INFO_TYPES`.
        min_likelihood: Minimum DLP likelihood level for a finding to be
            included.  Valid values: ``"VERY_UNLIKELY"``, ``"UNLIKELY"``,
            ``"POSSIBLE"``, ``"LIKELY"``, ``"VERY_LIKELY"``.  Defaults to
            ``"LIKELY"`` to reduce false positives.
        timeout: Timeout in seconds for each DLP API call.  Defaults to
            ``30``.
        credentials: Optional explicit GCP credentials object.  When
            ``None``, Application Default Credentials (ADC) are used.

    Example::

        adapter = GoogleDLPAdapter(
            project_id="my-gcp-project",
            location="europe-west2",
            info_types=["UK_NATIONAL_INSURANCE_NUMBER", "EMAIL_ADDRESS"],
            min_likelihood="POSSIBLE",
        )
        findings = await adapter.inspect("Email: alice@example.com")
    """

    def __init__(
        self,
        project_id: str,
        *,
        location: str = "global",
        info_types: Optional[Sequence[str]] = None,
        min_likelihood: str = "LIKELY",
        timeout: float = 30.0,
        credentials: object = None,
    ) -> None:
        self._project_id = project_id
        self._location = location
        self._info_types: list[str] = list(info_types) if info_types else list(_DEFAULT_INFO_TYPES)
        self._min_likelihood = min_likelihood
        self._timeout = timeout
        self._credentials = credentials

        logger.debug(
            "GoogleDLPAdapter initialised: project=%s location=%s info_types=%s min_likelihood=%s",
            project_id,
            location,
            self._info_types,
            min_likelihood,
        )

    # ------------------------------------------------------------------
    # CloudPIIAdapter interface
    # ------------------------------------------------------------------

    async def inspect(self, text: str) -> list[PIIFinding]:
        """Inspect *text* for PII using the Google Cloud DLP API.

        Submits the text to ``projects.content.inspect`` and maps each DLP
        ``Finding`` into a :class:`~fileguard.core.pii_detector.PIIFinding`.
        Blocking SDK calls are delegated to a thread-pool executor.

        Args:
            text: Plain text to inspect.  An empty string returns immediately
                with no API call.

        Returns:
            List of :class:`~fileguard.core.pii_detector.PIIFinding` objects,
            one per DLP finding at or above *min_likelihood*.

        Raises:
            :class:`~fileguard.core.adapters.cloud_pii_adapter.CloudPIIBackendError`:
                If the DLP API call fails for any reason (network error,
                authentication failure, quota exceeded, invalid request, etc.).
        """
        if not text:
            return []

        loop = asyncio.get_running_loop()
        try:
            findings = await loop.run_in_executor(None, self._inspect_sync, text)
        except CloudPIIBackendError:
            raise
        except Exception as exc:  # pragma: no cover
            raise CloudPIIBackendError(
                f"Unexpected error during Google DLP inspection: {exc}"
            ) from exc
        return findings

    async def is_available(self) -> bool:
        """Return ``True`` if the DLP API is reachable with current credentials.

        Makes a lightweight ``list_info_types`` call.  All exceptions are
        suppressed — this method always returns ``True`` or ``False`` and
        never raises.

        Returns:
            ``True`` if the DLP service responded successfully.
            ``False`` for any error (network, auth, quota, …).
        """
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._ping_sync)
            return True
        except Exception:
            return False

    def backend_name(self) -> str:
        """Return the backend identifier ``"google_dlp"``."""
        return "google_dlp"

    # ------------------------------------------------------------------
    # Synchronous helpers (run inside executor)
    # ------------------------------------------------------------------

    def _get_client(self) -> object:
        """Construct a DLP service client.

        Returns:
            :class:`google.cloud.dlp_v2.DlpServiceClient` instance.

        Raises:
            :class:`~fileguard.core.adapters.cloud_pii_adapter.CloudPIIBackendError`:
                If the ``google-cloud-dlp`` package is not installed.
        """
        if not _HAS_GOOGLE_DLP:
            raise CloudPIIBackendError(
                "google-cloud-dlp is not installed. "
                "Install it with: pip install google-cloud-dlp"
            )
        kwargs: dict = {}
        if self._credentials is not None:
            kwargs["credentials"] = self._credentials
        return dlp_v2.DlpServiceClient(**kwargs)

    def _parent(self) -> str:
        """Return the DLP API parent resource path for this adapter's configuration."""
        if self._location == "global":
            return f"projects/{self._project_id}"
        return f"projects/{self._project_id}/locations/{self._location}"

    def _inspect_sync(self, text: str) -> list[PIIFinding]:
        """Blocking DLP ``inspect_content`` call executed inside a thread-pool executor.

        Args:
            text: Plain text to inspect.

        Returns:
            List of :class:`~fileguard.core.pii_detector.PIIFinding` objects.

        Raises:
            :class:`~fileguard.core.adapters.cloud_pii_adapter.CloudPIIBackendError`:
                On SDK unavailability or API error (network, auth, quota, …).
        """
        if not _HAS_GOOGLE_DLP:
            raise CloudPIIBackendError(
                "google-cloud-dlp is not installed. "
                "Install it with: pip install google-cloud-dlp"
            )

        client = self._get_client()

        item = {"value": text}
        inspect_config = {
            "info_types": [{"name": t} for t in self._info_types],
            "min_likelihood": self._min_likelihood,
            "include_quote": True,
            "limits": {"max_findings_per_request": 1000},
        }

        try:
            response = client.inspect_content(
                request={
                    "parent": self._parent(),
                    "inspect_config": inspect_config,
                    "item": item,
                },
                timeout=self._timeout,
            )
        except Exception as exc:
            # GoogleAPICallError is caught as Exception here so that tests
            # can mock it without needing the real google-cloud-dlp package.
            # In production, GoogleAPICallError (a subclass of Exception) is
            # raised by the SDK on API errors.
            if GoogleAPICallError is not None and isinstance(exc, GoogleAPICallError):
                raise CloudPIIBackendError(
                    f"Google DLP API call failed: {exc}"
                ) from exc
            raise CloudPIIBackendError(
                f"Google DLP inspect_content raised unexpected error: {exc}"
            ) from exc

        findings: list[PIIFinding] = []
        result = response.result
        for dlp_finding in result.findings:
            info_type_name: str = dlp_finding.info_type.name
            likelihood_name: str = dlp_finding.likelihood.name
            quote: str = dlp_finding.quote or ""

            category, severity = _DLP_INFO_TYPE_MAP.get(
                info_type_name,
                (info_type_name.lower(), _LIKELIHOOD_TO_SEVERITY.get(likelihood_name, "medium")),
            )

            byte_offset: int = -1
            if dlp_finding.location and dlp_finding.location.byte_range:
                byte_offset = dlp_finding.location.byte_range.start

            findings.append(
                PIIFinding(
                    type="pii",
                    category=category,
                    severity=severity,  # type: ignore[arg-type]
                    match=quote,
                    offset=byte_offset,
                )
            )
            logger.debug(
                "Google DLP finding: info_type=%s category=%s severity=%s likelihood=%s offset=%d",
                info_type_name,
                category,
                severity,
                likelihood_name,
                byte_offset,
            )

        logger.info(
            "Google DLP inspect complete: project=%s findings=%d",
            self._project_id,
            len(findings),
        )
        return findings

    def _ping_sync(self) -> None:
        """Blocking connectivity check executed inside a thread-pool executor.

        Calls ``list_info_types`` with an empty filter as a lightweight
        credential and connectivity verification.

        Raises:
            :class:`~fileguard.core.adapters.cloud_pii_adapter.CloudPIIBackendError`:
                If the SDK is not installed.
            :class:`RuntimeError`:
                On API error (propagated to :meth:`is_available` which
                suppresses it and returns ``False``).
        """
        if not _HAS_GOOGLE_DLP:
            raise CloudPIIBackendError(
                "google-cloud-dlp is not installed. "
                "Install it with: pip install google-cloud-dlp"
            )

        client = self._get_client()
        try:
            client.list_info_types(request={}, timeout=self._timeout)
        except Exception as exc:
            if GoogleAPICallError is not None and isinstance(exc, GoogleAPICallError):
                raise RuntimeError(f"Google DLP connectivity check failed: {exc}") from exc
            raise RuntimeError(f"Google DLP connectivity check error: {exc}") from exc
