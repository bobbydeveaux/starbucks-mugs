# ROAM Analysis: fileguard

**Feature Count:** 15
**Created:** 2026-02-25T20:45:28Z

## Risks

1. **5-Second SLA Breach on Complex Files** (High): The scan pipeline executes 5+ sequential steps (extract → AV → PII detect → redact → disposition → audit) for files up to 50MB. Heavy PDFs and DOCX files with embedded images are known to be slow in pdfminer.six; ClamAV streaming adds 1–3 seconds on large payloads. The 5-second p95 budget may not hold under worst-case combinations.

2. **ClamAV Daemon as Service-Wide Single Point of Failure** (High): All real-time and batch scans depend on the ClamAV daemon being reachable. Fail-secure semantics mean a crashed or unreachable daemon causes 100% of scans to return `rejected`. A DaemonSet restart, signature update reload, or memory exhaustion on any node will surface as a scanning outage for tenants on that node.

3. **Decompression Bomb and Malicious Archive Exploitation** (High): ZIP extraction is in scope and runs within worker containers. A crafted ZIP bomb (e.g., 42.zip) can exhaust tmpfs memory before the extractor terminates. Malformed PDFs can trigger parser crashes in pdfminer.six. The LLD notes tmpfs isolation but does not specify resource limits or archive depth caps.

4. **PII Regex Precision Below 95% Target** (Medium): UK NI numbers, NHS numbers, and postcodes have overlapping lexical patterns with non-PII content (reference codes, order numbers). Without validation against a representative corpus, the >95% precision target is unconfirmed. High false-positive rates would erode tenant trust and trigger excess `flagged` verdicts.

5. **Cloud DLP API Latency Breaking Synchronous SLA** (Medium): Google DLP and AWS Macie are called synchronously in the scan pipeline when configured. Round-trip latency to external APIs (50–500ms per call, with potential throttling) is additive to local processing time. A single DLP timeout can blow the 5-second budget for real-time scans.

6. **Audit Log Append-Only Enforcement is Application-Layer Only** (Medium): PostgreSQL does not natively prevent DELETE or UPDATE on `scan_event` rows. Any operator with direct DB access or a misconfigured migration can silently destroy tamper evidence. HMAC signatures detect after-the-fact tampering but do not prevent deletion.

7. **Batch Throughput Target Unvalidated Against Real S3/GCS Latency** (Medium): The 500 files/hour target is specified but has no published baseline measurement. S3/GCS object listing, download, scan, and manifest write overhead per file is not profiled. Files with slow extraction (large scanned PDFs) or DLP API calls could reduce actual throughput significantly below the target.

8. **OAuth 2.0 JWKS Endpoint Dependency on Tenant Infrastructure** (Low): Authentication for JWT-mode tenants requires a live JWKS endpoint at the tenant's identity provider. If that endpoint is unreachable (DNS failure, outage), all JWT-authenticated requests from that tenant fail. FileGuard has no fallback or cached key mechanism described.

---

## Obstacles

- **ClamAV Integration Testing Requires Running Daemon**: The `fileguard-feat-av-engine` feature cannot be meaningfully integration-tested without a live clamd process. CI pipelines that don't include a ClamAV sidecar container will have no coverage for AV scan paths, leaving the adapter untested until deployment.

- **Google DLP and AWS Macie Require Live Cloud Credentials**: The cloud DLP adapters (`fileguard/core/adapters/dlp_adapter.py`) cannot be validated in an on-prem or air-gapped development environment without active cloud accounts and credentials. This creates a gap between the on-prem deployment promise and the ability to test cloud PII backends, and delays integration testing of `fileguard-feat-pii-detector`.

- **pdfminer.six Cannot Extract Text from Scanned (Image-Only) PDFs**: pdfminer.six operates on embedded text streams; scanned PDFs contain only raster images. OCR is explicitly out of scope for v1. This means a non-trivial class of real-world PDFs will return empty extraction results, silently bypassing PII detection for image-based documents.

- **Commercial AV Engine Adapter Cannot Be End-to-End Tested Internally**: The `AVEngineAdapter` plugin interface for Sophos and CrowdStrike requires customer-supplied SDK implementations. No internal test path exists to validate the adapter contract, meaning bugs in the interface definition will only surface at customer integration time.

---

## Assumptions

1. **ClamAV Provides Sufficient Detection Coverage for v1 Customers**: The design assumes ClamAV's open-source signature database meets tenant AV requirements without commercial engine augmentation. *Validation approach*: Survey pilot customers for AV compliance requirements before launch; confirm whether any require NCSC-certified or enterprise-licensed engines.

