"""Abstract AV engine adapter interface.

All antivirus engine integrations must implement :class:`AVEngineAdapter`.
The default implementation is :class:`~fileguard.engines.clamav.ClamAVAdapter`.
Commercial engine adapters (Sophos, CrowdStrike) are loaded via a
configurable class path at runtime, as described in ADR-04 of the HLD.

Usage::

    from fileguard.engines.base import AVEngineAdapter, Finding

    class MyAdapter(AVEngineAdapter):
        def scan(self, file_path: Path) -> list[Finding]:
            ...

        def ping(self) -> bool:
            ...
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class FindingType(str, Enum):
    """Classification of a scan finding."""

    AV_THREAT = "av_threat"
    PII = "pii"


class FindingSeverity(str, Enum):
    """Severity levels for findings, aligned with the HLD data model."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Finding:
    """Immutable record of a single scan finding.

    Attributes:
        type: Classification of the finding — antivirus threat or PII.
        category: Human-readable, engine-specific label for the detected
            issue (e.g. ``"EICAR-Test-Signature"``, ``"NHS_NUMBER"``).
        severity: Assessed severity of the finding.
        offset: Byte offset within the extracted text where the match
            starts. Use ``0`` for AV threats where no text extraction
            applies.
        match: The matched string. For PII findings this value **must**
            be ``"[REDACTED]"`` in stored form. For AV threats it is the
            virus name as reported by the engine.
    """

    type: FindingType
    category: str
    severity: FindingSeverity
    offset: int
    match: str


class AVEngineError(Exception):
    """Raised when the AV engine is unreachable or returns an unexpected error.

    Callers must treat this exception as a scan failure and apply the
    fail-secure policy — i.e. reject the file rather than allowing
    silent pass-through (see ADR-06).
    """


class AVEngineAdapter(ABC):
    """Abstract interface for antivirus scan engine adapters.

    Concrete implementations wrap a specific AV backend (ClamAV,
    Sophos, CrowdStrike, etc.) and expose a uniform ``scan`` / ``ping``
    contract to the scan pipeline.  The pipeline must not reference any
    concrete adapter class directly; it depends only on this interface.

    Implementing classes **must** be safe for concurrent use from
    multiple threads: the scan worker pool invokes ``scan`` from a
    ``ThreadPoolExecutor``, so any shared state must be protected by
    appropriate synchronisation primitives.

    Example — minimal stub for unit tests::

        class FakeAVAdapter(AVEngineAdapter):
            def __init__(self, findings: list[Finding] | None = None) -> None:
                self._findings = findings or []

            def scan(self, file_path: Path) -> list[Finding]:
                return self._findings

            def ping(self) -> bool:
                return True
    """

    @abstractmethod
    def scan(self, file_path: Path) -> list[Finding]:
        """Scan *file_path* and return any detected findings.

        An empty list indicates that the file is clean with respect to
        this adapter's detection scope (AV threats for AV adapters; PII
        for PII adapters).

        Args:
            file_path: Absolute path to the file to scan. The file must
                exist and be readable by the process.

        Returns:
            A list of :class:`Finding` objects. The list is empty when
            no threats or sensitive data are detected.

        Raises:
            AVEngineError: If the engine daemon is unreachable or
                returns an unexpected response. Callers should treat
                this as a scan failure and apply fail-secure policy.
            FileNotFoundError: If *file_path* does not exist.
        """

    @abstractmethod
    def ping(self) -> bool:
        """Return ``True`` if the engine is reachable and ready to scan.

        Implementations should perform a lightweight liveness check
        (e.g. the ClamAV ``PING`` command). All exceptions must be
        caught internally; the method must never raise.

        Returns:
            ``True`` if the engine responded successfully, ``False``
            otherwise.
        """
