"""Abstract plugin interface for anti-virus engine adapters.

All AV engine adapters (ClamAV, Sophos, CrowdStrike, etc.) must implement
the :class:`AVEngineAdapter` abstract base class.  The pipeline discovers
concrete adapters via a configurable class path so that commercial engines
can be plugged in without modifying the core scanning pipeline.

Usage::

    from fileguard.core.av_adapter import AVEngineAdapter, ScanResult, AVEngineError

    class MyClamAVAdapter(AVEngineAdapter):
        def scan(self, data: bytes) -> ScanResult:
            ...

        def is_available(self) -> bool:
            ...

        def engine_name(self) -> str:
            return "clamav"

See :class:`AVEngineAdapter` for the full interface contract, including the
fail-secure requirements that all adapters must uphold.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Threat severity
# ---------------------------------------------------------------------------


class AVThreatSeverity(str, Enum):
    """Severity level assigned to a detected AV threat."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AVThreat:
    """A single threat detected by the AV engine.

    Attributes:
        name: Threat / signature name returned by the engine
            (e.g. ``"Win.Trojan.EICAR-1"``).
        severity: Severity classification of the detected threat.
        category: Optional category string provided by the engine
            (e.g. ``"Trojan"``, ``"Ransomware"``).  ``None`` when the
            engine does not supply category metadata.
    """

    name: str
    severity: AVThreatSeverity = AVThreatSeverity.HIGH
    category: str | None = None


@dataclass(frozen=True)
class ScanResult:
    """Result of a single AV engine scan invocation.

    Attributes:
        is_clean: ``True`` when no threats were detected; ``False`` when
            one or more :attr:`threats` are present.
        threats: Immutable tuple of detected :class:`AVThreat` objects.
            Always empty when :attr:`is_clean` is ``True``.
        engine_name: Identifier string for the engine that produced this
            result (mirrors :meth:`AVEngineAdapter.engine_name`).
        engine_version: Optional version string for the AV engine or its
            signature database.  ``None`` when the engine does not expose
            version information.
        scan_duration_ms: Approximate elapsed scan time in milliseconds.
            ``None`` when the engine does not expose timing information.

    Raises:
        ValueError: On construction when *is_clean* is ``True`` but
            *threats* is non-empty, as this would be an inconsistent state.
    """

    is_clean: bool
    threats: tuple[AVThreat, ...] = field(default_factory=tuple)
    engine_name: str = ""
    engine_version: str | None = None
    scan_duration_ms: int | None = None

    def __post_init__(self) -> None:
        if self.is_clean and self.threats:
            raise ValueError(
                "ScanResult cannot be marked clean while threats are present."
            )


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class AVEngineError(Exception):
    """Base exception for all AV engine adapter errors.

    Concrete adapters must raise this exception (or a subclass) whenever
    the underlying engine encounters an error.  The scan pipeline treats
    any :class:`AVEngineError` as a *fail-secure* condition and returns a
    ``rejected`` verdict to the caller.

    Do **not** catch and suppress :class:`AVEngineError` inside an adapter;
    let it propagate so the pipeline can quarantine or block the file
    appropriately.
    """


class AVEngineUnavailableError(AVEngineError):
    """Raised when the AV engine daemon or service cannot be reached.

    This is distinct from a successful scan that returns threats.  The
    engine is considered *unavailable* when the adapter cannot establish a
    connection, receives a timeout, or detects that the underlying process
    has crashed.

    :meth:`AVEngineAdapter.is_available` must return ``False`` in the same
    scenario where this error would be raised by :meth:`AVEngineAdapter.scan`.
    """


class AVEngineScanError(AVEngineError):
    """Raised when the AV engine accepts a connection but returns an error.

    Examples:

    - The engine responds with an ``ERROR`` status code.
    - The response payload is malformed or cannot be parsed.
    - An internal engine error occurs mid-scan.
    """


# ---------------------------------------------------------------------------
# Abstract adapter interface
# ---------------------------------------------------------------------------


class AVEngineAdapter(ABC):
    """Abstract base class for all AV engine adapters.

    Each supported AV engine (ClamAV, Sophos, CrowdStrike, …) is integrated
    by subclassing :class:`AVEngineAdapter` and implementing the three
    abstract methods below.  Customer-provided implementations are discovered
    at runtime via the ``AV_ENGINE_CLASS_PATH`` configuration setting so that
    commercial engine SDKs can be bundled separately and loaded dynamically.

    Fail-secure contract
    --------------------
    Adapters must **never** return :class:`ScanResult` with ``is_clean=True``
    when an error or ambiguous engine response is encountered.  Instead they
    must raise :class:`AVEngineError` (or a subclass) so that the calling
    pipeline can apply the fail-secure policy (reject and block the file).

    Thread safety
    -------------
    Implementations should document whether their instances are thread-safe.
    The default worker pool invokes :meth:`scan` from multiple threads;
    adapters that maintain per-instance state (e.g. a socket connection)
    must synchronise access or document that a fresh adapter instance is
    required per thread.
    """

    @abstractmethod
    def scan(self, data: bytes) -> ScanResult:
        """Scan *data* for threats and return a structured result.

        The implementation must inspect all of *data* in a single call;
        partial scans are not supported by the interface.

        Args:
            data: Raw file bytes to inspect.  The adapter may receive any
                MIME type and must not assume a particular file format.

        Returns:
            A :class:`ScanResult` describing the outcome.  The
            ``engine_name`` field should be populated with the same value
            as :meth:`engine_name`.

        Raises:
            AVEngineUnavailableError: If the underlying engine process or
                daemon cannot be reached before or during the scan.
            AVEngineScanError: If the engine is reachable but returns an
                error status or malformed response.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Return ``True`` if the engine is ready to accept scan requests.

        This method is intended for health-check use and **must not raise**
        :class:`AVEngineError`; it should catch connectivity errors
        internally and return ``False`` instead.  The scan pipeline calls
        this method before routing files to the engine.

        Returns:
            ``True`` when the engine daemon is reachable and responsive.
            ``False`` when the engine is unavailable for any reason.
        """

    @abstractmethod
    def engine_name(self) -> str:
        """Return a short, stable identifier for this engine.

        The value is recorded in :class:`ScanResult` objects and audit log
        entries.  It must be a non-empty, lowercase, hyphen-separated ASCII
        string (e.g. ``"clamav"``, ``"sophos-sav"``,
        ``"crowdstrike-falcon"``).

        Returns:
            A non-empty, stable engine identifier string.
        """
