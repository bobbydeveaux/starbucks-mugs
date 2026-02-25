"""Unit tests for the ClamAV clamd socket adapter.

All tests are fully offline.  The ``clamd.ClamdNetworkSocket`` client is
replaced by :mod:`unittest.mock` patches so no live clamd daemon is required.

Coverage areas:

* ``_categorise_threat`` — threat name normalisation helper.
* ``_parse_clamd_response`` — clamd response dict → (status, findings) parsing,
  including fail-secure handling of ``ERROR`` results.
* ``ClamAVAdapter.scan`` — file path scanning with clean, flagged, and all
  failure modes (connection refused, timeout, clamd error, unexpected exception).
* ``ClamAVAdapter.scan_bytes`` — in-memory stream scanning with the same
  failure-mode coverage.
* ``ClamAVAdapter.ping`` — health-check with successful, failure, and
  unexpected-response scenarios.
* Constructor defaults and ``_get_client`` wiring.
"""

from __future__ import annotations

import socket
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import clamd
import pytest

from fileguard.core.av_engine import Finding, ScanResult
from fileguard.core.clamav_adapter import (
    ClamAVAdapter,
    _categorise_threat,
    _parse_clamd_response,
)


# ---------------------------------------------------------------------------
# _categorise_threat
# ---------------------------------------------------------------------------


def test_categorise_threat_returns_first_two_dot_components() -> None:
    assert _categorise_threat("Win.Test.EICAR_HDB-1") == "Win.Test"


def test_categorise_threat_with_exactly_two_components() -> None:
    assert _categorise_threat("Trojan.Generic") == "Trojan.Generic"


def test_categorise_threat_with_one_component_returns_full_name() -> None:
    assert _categorise_threat("EICAR") == "EICAR"


def test_categorise_threat_with_many_components() -> None:
    # Only first two parts should be returned
    assert _categorise_threat("Win.Trojan.PDF.Downloader.1") == "Win.Trojan"


def test_categorise_threat_with_empty_string() -> None:
    assert _categorise_threat("") == ""


# ---------------------------------------------------------------------------
# _parse_clamd_response
# ---------------------------------------------------------------------------


def test_parse_ok_response_returns_clean_with_no_findings() -> None:
    response: dict[str, tuple[str, str | None]] = {"/tmp/file.pdf": ("OK", None)}
    status, findings = _parse_clamd_response(response)
    assert status == "clean"
    assert findings == []


def test_parse_found_response_returns_flagged() -> None:
    threat = "Win.Test.EICAR_HDB-1"
    response: dict[str, tuple[str, str | None]] = {"/tmp/eicar.txt": ("FOUND", threat)}
    status, findings = _parse_clamd_response(response)
    assert status == "flagged"
    assert len(findings) == 1


def test_parse_found_response_finding_has_correct_fields() -> None:
    threat = "Win.Test.EICAR_HDB-1"
    response: dict[str, tuple[str, str | None]] = {"/tmp/eicar.txt": ("FOUND", threat)}
    _, findings = _parse_clamd_response(response)
    f = findings[0]
    assert f.type == "av_threat"
    assert f.match == threat
    assert f.category == "Win.Test"
    assert f.severity == "high"


def test_parse_found_response_with_stream_key() -> None:
    """instream responses use 'stream' as the key."""
    response: dict[str, tuple[str, str | None]] = {"stream": ("FOUND", "Trojan.PDF.1")}
    status, findings = _parse_clamd_response(response)
    assert status == "flagged"
    assert findings[0].category == "Trojan.PDF"


def test_parse_error_response_returns_rejected_fail_secure() -> None:
    """ERROR from clamd must produce a rejected verdict, never a pass-through."""
    response: dict[str, tuple[str, str | None]] = {
        "/tmp/file.pdf": ("ERROR", "access denied")
    }
    status, findings = _parse_clamd_response(response)
    assert status == "rejected"
    assert findings == []


def test_parse_multiple_findings_from_archive() -> None:
    """Multiple threats detected in a single response."""
    response: dict[str, tuple[str, str | None]] = {
        "/tmp/archive/file1.exe": ("FOUND", "Win.Trojan.1"),
        "/tmp/archive/file2.bat": ("FOUND", "Win.Backdoor.2"),
    }
    status, findings = _parse_clamd_response(response)
    assert status == "flagged"
    assert len(findings) == 2
    assert {f.match for f in findings} == {"Win.Trojan.1", "Win.Backdoor.2"}


def test_parse_mixed_ok_and_found() -> None:
    """If any file is FOUND, overall status is flagged."""
    response: dict[str, tuple[str, str | None]] = {
        "/tmp/file_clean.txt": ("OK", None),
        "/tmp/file_infected.exe": ("FOUND", "Malware.Generic"),
    }
    status, findings = _parse_clamd_response(response)
    assert status == "flagged"
    assert len(findings) == 1


# ---------------------------------------------------------------------------
# ClamAVAdapter constructor and _get_client
# ---------------------------------------------------------------------------


