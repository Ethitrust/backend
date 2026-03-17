"""Unit tests for admin request logging and observability helpers."""

from __future__ import annotations

import logging

import pytest
from app.logging_config import get_request_metrics_snapshot, install_request_logging
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_request_logging_sets_correlation_headers_and_metrics() -> None:
    app = FastAPI()
    install_request_logging(app)

    @app.get("/admin/users")
    async def list_users() -> dict[str, bool]:
        return {"ok": True}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/admin/users",
            headers={"X-Correlation-ID": "corr-users-1"},
        )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "corr-users-1"
    assert response.headers["X-Request-ID"]

    metrics = get_request_metrics_snapshot(app)
    assert metrics["requests_total"] == 1
    assert metrics["errors_total"] == 0
    assert metrics["modules"]["users"]["requests_total"] == 1
    assert metrics["modules"]["users"]["status_2xx"] == 1


@pytest.mark.asyncio
async def test_request_logging_tracks_server_errors() -> None:
    app = FastAPI()
    install_request_logging(app)

    @app.get("/admin/disputes/queue")
    async def break_queue() -> dict[str, bool]:
        raise RuntimeError("boom")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/admin/disputes/queue")

    assert response.status_code == 500

    metrics = get_request_metrics_snapshot(app)
    assert metrics["requests_total"] == 1
    assert metrics["errors_total"] == 1
    assert metrics["modules"]["disputes"]["errors_total"] == 1
    assert metrics["modules"]["disputes"]["status_5xx"] == 1


@pytest.mark.asyncio
async def test_high_risk_action_emits_alert_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = FastAPI()
    install_request_logging(app)

    @app.patch("/admin/users/{user_id}/role")
    async def update_role(user_id: str) -> dict[str, str]:
        return {"user_id": user_id}

    caplog.set_level(logging.WARNING, logger="app.request")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.patch("/admin/users/abc/role")

    assert response.status_code == 200
    assert any(
        "security.alert.high_risk_action" in record.message for record in caplog.records
    )
