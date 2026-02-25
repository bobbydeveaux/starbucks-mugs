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