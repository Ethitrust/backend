"""Unit tests for WalletService business logic."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.db import Transaction, Wallet, WalletLock
from app.service import WalletService
from fastapi import HTTPException


def _make_wallet(
    balance: int = 0,
    locked_balance: int = 0,
    currency: str = "ETB",
    owner_id: uuid.UUID = None,
) -> Wallet:
    w = Wallet()
    w.id = uuid.uuid4()
    w.owner_id = owner_id or uuid.uuid4()
    w.currency = currency
    w.balance = balance
    w.locked_balance = locked_balance
    w.status = "active"
    return w


def _make_transaction(**kwargs) -> Transaction:
    tx = Transaction()
    tx.id = uuid.uuid4()
    for k, v in kwargs.items():
        setattr(tx, k, v)
    return tx


def _make_repo(wallet: Wallet = None):
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=wallet)
    repo.get_by_owner = AsyncMock(return_value=[wallet] if wallet else [])
    repo.get_by_owner_currency = AsyncMock(return_value=None)
    repo.create = AsyncMock(return_value=wallet or _make_wallet())
    repo.update_balance = AsyncMock(
        side_effect=lambda wid, balance_delta, locked_delta: _apply_delta(
            wallet, balance_delta, locked_delta
        )
    )
    repo.get_lock_by_reference = AsyncMock(return_value=None)
    repo.get_active_lock = AsyncMock(return_value=None)
    repo.save_wallet_lock = AsyncMock(side_effect=lambda lock: lock)
    repo.mark_lock_status = AsyncMock(side_effect=lambda lock, status: lock)
    repo.save_transaction = AsyncMock(side_effect=lambda tx: tx)
    repo.get_transaction_by_reference = AsyncMock(return_value=None)
    repo.get_transactions = AsyncMock(return_value=([], 0))
    return repo


def _apply_delta(wallet, balance_delta, locked_delta):
    if wallet:
        wallet.balance += balance_delta
        wallet.locked_balance += locked_delta
    return wallet


class TestCreateWallet:
    @pytest.mark.asyncio
    async def test_create_wallet_success(self):
        owner_id = uuid.uuid4()
        new_wallet = _make_wallet(owner_id=owner_id, currency="ETB")
        repo = _make_repo(new_wallet)
        repo.get_by_owner_currency = AsyncMock(return_value=None)
        repo.create = AsyncMock(return_value=new_wallet)

        svc = WalletService(repo)
        result = await svc.create_wallet(owner_id, "ETB")

        assert result.currency == "ETB"
        repo.create.assert_called_once_with(owner_id, "ETB")

    @pytest.mark.asyncio
    async def test_create_wallet_duplicate_raises_409(self):
        owner_id = uuid.uuid4()
        existing = _make_wallet(owner_id=owner_id, currency="ETB")
        repo = _make_repo(existing)
        repo.get_by_owner_currency = AsyncMock(return_value=existing)

        svc = WalletService(repo)
        with pytest.raises(HTTPException) as exc_info:
            await svc.create_wallet(owner_id, "ETB")
        assert exc_info.value.status_code == 409


class TestLockFunds:
    @pytest.mark.asyncio
    async def test_lock_funds_requires_association_context(self):
        wallet = _make_wallet(balance=1000)
        repo = _make_repo(wallet)
        svc = WalletService(repo)

        with pytest.raises(HTTPException) as exc_info:
            await svc.lock_funds(wallet.id, 500, "ref-no-context")
        assert exc_info.value.status_code == 400
        assert "LOCK_ASSOCIATION_REQUIRED" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_lock_funds_raises_insufficient_balance(self):
        wallet = _make_wallet(balance=100)
        repo = _make_repo(wallet)
        svc = WalletService(repo)

        with pytest.raises(HTTPException) as exc_info:
            await svc.lock_funds(
                wallet.id,
                500,
                "ref-001",
                reason="ESCROW",
                source_type="ESCROW",
                source_id=uuid.uuid4(),
            )
        assert exc_info.value.status_code == 400
        assert "INSUFFICIENT_BALANCE" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_lock_funds_success_creates_transaction(self):
        wallet = _make_wallet(balance=1000)
        repo = _make_repo(wallet)
        svc = WalletService(repo)
        escrow_id = uuid.uuid4()

        tx = await svc.lock_funds(
            wallet.id,
            500,
            "ref-lock-001",
            reason="ESCROW",
            source_type="ESCROW",
            source_id=escrow_id,
            escrow_id=escrow_id,
        )

        repo.update_balance.assert_called_once_with(
            wallet.id, balance_delta=-500, locked_delta=500
        )
        repo.save_wallet_lock.assert_called_once()
        saved_lock = repo.save_wallet_lock.call_args[0][0]
        assert isinstance(saved_lock, WalletLock)
        assert saved_lock.reason == "ESCROW"
        repo.save_transaction.assert_called_once()
        saved_tx = repo.save_transaction.call_args[0][0]
        assert saved_tx.type == "escrow_lock"
        assert saved_tx.amount == 500

    @pytest.mark.asyncio
    async def test_lock_funds_exact_balance_succeeds(self):
        wallet = _make_wallet(balance=200)
        repo = _make_repo(wallet)
        svc = WalletService(repo)

        tx = await svc.lock_funds(
            wallet.id,
            200,
            "ref-exact",
            reason="ESCROW",
            source_type="ESCROW",
            source_id=uuid.uuid4(),
        )
        repo.update_balance.assert_called_once()


class TestReleaseFunds:
    @pytest.mark.asyncio
    async def test_release_funds_moves_locked_to_recipient(self):
        escrow_id = uuid.uuid4()
        sender = _make_wallet(balance=0, locked_balance=500, currency="ETB")
        recipient = _make_wallet(balance=100, currency="ETB")
        lock = WalletLock(
            wallet_id=sender.id,
            amount=500,
            currency="ETB",
            reason="ESCROW",
            source_type="ESCROW",
            source_id=escrow_id,
            reference="ref-release-001",
            status="locked",
        )

        repo = MagicMock()
        # get_by_id returns sender first, then recipient
        repo.get_by_id = AsyncMock(side_effect=[sender, recipient])
        repo.get_active_lock = AsyncMock(return_value=lock)
        repo.update_balance = AsyncMock(return_value=sender)
        repo.mark_lock_status = AsyncMock(return_value=lock)
        repo.save_transaction = AsyncMock(side_effect=lambda tx: tx)

        svc = WalletService(repo)
        tx = await svc.release_funds(
            sender.id,
            recipient.id,
            500,
            "ref-release-001",
            escrow_id=escrow_id,
            reason="ESCROW",
            source_type="ESCROW",
            source_id=escrow_id,
        )

        assert repo.update_balance.call_count == 2
        # First call: deduct sender locked_balance
        first_call = repo.update_balance.call_args_list[0]
        assert first_call.kwargs["balance_delta"] == 0
        assert first_call.kwargs["locked_delta"] == -500
        # Second call: credit recipient balance
        second_call = repo.update_balance.call_args_list[1]
        assert second_call.kwargs["balance_delta"] == 500
        assert second_call.kwargs["locked_delta"] == 0

    @pytest.mark.asyncio
    async def test_release_funds_insufficient_locked_raises_400(self):
        escrow_id = uuid.uuid4()
        sender = _make_wallet(balance=0, locked_balance=100)
        recipient = _make_wallet(balance=0)
        lock = WalletLock(
            wallet_id=sender.id,
            amount=500,
            currency="ETB",
            reason="ESCROW",
            source_type="ESCROW",
            source_id=escrow_id,
            reference="ref",
            status="locked",
        )

        repo = MagicMock()
        repo.get_active_lock = AsyncMock(return_value=lock)
        repo.get_by_id = AsyncMock(side_effect=[sender, recipient])
        repo.update_balance = AsyncMock()
        repo.save_transaction = AsyncMock()

        svc = WalletService(repo)
        with pytest.raises(HTTPException) as exc_info:
            await svc.release_funds(
                sender.id,
                recipient.id,
                500,
                "ref",
                escrow_id=escrow_id,
                reason="ESCROW",
                source_type="ESCROW",
                source_id=escrow_id,
            )
        assert exc_info.value.status_code == 400


class TestFundWallet:
    @pytest.mark.asyncio
    async def test_fund_wallet_adds_balance_and_creates_deposit_transaction(self):
        wallet = _make_wallet(balance=0, currency="ETB")
        repo = _make_repo(wallet)
        svc = WalletService(repo)
        svc._emit_deposit_success_event = AsyncMock()

        tx = await svc.fund_wallet(wallet.id, 10000, "pay_ref_001", "ETB", "chapa")

        repo.update_balance.assert_called_once_with(
            wallet.id, balance_delta=10000, locked_delta=0
        )
        saved_tx = repo.save_transaction.call_args[0][0]
        assert saved_tx.type == "deposit"
        assert saved_tx.amount == 10000
        assert saved_tx.status == "success"
        assert saved_tx.reference == "pay_ref_001"
        svc._emit_deposit_success_event.assert_awaited_once_with(wallet, tx)

    @pytest.mark.asyncio
    async def test_fund_wallet_not_found_raises_404(self):
        repo = _make_repo(None)
        repo.get_by_id = AsyncMock(return_value=None)
        svc = WalletService(repo)

        with pytest.raises(HTTPException) as exc_info:
            await svc.fund_wallet(uuid.uuid4(), 1000, "ref", "ETB", "chapa")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_funding_intent_creates_pending_transaction(self):
        wallet = _make_wallet(balance=0, currency="ETB")
        repo = _make_repo(wallet)
        svc = WalletService(repo)

        tx = await svc.create_funding_intent(
            wallet.id,
            10000,
            "pay_ref_pending",
            "ETB",
            "chapa",
        )

        saved_tx = repo.save_transaction.call_args[0][0]
        assert saved_tx.reference == "pay_ref_pending"
        assert saved_tx.status == "pending"
        assert saved_tx.type == "deposit"
        assert tx.status == "pending"

    @pytest.mark.asyncio
    async def test_initiate_deposit_transaction_creates_internal_reference(self):
        wallet = _make_wallet(balance=0, currency="ETB")
        repo = _make_repo(wallet)
        svc = WalletService(repo)

        tx = await svc.initiate_deposit_transaction(wallet.id, 10000, "ETB", "chapa")

        saved_tx = repo.save_transaction.call_args[0][0]
        assert saved_tx.reference.startswith("wallet-deposit-")
        assert saved_tx.status == "pending"
        assert saved_tx.type == "deposit"
        assert tx.reference.startswith("wallet-deposit-")

    @pytest.mark.asyncio
    async def test_get_deposit_transaction_raises_for_non_deposit_type(self):
        wallet = _make_wallet(balance=0, currency="ETB")
        repo = _make_repo(wallet)
        repo.get_transaction_by_wallet_reference = AsyncMock(
            return_value=_make_transaction(
                wallet_id=wallet.id,
                type="payout",
                amount=5000,
                currency="ETB",
                status="pending",
                reference="payout-ref",
            )
        )
        svc = WalletService(repo)

        with pytest.raises(HTTPException) as exc_info:
            await svc.get_deposit_transaction(wallet.id, "payout-ref")

        assert exc_info.value.status_code == 400
        assert "TRANSACTION_TYPE_NOT_SUPPORTED" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_apply_payment_completed_upgrades_pending_transaction(self):
        wallet = _make_wallet(balance=0, currency="ETB")
        repo = _make_repo(wallet)

        pending_tx = _make_transaction(
            wallet_id=wallet.id,
            type="deposit",
            amount=5000,
            currency="ETB",
            status="pending",
            reference="pay_ref_upgrade",
            description="Wallet funding initiated",
        )
        repo.get_transaction_by_reference = AsyncMock(return_value=pending_tx)

        svc = WalletService(repo)
        svc._emit_deposit_success_event = AsyncMock()
        tx = await svc.apply_payment_completed(
            wallet.id,
            5000,
            "pay_ref_upgrade",
            "ETB",
            "chapa",
        )

        repo.update_balance.assert_called_once_with(
            wallet.id, balance_delta=5000, locked_delta=0
        )
        assert tx.status == "success"
        assert tx.reference == "pay_ref_upgrade"
        svc._emit_deposit_success_event.assert_awaited_once_with(wallet, tx)

    @pytest.mark.asyncio
    async def test_apply_payment_completed_is_idempotent_for_success_transaction(self):
        wallet = _make_wallet(balance=1000, currency="ETB")
        repo = _make_repo(wallet)

        success_tx = _make_transaction(
            wallet_id=wallet.id,
            type="deposit",
            amount=5000,
            currency="ETB",
            status="success",
            reference="pay_ref_done",
            description="Wallet funded via payment provider",
        )
        repo.get_transaction_by_reference = AsyncMock(return_value=success_tx)

        svc = WalletService(repo)
        svc._emit_deposit_success_event = AsyncMock()
        tx = await svc.apply_payment_completed(
            wallet.id,
            5000,
            "pay_ref_done",
            "ETB",
            "chapa",
        )

        repo.update_balance.assert_not_called()
        assert tx.status == "success"
        svc._emit_deposit_success_event.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_apply_payment_completed_raises_when_provider_mismatch(self):
        wallet = _make_wallet(balance=0, currency="ETB")
        repo = _make_repo(wallet)

        pending_tx = _make_transaction(
            wallet_id=wallet.id,
            type="deposit",
            amount=5000,
            currency="ETB",
            status="pending",
            reference="pay_ref_provider_mismatch",
            description="Wallet funding initiated",
            provider="manual",
        )
        repo.get_transaction_by_reference = AsyncMock(return_value=pending_tx)

        svc = WalletService(repo)

        with pytest.raises(HTTPException) as exc_info:
            await svc.apply_payment_completed(
                wallet.id,
                5000,
                "pay_ref_provider_mismatch",
                "ETB",
                "chapa",
            )

        assert exc_info.value.status_code == 409
        assert "TRANSACTION_PROVIDER_MISMATCH" in exc_info.value.detail
        repo.update_balance.assert_not_called()


class TestDeductBalance:
    @pytest.mark.asyncio
    async def test_deduct_balance_success_debits_and_records_transaction(self):
        wallet = _make_wallet(balance=10000, currency="ETB")
        repo = _make_repo(wallet)
        svc = WalletService(repo)

        updated_wallet = await svc.deduct_balance(
            wallet.id,
            2500,
            "payout_ref_001",
            "chapa",
        )

        repo.update_balance.assert_called_once_with(
            wallet.id, balance_delta=-2500, locked_delta=0
        )
        saved_tx = repo.save_transaction.call_args[0][0]
        assert saved_tx.type == "payout"
        assert saved_tx.amount == 2500
        assert saved_tx.status == "success"
        assert saved_tx.reference == "payout_ref_001"
        assert updated_wallet.balance == 7500

    @pytest.mark.asyncio
    async def test_deduct_balance_not_found_raises_404(self):
        repo = _make_repo(None)
        repo.get_by_id = AsyncMock(return_value=None)
        svc = WalletService(repo)

        with pytest.raises(HTTPException) as exc_info:
            await svc.deduct_balance(uuid.uuid4(), 1000, "ref", "chapa")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_deduct_balance_insufficient_balance_raises_400(self):
        wallet = _make_wallet(balance=500, currency="ETB")
        repo = _make_repo(wallet)
        svc = WalletService(repo)

        with pytest.raises(HTTPException) as exc_info:
            await svc.deduct_balance(wallet.id, 1000, "ref", "chapa")
        assert exc_info.value.status_code == 400
        assert "INSUFFICIENT_BALANCE" in exc_info.value.detail
