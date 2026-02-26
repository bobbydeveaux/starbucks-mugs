"""AV engine and cloud PII backend adapter implementations.

Available adapters:

**AV engine adapters** (implement :class:`~fileguard.core.av_adapter.AVEngineAdapter`):

* :class:`~fileguard.core.adapters.clamav_adapter.ClamAVAdapter` — ClamAV daemon (default)

**Cloud PII detection adapters** (implement :class:`~fileguard.core.adapters.cloud_pii_adapter.CloudPIIAdapter`):

* :class:`~fileguard.core.adapters.google_dlp_adapter.GoogleDLPAdapter` — Google Cloud DLP API
* :class:`~fileguard.core.adapters.aws_macie_adapter.AWSMacieAdapter` — AWS Macie / Amazon Comprehend
"""

from fileguard.core.adapters.aws_macie_adapter import AWSMacieAdapter
from fileguard.core.adapters.clamav_adapter import ClamAVAdapter
from fileguard.core.adapters.cloud_pii_adapter import CloudPIIAdapter, CloudPIIBackendError
from fileguard.core.adapters.google_dlp_adapter import GoogleDLPAdapter

__all__ = [
    "AWSMacieAdapter",
    "ClamAVAdapter",
    "CloudPIIAdapter",
    "CloudPIIBackendError",
    "GoogleDLPAdapter",
]
