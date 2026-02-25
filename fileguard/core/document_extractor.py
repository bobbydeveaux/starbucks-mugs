"""Document text extractor with byte-offset mapping.

Supports PDF, DOCX, CSV, JSON, TXT, and ZIP archives.  ZIP archives are
recursively unpacked and each contained file is extracted using the
appropriate format handler.

CPU-bound extraction calls are dispatched through a ``ThreadPoolExecutor``
so the caller's asyncio event loop is never blocked.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import ClassVar


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class ExtractionError(Exception):
    """Raised when document extraction fails.

    Possible causes:

    * Unsupported MIME type — the caller passed a type not in
      :data:`SUPPORTED_MIME_TYPES`.
    * Corrupt or unreadable file bytes — the underlying parser raised an
      exception while reading *data*.
    """


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ByteOffsetEntry:
    """Maps a contiguous span in the normalised text to UTF-8 byte offsets.

    *char_start* and *char_end* are indices into :attr:`ExtractionResult.text`
    (i.e. ``text[char_start:char_end]``).

    *byte_start* and *byte_end* are indices into
    ``text.encode("utf-8")`` — they allow byte-accurate PII span
    localisation without re-encoding on every lookup.
    """

    char_start: int  # Inclusive character index in ``ExtractionResult.text``
    char_end: int    # Exclusive character index in ``ExtractionResult.text``
    byte_start: int  # Inclusive byte offset in ``text.encode("utf-8")``
    byte_end: int    # Exclusive byte offset in ``text.encode("utf-8")``


@dataclass
class ExtractionResult:
    """Result of a document extraction operation."""

    text: str
    byte_offsets: list[ByteOffsetEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# MIME-type constants
# ---------------------------------------------------------------------------

SUPPORTED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/csv",
        "application/json",
        "text/plain",
        "application/zip",
        "application/x-zip-compressed",
    }
)


# ---------------------------------------------------------------------------
# Main extractor class
# ---------------------------------------------------------------------------


class DocumentExtractor:
    """Extracts normalised text and byte-offset maps from documents.

    Supported formats:

    * **PDF**  — via *pdfminer.six*
    * **DOCX** — via *python-docx*
    * **CSV**  — stdlib ``csv`` module
    * **JSON** — stdlib ``json`` module
    * **TXT**  — UTF-8 / latin-1 fallback
    * **ZIP**  — recursive extraction of contained files

    CPU-bound extraction is dispatched to a ``ThreadPoolExecutor`` so the
    caller's asyncio event loop is never blocked.

    Parameters
    ----------
    max_workers:
        Maximum number of threads in the pool (default: 4).
    """

    _MIME_TO_HANDLER: ClassVar[dict[str, str]] = {
        "application/pdf": "_extract_pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "_extract_docx",
        "text/csv": "_extract_csv",
        "application/json": "_extract_json",
        "text/plain": "_extract_txt",
        "application/zip": "_extract_zip",
        "application/x-zip-compressed": "_extract_zip",
    }

    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    async def extract(self, data: bytes, mime_type: str) -> ExtractionResult:
        """Extract text and build a byte-offset map from *data*.

        Parameters
        ----------
        data:
            Raw file bytes.
        mime_type:
            MIME type of the file (e.g. ``"application/pdf"``).

        Returns
        -------
        ExtractionResult
            Normalised text and a per-line byte-offset map.

        Raises
        ------
        ExtractionError
            If *mime_type* is not in :data:`SUPPORTED_MIME_TYPES` or the
            file bytes are corrupt / unreadable.
        """
        handler_name = self._MIME_TO_HANDLER.get(mime_type)
        if handler_name is None:
            raise ExtractionError(
                f"Unsupported MIME type: {mime_type!r}. "
                f"Supported types: {sorted(self._MIME_TO_HANDLER)}"
            )

        handler = getattr(self, handler_name)
        loop = asyncio.get_running_loop()

        try:
            raw_text: str = await loop.run_in_executor(self._executor, handler, data)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to extract {mime_type!r}: {exc}") from exc

        normalised = _normalise(raw_text)
        offsets = _build_byte_offsets(normalised)
        return ExtractionResult(text=normalised, byte_offsets=offsets)

    # ------------------------------------------------------------------
    # Format handlers (synchronous — called inside the thread pool)
    # ------------------------------------------------------------------

    def _extract_pdf(self, data: bytes) -> str:
        try:
            from pdfminer.high_level import extract_text  # type: ignore[import-untyped]

            return extract_text(io.BytesIO(data)) or ""
        except Exception as exc:
            raise ExtractionError(f"PDF extraction failed: {exc}") from exc

    def _extract_docx(self, data: bytes) -> str:
        try:
            import docx  # type: ignore[import-untyped]

            doc = docx.Document(io.BytesIO(data))
            return "\n".join(para.text for para in doc.paragraphs)
        except Exception as exc:
            raise ExtractionError(f"DOCX extraction failed: {exc}") from exc

    def _extract_csv(self, data: bytes) -> str:
        try:
            text = data.decode("utf-8-sig")
            reader = csv.reader(io.StringIO(text))
            rows = [" ".join(cell for cell in row) for row in reader]
            return "\n".join(rows)
        except Exception as exc:
            raise ExtractionError(f"CSV extraction failed: {exc}") from exc

    def _extract_json(self, data: bytes) -> str:
        try:
            obj = json.loads(data)
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except json.JSONDecodeError as exc:
            raise ExtractionError(f"JSON extraction failed: {exc}") from exc

    def _extract_txt(self, data: bytes) -> str:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            # latin-1 decoding never fails; use it as a safe fallback
            return data.decode("latin-1")

    def _extract_zip(self, data: bytes) -> str:
        try:
            texts: list[str] = []
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for name in zf.namelist():
                    if name.endswith("/"):
                        continue  # skip directory entries
                    file_bytes = zf.read(name)
                    mime = _guess_mime(name)
                    handler_name = self._MIME_TO_HANDLER.get(mime)
                    if handler_name is None:
                        continue  # silently skip unsupported contained files
                    handler = getattr(self, handler_name)
                    texts.append(handler(file_bytes))
            return "\n".join(texts)
        except zipfile.BadZipFile as exc:
            raise ExtractionError(f"ZIP extraction failed: {exc}") from exc

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the underlying :class:`~concurrent.futures.ThreadPoolExecutor`."""
        self._executor.shutdown(wait=wait)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    """Collapse CR/CRLF line endings and strip trailing whitespace per line."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip()


def _build_byte_offsets(text: str) -> list[ByteOffsetEntry]:
    """Build a per-line byte-offset map for *text*.

    Each :class:`ByteOffsetEntry` records the character span and the
    corresponding UTF-8 byte span of one line in the normalised text.
    Callers can use this map to convert character-level PII findings
    to byte-accurate positions without re-encoding the full text.
    """
    entries: list[ByteOffsetEntry] = []
    char_pos = 0
    byte_pos = 0

    for line in text.split("\n"):
        char_start = char_pos
        byte_start = byte_pos

        char_end = char_start + len(line)
        line_bytes = line.encode("utf-8")
        byte_end = byte_start + len(line_bytes)

        entries.append(
            ByteOffsetEntry(
                char_start=char_start,
                char_end=char_end,
                byte_start=byte_start,
                byte_end=byte_end,
            )
        )

        # Account for the "\n" separator between lines (1 byte in UTF-8)
        char_pos = char_end + 1
        byte_pos = byte_end + 1

    return entries


# ---------------------------------------------------------------------------
# MIME-type guessing (used for ZIP member files)
# ---------------------------------------------------------------------------

_EXTENSION_TO_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
    ".zip": "application/zip",
}


def _guess_mime(filename: str) -> str:
    """Return a MIME type based on *filename*'s extension, or ``'application/octet-stream'``."""
    ext = os.path.splitext(filename)[1].lower()
    return _EXTENSION_TO_MIME.get(ext, "application/octet-stream")
