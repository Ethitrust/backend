import os

from celery import Celery

from app.logging_config import configure_logging

configure_logging("workers")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "ethitrust-workers",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.tasks.escrow_tasks",
        "app.tasks.recurring_tasks",
        "app.tasks.webhook_tasks",
        "app.tasks.email_tasks",
        "app.tasks.dispute_tasks",
        "app.tasks.payout_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    worker_hijack_root_logger=False,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "check-escrow-inspection-expiry": {
            "task": "app.tasks.escrow_tasks.check_escrow_inspection_expiry",
            "schedule": 3600.0,  # every hour
        },
        "check-invitation-expiry": {
            "task": "app.tasks.escrow_tasks.check_invitation_expiry",
            "schedule": 3600.0,  # every hour
        },
        "process-recurring-cycles": {
            "task": "app.tasks.recurring_tasks.process_recurring_cycle_due",
            "schedule": 86400.0,  # daily
        },
    },
)
