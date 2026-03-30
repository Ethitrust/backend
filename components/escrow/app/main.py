"""FastAPI entry point for the Escrow service."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api import router
from app.db import Base, engine
from app.grpc_server import serve as grpc_serve
from app.logging_config import configure_logging, install_request_logging
from app.messaging import start_consumer

configure_logging("escrow")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):  # noqa: ANN001
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    consumer_task = asyncio.create_task(start_consumer())
    grpc_task = asyncio.create_task(grpc_serve())
    logger.info("Escrow service is starting up")
    yield
    for task in (consumer_task, grpc_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("Escrow service has shut down")


app = FastAPI(
    title="Ethitrust Escrow Service",
    version="0.1.0",
    lifespan=lifespan,
)

install_request_logging(app)
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "escrow"}


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
