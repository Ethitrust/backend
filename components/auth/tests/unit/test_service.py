"""Unit tests for AuthService."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models import LoginRequest, SignupRequest
from app.security import (
    create_access_token,
    decode_token,
    get_current_user_id,
    hash_password,
)
from app.service import AuthService
from fastapi import HTTPException
from jose import JWTError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    email: str = "test@example.com",
    is_verified: bool = False,
    is_banned: bool = False,
    role: str = "user",
    **kwargs,
) -> MagicMock:
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = email
    user.password_hash = hash_password("ValidPass1")
    user.is_verified = is_verified
    user.is_banned = is_banned
    user.role = role
    for k, v in kwargs.items():
        setattr(user, k, v)
    return user


def _make_repo(user=None) -> MagicMock:
    repo = MagicMock()
    repo.get_by_email = AsyncMock(return_value=user)
    repo.get_by_id = AsyncMock(return_value=user)
    repo.create_user = AsyncMock(return_value=user or _make_user())
    repo.delete_user = AsyncMock(return_value=True)
    repo.set_verified = AsyncMock()
    repo.update_password = AsyncMock()
    repo.create_session = AsyncMock()
    repo.list_sessions = AsyncMock(return_value=[])
    repo.get_session_by_jti = AsyncMock(return_value=None)
    repo.revoke_session = AsyncMock(return_value=True)
    return repo


# ---------------------------------------------------------------------------
# Signup tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signup_success():
    repo = _make_repo(user=None)
    service = AuthService(repo)

    req = SignupRequest(
        email="new@example.com",
        password="ValidPass1",
        first_name="Jane",
        last_name="Doe",
    )

    with patch("app.service.sync_user", new_callable=AsyncMock) as mock_sync:
        with patch("app.service.publish", new_callable=AsyncMock) as mock_pub:
            with patch("app.service.set_otp", new_callable=AsyncMock) as mock_otp:
                user = await service.signup(req)

    mock_sync.assert_awaited_once()
    mock_otp.assert_awaited_once()
    mock_pub.assert_awaited_once()
    assert user is not None


@pytest.mark.asyncio
async def test_signup_and_login_success():
    created_user = _make_user(
        email="combo@example.com",
        password_hash=hash_password("ValidPass1"),
    )
    repo = _make_repo(user=None)
    repo.create_user = AsyncMock(return_value=created_user)
    repo.get_by_email = AsyncMock(side_effect=[None, created_user])
    service = AuthService(repo)

    req = SignupRequest(
        email="combo@example.com",
        password="ValidPass1",
        first_name="Jane",
        last_name="Doe",
    )

    with patch("app.service.sync_user", new_callable=AsyncMock):
        with patch("app.service.publish", new_callable=AsyncMock):
            with patch("app.service.set_otp", new_callable=AsyncMock):
                user, token = await service.signup_and_login(req)

    assert user is not None
    assert isinstance(token, str)
    payload = decode_token(token)
    assert payload["sub"] == str(user.id)


@pytest.mark.asyncio
async def test_signup_duplicate_email():
    existing_user = _make_user(email="dup@example.com")
    repo = _make_repo(user=existing_user)
    service = AuthService(repo)

    req = SignupRequest(
        email="dup@example.com",
        password="ValidPass1",
        first_name="Jane",
        last_name="Doe",
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.signup(req)

    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Login tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_success():
    user = _make_user(email="login@example.com", is_banned=False)
    repo = _make_repo(user=user)
    service = AuthService(repo)

    req = LoginRequest(email="login@example.com", password="ValidPass1")
    token = await service.login(req)
    assert isinstance(token, str)
    payload = decode_token(token)
    assert payload["sub"] == str(user.id)


@pytest.mark.asyncio
async def test_login_wrong_password():
    user = _make_user()
    repo = _make_repo(user=user)
    service = AuthService(repo)

    req = LoginRequest(email=user.email, password="WrongPassword99")
    with pytest.raises(HTTPException) as exc_info:
        await service.login(req)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_login_banned_user():
    user = _make_user(is_banned=True)
    repo = _make_repo(user=user)
    service = AuthService(repo)

    req = LoginRequest(email=user.email, password="ValidPass1")
    with pytest.raises(HTTPException) as exc_info:
        await service.login(req)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Verify email tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_email_success():
    user = _make_user()
    repo = _make_repo(user=user)
    service = AuthService(repo)

    with patch("app.service.get_otp", new_callable=AsyncMock, return_value="654321"):
        with patch(
            "app.service.update_email_verifiication_status", new_callable=AsyncMock
        ) as mock_sync:
            with patch("app.service.delete_otp", new_callable=AsyncMock) as mock_del:
                await service.verify_email(email=user.email, otp="654321")

    mock_sync.assert_awaited_once_with(user_id=str(user.id), is_verified=True)
    repo.set_verified.assert_awaited_once_with(user.id)
    mock_del.assert_awaited_once_with(user.email)


@pytest.mark.asyncio
async def test_verify_email_invalid_otp():
    user = _make_user()
    repo = _make_repo(user=user)
    service = AuthService(repo)

    with patch("app.service.get_otp", new_callable=AsyncMock, return_value="999999"):
        with pytest.raises(HTTPException) as exc_info:
            await service.verify_email(email=user.email, otp="000000")

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# JWT tests
# ---------------------------------------------------------------------------


def test_decode_token_correct_sub():
    user_id = str(uuid.uuid4())
    token = create_access_token(sub=user_id, role="user")
    payload = decode_token(token)
    assert payload["sub"] == user_id
    assert payload["role"] == "user"
    assert isinstance(payload.get("jti"), str)
    assert payload["jti"]


def test_decode_tampered_token_raises():
    token = create_access_token(sub=str(uuid.uuid4()))
    tampered = token[:-5] + "XXXXX"
    with pytest.raises(JWTError):
        decode_token(tampered)


@pytest.mark.asyncio
async def test_logout_blacklists_token_with_ttl():
    repo = _make_repo(user=None)
    service = AuthService(repo)
    token = create_access_token(sub=str(uuid.uuid4()), role="user", exp=5)

    with patch("app.service.blacklist_token", new_callable=AsyncMock) as mock_blacklist:
        await service.logout(token)

    mock_blacklist.assert_awaited_once()
    args = mock_blacklist.await_args.args
    kwargs = mock_blacklist.await_args.kwargs

    jti_arg = args[0] if args else kwargs.get("jti")
    ttl_arg = kwargs.get("ttl")
    if ttl_arg is None and len(args) > 1:
        ttl_arg = args[1]

    payload = decode_token(token)
    assert jti_arg == payload.get("jti")
    assert isinstance(ttl_arg, int)
    assert ttl_arg > 0


@pytest.mark.asyncio
async def test_logout_invalid_token_raises_401():
    repo = _make_repo(user=None)
    service = AuthService(repo)

    with pytest.raises(HTTPException) as exc_info:
        await service.logout("not-a-jwt")

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_id_rejects_blacklisted_token():
    token = create_access_token(sub=str(uuid.uuid4()), role="user")
    payload = decode_token(token)
    jti = payload["jti"]

    with patch(
        "app.redis_client.is_token_blacklisted",
        new_callable=AsyncMock,
        return_value=True,
    ) as mocked_blacklist:
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(f"Bearer {token}")

    mocked_blacklist.assert_awaited_once_with(jti)
    assert exc_info.value.status_code == 401
    assert "revoked" in exc_info.value.detail.lower()
