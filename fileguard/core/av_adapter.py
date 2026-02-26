"""Abstract plugin interface for antivirus engine adapters.

All concrete AV engine implementations (ClamAV, Sophos, CrowdStrike, …) must
implement :class:`AVEngineAdapter`.  The scan pipeline depends only on this
interface, enabling drop-in engine replacement without modifying pipeline code.

Usage::

    from fileguard.core.av_adapter import AVEngineAdapter, AVEngineError, ScanResult

    class MyEngine(AVEngineAdapter):
        async def scan(self, data: bytes) -> ScanResult: ...
        async def is_available(self) -> bool: ...
        def engine_name(self) -> str: ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


class AVEngineError(Exception):
    """Raised when an AV engine adapter encounters an unrecoverable error.

    This exception signals that the scan *could not be completed*, not that the
    file is clean.  Callers must treat :class:`AVEngineError` as a hard failure
    and apply fail-secure disposition (block / reject) rather than silently
    passing the file through.

    The original cause is always chained via ``__cause__`` so that log
    aggregation systems can surface the root error without losing context.
    """


@dataclass
class ScanResult:
    """Result of a single file scan performed by an :class:`AVEngineAdapter`.

    Attributes:
        is_clean: ``True`` if no threats were detected; ``False`` if the engine
            found a threat.
        threat_name: The threat identifier returned by the engine (e.g.
            ``"Win.Test.EICAR_HDB-1"``).  ``None`` when *is_clean* is ``True``.
        engine_name: Human-readable engine identifier (e.g. ``"clamav"``).
        raw_response: The raw response string from the engine, preserved for
            audit logging and debugging.
    """

    is_clean: bool
    threat_name: Optional[str] = field(default=None)
    engine_name: str = field(default="")
    raw_response: str = field(default="")


class AVEngineAdapter(ABC):
    """Abstract base class for antivirus engine adapters.

    Concrete implementations connect to an AV daemon or cloud API, perform
    scans, and translate engine-specific responses into :class:`ScanResult`
    objects.

    **Fail-secure contract:** :meth:`scan` must *never* return a clean
    :class:`ScanResult` when the scan cannot be completed.  Any communication
    failure or unexpected engine response must raise :class:`AVEngineError`
    instead.  :meth:`is_available` must *never* raise; it returns ``False``
    for all error conditions.
    """

    @abstractmethod
    async def scan(self, data: bytes) -> ScanResult:
        """Scan raw file bytes and return a structured verdict.

        Args:
            data: The raw file content to scan.  For large files, callers
                should stream via a wrapper; adapters may impose a maximum
                chunk size internally.

        Returns:
            :class:`ScanResult` with ``is_clean=True`` for clean files.
            :class:`ScanResult` with ``is_clean=False`` and ``threat_name``
            set when a threat is detected.

        Raises:
            :class:`AVEngineError`: If the engine is unreachable, returns an
                error status, or produces an unrecognised response.  The
                exception **must not** be suppressed; the pipeline must apply
                fail-secure disposition.
        """

    @abstractmethod
    async def is_available(self) -> bool:
        """Check whether the AV engine is reachable and ready to accept scans.

        This method is intended for health-check endpoints and pre-flight
        validation before submitting scan batches.

        Returns:
            ``True`` if the engine can accept scan requests right now.
            ``False`` for *any* error condition (connection refused, timeout,
            unexpected response, …).  This method must **never** raise.
        """

    @abstractmethod
    def engine_name(self) -> str:
        """Return a short, human-readable engine identifier.

        Returns:
            Lowercase string used in :class:`ScanResult` and log output,
            e.g. ``"clamav"``, ``"sophos"``, ``"crowdstrike"``.
        """
