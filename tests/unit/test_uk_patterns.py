"""Unit tests for fileguard/core/patterns/uk_patterns.py.

Coverage targets:
* All five built-in UK PII pattern types (NI number, NHS number, email,
  UK phone, UK postcode) match valid examples and reject invalid ones.
* ``load_patterns()`` returns the five built-in entries when called without
  a custom config path.
* ``load_patterns(path)`` correctly merges custom patterns from a JSON file.
* Error handling for missing file, invalid JSON, non-array root, and
  individual malformed entries (missing keys, bad severity, invalid regex).
* ``get_builtin_patterns()`` returns the canonical five built-in entries.
* All returned PatternEntry objects have pre-compiled regex objects (no
  string type).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fileguard.core.patterns.uk_patterns import (
    PatternEntry,
    _BUILTIN_PATTERNS,
    _VALID_SEVERITIES,
    get_builtin_patterns,
    load_patterns,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _matches(entry: PatternEntry, text: str) -> list[str]:
    """Return all matched strings for *entry* in *text*."""
    return [m.group() for m in entry.regex.finditer(text)]


def _builtin(name: str) -> PatternEntry:
    """Return the built-in pattern entry with the given *name*."""
    for e in _BUILTIN_PATTERNS:
        if e.name == name:
            return e
    raise KeyError(name)


# ---------------------------------------------------------------------------
# PatternEntry structure
# ---------------------------------------------------------------------------


class TestPatternEntryStructure:
    def test_builtin_count(self):
        assert len(_BUILTIN_PATTERNS) == 5

    def test_builtin_names(self):
        names = [e.name for e in _BUILTIN_PATTERNS]
        assert names == ["NI_NUMBER", "NHS_NUMBER", "EMAIL", "UK_PHONE", "UK_POSTCODE"]

    def test_all_regex_compiled(self):
        for entry in _BUILTIN_PATTERNS:
            assert isinstance(entry.regex, re.Pattern), (
                f"{entry.name} regex is not compiled"
            )

    def test_all_severities_valid(self):
        for entry in _BUILTIN_PATTERNS:
            assert entry.severity in _VALID_SEVERITIES, (
                f"{entry.name} has invalid severity {entry.severity!r}"
            )

    def test_severity_assignments(self):
        sev = {e.name: e.severity for e in _BUILTIN_PATTERNS}
        assert sev["NI_NUMBER"] == "high"
        assert sev["NHS_NUMBER"] == "high"
        assert sev["EMAIL"] == "medium"
        assert sev["UK_PHONE"] == "medium"
        assert sev["UK_POSTCODE"] == "low"

    def test_frozen_dataclass(self):
        entry = _builtin("NI_NUMBER")
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            entry.name = "OTHER"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# NI Number
# ---------------------------------------------------------------------------


class TestNINumber:
    """National Insurance number detection."""

    valid = [
        "AB123456C",       # compact
        "AB 12 34 56 C",  # spaced (card format)
        "ST123456A",       # valid prefix letters S, T
        "WX123456B",       # valid prefix letters W, X
        "JK123456D",       # valid prefix letters J, K; suffix D
    ]

    invalid = [
        "D123456C",        # first letter D — excluded
        "QQ123456C",       # letter Q — excluded from both positions
        "ABCD1234C",       # too many letters in prefix
        "AB12345C",        # only 5 digits
        "AB1234567C",      # 7 digits
        "AB123456E",       # suffix E not in A-D
        "123456C",         # no prefix letters
        "",
    ]

    def test_valid_matches(self):
        entry = _builtin("NI_NUMBER")
        for text in self.valid:
            matches = _matches(entry, text)
            assert matches, f"Expected NI_NUMBER to match {text!r}"

    def test_invalid_no_match(self):
        entry = _builtin("NI_NUMBER")
        for text in self.invalid:
            matches = _matches(entry, text)
            assert not matches, (
                f"Expected NI_NUMBER NOT to match {text!r} but got {matches}"
            )

    def test_match_in_sentence(self):
        entry = _builtin("NI_NUMBER")
        text = "The employee's NI number is AB123456C and was verified."
        assert _matches(entry, text) == ["AB123456C"]

    def test_case_insensitive(self):
        entry = _builtin("NI_NUMBER")
        assert _matches(entry, "ab123456c")

    def test_multiple_in_text(self):
        entry = _builtin("NI_NUMBER")
        text = "First: AB123456C Second: CD234567A"
        matches = _matches(entry, text)
        assert len(matches) == 2


# ---------------------------------------------------------------------------
# NHS Number
# ---------------------------------------------------------------------------


class TestNHSNumber:
    """NHS number detection (10-digit, 3-3-4 grouping)."""

    valid = [
        "9434765919",      # compact 10-digit
        "943 476 5919",   # space-separated (standard display)
        "943-476-5919",   # hyphen-separated
    ]

    invalid = [
        "123456789",       # only 9 digits
        "12345678901",     # 11 digits
        "943 476 591",     # incomplete (9 digits total)
        "",
    ]

    def test_valid_matches(self):
        entry = _builtin("NHS_NUMBER")
        for text in self.valid:
            matches = _matches(entry, text)
            assert matches, f"Expected NHS_NUMBER to match {text!r}"

    def test_invalid_no_match(self):
        entry = _builtin("NHS_NUMBER")
        for text in self.invalid:
            # All digits strings that are too short (9) or have no word boundary
            # in the middle (11 consecutive digits) should not match a valid
            # 10-digit NHS number anchored by word boundaries.
            matches = _matches(entry, text)
            assert not matches, (
                f"Expected NHS_NUMBER NOT to match {text!r} but got {matches}"
            )

    def test_no_match_for_empty(self):
        entry = _builtin("NHS_NUMBER")
        assert not _matches(entry, "")

    def test_match_in_sentence(self):
        entry = _builtin("NHS_NUMBER")
        text = "Patient NHS number: 943 476 5919 was admitted."
        assert _matches(entry, text)

    def test_hyphen_format(self):
        entry = _builtin("NHS_NUMBER")
        assert _matches(entry, "943-476-5919")

    def test_compact_format(self):
        entry = _builtin("NHS_NUMBER")
        assert _matches(entry, "9434765919")


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------


class TestEmail:
    """Email address detection."""

    valid = [
        "user@example.com",
        "first.last@domain.co.uk",
        "user+tag@sub.domain.org",
        "USER@EXAMPLE.COM",         # uppercase
        "a@b.io",                   # short TLD
        "user.name123@company.gov.uk",
    ]

    invalid = [
        "notanemail",
        "missing@tld",
        "@nodomain.com",
        "no-at-sign.com",
        "",
    ]

    def test_valid_matches(self):
        entry = _builtin("EMAIL")
        for text in self.valid:
            matches = _matches(entry, text)
            assert matches, f"Expected EMAIL to match {text!r}"

    def test_invalid_no_match(self):
        entry = _builtin("EMAIL")
        for text in self.invalid:
            assert not _matches(entry, text), (
                f"Expected EMAIL NOT to match {text!r}"
            )

    def test_match_in_sentence(self):
        entry = _builtin("EMAIL")
        text = "Please contact support@fileguard.co.uk for assistance."
        assert _matches(entry, text) == ["support@fileguard.co.uk"]

    def test_multiple_emails(self):
        entry = _builtin("EMAIL")
        text = "From: alice@example.com To: bob@example.org"
        matches = _matches(entry, text)
        assert len(matches) == 2


# ---------------------------------------------------------------------------
# UK Phone
# ---------------------------------------------------------------------------


class TestUKPhone:
    """UK telephone number detection."""

    valid = [
        "+44 7700 900123",    # E.164 with spaces
        "+447700900123",      # E.164 compact
        "07700 900123",       # national mobile
        "0044 7700 900123",   # 0044 prefix
        "0800 123 4567",      # freephone
        "0207 123 4567",      # London landline
    ]

    invalid = [
        "123",                # too short
        "not a number",
        "",
    ]

    def test_valid_matches(self):
        entry = _builtin("UK_PHONE")
        for text in self.valid:
            matches = _matches(entry, text)
            assert matches, f"Expected UK_PHONE to match {text!r}"

    def test_no_match_empty(self):
        entry = _builtin("UK_PHONE")
        assert not _matches(entry, "")

    def test_match_in_sentence(self):
        entry = _builtin("UK_PHONE")
        text = "Call us on 07700 900123 between 9am and 5pm."
        assert _matches(entry, text)

    def test_international_prefix(self):
        entry = _builtin("UK_PHONE")
        assert _matches(entry, "+44 20 7946 0958")

    def test_case_insensitive_flag_does_not_break_digit_match(self):
        # IGNORECASE should not affect digit matching
        entry = _builtin("UK_PHONE")
        assert _matches(entry, "07700 900123")


# ---------------------------------------------------------------------------
# UK Postcode
# ---------------------------------------------------------------------------


class TestUKPostcode:
    """UK postcode detection."""

    valid = [
        "SW1A 1AA",      # Westminster
        "EC1A 1BB",      # City of London
        "W1A 0AX",       # West End
        "M1 1AE",        # Manchester
        "B1 1BB",        # Birmingham
        "DN55 1PT",      # Doncaster
        "CR2 6XH",       # Croydon
        "sw1a 1aa",      # lowercase — IGNORECASE flag
    ]

    invalid = [
        "ABCDE FGH",     # too many letters, no digit
        "1234 567",      # all digits
        "",
    ]

    def test_valid_matches(self):
        entry = _builtin("UK_POSTCODE")
        for text in self.valid:
            matches = _matches(entry, text)
            assert matches, f"Expected UK_POSTCODE to match {text!r}"

    def test_no_match_empty(self):
        entry = _builtin("UK_POSTCODE")
        assert not _matches(entry, "")

    def test_match_in_sentence(self):
        entry = _builtin("UK_POSTCODE")
        text = "Delivery address: 10 Downing Street, London, SW1A 2AA."
        assert _matches(entry, text)

    def test_case_insensitive(self):
        entry = _builtin("UK_POSTCODE")
        assert _matches(entry, "ec1a 1bb")

    def test_multiple_postcodes(self):
        entry = _builtin("UK_POSTCODE")
        text = "From M1 1AE to SW1A 1AA."
        matches = _matches(entry, text)
        assert len(matches) == 2


# ---------------------------------------------------------------------------
# load_patterns — no custom config
# ---------------------------------------------------------------------------


class TestLoadPatternsBuiltinOnly:
    def test_returns_list(self):
        result = load_patterns()
        assert isinstance(result, list)

    def test_returns_five_builtins(self):
        result = load_patterns()
        assert len(result) == 5

    def test_all_entries_are_pattern_entry(self):
        for entry in load_patterns():
            assert isinstance(entry, PatternEntry)

    def test_all_regex_compiled(self):
        for entry in load_patterns():
            assert isinstance(entry.regex, re.Pattern)

    def test_order_preserved(self):
        names = [e.name for e in load_patterns()]
        assert names == ["NI_NUMBER", "NHS_NUMBER", "EMAIL", "UK_PHONE", "UK_POSTCODE"]

    def test_none_path_returns_builtins(self):
        assert len(load_patterns(None)) == 5

    def test_returns_new_list_each_call(self):
        a = load_patterns()
        b = load_patterns()
        assert a is not b  # new list objects
        assert a == b  # same contents


# ---------------------------------------------------------------------------
# load_patterns — custom config loading
# ---------------------------------------------------------------------------


class TestLoadPatternsCustomConfig:
    def _write_config(self, tmp_path: Path, entries: list[dict]) -> Path:
        config = tmp_path / "custom_patterns.json"
        config.write_text(json.dumps(entries), encoding="utf-8")
        return config

    def test_custom_pattern_appended(self, tmp_path):
        config = self._write_config(
            tmp_path,
            [{"name": "EMPLOYEE_ID", "pattern": r"EMP-\d{6}", "severity": "medium"}],
        )
        patterns = load_patterns(config)
        assert len(patterns) == 6
        names = [e.name for e in patterns]
        assert "EMPLOYEE_ID" in names

    def test_custom_pattern_last(self, tmp_path):
        config = self._write_config(
            tmp_path,
            [{"name": "EMPLOYEE_ID", "pattern": r"EMP-\d{6}", "severity": "medium"}],
        )
        patterns = load_patterns(config)
        assert patterns[-1].name == "EMPLOYEE_ID"

    def test_custom_pattern_compiled(self, tmp_path):
        config = self._write_config(
            tmp_path,
            [{"name": "CUSTOM", "pattern": r"\bfoo\b", "severity": "low"}],
        )
        patterns = load_patterns(config)
        custom = next(e for e in patterns if e.name == "CUSTOM")
        assert isinstance(custom.regex, re.Pattern)

    def test_custom_pattern_matches(self, tmp_path):
        config = self._write_config(
            tmp_path,
            [{"name": "ORDER_REF", "pattern": r"ORD-\d{8}", "severity": "low"}],
        )
        patterns = load_patterns(config)
        custom = next(e for e in patterns if e.name == "ORDER_REF")
        assert _matches(custom, "Order ORD-12345678 has been placed.")

    def test_multiple_custom_patterns(self, tmp_path):
        config = self._write_config(
            tmp_path,
            [
                {"name": "PAT_A", "pattern": r"AAA", "severity": "low"},
                {"name": "PAT_B", "pattern": r"BBB", "severity": "medium"},
            ],
        )
        patterns = load_patterns(config)
        assert len(patterns) == 7
        names = [e.name for e in patterns]
        assert "PAT_A" in names
        assert "PAT_B" in names

    def test_severity_values_accepted(self, tmp_path):
        for sev in _VALID_SEVERITIES:
            config = self._write_config(
                tmp_path / f"cfg_{sev}.json",
                [{"name": f"PAT_{sev.upper()}", "pattern": r"\btest\b", "severity": sev}],
            )
            patterns = load_patterns(config)
            custom = next(e for e in patterns if e.name.startswith("PAT_"))
            assert custom.severity == sev

    def test_path_as_string(self, tmp_path):
        config = self._write_config(
            tmp_path,
            [{"name": "STRPATH", "pattern": r"\bx\b", "severity": "low"}],
        )
        patterns = load_patterns(str(config))
        assert len(patterns) == 6

    def test_builtin_names_preserved_order(self, tmp_path):
        config = self._write_config(
            tmp_path,
            [{"name": "EXTRA", "pattern": r"\bextra\b", "severity": "low"}],
        )
        patterns = load_patterns(config)
        builtin_names = [e.name for e in patterns[:5]]
        assert builtin_names == [
            "NI_NUMBER", "NHS_NUMBER", "EMAIL", "UK_PHONE", "UK_POSTCODE"
        ]


# ---------------------------------------------------------------------------
# load_patterns — error handling
# ---------------------------------------------------------------------------


class TestLoadPatternsErrorHandling:
    def test_missing_file_returns_builtins(self, tmp_path):
        missing = tmp_path / "nonexistent.json"
        patterns = load_patterns(missing)
        assert len(patterns) == 5

    def test_invalid_json_returns_builtins(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{ not valid json", encoding="utf-8")
        patterns = load_patterns(bad)
        assert len(patterns) == 5

    def test_non_array_root_returns_builtins(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"name": "X", "pattern": r"\d", "severity": "low"}))
        patterns = load_patterns(bad)
        assert len(patterns) == 5

    def test_entry_missing_name_skipped(self, tmp_path, caplog):
        cfg = tmp_path / "cfg.json"
        cfg.write_text(
            json.dumps([
                {"pattern": r"\d+", "severity": "low"},          # missing name
                {"name": "GOOD", "pattern": r"\bfoo\b", "severity": "low"},
            ])
        )
        import logging
        with caplog.at_level(logging.WARNING):
            patterns = load_patterns(cfg)
        assert len(patterns) == 6  # 5 builtins + 1 good
        assert any(e.name == "GOOD" for e in patterns)

    def test_entry_missing_pattern_skipped(self, tmp_path):
        cfg = tmp_path / "cfg.json"
        cfg.write_text(
            json.dumps([
                {"name": "BAD", "severity": "low"},              # missing pattern
                {"name": "GOOD", "pattern": r"\bbar\b", "severity": "low"},
            ])
        )
        patterns = load_patterns(cfg)
        assert len(patterns) == 6
        assert any(e.name == "GOOD" for e in patterns)
        assert not any(e.name == "BAD" for e in patterns)

    def test_entry_invalid_severity_skipped(self, tmp_path):
        cfg = tmp_path / "cfg.json"
        cfg.write_text(
            json.dumps([
                {"name": "BAD", "pattern": r"\d+", "severity": "extreme"},  # invalid
                {"name": "GOOD", "pattern": r"\bfoo\b", "severity": "high"},
            ])
        )
        patterns = load_patterns(cfg)
        assert len(patterns) == 6
        assert any(e.name == "GOOD" for e in patterns)
        assert not any(e.name == "BAD" for e in patterns)

    def test_entry_invalid_regex_skipped(self, tmp_path):
        cfg = tmp_path / "cfg.json"
        cfg.write_text(
            json.dumps([
                {"name": "BAD", "pattern": r"[unclosed", "severity": "low"},  # bad regex
                {"name": "GOOD", "pattern": r"\bfoo\b", "severity": "low"},
            ])
        )
        patterns = load_patterns(cfg)
        assert len(patterns) == 6
        assert any(e.name == "GOOD" for e in patterns)
        assert not any(e.name == "BAD" for e in patterns)

    def test_non_dict_entry_skipped(self, tmp_path):
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps(["not_a_dict", {"name": "OK", "pattern": r"\bx\b", "severity": "low"}]))
        patterns = load_patterns(cfg)
        assert len(patterns) == 6

    def test_shadow_builtin_name_both_retained(self, tmp_path):
        """A custom pattern with the same name as a built-in is appended (not replaced)."""
        cfg = tmp_path / "cfg.json"
        cfg.write_text(
            json.dumps([
                {"name": "EMAIL", "pattern": r"custom@example\.com", "severity": "high"},
            ])
        )
        patterns = load_patterns(cfg)
        assert len(patterns) == 6
        email_entries = [e for e in patterns if e.name == "EMAIL"]
        assert len(email_entries) == 2

    def test_empty_array_returns_builtins(self, tmp_path):
        cfg = tmp_path / "cfg.json"
        cfg.write_text("[]")
        patterns = load_patterns(cfg)
        assert len(patterns) == 5


# ---------------------------------------------------------------------------
# get_builtin_patterns
# ---------------------------------------------------------------------------


class TestGetBuiltinPatterns:
    def test_returns_five_entries(self):
        result = get_builtin_patterns()
        assert len(result) == 5

    def test_all_pattern_entries(self):
        for e in get_builtin_patterns():
            assert isinstance(e, PatternEntry)

    def test_returns_new_list(self):
        a = get_builtin_patterns()
        b = get_builtin_patterns()
        assert a is not b

    def test_same_as_builtin_patterns_module_constant(self):
        assert get_builtin_patterns() == list(_BUILTIN_PATTERNS)

    def test_all_regex_compiled(self):
        for e in get_builtin_patterns():
            assert isinstance(e.regex, re.Pattern)
