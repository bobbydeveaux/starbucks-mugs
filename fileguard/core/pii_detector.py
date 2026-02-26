"""PIIDetector — core PII scanning engine for the FileGuard pipeline.

:class:`PIIDetector` runs the compiled pattern set against text extracted from
a document and returns structured :class:`PIIFinding` objects.  Each finding
carries the pattern category, severity, matched value, and the byte offset of
the match within the *original file bytes* (mapped via the byte-offset list
produced by :class:`~fileguard.core.document_extractor.DocumentExtractor`).

Integration with the scan pipeline is via :class:`~fileguard.core.scan_context.ScanContext`:
calling :meth:`PIIDetector.scan` reads ``context.extracted_text`` and
``context.byte_offsets`` and appends :class:`PIIFinding` objects to
``context.findings``.

**Design notes**

* All regex patterns are pre-compiled by the pattern library at startup; no
  per-scan compilation occurs.
* Overlapping matches from different patterns are all reported independently.
* Empty input (``context.extracted_text`` is ``None`` or empty string) is a
  no-op; no findings are produced and no error is recorded.
* The detector is stateless after construction; the same instance can be used
  concurrently from multiple asyncio tasks.

Usage::

    from fileguard.core.pii_detector import PIIDetector
    from fileguard.core.scan_context import ScanContext

    detector = PIIDetector()           # uses built-in UK patterns
    ctx = ScanContext(file_bytes=b"...", mime_type="text/plain")
    ctx.extracted_text = "Patient NI: AB 12 34 56 C"
    ctx.byte_offsets = list(range(len(ctx.extracted_text)))
    detector.scan(ctx)
    print(ctx.findings)  # [PIIFinding(category='NI_NUMBER', ...)]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

from fileguard.core.patterns.uk_patterns import PatternDefinition, get_patterns
from fileguard.core.scan_context import ScanContext

logger = logging.getLogger(__name__)

Severity = Literal["low", "medium", "high", "critical"]


# ---------------------------------------------------------------------------
# Finding type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PIIFinding:
    """A single PII detection finding.

    Attributes:
        type: Always ``"pii"`` for PII engine findings.
        category: Pattern category that produced this finding
            (e.g. ``"NI_NUMBER"``, ``"NHS_NUMBER"``, ``"EMAIL"``).
        severity: Severity level assigned by the matching pattern.
        match: The exact substring that was matched.  **Note:** callers
            that store or forward findings should redact this field
            before persisting to audit logs or SIEM to avoid recording
            raw PII in secondary stores.
        offset: Best-effort byte offset in the *original file bytes* of
            the start of the matched text.  Derived from the
            ``byte_offsets`` list produced by
            :class:`~fileguard.core.document_extractor.DocumentExtractor`.
            ``-1`` if byte-offset mapping was unavailable.
    """

    type: Literal["pii"]
    category: str
    severity: Severity
    match: str
    offset: int


# ---------------------------------------------------------------------------
# PIIDetector
# ---------------------------------------------------------------------------


class PIIDetector:
    """Stateless PII scanning engine.

    Runs the compiled pattern set against extracted text and returns
    :class:`PIIFinding` objects.  Integrates with :class:`ScanContext` so
    findings are appended to the shared pipeline state.

    Args:
        patterns: Explicit list of :class:`~fileguard.core.patterns.uk_patterns.PatternDefinition`
            objects.  When ``None``, the built-in UK pattern set is used.
        custom_patterns_path: Path to a JSON custom-patterns file that is
            merged with the built-in patterns at construction time.  Ignored
            when *patterns* is supplied explicitly.

    Example — standalone usage::

        detector = PIIDetector()
        findings = detector.detect("Call me on 07700 900123", byte_offsets=[])
        for f in findings:
            print(f.category, f.match, f.offset)

    Example — pipeline integration::

        detector = PIIDetector()
        detector.scan(context)        # appends to context.findings
    """

    def __init__(
        self,
        patterns: Sequence[PatternDefinition] | None = None,
        custom_patterns_path: str | Path | None = None,
    ) -> None:
        if patterns is not None:
            self._patterns: list[PatternDefinition] = list(patterns)
        else:
            self._patterns = get_patterns(custom_patterns_path)

        logger.debug(
            "PIIDetector initialised with %d pattern(s): %s",
            len(self._patterns),
            [p.name for p in self._patterns],
        )

    # ------------------------------------------------------------------
    # Core detection
    # ------------------------------------------------------------------

    def detect(
        self,
        text: str,
        byte_offsets: list[int],
    ) -> list[PIIFinding]:
        """Run all patterns against *text* and return findings.

        Each regex is applied independently across the full text.  Matches
        from different patterns that overlap the same character range are all
        reported; there is no de-duplication or priority merging.

        Args:
            text: The extracted plain text to scan.  An empty string produces
                no findings.
            byte_offsets: Parallel list mapping text positions to byte offsets
                in the original file.  When non-empty, ``byte_offsets[i]`` is
                the byte offset of ``text[i]``.  When empty (e.g. the
                extraction stage did not produce offset data), ``offset`` in
                all findings is set to ``-1``.

        Returns:
            Unsorted list of :class:`PIIFinding` objects, one per regex match.
            An empty list is returned for empty *text* or when no patterns
            match.
        """
        if not text:
            return []

        findings: list[PIIFinding] = []

        for pattern_def in self._patterns:
            for match in pattern_def.pattern.finditer(text):
                start = match.start()
                byte_offset: int
                if byte_offsets and start < len(byte_offsets):
                    byte_offset = byte_offsets[start]
                else:
                    byte_offset = -1

                findings.append(
                    PIIFinding(
                        type="pii",
                        category=pattern_def.category,
                        severity=pattern_def.severity,
                        match=match.group(),
                        offset=byte_offset,
                    )
                )
                logger.debug(
                    "PII match: category=%s severity=%s offset=%d match=%r",
                    pattern_def.category,
                    pattern_def.severity,
                    byte_offset,
                    match.group(),
                )

        return findings

    # ------------------------------------------------------------------
    # Pipeline integration
    # ------------------------------------------------------------------

    def scan(self, context: ScanContext) -> None:
        """Scan the text in *context* and append findings to ``context.findings``.

        This is the primary pipeline integration point.  It reads
        ``context.extracted_text`` and ``context.byte_offsets``, calls
        :meth:`detect`, and extends ``context.findings`` with the results.

        The method is a no-op (no findings, no error) when
        ``context.extracted_text`` is ``None`` or an empty string, which
        occurs when document extraction was skipped or produced no output.

        Args:
            context: The shared :class:`~fileguard.core.scan_context.ScanContext`
                for the current scan.  Modified in place by appending
                :class:`PIIFinding` objects to ``context.findings``.
        """
        text = context.extracted_text
        if not text:
            logger.debug(
                "PIIDetector.scan: no extracted text in context (scan_id=%s); skipping",
                context.scan_id,
            )
            return

        findings = self.detect(text, context.byte_offsets)
        context.findings.extend(findings)

        logger.info(
            "PIIDetector.scan complete: scan_id=%s findings=%d",
            context.scan_id,
            len(findings),
        )
