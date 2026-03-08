import hashlib
import hmac
import json
import logging
from typing import Optional

import httpx

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

# Retry countdown schedule (seconds): immediate → 5s → 30s → 5min
_RETRY_DELAYS = [0, 5, 30, 300]


@celery_app.task(bind=True, max_retries=4, default_retry_delay=5)
def deliver_webhook(
    self,
    target_url: str,
    payload: dict,
    secret: str,
    log_id: Optional[str] = None,
):
    """
    Delivers an outgoing webhook payload to target_url with HMAC-SHA256 signature.
    Retries on network errors and HTTP 5xx responses.
    Does NOT retry on HTTP 4xx (client-side rejection).
    """
    attempt = self.request.retries

    try:
        sig = hmac.new(
            secret.encode(), json.dumps(payload).encode(), hashlib.sha256
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Ethitrust-Signature": sig,
        }

        r = httpx.post(target_url, json=payload, headers=headers, timeout=10.0)

        if r.status_code >= 500:
            # Retry on server-side errors
            delay = (
                _RETRY_DELAYS[attempt + 1] if attempt + 1 < len(_RETRY_DELAYS) else 300
            )
            logger.warning(
                "Webhook %s returned %d (attempt %d), retrying in %ds",
                target_url,
                r.status_code,
                attempt,
                delay,
            )
            raise self.retry(countdown=delay)

        if r.status_code >= 400:
            # Do not retry on client-side rejection
            logger.warning(
                "Webhook rejected by %s: status=%d", target_url, r.status_code
            )
            return {"status": "rejected", "status_code": r.status_code}

        logger.info("Webhook delivered to %s: status=%d", target_url, r.status_code)
        return {"status": "delivered", "status_code": r.status_code}

    except httpx.RequestError as exc:
        # Network error — retry with backoff
        delay = _RETRY_DELAYS[attempt + 1] if attempt + 1 < len(_RETRY_DELAYS) else 300
        logger.warning(
            "Webhook delivery network error (attempt %d) for %s: %s",
            attempt,
            target_url,
            exc,
        )
        if attempt >= self.max_retries:
            logger.error(
                "Webhook permanently failed for %s after %d attempts",
                target_url,
                attempt + 1,
            )
            return {"status": "failed"}
        raise self.retry(exc=exc, countdown=delay)
