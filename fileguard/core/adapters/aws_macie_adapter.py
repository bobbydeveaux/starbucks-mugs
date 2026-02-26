"""AWS Macie / Comprehend backend adapter for cloud-native PII detection.

:class:`AWSMacieAdapter` integrates Amazon Web Services' PII detection
capabilities into the FileGuard scan pipeline.  AWS Macie is a data security
service that discovers, classifies, and protects sensitive data in S3 buckets.
For real-time text content inspection — the primary use-case within FileGuard —
the adapter uses **Amazon Comprehend** (``detect_pii_entities``), which provides
the same ML-powered PII detection engine that underlies Macie's sensitive data
discovery.

**API used:** ``boto3`` Comprehend client — ``detect_pii_entities``

**Why Comprehend, not Macie directly?**
AWS Macie exposes a bucket-level classification job API (``create_classification_job``)
designed for asynchronous S3 object scanning, not for synchronous inspection
of arbitrary text content.  Amazon Comprehend's ``detect_pii_entities``
provides the per-request text inspection capability needed for the FileGuard
real-time pipeline, using the same underlying ML models.  Macie classification
jobs are the appropriate tool for the FileGuard batch S3 scanning workflow
(see ``BatchJobProcessor``).

**Design notes**

* All API calls are executed in a thread-pool executor to avoid blocking the
  asyncio event loop.
* The adapter is stateless after construction; the same instance may be used
  concurrently from multiple asyncio tasks.
* Empty input text short-circuits before making any API call.
* :meth:`is_available` calls ``list_pii_entities_detection_jobs`` to verify
  AWS credentials and connectivity.
* Text longer than 100,000 UTF-8 bytes is automatically chunked before
  submission; Comprehend's per-request limit is 100 KB.

**Authentication:** Uses the default boto3 credential resolution chain
(environment variables, ``~/.aws/credentials``, instance profile, etc.) when
no explicit credentials are provided.

Usage::

    from fileguard.core.adapters.aws_macie_adapter import AWSMacieAdapter

    adapter = AWSMacieAdapter(region_name="eu-west-2")
    findings = await adapter.inspect("Patient email: alice@nhs.uk NI: AB123456C")
    for f in findings:
        print(f.category, f.severity, f.match)

    # Pipeline integration
    await adapter.scan(context)   # appends findings to context.findings
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fileguard.core.adapters.cloud_pii_adapter import CloudPIIAdapter, CloudPIIBackendError
from fileguard.core.pii_detector import PIIFinding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# boto3 / botocore module-level imports
# ---------------------------------------------------------------------------
# Imported at module level so tests can patch these names:
#   patch("fileguard.core.adapters.aws_macie_adapter.boto3", ...)
#   patch("fileguard.core.adapters.aws_macie_adapter.ClientError", ...)
#
# boto3 is a declared dependency (requirements.txt), so ImportError is
# treated as a fatal misconfiguration.

try:
    import boto3  # type: ignore[import]
    from botocore.config import Config  # type: ignore[import]
    from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import]
    _HAS_BOTO3 = True
except ImportError:
    boto3 = None  # type: ignore[assignment]
    Config = None  # type: ignore[assignment,misc]
    BotoCoreError = Exception  # type: ignore[assignment,misc]
    ClientError = Exception  # type: ignore[assignment,misc]
    _HAS_BOTO3 = False


# ---------------------------------------------------------------------------
# Amazon Comprehend PII entity type → (category, severity) mapping
# ---------------------------------------------------------------------------

# Mapping from Comprehend PII entity types to FileGuard category labels and
# severity levels.  Entity types not in this map are reported with their
# original Comprehend name in lowercase as category and severity "medium".
# See: https://docs.aws.amazon.com/comprehend/latest/dg/how-pii.html
_COMPREHEND_ENTITY_MAP: dict[str, tuple[str, str]] = {
    "NAME": ("PERSON_NAME", "medium"),
    "AGE": ("AGE", "low"),
    "ADDRESS": ("ADDRESS", "medium"),
    "EMAIL": ("EMAIL", "medium"),
    "PHONE": ("PHONE", "medium"),
    "DATE_TIME": ("DATE", "low"),
    "SSN": ("SSN", "critical"),
    "CREDIT_DEBIT_NUMBER": ("CREDIT_CARD", "critical"),
    "CREDIT_DEBIT_CVV": ("CREDIT_CARD_CVV", "critical"),
    "CREDIT_DEBIT_EXPIRY": ("CREDIT_CARD_EXPIRY", "high"),
    "PIN": ("PIN", "critical"),
    "BANK_ACCOUNT_NUMBER": ("BANK_ACCOUNT", "high"),
    "BANK_ROUTING": ("BANK_ROUTING", "high"),
    "PASSPORT_NUMBER": ("PASSPORT", "high"),
    "DRIVER_ID": ("DRIVERS_LICENSE", "high"),
    "NATIONAL_ID": ("NATIONAL_ID", "high"),
    "URL": ("URL", "low"),
    "IP_ADDRESS": ("IP_ADDRESS", "low"),
    "MAC_ADDRESS": ("MAC_ADDRESS", "low"),
    "USERNAME": ("USERNAME", "medium"),
    "PASSWORD": ("PASSWORD", "critical"),
    "AWS_ACCESS_KEY": ("AWS_ACCESS_KEY", "critical"),
    "AWS_SECRET_KEY": ("AWS_SECRET_KEY", "critical"),
    "INTERNATIONAL_BANK_ACCOUNT_NUMBER": ("IBAN", "high"),
    "SWIFT_CODE": ("SWIFT_CODE", "medium"),
    "UK_NATIONAL_INSURANCE_NUMBER": ("NI_NUMBER", "high"),
    "UK_UNIQUE_TAXPAYER_REFERENCE_NUMBER": ("UTR_NUMBER", "high"),
}

# Amazon Comprehend has a 100 KB per-request limit for detect_pii_entities.
# Texts longer than this are chunked on whitespace boundaries.
_COMPREHEND_MAX_BYTES = 100_000


class AWSMacieAdapter(CloudPIIAdapter):
    """AWS Macie / Comprehend adapter for cloud-native PII detection.

    Uses Amazon Comprehend's ``detect_pii_entities`` API to inspect extracted
    text for PII, then maps Comprehend entity types into
    :class:`~fileguard.core.pii_detector.PIIFinding` objects compatible with
    the FileGuard pipeline.

    For batch S3 bucket scanning, use Macie classification jobs via
    ``BatchJobProcessor`` instead.

    Args:
        region_name: AWS region for the Comprehend API endpoint.  Use an EU
            region (e.g. ``"eu-west-2"``) for GDPR data-residency requirements.
            Defaults to ``"eu-west-2"``.
        aws_access_key_id: Explicit AWS access key ID.  When ``None``,
            the boto3 credential chain is used (environment variables,
            ``~/.aws/credentials``, instance profile, etc.).
        aws_secret_access_key: Explicit AWS secret access key.  When ``None``,
            the boto3 credential chain is used.
        aws_session_token: Temporary session token for assumed roles or
            federated credentials.  Optional even when explicit key/secret are
            provided.
        timeout: Socket-level timeout in seconds applied to boto3 calls.
            Defaults to ``30``.

    Example::

        adapter = AWSMacieAdapter(region_name="eu-west-2")
        findings = await adapter.inspect("Name: John Smith, SSN: 123-45-6789")

        # With explicit credentials (e.g. in non-IAM environments)
        adapter = AWSMacieAdapter(
            region_name="us-east-1",
            aws_access_key_id="AKIA...",
            aws_secret_access_key="secret...",
        )
    """

    def __init__(
        self,
        *,
        region_name: str = "eu-west-2",
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self._region_name = region_name
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self._aws_session_token = aws_session_token
        self._timeout = timeout

        logger.debug(
            "AWSMacieAdapter initialised: region=%s explicit_credentials=%s",
            region_name,
            aws_access_key_id is not None,
        )

    # ------------------------------------------------------------------
    # CloudPIIAdapter interface
    # ------------------------------------------------------------------

    async def inspect(self, text: str) -> list[PIIFinding]:
        """Inspect *text* for PII using Amazon Comprehend ``detect_pii_entities``.

        For texts larger than 100 KB, the input is chunked and each chunk
        is inspected independently; findings from all chunks are merged.
        Blocking boto3 calls are delegated to a thread-pool executor.

        Args:
            text: Plain text to inspect.  An empty string returns immediately
                with no API call.

        Returns:
            List of :class:`~fileguard.core.pii_detector.PIIFinding` objects,
            one per Comprehend PII entity detected.

        Raises:
            :class:`~fileguard.core.adapters.cloud_pii_adapter.CloudPIIBackendError`:
                If the Comprehend API call fails for any reason (network error,
                authentication failure, throttling, invalid request, etc.).
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
                f"Unexpected error during AWS Comprehend PII inspection: {exc}"
            ) from exc
        return findings

    async def is_available(self) -> bool:
        """Return ``True`` if the Comprehend API is reachable with current credentials.

        Makes a ``list_pii_entities_detection_jobs`` call with empty filters as
        a lightweight credential and connectivity check.  All exceptions are
        suppressed — this method always returns ``True`` or ``False`` and
        never raises.

        Returns:
            ``True`` if the Comprehend service responded successfully.
            ``False`` for any error (network, auth, throttling, …).
        """
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._ping_sync)
            return True
        except Exception:
            return False

    def backend_name(self) -> str:
        """Return the backend identifier ``"aws_macie"``."""
        return "aws_macie"

    # ------------------------------------------------------------------
    # Synchronous helpers (run inside executor)
    # ------------------------------------------------------------------

    def _get_comprehend_client(self) -> object:
        """Construct a boto3 Comprehend client.

        Returns:
            boto3 ``comprehend`` service client configured for this adapter's
            region and credentials.

        Raises:
            :class:`~fileguard.core.adapters.cloud_pii_adapter.CloudPIIBackendError`:
                If ``boto3`` is not installed.
        """
        if not _HAS_BOTO3 or boto3 is None:
            raise CloudPIIBackendError(
                "boto3 is not installed. Install it with: pip install boto3"
            )

        config = Config(
            connect_timeout=self._timeout,
            read_timeout=self._timeout,
            retries={"max_attempts": 1, "mode": "standard"},
        )
        kwargs: dict = {
            "service_name": "comprehend",
            "region_name": self._region_name,
            "config": config,
        }
        if self._aws_access_key_id:
            kwargs["aws_access_key_id"] = self._aws_access_key_id
        if self._aws_secret_access_key:
            kwargs["aws_secret_access_key"] = self._aws_secret_access_key
        if self._aws_session_token:
            kwargs["aws_session_token"] = self._aws_session_token

        return boto3.client(**kwargs)

    @staticmethod
    def _chunk_text(text: str, max_bytes: int = _COMPREHEND_MAX_BYTES) -> list[tuple[str, int]]:
        """Split *text* into chunks each smaller than *max_bytes* UTF-8 bytes.

        Splits on whitespace boundaries to avoid breaking mid-token.  Each
        chunk is paired with the character offset of its first character in the
        original text.

        Args:
            text: Full input text.
            max_bytes: Maximum UTF-8 byte length per chunk.

        Returns:
            List of ``(chunk_text, start_char_offset)`` tuples.
        """
        if len(text.encode("utf-8")) <= max_bytes:
            return [(text, 0)]

        chunks: list[tuple[str, int]] = []
        words = text.split(" ")
        current_words: list[str] = []
        current_bytes = 0
        char_offset = 0
        chunk_start = 0

        for word in words:
            word_bytes = len((word + " ").encode("utf-8"))
            if current_bytes + word_bytes > max_bytes and current_words:
                chunk = " ".join(current_words)
                chunks.append((chunk, chunk_start))
                chunk_start = char_offset
                current_words = [word]
                current_bytes = word_bytes
            else:
                current_words.append(word)
                current_bytes += word_bytes
            char_offset += len(word) + 1  # +1 for the space

        if current_words:
            chunks.append((" ".join(current_words), chunk_start))

        return chunks

    def _inspect_sync(self, text: str) -> list[PIIFinding]:
        """Blocking Comprehend ``detect_pii_entities`` call executed in executor.

        Handles text chunking for inputs larger than the Comprehend limit.

        Args:
            text: Plain text to inspect.

        Returns:
            Merged list of :class:`~fileguard.core.pii_detector.PIIFinding`
            objects from all chunks.

        Raises:
            :class:`~fileguard.core.adapters.cloud_pii_adapter.CloudPIIBackendError`:
                On SDK unavailability or API error (network, auth, throttling, …).
        """
        client = self._get_comprehend_client()
        chunks = self._chunk_text(text)
        all_findings: list[PIIFinding] = []

        for chunk_text, chunk_char_offset in chunks:
            try:
                response = client.detect_pii_entities(
                    Text=chunk_text,
                    LanguageCode="en",
                )
            except ClientError as exc:
                error_code = exc.response["Error"]["Code"]
                raise CloudPIIBackendError(
                    f"AWS Comprehend API error ({error_code}): {exc}"
                ) from exc
            except BotoCoreError as exc:
                raise CloudPIIBackendError(
                    f"AWS Comprehend connection error: {exc}"
                ) from exc

            entities = response.get("Entities", [])
            for entity in entities:
                entity_type: str = entity.get("Type", "")
                begin_offset: int = entity.get("BeginOffset", 0)
                end_offset: int = entity.get("EndOffset", 0)
                score: float = entity.get("Score", 0.0)

                # Extract the matched text from the chunk
                match_text = chunk_text[begin_offset:end_offset]

                # Map entity type to FileGuard category and severity
                category, severity = _COMPREHEND_ENTITY_MAP.get(
                    entity_type,
                    (entity_type.lower(), "medium"),
                )

                # Compute byte offset in original text (approximate via char offset)
                abs_char_offset = chunk_char_offset + begin_offset
                byte_offset = len(text[:abs_char_offset].encode("utf-8"))

                all_findings.append(
                    PIIFinding(
                        type="pii",
                        category=category,
                        severity=severity,  # type: ignore[arg-type]
                        match=match_text,
                        offset=byte_offset,
                    )
                )
                logger.debug(
                    "Comprehend PII entity: type=%s category=%s score=%.3f offset=%d match=%r",
                    entity_type,
                    category,
                    score,
                    byte_offset,
                    match_text,
                )

        logger.info(
            "AWS Comprehend inspect complete: region=%s chunks=%d findings=%d",
            self._region_name,
            len(chunks),
            len(all_findings),
        )
        return all_findings

    def _ping_sync(self) -> None:
        """Blocking connectivity check executed inside a thread-pool executor.

        Calls ``list_pii_entities_detection_jobs`` with an empty filter as a
        lightweight credential and connectivity verification.

        Raises:
            :class:`~fileguard.core.adapters.cloud_pii_adapter.CloudPIIBackendError`:
                If boto3 is not installed.
            :class:`RuntimeError`:
                On API error (propagated to :meth:`is_available` which
                suppresses it and returns ``False``).
        """
        client = self._get_comprehend_client()
        try:
            client.list_pii_entities_detection_jobs(MaxResults=1)
        except ClientError as exc:
            # AccessDeniedException means creds are valid but no permission for list
            # — still reachable; treat as available
            error_code = exc.response["Error"]["Code"]
            if error_code in ("AccessDeniedException", "ResourceNotFoundException"):
                return
            raise RuntimeError(
                f"AWS Comprehend connectivity check failed ({error_code}): {exc}"
            ) from exc
        except BotoCoreError as exc:
            raise RuntimeError(
                f"AWS Comprehend connectivity check failed: {exc}"
            ) from exc
