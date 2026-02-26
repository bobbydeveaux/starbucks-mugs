"""Unit tests for fileguard/core/redaction.py.

Coverage targets aligned with task acceptance criteria:

* Zero findings — text is returned unchanged.
* Single span — one PII match is replaced with the token.
* Multiple non-overlapping spans — each span is replaced independently,
  preserving surrounding text exactly.
* Overlapping spans — two findings that share characters are merged into a
  single replacement token (no double-redaction).
* Adjacent spans — spans that touch end-to-end are merged.
* Repeated matches — the same PII value appearing more than once is
  redacted at every occurrence.
* Custom token — callers can supply a token other than the default.
* Empty / None extracted_text — engine returns an empty string immediately.
* Non-PII findings (e.g. AV findings) are ignored by the engine.
* ScanContext integration — redact() reads context.findings and
  context.extracted_text without mutating either.
* Character-level diff — non-PII characters are preserved byte-for-byte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import pytest

from fileguard.core.pii_detector import PIIFinding
from fileguard.core.redaction import RedactionEngine
from fileguard.core.scan_context import ScanContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_context(
    text: str | None,
    findings: list | None = None,
) -> ScanContext:
    """Create a ScanContext pre-populated with extracted_text and findings."""
    ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
    ctx.extracted_text = text
    if findings is not None:
        ctx.findings = list(findings)
    return ctx


def make_finding(match: str, category: str = "EMAIL") -> PIIFinding:
    """Return a PIIFinding for *match* with a dummy byte offset."""
    return PIIFinding(
        type="pii",
        category=category,
        severity="medium",
        match=match,
        offset=-1,
    )


# ---------------------------------------------------------------------------
# Zero findings
# ---------------------------------------------------------------------------


class TestZeroFindings:
    """Acceptance criterion: zero findings → text returned unchanged."""

    def test_no_findings_returns_original_text(self):
        engine = RedactionEngine()
        ctx = make_context("Hello, world. No PII here.")
        result = engine.redact(ctx)
        assert result == "Hello, world. No PII here."

    def test_no_findings_preserves_whitespace(self):
        engine = RedactionEngine()
        text = "Line one.\nLine two.\n  Indented."
        ctx = make_context(text)
        result = engine.redact(ctx)
        assert result == text

    def test_no_findings_preserves_special_chars(self):
        engine = RedactionEngine()
        text = "Price: £42.00 (VAT inc.) — order ref: #001"
        ctx = make_context(text)
        result = engine.redact(ctx)
        assert result == text


# ---------------------------------------------------------------------------
# Empty / None extracted_text
# ---------------------------------------------------------------------------


class TestEmptyText:
    """Engine must handle missing text gracefully."""

    def test_none_extracted_text_returns_empty_string(self):
        engine = RedactionEngine()
        ctx = make_context(None, findings=[make_finding("alice@example.com")])
        assert engine.redact(ctx) == ""

    def test_empty_string_returns_empty_string(self):
        engine = RedactionEngine()
        ctx = make_context("", findings=[make_finding("alice@example.com")])
        assert engine.redact(ctx) == ""

    def test_no_findings_and_none_text_returns_empty_string(self):
        engine = RedactionEngine()
        ctx = make_context(None)
        assert engine.redact(ctx) == ""


# ---------------------------------------------------------------------------
# Single span
# ---------------------------------------------------------------------------


class TestSingleSpan:
    """Acceptance criterion: single span → replaced, surrounding text intact."""

    def test_single_email_replaced(self):
        engine = RedactionEngine()
        text = "Contact: alice@example.com for details."
        ctx = make_context(text, findings=[make_finding("alice@example.com")])
        result = engine.redact(ctx)
        assert "alice@example.com" not in result
        assert "[REDACTED]" in result
        assert result.startswith("Contact: ")
        assert result.endswith(" for details.")

    def test_single_ni_number_replaced(self):
        engine = RedactionEngine()
        text = "NI: AB123456C."
        ctx = make_context(text, findings=[make_finding("AB123456C", "NI_NUMBER")])
        result = engine.redact(ctx)
        assert result == "NI: [REDACTED]."

    def test_single_span_at_start_of_text(self):
        engine = RedactionEngine()
        text = "AB123456C is a valid NI number."
        ctx = make_context(text, findings=[make_finding("AB123456C", "NI_NUMBER")])
        result = engine.redact(ctx)
        assert result == "[REDACTED] is a valid NI number."

    def test_single_span_at_end_of_text(self):
        engine = RedactionEngine()
        text = "Patient email: alice@nhs.uk"
        ctx = make_context(text, findings=[make_finding("alice@nhs.uk")])
        result = engine.redact(ctx)
        assert result == "Patient email: [REDACTED]"

    def test_single_span_entire_text(self):
        engine = RedactionEngine()
        text = "alice@nhs.uk"
        ctx = make_context(text, findings=[make_finding("alice@nhs.uk")])
        result = engine.redact(ctx)
        assert result == "[REDACTED]"


# ---------------------------------------------------------------------------
# Multiple non-overlapping spans
# ---------------------------------------------------------------------------


class TestMultipleNonOverlappingSpans:
    """Acceptance criterion: multiple non-overlapping spans."""

    def test_two_emails_both_replaced(self):
        engine = RedactionEngine()
        text = "From: alice@example.com To: bob@example.org"
        ctx = make_context(
            text,
            findings=[
                make_finding("alice@example.com"),
                make_finding("bob@example.org"),
            ],
        )
        result = engine.redact(ctx)
        assert "alice@example.com" not in result
        assert "bob@example.org" not in result
        assert result.count("[REDACTED]") == 2
        assert "From: " in result
        assert " To: " in result

    def test_three_different_pii_types_all_replaced(self):
        engine = RedactionEngine()
        text = (
            "Name: John Smith, NI: AB123456C, "
            "email: john@nhs.uk, phone: 07700 900123"
        )
        ctx = make_context(
            text,
            findings=[
                make_finding("AB123456C", "NI_NUMBER"),
                make_finding("john@nhs.uk", "EMAIL"),
                make_finding("07700 900123", "PHONE"),
            ],
        )
        result = engine.redact(ctx)
        assert "AB123456C" not in result
        assert "john@nhs.uk" not in result
        assert "07700 900123" not in result
        assert result.count("[REDACTED]") == 3

    def test_non_pii_text_preserved_exactly(self):
        engine = RedactionEngine()
        text = "prefix alice@example.com suffix"
        ctx = make_context(text, findings=[make_finding("alice@example.com")])
        result = engine.redact(ctx)
        assert result == "prefix [REDACTED] suffix"

    def test_order_of_replacements_is_correct(self):
        """Spans processed left-to-right; result segments maintain correct order."""
        engine = RedactionEngine()
        text = "A: aa@a.com B: bb@b.com C: cc@c.com"
        ctx = make_context(
            text,
            findings=[
                make_finding("aa@a.com"),
                make_finding("bb@b.com"),
                make_finding("cc@c.com"),
            ],
        )
        result = engine.redact(ctx)
        assert result == "A: [REDACTED] B: [REDACTED] C: [REDACTED]"


# ---------------------------------------------------------------------------
# Overlapping spans
# ---------------------------------------------------------------------------


class TestOverlappingSpans:
    """Acceptance criterion: overlapping spans are merged into one token."""

    def test_two_findings_same_span_produce_one_token(self):
        """Two findings with the same match string → single [REDACTED]."""
        engine = RedactionEngine()
        text = "Value: SECRET"
        # Two patterns both match the same "SECRET" span.
        findings = [
            make_finding("SECRET", "PATTERN_A"),
            make_finding("SECRET", "PATTERN_B"),
        ]
        ctx = make_context(text, findings=findings)
        result = engine.redact(ctx)
        assert result == "Value: [REDACTED]"
        assert result.count("[REDACTED]") == 1

    def test_fully_contained_span_is_merged(self):
        """A span fully inside another produces one merged replacement."""
        engine = RedactionEngine()
        text = "Data: 07700 900123 end"
        # Simulate one finding for the full number and another for a sub-match.
        findings = [
            make_finding("07700 900123", "PHONE"),
            make_finding("900123", "NHS_PARTIAL"),
        ]
        ctx = make_context(text, findings=findings)
        result = engine.redact(ctx)
        # The whole span should be one [REDACTED]; no double-token.
        assert result.count("[REDACTED]") == 1
        assert "07700" not in result
        assert "900123" not in result

    def test_partially_overlapping_spans_merged(self):
        """Partially overlapping spans merge into a single token."""
        engine = RedactionEngine()
        # Manually construct overlapping spans by using two findings whose
        # match strings overlap within the text.
        text = "ABCDEF"
        # "ABCD" spans (0,4); "CDEF" spans (2,6) — they overlap at (2,4).
        findings = [
            make_finding("ABCD", "CAT_A"),
            make_finding("CDEF", "CAT_B"),
        ]
        ctx = make_context(text, findings=findings)
        result = engine.redact(ctx)
        assert result == "[REDACTED]"
        assert result.count("[REDACTED]") == 1


# ---------------------------------------------------------------------------
# Adjacent spans
# ---------------------------------------------------------------------------


class TestAdjacentSpans:
    """Adjacent spans (touching end-to-end) are merged into one token."""

    def test_adjacent_spans_merged(self):
        engine = RedactionEngine()
        # "AB" ends at index 2; "CD" starts at index 2 — they are adjacent.
        text = "ABCD"
        findings = [
            make_finding("AB", "CAT_A"),
            make_finding("CD", "CAT_B"),
        ]
        ctx = make_context(text, findings=findings)
        result = engine.redact(ctx)
        assert result == "[REDACTED]"

    def test_non_adjacent_spans_not_merged(self):
        engine = RedactionEngine()
        text = "AB_CD"
        findings = [
            make_finding("AB", "CAT_A"),
            make_finding("CD", "CAT_B"),
        ]
        ctx = make_context(text, findings=findings)
        result = engine.redact(ctx)
        # There is a "_" between them — they should produce two tokens.
        assert result == "[REDACTED]_[REDACTED]"
        assert result.count("[REDACTED]") == 2


# ---------------------------------------------------------------------------
# Repeated matches
# ---------------------------------------------------------------------------


class TestRepeatedMatches:
    """Each occurrence of a PII value is redacted, not just the first."""

    def test_same_email_twice_both_redacted(self):
        engine = RedactionEngine()
        text = "From: alice@example.com CC: alice@example.com"
        # Even a single finding for "alice@example.com" should redact both
        # occurrences, since we search all positions.
        ctx = make_context(text, findings=[make_finding("alice@example.com")])
        result = engine.redact(ctx)
        assert "alice@example.com" not in result
        assert result.count("[REDACTED]") == 2

    def test_duplicate_findings_do_not_cause_double_tokens(self):
        """Two PIIFinding objects with the same match produce one set of replacements."""
        engine = RedactionEngine()
        text = "email: alice@example.com"
        # Two identical findings (e.g. two patterns both matched the same span).
        findings = [
            make_finding("alice@example.com"),
            make_finding("alice@example.com"),
        ]
        ctx = make_context(text, findings=findings)
        result = engine.redact(ctx)
        assert result == "email: [REDACTED]"

    def test_three_occurrences_all_replaced(self):
        engine = RedactionEngine()
        text = "a a a"
        ctx = make_context(text, findings=[make_finding("a", "CHAR")])
        result = engine.redact(ctx)
        assert result == "[REDACTED] [REDACTED] [REDACTED]"


# ---------------------------------------------------------------------------
# Custom token
# ---------------------------------------------------------------------------


class TestCustomToken:
    def test_custom_token_used_in_output(self):
        engine = RedactionEngine(token="[PII REMOVED]")
        ctx = make_context(
            "email: alice@example.com",
            findings=[make_finding("alice@example.com")],
        )
        result = engine.redact(ctx)
        assert result == "email: [PII REMOVED]"
        assert "[REDACTED]" not in result

    def test_empty_token_removes_pii(self):
        engine = RedactionEngine(token="")
        ctx = make_context(
            "prefix alice@example.com suffix",
            findings=[make_finding("alice@example.com")],
        )
        result = engine.redact(ctx)
        assert result == "prefix  suffix"

    def test_default_token_is_redacted(self):
        assert RedactionEngine.DEFAULT_TOKEN == "[REDACTED]"
        engine = RedactionEngine()
        assert engine._token == "[REDACTED]"


# ---------------------------------------------------------------------------
# Non-PII findings are ignored
# ---------------------------------------------------------------------------


@dataclass
class _AVFinding:
    """Minimal fake AV finding (not a PIIFinding)."""

    type: Literal["av"] = "av"
    threat: str = "Eicar-Test-Signature"


class TestNonPIIFindingsIgnored:
    """Non-PIIFinding objects in context.findings must not cause errors."""

    def test_av_finding_is_ignored(self):
        engine = RedactionEngine()
        text = "clean text with no PII"
        ctx = make_context(text, findings=[_AVFinding()])
        result = engine.redact(ctx)
        assert result == text

    def test_mixed_findings_only_pii_redacted(self):
        engine = RedactionEngine()
        text = "email: alice@example.com threat: none"
        ctx = make_context(
            text,
            findings=[
                _AVFinding(),
                make_finding("alice@example.com"),
            ],
        )
        result = engine.redact(ctx)
        assert "alice@example.com" not in result
        assert "[REDACTED]" in result


# ---------------------------------------------------------------------------
# ScanContext not mutated
# ---------------------------------------------------------------------------


class TestContextNotMutated:
    """redact() must not modify context.extracted_text or context.findings."""

    def test_extracted_text_unchanged(self):
        engine = RedactionEngine()
        text = "email: alice@example.com"
        ctx = make_context(text, findings=[make_finding("alice@example.com")])
        engine.redact(ctx)
        assert ctx.extracted_text == text

    def test_findings_list_unchanged(self):
        engine = RedactionEngine()
        finding = make_finding("alice@example.com")
        ctx = make_context(
            "email: alice@example.com",
            findings=[finding],
        )
        original_findings = list(ctx.findings)
        engine.redact(ctx)
        assert ctx.findings == original_findings


# ---------------------------------------------------------------------------
# Character-level diff
# ---------------------------------------------------------------------------


class TestCharacterLevelDiff:
    """Non-PII characters are preserved byte-for-byte."""

    def test_prefix_preserved_exactly(self):
        engine = RedactionEngine()
        text = "KEEP_THIS alice@example.com END"
        ctx = make_context(text, findings=[make_finding("alice@example.com")])
        result = engine.redact(ctx)
        assert result.startswith("KEEP_THIS ")
        assert result.endswith(" END")

    def test_unicode_preserved_in_non_pii_segments(self):
        engine = RedactionEngine()
        text = "Héllo wörld: alice@example.com — fin"
        ctx = make_context(text, findings=[make_finding("alice@example.com")])
        result = engine.redact(ctx)
        assert result == "Héllo wörld: [REDACTED] — fin"

    def test_newlines_in_non_pii_segments_preserved(self):
        engine = RedactionEngine()
        text = "Line 1\nalice@example.com\nLine 3"
        ctx = make_context(text, findings=[make_finding("alice@example.com")])
        result = engine.redact(ctx)
        assert result == "Line 1\n[REDACTED]\nLine 3"


# ---------------------------------------------------------------------------
# Internal helpers (unit-level)
# ---------------------------------------------------------------------------


class TestMergeSpans:
    """Directly test _merge_spans for correctness."""

    def test_empty_input(self):
        assert RedactionEngine._merge_spans([]) == []

    def test_single_span(self):
        assert RedactionEngine._merge_spans([(0, 5)]) == [(0, 5)]

    def test_non_overlapping_spans_unchanged(self):
        assert RedactionEngine._merge_spans([(0, 3), (5, 8)]) == [(0, 3), (5, 8)]

    def test_adjacent_spans_merged(self):
        assert RedactionEngine._merge_spans([(0, 3), (3, 6)]) == [(0, 6)]

    def test_overlapping_spans_merged(self):
        assert RedactionEngine._merge_spans([(0, 5), (3, 8)]) == [(0, 8)]

    def test_contained_span_merged(self):
        assert RedactionEngine._merge_spans([(0, 10), (2, 5)]) == [(0, 10)]

    def test_unsorted_input_handled(self):
        # Input is out of order; _merge_spans sorts before merging.
        assert RedactionEngine._merge_spans([(5, 8), (0, 3)]) == [(0, 3), (5, 8)]

    def test_three_spans_two_overlapping(self):
        assert RedactionEngine._merge_spans([(0, 4), (3, 7), (10, 14)]) == [
            (0, 7),
            (10, 14),
        ]

    def test_all_spans_merged_into_one(self):
        assert RedactionEngine._merge_spans([(0, 3), (2, 5), (4, 7)]) == [(0, 7)]


class TestCollectSpans:
    """Directly test _collect_spans for correctness."""

    def test_single_match_found(self):
        engine = RedactionEngine()
        text = "foo alice@example.com bar"
        findings = [make_finding("alice@example.com")]
        spans = engine._collect_spans(text, findings)
        assert (4, 21) in spans

    def test_two_occurrences_both_found(self):
        engine = RedactionEngine()
        text = "a@b.com and a@b.com"
        findings = [make_finding("a@b.com")]
        spans = engine._collect_spans(text, findings)
        assert len(spans) == 2

    def test_match_not_in_text_produces_no_span(self):
        engine = RedactionEngine()
        text = "no email here"
        findings = [make_finding("missing@example.com")]
        spans = engine._collect_spans(text, findings)
        assert spans == []

    def test_empty_match_string_skipped(self):
        engine = RedactionEngine()
        finding = PIIFinding(type="pii", category="X", severity="low", match="", offset=-1)
        spans = engine._collect_spans("some text", [finding])
        assert spans == []

    def test_duplicate_findings_deduplicated(self):
        """Two findings with the same match → one pass, not two."""
        engine = RedactionEngine()
        text = "alice@example.com"
        findings = [
            make_finding("alice@example.com"),
            make_finding("alice@example.com"),
        ]
        spans = engine._collect_spans(text, findings)
        # Only one span at (0, 17), not duplicated.
        assert len(spans) == 1

    def test_special_regex_chars_in_match_escaped(self):
        """Match values containing regex metacharacters are treated literally."""
        engine = RedactionEngine()
        text = "user+tag@domain.org"
        findings = [make_finding("user+tag@domain.org")]
        spans = engine._collect_spans(text, findings)
        assert len(spans) == 1
        assert (0, 19) in spans
