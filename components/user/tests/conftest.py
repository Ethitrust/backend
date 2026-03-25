"""Pytest configuration for the User service tests."""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from app.db import Base, User, get_db
from app.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestSessionLocal = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture()
async def client(db_session: AsyncSession):
    """HTTP test client with DB and external deps mocked."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    with (
        patch("app.main.start_consumer", new_callable=AsyncMock),
        patch(
            "app.grpc_clients.validate_token",
            new_callable=AsyncMock,
            return_value={
                "user_id": str(uuid.UUID(int=0)),
                "role": "user",
                "is_verified": True,
                "is_banned": False,
            },
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()


@pytest.fixture()
def mock_user(db_session: AsyncSession):
    """Factory fixture returning a persisted User row."""

    async def _create(
        email: str = "test@example.com",
        user_id: uuid.UUID | None = None,
    ) -> User:
        u = User(
            id=user_id or uuid.UUID(int=0),
            email=email,
            password_hash="hashed",
            first_name="Test",
            last_name="User",
            role="user",
            is_verified=True,
            is_banned=False,
            kyc_level=0,
        )
        db_session.add(u)
        await db_session.flush()
        return u

    return _create
