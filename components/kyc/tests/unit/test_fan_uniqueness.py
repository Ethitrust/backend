from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.service import KYCService


@pytest.mark.asyncio
async def test_verify_fayda_otp_rejects_fan_already_claimed_by_other_user(monkeypatch):
    claim_repo = SimpleNamespace(
        get_fan_claim=AsyncMock(return_value=SimpleNamespace(user_id=uuid.uuid4())),
        create_fan_claim=AsyncMock(),
    )
    svc = KYCService(claim_repo=claim_repo)

    mock_verify_otp = AsyncMock(
        return_value={"user": {"data": {"verified": True}}, "status": "success"}
    )
    monkeypatch.setattr(
        "app.service.get_fayda_client",
        lambda: SimpleNamespace(verify_otp=mock_verify_otp),
    )
    monkeypatch.setattr("app.service.grpc_clients.set_kyc_level", AsyncMock())

    result = await svc.verify_fayda_otp(
        user_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        transaction_id="tx-1",
        otp="123456",
        fan_or_fin="1234567890123456",
    )

    assert result["status"] == "error"
    assert "already been used" in result["message"]
    mock_verify_otp.assert_not_awaited()
    claim_repo.create_fan_claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_verify_fayda_otp_claims_fan_on_first_success(monkeypatch):
    claim_repo = SimpleNamespace(
        get_fan_claim=AsyncMock(return_value=None),
        create_fan_claim=AsyncMock(),
        upsert_identity_record=AsyncMock(),
    )
    svc = KYCService(claim_repo=claim_repo)

    monkeypatch.setattr(
        svc,
        "_resolve_mirrored_transaction_id",
        AsyncMock(return_value="provider-tx-1"),
    )
    monkeypatch.setattr(
        "app.service.get_fayda_client",
        lambda: SimpleNamespace(
            verify_otp=AsyncMock(
                return_value={"user": {"data": {"verified": True}}, "status": "success"}
            )
        ),
    )
    set_kyc_level = AsyncMock()
    monkeypatch.setattr("app.service.grpc_clients.set_kyc_level", set_kyc_level)

    result = await svc.verify_fayda_otp(
        user_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        transaction_id="tx-1",
        otp="123456",
        fan_or_fin="1234567890123456",
    )

    assert result["status"] == "success"
    claim_repo.create_fan_claim.assert_awaited_once_with(
        user_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        fan_or_fin="1234567890123456",
    )
    set_kyc_level.assert_awaited_once_with("ffffffff-ffff-ffff-ffff-ffffffffffff", 1)


@pytest.mark.asyncio
async def test_verify_fayda_otp_uploads_photo_fronts_and_backs(monkeypatch):
    png_base64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/"
        "x8AAwMCAO6sN9sAAAAASUVORK5CYII="
    )

    claim_repo = SimpleNamespace(
        get_fan_claim=AsyncMock(return_value=None),
        create_fan_claim=AsyncMock(),
        upsert_identity_record=AsyncMock(),
    )
    svc = KYCService(claim_repo=claim_repo)

    monkeypatch.setattr(
        svc,
        "_resolve_mirrored_transaction_id",
        AsyncMock(return_value="provider-tx-1"),
    )
    monkeypatch.setattr(
        "app.service.get_fayda_client",
        lambda: SimpleNamespace(
            verify_otp=AsyncMock(
                return_value={
                    "user": {
                        "data": {
                            "photo": f"data:image/png;base64,{png_base64}",
                            "fronts": [png_base64],
                            "backs": [png_base64],
                            "fullName_eng": "Test User",
                            "phone": "0912345678",
                            "email": "test@example.com",
                        }
                    },
                    "status": "success",
                }
            )
        ),
    )

    captured_upload_requests: list[dict] = []

    async def _mock_generate_storage_upload_url(**kwargs):
        captured_upload_requests.append(kwargs)
        return {
            "url": f"https://storage.example/upload/{len(captured_upload_requests)}",
            "method": "PUT",
            "object_key": kwargs["object_key"],
            "expires_in_seconds": kwargs["expires_in_seconds"],
        }

    upload_binary = AsyncMock()
    set_kyc_level = AsyncMock()

    monkeypatch.setattr(
        "app.service.grpc_clients.generate_storage_upload_url",
        _mock_generate_storage_upload_url,
    )
    monkeypatch.setattr(svc, "_upload_photo_via_signed_url", upload_binary)
    monkeypatch.setattr("app.service.grpc_clients.set_kyc_level", set_kyc_level)

    result = await svc.verify_fayda_otp(
        user_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        transaction_id="tx-1",
        otp="123456",
        fan_or_fin="1234567890123456",
    )

    assert result["status"] == "success"
    assert len(captured_upload_requests) == 3
    assert all(req["content_type"] == "image/png" for req in captured_upload_requests)
    assert all(req["object_key"].endswith(".png") for req in captured_upload_requests)

    claim_repo.upsert_identity_record.assert_awaited_once()
    payload = claim_repo.upsert_identity_record.await_args.kwargs["metadata"]
    assert len(payload["front_object_keys"]) == 1
    assert len(payload["back_object_keys"]) == 1


def test_decode_base64_image_detects_content_type_and_extension():
    png_data_uri = (
        "data:image/png;base64,"
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/"
        "x8AAwMCAO6sN9sAAAAASUVORK5CYII="
    )
    payload, content_type, extension = KYCService._decode_base64_image(png_data_uri)

    assert isinstance(payload, bytes)
    assert content_type == "image/png"
    assert extension == "png"
