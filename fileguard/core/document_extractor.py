"""DocumentExtractor: multi-format text extraction with byte-offset mapping.

Supports PDF (pdfminer.six), DOCX (python-docx), CSV, JSON, TXT, and ZIP
archives.  ZIP archives are recursively unpacked and each contained file is
extracted using the appropriate format handler.

Thread-pool execution is used for CPU-bound extraction calls so that the
asyncio event loop is never blocked.

Usage::

    from fileguard.core.document_extractor import DocumentExtractor

    extractor = DocumentExtractor()

    result = await extractor.extract(file_bytes, "application/pdf")
    print(result.text)
    for entry in result.offsets:
        span = result.text[entry.text_start:entry.text_end]
        print(f"Span {entry.text_start}:{entry.text_end} -> {span!r}")
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

#: MIME types supported by DocumentExtractor.
SUPPORTED_MIME_TYPES: frozenset[str] = frozenset({
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/csv",
    "application/json",
    "text/plain",
    "application/zip",
    "application/x-zip-compressed",
})


class ExtractionError(Exception):
    """Raised when :class:`DocumentExtractor` cannot process a file.

    This exception is raised for:

    * Unsupported MIME types.
    * Corrupt or malformed files (e.g. truncated PDF, invalid ZIP).
    * Unexpected failures inside the extraction library.

    Callers should treat this as a hard error; the scan pipeline must not
    silently return empty output when extraction fails.
    """


@dataclass
class OffsetEntry:
    """Maps a span of normalised output text back to the source byte range.

    Attributes:
        text_start: Start character index (inclusive) in the normalised text.
        text_end:   End character index (exclusive) in the normalised text.
        byte_start: Start byte offset (inclusive) in the original content.
        byte_end:   End byte offset (exclusive) in the original content.

    Invariant::

        normalised_text[text_start:text_end]  # gives the extracted span
    """

    text_start: int
    text_end: int
    byte_start: int
    byte_end: int


@dataclass
class ExtractionResult:
    """Result of a document extraction operation.

    Attributes:
        text:    Normalised, flattened text extracted from the document.
        offsets: Byte-offset map linking spans of *text* back to their
                 approximate source position in the original content bytes.
    """

    text: str
    offsets: list[OffsetEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DocumentExtractor
# ---------------------------------------------------------------------------


class DocumentExtractor:
    """Extract text and a byte-offset map from multi-format documents.

    CPU-bound extraction is dispatched to a :class:`~concurrent.futures.ThreadPoolExecutor`
    via :func:`asyncio.get_event_loop().run_in_executor` so that the event
    loop remains responsive during heavy workloads.

    Args:
        max_workers: Number of worker threads in the pool.  Defaults to
            ``settings.THREAD_POOL_WORKERS`` when *None*.

    Supported formats (by MIME type):

    ============================================================= ==================
    Format                                                        MIME type
    ============================================================= ==================
    PDF                                                           ``application/pdf``
    DOCX                                                          ``application/vnd.openxmlformats-officedocument.wordprocessingml.document``
    CSV                                                           ``text/csv``
    JSON                                                          ``application/json``
    Plain text                                                    ``text/plain``
    ZIP archive (recursive)                                       ``application/zip``
    ============================================================= ==================
    """

    def __init__(self, max_workers: int | None = None) -> None:
        if max_workers is None:
            from fileguard.config import settings
            max_workers = settings.THREAD_POOL_WORKERS
        self._executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="doc-extractor",
        )

    # ------------------------------------------------------------------
    # Public async interface
    # ------------------------------------------------------------------

    async def extract(self, content: bytes, mime_type: str) -> ExtractionResult:
        """Extract text from *content* using the configured thread pool.

        The synchronous extraction work is dispatched via
        :meth:`asyncio.AbstractEventLoop.run_in_executor` so that this
        coroutine returns immediately to the event loop while the CPU-bound
        work executes in a background thread.

        Args:
            content:   Raw bytes of the document.
            mime_type: MIME type string identifying the document format.
                       Leading/trailing whitespace and charset parameters
                       (e.g. ``text/plain; charset=utf-8``) are handled
                       transparently.

        Returns:
            :class:`ExtractionResult` containing normalised text and a
            byte-offset map.

        Raises:
            ExtractionError: If the MIME type is unsupported or the file
                is corrupt / malformed.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self._extract_sync,
            content,
            mime_type,
        )

    # ------------------------------------------------------------------
    # Synchronous dispatcher (runs inside the thread pool)
    # ------------------------------------------------------------------

    def _extract_sync(self, content: bytes, mime_type: str) -> ExtractionResult:
        """Route *content* to the correct format handler (thread-pool context).

        Args:
            content:   Raw bytes of the document.
            mime_type: MIME type string.

        Returns:
            :class:`ExtractionResult`.

        Raises:
            ExtractionError: For unsupported MIME types or malformed files.
        """
        # Strip charset and other parameters, normalise case.
        normalized_mime = mime_type.lower().split(";")[0].strip()

        if normalized_mime == "application/pdf":
            return self._extract_pdf(content)
        elif normalized_mime == (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        ):
            return self._extract_docx(content)
        elif normalized_mime == "text/csv":
            return self._extract_csv(content)
        elif normalized_mime == "application/json":
            return self._extract_json(content)
        elif normalized_mime == "text/plain":
            return self._extract_txt(content)
        elif normalized_mime in ("application/zip", "application/x-zip-compressed"):
            return self._extract_zip(content)
        else:
            raise ExtractionError(
                f"Unsupported MIME type: {mime_type!r}. "
                f"Supported types: {sorted(SUPPORTED_MIME_TYPES)}"
            )

    # ------------------------------------------------------------------
    # Format handlers
    # ------------------------------------------------------------------

    def _extract_pdf(self, content: bytes) -> ExtractionResult:
        """Extract text from PDF bytes using *pdfminer.six*."""
        try:
            from pdfminer.high_level import extract_text_to_fp
            from pdfminer.layout import LAParams

            output = io.StringIO()
            extract_text_to_fp(
                io.BytesIO(content),
                output,
                laparams=LAParams(),
            )
            raw_text = output.getvalue()
            text = _normalize(raw_text)
            offsets = []
            if text:
                offsets.append(
                    OffsetEntry(
                        text_start=0,
                        text_end=len(text),
                        byte_start=0,
                        byte_end=len(content),
                    )
                )
            return ExtractionResult(text=text, offsets=offsets)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to extract PDF: {exc}") from exc

    def _extract_docx(self, content: bytes) -> ExtractionResult:
        """Extract text from DOCX bytes using *python-docx*."""
        try:
            import docx  # type: ignore[import-untyped]

            doc = docx.Document(io.BytesIO(content))
            texts: list[str] = []
            offsets: list[OffsetEntry] = []
            text_pos = 0

            for para in doc.paragraphs:
                para_text = _normalize(para.text)
                if not para_text:
                    continue
                offsets.append(
                    OffsetEntry(
                        text_start=text_pos,
                        text_end=text_pos + len(para_text),
                        byte_start=0,
                        byte_end=len(content),
                    )
                )
                texts.append(para_text)
                text_pos += len(para_text) + 1  # +1 for the "\n" separator

            full_text = "\n".join(texts)
            return ExtractionResult(text=full_text, offsets=offsets)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to extract DOCX: {exc}") from exc

    def _extract_csv(self, content: bytes) -> ExtractionResult:
        """Extract text from CSV bytes using the stdlib *csv* module."""
        try:
            text_content = content.decode("utf-8", errors="replace")
            reader = csv.reader(io.StringIO(text_content))

            row_texts: list[str] = []
            offsets: list[OffsetEntry] = []
            text_pos = 0
            byte_pos = 0

            for raw_row in reader:
                # Represent each row as space-separated non-empty cell values.
                row_text = " ".join(cell.strip() for cell in raw_row if cell.strip())
                if not row_text:
                    continue
                # Approximate byte span using the original CSV row bytes.
                row_bytes_len = len((",".join(raw_row) + "\n").encode("utf-8"))
                offsets.append(
                    OffsetEntry(
                        text_start=text_pos,
                        text_end=text_pos + len(row_text),
                        byte_start=byte_pos,
                        byte_end=byte_pos + row_bytes_len,
                    )
                )
                row_texts.append(row_text)
                text_pos += len(row_text) + 1  # +1 for "\n"
                byte_pos += row_bytes_len

            full_text = "\n".join(row_texts)
            return ExtractionResult(text=full_text, offsets=offsets)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to extract CSV: {exc}") from exc

    def _extract_json(self, content: bytes) -> ExtractionResult:
        """Extract all string values from JSON bytes."""
        try:
            text_content = content.decode("utf-8", errors="replace")
            data = json.loads(text_content)

            strings: list[str] = []
            _collect_strings(data, strings)

            full_text = " ".join(strings)
            offsets = []
            if full_text:
                offsets.append(
                    OffsetEntry(
                        text_start=0,
                        text_end=len(full_text),
                        byte_start=0,
                        byte_end=len(content),
                    )
                )
            return ExtractionResult(text=full_text, offsets=offsets)
        except json.JSONDecodeError as exc:
            raise ExtractionError(f"Failed to parse JSON: {exc}") from exc
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to extract JSON: {exc}") from exc

    def _extract_txt(self, content: bytes) -> ExtractionResult:
        """Extract text from plain-text bytes (UTF-8 with Latin-1 fallback)."""
        try:
            try:
                raw = content.decode("utf-8")
            except UnicodeDecodeError:
                raw = content.decode("latin-1")

            text = _normalize(raw)
            offsets = []
            if text:
                offsets.append(
                    OffsetEntry(
                        text_start=0,
                        text_end=len(text),
                        byte_start=0,
                        byte_end=len(content),
                    )
                )
            return ExtractionResult(text=text, offsets=offsets)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to extract TXT: {exc}") from exc

    def _extract_zip(self, content: bytes) -> ExtractionResult:
        """Recursively extract text from all files inside a ZIP archive.

        Files with unrecognised extensions are treated as plain text.
        Entries that fail extraction are logged and skipped so that one
        corrupt member does not abort the whole archive.

        Args:
            content: Raw ZIP archive bytes.

        Raises:
            ExtractionError: If *content* is not a valid ZIP archive.
        """
        try:
            buf = io.BytesIO(content)
            if not zipfile.is_zipfile(buf):
                raise ExtractionError("Content is not a valid ZIP archive")

            chunks: list[str] = []
            offsets: list[OffsetEntry] = []
            text_pos = 0

            buf.seek(0)
            with zipfile.ZipFile(buf) as zf:
                for name in zf.namelist():
                    if name.endswith("/"):
                        # Directory entry — skip.
                        continue

                    member_bytes = zf.read(name)
                    mime = _guess_mime_from_name(name)

                    try:
                        member_result = self._extract_sync(member_bytes, mime)
                    except ExtractionError as exc:
                        logger.warning(
                            "ZIP member %r skipped — extraction failed: %s",
                            name,
                            exc,
                        )
                        continue

                    if not member_result.text.strip():
                        continue

                    offsets.append(
                        OffsetEntry(
                            text_start=text_pos,
                            text_end=text_pos + len(member_result.text),
                            byte_start=0,
                            byte_end=len(content),
                        )
                    )
                    chunks.append(member_result.text)
                    text_pos += len(member_result.text) + 1  # +1 for "\n"

            full_text = "\n".join(chunks)
            return ExtractionResult(text=full_text, offsets=offsets)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to extract ZIP: {exc}") from exc

    # ------------------------------------------------------------------
    # Resource management
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Shut down the thread-pool executor.

        Call this when the extractor is no longer needed to release worker
        threads promptly.
        """
        self._executor.shutdown(wait=True)

    def __enter__(self) -> "DocumentExtractor":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"[ \t]+")


def _normalize(text: str) -> str:
    """Normalise extracted text for consistent downstream processing.

    Steps applied (in order):

    1. Collapse runs of horizontal whitespace (spaces and tabs) to a single
       space on each line.
    2. Strip leading and trailing whitespace from each line.
    3. Remove lines that are empty after stripping.
    4. Join remaining lines with ``\\n``.

    Args:
        text: Raw text as returned by an extraction library.

    Returns:
        Normalised text string.
    """
    lines = (_WHITESPACE_RE.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _collect_strings(obj: Any, result: list[str]) -> None:
    """Recursively collect all string leaf values from a JSON structure.

    Args:
        obj:    Any JSON-deserialisable Python value.
        result: Accumulator list; string values are appended in-place.
    """
    if isinstance(obj, str):
        result.append(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            _collect_strings(value, result)
    elif isinstance(obj, list):
        for item in obj:
            _collect_strings(item, result)
    # Numbers, booleans, and None are intentionally skipped.


def _guess_mime_from_name(filename: str) -> str:
    """Infer a MIME type from the file extension of *filename*.

    Used when extracting members from a ZIP archive.  Unknown extensions
    default to ``text/plain`` so that extraction is always attempted.

    Args:
        filename: File name (may include path components).

    Returns:
        A MIME type string supported by :meth:`DocumentExtractor._extract_sync`.
    """
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith(".docx"):
        return (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        )
    if lower.endswith(".csv"):
        return "text/csv"
    if lower.endswith(".json"):
        return "application/json"
    if lower.endswith(".zip"):
        return "application/zip"
    # Default: attempt plain-text extraction for all other types.
    return "text/plain"
