"""Multi-format document text extractor for the FileGuard scan pipeline.

:class:`DocumentExtractor` converts raw file bytes into normalised plain text
and produces a ``byte_offsets`` list that maps each character position in the
normalised text back to the corresponding byte offset in the original file
bytes.  This mapping is consumed by :class:`~fileguard.core.pii_detector.PIIDetector`
to report finding locations as byte offsets rather than text-space indices.

**Supported formats**

+----------+----------------------------+------------------------------------+
| Format   | MIME types                 | Library                            |
+==========+============================+====================================+
| PDF      | application/pdf            | pdfminer.six                       |
+----------+----------------------------+------------------------------------+
| DOCX     | application/vnd.openxml…   | python-docx                        |
+----------+----------------------------+------------------------------------+
| CSV      | text/csv                   | stdlib csv                         |
+----------+----------------------------+------------------------------------+
| JSON     | application/json           | stdlib json                        |
+----------+----------------------------+------------------------------------+
| TXT      | text/plain                 | raw decode                         |
+----------+----------------------------+------------------------------------+
| ZIP      | application/zip            | stdlib zipfile (recursive)         |
+----------+----------------------------+------------------------------------+

**Thread-pool execution**

All format-specific extraction functions are CPU-bound (parsing structured
binary files).  :meth:`DocumentExtractor.extract` dispatches extraction to a
:class:`concurrent.futures.ThreadPoolExecutor` so that the event loop is never
blocked.  The pool size defaults to ``settings.THREAD_POOL_WORKERS`` and can
be overridden at construction time for testing.

**Byte-offset map**

The ``byte_offsets`` list returned inside :class:`ExtractionResult` has exactly
``len(text)`` entries.  ``byte_offsets[i]`` is the byte offset in the *original
file bytes* of the character at ``text[i]``.

For formats where a precise per-character mapping to original bytes is not
possible (PDF, DOCX, ZIP children), byte offsets are approximated linearly
within the known start/end range of the extracted segment.  This gives PII
detectors sufficient precision to report findings at the paragraph/block
granularity required by the compliance report schema.

Usage::

    from fileguard.core.document_extractor import DocumentExtractor

    extractor = DocumentExtractor()
    result = await extractor.extract(file_bytes, mime_type="application/pdf")
    print(result.text[:200])
    print(result.byte_offsets[:5])
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy dependencies — imported at module level so tests can patch
# them without monkey-patching inside function scope.
# ---------------------------------------------------------------------------

try:
    from pdfminer.high_level import extract_pages as _pdfminer_extract_pages  # type: ignore[import]
    _PDFMINER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _pdfminer_extract_pages = None  # type: ignore[assignment]
    _PDFMINER_AVAILABLE = False

try:
    import docx as _docx_module  # type: ignore[import]
    _DOCX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _docx_module = None  # type: ignore[assignment]
    _DOCX_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum uncompressed size of ZIP contents (200 MiB).
_MAX_ZIP_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
# Maximum number of files within a single ZIP archive.
_MAX_ZIP_FILE_COUNT = 1000
# Maximum ZIP recursion depth.  0 = top-level call; raises when depth >= limit.
_MAX_ZIP_DEPTH = 2

# MIME types that DocumentExtractor can handle.
_SUPPORTED_MIME_TYPES: frozenset[str] = frozenset({
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/csv",
    "application/csv",
    "application/json",
    "text/json",
    "text/plain",
    "text/x-plain",
    "application/zip",
    "application/x-zip-compressed",
    "application/x-zip",
})

# Whitespace-normalisation pattern: collapse all runs of whitespace to a
# single space and strip leading/trailing whitespace.
_WS_RE = re.compile(r"\s+")

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class ExtractionResult:
    """Result produced by :class:`DocumentExtractor`.

    Attributes:
        text: Normalised, whitespace-collapsed plain text extracted from the
            document.  Guaranteed to be a non-None ``str``; empty string for
            documents that contain no extractable text.
        byte_offsets: Parallel list to the characters in ``text``.
            ``byte_offsets[i]`` is the best-effort byte offset in the
            *original* file bytes where the character ``text[i]`` was found.
            For compound formats (ZIP, multi-page PDF) this represents the
            offset relative to the start of the enclosing segment.
    """

    text: str
    byte_offsets: list[int] = field(default_factory=list)


class ExtractionError(Exception):
    """Raised when a document cannot be extracted.

    This covers two categories:

    * **Unsupported format**: the MIME type is not in the supported set.
    * **Corrupt or malformed file**: the format handler raised an unexpected
      error during parsing, indicating the file is damaged or misidentified.

    Callers must not silently ignore this exception; the scan pipeline should
    surface it as an ``EXTRACTION_FAILED`` finding.

    Attributes:
        mime_type: The MIME type that was supplied to
            :meth:`~DocumentExtractor.extract`.
        original: The underlying exception, if any.
    """

    def __init__(
        self,
        message: str,
        *,
        mime_type: str | None = None,
        original: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.mime_type = mime_type
        self.original = original

    def __str__(self) -> str:
        base = super().__str__()
        parts = [base]
        if self.mime_type:
            parts.append(f"mime_type={self.mime_type!r}")
        if self.original is not None:
            parts.append(f"caused_by={type(self.original).__name__}: {self.original}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Private helpers — synchronous format handlers
# ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    """Collapse whitespace and strip surrounding spaces."""
    return _WS_RE.sub(" ", text).strip()


def _build_offsets(text: str, byte_start: int, byte_end: int) -> list[int]:
    """Build a linear byte-offset list for *text* within [byte_start, byte_end).

    For formats where per-character byte tracking is not available, we
    distribute the byte range evenly across the characters.

    Args:
        text: The normalised text segment.
        byte_start: Byte offset in the original file where this segment starts.
        byte_end: Exclusive byte offset where this segment ends.

    Returns:
        A list of length ``len(text)`` with monotonically increasing byte
        offsets drawn from ``[byte_start, byte_end)``.
    """
    n = len(text)
    if n == 0:
        return []
    byte_range = max(byte_end - byte_start, 1)
    return [byte_start + int(i * byte_range / n) for i in range(n)]


def _extract_txt(data: bytes) -> ExtractionResult:
    """Extract plain text from UTF-8/Latin-1 bytes.

    Attempts UTF-8 first, then falls back to Latin-1 which can always decode
    arbitrary byte sequences.

    Args:
        data: Raw file bytes.

    Returns:
        :class:`ExtractionResult` with approximate per-character byte offsets.
    """
    try:
        text_raw = data.decode("utf-8")
    except UnicodeDecodeError:
        text_raw = data.decode("latin-1")

    text = _normalise(text_raw)
    return ExtractionResult(
        text=text,
        byte_offsets=_build_offsets(text, 0, len(data)),
    )


def _extract_json(data: bytes) -> ExtractionResult:
    """Extract text from a JSON document.

    Recursively collects all string leaf values from the parsed JSON structure
    and joins them with spaces.

    Args:
        data: Raw JSON bytes.

    Returns:
        :class:`ExtractionResult` with linear byte offsets.

    Raises:
        ExtractionError: If *data* is not valid JSON.
    """
    try:
        obj = json.loads(data.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ExtractionError(
            "Failed to parse JSON document",
            mime_type="application/json",
            original=exc,
        ) from exc

    strings: list[str] = []

    def _collect(node: object) -> None:
        if isinstance(node, str):
            strings.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                _collect(v)
        elif isinstance(node, list):
            for item in node:
                _collect(item)

    _collect(obj)
    text = _normalise(" ".join(strings))
    return ExtractionResult(
        text=text,
        byte_offsets=_build_offsets(text, 0, len(data)),
    )


def _extract_csv(data: bytes) -> ExtractionResult:
    """Extract text from a CSV document.

    All cell values are concatenated with spaces.  Headers (first row) are
    included in the output as they may contain sensitive column names.

    Args:
        data: Raw CSV bytes.

    Returns:
        :class:`ExtractionResult` with linear byte offsets.

    Raises:
        ExtractionError: If the CSV cannot be parsed.
    """
    try:
        text_raw = data.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text_raw))
        cells: list[str] = []
        for row in reader:
            cells.extend(row)
    except csv.Error as exc:
        raise ExtractionError(
            "Failed to parse CSV document",
            mime_type="text/csv",
            original=exc,
        ) from exc

    text = _normalise(" ".join(cells))
    return ExtractionResult(
        text=text,
        byte_offsets=_build_offsets(text, 0, len(data)),
    )


def _extract_pdf(data: bytes) -> ExtractionResult:
    """Extract text from a PDF document using pdfminer.six.

    Text is extracted page-by-page and concatenated.  Byte offsets are
    approximated linearly across the full file.

    Args:
        data: Raw PDF bytes.

    Returns:
        :class:`ExtractionResult`.

    Raises:
        ExtractionError: If pdfminer is not installed or cannot parse the file.
    """
    if not _PDFMINER_AVAILABLE or _pdfminer_extract_pages is None:
        raise ExtractionError(
            "pdfminer.six is not installed; cannot extract PDF",
            mime_type="application/pdf",
        )

    try:
        page_texts: list[str] = []
        for page_layout in _pdfminer_extract_pages(io.BytesIO(data)):
            page_chars: list[str] = []
            for element in page_layout:
                # Use duck-typing so that mocks work without importing the
                # actual LTTextContainer class in tests.
                get_text = getattr(element, "get_text", None)
                if get_text is not None and callable(get_text):
                    page_chars.append(get_text())
            page_texts.append("".join(page_chars))
    except Exception as exc:
        raise ExtractionError(
            "Failed to extract text from PDF",
            mime_type="application/pdf",
            original=exc,
        ) from exc

    text = _normalise(" ".join(t for t in page_texts if t.strip()))
    return ExtractionResult(
        text=text,
        byte_offsets=_build_offsets(text, 0, len(data)),
    )


def _extract_docx(data: bytes) -> ExtractionResult:
    """Extract text from a DOCX document using python-docx.

    All paragraphs in the main body are concatenated.  Byte offsets are
    approximated linearly across the full file.

    Args:
        data: Raw DOCX bytes.

    Returns:
        :class:`ExtractionResult`.

    Raises:
        ExtractionError: If python-docx is not installed or cannot parse the file.
    """
    _mime = (
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document"
    )

    if not _DOCX_AVAILABLE or _docx_module is None:
        raise ExtractionError(
            "python-docx is not installed; cannot extract DOCX",
            mime_type=_mime,
        )

    try:
        doc = _docx_module.Document(io.BytesIO(data))
        paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
    except Exception as exc:
        raise ExtractionError(
            "Failed to extract text from DOCX",
            mime_type=_mime,
            original=exc,
        ) from exc

    text = _normalise(" ".join(paragraphs))
    return ExtractionResult(
        text=text,
        byte_offsets=_build_offsets(text, 0, len(data)),
    )


def _extract_zip(data: bytes, *, depth: int = 0) -> ExtractionResult:
    """Recursively extract text from a ZIP archive.

    Each contained file is extracted using the appropriate format handler.
    Results are concatenated in archive-member order.

    Safety limits:
    * Maximum uncompressed size: :data:`_MAX_ZIP_UNCOMPRESSED_BYTES` (200 MiB)
    * Maximum member count: :data:`_MAX_ZIP_FILE_COUNT`
    * Maximum recursion depth: :data:`_MAX_ZIP_DEPTH` (raises when
      ``depth >= _MAX_ZIP_DEPTH``)

    Args:
        data: Raw ZIP bytes.
        depth: Current recursion depth (0 = top-level call).

    Returns:
        :class:`ExtractionResult` with concatenated text from all members.

    Raises:
        ExtractionError: If the archive is corrupt, exceeds safety limits, or
            the recursion depth is exceeded.
    """
    if depth >= _MAX_ZIP_DEPTH:
        raise ExtractionError(
            f"ZIP recursion depth limit ({_MAX_ZIP_DEPTH}) exceeded",
            mime_type="application/zip",
        )

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ExtractionError(
            "Corrupt or invalid ZIP archive",
            mime_type="application/zip",
            original=exc,
        ) from exc

    members = zf.infolist()
    if len(members) > _MAX_ZIP_FILE_COUNT:
        raise ExtractionError(
            f"ZIP archive exceeds maximum member count ({_MAX_ZIP_FILE_COUNT})",
            mime_type="application/zip",
        )

    total_uncompressed = sum(m.file_size for m in members)
    if total_uncompressed > _MAX_ZIP_UNCOMPRESSED_BYTES:
        raise ExtractionError(
            f"ZIP uncompressed size ({total_uncompressed} bytes) exceeds "
            f"limit ({_MAX_ZIP_UNCOMPRESSED_BYTES} bytes)",
            mime_type="application/zip",
        )

    segments: list[str] = []
    byte_cursor = 0  # Tracks cumulative compressed position across members.

    for member in members:
        # Skip directory entries.
        if member.filename.endswith("/"):
            continue
        try:
            member_bytes = zf.read(member.filename)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Skipping unreadable ZIP member %r: %s",
                member.filename,
                exc,
            )
            continue

        member_mime = _guess_mime(member.filename)
        try:
            if member_mime in {
                "application/zip",
                "application/x-zip-compressed",
                "application/x-zip",
            }:
                member_result = _extract_zip(member_bytes, depth=depth + 1)
            else:
                member_result = _dispatch_sync(member_bytes, member_mime)
        except ExtractionError as exc:
            logger.warning(
                "Skipping ZIP member %r (extraction failed): %s",
                member.filename,
                exc,
            )
            continue

        if member_result.text:
            segments.append(member_result.text)
        byte_cursor += member.compress_size

    text = " ".join(segments)
    final_offsets = _build_offsets(text, 0, len(data))
    return ExtractionResult(text=text, byte_offsets=final_offsets)


# ---------------------------------------------------------------------------
# MIME-type helpers
# ---------------------------------------------------------------------------

_EXT_TO_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": (
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document"
    ),
    ".doc": "application/msword",
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
    ".zip": "application/zip",
}


def _guess_mime(filename: str) -> str:
    """Return a best-effort MIME type for *filename* based on its extension.

    Returns ``"application/octet-stream"`` when the extension is unknown.
    """
    lower = filename.lower()
    for ext, mime in _EXT_TO_MIME.items():
        if lower.endswith(ext):
            return mime
    return "application/octet-stream"


def _dispatch_sync(data: bytes, mime_type: str) -> ExtractionResult:
    """Synchronously dispatch to the appropriate format handler.

    Args:
        data: Raw file bytes.
        mime_type: Canonical MIME type string.

    Returns:
        :class:`ExtractionResult`.

    Raises:
        ExtractionError: For unsupported MIME types or parse failures.
    """
    # Strip parameters (e.g. "text/plain; charset=utf-8").
    base_mime = mime_type.split(";")[0].strip().lower()

    if base_mime == "application/pdf":
        return _extract_pdf(data)

    if base_mime in {
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document",
        "application/msword",
    }:
        return _extract_docx(data)

    if base_mime in {"text/csv", "application/csv"}:
        return _extract_csv(data)

    if base_mime in {"application/json", "text/json"}:
        return _extract_json(data)

    if base_mime in {"text/plain", "text/x-plain"}:
        return _extract_txt(data)

    if base_mime in {
        "application/zip",
        "application/x-zip-compressed",
        "application/x-zip",
    }:
        return _extract_zip(data)

    raise ExtractionError(
        f"Unsupported MIME type: {mime_type!r}",
        mime_type=mime_type,
    )


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class DocumentExtractor:
    """Multi-format document text extractor with thread-pool execution.

    Extraction methods are synchronous and CPU-bound.  :meth:`extract`
    dispatches them to a :class:`~concurrent.futures.ThreadPoolExecutor`
    to prevent blocking the asyncio event loop.

    Args:
        max_workers: Number of threads in the pool.  Defaults to
            ``settings.THREAD_POOL_WORKERS`` (typically 4).
        executor: Pre-built executor to use (useful for testing/injection).
            When supplied, *max_workers* is ignored.

    Example::

        extractor = DocumentExtractor()
        result = await extractor.extract(pdf_bytes, "application/pdf")
        print(result.text)
    """

    def __init__(
        self,
        max_workers: int | None = None,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        if executor is not None:
            self._executor = executor
            self._owns_executor = False
        else:
            workers: int
            if max_workers is not None:
                workers = max_workers
            else:
                from fileguard.config import settings

                workers = settings.THREAD_POOL_WORKERS
            self._executor = ThreadPoolExecutor(max_workers=workers)
            self._owns_executor = True

    # ------------------------------------------------------------------
    # Context-manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "DocumentExtractor":
        return self

    def __exit__(self, *_: object) -> None:
        self.shutdown()

    def shutdown(self, *, wait: bool = True) -> None:
        """Shut down the thread pool.

        Safe to call multiple times.  Does nothing if the executor was
        supplied externally.
        """
        if self._owns_executor:
            self._executor.shutdown(wait=wait)

    # ------------------------------------------------------------------
    # Core extraction method
    # ------------------------------------------------------------------

    async def extract(self, file_bytes: bytes, mime_type: str) -> ExtractionResult:
        """Extract normalised text from *file_bytes* in the thread pool.

        The extraction runs in a background thread so the asyncio event loop
        is not blocked by CPU-intensive parsing work.

        Args:
            file_bytes: Raw bytes of the document to extract.
            mime_type: MIME type of the document (e.g. ``"application/pdf"``).
                MIME type parameters (``; charset=utf-8``) are stripped
                automatically.

        Returns:
            :class:`ExtractionResult` containing normalised text and a
            byte-offset list of length ``len(result.text)``.

        Raises:
            ExtractionError: If the MIME type is unsupported or the file is
                corrupt and cannot be parsed.
        """
        import asyncio

        loop = asyncio.get_running_loop()
        logger.debug(
            "Dispatching extraction to thread pool: mime_type=%r, size=%d bytes",
            mime_type,
            len(file_bytes),
        )
        result: ExtractionResult = await loop.run_in_executor(
            self._executor,
            _dispatch_sync,
            file_bytes,
            mime_type,
        )
        logger.debug(
            "Extraction complete: %d chars extracted", len(result.text)
        )
        return result
