"""FileGuard Celery worker package.

This package contains Celery task definitions for asynchronous and batch
file scanning via the FileGuard scan pipeline.

Modules
-------
scan_worker
    Single-file async scan task and batch fan-out task wrapping
    :class:`~fileguard.core.pipeline.ScanPipeline`.
"""