2. **The 5-Second SLA Is Achievable Across All Supported File Types at 50MB**: The plan treats this as a hard requirement without profiling evidence. *Validation approach*: Run a pre-implementation benchmark using pdfminer.six + clamd against a 50MB PDF, DOCX, and ZIP corpus to establish a realistic baseline before committing the SLA.

3. **UK Regex Patterns Cover ≥95% of Tenant PII Detection Needs Without ML**: The architecture relies entirely on regex and cloud DLP — no semantic or ML-based classification. *Validation approach*: Build and run the pattern test harness against labelled sample documents (including obfuscated PII formats) before shipping `fileguard-feat-pii-detector`.

4. **PostgreSQL Write Throughput Is Adequate at Peak Scan Volume**: Every scan writes an audit event; at 500 files/hour batch throughput plus concurrent real-time scans, write contention on `scan_event` is a risk. *Validation approach*: Load-test audit writes at 2× expected peak before launch; add write buffer or async audit flush if contention is observed.

5. **Redis Availability Can Be Treated as Infrastructure-Guaranteed**: Both rate limiting and Celery task brokering depend on Redis. The design has no Redis failover or degraded-mode behaviour defined. *Validation approach*: Define and test Redis-down behaviour explicitly — does the API gate all requests or degrade rate-limiting only?

---

## Mitigations

### Risk 1 — 5-Second SLA Breach on Complex Files

- **Benchmark before committing**: Profile pdfminer.six extraction and ClamAV streaming against representative 10MB, 30MB, and 50MB PDF/DOCX files before implementation begins. Set per-step time budgets (e.g., extraction ≤1.5s, AV ≤2s, PII ≤1s).
- **Enforce per-step timeouts in `ScanPipeline`**: Wrap each pipeline step in an `asyncio.wait_for` or thread-pool timeout. If extraction exceeds budget, emit a `partial_extraction` warning and proceed with available text rather than blocking the entire scan.
- **Stream AV scan concurrently with extraction**: Begin ClamAV streaming of raw bytes while document extraction runs in the thread pool. Overlap reduces total wall time by 1–2 seconds on large files.
- **Cap synchronous scan at 50MB with enforcement**: Reject files above 50MB at the handler layer before pipeline entry; redirect to signed URL flow. Add a fast MIME type check before invoking the full extractor.
- **Add p95 latency alerting at 3s** (not 4s as currently specified): Earlier warning provides a reaction window before the SLA is breached in production.

### Risk 2 — ClamAV Daemon as Service-Wide SPOF

- **Add ClamAV health probe to worker startup**: Workers should refuse to accept Celery tasks if the clamd socket is unreachable at startup, rather than failing mid-scan. Surface this via a `/healthz` liveness probe so Kubernetes restarts the pod and routes tasks elsewhere.
- **Deploy ClamAV as a DaemonSet with PodDisruptionBudget**: Ensure at least one ClamAV pod is available on each node during rolling updates. Set `maxUnavailable: 0` during signature update restarts.
- **Implement circuit breaker in `ClamAVAdapter`**: After N consecutive connection failures, open the circuit and emit a `CLAMAV_UNAVAILABLE` metric. Alert ops within 60 seconds of circuit opening.
- **Consider a secondary in-process ClamAV scan via `python-clamav` as fallback**: For deployments with strict availability requirements, bundle a lightweight ClamAV library scan as a degraded fallback when the daemon is unreachable, scanning only the first 1MB as a heuristic.

### Risk 3 — Decompression Bomb and Malicious Archive Exploitation

- **Enforce archive extraction limits in `DocumentExtractor`**: Set a maximum uncompressed size cap (e.g., 200MB), maximum file count per archive (e.g., 1000 files), and maximum recursion depth (e.g., 2 levels). Abort extraction and return a `MALFORMED_ARCHIVE` finding if any limit is exceeded.
- **Set tmpfs size limits per worker container**: Kubernetes container resource spec should cap the tmpfs mount at 200MB. This bounds the blast radius of a zip bomb to the container's tmpfs rather than the node.
- **Wrap pdfminer.six extraction in a subprocess with memory limit**: Use `resource.setrlimit(RLIMIT_AS, ...)` or a subprocess with `ulimit` to cap memory usage of the PDF parser. A crash in the subprocess returns `EXTRACTION_FAILED` without killing the worker.
- **Add EICAR-equivalent test cases for archive bombs to the test suite**: Include `42.zip` and a deeply nested ZIP in the integration test corpus to validate limits are enforced before deployment.

### Risk 4 — PII Regex Precision Below 95% Target

