"""Pytest configuration for the Auth service tests."""

from __future__ import annotations

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
    """HTTP test client with DB, Redis, and RabbitMQ mocked."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    with patch("app.main.start_consumer", new_callable=AsyncMock):
        with patch("app.service.publish", new_callable=AsyncMock):
            with patch("app.service.set_otp", new_callable=AsyncMock):
                with patch(
                    "app.service.get_otp", new_callable=AsyncMock, return_value="123456"
                ):
                    with patch("app.service.delete_otp", new_callable=AsyncMock):
                        with patch(
                            "app.service.blacklist_token", new_callable=AsyncMock
                        ):
                            with patch(
                                "app.redis_client.is_token_blacklisted",
                                new_callable=AsyncMock,
                                return_value=False,
                            ):
                                transport = ASGITransport(app=app)
                                async with AsyncClient(
                                    transport=transport, base_url="http://test"
                                ) as ac:
                                    yield ac

    app.dependency_overrides.clear()


@pytest.fixture()
def make_user(db_session: AsyncSession):
    """Factory fixture that creates and persists a User row."""

    async def _create(
        email: str = "fixture@example.com",
        password_hash: str = "hashed",
        is_verified: bool = False,
        is_banned: bool = False,
        role: str = "user",
    ) -> User:
        u = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=password_hash,
            first_name="Test",
            last_name="User",
            is_verified=is_verified,
            is_banned=is_banned,
            role=role,
        )
        db_session.add(u)
        await db_session.flush()
        return u

    return _create
