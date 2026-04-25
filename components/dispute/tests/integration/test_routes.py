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
        f"/dispute/{ESCROW_ID}/dispute",
        json={
            "reason": "not_delivered",
            "description": "Item was not delivered as promised.",
        },
        headers=AUTH_HEADER,
    )
    assert r.status_code == 201
    data = r.json()
    assert data["reason"] == "not_delivered"
    assert data["status"] == "open_negotiation"


@pytest.mark.asyncio
async def test_raise_dispute_route_alias(client):
    r = await client.post(
        f"/dispute/{ESCROW_ID}/dispute",
        json={
            "reason": "not_delivered",
            "description": "Item was not delivered as promised.",
        },
        headers=AUTH_HEADER,
    )
    assert r.status_code == 201
    data = r.json()
    assert data["reason"] == "not_delivered"
    assert data["status"] == "open_negotiation"


@pytest.mark.asyncio
async def test_raise_dispute_returns_escrow_not_found_detail(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.get_escrow",
        AsyncMock(side_effect=RuntimeError("Escrow not found")),
    )
    r = await client.post(
        f"/dispute/{uuid.uuid4()}/dispute",
        json={
            "reason": "fraud",
            "description": "Buyer did not receive the item after agreed delivery date.",
        },
        headers=AUTH_HEADER,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "Escrow not found"


@pytest.mark.asyncio
async def test_get_dispute(client):
    await client.post(
        f"/dispute/{ESCROW_ID}/dispute",
        json={"reason": "fraud", "description": "Fraudulent transaction detected."},
        headers=AUTH_HEADER,
    )
    r = await client.get(f"/dispute/{ESCROW_ID}/dispute", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert r.json()["reason"] == "fraud"


@pytest.mark.asyncio
async def test_request_evidence_upload_url(client):
    create_r = await client.post(
        f"/dispute/{ESCROW_ID}/dispute",
        json={
            "reason": "fraud",
            "description": "Need to upload evidence for this dispute.",
        },
        headers=AUTH_HEADER,
    )
    dispute_id = create_r.json()["id"]

    r = await client.post(
        f"/dispute/{dispute_id}/evidence/presign-upload",
        json={
            "object_key": "dispute/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/evidence.png",
            "content_type": "image/png",
            "expires_in_seconds": 600,
        },
        headers=AUTH_HEADER,
    )

    assert r.status_code == 200
    payload = r.json()
    assert payload["method"] == "PUT"
    assert payload["object_key"].endswith("evidence.png")
    assert "url" in payload and payload["url"]


@pytest.mark.asyncio
async def test_resolve_dispute_seller(client):
    create_r = await client.post(
        f"/dispute/{ESCROW_ID}/dispute",
        json={
            "reason": "quality_issue",
            "description": "Quality did not meet expectations.",
        },
        headers=AUTH_HEADER,
    )
    dispute_id = create_r.json()["id"]
    escalated = await client.post(f"/dispute/{dispute_id}/escalate", headers=AUTH_HEADER)
    assert escalated.status_code == 200

    r = await client.post(
        f"/dispute/{ESCROW_ID}/dispute/{dispute_id}/resolve",
        json={
            "resolution": "seller",
            "resolution_note": "Evidence supports seller claim.",
        },
        headers=AUTH_HEADER,
    )
    assert r.status_code == 202
    assert r.json()["status"] == "resolved_seller"


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
        f"/dispute/{ESCROW_ID}/dispute",
        json={"reason": "fraud", "description": "Fraudulent transaction."},
        headers=AUTH_HEADER,
    )
    dispute_id = create_r.json()["id"]
    r = await client.post(
        f"/dispute/{ESCROW_ID}/dispute/{dispute_id}/resolve",
        json={"resolution": "buyer", "resolution_note": "Buyer wins."},
        headers=AUTH_HEADER,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_mark_dispute_under_review(client):
    create_r = await client.post(
        f"/dispute/{ESCROW_ID}/dispute",
        json={
            "reason": "fraud",
            "description": "Fraudulent transaction with clear evidence.",
        },
        headers=AUTH_HEADER,
    )
    dispute_id = create_r.json()["id"]

    review_r = await client.post(
        f"/dispute/{dispute_id}/review",
        json={"note": "Escalating for moderator review."},
        headers=AUTH_HEADER,
    )
    assert review_r.status_code == 200
    assert review_r.json()["status"] == "escalated_mediation"


@pytest.mark.asyncio
async def test_cancel_dispute(client):
    create_r = await client.post(
        f"/dispute/{ESCROW_ID}/dispute",
        json={
            "reason": "wrong_item",
            "description": "Received the wrong item and want to cancel dispute.",
        },
        headers=AUTH_HEADER,
    )
    dispute_id = create_r.json()["id"]

    cancel_r = await client.post(f"/dispute/{dispute_id}/cancel", headers=AUTH_HEADER)
    assert cancel_r.status_code == 200
    assert cancel_r.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_list_disputes_for_admin(client):
    await client.post(
        f"/dispute/{ESCROW_ID}/dispute",
        json={
            "reason": "quality_issue",
            "description": "Quality was below agreed acceptance criteria.",
        },
        headers=AUTH_HEADER,
    )
    r = await client.get("/dispute", headers=AUTH_HEADER)
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

    r = await client.get("/dispute", headers=AUTH_HEADER)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_list_my_disputes_returns_only_current_user_items(client, monkeypatch):
    from unittest.mock import AsyncMock

    user_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    user_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    token_mock = AsyncMock(return_value={"user_id": user_a, "role": "user"})
    monkeypatch.setattr("app.grpc_clients.validate_token", token_mock)

    await client.post(
        f"/dispute/{ESCROW_ID}/dispute",
        json={
            "reason": "quality_issue",
            "description": "Raised by user A.",
        },
        headers=AUTH_HEADER,
    )

    token_mock.return_value = {"user_id": user_b, "role": "user"}
    await client.post(
        f"/dispute/{ESCROW_ID}/dispute",
        json={
            "reason": "fraud",
            "description": "Raised by user B.",
        },
        headers=AUTH_HEADER,
    )

    token_mock.return_value = {"user_id": user_a, "role": "user"}
    response = await client.get("/dispute/me", headers=AUTH_HEADER)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["raised_by"] == user_a
