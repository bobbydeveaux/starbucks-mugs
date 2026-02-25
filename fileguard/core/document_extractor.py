"""Document text extractor with multi-format support and byte-offset mapping.

Supported formats:
- PDF (via pdfminer.six)
- DOCX (via python-docx)
- CSV
- JSON
- TXT (plain text)
- ZIP (recursive extraction)

Usage::

    extractor = DocumentExtractor()
    result = extractor.extract(pdf_bytes, "report.pdf")
    print(result.text)
    for offset in result.offsets:
        print(f"Chars [{offset.char_start}:{offset.char_end}] -> "
              f"Bytes [{offset.byte_start}:{offset.byte_end}]")

CPU-bound extraction runs in a ``concurrent.futures.ThreadPoolExecutor`` so it
does not block the asyncio event loop.

Exceptions:
    UnsupportedMIMETypeError: Raised for file types not in the supported list.
    CorruptFileError: Raised when a file cannot be parsed due to corruption or
        malformation.
"""
from __future__ import annotations

import csv
import io
import json
import mimetypes
import zipfile
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------


class ByteOffset(NamedTuple):
    """Maps a character span in the extracted text to bytes in the original data.

    Attributes:
        char_start: Inclusive start index in the normalised text string.
        char_end:   Exclusive end index in the normalised text string.
        byte_start: Inclusive start byte offset in the original file data.
        byte_end:   Exclusive end byte offset in the original file data.
    """

    char_start: int
    char_end: int
    byte_start: int
    byte_end: int


class ExtractionResult(NamedTuple):
    """Result of a document extraction operation.

    Attributes:
        text:    Normalised Unicode text extracted from the document.
        offsets: List of :class:`ByteOffset` entries mapping text spans back to
                 byte positions in the original file for PII span localisation.
    """

    text: str
    offsets: list[ByteOffset]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DocumentExtractorError(Exception):
    """Base exception for all DocumentExtractor failures."""


class UnsupportedMIMETypeError(DocumentExtractorError):
    """Raised when the input file's MIME type is not supported.

    Attributes:
        mime_type: The detected MIME type string.
        filename:  The filename that was inspected.
    """

    def __init__(self, message: str, *, mime_type: str = "", filename: str = "") -> None:
        super().__init__(message)
        self.mime_type = mime_type
        self.filename = filename


class CorruptFileError(DocumentExtractorError):
    """Raised when a file cannot be parsed due to corruption or malformation.

    Attributes:
        cause: The underlying exception, if any.
    """

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause


# ---------------------------------------------------------------------------
# DocumentExtractor
# ---------------------------------------------------------------------------

_DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_ZIP_MIMES = frozenset(
    ["application/zip", "application/x-zip-compressed", "application/x-zip"]
)
_SUPPORTED_MIMES = frozenset(
    [
        "application/pdf",
        _DOCX_MIME,
        "text/csv",
        "application/json",
        "text/plain",
        *_ZIP_MIMES,
    ]
)


