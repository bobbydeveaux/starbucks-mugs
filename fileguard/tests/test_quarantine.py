"""Unit tests for fileguard/services/quarantine.py (QuarantineService).

All tests run fully offline — Redis and PostgreSQL are replaced by mocks so no
external services are required.

Coverage targets
----------------
* AES-256-GCM key derivation produces a 32-byte key.
* Encryption produces nonce-prefixed ciphertext; decryption recovers plaintext.
* Encrypt → decrypt round-trip is lossless for arbitrary byte sequences.
* A different key cannot decrypt ciphertext (GCM auth-tag rejection).
* Truncated blob raises QuarantineError on decrypt.
* ``quarantine_file`` stores encrypted blob in Redis with the correct TTL.
* ``quarantine_file`` inserts a QuarantinedFile record in the session.
* ``quarantine_file`` clamps TTL to configured max.
* ``quarantine_file`` raises QuarantineError on Redis failure, and does not
  persist the DB row.
* ``quarantine_file`` raises QuarantineError on DB failure, and rolls back
  the Redis key.
* ``quarantine_file`` raises ValueError on invalid reason.
* ``retrieve_file`` fetches and decrypts the Redis blob.
* ``retrieve_file`` raises QuarantineNotFoundError when key is absent.
* ``release_file`` updates status to 'released', sets released_at, deletes
  the Redis key.
* ``release_file`` raises QuarantineNotFoundError for unknown id.
* ``release_file`` raises QuarantineError when status is not 'active'.
* ``purge_file`` deletes the Redis key and removes the DB row.
* ``purge_file`` raises QuarantineNotFoundError for unknown id.
* ``mark_expired`` transitions status from 'active' to 'expired'.
* ``mark_expired`` raises QuarantineError when already expired.
* Prometheus counters are incremented on success and failure.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Provide required env vars before importing fileguard modules.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-chars!!")

from fileguard.services.quarantine import (
    QuarantineError,
    QuarantineNotFoundError,
    QuarantineService,
    _NONCE_LEN,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_SCAN_EVENT_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
_PLAINTEXT = b"Hello, quarantine world! \x00\x01\x02\xff"
_SECRET = "test-secret-key-that-is-at-least-32-chars!!"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(**kwargs) -> QuarantineService:
    """Return a QuarantineService with test defaults."""
    return QuarantineService(
        secret_key=_SECRET,
        default_ttl_seconds=3600,
        max_ttl_seconds=86400,
        redis_key_prefix="test:quarantine",
        **kwargs,
    )


def _make_active_record(quarantine_id: uuid.UUID | None = None) -> MagicMock:
    """Return a mock QuarantinedFile in 'active' state."""
    record = MagicMock()
    record.id = quarantine_id or uuid.uuid4()
    record.tenant_id = _TENANT_ID
    record.file_hash = "abc123"
    record.status = "active"
    record.released_at = None
    return record


# ---------------------------------------------------------------------------
# Encryption primitives
# ---------------------------------------------------------------------------


class TestKeyDerivation:
    def test_derives_32_byte_key(self) -> None:
        key = QuarantineService._derive_key(_SECRET)
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_different_secrets_produce_different_keys(self) -> None:
        key_a = QuarantineService._derive_key("secret-a")
        key_b = QuarantineService._derive_key("secret-b")
        assert key_a != key_b

    def test_same_secret_is_deterministic(self) -> None:
        key1 = QuarantineService._derive_key(_SECRET)
        key2 = QuarantineService._derive_key(_SECRET)
        assert key1 == key2


class TestEncryptDecrypt:
    def setup_method(self) -> None:
        self.svc = _make_service()

    def test_encrypt_produces_nonce_plus_ciphertext(self) -> None:
        blob = self.svc._encrypt(_PLAINTEXT)
        # Minimum: nonce (12) + empty ciphertext (0) + GCM tag (16) = 28 bytes
        assert len(blob) >= _NONCE_LEN + 16
        # First 12 bytes are the nonce — different every call
        blob2 = self.svc._encrypt(_PLAINTEXT)
        assert blob[:_NONCE_LEN] != blob2[:_NONCE_LEN]

    def test_roundtrip_lossless(self) -> None:
        blob = self.svc._encrypt(_PLAINTEXT)
        recovered = self.svc._decrypt(blob)
        assert recovered == _PLAINTEXT

    def test_empty_plaintext_roundtrip(self) -> None:
        blob = self.svc._encrypt(b"")
        assert self.svc._decrypt(blob) == b""

    def test_large_plaintext_roundtrip(self) -> None:
        data = os.urandom(1024 * 1024)  # 1 MiB
        blob = self.svc._encrypt(data)
        assert self.svc._decrypt(blob) == data

    def test_wrong_key_raises_quarantine_error(self) -> None:
        blob = self.svc._encrypt(_PLAINTEXT)
        other_svc = _make_service(secret_key="completely-different-secret-key-xyz!")
        with pytest.raises(QuarantineError, match="decryption failed"):
            other_svc._decrypt(blob)

    def test_truncated_blob_raises_quarantine_error(self) -> None:
        with pytest.raises(QuarantineError, match="too short"):
            self.svc._decrypt(b"\x00" * 10)

    def test_tampered_ciphertext_raises_quarantine_error(self) -> None:
        blob = bytearray(self.svc._encrypt(_PLAINTEXT))
        blob[-1] ^= 0xFF  # flip last byte of GCM tag
        with pytest.raises(QuarantineError):
            self.svc._decrypt(bytes(blob))


# ---------------------------------------------------------------------------
# TTL clamping
# ---------------------------------------------------------------------------


class TestClampTTL:
    def test_clamp_above_max(self) -> None:
        svc = _make_service(max_ttl_seconds=100)
        assert svc._clamp_ttl(999) == 100

    def test_clamp_below_one(self) -> None:
        svc = _make_service()
        assert svc._clamp_ttl(0) == 1
        assert svc._clamp_ttl(-5) == 1

    def test_within_bounds_unchanged(self) -> None:
        svc = _make_service(max_ttl_seconds=7200)
        assert svc._clamp_ttl(3600) == 3600


# ---------------------------------------------------------------------------
# quarantine_file
# ---------------------------------------------------------------------------


class TestQuarantineFile:
    def setup_method(self) -> None:
        self.svc = _make_service()

    @pytest.mark.asyncio
    async def test_stores_encrypted_blob_in_redis(self) -> None:
        redis = AsyncMock()
        session = AsyncMock()
        session.flush = AsyncMock()

        record = await self.svc.quarantine_file(
            session=session,
            redis=redis,
            file_bytes=_PLAINTEXT,
            file_hash="deadbeef",
            file_name="test.bin",
            file_size_bytes=len(_PLAINTEXT),
            mime_type="application/octet-stream",
            tenant_id=_TENANT_ID,
            reason="av_threat",
            ttl_seconds=600,
        )

        # Redis.set should have been called with the encrypted blob and TTL.
        redis.set.assert_awaited_once()
        call_args = redis.set.call_args
        key_arg = call_args.args[0]
        blob_arg = call_args.args[1]
        assert key_arg.startswith("test:quarantine:")
        # The blob is encrypted; decrypt it to verify plaintext.
        recovered = self.svc._decrypt(blob_arg)
        assert recovered == _PLAINTEXT
        assert call_args.kwargs.get("ex") == 600

    @pytest.mark.asyncio
    async def test_persists_metadata_row(self) -> None:
        redis = AsyncMock()
        session = AsyncMock()
        session.flush = AsyncMock()

        record = await self.svc.quarantine_file(
            session=session,
            redis=redis,
            file_bytes=_PLAINTEXT,
            file_hash="abc123",
            file_name="virus.exe",
            file_size_bytes=42,
            mime_type="application/x-dosexec",
            tenant_id=_TENANT_ID,
            reason="av_threat",
            scan_event_id=_SCAN_EVENT_ID,
        )

        session.add.assert_called_once()
        session.flush.assert_awaited_once()
        assert record.file_hash == "abc123"
        assert record.status == "active"
        assert record.reason == "av_threat"
        assert record.scan_event_id == _SCAN_EVENT_ID
        assert record.ttl_seconds == 3600  # default TTL

    @pytest.mark.asyncio
    async def test_clamps_ttl_to_max(self) -> None:
        redis = AsyncMock()
        session = AsyncMock()
        session.flush = AsyncMock()

        await self.svc.quarantine_file(
            session=session,
            redis=redis,
            file_bytes=b"x",
            file_hash="ff",
            file_name="f.bin",
            file_size_bytes=1,
            mime_type="application/octet-stream",
            tenant_id=_TENANT_ID,
            reason="policy",
            ttl_seconds=999999,
        )

        call_args = redis.set.call_args
        assert call_args.kwargs.get("ex") == 86400  # max_ttl

    @pytest.mark.asyncio
    async def test_raises_on_redis_failure(self) -> None:
        redis = AsyncMock()
        redis.set.side_effect = Exception("Redis connection refused")
        session = AsyncMock()

        with pytest.raises(QuarantineError, match="Failed to store quarantined file"):
            await self.svc.quarantine_file(
                session=session,
                redis=redis,
                file_bytes=b"data",
                file_hash="ff",
                file_name="f.bin",
                file_size_bytes=4,
                mime_type="text/plain",
                tenant_id=_TENANT_ID,
                reason="pii",
            )
        # DB row should not have been added.
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_rolls_back_redis_on_db_failure(self) -> None:
        redis = AsyncMock()
        session = AsyncMock()
        session.flush.side_effect = Exception("DB constraint violation")

        with pytest.raises(QuarantineError, match="Failed to persist"):
            await self.svc.quarantine_file(
                session=session,
                redis=redis,
                file_bytes=b"data",
                file_hash="ff",
                file_name="f.bin",
                file_size_bytes=4,
                mime_type="text/plain",
                tenant_id=_TENANT_ID,
                reason="av_threat",
            )

        # Redis key should have been deleted during rollback.
        redis.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_reason_raises_value_error(self) -> None:
        redis = AsyncMock()
        session = AsyncMock()

        with pytest.raises(ValueError, match="Invalid quarantine reason"):
            await self.svc.quarantine_file(
                session=session,
                redis=redis,
                file_bytes=b"data",
                file_hash="ff",
                file_name="f.bin",
                file_size_bytes=4,
                mime_type="text/plain",
                tenant_id=_TENANT_ID,
                reason="unknown_reason",  # invalid
            )


# ---------------------------------------------------------------------------
# retrieve_file
# ---------------------------------------------------------------------------


class TestRetrieveFile:
    def setup_method(self) -> None:
        self.svc = _make_service()

    @pytest.mark.asyncio
    async def test_returns_decrypted_bytes(self) -> None:
        qid = uuid.uuid4()
        blob = self.svc._encrypt(_PLAINTEXT)
        redis = AsyncMock()
        redis.get.return_value = blob

        result = await self.svc.retrieve_file(redis=redis, quarantine_id=qid)

        assert result == _PLAINTEXT
        redis.get.assert_awaited_once_with(f"test:quarantine:{qid}")

    @pytest.mark.asyncio
    async def test_raises_not_found_when_key_absent(self) -> None:
        redis = AsyncMock()
        redis.get.return_value = None

        with pytest.raises(QuarantineNotFoundError, match="not found in Redis"):
            await self.svc.retrieve_file(redis=redis, quarantine_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_raises_on_redis_error(self) -> None:
        redis = AsyncMock()
        redis.get.side_effect = Exception("Redis timeout")

        with pytest.raises(QuarantineError, match="Redis fetch failed"):
            await self.svc.retrieve_file(redis=redis, quarantine_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# release_file
# ---------------------------------------------------------------------------


class TestReleaseFile:
    def setup_method(self) -> None:
        self.svc = _make_service()

    @pytest.mark.asyncio
    async def test_releases_active_record(self) -> None:
        qid = uuid.uuid4()
        record = _make_active_record(qid)
        redis = AsyncMock()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: record))
        session.flush = AsyncMock()

        result = await self.svc.release_file(
            session=session, redis=redis, quarantine_id=qid
        )

        assert result.status == "released"
        assert result.released_at is not None
        redis.delete.assert_awaited_once_with(f"test:quarantine:{qid}")

    @pytest.mark.asyncio
    async def test_raises_not_found_for_unknown_id(self) -> None:
        redis = AsyncMock()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        with pytest.raises(QuarantineNotFoundError):
            await self.svc.release_file(
                session=session, redis=redis, quarantine_id=uuid.uuid4()
            )

    @pytest.mark.asyncio
    async def test_raises_error_when_not_active(self) -> None:
        qid = uuid.uuid4()
        record = _make_active_record(qid)
        record.status = "expired"
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: record))
        redis = AsyncMock()

        with pytest.raises(QuarantineError, match="Cannot release"):
            await self.svc.release_file(
                session=session, redis=redis, quarantine_id=qid
            )


# ---------------------------------------------------------------------------
# purge_file
# ---------------------------------------------------------------------------


class TestPurgeFile:
    def setup_method(self) -> None:
        self.svc = _make_service()

    @pytest.mark.asyncio
    async def test_deletes_redis_key_and_db_row(self) -> None:
        qid = uuid.uuid4()
        record = _make_active_record(qid)
        redis = AsyncMock()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: record))
        session.flush = AsyncMock()

        await self.svc.purge_file(session=session, redis=redis, quarantine_id=qid)

        redis.delete.assert_awaited_once_with(f"test:quarantine:{qid}")
        session.delete.assert_called_once_with(record)

    @pytest.mark.asyncio
    async def test_raises_not_found_for_unknown_id(self) -> None:
        redis = AsyncMock()
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        with pytest.raises(QuarantineNotFoundError):
            await self.svc.purge_file(
                session=session, redis=redis, quarantine_id=uuid.uuid4()
            )


# ---------------------------------------------------------------------------
# mark_expired
# ---------------------------------------------------------------------------


class TestMarkExpired:
    def setup_method(self) -> None:
        self.svc = _make_service()

    @pytest.mark.asyncio
    async def test_transitions_active_to_expired(self) -> None:
        qid = uuid.uuid4()
        record = _make_active_record(qid)
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: record))
        session.flush = AsyncMock()

        result = await self.svc.mark_expired(session=session, quarantine_id=qid)

        assert result.status == "expired"

    @pytest.mark.asyncio
    async def test_raises_error_when_already_expired(self) -> None:
        qid = uuid.uuid4()
        record = _make_active_record(qid)
        record.status = "expired"
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: record))

        with pytest.raises(QuarantineError, match="Cannot expire"):
            await self.svc.mark_expired(session=session, quarantine_id=qid)

    @pytest.mark.asyncio
    async def test_raises_not_found_for_unknown_id(self) -> None:
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))

        with pytest.raises(QuarantineNotFoundError):
            await self.svc.mark_expired(session=session, quarantine_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Prometheus counters
# ---------------------------------------------------------------------------


class TestPrometheusCounters:
    @pytest.mark.asyncio
    async def test_quarantine_op_counter_increments(self) -> None:
        from fileguard.services.quarantine import _QUARANTINE_OPS

        svc = _make_service()
        before = _QUARANTINE_OPS.labels(operation="quarantine")._value.get()
        redis = AsyncMock()
        session = AsyncMock()
        session.flush = AsyncMock()

        await svc.quarantine_file(
            session=session,
            redis=redis,
            file_bytes=b"test",
            file_hash="abc",
            file_name="f.txt",
            file_size_bytes=4,
            mime_type="text/plain",
            tenant_id=_TENANT_ID,
            reason="pii",
        )

        after = _QUARANTINE_OPS.labels(operation="quarantine")._value.get()
        assert after == before + 1.0

    @pytest.mark.asyncio
    async def test_error_counter_increments_on_redis_failure(self) -> None:
        from fileguard.services.quarantine import _QUARANTINE_ERRORS

        svc = _make_service()
        before = _QUARANTINE_ERRORS.labels(operation="quarantine")._value.get()
        redis = AsyncMock()
        redis.set.side_effect = Exception("oops")
        session = AsyncMock()

        with pytest.raises(QuarantineError):
            await svc.quarantine_file(
                session=session,
                redis=redis,
                file_bytes=b"x",
                file_hash="ff",
                file_name="f.bin",
                file_size_bytes=1,
                mime_type="application/octet-stream",
                tenant_id=_TENANT_ID,
                reason="av_threat",
            )

        after = _QUARANTINE_ERRORS.labels(operation="quarantine")._value.get()
        assert after == before + 1.0
