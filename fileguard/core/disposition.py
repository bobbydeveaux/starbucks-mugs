"""DispositionEngine — rule-based file disposition for the FileGuard pipeline.

:class:`DispositionEngine` evaluates AV and PII findings accumulated in a
:class:`~fileguard.core.scan_context.ScanContext` against per-tenant,
per-file-type disposition rules and produces a final
:class:`DispositionResult` of ``block``, ``quarantine``, or ``pass``.

**Fail-secure guarantee:** any unhandled exception during rule evaluation
results in a ``block`` outcome.  A file is *never* silently passed through
when the engine encounters an error.

**Disposition rule schema** (stored as JSONB in ``tenant_config.disposition_rules``):

.. code-block:: json

    {
        "on_error":     "block",
        "on_av_threat": "block",
        "on_pii":       "pass",
        "mime_type_overrides": {
            "application/pdf": {
                "on_pii": "quarantine"
            }
        }
    }

All keys are optional.  The built-in defaults apply whenever a key is absent:

* ``on_error``     → ``"block"``   (scan errors are always fail-secure)
* ``on_av_threat`` → ``"block"``   (AV threats are blocked by default)
* ``on_pii``       → ``"pass"``    (PII triggers a flag but passes through)

Usage::

    from fileguard.core.disposition import DispositionEngine
    from fileguard.core.scan_context import ScanContext

    engine = DispositionEngine()
    ctx = ScanContext(file_bytes=b"...", mime_type="application/pdf")
    # ... run AV and PII pipeline steps ...
    result = await engine.decide(ctx, rules=tenant.disposition_rules)
    print(result.action, result.status)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from fileguard.core.scan_context import ScanContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Action and status types
# ---------------------------------------------------------------------------

Action = Literal["pass", "quarantine", "block"]
Status = Literal["clean", "flagged", "rejected"]

# Severity ordering for PII-based rule evaluation (higher index = higher severity)
_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# Default actions when no rule is specified
_DEFAULT_ON_ERROR = "block"
_DEFAULT_ON_AV_THREAT = "block"
_DEFAULT_ON_PII = "pass"


# ---------------------------------------------------------------------------
# QuarantineService interface
# ---------------------------------------------------------------------------


class QuarantineService(ABC):
    """Abstract interface for the quarantine storage backend.

    The :class:`DispositionEngine` depends on this interface to store
    quarantined files.  Concrete implementations (e.g. S3-backed AES-256
    encrypted store) are injected at construction time.

    This interface allows the DispositionEngine to be tested independently
    of storage infrastructure by substituting a mock.
    """

    @abstractmethod
    async def store(self, context: ScanContext) -> str:
        """Encrypt and store the file bytes from *context* in quarantine.

        Args:
            context: The shared :class:`~fileguard.core.scan_context.ScanContext`
                for the current scan.  The implementation reads
                ``context.file_bytes`` and associates the stored object with
                ``context.scan_id``.

        Returns:
            An opaque quarantine reference string (e.g. an S3 object key or
            a URN) that can be used to retrieve or audit the quarantined file.

        Raises:
            :class:`QuarantineError`: If the file could not be stored.  The
                caller (DispositionEngine) treats this as a hard failure and
                falls back to a ``block`` outcome.
        """


class QuarantineError(Exception):
    """Raised when the quarantine store fails to store a file.

    Callers must treat this as a hard failure and apply fail-secure block
    disposition rather than silently passing the file through.
    """


# ---------------------------------------------------------------------------
# DispositionResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispositionResult:
    """Immutable result of a disposition evaluation.

    Attributes:
        action: The resolved action taken on the file:

            - ``"pass"``       – file is allowed through.
            - ``"quarantine"`` – file was written to quarantine storage.
            - ``"block"``      – file is rejected outright.

        status: Overall verdict derived from the action and findings:

            - ``"clean"``    – action is ``"pass"`` and no findings were
              present.
            - ``"flagged"``  – action is ``"pass"`` but findings were recorded
              (pass-with-flags).
            - ``"rejected"`` – action is ``"block"`` or ``"quarantine"``.

        quarantine_ref: Opaque reference returned by the
            :class:`QuarantineService` when the action is ``"quarantine"``.
            ``None`` for all other actions.
        reasons: Human-readable strings explaining why each rule fired.  Useful
            for audit logs and SIEM event payloads.
    """

    action: Action
    status: Status
    quarantine_ref: str | None = None
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal rule resolution helpers
# ---------------------------------------------------------------------------


def _resolve_action(
    rules: dict[str, Any],
    mime_type: str,
    rule_key: str,
    default: Action,
) -> Action:
    """Return the action for *rule_key*, applying MIME-type overrides.

    Resolution order:
    1. ``rules["mime_type_overrides"][mime_type][rule_key]``
    2. ``rules[rule_key]``
    3. *default*

    Any value that is not a valid :data:`Action` literal is ignored and the
    next level in the resolution chain is tried, so malformed rule entries
    do not crash the engine (fail-secure: unknown values fall through to the
    default).

    Args:
        rules: Disposition rules dict from ``TenantConfig.disposition_rules``.
        mime_type: MIME type of the file being scanned (e.g.
            ``"application/pdf"``).
        rule_key: The rule key to look up (``"on_error"``,
            ``"on_av_threat"``, or ``"on_pii"``).
        default: Fallback action when no valid rule is found.

    Returns:
        The resolved :data:`Action` value.
    """
    valid_actions: frozenset[str] = frozenset({"pass", "quarantine", "block"})

    # Check MIME-type-specific override first
    overrides: dict[str, Any] = rules.get("mime_type_overrides", {}) or {}
    mime_rules: dict[str, Any] = overrides.get(mime_type, {}) or {}
    mime_value = mime_rules.get(rule_key)
    if mime_value in valid_actions:
        return mime_value  # type: ignore[return-value]

    # Fall back to top-level rule
    top_value = rules.get(rule_key)
    if top_value in valid_actions:
        return top_value  # type: ignore[return-value]

    return default


def _derive_status(action: Action, has_findings: bool) -> Status:
    """Derive the overall scan status from the resolved *action* and findings.

    Args:
        action: The resolved disposition action.
        has_findings: ``True`` if the scan context has any findings (AV or PII).

    Returns:
        ``"clean"`` when the file passes with no findings.
        ``"flagged"`` when the file passes but findings were recorded.
        ``"rejected"`` when the file is blocked or quarantined.
    """
    if action in ("block", "quarantine"):
        return "rejected"
    return "flagged" if has_findings else "clean"


# ---------------------------------------------------------------------------
# DispositionEngine
# ---------------------------------------------------------------------------


class DispositionEngine:
    """Evaluates scan findings against disposition rules and resolves an action.

    The engine is stateless after construction.  The same instance can be
    reused concurrently from multiple asyncio tasks.

    Args:
        quarantine_service: Optional :class:`QuarantineService` implementation
            used to store files when the resolved action is ``"quarantine"``.
            When ``None``, a quarantine decision falls back to ``"block"``
            and a warning is logged.

    Example — inline usage::

        engine = DispositionEngine(quarantine_service=my_qs)
        result = await engine.decide(ctx, rules=tenant_config.disposition_rules)
        if result.action == "block":
            raise HTTPException(status_code=403, detail="File rejected")

    Example — no quarantine service::

        engine = DispositionEngine()          # quarantine falls back to block
        result = await engine.decide(ctx)     # uses built-in defaults
    """

    def __init__(
        self,
        quarantine_service: QuarantineService | None = None,
    ) -> None:
        self._quarantine_service = quarantine_service

    # ------------------------------------------------------------------
    # Primary pipeline entry point
    # ------------------------------------------------------------------

    async def decide(
        self,
        context: ScanContext,
        rules: dict[str, Any] | None = None,
    ) -> DispositionResult:
        """Evaluate findings in *context* and return a disposition decision.

        This is the primary pipeline integration point.  It reads
        ``context.findings`` and ``context.errors``, resolves the applicable
        disposition rules, and returns an immutable :class:`DispositionResult`.

        **Fail-secure:** any unhandled exception during rule evaluation is
        caught, logged, and results in a ``block`` outcome.  The file is
        *never* silently passed through on error.

        Args:
            context: The shared :class:`~fileguard.core.scan_context.ScanContext`
                for the current scan.  Read-only — this method does not
                mutate the context.
            rules: Disposition rules dict (typically from
                ``TenantConfig.disposition_rules``).  ``None`` or an empty
                dict applies the built-in fail-secure defaults.

        Returns:
            An immutable :class:`DispositionResult` describing the resolved
            action, derived scan status, optional quarantine reference, and
            the human-readable reasons that drove the decision.
        """
        try:
            return await self._evaluate(context, rules or {})
        except Exception as exc:
            logger.error(
                "DispositionEngine unhandled exception (scan_id=%s): %r — "
                "applying fail-secure block",
                context.scan_id,
                exc,
                exc_info=True,
            )
            return DispositionResult(
                action="block",
                status="rejected",
                quarantine_ref=None,
                reasons=[
                    f"fail-secure: unhandled exception during disposition "
                    f"evaluation: {type(exc).__name__}: {exc}"
                ],
            )

    # ------------------------------------------------------------------
    # Internal evaluation logic
    # ------------------------------------------------------------------

    async def _evaluate(
        self,
        context: ScanContext,
        rules: dict[str, Any],
    ) -> DispositionResult:
        """Core disposition logic (not wrapped in fail-secure catch).

        Separated so that the outer :meth:`decide` can cleanly catch any
        exception that escapes this method.
        """
        reasons: list[str] = []
        mime_type = context.mime_type or ""

        # ---------------------------------------------------------------
        # 1. Scan errors → fail-secure block (highest priority)
        # ---------------------------------------------------------------
        if context.errors:
            error_action = _resolve_action(
                rules, mime_type, "on_error", _DEFAULT_ON_ERROR
            )
            for err in context.errors:
                reasons.append(f"scan error: {err}")

            logger.warning(
                "DispositionEngine: scan_id=%s errors=%d action=%s",
                context.scan_id,
                len(context.errors),
                error_action,
            )

            result = await self._apply_action(
                action=error_action,
                context=context,
                reasons=reasons,
            )
            logger.info(
                "DispositionEngine decision: scan_id=%s action=%s status=%s "
                "reasons=%r",
                context.scan_id,
                result.action,
                result.status,
                result.reasons,
            )
            return result

        # ---------------------------------------------------------------
        # 2. Classify findings
        # ---------------------------------------------------------------
        av_findings = [f for f in context.findings if getattr(f, "type", None) == "av_threat"]
        pii_findings = [f for f in context.findings if getattr(f, "type", None) == "pii"]
        has_findings = bool(av_findings or pii_findings)

        # ---------------------------------------------------------------
        # 3. AV threats → highest-priority action after errors
        # ---------------------------------------------------------------
        if av_findings:
            av_action = _resolve_action(
                rules, mime_type, "on_av_threat", _DEFAULT_ON_AV_THREAT
            )
            for finding in av_findings:
                cat = getattr(finding, "category", "unknown")
                match = getattr(finding, "match", "")
                reasons.append(f"av_threat: category={cat} match={match!r}")

            logger.warning(
                "DispositionEngine: scan_id=%s av_threats=%d action=%s",
                context.scan_id,
                len(av_findings),
                av_action,
            )

            result = await self._apply_action(
                action=av_action,
                context=context,
                reasons=reasons,
            )
            logger.info(
                "DispositionEngine decision: scan_id=%s action=%s status=%s "
                "reasons=%r",
                context.scan_id,
                result.action,
                result.status,
                result.reasons,
            )
            return result

        # ---------------------------------------------------------------
        # 4. PII findings
        # ---------------------------------------------------------------
        if pii_findings:
            pii_action = _resolve_action(
                rules, mime_type, "on_pii", _DEFAULT_ON_PII
            )
            for finding in pii_findings:
                cat = getattr(finding, "category", "unknown")
                sev = getattr(finding, "severity", "unknown")
                reasons.append(f"pii: category={cat} severity={sev}")

            logger.info(
                "DispositionEngine: scan_id=%s pii_findings=%d action=%s",
                context.scan_id,
                len(pii_findings),
                pii_action,
            )

            result = await self._apply_action(
                action=pii_action,
                context=context,
                reasons=reasons,
            )
            logger.info(
                "DispositionEngine decision: scan_id=%s action=%s status=%s "
                "reasons=%r",
                context.scan_id,
                result.action,
                result.status,
                result.reasons,
            )
            return result

        # ---------------------------------------------------------------
        # 5. No findings — clean pass
        # ---------------------------------------------------------------
        logger.info(
            "DispositionEngine decision: scan_id=%s action=pass status=clean",
            context.scan_id,
        )
        return DispositionResult(
            action="pass",
            status="clean",
            quarantine_ref=None,
            reasons=[],
        )

    async def _apply_action(
        self,
        action: Action,
        context: ScanContext,
        reasons: list[str],
    ) -> DispositionResult:
        """Execute the resolved *action* and return a :class:`DispositionResult`.

        For ``"quarantine"`` actions this method delegates to the
        :class:`QuarantineService`.  If no quarantine service is configured,
        or if the service raises :class:`QuarantineError`, the action falls
        back to ``"block"`` (fail-secure).

        Args:
            action: The resolved disposition action.
            context: The current scan context (used by quarantine service).
            reasons: List of human-readable reason strings accumulated by the
                caller.

        Returns:
            A :class:`DispositionResult` with the final action, derived
            status, and quarantine reference (if applicable).
        """
        has_findings = bool(context.findings)

        if action == "quarantine":
            quarantine_ref = await self._store_quarantine(context)
            if quarantine_ref is None:
                # Quarantine failed — fall back to block (fail-secure)
                return DispositionResult(
                    action="block",
                    status="rejected",
                    quarantine_ref=None,
                    reasons=reasons + [
                        "quarantine store unavailable — falling back to block"
                    ],
                )
            return DispositionResult(
                action="quarantine",
                status="rejected",
                quarantine_ref=quarantine_ref,
                reasons=reasons,
            )

        # "block" or "pass"
        status = _derive_status(action, has_findings)
        return DispositionResult(
            action=action,
            status=status,
            quarantine_ref=None,
            reasons=reasons,
        )

    async def _store_quarantine(self, context: ScanContext) -> str | None:
        """Attempt to quarantine the file; return the ref or ``None`` on failure.

        Args:
            context: The current scan context passed to the quarantine service.

        Returns:
            The quarantine reference string, or ``None`` if storage failed or
            no :class:`QuarantineService` is configured.
        """
        if self._quarantine_service is None:
            logger.warning(
                "DispositionEngine: quarantine action requested but no "
                "QuarantineService configured (scan_id=%s) — falling back to block",
                context.scan_id,
            )
            return None

        try:
            ref = await self._quarantine_service.store(context)
            logger.info(
                "DispositionEngine: file quarantined scan_id=%s ref=%r",
                context.scan_id,
                ref,
            )
            return ref
        except QuarantineError as exc:
            logger.error(
                "DispositionEngine: quarantine store failed (scan_id=%s): %r "
                "— falling back to block",
                context.scan_id,
                exc,
            )
            return None
        except Exception as exc:
            logger.error(
                "DispositionEngine: unexpected quarantine error (scan_id=%s): %r "
                "— falling back to block",
                context.scan_id,
                exc,
                exc_info=True,
            )
            return None
