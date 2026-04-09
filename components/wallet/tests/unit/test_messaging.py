"""Unit tests for wallet RabbitMQ message handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from app import messaging


class _DummySession:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_handle_organization_created_creates_wallet(monkeypatch):
    dummy_session = _DummySession()
    monkeypatch.setattr("app.messaging.AsyncSessionLocal", lambda: dummy_session)

    repo_instance = MagicMock()
    monkeypatch.setattr("app.messaging.WalletRepository", lambda session: repo_instance)

    wallet = MagicMock()
    wallet.id = "wallet-id"
    service_instance = MagicMock()
    service_instance.create_wallet = AsyncMock(return_value=wallet)
    monkeypatch.setattr("app.messaging.WalletService", lambda repo: service_instance)

    await messaging._handle_organization_created(
        {"org_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}
    )

    service_instance.create_wallet.assert_awaited_once()
    _, currency = service_instance.create_wallet.await_args.args
    assert currency == "ETB"
    dummy_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_organization_created_ignores_invalid_org_id(monkeypatch):
    service_instance = MagicMock()
    service_instance.create_wallet = AsyncMock()
    monkeypatch.setattr("app.messaging.WalletService", lambda repo: service_instance)

    await messaging._handle_organization_created({"org_id": "not-a-uuid"})

    service_instance.create_wallet.assert_not_called()


@pytest.mark.asyncio
async def test_handle_payment_completed_applies_funding_and_commits(monkeypatch):
    dummy_session = _DummySession()
    monkeypatch.setattr("app.messaging.AsyncSessionLocal", lambda: dummy_session)

    repo_instance = MagicMock()
    monkeypatch.setattr("app.messaging.WalletRepository", lambda session: repo_instance)

    tx = MagicMock()
    tx.id = "tx-123"
    service_instance = MagicMock()
    service_instance.apply_payment_completed = AsyncMock(return_value=tx)
    monkeypatch.setattr("app.messaging.WalletService", lambda repo: service_instance)

    await messaging._handle_payment_completed(
        {
            "wallet_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "reference": "pay_ref_123",
            "amount": 10000,
            "currency": "ETB",
        }
    )

    service_instance.apply_payment_completed.assert_awaited_once()
    dummy_session.commit.assert_awaited_once()
