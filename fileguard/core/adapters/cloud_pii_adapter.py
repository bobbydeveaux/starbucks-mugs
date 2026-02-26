"""Abstract plugin interface for cloud-native PII detection backend adapters.

Cloud PII adapters integrate third-party managed services (Google DLP, AWS
Macie / Comprehend) into the FileGuard scan pipeline as configurable
alternatives to — or augmentations of — the built-in UK regex pattern engine.

All concrete cloud PII implementations must implement
:class:`CloudPIIAdapter`.  The pipeline depends only on this interface,
enabling drop-in replacement or simultaneous multi-backend operation without
modifying pipeline code.

**Fail-secure contract:** :meth:`CloudPIIAdapter.inspect` must *never* return
an empty findings list when the backend cannot be contacted or encounters an
error.  Any communication failure or unexpected API response must raise
:class:`CloudPIIBackendError` instead.  :meth:`is_available` must *never*
raise; it returns ``False`` for all error conditions.

Usage::

    from fileguard.core.adapters.cloud_pii_adapter import CloudPIIAdapter, CloudPIIBackendError
    from fileguard.core.pii_detector import PIIFinding
    from fileguard.core.scan_context import ScanContext

    class MyCloudAdapter(CloudPIIAdapter):
        async def inspect(self, text: str) -> list[PIIFinding]: ...
        async def is_available(self) -> bool: ...
        def backend_name(self) -> str: ...
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from fileguard.core.pii_detector import PIIFinding
from fileguard.core.scan_context import ScanContext

logger = logging.getLogger(__name__)


class CloudPIIBackendError(Exception):
    """Raised when a cloud PII backend adapter encounters an unrecoverable error.

    This exception signals that the inspection *could not be completed*, not
    that the text is PII-free.  Callers must treat
    :class:`CloudPIIBackendError` as a hard failure and apply fail-secure
    disposition (record error, do not silently pass the file through).

    The original cause is always chained via ``__cause__`` so that log
    aggregation systems can surface the root error without losing context.
    """


class CloudPIIAdapter(ABC):
    """Abstract base class for cloud-native PII detection backend adapters.

    Concrete implementations connect to a managed cloud API (Google DLP,
    AWS Comprehend/Macie, etc.), submit text for inspection, and translate
    service-specific responses into :class:`~fileguard.core.pii_detector.PIIFinding`
    objects that integrate directly with the FileGuard scan pipeline.

    **Fail-secure contract:** :meth:`inspect` must *never* return an empty
    result when the inspection cannot be completed.  Any communication
    failure or unexpected API response must raise :class:`CloudPIIBackendError`
    instead.  :meth:`is_available` must *never* raise; it returns ``False``
    for all error conditions.
    """

    @abstractmethod
    async def inspect(self, text: str) -> list[PIIFinding]:
        """Inspect *text* for PII and return structured findings.

        Submits the supplied text to the cloud backend for PII detection
        and translates the service response into a list of
        :class:`~fileguard.core.pii_detector.PIIFinding` objects.

        Args:
            text: The plain text to inspect.  An empty string may be passed;
                backends should return an empty list without making an API
                call.

        Returns:
            List of :class:`~fileguard.core.pii_detector.PIIFinding` objects,
            one per detected PII instance.  An empty list indicates no PII
            was detected (not that inspection failed).

        Raises:
            :class:`CloudPIIBackendError`: If the backend is unreachable,
                returns an error status, or produces an unrecognised response.
                The exception **must not** be suppressed; the caller must
                apply fail-secure disposition.
        """

    @abstractmethod
    async def is_available(self) -> bool:
        """Check whether the cloud backend is reachable and ready for inspection.

        Intended for health-check endpoints and pre-flight validation.

        Returns:
            ``True`` if the backend can accept inspection requests right now.
            ``False`` for *any* error condition (connection refused, auth
            failure, quota exceeded, …).  This method must **never** raise.
        """

    @abstractmethod
    def backend_name(self) -> str:
        """Return a short, human-readable backend identifier.

        Returns:
            Lowercase string used in finding metadata and log output,
            e.g. ``"google_dlp"``, ``"aws_macie"``.
        """

    # ------------------------------------------------------------------
    # Pipeline integration
    # ------------------------------------------------------------------

    async def scan(self, context: ScanContext) -> None:
        """Inspect the text in *context* and append findings to ``context.findings``.

        This is the primary async pipeline integration point.  It reads
        ``context.extracted_text``, calls :meth:`inspect`, and extends
        ``context.findings`` with the results.

        When ``context.extracted_text`` is ``None`` or empty, the method is a
        no-op — no findings are added and no API call is made.

        When :meth:`inspect` raises :class:`CloudPIIBackendError`, the error
        message is appended to ``context.errors`` and no findings are added
        (fail-secure: the calling pipeline should treat non-empty
        ``context.errors`` as a scan failure).

        Args:
            context: The shared :class:`~fileguard.core.scan_context.ScanContext`
                for the current scan.  Modified in place by appending
                :class:`~fileguard.core.pii_detector.PIIFinding` objects to
                ``context.findings`` and error strings to ``context.errors``.
        """
        text = context.extracted_text
        if not text:
            logger.debug(
                "%s.scan: no extracted text in context (scan_id=%s); skipping",
                type(self).__name__,
                context.scan_id,
            )
            return

        try:
            findings = await self.inspect(text)
        except CloudPIIBackendError as exc:
            error_msg = (
                f"{self.backend_name()} inspection failed "
                f"(scan_id={context.scan_id}): {exc}"
            )
            logger.error(error_msg)
            context.errors.append(error_msg)
            return

        context.findings.extend(findings)

        logger.info(
            "%s.scan complete: scan_id=%s findings=%d",
            type(self).__name__,
            context.scan_id,
            len(findings),
        )
