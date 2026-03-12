"""FastAPI entry point for the Admin service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api import router
from app.logging_config import (
    configure_logging,
    get_request_metrics_snapshot,
    install_request_logging,
)

configure_logging("admin")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):  # noqa: ANN001
    logger.info("Admin service starting up")
    yield
    logger.info("Admin service shut down")


app = FastAPI(title="Ethitrust Admin Service", version="0.1.0", lifespan=lifespan)
install_request_logging(app)
app.include_router(router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "service": "admin"}


@app.get("/metrics", tags=["observability"])
async def metrics() -> dict[str, Any]:
    return get_request_metrics_snapshot(app)
