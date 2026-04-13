"""Integration tests for Fee HTTP routes."""

from __future__ import annotations

import uuid

import pytest

ESCROW_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "fee"


@pytest.mark.asyncio
async def test_calculate_fee_buyer(client):
    r = await client.post("/fee/calculate", json={"amount": 100000, "who_pays": "buyer"})
    assert r.status_code == 200
    data = r.json()
    assert data["fee_amount"] == 1000  # capped by default max fee (10 birr)
    assert data["buyer_fee"] == 1000
    assert data["seller_fee"] == 0


@pytest.mark.asyncio
async def test_calculate_fee_both(client):
    r = await client.post("/fee/calculate", json={"amount": 100000, "who_pays": "split"})
    assert r.status_code == 200
    data = r.json()
    assert data["buyer_fee"] + data["seller_fee"] == data["fee_amount"]


@pytest.mark.asyncio
async def test_record_fee(client):
    r = await client.post(
        "/fee/record",
        json={
            "escrow_id": ESCROW_ID,
            "fee_amount": 1500,
            "currency": "ETB",
            "paid_by": "buyer",
            "fee_type": "escrow_fee",
        },
    )
    assert r.status_code == 201
    assert r.json()["status"] == "collected"


@pytest.mark.asyncio
async def test_refund_fee(client):
    await client.post(
        "/fee/record",
        json={
            "escrow_id": ESCROW_ID,
            "fee_amount": 1500,
            "currency": "ETB",
            "paid_by": "buyer",
            "fee_type": "escrow_fee",
        },
    )
    r = await client.post(f"/fee/refund/{ESCROW_ID}")
    assert r.status_code == 200
    entries = r.json()
    assert all(e["status"] == "refunded" for e in entries)