def test_default_constructor_values() -> None:
    adapter = ClamAVAdapter()
    assert adapter._host == "clamav"
    assert adapter._port == 3310
    assert adapter._timeout == 30.0


def test_custom_constructor_values() -> None:
    adapter = ClamAVAdapter(host="192.168.1.1", port=9999, timeout=5.0)
    assert adapter._host == "192.168.1.1"
    assert adapter._port == 9999
    assert adapter._timeout == 5.0


def test_get_client_passes_correct_args_to_clamd() -> None:
    adapter = ClamAVAdapter(host="localhost", port=3310, timeout=10.0)
    with patch("fileguard.core.clamav_adapter.clamd.ClamdNetworkSocket") as mock_cls:
        mock_cls.return_value = MagicMock()
        adapter._get_client()
        mock_cls.assert_called_once_with(host="localhost", port=3310, timeout=10.0)


def test_engine_name_constant() -> None:
    assert ClamAVAdapter.ENGINE_NAME == "clamav"


# ---------------------------------------------------------------------------
# ClamAVAdapter.scan — file path scanning
# ---------------------------------------------------------------------------


async def test_scan_path_clean_file_returns_clean_result() -> None:
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_path",
        return_value={"/tmp/clean.pdf": ("OK", None)},
    ):
        result = await adapter.scan("/tmp/clean.pdf")

    assert result.status == "clean"
    assert result.findings == ()
    assert result.engine == "clamav"
    assert result.duration_ms >= 0


async def test_scan_path_infected_file_returns_flagged() -> None:
    threat = "Win.Test.EICAR_HDB-1"
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_path",
        return_value={"/tmp/eicar.txt": ("FOUND", threat)},
    ):
        result = await adapter.scan("/tmp/eicar.txt")

    assert result.status == "flagged"
    assert len(result.findings) == 1
    assert result.findings[0].match == threat
    assert result.findings[0].type == "av_threat"
    assert result.findings[0].severity == "high"
    assert result.engine == "clamav"


async def test_scan_path_connection_refused_returns_rejected() -> None:
    """Fail-secure: connection refused must return rejected, not raise."""
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_path",
        side_effect=ConnectionRefusedError("Connection refused"),
    ):
        result = await adapter.scan("/tmp/file.pdf")

    assert result.status == "rejected"
    assert result.findings == ()
    assert result.engine == "clamav"


async def test_scan_path_socket_timeout_returns_rejected() -> None:
    """Fail-secure: socket timeout must return rejected."""
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_path",
        side_effect=socket.timeout("timed out"),
    ):
        result = await adapter.scan("/tmp/file.pdf")

    assert result.status == "rejected"
    assert result.findings == ()


async def test_scan_path_clamd_connection_error_returns_rejected() -> None:
    """Fail-secure: clamd.ConnectionError must return rejected."""
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_path",
        side_effect=clamd.ConnectionError("clamd unavailable"),
    ):
        result = await adapter.scan("/tmp/file.pdf")

    assert result.status == "rejected"
    assert result.findings == ()


async def test_scan_path_unexpected_exception_returns_rejected() -> None:
    """Fail-secure: any unexpected exception must return rejected."""
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_path",
        side_effect=RuntimeError("unexpected internal error"),
    ):
        result = await adapter.scan("/tmp/file.pdf")

    assert result.status == "rejected"
    assert result.findings == ()
    assert result.engine == "clamav"


async def test_scan_path_clamd_error_response_returns_rejected() -> None:
    """Fail-secure: ERROR result in clamd response returns rejected."""
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_path",
        return_value={"/tmp/file.pdf": ("ERROR", "permission denied")},
    ):
        result = await adapter.scan("/tmp/file.pdf")

    assert result.status == "rejected"
    assert result.findings == ()


async def test_scan_path_result_includes_duration_ms() -> None:
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_path",
        return_value={"/tmp/file.txt": ("OK", None)},
    ):
        result = await adapter.scan("/tmp/file.txt")

    assert isinstance(result.duration_ms, int)
    assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# ClamAVAdapter.scan_bytes — in-memory stream scanning
# ---------------------------------------------------------------------------


async def test_scan_bytes_clean_data_returns_clean() -> None:
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_stream",
        return_value={"stream": ("OK", None)},
    ):
        result = await adapter.scan_bytes(b"safe file content")

    assert result.status == "clean"
    assert result.findings == ()
    assert result.engine == "clamav"


async def test_scan_bytes_infected_data_returns_flagged() -> None:
    threat = "Win.Test.EICAR_HDB-1"
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_stream",
        return_value={"stream": ("FOUND", threat)},
    ):
        result = await adapter.scan_bytes(b"EICAR test string")

    assert result.status == "flagged"
    assert len(result.findings) == 1
    assert result.findings[0].match == threat


async def test_scan_bytes_connection_refused_returns_rejected() -> None:
    """Fail-secure: stream scan connection error returns rejected."""
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_stream",
        side_effect=ConnectionRefusedError("refused"),
    ):
        result = await adapter.scan_bytes(b"content")

    assert result.status == "rejected"
    assert result.findings == ()


