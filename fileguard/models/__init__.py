"""ORM model registry - import all models so Alembic autogenerate can detect them."""

from fileguard.models.batch_job import BatchJob
from fileguard.models.compliance_report import ComplianceReport
from fileguard.models.scan_event import ScanEvent
from fileguard.models.tenant_config import TenantConfig

__all__ = [
    "TenantConfig",
    "ScanEvent",
    "BatchJob",
    "ComplianceReport",
]
