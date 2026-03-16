"""Integration tests for transfer endpoints in Payment Provider API."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


class _FakeTransferResult:
    def __init__(self, success: bool, provider_ref: str, message: str):
        self.success = success
        self.provider_ref = provider_ref
        self.message = message


class _FakeProvider:
    def __init__(self) -> None:
        self.initiate_transfer = AsyncMock(
            return_value=_FakeTransferResult(True, "TRF-123", "Transfer initiated")
        )
        self.verify_transfer = AsyncMock(return_value=True)


@pytest.mark.asyncio
async def test_initiate_transfer_route_success(client, monkeypatch):
    provider = _FakeProvider()
    monkeypatch.setattr("app.api.get_provider", lambda name: provider)

    response = await client.post(
        "/payment/transfer",
        json={
            "account_name": "Test User",
            "account_number": "0123456789",
            "amount": 10000,
            "currency": "ETB",
            "reference": "payout-ref-1",
            "bank_code": "044",
            "provider": "chapa",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["provider_ref"] == "TRF-123"


@pytest.mark.asyncio
async def test_verify_transfer_route_success(client, monkeypatch):
    provider = _FakeProvider()
    monkeypatch.setattr("app.api.get_provider", lambda name: provider)

    response = await client.get("/payment/transfer/verify/TRF-123?provider=chapa")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider_ref"] == "TRF-123"
    assert payload["success"] is True
    assert payload["status"] == "success"
