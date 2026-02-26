"""Unit tests for RedactionEngine and RedactedFileStorage.

Coverage:
* RedactionEngine.redact()
  - Zero findings → text returned unchanged
  - Single PII span redacted correctly
  - Multiple non-overlapping spans each redacted
  - Overlapping spans merged and redacted as one
  - Adjacent (touching) spans merged
  - Byte-offset reverse-map used when offset != -1
  - Substring fallback when offset == -1 or byte_offsets is empty
  - Redacted output preserves non-PII content exactly
  - Empty extracted_text → empty string returned (no-op)
  - None extracted_text → empty string returned (no-op)
  - Non-PII findings in context are ignored
  - ScanContext integration: context.findings consumed, context unchanged otherwise

* RedactedFileStorage
  - store_and_sign() writes a file and returns a valid signed URL
  - verify_signature() returns True for a fresh URL
  - verify_signature() returns False when the URL has expired
  - verify_signature() returns False when the HMAC is tampered
  - retrieve() returns the stored bytes
  - retrieve() returns None for unknown file_id
  - URL contains expected query parameters (expires, sig)
  - TTL is honoured: URL expires after configured seconds
  - Path traversal characters are stripped from file_id in storage

* Integration scenario (signed URL round-trip)
  - Store redacted content → parse signed URL → verify → retrieve → check content
"""

from __future__ import annotations

import re
import time
import uuid
from unittest.mock import patch

import pytest

from fileguard.core.redaction import REDACTED_TOKEN, RedactionEngine
from fileguard.core.scan_context import ScanContext
from fileguard.services.storage import RedactedFileStorage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_finding(match: str, offset: int = -1):
    """Create a minimal PII-like finding object for tests."""
    from types import SimpleNamespace
    return SimpleNamespace(type="pii", category="TEST", severity="high", match=match, offset=offset)


def _make_ctx(
    text: str | None,
    byte_offsets: list[int] | None = None,
) -> ScanContext:
    ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
    ctx.extracted_text = text
    if byte_offsets is not None:
        ctx.byte_offsets = byte_offsets
    return ctx


# ---------------------------------------------------------------------------
# RedactionEngine — zero findings
# ---------------------------------------------------------------------------


class TestRedactNoFindings:
    def test_empty_findings_returns_text_unchanged(self):
        engine = RedactionEngine()
        ctx = _make_ctx("hello world")
        assert engine.redact(ctx) == "hello world"

    def test_non_pii_findings_are_ignored(self):
        from types import SimpleNamespace

        engine = RedactionEngine()
        ctx = _make_ctx("hello world")
        ctx.findings = [
            SimpleNamespace(type="av_threat", category="EICAR", severity="critical",
                            match="hello", offset=0)
        ]
        assert engine.redact(ctx) == "hello world"

    def test_empty_text_returns_empty_string(self):
        engine = RedactionEngine()
        ctx = _make_ctx("")
        assert engine.redact(ctx) == ""

    def test_none_text_returns_empty_string(self):
        engine = RedactionEngine()
        ctx = _make_ctx(None)
        assert engine.redact(ctx) == ""


# ---------------------------------------------------------------------------
# RedactionEngine — single span
# ---------------------------------------------------------------------------


class TestRedactSingleSpan:
    def test_single_match_replaced_with_token(self):
        engine = RedactionEngine()
        text = "NI: AB123456C is sensitive"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [_make_finding("AB123456C", offset=4)]
        result = engine.redact(ctx)
        assert REDACTED_TOKEN in result
        assert "AB123456C" not in result
        assert result.startswith("NI: ")
        assert result.endswith(" is sensitive")

    def test_leading_match_replaced(self):
        engine = RedactionEngine()
        text = "AB123456C is sensitive"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [_make_finding("AB123456C", offset=0)]
        result = engine.redact(ctx)
        assert result.startswith(REDACTED_TOKEN)
        assert "AB123456C" not in result

    def test_trailing_match_replaced(self):
        engine = RedactionEngine()
        text = "Contact: alice@example.com"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [_make_finding("alice@example.com", offset=9)]
        result = engine.redact(ctx)
        assert result.endswith(REDACTED_TOKEN)
        assert "alice@example.com" not in result

    def test_non_pii_content_preserved_exactly(self):
        engine = RedactionEngine()
        text = "Name: John, NI: AB123456C, DOB: 01-01-1990"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [_make_finding("AB123456C", offset=16)]
        result = engine.redact(ctx)
        expected = f"Name: John, NI: {REDACTED_TOKEN}, DOB: 01-01-1990"
        assert result == expected


