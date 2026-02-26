"""API route for serving redacted files via signed URLs.

Endpoint
--------
GET /v1/redacted/{file_id}?expires=<unix_ts>&sig=<hex_hmac>
    Verify the HMAC-SHA256 signature and expiry timestamp, then stream the
    stored redacted file content as ``text/plain``.

    Returns:
        ``200 OK`` with the redacted file content as plain text.
        ``403 Forbidden`` if the signature is invalid or the URL has expired.
        ``404 Not Found`` if the file does not exist in storage.

Authentication note
-------------------
The signed-URL parameters (``expires`` and ``sig``) act as a short-lived
bearer credential for the specific file.  No ``Authorization`` header is
required on this endpoint; the HMAC signature proves authenticity and the
``expires`` timestamp enforces time-bounding.  The
:class:`~fileguard.api.middleware.auth.AuthMiddleware` is therefore
**skipped** for this path via the ``public_paths`` allowlist.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from fileguard.services.storage import RedactedFileStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/redacted", tags=["redacted"])

_storage = RedactedFileStorage()


@router.get("/{file_id}", response_class=PlainTextResponse)
async def download_redacted(
    file_id: str,
    expires: int = Query(..., description="Unix UTC expiry timestamp embedded in the signed URL"),
    sig: str = Query(..., description="HMAC-SHA256 hex digest for signature verification"),
) -> PlainTextResponse:
    """Download a stored redacted file using its signed URL parameters.

    The *file_id*, *expires*, and *sig* parameters are produced by
    :meth:`~fileguard.services.storage.RedactedFileStorage.store_and_sign`
    and embedded in the URL returned to the caller as ``redacted_file_url``
    in the scan response.

    Args:
        file_id: Unique identifier of the stored redacted file.
        expires: Unix UTC timestamp after which the URL is invalid.
        sig: HMAC-SHA256 hex digest authenticating the URL parameters.

    Returns:
        A ``200 OK`` :class:`~fastapi.responses.PlainTextResponse` with
        ``Content-Type: text/plain; charset=utf-8`` containing the redacted
        file content.

    Raises:
        :class:`~fastapi.HTTPException`: ``403 Forbidden`` when the signature
            is invalid or the URL has expired; ``404 Not Found`` when the
            file is not present in storage.
    """
    if not _storage.verify_signature(file_id, expires, sig):
        raise HTTPException(
            status_code=403,
            detail="Invalid or expired signed URL",
        )

    content_bytes = _storage.retrieve(file_id)
    if content_bytes is None:
        raise HTTPException(status_code=404, detail="Redacted file not found")

    logger.info("Serving redacted file file_id=%s", file_id)
    return PlainTextResponse(
        content=content_bytes.decode("utf-8"),
        status_code=200,
    )
