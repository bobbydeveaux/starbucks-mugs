# UK PII Pattern Library

**Module:** `fileguard.core.patterns.uk_patterns`
**Status:** Implemented (Sprint 3)

---

## Overview

The UK PII pattern library provides a curated set of pre-compiled regular
expressions for detecting the five primary UK personally identifiable
information (PII) types in scanned documents.  All patterns are compiled
once at module import time so that no regex compilation occurs during scan
execution.

The library also supports loading additional organisation-specific patterns
from a JSON configuration file at startup, merging them with the built-in
set (see [Custom Patterns](#custom-patterns)).

---

## Built-in Patterns

| Name | Category | Severity | Examples |
|---|---|---|---|
| `NI_NUMBER` | National Insurance number | `high` | `AB123456C`, `AB 12 34 56 C` |
| `NHS_NUMBER` | NHS number (10-digit) | `high` | `943 476 5919`, `9434765919` |
| `EMAIL` | Email address | `medium` | `user@example.com`, `first.last@nhs.uk` |
| `UK_PHONE` | UK telephone number | `medium` | `07700 900123`, `+44 20 7946 0958` |
| `UK_POSTCODE` | UK postcode | `low` | `SW1A 1AA`, `EC1A 1BB`, `M1 1AE` |

All patterns use `re.IGNORECASE` so that documents containing lower-case
representations (common in typed correspondence) are detected correctly.

### NI Number (`NI_NUMBER`)

Matches National Insurance numbers in compact (`AA123456C`) or card-printed
spaced form (`AA 12 34 56 C`).

The character class for the two-letter prefix excludes the letters
**D, F, I, Q, U, V** from both positions and additionally **O** from the
second position, consistent with the HMRC NI number specification.  The
suffix letter must be **A–D**.

> **Note:** Deeper validation (reserved prefix pairs such as `BG`, `GB`,
> `KN`, `NK`, `NT`, `TN`, `ZZ`) is not enforced by the regex.  Apply
> application-level filtering where stricter matching is required.

### NHS Number (`NHS_NUMBER`)

Matches the 10-digit NHS number in compact (`9434765919`) or
spaced/hyphenated display format (`943 476 5919`, `943-476-5919`).

> **Note:** The mod-11 check digit algorithm is not evaluated by the regex.
> Apply the DV check algorithm in code when false-positive reduction is
> required.

### Email (`EMAIL`)

Matches the vast majority of real-world email addresses using a practical
pattern that balances precision with recall.  Internationalised local parts
and multi-level domains are supported.

### UK Phone (`UK_PHONE`)

Accepts UK telephone numbers with the following prefix families:

- `+44` / `0044` — E.164 international dialling prefix
- `0` — standard UK national prefix (landline and mobile)

Digits may be grouped with spaces or hyphens in any common format.

### UK Postcode (`UK_POSTCODE`)

Covers all Royal Mail PAF outward/inward code formats:

| Format | Example |
|---|---|
| AN NAA | `M1 1AE` |
| ANN NAA | `M60 1NW` |
| AAN NAA | `CR2 6XH` |
| AANN NAA | `DN55 1PT` |
| ANA NAA | `W1A 1HQ` |
| AANA NAA | `EC1A 1BB` |

---

## API Reference

### `PatternEntry`

```python
@dataclass(frozen=True)
class PatternEntry:
    name: str          # Category identifier, e.g. "NI_NUMBER"
    regex: re.Pattern  # Pre-compiled regular expression
    severity: str      # "low" | "medium" | "high" | "critical"
```

Immutable dataclass representing a single PII pattern.  Use
`entry.regex.finditer(text)` to locate all non-overlapping matches.

### `load_patterns(custom_config_path=None)`

```python
def load_patterns(
    custom_config_path: str | Path | None = None,
) -> list[PatternEntry]:
    ...
```

Returns a pre-compiled list of `PatternEntry` objects.  Always includes the
five built-in UK patterns.  When `custom_config_path` is provided, custom
patterns from that JSON file are appended after the built-ins.

This function never raises — filesystem and JSON errors are logged and the
application continues with the built-in patterns only.

### `get_builtin_patterns()`

```python
def get_builtin_patterns() -> list[PatternEntry]:
    ...
```

Lightweight accessor that returns the built-in patterns without any
filesystem I/O.  Useful when custom patterns are not required.

---

## Custom Patterns

Custom patterns extend the built-in set without modifying the source code.
They are loaded from a JSON file at startup and merged after the built-ins.

### File Format

The file must contain a **JSON array** at the root.  Each element is an
object with the following fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | Category identifier used in scan findings |
| `pattern` | string | Yes | Raw Python regex pattern string |
| `severity` | string | Yes | One of `"low"`, `"medium"`, `"high"`, `"critical"` |

**Example:**

```json
[
    {
        "name": "EMPLOYEE_ID",
        "pattern": "EMP-\\d{6}",
        "severity": "medium"
    },
    {
        "name": "INTERNAL_REF",
        "pattern": "REF-[A-Z]{3}-\\d{4}",
        "severity": "low"
    }
]
```

### Loading Custom Patterns

Pass the config file path to `load_patterns()`:

```python
from fileguard.core.patterns.uk_patterns import load_patterns

# At service startup:
patterns = load_patterns("/etc/fileguard/custom_patterns.json")
```

### Error Handling

The following errors are handled gracefully (logged, entry skipped):

| Condition | Behaviour |
|---|---|
| Config file not found | Warning logged; built-in patterns returned |
| File is not valid JSON | Error logged; built-in patterns returned |
| Root is not a JSON array | Error logged; built-in patterns returned |
| Entry missing `name` or `pattern` | Warning logged; entry skipped |
| Invalid `severity` value | Warning logged; entry skipped |
| Invalid regex in `pattern` | Error logged; entry skipped |
| Non-object entry in array | Warning logged; entry skipped |

If a custom entry uses the same `name` as a built-in pattern, both are
retained (built-in first, custom appended) and a warning is logged.

---

## Usage in the Scan Pipeline

The pattern list is consumed by `PIIDetector` (Sprint 3, task 2):

```python
from fileguard.core.patterns.uk_patterns import load_patterns
from fileguard.config import settings

# Initialise once at application startup.
_patterns = load_patterns(settings.CUSTOM_PATTERNS_PATH)

# At scan time:
for entry in _patterns:
    for match in entry.regex.finditer(extracted_text):
        findings.append(Finding(
            type=FindingType.PII,
            category=entry.name,
            severity=FindingSeverity(entry.severity),
            offset=match.start(),
            match="[REDACTED]",
        ))
```

---

## Performance Notes

- All five built-in patterns are compiled **once at module import** using
  `re.compile(pattern, re.IGNORECASE)`.
- Custom patterns are compiled once in `load_patterns()` at startup.
- No regex compilation occurs at scan time — `finditer()` uses the
  pre-compiled `re.Pattern` object directly.
- Word boundaries (`\b`) are used on all patterns to avoid partial matches
  inside longer alphanumeric sequences.
