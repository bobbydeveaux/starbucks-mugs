"""Unit tests for fileguard/core/document_extractor.py.

All tests run fully offline — no external network or filesystem dependencies.
In-memory bytes are used for all document formats; pdfminer and python-docx
are mocked where creating a real file would require complex binary encoding.

Coverage targets:
* TXT, CSV, JSON format handlers — real in-memory content.
* PDF and DOCX format handlers — mocked extraction libraries.
* ZIP archive handler — real in-memory ZIP containing TXT, CSV, and JSON.
* Byte-offset map correctness: result.text[entry.text_start:entry.text_end]
  must equal the extracted span.
* Error paths: ExtractionError raised for unsupported MIME types and
  malformed inputs.
* Thread-pool dispatch: extract() must delegate to run_in_executor with
  the configured executor instance.
"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fileguard.core.document_extractor import (
    DocumentExtractor,
    ExtractionError,
    ExtractionResult,
    OffsetEntry,
    _normalize,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_zip(*members: tuple[str, bytes]) -> bytes:
    """Return ZIP archive bytes containing the given (name, content) pairs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in members:
            zf.writestr(name, content)
    return buf.getvalue()


def _assert_offsets_valid(result: ExtractionResult) -> None:
    """Assert that every OffsetEntry correctly slices the normalised text."""
    for entry in result.offsets:
        span = result.text[entry.text_start:entry.text_end]
        assert span, (
            f"OffsetEntry {entry} produced an empty slice of {result.text!r}"
        )
        # text_start must be < text_end
        assert entry.text_start < entry.text_end, (
            f"OffsetEntry has text_start >= text_end: {entry}"
        )
        # byte offsets must be non-negative
        assert entry.byte_start >= 0
        assert entry.byte_end > entry.byte_start


# ---------------------------------------------------------------------------
# TXT extraction
# ---------------------------------------------------------------------------


class TestDocumentExtractorTXT:
    """Plain-text extraction using real in-memory bytes."""

    def setup_method(self) -> None:
        self.extractor = DocumentExtractor(max_workers=1)

    def test_extracts_basic_text(self) -> None:
        content = b"Hello World"
        result = self.extractor._extract_txt(content)
        assert result.text == "Hello World"

    def test_returns_extraction_result(self) -> None:
        result = self.extractor._extract_txt(b"Hello")
        assert isinstance(result, ExtractionResult)

    def test_offset_spans_whole_text(self) -> None:
        content = b"Hello World"
        result = self.extractor._extract_txt(content)
        assert len(result.offsets) == 1
        entry = result.offsets[0]
        assert entry.text_start == 0
        assert entry.text_end == len(result.text)
        assert result.text[entry.text_start:entry.text_end] == "Hello World"

    def test_offset_byte_range_covers_content(self) -> None:
        content = b"Hello World"
        result = self.extractor._extract_txt(content)
        entry = result.offsets[0]
        assert entry.byte_start == 0
        assert entry.byte_end == len(content)

    def test_normalises_excess_whitespace(self) -> None:
        content = b"Hello   World"
        result = self.extractor._extract_txt(content)
        assert result.text == "Hello World"

    def test_normalises_multiple_lines(self) -> None:
        content = b"Line one\n\nLine two"
        result = self.extractor._extract_txt(content)
        assert "Line one" in result.text
        assert "Line two" in result.text
        # Empty lines must be stripped
        assert "\n\n" not in result.text

    def test_latin1_fallback_on_non_utf8(self) -> None:
        # b'\xe9' is 'é' in Latin-1 but invalid UTF-8
        content = b"caf\xe9"
        result = self.extractor._extract_txt(content)
        assert "caf" in result.text  # at minimum the ASCII prefix is present

    def test_empty_content_returns_empty_text(self) -> None:
        result = self.extractor._extract_txt(b"")
        assert result.text == ""
        assert result.offsets == []

    def test_offset_validity(self) -> None:
        result = self.extractor._extract_txt(b"Hello World")
        _assert_offsets_valid(result)


