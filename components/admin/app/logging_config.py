from __future__ import annotations

import contextvars
import logging
import os
import time
import uuid
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from fastapi import FastAPI, Request, Response

_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)
_correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="-"
)

_HIGH_RISK_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _module_from_path(path: str) -> str:
    if path == "/health":
        return "health"
    if not path.startswith("/admin"):
        return "other"
    parts = [segment for segment in path.split("/") if segment]
    if len(parts) == 1:
        return "admin"
    return parts[1]


def _is_high_risk_action(path: str, method: str) -> bool:
    if method not in _HIGH_RISK_METHODS:
        return False

    if path == "/admin/bulk/users/ban":
        return True

    if path.startswith("/admin/users/") and (
        path.endswith("/role")
        or path.endswith("/ban")
        or path.endswith("/verification-override")
    ):
        return True

    if path.startswith("/admin/disputes/") and path.endswith("/resolution"):
        return True

    if path.startswith("/admin/payouts/") and path.endswith("/retry"):
        return True

    if path.startswith("/admin/configs/") and (method in {"POST", "PUT"}):
        return True

    return False


def _ensure_metrics_container(app: FastAPI) -> dict[str, Any]:
    existing = getattr(app.state, "request_metrics", None)
    if isinstance(existing, dict):
        return existing

    metrics: dict[str, Any] = {
        "requests_total": 0,
        "errors_total": 0,
        "modules": {},
    }
    app.state.request_metrics = metrics
    return metrics


def _record_metrics(
    app: FastAPI,
    *,
    module: str,
    status_code: int,
    duration_ms: float,
) -> None:
    metrics = _ensure_metrics_container(app)
    metrics["requests_total"] = int(metrics.get("requests_total", 0)) + 1
    if status_code >= 500:
        metrics["errors_total"] = int(metrics.get("errors_total", 0)) + 1

    modules = metrics.setdefault("modules", {})
    module_metrics = modules.setdefault(
        module,
        {
            "requests_total": 0,
            "errors_total": 0,
            "latency_ms_sum": 0.0,
            "latency_ms_max": 0.0,
            "status_2xx": 0,
            "status_4xx": 0,
            "status_5xx": 0,
        },
    )

    module_metrics["requests_total"] += 1
    if status_code >= 500:
        module_metrics["errors_total"] += 1

    module_metrics["latency_ms_sum"] += duration_ms
    module_metrics["latency_ms_max"] = max(
        float(module_metrics["latency_ms_max"]), duration_ms
    )

    if 200 <= status_code < 300:
        module_metrics["status_2xx"] += 1
    elif 400 <= status_code < 500:
        module_metrics["status_4xx"] += 1
    elif status_code >= 500:
        module_metrics["status_5xx"] += 1


def get_request_metrics_snapshot(app: FastAPI) -> dict[str, Any]:
    metrics = _ensure_metrics_container(app)
    return deepcopy(metrics)


class _ServiceContextFilter(logging.Filter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self.service_name
        request_id = _request_id_ctx.get()
        correlation_id = _correlation_id_ctx.get()
        record.request_id = request_id if request_id else "-"
        record.correlation_id = correlation_id if correlation_id else "-"
        return True


def configure_logging(service_name: str) -> None:
    root_logger = logging.getLogger()
    if getattr(root_logger, "_ethitrust_logging_configured", False):
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | service=%(service)s | "
        "request_id=%(request_id)s | correlation_id=%(correlation_id)s | "
        "%(name)s | %(message)s"
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger.handlers.clear()
    root_logger.addHandler(stream_handler)
    root_logger.addFilter(_ServiceContextFilter(service_name))
    root_logger.setLevel(level)
    root_logger._ethitrust_logging_configured = True


def install_request_logging(app: FastAPI) -> None:
    if getattr(app.state, "request_logging_installed", False):
        return

    app.state.request_logging_installed = True
    request_logger = logging.getLogger("app.request")
    _ensure_metrics_container(app)

    @app.middleware("http")
    async def request_logging_middleware(
        request: Request,
        call_next: Callable[[Request], Response],
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        correlation_id = request.headers.get("X-Correlation-ID") or request_id
        request_token = _request_id_ctx.set(request_id)
        correlation_token = _correlation_id_ctx.set(correlation_id)

        request.state.request_id = request_id
        request.state.correlation_id = correlation_id

        start = time.perf_counter()
        module = _module_from_path(request.url.path)
        request_logger.info(
            "request.start method=%s path=%s module=%s client=%s",
            request.method,
            request.url.path,
            module,
            request.client.host if request.client else "-",
        )

        try:
            try:
                response = await call_next(request)
            except Exception:
                duration_ms = (time.perf_counter() - start) * 1000
                _record_metrics(
                    request.app,
                    module=module,
                    status_code=500,
                    duration_ms=duration_ms,
                )
                request_logger.exception(
                    "request.error method=%s path=%s module=%s duration_ms=%.2f",
                    request.method,
                    request.url.path,
                    module,
                    duration_ms,
                )
                if _is_high_risk_action(request.url.path, request.method):
                    request_logger.error(
                        "security.alert.high_risk_action method=%s path=%s "
                        "module=%s status_code=%s duration_ms=%.2f",
                        request.method,
                        request.url.path,
                        module,
                        500,
                        duration_ms,
                    )
                raise

            duration_ms = (time.perf_counter() - start) * 1000
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Correlation-ID"] = correlation_id
            _record_metrics(
                request.app,
                module=module,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            request_logger.info(
                "request.end method=%s path=%s module=%s status_code=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                module,
                response.status_code,
                duration_ms,
            )
            request_logger.info(
                "request.metric module=%s method=%s path=%s status_code=%s latency_ms=%.2f",
                module,
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )

            if _is_high_risk_action(request.url.path, request.method):
                request_logger.warning(
                    "security.alert.high_risk_action method=%s path=%s module=%s "
                    "status_code=%s duration_ms=%.2f",
                    request.method,
                    request.url.path,
                    module,
                    response.status_code,
                    duration_ms,
                )
            return response
        finally:
            _request_id_ctx.reset(request_token)
            _correlation_id_ctx.reset(correlation_token)
