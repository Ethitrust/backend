"""FastAPI entry point for the Payment Provider service.

No database or RabbitMQ consumer — this service is stateless and responds to
HTTP requests (and, once proto stubs are compiled, gRPC calls) from other
Ethitrust components.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api import router
from app.grpc_server import serve as grpc_serve
from app.logging_config import configure_logging, install_request_logging

configure_logging("payment_provider")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):  # noqa: ANN001
    grpc_task = asyncio.create_task(grpc_serve())
    logger.info("Payment Provider service is starting up")
    yield
    grpc_task.cancel()
    try:
        await grpc_task
    except asyncio.CancelledError:
        pass
    logger.info("Payment Provider service has shut down")


app = FastAPI(
    title="Ethitrust Payment Provider Service",
    version="0.1.0",
    lifespan=lifespan,
)

install_request_logging(app)
app.include_router(router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "service": "payment_provider"}
