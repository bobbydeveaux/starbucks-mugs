# PII Cloud Adapter Backends

**Module:** `fileguard.core.adapters`
**Status:** Implemented (Sprint 3)

---

## Overview

FileGuard supports two cloud-based PII detection backends that supplement or
replace the built-in regex scanner:

| Adapter | Class | Cloud Service |
|---------|-------|---------------|
| Google DLP | `GoogleDLPAdapter` | Google Cloud Data Loss Prevention API |
| AWS Macie | `AWSMacieAdapter` | Amazon Macie v2 |

Both adapters implement a common async interface and return
:class:`~fileguard.engines.base.Finding` objects with `type=FindingType.PII`
and `match="[REDACTED]"` — identical to the schema produced by the local
regex scanner.

---

## Fail-Secure Contract

Both adapters are fail-secure:

- If the cloud API is unreachable, the call times out, or an unexpected error
  occurs, `scan()` raises `AVEngineError`.
- Callers **must not** treat `AVEngineError` as a clean result. The pipeline
  must apply fail-secure disposition (block / surface an error code rather
  than returning partial results silently).
- `is_available()` never raises — it returns `False` on any error.

---

## Common Interface

Both adapters expose:

```python
async def scan(self, data: bytes, mime_type: str = "text/plain") -> list[Finding]:
    """Detect PII in data bytes. Raises AVEngineError on failure."""

async def is_available(self) -> bool:
    """Return True if the cloud backend is reachable. Never raises."""

def adapter_name(self) -> str:
    """Return a short adapter identifier string."""
```

`Finding` fields for PII detections:

| Field | Value |
|-------|-------|
| `type` | `FindingType.PII` |
| `category` | DLP info type or Macie category name |
| `severity` | `HIGH` / `MEDIUM` / `LOW` based on data type |
| `offset` | Byte offset in content (Macie: always `0`) |
| `match` | Always `"[REDACTED]"` — actual PII never stored |

---

## Google Cloud DLP Adapter

### How it works

1. Sends raw file bytes to the DLP `InspectContent` API.
2. Receives findings with info type names and byte offsets.
3. Filters findings below the configured minimum likelihood.
4. Maps info types to `FindingSeverity` values.

### Severity mapping

| Severity | Info types |
|----------|-----------|
| `HIGH` | `UK_NATIONAL_INSURANCE_NUMBER`, `UK_NHS_NUMBER`, `CREDIT_CARD_NUMBER`, `PASSPORT`, `DATE_OF_BIRTH`, `PERSON_NAME`, `IBAN_CODE`, … |
| `MEDIUM` | `EMAIL_ADDRESS`, `PHONE_NUMBER`, `UK_POSTAL_CODE`, `IP_ADDRESS`, `STREET_ADDRESS` |
| `LOW` | All other info types |

### Configuration

| Setting | Env var | Default | Description |
|---------|---------|---------|-------------|
| `project_id` | `GOOGLE_DLP_PROJECT_ID` | _(required)_ | GCP project ID |
| `credentials_file` | `GOOGLE_DLP_CREDENTIALS_FILE` | `""` | Service account key file path; falls back to ADC |
| `min_likelihood` | `GOOGLE_DLP_MIN_LIKELIHOOD` | `"LIKELY"` | Minimum DLP likelihood threshold |
| `timeout` | `GOOGLE_DLP_TIMEOUT` | `30.0` | RPC timeout in seconds |

### Usage

```python
from fileguard.core.adapters import GoogleDLPAdapter
from fileguard.config import settings

adapter = GoogleDLPAdapter(
    project_id=settings.GOOGLE_DLP_PROJECT_ID,
    min_likelihood=settings.GOOGLE_DLP_MIN_LIKELIHOOD,
    credentials_file=settings.GOOGLE_DLP_CREDENTIALS_FILE or None,
)

if not await adapter.is_available():
    raise RuntimeError("Google DLP API is not reachable")

findings = await adapter.scan(file_bytes, mime_type="application/pdf")
```

### Dependency

```
google-cloud-dlp>=3.15.0
```

---

## AWS Macie Adapter

### How it works

Because Macie operates on S3 objects rather than arbitrary byte streams, the
adapter follows a staging workflow:

1. Uploads file bytes to a configured S3 staging bucket with a unique key.
2. Creates a one-time Macie classification job scoped to that object.
3. Polls `DescribeClassificationJob` until the job reaches `COMPLETE`.
4. Calls `ListFindings` + `GetFindings` to retrieve sensitive-data findings.
5. Maps each `sensitiveData[].category` to a `Finding` object.
6. **Always** deletes the staged S3 object (even on failure).

### Severity mapping

| Severity | Macie categories |
|----------|-----------------|
| `HIGH` | `NATIONAL_IDENTIFICATION_NUMBER`, `FINANCIAL_INFORMATION`, `HEALTH_INFORMATION`, `PASSPORT_NUMBER`, `TAX_IDENTIFICATION_NUMBER`, `DRIVER_ID` |
| `MEDIUM` | `EMAIL`, `ADDRESS`, `PHONE_NUMBER`, `IP_ADDRESS` |
| `LOW` | All other categories |

### Configuration

| Setting | Env var | Default | Description |
|---------|---------|---------|-------------|
| `staging_bucket` | `MACIE_STAGING_BUCKET` | _(required)_ | S3 bucket for file staging |
| `region_name` | `MACIE_REGION` | `"eu-west-2"` | AWS region |
| `poll_interval` | `MACIE_POLL_INTERVAL` | `5.0` | Seconds between job status polls |
| `job_timeout` | `MACIE_JOB_TIMEOUT` | `300.0` | Maximum seconds to wait for job |

### Required IAM permissions

```
s3:PutObject, s3:DeleteObject  — on the staging bucket
macie2:CreateClassificationJob
macie2:DescribeClassificationJob
macie2:ListFindings
macie2:GetFindings
sts:GetCallerIdentity
```

### Usage

```python
from fileguard.core.adapters import AWSMacieAdapter
from fileguard.config import settings

adapter = AWSMacieAdapter(
    staging_bucket=settings.MACIE_STAGING_BUCKET,
    region_name=settings.MACIE_REGION,
    poll_interval=settings.MACIE_POLL_INTERVAL,
    job_timeout=settings.MACIE_JOB_TIMEOUT,
)

if not await adapter.is_available():
    raise RuntimeError("AWS Macie is not reachable")

findings = await adapter.scan(file_bytes, mime_type="text/csv")
```

### Dependency

```
boto3>=1.34.0
```

---

## Backend selection via tenant config

Adapters are selected at runtime from the tenant's `custom_patterns` config:

```json
{
  "pii_backend": "google_dlp"
}
```

or

```json
{
  "pii_backend": "aws_macie"
}
```

When neither is set, the local regex scanner is used by default.

---

## File locations

```
fileguard/
└── core/
    └── adapters/
        ├── __init__.py          # GoogleDLPAdapter, AWSMacieAdapter exports
        ├── clamav_adapter.py    # ClamAV AV adapter
        ├── dlp_adapter.py       # GoogleDLPAdapter
        └── macie_adapter.py     # AWSMacieAdapter
fileguard/
└── tests/
    ├── test_dlp_adapter.py      # GoogleDLPAdapter unit tests
    └── test_macie_adapter.py    # AWSMacieAdapter unit tests
```