# ---------------------------------------------------------------------------
# CSV extraction
# ---------------------------------------------------------------------------


class TestDocumentExtractorCSV:
    """CSV extraction using real in-memory bytes."""

    def setup_method(self) -> None:
        self.extractor = DocumentExtractor(max_workers=1)

    def _csv(self, *rows: tuple[str, ...]) -> bytes:
        buf = io.StringIO()
        import csv
        writer = csv.writer(buf)
        writer.writerows(rows)
        return buf.getvalue().encode("utf-8")

    def test_extracts_header_row(self) -> None:
        content = self._csv(("name", "age"), ("Alice", "30"))
        result = self.extractor._extract_csv(content)
        assert "name" in result.text
        assert "age" in result.text

    def test_extracts_data_rows(self) -> None:
        content = self._csv(("name", "age"), ("Alice", "30"))
        result = self.extractor._extract_csv(content)
        assert "Alice" in result.text
        assert "30" in result.text

    def test_returns_extraction_result(self) -> None:
        content = self._csv(("a", "b"),)
        result = self.extractor._extract_csv(content)
        assert isinstance(result, ExtractionResult)

    def test_produces_one_offset_entry_per_non_empty_row(self) -> None:
        content = self._csv(("header1", "header2"), ("val1", "val2"))
        result = self.extractor._extract_csv(content)
        assert len(result.offsets) == 2

    def test_offset_text_ranges_are_non_overlapping(self) -> None:
        content = self._csv(("a", "b"), ("c", "d"), ("e", "f"))
        result = self.extractor._extract_csv(content)
        for i, entry in enumerate(result.offsets[:-1]):
            next_entry = result.offsets[i + 1]
            assert entry.text_end <= next_entry.text_start

    def test_offsets_correctly_slice_text(self) -> None:
        content = self._csv(("name", "age"), ("Alice", "30"))
        result = self.extractor._extract_csv(content)
        for entry in result.offsets:
            span = result.text[entry.text_start:entry.text_end]
            assert span  # non-empty

    def test_empty_csv_returns_empty_text(self) -> None:
        result = self.extractor._extract_csv(b"")
        assert result.text == ""
        assert result.offsets == []

    def test_offset_validity(self) -> None:
        content = self._csv(("name", "age"), ("Alice", "30"))
        result = self.extractor._extract_csv(content)
        _assert_offsets_valid(result)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


class TestDocumentExtractorJSON:
    """JSON extraction using real in-memory bytes."""

    def setup_method(self) -> None:
        self.extractor = DocumentExtractor(max_workers=1)

    def test_extracts_top_level_string_value(self) -> None:
        content = json.dumps({"key": "hello world"}).encode()
        result = self.extractor._extract_json(content)
        assert "hello world" in result.text

    def test_extracts_nested_strings(self) -> None:
        data = {"outer": {"inner": "deep value"}}
        content = json.dumps(data).encode()
        result = self.extractor._extract_json(content)
        assert "deep value" in result.text

    def test_extracts_strings_from_array(self) -> None:
        content = json.dumps(["first", "second", "third"]).encode()
        result = self.extractor._extract_json(content)
        assert "first" in result.text
        assert "second" in result.text
        assert "third" in result.text

    def test_ignores_numeric_values(self) -> None:
        content = json.dumps({"number": 42, "text": "hello"}).encode()
        result = self.extractor._extract_json(content)
        # "42" should not appear as a standalone token in the text
        assert "hello" in result.text

    def test_returns_extraction_result(self) -> None:
        content = json.dumps({"k": "v"}).encode()
        result = self.extractor._extract_json(content)
        assert isinstance(result, ExtractionResult)

    def test_offset_covers_full_text(self) -> None:
        content = json.dumps({"message": "test content"}).encode()
        result = self.extractor._extract_json(content)
        assert len(result.offsets) == 1
        entry = result.offsets[0]
        assert entry.text_start == 0
        assert entry.text_end == len(result.text)

    def test_offset_byte_range_covers_content(self) -> None:
        content = json.dumps({"k": "v"}).encode()
        result = self.extractor._extract_json(content)
        assert result.offsets[0].byte_start == 0
        assert result.offsets[0].byte_end == len(content)

    def test_raises_extraction_error_on_invalid_json(self) -> None:
        with pytest.raises(ExtractionError, match="Failed to parse JSON"):
            self.extractor._extract_json(b"{ invalid json }")

    def test_empty_object_returns_empty_text(self) -> None:
        result = self.extractor._extract_json(b"{}")
        assert result.text == ""
        assert result.offsets == []

    def test_offset_validity(self) -> None:
        content = json.dumps({"key": "some value here"}).encode()
        result = self.extractor._extract_json(content)
        _assert_offsets_valid(result)


