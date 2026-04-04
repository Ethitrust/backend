"""Unit tests for PayoutService business logic."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.db import Payout
from app.models import PayoutRequest
from app.service import PayoutService
from fastapi import HTTPException

USER_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
WALLET_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


def _make_payout(**kw) -> Payout:
    p = Payout()
    p.id = uuid.uuid4()
    p.user_id = kw.get("user_id", USER_ID)
    p.wallet_id = kw.get("wallet_id", WALLET_ID)
    p.amount = kw.get("amount", 10000)
    p.currency = kw.get("currency", "ETB")
    p.bank_code = "044"
    p.account_number = "0123456789"
    p.account_name = "Test User"
    p.status = kw.get("status", "pending")
    p.provider = "chapa"
    p.provider_ref = None
    p.failure_reason = None
    return p


def _make_repo(payout=None):
    repo = MagicMock()
    repo.create = AsyncMock(return_value=payout or _make_payout())
    repo.get_by_id = AsyncMock(return_value=payout)
    repo.list_by_user = AsyncMock(
        return_value=([payout] if payout else [], 1 if payout else 0)
    )
    repo.update_status = AsyncMock(
        return_value=payout or _make_payout(status="success")
    )
    return repo


@pytest.mark.asyncio
async def test_request_payout_success(monkeypatch):
    payout = _make_payout()
    repo = _make_repo(payout)
    monkeypatch.setattr(
        "app.grpc_clients.deduct_wallet_balance",
        AsyncMock(return_value={"success": True, "new_balance": 90000}),
    )
    monkeypatch.setattr("app.messaging.publish", AsyncMock())
    svc = PayoutService(repo)

    data = PayoutRequest(
        wallet_id=WALLET_ID,
        amount=10000,
        currency="ETB",
        bank_code="044",
        account_number="0123456789",
        account_name="Test User",
    )
    result = await svc.request_payout(USER_ID, data)
    assert result.amount == 10000
    repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_request_payout_insufficient_balance(monkeypatch):
    repo = _make_repo()
    monkeypatch.setattr(
        "app.grpc_clients.deduct_wallet_balance",
        AsyncMock(return_value={"success": False}),
    )
    monkeypatch.setattr("app.messaging.publish", AsyncMock())
    svc = PayoutService(repo)

    data = PayoutRequest(
        wallet_id=WALLET_ID,
        amount=999999999,
        currency="ETB",
        bank_code="044",
        account_number="0123456789",
        account_name="Test User",
    )
    with pytest.raises(HTTPException) as exc:
        await svc.request_payout(USER_ID, data)
    assert exc.value.status_code == 400
    assert "INSUFFICIENT_BALANCE" in exc.value.detail


@pytest.mark.asyncio
async def test_get_payout_status_ownership():
    payout = _make_payout(user_id=uuid.uuid4())  # different user
    repo = _make_repo(payout)
    svc = PayoutService(repo)

    with pytest.raises(HTTPException) as exc:
        await svc.get_payout_status(USER_ID, payout.id)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_payout_not_found():
    repo = _make_repo(None)
    svc = PayoutService(repo)

    with pytest.raises(HTTPException) as exc:
        await svc.get_payout_status(USER_ID, uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_process_bank_transfer_success_marks_success_and_publishes(monkeypatch):
    payout = _make_payout(status="pending")
    repo = _make_repo(payout)
    repo.update_status = AsyncMock(
        side_effect=[_make_payout(status="processing"), _make_payout(status="success")]
    )

    monkeypatch.setattr(
        "app.grpc_clients.initiate_bank_transfer",
        AsyncMock(return_value={"provider_ref": "CHAPA-123", "status": "processing"}),
    )
    reverse_mock = AsyncMock(return_value={"success": True, "message": "ok"})
    monkeypatch.setattr("app.grpc_clients.credit_wallet_balance", reverse_mock)
    publish_mock = AsyncMock()
    monkeypatch.setattr("app.service.publish", publish_mock)

    svc = PayoutService(repo)
    result = await svc.process_bank_transfer(payout.id)

    assert result.status == "success"
    assert repo.update_status.call_count == 2
    reverse_mock.assert_not_awaited()
    publish_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_bank_transfer_failure_marks_failed_and_emits_event(monkeypatch):
    payout = _make_payout(status="pending")
    repo = _make_repo(payout)
    repo.update_status = AsyncMock(
        side_effect=[_make_payout(status="processing"), _make_payout(status="failed")]
    )

    monkeypatch.setattr(
        "app.grpc_clients.initiate_bank_transfer",
        AsyncMock(side_effect=RuntimeError("Unsupported payout provider")),
    )
    reverse_mock = AsyncMock(return_value={"success": True, "message": "credited"})
    monkeypatch.setattr("app.grpc_clients.credit_wallet_balance", reverse_mock)
    publish_mock = AsyncMock()
    monkeypatch.setattr("app.service.publish", publish_mock)

    svc = PayoutService(repo)
    result = await svc.process_bank_transfer(payout.id)

    assert result.status == "failed"
    assert repo.update_status.call_count == 2
    reverse_mock.assert_awaited_once()
    publish_payload = publish_mock.call_args.args[1]
    assert publish_payload["reversal_succeeded"] is True
    assert publish_payload["reversal_error"] is None
    publish_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_bank_transfer_failure_reversal_failure_is_recorded(monkeypatch):
    payout = _make_payout(status="pending")
    repo = _make_repo(payout)
    repo.update_status = AsyncMock(
        side_effect=[_make_payout(status="processing"), _make_payout(status="failed")]
    )

    monkeypatch.setattr(
        "app.grpc_clients.initiate_bank_transfer",
        AsyncMock(side_effect=RuntimeError("provider timeout")),
    )
    monkeypatch.setattr(
        "app.grpc_clients.credit_wallet_balance",
        AsyncMock(side_effect=RuntimeError("wallet unavailable")),
    )
    publish_mock = AsyncMock()
    monkeypatch.setattr("app.service.publish", publish_mock)

    svc = PayoutService(repo)
    result = await svc.process_bank_transfer(payout.id)

    assert result.status == "failed"
    failure_reason = repo.update_status.call_args_list[1].kwargs["failure_reason"]
    assert "REVERSAL_FAILED" in failure_reason
    publish_payload = publish_mock.call_args.args[1]
    assert publish_payload["reversal_succeeded"] is False
    assert "wallet unavailable" in publish_payload["reversal_error"]
