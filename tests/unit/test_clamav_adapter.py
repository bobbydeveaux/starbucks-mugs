"""Unit tests for fileguard/core/adapters/clamav_adapter.py.

All tests are fully offline — the ``clamd`` client is replaced with mocks
so no real ClamAV daemon is required.

Coverage targets:

* scan() returns a clean ScanResult on clamd ``OK`` response
* scan() returns an infected ScanResult on clamd ``FOUND`` response
* scan() raises AVEngineError on clamd ``ERROR`` response
* scan() raises AVEngineError when the daemon is unreachable (ConnectionError)
* scan() raises AVEngineError on an unexpected response structure
* scan() raises AVEngineError on an unrecognised status token
* is_available() returns True when PING succeeds
* is_available() returns False (never raises) when PING fails
* is_available() returns False for any arbitrary exception (not just ConnectionError)
* Constructor stores socket_path and passes it to ClamdUnixSocket
* Constructor falls back to TCP (ClamdNetworkSocket) when socket_path is None
* engine_name() returns "clamav"
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import clamd
import pytest

from fileguard.core.adapters.clamav_adapter import ClamAVAdapter
from fileguard.core.av_adapter import AVEngineError, ScanResult

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SOCKET_PATH = "/var/run/clamav/clamd.ctl"
_CLEAN_FILE = b"Hello, safe world!"
_EICAR = (
    b"X5O!P%@AP[4\\PZX54(P^)7CC)7}"
    b"$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_clamd_client(response: dict) -> MagicMock:
    """Return a mock clamd client whose instream() returns *response*."""
    client = MagicMock()
    client.instream.return_value = response
    return client


def _make_unix_adapter(**kwargs: Any) -> ClamAVAdapter:
    """Return a ClamAVAdapter configured for Unix socket."""
    return ClamAVAdapter(socket_path=_SOCKET_PATH, **kwargs)


def _make_tcp_adapter(**kwargs: Any) -> ClamAVAdapter:
    """Return a ClamAVAdapter configured for TCP."""
    return ClamAVAdapter(host="clamav", port=3310, **kwargs)


# ---------------------------------------------------------------------------
# engine_name
# ---------------------------------------------------------------------------


class TestEngineName:
    def test_returns_clamav(self) -> None:
        adapter = _make_unix_adapter()
        assert adapter.engine_name() == "clamav"


# ---------------------------------------------------------------------------
# Constructor / transport selection
# ---------------------------------------------------------------------------


class TestConstructor:
    def test_socket_path_stored(self) -> None:
        adapter = ClamAVAdapter(socket_path=_SOCKET_PATH)
        assert adapter._socket_path == _SOCKET_PATH

    def test_unix_socket_client_when_socket_path_provided(self) -> None:
        adapter = ClamAVAdapter(socket_path=_SOCKET_PATH, timeout=10)
        with patch("fileguard.core.adapters.clamav_adapter.clamd") as mock_clamd:
            adapter._get_client()
            mock_clamd.ClamdUnixSocket.assert_called_once_with(_SOCKET_PATH, timeout=10)
            mock_clamd.ClamdNetworkSocket.assert_not_called()

    def test_tcp_client_when_socket_path_is_none(self) -> None:
        adapter = ClamAVAdapter(host="myhost", port=9999, timeout=15)
        with patch("fileguard.core.adapters.clamav_adapter.clamd") as mock_clamd:
            adapter._get_client()
            mock_clamd.ClamdNetworkSocket.assert_called_once_with(
                "myhost", 9999, timeout=15
            )
            mock_clamd.ClamdUnixSocket.assert_not_called()

    def test_default_host_port_timeout(self) -> None:
        adapter = ClamAVAdapter()
        assert adapter._host == "clamav"
        assert adapter._port == 3310
        assert adapter._timeout == 30


# ---------------------------------------------------------------------------
# scan() — clean file (OK response)
# ---------------------------------------------------------------------------


class TestScanClean:
    @pytest.mark.asyncio
    async def test_returns_scan_result_with_is_clean_true(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client({"stream": ("OK", None)})

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.scan(_CLEAN_FILE)

        assert isinstance(result, ScanResult)
        assert result.is_clean is True

    @pytest.mark.asyncio
    async def test_threat_name_is_none_for_clean_file(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client({"stream": ("OK", None)})

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.scan(_CLEAN_FILE)

        assert result.threat_name is None

    @pytest.mark.asyncio
    async def test_engine_name_is_clamav(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client({"stream": ("OK", None)})

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.scan(_CLEAN_FILE)

        assert result.engine_name == "clamav"

    @pytest.mark.asyncio
    async def test_raw_response_contains_ok(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client({"stream": ("OK", None)})

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.scan(_CLEAN_FILE)

        assert "OK" in result.raw_response

    @pytest.mark.asyncio
    async def test_instream_called_with_file_bytes(self) -> None:
        """The clamd client must receive the exact bytes passed to scan()."""
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client({"stream": ("OK", None)})

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.scan(_CLEAN_FILE)

        # instream() is called once; the arg is an io.BytesIO wrapping the data
        call_args = mock_client.instream.call_args
        assert call_args is not None
        file_obj = call_args.args[0]
        assert file_obj.read() == _CLEAN_FILE


# ---------------------------------------------------------------------------
# scan() — infected file (FOUND response)
# ---------------------------------------------------------------------------


class TestScanInfected:
    _THREAT = "Win.Test.EICAR_HDB-1"
    _RESPONSE = {"stream": ("FOUND", _THREAT)}

    @pytest.mark.asyncio
    async def test_returns_scan_result_with_is_clean_false(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client(self._RESPONSE)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.scan(_EICAR)

        assert result.is_clean is False

    @pytest.mark.asyncio
    async def test_threat_name_matches_clamd_response(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client(self._RESPONSE)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.scan(_EICAR)

        assert result.threat_name == self._THREAT

    @pytest.mark.asyncio
    async def test_engine_name_is_clamav(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client(self._RESPONSE)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.scan(_EICAR)

        assert result.engine_name == "clamav"

    @pytest.mark.asyncio
    async def test_raw_response_contains_found(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client(self._RESPONSE)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.scan(_EICAR)

        assert "FOUND" in result.raw_response
        assert self._THREAT in result.raw_response


# ---------------------------------------------------------------------------
# scan() — daemon returns ERROR status
# ---------------------------------------------------------------------------


class TestScanErrorStatus:
    _ERROR_RESPONSE = {"stream": ("ERROR", "lstat() failed: No such file or directory")}

    @pytest.mark.asyncio
    async def test_raises_av_engine_error(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client(self._ERROR_RESPONSE)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with pytest.raises(AVEngineError):
                await adapter.scan(_CLEAN_FILE)

    @pytest.mark.asyncio
    async def test_error_message_contains_clamd_detail(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client(self._ERROR_RESPONSE)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with pytest.raises(AVEngineError) as exc_info:
                await adapter.scan(_CLEAN_FILE)

        assert "lstat() failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_does_not_return_clean_result_on_error(self) -> None:
        """Fail-secure: must never return clean when ERROR is received."""
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client(self._ERROR_RESPONSE)

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with pytest.raises(AVEngineError):
                await adapter.scan(_CLEAN_FILE)


# ---------------------------------------------------------------------------
# scan() — daemon unreachable (ConnectionError)
# ---------------------------------------------------------------------------


class TestScanDaemonDown:
    @pytest.mark.asyncio
    async def test_raises_av_engine_error_on_connection_error(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = MagicMock()
        mock_client.instream.side_effect = clamd.ConnectionError("socket not found")

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with pytest.raises(AVEngineError):
                await adapter.scan(_CLEAN_FILE)

    @pytest.mark.asyncio
    async def test_av_engine_error_chains_connection_error(self) -> None:
        adapter = _make_unix_adapter()
        original = clamd.ConnectionError("refused")
        mock_client = MagicMock()
        mock_client.instream.side_effect = original

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with pytest.raises(AVEngineError) as exc_info:
                await adapter.scan(_CLEAN_FILE)

        assert exc_info.value.__cause__ is original

    @pytest.mark.asyncio
    async def test_does_not_return_clean_result_when_daemon_is_down(self) -> None:
        """Fail-secure: must raise, not return clean, when daemon is down."""
        adapter = _make_unix_adapter()
        mock_client = MagicMock()
        mock_client.instream.side_effect = clamd.ConnectionError("refused")

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with pytest.raises(AVEngineError):
                await adapter.scan(_CLEAN_FILE)

    @pytest.mark.asyncio
    async def test_connection_desc_in_error_for_unix_socket(self) -> None:
        adapter = ClamAVAdapter(socket_path="/run/clamd.ctl")
        mock_client = MagicMock()
        mock_client.instream.side_effect = clamd.ConnectionError("refused")

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with pytest.raises(AVEngineError) as exc_info:
                await adapter.scan(_CLEAN_FILE)

        assert "unix:/run/clamd.ctl" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_connection_desc_in_error_for_tcp(self) -> None:
        adapter = ClamAVAdapter(host="clamd-host", port=3310)
        mock_client = MagicMock()
        mock_client.instream.side_effect = clamd.ConnectionError("refused")

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with pytest.raises(AVEngineError) as exc_info:
                await adapter.scan(_CLEAN_FILE)

        assert "tcp:clamd-host:3310" in str(exc_info.value)


# ---------------------------------------------------------------------------
# scan() — unexpected / malformed response structure
# ---------------------------------------------------------------------------


class TestScanMalformedResponse:
    @pytest.mark.asyncio
    async def test_raises_av_engine_error_when_stream_key_missing(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client({"unexpected_key": ("OK", None)})

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with pytest.raises(AVEngineError):
                await adapter.scan(_CLEAN_FILE)

    @pytest.mark.asyncio
    async def test_raises_av_engine_error_for_empty_stream_tuple(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client({"stream": ()})

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with pytest.raises(AVEngineError):
                await adapter.scan(_CLEAN_FILE)

    @pytest.mark.asyncio
    async def test_raises_av_engine_error_for_unknown_status_token(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client({"stream": ("UNKNOWN_STATUS", None)})

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with pytest.raises(AVEngineError) as exc_info:
                await adapter.scan(_CLEAN_FILE)

        assert "UNKNOWN_STATUS" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_av_engine_error_when_stream_value_is_none(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = _make_clamd_client({"stream": None})

        with patch.object(adapter, "_get_client", return_value=mock_client):
            with pytest.raises(AVEngineError):
                await adapter.scan(_CLEAN_FILE)


# ---------------------------------------------------------------------------
# is_available() — daemon reachable
# ---------------------------------------------------------------------------


class TestIsAvailableReachable:
    @pytest.mark.asyncio
    async def test_returns_true_when_ping_succeeds(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = MagicMock()
        mock_client.ping.return_value = "PONG"

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.is_available()

        assert result is True

    @pytest.mark.asyncio
    async def test_ping_is_called_once(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = MagicMock()
        mock_client.ping.return_value = "PONG"

        with patch.object(adapter, "_get_client", return_value=mock_client):
            await adapter.is_available()

        mock_client.ping.assert_called_once()


# ---------------------------------------------------------------------------
# is_available() — daemon unreachable (fail-safe: returns False, never raises)
# ---------------------------------------------------------------------------


class TestIsAvailableUnreachable:
    @pytest.mark.asyncio
    async def test_returns_false_when_connection_error(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = MagicMock()
        mock_client.ping.side_effect = clamd.ConnectionError("refused")

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.is_available()

        assert result is False

    @pytest.mark.asyncio
    async def test_does_not_raise_when_connection_error(self) -> None:
        adapter = _make_unix_adapter()
        mock_client = MagicMock()
        mock_client.ping.side_effect = clamd.ConnectionError("refused")

        with patch.object(adapter, "_get_client", return_value=mock_client):
            # Must return False, not raise
            result = await adapter.is_available()

        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_returns_false_for_any_exception(self) -> None:
        """is_available() must suppress *all* exceptions, not just ConnectionError."""
        adapter = _make_unix_adapter()
        mock_client = MagicMock()
        mock_client.ping.side_effect = RuntimeError("unexpected daemon failure")

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.is_available()

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_timeout(self) -> None:
        import socket

        adapter = _make_unix_adapter()
        mock_client = MagicMock()
        mock_client.ping.side_effect = socket.timeout("timed out")

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.is_available()

        assert result is False


# ---------------------------------------------------------------------------
# TCP adapter — basic behaviour
# ---------------------------------------------------------------------------


class TestTcpAdapter:
    @pytest.mark.asyncio
    async def test_scan_clean_over_tcp(self) -> None:
        adapter = _make_tcp_adapter()
        mock_client = _make_clamd_client({"stream": ("OK", None)})

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.scan(_CLEAN_FILE)

        assert result.is_clean is True

    @pytest.mark.asyncio
    async def test_is_available_true_over_tcp(self) -> None:
        adapter = _make_tcp_adapter()
        mock_client = MagicMock()
        mock_client.ping.return_value = "PONG"

        with patch.object(adapter, "_get_client", return_value=mock_client):
            result = await adapter.is_available()

        assert result is True
