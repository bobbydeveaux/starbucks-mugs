"""Abstract AV engine adapter interface and scan result types.

Defines the contract that all AV engine adapters must fulfil.  Concrete
implementations (e.g. :class:`~fileguard.core.clamav_adapter.ClamAVAdapter`)
are loaded via the configurable adapter class path.

Design principle — **fail-secure**: adapter implementations must **never**
silently pass a file through on error.  Any unhandled exception, engine
unavailability, or timeout must result in
``ScanResult(status="rejected", ...)``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Finding:
    """A single threat detection finding returned by an AV scan.

    Attributes:
        type: Always ``"av_threat"`` for AV engine findings.
        category: Normalised threat category derived from the engine-specific
            threat name (e.g. ``"Win.Test"``, ``"Trojan.Generic"``).
        severity: Threat severity level.  ClamAV does not provide severity
            ratings natively; the adapter assigns ``"high"`` for all detected
            threats as a conservative default.
        match: Raw threat identifier as reported by the AV engine
            (e.g. ``"Win.Test.EICAR_HDB-1"``).
    """

    type: Literal["av_threat"]
    category: str
    severity: Literal["low", "medium", "high", "critical"]
    match: str


@dataclass(frozen=True)
class ScanResult:
    """Result of an AV engine scan operation.

    Attributes:
        status: Overall verdict.
            - ``"clean"``    – no threats detected.
            - ``"flagged"``  – one or more threats detected; file should be
              quarantined or blocked per disposition rules.
            - ``"rejected"`` – scan could not be completed (engine error,
              connection failure, timeout); file is blocked by fail-secure
              policy.
        findings: Tuple of :class:`Finding` objects describing detected
            threats.  Empty for ``"clean"`` and ``"rejected"`` verdicts.
        duration_ms: Wall-clock time taken for the scan in milliseconds.
        engine: Name of the AV engine that produced this result
            (e.g. ``"clamav"``).
    """

    status: Literal["clean", "flagged", "rejected"]
    findings: tuple[Finding, ...] = field(default_factory=tuple)
    duration_ms: int = 0
    engine: str = "unknown"


class AVEngineAdapter(abc.ABC):
    """Abstract base class for AV engine adapters.

    All adapters must implement :meth:`scan`, :meth:`scan_bytes`, and
    :meth:`ping`.  The fail-secure contract requires that on any engine
    failure the adapter returns ``ScanResult(status="rejected", ...)``
    rather than raising an exception.
    """

    @abc.abstractmethod
    async def scan(self, file_path: str) -> ScanResult:
        """Scan the file at *file_path* and return a verdict.

        The engine reads the file directly; the engine process must have
        read access to *file_path* (use a shared volume in containerised
        deployments or prefer :meth:`scan_bytes` when filesystem sharing is
        not possible).

        On any engine failure implementations **must** return
        ``ScanResult(status="rejected", ...)`` rather than raising.

        Args:
            file_path: Absolute path to the file to scan.

        Returns:
            A :class:`ScanResult` with ``status`` set to ``"clean"``,
            ``"flagged"``, or ``"rejected"``.
        """

    @abc.abstractmethod
    async def scan_bytes(self, data: bytes) -> ScanResult:
        """Scan in-memory *data* without requiring shared filesystem access.

        Streams the raw bytes directly to the AV engine.  Preferred in
        containerised environments where the worker container does not share
        a filesystem with the AV daemon container.

        On any engine failure implementations **must** return
        ``ScanResult(status="rejected", ...)`` rather than raising.

        Args:
            data: Raw file bytes to scan.

        Returns:
            A :class:`ScanResult` with ``status`` set to ``"clean"``,
            ``"flagged"``, or ``"rejected"``.
        """

    @abc.abstractmethod
    async def ping(self) -> bool:
        """Return ``True`` if the AV engine is reachable and healthy.

        Used by health-check endpoints and circuit-breaker logic to
        determine engine availability before accepting scan requests.

        Returns:
            ``True`` if the engine responded successfully; ``False``
            on any error or unexpected response.
        """
