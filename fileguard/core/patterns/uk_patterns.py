"""UK PII regex pattern library for FileGuard.

Provides pre-compiled regex patterns for the five built-in UK PII categories:

* **NI_NUMBER** — UK National Insurance numbers (e.g. ``AB123456C``)
* **NHS_NUMBER** — UK NHS numbers (10-digit, space/hyphen-separated)
* **EMAIL** — Email addresses (RFC-5321 simplified)
* **PHONE** — UK telephone numbers (mobile, landline, and international prefix)
* **POSTCODE** — UK postcodes (e.g. ``SW1A 1AA``, ``EC1A 1BB``)

All built-in patterns are pre-compiled at **module load time** so no
re-compilation occurs at scan time.

Custom patterns can be loaded from a JSON config file using
:func:`load_custom_patterns` and merged with the built-in set via
:func:`get_patterns`.

JSON config file format::

    [
        {
            "name": "EMPLOYEE_ID",
            "pattern": "EMP-[0-9]{6}",
            "severity": "medium"
        }
    ]

Usage::

    from fileguard.core.patterns.uk_patterns import get_patterns

    patterns = get_patterns()          # built-in only
    patterns = get_patterns("/etc/fileguard/custom_patterns.json")  # merged
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Severity = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class PatternDefinition:
    """A single compiled PII pattern definition.

    Attributes:
        name: Unique pattern identifier used as the finding category
            (e.g. ``"NI_NUMBER"``).
        pattern: Pre-compiled :class:`re.Pattern` ready for matching.
        severity: Severity level assigned to findings produced by this
            pattern.
        category: Finding category label.  Defaults to *name*.
    """

    name: str
    pattern: re.Pattern[str]
    severity: Severity
    category: str


# ---------------------------------------------------------------------------
# Built-in pattern definitions (name, raw_regex, severity)
# ---------------------------------------------------------------------------

_BUILTIN_RAW: list[tuple[str, str, Severity]] = [
    # National Insurance number.
    # Format: two prefix letters (D, F, I, Q, U, V excluded as first; D, F,
    # I, O, Q, U, V excluded as second), six digits, suffix A-D.
    # Allows optional spaces between groups (e.g. "AB 12 34 56 C").
    (
        "NI_NUMBER",
        r"\b[A-CEGHJ-PR-TW-Z][A-CEGHJ-PR-TW-Z][0-9]{2}\s?[0-9]{2}\s?[0-9]{2}\s?[A-D]\b",
        "high",
    ),
    # NHS number.
    # 10 digits, optionally separated by spaces or hyphens in groups of
    # 3-3-4 (e.g. "943 476 5919" or "9434765919").
    (
        "NHS_NUMBER",
        r"\b[0-9]{3}[\s\-]?[0-9]{3}[\s\-]?[0-9]{4}\b",
        "high",
    ),
    # Email address (RFC-5321 simplified — covers the vast majority of
    # real-world addresses without false positives from version numbers).
    (
        "EMAIL",
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
        "medium",
    ),
    # UK telephone number.
    # Covers: 01xx/02x landlines, 07xxx mobiles, 08xx/09xx service numbers,
    # and +44 international prefix.  Accepts spaces and hyphens as
    # separators.  Minimum 9 digits after the prefix.
    (
        "PHONE",
        r"\b(?:\+44[\s\-]?|0)(?:[0-9][\s\-]?){9,12}[0-9]\b",
        "medium",
    ),
    # UK postcode.
    # Covers all valid postcode formats (AN, ANN, AAN, AANN, ANA, AANA).
    # Optional single space between outward and inward codes.
    (
        "POSTCODE",
        r"\b[A-Z]{1,2}[0-9][0-9A-Z]?\s?[0-9][A-Z]{2}\b",
        "low",
    ),
]


def _compile(raw: list[tuple[str, str, Severity]]) -> list[PatternDefinition]:
    """Compile raw pattern tuples into :class:`PatternDefinition` objects."""
    return [
        PatternDefinition(
            name=name,
            pattern=re.compile(regex, re.ASCII),
            severity=severity,
            category=name,
        )
        for name, regex, severity in raw
    ]


# Pre-compiled at module load — zero per-scan compilation overhead.
BUILTIN_PATTERNS: list[PatternDefinition] = _compile(_BUILTIN_RAW)


# ---------------------------------------------------------------------------
# Custom pattern loading
# ---------------------------------------------------------------------------


def load_custom_patterns(config_path: str | Path) -> list[PatternDefinition]:
    """Load and compile custom patterns from a JSON config file.

    The file must contain a JSON array of objects, each with the keys
    ``name`` (str), ``pattern`` (str regex), and ``severity``
    (``"low"`` | ``"medium"`` | ``"high"`` | ``"critical"``).

    Patterns are compiled with :data:`re.UNICODE` so they can match
    non-ASCII identifiers defined by organisations operating in
    multilingual environments.

    Args:
        config_path: Path to the JSON configuration file.

    Returns:
        List of compiled :class:`PatternDefinition` objects.

    Raises:
        FileNotFoundError: If *config_path* does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
        KeyError: If a pattern entry is missing a required key.
        re.error: If a pattern entry contains an invalid regex.
    """
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as fh:
        entries = json.load(fh)

    result: list[PatternDefinition] = []
    for entry in entries:
        name: str = entry["name"]
        raw_pattern: str = entry["pattern"]
        severity: Severity = entry["severity"]
        category: str = entry.get("category", name)
        result.append(
            PatternDefinition(
                name=name,
                pattern=re.compile(raw_pattern, re.UNICODE),
                severity=severity,
                category=category,
            )
        )
    return result


def get_patterns(
    custom_patterns_path: str | Path | None = None,
) -> list[PatternDefinition]:
    """Return the full pattern set, merging built-in with custom patterns.

    Built-in patterns are always included.  When *custom_patterns_path* is
    provided, custom patterns are appended after the built-in set so they
    take effect in addition to (not instead of) the built-ins.

    Args:
        custom_patterns_path: Optional path to a JSON custom patterns file.
            When ``None``, only built-in patterns are returned.

    Returns:
        Combined list of :class:`PatternDefinition` objects.
    """
    patterns: list[PatternDefinition] = list(BUILTIN_PATTERNS)
    if custom_patterns_path is not None:
        patterns.extend(load_custom_patterns(custom_patterns_path))
    return patterns
