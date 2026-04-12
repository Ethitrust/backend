"""Integration tests for Notification HTTP routes."""

from __future__ import annotations

import uuid

import pytest
from app.models import NotificationCreate
from app.repository import NotificationRepository
from app.service import NotificationService

AUTH_HEADER = {"Authorization": "Bearer test-token"}
USER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "notification"


@pytest.mark.asyncio
async def test_list_notifications_includes_invitation_id(client, db):
    svc = NotificationService(NotificationRepository(db))
    await svc.notify(
        NotificationCreate(
            user_id=uuid.UUID(USER_ID),
            type="escrow.invite_received",
            title="Escrow Invitation",
            body="You have received a new escrow invitation.",
            metadata={"escrow_id": "invite-escrow-123"},
        )
    )
    await db.commit()

    response = await client.get("/notifications", headers=AUTH_HEADER)

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["type"] == "escrow.invite_received"
    assert payload[0]["invitation_id"] == "invite-escrow-123"


@pytest.mark.asyncio
async def test_list_notifications_includes_dispute_id(client, db):
    svc = NotificationService(NotificationRepository(db))
    await svc.notify(
        NotificationCreate(
            user_id=uuid.UUID(USER_ID),
            type="dispute.opened",
            title="Dispute Opened",
            body="Your counterparty raised a dispute on this escrow.",
            metadata={"dispute_id": "dispute-987"},
        )
    )
    await db.commit()

    response = await client.get("/notifications", headers=AUTH_HEADER)

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["type"] == "dispute.opened"
    assert payload[0]["dispute_id"] == "dispute-987"
