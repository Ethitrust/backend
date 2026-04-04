"""Integration tests for Payout HTTP routes."""

from __future__ import annotations

import uuid

import pytest

USER_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
AUTH_HEADER = {"Authorization": "Bearer test-token"}

PAYOUT_PAYLOAD = {
    "wallet_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
    "amount": 10000,
    "currency": "ETB",
    "bank_code": "044",
    "account_number": "0123456789",
    "account_name": "Test User",
    "provider": "chapa",
}


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "payout"


@pytest.mark.asyncio
async def test_request_payout(client):
    r = await client.post("/payout/request", json=PAYOUT_PAYLOAD, headers=AUTH_HEADER)
    assert r.status_code == 201
    data = r.json()
    assert data["amount"] == 10000
    assert data["status"] == "pending"
    assert data["user_id"] == USER_ID


@pytest.mark.asyncio
async def test_get_payout_status(client):
    create_r = await client.post(
        "/payout/request", json=PAYOUT_PAYLOAD, headers=AUTH_HEADER
    )
    payout_id = create_r.json()["id"]
    r = await client.get(f"/payout/{payout_id}", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert r.json()["id"] == payout_id


@pytest.mark.asyncio
async def test_payout_not_found(client):
    r = await client.get(f"/payout/{uuid.uuid4()}", headers=AUTH_HEADER)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_payouts(client):
    await client.post("/payout/request", json=PAYOUT_PAYLOAD, headers=AUTH_HEADER)
    r = await client.get("/payout", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert r.json()["total"] == 1