# ---------------------------------------------------------------------------
# RedactionEngine — multiple non-overlapping spans
# ---------------------------------------------------------------------------


class TestRedactMultipleSpans:
    def test_two_non_overlapping_spans_both_redacted(self):
        engine = RedactionEngine()
        text = "NI: AB123456C, email: alice@example.com"
        ctx = _make_ctx(text, list(range(len(text))))
        ni_offset = text.index("AB123456C")
        email_offset = text.index("alice@example.com")
        ctx.findings = [
            _make_finding("AB123456C", offset=ni_offset),
            _make_finding("alice@example.com", offset=email_offset),
        ]
        result = engine.redact(ctx)
        assert "AB123456C" not in result
        assert "alice@example.com" not in result
        assert result.count(REDACTED_TOKEN) == 2

    def test_order_of_findings_does_not_matter(self):
        engine = RedactionEngine()
        text = "a@b.com and c@d.com are both PII"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [
            _make_finding("c@d.com", offset=text.index("c@d.com")),
            _make_finding("a@b.com", offset=text.index("a@b.com")),
        ]
        result = engine.redact(ctx)
        assert "a@b.com" not in result
        assert "c@d.com" not in result
        assert result.count(REDACTED_TOKEN) == 2

    def test_surrounding_text_preserved(self):
        engine = RedactionEngine()
        text = "prefix MATCH1 middle MATCH2 suffix"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [
            _make_finding("MATCH1", offset=text.index("MATCH1")),
            _make_finding("MATCH2", offset=text.index("MATCH2")),
        ]
        result = engine.redact(ctx)
        assert "prefix" in result
        assert "middle" in result
        assert "suffix" in result


# ---------------------------------------------------------------------------
# RedactionEngine — overlapping and adjacent spans
# ---------------------------------------------------------------------------


class TestRedactOverlappingSpans:
    """Acceptance criterion: overlapping spans are merged before substitution."""

    def test_overlapping_spans_merged_into_one(self):
        # Simulate two patterns that both match in the range [0, 5)
        engine = RedactionEngine()
        text = "SECRET_DATA extra"
        ctx = _make_ctx(text, list(range(len(text))))
        # Both findings match the same range
        ctx.findings = [
            _make_finding("SECRET", offset=0),
            _make_finding("SECRE", offset=0),
        ]
        result = engine.redact(ctx)
        # Only one [REDACTED] token should appear (merged)
        assert result.count(REDACTED_TOKEN) == 1
        # Neither match string should remain
        assert "SECRET" not in result

    def test_adjacent_spans_merged(self):
        # Span1 ends where Span2 begins (touching)
        engine = RedactionEngine()
        text = "AABB extra"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [
            _make_finding("AA", offset=0),
            _make_finding("BB", offset=2),  # starts exactly where AA ends
        ]
        result = engine.redact(ctx)
        # Should be treated as a single merged span covering "AABB"
        assert result.count(REDACTED_TOKEN) == 1
        assert "AABB" not in result

    def test_non_overlapping_spans_produce_separate_tokens(self):
        engine = RedactionEngine()
        text = "AA xx BB"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [
            _make_finding("AA", offset=0),
            _make_finding("BB", offset=6),
        ]
        result = engine.redact(ctx)
        assert result.count(REDACTED_TOKEN) == 2


# ---------------------------------------------------------------------------
# RedactionEngine — byte-offset mapping
# ---------------------------------------------------------------------------


