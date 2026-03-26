"""Integration tests for KYC HTTP routes."""

from __future__ import annotations

import pytest

AUTH_HEADER = {"Authorization": "Bearer test-token"}


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "kyc"


@pytest.mark.asyncio
async def test_lookup_drivers_license(client):
    r = await client.post(
        "/kyc/drivers-license",
        json={"license_number": "ABC123456"},
        headers=AUTH_HEADER,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_lookup_tin(client):
    r = await client.post(
        "/kyc/tin", json={"tin": "12345678-0001"}, headers=AUTH_HEADER
    )
    assert r.status_code == 200
    assert r.json()["status"] == "success"


@pytest.mark.asyncio
async def test_cache_hit_on_second_call(client):
    payload = {"license_number": "CACHED-001"}
    r1 = await client.post("/kyc/drivers-license", json=payload, headers=AUTH_HEADER)
    r2 = await client.post("/kyc/drivers-license", json=payload, headers=AUTH_HEADER)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["cached"] is True


@pytest.mark.asyncio
async def test_fayda_send_otp(client):
    r = await client.post(
        "/kyc/fayda/send-otp",
        json={"fan_or_fin": "1234567890123456"},
        headers=AUTH_HEADER,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    assert data["data"]["transactionId"] != "tx-001"


@pytest.mark.asyncio
async def test_fayda_verify_otp(client):
    send_resp = await client.post(
        "/kyc/fayda/send-otp",
        json={"fan_or_fin": "1234567890123456"},
        headers=AUTH_HEADER,
    )
    mirrored_tx_id = send_resp.json()["data"]["transactionId"]

    r = await client.post(
        "/kyc/fayda/verify-otp",
        json={
            "transaction_id": mirrored_tx_id,
            "otp": "123456",
            "fan_or_fin": "1234567890123456",
        },
        headers=AUTH_HEADER,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_get_my_photo_url(client):
    send_resp = await client.post(
        "/kyc/fayda/send-otp",
        json={"fan_or_fin": "1234567890123456"},
        headers=AUTH_HEADER,
    )
    mirrored_tx_id = send_resp.json()["data"]["transactionId"]

    verify_resp = await client.post(
        "/kyc/fayda/verify-otp",
        json={
            "transaction_id": mirrored_tx_id,
            "otp": "123456",
            "fan_or_fin": "1234567890123456",
        },
        headers=AUTH_HEADER,
    )
    assert verify_resp.status_code == 200

    r = await client.get("/kyc/me/photo-url", headers=AUTH_HEADER)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "success"
    assert "url" in data["data"]


@pytest.mark.asyncio
async def test_fayda_send_otp_forbidden_after_verification(client):
    send_resp = await client.post(
        "/kyc/fayda/send-otp",
        json={"fan_or_fin": "1234567890123456"},
        headers=AUTH_HEADER,
    )
    assert send_resp.status_code == 200

    mirrored_tx_id = send_resp.json()["data"]["transactionId"]
    verify_resp = await client.post(
        "/kyc/fayda/verify-otp",
        json={
            "transaction_id": mirrored_tx_id,
            "otp": "123456",
            "fan_or_fin": "1234567890123456",
        },
        headers=AUTH_HEADER,
    )
    assert verify_resp.status_code == 200

    repeat_send = await client.post(
        "/kyc/fayda/send-otp",
        json={"fan_or_fin": "1234567890123456"},
        headers=AUTH_HEADER,
    )
    assert repeat_send.status_code == 403
    assert "already completed" in repeat_send.json()["detail"].lower()


@pytest.mark.asyncio
async def test_fayda_verify_otp_forbidden_after_verification(client):
    send_resp = await client.post(
        "/kyc/fayda/send-otp",
        json={"fan_or_fin": "1234567890123456"},
        headers=AUTH_HEADER,
    )
    assert send_resp.status_code == 200

    mirrored_tx_id = send_resp.json()["data"]["transactionId"]
    verify_resp = await client.post(
        "/kyc/fayda/verify-otp",
        json={
            "transaction_id": mirrored_tx_id,
            "otp": "123456",
            "fan_or_fin": "1234567890123456",
        },
        headers=AUTH_HEADER,
    )
    assert verify_resp.status_code == 200

    repeat_verify = await client.post(
        "/kyc/fayda/verify-otp",
        json={
            "transaction_id": mirrored_tx_id,
            "otp": "123456",
            "fan_or_fin": "1234567890123456",
        },
        headers=AUTH_HEADER,
    )
    assert repeat_verify.status_code == 403
    assert "already completed" in repeat_verify.json()["detail"].lower()
