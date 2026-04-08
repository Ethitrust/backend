"""FastAPI entry point for the KYC service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api import router
from app.db import init_db
from app.fayda_verify import close_fayda_client, init_fayda_client
from app.logging_config import configure_logging, install_request_logging

configure_logging("kyc")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):  # noqa: ANN001
    await init_fayda_client()
    yield
    await close_fayda_client()
    logger.info("KYC service shut down")


app = FastAPI(title="Ethitrust KYC Service", version="0.1.0", lifespan=lifespan)
install_request_logging(app)
app.include_router(router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "service": "kyc"}
