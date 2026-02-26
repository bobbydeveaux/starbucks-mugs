"""AV engine and cloud backend adapter implementations.

Public re-exports for the adapters package::

    from fileguard.core.adapters import GoogleDLPAdapter, AWSMacieAdapter
"""

from fileguard.core.adapters.dlp_adapter import GoogleDLPAdapter
from fileguard.core.adapters.macie_adapter import AWSMacieAdapter

__all__ = [
    "AWSMacieAdapter",
    "GoogleDLPAdapter",
]
