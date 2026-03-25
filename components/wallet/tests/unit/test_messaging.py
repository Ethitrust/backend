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
