# Cloud PII Detection Adapters

FileGuard provides two cloud-native PII detection backends as configurable alternatives to (or augmentations of) the built-in UK regex pattern engine:

| Adapter | Backend Service | Package |
|---------|----------------|---------|
| `GoogleDLPAdapter` | Google Cloud Data Loss Prevention (DLP) API v2 | `google-cloud-dlp` |
| `AWSMacieAdapter` | Amazon Comprehend `detect_pii_entities` | `boto3` |

Both adapters implement the `CloudPIIAdapter` abstract interface and integrate with the FileGuard `ScanContext` pipeline.

---

## Architecture Overview

```
ScanContext
    │
    ├── PIIDetector (built-in UK regex patterns)
    │       └── appends PIIFinding objects to context.findings
    │
    ├── GoogleDLPAdapter (optional cloud backend)
    │       └── appends PIIFinding objects to context.findings
    │
    └── AWSMacieAdapter (optional cloud backend)
            └── appends PIIFinding objects to context.findings
```

Cloud adapters are **additive** — they append their findings to `context.findings` alongside the regex engine results. All three backends can run concurrently by calling each adapter's `scan()` method.

---

## `CloudPIIAdapter` Interface

All cloud PII backends implement the following abstract interface defined in
`fileguard/core/adapters/cloud_pii_adapter.py`:

```python
class CloudPIIAdapter(ABC):
    async def inspect(self, text: str) -> list[PIIFinding]: ...
    async def is_available(self) -> bool: ...
    def backend_name(self) -> str: ...
    async def scan(self, context: ScanContext) -> None: ...  # provided
```

### `inspect(text)`
Submits text to the cloud backend and returns a list of `PIIFinding` objects.
Raises `CloudPIIBackendError` on any API failure (fail-secure — never silently
returns empty results when the backend cannot be reached).

### `is_available()`
Lightweight connectivity and credential check.  Returns `True`/`False`,
never raises.

### `scan(context)`
Pipeline integration method.  Reads `context.extracted_text`, calls `inspect()`,
and appends findings to `context.findings`.  If the backend raises
`CloudPIIBackendError`, the error is recorded in `context.errors` and no
findings are added (fail-secure).

---

## Google DLP Adapter

### Overview

