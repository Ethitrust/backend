import hashlib
import hmac
import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def set_secrets(monkeypatch):
    monkeypatch.setenv("CHAPA_WEBHOOK_SECRET", "testsecret")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "stripesecret")


@pytest.fixture()
def app():
    """Import the app with DB and messaging patched out."""
    with (
        patch("app.db.create_async_engine", MagicMock()),
        patch("app.db.async_sessionmaker", MagicMock()),
        patch("app.messaging.start_consumer", new_callable=AsyncMock),
        patch("app.messaging.publish", new_callable=AsyncMock),
    ):
        from app.main import app as _app

        yield _app


@pytest.fixture()
def mock_db_session():
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


async def _make_client(app, mock_db_session):
    from app.db import WebhookLog

    mock_log = MagicMock(spec=WebhookLog)
    mock_db_session.refresh = AsyncMock(return_value=None)
    mock_db_session.add = MagicMock()
    mock_db_session.flush = AsyncMock(return_value=None)

    with patch("app.db.AsyncSessionLocal", return_value=mock_db_session):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return client


@pytest.mark.asyncio
async def test_chapa_webhook_valid_signature(app, mock_db_session):
    """POST /webhook/chapa with valid HMAC-SHA512 signature returns 200."""
    secret = "testsecret"
    body = {
        "event": "charge.success",
        "data": {
            "reference": "ref_abc",
            "amount": 50000,
            "currency": "ETB",
        },
    }
    payload = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()

    with (
        patch("app.db.AsyncSessionLocal") as mock_session_maker,
        patch("app.messaging.publish", new_callable=AsyncMock),
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_maker.return_value = mock_ctx

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhook/chapa",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-chapa-signature": sig,
                },
            )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"


@pytest.mark.asyncio
async def test_chapa_webhook_invalid_signature(app, mock_db_session):
    """POST /webhook/chapa with wrong signature returns 400."""
    body = {"event": "charge.success", "data": {}}
    payload = json.dumps(body).encode()
    bad_sig = "000invalidbadsig"

    with (
        patch("app.db.AsyncSessionLocal") as mock_session_maker,
        patch("app.messaging.publish", new_callable=AsyncMock),
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_maker.return_value = mock_ctx

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhook/chapa",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-chapa-signature": bad_sig,
                },
            )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_stripe_webhook_valid_signature(app, mock_db_session):
    """POST /webhook/stripe with valid timestamp-based HMAC-SHA256 signature returns 200."""
    import time

    secret = "stripesecret"
    body = {
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "amount": 2000,
                "currency": "usd",
                "metadata": {"reference": "pi_ref"},
            }
        },
    }
    payload = json.dumps(body).encode()
    ts = str(int(time.time()))
    signed_payload = f"{ts}.{payload.decode()}"
    sig_hash = hmac.new(
        secret.encode(), signed_payload.encode(), hashlib.sha256
    ).hexdigest()
    stripe_sig = f"t={ts},v1={sig_hash}"

    with (
        patch("app.db.AsyncSessionLocal") as mock_session_maker,
        patch("app.messaging.publish", new_callable=AsyncMock),
    ):
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_maker.return_value = mock_ctx

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhook/stripe",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "stripe-signature": stripe_sig,
                },
            )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
