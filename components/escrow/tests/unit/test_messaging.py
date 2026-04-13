from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.messaging import handle_event


@pytest.mark.asyncio
async def test_wallet_deposit_success_triggers_pending_activation_retry() -> None:
    mock_service = AsyncMock()
    mock_service.activate_pending_escrows_for_buyer = AsyncMock(return_value=1)
    mock_repo = object()

    class _DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with (
        patch("app.db.async_session_factory", return_value=_DummySession()),
        patch("app.repository.EscrowRepository", return_value=mock_repo),
        patch("app.service.EscrowService", return_value=mock_service),
    ):
        await handle_event(
            "wallet.deposit.success",
            {
                "user_id": "11111111-1111-4111-8111-11111111111a",
                "reference": "wallet-deposit-ref-1",
            },
        )

    mock_service.activate_pending_escrows_for_buyer.assert_awaited_once()


@pytest.mark.asyncio
async def test_payment_completed_with_missing_user_id_is_ignored() -> None:
    with (
        patch("app.db.async_session_factory", side_effect=AssertionError()),
    ):
        await handle_event(
            "payment.completed",
            {
                "transaction_ref": "pay-ref-99",
                "amount": 2500,
                "currency": "ETB",
            },
        )


@pytest.mark.asyncio
async def test_user_registered_associates_pending_email_invitations() -> None:
    mock_service = AsyncMock()
    mock_service.associate_pending_invitations_for_user_email = AsyncMock(return_value=2)
    mock_repo = object()

    class _DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with (
        patch("app.db.async_session_factory", return_value=_DummySession()),
        patch("app.repository.EscrowRepository", return_value=mock_repo),
        patch("app.service.EscrowService", return_value=mock_service),
    ):
        await handle_event(
            "user.registered",
            {
                "user_id": "11111111-1111-4111-8111-11111111111a",
                "email": "invitee@example.com",
            },
        )

    mock_service.associate_pending_invitations_for_user_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_registered_missing_email_is_ignored() -> None:
    with patch("app.db.async_session_factory", side_effect=AssertionError()):
        await handle_event(
            "user.registered",
            {
                "user_id": "11111111-1111-4111-8111-11111111111a",
            },
        )
