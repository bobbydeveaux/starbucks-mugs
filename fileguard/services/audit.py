"""AuditService — tamper-evident scan event logging and SIEM forwarding.

Responsibilities
----------------
1. Compute an HMAC-SHA256 signature over the canonical fields of a
   :class:`~fileguard.models.scan_event.ScanEvent` before it is persisted,
   so that any post-write tampering can be detected during compliance export.

2. Persist a new ``ScanEvent`` row to PostgreSQL using the supplied async
   SQLAlchemy session.  The model's SQLAlchemy event hooks enforce that no
   UPDATE or DELETE is ever issued at the application layer.

3. Optionally forward the scan event to a tenant-configured SIEM endpoint
   (Splunk HEC or RiverSafe WatchTower) as a best-effort fire-and-forget
   operation.  SIEM delivery failures are *logged but never raised*, so that
   a degraded SIEM integration never blocks the scan critical path.

Usage
-----
    service = AuditService(signing_key="shared-secret", http_client=client)
    event = await service.log_scan_event(
        session=db_session,
        tenant_id=tenant.id,
        file_hash="abc123...",
        file_name="report.pdf",
        file_size_bytes=102400,
        mime_type="application/pdf",
        status="flagged",
        action_taken="quarantine",
        findings=[{"type": "pii", "category": "NHS_NUMBER", "severity": "high"}],
        scan_duration_ms=1240,
        siem_config=tenant.siem_config,
    )
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from fileguard.models.scan_event import ScanEvent

logger = logging.getLogger(__name__)

# Supported SIEM endpoint types
_SIEM_TYPE_SPLUNK = "splunk"
_SIEM_TYPE_WATCHTOWER = "watchtower"

# HTTP timeout for SIEM forwarding (seconds) — short so it never blocks scans
_SIEM_HTTP_TIMEOUT = 5.0


class AuditService:
    """Service for writing tamper-evident audit records and forwarding to SIEM.

    Parameters
    ----------
    signing_key:
        The server-side HMAC signing secret.  Must be kept confidential; it is
        used to produce and verify signatures on every ``ScanEvent`` record.
    http_client:
        An optional ``httpx.AsyncClient`` used for SIEM forwarding.  When
        ``None`` a new transient client is created per forward call.  Injecting
        a shared client is recommended in production for connection pooling.
    """

    def __init__(
        self,
        signing_key: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._signing_key = signing_key.encode()
        self._http_client = http_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def log_scan_event(
        self,
        *,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        file_hash: str,
        file_name: str,
        file_size_bytes: int,
        mime_type: str,
        status: str,
        action_taken: str,
        findings: list[dict[str, Any]],
        scan_duration_ms: int,
        siem_config: dict[str, Any] | None = None,
    ) -> ScanEvent:
        """Persist a tamper-evident scan event and optionally forward to SIEM.

        The HMAC signature is computed over the canonical fields
        ``(id, file_hash, status, action_taken, created_at)`` *after* the event
        is flushed so that the database-generated values are available.

        Parameters
        ----------
        session:
            An open async SQLAlchemy session.  The caller is responsible for
            committing or rolling back the transaction.
        tenant_id:
            UUID of the tenant that owns this scan.
        file_hash:
            SHA-256 hex digest of the scanned file.
        file_name:
            Original file name as submitted by the client.
        file_size_bytes:
            File size in bytes.
        mime_type:
            Detected MIME type of the scanned file.
        status:
            Scan verdict: ``"clean"``, ``"flagged"``, or ``"rejected"``.
        action_taken:
            Disposition applied: ``"pass"``, ``"quarantine"``, or ``"block"``.
        findings:
            List of finding dicts (each with ``type``, ``category``,
            ``severity``, and optionally ``offset`` / ``match``).
        scan_duration_ms:
            Wall-clock duration of the scan pipeline in milliseconds.
        siem_config:
            Optional tenant SIEM integration config dict with keys ``type``
            (``"splunk"`` or ``"watchtower"``), ``endpoint``, and optionally
            ``token``.  When ``None`` SIEM forwarding is skipped.

        Returns
        -------
        ScanEvent
            The persisted ORM instance (not yet committed).
        """
        event_id = uuid.uuid4()
        created_at = datetime.now(tz=timezone.utc)

        hmac_signature = self._compute_hmac(
            event_id=event_id,
            file_hash=file_hash,
            status=status,
            action_taken=action_taken,
            created_at=created_at,
        )

        event = ScanEvent(
            id=event_id,
            tenant_id=tenant_id,
            file_hash=file_hash,
            file_name=file_name,
            file_size_bytes=file_size_bytes,
            mime_type=mime_type,
            status=status,
            action_taken=action_taken,
            findings=findings,
            scan_duration_ms=scan_duration_ms,
            created_at=created_at,
            hmac_signature=hmac_signature,
        )

        session.add(event)
        await session.flush()

        logger.info(
            "Audit event recorded: scan_id=%s tenant=%s status=%s action=%s",
            event_id,
            tenant_id,
            status,
            action_taken,
        )

        if siem_config:
            await self._forward_to_siem(event, siem_config)

        return event

    def verify_hmac(self, event: ScanEvent) -> bool:
        """Return ``True`` if the event's HMAC signature is still valid.

        Computes the expected signature over the canonical fields and compares
        it with the stored ``hmac_signature`` using a constant-time comparison
        to prevent timing attacks.

        Parameters
        ----------
        event:
            A ``ScanEvent`` ORM instance (retrieved from the database).

        Returns
        -------
        bool
            ``True`` when the signature matches; ``False`` when tampered.
        """
        expected = self._compute_hmac(
            event_id=event.id,
            file_hash=event.file_hash,
            status=event.status,
            action_taken=event.action_taken,
            created_at=event.created_at,
        )
        return hmac.compare_digest(expected, event.hmac_signature)

    # ------------------------------------------------------------------
    # HMAC helpers
    # ------------------------------------------------------------------

    def _compute_hmac(
        self,
        *,
        event_id: uuid.UUID,
        file_hash: str,
        status: str,
        action_taken: str,
        created_at: datetime,
    ) -> str:
        """Compute HMAC-SHA256 over canonical event fields.

        The canonical message is the JSON serialisation of the ordered dict::

            {
                "id": "<uuid-str>",
                "file_hash": "<sha256-hex>",
                "status": "<status>",
                "action_taken": "<action>",
                "created_at": "<iso8601-utc>"
            }

        Using JSON with a fixed key order makes the message unambiguous and
        human-inspectable for offline verification.

        Returns
        -------
        str
            Lower-case hex HMAC-SHA256 digest.
        """
        canonical = json.dumps(
            {
                "id": str(event_id),
                "file_hash": file_hash,
                "status": status,
                "action_taken": action_taken,
                "created_at": created_at.isoformat(),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hmac.new(
            self._signing_key,
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()
        return digest

    # ------------------------------------------------------------------
    # SIEM forwarding
    # ------------------------------------------------------------------

    async def _forward_to_siem(
        self,
        event: ScanEvent,
        siem_config: dict[str, Any],
    ) -> None:
        """Forward a scan event to the configured SIEM endpoint.

        Delivery is **best-effort**: any HTTP or networking error is logged at
        WARNING level and suppressed — SIEM failures must never disrupt the scan
        pipeline or cause transaction rollbacks.

        Supported ``siem_config`` types
        --------------------------------
        ``"splunk"``
            HTTP Event Collector (HEC).  Sends a single HEC event JSON payload.
            Requires ``endpoint`` (HEC URL) and optionally ``token`` (HEC auth
            token, sent as ``Authorization: Splunk <token>``).

        ``"watchtower"``
            RiverSafe WatchTower REST API.  Sends the event payload as JSON.
            Requires ``endpoint`` and optionally ``token`` (Bearer token).
        """
        siem_type = siem_config.get("type", "").lower()
        endpoint = siem_config.get("endpoint")
        token = siem_config.get("token")

        if not endpoint:
            logger.warning("SIEM config missing 'endpoint'; skipping forwarding")
            return

        payload = self._build_siem_payload(event, siem_type)
        headers = self._build_siem_headers(siem_type, token)

        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=_SIEM_HTTP_TIMEOUT,
                )
                response.raise_for_status()
            else:
                async with httpx.AsyncClient(timeout=_SIEM_HTTP_TIMEOUT) as client:
                    response = await client.post(
                        endpoint,
                        json=payload,
                        headers=headers,
                    )
                    response.raise_for_status()

            logger.info(
                "SIEM event forwarded: scan_id=%s type=%s status_code=%d",
                event.id,
                siem_type,
                response.status_code,
            )

        except httpx.HTTPStatusError as exc:
            logger.warning(
                "SIEM delivery failed (HTTP %d) for scan_id=%s: %s",
                exc.response.status_code,
                event.id,
                exc,
            )
        except (httpx.RequestError, Exception) as exc:
            logger.warning(
                "SIEM delivery error for scan_id=%s: %s",
                event.id,
                exc,
            )

    @staticmethod
    def _build_siem_payload(
        event: ScanEvent,
        siem_type: str,
    ) -> dict[str, Any]:
        """Construct the SIEM-specific event payload dict."""
        base_event = {
            "scan_id": str(event.id),
            "tenant_id": str(event.tenant_id),
            "file_hash": event.file_hash,
            "file_name": event.file_name,
            "file_size_bytes": event.file_size_bytes,
            "mime_type": event.mime_type,
            "status": event.status,
            "action_taken": event.action_taken,
            "findings": event.findings,
            "scan_duration_ms": event.scan_duration_ms,
            "created_at": event.created_at.isoformat()
            if isinstance(event.created_at, datetime)
            else str(event.created_at),
            "hmac_signature": event.hmac_signature,
        }

        if siem_type == _SIEM_TYPE_SPLUNK:
            # Splunk HEC format wraps the event in a ``{"event": {...}}`` envelope
            return {"event": base_event, "sourcetype": "fileguard:scan"}

        # WatchTower and generic — send the event dict directly
        return base_event

    @staticmethod
    def _build_siem_headers(
        siem_type: str,
        token: str | None,
    ) -> dict[str, str]:
        """Return HTTP headers for SIEM delivery."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            if siem_type == _SIEM_TYPE_SPLUNK:
                headers["Authorization"] = f"Splunk {token}"
            else:
                headers["Authorization"] = f"Bearer {token}"
        return headers