async def test_scan_bytes_clamd_connection_error_returns_rejected() -> None:
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_stream",
        side_effect=clamd.ConnectionError("clamd not available"),
    ):
        result = await adapter.scan_bytes(b"content")

    assert result.status == "rejected"
    assert result.findings == ()


async def test_scan_bytes_socket_timeout_returns_rejected() -> None:
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_stream",
        side_effect=socket.timeout("timed out"),
    ):
        result = await adapter.scan_bytes(b"content")

    assert result.status == "rejected"


async def test_scan_bytes_unexpected_exception_returns_rejected() -> None:
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_stream",
        side_effect=OSError("broken pipe"),
    ):
        result = await adapter.scan_bytes(b"content")

    assert result.status == "rejected"
    assert result.engine == "clamav"


async def test_scan_bytes_clamd_error_response_returns_rejected() -> None:
    """Fail-secure: ERROR in instream response returns rejected."""
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_stream",
        return_value={"stream": ("ERROR", "size limit exceeded")},
    ):
        result = await adapter.scan_bytes(b"large content")

    assert result.status == "rejected"
    assert result.findings == ()


async def test_scan_bytes_result_includes_duration_ms() -> None:
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_scan_stream",
        return_value={"stream": ("OK", None)},
    ):
        result = await adapter.scan_bytes(b"data")

    assert isinstance(result.duration_ms, int)
    assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# ClamAVAdapter.ping
# ---------------------------------------------------------------------------


async def test_ping_returns_true_when_clamd_responds_pong() -> None:
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(adapter, "_sync_ping", return_value="PONG"):
        result = await adapter.ping()

    assert result is True


async def test_ping_returns_false_when_connection_refused() -> None:
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_ping",
        side_effect=ConnectionRefusedError("refused"),
    ):
        result = await adapter.ping()

    assert result is False


async def test_ping_returns_false_on_clamd_connection_error() -> None:
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_ping",
        side_effect=clamd.ConnectionError("daemon not running"),
    ):
        result = await adapter.ping()

    assert result is False


async def test_ping_returns_false_on_socket_timeout() -> None:
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_ping",
        side_effect=socket.timeout("timed out"),
    ):
        result = await adapter.ping()

    assert result is False


async def test_ping_returns_false_on_unexpected_response() -> None:
    """Any response other than 'PONG' must return False."""
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(adapter, "_sync_ping", return_value="UNEXPECTED"):
        result = await adapter.ping()

    assert result is False


async def test_ping_returns_false_on_empty_response() -> None:
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(adapter, "_sync_ping", return_value=""):
        result = await adapter.ping()

    assert result is False


async def test_ping_returns_false_on_unexpected_exception() -> None:
    adapter = ClamAVAdapter(host="localhost", port=3310)
    with patch.object(
        adapter,
        "_sync_ping",
        side_effect=RuntimeError("unexpected error"),
    ):
        result = await adapter.ping()

    assert result is False


# ---------------------------------------------------------------------------
# ScanResult and Finding are frozen dataclasses
# ---------------------------------------------------------------------------


def test_scan_result_is_immutable() -> None:
    result = ScanResult(status="clean", findings=(), duration_ms=10, engine="clamav")
    with pytest.raises(Exception):
        result.status = "flagged"  # type: ignore[misc]


def test_finding_is_immutable() -> None:
    finding = Finding(
        type="av_threat",
        category="Win.Test",
        severity="high",
        match="Win.Test.EICAR_HDB-1",
    )
    with pytest.raises(Exception):
        finding.severity = "low"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ClamAVAdapter implements AVEngineAdapter contract
# ---------------------------------------------------------------------------


def test_clamav_adapter_is_subclass_of_av_engine_adapter() -> None:
    from fileguard.core.av_engine import AVEngineAdapter

    assert issubclass(ClamAVAdapter, AVEngineAdapter)


def test_clamav_adapter_can_be_instantiated() -> None:
    """ClamAVAdapter provides all abstract method implementations."""
    adapter = ClamAVAdapter(host="localhost", port=3310)
    assert adapter is not None


# ---------------------------------------------------------------------------
# _sync_scan_stream passes BytesIO to clamd
# ---------------------------------------------------------------------------


def test_sync_scan_stream_passes_bytesio_to_instream() -> None:
    """_sync_scan_stream wraps raw bytes in a BytesIO before calling clamd."""
    import io

    adapter = ClamAVAdapter(host="localhost", port=3310)
    mock_client = MagicMock()
    mock_client.instream.return_value = {"stream": ("OK", None)}

    with patch.object(adapter, "_get_client", return_value=mock_client):
        result = adapter._sync_scan_stream(b"test data")

    mock_client.instream.assert_called_once()
    call_arg = mock_client.instream.call_args[0][0]
    assert isinstance(call_arg, io.BytesIO)
    assert result == {"stream": ("OK", None)}
