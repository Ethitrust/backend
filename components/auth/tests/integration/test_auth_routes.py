"""Integration tests for Auth service REST routes."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from app.security import decode_token

SIGNUP_PAYLOAD = {
    "email": "integration@example.com",
    "password": "SecurePass1",
    "first_name": "Integration",
    "last_name": "Test",
}


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_success(client):
    """POST /auth/signup returns 201 with user data and an access token."""
    with patch("app.service.sync_user", new_callable=AsyncMock):
        with patch("app.service.publish", new_callable=AsyncMock):
            with patch("app.service.set_otp", new_callable=AsyncMock):
                response = await client.post("/auth/signup", json=SIGNUP_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == SIGNUP_PAYLOAD["email"]
    assert "id" in body
    assert body["is_verified"] is False
    assert "access_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate(client):
    """Second signup with the same email returns 409."""
    with patch("app.service.sync_user", new_callable=AsyncMock):
        with patch("app.service.publish", new_callable=AsyncMock):
            with patch("app.service.set_otp", new_callable=AsyncMock):
                await client.post("/auth/signup", json=SIGNUP_PAYLOAD)
                response = await client.post("/auth/signup", json=SIGNUP_PAYLOAD)

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_success(client, make_user):
    """POST /auth/login returns 200 with an access_token."""
    from app.security import hash_password

    await make_user(
        email="logintest@example.com", password_hash=hash_password("SecurePass1")
    )

    response = await client.post(
        "/auth/login",
        json={"email": "logintest@example.com", "password": "SecurePass1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client, make_user):
    """POST /auth/login returns 401 for bad credentials."""
    from app.security import hash_password

    await make_user(
        email="wrongpw@example.com", password_hash=hash_password("RealPass1")
    )

    response = await client.post(
        "/auth/login",
        json={"email": "wrongpw@example.com", "password": "BadPassword99"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_success(client, make_user):
    """POST /auth/logout revokes a valid bearer token."""
    from app.security import hash_password

    await make_user(
        email="logout@example.com",
        password_hash=hash_password("SecurePass1"),
    )

    login_resp = await client.post(
        "/auth/login",
        json={"email": "logout@example.com", "password": "SecurePass1"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    with patch("app.service.blacklist_token", new_callable=AsyncMock) as mock_blacklist:
        logout_resp = await client.post(
            "/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert logout_resp.status_code == 200
    assert logout_resp.json()["detail"] == "Logged out successfully"
    mock_blacklist.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_sessions_returns_current_session(client, make_user):
    from app.security import hash_password

    await make_user(
        email="sessions@example.com",
        password_hash=hash_password("SecurePass1"),
    )

    login_resp = await client.post(
        "/auth/login",
        json={"email": "sessions@example.com", "password": "SecurePass1"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    sessions_resp = await client.get(
        "/auth/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert sessions_resp.status_code == 200
    body = sessions_resp.json()
    assert len(body) >= 1
    assert any(session["is_current"] is True for session in body)


@pytest.mark.asyncio
async def test_revoke_specific_session_by_jti(client, make_user):
    from app.security import hash_password

    await make_user(
        email="revoke-session@example.com",
        password_hash=hash_password("SecurePass1"),
    )

    login_resp = await client.post(
        "/auth/login",
        json={"email": "revoke-session@example.com", "password": "SecurePass1"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    jti = decode_token(token)["jti"]

    with patch("app.service.blacklist_token", new_callable=AsyncMock) as mock_blacklist:
        revoke_resp = await client.post(
            f"/auth/sessions/{jti}/revoke",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["detail"] == "Session revoked successfully"
    mock_blacklist.assert_awaited_once()


# ---------------------------------------------------------------------------
# Verify email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_email_full_flow(client, make_user):
    """Signup → capture OTP → POST /auth/verify-email → is_verified True."""
    captured_otp: list[str] = []

    async def capture_otp(email: str, otp: str, ttl: int = 600) -> None:
        captured_otp.append(otp)

    with patch("app.service.sync_user", new_callable=AsyncMock):
        with patch("app.service.publish", new_callable=AsyncMock):
            with patch("app.service.set_otp", side_effect=capture_otp):
                signup_resp = await client.post(
                    "/auth/signup",
                    json={
                        "email": "verify@example.com",
                        "password": "Verify123",
                        "first_name": "V",
                        "last_name": "U",
                    },
                )

    assert signup_resp.status_code == 201

    otp = captured_otp[0] if captured_otp else "123456"

    with patch("app.service.get_otp", new_callable=AsyncMock, return_value=otp):
        with patch("app.service.delete_otp", new_callable=AsyncMock):
            verify_resp = await client.post(
                "/auth/verify-email",
                json={"email": "verify@example.com", "otp": otp},
            )

    assert verify_resp.status_code == 200
    assert verify_resp.json()["detail"] == "Email verified successfully"
