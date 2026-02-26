"""ClamAV clamd socket adapter with fail-secure behavior.

Implements :class:`~fileguard.core.av_engine.AVEngineAdapter` by delegating
scan operations to a running ``clamd`` daemon over a TCP socket connection.

**Fail-secure guarantee:** any connection failure, socket timeout, or
unexpected engine response causes the adapter to return
``ScanResult(status="rejected", ...)`` rather than allowing the file to
pass through unchecked.  This aligns with ADR-06 in the HLD: a crashed or
unreachable AV worker must never become a silent pass-through.

**Async compatibility:** the ``clamd`` library is synchronous.  All blocking
calls are dispatched to :func:`asyncio.to_thread` (Python 3.9+) so the
event loop is never blocked during I/O with the clamd daemon.

Usage example::

    from fileguard.core.clamav_adapter import ClamAVAdapter
    from fileguard.config import settings

    adapter = ClamAVAdapter(
        host=settings.CLAMAV_HOST,
        port=settings.CLAMAV_PORT,
    )

    # Scan a file already written to disk
    result = await adapter.scan("/tmp/upload_abc123.pdf")

    # Or stream raw bytes directly (no shared filesystem required)
    result = await adapter.scan_bytes(file_bytes)

    if result.status == "flagged":
        # Apply disposition rules…
        ...
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from typing import Any

import clamd

from fileguard.core.av_engine import AVEngineAdapter, Finding, ScanResult

logger = logging.getLogger(__name__)

# Conservative severity for ClamAV findings.  ClamAV signature names encode
# family/type information but not a numeric severity score; we assign "high"
# as a safe default so downstream disposition rules apply appropriate action.
_DEFAULT_SEVERITY: Finding.__annotations__["severity"] = "high"  # type: ignore[assignment]


def _categorise_threat(threat_name: str) -> str:
    """Return a normalised threat category from a raw ClamAV threat name.

    ClamAV threat names follow a hierarchical dot-separated convention
    (e.g. ``"Win.Test.EICAR_HDB-1"``, ``"Trojan.PDF.Generic"``).  The
    first two components are returned as the category to provide a stable,
    human-readable label for grouping in findings reports.

    If the name has fewer than two components the full name is returned
    unchanged.

    Args:
        threat_name: Raw ClamAV threat identifier string.

    Returns:
        Normalised category string (e.g. ``"Win.Test"``, ``"Trojan.PDF"``).
    """
    parts = threat_name.split(".")
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return threat_name


def _parse_clamd_response(
    response: dict[str, tuple[str, str | None]],
) -> tuple[str, list[Finding]]:
    """Parse a clamd scan response dict into a ``(status, findings)`` pair.

    The clamd library returns a dict mapping scanned paths (or ``"stream"``
    for :func:`clamd.ClamdNetworkSocket.instream`) to a
    ``(result_code, detail)`` tuple:

    * ``("OK", None)``        – file is clean.
    * ``("FOUND", name)``     – threat *name* was detected.
    * ``("ERROR", message)``  – the engine could not scan the item.

    Fail-secure: an ``"ERROR"`` result from clamd is treated as a
    ``"rejected"`` verdict so the file is blocked rather than passed.

    Args:
        response: Dict returned by ``clamd.ClamdNetworkSocket.scan()`` or
            ``clamd.ClamdNetworkSocket.instream()``.

    Returns:
        A ``(status, findings)`` tuple where *status* is ``"clean"``,
        ``"flagged"``, or ``"rejected"`` and *findings* is a list of
        :class:`~fileguard.core.av_engine.Finding` objects.
    """
    findings: list[Finding] = []

    for _path, (result_code, detail) in response.items():
        if result_code == "FOUND" and detail:
            findings.append(
                Finding(
                    type="av_threat",
                    category=_categorise_threat(detail),
                    severity=_DEFAULT_SEVERITY,
                    match=detail,
                )
            )
        elif result_code == "ERROR":
            # Treat any per-file scan error as a rejected verdict (fail-secure).
            logger.warning(
                "ClamAV reported ERROR for path=%s detail=%s; treating as rejected",
                _path,
                detail,
            )
            return "rejected", []

    if findings:
        return "flagged", findings
    return "clean", []


class ClamAVAdapter(AVEngineAdapter):
    """AV engine adapter that communicates with a clamd daemon via TCP socket.

    Each scan operation opens a new TCP connection to clamd.  Connection
    pooling is intentionally avoided because ``clamd`` does not support
    concurrent requests on a single connection; the overhead of a fresh
    connection per scan is acceptable given the cost of a full file scan.

    Implements **fail-secure** behavior: connection errors, socket timeouts,
    and any other unexpected exceptions all result in
    ``ScanResult(status="rejected", ...)`` so files are never silently
    passed through when the AV engine is unavailable.

    Args:
        host: Hostname or IP address of the clamd daemon.
            Defaults to ``"clamav"`` (the Docker Compose service name).
        port: TCP port on which clamd listens.  Defaults to ``3310``.
        timeout: Socket timeout in seconds for clamd connections and
            responses.  Defaults to ``30.0``.
    """

    ENGINE_NAME = "clamav"

    def __init__(
        self,
        host: str = "clamav",
        port: int = 3310,
        timeout: float = 30.0,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public async interface (AVEngineAdapter contract)
    # ------------------------------------------------------------------

    async def scan(self, file_path: str) -> ScanResult:
        """Scan the file at *file_path* via the clamd ``SCAN`` command.

        clamd reads the file directly from the filesystem; the daemon
        process must have read access to *file_path*.  In Docker/Kubernetes
        deployments this requires a shared volume between the application
        container and the clamd container (or DaemonSet pod).

        When filesystem sharing is not available, use :meth:`scan_bytes`
        instead.

        Fail-secure: any exception during the scan (connection refused,
        timeout, unexpected response, etc.) returns
        ``ScanResult(status="rejected", ...)``.

        Args:
            file_path: Absolute path to the file to scan.

        Returns:
            :class:`~fileguard.core.av_engine.ScanResult` with
            ``status="clean"`` if no threats were found, ``"flagged"`` if
            threats were detected, or ``"rejected"`` on any engine failure.
        """
        start_ms = int(time.monotonic() * 1000)

        try:
            response: dict[str, tuple[str, str | None]] = await asyncio.to_thread(
                self._sync_scan_path, file_path
            )
        except Exception as exc:
            elapsed_ms = int(time.monotonic() * 1000) - start_ms
            logger.error(
                "ClamAV scan error path=%s error=%r duration_ms=%d",
                file_path,
                exc,
                elapsed_ms,
            )
            return ScanResult(
                status="rejected",
                findings=(),
                duration_ms=elapsed_ms,
                engine=self.ENGINE_NAME,
            )

        elapsed_ms = int(time.monotonic() * 1000) - start_ms
        status, findings = _parse_clamd_response(response)

        logger.info(
            "ClamAV scan complete path=%s status=%s findings=%d duration_ms=%d",
            file_path,
            status,
            len(findings),
            elapsed_ms,
        )

        return ScanResult(
            status=status,
            findings=tuple(findings),
            duration_ms=elapsed_ms,
            engine=self.ENGINE_NAME,
        )

    async def scan_bytes(self, data: bytes) -> ScanResult:
        """Scan in-memory *data* via the clamd ``INSTREAM`` command.

        Streams the raw bytes directly to the clamd daemon without writing
        to disk or requiring a shared filesystem.  This is the preferred
        scanning method in containerised environments where the application
        container cannot share a tmpfs mount with the clamd container.

        Fail-secure: any exception during the stream scan returns
        ``ScanResult(status="rejected", ...)``.

        Args:
            data: Raw file bytes to scan.

        Returns:
            :class:`~fileguard.core.av_engine.ScanResult` with
            ``status="clean"``, ``"flagged"``, or ``"rejected"``.
        """
        start_ms = int(time.monotonic() * 1000)

        try:
            response: dict[str, tuple[str, str | None]] = await asyncio.to_thread(
                self._sync_scan_stream, data
            )
        except Exception as exc:
            elapsed_ms = int(time.monotonic() * 1000) - start_ms
            logger.error(
                "ClamAV instream scan error error=%r duration_ms=%d",
                exc,
                elapsed_ms,
            )
            return ScanResult(
                status="rejected",
                findings=(),
                duration_ms=elapsed_ms,
                engine=self.ENGINE_NAME,
            )

        elapsed_ms = int(time.monotonic() * 1000) - start_ms
        status, findings = _parse_clamd_response(response)

        logger.info(
            "ClamAV instream scan complete status=%s findings=%d duration_ms=%d",
            status,
            len(findings),
            elapsed_ms,
        )

        return ScanResult(
            status=status,
            findings=tuple(findings),
            duration_ms=elapsed_ms,
            engine=self.ENGINE_NAME,
        )

    async def ping(self) -> bool:
        """Return ``True`` if the clamd daemon is reachable and responds to ``PING``.

        Used by health-check endpoints and liveness probes to verify that
        the AV engine is available before processing scan requests.

        Returns:
            ``True`` if clamd responded with ``"PONG"``; ``False`` on any
            connection error or unexpected response.
        """
        try:
            response: str = await asyncio.to_thread(self._sync_ping)
            return response == "PONG"
        except Exception as exc:
            logger.warning("ClamAV ping failed: %r", exc)
            return False

    # ------------------------------------------------------------------
    # Synchronous helpers (run inside asyncio.to_thread)
    # ------------------------------------------------------------------

    def _get_client(self) -> clamd.ClamdNetworkSocket:
        """Create and return a new clamd TCP socket client.

        A fresh client is created for each call because the ``clamd``
        library does not support multiplexed requests on a single
        connection.
        """
        return clamd.ClamdNetworkSocket(
            host=self._host,
            port=self._port,
            timeout=self._timeout,
        )

    def _sync_scan_path(self, file_path: str) -> dict[str, tuple[str, Any]]:
        """Synchronous: send SCAN command to clamd for *file_path*."""
        client = self._get_client()
        return client.scan(file_path)  # type: ignore[return-value]

    def _sync_scan_stream(self, data: bytes) -> dict[str, tuple[str, Any]]:
        """Synchronous: send INSTREAM command to clamd with *data*."""
        client = self._get_client()
        buffer = io.BytesIO(data)
        return client.instream(buffer)  # type: ignore[return-value]

    def _sync_ping(self) -> str:
        """Synchronous: send PING to clamd and return the response string."""
        client = self._get_client()
        return client.ping()  # type: ignore[return-value]
