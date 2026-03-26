"""Test fixtures for the KYC service."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./kyc_test.db")

from app.db import Base, engine, init_db
from app.fayda_verify import FaydaVerify
from app.main import app
from app.service import _cache
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
async def reset_kyc_db():
    await init_db()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture(autouse=True)
def mock_grpc(monkeypatch):
    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                "role": "user",
            }
        ),
    )
    monkeypatch.setattr(
        "app.grpc_clients.set_kyc_level",
        AsyncMock(return_value={"success": True, "kyc_level": 2}),
    )
    monkeypatch.setattr(
        "app.grpc_clients.generate_storage_upload_url",
        AsyncMock(
            return_value={
                "url": "https://storage.example/upload",
                "method": "PUT",
                "object_key": "kyc/ffffffff-ffff-ffff-ffff-ffffffffffff/fayda/photo.jpg",
                "expires_in_seconds": 900,
            }
        ),
    )
    monkeypatch.setattr(
        "app.grpc_clients.generate_storage_download_url",
        AsyncMock(
            return_value={
                "url": "https://storage.example/download",
                "method": "GET",
                "object_key": "kyc/ffffffff-ffff-ffff-ffff-ffffffffffff/fayda/photo.jpg",
                "expires_in_seconds": 900,
            }
        ),
    )
    monkeypatch.setattr(
        "app.fayda_verify.FaydaVerify.send_otp",
        AsyncMock(
            return_value={
                "message": "OTP sent successfully",
                "transactionId": "tx-001",
            }
        ),
    )
    monkeypatch.setattr(
        "app.fayda_verify.FaydaVerify.verify_otp",
        AsyncMock(
            return_value={
                "message": "OTP verified successfully",
                "status": "success",
                "user": {
                    "data": {
                        "photo": (
                            "data:image/png;base64,"
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/"
                            "x8AAwMCAO6sN9sAAAAASUVORK5CYII="
                        ),
                        "fronts": [
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/"
                            "x8AAwMCAO6sN9sAAAAASUVORK5CYII="
                        ],
                        "backs": [
                            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/"
                            "x8AAwMCAO6sN9sAAAAASUVORK5CYII="
                        ],
                        "fullName_eng": "Test User",
                        "phone": "0912345678",
                        "email": "test@example.com",
                        "UIN": "291234520491",
                    }
                },
            }
        ),
    )
    monkeypatch.setattr(
        "app.fayda_verify.FaydaVerify.refresh_token",
        AsyncMock(return_value={"accessToken": "new-token"}),
    )
    # Ensure get_fayda_client() returns a real instance without hitting the network
    monkeypatch.setattr(
        "app.fayda_verify.get_fayda_client",
        lambda: FaydaVerify(),
    )
    monkeypatch.setattr(
        "app.service.get_fayda_client",
        lambda: FaydaVerify(),
    )
    monkeypatch.setattr(
        "app.service.KYCService._upload_photo_via_signed_url",
        AsyncMock(),
    )


@pytest.fixture(autouse=True)
def mock_kyc_provider(monkeypatch):
    async def _mock_call_provider(_self, endpoint, params):
        return {
            "status": "success",
            "data": {
                "endpoint": endpoint,
                "verified": True,
                **params,
            },
        }

    monkeypatch.setattr(
        "app.service.KYCService._call_provider",
        _mock_call_provider,
    )


@pytest.fixture(autouse=True)
def mock_redis_alias_store(monkeypatch):
    store: dict[
        str, tuple[str, str]
    ] = {}  # mirrored_id -> (provider_tx_id, fan_or_fin)

    async def _mock_set_tx_alias(
        mirrored_id: str, provider_transaction_id: str, fan_or_fin: str
    ) -> None:
        store[mirrored_id] = (provider_transaction_id, fan_or_fin)

    async def _mock_get_and_delete_tx_alias(
        mirrored_transaction_id: str, fan_or_fin: str
    ):
        entry = store.get(mirrored_transaction_id)
        if entry is None:
            return None
        provider_tx_id, stored_fan_or_fin = entry
        if stored_fan_or_fin != fan_or_fin:
            return None
        del store[mirrored_transaction_id]
        return provider_tx_id

    monkeypatch.setattr("app.redis_client.set_tx_alias", _mock_set_tx_alias)
    monkeypatch.setattr(
        "app.redis_client.get_and_delete_tx_alias", _mock_get_and_delete_tx_alias
    )
    monkeypatch.setattr("app.service.set_tx_alias", _mock_set_tx_alias)
    monkeypatch.setattr(
        "app.service.get_and_delete_tx_alias", _mock_get_and_delete_tx_alias
    )
    yield
    store.clear()


@pytest.fixture(autouse=True)
def clear_kyc_cache():
    _cache.clear()
    yield
    _cache.clear()
