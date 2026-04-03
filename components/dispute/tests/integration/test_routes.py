"""Integration tests for Dispute HTTP routes."""

from __future__ import annotations

import uuid

import pytest

AUTH_HEADER = {"Authorization": "Bearer test-token"}
ESCROW_ID = "123e4567-e89b-12d3-a456-426614174000"


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "dispute"


@pytest.mark.asyncio
async def test_raise_dispute(client):
    r = await client.post(
        f"/escrow/{ESCROW_ID}/dispute",
        json={
            "reason": "not_delivered",
            "description": "Item was not delivered as promised.",
        },
        headers=AUTH_HEADER,
    )
    assert r.status_code == 201
    data = r.json()
    assert data["reason"] == "not_delivered"
    assert data["status"] == "open"


@pytest.mark.asyncio
async def test_get_dispute(client):
    await client.post(
        f"/escrow/{ESCROW_ID}/dispute",
        json={"reason": "fraud", "description": "Fraudulent transaction detected."},
        headers=AUTH_HEADER,
    )
    r = await client.get(f"/escrow/{ESCROW_ID}/dispute", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert r.json()["reason"] == "fraud"


@pytest.mark.asyncio
async def test_resolve_dispute_seller(client):
    create_r = await client.post(
        f"/escrow/{ESCROW_ID}/dispute",
        json={
            "reason": "quality_issue",
            "description": "Quality did not meet expectations.",
        },
        headers=AUTH_HEADER,
    )
    dispute_id = create_r.json()["id"]
    r = await client.post(
        f"/escrow/{ESCROW_ID}/dispute/{dispute_id}/resolve",
        json={
            "resolution": "seller",
            "resolution_note": "Evidence supports seller claim.",
        },
        headers=AUTH_HEADER,
    )
    assert r.status_code == 202
    assert r.json()["status"] == "resolution_pending_seller"


@pytest.mark.asyncio
async def test_execute_resolution_after_queueing(client):
    create_r = await client.post(
        f"/escrow/{ESCROW_ID}/dispute",
        json={
            "reason": "quality_issue",
            "description": "Quality is clearly below the agreed standard.",
        },
        headers=AUTH_HEADER,
    )
    dispute_id = create_r.json()["id"]

    queue_r = await client.post(
        f"/escrow/{ESCROW_ID}/dispute/{dispute_id}/resolve",
        json={
            "resolution": "buyer",
            "resolution_note": "Queueing buyer-friendly resolution for worker execution.",
        },
        headers=AUTH_HEADER,
    )
    assert queue_r.status_code == 202
    assert queue_r.json()["status"] == "resolution_pending_buyer"

    execute_r = await client.post(
        f"/disputes/{dispute_id}/execute-resolution",
        json={
            "resolution": "buyer",
            "admin_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        },
    )
    assert execute_r.status_code == 200
    assert execute_r.json()["status"] == "resolved_buyer"


@pytest.mark.asyncio
async def test_execute_resolution_is_idempotent(client):
    create_r = await client.post(
        f"/escrow/{ESCROW_ID}/dispute",
        json={
            "reason": "fraud",
            "description": "Evidence supports a clear buyer-side fraudulent pattern.",
        },
        headers=AUTH_HEADER,
    )
    dispute_id = create_r.json()["id"]

    await client.post(
        f"/escrow/{ESCROW_ID}/dispute/{dispute_id}/resolve",
        json={
            "resolution": "seller",
            "resolution_note": "Queueing seller-favoring decision for execution.",
        },
        headers=AUTH_HEADER,
    )

    first = await client.post(
        f"/disputes/{dispute_id}/execute-resolution",
        json={"resolution": "seller"},
    )
    second = await client.post(
        f"/disputes/{dispute_id}/execute-resolution",
        json={"resolution": "seller"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "resolved_seller"
    assert second.json()["status"] == "resolved_seller"


@pytest.mark.asyncio
async def test_execute_resolution_requires_internal_token_when_configured(
    client,
    monkeypatch,
):
    monkeypatch.setattr("app.api.DISPUTE_INTERNAL_TOKEN", "secret-token")

    create_r = await client.post(
        f"/escrow/{ESCROW_ID}/dispute",
        json={
            "reason": "wrong_item",
            "description": "Wrong item was delivered and resolution is now queued.",
        },
        headers=AUTH_HEADER,
    )
    dispute_id = create_r.json()["id"]

    await client.post(
        f"/escrow/{ESCROW_ID}/dispute/{dispute_id}/resolve",
        json={
            "resolution": "buyer",
            "resolution_note": "Queueing to validate internal token enforcement.",
        },
        headers=AUTH_HEADER,
    )

    execute_r = await client.post(
        f"/disputes/{dispute_id}/execute-resolution",
        json={"resolution": "buyer"},
    )
    assert execute_r.status_code == 401


@pytest.mark.asyncio
async def test_resolve_requires_admin_role(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "role": "user",
            }
        ),
    )
    create_r = await client.post(
        f"/escrow/{ESCROW_ID}/dispute",
        json={"reason": "fraud", "description": "Fraudulent transaction."},
        headers=AUTH_HEADER,
    )
    dispute_id = create_r.json()["id"]
    r = await client.post(
        f"/escrow/{ESCROW_ID}/dispute/{dispute_id}/resolve",
        json={"resolution": "buyer", "resolution_note": "Buyer wins."},
        headers=AUTH_HEADER,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_mark_dispute_under_review(client):
    create_r = await client.post(
        f"/escrow/{ESCROW_ID}/dispute",
        json={
            "reason": "fraud",
            "description": "Fraudulent transaction with clear evidence.",
        },
        headers=AUTH_HEADER,
    )
    dispute_id = create_r.json()["id"]

    review_r = await client.post(
        f"/disputes/{dispute_id}/review",
        json={"note": "Escalating for moderator review."},
        headers=AUTH_HEADER,
    )
    assert review_r.status_code == 200
    assert review_r.json()["status"] == "under_review"


@pytest.mark.asyncio
async def test_cancel_dispute(client):
    create_r = await client.post(
        f"/escrow/{ESCROW_ID}/dispute",
        json={
            "reason": "wrong_item",
            "description": "Received the wrong item and want to cancel dispute.",
        },
        headers=AUTH_HEADER,
    )
    dispute_id = create_r.json()["id"]

    cancel_r = await client.post(f"/disputes/{dispute_id}/cancel", headers=AUTH_HEADER)
    assert cancel_r.status_code == 200
    assert cancel_r.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_list_disputes_for_admin(client):
    await client.post(
        f"/escrow/{ESCROW_ID}/dispute",
        json={
            "reason": "quality_issue",
            "description": "Quality was below agreed acceptance criteria.",
        },
        headers=AUTH_HEADER,
    )
    r = await client.get("/disputes", headers=AUTH_HEADER)
    assert r.status_code == 200
    payload = r.json()
    assert "items" in payload
    assert payload["total"] >= 1


@pytest.mark.asyncio
async def test_list_disputes_requires_admin_or_moderator(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "role": "user",
            }
        ),
    )

    r = await client.get("/disputes", headers=AUTH_HEADER)
    assert r.status_code == 403