`GoogleDLPAdapter` calls the [Google Cloud DLP `projects.content.inspect`](https://cloud.google.com/dlp/docs/reference/rest/v2/projects.content/inspect)
endpoint to detect PII in extracted document text.

### Installation

```bash
pip install google-cloud-dlp
```

### Usage

```python
from fileguard.core.adapters.google_dlp_adapter import GoogleDLPAdapter

# Basic usage (Application Default Credentials)
adapter = GoogleDLPAdapter(project_id="my-gcp-project")

# Regional endpoint for GDPR data residency
adapter = GoogleDLPAdapter(
    project_id="my-gcp-project",
    location="europe-west2",
    info_types=["UK_NATIONAL_INSURANCE_NUMBER", "EMAIL_ADDRESS", "PHONE_NUMBER"],
    min_likelihood="LIKELY",
    timeout=30.0,
)

# Standalone inspection
findings = await adapter.inspect("Patient NI: AB123456C, email: alice@nhs.uk")

# Pipeline integration
await adapter.scan(context)  # appends findings to context.findings
```

### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_id` | `str` | required | GCP project ID for API billing |
| `location` | `str` | `"global"` | DLP processing location; use a regional location (e.g. `"europe-west2"`) for data-residency requirements |
| `info_types` | `list[str] \| None` | `None` | DLP infoType names to inspect for. Uses a default UK-focused set when `None` |
| `min_likelihood` | `str` | `"LIKELY"` | Minimum DLP confidence level: `VERY_UNLIKELY`, `UNLIKELY`, `POSSIBLE`, `LIKELY`, `VERY_LIKELY` |
| `timeout` | `float` | `30.0` | Seconds before API call times out |
| `credentials` | `object \| None` | `None` | Explicit GCP credentials; uses ADC when `None` |

### Default infoTypes

When `info_types` is `None`, the following DLP infoTypes are requested:

```python
[
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
```

### InfoType → FileGuard Category Mapping

| DLP infoType | FileGuard Category | Severity |
|---|---|---|
| `UK_NATIONAL_INSURANCE_NUMBER` | `NI_NUMBER` | high |
| `UK_NATIONAL_HEALTH_SERVICE_NUMBER` | `NHS_NUMBER` | high |
| `EMAIL_ADDRESS` | `EMAIL` | medium |
| `PHONE_NUMBER` | `PHONE` | medium |
| `UK_POSTAL_CODE` | `POSTCODE` | low |
| `PERSON_NAME` | `PERSON_NAME` | medium |
| `DATE_OF_BIRTH` | `DATE_OF_BIRTH` | high |
| `PASSPORT` | `PASSPORT` | high |
| `UK_DRIVERS_LICENSE_NUMBER` | `DRIVERS_LICENSE` | high |
| `CREDIT_CARD_NUMBER` | `CREDIT_CARD` | critical |
| `IBAN_CODE` | `IBAN` | high |
| `IP_ADDRESS` | `IP_ADDRESS` | low |
| *(unknown)* | `<info_type_name.lower()>` | derived from likelihood |

### Authentication

Uses [Application Default Credentials (ADC)](https://cloud.google.com/docs/authentication/application-default-credentials) by default.
For explicit service-account key injection:

```python
from google.oauth2 import service_account

credentials = service_account.Credentials.from_service_account_file(
    "service-account-key.json",
    scopes=["https://www.googleapis.com/auth/cloud-platform"],
)
adapter = GoogleDLPAdapter(project_id="my-project", credentials=credentials)
```

---

## AWS Macie Adapter

### Overview

`AWSMacieAdapter` uses [Amazon Comprehend's `detect_pii_entities`](https://docs.aws.amazon.com/comprehend/latest/dg/API_DetectPiiEntities.html)
API for real-time text PII inspection.

> **Note on AWS Macie vs. Amazon Comprehend:**
> AWS Macie is a data security service for discovering and protecting sensitive
> data *in S3 buckets* via classification jobs.  It does not provide a
> synchronous text inspection API.  Amazon Comprehend (`detect_pii_entities`)
> is the AWS service for per-request text PII detection and is the same ML
> engine underlying Macie's sensitive data discovery.  The `AWSMacieAdapter`
> uses Comprehend for FileGuard's real-time pipeline; Macie classification
> jobs are appropriate for the FileGuard batch S3 scanning workflow
> (`BatchJobProcessor`).

### Installation

`boto3` is already included in `requirements.txt`:

```bash
pip install boto3
```

### Usage

```python
from fileguard.core.adapters.aws_macie_adapter import AWSMacieAdapter

# Default credentials (IAM role / environment variables)
adapter = AWSMacieAdapter(region_name="eu-west-2")

# Explicit credentials
adapter = AWSMacieAdapter(
    region_name="eu-west-2",
    aws_access_key_id="AKIA...",
    aws_secret_access_key="secret...",
    aws_session_token="token...",  # optional, for assumed roles
    timeout=30.0,
)

# Standalone inspection
findings = await adapter.inspect("Name: John Smith, SSN: 123-45-6789")

# Pipeline integration
await adapter.scan(context)  # appends findings to context.findings
```

### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `region_name` | `str` | `"eu-west-2"` | AWS region for the Comprehend endpoint |
| `aws_access_key_id` | `str \| None` | `None` | Explicit AWS key ID; boto3 credential chain used when `None` |
| `aws_secret_access_key` | `str \| None` | `None` | Explicit AWS secret; boto3 credential chain used when `None` |
| `aws_session_token` | `str \| None` | `None` | Temporary session token for assumed roles |
| `timeout` | `float` | `30.0` | Seconds before API call times out |

### Comprehend Entity Type → FileGuard Category Mapping

| Comprehend Entity Type | FileGuard Category | Severity |
|---|---|---|
| `NAME` | `PERSON_NAME` | medium |
| `EMAIL` | `EMAIL` | medium |
| `PHONE` | `PHONE` | medium |
| `ADDRESS` | `ADDRESS` | medium |
| `SSN` | `SSN` | critical |
| `CREDIT_DEBIT_NUMBER` | `CREDIT_CARD` | critical |
| `CREDIT_DEBIT_CVV` | `CREDIT_CARD_CVV` | critical |
| `PIN` | `PIN` | critical |
| `PASSWORD` | `PASSWORD` | critical |
| `AWS_ACCESS_KEY` | `AWS_ACCESS_KEY` | critical |
| `AWS_SECRET_KEY` | `AWS_SECRET_KEY` | critical |
| `BANK_ACCOUNT_NUMBER` | `BANK_ACCOUNT` | high |
| `BANK_ROUTING` | `BANK_ROUTING` | high |
| `PASSPORT_NUMBER` | `PASSPORT` | high |
| `DRIVER_ID` | `DRIVERS_LICENSE` | high |
| `NATIONAL_ID` | `NATIONAL_ID` | high |
| `CREDIT_DEBIT_EXPIRY` | `CREDIT_CARD_EXPIRY` | high |
| `INTERNATIONAL_BANK_ACCOUNT_NUMBER` | `IBAN` | high |
| `DATE_TIME` | `DATE` | low |
| `AGE` | `AGE` | low |
| `URL` | `URL` | low |
| `IP_ADDRESS` | `IP_ADDRESS` | low |
| `MAC_ADDRESS` | `MAC_ADDRESS` | low |
| `USERNAME` | `USERNAME` | medium |
| `SWIFT_CODE` | `SWIFT_CODE` | medium |
| *(unknown)* | `<entity_type.lower()>` | medium |

### Text Chunking

Amazon Comprehend's `detect_pii_entities` accepts at most 100 KB of UTF-8
encoded text per request.  `AWSMacieAdapter` automatically splits larger texts
on whitespace boundaries and submits each chunk independently.  Findings from
all chunks are merged into a single result list with correct byte offsets
relative to the original full text.

### Authentication

Uses the [boto3 credential resolution chain](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html)
by default:

1. Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`)
2. AWS credentials file (`~/.aws/credentials`)
3. AWS config file (`~/.aws/config`)
4. IAM instance profile (EC2) or ECS task role
5. EKS Pod Identity / IRSA (Kubernetes)

For service-account-style explicit credentials, pass them to the constructor.

---

## Error Handling

Both adapters raise `CloudPIIBackendError` on failure:

```python
from fileguard.core.adapters.cloud_pii_adapter import CloudPIIBackendError

try:
    findings = await adapter.inspect(text)
except CloudPIIBackendError as exc:
    logger.error("Cloud PII inspection failed: %s", exc)
    # Apply fail-secure: treat as scan error, not clean result
```

When used via `scan(context)`, backend errors are automatically captured in
`context.errors` without raising.  Pipelines should treat non-empty
`context.errors` as a scan failure requiring fail-secure disposition.

---

## Deployment Considerations

### On-Prem / Air-Gapped Deployments

Cloud PII adapters make outbound HTTPS calls to Google or AWS APIs.  For
deployments where no external API calls are permitted (see `US-06`), disable
cloud adapters and rely solely on the built-in `PIIDetector` with UK regex
patterns.  Set adapter construction to `None` in the pipeline configuration.

### GDPR / Data Residency

- **Google DLP:** Use a regional `location` parameter (e.g. `"europe-west2"`)
  to ensure data does not leave the EU during inspection.
- **AWS Comprehend:** Use an EU region (e.g. `"eu-west-2"`) in the
  `region_name` parameter.

### IAM / Permissions

**Google DLP** — The service account or ADC principal requires the
`roles/dlp.user` role or the `dlp.content.inspect` permission on the project.

**AWS Comprehend** — The IAM role/user requires:
```json
{
  "Effect": "Allow",
  "Action": [
    "comprehend:DetectPiiEntities",
    "comprehend:ListPiiEntitiesDetectionJobs"
  ],
  "Resource": "*"
}
```

---

## Testing

Both adapters are fully tested with mocked cloud SDKs — no real GCP or AWS
credentials are required to run the unit test suite:

```bash
# Run cloud PII adapter tests
pytest tests/unit/test_google_dlp_adapter.py -v
pytest tests/unit/test_aws_macie_adapter.py -v
```
