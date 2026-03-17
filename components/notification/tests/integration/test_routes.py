"""Integration tests for Notification HTTP routes."""

from __future__ import annotations

import pytest

AUTH_HEADER = {"Authorization": "Bearer test-token"}
USER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "notification"


@pytest.mark.asyncio
async def test_create_notification_internal(client):
    r = await client.post(
        "/notifications/internal",
        json={
            "user_id": USER_ID,
            "type": "escrow.funded",
            "title": "Escrow Funded",
            "body": "Your escrow of 10,000 ETB has been funded.",
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["type"] == "escrow.funded"
    assert data["is_read"] is False


@pytest.mark.asyncio
async def test_list_notifications(client):
    await client.post(
        "/notifications/internal",
        json={
            "user_id": USER_ID,
            "type": "dispute.opened",
            "title": "Dispute Opened",
            "body": "A dispute was raised.",
        },
    )
    r = await client.get("/notifications", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.asyncio
async def test_mark_read(client):
    create_r = await client.post(
        "/notifications/internal",
        json={
            "user_id": USER_ID,
            "type": "payout.success",
            "title": "Payout Done",
            "body": "Payout processed.",
        },
    )
    notif_id = create_r.json()["id"]
    r = await client.patch(f"/notifications/{notif_id}/read", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert r.json()["is_read"] is True


@pytest.mark.asyncio
async def test_mark_all_read(client):
    for i in range(3):
        await client.post(
            "/notifications/internal",
            json={
                "user_id": USER_ID,
                "type": "escrow.completed",
                "title": f"Escrow Done {i}",
                "body": "Your escrow has been completed.",
            },
        )
    r = await client.post("/notifications/read-all", headers=AUTH_HEADER)
    assert r.status_code == 204
