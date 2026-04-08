import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router
from app.db import Base, engine
from app.logging_config import configure_logging, install_request_logging

configure_logging("webhook")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (migrations handle production)

    # Start outgoing webhook consumer in background
    from app.messaging import start_consumer

    consumer_task = asyncio.create_task(start_consumer())
    logger.info("Webhook service started.")

    yield

    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()
    logger.info("Webhook service shutdown complete.")


app = FastAPI(
    title="Ethitrust Webhook Service",
    version="0.1.0",
    lifespan=lifespan,
)

install_request_logging(app)
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "webhook"}
