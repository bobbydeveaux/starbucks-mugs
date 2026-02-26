"""ClamAV daemon adapter with fail-secure socket integration.

:class:`ClamAVAdapter` connects to a running ``clamd`` daemon via a Unix
domain socket (default, used in Kubernetes/on-prem deployments) or a TCP
socket (used in Lambda/network-separated deployments), performs INSTREAM
scans, and returns structured :class:`~fileguard.core.av_adapter.ScanResult`
objects.

**Fail-secure contract:** ``scan()`` *never* returns a clean result when the
scan cannot be completed.  Any daemon-unreachable condition, clamd ``ERROR``
response, or unrecognised response format raises :class:`AVEngineError` so
that the pipeline can apply its reject-on-error disposition policy.

Usage::

    from fileguard.core.adapters.clamav_adapter import ClamAVAdapter
    from fileguard.config import settings

    # Unix socket (Kubernetes DaemonSet / on-prem)
    adapter = ClamAVAdapter(socket_path="/var/run/clamav/clamd.ctl")

    # TCP (network-separated or Lambda deployment)
    adapter = ClamAVAdapter(host=settings.CLAMAV_HOST, port=settings.CLAMAV_PORT)

    result = await adapter.scan(file_bytes)
    if not result.is_clean:
        raise SecurityError(f"Threat detected: {result.threat_name}")
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any, Optional

import clamd

from fileguard.core.av_adapter import AVEngineAdapter, AVEngineError, ScanResult

logger = logging.getLogger(__name__)

# clamd INSTREAM response status tokens.
_STATUS_OK = "OK"
_STATUS_FOUND = "FOUND"
_STATUS_ERROR = "ERROR"


class ClamAVAdapter(AVEngineAdapter):
    """ClamAV daemon adapter that implements fail-secure INSTREAM scanning.

    Connects to ``clamd`` over a Unix domain socket or TCP, streams file bytes
    using the ``INSTREAM`` command, and parses the response into a
    :class:`~fileguard.core.av_adapter.ScanResult`.

    Args:
        socket_path: Absolute path to the ``clamd`` Unix domain socket (e.g.
            ``"/var/run/clamav/clamd.ctl"``).  When provided, Unix socket
            transport is used and *host*/*port* are ignored.
        host: Hostname or IP address of the ``clamd`` TCP listener.  Only
            used when *socket_path* is ``None``.  Defaults to ``"clamav"``.
        port: TCP port of the ``clamd`` daemon.  Defaults to ``3310``.
        timeout: Socket I/O timeout in seconds applied to both the Unix and
            TCP transports.  Defaults to ``30``.
    """

    def __init__(
        self,
        socket_path: Optional[str] = None,
        *,
        host: str = "clamav",
        port: int = 3310,
        timeout: int = 30,
    ) -> None:
        self._socket_path = socket_path
        self._host = host
        self._port = port
        self._timeout = timeout

    # ------------------------------------------------------------------
    # AVEngineAdapter interface
    # ------------------------------------------------------------------

    async def scan(self, data: bytes) -> ScanResult:
        """Scan *data* via the clamd ``INSTREAM`` protocol.

        Delegates the blocking socket I/O to a thread-pool executor so the
        async event loop is not blocked during the scan.

        Args:
            data: Raw file bytes to scan.

        Returns:
            :class:`~fileguard.core.av_adapter.ScanResult` with
            ``is_clean=True`` for clean files, or ``is_clean=False`` with
            ``threat_name`` populated for infected files.

        Raises:
            :class:`~fileguard.core.av_adapter.AVEngineError`: If the daemon
                is unreachable, returns ``ERROR`` status, or produces an
                unrecognised response.  A clean result is **never** returned
                when the scan cannot be verified (fail-secure).
        """
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, self._scan_sync, data)
        except AVEngineError:
            raise
        except Exception as exc:  # pragma: no cover
            raise AVEngineError(
                f"Unexpected error during ClamAV scan: {exc}"
            ) from exc
        return result

    async def is_available(self) -> bool:
        """Return ``True`` if the clamd daemon responds to a ``PING``.

        Executes the ``PING`` command in a thread-pool executor.  All
        exceptions are suppressed — this method always returns ``True`` or
        ``False`` and never raises.

        Returns:
            ``True`` if the daemon is reachable and replied ``PONG``.
            ``False`` for any error (connection refused, timeout, etc.).
        """
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._ping_sync)
            return True
        except Exception:
            return False

    def engine_name(self) -> str:
        """Return the engine identifier ``"clamav"``."""
        return "clamav"

    # ------------------------------------------------------------------
    # Synchronous helpers (run inside executor)
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        """Construct a ``clamd`` client appropriate for the configured transport.

        Returns:
            :class:`clamd.ClamdUnixSocket` when *socket_path* is set, or
            :class:`clamd.ClamdNetworkSocket` for TCP transport.
        """
        if self._socket_path is not None:
            return clamd.ClamdUnixSocket(self._socket_path, timeout=self._timeout)
        return clamd.ClamdNetworkSocket(self._host, self._port, timeout=self._timeout)

    def _scan_sync(self, data: bytes) -> ScanResult:
        """Blocking INSTREAM scan executed inside a thread-pool executor.

        Parses the clamd response dict and maps it to :class:`ScanResult`:

        * ``{'stream': ('OK', None)}``  →  clean result
        * ``{'stream': ('FOUND', '<name>')}``  →  infected result
        * ``{'stream': ('ERROR', '<msg>')}``  →  raises :class:`AVEngineError`

        Args:
            data: Raw file bytes to stream to clamd.

        Raises:
            :class:`~fileguard.core.av_adapter.AVEngineError`: On connection
                failure, ERROR response, or unrecognised response structure.
        """
        try:
            client = self._get_client()
            response: dict = client.instream(io.BytesIO(data))
        except clamd.ConnectionError as exc:
            raise AVEngineError(
                f"ClamAV daemon unreachable ({self._connection_desc()}): {exc}"
            ) from exc
        except AVEngineError:
            raise
        except Exception as exc:
            raise AVEngineError(
                f"ClamAV INSTREAM scan failed ({self._connection_desc()}): {exc}"
            ) from exc

        stream_result = response.get("stream")
        if not stream_result or len(stream_result) < 2:
            raise AVEngineError(
                f"Unexpected ClamAV INSTREAM response: {response!r}"
            )

        status: str = stream_result[0]
        detail: Optional[str] = stream_result[1]
        raw = f"{status}: {detail}"

        if status == _STATUS_OK:
            logger.debug("ClamAV scan: clean (%s)", self._connection_desc())
            return ScanResult(
                is_clean=True,
                engine_name=self.engine_name(),
                raw_response=raw,
            )

        if status == _STATUS_FOUND:
            logger.warning(
                "ClamAV scan: FOUND threat=%s (%s)",
                detail,
                self._connection_desc(),
            )
            return ScanResult(
                is_clean=False,
                threat_name=detail,
                engine_name=self.engine_name(),
                raw_response=raw,
            )

        if status == _STATUS_ERROR:
            raise AVEngineError(
                f"ClamAV daemon reported error: {detail}"
            )

        raise AVEngineError(
            f"Unrecognised ClamAV response status {status!r} "
            f"(detail={detail!r})"
        )

    def _ping_sync(self) -> None:
        """Blocking daemon health-check executed inside a thread-pool executor.

        Raises:
            Any exception raised by the clamd client (propagated to
            :meth:`is_available` which suppresses it and returns ``False``).
        """
        client = self._get_client()
        client.ping()

    def _connection_desc(self) -> str:
        """Return a short, human-readable description of the connection target."""
        if self._socket_path is not None:
            return f"unix:{self._socket_path}"
        return f"tcp:{self._host}:{self._port}"
