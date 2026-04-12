"""
Pytest fixtures for the Escrow service test suite.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.db import Base, get_db
from app.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DB = "sqlite+aiosqlite:///:memory:"
TEST_USER_ID = "11111111-1111-4111-8111-11111111111a"
TEST_RECEIVER_ID = "22222222-2222-4222-8222-22222222222b"
TEST_OUTSIDER_ID = "33333333-3333-4333-8333-33333333333c"
TEST_USER_EMAIL = "initiator@example.com"
TEST_RECEIVER_EMAIL = "receiver@example.com"
TEST_OUTSIDER_EMAIL = "outsider@example.com"
TEST_ORG_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.fixture
async def db():
    engine = create_async_engine(TEST_DB)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
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
def mock_messaging(monkeypatch):
    publish_mock = AsyncMock()
    monkeypatch.setattr("app.messaging.publish", publish_mock)
    monkeypatch.setattr("app.service.publish", publish_mock)


@pytest.fixture(autouse=True)
def mock_grpc(monkeypatch):
    async def _validate_token(token: str) -> dict:
        if token == "receiver-token":
            return {"user_id": TEST_RECEIVER_ID, "role": "user"}
        if token == "outsider-token":
            return {"user_id": TEST_OUTSIDER_ID, "role": "user"}
        return {"user_id": TEST_USER_ID, "role": "user"}

    async def _get_user_by_id(user_id: str) -> dict:
        email = TEST_USER_EMAIL
        if user_id == TEST_RECEIVER_ID:
            email = TEST_RECEIVER_EMAIL
        elif user_id == TEST_OUTSIDER_ID:
            email = TEST_OUTSIDER_EMAIL

        return {
            "user_id": user_id,
            "email": email,
            "role": "user",
            "is_verified": True,
            "is_banned": False,
            "kyc_level": 2,
        }

    async def _get_user_by_email(email: str) -> dict | None:
        if email == TEST_RECEIVER_EMAIL:
            return {
                "user_id": TEST_RECEIVER_ID,
                "email": TEST_RECEIVER_EMAIL,
                "role": "user",
                "is_verified": True,
                "is_banned": False,
                "kyc_level": 2,
            }
        if email == TEST_USER_EMAIL:
            return {
                "user_id": TEST_USER_ID,
                "email": TEST_USER_EMAIL,
                "role": "user",
                "is_verified": True,
                "is_banned": False,
                "kyc_level": 2,
            }
        return None

    async def _verify_org_key(secret_key: str) -> dict:
        if secret_key != "sk_test_org_key":
            raise PermissionError("Invalid organization API key")
        return {
            "org_id": TEST_ORG_ID,
            "public_key": "pk_test_example",
            "status": "active",
        }

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(side_effect=_validate_token),
    )
    monkeypatch.setattr(
        "app.grpc_clients.get_user_by_id",
        AsyncMock(side_effect=_get_user_by_id),
    )
    monkeypatch.setattr(
        "app.grpc_clients.get_user_by_email",
        AsyncMock(side_effect=_get_user_by_email),
    )
    monkeypatch.setattr(
        "app.grpc_clients.lock_funds",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.grpc_clients.unlock_funds",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.grpc_clients.release_funds",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.grpc_clients.create_checkout",
        AsyncMock(
            return_value={
                "payment_url": "https://checkout.example.com/pay",
                "transaction_ref": "ref123",
                "provider": "chapa",
            }
        ),
    )
    monkeypatch.setattr(
        "app.grpc_clients.get_user_wallet",
        AsyncMock(return_value="wallet-uuid-123"),
    )
    monkeypatch.setattr(
        "app.grpc_clients.check_org_membership",
        AsyncMock(side_effect=lambda user_id, org_id: user_id != TEST_OUTSIDER_ID),
    )
    monkeypatch.setattr(
        "app.grpc_clients.check_organization_exists",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "app.grpc_clients.check_email_exists",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.grpc_clients.verify_organization_secret_key",
        AsyncMock(side_effect=_verify_org_key),
    )
