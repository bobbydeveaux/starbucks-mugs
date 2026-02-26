"""QuarantineService — AES-256-GCM encryption with Redis-backed TTL.

Quarantining isolates a suspicious file so that it cannot be accessed via
normal channels while under investigation.  This service handles:

* **Encryption** — AES-256-GCM (authenticated encryption) using a key derived
  from ``settings.SECRET_KEY`` via HKDF-SHA-256.  Each file gets a
  cryptographically-random 96-bit nonce; the GCM authentication tag (128 bits)
  is appended to the ciphertext so tampering is detectable on retrieval.

* **TTL management** — Encrypted blobs are stored in Redis with an automatic
  ``EXPIRE`` so the payload is evicted without operator intervention.  TTL is
  also persisted to PostgreSQL as ``expires_at`` for range-query compliance
  reporting.

* **Lifecycle tracking** — A ``QuarantinedFile`` row tracks the quarantine
  state (``active`` → ``released`` / ``expired`` / ``deleted``) so the audit
  trail survives Redis eviction.

Storage layout
--------------
Redis key  ``{QUARANTINE_REDIS_KEY_PREFIX}:{quarantine_id}`` → encrypted blob
Blob format ``<12-byte nonce> || <ciphertext+GCM-tag>``

Usage::

    from fileguard.services.quarantine import QuarantineService

    svc = QuarantineService()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            record = await svc.quarantine_file(
                session=session,
                redis=app.state.redis,
                file_bytes=raw_bytes,
                file_hash="sha256...",
                file_name="malware.exe",
                file_size_bytes=len(raw_bytes),
                mime_type="application/octet-stream",
                tenant_id=tenant.id,
                reason="av_threat",
            )

    # Later: retrieve and decrypt
    raw = await svc.retrieve_file(redis=app.state.redis, quarantine_id=record.id)

    # Release (mark row, delete from Redis)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await svc.release_file(session=session, redis=app.state.redis,
                                   quarantine_id=record.id)
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from prometheus_client import Counter, Gauge
from sqlalchemy.ext.asyncio import AsyncSession

from fileguard.config import settings
from fileguard.models.quarantined_file import QuarantinedFile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

_QUARANTINE_OPS = Counter(
    "fileguard_quarantine_operations_total",
    "Total quarantine operations by type",
    ["operation"],  # quarantine | retrieve | release | purge
)
_QUARANTINE_ERRORS = Counter(
    "fileguard_quarantine_errors_total",
    "Total quarantine operation errors by type",
    ["operation"],
)
_QUARANTINE_ACTIVE = Gauge(
    "fileguard_quarantine_active_files",
    "Approximate number of files currently in active quarantine",
)

# ---------------------------------------------------------------------------
# Encryption constants
# ---------------------------------------------------------------------------

# HKDF info string that scopes the derived key to quarantine usage.
# Changing this value invalidates all existing quarantined blobs.
_HKDF_INFO = b"fileguard:quarantine:aes256gcm:v1"

# AES-GCM nonce length in bytes (NIST SP 800-38D recommends 96 bits = 12 bytes).
_NONCE_LEN = 12


class QuarantineError(Exception):
    """Raised when a quarantine operation fails in an unrecoverable way."""


class QuarantineNotFoundError(QuarantineError):
    """Raised when the requested quarantine record or blob cannot be found."""


class QuarantineService:
    """AES-256-GCM quarantine with Redis-backed TTL and PostgreSQL metadata.

    Args:
        secret_key:
            Raw secret used for key derivation.  Defaults to
            ``settings.SECRET_KEY``.  Must be kept confidential; leaking it
            allows decryption of all quarantined files.
        default_ttl_seconds:
            Default TTL applied when callers do not specify one.  Defaults to
            ``settings.QUARANTINE_DEFAULT_TTL_SECONDS`` (24 hours).
        max_ttl_seconds:
            Upper bound on caller-supplied TTLs.  Defaults to
            ``settings.QUARANTINE_MAX_TTL_SECONDS`` (30 days).
        redis_key_prefix:
            Redis key prefix.  Defaults to
            ``settings.QUARANTINE_REDIS_KEY_PREFIX``.
    """

    def __init__(
        self,
        secret_key: str | None = None,
        default_ttl_seconds: int | None = None,
        max_ttl_seconds: int | None = None,
        redis_key_prefix: str | None = None,
    ) -> None:
        raw_key = secret_key or settings.SECRET_KEY
        self._aes_key: bytes = self._derive_key(raw_key)
        self._default_ttl = default_ttl_seconds or settings.QUARANTINE_DEFAULT_TTL_SECONDS
        self._max_ttl = max_ttl_seconds or settings.QUARANTINE_MAX_TTL_SECONDS
        self._key_prefix = redis_key_prefix or settings.QUARANTINE_REDIS_KEY_PREFIX

    # ------------------------------------------------------------------
    # Key derivation
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_key(secret: str) -> bytes:
        """Derive a 256-bit AES key from *secret* using HKDF-SHA-256.

        HKDF (RFC 5869) provides domain separation via the ``info`` parameter
        so the same ``SECRET_KEY`` can be reused for multiple purposes without
        key-reuse risks.

        Returns:
            32 raw bytes suitable for ``AESGCM(key)``.
        """
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=_HKDF_INFO,
        )
        return hkdf.derive(secret.encode("utf-8"))

    # ------------------------------------------------------------------
    # Encryption / decryption primitives
    # ------------------------------------------------------------------

    def _encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt *plaintext* with AES-256-GCM.

        Returns a blob of ``<12-byte nonce> || <ciphertext+16-byte GCM tag>``.
        The GCM tag authenticates both the nonce and ciphertext, so any
        tampering is detected during :meth:`_decrypt`.

        A fresh nonce is generated for every call via ``os.urandom`` (CSPRNG).
        """
        nonce = os.urandom(_NONCE_LEN)
        aesgcm = AESGCM(self._aes_key)
        # ``cryptography``'s AESGCM.encrypt() returns ciphertext + 16-byte tag.
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ciphertext

    def _decrypt(self, blob: bytes) -> bytes:
        """Decrypt a blob produced by :meth:`_encrypt`.

        Raises:
            QuarantineError: If the blob is too short or authentication fails
                (indicating tampering or key mismatch).
        """
        if len(blob) < _NONCE_LEN + 16:  # nonce + minimum tag
            raise QuarantineError("Encrypted blob is too short; possible corruption.")
        nonce = blob[:_NONCE_LEN]
        ciphertext = blob[_NONCE_LEN:]
        aesgcm = AESGCM(self._aes_key)
        try:
            return aesgcm.decrypt(nonce, ciphertext, None)
        except Exception as exc:
            raise QuarantineError(
                "AES-GCM decryption failed; blob may be tampered or key mismatch."
            ) from exc

    # ------------------------------------------------------------------
    # Redis key helpers
    # ------------------------------------------------------------------

    def _redis_key(self, quarantine_id: uuid.UUID) -> str:
        return f"{self._key_prefix}:{quarantine_id}"

    def _clamp_ttl(self, ttl_seconds: int) -> int:
        """Clamp *ttl_seconds* to [1, max_ttl]."""
        return max(1, min(ttl_seconds, self._max_ttl))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        reason: str = "av_threat",
        scan_event_id: uuid.UUID | None = None,
        ttl_seconds: int | None = None,
    ) -> QuarantinedFile:
        """Encrypt *file_bytes* and place it in quarantine.

        The encrypted blob is stored in Redis under
        ``{prefix}:{quarantine_id}`` with the specified TTL.  A
        :class:`~fileguard.models.quarantined_file.QuarantinedFile` metadata
        row is inserted into the active database session (caller must commit).

        Args:
            session: Open async SQLAlchemy session within an active transaction.
            redis: An ``redis.asyncio.Redis`` (or compatible) client.
            file_bytes: Raw file content to encrypt and quarantine.
            file_hash: SHA-256 hex digest of *file_bytes* (caller computes).
            file_name: Original filename for display/audit purposes.
            file_size_bytes: Size of the original file in bytes.
            mime_type: MIME type of the file.
            tenant_id: Owning tenant's UUID.
            reason: Why the file was quarantined: ``"av_threat"``,
                ``"pii"``, or ``"policy"``.
            scan_event_id: Optional UUID of the triggering scan event.
            ttl_seconds: Lifetime in seconds.  Clamped to
                ``[1, max_ttl_seconds]``.  Defaults to
                ``default_ttl_seconds``.

        Returns:
            The persisted :class:`~fileguard.models.quarantined_file.QuarantinedFile`
            record (not yet committed).

        Raises:
            QuarantineError: If encryption or Redis storage fails.
            ValueError: If *reason* is not a recognised value.
        """
        valid_reasons = {"av_threat", "pii", "policy"}
        if reason not in valid_reasons:
            raise ValueError(f"Invalid quarantine reason {reason!r}; must be one of {valid_reasons}")

        effective_ttl = self._clamp_ttl(ttl_seconds or self._default_ttl)
        now = datetime.now(tz=timezone.utc)
        expires_at = now + timedelta(seconds=effective_ttl)
        quarantine_id = uuid.uuid4()

        # --- Encrypt ---
        try:
            encrypted_blob = self._encrypt(file_bytes)
        except Exception as exc:
            _QUARANTINE_ERRORS.labels(operation="quarantine").inc()
            raise QuarantineError(f"Encryption failed for file {file_name!r}: {exc}") from exc

        # --- Store in Redis with TTL ---
        redis_key = self._redis_key(quarantine_id)
        try:
            await redis.set(redis_key, encrypted_blob, ex=effective_ttl)
        except Exception as exc:
            _QUARANTINE_ERRORS.labels(operation="quarantine").inc()
            raise QuarantineError(
                f"Failed to store quarantined file {quarantine_id} in Redis: {exc}"
            ) from exc

        # --- Persist metadata row ---
        record = QuarantinedFile(
            id=quarantine_id,
            tenant_id=tenant_id,
            scan_event_id=scan_event_id,
            file_hash=file_hash,
            file_name=file_name,
            file_size_bytes=file_size_bytes,
            mime_type=mime_type,
            reason=reason,
            status="active",
            ttl_seconds=effective_ttl,
            expires_at=expires_at,
            created_at=now,
        )
        session.add(record)
        try:
            await session.flush()
        except Exception as exc:
            # Roll back Redis write on DB failure so they stay in sync.
            try:
                await redis.delete(redis_key)
            except Exception:
                logger.warning("Failed to delete Redis key %s during rollback", redis_key)
            _QUARANTINE_ERRORS.labels(operation="quarantine").inc()
            raise QuarantineError(
                f"Failed to persist QuarantinedFile metadata for {quarantine_id}: {exc}"
            ) from exc

        _QUARANTINE_OPS.labels(operation="quarantine").inc()
        _QUARANTINE_ACTIVE.inc()
        logger.info(
            json.dumps({
                "event": "file_quarantined",
                "quarantine_id": str(quarantine_id),
                "tenant_id": str(tenant_id),
                "file_hash": file_hash,
                "file_name": file_name,
                "reason": reason,
                "ttl_seconds": effective_ttl,
                "expires_at": expires_at.isoformat(),
            })
        )
        return record

    async def retrieve_file(
        self,
        *,
        redis: Any,
        quarantine_id: uuid.UUID,
    ) -> bytes:
        """Retrieve and decrypt a quarantined file's bytes from Redis.

        Args:
            redis: Redis client.
            quarantine_id: UUID of the quarantine record.

        Returns:
            Decrypted raw file bytes.

        Raises:
            QuarantineNotFoundError: If the Redis key has expired or was never set.
            QuarantineError: If decryption fails (tampering or key mismatch).
        """
        redis_key = self._redis_key(quarantine_id)
        try:
            blob = await redis.get(redis_key)
        except Exception as exc:
            _QUARANTINE_ERRORS.labels(operation="retrieve").inc()
            raise QuarantineError(
                f"Redis fetch failed for quarantine_id={quarantine_id}: {exc}"
            ) from exc

        if blob is None:
            _QUARANTINE_ERRORS.labels(operation="retrieve").inc()
            raise QuarantineNotFoundError(
                f"Quarantined blob for {quarantine_id} not found in Redis "
                "(may have expired or been deleted)."
            )

        try:
            plaintext = self._decrypt(blob)
        except QuarantineError:
            _QUARANTINE_ERRORS.labels(operation="retrieve").inc()
            raise

        _QUARANTINE_OPS.labels(operation="retrieve").inc()
        logger.debug("Retrieved quarantined file quarantine_id=%s", quarantine_id)
        return plaintext

    async def release_file(
        self,
        *,
        session: AsyncSession,
        redis: Any,
        quarantine_id: uuid.UUID,
    ) -> QuarantinedFile:
        """Release a quarantined file: delete from Redis and mark status 'released'.

        Releasing indicates a deliberate operator decision (e.g. false-positive
        review).  The metadata row is retained for audit purposes.

        Args:
            session: Open async SQLAlchemy session within an active transaction.
            redis: Redis client.
            quarantine_id: UUID of the quarantine record.

        Returns:
            The updated :class:`~fileguard.models.quarantined_file.QuarantinedFile`
            record.

        Raises:
            QuarantineNotFoundError: If the record does not exist in the database.
            QuarantineError: If the record is not in ``active`` state.
        """
        from sqlalchemy import select

        stmt = select(QuarantinedFile).where(QuarantinedFile.id == quarantine_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()

        if record is None:
            raise QuarantineNotFoundError(
                f"QuarantinedFile record {quarantine_id} not found."
            )
        if record.status != "active":
            raise QuarantineError(
                f"Cannot release quarantined file {quarantine_id}: "
                f"current status is {record.status!r} (expected 'active')."
            )

        # Delete from Redis (best-effort; TTL will clean up if this fails).
        redis_key = self._redis_key(quarantine_id)
        try:
            await redis.delete(redis_key)
        except Exception as exc:
            logger.warning(
                "Failed to delete Redis key %s during release: %s", redis_key, exc
            )

        record.status = "released"
        record.released_at = datetime.now(tz=timezone.utc)
        await session.flush()

        _QUARANTINE_OPS.labels(operation="release").inc()
        _QUARANTINE_ACTIVE.dec()
        logger.info(
            json.dumps({
                "event": "file_released",
                "quarantine_id": str(quarantine_id),
                "tenant_id": str(record.tenant_id),
                "file_hash": record.file_hash,
            })
        )
        return record

    async def purge_file(
        self,
        *,
        session: AsyncSession,
        redis: Any,
        quarantine_id: uuid.UUID,
    ) -> None:
        """Permanently delete a quarantined file from both Redis and the database.

        Unlike :meth:`release_file`, this removes the metadata row entirely.
        Use this for GDPR/right-to-erasure requests or administrative cleanup.

        Args:
            session: Open async SQLAlchemy session within an active transaction.
            redis: Redis client.
            quarantine_id: UUID of the quarantine record.

        Raises:
            QuarantineNotFoundError: If the record does not exist in the database.
        """
        from sqlalchemy import select

        stmt = select(QuarantinedFile).where(QuarantinedFile.id == quarantine_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()

        if record is None:
            raise QuarantineNotFoundError(
                f"QuarantinedFile record {quarantine_id} not found."
            )

        was_active = record.status == "active"

        # Delete from Redis (best-effort).
        redis_key = self._redis_key(quarantine_id)
        try:
            await redis.delete(redis_key)
        except Exception as exc:
            logger.warning(
                "Failed to delete Redis key %s during purge: %s", redis_key, exc
            )

        await session.delete(record)
        await session.flush()

        _QUARANTINE_OPS.labels(operation="purge").inc()
        if was_active:
            _QUARANTINE_ACTIVE.dec()
        logger.info(
            json.dumps({
                "event": "file_purged",
                "quarantine_id": str(quarantine_id),
                "tenant_id": str(record.tenant_id),
            })
        )

    async def mark_expired(
        self,
        *,
        session: AsyncSession,
        quarantine_id: uuid.UUID,
    ) -> QuarantinedFile:
        """Transition a record from ``active`` to ``expired``.

        Called by a background worker that scans for records whose
        ``expires_at`` has passed (i.e. Redis TTL has elapsed and the blob is
        gone).  This keeps the PostgreSQL status in sync with Redis reality.

        Args:
            session: Open async SQLAlchemy session within an active transaction.
            quarantine_id: UUID of the record to expire.

        Returns:
            The updated record.

        Raises:
            QuarantineNotFoundError: If the record does not exist.
            QuarantineError: If the record is not in ``active`` state.
        """
        from sqlalchemy import select

        stmt = select(QuarantinedFile).where(QuarantinedFile.id == quarantine_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()

        if record is None:
            raise QuarantineNotFoundError(
                f"QuarantinedFile record {quarantine_id} not found."
            )
        if record.status != "active":
            raise QuarantineError(
                f"Cannot expire quarantine {quarantine_id}: "
                f"status is already {record.status!r}."
            )

        record.status = "expired"
        await session.flush()

        _QUARANTINE_OPS.labels(operation="expire").inc()
        _QUARANTINE_ACTIVE.dec()
        logger.info(
            json.dumps({
                "event": "file_expired",
                "quarantine_id": str(quarantine_id),
                "tenant_id": str(record.tenant_id),
            })
        )
        return record
