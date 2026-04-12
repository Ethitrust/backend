"""Test fixtures for the Admin service."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./admin_test.db")

from app.db import Base, get_db
from app.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

TEST_DB = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(
        TEST_DB,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def client(db: AsyncSession):
    async def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_grpc(monkeypatch):
    async def _mock_get_user_by_id(user_id: str):
        return {
            "user_id": user_id,
            "email": "user@example.com",
            "role": "user",
            "is_verified": True,
            "is_banned": False,
            "kyc_level": 2,
        }

    async def _mock_ban_user(user_id, ban: bool, reason: str):
        return {
            "id": str(user_id),
            "is_active": not ban,
        }

    async def _mock_update_verification(user_id, is_verified: bool):
        return {
            "id": str(user_id),
            "is_verified": is_verified,
        }

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "role": "admin",
            }
        ),
    )
    monkeypatch.setattr(
        "app.grpc_clients.get_user_by_id",
        AsyncMock(side_effect=_mock_get_user_by_id),
    )
    monkeypatch.setattr(
        "app.grpc_clients.get_all_users",
        AsyncMock(
            return_value=[
                {
                    "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "email": "user@example.com",
                    "role": "user",
                    "is_active": True,
                },
            ]
        ),
    )
    monkeypatch.setattr(
        "app.grpc_clients.update_user_role",
        AsyncMock(
            return_value={
                "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "role": "moderator",
            }
        ),
    )
    monkeypatch.setattr(
        "app.grpc_clients.ban_user",
        AsyncMock(side_effect=_mock_ban_user),
    )
    monkeypatch.setattr(
        "app.grpc_clients.update_user_verification",
        AsyncMock(side_effect=_mock_update_verification),
    )
    monkeypatch.setattr(
        "app.grpc_clients.get_platform_stats",
        AsyncMock(
            return_value={
                "total_users": 100,
                "total_escrows": 50,
                "total_transactions": 80,
                "total_volume": 500000,
            }
        ),
    )


@pytest.fixture(autouse=True)
def mock_audit_emission(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr("app.grpc_clients.emit_audit_log", mock)
    return mock


@pytest.fixture(autouse=True)
def mock_dispute_clients(monkeypatch):
    dispute_id = "11111111-1111-1111-1111-111111111111"
    escrow_id = "22222222-2222-2222-2222-222222222222"
    raised_by = "33333333-3333-3333-3333-333333333333"

    list_mock = AsyncMock(
        return_value={
            "items": [
                {
                    "id": dispute_id,
                    "escrow_id": escrow_id,
                    "raised_by": raised_by,
                    "reason": "fraud",
                    "status": "open",
                    "created_at": "2026-03-29T10:00:00Z",
                }
            ],
            "total": 1,
            "page": 1,
            "limit": 20,
            "pages": 1,
        }
    )
    review_mock = AsyncMock(
        return_value={
            "id": dispute_id,
            "escrow_id": escrow_id,
            "raised_by": raised_by,
            "reason": "fraud",
            "status": "under_review",
            "created_at": "2026-03-29T10:00:00Z",
        }
    )
    request_resolution_mock = AsyncMock(
        return_value={
            "id": dispute_id,
            "escrow_id": escrow_id,
            "raised_by": raised_by,
            "reason": "fraud",
            "status": "resolution_pending_buyer",
            "created_at": "2026-03-29T10:00:00Z",
        }
    )
    execute_resolution_mock = AsyncMock(
        return_value={
            "id": dispute_id,
            "escrow_id": escrow_id,
            "raised_by": raised_by,
            "reason": "fraud",
            "status": "resolved_buyer",
            "created_at": "2026-03-29T10:00:00Z",
        }
    )
    refund_fee_mock = AsyncMock(
        return_value=[
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "escrow_id": escrow_id,
                "fee_type": "escrow_fee",
                "amount": 150,
                "currency": "ETB",
                "paid_by": "buyer",
                "status": "refunded",
                "created_at": "2026-03-29T10:01:00Z",
            }
        ]
    )
    get_escrow_mock = AsyncMock(
        return_value={
            "escrow_id": escrow_id,
            "status": "disputed",
            "escrow_type": "onetime",
            "initiator_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "receiver_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "amount": 450000,
            "currency": "ETB",
        }
    )

    monkeypatch.setattr("app.grpc_clients.list_disputes", list_mock)
    monkeypatch.setattr("app.grpc_clients.mark_dispute_under_review", review_mock)
    monkeypatch.setattr("app.grpc_clients.request_dispute_resolution", request_resolution_mock)
    monkeypatch.setattr("app.grpc_clients.execute_dispute_resolution", execute_resolution_mock)
    monkeypatch.setattr("app.grpc_clients.refund_fee_for_escrow", refund_fee_mock)
    monkeypatch.setattr("app.grpc_clients.get_escrow", get_escrow_mock)

    return {
        "list_disputes": list_mock,
        "mark_dispute_under_review": review_mock,
        "request_dispute_resolution": request_resolution_mock,
        "execute_dispute_resolution": execute_resolution_mock,
        "refund_fee_for_escrow": refund_fee_mock,
        "get_escrow": get_escrow_mock,
    }


@pytest.fixture(autouse=True)
def mock_payout_clients(monkeypatch):
    payout_id = "55555555-5555-5555-5555-555555555555"
    user_id = "66666666-6666-6666-6666-666666666666"
    wallet_id = "77777777-7777-7777-7777-777777777777"

    list_mock = AsyncMock(
        return_value={
            "items": [
                {
                    "id": payout_id,
                    "user_id": user_id,
                    "wallet_id": wallet_id,
                    "amount": 125000,
                    "currency": "ETB",
                    "status": "failed",
                    "provider": "telebirr",
                    "provider_ref": "payout-ref-001",
                    "failure_reason": "insufficient_provider_liquidity",
                    "created_at": "2026-03-29T11:00:00Z",
                }
            ],
            "total": 1,
            "page": 1,
            "limit": 20,
            "pages": 1,
        }
    )

    retry_mock = AsyncMock(
        return_value={
            "id": payout_id,
            "user_id": user_id,
            "wallet_id": wallet_id,
            "amount": 125000,
            "currency": "ETB",
            "status": "processing",
            "provider": "telebirr",
            "provider_ref": "payout-ref-001",
            "failure_reason": None,
            "created_at": "2026-03-29T11:00:00Z",
        }
    )

    monkeypatch.setattr("app.grpc_clients.list_payouts", list_mock)
    monkeypatch.setattr("app.grpc_clients.retry_payout_transfer", retry_mock)

    return {
        "list_payouts": list_mock,
        "retry_payout_transfer": retry_mock,
    }
