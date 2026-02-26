# FileGuard QuarantineService Reference

Documentation for the AES-256-GCM quarantine service used by the FileGuard scan pipeline to isolate suspicious files with time-bound encrypted storage.

---

## Overview

`QuarantineService` provides encrypted file isolation backed by Redis (for automatic TTL-based expiry) and PostgreSQL (for durable metadata and audit history).

**Design goals:**

| Goal | Implementation |
|---|---|
| Confidentiality | AES-256-GCM (NIST SP 800-38D) — authenticated encryption so ciphertext is both confidential and integrity-protected |
| Key security | 256-bit key derived from `SECRET_KEY` via HKDF-SHA-256 (RFC 5869) with a fixed domain-separation `info` string |
| Automatic expiry | Redis `SETEX` guarantees blobs are evicted at TTL without operator intervention |
| Audit trail | `QuarantinedFile` PostgreSQL row survives Redis eviction, preserving compliance history |
| Tamper detection | AES-GCM authentication tag (128 bits) is verified on every retrieval; modified ciphertext raises `QuarantineError` |
| Observability | Prometheus counters (`fileguard_quarantine_operations_total`, `fileguard_quarantine_errors_total`) and a live gauge (`fileguard_quarantine_active_files`) |

---

## File

**`fileguard/services/quarantine.py`**

---

## Classes

### `QuarantineService`

```python
class QuarantineService:
    def __init__(
        self,
        secret_key: str | None = None,
        default_ttl_seconds: int | None = None,
        max_ttl_seconds: int | None = None,
        redis_key_prefix: str | None = None,
    ) -> None
```

All parameters default to the corresponding `settings.*` values.  In
production, a single shared instance should be wired to the FastAPI
application at startup.

#### Configuration

| Setting env var | Default | Description |
|---|---|---|
| `QUARANTINE_DEFAULT_TTL_SECONDS` | `86400` (24 h) | TTL when callers don't specify one |
| `QUARANTINE_MAX_TTL_SECONDS` | `2592000` (30 days) | Upper bound on caller-supplied TTLs |
| `QUARANTINE_REDIS_KEY_PREFIX` | `fileguard:quarantine` | Prefix for all Redis keys |

#### Methods

##### `quarantine_file`

```python
async def quarantine_file(
    self,
    *,
    session: AsyncSession,
    redis: Any,
    file_bytes: bytes,
    file_hash: str,
    file_name: str,
    file_size_bytes: int,
    mime_type: str,
    tenant_id: uuid.UUID,
    reason: str = "av_threat",   # "av_threat" | "pii" | "policy"
    scan_event_id: uuid.UUID | None = None,
    ttl_seconds: int | None = None,
) -> QuarantinedFile
```

Encrypts `file_bytes` with AES-256-GCM and stores the blob in Redis with
the specified TTL.  Inserts a `QuarantinedFile` metadata row into the
active SQLAlchemy session.  The caller must commit the session.

**Raises**

| Exception | Condition |
|---|---|
| `ValueError` | `reason` is not one of `"av_threat"`, `"pii"`, `"policy"` |
| `QuarantineError` | Encryption failed, Redis write failed, or DB flush failed |

When the DB flush fails the Redis key is deleted synchronously to keep
both stores in sync before the exception propagates.

##### `retrieve_file`

```python
async def retrieve_file(
    self,
    *,
    redis: Any,
    quarantine_id: uuid.UUID,
) -> bytes
```

Fetches the encrypted blob from Redis, verifies the GCM authentication tag,
and returns the original plaintext.

**Raises**

| Exception | Condition |
|---|---|
| `QuarantineNotFoundError` | Redis key absent (expired or never set) |
| `QuarantineError` | Decryption failure (tampering or key mismatch) |

##### `release_file`

```python
async def release_file(
    self,
    *,
    session: AsyncSession,
    redis: Any,
    quarantine_id: uuid.UUID,
) -> QuarantinedFile
```

Operator action (e.g. false-positive review).  Deletes the Redis key and
transitions the record status to `"released"`, recording `released_at`.

**Raises**

| Exception | Condition |
|---|---|
| `QuarantineNotFoundError` | Record not found in PostgreSQL |
| `QuarantineError` | Record is not in `"active"` state |

##### `purge_file`

```python
async def purge_file(
    self,
    *,
    session: AsyncSession,
    redis: Any,
    quarantine_id: uuid.UUID,
) -> None
```

Permanently removes the Redis blob and deletes the metadata row from
PostgreSQL.  Use for GDPR right-to-erasure requests or administrative
cleanup.

##### `mark_expired`

```python
async def mark_expired(
    self,
    *,
    session: AsyncSession,
    quarantine_id: uuid.UUID,
) -> QuarantinedFile
```

