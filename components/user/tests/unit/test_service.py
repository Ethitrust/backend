"""Unit tests for UserService."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models import UserUpdateRequest
from app.service import UserService
from fastapi import HTTPException


def _make_user(**kwargs) -> MagicMock:
    defaults = dict(
        id=uuid.uuid4(),
        email="user@example.com",
        first_name="John",
        last_name="Doe",
        phone=None,
        role="user",
        is_verified=True,
        is_banned=False,
        kyc_level=0,
    )
    defaults.update(kwargs)
    user = MagicMock(**defaults)
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


def _make_repo(user=None) -> MagicMock:
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=user)
    repo.get_by_email = AsyncMock(return_value=user)
    repo.update = AsyncMock(side_effect=lambda u, d: u)
    return repo


@pytest.mark.asyncio
async def test_get_by_email_returns_none_for_unknown():
    repo = _make_repo(user=None)
    service = UserService(repo)
    result = await service.get_by_email("nobody@example.com")
    assert result is None
    repo.get_by_email.assert_awaited_once_with("nobody@example.com")


@pytest.mark.asyncio
async def test_get_by_id_raises_404_when_missing():
    repo = _make_repo(user=None)
    service = UserService(repo)
    with pytest.raises(HTTPException) as exc_info:
        await service.get_by_id(uuid.uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_profile_persists():
    user = _make_user(first_name="Old")
    repo = _make_repo(user=user)

    # repo.update mutates the user
    async def _update(u, d):
        for k, v in d.items():
            setattr(u, k, v)
        return u

    repo.update = AsyncMock(side_effect=_update)
    service = UserService(repo)

    req = UserUpdateRequest(first_name="New", last_name=None, phone=None)
    updated = await service.update_profile(user.id, req)

    repo.update.assert_awaited_once()
    assert updated.first_name == "New"


@pytest.mark.asyncio
async def test_set_kyc_level_increments():
    user = _make_user(kyc_level=0)
    repo = _make_repo(user=user)

    async def _update(u, d):
        for k, v in d.items():
            setattr(u, k, v)
        return u

    repo.update = AsyncMock(side_effect=_update)
    service = UserService(repo)

    result = await service.set_kyc_level(user.id, 2)
    assert result.kyc_level == 2


@pytest.mark.asyncio
async def test_set_kyc_level_rejects_invalid():
    repo = _make_repo(user=_make_user())
    service = UserService(repo)
    with pytest.raises(HTTPException) as exc_info:
        await service.set_kyc_level(uuid.uuid4(), 99)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_ban_user():
    user = _make_user(is_banned=False)
    repo = _make_repo(user=user)

    async def _update(u, d):
        for k, v in d.items():
            setattr(u, k, v)
        return u

    repo.update = AsyncMock(side_effect=_update)
    service = UserService(repo)

    result = await service.ban_user(user.id, ban=True)
    assert result.is_banned is True
