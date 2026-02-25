"""Unit tests for fileguard/core/document_extractor.py.

Covers:
- All six extraction format handlers (PDF, DOCX, CSV, JSON, TXT, ZIP)
- Byte-offset map correctness: entries reference correct character positions
  within the normalised text string.
- ZIP archive recursive unpacking and multi-file handling.
- ThreadPoolExecutor dispatch: extract() calls run_in_executor.
- Error-path: ExtractionError raised for unsupported MIME types.
- Error-path: ExtractionError raised for malformed/corrupt file bytes.

All tests are fully offline — no network access or real filesystem I/O.
File fixtures are created as in-memory bytes using stdlib/test libraries.
"""
from __future__ import annotations

import io
import json
import zipfile
from concurrent.futures import Future
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fileguard.core.document_extractor import (
    ByteOffsetEntry,
    DocumentExtractor,
    ExtractionError,
    ExtractionResult,
    _build_byte_offsets,
    _guess_mime,
    _normalise,
    SUPPORTED_MIME_TYPES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def extractor() -> DocumentExtractor:
    """A DocumentExtractor instance with a single worker (deterministic)."""
    ex = DocumentExtractor(max_workers=1)
    yield ex
    ex.shutdown(wait=True)


def _make_zip(files: dict[str, bytes]) -> bytes:
    """Build an in-memory ZIP archive containing *files*."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _make_docx(paragraphs: list[str]) -> bytes:
    """Build a minimal in-memory DOCX document."""
    import docx  # type: ignore[import-untyped]

    doc = docx.Document()
    for para in paragraphs:
        doc.add_paragraph(para)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Helper / utility unit tests
# ---------------------------------------------------------------------------


class TestNormalise:
    def test_crlf_converted_to_lf(self) -> None:
        assert _normalise("line1\r\nline2") == "line1\nline2"

    def test_cr_only_converted_to_lf(self) -> None:
        assert _normalise("line1\rline2") == "line1\nline2"

    def test_trailing_whitespace_stripped_per_line(self) -> None:
        assert _normalise("hello   \nworld  ") == "hello\nworld"

    def test_leading_and_trailing_blank_lines_stripped(self) -> None:
        assert _normalise("\n\nhello\n\n") == "hello"

    def test_empty_string_returns_empty(self) -> None:
        assert _normalise("") == ""


class TestBuildByteOffsets:
    def test_single_line_offsets(self) -> None:
        text = "Hello"
        entries = _build_byte_offsets(text)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.char_start == 0
        assert entry.char_end == 5
        assert entry.byte_start == 0
        assert entry.byte_end == 5

    def test_two_line_offsets(self) -> None:
        text = "Hello\nWorld"
        entries = _build_byte_offsets(text)
        assert len(entries) == 2

        # First line: "Hello"
        assert entries[0].char_start == 0
        assert entries[0].char_end == 5

        # Second line: "World" starts after "Hello\n" (6 chars / 6 bytes)
        assert entries[1].char_start == 6
        assert entries[1].char_end == 11

    def test_offsets_reference_correct_chars(self) -> None:
        text = "foo\nbar\nbaz"
        entries = _build_byte_offsets(text)
        for entry in entries:
            extracted_chars = text[entry.char_start:entry.char_end]
            extracted_bytes = text.encode("utf-8")[entry.byte_start:entry.byte_end]
            assert extracted_chars == extracted_bytes.decode("utf-8")

    def test_multibyte_unicode_byte_offsets(self) -> None:
        # "café" — 'é' is 2 bytes in UTF-8
        text = "café\nbar"
        entries = _build_byte_offsets(text)

        # First line: "café" → 4 chars, 5 bytes
        assert entries[0].char_end - entries[0].char_start == 4
        assert entries[0].byte_end - entries[0].byte_start == 5

        # Second line: "bar" → 3 chars, 3 bytes
        assert entries[1].char_end - entries[1].char_start == 3
        assert entries[1].byte_end - entries[1].byte_start == 3

    def test_byte_offsets_reference_correct_bytes(self) -> None:
        text = "café\nhello"
        encoded = text.encode("utf-8")
        entries = _build_byte_offsets(text)
        for entry in entries:
            byte_slice = encoded[entry.byte_start:entry.byte_end]
            char_slice = text[entry.char_start:entry.char_end]
            assert byte_slice.decode("utf-8") == char_slice


class TestGuessMime:
    def test_pdf_extension(self) -> None:
        assert _guess_mime("report.pdf") == "application/pdf"

    def test_docx_extension(self) -> None:
        assert _guess_mime("doc.docx") == (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    def test_csv_extension(self) -> None:
        assert _guess_mime("data.csv") == "text/csv"

    def test_json_extension(self) -> None:
        assert _guess_mime("config.json") == "application/json"

    def test_txt_extension(self) -> None:
        assert _guess_mime("readme.txt") == "text/plain"

    def test_zip_extension(self) -> None:
        assert _guess_mime("archive.zip") == "application/zip"

    def test_unknown_extension_returns_octet_stream(self) -> None:
        assert _guess_mime("binary.exe") == "application/octet-stream"

    def test_case_insensitive_extension(self) -> None:
        assert _guess_mime("REPORT.PDF") == "application/pdf"


# ---------------------------------------------------------------------------
# Format handler tests (all async, dispatched via the extractor)
# ---------------------------------------------------------------------------


class TestExtractTxt:
    async def test_simple_text(self, extractor: DocumentExtractor) -> None:
        data = b"Hello world\nSecond line"
        result = await extractor.extract(data, "text/plain")
        assert "Hello world" in result.text
        assert "Second line" in result.text

    async def test_returns_extraction_result(self, extractor: DocumentExtractor) -> None:
        data = b"test content"
        result = await extractor.extract(data, "text/plain")
        assert isinstance(result, ExtractionResult)

    async def test_byte_offsets_populated(self, extractor: DocumentExtractor) -> None:
        data = b"line one\nline two"
        result = await extractor.extract(data, "text/plain")
        assert len(result.byte_offsets) >= 1
        assert all(isinstance(e, ByteOffsetEntry) for e in result.byte_offsets)

    async def test_byte_offsets_correctness(self, extractor: DocumentExtractor) -> None:
        data = b"Hello\nWorld"
        result = await extractor.extract(data, "text/plain")
        encoded = result.text.encode("utf-8")
        for entry in result.byte_offsets:
            char_span = result.text[entry.char_start:entry.char_end]
            byte_span = encoded[entry.byte_start:entry.byte_end].decode("utf-8")
            assert char_span == byte_span

    async def test_normalises_crlf(self, extractor: DocumentExtractor) -> None:
        data = b"line1\r\nline2"
        result = await extractor.extract(data, "text/plain")
        assert "\r" not in result.text

    async def test_latin1_fallback(self, extractor: DocumentExtractor) -> None:
        # Bytes that are invalid UTF-8 but valid latin-1
        data = bytes([0x48, 0x65, 0x6C, 0x6C, 0x6F, 0xE9])  # "Hellé" in latin-1
        result = await extractor.extract(data, "text/plain")
        assert "Hell" in result.text


class TestExtractCsv:
    async def test_basic_csv(self, extractor: DocumentExtractor) -> None:
        data = b"name,age\nAlice,30\nBob,25"
        result = await extractor.extract(data, "text/csv")
        assert "Alice" in result.text
        assert "Bob" in result.text

    async def test_csv_with_bom(self, extractor: DocumentExtractor) -> None:
        data = b"\xef\xbb\xbfname,value\nhello,world"
        result = await extractor.extract(data, "text/csv")
        assert "hello" in result.text
        assert "world" in result.text

    async def test_byte_offsets_correctness(self, extractor: DocumentExtractor) -> None:
        data = b"a,b\n1,2"
        result = await extractor.extract(data, "text/csv")
        encoded = result.text.encode("utf-8")
        for entry in result.byte_offsets:
            char_span = result.text[entry.char_start:entry.char_end]
            byte_span = encoded[entry.byte_start:entry.byte_end].decode("utf-8")
            assert char_span == byte_span

    async def test_single_row(self, extractor: DocumentExtractor) -> None:
        data = b"only,one,row"
        result = await extractor.extract(data, "text/csv")
        assert "only" in result.text


class TestExtractJson:
    async def test_simple_json_object(self, extractor: DocumentExtractor) -> None:
        payload = {"name": "Alice", "age": 30}
        data = json.dumps(payload).encode()
        result = await extractor.extract(data, "application/json")
        assert "Alice" in result.text

    async def test_json_array(self, extractor: DocumentExtractor) -> None:
        payload = [{"id": 1}, {"id": 2}]
        data = json.dumps(payload).encode()
        result = await extractor.extract(data, "application/json")
        assert "id" in result.text

    async def test_non_ascii_json(self, extractor: DocumentExtractor) -> None:
        payload = {"city": "München"}
        data = json.dumps(payload, ensure_ascii=False).encode()
        result = await extractor.extract(data, "application/json")
        assert "München" in result.text

    async def test_byte_offsets_correctness(self, extractor: DocumentExtractor) -> None:
        data = b'{"key": "value"}'
        result = await extractor.extract(data, "application/json")
        encoded = result.text.encode("utf-8")
        for entry in result.byte_offsets:
            char_span = result.text[entry.char_start:entry.char_end]
            byte_span = encoded[entry.byte_start:entry.byte_end].decode("utf-8")
            assert char_span == byte_span

    async def test_corrupt_json_raises_extraction_error(
        self, extractor: DocumentExtractor
    ) -> None:
        with pytest.raises(ExtractionError, match="JSON extraction failed"):
            await extractor.extract(b"{not valid json", "application/json")


class TestExtractPdf:
    async def test_successful_extraction_returns_text(
        self, extractor: DocumentExtractor
    ) -> None:
        with patch(
            "fileguard.core.document_extractor.DocumentExtractor._extract_pdf",
            return_value="PDF content here",
        ):
            result = await extractor.extract(b"fake-pdf-bytes", "application/pdf")
        assert "PDF content here" in result.text

    async def test_byte_offsets_populated(self, extractor: DocumentExtractor) -> None:
        with patch(
            "fileguard.core.document_extractor.DocumentExtractor._extract_pdf",
            return_value="line one\nline two",
        ):
            result = await extractor.extract(b"fake-pdf-bytes", "application/pdf")
        assert len(result.byte_offsets) == 2

    async def test_byte_offsets_correctness(self, extractor: DocumentExtractor) -> None:
        with patch(
            "fileguard.core.document_extractor.DocumentExtractor._extract_pdf",
            return_value="Hello PDF\nSecond line",
        ):
            result = await extractor.extract(b"fake-pdf-bytes", "application/pdf")
        encoded = result.text.encode("utf-8")
        for entry in result.byte_offsets:
            char_span = result.text[entry.char_start:entry.char_end]
            byte_span = encoded[entry.byte_start:entry.byte_end].decode("utf-8")
            assert char_span == byte_span

    async def test_pdfminer_error_raises_extraction_error(
        self, extractor: DocumentExtractor
    ) -> None:
        with patch(
            "pdfminer.high_level.extract_text",
            side_effect=Exception("malformed PDF stream"),
        ):
            with pytest.raises(ExtractionError):
                await extractor.extract(b"corrupt-pdf", "application/pdf")

    async def test_returns_extraction_result(self, extractor: DocumentExtractor) -> None:
        with patch(
            "fileguard.core.document_extractor.DocumentExtractor._extract_pdf",
            return_value="some text",
        ):
            result = await extractor.extract(b"fake-pdf", "application/pdf")
        assert isinstance(result, ExtractionResult)


class TestExtractDocx:
    async def test_successful_extraction(self, extractor: DocumentExtractor) -> None:
        docx_bytes = _make_docx(["Hello DOCX", "Second paragraph"])
        result = await extractor.extract(
            docx_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert "Hello DOCX" in result.text
        assert "Second paragraph" in result.text

    async def test_byte_offsets_populated(self, extractor: DocumentExtractor) -> None:
        docx_bytes = _make_docx(["Paragraph one", "Paragraph two"])
        result = await extractor.extract(
            docx_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert len(result.byte_offsets) >= 1

    async def test_byte_offsets_correctness(self, extractor: DocumentExtractor) -> None:
        docx_bytes = _make_docx(["café", "hello"])
        result = await extractor.extract(
            docx_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        encoded = result.text.encode("utf-8")
        for entry in result.byte_offsets:
            char_span = result.text[entry.char_start:entry.char_end]
            byte_span = encoded[entry.byte_start:entry.byte_end].decode("utf-8")
            assert char_span == byte_span

    async def test_corrupt_docx_raises_extraction_error(
        self, extractor: DocumentExtractor
    ) -> None:
        with pytest.raises(ExtractionError, match="DOCX extraction failed"):
            await extractor.extract(
                b"not-a-docx-file",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )

    async def test_returns_extraction_result(self, extractor: DocumentExtractor) -> None:
        docx_bytes = _make_docx(["Test"])
        result = await extractor.extract(
            docx_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        assert isinstance(result, ExtractionResult)


class TestExtractZip:
    async def test_zip_with_txt_files(self, extractor: DocumentExtractor) -> None:
        zip_bytes = _make_zip(
            {
                "hello.txt": b"Hello from TXT",
                "world.txt": b"World text here",
            }
        )
        result = await extractor.extract(zip_bytes, "application/zip")
        assert "Hello from TXT" in result.text
        assert "World text here" in result.text

    async def test_zip_with_json_file(self, extractor: DocumentExtractor) -> None:
        payload = json.dumps({"secret": "value"}).encode()
        zip_bytes = _make_zip({"data.json": payload})
        result = await extractor.extract(zip_bytes, "application/zip")
        assert "secret" in result.text

    async def test_zip_with_csv_file(self, extractor: DocumentExtractor) -> None:
        csv_bytes = b"col1,col2\nfoo,bar"
        zip_bytes = _make_zip({"sheet.csv": csv_bytes})
        result = await extractor.extract(zip_bytes, "application/zip")
        assert "foo" in result.text

    async def test_zip_recursive_nested_zip(self, extractor: DocumentExtractor) -> None:
        # Inner ZIP contains a TXT
        inner_zip = _make_zip({"inner.txt": b"nested text"})
        # Outer ZIP contains the inner ZIP
        outer_zip = _make_zip({"inner.zip": inner_zip})
        result = await extractor.extract(outer_zip, "application/zip")
        assert "nested text" in result.text

    async def test_zip_skips_unsupported_files(
        self, extractor: DocumentExtractor
    ) -> None:
        zip_bytes = _make_zip(
            {
                "image.png": b"\x89PNG\r\n\x1a\n",
                "readme.txt": b"readable text",
            }
        )
        result = await extractor.extract(zip_bytes, "application/zip")
        # PNG is silently skipped; TXT is extracted
        assert "readable text" in result.text

    async def test_zip_skips_directory_entries(
        self, extractor: DocumentExtractor
    ) -> None:
        zip_bytes = _make_zip({"subdir/": b"", "subdir/file.txt": b"file content"})
        result = await extractor.extract(zip_bytes, "application/zip")
        assert "file content" in result.text

    async def test_zip_byte_offsets_populated(
        self, extractor: DocumentExtractor
    ) -> None:
        zip_bytes = _make_zip({"a.txt": b"line1\nline2"})
        result = await extractor.extract(zip_bytes, "application/zip")
        assert len(result.byte_offsets) >= 1

    async def test_zip_byte_offsets_correctness(
        self, extractor: DocumentExtractor
    ) -> None:
        zip_bytes = _make_zip({"a.txt": b"café\nbar"})
        result = await extractor.extract(zip_bytes, "application/zip")
        encoded = result.text.encode("utf-8")
        for entry in result.byte_offsets:
            char_span = result.text[entry.char_start:entry.char_end]
            byte_span = encoded[entry.byte_start:entry.byte_end].decode("utf-8")
            assert char_span == byte_span

    async def test_x_zip_compressed_mime_alias(
        self, extractor: DocumentExtractor
    ) -> None:
        zip_bytes = _make_zip({"file.txt": b"alias content"})
        result = await extractor.extract(zip_bytes, "application/x-zip-compressed")
        assert "alias content" in result.text

    async def test_corrupt_zip_raises_extraction_error(
        self, extractor: DocumentExtractor
    ) -> None:
        with pytest.raises(ExtractionError, match="ZIP extraction failed"):
            await extractor.extract(b"not-a-zip-file", "application/zip")


# ---------------------------------------------------------------------------
# Error-path tests
# ---------------------------------------------------------------------------


class TestUnsupportedMimeType:
    async def test_image_png_raises_error(self, extractor: DocumentExtractor) -> None:
        with pytest.raises(ExtractionError, match="Unsupported MIME type"):
            await extractor.extract(b"\x89PNG", "image/png")

    async def test_octet_stream_raises_error(self, extractor: DocumentExtractor) -> None:
        with pytest.raises(ExtractionError, match="Unsupported MIME type"):
            await extractor.extract(b"\x00\x01\x02", "application/octet-stream")

    async def test_html_raises_error(self, extractor: DocumentExtractor) -> None:
        with pytest.raises(ExtractionError, match="Unsupported MIME type"):
            await extractor.extract(b"<html/>", "text/html")

    async def test_empty_mime_type_raises_error(
        self, extractor: DocumentExtractor
    ) -> None:
        with pytest.raises(ExtractionError, match="Unsupported MIME type"):
            await extractor.extract(b"data", "")

    async def test_error_message_lists_supported_types(
        self, extractor: DocumentExtractor
    ) -> None:
        with pytest.raises(ExtractionError) as exc_info:
            await extractor.extract(b"data", "video/mp4")
        assert "application/pdf" in str(exc_info.value)


class TestCorruptFiles:
    async def test_corrupt_pdf_raises_extraction_error(
        self, extractor: DocumentExtractor
    ) -> None:
        with patch(
            "pdfminer.high_level.extract_text",
            side_effect=Exception("unexpected end of stream"),
        ):
            with pytest.raises(ExtractionError):
                await extractor.extract(b"%PDF-bad", "application/pdf")

    async def test_corrupt_docx_raises_extraction_error(
        self, extractor: DocumentExtractor
    ) -> None:
        with pytest.raises(ExtractionError, match="DOCX extraction failed"):
            await extractor.extract(
                b"PK not-really-a-docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )

    async def test_corrupt_json_raises_extraction_error(
        self, extractor: DocumentExtractor
    ) -> None:
        with pytest.raises(ExtractionError, match="JSON extraction failed"):
            await extractor.extract(b"{invalid json!!!}", "application/json")

    async def test_corrupt_zip_raises_extraction_error(
        self, extractor: DocumentExtractor
    ) -> None:
        with pytest.raises(ExtractionError, match="ZIP extraction failed"):
            await extractor.extract(b"PK not-a-real-zip", "application/zip")


# ---------------------------------------------------------------------------
# Thread-pool (run_in_executor) dispatch tests
# ---------------------------------------------------------------------------


class TestThreadPoolDispatch:
    async def test_extract_uses_run_in_executor(
        self, extractor: DocumentExtractor
    ) -> None:
        """extract() must dispatch the synchronous handler via run_in_executor."""
        data = b"hello world"

        original_extract = extractor._extract_txt
        calls: list[tuple] = []

        def recording_handler(d: bytes) -> str:
            calls.append((d,))
            return original_extract(d)

        extractor._extract_txt = recording_handler  # type: ignore[method-assign]

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            # run_in_executor must return an awaitable; return a coroutine that
            # yields the handler result to keep the test simple.
            async def fake_run_in_executor(executor, func, *args):
                return func(*args)

            mock_loop.run_in_executor = fake_run_in_executor

            result = await extractor.extract(data, "text/plain")

        mock_get_loop.assert_called_once()
        assert "hello world" in result.text

    async def test_executor_is_passed_to_run_in_executor(
        self, extractor: DocumentExtractor
    ) -> None:
        """The ThreadPoolExecutor instance must be the first argument to run_in_executor."""
        data = b"test"
        received_executors: list = []

        original_extract = extractor._extract_txt

        with patch("asyncio.get_running_loop") as mock_get_loop:
            mock_loop = MagicMock()
            mock_get_loop.return_value = mock_loop

            async def capturing_run_in_executor(executor, func, *args):
                received_executors.append(executor)
                return func(*args)

            mock_loop.run_in_executor = capturing_run_in_executor

            await extractor.extract(data, "text/plain")

        assert len(received_executors) == 1
        assert received_executors[0] is extractor._executor


# ---------------------------------------------------------------------------
# SUPPORTED_MIME_TYPES constant tests
# ---------------------------------------------------------------------------


class TestSupportedMimeTypes:
    def test_all_six_formats_present(self) -> None:
        assert "application/pdf" in SUPPORTED_MIME_TYPES
        assert (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            in SUPPORTED_MIME_TYPES
        )
        assert "text/csv" in SUPPORTED_MIME_TYPES
        assert "application/json" in SUPPORTED_MIME_TYPES
        assert "text/plain" in SUPPORTED_MIME_TYPES
        assert "application/zip" in SUPPORTED_MIME_TYPES

    def test_is_frozenset(self) -> None:
        assert isinstance(SUPPORTED_MIME_TYPES, frozenset)
