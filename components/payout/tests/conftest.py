"""Test fixtures for the Payout service."""

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
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def client(db):
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_rabbitmq(monkeypatch):
    monkeypatch.setattr("app.messaging.publish", AsyncMock())


@pytest.fixture(autouse=True)
def mock_grpc(monkeypatch):
    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "role": "user",
            }
        ),
    )
    monkeypatch.setattr(
        "app.grpc_clients.get_user_by_id",
        AsyncMock(
            return_value={
                "user_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "email": "user@example.com",
                "role": "user",
                "is_verified": True,
                "is_banned": False,
                "kyc_level": 2,
            }
        ),
    )
    monkeypatch.setattr(
        "app.grpc_clients.deduct_wallet_balance",
        AsyncMock(return_value={"success": True, "new_balance": 50000}),
    )
    monkeypatch.setattr(
        "app.grpc_clients.initiate_bank_transfer",
        AsyncMock(
            return_value={"provider_ref": "PAY-TEST-001", "status": "processing"}
        ),
    )