class TestByteOffsetMapping:
    def test_byte_offset_used_for_span_location(self):
        """When byte_offsets is correct, span is found via reverse map."""
        engine = RedactionEngine()
        text = "prefix MATCH suffix"
        # Identity mapping: char_idx == byte_offset
        byte_offsets = list(range(len(text)))
        ctx = _make_ctx(text, byte_offsets)
        match_char_idx = text.index("MATCH")
        ctx.findings = [_make_finding("MATCH", offset=match_char_idx)]
        result = engine.redact(ctx)
        assert "MATCH" not in result
        assert REDACTED_TOKEN in result

    def test_fallback_to_substring_search_when_offset_minus_one(self):
        """offset=-1 triggers substring search instead of reverse map lookup."""
        engine = RedactionEngine()
        text = "prefix MATCH suffix"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [_make_finding("MATCH", offset=-1)]
        result = engine.redact(ctx)
        assert "MATCH" not in result
        assert REDACTED_TOKEN in result

    def test_fallback_when_byte_offsets_empty(self):
        """Empty byte_offsets → reverse map empty → substring search used."""
        engine = RedactionEngine()
        text = "Call 07700 900123 now"
        ctx = _make_ctx(text, [])
        ctx.findings = [_make_finding("07700 900123", offset=5)]
        result = engine.redact(ctx)
        assert "07700 900123" not in result
        assert REDACTED_TOKEN in result

    def test_byte_offset_mismatch_falls_back_to_search(self):
        """If byte-offset map gives wrong char position, search fallback is used."""
        engine = RedactionEngine()
        text = "hello world"
        # Deliberately wrong byte_offsets (all zeros)
        ctx = _make_ctx(text, [0] * len(text))
        ctx.findings = [_make_finding("world", offset=6)]
        result = engine.redact(ctx)
        # Should still find and redact "world" via substring search
        assert "world" not in result
        assert REDACTED_TOKEN in result


# ---------------------------------------------------------------------------
# RedactionEngine._merge_spans internals
# ---------------------------------------------------------------------------


class TestMergeSpans:
    engine = RedactionEngine()

    def test_empty_input_returns_empty(self):
        assert self.engine._merge_spans([]) == []

    def test_single_span_unchanged(self):
        assert self.engine._merge_spans([(3, 7)]) == [(3, 7)]

    def test_non_overlapping_sorted(self):
        result = self.engine._merge_spans([(0, 3), (5, 8)])
        assert result == [(0, 3), (5, 8)]

    def test_overlapping_merged(self):
        result = self.engine._merge_spans([(0, 5), (3, 9)])
        assert result == [(0, 9)]

    def test_adjacent_merged(self):
        result = self.engine._merge_spans([(0, 3), (3, 6)])
        assert result == [(0, 6)]

    def test_unsorted_input_sorted_and_merged(self):
        result = self.engine._merge_spans([(5, 9), (0, 3), (2, 6)])
        assert result == [(0, 9)]

    def test_completely_contained_span_merged(self):
        result = self.engine._merge_spans([(0, 10), (2, 5)])
        assert result == [(0, 10)]


# ---------------------------------------------------------------------------
# ScanContext integration
# ---------------------------------------------------------------------------


class TestScanContextIntegration:
    def test_scan_id_unchanged_after_redact(self):
        engine = RedactionEngine()
        ctx = _make_ctx("test text")
        original_id = ctx.scan_id
        engine.redact(ctx)
        assert ctx.scan_id == original_id

    def test_findings_list_not_modified(self):
        engine = RedactionEngine()
        text = "AB123456C"
        ctx = _make_ctx(text, list(range(len(text))))
        ctx.findings = [_make_finding("AB123456C", offset=0)]
        original_findings = list(ctx.findings)
        engine.redact(ctx)
        assert ctx.findings == original_findings

    def test_request_redaction_flag_accessible(self):
        ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
        assert ctx.request_redaction is False
        ctx.request_redaction = True
        assert ctx.request_redaction is True

    def test_redacted_file_url_initially_none(self):
        ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
        assert ctx.redacted_file_url is None

    def test_redacted_file_url_can_be_set(self):
        ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
        ctx.redacted_file_url = "https://example.com/v1/redacted/abc?expires=1&sig=xyz"
        assert ctx.redacted_file_url is not None


