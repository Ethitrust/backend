"""
Workers service health endpoint (for liveness probes in Kubernetes/Docker).
The actual background work is performed by the Celery worker process, not uvicorn.
Start workers with:  celery -A app.celery_app worker -B --loglevel=info
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.logging_config import configure_logging, install_request_logging

configure_logging("workers")
logger = logging.getLogger(__name__)

app = FastAPI(title="Ethitrust Workers Health", version="0.1.0")
install_request_logging(app)


@app.get("/health")
async def health() -> dict:
    """Liveness probe — also pings Celery workers."""
    from app.celery_app import celery_app

    try:
        responses = celery_app.control.ping(timeout=1)
        workers_up = bool(responses)
    except Exception as exc:
        logger.exception("Failed to ping Celery workers: %s", exc)
        workers_up = False

    return {"status": "ok", "celery_workers": workers_up}