- **Build and run the QA test harness before `fileguard-feat-pii-detector` is marked complete**: The success metric requires >95% precision on a UK pattern test suite. This suite must be built and executed as part of the feature acceptance, not deferred to post-launch.
- **Add anchoring and negative lookahead to UK patterns**: NI numbers match the format `AB123456C`; patterns should include word boundary anchors and exclude common false-positive prefixes (e.g., product codes). Review each pattern in `uk_patterns.py` against a labelled false-positive corpus.
- **Implement per-category confidence threshold**: Allow tenants to configure minimum match confidence per PII category. Lower-confidence matches produce `flagged` verdicts rather than `rejected`, reducing operational impact of false positives.
- **Log false positive rate per category in production**: Add a Prometheus counter `fileguard_pii_false_positive_total{category}` seeded from tenant feedback via a dispute endpoint. Use this to iterate on patterns post-launch.

### Risk 5 — Cloud DLP API Latency Breaking Synchronous SLA

- **Make cloud DLP opt-in and async for real-time scans**: In synchronous scan mode, run local regex detection first and return the verdict. Dispatch cloud DLP as a background Celery task and update findings via a follow-up webhook if additional PII is detected. This decouples cloud API latency from the 5-second SLA.
- **Set a hard timeout on DLP API calls (1.5 seconds)**: If Google DLP or AWS Macie does not respond within the budget, log a `DLP_TIMEOUT` warning, use local regex results only, and flag the scan as `partial_scan`. Never block the verdict on an external API timeout.
- **Cache DLP results by content hash**: For batch jobs that repeatedly encounter near-identical file content (e.g., template documents), a Redis cache on content hash avoids redundant DLP API calls and reduces both latency and API cost.

### Risk 6 — Audit Log Append-Only Enforcement is Application-Layer Only

- **Add PostgreSQL row-level security (RLS) policy**: Create a dedicated `fileguard_writer` DB role that has INSERT-only access to `scan_event`. The application connection pool uses this role. Direct UPDATE/DELETE requires a separate privileged role that is not available to the application.
- **Implement periodic HMAC chain verification job**: Schedule a Celery beat task that re-computes and validates HMAC signatures for all `scan_event` rows in the previous 24-hour window. Alert on any signature mismatch via PagerDuty or equivalent.
- **Export audit events to SIEM in real time**: Since Splunk HEC and WatchTower receive events asynchronously, the SIEM copy serves as an independent tamper-evident record. Cross-reference SIEM event count against PostgreSQL row count in the compliance report generator.

### Risk 7 — Batch Throughput Target Unvalidated Against Real S3/GCS Latency

- **Run a load test as part of `fileguard-feat-batch-processor` acceptance**: Before the feature is signed off, run a test job against a bucket containing 1000 files of representative size and measure actual files/hour. Gate acceptance on meeting the 500 files/hour target.
- **Instrument per-file processing time in the batch worker**: Emit `fileguard_batch_file_duration_seconds` histogram broken down by file type and size. Use this to identify extraction or scan bottlenecks specific to batch workloads.
- **Increase partition granularity for large buckets**: The current design partitions by prefix range (A-F, G-M, N-Z). For buckets with millions of objects, add a second partitioning level (timestamp prefix or hash prefix) to increase parallelism beyond 3 workers.

### Risk 8 — OAuth 2.0 JWKS Endpoint Dependency on Tenant Infrastructure

- **Implement JWKS key caching with configurable TTL**: Cache the JWKS response in Redis with a 5-minute TTL. Serve cached keys if the JWKS endpoint returns a 5xx or times out. This tolerates brief JWKS outages without blocking tenant access.
- **Add a JWKS endpoint health check to tenant onboarding**: Validate that the configured JWKS URL is reachable and returns a valid key set during tenant configuration, not at first request.
- **Document fallback to API key auth**: Recommend that tenants configure both an API key and OAuth 2.0. If JWKS is unavailable, tenants can fall back to API key authentication without service interruption.

---

## Appendix: Plan Documents

### PRD
# Product Requirements Document: Fileguard

RiverSafe FileGuard is a security-focused file processing gateway that inspects, sanitises, and redacts uploaded files before they are accepted into critical systems. It offers real-time and batch scanning capabilities, making it ideal for organisations that manage sensitive data, customer uploads, or large cloud storage buckets.

By integrating anti-virus scanning, PII detection, and automated redaction, FileGuard acts as a protective buffer between untrusted files and internal infrastructure.

**Created:** 2026-02-25T20:33:25Z
**Status:** Draft

---

## 1. Overview

**Concept:** Fileguard — a security-focused file processing gateway providing antivirus scanning, PII detection, and automated redaction for uploaded files before ingestion into critical systems.

**Description:** FileGuard sits between untrusted file uploads and internal infrastructure, offering real-time and batch processing modes with configurable quarantine, redaction, and SIEM-forwarded audit logging.

---

## 2. Goals

