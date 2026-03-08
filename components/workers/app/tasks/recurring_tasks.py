import logging
import os

import httpx

from app.celery_app import celery_app

logger = logging.getLogger(__name__)
ESCROW_SERVICE_URL = os.getenv("ESCROW_SERVICE_URL", "http://escrow-service:8000")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300)
def process_recurring_cycle_due(self):
    """
    Processes recurring escrow cycles that are due today. Called daily by Celery beat.
    """
    try:
        r = httpx.post(
            f"{ESCROW_SERVICE_URL}/escrow/internal/process-recurring",
            timeout=60.0,
        )
        r.raise_for_status()
        result = r.json()
        logger.info("Processed %d recurring cycles", result.get("count", 0))
        return result
    except Exception as exc:
        logger.exception("Recurring cycle processing failed: %s", exc)
        raise self.retry(exc=exc)
