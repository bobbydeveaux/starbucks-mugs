"""ClamAV engine adapter.

Connects to a running ``clamd`` daemon via TCP socket and delegates file
scanning to it.  The ClamAV daemon must be started separately (e.g. via
the ``clamav`` service defined in ``docker-compose.yml``).

The adapter is intentionally stateless beyond the connection parameters:
``clamd`` serialises concurrent scan requests on its side, so the adapter
is safe to call from multiple threads without additional locking.
"""
from __future__ import annotations

import logging
from pathlib import Path

import clamd

from fileguard.engines.base import (
    AVEngineAdapter,
    AVEngineError,
    Finding,
    FindingSeverity,
    FindingType,
)

logger = logging.getLogger(__name__)

# ClamAV reports detected threats with this status string.
_STATUS_FOUND = "FOUND"


class ClamAVAdapter(AVEngineAdapter):
    """Antivirus adapter for the ClamAV daemon (``clamd``).

    Communicates with ``clamd`` over a TCP network socket.  A new
    socket connection is established for each :meth:`scan` call by the
    underlying ``clamd`` library; no persistent connection state is held
    in this class.

    Args:
        host: Hostname or IP address of the ``clamd`` daemon.
            Defaults to ``"clamav"`` to match the Docker Compose
            service name.
        port: TCP port the ``clamd`` daemon listens on.
            Defaults to ``3310`` (ClamAV standard port).

    Example::

        adapter = ClamAVAdapter(host="localhost", port=3310)
        findings = adapter.scan(Path("/tmp/upload.pdf"))
        if findings:
            raise QuarantineError(findings)
    """

    def __init__(self, host: str = "clamav", port: int = 3310) -> None:
        self._host = host
        self._port = port
        self._client = clamd.ClamdNetworkSocket(host=host, port=port)

    # ------------------------------------------------------------------
    # AVEngineAdapter interface
    # ------------------------------------------------------------------

    def scan(self, file_path: Path) -> list[Finding]:
        """Scan *file_path* with ClamAV and return detected AV findings.

        Args:
            file_path: Absolute path to the file to scan.

        Returns:
            A list of :class:`~fileguard.engines.base.Finding` objects,
            one per detected threat. Returns an empty list when the file
            is clean.

        Raises:
            AVEngineError: If the ``clamd`` daemon is unreachable or
                returns an unexpected response.
            FileNotFoundError: If *file_path* does not exist.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            result = self._client.scan(str(file_path))
        except clamd.ConnectionError as exc:
            raise AVEngineError(
                f"ClamAV daemon unreachable at {self._host}:{self._port}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise AVEngineError(f"ClamAV scan failed: {exc}") from exc

        findings: list[Finding] = []
        if result:
            for _path, (status, virus_name) in result.items():
                if status == _STATUS_FOUND:
                    category = virus_name or "UNKNOWN"
                    logger.warning(
                        "ClamAV detected threat",
                        extra={"file": str(file_path), "threat": category},
                    )
                    findings.append(
                        Finding(
                            type=FindingType.AV_THREAT,
                            category=category,
                            severity=FindingSeverity.CRITICAL,
                            offset=0,
                            match=category,
                        )
                    )

        return findings

    def ping(self) -> bool:
        """Check whether the ``clamd`` daemon is reachable.

        Returns:
            ``True`` if the daemon responds to a ``PING`` command,
            ``False`` on any connection or protocol error.
        """
        try:
            self._client.ping()
            return True
        except Exception:  # noqa: BLE001
            return False