- **G-01:** Provide real-time file scanning (antivirus + PII detection) with sub-5-second response for files up to 50MB via REST API.
- **G-02:** Support batch processing of cloud storage buckets (S3/GCS) with scheduled scan jobs and structured result reporting.
- **G-03:** Detect and optionally redact UK/global PII patterns (NI, NHS, email, phone, address) across PDF, DOCX, TXT, CSV, JSON, ZIP formats.
- **G-04:** Produce tamper-evident audit logs forwarded to SIEM integrations (Splunk, WatchTower) for compliance reporting.
- **G-05:** Enable deployment in SaaS, Docker on-prem, and serverless (AWS Lambda/GCP Cloud Functions) configurations.

---

## 3. Non-Goals

- **NG-01:** FileGuard does not provide a consumer-facing UI for end users to upload files directly; it is a developer/API-first product.
- **NG-02:** FileGuard does not store or archive original files; it processes in transit and discards.
- **NG-03:** FileGuard does not replace a full DLP platform; PII redaction covers defined patterns only, not ML-based content classification.
- **NG-04:** FileGuard does not manage access control or authentication for downstream systems it protects.
- **NG-05:** Language SDKs (Python, Node.js, Java) are out of scope for v1 beyond API documentation.

---

## 4. User Stories

- **US-01:** As a developer, I want to POST a file to the FileGuard API and receive a clean/flagged/rejected verdict so that I can gate downstream ingestion.
- **US-02:** As a security engineer, I want to configure quarantine vs. block behaviour per file type so that policy matches organisational risk tolerance.
- **US-03:** As a compliance officer, I want weekly PDF/JSON reports of all scan outcomes so that I can demonstrate GDPR and HIPAA adherence.
- **US-04:** As a DevOps engineer, I want to connect FileGuard to an S3 bucket and schedule batch scans so that legacy uploads are retroactively checked.
- **US-05:** As a developer, I want webhook callbacks on scan completion so that my application can react asynchronously without polling.
- **US-06:** As a system administrator, I want to deploy FileGuard as a Docker container on-prem so that files never leave our network boundary.
- **US-07:** As a security analyst, I want scan results forwarded to Splunk so that FileGuard events appear in our existing SIEM dashboards.
- **US-08:** As a developer, I want to define custom regex PII patterns so that organisation-specific identifiers are detected beyond built-in patterns.

---

## 5. Acceptance Criteria

**US-01 — Real-time scan API:**
- Given a valid authenticated POST to `/v1/scan` with a supported file type, when the file is under 50MB, then the response returns within 5 seconds with `status: clean | flagged | rejected` and a findings array.

**US-03 — Compliance reports:**
- Given scan activity exists for a reporting period, when the scheduled report job runs, then a PDF and JSON report is generated containing file count, verdict breakdown, and PII hit counts, and is available via API download endpoint.

**US-04 — Batch S3 scan:**
- Given a configured S3 bucket connection and cron schedule, when the job executes, then all new files since last run are scanned and a structured result manifest is written back to the bucket.

**US-06 — On-prem Docker deployment:**
- Given a Docker Compose configuration, when deployed with ClamAV and custom pattern config, then FileGuard processes files entirely within the local network with no external API calls required.

**US-08 — Custom PII patterns:**
- Given a JSON pattern config with regex definitions, when FileGuard loads on startup, then custom patterns are applied alongside built-in patterns in all scan operations.

---

## 6. Functional Requirements

- **FR-001:** Real-time scan endpoint `POST /v1/scan` accepting multipart file upload; returns verdict JSON within SLA.
- **FR-002:** Signed URL upload flow for large files (50MB–500MB) via `POST /v1/scan/signed-url`.
- **FR-003:** ClamAV integration for signature-based and heuristic antivirus scanning (default engine).
- **FR-004:** Optional commercial AV engine plugin interface (Sophos, CrowdStrike) via configurable adapter.
- **FR-005:** PII detection across PDF, DOCX, TXT, CSV, JSON, ZIP using built-in UK pattern library (NI, NHS, email, phone, postcode).
- **FR-006:** Google DLP and AWS Macie integration as cloud-native PII detection backends (configurable).
- **FR-007:** Custom regex pattern sets loaded from JSON config file at startup.
- **FR-008:** PII redaction mode: replace detected PII with `[REDACTED]` tokens before returning/forwarding file.
- **FR-009:** Configurable file disposition: `block`, `quarantine`, or `pass-with-flags` per rule set.
- **FR-010:** Batch job processor connecting to S3/GCS buckets, configurable via cron schedule.
- **FR-011:** CLI tool for manual batch submission and status querying.
- **FR-012:** Webhook callback `POST` to configured URL on scan completion with full result payload.
- **FR-013:** Structured audit log per scan event (file hash, timestamp, verdict, findings, action taken).
- **FR-014:** SIEM forwarding to Splunk (HTTP Event Collector) and RiverSafe WatchTower.
- **FR-015:** Scheduled compliance report generation (PDF + JSON) with configurable daily/weekly cadence.

