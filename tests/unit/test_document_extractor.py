"""Unit tests for fileguard/core/document_extractor.py.

All tests are fully offline – no network calls, no filesystem access, and no
external services are required.  Document fixtures are built in-memory.

Coverage targets:
- All six format handlers (TXT, JSON, CSV, PDF, DOCX, ZIP)
- Byte-offset map correctness (char_start / char_end reference valid spans)
- ZIP recursion and depth limiting
- ThreadPoolExecutor dispatch (concurrent.futures mocked)
- Error paths: UnsupportedMIMETypeError and CorruptFileError
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from fileguard.core.document_extractor import (
    ByteOffset,
    CorruptFileError,
    DocumentExtractor,
    ExtractionResult,
    UnsupportedMIMETypeError,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_txt(content: str, encoding: str = "utf-8") -> bytes:
    return content.encode(encoding)


def _make_json(obj: Any) -> bytes:
    return json.dumps(obj).encode("utf-8")


def _make_csv(rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _make_docx(paragraphs: list[str]) -> bytes:
    """Create a minimal in-memory DOCX with the given paragraphs."""
    from docx import Document  # noqa: PLC0415

    doc = Document()
    for para in paragraphs:
        doc.add_paragraph(para)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def extractor() -> DocumentExtractor:
    return DocumentExtractor(thread_pool_workers=1)


# ---------------------------------------------------------------------------
# Helper: assert offsets are internally consistent
# ---------------------------------------------------------------------------


def _assert_offsets_valid(result: ExtractionResult) -> None:
    """Verify that every ByteOffset entry points to a valid span in result.text."""
    for off in result.offsets:
        assert off.char_start >= 0, "char_start must be non-negative"
        assert off.char_end >= off.char_start, "char_end must be >= char_start"
        assert off.char_end <= len(result.text), (
            f"char_end {off.char_end} exceeds text length {len(result.text)}"
        )
        assert off.byte_start >= 0, "byte_start must be non-negative"
        assert off.byte_end >= off.byte_start, "byte_end must be >= byte_start"
        # Verify the character span actually indexes into the text
        _ = result.text[off.char_start : off.char_end]


# ===========================================================================
# TXT handler
# ===========================================================================


class TestTxtExtraction:
    def test_basic_text_returned(self, extractor: DocumentExtractor) -> None:
        data = _make_txt("Hello, world!\nSecond line.")
        result = extractor.extract(data, "sample.txt")
        assert "Hello, world!" in result.text
        assert "Second line." in result.text

    def test_offsets_cover_full_text(self, extractor: DocumentExtractor) -> None:
        data = _make_txt("line one\nline two\n")
        result = extractor.extract(data, "file.txt")
        assert result.offsets, "Expected at least one offset entry"
        _assert_offsets_valid(result)

    def test_char_spans_reconstruct_text(self, extractor: DocumentExtractor) -> None:
        content = "alpha\nbeta\ngamma\n"
        data = _make_txt(content)
        result = extractor.extract(data, "f.txt")
        # Reconstruct text from spans
        reconstructed = "".join(
            result.text[off.char_start : off.char_end] for off in result.offsets
        )
        assert reconstructed == result.text

    def test_byte_offsets_match_utf8(self, extractor: DocumentExtractor) -> None:
        content = "abc\ndef\n"
        data = _make_txt(content)
        result = extractor.extract(data, "f.txt")
        # For pure ASCII, char count == byte count per line
        for off in result.offsets:
            segment_bytes = off.byte_end - off.byte_start
            segment_chars = off.char_end - off.char_start
            assert segment_bytes == segment_chars  # ASCII: 1 byte per char

    def test_multibyte_unicode(self, extractor: DocumentExtractor) -> None:
        content = "café\nnaïve\n"
        data = _make_txt(content)
        result = extractor.extract(data, "uni.txt")
        assert "café" in result.text
        _assert_offsets_valid(result)

    def test_empty_file(self, extractor: DocumentExtractor) -> None:
        result = extractor.extract(b"", "empty.txt")
        assert result.text == ""
        assert result.offsets == []

    def test_single_line_no_newline(self, extractor: DocumentExtractor) -> None:
        data = _make_txt("no newline here")
        result = extractor.extract(data, "f.txt")
        assert "no newline here" in result.text
        _assert_offsets_valid(result)


# ===========================================================================
# JSON handler
# ===========================================================================


class TestJsonExtraction:
    def test_basic_json_object(self, extractor: DocumentExtractor) -> None:
        data = _make_json({"name": "Alice", "id": 42})
        result = extractor.extract(data, "data.json")
        assert "Alice" in result.text
        assert "42" in result.text

    def test_offsets_cover_full_text(self, extractor: DocumentExtractor) -> None:
        data = _make_json({"key": "value"})
        result = extractor.extract(data, "f.json")
        assert len(result.offsets) == 1
        off = result.offsets[0]
        assert off.char_start == 0
        assert off.char_end == len(result.text)
        assert off.byte_start == 0
        assert off.byte_end == len(data)

    def test_json_array(self, extractor: DocumentExtractor) -> None:
        data = _make_json([1, 2, 3, "four"])
        result = extractor.extract(data, "list.json")
        assert "four" in result.text
        _assert_offsets_valid(result)

    def test_malformed_json_raises_corrupt(self, extractor: DocumentExtractor) -> None:
        with pytest.raises(CorruptFileError):
            extractor.extract(b"{not valid json}", "bad.json")

    def test_empty_json_object(self, extractor: DocumentExtractor) -> None:
        data = _make_json({})
        result = extractor.extract(data, "empty.json")
        assert result.text.strip() == "{}"
        _assert_offsets_valid(result)


# ===========================================================================
# CSV handler
# ===========================================================================


class TestCsvExtraction:
    def test_basic_fields_present(self, extractor: DocumentExtractor) -> None:
        data = _make_csv([["name", "email"], ["Alice", "alice@example.com"]])
        result = extractor.extract(data, "contacts.csv")
        assert "Alice" in result.text
        assert "alice@example.com" in result.text

    def test_offsets_reference_valid_spans(self, extractor: DocumentExtractor) -> None:
        data = _make_csv([["a", "b", "c"], ["x", "y", "z"]])
        result = extractor.extract(data, "grid.csv")
        _assert_offsets_valid(result)

    def test_byte_offsets_within_data_bounds(self, extractor: DocumentExtractor) -> None:
        data = _make_csv([["hello", "world"]])
        result = extractor.extract(data, "row.csv")
        for off in result.offsets:
            assert off.byte_end <= len(data)

    def test_char_spans_non_overlapping_and_contiguous(
        self, extractor: DocumentExtractor
    ) -> None:
        data = _make_csv([["one", "two"], ["three", "four"]])
        result = extractor.extract(data, "f.csv")
        if len(result.offsets) > 1:
            for prev, curr in zip(result.offsets, result.offsets[1:]):
                assert curr.char_start == prev.char_end

    def test_multiline_csv(self, extractor: DocumentExtractor) -> None:
        rows = [["r1c1", "r1c2"], ["r2c1", "r2c2"], ["r3c1", "r3c2"]]
        data = _make_csv(rows)
        result = extractor.extract(data, "multi.csv")
        assert "r3c2" in result.text
        _assert_offsets_valid(result)

    def test_empty_csv(self, extractor: DocumentExtractor) -> None:
        result = extractor.extract(b"", "empty.csv")
        assert result.text == ""


# ===========================================================================
# PDF handler
# ===========================================================================


class TestPdfExtraction:
    """PDF extraction tests mock pdfminer to avoid binary fixture complexity."""

    def test_extracted_text_returned(self, extractor: DocumentExtractor) -> None:
        fake_pdf = b"%PDF-1.4 fake content for magic bytes"
        with patch(
            "pdfminer.high_level.extract_text",
            return_value="Hello from PDF\n",
        ):
            result = extractor.extract(fake_pdf, "doc.pdf")
        assert "Hello from PDF" in result.text

    def test_offsets_cover_full_text(self, extractor: DocumentExtractor) -> None:
        fake_pdf = b"%PDF-1.4 fake"
        extracted = "Some extracted text from PDF."
        with patch("pdfminer.high_level.extract_text", return_value=extracted):
            result = extractor.extract(fake_pdf, "r.pdf")

        assert len(result.offsets) == 1
        off = result.offsets[0]
        assert off.char_start == 0
        assert off.char_end == len(result.text)
        assert off.byte_start == 0
        assert off.byte_end == len(fake_pdf)
        _assert_offsets_valid(result)

    def test_empty_pdf_text_no_offsets(self, extractor: DocumentExtractor) -> None:
        fake_pdf = b"%PDF-1.4 fake"
        with patch("pdfminer.high_level.extract_text", return_value=""):
            result = extractor.extract(fake_pdf, "empty.pdf")
        assert result.text == ""
        assert result.offsets == []

    def test_corrupt_pdf_raises_error(self, extractor: DocumentExtractor) -> None:
        fake_pdf = b"%PDF-1.4 fake"
        with patch(
            "pdfminer.high_level.extract_text",
            side_effect=Exception("parse error"),
        ):
            with pytest.raises(CorruptFileError):
                extractor.extract(fake_pdf, "bad.pdf")

    def test_char_spans_index_into_text(self, extractor: DocumentExtractor) -> None:
        fake_pdf = b"%PDF-1.4 fake"
        extracted = "National Insurance: AA 12 34 56 A\n"
        with patch("pdfminer.high_level.extract_text", return_value=extracted):
            result = extractor.extract(fake_pdf, "r.pdf")

        _assert_offsets_valid(result)
        off = result.offsets[0]
        assert result.text[off.char_start : off.char_end] == extracted


# ===========================================================================
# DOCX handler
# ===========================================================================


class TestDocxExtraction:
    def test_paragraph_text_returned(self, extractor: DocumentExtractor) -> None:
        data = _make_docx(["First paragraph.", "Second paragraph."])
        result = extractor.extract(data, "document.docx")
        assert "First paragraph." in result.text
        assert "Second paragraph." in result.text

    def test_offsets_per_paragraph(self, extractor: DocumentExtractor) -> None:
        paragraphs = ["Para one.", "Para two.", "Para three."]
        data = _make_docx(paragraphs)
        result = extractor.extract(data, "doc.docx")
        # At least as many offsets as non-empty paragraphs (python-docx may
        # insert a default empty paragraph)
        assert len(result.offsets) >= len(paragraphs)
        _assert_offsets_valid(result)

    def test_char_spans_contiguous(self, extractor: DocumentExtractor) -> None:
        data = _make_docx(["A", "B", "C"])
        result = extractor.extract(data, "abc.docx")
        if len(result.offsets) > 1:
            for prev, curr in zip(result.offsets, result.offsets[1:]):
                assert curr.char_start == prev.char_end

    def test_byte_range_covers_full_docx(self, extractor: DocumentExtractor) -> None:
        data = _make_docx(["content"])
        result = extractor.extract(data, "f.docx")
        for off in result.offsets:
            assert off.byte_start == 0
            assert off.byte_end == len(data)

    def test_corrupt_docx_raises_error(self, extractor: DocumentExtractor) -> None:
        bad_docx = b"PK\x03\x04" + b"\x00" * 20  # ZIP magic but invalid DOCX
        with pytest.raises(CorruptFileError):
            extractor.extract(bad_docx, "corrupt.docx")

    def test_empty_docx(self, extractor: DocumentExtractor) -> None:
        """python-docx always adds a default empty paragraph."""
        data = _make_docx([])
        result = extractor.extract(data, "empty.docx")
        # Empty DOCX has a default paragraph; text may be just "\n"
        assert isinstance(result.text, str)
        _assert_offsets_valid(result)


# ===========================================================================
# ZIP handler
# ===========================================================================


class TestZipExtraction:
    def test_txt_inside_zip(self, extractor: DocumentExtractor) -> None:
        data = _make_zip({"readme.txt": _make_txt("Hello from ZIP!")})
        result = extractor.extract(data, "archive.zip")
        assert "Hello from ZIP!" in result.text

    def test_json_inside_zip(self, extractor: DocumentExtractor) -> None:
        data = _make_zip({"data.json": _make_json({"secret": "NI number AA123456A"})})
        result = extractor.extract(data, "archive.zip")
        assert "AA123456A" in result.text

    def test_multiple_files_inside_zip(self, extractor: DocumentExtractor) -> None:
        data = _make_zip(
            {
                "a.txt": _make_txt("file A content"),
                "b.txt": _make_txt("file B content"),
            }
        )
        result = extractor.extract(data, "multi.zip")
        assert "file A content" in result.text
        assert "file B content" in result.text

    def test_offsets_reference_valid_spans(self, extractor: DocumentExtractor) -> None:
        data = _make_zip(
            {
                "x.txt": _make_txt("text in x"),
                "y.json": _make_json({"k": "v"}),
            }
        )
        result = extractor.extract(data, "a.zip")
        _assert_offsets_valid(result)

    def test_nested_zip_recursion(self, extractor: DocumentExtractor) -> None:
        inner = _make_zip({"inner.txt": _make_txt("deep content")})
        outer = _make_zip({"nested.zip": inner})
        result = extractor.extract(outer, "outer.zip")
        assert "deep content" in result.text

    def test_zip_depth_limit_respected(self) -> None:
        extractor = DocumentExtractor(max_zip_depth=1, thread_pool_workers=1)
        inner = _make_zip({"inner.txt": _make_txt("should not appear")})
        outer = _make_zip({"nested.zip": inner})
        result = extractor.extract(outer, "outer.zip")
        # The outer archive is at depth 0; the inner is at depth 1 (== max),
        # so recursion stops and the nested content is NOT extracted.
        assert "should not appear" not in result.text

    def test_unsupported_entry_skipped(self, extractor: DocumentExtractor) -> None:
        data = _make_zip(
            {
                "file.bin": b"\x00\x01\x02\x03",  # octet-stream
                "valid.txt": _make_txt("good content"),
            }
        )
        result = extractor.extract(data, "mix.zip")
        assert "good content" in result.text

    def test_corrupt_zip_raises_error(self, extractor: DocumentExtractor) -> None:
        with pytest.raises(CorruptFileError):
            extractor.extract(b"PK\x03\x04 not a zip", "broken.zip")

    def test_zip_files_limit(self) -> None:
        extractor = DocumentExtractor(max_zip_files=2, thread_pool_workers=1)
        files = {f"file{i}.txt": _make_txt(f"content {i}") for i in range(10)}
        data = _make_zip(files)
        result = extractor.extract(data, "big.zip")
        # At most max_zip_files entries processed; not all 10 will appear
        count = sum(
            1 for i in range(10) if f"content {i}" in result.text
        )
        assert count <= 2

    def test_byte_offsets_within_zip_bounds(self, extractor: DocumentExtractor) -> None:
        data = _make_zip({"hello.txt": _make_txt("hello world")})
        result = extractor.extract(data, "a.zip")
        for off in result.offsets:
            assert off.byte_start >= 0
            assert off.byte_end <= len(data)


# ===========================================================================
# Thread-pool dispatch
# ===========================================================================


class TestThreadPoolDispatch:
    def test_executor_submit_called(self) -> None:
        """extract() must submit work to the ThreadPoolExecutor."""
        extractor = DocumentExtractor(thread_pool_workers=1)

        real_submit = extractor._executor.submit  # noqa: SLF001

        submitted: list[Any] = []

        def tracking_submit(fn, *args, **kwargs):  # noqa: ANN001
            submitted.append((fn, args, kwargs))
            return real_submit(fn, *args, **kwargs)

        extractor._executor.submit = tracking_submit  # type: ignore[method-assign]
        extractor.extract(_make_txt("test"), "test.txt")
        assert len(submitted) == 1, "Expected exactly one submit call"

    def test_future_result_returned(self) -> None:
        """extract() returns the result produced by the submitted future."""
        expected = ExtractionResult(
            text="mocked text",
            offsets=[ByteOffset(0, 11, 0, 11)],
        )

        mock_future: Future[ExtractionResult] = Future()
        mock_future.set_result(expected)

        mock_executor = MagicMock(spec=ThreadPoolExecutor)
        mock_executor.submit.return_value = mock_future

        extractor = DocumentExtractor.__new__(DocumentExtractor)
        extractor._executor = mock_executor  # type: ignore[attr-defined]
        extractor._max_zip_depth = 2
        extractor._max_zip_files = 1000

        result = extractor.extract(_make_txt("test"), "test.txt")
        assert result == expected
        mock_executor.submit.assert_called_once()


# ===========================================================================
# MIME type detection and unsupported type error
# ===========================================================================


class TestMimeDetectionAndErrors:
    def test_unsupported_mime_raises_error(
        self, extractor: DocumentExtractor
    ) -> None:
        with pytest.raises(UnsupportedMIMETypeError) as exc_info:
            extractor.extract(b"\x89PNG\r\n", "image.png")
        assert exc_info.value.mime_type  # non-empty
        assert "image.png" in exc_info.value.filename

    def test_pdf_detected_by_magic_bytes(
        self, extractor: DocumentExtractor
    ) -> None:
        detected = extractor._detect_mime_type(b"%PDF-1.4 data", "unknown")
        assert detected == "application/pdf"

    def test_zip_detected_by_magic_bytes(
        self, extractor: DocumentExtractor
    ) -> None:
        detected = extractor._detect_mime_type(b"PK\x03\x04 data", "archive.zip")
        assert detected == "application/zip"

    def test_docx_detected_by_magic_and_extension(
        self, extractor: DocumentExtractor
    ) -> None:
        detected = extractor._detect_mime_type(b"PK\x03\x04 data", "report.docx")
        assert "wordprocessingml" in detected

    def test_txt_detected_by_extension(
        self, extractor: DocumentExtractor
    ) -> None:
        detected = extractor._detect_mime_type(b"plain text", "notes.txt")
        assert detected == "text/plain"

    def test_json_detected_by_extension(
        self, extractor: DocumentExtractor
    ) -> None:
        detected = extractor._detect_mime_type(b'{"a": 1}', "data.json")
        assert detected == "application/json"

    def test_csv_detected_by_extension(
        self, extractor: DocumentExtractor
    ) -> None:
        detected = extractor._detect_mime_type(b"a,b,c", "sheet.csv")
        assert detected == "text/csv"

    def test_unsupported_error_attributes(
        self, extractor: DocumentExtractor
    ) -> None:
        exc = UnsupportedMIMETypeError(
            "not supported", mime_type="image/png", filename="img.png"
        )
        assert exc.mime_type == "image/png"
        assert exc.filename == "img.png"

    def test_corrupt_file_error_has_cause(self) -> None:
        original = ValueError("underlying error")
        exc = CorruptFileError("wrapped", cause=original)
        assert exc.cause is original


# ===========================================================================
# Context manager and shutdown
# ===========================================================================


class TestLifecycle:
    def test_context_manager_returns_extractor(self) -> None:
        with DocumentExtractor(thread_pool_workers=1) as ext:
            assert isinstance(ext, DocumentExtractor)

    def test_shutdown_called_on_exit(self) -> None:
        extractor = DocumentExtractor(thread_pool_workers=1)
        mock_executor = MagicMock(spec=ThreadPoolExecutor)
        extractor._executor = mock_executor  # type: ignore[attr-defined]
        extractor.shutdown()
        mock_executor.shutdown.assert_called_once_with(wait=True)

    def test_context_manager_shuts_down(self) -> None:
        extractor = DocumentExtractor(thread_pool_workers=1)
        mock_executor = MagicMock(spec=ThreadPoolExecutor)
        extractor._executor = mock_executor  # type: ignore[attr-defined]
        with extractor:
            pass
        mock_executor.shutdown.assert_called_once()


# ===========================================================================
# Integration: ExtractionResult structure
# ===========================================================================


class TestExtractionResultStructure:
    def test_result_is_named_tuple(self, extractor: DocumentExtractor) -> None:
        result = extractor.extract(_make_txt("hello"), "f.txt")
        assert isinstance(result, ExtractionResult)
        assert hasattr(result, "text")
        assert hasattr(result, "offsets")

    def test_offset_is_named_tuple(self, extractor: DocumentExtractor) -> None:
        result = extractor.extract(_make_txt("hello\n"), "f.txt")
        assert result.offsets
        off = result.offsets[0]
        assert isinstance(off, ByteOffset)
        assert hasattr(off, "char_start")
        assert hasattr(off, "char_end")
        assert hasattr(off, "byte_start")
        assert hasattr(off, "byte_end")

    def test_all_formats_return_extraction_result(
        self, extractor: DocumentExtractor
    ) -> None:
        """Smoke test that all 6 formats return a valid ExtractionResult."""
        fixtures: list[tuple[bytes, str]] = [
            (_make_txt("text"), "f.txt"),
            (_make_json({"k": "v"}), "f.json"),
            (_make_csv([["a", "b"]]), "f.csv"),
            (_make_zip({"inner.txt": _make_txt("zipped")}), "f.zip"),
        ]

        docx_data = _make_docx(["docx content"])
        fixtures.append((docx_data, "f.docx"))

        fake_pdf = b"%PDF-1.4 minimal"
        with patch(
            "pdfminer.high_level.extract_text", return_value="pdf text\n"
        ):
            pdf_result = extractor.extract(fake_pdf, "f.pdf")
        assert isinstance(pdf_result, ExtractionResult)

        for data, name in fixtures:
            result = extractor.extract(data, name)
            assert isinstance(result, ExtractionResult), (
                f"Expected ExtractionResult for {name}"
            )
            _assert_offsets_valid(result)
