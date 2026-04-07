from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from scripts.create_admin import create_or_promote_admin


class _FakeSession:
    def __init__(self) -> None:
        self.add = MagicMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


class _FakeSessionCtx:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.asyncio
async def test_create_or_promote_admin_creates_new_user():
    fake_session = _FakeSession()
    new_user = SimpleNamespace(
        id=uuid.uuid4(),
        email="admin@example.com",
        password_hash="hashed",
        first_name="Ada",
        last_name="Lovelace",
        role="user",
        is_verified=False,
        is_banned=False,
    )

    fake_repo = MagicMock()
    fake_repo.get_by_email = AsyncMock(return_value=None)
    fake_repo.create_user = AsyncMock(return_value=new_user)

    with patch("scripts.create_admin.AsyncSessionLocal", return_value=_FakeSessionCtx(fake_session)):
        with patch("scripts.create_admin.AuthRepository", return_value=fake_repo):
            with patch("scripts.create_admin.hash_password", return_value="hashed"):
                with patch("scripts.create_admin.sync_user", new_callable=AsyncMock) as mock_sync:
                    action, user_id = await create_or_promote_admin(
                        email="admin@example.com",
                        password="ValidPass1",
                        first_name="Ada",
                        last_name="Lovelace",
                        dry_run=False,
                    )

    assert action == "created"
    assert user_id == str(new_user.id)
    assert new_user.role == "admin"
    assert new_user.is_verified is True
    fake_repo.create_user.assert_awaited_once()
    mock_sync.assert_awaited_once()
    fake_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_or_promote_admin_promotes_existing_user():
    fake_session = _FakeSession()
    existing_user = SimpleNamespace(
        id=uuid.uuid4(),
        email="existing@example.com",
        password_hash="existing-hash",
        first_name="Existing",
        last_name="User",
        role="user",
        is_verified=False,
        is_banned=False,
    )

    fake_repo = MagicMock()
    fake_repo.get_by_email = AsyncMock(return_value=existing_user)
    fake_repo.create_user = AsyncMock()

    with patch("scripts.create_admin.AsyncSessionLocal", return_value=_FakeSessionCtx(fake_session)):
        with patch("scripts.create_admin.AuthRepository", return_value=fake_repo):
            with patch("scripts.create_admin.update_user_role", new_callable=AsyncMock) as mock_role:
                with patch(
                    "scripts.create_admin.update_email_verification_status",
                    new_callable=AsyncMock,
                ) as mock_verify:
                    action, user_id = await create_or_promote_admin(
                        email="existing@example.com",
                        password="IgnoredForExisting1",
                        first_name="Existing",
                        last_name="User",
                        dry_run=False,
                    )

    assert action == "promoted"
    assert user_id == str(existing_user.id)
    assert existing_user.role == "admin"
    assert existing_user.is_verified is True
    fake_repo.create_user.assert_not_called()
    mock_role.assert_awaited_once_with(user_id=str(existing_user.id), role="admin")
    mock_verify.assert_awaited_once_with(
        user_id=str(existing_user.id),
        is_verified=True,
    )
    fake_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_or_promote_admin_dry_run_rolls_back_without_sync():
    fake_session = _FakeSession()
    new_user = SimpleNamespace(
        id=uuid.uuid4(),
        email="dryrun@example.com",
        password_hash="hashed",
        first_name="Dry",
        last_name="Run",
        role="user",
        is_verified=False,
        is_banned=False,
    )

    fake_repo = MagicMock()
    fake_repo.get_by_email = AsyncMock(return_value=None)
    fake_repo.create_user = AsyncMock(return_value=new_user)

    with patch("scripts.create_admin.AsyncSessionLocal", return_value=_FakeSessionCtx(fake_session)):
        with patch("scripts.create_admin.AuthRepository", return_value=fake_repo):
            with patch("scripts.create_admin.hash_password", return_value="hashed"):
                with patch("scripts.create_admin.sync_user", new_callable=AsyncMock) as mock_sync:
                    action, _ = await create_or_promote_admin(
                        email="dryrun@example.com",
                        password="ValidPass1",
                        first_name="Dry",
                        last_name="Run",
                        dry_run=True,
                    )

    assert action == "created"
    fake_session.rollback.assert_awaited_once()
    fake_session.commit.assert_not_awaited()
    mock_sync.assert_not_awaited()
