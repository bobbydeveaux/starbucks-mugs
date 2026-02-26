"""RedactionEngine — PII span replacement and document reconstruction.

:class:`RedactionEngine` accepts a :class:`~fileguard.core.scan_context.ScanContext`
populated with :class:`~fileguard.core.pii_detector.PIIFinding` objects and
returns a redacted copy of the extracted text with every PII span replaced by
a configurable token (default: ``[REDACTED]``).

**Algorithm**

1. Collect all character-level spans by searching for each finding's ``match``
   string within ``context.extracted_text`` using a literal regex search.
   This handles duplicate occurrences of the same matched value correctly.
2. Sort spans by start position and merge any that overlap or are adjacent, to
   prevent double-redaction artefacts and index drift.
3. Reconstruct the output string by iterating through the merged spans from
   left to right, appending un-redacted segments and the replacement token
   alternately.  This is O(n) in the length of the text.

**Design notes**

* The engine is stateless after construction; the same instance is safe for
  concurrent use from multiple asyncio tasks.
* Findings that carry ``type != "pii"`` (e.g. AV findings) are silently
  ignored; only :class:`~fileguard.core.pii_detector.PIIFinding` objects
  participate in redaction.
* When ``context.extracted_text`` is ``None`` or an empty string, an empty
  string is returned immediately with no error.
* The redaction token is configurable at construction time so callers can use
  labelled tokens (e.g. ``"[REDACTED:EMAIL]"``) or masked tokens
  (``"████"``).

Usage::

    from fileguard.core.redaction import RedactionEngine
    from fileguard.core.scan_context import ScanContext

    engine = RedactionEngine()
    ctx = ScanContext(file_bytes=b"...", mime_type="text/plain")
    ctx.extracted_text = "Patient NI: AB 12 34 56 C, email: alice@nhs.uk"
    # ... run PIIDetector.scan(ctx) ...
    redacted = engine.redact(ctx)
    # "Patient NI: [REDACTED], email: [REDACTED]"
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fileguard.core.pii_detector import PIIFinding

from fileguard.core.scan_context import ScanContext

logger = logging.getLogger(__name__)


class RedactionEngine:
    """Stateless PII span replacement engine.

    Replaces all PII spans in the extracted text with a configurable
    redaction token.  Overlapping or adjacent spans are merged before
    substitution to prevent double-redaction and index drift.

    Args:
        token: The replacement string inserted in place of each PII span.
            Defaults to ``"[REDACTED]"``.

    Example — basic usage::

        engine = RedactionEngine()
        redacted = engine.redact(context)

    Example — custom token::

        engine = RedactionEngine(token="[PII REMOVED]")
        redacted = engine.redact(context)
    """

    DEFAULT_TOKEN: str = "[REDACTED]"

    def __init__(self, token: str = DEFAULT_TOKEN) -> None:
        self._token = token

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def redact(self, context: ScanContext) -> str:
        """Redact PII spans in ``context.extracted_text``.

        Steps
        -----
        1. Build a reverse map ``{byte_offset: char_index}`` from
           ``context.byte_offsets``.
        2. For each PII finding in ``context.findings``, locate the
           corresponding character span in ``extracted_text`` — using the
           reverse map when ``offset != -1``, or a substring search
           otherwise.
        3. Merge overlapping / adjacent spans.
        4. Apply substitutions left-to-right to reconstruct the output.

        Args:
            context: Populated :class:`~fileguard.core.scan_context.ScanContext`
                with ``extracted_text`` and ``findings``.

        Returns:
            Redacted text string.  An empty string is returned when
            ``context.extracted_text`` is ``None`` or empty, or when there
            are no PII findings.
        """
        text = context.extracted_text or ""
        if not text:
            logger.debug(
                "RedactionEngine.redact: no extracted text (scan_id=%s); returning empty",
                context.scan_id,
            )
            return text

        # Import here to avoid circular imports at module level.
        from fileguard.core.pii_detector import PIIFinding  # noqa: PLC0415

        pii_findings: list[PIIFinding] = [
            f for f in context.findings if isinstance(f, PIIFinding)
        ]

        if not pii_findings:
            logger.debug(
                "RedactionEngine.redact: no PII findings (scan_id=%s); text unchanged",
                context.scan_id,
            )
            return text

        # Build reverse map: byte_offset → first char index at that offset
        byte_to_char: dict[int, int] = {}
        for char_idx, byte_off in enumerate(context.byte_offsets):
            if byte_off not in byte_to_char:
                byte_to_char[byte_off] = char_idx

        spans = self._collect_spans(text, pii_findings, byte_to_char)
        merged = self._merge_spans(spans)
        result = self._apply_replacements(text, merged)

        logger.info(
            "RedactionEngine.redact: scan_id=%s spans_merged=%d input_len=%d output_len=%d",
            context.scan_id,
            len(merged),
            len(text),
            len(result),
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_spans(
        self,
        text: str,
        findings: list,
        byte_to_char: dict[int, int],
    ) -> list[tuple[int, int]]:
        """Convert PIIFinding objects into (start, end) character spans.

        For each finding, the primary lookup path uses the ``byte_to_char``
        reverse map (built from ``context.byte_offsets``) when
        ``finding.offset != -1`` and the offset is present in the map.  If
        the mapped character position does not match the expected text, or if
        ``offset == -1``, a fallback regex search finds all occurrences of
        the match string across the full text (ensuring repeated PII values
        are all captured).

        Args:
            text: The extracted text to search.
            findings: PII findings whose ``match`` values locate spans.
            byte_to_char: Reverse map from byte offset to character index.

        Returns:
            Unsorted list of ``(start, end)`` half-open character intervals.
        """
        spans: list[tuple[int, int]] = []

        # Deduplicate match strings to avoid redundant searches.
        seen: set[str] = set()
        for finding in findings:
            match_str: str = getattr(finding, "match", "")
            byte_offset: int = getattr(finding, "offset", -1)

            if not match_str or match_str in seen:
                continue
            seen.add(match_str)

            span_found_via_offset = False

            # --- primary path: use byte-offset reverse map ------------------
            if byte_offset != -1 and byte_offset in byte_to_char:
                char_start = byte_to_char[byte_offset]
                char_end = char_start + len(match_str)
                # Validate that the text slice actually matches
                if text[char_start:char_end] == match_str:
                    spans.append((char_start, char_end))
                    logger.debug(
                        "RedactionEngine: span (%d, %d) for match %r (via byte offset)",
                        char_start,
                        char_end,
                        match_str,
                    )
                    span_found_via_offset = True
                else:
                    # Offset map mismatch — fall through to regex search
                    logger.debug(
                        "RedactionEngine: byte-offset mismatch for match=%r at char=%d; "
                        "falling back to regex search",
                        match_str,
                        char_start,
                    )

            # --- fallback path: regex search for all occurrences ------------
            if not span_found_via_offset:
                for m in re.finditer(re.escape(match_str), text):
                    spans.append((m.start(), m.end()))
                    logger.debug(
                        "RedactionEngine: span (%d, %d) for match %r (via regex)",
                        m.start(),
                        m.end(),
                        match_str,
                    )

        return spans

    @staticmethod
    def _merge_spans(
        spans: list[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        """Merge overlapping and adjacent ``(start, end)`` spans.

        Returns a sorted list of non-overlapping, non-adjacent spans that
        cover the union of all input spans.  Adjacent spans (where one span
        ends exactly where the next begins) are merged to produce a single
        contiguous replacement token.

        Args:
            spans: Unsorted list of ``(start, end)`` character spans.

        Returns:
            Sorted, merged list of ``(start, end)`` spans.  Empty list when
            *spans* is empty.
        """
        if not spans:
            return []

        sorted_spans = sorted(spans)
        merged: list[tuple[int, int]] = [sorted_spans[0]]

        for start, end in sorted_spans[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:
                # Overlapping or adjacent — extend the current merged span.
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))

        return merged

    def _apply_replacements(
        self,
        text: str,
        spans: list[tuple[int, int]],
    ) -> str:
        """Reconstruct the text with merged spans replaced by the token.

        Iterates through the sorted, merged spans from left to right,
        collecting un-redacted segments and interleaving the replacement
        token.  This is O(n) in ``len(text)``.

        Args:
            text: Original extracted text.
            spans: Sorted, merged ``(start, end)`` spans to replace.

        Returns:
            Reconstructed string with every span replaced by :attr:`_token`.
        """
        if not spans:
            return text

        parts: list[str] = []
        prev_end = 0

        for start, end in spans:
            # Preserve text before this span.
            parts.append(text[prev_end:start])
            # Insert the redaction token.
            parts.append(self._token)
            prev_end = end

        # Append any trailing non-PII text.
        parts.append(text[prev_end:])
        return "".join(parts)
