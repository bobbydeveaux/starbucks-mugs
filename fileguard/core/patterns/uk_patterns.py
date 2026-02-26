"""Built-in UK PII regex pattern library for FileGuard.

This module provides a curated set of pre-compiled regular expressions covering
the five primary UK personally identifiable information (PII) types required by
the scan pipeline:

* National Insurance (NI) numbers
* NHS numbers
* Email addresses
* UK telephone numbers
* UK postcodes

Additional organisation-specific patterns can be supplied at startup via a JSON
config file (see :func:`load_patterns`). Custom patterns are merged with the
built-in set and returned as a single, pre-compiled list.  No regex compilation
occurs at scan time — all patterns are compiled on load.

**JSON config format** (array of objects at the root):

.. code-block:: json

    [
        {
            "name": "EMPLOYEE_ID",
            "pattern": "EMP-\\\\d{6}",
            "severity": "medium"
        }
    ]

Valid severity values: ``"low"``, ``"medium"``, ``"high"``, ``"critical"``.

Usage::

    from fileguard.core.patterns.uk_patterns import load_patterns

    patterns = load_patterns()                          # built-ins only
    patterns = load_patterns("/path/to/custom.json")    # built-ins + custom

    for entry in patterns:
        for match in entry.regex.finditer(text):
            print(entry.name, entry.severity, match.start())
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_SEVERITIES: frozenset[str] = frozenset({"low", "medium", "high", "critical"})

# ---------------------------------------------------------------------------
# Built-in raw pattern strings
# ---------------------------------------------------------------------------

# National Insurance number
# Format: two prefix letters + six digits + one suffix letter (A–D).
#
# Prefix letter constraints (from HMRC specification):
#   First letter:  any except D, F, I, Q, U, V
#   Second letter: any except D, F, I, O, Q, U, V
# Additionally, the prefixes BG, GB, KN, NK, NT, TN, ZZ are reserved and
# never allocated — we do not exclude them here because the regex would become
# unwieldy; downstream processing should apply deeper validation where needed.
#
# Display formats accepted:
#   - AA123456C   (compact)
#   - AA 12 34 56 C  (spaced into pairs, as printed on the card)
_NI_NUMBER = (
    r"\b"
    r"[A-CEGHJ-PR-TW-Z]"      # first prefix letter (excludes D, F, I, Q, U, V)
    r"[A-CEGHJ-NPR-TW-Z]"     # second prefix letter (additionally excludes O)
    r"(?:\s?)"                  # optional space before digit block
    r"(?:\d{2}\s?){3}"         # six digits, possibly spaced into three pairs
    r"[A-D]"                   # suffix letter
    r"\b"
)

# NHS number
# A 10-digit identifier (DV check digit algorithm), displayed as 3-3-4 digit
# groups separated by spaces or hyphens.  Check-digit validation requires
# procedural code and is out of scope for the pattern library; callers that
# need strict validation should apply the mod-11 algorithm on matched strings.
_NHS_NUMBER = (
    r"\b"
    r"\d{3}"
    r"[\s\-]?"
    r"\d{3}"
    r"[\s\-]?"
    r"\d{4}"
    r"\b"
)

# Email address
# Matches the vast majority of real-world addresses including quoted local
# parts and internationalised domains.  This intentionally avoids the full
# RFC 5321 complexity for performance; the goal is high recall over precision.
_EMAIL = (
    r"\b"
    r"[A-Za-z0-9._%+\-]+"      # local part
    r"@"
    r"[A-Za-z0-9.\-]+"         # domain labels
    r"\.[A-Za-z]{2,}"          # TLD (≥2 characters)
    r"\b"
)

# UK telephone number
# Accepts the following prefix families:
#   +44 / 0044    — E.164 international dialling prefix
#   0             — standard UK national prefix
# Followed by 9–10 significant digits (after the prefix), with optional
# spaces or hyphens as grouping separators (e.g. 07700 900123, +44 7700 900123).
#
# The pattern uses lookbehind/lookahead rather than \b because the E.164
# international form starts with '+' which is a non-word character.
_UK_PHONE = (
    r"(?<!\w)"                      # not preceded by a word character
    r"(?:"
        r"(?:\+44|0044)"            # E.164 / international prefix
        r"[\s\-]?"                  # optional separator after prefix
        r"\d[\d\s\-]{7,12}\d"      # 9–10 significant digits; ends on a digit
    r"|"
        r"0"                        # national prefix
        r"\d[\d\s\-]{7,12}\d"      # remaining 9–10 digits; ends on a digit
    r")"
    r"(?!\d)"                       # not followed by a digit (avoids over-matching)
)

# UK postcode
# Covers all Royal Mail PAF outward/inward code formats:
#   AN NAA   e.g. M1 1AE
#   ANN NAA  e.g. M60 1NW
#   AAN NAA  e.g. CR2 6XH
#   AANN NAA e.g. DN55 1PT
#   ANA NAA  e.g. W1A 1HQ
#   AANA NAA e.g. EC1A 1BB
# The inward code is always a digit followed by two letters; the outward code
# district varies.  We require a word boundary on each side so we do not match
# fragments of longer codes.
_UK_POSTCODE = (
    r"\b"
    r"(?:"
        r"[A-Z]{1,2}"              # area (1 or 2 letters)
        r"\d"                      # district digit
        r"[A-Z\d]?"               # optional district sub-code letter/digit
    r")"
    r"[\s]?"                       # optional single space between parts
    r"(?:"
        r"\d"                      # inward sector digit
        r"[A-Z]{2}"               # inward unit letters
    r")"
    r"\b"
)

# ---------------------------------------------------------------------------
# PatternEntry dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PatternEntry:
    """An immutable, pre-compiled PII pattern entry.

    Attributes:
        name: Category identifier used in scan findings
            (e.g. ``"NI_NUMBER"``, ``"NHS_NUMBER"``).
        regex: Pre-compiled regular expression. Use ``regex.finditer(text)``
            to find all non-overlapping matches in O(n) time.
        severity: Assessed severity of a positive match. One of ``"low"``,
            ``"medium"``, ``"high"``, ``"critical"``.
    """

    name: str
    regex: re.Pattern  # type: ignore[type-arg]
    severity: str


# ---------------------------------------------------------------------------
# Built-in pattern catalogue
# ---------------------------------------------------------------------------

#: Ordered list of (name, raw_pattern, severity) tuples for the five built-in
#: UK PII pattern types.  The order determines the index in the compiled list.
_BUILTIN_DEFINITIONS: list[tuple[str, str, str]] = [
    ("NI_NUMBER",   _NI_NUMBER,   "high"),
    ("NHS_NUMBER",  _NHS_NUMBER,  "high"),
    ("EMAIL",       _EMAIL,       "medium"),
    ("UK_PHONE",    _UK_PHONE,    "medium"),
    ("UK_POSTCODE", _UK_POSTCODE, "low"),
]

# Pre-compile all built-in patterns once at module import time.
# re.IGNORECASE is applied uniformly so that documents using lower-case
# letters (common for postcodes and NI numbers in typed text) are detected.
_BUILTIN_PATTERNS: list[PatternEntry] = [
    PatternEntry(
        name=name,
        regex=re.compile(raw, re.IGNORECASE),
        severity=severity,
    )
    for name, raw, severity in _BUILTIN_DEFINITIONS
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_patterns(
    custom_config_path: Optional[str | Path] = None,
) -> list[PatternEntry]:
    """Return a pre-compiled list of PII pattern entries.

    Always includes all five built-in UK patterns (NI number, NHS number,
    email, UK phone, UK postcode).  When *custom_config_path* is provided,
    additional patterns from that JSON file are appended **after** the
    built-ins.

    If a custom entry shares a name with a built-in, both are retained — the
    built-in appears first and a warning is logged.  This means the built-in
    pattern always has priority in any deduplication step the caller performs.

    Malformed entries (missing keys, invalid severity, un-compilable regex)
    are skipped with a warning so that the application can start with the
    valid patterns even when the config contains errors.

    Args:
        custom_config_path: Filesystem path to a JSON file containing an
            array of custom pattern objects.  Each object must contain:

            ``"name"`` (str)
                Category identifier, e.g. ``"EMPLOYEE_ID"``.
            ``"pattern"`` (str)
                Raw regex pattern string.
            ``"severity"`` (str)
                One of ``"low"``, ``"medium"``, ``"high"``, ``"critical"``.

            Pass ``None`` (the default) to use built-in patterns only.

    Returns:
        A :class:`list` of :class:`PatternEntry` objects in stable order:
        built-in patterns first, then custom patterns in file order.
        Every :attr:`PatternEntry.regex` is already compiled; no compilation
        occurs at scan time.

    Note:
        This function never raises.  All filesystem and JSON errors are
        handled internally and surfaced only as log messages so that a
        missing or corrupt config file does not prevent the service from
        starting.
    """
    patterns: list[PatternEntry] = list(_BUILTIN_PATTERNS)

    if custom_config_path is None:
        return patterns

    path = Path(custom_config_path)

    if not path.exists():
        logger.warning(
            "Custom PII pattern config not found: %s — using built-in patterns only",
            path,
        )
        return patterns

    try:
        raw_text = path.read_text(encoding="utf-8")
        entries = json.loads(raw_text)
    except OSError as exc:
        logger.error(
            "Cannot read custom PII pattern config %s: %s — "
            "using built-in patterns only",
            path,
            exc,
        )
        return patterns
    except json.JSONDecodeError as exc:
        logger.error(
            "Invalid JSON in custom PII pattern config %s: %s — "
            "using built-in patterns only",
            path,
            exc,
        )
        return patterns

    if not isinstance(entries, list):
        logger.error(
            "Custom PII pattern config %s must contain a JSON array at the root "
            "(got %s) — using built-in patterns only",
            path,
            type(entries).__name__,
        )
        return patterns

    builtin_names: frozenset[str] = frozenset(e.name for e in _BUILTIN_PATTERNS)
    loaded = 0

    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            logger.warning(
                "Custom PII pattern entry at index %d is not a JSON object — skipping",
                i,
            )
            continue

        name = entry.get("name")
        raw_pattern = entry.get("pattern")
        severity = entry.get("severity")

        if not name or not isinstance(name, str):
            logger.warning(
                "Custom PII pattern entry at index %d missing valid 'name' — skipping",
                i,
            )
            continue

        if not raw_pattern or not isinstance(raw_pattern, str):
            logger.warning(
                "Custom PII pattern %r at index %d missing valid 'pattern' — skipping",
                name,
                i,
            )
            continue

        if severity not in _VALID_SEVERITIES:
            logger.warning(
                "Custom PII pattern %r at index %d has invalid severity %r "
                "(must be one of %s) — skipping",
                name,
                i,
                severity,
                sorted(_VALID_SEVERITIES),
            )
            continue

        if name in builtin_names:
            logger.warning(
                "Custom PII pattern %r shadows a built-in pattern name — "
                "the built-in will still be applied; the custom entry is "
                "appended after it",
                name,
            )

        try:
            compiled = re.compile(raw_pattern, re.IGNORECASE)
        except re.error as exc:
            logger.error(
                "Custom PII pattern %r at index %d has invalid regex %r: %s — skipping",
                name,
                i,
                raw_pattern,
                exc,
            )
            continue

        patterns.append(PatternEntry(name=name, regex=compiled, severity=severity))
        loaded += 1

    logger.info(
        "Loaded %d custom PII pattern(s) from %s (total patterns: %d)",
        loaded,
        path,
        len(patterns),
    )
    return patterns


def get_builtin_patterns() -> list[PatternEntry]:
    """Return the pre-compiled built-in patterns without loading any config.

    This is a lightweight accessor that returns the module-level compiled list
    directly (no filesystem I/O, no JSON parsing).  Useful for callers that
    know they do not need custom patterns.

    Returns:
        A new list containing the five built-in :class:`PatternEntry` objects
        in their canonical order.
    """
    return list(_BUILTIN_PATTERNS)
