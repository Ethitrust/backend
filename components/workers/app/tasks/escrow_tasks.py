import logging
import os

import httpx

from app.celery_app import celery_app

logger = logging.getLogger(__name__)
ESCROW_SERVICE_URL = os.getenv("ESCROW_SERVICE_URL", "http://escrow-service:8000")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def check_escrow_inspection_expiry(self):
    """
    Checks all active escrows where delivery_date + inspection_period < now.
    Completes them automatically. Called by Celery beat every hour.
    """
    try:
        r = httpx.post(
            f"{ESCROW_SERVICE_URL}/escrow/internal/process-expiry",
            timeout=30.0,
        )
        r.raise_for_status()
        result = r.json()
        logger.info("Processed %d expired escrows", result.get("count", 0))
        return result
    except Exception as exc:
        logger.exception("Error checking escrow expiry: %s", exc)
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def check_invitation_expiry(self):
    """
    Expires stale invitation-state escrows. Called by Celery beat every hour.
    """
    # TODO: we should use grpc or a message queu for this kind of things
    try:
        r = httpx.post(
            f"{ESCROW_SERVICE_URL}/escrow/internal/process-invitation-expiry",
            timeout=30.0,
        )
        r.raise_for_status()
        result = r.json()
        logger.info("Processed %d expired invitations", result.get("count", 0))
        return result
    except Exception as exc:
        logger.exception("Error checking invitation expiry: %s", exc)
        raise self.retry(exc=exc)
