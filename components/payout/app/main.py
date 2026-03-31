"""FastAPI entry point for the Payout service."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api import router
from app.grpc_server import serve as grpc_serve
from app.logging_config import configure_logging, install_request_logging
from app.messaging import start_consumer

configure_logging("payout")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):  # noqa: ANN001
    consumer_task = asyncio.create_task(start_consumer())
    grpc_task = asyncio.create_task(grpc_serve())
    logger.info("Payout service starting up")
    yield
    for task in (consumer_task, grpc_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("Payout service shut down")


app = FastAPI(title="Ethitrust Payout Service", version="0.1.0", lifespan=lifespan)
install_request_logging(app)
app.include_router(router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "service": "payout"}
