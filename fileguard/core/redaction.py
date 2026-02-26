"""RedactionEngine — span-based PII redaction for the FileGuard scan pipeline.

:class:`RedactionEngine` accepts a :class:`~fileguard.core.scan_context.ScanContext`
whose ``findings`` list has been populated by :class:`~fileguard.core.pii_detector.PIIDetector`,
and returns a copy of ``extracted_text`` with every PII span replaced by
the token ``[REDACTED]``.

**Span detection** relies on two pieces of information present in each
:class:`~fileguard.core.pii_detector.PIIFinding`:

* ``match`` — the exact substring that was matched.
* ``offset`` — the byte offset in the *original file bytes* where the match
  starts, produced by the ``byte_offsets`` map maintained in
  :class:`~fileguard.core.scan_context.ScanContext`.

A reverse mapping from byte offsets to character positions in
``extracted_text`` is built once per call, allowing O(1) span lookup for
findings that carry a valid ``offset``.  Findings with ``offset == -1``
(i.e. byte-offset mapping was unavailable) fall back to a left-to-right
substring search in the extracted text.

**Overlap handling:** overlapping or immediately adjacent spans are merged
into a single replacement span before substitution, preventing double
redaction and index drift.

**Substitution order:** replacements are applied right-to-left so that
earlier span indices are not invalidated by upstream replacements.

Usage::

    from fileguard.core.redaction import RedactionEngine
    from fileguard.core.scan_context import ScanContext

    engine = RedactionEngine()
    ctx = ScanContext(file_bytes=b"...", mime_type="text/plain")
    ctx.extracted_text = "Patient NI: AB123456C, email: alice@example.com"
    ctx.byte_offsets = list(range(len(ctx.extracted_text)))
    # ... populate ctx.findings with PIIFinding objects ...
    redacted = engine.redact(ctx)
    # "Patient NI: [REDACTED], email: [REDACTED]"
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fileguard.core.scan_context import ScanContext

logger = logging.getLogger(__name__)

REDACTED_TOKEN = "[REDACTED]"


class RedactionEngine:
    """Stateless PII span redaction engine.

    Replaces each detected PII span in ``context.extracted_text`` with the
    token ``[REDACTED]`` and returns the resulting string.  The engine is
    safe for concurrent use from multiple asyncio tasks.

    Typical usage inside the scan pipeline::

        engine = RedactionEngine()
        redacted_text = engine.redact(context)
        # Store or forward redacted_text as needed.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def redact(self, context: "ScanContext") -> str:
        """Return a copy of ``context.extracted_text`` with PII spans replaced.

        Steps
        -----
        1. Build a reverse map ``{byte_offset: char_index}`` from
           ``context.byte_offsets``.
        2. For each PII finding in ``context.findings``, locate the
           corresponding character span in ``extracted_text`` — using the
           reverse map when ``offset != -1``, or a substring search
           otherwise.
        3. Merge overlapping / adjacent spans.
        4. Apply substitutions right-to-left to preserve index validity.

        Args:
            context: Shared scan state.  ``extracted_text`` and ``findings``
                must be populated by upstream pipeline steps.

        Returns:
            The redacted string.  Returns an empty string if
            ``context.extracted_text`` is ``None`` or empty, which is a
            no-op condition (nothing to redact).
        """
        text = context.extracted_text or ""
        if not text:
            logger.debug(
                "RedactionEngine.redact: no extracted text (scan_id=%s); skipping",
                context.scan_id,
            )
            return text

        pii_findings = [
            f for f in context.findings if getattr(f, "type", None) == "pii"
        ]
        if not pii_findings:
            logger.debug(
                "RedactionEngine.redact: no PII findings (scan_id=%s); no redaction needed",
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
        redacted = self._apply_redaction(text, merged)

        logger.info(
            "RedactionEngine.redact: scan_id=%s pii_findings=%d spans=%d",
            context.scan_id,
            len(pii_findings),
            len(merged),
        )
        return redacted

    # ------------------------------------------------------------------
    # Span collection
    # ------------------------------------------------------------------

    def _collect_spans(
        self,
        text: str,
        findings: list,
        byte_to_char: dict[int, int],
    ) -> list[tuple[int, int]]:
        """Convert PIIFinding objects into (start, end) character spans.

        Args:
            text: The extracted text in which spans are located.
            findings: List of PII findings from the scan pipeline.
            byte_to_char: Reverse map from byte offset to character index.

        Returns:
            List of ``(start, end)`` character index tuples (exclusive end).
        """
        spans: list[tuple[int, int]] = []
        # Track covered positions to avoid re-using the same string position
        # for multiple findings that share the same matched value.
        used_positions: set[int] = set()

        for finding in findings:
            match_str: str = getattr(finding, "match", "")
            byte_offset: int = getattr(finding, "offset", -1)

            if not match_str:
                continue

            span: tuple[int, int] | None = None

            # --- primary path: use byte-offset reverse map ------------------
            if byte_offset != -1 and byte_offset in byte_to_char:
                char_start = byte_to_char[byte_offset]
                char_end = char_start + len(match_str)
                # Validate that the text slice actually matches
                if text[char_start:char_end] == match_str:
                    span = (char_start, char_end)
                else:
                    # Offset map mismatch — fall through to substring search
                    logger.debug(
                        "RedactionEngine: byte-offset mismatch for match=%r at char=%d; "
                        "falling back to substring search",
                        match_str,
                        char_start,
                    )

            # --- fallback path: substring search ----------------------------
            if span is None:
                search_start = 0
                while True:
                    pos = text.find(match_str, search_start)
                    if pos == -1:
                        break
                    if pos not in used_positions:
                        span = (pos, pos + len(match_str))
                        break
                    search_start = pos + 1

            if span is not None:
                spans.append(span)
                used_positions.add(span[0])

        return spans

    # ------------------------------------------------------------------
    # Span merging
    # ------------------------------------------------------------------

    def _merge_spans(
        self,
        spans: list[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        """Merge overlapping or adjacent ``(start, end)`` spans.

        Spans are sorted by ``start`` and then merged greedily: two spans
        are merged when the second's ``start`` is less than or equal to
        the first's ``end`` (touching or overlapping).

        Args:
            spans: Unsorted list of ``(start, end)`` character spans.

        Returns:
            Sorted list of non-overlapping, non-adjacent merged spans.
        """
        if not spans:
            return []

        sorted_spans = sorted(spans)
        merged: list[tuple[int, int]] = [sorted_spans[0]]

        for start, end in sorted_spans[1:]:
            prev_start, prev_end = merged[-1]
            if start <= prev_end:
                # Overlapping or adjacent — extend the current span
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))

        return merged

    # ------------------------------------------------------------------
    # Substitution
    # ------------------------------------------------------------------

    def _apply_redaction(
        self,
        text: str,
        merged_spans: list[tuple[int, int]],
    ) -> str:
        """Replace character spans in *text* with :data:`REDACTED_TOKEN`.

        Substitutions are applied right-to-left so that earlier span
        indices remain valid throughout the process.

        Args:
            text: The original extracted text.
            merged_spans: Sorted, non-overlapping ``(start, end)`` spans.

        Returns:
            The redacted string.
        """
        chars = list(text)
        for start, end in reversed(merged_spans):
            chars[start:end] = list(REDACTED_TOKEN)
        return "".join(chars)
