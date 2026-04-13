"""Test fixtures for the Organization service."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.db import Base, get_db
from app.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DB = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db():
    engine = create_async_engine(TEST_DB)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(db):
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_grpc(monkeypatch):
    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "11111111-1111-1111-1111-111111111111",
                "role": "user",
            }
        ),
    )
    monkeypatch.setattr(
        "app.grpc_clients.get_user_by_id",
        AsyncMock(
            return_value={
                "user_id": "11111111-1111-1111-1111-111111111111",
                "email": "org-user@example.com",
                "role": "user",
                "is_verified": True,
                "is_banned": False,
                "kyc_level": 2,
            }
        ),
    )
    monkeypatch.setattr(
        "app.grpc_clients.ensure_owner_wallet",
        AsyncMock(return_value="55555555-5555-5555-5555-555555555555"),
    )
    monkeypatch.setattr(
        "app.grpc_clients.get_wallet_balance",
        AsyncMock(
            return_value={
                "balance": 100_000,
                "locked_balance": 10_000,
                "currency": "ETB",
            }
        ),
    )
    monkeypatch.setattr(
        "app.grpc_clients.deduct_wallet_balance",
        AsyncMock(
            return_value={
                "success": True,
                "new_balance": 95_000,
                "message": "Deducted",
            }
        ),
    )


@pytest.fixture(autouse=True)
def mock_messaging(monkeypatch):
    publish_mock = AsyncMock()
    monkeypatch.setattr("app.messaging.publish", publish_mock)
    monkeypatch.setattr("app.service.publish", publish_mock)
    return publish_mock
