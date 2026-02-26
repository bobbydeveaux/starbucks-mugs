"""Celery application factory for FileGuard.

Creates and configures the shared Celery application used for asynchronous
task execution (compliance report generation, batch scan fan-out, webhook
delivery, etc.).

The broker and result backend are both configured to use Redis (sourced from
``settings.REDIS_URL``).  Tasks are routed to a ``fileguard`` queue by default.

Usage (importing the app in a task module)::

    from fileguard.celery_app import celery_app

    @celery_app.task
    def my_task():
        ...

Starting a worker::

    celery -A fileguard.celery_app worker --loglevel=info -Q fileguard

Starting the beat scheduler::

    celery -A fileguard.celery_app beat --loglevel=info
"""

from celery import Celery

from fileguard.config import settings

#: Shared Celery application instance.  Import this in task modules.
celery_app = Celery(
    "fileguard",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    # Task modules that define @celery_app.task decorators.
    include=["fileguard.services.reports"],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Task routing — all FileGuard tasks go to the "fileguard" queue
    task_default_queue="fileguard",
    # Retry policy defaults (tasks may override)
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Result expiry — keep results for 24 h
    result_expires=86400,
)

# ---------------------------------------------------------------------------
# Beat schedule — configurable daily / weekly compliance report generation
# ---------------------------------------------------------------------------

_CADENCE_SECONDS = {
    "daily": 86_400,    # 24 hours
    "weekly": 604_800,  # 7 days
}

_schedule_seconds = _CADENCE_SECONDS.get(settings.REPORT_CADENCE, 86_400)

celery_app.conf.beat_schedule = {
    "generate-scheduled-compliance-reports": {
        "task": "fileguard.services.reports.generate_scheduled_reports",
        "schedule": _schedule_seconds,
        "options": {"queue": "fileguard"},
    },
}
