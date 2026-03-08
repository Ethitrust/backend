import logging
import os

import httpx

from app.celery_app import celery_app

logger = logging.getLogger(__name__)
DISPUTE_SERVICE_URL = os.getenv("DISPUTE_SERVICE_URL", "http://dispute-service:8000")
DISPUTE_INTERNAL_TOKEN = os.getenv("DISPUTE_INTERNAL_TOKEN", "").strip()


# TODO: use grpc
@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_dispute_resolution(self, dispute_id: str, resolution: str, admin_id: str):
    """
    Execute fund movements for a dispute resolution decision.
    resolution must be either 'buyer' or 'seller'.
    Called by admin after manually reviewing the dispute.
    """
    if resolution not in ("buyer", "seller"):
        logger.error(
            "Invalid resolution '%s' for dispute %s — skipping", resolution, dispute_id
        )
        return {"status": "invalid_resolution"}

    try:
        headers = (
            {
                "X-Internal-Token": DISPUTE_INTERNAL_TOKEN,
            }
            if DISPUTE_INTERNAL_TOKEN
            else None
        )

        # unsecure function VERY DANGEROUS
        r = httpx.post(
            f"{DISPUTE_SERVICE_URL}/disputes/{dispute_id}/execute-resolution",
            json={"resolution": resolution, "admin_id": admin_id},
            headers=headers,
            timeout=30.0,
        )
        r.raise_for_status()
        result = r.json()
        logger.info(
            "Dispute %s resolved in favour of %s by admin %s",
            dispute_id,
            resolution,
            admin_id,
        )
        return result
    except Exception as exc:
        logger.exception("Dispute resolution task failed for %s: %s", dispute_id, exc)
        raise self.retry(exc=exc)
