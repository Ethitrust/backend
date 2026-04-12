"""FastAPI entry point for the Dispute service."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api import dispute_escrow_router
from app.grpc_server import serve as serve_grpc
from app.logging_config import configure_logging, install_request_logging
from app.messaging import start_consumer

configure_logging("dispute")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):  # noqa: ANN001
    consumer_task = asyncio.create_task(start_consumer())
    grpc_task = asyncio.create_task(serve_grpc())
    logger.info("Dispute service starting up")
    yield
    for task in (consumer_task, grpc_task):
        task.cancel()
    for task in (consumer_task, grpc_task):
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("Dispute service shut down")


app = FastAPI(title="Ethitrust Dispute Service", version="0.1.0", lifespan=lifespan)
install_request_logging(app)
app.include_router(dispute_escrow_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "service": "dispute"}
