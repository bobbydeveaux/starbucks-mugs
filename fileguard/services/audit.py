"""Tamper-evident audit logging service for FileGuard.

:class:`AuditService` persists :class:`~fileguard.models.scan_event.ScanEvent`
records to PostgreSQL with an HMAC-SHA256 integrity signature computed over the
canonical immutable fields of each record.  All writes are INSERT-only; the
service contains no UPDATE or DELETE code paths.

Structured JSON log entries carrying ``correlation_id``, ``tenant_id``, and
``scan_id`` are emitted on every successful audit call.

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
            )
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from fileguard.config import settings
from fileguard.models.scan_event import ScanEvent

logger = logging.getLogger(__name__)

# Fields included in HMAC computation (order matters — never reorder).
_HMAC_FIELDS = ("id", "file_hash", "status", "action_taken", "created_at")


class AuditError(Exception):
    """Raised when :class:`AuditService` cannot persist a :class:`ScanEvent`.

    Callers must not silently ignore this exception; the scan pipeline should
    treat an audit write failure as a hard error and surface it to the
    operator.
    """


class AuditService:
    """Append-only audit log service with HMAC-SHA256 integrity signing.

    Each :class:`~fileguard.models.scan_event.ScanEvent` is signed with
    HMAC-SHA256 over the canonical immutable fields
    ``(id, file_hash, status, action_taken, created_at)`` before being
    persisted to PostgreSQL.

    Args:
        secret_key: Raw HMAC secret.  Defaults to ``settings.SECRET_KEY``.
            The key must be kept confidential; leaking it allows an attacker
            to forge signatures.
    """

    def __init__(self, secret_key: str | None = None) -> None:
        raw = secret_key if secret_key is not None else settings.SECRET_KEY
        self._secret_key: bytes = raw.encode("utf-8")

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
    ) -> ScanEvent:
        """Compute an HMAC-SHA256 signature and persist *scan_event*.

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

        return scan_event
