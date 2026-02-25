"""Unit tests for fileguard/core/document_extractor.py.

All tests are fully offline — no filesystem, network, or real PDF/DOCX
rendering required.  Heavy optional dependencies (pdfminer.six, python-docx)
are patched at the module level where document_extractor.py holds references
to them, so the tests work regardless of whether those libraries are installed.

Coverage targets:
* TXT, CSV, JSON, PDF, DOCX, ZIP format handlers.
* Byte-offset list structure and basic correctness.
* ZIP recursion (nested archives, member limit, size limit, depth limit).
* Thread-pool dispatch via DocumentExtractor.extract().
* ExtractionError raised for unsupported MIME types and corrupt files.
"""

from __future__ import annotations

import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from fileguard.core.document_extractor import (
    ExtractionError,
    ExtractionResult,
    DocumentExtractor,
    _extract_txt,
    _extract_json,
    _extract_csv,
    _extract_zip,
    _dispatch_sync,
    _build_offsets,
    _guess_mime,
    _MAX_ZIP_FILE_COUNT,
    _MAX_ZIP_UNCOMPRESSED_BYTES,
    _MAX_ZIP_DEPTH,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_zip(members: dict[str, bytes]) -> bytes:
    """Return in-memory ZIP bytes containing *members*."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# _build_offsets
# ---------------------------------------------------------------------------


class TestBuildOffsets:
    def test_length_matches_text(self) -> None:
        text = "hello world"
        offsets = _build_offsets(text, 0, 100)
        assert len(offsets) == len(text)

    def test_monotonically_increasing(self) -> None:
        offsets = _build_offsets("abcdef", 10, 70)
        for i in range(len(offsets) - 1):
            assert offsets[i] <= offsets[i + 1]

    def test_starts_at_byte_start(self) -> None:
        offsets = _build_offsets("abc", 50, 80)
        assert offsets[0] == 50

    def test_empty_text_returns_empty(self) -> None:
        assert _build_offsets("", 0, 100) == []

    def test_single_char_returns_byte_start(self) -> None:
        offsets = _build_offsets("x", 42, 100)
        assert offsets == [42]


# ---------------------------------------------------------------------------
# _guess_mime
# ---------------------------------------------------------------------------


class TestGuessMime:
    def test_pdf(self) -> None:
        assert _guess_mime("report.pdf") == "application/pdf"

    def test_docx(self) -> None:
        assert "wordprocessingml" in _guess_mime("doc.docx")

    def test_csv(self) -> None:
        assert _guess_mime("data.csv") == "text/csv"

    def test_json(self) -> None:
        assert _guess_mime("config.json") == "application/json"

    def test_txt(self) -> None:
        assert _guess_mime("notes.txt") == "text/plain"

    def test_zip(self) -> None:
        assert _guess_mime("archive.zip") == "application/zip"

    def test_unknown(self) -> None:
        assert _guess_mime("file.xyz") == "application/octet-stream"

    def test_case_insensitive(self) -> None:
        assert _guess_mime("REPORT.PDF") == "application/pdf"

    def test_path_with_directory(self) -> None:
        assert _guess_mime("subdir/file.txt") == "text/plain"


# ---------------------------------------------------------------------------
# TXT extraction
# ---------------------------------------------------------------------------


class TestExtractTxt:
    def test_basic_utf8(self) -> None:
        data = b"Hello, World!"
        result = _extract_txt(data)
        assert "Hello" in result.text
        assert "World" in result.text

    def test_offsets_length_matches_text(self) -> None:
        data = b"Hello World"
        result = _extract_txt(data)
        assert len(result.byte_offsets) == len(result.text)

    def test_whitespace_normalised(self) -> None:
        data = b"Hello   World\n\nFoo"
        result = _extract_txt(data)
        assert "  " not in result.text
        assert "\n" not in result.text

    def test_latin1_fallback(self) -> None:
        # Bytes that are not valid UTF-8.
        data = b"caf\xe9"
        result = _extract_txt(data)
        assert "caf" in result.text

    def test_empty_bytes(self) -> None:
        result = _extract_txt(b"")
        assert result.text == ""
        assert result.byte_offsets == []

    def test_returns_extraction_result(self) -> None:
        result = _extract_txt(b"text")
        assert isinstance(result, ExtractionResult)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


class TestExtractJson:
    def test_string_values_extracted(self) -> None:
        data = json.dumps({"name": "Alice", "email": "alice@example.com"}).encode()
        result = _extract_json(data)
        assert "Alice" in result.text
        assert "alice@example.com" in result.text

    def test_nested_values_extracted(self) -> None:
        obj = {"outer": {"inner": "deep value"}}
        data = json.dumps(obj).encode()
        result = _extract_json(data)
        assert "deep value" in result.text

    def test_list_values_extracted(self) -> None:
        obj = ["foo", "bar", "baz"]
        data = json.dumps(obj).encode()
        result = _extract_json(data)
        assert "foo" in result.text
        assert "bar" in result.text
        assert "baz" in result.text

    def test_non_string_values_ignored(self) -> None:
        obj = {"count": 42, "active": True, "name": "test"}
        data = json.dumps(obj).encode()
        result = _extract_json(data)
        assert "test" in result.text
        # Numeric/bool values are not collected as text strings.
        assert "42" not in result.text

    def test_offsets_length_matches_text(self) -> None:
        data = json.dumps({"key": "value"}).encode()
        result = _extract_json(data)
        assert len(result.byte_offsets) == len(result.text)

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(ExtractionError) as exc_info:
            _extract_json(b"not json {{{")
        assert exc_info.value.original is not None

    def test_invalid_json_mime_type_set(self) -> None:
        with pytest.raises(ExtractionError) as exc_info:
            _extract_json(b"broken")
        assert exc_info.value.mime_type == "application/json"

    def test_empty_object(self) -> None:
        result = _extract_json(b"{}")
        assert result.text == ""

    def test_nested_list_in_dict(self) -> None:
        obj = {"items": ["alpha", "beta"]}
        result = _extract_json(json.dumps(obj).encode())
        assert "alpha" in result.text
        assert "beta" in result.text


# ---------------------------------------------------------------------------
# CSV extraction
# ---------------------------------------------------------------------------


class TestExtractCsv:
    def test_basic_csv_extracted(self) -> None:
        data = b"name,email\nAlice,alice@example.com\nBob,bob@example.com\n"
        result = _extract_csv(data)
        assert "Alice" in result.text
        assert "alice@example.com" in result.text
        assert "Bob" in result.text

    def test_headers_included(self) -> None:
        data = b"name,email\nAlice,alice@example.com\n"
        result = _extract_csv(data)
        assert "name" in result.text
        assert "email" in result.text

    def test_offsets_length_matches_text(self) -> None:
        data = b"a,b\n1,2\n"
        result = _extract_csv(data)
        assert len(result.byte_offsets) == len(result.text)

    def test_empty_csv(self) -> None:
        result = _extract_csv(b"")
        assert result.text == ""

    def test_whitespace_normalised(self) -> None:
        data = b"field one,field   two\n"
        result = _extract_csv(data)
        assert "  " not in result.text

    def test_returns_extraction_result(self) -> None:
        result = _extract_csv(b"col\nval\n")
        assert isinstance(result, ExtractionResult)


# ---------------------------------------------------------------------------
# PDF extraction (pdfminer patched at module level)
# ---------------------------------------------------------------------------


class TestExtractPdf:
    """Tests for _extract_pdf with pdfminer mocked at module level."""

    def _mock_page(self, text: str) -> MagicMock:
        """Build a page-layout mock whose elements have get_text()."""
        elem = MagicMock()
        elem.get_text.return_value = text
        page = MagicMock()
        page.__iter__ = MagicMock(return_value=iter([elem]))
        return page

    def test_text_extracted_from_pages(self) -> None:
        page = self._mock_page("Hello PDF world")
        with patch("fileguard.core.document_extractor._pdfminer_extract_pages",
                   return_value=[page]), \
             patch("fileguard.core.document_extractor._PDFMINER_AVAILABLE", True):
            from fileguard.core.document_extractor import _extract_pdf
            result = _extract_pdf(b"%PDF-1.4 fake")
        assert "Hello PDF world" in result.text

    def test_multi_page_text_concatenated(self) -> None:
        page1 = self._mock_page("First page")
        page2 = self._mock_page("Second page")
        with patch("fileguard.core.document_extractor._pdfminer_extract_pages",
                   return_value=[page1, page2]), \
             patch("fileguard.core.document_extractor._PDFMINER_AVAILABLE", True):
            from fileguard.core.document_extractor import _extract_pdf
            result = _extract_pdf(b"%PDF-1.4 fake")
        assert "First page" in result.text
        assert "Second page" in result.text

    def test_offsets_length_matches_text(self) -> None:
        page = self._mock_page("Some page text here")
        with patch("fileguard.core.document_extractor._pdfminer_extract_pages",
                   return_value=[page]), \
             patch("fileguard.core.document_extractor._PDFMINER_AVAILABLE", True):
            from fileguard.core.document_extractor import _extract_pdf
            result = _extract_pdf(b"%PDF-1.4 fake")
        assert len(result.byte_offsets) == len(result.text)

    def test_corrupt_pdf_raises(self) -> None:
        with patch("fileguard.core.document_extractor._pdfminer_extract_pages",
                   side_effect=Exception("PDF parse error")), \
             patch("fileguard.core.document_extractor._PDFMINER_AVAILABLE", True):
            from fileguard.core.document_extractor import _extract_pdf
            with pytest.raises(ExtractionError) as exc_info:
                _extract_pdf(b"not a pdf")
        assert exc_info.value.original is not None

    def test_unavailable_pdfminer_raises(self) -> None:
        with patch("fileguard.core.document_extractor._PDFMINER_AVAILABLE", False), \
             patch("fileguard.core.document_extractor._pdfminer_extract_pages", None):
            from fileguard.core.document_extractor import _extract_pdf
            with pytest.raises(ExtractionError) as exc_info:
                _extract_pdf(b"data")
        assert exc_info.value.mime_type == "application/pdf"

    def test_empty_pages_produce_empty_text(self) -> None:
        with patch("fileguard.core.document_extractor._pdfminer_extract_pages",
                   return_value=[]), \
             patch("fileguard.core.document_extractor._PDFMINER_AVAILABLE", True):
            from fileguard.core.document_extractor import _extract_pdf
            result = _extract_pdf(b"%PDF")
        assert result.text == ""
        assert result.byte_offsets == []


# ---------------------------------------------------------------------------
# DOCX extraction (python-docx patched at module level)
# ---------------------------------------------------------------------------


class TestExtractDocx:
    def _mock_doc(self, paragraphs: list[str]) -> MagicMock:
        para_mocks = []
        for text in paragraphs:
            p = MagicMock()
            p.text = text
            para_mocks.append(p)
        doc = MagicMock()
        doc.paragraphs = para_mocks
        return doc

    def test_paragraphs_concatenated(self) -> None:
        doc = self._mock_doc(["Hello", "World", "Paragraph three"])
        with patch("fileguard.core.document_extractor._docx_module") as mock_mod, \
             patch("fileguard.core.document_extractor._DOCX_AVAILABLE", True):
            mock_mod.Document.return_value = doc
            from fileguard.core.document_extractor import _extract_docx
            result = _extract_docx(b"fake docx bytes")
        assert "Hello" in result.text
        assert "World" in result.text
        assert "Paragraph three" in result.text

    def test_offsets_length_matches_text(self) -> None:
        doc = self._mock_doc(["Some text in paragraph"])
        with patch("fileguard.core.document_extractor._docx_module") as mock_mod, \
             patch("fileguard.core.document_extractor._DOCX_AVAILABLE", True):
            mock_mod.Document.return_value = doc
            from fileguard.core.document_extractor import _extract_docx
            result = _extract_docx(b"fake docx bytes")
        assert len(result.byte_offsets) == len(result.text)

    def test_corrupt_docx_raises(self) -> None:
        with patch("fileguard.core.document_extractor._docx_module") as mock_mod, \
             patch("fileguard.core.document_extractor._DOCX_AVAILABLE", True):
            mock_mod.Document.side_effect = Exception("bad zip")
            from fileguard.core.document_extractor import _extract_docx
            with pytest.raises(ExtractionError) as exc_info:
                _extract_docx(b"not a docx")
        assert exc_info.value.original is not None

    def test_empty_paragraphs_skipped(self) -> None:
        doc = self._mock_doc(["", "   ", "Real content"])
        with patch("fileguard.core.document_extractor._docx_module") as mock_mod, \
             patch("fileguard.core.document_extractor._DOCX_AVAILABLE", True):
            mock_mod.Document.return_value = doc
            from fileguard.core.document_extractor import _extract_docx
            result = _extract_docx(b"fake docx bytes")
        assert "Real content" in result.text

    def test_unavailable_docx_raises(self) -> None:
        with patch("fileguard.core.document_extractor._DOCX_AVAILABLE", False), \
             patch("fileguard.core.document_extractor._docx_module", None):
            from fileguard.core.document_extractor import _extract_docx
            with pytest.raises(ExtractionError) as exc_info:
                _extract_docx(b"data")
        assert "wordprocessingml" in (exc_info.value.mime_type or "")


# ---------------------------------------------------------------------------
# ZIP extraction
# ---------------------------------------------------------------------------


class TestExtractZip:
    def test_txt_member_extracted(self) -> None:
        data = _make_zip({"file.txt": b"Hello from ZIP"})
        result = _extract_zip(data)
        assert "Hello from ZIP" in result.text

    def test_json_member_extracted(self) -> None:
        payload = json.dumps({"msg": "from json in zip"}).encode()
        data = _make_zip({"data.json": payload})
        result = _extract_zip(data)
        assert "from json in zip" in result.text

    def test_csv_member_extracted(self) -> None:
        payload = b"name,value\nfoo,bar\n"
        data = _make_zip({"data.csv": payload})
        result = _extract_zip(data)
        assert "foo" in result.text or "bar" in result.text

    def test_multiple_members_concatenated(self) -> None:
        data = _make_zip({
            "a.txt": b"first file",
            "b.txt": b"second file",
        })
        result = _extract_zip(data)
        assert "first" in result.text
        assert "second" in result.text

    def test_nested_zip_extracted(self) -> None:
        """One level of nesting (depth=0 → depth=1) must be processed."""
        inner = _make_zip({"inner.txt": b"nested content"})
        outer = _make_zip({"inner.zip": inner})
        result = _extract_zip(outer)
        assert "nested content" in result.text

    def test_offsets_length_matches_text(self) -> None:
        data = _make_zip({"file.txt": b"Some text inside a ZIP archive"})
        result = _extract_zip(data)
        assert len(result.byte_offsets) == len(result.text)

    def test_corrupt_zip_raises(self) -> None:
        with pytest.raises(ExtractionError) as exc_info:
            _extract_zip(b"not a zip file at all")
        err_str = str(exc_info.value).lower()
        assert "corrupt" in err_str or "zip" in err_str

    def test_depth_limit_raises(self) -> None:
        """Recursion at depth >= _MAX_ZIP_DEPTH must raise ExtractionError.

        With _MAX_ZIP_DEPTH=2, processing starts at depth=0.
        A ZIP two levels deep (outer → inner) processes inner at depth=1.
        A ZIP three levels deep (outer → inner → inner2) tries to process
        inner2 at depth=2 which equals _MAX_ZIP_DEPTH, triggering the limit.
        """
        inner2 = _make_zip({"deep.txt": b"too deep"})
        inner1 = _make_zip({"inner2.zip": inner2})
        outer = _make_zip({"inner1.zip": inner1})
        # The error is caught per-member and logged, so the outer call
        # returns successfully but with empty text (inner ZIP failed).
        # Alternatively, if all members fail we get an empty result.
        # We verify the depth error IS raised internally, but since _extract_zip
        # catches and logs member errors gracefully, the outer call won't re-raise.
        # Instead, verify the inner call raises when called directly at depth limit.
        with pytest.raises(ExtractionError) as exc_info:
            _extract_zip(inner2, depth=_MAX_ZIP_DEPTH)
        err_str = str(exc_info.value).lower()
        assert "depth" in err_str or "limit" in err_str

    def test_member_count_limit_raises(self) -> None:
        members = {f"file_{i}.txt": b"x" for i in range(_MAX_ZIP_FILE_COUNT + 1)}
        data = _make_zip(members)
        with pytest.raises(ExtractionError) as exc_info:
            _extract_zip(data)
        err_str = str(exc_info.value).lower()
        assert "member count" in err_str or "limit" in err_str

    def test_directories_skipped(self) -> None:
        """Directory entries in a ZIP should not cause errors."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # Create a directory entry manually.
            info = zipfile.ZipInfo("subdir/")
            zf.writestr(info, "")
            zf.writestr("subdir/file.txt", "contents")
        result = _extract_zip(buf.getvalue())
        assert "contents" in result.text

    def test_unsupported_member_type_skipped(self) -> None:
        """Members with unknown extensions are skipped gracefully."""
        data = _make_zip({
            "binary.xyz": b"\x00\x01\x02binary",
            "text.txt": b"readable text",
        })
        result = _extract_zip(data)
        assert "readable text" in result.text

    def test_returns_extraction_result(self) -> None:
        data = _make_zip({"f.txt": b"hello"})
        result = _extract_zip(data)
        assert isinstance(result, ExtractionResult)

    def test_empty_zip_returns_empty_text(self) -> None:
        data = _make_zip({})
        result = _extract_zip(data)
        assert result.text == ""


# ---------------------------------------------------------------------------
# _dispatch_sync — unsupported types and routing
# ---------------------------------------------------------------------------


class TestDispatchSync:
    def test_unsupported_mime_raises(self) -> None:
        with pytest.raises(ExtractionError) as exc_info:
            _dispatch_sync(b"data", "image/png")
        assert "Unsupported" in str(exc_info.value)
        assert exc_info.value.mime_type == "image/png"

    def test_mime_params_stripped(self) -> None:
        # "text/plain; charset=utf-8" should resolve to TXT handler.
        result = _dispatch_sync(b"hello world", "text/plain; charset=utf-8")
        assert "hello" in result.text

    def test_json_mime_dispatched(self) -> None:
        result = _dispatch_sync(b'{"k": "v"}', "application/json")
        assert "v" in result.text

    def test_csv_mime_dispatched(self) -> None:
        result = _dispatch_sync(b"a,b\n1,2\n", "text/csv")
        assert isinstance(result, ExtractionResult)

    def test_txt_mime_dispatched(self) -> None:
        result = _dispatch_sync(b"plain text", "text/plain")
        assert "plain text" in result.text

    def test_zip_mime_dispatched(self) -> None:
        data = _make_zip({"f.txt": b"zip content"})
        result = _dispatch_sync(data, "application/zip")
        assert "zip content" in result.text

    def test_application_csv_alias(self) -> None:
        result = _dispatch_sync(b"col\nval\n", "application/csv")
        assert isinstance(result, ExtractionResult)

    def test_text_json_alias(self) -> None:
        result = _dispatch_sync(b'{"x": "y"}', "text/json")
        assert "y" in result.text

    def test_pdf_mime_dispatched(self) -> None:
        page = MagicMock()
        elem = MagicMock()
        elem.get_text.return_value = "pdf text"
        page.__iter__ = MagicMock(return_value=iter([elem]))
        with patch("fileguard.core.document_extractor._pdfminer_extract_pages",
                   return_value=[page]), \
             patch("fileguard.core.document_extractor._PDFMINER_AVAILABLE", True):
            result = _dispatch_sync(b"%PDF", "application/pdf")
        assert isinstance(result, ExtractionResult)


# ---------------------------------------------------------------------------
# DocumentExtractor (async, thread-pool dispatch)
# ---------------------------------------------------------------------------


class TestDocumentExtractor:
    @pytest.mark.asyncio
    async def test_extract_txt(self) -> None:
        extractor = DocumentExtractor(max_workers=1)
        result = await extractor.extract(b"hello world", "text/plain")
        assert "hello world" in result.text
        extractor.shutdown()

    @pytest.mark.asyncio
    async def test_extract_json(self) -> None:
        data = json.dumps({"greeting": "hello"}).encode()
        extractor = DocumentExtractor(max_workers=1)
        result = await extractor.extract(data, "application/json")
        assert "hello" in result.text
        extractor.shutdown()

    @pytest.mark.asyncio
    async def test_extract_csv(self) -> None:
        data = b"col1,col2\nval1,val2\n"
        extractor = DocumentExtractor(max_workers=1)
        result = await extractor.extract(data, "text/csv")
        assert "val1" in result.text
        extractor.shutdown()

    @pytest.mark.asyncio
    async def test_extract_zip(self) -> None:
        data = _make_zip({"notes.txt": b"zip extraction test"})
        extractor = DocumentExtractor(max_workers=1)
        result = await extractor.extract(data, "application/zip")
        assert "zip extraction test" in result.text
        extractor.shutdown()

    @pytest.mark.asyncio
    async def test_offsets_parallel_to_text(self) -> None:
        extractor = DocumentExtractor(max_workers=1)
        result = await extractor.extract(b"testing offsets", "text/plain")
        assert len(result.byte_offsets) == len(result.text)
        extractor.shutdown()

    @pytest.mark.asyncio
    async def test_unsupported_mime_raises_extraction_error(self) -> None:
        extractor = DocumentExtractor(max_workers=1)
        with pytest.raises(ExtractionError):
            await extractor.extract(b"bytes", "video/mp4")
        extractor.shutdown()

    @pytest.mark.asyncio
    async def test_uses_provided_executor(self) -> None:
        """When an executor is injected, it must be used for dispatch."""
        real_executor = ThreadPoolExecutor(max_workers=1)
        extractor = DocumentExtractor(executor=real_executor)
        result = await extractor.extract(b"injected executor", "text/plain")
        assert "injected executor" in result.text
        real_executor.shutdown()

    @pytest.mark.asyncio
    async def test_does_not_shut_down_injected_executor(self) -> None:
        """DocumentExtractor must not own an injected executor."""
        pool = ThreadPoolExecutor(max_workers=1)
        extractor = DocumentExtractor(executor=pool)
        extractor.shutdown()
        # Pool should still be usable after extractor.shutdown().
        future = pool.submit(lambda: 42)
        assert future.result() == 42
        pool.shutdown()

    def test_context_manager_shuts_down_pool(self) -> None:
        with DocumentExtractor(max_workers=1) as extractor:
            assert extractor is not None
        # Executor should be shut down after exiting the context.
        with pytest.raises(RuntimeError):
            extractor._executor.submit(lambda: None)

    @pytest.mark.asyncio
    async def test_extraction_runs_in_worker_thread(self) -> None:
        """Verify extraction is dispatched to a background thread."""
        import threading

        main_thread = threading.current_thread()
        extraction_threads: list[threading.Thread] = []

        def patched_dispatch(data: bytes, mime: str) -> ExtractionResult:
            extraction_threads.append(threading.current_thread())
            return ExtractionResult(text="patched", byte_offsets=[0] * 7)

        with patch(
            "fileguard.core.document_extractor._dispatch_sync",
            side_effect=patched_dispatch,
        ):
            extractor = DocumentExtractor(max_workers=1)
            await extractor.extract(b"fake", "text/plain")
            extractor.shutdown()

        assert len(extraction_threads) == 1
        # Extraction must NOT have run on the main (event loop) thread.
        assert extraction_threads[0] is not main_thread

    @pytest.mark.asyncio
    async def test_extraction_result_has_correct_structure(self) -> None:
        extractor = DocumentExtractor(max_workers=1)
        result = await extractor.extract(b"structured result", "text/plain")
        assert isinstance(result, ExtractionResult)
        assert isinstance(result.text, str)
        assert isinstance(result.byte_offsets, list)
        extractor.shutdown()

    @pytest.mark.asyncio
    async def test_extract_pdf_via_dispatcher(self) -> None:
        page = MagicMock()
        elem = MagicMock()
        elem.get_text.return_value = "async pdf content"
        page.__iter__ = MagicMock(return_value=iter([elem]))
        with patch("fileguard.core.document_extractor._pdfminer_extract_pages",
                   return_value=[page]), \
             patch("fileguard.core.document_extractor._PDFMINER_AVAILABLE", True):
            extractor = DocumentExtractor(max_workers=1)
            result = await extractor.extract(b"%PDF-1.4 fake", "application/pdf")
            extractor.shutdown()
        assert "async pdf content" in result.text