class DocumentExtractor:
    """Extracts normalised text from documents with byte-offset mapping.

    Supported MIME types:
    - ``application/pdf``
    - ``application/vnd.openxmlformats-officedocument.wordprocessingml.document``
    - ``text/csv``
    - ``application/json``
    - ``text/plain``
    - ``application/zip`` (and variants)

    ZIP archives are recursively unpacked up to *max_zip_depth* levels deep
    with at most *max_zip_files* entries per archive to guard against zip bombs.

    CPU-bound extraction is dispatched to a ``ThreadPoolExecutor`` so it does
    not block the asyncio event loop.

    Args:
        thread_pool_workers: Number of threads in the pool (default 4).
        max_zip_depth:       Maximum ZIP nesting depth (default 2).
        max_zip_files:       Maximum files to extract from a single archive
                             (default 1 000).

    Raises:
        UnsupportedMIMETypeError: For unsupported file types.
        CorruptFileError:         For malformed or unreadable files.
    """

    SUPPORTED_MIME_TYPES: frozenset[str] = _SUPPORTED_MIMES

    def __init__(
        self,
        *,
        thread_pool_workers: int = 4,
        max_zip_depth: int = 2,
        max_zip_files: int = 1_000,
    ) -> None:
        self._executor = ThreadPoolExecutor(max_workers=thread_pool_workers)
        self._max_zip_depth = max_zip_depth
        self._max_zip_files = max_zip_files

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, data: bytes, filename: str) -> ExtractionResult:
        """Extract normalised text and byte-offset map from *data*.

        Args:
            data:     Raw file bytes.
            filename: Original filename used for MIME type detection when magic
                      bytes are ambiguous.

        Returns:
            :class:`ExtractionResult` containing the normalised text and a list
            of :class:`ByteOffset` entries.

        Raises:
            UnsupportedMIMETypeError: If the MIME type cannot be handled.
            CorruptFileError:         If the file is malformed or unreadable.
        """
        mime_type = self._detect_mime_type(data, filename)
        if mime_type not in self.SUPPORTED_MIME_TYPES:
            raise UnsupportedMIMETypeError(
                f"Unsupported MIME type {mime_type!r} for file {filename!r}",
                mime_type=mime_type,
                filename=filename,
            )
        future = self._executor.submit(self._dispatch, data, mime_type)
        return future.result()

    def shutdown(self, *, wait: bool = True) -> None:
        """Shut down the thread-pool executor.

        Args:
            wait: Block until all pending futures have finished (default True).
        """
        self._executor.shutdown(wait=wait)

    def __enter__(self) -> "DocumentExtractor":
        return self

    def __exit__(self, *_: object) -> None:
        self.shutdown()

    # ------------------------------------------------------------------
    # MIME detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_mime_type(data: bytes, filename: str) -> str:
        """Identify MIME type using magic bytes then file extension."""
        # --- Binary magic bytes ----------------------------------------
        if data[:4] == b"%PDF":
            return "application/pdf"

        # ZIP-based formats (DOCX is a ZIP archive internally)
        if data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
            if filename.lower().endswith(".docx"):
                return _DOCX_MIME
            return "application/zip"

        # --- Extension fallback ----------------------------------------
        lower = filename.lower()
        if lower.endswith(".csv"):
            return "text/csv"
        if lower.endswith(".json"):
            return "application/json"
        if lower.endswith(".txt"):
            return "text/plain"
        if lower.endswith((".zip", ".ZIP")):
            return "application/zip"
        if lower.endswith(".docx"):
            return _DOCX_MIME

        # --- mimetypes library fallback --------------------------------
        guessed, _ = mimetypes.guess_type(filename)
        if guessed:
            return guessed

        # --- Content sniffing for text formats -------------------------
        try:
            decoded = data.decode("utf-8")
            decoded.lstrip()
            json.loads(decoded)
            return "application/json"
        except (UnicodeDecodeError, ValueError):
            pass

        try:
            data.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            pass

        return "application/octet-stream"

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    def _dispatch(self, data: bytes, mime_type: str) -> ExtractionResult:
        """Route to the appropriate format handler."""
        if mime_type == "application/pdf":
            return self._extract_pdf(data)
        if mime_type == _DOCX_MIME:
            return self._extract_docx(data)
        if mime_type == "text/csv":
            return self._extract_csv(data)
        if mime_type == "application/json":
            return self._extract_json(data)
        if mime_type == "text/plain":
            return self._extract_txt(data)
        if mime_type in _ZIP_MIMES:
            return self._extract_zip(data, depth=0)
        raise UnsupportedMIMETypeError(
            f"No handler for MIME type {mime_type!r}",
            mime_type=mime_type,
        )

    # ------------------------------------------------------------------
    # Format handlers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_txt(data: bytes) -> ExtractionResult:
        """Extract text from a UTF-8 plain-text file.

        Byte offsets are tracked per line to provide character-accurate spans
        even for multi-byte Unicode content.
        """
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception as exc:
            raise CorruptFileError(
                f"Failed to decode plain-text file: {exc}", cause=exc
            ) from exc

        offsets: list[ByteOffset] = []
        if not text:
            return ExtractionResult(text="", offsets=offsets)

        char_pos = 0
        byte_pos = 0
        for line in text.splitlines(keepends=True):
            char_end = char_pos + len(line)
            byte_end = byte_pos + len(line.encode("utf-8"))
            offsets.append(
                ByteOffset(
                    char_start=char_pos,
                    char_end=char_end,
                    byte_start=byte_pos,
                    byte_end=byte_end,
                )
            )
            char_pos = char_end
            byte_pos = byte_end

        return ExtractionResult(text=text, offsets=offsets)

    @staticmethod
    def _extract_json(data: bytes) -> ExtractionResult:
        """Extract text from a JSON file.

        The entire decoded JSON text is returned as-is.  A single
        :class:`ByteOffset` covers the full document.  If the bytes do not
        parse as valid JSON a :class:`CorruptFileError` is raised.
        """
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception as exc:
            raise CorruptFileError(
                f"Failed to decode JSON file: {exc}", cause=exc
            ) from exc

        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise CorruptFileError(
                f"Malformed JSON: {exc}", cause=exc
            ) from exc

        offsets = [
            ByteOffset(
                char_start=0,
                char_end=len(text),
                byte_start=0,
                byte_end=len(data),
            )
        ]
        return ExtractionResult(text=text, offsets=offsets)

    @staticmethod
    def _extract_csv(data: bytes) -> ExtractionResult:
        """Extract text from a CSV file.

        Each field value is appended to the normalised text separated by a
        space.  Byte offsets are tracked per row so that the row-level byte
        range is preserved for PII localisation.
        """
        try:
            decoded = data.decode("utf-8", errors="replace")
        except Exception as exc:
            raise CorruptFileError(
                f"Failed to decode CSV file: {exc}", cause=exc
            ) from exc

        parts: list[str] = []
        offsets: list[ByteOffset] = []
        char_pos = 0
        byte_pos = 0

        for raw_line in decoded.splitlines(keepends=True):
            line_byte_len = len(raw_line.encode("utf-8"))
            line_byte_end = byte_pos + line_byte_len

            stripped = raw_line.rstrip("\r\n")
            try:
                rows = list(csv.reader([stripped]))
            except csv.Error as exc:
                raise CorruptFileError(
                    f"Malformed CSV: {exc}", cause=exc
                ) from exc

            for row in rows:
                for field in row:
                    segment = field + " "
                    char_end = char_pos + len(segment)
                    offsets.append(
                        ByteOffset(
                            char_start=char_pos,
                            char_end=char_end,
                            byte_start=byte_pos,
                            byte_end=line_byte_end,
                        )
                    )
                    parts.append(segment)
                    char_pos = char_end

            byte_pos = line_byte_end

        text = "".join(parts)
        return ExtractionResult(text=text, offsets=offsets)

    @staticmethod
    def _extract_pdf(data: bytes) -> ExtractionResult:
        """Extract text from a PDF file using pdfminer.six.

        Page text is concatenated with form-feed separators.  A single
        document-level :class:`ByteOffset` is produced because PDF internal
        stream offsets are not meaningful after text extraction.

        Raises:
            CorruptFileError: If pdfminer fails to parse the PDF.
        """
        try:
            # Import here to keep the module importable even if pdfminer
            # is not installed in environments that don't need PDF support.
            from pdfminer.high_level import extract_text  # noqa: PLC0415
            from pdfminer.layout import LAParams  # noqa: PLC0415
        except ImportError as exc:
            raise CorruptFileError(
                "pdfminer.six is required for PDF extraction", cause=exc
            ) from exc

        try:
            text = extract_text(
                io.BytesIO(data),
                laparams=LAParams(),
            )
        except Exception as exc:
            raise CorruptFileError(
                f"Failed to extract PDF text: {exc}", cause=exc
            ) from exc

        text = text or ""
        offsets: list[ByteOffset] = []
        if text:
            offsets.append(
                ByteOffset(
                    char_start=0,
                    char_end=len(text),
                    byte_start=0,
                    byte_end=len(data),
                )
            )
        return ExtractionResult(text=text, offsets=offsets)

    @staticmethod
    def _extract_docx(data: bytes) -> ExtractionResult:
        """Extract text from a DOCX file using python-docx.

        Each paragraph is appended with a newline.  Per-paragraph
        :class:`ByteOffset` entries are produced with character-accurate
        spans; the byte range covers the full DOCX binary because paragraph
        byte positions within the embedded XML are not easily surfaced via the
        python-docx API.

        Raises:
            CorruptFileError: If python-docx fails to parse the DOCX.
        """
        try:
            from docx import Document  # noqa: PLC0415
        except ImportError as exc:
            raise CorruptFileError(
                "python-docx is required for DOCX extraction", cause=exc
            ) from exc

        try:
            doc = Document(io.BytesIO(data))
        except Exception as exc:
            raise CorruptFileError(
                f"Failed to parse DOCX file: {exc}", cause=exc
            ) from exc

        parts: list[str] = []
        offsets: list[ByteOffset] = []
        char_pos = 0

        for para in doc.paragraphs:
            segment = para.text + "\n"
            char_end = char_pos + len(segment)
            offsets.append(
                ByteOffset(
                    char_start=char_pos,
                    char_end=char_end,
                    byte_start=0,
                    byte_end=len(data),
                )
            )
            parts.append(segment)
            char_pos = char_end

        text = "".join(parts)
        return ExtractionResult(text=text, offsets=offsets)

    def _extract_zip(self, data: bytes, *, depth: int = 0) -> ExtractionResult:
        """Recursively extract text from a ZIP archive.

        Each contained file is extracted using the appropriate format handler.
        Zip bombs are mitigated via *max_zip_depth* and *max_zip_files*.

        Entries whose MIME type is unsupported or that are corrupt are silently
        skipped so that the archive as a whole still yields results from valid
        entries.

        Args:
            data:  Raw ZIP bytes.
            depth: Current recursion depth (0 for the outermost archive).

        Returns:
            :class:`ExtractionResult` whose text is the concatenation of all
            extracted entry texts and whose offsets map each entry's text span
            to the entry's compressed byte range within the ZIP stream.

        Raises:
            CorruptFileError: If the top-level ZIP structure is invalid.
        """
        if depth >= self._max_zip_depth:
            return ExtractionResult(text="", offsets=[])

        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise CorruptFileError(
                f"Malformed ZIP archive: {exc}", cause=exc
            ) from exc
        except Exception as exc:
            raise CorruptFileError(
                f"Failed to open ZIP archive: {exc}", cause=exc
            ) from exc

        all_parts: list[str] = []
        all_offsets: list[ByteOffset] = []
        char_pos = 0
        file_count = 0

        with zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if file_count >= self._max_zip_files:
                    break
                file_count += 1

                try:
                    entry_data = zf.read(info.filename)
                except Exception:
                    continue

                try:
                    result = self._extract_zip_entry(
                        entry_data, info.filename, depth=depth + 1
                    )
                except (UnsupportedMIMETypeError, CorruptFileError):
                    continue

                if not result.text:
                    continue

                char_end = char_pos + len(result.text)
                # Map the entry's text span to its byte range within the ZIP.
                all_offsets.append(
                    ByteOffset(
                        char_start=char_pos,
                        char_end=char_end,
                        byte_start=info.header_offset,
                        byte_end=info.header_offset + info.compress_size,
                    )
                )
                all_parts.append(result.text)
                char_pos = char_end

        return ExtractionResult(text="".join(all_parts), offsets=all_offsets)

    def _extract_zip_entry(
        self, data: bytes, filename: str, *, depth: int
    ) -> ExtractionResult:
        """Dispatch extraction for a single entry within a ZIP archive."""
        mime_type = self._detect_mime_type(data, filename)

        if mime_type in _ZIP_MIMES:
            return self._extract_zip(data, depth=depth)

        if mime_type not in self.SUPPORTED_MIME_TYPES:
            raise UnsupportedMIMETypeError(
                f"Unsupported MIME type {mime_type!r} in ZIP entry {filename!r}",
                mime_type=mime_type,
                filename=filename,
            )

        return self._dispatch(data, mime_type)
