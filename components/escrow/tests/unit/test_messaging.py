from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.messaging import handle_event


@pytest.mark.asyncio
async def test_payment_completed_uses_reference_fallback_but_does_not_activate() -> (
    None
):
    with (
        patch("app.messaging.publish", AsyncMock()) as mock_publish,
    ):
        await handle_event(
            "payment.completed",
            {
                "reference": "pay-ref-42",
                "amount": 1000,
                "currency": "ETB",
            },
        )

    mock_publish.assert_not_called()


@pytest.mark.asyncio
async def test_payment_completed_is_idempotent_when_not_pending() -> None:
    with (
        patch("app.messaging.publish", AsyncMock()) as mock_publish,
    ):
        await handle_event(
            "payment.completed",
            {
                "transaction_ref": "pay-ref-99",
                "amount": 2500,
                "currency": "ETB",
            },
        )

    mock_publish.assert_not_called()