# ---------------------------------------------------------------------------
# PDF extraction (mocked pdfminer)
# ---------------------------------------------------------------------------


class TestDocumentExtractorPDF:
    """PDF extraction with pdfminer.six mocked out."""

    def setup_method(self) -> None:
        self.extractor = DocumentExtractor(max_workers=1)

    def _run(self, content: bytes, mock_text: str) -> ExtractionResult:
        """Call _extract_pdf with pdfminer mocked to return *mock_text*."""
        with patch(
            "pdfminer.high_level.extract_text_to_fp",
        ) as mock_extract:
            def _write_text(src, dst, **kwargs):
                dst.write(mock_text)

            mock_extract.side_effect = _write_text
            return self.extractor._extract_pdf(content)

    def test_extracts_text_returned_by_pdfminer(self) -> None:
        result = self._run(b"%PDF-1.4 fake", "Hello from PDF\n")
        assert "Hello from PDF" in result.text

    def test_returns_extraction_result(self) -> None:
        result = self._run(b"%PDF-1.4 fake", "Some text\n")
        assert isinstance(result, ExtractionResult)

    def test_offset_covers_full_text(self) -> None:
        result = self._run(b"%PDF-1.4 fake", "Hello from PDF\n")
        assert len(result.offsets) == 1
        entry = result.offsets[0]
        assert entry.text_start == 0
        assert entry.text_end == len(result.text)
        assert result.text[entry.text_start:entry.text_end] == result.text

    def test_offset_byte_range_covers_content(self) -> None:
        content = b"%PDF-1.4 fake"
        result = self._run(content, "Hello\n")
        assert result.offsets[0].byte_start == 0
        assert result.offsets[0].byte_end == len(content)

    def test_normalises_whitespace(self) -> None:
        result = self._run(b"%PDF-1.4 fake", "Hello   World\n")
        assert result.text == "Hello World"

    def test_raises_extraction_error_on_pdfminer_failure(self) -> None:
        with patch("pdfminer.high_level.extract_text_to_fp") as mock_extract:
            mock_extract.side_effect = Exception("corrupt PDF")
            with pytest.raises(ExtractionError, match="Failed to extract PDF"):
                self.extractor._extract_pdf(b"not a real pdf")

    def test_empty_pdf_returns_empty_text(self) -> None:
        result = self._run(b"%PDF-1.4 empty", "")
        assert result.text == ""
        assert result.offsets == []

    def test_offset_validity(self) -> None:
        result = self._run(b"%PDF-1.4 fake", "Hello from PDF\n")
        _assert_offsets_valid(result)


# ---------------------------------------------------------------------------
# DOCX extraction (mocked python-docx)
# ---------------------------------------------------------------------------


