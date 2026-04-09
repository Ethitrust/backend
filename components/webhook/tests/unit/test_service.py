import hashlib
import hmac
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


@pytest.fixture(autouse=True)
def set_chapa_secret(monkeypatch):
    monkeypatch.setenv("CHAPA_WEBHOOK_SECRET", "testsecret")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "stripesecret")


def _make_repo():
    repo = MagicMock()
    repo.save_log = AsyncMock(return_value=MagicMock())
    return repo


async def test_invalid_chapa_signature_raises_400():
    """An invalid Chapa signature must raise HTTPException 400."""
    from app.service import WebhookService

    repo = _make_repo()
    svc = WebhookService(repo=repo)

    payload = json.dumps({"event": "charge.success", "data": {}}).encode()

    with pytest.raises(HTTPException) as exc_info:
        await svc.handle_chapa_event(payload)

    assert exc_info.value.status_code == 400


async def test_valid_chapa_charge_success_publishes_payment_completed():
    """A valid charge.success event should publish payment.completed."""
    from app.service import WebhookService

    repo = _make_repo()
    svc = WebhookService(repo=repo)

    body = {
        "event": "charge.success",
        "data": {
            "reference": "provider_ref_123",
            "tx_ref": "wallet-deposit-ref-123",
            "amount": 100000,
            "currency": "ETB",
            "meta": {
                "invoices": [
                    {
                        "key": "wallet_id",
                        "value": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                    }
                ]
            },
        },
    }
    payload = json.dumps(body).encode()

    with patch("app.messaging.publish", new_callable=AsyncMock) as mock_publish:
        result = await svc.handle_chapa_event(payload)

    assert result == {"status": "processed"}
    mock_publish.assert_awaited_once()
    args = mock_publish.call_args
    assert args[0][0] == "payment.completed"
    assert args[0][1]["reference"] == "wallet-deposit-ref-123"
    assert args[0][1]["transaction_ref"] == "wallet-deposit-ref-123"
    assert args[0][1]["provider_reference"] == "provider_ref_123"
    assert args[0][1]["wallet_id"] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_verify_signature_returns_true_for_valid():
    """verify_signature should return True for a matching signature."""
    from app.service import WebhookService

    secret = "mysecret"
    payload = b"hello world"
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert WebhookService.verify_signature(payload, sig, secret) is True


def test_verify_signature_returns_false_for_invalid():
    """verify_signature should return False for a non-matching signature."""
    from app.service import WebhookService

    assert WebhookService.verify_signature(b"data", "badsig", "secret") is False
