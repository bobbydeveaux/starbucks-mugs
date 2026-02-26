"""Unit tests for fileguard/core/redaction.py and related storage.

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
* Byte-offset reverse-map used when offset != -1.
* Substring fallback when offset == -1 or byte_offsets is empty.

* RedactedFileStorage
  - store_and_sign() writes a file and returns a valid signed URL
  - verify_signature() returns True for a fresh URL
  - verify_signature() returns False when the URL has expired
  - verify_signature() returns False when the HMAC is tampered
  - retrieve() returns the stored bytes
  - retrieve() returns None for unknown file_id
  - URL contains expected query parameters (expires, sig)
  - TTL is honoured: URL expires after configured seconds
  - Path traversal characters are stripped from file_id in storage

* Integration scenario (signed URL round-trip)
  - Store redacted content → parse signed URL → verify → retrieve → check content
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import Literal
from unittest.mock import patch

import pytest

from fileguard.core.pii_detector import PIIFinding
from fileguard.core.redaction import RedactionEngine
from fileguard.core.scan_context import ScanContext
from fileguard.services.storage import RedactedFileStorage

# Also expose the module-level constant alias used by origin/main tests.
REDACTED_TOKEN = RedactionEngine.DEFAULT_TOKEN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_context(
    text: str | None,
    findings: list | None = None,
    byte_offsets: list[int] | None = None,
) -> ScanContext:
    """Create a ScanContext pre-populated with extracted_text and findings."""
    ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
    ctx.extracted_text = text
    if findings is not None:
        ctx.findings = list(findings)
    if byte_offsets is not None:
        ctx.byte_offsets = byte_offsets
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


def _make_finding(match: str, offset: int = -1) -> PIIFinding:
    """Create a PIIFinding object for tests (origin/main compatible helper)."""
    return PIIFinding(
        type="pii",
        category="TEST",
        severity="high",
        match=match,
        offset=offset,
    )


def _make_ctx(
    text: str | None,
    byte_offsets: list[int] | None = None,
) -> ScanContext:
    """Create a ScanContext (origin/main compatible helper)."""
    ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
    ctx.extracted_text = text
    if byte_offsets is not None:
        ctx.byte_offsets = byte_offsets
    return ctx


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
# RedactionEngine — zero findings (origin/main variants)
# ---------------------------------------------------------------------------


class TestRedactNoFindings:
    def test_empty_findings_returns_text_unchanged(self):
        engine = RedactionEngine()
        ctx = _make_ctx("hello world")
        assert engine.redact(ctx) == "hello world"

    def test_non_pii_findings_are_ignored(self):
        from types import SimpleNamespace

        engine = RedactionEngine()
        ctx = _make_ctx("hello world")
        ctx.findings = [
            SimpleNamespace(type="av_threat", category="EICAR", severity="critical",
                            match="hello", offset=0)
        ]
        assert engine.redact(ctx) == "hello world"

    def test_empty_text_returns_empty_string(self):
        engine = RedactionEngine()
        ctx = _make_ctx("")
        assert engine.redact(ctx) == ""

    def test_none_text_returns_empty_string(self):
        engine = RedactionEngine()
        ctx = _make_ctx(None)
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
# RedactionEngine — single span (origin/main variants with byte offsets)
# ---------------------------------------------------------------------------


class TestRedactSingleSpan:
    def test_single_match_replaced_with_token(self):
        engine = RedactionEngine()
        text = "NI: AB123456C is sensitive"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [_make_finding("AB123456C", offset=4)]
        result = engine.redact(ctx)
        assert REDACTED_TOKEN in result
        assert "AB123456C" not in result
        assert result.startswith("NI: ")
        assert result.endswith(" is sensitive")

    def test_leading_match_replaced(self):
        engine = RedactionEngine()
        text = "AB123456C is sensitive"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [_make_finding("AB123456C", offset=0)]
        result = engine.redact(ctx)
        assert result.startswith(REDACTED_TOKEN)
        assert "AB123456C" not in result

    def test_trailing_match_replaced(self):
        engine = RedactionEngine()
        text = "Contact: alice@example.com"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [_make_finding("alice@example.com", offset=9)]
        result = engine.redact(ctx)
        assert result.endswith(REDACTED_TOKEN)
        assert "alice@example.com" not in result

    def test_non_pii_content_preserved_exactly(self):
        engine = RedactionEngine()
        text = "Name: John, NI: AB123456C, DOB: 01-01-1990"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [_make_finding("AB123456C", offset=16)]
        result = engine.redact(ctx)
        expected = f"Name: John, NI: {REDACTED_TOKEN}, DOB: 01-01-1990"
        assert result == expected


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
# RedactionEngine — multiple non-overlapping spans (origin/main variants)
# ---------------------------------------------------------------------------


class TestRedactMultipleSpans:
    def test_two_non_overlapping_spans_both_redacted(self):
        engine = RedactionEngine()
        text = "NI: AB123456C, email: alice@example.com"
        ctx = _make_ctx(text, list(range(len(text))))
        ni_offset = text.index("AB123456C")
        email_offset = text.index("alice@example.com")
        ctx.findings = [
            _make_finding("AB123456C", offset=ni_offset),
            _make_finding("alice@example.com", offset=email_offset),
        ]
        result = engine.redact(ctx)
        assert "AB123456C" not in result
        assert "alice@example.com" not in result
        assert result.count(REDACTED_TOKEN) == 2

    def test_order_of_findings_does_not_matter(self):
        engine = RedactionEngine()
        text = "a@b.com and c@d.com are both PII"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [
            _make_finding("c@d.com", offset=text.index("c@d.com")),
            _make_finding("a@b.com", offset=text.index("a@b.com")),
        ]
        result = engine.redact(ctx)
        assert "a@b.com" not in result
        assert "c@d.com" not in result
        assert result.count(REDACTED_TOKEN) == 2

    def test_surrounding_text_preserved(self):
        engine = RedactionEngine()
        text = "prefix MATCH1 middle MATCH2 suffix"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [
            _make_finding("MATCH1", offset=text.index("MATCH1")),
            _make_finding("MATCH2", offset=text.index("MATCH2")),
        ]
        result = engine.redact(ctx)
        assert "prefix" in result
        assert "middle" in result
        assert "suffix" in result


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
# RedactionEngine — overlapping and adjacent spans (origin/main variants)
# ---------------------------------------------------------------------------


class TestRedactOverlappingSpans:
    """Acceptance criterion: overlapping spans are merged before substitution."""

    def test_overlapping_spans_merged_into_one(self):
        # Simulate two patterns that both match in the range [0, 5)
        engine = RedactionEngine()
        text = "SECRET_DATA extra"
        ctx = _make_ctx(text, list(range(len(text))))
        # Both findings match the same range
        ctx.findings = [
            _make_finding("SECRET", offset=0),
            _make_finding("SECRE", offset=0),
        ]
        result = engine.redact(ctx)
        # Only one [REDACTED] token should appear (merged)
        assert result.count(REDACTED_TOKEN) == 1
        # Neither match string should remain
        assert "SECRET" not in result

    def test_adjacent_spans_merged(self):
        # Span1 ends where Span2 begins (touching)
        engine = RedactionEngine()
        text = "AABB extra"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [
            _make_finding("AA", offset=0),
            _make_finding("BB", offset=2),  # starts exactly where AA ends
        ]
        result = engine.redact(ctx)
        # Should be treated as a single merged span covering "AABB"
        assert result.count(REDACTED_TOKEN) == 1
        assert "AABB" not in result

    def test_non_overlapping_spans_produce_separate_tokens(self):
        engine = RedactionEngine()
        text = "AA xx BB"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [
            _make_finding("AA", offset=0),
            _make_finding("BB", offset=6),
        ]
        result = engine.redact(ctx)
        assert result.count(REDACTED_TOKEN) == 2


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
# Byte-offset mapping
# ---------------------------------------------------------------------------


class TestByteOffsetMapping:
    def test_byte_offset_used_for_span_location(self):
        """When byte_offsets is correct, span is found via reverse map."""
        engine = RedactionEngine()
        text = "prefix MATCH suffix"
        # Identity mapping: char_idx == byte_offset
        byte_offsets = list(range(len(text)))
        ctx = _make_ctx(text, byte_offsets)
        match_char_idx = text.index("MATCH")
        ctx.findings = [_make_finding("MATCH", offset=match_char_idx)]
        result = engine.redact(ctx)
        assert "MATCH" not in result
        assert REDACTED_TOKEN in result

    def test_fallback_to_substring_search_when_offset_minus_one(self):
        """offset=-1 triggers substring search instead of reverse map lookup."""
        engine = RedactionEngine()
        text = "prefix MATCH suffix"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [_make_finding("MATCH", offset=-1)]
        result = engine.redact(ctx)
        assert "MATCH" not in result
        assert REDACTED_TOKEN in result

    def test_fallback_when_byte_offsets_empty(self):
        """Empty byte_offsets → reverse map empty → substring search used."""
        engine = RedactionEngine()
        text = "Call 07700 900123 now"
        ctx = _make_ctx(text, [])
        ctx.findings = [_make_finding("07700 900123", offset=5)]
        result = engine.redact(ctx)
        assert "07700 900123" not in result
        assert REDACTED_TOKEN in result

    def test_byte_offset_mismatch_falls_back_to_search(self):
        """If byte-offset map gives wrong char position, search fallback is used."""
        engine = RedactionEngine()
        text = "hello world"
        # Deliberately wrong byte_offsets (all zeros)
        ctx = _make_ctx(text, [0] * len(text))
        ctx.findings = [_make_finding("world", offset=6)]
        result = engine.redact(ctx)
        # Should still find and redact "world" via substring search
        assert "world" not in result
        assert REDACTED_TOKEN in result


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

    # Additional variants from origin/main
    engine = RedactionEngine()

    def test_empty_input_returns_empty(self):
        assert self.engine._merge_spans([]) == []

    def test_single_span_unchanged(self):
        assert self.engine._merge_spans([(3, 7)]) == [(3, 7)]

    def test_non_overlapping_sorted(self):
        result = self.engine._merge_spans([(0, 3), (5, 8)])
        assert result == [(0, 3), (5, 8)]

    def test_overlapping_merged(self):
        result = self.engine._merge_spans([(0, 5), (3, 9)])
        assert result == [(0, 9)]

    def test_adjacent_merged(self):
        result = self.engine._merge_spans([(0, 3), (3, 6)])
        assert result == [(0, 6)]

    def test_unsorted_input_sorted_and_merged(self):
        result = self.engine._merge_spans([(5, 9), (0, 3), (2, 6)])
        assert result == [(0, 9)]

    def test_completely_contained_span_merged(self):
        result = self.engine._merge_spans([(0, 10), (2, 5)])
        assert result == [(0, 10)]


class TestCollectSpans:
    """Directly test _collect_spans for correctness."""

    def test_single_match_found(self):
        engine = RedactionEngine()
        text = "foo alice@example.com bar"
        findings = [make_finding("alice@example.com")]
        spans = engine._collect_spans(text, findings, {})
        assert (4, 21) in spans

    def test_two_occurrences_both_found(self):
        engine = RedactionEngine()
        text = "a@b.com and a@b.com"
        findings = [make_finding("a@b.com")]
        spans = engine._collect_spans(text, findings, {})
        assert len(spans) == 2

    def test_match_not_in_text_produces_no_span(self):
        engine = RedactionEngine()
        text = "no email here"
        findings = [make_finding("missing@example.com")]
        spans = engine._collect_spans(text, findings, {})
        assert spans == []

    def test_empty_match_string_skipped(self):
        engine = RedactionEngine()
        finding = PIIFinding(type="pii", category="X", severity="low", match="", offset=-1)
        spans = engine._collect_spans("some text", [finding], {})
        assert spans == []

    def test_duplicate_findings_deduplicated(self):
        """Two findings with the same match → one pass, not two."""
        engine = RedactionEngine()
        text = "alice@example.com"
        findings = [
            make_finding("alice@example.com"),
            make_finding("alice@example.com"),
        ]
        spans = engine._collect_spans(text, findings, {})
        # Only one span at (0, 17), not duplicated.
        assert len(spans) == 1

    def test_special_regex_chars_in_match_escaped(self):
        """Match values containing regex metacharacters are treated literally."""
        engine = RedactionEngine()
        text = "user+tag@domain.org"
        findings = [make_finding("user+tag@domain.org")]
        spans = engine._collect_spans(text, findings, {})
        assert len(spans) == 1
        assert (0, 19) in spans

    def test_byte_offset_used_when_valid(self):
        """When byte_to_char provides a valid mapping, it is used."""
        engine = RedactionEngine()
        text = "prefix MATCH suffix"
        byte_to_char = {7: 7}  # identity mapping for 'M' at index 7
        findings = [_make_finding("MATCH", offset=7)]
        spans = engine._collect_spans(text, findings, byte_to_char)
        assert (7, 12) in spans


# ---------------------------------------------------------------------------
# ScanContext integration
# ---------------------------------------------------------------------------


class TestScanContextIntegration:
    def test_scan_id_unchanged_after_redact(self):
        engine = RedactionEngine()
        ctx = _make_ctx("test text")
        original_id = ctx.scan_id
        engine.redact(ctx)
        assert ctx.scan_id == original_id

    def test_findings_list_not_modified(self):
        engine = RedactionEngine()
        text = "AB123456C"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [_make_finding("AB123456C", offset=0)]
        original_findings = list(ctx.findings)
        engine.redact(ctx)
        assert ctx.findings == original_findings

    def test_request_redaction_flag_accessible(self):
        ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
        assert ctx.request_redaction is False
        ctx.request_redaction = True
        assert ctx.request_redaction is True

    def test_redacted_file_url_initially_none(self):
        ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
        assert ctx.redacted_file_url is None

    def test_redacted_file_url_can_be_set(self):
        ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
        ctx.redacted_file_url = "https://example.com/v1/redacted/abc?expires=1&sig=xyz"
        assert ctx.redacted_file_url is not None


# ---------------------------------------------------------------------------
# RedactedFileStorage — basic operations
# ---------------------------------------------------------------------------


class TestRedactedFileStorageBasic:
    def _make_storage(self, tmp_path, ttl: int = 3600) -> RedactedFileStorage:
        return RedactedFileStorage(
            base_url="http://localhost:8000",
            storage_dir=str(tmp_path),
            secret_key="test-secret-key-32-chars-xxxxxxxxx",
        )

    def test_store_and_sign_returns_url_string(self, tmp_path):
        storage = self._make_storage(tmp_path)
        url = storage.store_and_sign("redacted content", scan_id="scan-abc")
        assert isinstance(url, str)
        assert url.startswith("http://localhost:8000/v1/redacted/")

    def test_url_contains_expires_parameter(self, tmp_path):
        storage = self._make_storage(tmp_path)
        url = storage.store_and_sign("content", scan_id="scan-abc")
        assert "expires=" in url

    def test_url_contains_sig_parameter(self, tmp_path):
        storage = self._make_storage(tmp_path)
        url = storage.store_and_sign("content", scan_id="scan-abc")
        assert "sig=" in url

    def test_retrieve_returns_stored_content(self, tmp_path):
        storage = self._make_storage(tmp_path)
        content = "Patient NI: [REDACTED], email: [REDACTED]"
        url = storage.store_and_sign(content, scan_id="scan-123")

        # Extract file_id from the URL
        path_part = url.split("?")[0]
        file_id = path_part.split("/v1/redacted/")[1]

        retrieved = storage.retrieve(file_id)
        assert retrieved is not None
        assert retrieved.decode("utf-8") == content

    def test_retrieve_returns_none_for_unknown_id(self, tmp_path):
        storage = self._make_storage(tmp_path)
        assert storage.retrieve("nonexistent-id") is None


# ---------------------------------------------------------------------------
# RedactedFileStorage — signature verification
# ---------------------------------------------------------------------------


class TestRedactedFileStorageVerification:
    def _make_storage(self, tmp_path) -> RedactedFileStorage:
        return RedactedFileStorage(
            base_url="http://localhost:8000",
            storage_dir=str(tmp_path),
            secret_key="test-secret-key-32-chars-xxxxxxxxx",
        )

    def test_fresh_url_signature_valid(self, tmp_path):
        storage = self._make_storage(tmp_path)
        url = storage.store_and_sign("content", scan_id="scan-xyz")
        # Parse URL parameters
        from urllib.parse import parse_qs, urlsplit
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        file_id = parsed.path.split("/v1/redacted/")[1]
        expires = int(params["expires"][0])
        sig = params["sig"][0]

        assert storage.verify_signature(file_id, expires, sig) is True

    def test_expired_url_rejected(self, tmp_path):
        storage = self._make_storage(tmp_path)
        file_id = "test-file-id"
        # Set expiry in the past
        past_expires = int(time.time()) - 1
        sig = storage._sign(file_id, past_expires)
        assert storage.verify_signature(file_id, past_expires, sig) is False

    def test_tampered_sig_rejected(self, tmp_path):
        storage = self._make_storage(tmp_path)
        url = storage.store_and_sign("content", scan_id="scan-xyz")
        from urllib.parse import parse_qs, urlsplit
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        file_id = parsed.path.split("/v1/redacted/")[1]
        expires = int(params["expires"][0])
        assert storage.verify_signature(file_id, expires, "deadbeef" * 8) is False

    def test_tampered_file_id_rejected(self, tmp_path):
        storage = self._make_storage(tmp_path)
        url = storage.store_and_sign("content", scan_id="scan-xyz")
        from urllib.parse import parse_qs, urlsplit
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        file_id = parsed.path.split("/v1/redacted/")[1]
        expires = int(params["expires"][0])
        sig = params["sig"][0]
        # Tamper with file_id
        assert storage.verify_signature(file_id + "-tampered", expires, sig) is False

    def test_custom_ttl_honoured(self, tmp_path):
        storage = self._make_storage(tmp_path)
        ttl = 7200
        url = storage.store_and_sign("content", scan_id="scan-abc", ttl_seconds=ttl)
        from urllib.parse import parse_qs, urlsplit
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        expires = int(params["expires"][0])
        # expires should be approximately now + ttl
        now = int(time.time())
        assert now + ttl - 5 <= expires <= now + ttl + 5


# ---------------------------------------------------------------------------
# RedactedFileStorage — path traversal safety
# ---------------------------------------------------------------------------


class TestRedactedFileStoragePathSafety:
    def test_path_traversal_chars_stripped_from_file_id(self, tmp_path):
        storage = RedactedFileStorage(
            base_url="http://localhost:8000",
            storage_dir=str(tmp_path),
            secret_key="test-secret",
        )
        malicious_id = "../../etc/passwd"
        # _file_path should sanitise the id
        path = storage._file_path(malicious_id)
        # The resulting path must be inside storage_dir
        import os
        assert os.path.commonpath([str(tmp_path), path]) == str(tmp_path)
        # And must not contain ..
        assert ".." not in path


# ---------------------------------------------------------------------------
# Integration: signed URL round-trip
# ---------------------------------------------------------------------------


class TestSignedUrlRoundTrip:
    """Integration test: content stored → URL parsed → verified → retrieved.

    This confirms the acceptance criterion:
    'Integration test confirms URL resolves to content where all PII spans
    are replaced with [REDACTED]'
    """

    def test_redacted_content_stored_and_retrievable(self, tmp_path):
        # Step 1: Simulate PII detection on extracted text
        original_text = (
            "Patient: John Smith, NI AB123456C, "
            "email john@nhs.uk, phone 07700 900123"
        )
        ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
        ctx.extracted_text = original_text
        ctx.byte_offsets = list(range(len(original_text)))
        ctx.request_redaction = True

        # Step 2: Redact PII spans
        ni_offset = original_text.index("AB123456C")
        email_offset = original_text.index("john@nhs.uk")
        phone_offset = original_text.index("07700 900123")
        ctx.findings = [
            _make_finding("AB123456C", offset=ni_offset),
            _make_finding("john@nhs.uk", offset=email_offset),
            _make_finding("07700 900123", offset=phone_offset),
        ]

        engine = RedactionEngine()
        redacted_text = engine.redact(ctx)

        # Confirm all PII is replaced
        assert "AB123456C" not in redacted_text
        assert "john@nhs.uk" not in redacted_text
        assert "07700 900123" not in redacted_text
        assert redacted_text.count(REDACTED_TOKEN) == 3

        # Step 3: Store and sign
        storage = RedactedFileStorage(
            base_url="http://localhost:8000",
            storage_dir=str(tmp_path),
            secret_key="test-secret-key-for-integration",
        )
        signed_url = storage.store_and_sign(redacted_text, scan_id=ctx.scan_id)
        ctx.redacted_file_url = signed_url

        # Step 4: Parse the signed URL and verify
        from urllib.parse import parse_qs, urlsplit
        parsed = urlsplit(signed_url)
        params = parse_qs(parsed.query)
        file_id = parsed.path.split("/v1/redacted/")[1]
        expires = int(params["expires"][0])
        sig = params["sig"][0]

        assert storage.verify_signature(file_id, expires, sig) is True

        # Step 5: Retrieve and confirm content matches redacted text
        retrieved = storage.retrieve(file_id)
        assert retrieved is not None
        content = retrieved.decode("utf-8")
        assert content == redacted_text
        assert REDACTED_TOKEN in content
        assert "AB123456C" not in content
        assert "john@nhs.uk" not in content
        assert "07700 900123" not in content
