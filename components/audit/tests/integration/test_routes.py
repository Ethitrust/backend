"""Integration tests for Audit HTTP routes."""

from __future__ import annotations

import pytest

AUTH_HEADER = {"Authorization": "Bearer test-token"}


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "audit"


@pytest.mark.asyncio
async def test_create_log(client):
    r = await client.post(
        "/audit/log",
        json={
            "action": "escrow.created",
            "resource": "escrow",
            "resource_id": "12345678-1234-1234-1234-123456789012",
            "details": {"amount": 10000},
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["action"] == "escrow.created"
    assert data["resource"] == "escrow"


@pytest.mark.asyncio
async def test_log_with_null_actor(client):
    """System-triggered logs have null actor_id."""
    r = await client.post(
        "/audit/log",
        json={
            "action": "system.cron",
            "resource": "escrow",
            "actor_id": None,
        },
    )
    assert r.status_code == 201
    assert r.json()["actor_id"] is None


@pytest.mark.asyncio
async def test_query_logs_admin(client):
    await client.post(
        "/audit/log", json={"action": "wallet.funded", "resource": "wallet"}
    )
    await client.post(
        "/audit/log", json={"action": "escrow.completed", "resource": "escrow"}
    )
    r = await client.get("/audit/logs/query", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert r.json()["total"] >= 2


@pytest.mark.asyncio
async def test_query_logs_non_admin_forbidden(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "11111111-1111-1111-1111-111111111111",
                "role": "user",
            }
        ),
    )
    r = await client.get("/audit/logs/query", headers=AUTH_HEADER)
    assert r.status_code == 403