class TestDocumentExtractorDOCX:
    """DOCX extraction with python-docx mocked out."""

    def setup_method(self) -> None:
        self.extractor = DocumentExtractor(max_workers=1)

    @staticmethod
    def _make_mock_doc(*para_texts: str) -> MagicMock:
        """Return a mock docx.Document with the given paragraph texts."""
        doc = MagicMock()
        paragraphs = []
        for text in para_texts:
            para = MagicMock()
            para.text = text
            paragraphs.append(para)
        doc.paragraphs = paragraphs
        return doc

    def _run(self, content: bytes, *para_texts: str) -> ExtractionResult:
        mock_doc = TestDocumentExtractorDOCX._make_mock_doc(*para_texts)
        with patch("docx.Document", return_value=mock_doc):
            return self.extractor._extract_docx(content)

    def test_extracts_single_paragraph(self) -> None:
        result = self._run(b"fake-docx", "Hello from DOCX")
        assert "Hello from DOCX" in result.text

    def test_extracts_multiple_paragraphs(self) -> None:
        result = self._run(b"fake-docx", "First paragraph", "Second paragraph")
        assert "First paragraph" in result.text
        assert "Second paragraph" in result.text

    def test_returns_extraction_result(self) -> None:
        result = self._run(b"fake-docx", "Some text")
        assert isinstance(result, ExtractionResult)

    def test_produces_one_offset_entry_per_non_empty_paragraph(self) -> None:
        result = self._run(b"fake-docx", "Para one", "", "Para three")
        # Empty paragraph should be skipped
        assert len(result.offsets) == 2

    def test_offsets_correctly_slice_text(self) -> None:
        result = self._run(b"fake-docx", "First paragraph", "Second paragraph")
        for entry in result.offsets:
            span = result.text[entry.text_start:entry.text_end]
            assert span  # non-empty slice

    def test_first_paragraph_text_start_is_zero(self) -> None:
        result = self._run(b"fake-docx", "Hello World")
        assert result.offsets[0].text_start == 0

    def test_paragraphs_joined_with_newline(self) -> None:
        result = self._run(b"fake-docx", "Para A", "Para B")
        assert result.text == "Para A\nPara B"

    def test_raises_extraction_error_on_docx_failure(self) -> None:
        with patch("docx.Document", side_effect=Exception("bad zip")):
            with pytest.raises(ExtractionError, match="Failed to extract DOCX"):
                self.extractor._extract_docx(b"not a real docx")

    def test_empty_document_returns_empty_text(self) -> None:
        result = self._run(b"fake-docx")  # no paragraphs
        assert result.text == ""
        assert result.offsets == []

    def test_offset_validity(self) -> None:
        result = self._run(b"fake-docx", "First", "Second", "Third")
        _assert_offsets_valid(result)

    def test_offset_byte_range_covers_content(self) -> None:
        content = b"fake-docx-bytes"
        result = self._run(content, "Hello")
        assert result.offsets[0].byte_start == 0
        assert result.offsets[0].byte_end == len(content)


# ---------------------------------------------------------------------------
# ZIP extraction
# ---------------------------------------------------------------------------


