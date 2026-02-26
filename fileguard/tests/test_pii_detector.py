"""Unit tests for PIIDetector and the UK pattern library.

Test coverage:
* Each built-in UK pattern matches valid examples and rejects invalid ones.
* Multi-pattern documents — text containing multiple PII types produces the
  correct set of findings.
* Overlapping matches — two patterns matching overlapping spans are both
  reported independently.
* Empty input — empty string and None extracted_text produce no findings.
* ScanContext integration — findings are appended (not replaced) and
  pre-existing findings are preserved.
* Byte-offset mapping — offsets are looked up correctly from byte_offsets.
* Missing byte_offsets — offset falls back to -1.
* Custom patterns — detector can be constructed with an explicit pattern list.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest

from fileguard.core.patterns.uk_patterns import (
    BUILTIN_PATTERNS,
    PatternDefinition,
    get_patterns,
    load_custom_patterns,
)
from fileguard.core.pii_detector import PIIDetector, PIIFinding
from fileguard.core.scan_context import ScanContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_detector(**kwargs) -> PIIDetector:
    return PIIDetector(**kwargs)


def make_ctx(text: str | None, byte_offsets: list[int] | None = None) -> ScanContext:
    ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
    ctx.extracted_text = text
    if byte_offsets is not None:
        ctx.byte_offsets = byte_offsets
    return ctx


def categories_found(findings: list[PIIFinding]) -> set[str]:
    return {f.category for f in findings}


# ---------------------------------------------------------------------------
# Built-in pattern: NI_NUMBER
# ---------------------------------------------------------------------------


class TestNINumber:
    PATTERN = next(p for p in BUILTIN_PATTERNS if p.name == "NI_NUMBER")

    def _match(self, text: str) -> re.Match | None:
        return self.PATTERN.pattern.search(text)

    def test_valid_compact(self):
        assert self._match("AB123456C") is not None

    def test_valid_spaced(self):
        assert self._match("AB 12 34 56 C") is not None

    def test_valid_suffix_d(self):
        assert self._match("ZY 99 99 99 D") is not None

    def test_invalid_suffix_e(self):
        # E is not a valid suffix (only A-D)
        assert self._match("AB123456E") is None

    def test_invalid_too_short(self):
        assert self._match("AB12345") is None

    def test_severity_is_high(self):
        assert self.PATTERN.severity == "high"


# ---------------------------------------------------------------------------
# Built-in pattern: NHS_NUMBER
# ---------------------------------------------------------------------------


class TestNHSNumber:
    PATTERN = next(p for p in BUILTIN_PATTERNS if p.name == "NHS_NUMBER")

    def _match(self, text: str) -> re.Match | None:
        return self.PATTERN.pattern.search(text)

    def test_valid_plain(self):
        assert self._match("9434765919") is not None

    def test_valid_space_separated(self):
        assert self._match("943 476 5919") is not None

    def test_valid_hyphen_separated(self):
        assert self._match("943-476-5919") is not None

    def test_invalid_nine_digits(self):
        # 9 digits — too short to match 3-3-4
        result = self._match("943476591")
        # 9 digits won't form 10-digit pattern
        assert result is None or len(result.group().replace(" ", "").replace("-", "")) == 10

    def test_severity_is_high(self):
        assert self.PATTERN.severity == "high"


# ---------------------------------------------------------------------------
# Built-in pattern: EMAIL
# ---------------------------------------------------------------------------


class TestEmail:
    PATTERN = next(p for p in BUILTIN_PATTERNS if p.name == "EMAIL")

    def _match(self, text: str) -> re.Match | None:
        return self.PATTERN.pattern.search(text)

    def test_valid_simple(self):
        assert self._match("user@example.com") is not None

    def test_valid_subdomain(self):
        assert self._match("alice.smith@mail.nhs.uk") is not None

    def test_valid_plus_addressing(self):
        assert self._match("user+tag@domain.org") is not None

    def test_invalid_no_at(self):
        assert self._match("userexample.com") is None

    def test_invalid_no_tld(self):
        assert self._match("user@domain") is None

    def test_severity_is_medium(self):
        assert self.PATTERN.severity == "medium"


# ---------------------------------------------------------------------------
# Built-in pattern: PHONE
# ---------------------------------------------------------------------------


class TestPhone:
    PATTERN = next(p for p in BUILTIN_PATTERNS if p.name == "PHONE")

    def _match(self, text: str) -> re.Match | None:
        return self.PATTERN.pattern.search(text)

    def test_valid_mobile(self):
        assert self._match("07700 900123") is not None

    def test_valid_landline(self):
        assert self._match("01234 567890") is not None

    def test_valid_international(self):
        assert self._match("+44 7700 900123") is not None

    def test_valid_no_spaces(self):
        assert self._match("07700900123") is not None

    def test_severity_is_medium(self):
        assert self.PATTERN.severity == "medium"


# ---------------------------------------------------------------------------
# Built-in pattern: POSTCODE
# ---------------------------------------------------------------------------


class TestPostcode:
    PATTERN = next(p for p in BUILTIN_PATTERNS if p.name == "POSTCODE")

    def _match(self, text: str) -> re.Match | None:
        return self.PATTERN.pattern.search(text)

    def test_valid_with_space(self):
        assert self._match("SW1A 1AA") is not None

    def test_valid_without_space(self):
        assert self._match("EC1A1BB") is not None

    def test_valid_short_format(self):
        assert self._match("W1A 1AA") is not None

    def test_invalid_lowercase(self):
        # Pattern uses re.ASCII; lowercase letters won't match [A-Z] range
        assert self._match("sw1a 1aa") is None

    def test_severity_is_low(self):
        assert self.PATTERN.severity == "low"


# ---------------------------------------------------------------------------
# PIIDetector.detect — core behaviour
# ---------------------------------------------------------------------------


class TestDetectEmptyInput:
    def test_empty_string_returns_no_findings(self):
        detector = PIIDetector()
        assert detector.detect("", []) == []

    def test_whitespace_only_returns_no_findings(self):
        detector = PIIDetector()
        # Whitespace only won't match any pattern
        result = detector.detect("   \n\t  ", [])
        assert result == []


class TestDetectSinglePattern:
    def test_ni_number_detected(self):
        detector = PIIDetector()
        findings = detector.detect("NI: AB123456C", list(range(13)))
        ni_findings = [f for f in findings if f.category == "NI_NUMBER"]
        assert len(ni_findings) == 1
        assert ni_findings[0].match == "AB123456C"
        assert ni_findings[0].severity == "high"
        assert ni_findings[0].type == "pii"

    def test_email_detected(self):
        detector = PIIDetector()
        text = "Contact: alice@example.com"
        findings = detector.detect(text, list(range(len(text))))
        email_findings = [f for f in findings if f.category == "EMAIL"]
        assert len(email_findings) == 1
        assert email_findings[0].match == "alice@example.com"
        assert email_findings[0].severity == "medium"

    def test_postcode_detected(self):
        detector = PIIDetector()
        text = "Address: EC1A 1BB"
        findings = detector.detect(text, list(range(len(text))))
        postcode_findings = [f for f in findings if f.category == "POSTCODE"]
        assert len(postcode_findings) == 1
        assert postcode_findings[0].match == "EC1A 1BB"
        assert postcode_findings[0].severity == "low"


class TestDetectMultiPatternDocument:
    """Acceptance criterion: Unit tests cover multi-pattern documents."""

    def test_multiple_pii_types_in_single_text(self):
        text = (
            "Patient: John Smith, NI AB123456C, "
            "NHS 943 476 5919, "
            "email john@nhs.uk, "
            "phone 07700 900123, "
            "postcode SW1A 1AA"
        )
        detector = PIIDetector()
        findings = detector.detect(text, list(range(len(text))))
        found_cats = categories_found(findings)

        assert "NI_NUMBER" in found_cats
        assert "NHS_NUMBER" in found_cats
        assert "EMAIL" in found_cats
        assert "PHONE" in found_cats
        assert "POSTCODE" in found_cats

    def test_finding_count_matches_occurrence_count(self):
        # Two NI numbers in the text → two findings
        text = "NI1: AB123456C and NI2: CD987654A"
        detector = PIIDetector()
        findings = detector.detect(text, list(range(len(text))))
        ni_findings = [f for f in findings if f.category == "NI_NUMBER"]
        assert len(ni_findings) == 2

    def test_two_emails_produce_two_findings(self):
        text = "From: alice@example.com To: bob@example.org"
        detector = PIIDetector()
        findings = detector.detect(text, list(range(len(text))))
        email_findings = [f for f in findings if f.category == "EMAIL"]
        assert len(email_findings) == 2
        matched = {f.match for f in email_findings}
        assert "alice@example.com" in matched
        assert "bob@example.org" in matched


class TestDetectOverlappingMatches:
    """Acceptance criterion: Unit tests cover overlapping matches.

    'Overlapping' in this context means two *different* patterns both produce
    a finding in the same region of text.  For example, a string that is
    simultaneously a valid email address and happens to match another pattern.
    We test this by injecting two custom patterns that both match the same
    span and verify both findings are independently reported.
    """

    def test_two_patterns_match_same_span_both_reported(self):
        # Use two custom patterns that both match the word "SECRET"
        pattern_a = PatternDefinition(
            name="PATTERN_A",
            pattern=re.compile(r"SECRET"),
            severity="high",
            category="PATTERN_A",
        )
        pattern_b = PatternDefinition(
            name="PATTERN_B",
            pattern=re.compile(r"SECRET"),
            severity="medium",
            category="PATTERN_B",
        )
        detector = PIIDetector(patterns=[pattern_a, pattern_b])
        text = "The word SECRET is flagged twice"
        findings = detector.detect(text, list(range(len(text))))
        assert len(findings) == 2
        assert {f.category for f in findings} == {"PATTERN_A", "PATTERN_B"}

    def test_overlapping_spans_different_patterns(self):
        # "07700 900123" matches PHONE; also contains digits that could match
        # NHS_NUMBER pattern (10 digits). Verify PHONE finding is present.
        text = "Call 07700900123 now"
        detector = PIIDetector()
        findings = detector.detect(text, list(range(len(text))))
        phone_findings = [f for f in findings if f.category == "PHONE"]
        assert len(phone_findings) >= 1


# ---------------------------------------------------------------------------
# Byte-offset mapping
# ---------------------------------------------------------------------------


class TestByteOffsets:
    def test_offset_mapped_from_byte_offsets_list(self):
        text = "NI: AB123456C"
        # Simulate byte_offsets where each char maps to 2x its index
        # (as if we had a multi-byte encoding scenario)
        byte_offsets = [i * 2 for i in range(len(text))]
        detector = PIIDetector()
        findings = detector.detect(text, byte_offsets)
        ni_findings = [f for f in findings if f.category == "NI_NUMBER"]
        assert len(ni_findings) == 1
        # "AB123456C" starts at index 4 in text → byte offset = 4*2 = 8
        assert ni_findings[0].offset == 8

    def test_offset_is_minus_one_when_no_byte_offsets(self):
        text = "NI: AB123456C"
        detector = PIIDetector()
        findings = detector.detect(text, [])  # empty byte_offsets
        ni_findings = [f for f in findings if f.category == "NI_NUMBER"]
        assert len(ni_findings) == 1
        assert ni_findings[0].offset == -1

    def test_offset_is_minus_one_when_byte_offsets_shorter_than_text(self):
        text = "NI: AB123456C extra stuff"
        # Provide byte_offsets only for first 3 chars (before match)
        byte_offsets = [0, 1, 2]
        detector = PIIDetector()
        findings = detector.detect(text, byte_offsets)
        ni_findings = [f for f in findings if f.category == "NI_NUMBER"]
        assert len(ni_findings) == 1
        assert ni_findings[0].offset == -1


# ---------------------------------------------------------------------------
# ScanContext integration
# ---------------------------------------------------------------------------


class TestScanContextIntegration:
    """Acceptance criterion: PIIDetector integrates with ScanContext."""

    def test_findings_appended_to_context(self):
        ctx = make_ctx("NI: AB123456C")
        ctx.byte_offsets = list(range(len(ctx.extracted_text)))
        detector = PIIDetector()
        detector.scan(ctx)

        ni_findings = [f for f in ctx.findings if f.category == "NI_NUMBER"]
        assert len(ni_findings) == 1

    def test_preexisting_findings_are_preserved(self):
        ctx = make_ctx("email: alice@example.com")
        ctx.byte_offsets = list(range(len(ctx.extracted_text)))
        # Simulate a prior pipeline step having added a finding
        sentinel = object()
        ctx.findings.append(sentinel)

        detector = PIIDetector()
        detector.scan(ctx)

        assert sentinel in ctx.findings
        assert len(ctx.findings) >= 2  # sentinel + at least one email finding

    def test_no_findings_when_extracted_text_is_none(self):
        ctx = make_ctx(None)
        detector = PIIDetector()
        detector.scan(ctx)
        assert ctx.findings == []

    def test_no_findings_when_extracted_text_is_empty(self):
        ctx = make_ctx("")
        detector = PIIDetector()
        detector.scan(ctx)
        assert ctx.findings == []

    def test_scan_id_preserved(self):
        ctx = make_ctx("AB123456C")
        ctx.byte_offsets = list(range(len(ctx.extracted_text)))
        original_scan_id = ctx.scan_id
        detector = PIIDetector()
        detector.scan(ctx)
        assert ctx.scan_id == original_scan_id

    def test_multiple_scans_accumulate_findings(self):
        # Calling scan twice accumulates findings (pipeline reuse scenario)
        ctx = make_ctx("NI: AB123456C email: bob@test.com")
        ctx.byte_offsets = list(range(len(ctx.extracted_text)))
        detector = PIIDetector()
        detector.scan(ctx)
        first_count = len(ctx.findings)
        # Run again (unusual but must not crash; findings are cumulative)
        detector.scan(ctx)
        assert len(ctx.findings) == first_count * 2


# ---------------------------------------------------------------------------
# Custom patterns
# ---------------------------------------------------------------------------


class TestCustomPatterns:
    def test_explicit_pattern_list(self):
        custom = PatternDefinition(
            name="EMPLOYEE_ID",
            pattern=re.compile(r"EMP-[0-9]{6}"),
            severity="medium",
            category="EMPLOYEE_ID",
        )
        detector = PIIDetector(patterns=[custom])
        text = "ID: EMP-123456"
        findings = detector.detect(text, list(range(len(text))))
        assert len(findings) == 1
        assert findings[0].category == "EMPLOYEE_ID"
        assert findings[0].match == "EMP-123456"

    def test_custom_patterns_from_json_file(self, tmp_path: Path):
        config = [
            {
                "name": "CASE_NUMBER",
                "pattern": r"CASE-[0-9]{4}",
                "severity": "low",
            }
        ]
        config_file = tmp_path / "patterns.json"
        config_file.write_text(json.dumps(config))

        patterns = load_custom_patterns(config_file)
        assert len(patterns) == 1
        assert patterns[0].name == "CASE_NUMBER"
        assert patterns[0].severity == "low"

        detector = PIIDetector(patterns=patterns)
        text = "Reference: CASE-9001"
        findings = detector.detect(text, list(range(len(text))))
        assert len(findings) == 1
        assert findings[0].category == "CASE_NUMBER"

    def test_get_patterns_merges_builtin_and_custom(self, tmp_path: Path):
        config = [
            {
                "name": "CUSTOM_ID",
                "pattern": r"CID-[0-9]{3}",
                "severity": "medium",
            }
        ]
        config_file = tmp_path / "custom.json"
        config_file.write_text(json.dumps(config))

        merged = get_patterns(custom_patterns_path=config_file)
        names = [p.name for p in merged]
        assert "NI_NUMBER" in names
        assert "CUSTOM_ID" in names

    def test_get_patterns_builtin_only_when_no_path(self):
        patterns = get_patterns()
        names = {p.name for p in patterns}
        assert names == {"NI_NUMBER", "NHS_NUMBER", "EMAIL", "PHONE", "POSTCODE"}


# ---------------------------------------------------------------------------
# PIIFinding structure
# ---------------------------------------------------------------------------


class TestPIIFindingStructure:
    def test_finding_fields_populated(self):
        detector = PIIDetector()
        text = "alice@example.com"
        findings = detector.detect(text, list(range(len(text))))
        email_findings = [f for f in findings if f.category == "EMAIL"]
        assert len(email_findings) == 1
        f = email_findings[0]
        assert f.type == "pii"
        assert f.category == "EMAIL"
        assert f.severity == "medium"
        assert f.match == "alice@example.com"
        assert isinstance(f.offset, int)

    def test_finding_is_immutable(self):
        detector = PIIDetector()
        findings = detector.detect("alice@example.com", [])
        f = findings[0]
        with pytest.raises((AttributeError, TypeError)):
            f.category = "MODIFIED"  # type: ignore[misc]