# ---------------------------------------------------------------------------
# RedactedFileStorage — basic operations
# ---------------------------------------------------------------------------


class TestRedactedFileStorageBasic:
    def _make_storage(self, tmp_path, ttl: int = 3600) -> RedactedFileStorage:
        return RedactedFileStorage(
            base_url="http://localhost:8000",
            storage_dir=str(tmp_path),
            secret_key="test-secret-key-32-chars-xxxxxxxxx",
        )

    def test_store_and_sign_returns_url_string(self, tmp_path):
        storage = self._make_storage(tmp_path)
        url = storage.store_and_sign("redacted content", scan_id="scan-abc")
        assert isinstance(url, str)
        assert url.startswith("http://localhost:8000/v1/redacted/")

    def test_url_contains_expires_parameter(self, tmp_path):
        storage = self._make_storage(tmp_path)
        url = storage.store_and_sign("content", scan_id="scan-abc")
        assert "expires=" in url

    def test_url_contains_sig_parameter(self, tmp_path):
        storage = self._make_storage(tmp_path)
        url = storage.store_and_sign("content", scan_id="scan-abc")
        assert "sig=" in url

    def test_retrieve_returns_stored_content(self, tmp_path):
        storage = self._make_storage(tmp_path)
        content = "Patient NI: [REDACTED], email: [REDACTED]"
        url = storage.store_and_sign(content, scan_id="scan-123")

        # Extract file_id from the URL
        path_part = url.split("?")[0]
        file_id = path_part.split("/v1/redacted/")[1]

        retrieved = storage.retrieve(file_id)
        assert retrieved is not None
        assert retrieved.decode("utf-8") == content

    def test_retrieve_returns_none_for_unknown_id(self, tmp_path):
        storage = self._make_storage(tmp_path)
        assert storage.retrieve("nonexistent-id") is None


# ---------------------------------------------------------------------------
# RedactedFileStorage — signature verification
# ---------------------------------------------------------------------------


class TestRedactedFileStorageVerification:
    def _make_storage(self, tmp_path) -> RedactedFileStorage:
        return RedactedFileStorage(
            base_url="http://localhost:8000",
            storage_dir=str(tmp_path),
            secret_key="test-secret-key-32-chars-xxxxxxxxx",
        )

    def test_fresh_url_signature_valid(self, tmp_path):
        storage = self._make_storage(tmp_path)
        url = storage.store_and_sign("content", scan_id="scan-xyz")
        # Parse URL parameters
        from urllib.parse import parse_qs, urlsplit
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        file_id = parsed.path.split("/v1/redacted/")[1]
        expires = int(params["expires"][0])
        sig = params["sig"][0]

        assert storage.verify_signature(file_id, expires, sig) is True

    def test_expired_url_rejected(self, tmp_path):
        storage = self._make_storage(tmp_path)
        file_id = "test-file-id"
        # Set expiry in the past
        past_expires = int(time.time()) - 1
        sig = storage._sign(file_id, past_expires)
        assert storage.verify_signature(file_id, past_expires, sig) is False

    def test_tampered_sig_rejected(self, tmp_path):
        storage = self._make_storage(tmp_path)
        url = storage.store_and_sign("content", scan_id="scan-xyz")
        from urllib.parse import parse_qs, urlsplit
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        file_id = parsed.path.split("/v1/redacted/")[1]
        expires = int(params["expires"][0])
        assert storage.verify_signature(file_id, expires, "deadbeef" * 8) is False

    def test_tampered_file_id_rejected(self, tmp_path):
        storage = self._make_storage(tmp_path)
        url = storage.store_and_sign("content", scan_id="scan-xyz")
        from urllib.parse import parse_qs, urlsplit
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        file_id = parsed.path.split("/v1/redacted/")[1]
        expires = int(params["expires"][0])
        sig = params["sig"][0]
        # Tamper with file_id
        assert storage.verify_signature(file_id + "-tampered", expires, sig) is False

    def test_custom_ttl_honoured(self, tmp_path):
        storage = self._make_storage(tmp_path)
        ttl = 7200
        url = storage.store_and_sign("content", scan_id="scan-abc", ttl_seconds=ttl)
        from urllib.parse import parse_qs, urlsplit
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)
        expires = int(params["expires"][0])
        # expires should be approximately now + ttl
        now = int(time.time())
        assert now + ttl - 5 <= expires <= now + ttl + 5


