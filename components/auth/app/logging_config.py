from __future__ import annotations

import contextvars
import logging
import os
import time
import uuid
from collections.abc import Callable

from fastapi import FastAPI, Request, Response

_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class _ServiceContextFilter(logging.Filter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self.service_name
        record.request_id = _request_id_ctx.get() if _request_id_ctx.get() else "-"
        return True


def configure_logging(service_name: str) -> None:
    root_logger = logging.getLogger()
    if getattr(root_logger, "_ethitrust_logging_configured", False):
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | service=%(service)s | "
        "request_id=%(request_id)s | %(name)s | %(message)s"
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    context_filter = _ServiceContextFilter(service_name)
    stream_handler.addFilter(context_filter)

    root_logger.handlers.clear()
    root_logger.addHandler(stream_handler)
    root_logger.addFilter(context_filter)
    root_logger.setLevel(level)
    root_logger._ethitrust_logging_configured = True


def install_request_logging(app: FastAPI) -> None:
    if getattr(app.state, "request_logging_installed", False):
        return

    app.state.request_logging_installed = True
    request_logger = logging.getLogger("app.request")

    @app.middleware("http")
    async def request_logging_middleware(
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = _request_id_ctx.set(request_id)

        start = time.perf_counter()
        request_logger.info(
            "request.start method=%s path=%s client=%s",
            request.method,
            request.url.path,
            request.client.host if request.client else "-",
        )

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            request_logger.exception(
                "request.error method=%s path=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                duration_ms,
            )
            raise
        finally:
            _request_id_ctx.reset(token)

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        request_logger.info(
            "request.end method=%s path=%s status_code=%s duration_ms=%.2f",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
