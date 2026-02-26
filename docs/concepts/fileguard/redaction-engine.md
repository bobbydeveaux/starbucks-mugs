# PII Redaction Engine

**Module:** `fileguard.core.redaction`
**Status:** Implemented (Sprint 4)

---

## Overview

The Redaction Engine (`RedactionEngine`) replaces matched PII spans in
extracted document text with a configurable token (default: `[REDACTED]`).
It is a pure, stateless post-processing step that follows the PII detection
stage in the scan pipeline.

The engine operates on the `extracted_text` field of a `ScanContext` and
reads `PIIFinding` objects from `context.findings` (other finding types, such
as AV threat findings, are silently ignored).

---

## Algorithm

1. **Collect spans** — For each unique `PIIFinding.match` value, search the
   extracted text with `re.finditer(re.escape(match), text)` and record every
   occurrence as a `(start, end)` character interval.  Literal (non-regex)
   matching ensures special characters in PII values (e.g. `+`, `.`) are
   treated as literal characters, not metacharacters.

2. **Merge spans** — Sort all spans by start position and merge any that
   overlap or are adjacent.  Merging prevents double-redaction artefacts
   (e.g. a single phone number matched by two patterns would otherwise produce
   `[REDACTED][REDACTED]` rather than a single `[REDACTED]`).

3. **Reconstruct** — Iterate through the merged spans from left to right,
   appending un-redacted text segments and replacement tokens alternately.
   This is O(n) in the length of the text and avoids index-drift errors.

---

## Class Reference

### `RedactionEngine`

```python
class RedactionEngine:
    DEFAULT_TOKEN: str = "[REDACTED]"

    def __init__(self, token: str = DEFAULT_TOKEN) -> None: ...

    def redact(self, context: ScanContext) -> str: ...
```

#### Constructor

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `token` | `str` | `"[REDACTED]"` | Replacement string inserted in place of each PII span. |

#### `redact(context)`

| Parameter | Type | Description |
|-----------|------|-------------|
| `context` | `ScanContext` | Populated context with `extracted_text` and `findings`. |

**Returns:** Redacted text string.  Empty string when `extracted_text` is
`None` or empty, or when there are no PII findings.

**Side-effects:** None.  `context.extracted_text` and `context.findings`
are not modified.

---

## Usage

### Basic pipeline integration

```python
from fileguard.core.pii_detector import PIIDetector
from fileguard.core.redaction import RedactionEngine
from fileguard.core.scan_context import ScanContext

detector = PIIDetector()
engine = RedactionEngine()

ctx = ScanContext(file_bytes=b"...", mime_type="text/plain")
ctx.extracted_text = "Patient NI: AB 12 34 56 C, email: alice@nhs.uk"
ctx.byte_offsets = list(range(len(ctx.extracted_text)))

detector.scan(ctx)         # populates ctx.findings
redacted = engine.redact(ctx)
# "Patient NI: [REDACTED], email: [REDACTED]"
```

### Custom token

```python
engine = RedactionEngine(token="[PII REMOVED]")
redacted = engine.redact(ctx)
# "Patient NI: [PII REMOVED], email: [PII REMOVED]"
```

---

## Behaviour details

### Overlapping and adjacent spans

When two or more patterns match the same or adjacent regions of text, all
matching spans are merged into a single replacement token:

```
Input:  "07700 900123"
Span A: (0, 12)  ← PHONE pattern
Span B: (6, 12)  ← partial digit sub-match
Merged: (0, 12)  → "[REDACTED]"
```

### Repeated PII values

The same PII value appearing multiple times in the text is redacted at
every occurrence:

```
Input:  "From: alice@example.com CC: alice@example.com"
Output: "From: [REDACTED] CC: [REDACTED]"
```

### Non-PII findings are ignored

The engine filters `context.findings` by `isinstance(f, PIIFinding)`.
AV threat findings or other future finding types do not participate in
redaction.

### Context immutability

`redact()` reads from the context but never writes to it.  Callers may
inspect `context.extracted_text` and `context.findings` unchanged after
the call.

---

## Testing

Unit tests covering all acceptance criteria are in
`tests/unit/test_redaction.py`:

| Test class | Scenario covered |
|---|---|
| `TestZeroFindings` | No findings → text unchanged |
| `TestEmptyText` | `None` or empty `extracted_text` → empty string |
| `TestSingleSpan` | Single match at start, middle, and end |
| `TestMultipleNonOverlappingSpans` | Multiple distinct matches |
| `TestOverlappingSpans` | Overlapping matches merged into one token |
| `TestAdjacentSpans` | Adjacent matches merged; non-adjacent kept separate |
| `TestRepeatedMatches` | Same value at multiple positions all redacted |
| `TestCustomToken` | Custom and empty token |
| `TestNonPIIFindingsIgnored` | AV findings do not trigger redaction |
| `TestContextNotMutated` | Input context untouched after call |
| `TestCharacterLevelDiff` | Non-PII characters preserved exactly |
| `TestMergeSpans` | Unit tests for `_merge_spans` helper |
| `TestCollectSpans` | Unit tests for `_collect_spans` helper |