# ---------------------------------------------------------------------------
# RedactedFileStorage — path traversal safety
# ---------------------------------------------------------------------------


class TestRedactedFileStoragePathSafety:
    def test_path_traversal_chars_stripped_from_file_id(self, tmp_path):
        storage = RedactedFileStorage(
            base_url="http://localhost:8000",
            storage_dir=str(tmp_path),
            secret_key="test-secret",
        )
        malicious_id = "../../etc/passwd"
        # _file_path should sanitise the id
        path = storage._file_path(malicious_id)
        # The resulting path must be inside storage_dir
        import os
        assert os.path.commonpath([str(tmp_path), path]) == str(tmp_path)
        # And must not contain ..
        assert ".." not in path


# ---------------------------------------------------------------------------
# Integration: signed URL round-trip
# ---------------------------------------------------------------------------


class TestSignedUrlRoundTrip:
    """Integration test: content stored → URL parsed → verified → retrieved.

    This confirms the acceptance criterion:
    'Integration test confirms URL resolves to content where all PII spans
    are replaced with [REDACTED]'
    """

    def test_redacted_content_stored_and_retrievable(self, tmp_path):
        # Step 1: Simulate PII detection on extracted text
        original_text = (
            "Patient: John Smith, NI AB123456C, "
            "email john@nhs.uk, phone 07700 900123"
        )
        ctx = ScanContext(file_bytes=b"", mime_type="text/plain")
        ctx.extracted_text = original_text
        ctx.byte_offsets = list(range(len(original_text)))
        ctx.request_redaction = True

        # Step 2: Redact PII spans
        ni_offset = original_text.index("AB123456C")
        email_offset = original_text.index("john@nhs.uk")
        phone_offset = original_text.index("07700 900123")
        ctx.findings = [
            _make_finding("AB123456C", offset=ni_offset),
            _make_finding("john@nhs.uk", offset=email_offset),
            _make_finding("07700 900123", offset=phone_offset),
        ]

        engine = RedactionEngine()
        redacted_text = engine.redact(ctx)

        # Confirm all PII is replaced
        assert "AB123456C" not in redacted_text
        assert "john@nhs.uk" not in redacted_text
        assert "07700 900123" not in redacted_text
        assert redacted_text.count(REDACTED_TOKEN) == 3

        # Step 3: Store and sign
        storage = RedactedFileStorage(
            base_url="http://localhost:8000",
            storage_dir=str(tmp_path),
            secret_key="test-secret-key-for-integration",
        )
        signed_url = storage.store_and_sign(redacted_text, scan_id=ctx.scan_id)
        ctx.redacted_file_url = signed_url

        # Step 4: Parse the signed URL and verify
        from urllib.parse import parse_qs, urlsplit
        parsed = urlsplit(signed_url)
        params = parse_qs(parsed.query)
        file_id = parsed.path.split("/v1/redacted/")[1]
        expires = int(params["expires"][0])
        sig = params["sig"][0]

        assert storage.verify_signature(file_id, expires, sig) is True

        # Step 5: Retrieve and confirm content matches redacted text
        retrieved = storage.retrieve(file_id)
        assert retrieved is not None
        content = retrieved.decode("utf-8")
        assert content == redacted_text
        assert REDACTED_TOKEN in content
        assert "AB123456C" not in content
        assert "john@nhs.uk" not in content
        assert "07700 900123" not in content