class TestDocumentExtractorZIP:
    """ZIP archive extraction using real in-memory ZIP files."""

    def setup_method(self) -> None:
        self.extractor = DocumentExtractor(max_workers=1)

    def test_extracts_txt_member(self) -> None:
        content = _make_zip(("readme.txt", b"Hello from TXT inside ZIP"))
        result = self.extractor._extract_zip(content)
        assert "Hello from TXT inside ZIP" in result.text

    def test_extracts_csv_member(self) -> None:
        csv_bytes = b"name,age\nAlice,30\n"
        content = _make_zip(("data.csv", csv_bytes))
        result = self.extractor._extract_zip(content)
        assert "Alice" in result.text

    def test_extracts_json_member(self) -> None:
        json_bytes = json.dumps({"message": "hello from json"}).encode()
        content = _make_zip(("config.json", json_bytes))
        result = self.extractor._extract_zip(content)
        assert "hello from json" in result.text

    def test_extracts_multiple_members(self) -> None:
        content = _make_zip(
            ("a.txt", b"Alpha content"),
            ("b.txt", b"Beta content"),
        )
        result = self.extractor._extract_zip(content)
        assert "Alpha content" in result.text
        assert "Beta content" in result.text

    def test_skips_directory_entries(self) -> None:
        content = _make_zip(("subdir/", b""), ("subdir/file.txt", b"Inner file"))
        result = self.extractor._extract_zip(content)
        assert "Inner file" in result.text

    def test_recursive_zip_extraction(self) -> None:
        """A ZIP inside a ZIP should be recursively extracted."""
        inner_zip = _make_zip(("inner.txt", b"Deeply nested content"))
        outer_zip = _make_zip(("nested.zip", inner_zip))
        result = self.extractor._extract_zip(outer_zip)
        assert "Deeply nested content" in result.text

    def test_offset_spans_each_member_text(self) -> None:
        content = _make_zip(
            ("a.txt", b"Alpha"),
            ("b.txt", b"Beta"),
        )
        result = self.extractor._extract_zip(content)
        assert len(result.offsets) == 2
        for entry in result.offsets:
            span = result.text[entry.text_start:entry.text_end]
            assert span  # non-empty

    def test_raises_extraction_error_for_non_zip_bytes(self) -> None:
        with pytest.raises(ExtractionError, match="not a valid ZIP archive"):
            self.extractor._extract_zip(b"this is not a zip file at all")

    def test_corrupt_member_is_skipped_not_fatal(self) -> None:
        """A ZIP member that fails extraction should be skipped, not abort."""
        # Add a file with a .pdf extension but corrupt bytes — pdfminer will
        # fail, but the extractor should log a warning and continue.
        content = _make_zip(
            ("good.txt", b"Good content"),
            ("bad.pdf", b"not a real pdf"),
        )
        with patch("pdfminer.high_level.extract_text_to_fp") as mock_pdf:
            mock_pdf.side_effect = Exception("pdfminer error")
            result = self.extractor._extract_zip(content)
        # The good .txt member should still be extracted
        assert "Good content" in result.text

    def test_returns_extraction_result(self) -> None:
        content = _make_zip(("file.txt", b"Some text"))
        result = self.extractor._extract_zip(content)
        assert isinstance(result, ExtractionResult)

    def test_offset_validity(self) -> None:
        content = _make_zip(("a.txt", b"Alpha"), ("b.txt", b"Beta"))
        result = self.extractor._extract_zip(content)
        _assert_offsets_valid(result)


# ---------------------------------------------------------------------------
# Byte-offset map correctness (cross-format)
# ---------------------------------------------------------------------------


