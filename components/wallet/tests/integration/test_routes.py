"""Integration tests for Wallet HTTP routes."""

from __future__ import annotations

import uuid

import pytest
from app.db import Wallet

AUTH_HEADER = {"Authorization": "Bearer test-token"}
USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


async def _create_wallet(db, currency: str = "ETB") -> str:
    wallet_id = uuid.uuid4()
    wallet = Wallet(
        id=wallet_id,
        owner_id=uuid.UUID(USER_ID),
        currency=currency,
        balance=0,
        locked_balance=0,
        status="active",
    )
    db.add(wallet)
    await db.flush()
    await db.commit()
    return str(wallet_id)


class TestListWallets:
    @pytest.mark.asyncio
    async def test_get_wallet_returns_empty_list_for_new_user(self, client):
        response = await client.get("/wallet", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_get_wallet_requires_auth(self, client):
        response = await client.get("/wallet")
        assert response.status_code == 401


class TestGetBalance:
    @pytest.mark.asyncio
    async def test_get_balance_returns_zero_for_new_wallet(self, client, db):
        wallet_id = await _create_wallet(db)

        response = await client.get(f"/wallet/{wallet_id}/balance", headers=AUTH_HEADER)
        assert response.status_code == 200
        data = response.json()
        assert data["balance"] == 0
        assert data["locked_balance"] == 0

    @pytest.mark.asyncio
    async def test_get_balance_not_found_returns_404(self, client):
        fake_id = str(uuid.uuid4())
        response = await client.get(f"/wallet/{fake_id}/balance", headers=AUTH_HEADER)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_wallet_by_id(self, client, db):
        wallet_id = await _create_wallet(db)

        response = await client.get(f"/wallet/{wallet_id}", headers=AUTH_HEADER)
        assert response.status_code == 200
        assert response.json()["id"] == wallet_id


class TestFundWallet:
    @pytest.mark.asyncio
    async def test_fund_wallet_returns_payment_url(self, client, db):
        wallet_id = await _create_wallet(db)

        response = await client.post(
            f"/wallet/{wallet_id}/fund",
            json={"amount": 50000, "currency": "ETB", "provider": "chapa"},
            headers=AUTH_HEADER,
        )
        assert response.status_code == 202
        data = response.json()
        assert "payment_url" in data
        assert "transaction_ref" in data
        assert data["wallet_id"] == wallet_id

    @pytest.mark.asyncio
    async def test_fund_wallet_requires_positive_amount(self, client, db):
        wallet_id = await _create_wallet(db)

        response = await client.post(
            f"/wallet/{wallet_id}/fund",
            json={"amount": 0, "currency": "ETB"},
            headers=AUTH_HEADER,
        )
        assert response.status_code == 422  # Pydantic validation error


class TestTransactions:
    @pytest.mark.asyncio
    async def test_get_transactions_returns_paginated_empty_result(self, client, db):
        wallet_id = await _create_wallet(db)

        response = await client.get(
            f"/wallet/{wallet_id}/transactions?page=1&limit=20",
            headers=AUTH_HEADER,
        )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["service"] == "wallet"
