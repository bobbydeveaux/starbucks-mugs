"""ScanContext — shared state object for the FileGuard scan pipeline.

:class:`ScanContext` is created once per scan request and passed through each
composable pipeline step (AV scan → document extraction → PII detection →
disposition).  Each step reads inputs from the context and appends its results
back to it, ensuring that all pipeline stages share a single authoritative
state object without coupling to each other directly.

Usage::

    from fileguard.core.scan_context import ScanContext

    ctx = ScanContext(file_bytes=raw_bytes, mime_type="application/pdf")
    # ... run pipeline steps ...
    print(ctx.findings)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScanContext:
    """Mutable shared state carried through the FileGuard scan pipeline.

    Attributes:
        file_bytes: Raw bytes of the file being scanned.
        mime_type: MIME type of the file (e.g. ``"application/pdf"``).
        scan_id: UUID string identifying this scan operation.  Automatically
            generated if not supplied.
        tenant_id: Tenant identifier, if available.  ``None`` for anonymous
            scans or when tenant resolution happens later in the pipeline.
        extracted_text: Plain text extracted by the
            :class:`~fileguard.core.document_extractor.DocumentExtractor`
            step.  ``None`` until extraction has run.
        byte_offsets: Parallel list to *extracted_text*.
            ``byte_offsets[i]`` is the best-effort byte offset in the
            original *file_bytes* of ``extracted_text[i]``.  Empty list
            until extraction has run.
        findings: Accumulated list of finding objects from all pipeline steps.
            AV steps append AV threat findings; PII detection appends
            :class:`~fileguard.core.pii_detector.PIIFinding` objects.
            The order reflects the pipeline execution order.
        errors: Human-readable error strings recorded by any pipeline step.
            Non-empty errors do *not* automatically abort the pipeline; each
            step decides whether an error is recoverable.
        metadata: Arbitrary key-value metadata attached by pipeline steps
            (e.g. page count from document extraction, redaction stats).
        request_redaction: When ``True``, the scan pipeline will redact PII
            spans in the extracted text and produce a
            :attr:`redacted_file_url`.  Defaults to ``False``.
        redacted_file_url: Time-limited signed URL pointing to the stored
            redacted file.  Populated by the redaction pipeline step when
            :attr:`request_redaction` is ``True`` and PII findings are
            present.  ``None`` otherwise.
    """

    file_bytes: bytes
    mime_type: str
    scan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str | None = None
    extracted_text: str | None = None
    byte_offsets: list[int] = field(default_factory=list)
    findings: list[Any] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    request_redaction: bool = False
    redacted_file_url: str | None = None