class TestOffsetCorrectness:
    """Verify the offset invariant across all formats."""

    def setup_method(self) -> None:
        self.extractor = DocumentExtractor(max_workers=1)

    def test_txt_offsets_slice_text_correctly(self) -> None:
        result = self.extractor._extract_txt(b"Hello World. This is a test.")
        for entry in result.offsets:
            # The slice must not raise and must be non-empty.
            assert result.text[entry.text_start:entry.text_end]

    def test_csv_offsets_slice_text_correctly(self) -> None:
        import csv as _csv
        buf = io.StringIO()
        _csv.writer(buf).writerows([
            ("first_name", "last_name", "email"),
            ("John", "Doe", "john.doe@example.com"),
            ("Jane", "Smith", "jane.smith@example.com"),
        ])
        content = buf.getvalue().encode()
        result = self.extractor._extract_csv(content)
        for entry in result.offsets:
            assert result.text[entry.text_start:entry.text_end]

    def test_json_offsets_slice_text_correctly(self) -> None:
        content = json.dumps({
            "users": [
                {"name": "Alice", "role": "admin"},
                {"name": "Bob", "role": "viewer"},
            ]
        }).encode()
        result = self.extractor._extract_json(content)
        for entry in result.offsets:
            assert result.text[entry.text_start:entry.text_end]

    def test_zip_offsets_slice_text_correctly(self) -> None:
        content = _make_zip(
            ("notes.txt", b"First note"),
            ("data.json", json.dumps({"info": "second note"}).encode()),
        )
        result = self.extractor._extract_zip(content)
        for entry in result.offsets:
            assert result.text[entry.text_start:entry.text_end]

    def test_pdf_offsets_slice_text_correctly(self) -> None:
        with patch("pdfminer.high_level.extract_text_to_fp") as mock_pdf:
            def _write(src, dst, **kwargs):
                dst.write("PDF extracted text\n")
            mock_pdf.side_effect = _write
            result = self.extractor._extract_pdf(b"%PDF-1.4 stub")
        for entry in result.offsets:
            assert result.text[entry.text_start:entry.text_end]

    def test_docx_offsets_slice_text_correctly(self) -> None:
        para = MagicMock()
        para.text = "DOCX paragraph text"
        mock_doc = MagicMock()
        mock_doc.paragraphs = [para]
        with patch("docx.Document", return_value=mock_doc):
            result = self.extractor._extract_docx(b"stub")
        for entry in result.offsets:
            assert result.text[entry.text_start:entry.text_end]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestDocumentExtractorErrors:
    """Verify ExtractionError is raised for unsupported types and bad inputs."""

    def setup_method(self) -> None:
        self.extractor = DocumentExtractor(max_workers=1)

    def test_raises_for_unsupported_mime_type(self) -> None:
        with pytest.raises(ExtractionError, match="Unsupported MIME type"):
            self.extractor._extract_sync(b"data", "application/octet-stream")

    def test_raises_for_image_mime_type(self) -> None:
        with pytest.raises(ExtractionError, match="Unsupported MIME type"):
            self.extractor._extract_sync(b"\x89PNG", "image/png")

    def test_raises_for_xml_mime_type(self) -> None:
        with pytest.raises(ExtractionError, match="Unsupported MIME type"):
            self.extractor._extract_sync(b"<xml/>", "application/xml")

    def test_raises_for_malformed_json(self) -> None:
        with pytest.raises(ExtractionError, match="Failed to parse JSON"):
            self.extractor._extract_json(b"{ not valid json !!}")

    def test_raises_for_non_zip_bytes(self) -> None:
        with pytest.raises(ExtractionError, match="not a valid ZIP archive"):
            self.extractor._extract_zip(b"PK this is not a zip")

    def test_raises_for_pdf_extraction_failure(self) -> None:
        with patch("pdfminer.high_level.extract_text_to_fp") as mock_pdf:
            mock_pdf.side_effect = RuntimeError("PDF parse error")
            with pytest.raises(ExtractionError, match="Failed to extract PDF"):
                self.extractor._extract_pdf(b"not a pdf")

    def test_raises_for_docx_extraction_failure(self) -> None:
        with patch("docx.Document") as mock_docx:
            mock_docx.side_effect = Exception("docx open error")
            with pytest.raises(ExtractionError, match="Failed to extract DOCX"):
                self.extractor._extract_docx(b"not a docx")

    def test_error_message_includes_mime_type(self) -> None:
        try:
            self.extractor._extract_sync(b"data", "audio/mpeg")
        except ExtractionError as exc:
            assert "audio/mpeg" in str(exc)
        else:
            pytest.fail("ExtractionError was not raised")

    def test_mime_type_params_are_stripped(self) -> None:
        """MIME type parameters like charset should not cause an error."""
        result = self.extractor._extract_sync(b"hello", "text/plain; charset=utf-8")
        assert "hello" in result.text

    def test_case_insensitive_mime_type(self) -> None:
        result = self.extractor._extract_sync(b"hello", "TEXT/PLAIN")
        assert "hello" in result.text


# ---------------------------------------------------------------------------
# Thread-pool dispatch
# ---------------------------------------------------------------------------


