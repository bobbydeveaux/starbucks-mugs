"""AWS Macie PII detection adapter.

:class:`AWSMacieAdapter` integrates with Amazon Macie v2 to perform
sensitive-data discovery on file content.  Because Macie operates on S3
objects rather than arbitrary byte streams, the adapter stages file content
into a configured *staging bucket*, creates a one-time classification job,
polls for completion, retrieves findings, then cleans up the staged object.

**Cloud backend selection**

This adapter is selected when ``pii_backend = "aws_macie"`` is set in the
tenant's ``custom_patterns`` config.  It supplements or replaces the local
regex scanner (:class:`~fileguard.core.pii_detector.PIIDetector`) depending
on the tenant disposition rules.

**Fail-secure contract**

If Macie is unreachable, the job creation fails, the job does not complete
within the configured timeout, or any unexpected error occurs, :meth:`scan`
raises :class:`~fileguard.core.av_adapter.AVEngineError`.  Callers **must
not** treat an exception from this method as a clean result; they must apply
fail-secure disposition (block / surface an error code).

**Required AWS permissions**

The IAM role or user running the adapter needs the following permissions:

* ``s3:PutObject`` / ``s3:DeleteObject`` on the staging bucket
* ``s3:GetObject`` / ``s3:ListBucket`` on the findings output bucket
* ``macie2:CreateClassificationJob``
* ``macie2:DescribeClassificationJob``
* ``macie2:GetFindings`` / ``macie2:ListFindings``
* ``macie2:ListClassificationJobs`` (optional, for health checks)

**Environment variables**

Configure the staging and output buckets via the application settings
(``MACIE_STAGING_BUCKET`` and ``MACIE_OUTPUT_BUCKET``) or pass them directly
to the constructor.

Usage::

    from fileguard.core.adapters.macie_adapter import AWSMacieAdapter

    adapter = AWSMacieAdapter(
        staging_bucket="my-fileguard-staging",
        region_name="eu-west-2",
    )
    findings = await adapter.scan(pdf_bytes, mime_type="application/pdf")
    for finding in findings:
        print(finding.category, finding.severity)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Optional

from fileguard.core.av_adapter import AVEngineError
from fileguard.engines.base import Finding, FindingSeverity, FindingType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------

# Macie sensitive data categories that warrant HIGH severity.
_HIGH_SEVERITY_CATEGORIES: frozenset[str] = frozenset({
    "NATIONAL_IDENTIFICATION_NUMBER",
    "FINANCIAL_INFORMATION",
    "HEALTH_INFORMATION",
    "PASSPORT_NUMBER",
    "TAX_IDENTIFICATION_NUMBER",
    "DRIVER_ID",
})

# Categories that warrant MEDIUM severity.
_MEDIUM_SEVERITY_CATEGORIES: frozenset[str] = frozenset({
    "EMAIL",
    "ADDRESS",
    "PHONE_NUMBER",
    "IP_ADDRESS",
})


def _severity_for_category(category: str) -> FindingSeverity:
    """Map a Macie sensitive data category to :class:`FindingSeverity`.

    Args:
        category: Macie sensitive data type category string
            (e.g. ``"EMAIL"``, ``"FINANCIAL_INFORMATION"``).

    Returns:
        :data:`FindingSeverity.HIGH`, :data:`FindingSeverity.MEDIUM`, or
        :data:`FindingSeverity.LOW`.
    """
    upper = category.upper()
    if upper in _HIGH_SEVERITY_CATEGORIES:
        return FindingSeverity.HIGH
    if upper in _MEDIUM_SEVERITY_CATEGORIES:
        return FindingSeverity.MEDIUM
    return FindingSeverity.LOW


def _severity_for_macie_severity(severity_str: str) -> FindingSeverity:
    """Map a Macie finding severity string to :class:`FindingSeverity`.

    Args:
        severity_str: Macie severity string — ``"High"``, ``"Medium"``, or
            ``"Low"``.

    Returns:
        Corresponding :class:`FindingSeverity` enum value.
    """
    mapping = {
        "High": FindingSeverity.HIGH,
        "HIGH": FindingSeverity.HIGH,
        "Medium": FindingSeverity.MEDIUM,
        "MEDIUM": FindingSeverity.MEDIUM,
        "Low": FindingSeverity.LOW,
        "LOW": FindingSeverity.LOW,
    }
    return mapping.get(severity_str, FindingSeverity.LOW)


# ---------------------------------------------------------------------------
# Polling defaults
# ---------------------------------------------------------------------------

_DEFAULT_POLL_INTERVAL_S: float = 5.0
_DEFAULT_JOB_TIMEOUT_S: float = 300.0  # 5 minutes
_STAGING_KEY_PREFIX: str = "fileguard-scan/"


class AWSMacieAdapter:
    """AWS Macie v2 adapter for PII detection.

    Stages file bytes in an S3 bucket, creates a one-time Macie
    classification job, polls for completion, and translates Macie findings
    into :class:`~fileguard.engines.base.Finding` objects with
    ``type=FindingType.PII``.

    The adapter cleans up the staged S3 object regardless of whether the
    Macie job succeeded or failed.

    Args:
        staging_bucket: S3 bucket name used to temporarily store file content
            for Macie inspection.  The bucket must be in the same AWS region
            and Macie must have read access to it.
        region_name: AWS region name (e.g. ``"eu-west-2"``).  Defaults to
            the region configured in the AWS SDK environment.
        aws_access_key_id: Optional explicit AWS access key.  When ``None``,
            the SDK credential chain is used (IAM role, environment variables,
            ``~/.aws/credentials``).
        aws_secret_access_key: Optional explicit AWS secret key.
        poll_interval: Seconds between job-status poll requests.  Defaults
            to ``5.0``.
        job_timeout: Maximum seconds to wait for a Macie job to complete.
            Raises :class:`~fileguard.core.av_adapter.AVEngineError` on
            timeout.  Defaults to ``300.0`` (5 minutes).

    Example::

        adapter = AWSMacieAdapter(
            staging_bucket="my-staging-bucket",
            region_name="eu-west-2",
        )
        findings = await adapter.scan(csv_bytes, "text/csv")
    """

    def __init__(
        self,
        staging_bucket: str,
        region_name: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        poll_interval: float = _DEFAULT_POLL_INTERVAL_S,
        job_timeout: float = _DEFAULT_JOB_TIMEOUT_S,
    ) -> None:
        self._staging_bucket = staging_bucket
        self._region_name = region_name
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self._poll_interval = poll_interval
        self._job_timeout = job_timeout

        # Lazily-built boto3 clients (one per session for thread safety).
        self._s3_client = self._build_s3_client()
        self._macie_client = self._build_macie_client()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scan(self, data: bytes, mime_type: str = "text/plain") -> list[Finding]:
        """Detect PII in *data* using Amazon Macie.

        The workflow:

        1. Upload *data* to the staging S3 bucket under a unique key.
        2. Create a one-time Macie classification job targeting that object.
        3. Poll until the job reaches a terminal state (``COMPLETE`` or
           ``CANCELLED`` / ``FAILED``).
        4. Retrieve and parse Macie findings.
        5. Delete the staged S3 object (cleanup runs even on failure).

        Args:
            data: Raw file bytes to inspect.
            mime_type: MIME type of the content (informational — Macie
                detects content type automatically).

        Returns:
            List of :class:`~fileguard.engines.base.Finding` objects with
            ``type=FindingType.PII`` and ``match="[REDACTED]"``.

        Raises:
            :class:`~fileguard.core.av_adapter.AVEngineError`: If the S3
                upload fails, the Macie job cannot be created, the job times
                out, or any unexpected AWS error occurs.
        """
        if not data:
            logger.debug("AWSMacieAdapter.scan: empty content, skipping Macie scan")
            return []

        staging_key = f"{_STAGING_KEY_PREFIX}{uuid.uuid4()}"
        loop = asyncio.get_running_loop()

        try:
            findings = await loop.run_in_executor(
                None,
                self._scan_sync,
                data,
                staging_key,
                mime_type,
            )
        except AVEngineError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AVEngineError(
                f"AWSMacieAdapter: unexpected error during scan: {exc}"
            ) from exc

        return findings

    async def is_available(self) -> bool:
        """Return ``True`` if AWS Macie is reachable.

        Performs a lightweight ``describe_bucket_count`` call to verify
        connectivity.  All exceptions are suppressed.

        Returns:
            ``True`` if Macie responded, ``False`` on any error.
        """
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._ping_sync)
            return True
        except Exception:  # noqa: BLE001
            return False

    def adapter_name(self) -> str:
        """Return the adapter identifier ``"aws_macie"``."""
        return "aws_macie"

    # ------------------------------------------------------------------
    # Synchronous helpers (executed in thread-pool)
    # ------------------------------------------------------------------

    def _build_s3_client(self) -> object:
        """Construct a boto3 S3 client.

        Raises:
            ImportError: If boto3 is not installed.
        """
        try:
            import boto3  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for AWSMacieAdapter. "
                "Install it with: pip install boto3"
            ) from exc

        kwargs: dict = {}
        if self._region_name:
            kwargs["region_name"] = self._region_name
        if self._aws_access_key_id:
            kwargs["aws_access_key_id"] = self._aws_access_key_id
        if self._aws_secret_access_key:
            kwargs["aws_secret_access_key"] = self._aws_secret_access_key

        return boto3.client("s3", **kwargs)

    def _build_macie_client(self) -> object:
        """Construct a boto3 Macie v2 client.

        Raises:
            ImportError: If boto3 is not installed.
        """
        try:
            import boto3  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for AWSMacieAdapter. "
                "Install it with: pip install boto3"
            ) from exc

        kwargs: dict = {}
        if self._region_name:
            kwargs["region_name"] = self._region_name
        if self._aws_access_key_id:
            kwargs["aws_access_key_id"] = self._aws_access_key_id
        if self._aws_secret_access_key:
            kwargs["aws_secret_access_key"] = self._aws_secret_access_key

        return boto3.client("macie2", **kwargs)

    def _scan_sync(
        self,
        data: bytes,
        staging_key: str,
        mime_type: str,
    ) -> list[Finding]:
        """Orchestrate the full Macie scan workflow synchronously.

        Executes inside a thread-pool executor.

        Args:
            data: File bytes to scan.
            staging_key: S3 object key to use for staging.
            mime_type: MIME type (informational).

        Returns:
            List of :class:`Finding` objects.

        Raises:
            :class:`~fileguard.core.av_adapter.AVEngineError`: On any
                AWS API error, timeout, or unexpected response.
        """
        try:
            from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import]
        except ImportError as exc:
            raise AVEngineError("boto3/botocore is not installed") from exc

        # Step 1: Upload to staging bucket.
        try:
            self._upload_to_s3(staging_key, data, mime_type)
        except (BotoCoreError, ClientError) as exc:
            raise AVEngineError(
                f"AWSMacieAdapter: S3 upload failed for key {staging_key!r}: {exc}"
            ) from exc

        # Step 2–4: Run Macie job, poll, retrieve findings.
        findings: list[Finding] = []
        try:
            job_id = self._create_classification_job(staging_key)
            logger.debug(
                "AWSMacieAdapter: created classification job %s for key %s",
                job_id,
                staging_key,
            )
            self._wait_for_job(job_id)
            findings = self._retrieve_findings(job_id)
        except (BotoCoreError, ClientError) as exc:
            raise AVEngineError(
                f"AWSMacieAdapter: Macie API error: {exc}"
            ) from exc
        finally:
            # Step 5: Always clean up the staged object.
            self._delete_from_s3(staging_key)

        logger.info(
            "AWSMacieAdapter: scan complete, %d findings for key %s",
            len(findings),
            staging_key,
        )
        return findings

    def _upload_to_s3(self, key: str, data: bytes, mime_type: str) -> None:
        """Upload *data* to the staging bucket under *key*.

        Args:
            key: S3 object key.
            data: File bytes.
            mime_type: Content type for the S3 object metadata.

        Raises:
            ClientError: On S3 API errors.
        """
        self._s3_client.put_object(  # type: ignore[attr-defined]
            Bucket=self._staging_bucket,
            Key=key,
            Body=data,
            ContentType=mime_type,
        )
        logger.debug(
            "AWSMacieAdapter: uploaded %d bytes to s3://%s/%s",
            len(data),
            self._staging_bucket,
            key,
        )

    def _delete_from_s3(self, key: str) -> None:
        """Delete the staged S3 object.

        Suppresses all exceptions so cleanup never masks the original error.

        Args:
            key: S3 object key to delete.
        """
        try:
            self._s3_client.delete_object(  # type: ignore[attr-defined]
                Bucket=self._staging_bucket,
                Key=key,
            )
            logger.debug(
                "AWSMacieAdapter: deleted staged object s3://%s/%s",
                self._staging_bucket,
                key,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "AWSMacieAdapter: failed to delete staged object %r: %s",
                key,
                exc,
            )

    def _create_classification_job(self, staging_key: str) -> str:
        """Create a one-time Macie classification job for the staged object.

        Args:
            staging_key: S3 key of the object to scan.

        Returns:
            The Macie job ID.

        Raises:
            ClientError: On Macie API errors.
        """
        job_name = f"fileguard-{uuid.uuid4()}"

        response = self._macie_client.create_classification_job(  # type: ignore[attr-defined]
            name=job_name,
            jobType="ONE_TIME",
            s3JobDefinition={
                "bucketDefinitions": [
                    {
                        "accountId": self._get_account_id(),
                        "buckets": [self._staging_bucket],
                    }
                ],
                "scoping": {
                    "includes": {
                        "and": [
                            {
                                "simpleScopeTerm": {
                                    "comparator": "EQ",
                                    "key": "OBJECT_KEY",
                                    "values": [staging_key],
                                }
                            }
                        ]
                    }
                },
            },
        )

        job_id: str = response["jobId"]
        return job_id

    def _get_account_id(self) -> str:
        """Retrieve the AWS account ID via STS.

        Returns:
            The caller's AWS account ID string.

        Raises:
            ClientError: On STS API errors.
        """
        try:
            import boto3  # type: ignore[import]

            kwargs: dict = {}
            if self._region_name:
                kwargs["region_name"] = self._region_name
            if self._aws_access_key_id:
                kwargs["aws_access_key_id"] = self._aws_access_key_id
            if self._aws_secret_access_key:
                kwargs["aws_secret_access_key"] = self._aws_secret_access_key

            sts = boto3.client("sts", **kwargs)
            identity = sts.get_caller_identity()
            return identity["Account"]
        except Exception as exc:  # noqa: BLE001
            raise AVEngineError(
                f"AWSMacieAdapter: failed to retrieve AWS account ID: {exc}"
            ) from exc

    def _wait_for_job(self, job_id: str) -> None:
        """Poll Macie until the classification job reaches a terminal state.

        Terminal states: ``COMPLETE``, ``CANCELLED``, ``PAUSED`` (error
        conditions), or any unknown status.

        Args:
            job_id: Macie job ID to poll.

        Raises:
            :class:`~fileguard.core.av_adapter.AVEngineError`: If the job
                does not complete within :attr:`_job_timeout` seconds, or
                if the job reaches a non-successful terminal state.
        """
        deadline = time.monotonic() + self._job_timeout
        terminal_states = {"COMPLETE", "CANCELLED", "PAUSED", "IDLE"}

        while True:
            response = self._macie_client.describe_classification_job(  # type: ignore[attr-defined]
                jobId=job_id
            )
            status: str = response.get("jobStatus", "UNKNOWN")

            if status in terminal_states:
                if status != "COMPLETE":
                    raise AVEngineError(
                        f"AWSMacieAdapter: job {job_id!r} ended with status {status!r}"
                    )
                logger.debug(
                    "AWSMacieAdapter: job %s completed successfully", job_id
                )
                return

            if time.monotonic() >= deadline:
                raise AVEngineError(
                    f"AWSMacieAdapter: job {job_id!r} did not complete within "
                    f"{self._job_timeout:.0f}s (last status: {status!r})"
                )

            logger.debug(
                "AWSMacieAdapter: job %s status=%s; polling again in %.1fs",
                job_id,
                status,
                self._poll_interval,
            )
            time.sleep(self._poll_interval)

    def _retrieve_findings(self, job_id: str) -> list[Finding]:
        """Retrieve Macie sensitive-data findings for *job_id*.

        Args:
            job_id: Completed Macie job ID.

        Returns:
            Normalised list of :class:`Finding` objects.

        Raises:
            ClientError: On Macie API errors.
        """
        # List finding IDs associated with the job.
        list_response = self._macie_client.list_findings(  # type: ignore[attr-defined]
            findingCriteria={
                "criterion": {
                    "classificationDetails.jobId": {
                        "eq": [job_id],
                    }
                }
            }
        )

        finding_ids: list[str] = list_response.get("findingIds", [])
        if not finding_ids:
            return []

        # Fetch full finding details in batches of up to 25 (AWS limit).
        findings: list[Finding] = []
        batch_size = 25
        for i in range(0, len(finding_ids), batch_size):
            batch_ids = finding_ids[i : i + batch_size]
            get_response = self._macie_client.get_findings(  # type: ignore[attr-defined]
                findingIds=batch_ids
            )
            for raw_finding in get_response.get("findings", []):
                findings.extend(self._map_finding(raw_finding))

        return findings

    def _map_finding(self, raw: dict) -> list[Finding]:
        """Map a single Macie finding dict to :class:`Finding` objects.

        Macie ``SensitiveData`` findings contain a list of detected data
        categories, each with occurrences.  Each category becomes one
        :class:`Finding` with offset ``0`` (Macie reports occurrence counts
        rather than byte offsets).

        Args:
            raw: A Macie finding dictionary as returned by ``GetFindings``.

        Returns:
            List of zero or more :class:`Finding` objects.
        """
        findings: list[Finding] = []

        # Only process SensitiveData findings.
        finding_type: str = raw.get("type", "")
        if finding_type != "SensitiveData:S3Object/Multiple" and not finding_type.startswith(
            "SensitiveData"
        ):
            return findings

        # Extract severity from the finding itself.
        severity_obj = raw.get("severity", {})
        macie_severity: str = severity_obj.get("description", "Low")

        # Walk classificationDetails.result.sensitiveData[].category
        classification = raw.get("classificationDetails", {})
        result = classification.get("result", {})
        sensitive_data_list: list[dict] = result.get("sensitiveData", [])

        for sd_entry in sensitive_data_list:
            category: str = sd_entry.get("category", "UNKNOWN")
            # Use category-specific severity first; fall back to job-level severity.
            severity = _severity_for_category(category)
            if severity == FindingSeverity.LOW:
                # Upgrade if Macie itself rated the finding higher.
                severity = _severity_for_macie_severity(macie_severity)

            findings.append(
                Finding(
                    type=FindingType.PII,
                    category=category,
                    severity=severity,
                    offset=0,  # Macie does not provide byte offsets.
                    match="[REDACTED]",
                )
            )

            logger.debug(
                "AWSMacieAdapter: mapped finding category=%s severity=%s",
                category,
                severity.value,
            )

        return findings

    def _ping_sync(self) -> None:
        """Blocking health-check via ``describe_buckets``.

        Raises:
            Any exception raised by the Macie client; suppressed by
            :meth:`is_available`.
        """
        # Use a non-intrusive Macie read call to verify connectivity.
        self._macie_client.describe_buckets(  # type: ignore[attr-defined]
            maxResults=1
        )