---

## 7. Non-Functional Requirements

### Performance
- Real-time scan: p95 response under 5 seconds for files up to 50MB.
- Batch processing: minimum 500 files/hour sustained throughput per instance.
- Signed URL uploads must complete within 60 seconds for files up to 500MB.

### Security
- All API endpoints require bearer token authentication (API key or OAuth 2.0 client credentials).
- Files processed in isolated sandboxed containers; no file persistence post-scan.
- All data in transit encrypted via TLS 1.2+; at-rest encryption for quarantine store (AES-256).
- Audit logs are append-only and tamper-evident (HMAC-signed entries).

### Scalability
- Horizontal scaling via stateless scan worker pods (Kubernetes-compatible).
- Batch processor supports partitioned parallel execution across bucket prefixes.
- API gateway rate limiting: configurable per tenant (default 100 req/min).

### Reliability
- API availability SLA: 99.9% uptime for hosted SaaS tier.
- Scan worker failures must not result in silent pass-through; fail-secure default rejects the file.
- Dead-letter queue for failed batch jobs with automatic retry (3 attempts, exponential backoff).

---

## 8. Dependencies

| Dependency | Type | Purpose |
|---|---|---|
| ClamAV | Open-source library | Default AV scanning engine |
| Google DLP API | External API | Cloud-native PII detection |
| AWS Macie | External API | Cloud-native PII detection (alternative) |
| Apache PDFBox / python-docx | Libraries | Document text extraction |
| Splunk HEC | External API | SIEM log forwarding |
| AWS S3 / GCP GCS SDK | Cloud SDK | Batch bucket integration |
| Docker / Kubernetes | Infrastructure | Containerised deployment |
| PostgreSQL | Database | Audit log persistence and report data |

---

## 9. Out of Scope