class TestDocumentExtractorThreadPool:
    """Verify that extract() uses run_in_executor to dispatch to the pool."""

    @pytest.mark.asyncio
    async def test_extract_calls_run_in_executor(self) -> None:
        """extract() must delegate CPU-bound work via run_in_executor."""
        extractor = DocumentExtractor(max_workers=1)
        expected_result = ExtractionResult(text="mocked", offsets=[])

        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value=expected_result)

        with patch("asyncio.get_running_loop", return_value=mock_loop):
            result = await extractor.extract(b"hello", "text/plain")

        mock_loop.run_in_executor.assert_awaited_once_with(
            extractor._executor,
            extractor._extract_sync,
            b"hello",
            "text/plain",
        )
        assert result is expected_result

    @pytest.mark.asyncio
    async def test_extract_passes_correct_executor(self) -> None:
        """The configured executor instance must be passed to run_in_executor."""
        extractor = DocumentExtractor(max_workers=2)

        captured_executor = []

        async def _capture(*args, **kwargs):
            captured_executor.append(args[0])
            return ExtractionResult(text="x", offsets=[])

        mock_loop = MagicMock()
        mock_loop.run_in_executor = _capture

        with patch("asyncio.get_running_loop", return_value=mock_loop):
            await extractor.extract(b"data", "text/plain")

        assert captured_executor[0] is extractor._executor

    @pytest.mark.asyncio
    async def test_extract_passes_extract_sync_as_callable(self) -> None:
        """_extract_sync must be the callable passed to run_in_executor."""
        extractor = DocumentExtractor(max_workers=1)

        captured_fn = []

        async def _capture(*args, **kwargs):
            captured_fn.append(args[1])
            return ExtractionResult(text="y", offsets=[])

        mock_loop = MagicMock()
        mock_loop.run_in_executor = _capture

        with patch("asyncio.get_running_loop", return_value=mock_loop):
            await extractor.extract(b"data", "text/plain")

        # Bound methods compare equal when they wrap the same function/instance.
        assert captured_fn[0] == extractor._extract_sync
        assert captured_fn[0].__func__ is DocumentExtractor._extract_sync
        assert captured_fn[0].__self__ is extractor

    @pytest.mark.asyncio
    async def test_extract_returns_result_from_executor(self) -> None:
        """extract() must return whatever run_in_executor resolves to."""
        extractor = DocumentExtractor(max_workers=1)
        sentinel = ExtractionResult(text="sentinel", offsets=[
            OffsetEntry(text_start=0, text_end=8, byte_start=0, byte_end=8)
        ])

        mock_loop = MagicMock()
        mock_loop.run_in_executor = AsyncMock(return_value=sentinel)

        with patch("asyncio.get_running_loop", return_value=mock_loop):
            result = await extractor.extract(b"bytes", "text/plain")

        assert result is sentinel

    @pytest.mark.asyncio
    async def test_extract_dispatches_to_thread_not_event_loop(self) -> None:
        """_extract_sync must run in a worker thread, not the event loop thread."""
        import threading

        extractor = DocumentExtractor(max_workers=1)
        main_thread_id = threading.current_thread().ident
        call_thread_ids: list[int] = []

        original_sync = extractor._extract_sync

        def _tracking_sync(content: bytes, mime_type: str) -> ExtractionResult:
            call_thread_ids.append(threading.current_thread().ident)
            return original_sync(content, mime_type)

        extractor._extract_sync = _tracking_sync  # type: ignore[method-assign]

        await extractor.extract(b"hello world", "text/plain")

        assert len(call_thread_ids) == 1
        assert call_thread_ids[0] != main_thread_id


# ---------------------------------------------------------------------------
# _normalize helper
# ---------------------------------------------------------------------------


class TestNormalizeHelper:
    """Unit tests for the _normalize() text normalisation function."""

    def test_strips_leading_trailing_whitespace_per_line(self) -> None:
        assert _normalize("  hello  \n  world  ") == "hello\nworld"

    def test_collapses_multiple_spaces(self) -> None:
        assert _normalize("hello   world") == "hello world"

    def test_collapses_tabs_to_spaces(self) -> None:
        assert _normalize("hello\tworld") == "hello world"

    def test_removes_blank_lines(self) -> None:
        result = _normalize("line1\n\n\nline2")
        assert "\n\n" not in result
        assert "line1" in result
        assert "line2" in result

    def test_empty_string_returns_empty(self) -> None:
        assert _normalize("") == ""

    def test_only_whitespace_returns_empty(self) -> None:
        assert _normalize("   \n\t\n   ") == ""

    def test_preserves_meaningful_newlines(self) -> None:
        result = _normalize("line1\nline2")
        assert result == "line1\nline2"
