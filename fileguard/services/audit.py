"""AuditService — tamper-evident scan event logging and SIEM forwarding.

:class:`AuditService` persists :class:`~fileguard.models.scan_event.ScanEvent`
records to PostgreSQL with an HMAC-SHA256 integrity signature computed over the
canonical immutable fields of each record.  All writes are INSERT-only; the
service contains no UPDATE or DELETE code paths.

Structured JSON log entries carrying ``correlation_id``, ``tenant_id``, and
``scan_id`` are emitted on every successful audit call.

Scan events may also be forwarded to a tenant-configured SIEM endpoint
(Splunk HEC or RiverSafe WatchTower) as a best-effort fire-and-forget
operation.  SIEM delivery failures are *logged but never raised*, so that
a degraded SIEM integration never blocks the scan critical path.

Usage::

    from fileguard.services.audit import AuditService

    service = AuditService()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await service.log_scan_event(
                session,
                scan_event,
                correlation_id="req-abc123",
                tenant_id=tenant.id,
                scan_id=scan_event.id,
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

from fileguard.config import settings
from fileguard.models.scan_event import ScanEvent

logger = logging.getLogger(__name__)

# Supported SIEM endpoint types
_SIEM_TYPE_SPLUNK = "splunk"
_SIEM_TYPE_WATCHTOWER = "watchtower"

# HTTP timeout for SIEM forwarding (seconds) — short so it never blocks scans
_SIEM_HTTP_TIMEOUT = 5.0

# Fields included in HMAC computation (order matters — never reorder).
_HMAC_FIELDS = ("id", "file_hash", "status", "action_taken", "created_at")


class AuditError(Exception):
    """Raised when :class:`AuditService` cannot persist a :class:`ScanEvent`.

    Callers must not silently ignore this exception; the scan pipeline should
    treat an audit write failure as a hard error and surface it to the
    operator.
    """


class AuditService:
    """Append-only audit log service with HMAC-SHA256 integrity signing and SIEM forwarding.

    Each :class:`~fileguard.models.scan_event.ScanEvent` is signed with
    HMAC-SHA256 over the canonical immutable fields
    ``(id, file_hash, status, action_taken, created_at)`` before being
    persisted to PostgreSQL.

    Args:
        secret_key: Raw HMAC secret.  Defaults to ``settings.SECRET_KEY``.
            The key must be kept confidential; leaking it allows an attacker
            to forge signatures.
        signing_key: Alias for ``secret_key`` (alternate parameter name).
            When both are supplied, ``signing_key`` takes precedence.
        http_client: An optional ``httpx.AsyncClient`` used for SIEM forwarding.
            When ``None`` a new transient client is created per forward call.
            Injecting a shared client is recommended in production for
            connection pooling.
    """

    def __init__(
        self,
        secret_key: str | None = None,
        signing_key: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        raw = signing_key or secret_key
        if raw is None:
            raw = settings.SECRET_KEY
        self._secret_key: bytes = raw.encode("utf-8")
        # Alias so that code referencing either attribute works correctly.
        self._signing_key: bytes = self._secret_key
        self._http_client = http_client

    # ------------------------------------------------------------------
    # Signature helpers
    # ------------------------------------------------------------------

    def compute_hmac(self, scan_event: ScanEvent) -> str:
        """Return the HMAC-SHA256 hex digest for *scan_event*.

        The canonical message is a pipe-separated concatenation of the
        immutable fields (in the order defined by :data:`_HMAC_FIELDS`):

        ``{id}|{file_hash}|{status}|{action_taken}|{created_at}``

        ``created_at`` is serialised as an ISO-8601 string with UTC offset
        so that the representation is unambiguous across time zones.

        Args:
            scan_event: The event to sign.  ``created_at`` must be set
                before calling this method.

        Returns:
            A 64-character lowercase hex string.
        """
        created_at = scan_event.created_at
        if isinstance(created_at, datetime):
            created_at_str = created_at.isoformat()
        else:
            # Fall back to str() for date-only or pre-set string values.
            created_at_str = str(created_at)

        canonical = "|".join([
            str(scan_event.id),
            scan_event.file_hash,
            scan_event.status,
            scan_event.action_taken,
            created_at_str,
        ])

        return hmac.new(
            self._secret_key,
            canonical.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _compute_hmac(
        self,
        *,
        event_id: uuid.UUID,
        file_hash: str,
        status: str,
        action_taken: str,
        created_at: datetime,
    ) -> str:
        """Compute HMAC-SHA256 over canonical event fields using JSON encoding.

        The canonical message is the JSON serialisation of the ordered dict::

            {
                "action_taken": "<action>",
                "created_at": "<iso8601-utc>",
                "file_hash": "<sha256-hex>",
                "id": "<uuid-str>",
                "status": "<status>"
            }

        Using JSON with ``sort_keys=True`` makes the message unambiguous and
        human-inspectable for offline verification.

        Returns:
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
        return hmac.new(
            self._signing_key,
            canonical.encode(),
            hashlib.sha256,
        ).hexdigest()

    def verify_hmac(self, scan_event: ScanEvent) -> bool:
        """Return ``True`` if *scan_event*'s stored signature is valid.

        Uses :func:`hmac.compare_digest` to prevent timing-attack
        comparisons.

        Args:
            scan_event: The event to verify.  ``hmac_signature`` must be
                populated.
        """
        expected = self.compute_hmac(scan_event)
        return hmac.compare_digest(expected, scan_event.hmac_signature)

    # ------------------------------------------------------------------
    # Core persistence method
    # ------------------------------------------------------------------

    async def log_scan_event(
        self,
        session: AsyncSession,
        scan_event: ScanEvent,
        *,
        correlation_id: str | uuid.UUID | None = None,
        tenant_id: str | uuid.UUID | None = None,
        scan_id: str | uuid.UUID | None = None,
        siem_config: dict[str, Any] | None = None,
    ) -> ScanEvent:
        """Compute an HMAC-SHA256 signature, persist *scan_event*, and optionally forward to SIEM.

        Only an INSERT is issued; this method contains no UPDATE or DELETE
        code paths.  The caller retains full control of the transaction
        lifecycle (begin / commit / rollback).

        Args:
            session: Open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
                The session must already be within an active transaction if
                the caller intends to batch multiple writes atomically.
            scan_event: The :class:`~fileguard.models.scan_event.ScanEvent`
                to audit-log.  Its ``hmac_signature`` field will be
                overwritten with the computed value before the INSERT.
            correlation_id: Optional request-scoped trace identifier emitted
                in the structured log entry.
            tenant_id: Optional tenant identifier for the log entry.  Falls
                back to ``scan_event.tenant_id`` when omitted.
            scan_id: Optional scan identifier for the log entry.  Falls back
                to ``scan_event.id`` when omitted.
            siem_config: Optional tenant SIEM integration config dict with
                keys ``type`` (``"splunk"`` or ``"watchtower"``),
                ``endpoint``, and optionally ``token``.  When ``None`` SIEM
                forwarding is skipped.

        Returns:
            The same *scan_event* instance, now attached to *session* and
            with ``hmac_signature`` populated.

        Raises:
            AuditError: If the database INSERT fails for any reason.
        """
        # Compute and attach the HMAC signature before the INSERT so that
        # the stored value is always consistent with the persisted fields.
        scan_event.hmac_signature = self.compute_hmac(scan_event)

        try:
            session.add(scan_event)
            # flush() pushes the INSERT to the DB within the current
            # transaction without committing.  This lets callers batch
            # multiple inserts and commit once.
            await session.flush()
        except Exception as exc:
            raise AuditError(
                f"Failed to persist ScanEvent {scan_event.id}: {exc}"
            ) from exc

        # Emit a structured JSON audit log entry so that log-aggregation
        # systems (e.g. Splunk, Elasticsearch) can index these fields.
        log_entry: dict[str, Any] = {
            "event": "scan_event_audited",
            "correlation_id": str(correlation_id) if correlation_id is not None else None,
            "tenant_id": str(tenant_id) if tenant_id is not None else str(scan_event.tenant_id),
            "scan_id": str(scan_id) if scan_id is not None else str(scan_event.id),
            "file_hash": scan_event.file_hash,
            "status": scan_event.status,
            "action_taken": scan_event.action_taken,
        }
        logger.info(json.dumps(log_entry))

        if siem_config:
            await self._forward_to_siem(scan_event, siem_config)

        return scan_event

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
