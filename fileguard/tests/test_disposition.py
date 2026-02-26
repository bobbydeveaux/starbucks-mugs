"""Unit tests for DispositionEngine rule evaluation and fail-secure behaviour.

Coverage targets
----------------
* **Pass (clean)** — no findings, no errors → action="pass", status="clean".
* **Pass-with-flags** — PII findings with on_pii="pass" rule → action="pass",
  status="flagged".
* **Block on AV threat** — AV threat findings → action="block",
  status="rejected".
* **Quarantine on PII** — PII findings with on_pii="quarantine" rule and
  configured QuarantineService → action="quarantine", quarantine_ref set.
* **Block (quarantine fallback)** — quarantine action but no service
  configured → action="block".
* **Block on scan error** — context.errors populated → action="block",
  on_error rule respected.
* **Fail-secure exception path** — exception raised during evaluation →
  action="block", status="rejected", reason explains the exception.
* **Rule resolution** — MIME-type overrides take precedence over top-level
  rules; invalid rule values are ignored (default applied).
* **QuarantineService failure** — store() raises QuarantineError → falls
  back to block.
* **_resolve_action helper** — priority order and default fallback.
* **_derive_status helper** — all action/findings combinations.
* **DispositionResult is immutable** (frozen dataclass).
"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure required env vars are present before importing fileguard modules
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-chars!!")

from fileguard.core.disposition import (
    DispositionEngine,
    DispositionResult,
    QuarantineError,
    QuarantineService,
    _DEFAULT_ON_AV_THREAT,
    _DEFAULT_ON_ERROR,
    _DEFAULT_ON_PII,
    _derive_status,
    _resolve_action,
)
from fileguard.core.scan_context import ScanContext


# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------


def make_context(
    mime_type: str = "application/octet-stream",
    findings: list[Any] | None = None,
    errors: list[str] | None = None,
) -> ScanContext:
    """Return a ScanContext with the given attributes pre-populated."""
    ctx = ScanContext(file_bytes=b"test-file-bytes", mime_type=mime_type)
    if findings is not None:
        ctx.findings.extend(findings)
    if errors is not None:
        ctx.errors.extend(errors)
    return ctx


def av_finding(category: str = "Win.Test", match: str = "EICAR") -> MagicMock:
    """Return a mock AV-threat finding."""
    f = MagicMock()
    f.type = "av_threat"
    f.category = category
    f.match = match
    f.severity = "high"
    return f


def pii_finding(
    category: str = "NI_NUMBER", severity: str = "high"
) -> MagicMock:
    """Return a mock PII finding."""
    f = MagicMock()
    f.type = "pii"
    f.category = category
    f.severity = severity
    return f


class FakeQuarantineService(QuarantineService):
    """Test double for QuarantineService that records calls."""

    def __init__(self, ref: str = "quarantine://test-ref-001") -> None:
        self._ref = ref
        self.calls: list[ScanContext] = []

    async def store(self, context: ScanContext) -> str:
        self.calls.append(context)
        return self._ref


class FailingQuarantineService(QuarantineService):
    """Test double that always raises QuarantineError."""

    async def store(self, context: ScanContext) -> str:
        raise QuarantineError("quarantine store unavailable")


class ExplodingQuarantineService(QuarantineService):
    """Test double that raises a generic (non-QuarantineError) exception."""

    async def store(self, context: ScanContext) -> str:
        raise RuntimeError("unexpected storage backend failure")


# ---------------------------------------------------------------------------
# _resolve_action helper
# ---------------------------------------------------------------------------


class TestResolveAction:
    def test_returns_default_when_rules_empty(self):
        result = _resolve_action({}, "application/pdf", "on_pii", "pass")
        assert result == "pass"

    def test_returns_top_level_rule(self):
        rules = {"on_pii": "block"}
        result = _resolve_action(rules, "text/plain", "on_pii", "pass")
        assert result == "block"

    def test_mime_type_override_takes_priority(self):
        rules = {
            "on_pii": "pass",
            "mime_type_overrides": {
                "application/pdf": {"on_pii": "quarantine"},
            },
        }
        result = _resolve_action(rules, "application/pdf", "on_pii", "pass")
        assert result == "quarantine"

    def test_top_level_rule_used_when_no_mime_override(self):
        rules = {
            "on_pii": "block",
            "mime_type_overrides": {
                "application/pdf": {"on_av_threat": "quarantine"},
            },
        }
        result = _resolve_action(rules, "application/pdf", "on_pii", "pass")
        assert result == "block"

    def test_default_used_when_mime_override_has_different_key(self):
        rules = {
            "mime_type_overrides": {
                "application/pdf": {"on_av_threat": "block"},
            },
        }
        result = _resolve_action(rules, "application/pdf", "on_pii", "pass")
        assert result == "pass"

    def test_invalid_value_falls_through_to_default(self):
        rules = {"on_pii": "invalid-action"}
        result = _resolve_action(rules, "text/plain", "on_pii", "quarantine")
        assert result == "quarantine"

    def test_mime_override_invalid_value_falls_through_to_top_level(self):
        rules = {
            "on_pii": "block",
            "mime_type_overrides": {"text/plain": {"on_pii": "bad-value"}},
        }
        result = _resolve_action(rules, "text/plain", "on_pii", "pass")
        assert result == "block"

    def test_none_mime_type_overrides_are_ignored(self):
        # Handles None values in JSONB gracefully
        rules = {"on_pii": "quarantine", "mime_type_overrides": None}
        result = _resolve_action(rules, "application/pdf", "on_pii", "pass")
        assert result == "quarantine"

    def test_all_three_actions_are_valid(self):
        for action in ("pass", "quarantine", "block"):
            rules = {"on_pii": action}
            assert _resolve_action(rules, "text/plain", "on_pii", "pass") == action


# ---------------------------------------------------------------------------
# _derive_status helper
# ---------------------------------------------------------------------------


class TestDeriveStatus:
    def test_clean_when_pass_and_no_findings(self):
        assert _derive_status("pass", False) == "clean"

    def test_flagged_when_pass_and_has_findings(self):
        assert _derive_status("pass", True) == "flagged"

    def test_rejected_when_block(self):
        assert _derive_status("block", False) == "rejected"
        assert _derive_status("block", True) == "rejected"

    def test_rejected_when_quarantine(self):
        assert _derive_status("quarantine", False) == "rejected"
        assert _derive_status("quarantine", True) == "rejected"


# ---------------------------------------------------------------------------
# DispositionResult — structure and immutability
# ---------------------------------------------------------------------------


class TestDispositionResult:
    def test_result_is_immutable(self):
        result = DispositionResult(action="pass", status="clean")
        with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
            result.action = "block"  # type: ignore[misc]

    def test_quarantine_ref_defaults_to_none(self):
        result = DispositionResult(action="pass", status="clean")
        assert result.quarantine_ref is None

    def test_reasons_defaults_to_empty_list(self):
        result = DispositionResult(action="block", status="rejected")
        assert result.reasons == []

    def test_all_fields_populated(self):
        result = DispositionResult(
            action="quarantine",
            status="rejected",
            quarantine_ref="q://ref-123",
            reasons=["av_threat: category=Win.Test"],
        )
        assert result.action == "quarantine"
        assert result.status == "rejected"
        assert result.quarantine_ref == "q://ref-123"
        assert len(result.reasons) == 1


# ---------------------------------------------------------------------------
# DispositionEngine.decide — clean / no-findings path
# ---------------------------------------------------------------------------


class TestCleanPass:
    """Acceptance criterion: pass action when no findings and no errors."""

    @pytest.mark.asyncio
    async def test_no_findings_returns_pass_clean(self):
        engine = DispositionEngine()
        ctx = make_context()
        result = await engine.decide(ctx)
        assert result.action == "pass"
        assert result.status == "clean"
        assert result.quarantine_ref is None
        assert result.reasons == []

    @pytest.mark.asyncio
    async def test_no_findings_with_rules_still_passes(self):
        engine = DispositionEngine()
        ctx = make_context()
        rules = {"on_av_threat": "block", "on_pii": "quarantine"}
        result = await engine.decide(ctx, rules=rules)
        assert result.action == "pass"
        assert result.status == "clean"

    @pytest.mark.asyncio
    async def test_none_rules_treated_as_empty(self):
        engine = DispositionEngine()
        ctx = make_context()
        result = await engine.decide(ctx, rules=None)
        assert result.action == "pass"
        assert result.status == "clean"


# ---------------------------------------------------------------------------
# DispositionEngine.decide — AV threat path
# ---------------------------------------------------------------------------


class TestAVThreatDisposition:
    """Acceptance criterion: block action resolved for AV threats."""

    @pytest.mark.asyncio
    async def test_av_threat_default_block(self):
        engine = DispositionEngine()
        ctx = make_context(findings=[av_finding()])
        result = await engine.decide(ctx)
        assert result.action == "block"
        assert result.status == "rejected"

    @pytest.mark.asyncio
    async def test_av_threat_reason_recorded(self):
        engine = DispositionEngine()
        ctx = make_context(findings=[av_finding(category="Trojan.PDF", match="evil")])
        result = await engine.decide(ctx)
        assert any("av_threat" in r for r in result.reasons)
        assert any("Trojan.PDF" in r for r in result.reasons)

    @pytest.mark.asyncio
    async def test_av_threat_rule_quarantine(self):
        qs = FakeQuarantineService()
        engine = DispositionEngine(quarantine_service=qs)
        ctx = make_context(findings=[av_finding()])
        rules = {"on_av_threat": "quarantine"}
        result = await engine.decide(ctx, rules=rules)
        assert result.action == "quarantine"
        assert result.status == "rejected"
        assert result.quarantine_ref == qs._ref
        assert len(qs.calls) == 1

    @pytest.mark.asyncio
    async def test_av_threat_rule_pass_allowed(self):
        engine = DispositionEngine()
        ctx = make_context(findings=[av_finding()])
        rules = {"on_av_threat": "pass"}
        result = await engine.decide(ctx, rules=rules)
        assert result.action == "pass"
        assert result.status == "flagged"  # findings present → flagged

    @pytest.mark.asyncio
    async def test_av_threat_mime_override(self):
        engine = DispositionEngine()
        ctx = make_context(mime_type="image/png", findings=[av_finding()])
        rules = {
            "on_av_threat": "block",
            "mime_type_overrides": {"image/png": {"on_av_threat": "pass"}},
        }
        result = await engine.decide(ctx, rules=rules)
        assert result.action == "pass"
        assert result.status == "flagged"

    @pytest.mark.asyncio
    async def test_multiple_av_threats_all_recorded_in_reasons(self):
        engine = DispositionEngine()
        findings = [
            av_finding(category="Trojan.Generic", match="evil1"),
            av_finding(category="Win.Test", match="evil2"),
        ]
        ctx = make_context(findings=findings)
        result = await engine.decide(ctx)
        assert result.action == "block"
        # Both findings should appear in reasons
        assert sum(1 for r in result.reasons if "av_threat" in r) == 2


# ---------------------------------------------------------------------------
# DispositionEngine.decide — PII path
# ---------------------------------------------------------------------------


class TestPIIDisposition:
    """Acceptance criterion: pass-with-flags and quarantine for PII findings."""

    @pytest.mark.asyncio
    async def test_pii_default_pass_with_flags(self):
        """Default on_pii is 'pass', so PII findings → pass-with-flags."""
        engine = DispositionEngine()
        ctx = make_context(findings=[pii_finding()])
        result = await engine.decide(ctx)
        assert result.action == "pass"
        assert result.status == "flagged"

    @pytest.mark.asyncio
    async def test_pii_reason_recorded(self):
        engine = DispositionEngine()
        ctx = make_context(findings=[pii_finding(category="NHS_NUMBER", severity="high")])
        result = await engine.decide(ctx)
        assert any("pii" in r for r in result.reasons)
        assert any("NHS_NUMBER" in r for r in result.reasons)

    @pytest.mark.asyncio
    async def test_pii_rule_block(self):
        engine = DispositionEngine()
        ctx = make_context(findings=[pii_finding()])
        rules = {"on_pii": "block"}
        result = await engine.decide(ctx, rules=rules)
        assert result.action == "block"
        assert result.status == "rejected"

    @pytest.mark.asyncio
    async def test_pii_rule_quarantine_with_service(self):
        qs = FakeQuarantineService(ref="s3://quarantine/abc123")
        engine = DispositionEngine(quarantine_service=qs)
        ctx = make_context(
            mime_type="application/pdf",
            findings=[pii_finding()],
        )
        rules = {"on_pii": "quarantine"}
        result = await engine.decide(ctx, rules=rules)
        assert result.action == "quarantine"
        assert result.status == "rejected"
        assert result.quarantine_ref == "s3://quarantine/abc123"
        assert qs.calls[0] is ctx

    @pytest.mark.asyncio
    async def test_pii_mime_override_quarantine(self):
        qs = FakeQuarantineService()
        engine = DispositionEngine(quarantine_service=qs)
        ctx = make_context(mime_type="application/pdf", findings=[pii_finding()])
        rules = {
            "on_pii": "pass",
            "mime_type_overrides": {"application/pdf": {"on_pii": "quarantine"}},
        }
        result = await engine.decide(ctx, rules=rules)
        assert result.action == "quarantine"
        assert result.quarantine_ref is not None

    @pytest.mark.asyncio
    async def test_multiple_pii_findings_all_in_reasons(self):
        engine = DispositionEngine()
        findings = [
            pii_finding(category="NI_NUMBER", severity="high"),
            pii_finding(category="EMAIL", severity="medium"),
        ]
        ctx = make_context(findings=findings)
        result = await engine.decide(ctx)
        pii_reasons = [r for r in result.reasons if "pii" in r]
        assert len(pii_reasons) == 2

    @pytest.mark.asyncio
    async def test_pii_takes_lower_priority_than_av(self):
        """When both AV and PII findings exist, AV rule takes effect."""
        engine = DispositionEngine()
        ctx = make_context(findings=[av_finding(), pii_finding()])
        # Default: on_av_threat=block, on_pii=pass
        result = await engine.decide(ctx)
        # AV threat is evaluated first and results in block
        assert result.action == "block"
        assert result.status == "rejected"
        assert any("av_threat" in r for r in result.reasons)


# ---------------------------------------------------------------------------
# DispositionEngine.decide — scan errors path
# ---------------------------------------------------------------------------


class TestScanErrorDisposition:
    """Acceptance criterion: errors in context trigger fail-secure block."""

    @pytest.mark.asyncio
    async def test_context_errors_trigger_block(self):
        engine = DispositionEngine()
        ctx = make_context(errors=["clamav: connection refused"])
        result = await engine.decide(ctx)
        assert result.action == "block"
        assert result.status == "rejected"

    @pytest.mark.asyncio
    async def test_error_reason_recorded(self):
        engine = DispositionEngine()
        ctx = make_context(errors=["dlp: timeout after 30s"])
        result = await engine.decide(ctx)
        assert any("scan error" in r for r in result.reasons)
        assert any("dlp: timeout" in r for r in result.reasons)

    @pytest.mark.asyncio
    async def test_on_error_rule_quarantine(self):
        qs = FakeQuarantineService()
        engine = DispositionEngine(quarantine_service=qs)
        ctx = make_context(errors=["backend error"])
        rules = {"on_error": "quarantine"}
        result = await engine.decide(ctx, rules=rules)
        assert result.action == "quarantine"
        assert result.quarantine_ref == qs._ref

    @pytest.mark.asyncio
    async def test_errors_take_priority_over_av_findings(self):
        """Errors are evaluated before findings."""
        engine = DispositionEngine()
        ctx = make_context(
            findings=[av_finding()],
            errors=["scan engine crash"],
        )
        result = await engine.decide(ctx)
        assert result.action == "block"
        # Error reason appears
        assert any("scan error" in r for r in result.reasons)

    @pytest.mark.asyncio
    async def test_multiple_errors_all_in_reasons(self):
        engine = DispositionEngine()
        ctx = make_context(errors=["error 1", "error 2"])
        result = await engine.decide(ctx)
        error_reasons = [r for r in result.reasons if "scan error" in r]
        assert len(error_reasons) == 2


# ---------------------------------------------------------------------------
# Quarantine fallback paths
# ---------------------------------------------------------------------------


class TestQuarantineFallback:
    """Acceptance criterion: quarantine falls back to block on failure."""

    @pytest.mark.asyncio
    async def test_no_service_configured_falls_back_to_block(self):
        engine = DispositionEngine(quarantine_service=None)
        ctx = make_context(findings=[pii_finding()])
        rules = {"on_pii": "quarantine"}
        result = await engine.decide(ctx, rules=rules)
        assert result.action == "block"
        assert result.status == "rejected"
        assert result.quarantine_ref is None
        assert any("quarantine" in r.lower() for r in result.reasons)

    @pytest.mark.asyncio
    async def test_quarantine_error_falls_back_to_block(self):
        engine = DispositionEngine(quarantine_service=FailingQuarantineService())
        ctx = make_context(findings=[pii_finding()])
        rules = {"on_pii": "quarantine"}
        result = await engine.decide(ctx, rules=rules)
        assert result.action == "block"
        assert result.status == "rejected"
        assert result.quarantine_ref is None

    @pytest.mark.asyncio
    async def test_unexpected_quarantine_exception_falls_back_to_block(self):
        engine = DispositionEngine(quarantine_service=ExplodingQuarantineService())
        ctx = make_context(findings=[pii_finding()])
        rules = {"on_pii": "quarantine"}
        result = await engine.decide(ctx, rules=rules)
        assert result.action == "block"
        assert result.status == "rejected"


# ---------------------------------------------------------------------------
# Fail-secure exception path (outer catch)
# ---------------------------------------------------------------------------


class TestFailSecureException:
    """Acceptance criterion: unhandled exception → block (never silent pass)."""

    @pytest.mark.asyncio
    async def test_exception_in_evaluate_returns_block(self):
        """Patch the internal _evaluate method to raise unexpectedly."""
        engine = DispositionEngine()
        ctx = make_context()

        with patch.object(
            engine,
            "_evaluate",
            side_effect=RuntimeError("simulated crash"),
        ):
            result = await engine.decide(ctx)

        assert result.action == "block"
        assert result.status == "rejected"
        assert result.quarantine_ref is None
        assert len(result.reasons) == 1
        assert "fail-secure" in result.reasons[0]
        assert "RuntimeError" in result.reasons[0]

    @pytest.mark.asyncio
    async def test_exception_reason_includes_message(self):
        engine = DispositionEngine()
        ctx = make_context()

        with patch.object(
            engine,
            "_evaluate",
            side_effect=ValueError("unexpected schema version"),
        ):
            result = await engine.decide(ctx)

        assert "unexpected schema version" in result.reasons[0]

    @pytest.mark.asyncio
    async def test_exception_never_passes_file_through(self):
        """Regardless of findings, an exception must NEVER result in pass."""
        engine = DispositionEngine()
        ctx = make_context()  # no findings, no errors

        with patch.object(engine, "_evaluate", side_effect=Exception("boom")):
            result = await engine.decide(ctx)

        # File must NOT pass through silently
        assert result.action != "pass"
        assert result.status == "rejected"


# ---------------------------------------------------------------------------
# Rule edge cases
# ---------------------------------------------------------------------------


class TestRuleEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_rules_dict_uses_defaults(self):
        engine = DispositionEngine()
        ctx = make_context(findings=[av_finding()])
        result = await engine.decide(ctx, rules={})
        # Default on_av_threat is "block"
        assert result.action == "block"

    @pytest.mark.asyncio
    async def test_unknown_mime_type_uses_top_level_rule(self):
        engine = DispositionEngine()
        ctx = make_context(
            mime_type="application/x-custom",
            findings=[pii_finding()],
        )
        rules = {
            "on_pii": "block",
            "mime_type_overrides": {"application/pdf": {"on_pii": "pass"}},
        }
        result = await engine.decide(ctx, rules=rules)
        # No override for "application/x-custom" → top-level "block"
        assert result.action == "block"

    @pytest.mark.asyncio
    async def test_invalid_on_pii_value_uses_default_pass(self):
        engine = DispositionEngine()
        ctx = make_context(findings=[pii_finding()])
        rules = {"on_pii": "totally-invalid-action"}
        result = await engine.decide(ctx, rules=rules)
        # Invalid value → default is "pass"
        assert result.action == "pass"
        assert result.status == "flagged"

    @pytest.mark.asyncio
    async def test_findings_mixed_types_av_takes_priority(self):
        engine = DispositionEngine()
        ctx = make_context(
            findings=[pii_finding(), av_finding()],  # PII listed first, AV second
        )
        # Default: on_av_threat=block, on_pii=pass
        result = await engine.decide(ctx)
        assert result.action == "block"


# ---------------------------------------------------------------------------
# QuarantineService interface
# ---------------------------------------------------------------------------


class TestQuarantineServiceInterface:
    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            QuarantineService()  # type: ignore[abstract]

    def test_fake_service_implements_interface(self):
        qs = FakeQuarantineService()
        assert isinstance(qs, QuarantineService)

    def test_quarantine_error_is_exception(self):
        err = QuarantineError("store failed")
        assert isinstance(err, Exception)

    @pytest.mark.asyncio
    async def test_fake_service_returns_ref(self):
        qs = FakeQuarantineService(ref="my-ref")
        ctx = make_context()
        ref = await qs.store(ctx)
        assert ref == "my-ref"
        assert ctx in qs.calls
