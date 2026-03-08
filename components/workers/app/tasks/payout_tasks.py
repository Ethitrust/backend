import logging
import os

import httpx

from app.celery_app import celery_app

logger = logging.getLogger(__name__)
PAYOUT_SERVICE_URL = os.getenv("PAYOUT_SERVICE_URL", "http://payout-service:8000")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_bank_transfer(self, payout_id: str):
    """
    Execute a bank transfer for an approved payout record.
    Called by the payout service after deducting the wallet balance.
    """
    try:
        r = httpx.post(
            f"{PAYOUT_SERVICE_URL}/payout/{payout_id}/execute-transfer",
            timeout=30.0,
        )
        r.raise_for_status()
        result = r.json()
        logger.info("Bank transfer executed for payout %s", payout_id)
        return result
    except Exception as exc:
        logger.exception("Bank transfer task failed for payout %s: %s", payout_id, exc)
        raise self.retry(exc=exc)