- Consumer-facing file upload UI or admin dashboard (v1 is API-only).
- ML-based content classification beyond regex/DLP pattern matching.
- File storage, archival, or content management capabilities.
- Native integrations with Sophos or CrowdStrike AV engines (plugin interface provided; integration is customer responsibility).
- Language SDKs; API documentation and OpenAPI spec are in scope, SDK libraries are not.
- Real-time antivirus signature update management (deferred to ClamAV daemon's built-in freshclam).

---

## 10. Success Metrics

| Metric | Target | Measurement |
|---|---|---|
| Real-time scan p95 latency | < 5 seconds (≤50MB files) | API gateway telemetry |
| PII detection accuracy | > 95% precision on UK pattern test suite | QA test harness |
| Batch throughput | ≥ 500 files/hour per worker | Load test results |
| SIEM event delivery rate | > 99.5% of scan events forwarded | Log reconciliation |
| API uptime (SaaS) | ≥ 99.9% monthly | Synthetic monitoring |
| False positive rate (AV) | < 0.1% on clean file corpus | Weekly regression test |

---

## Appendix: Clarification Q&A

No clarification questions were raised prior to PRD creation. Requirements derived from concept specification.

### HLD
# High-Level Design: starbucks-mugs

**Created:** 2026-02-25T20:35:12Z
**Status:** Draft

## 1. Architecture Overview

FileGuard is a **modular monolith** deployed as stateless containerised workers behind an API gateway, with plugin-based scan engine adapters. Three operational modes share a common scan pipeline core:

1. **Synchronous REST API** — real-time scan for files ≤50MB; returns verdict within SLA
2. **Async Batch Processor** — cron-driven cloud bucket (S3/GCS) scanner with queue-backed parallel workers
3. **CLI Tool** — thin wrapper over the REST API for manual submission and status queries

A message queue decouples batch job submission from execution. An independent audit service handles tamper-evident log writing and SIEM forwarding, isolated from the scan critical path.

```
Clients ──► API Gateway (auth, rate-limit) ──► Scan API Service
                                                     │
                                        ┌────────────┴────────────┐
                                        ▼                         ▼
                                  Scan Worker Pool          Batch Job Processor
                                  (AV + PII pipeline)       (S3/GCS connector)
                                        │                         │
                                   Audit Service ◄───────────────┘
                                        │
                              SIEM (Splunk / WatchTower)
```

---

## 2. System Components

| Component | Responsibility |
|---|---|
| **API Gateway** | TLS termination, bearer token auth, per-tenant rate limiting, request routing |
| **Scan API Service** | `POST /v1/scan` and signed-URL endpoints; orchestrates worker pipeline; dispatches webhooks |
| **Scan Worker Pool** | Stateless pods executing AV scan → document extraction → PII detection → disposition |
| **AV Engine Adapter** | ClamAV daemon (default) + plugin interface for commercial engines (Sophos, CrowdStrike) |
| **Document Extractor** | Text extraction from PDF (PDFBox), DOCX (python-docx), CSV, JSON, ZIP |
| **PII Detection Engine** | Built-in UK regex patterns (NI, NHS, email, phone, postcode) + cloud DLP adapter (Google DLP / AWS Macie) |
| **Redaction Engine** | Replaces matched PII spans with `[REDACTED]` tokens in extracted content and reconstructed file |
| **Batch Job Processor** | Cron-scheduled connector to S3/GCS; partitions prefix ranges across parallel workers; writes result manifest to bucket |
| **Audit Service** | Appends HMAC-SHA256-signed scan events to PostgreSQL; forwards to SIEM asynchronously |
| **Report Generator** | Scheduled job producing PDF and JSON compliance reports from aggregated scan data |
| **Quarantine Store** | AES-256-encrypted object store (S3 bucket or local volume) for quarantined files; TTL-based auto-expiry |
| **Webhook Dispatcher** | Async delivery of scan result payloads to tenant-configured callback URLs with retry logic |
| **CLI Tool** | Python CLI wrapping the REST API for batch submission and status polling |

---

## 3. Data Model

**ScanEvent** (primary audit record)
```
id              UUID PK
tenant_id       UUID FK
file_hash       SHA-256 hex
file_name       TEXT
file_size_bytes BIGINT
mime_type       TEXT
status          ENUM(clean, flagged, rejected)
action_taken    ENUM(pass, quarantine, block)
findings        JSONB          -- array of Finding objects
scan_duration_ms INT
created_at      TIMESTAMPTZ
hmac_signature  TEXT           -- HMAC-SHA256 over canonical fields
```

**Finding** (embedded in ScanEvent.findings JSONB)
```
type        ENUM(av_threat, pii)
category    TEXT               -- e.g. "NHS_NUMBER", "EICAR", "EMAIL"
severity    ENUM(low, medium, high, critical)
offset      INT                -- byte offset in extracted text
match       TEXT               -- redacted in stored form if PII
```

**TenantConfig**
```
id               UUID PK
api_key_hash     TEXT
disposition_rules JSONB         -- per file-type: block|quarantine|pass-with-flags
custom_patterns  JSONB          -- user-defined regex definitions
webhook_url      TEXT
siem_config      JSONB          -- type, endpoint, credentials ref
rate_limit_rpm   INT
```

**BatchJob**
```
id                UUID PK
tenant_id         UUID FK
bucket_type       ENUM(s3, gcs)
bucket_name       TEXT
prefix_filter     TEXT
cron_schedule     TEXT
last_run_at       TIMESTAMPTZ
status            ENUM(idle, running, completed, failed)
result_manifest_uri TEXT
```

**ComplianceReport**
```
id           UUID PK
tenant_id    UUID FK
period_start TIMESTAMPTZ
period_end   TIMESTAMPTZ
format       ENUM(pdf, json)
file_uri     TEXT
generated_at TIMESTAMPTZ
```

---

## 4. API Contracts

**Real-time scan**
```
POST /v1/scan
Content-Type: multipart/form-data
Authorization: Bearer <token>

Body: file (binary), options (JSON): { redact: bool, disposition_override: string }

Response 200:
{
  "scan_id": "uuid",
  "status": "clean|flagged|rejected",
  "action": "pass|quarantine|block",
  "findings": [ { "type": "pii", "category": "NI_NUMBER", "severity": "high" } ],
  "file_hash": "sha256hex",
  "scan_duration_ms": 1240,
  "redacted_file_url": "signed-url | null"
}
```

**Signed URL upload (large files)**
```
POST /v1/scan/signed-url
Body: { "filename": "report.pdf", "size_bytes": 104857600 }
Response: { "upload_url": "...", "scan_id": "uuid", "expires_in": 300 }
```

**Batch job management**
```
POST   /v1/batch/jobs           -- create job with bucket config + cron
GET    /v1/batch/jobs/{id}      -- status + last run result
DELETE /v1/batch/jobs/{id}      -- remove job
```

**Compliance reports**
```
GET /v1/reports?period=2026-01&format=pdf   -- list reports
GET /v1/reports/{id}/download               -- stream report file
```

**Scan result retrieval**
```
GET /v1/scan/{id}    -- retrieve stored scan event
```

---

## 5. Technology Stack

### Backend
- **Python 3.12 + FastAPI** — async I/O for concurrent scan handling; rich ecosystem for document parsing, regex, and cloud SDKs
- **Celery + Redis** — distributed task queue for batch job execution and webhook dispatch
- **python-docx, pdfminer.six** — document text extraction
- **clamd (Python)** — ClamAV daemon socket client

### Frontend
None. FileGuard is API-only (v1). OpenAPI spec served at `/v1/openapi.json`; Swagger UI available at `/v1/docs` for developer reference.

### Infrastructure
- **Docker** — containerised packaging for all components
- **Kubernetes** — production orchestration with HPA for scan worker pods
- **Docker Compose** — on-prem single-node deployment
- **AWS Lambda / GCP Cloud Functions** — serverless deployment variant (scan handler only)
- **Helm** — Kubernetes packaging and configuration management

### Data Storage
- **PostgreSQL 16** — audit log persistence, tenant config, report metadata
- **Redis 7** — Celery broker, rate-limit counters, job state cache
- **S3 / GCS** — quarantine store (AES-256 SSE), batch result manifests, compliance report files

---

## 6. Integration Points

| Integration | Protocol | Direction | Purpose |
|---|---|---|---|
| ClamAV daemon | TCP socket (clamd) | Outbound | AV signature scanning |
| Google DLP API | HTTPS REST | Outbound | Cloud-native PII detection |
| AWS Macie | HTTPS REST | Outbound | Cloud-native PII detection (alt) |
| AWS S3 SDK | HTTPS | Bidirectional | Batch bucket scan + quarantine store |
| GCP GCS SDK | HTTPS | Bidirectional | Batch bucket scan (alt) |
| Splunk HEC | HTTPS POST | Outbound | SIEM audit event forwarding |
| RiverSafe WatchTower | HTTPS REST | Outbound | SIEM audit event forwarding |
| Customer webhook URLs | HTTPS POST | Outbound | Async scan result callbacks |

All outbound integrations are optional/configurable per deployment profile. On-prem deployments can disable all cloud integrations.

---

## 7. Security Architecture

**Authentication:** All API endpoints require `Authorization: Bearer <token>`. Two modes:
- API key (hashed with bcrypt, stored in TenantConfig)
- OAuth 2.0 client credentials flow (JWT validated against configured JWKS endpoint)

**File processing isolation:** Files are written to ephemeral `tmpfs` mounts within worker containers. Containers run as non-root with read-only root filesystem. Files are zeroed and deleted immediately post-scan; no persistence unless explicitly quarantined.

**Encryption:**
- TLS 1.2+ on all API and integration endpoints
- Quarantine store: AES-256 SSE (S3 SSE-S3 or customer-managed KMS key)
- Secrets (API keys, cloud credentials): Kubernetes Secrets / environment variables; never logged

**Audit log integrity:** Each ScanEvent record includes an HMAC-SHA256 signature computed over `(id, file_hash, status, action_taken, created_at)` using a server-side signing key. Signature chain enables tamper detection during compliance export.

**Rate limiting:** Redis-backed sliding window counter per `tenant_id`; default 100 req/min; configurable per tenant.

**Fail-secure:** Worker crashes or timeout result in `rejected` verdict, not silent pass-through.

---

## 8. Deployment Architecture

**SaaS (Kubernetes)**
```
Ingress (TLS) → Scan API Deployment (2+ replicas)
                     ↓ Celery tasks
              Worker Deployment (HPA: 2–20 pods, CPU trigger)
              ClamAV DaemonSet (one per node)
              Audit Service Deployment
              PostgreSQL (managed RDS / Cloud SQL)
              Redis (managed ElastiCache / Memorystore)
```

**On-Prem (Docker Compose)**
```
Services: fileguard-api, fileguard-worker, clamav, postgres, redis
Volumes: tmpfs for scan temp, named volume for quarantine (encrypted at host level)
Network: bridge network; no external egress required
Config: mounted JSON config file for patterns and disposition rules
```

**Serverless (AWS Lambda)**
- Scan handler deployed as Lambda function (container image)
- ClamAV layer bundled in image (signature DB fetched at cold start from S3)
- PostgreSQL via RDS Proxy; Redis via ElastiCache (VPC-bound)
- Batch processor as EventBridge-triggered Lambda; not recommended for sustained high-throughput batch

---

## 9. Scalability Strategy

- **Stateless scan workers** scale horizontally via K8s HPA; target metric: CPU utilisation >60% or Celery queue depth >50 tasks
- **Batch partitioning:** large bucket jobs split by prefix (A-F, G-M, N-Z…) and executed as parallel Celery tasks; each partition independently retried
- **ClamAV shared per node** (DaemonSet) avoids redundant signature DB loading; workers connect via Unix socket
- **Read replicas** for PostgreSQL report queries to avoid contention with audit writes
- **Rate limiting** at API gateway layer (Redis) prevents single tenant from monopolising worker pool
- **Dead-letter queue (DLQ):** failed batch tasks moved to DLQ after 3 attempts (exponential backoff: 30s, 2m, 10m); DLQ alerts ops team

---

## 10. Monitoring & Observability

**Structured logging:** JSON logs with `correlation_id`, `tenant_id`, `scan_id`, `duration_ms` on every request. Log level configurable per environment.

**Metrics (Prometheus + Grafana):**
- `fileguard_scan_duration_seconds` histogram (p50, p95, p99 per file type)
- `fileguard_scan_total` counter by `status` label
- `fileguard_batch_files_per_hour` gauge
- `fileguard_siem_delivery_errors_total` counter
- Celery queue depth via `celery-exporter`

**Distributed tracing:** OpenTelemetry SDK with OTLP export (Jaeger / Tempo); trace spans for: API receive → AV scan → PII detection → disposition → audit write → webhook dispatch

**Alerting rules:**
- Scan p95 latency > 4s (warn) / > 6s (critical)
- Worker error rate > 1% over 5 minutes
- SIEM delivery failure rate > 0.5%
- Celery DLQ depth > 10
- ClamAV daemon unreachable (any worker)

---

## 11. Architectural Decisions (ADRs)

**ADR-01: Python + FastAPI over Go or Java**
Python chosen for document processing ecosystem maturity (pdfminer, python-docx, boto3, google-cloud-dlp). FastAPI provides async I/O sufficient for concurrent scan orchestration. Go would require FFI wrappers or port of document libraries; Java adds JVM overhead per container.

**ADR-02: Modular monolith over microservices**
Scan pipeline steps (extract → AV → PII → redact → audit) are tightly coupled by data flow. Splitting into independent services adds inter-service latency that conflicts with the 5-second SLA. Workers remain independently scalable as Kubernetes Deployments without requiring full service mesh overhead.

**ADR-03: Celery + Redis for async tasks**
Batch processing and webhook dispatch require durable async queuing. Celery with Redis broker provides DLQ, retry policies, and task routing out of the box. Avoids operational complexity of a managed message queue (SQS/Pub-Sub) for on-prem deployments where Redis already satisfies rate-limiting requirements.

**ADR-04: ClamAV as default AV engine; plugin interface for commercial**
ClamAV is self-hostable, meeting the on-prem no-external-calls requirement (US-06). Commercial engine adapters (Sophos, CrowdStrike) are defined as an abstract `AVEngineAdapter` interface; customer-provided implementations loaded via configurable class path. This avoids bundling commercial SDK licensing into the core product.

**ADR-05: PostgreSQL for audit log with HMAC signatures**
Relational model supports the complex aggregation queries required for compliance reports (verdict breakdown, PII hit counts by category). HMAC-SHA256 signatures on individual rows provide tamper evidence without requiring a specialised append-only store or blockchain. Append-only enforced at application layer (no UPDATE/DELETE on ScanEvent).

**ADR-06: Fail-secure by default**
Any unhandled exception in the scan worker pipeline results in `status: rejected`, `action: block`. This ensures a compromised or crashed worker cannot become a pass-through vulnerability. Operators can inspect DLQ and manually release files after investigation.

---

## Appendix: PRD Reference

[PRD content as above]

### LLD
The LLD has been written to `docs/concepts/fileguard/LLD.md`. Here is a summary of what each section covers:

**Section 1 — Implementation Overview:** Modular monolith in Python 3.12/FastAPI; `ScanContext` shared across composable pipeline steps; Celery for batch/webhooks; HMAC-signed PostgreSQL audit log; fail-secure by default.

**Section 2 — File Structure:** Full `fileguard/` directory tree covering API handlers, core pipeline modules, Celery workers, services (audit, SIEM, quarantine, reports), batch connectors, ORM models, Pydantic schemas, Alembic migrations, tests, Docker/Helm, and CLI.

**Section 3 — Component Designs:** Nine components with class layouts and inline pseudocode: `ScanPipeline`, `ScanContext`, `ClamAVAdapter`, `DocumentExtractor`, `PIIDetector`, `DispositionEngine`, `AuditService`, `BatchJobProcessor`, and `WebhookDispatcher`.

**Section 4 — Database Schema:** Full SQL for all four tables (`tenant_config`, `scan_event`, `batch_job`, `compliance_report`) with constraints, indexes, and append-only enforcement note.

**Section 5 — API Implementation:** Handler logic, validation rules, processing steps, and error codes for all five key endpoints.

**Section 6 — Function Signatures:** All public method signatures across every module with type annotations.

**Sections 7–12:** State management (stateless app + three external stores), error handling strategy (fail-secure + error code table), unit/integration/E2E test plans, green-field migration steps, rollback procedures per failure scenario, and performance optimisations (tmpfs, regex pre-compilation, thread pool for CPU-bound extraction, prefix partitioning, DB indexing).