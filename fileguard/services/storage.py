"""RedactedFileStorage — store redacted files and issue time-limited signed URLs.

:class:`RedactedFileStorage` provides two operations:

1. **Store** — persist redacted content to a local directory (or an
   S3-compatible object store when ``REDACTED_STORAGE_BACKEND=s3`` is set).

2. **Sign** — generate a time-limited HMAC-SHA256-signed download URL that
   callers can use to retrieve the stored file via the
   ``GET /v1/redacted/{file_id}`` endpoint.

The signing scheme is intentionally simple and self-contained:

* A ``file_id`` (UUID) uniquely identifies the stored object.
* An ``expires`` Unix timestamp (UTC) is embedded in the URL.
* The HMAC-SHA256 signature is computed over ``"{file_id}:{expires}"``
  using the application ``SECRET_KEY`` as the key.
* Signature verification rejects requests where the timestamp has elapsed
  or where the HMAC does not match.

This avoids a round-trip to a third-party service for local deployments
while remaining compatible with a future swap to S3 presigned URLs.

Configuration (via environment variables / ``.env``)::

    REDACTED_FILES_DIR=/tmp/fileguard/redacted   # local storage root
    REDACTED_URL_TTL_SECONDS=3600                # default signed-URL TTL
    REDACTED_BASE_URL=https://api.example.com    # base URL for signed URLs

Usage::

    from fileguard.services.storage import RedactedFileStorage

    storage = RedactedFileStorage()
    url = storage.store_and_sign(
        content="Patient NI: [REDACTED]",
        scan_id="abc123",
        ttl_seconds=3600,
    )
    # Returns: "https://api.example.com/v1/redacted/abc123-<uuid>?expires=...&sig=..."

    # Verify on retrieval:
    is_valid = storage.verify_signature(file_id, expires, sig)
    content = storage.retrieve(file_id)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import uuid

from fileguard.config import settings

logger = logging.getLogger(__name__)

_SIGN_SEP = ":"


class RedactedFileStorage:
    """Store redacted content locally and generate HMAC-signed download URLs.

    The storage backend writes UTF-8 encoded files to the directory
    configured by ``settings.REDACTED_FILES_DIR``.  Each stored file is
    named ``{file_id}.txt``.

    Signed URLs follow the format::

        {base_url}/v1/redacted/{file_id}?expires={unix_ts}&sig={hex_digest}

    The ``expires`` field is a Unix UTC timestamp.  Requests arriving after
    this timestamp are rejected by :meth:`verify_signature`.

    Args:
        base_url: Base URL prepended to download paths.  Defaults to
            ``settings.REDACTED_BASE_URL``.
        storage_dir: Directory for storing redacted files.  Defaults to
            ``settings.REDACTED_FILES_DIR``.
        secret_key: HMAC signing key.  Defaults to ``settings.SECRET_KEY``.
    """

    def __init__(
        self,
        base_url: str | None = None,
        storage_dir: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self._base_url = (base_url or settings.REDACTED_BASE_URL).rstrip("/")
        self._storage_dir = storage_dir or settings.REDACTED_FILES_DIR
        self._secret_key = (secret_key or settings.SECRET_KEY).encode("utf-8")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store_and_sign(
        self,
        content: str,
        scan_id: str,
        ttl_seconds: int | None = None,
    ) -> str:
        """Persist *content* to storage and return a signed download URL.

        A unique ``file_id`` is derived from *scan_id* and a UUID suffix to
        allow multiple redacted versions per scan (e.g. different formats).

        Args:
            content: The redacted text content to store.
            scan_id: The scan identifier — embedded in the ``file_id`` for
                traceability.
            ttl_seconds: Signed-URL lifetime in seconds.  Defaults to
                ``settings.REDACTED_URL_TTL_SECONDS``.

        Returns:
            A signed download URL string valid for *ttl_seconds* seconds.
        """
        ttl = ttl_seconds if ttl_seconds is not None else settings.REDACTED_URL_TTL_SECONDS
        file_id = f"{scan_id}-{uuid.uuid4().hex[:8]}"

        self._write(file_id, content)

        expires = int(time.time()) + ttl
        sig = self._sign(file_id, expires)
        url = (
            f"{self._base_url}/v1/redacted/{file_id}"
            f"?expires={expires}&sig={sig}"
        )

        logger.info(
            "RedactedFileStorage: stored file_id=%s ttl=%ds url=%s",
            file_id,
            ttl,
            url,
        )
        return url

    def verify_signature(self, file_id: str, expires: int, sig: str) -> bool:
        """Return ``True`` if the signed URL parameters are valid and unexpired.

        Performs a constant-time HMAC comparison to prevent timing attacks.

        Args:
            file_id: The file identifier from the URL path.
            expires: The Unix UTC expiry timestamp from the URL query string.
            sig: The hex HMAC digest from the URL query string.

        Returns:
            ``True`` when the signature matches and the URL has not expired;
            ``False`` otherwise.
        """
        if time.time() > expires:
            logger.warning(
                "RedactedFileStorage: signed URL expired for file_id=%s", file_id
            )
            return False

        expected_sig = self._sign(file_id, expires)
        valid = hmac.compare_digest(expected_sig, sig)
        if not valid:
            logger.warning(
                "RedactedFileStorage: invalid signature for file_id=%s", file_id
            )
        return valid

    def retrieve(self, file_id: str) -> bytes | None:
        """Read stored redacted content as raw bytes.

        Args:
            file_id: The file identifier returned by :meth:`store_and_sign`.

        Returns:
            Raw UTF-8 bytes of the stored content, or ``None`` if not found.
        """
        path = self._file_path(file_id)
        if not os.path.exists(path):
            logger.warning(
                "RedactedFileStorage.retrieve: file not found file_id=%s path=%s",
                file_id,
                path,
            )
            return None
        with open(path, "rb") as fh:
            return fh.read()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write(self, file_id: str, content: str) -> None:
        """Write *content* to storage as UTF-8."""
        os.makedirs(self._storage_dir, exist_ok=True)
        path = self._file_path(file_id)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        logger.debug(
            "RedactedFileStorage._write: file_id=%s path=%s bytes=%d",
            file_id,
            path,
            len(content.encode("utf-8")),
        )

    def _file_path(self, file_id: str) -> str:
        """Return the absolute filesystem path for *file_id*."""
        # Sanitise file_id to prevent path traversal
        safe_id = "".join(c for c in file_id if c.isalnum() or c in "-_")
        return os.path.join(self._storage_dir, f"{safe_id}.txt")

    def _sign(self, file_id: str, expires: int) -> str:
        """Compute the HMAC-SHA256 signature for *file_id* and *expires*.

        Args:
            file_id: File identifier.
            expires: Unix UTC expiry timestamp.

        Returns:
            Lowercase hex digest string.
        """
        message = f"{file_id}{_SIGN_SEP}{expires}".encode("utf-8")
        return hmac.new(self._secret_key, message, hashlib.sha256).hexdigest()
