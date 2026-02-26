"""AV engine adapters for FileGuard.

Public re-exports for the engines package. Import adapters via this
module to avoid coupling to internal module layout::

    from fileguard.engines import AVEngineAdapter, ClamAVAdapter, Finding
"""

from fileguard.engines.base import (
    AVEngineAdapter,
    AVEngineError,
    Finding,
    FindingSeverity,
    FindingType,
)
from fileguard.engines.clamav import ClamAVAdapter

__all__ = [
    "AVEngineAdapter",
    "AVEngineError",
    "ClamAVAdapter",
    "Finding",
    "FindingSeverity",
    "FindingType",
]