Called by a background worker scanning for records whose `expires_at` has
passed (Redis TTL elapsed).  Transitions status from `"active"` to
`"expired"` to keep the PostgreSQL record consistent with Redis reality.

---

### `QuarantineError`

Base exception raised by `QuarantineService` for unrecoverable errors.
Subclasses: `QuarantineNotFoundError`.

### `QuarantineNotFoundError`

Raised when the requested quarantine record or Redis blob cannot be found.

---

## ORM Model

**`fileguard/models/quarantined_file.py`**

```
quarantined_file
├── id             UUID       PK
├── tenant_id      UUID       FK → tenant_config.id  CASCADE
├── scan_event_id  UUID?      FK → scan_event.id     SET NULL
├── file_hash      TEXT       SHA-256 hex digest of original file
├── file_name      TEXT
├── file_size_bytes INTEGER
├── mime_type      TEXT
├── reason         ENUM       av_threat | pii | policy
├── status         ENUM       active | expired | released | deleted
├── ttl_seconds    INTEGER    TTL recorded at quarantine time
├── expires_at     TIMESTAMPTZ computed expiry (indexed for background sweep)
├── created_at     TIMESTAMPTZ server default now()
└── released_at    TIMESTAMPTZ? set when status = 'released'
```

A partial index on `(expires_at) WHERE status = 'active'` supports efficient
background sweeps for expired records.

---

## Redis Storage Layout

```
Key:   {QUARANTINE_REDIS_KEY_PREFIX}:{quarantine_id}
Value: <12-byte AES-GCM nonce> || <ciphertext + 16-byte GCM tag>
TTL:   ttl_seconds (set via SETEX)
```

The 12-byte nonce is randomly generated per file; it is prepended to the
ciphertext so retrieval can split them with a fixed offset.

---

## Encryption Details

| Property | Value |
|---|---|
| Algorithm | AES-256-GCM (NIST SP 800-38D) |
| Key length | 256 bits (32 bytes) |
| Key derivation | HKDF-SHA-256 (RFC 5869), `info = b"fileguard:quarantine:aes256gcm:v1"` |
| Nonce length | 96 bits (12 bytes), CSPRNG (`os.urandom`) |
| Authentication tag | 128 bits (appended by `cryptography.hazmat.primitives.ciphers.aead.AESGCM`) |
| Associated data | None |

The fixed `info` string provides domain separation so the same `SECRET_KEY`
can be used for multiple purposes (HMAC signing in `AuditService`, quarantine
encryption here) without key-reuse risk.

---

## Quarantine Lifecycle

```
                    quarantine_file()
                          │
                          ▼
                      [active]  ──── expires_at elapsed ──► [expired]
                          │                                 (mark_expired)
                   ┌──────┴──────┐
            release_file()    purge_file()
                   │               │
                   ▼               ▼
              [released]       (row deleted)
```

---

## Prometheus Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `fileguard_quarantine_operations_total` | Counter | `operation` | Total operations (`quarantine`, `retrieve`, `release`, `purge`, `expire`) |
| `fileguard_quarantine_errors_total` | Counter | `operation` | Total errors per operation type |
| `fileguard_quarantine_active_files` | Gauge | — | Approximate count of files currently in active quarantine |

---

## Database Migration

Migration `0002_add_quarantined_file.py` adds:

- Custom ENUM types `quarantine_status` and `quarantine_reason`
- Table `quarantined_file` with all columns and FK constraints
- Indexes: `tenant_id`, `scan_event_id`, `file_hash`, and a partial index on
  `expires_at WHERE status = 'active'` for the expiry sweep

---

## Usage Example

```python
from fileguard.services.quarantine import QuarantineService, QuarantineNotFoundError
from fileguard.db.session import AsyncSessionLocal

svc = QuarantineService()  # uses settings defaults

# Quarantine a suspicious file
async with AsyncSessionLocal() as session:
    async with session.begin():
        record = await svc.quarantine_file(
            session=session,
            redis=app.state.redis,
            file_bytes=raw_bytes,
            file_hash=sha256_hex,
            file_name="malware.exe",
            file_size_bytes=len(raw_bytes),
            mime_type="application/x-dosexec",
            tenant_id=tenant.id,
            reason="av_threat",
            scan_event_id=scan_event.id,
            ttl_seconds=86400,  # 24 h
        )

# Retrieve and decrypt (e.g. for analyst review)
try:
    plaintext = await svc.retrieve_file(
        redis=app.state.redis,
        quarantine_id=record.id,
    )
except QuarantineNotFoundError:
    # TTL expired or record was purged
    ...

# Release after false-positive review
async with AsyncSessionLocal() as session:
    async with session.begin():
        await svc.release_file(
            session=session,
            redis=app.state.redis,
            quarantine_id=record.id,
        )
```
