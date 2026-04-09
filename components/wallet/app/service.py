"""Business logic for the Wallet service."""

from __future__ import annotations

import math
import uuid
from typing import Optional

from fastapi import HTTPException

from app import grpc_clients
from app.db import Transaction, Wallet, WalletLock
from app.repository import WalletRepository


class WalletService:
    def __init__(self, repo: WalletRepository) -> None:
        self.repo = repo

    # ------------------------------------------------------------------
    # Wallet management
    # ------------------------------------------------------------------

    async def create_wallet(self, owner_id: uuid.UUID, currency: str) -> Wallet:
        existing = await self.repo.get_by_owner_currency(owner_id, currency)
        if existing:
            raise HTTPException(
                409, f"Wallet for currency {currency} already exists for this user"
            )
        return await self.repo.create(owner_id, currency)

    async def get_wallets(self, owner_id: uuid.UUID) -> list[Wallet]:
        return await self.repo.get_by_owner(owner_id)

    async def get_wallet_by_owner_currency(
        self,
        owner_id: uuid.UUID,
        currency: str,
    ) -> Wallet | None:
        return await self.repo.get_by_owner_currency(owner_id, currency.upper())

    async def get_balance(self, wallet_id: uuid.UUID) -> Wallet:
        wallet = await self.repo.get_by_id(wallet_id)
        if not wallet:
            raise HTTPException(404, "Wallet not found")
        return wallet

    # ------------------------------------------------------------------
    # Balance mutations
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_lock_context(
        reason: str | None,
        source_type: str | None,
        source_id: uuid.UUID | None,
        escrow_id: uuid.UUID | None,
    ) -> tuple[str, str, uuid.UUID]:
        """Resolve and validate lock association context.

        Backward compatibility: if explicit context is not provided but escrow_id exists,
        derive ESCROW context from escrow_id.
        """
        if reason and source_type and source_id:
            return reason.upper(), source_type.upper(), source_id

        if escrow_id is not None:
            return "ESCROW", "ESCROW", escrow_id

        raise HTTPException(
            400,
            (
                "LOCK_ASSOCIATION_REQUIRED: lock operations must include reason, "
                "source_type, and source_id"
            ),
        )

    @staticmethod
    def _tx_type_for_lock(reason: str) -> str:
        return "escrow_lock" if reason == "ESCROW" else "lock"

    @staticmethod
    def _tx_type_for_unlock(reason: str) -> str:
        return "escrow_release" if reason == "ESCROW" else "unlock"

    @staticmethod
    def _tx_type_for_capture(reason: str) -> str:
        return "escrow_release" if reason == "ESCROW" else "capture"

    @staticmethod
    def _new_deposit_reference() -> str:
        return f"wallet-deposit-{uuid.uuid4().hex}"

    async def fund_wallet(
        self,
        wallet_id: uuid.UUID,
        amount: int,
        reference: str,
        currency: str,
    ) -> Transaction:
        """Credit *amount* to the wallet balance after a confirmed deposit."""
        wallet = await self.repo.get_by_id(wallet_id)
        if not wallet:
            raise HTTPException(404, "Wallet not found")

        await self.repo.update_balance(wallet_id, balance_delta=amount, locked_delta=0)

        tx = Transaction(
            wallet_id=wallet_id,
            type="deposit",
            amount=amount,
            currency=currency,
            status="success",
            reference=reference,
            description="Wallet funded via payment provider",
        )
        return await self.repo.save_transaction(tx)

    async def create_funding_intent(
        self,
        wallet_id: uuid.UUID,
        amount: int,
        reference: str,
        currency: str,
    ) -> Transaction:
        """Create (or return) a pending funding transaction for reconciliation."""
        wallet = await self.repo.get_by_id(wallet_id)
        if not wallet:
            raise HTTPException(404, "Wallet not found")

        existing_tx = await self.repo.get_transaction_by_reference(reference)
        if existing_tx is not None:
            return existing_tx

        tx = Transaction(
            wallet_id=wallet_id,
            type="deposit",
            amount=amount,
            currency=currency,
            status="pending",
            reference=reference,
            description="Wallet funding initiated",
        )
        return await self.repo.save_transaction(tx)

    async def initiate_deposit_transaction(
        self,
        wallet_id: uuid.UUID,
        amount: int,
        currency: str,
    ) -> Transaction:
        """Create a wallet-owned pending deposit transaction with internal reference."""
        if amount <= 0:
            raise HTTPException(400, "INVALID_AMOUNT")

        internal_reference = self._new_deposit_reference()
        return await self.create_funding_intent(
            wallet_id=wallet_id,
            amount=amount,
            reference=internal_reference,
            currency=currency,
        )

    async def initiate_deposit_checkout(
        self,
        wallet_id: uuid.UUID,
        user_id: uuid.UUID,
        amount: int,
        provider: str,
        return_url: str,
    ) -> dict:
        """Create internal deposit tx and initialize provider checkout session."""
        wallet = await self.get_balance(wallet_id)
        if wallet.owner_id != user_id:
            raise HTTPException(403, "Access denied")

        initiated_tx = await self.initiate_deposit_transaction(
            wallet_id=wallet_id,
            amount=amount,
            currency=wallet.currency,
        )

        try:
            checkout = await grpc_clients.create_checkout(
                amount=amount,
                currency=wallet.currency,
                metadata={
                    "wallet_id": str(wallet_id),
                    "user_id": str(user_id),
                    "tx_ref": initiated_tx.reference,
                },
                provider=provider,
                return_url=return_url,
            )
        except RuntimeError as exc:
            raise HTTPException(503, "Unable to initialize payment checkout") from exc

        return {
            "payment_url": checkout["payment_url"],
            "transaction_ref": initiated_tx.reference,
            "provider_transaction_ref": checkout["transaction_ref"],
            "provider": checkout["provider"],
            "wallet_id": str(wallet_id),
        }

    async def get_deposit_transaction(
        self,
        wallet_id: uuid.UUID,
        reference: str,
    ) -> Transaction:
        """Return a deposit transaction by wallet/reference or raise an HTTP error."""
        tx = await self.repo.get_transaction_by_wallet_reference(wallet_id, reference)
        if tx is None:
            raise HTTPException(404, "TRANSACTION_NOT_FOUND")
        if tx.type != "deposit":
            raise HTTPException(400, "TRANSACTION_TYPE_NOT_SUPPORTED")
        return tx

    async def reconcile_deposit_transaction(
        self,
        wallet_id: uuid.UUID,
        user_id: uuid.UUID,
        transaction_ref: str,
        provider: str,
    ) -> dict:
        """Verify and settle a pending deposit transaction manually."""
        wallet = await self.get_balance(wallet_id)
        if wallet.owner_id != user_id:
            raise HTTPException(403, "Access denied")

        tx = await self.get_deposit_transaction(wallet_id, transaction_ref)
        if tx.status == "success":
            return {
                "transaction_ref": tx.reference,
                "status": tx.status,
                "verified": True,
                "wallet_id": str(wallet_id),
            }

        try:
            verified = await grpc_clients.verify_payment(
                reference=transaction_ref,
                provider=provider,
            )
        except RuntimeError as exc:
            raise HTTPException(503, "Unable to verify payment status") from exc

        if not verified:
            return {
                "transaction_ref": tx.reference,
                "status": tx.status,
                "verified": False,
                "wallet_id": str(wallet_id),
            }

        settled_tx = await self.apply_payment_completed(
            wallet_id=wallet_id,
            amount=tx.amount,
            reference=tx.reference,
            currency=tx.currency,
        )
        return {
            "transaction_ref": settled_tx.reference,
            "status": settled_tx.status,
            "verified": True,
            "wallet_id": str(wallet_id),
        }

    async def apply_payment_completed(
        self,
        wallet_id: uuid.UUID,
        amount: int,
        reference: str,
        currency: str,
    ) -> Transaction:
        """Mark payment as successful and credit wallet exactly once."""
        wallet = await self.repo.get_by_id(wallet_id)
        if not wallet:
            raise HTTPException(404, "Wallet not found")

        existing_tx = await self.repo.get_transaction_by_reference(reference)
        if existing_tx is not None:
            if existing_tx.status == "success":
                return existing_tx

            if existing_tx.wallet_id != wallet_id:
                raise HTTPException(409, "REFERENCE_WALLET_MISMATCH")

            await self.repo.update_balance(
                wallet_id, balance_delta=amount, locked_delta=0
            )
            existing_tx.status = "success"
            existing_tx.description = "Wallet funded via payment provider"
            return await self.repo.save_transaction(existing_tx)

        return await self.fund_wallet(wallet_id, amount, reference, currency)

    async def deduct_balance(
        self,
        wallet_id: uuid.UUID,
        amount: int,
        reference: str,
    ) -> Wallet:
        """Debit *amount* from available balance for payout-style operations."""
        if amount <= 0:
            raise HTTPException(400, "INVALID_AMOUNT")

        wallet = await self.repo.get_by_id(wallet_id)
        if not wallet:
            raise HTTPException(404, "Wallet not found")
        if amount > wallet.balance:
            raise HTTPException(400, "INSUFFICIENT_BALANCE")

        updated_wallet = await self.repo.update_balance(
            wallet_id, balance_delta=-amount, locked_delta=0
        )

        tx = Transaction(
            wallet_id=wallet_id,
            type="payout",
            amount=amount,
            currency=wallet.currency,
            status="success",
            reference=reference,
            description="Wallet debited via DeductBalance",
        )
        await self.repo.save_transaction(tx)
        return updated_wallet

    async def lock_funds(
        self,
        wallet_id: uuid.UUID,
        amount: int,
        reference: str,
        escrow_id: Optional[uuid.UUID] = None,
        reason: str | None = None,
        source_type: str | None = None,
        source_id: uuid.UUID | None = None,
    ) -> Transaction:
        """Move *amount* from available balance into locked_balance for escrow."""
        reason_value, source_type_value, source_id_value = self._resolve_lock_context(
            reason=reason,
            source_type=source_type,
            source_id=source_id,
            escrow_id=escrow_id,
        )

        existing_lock = await self.repo.get_lock_by_reference(reference)
        if existing_lock is not None:
            raise HTTPException(409, "DUPLICATE_LOCK_REFERENCE")

        wallet = await self.repo.get_by_id(wallet_id)
        if not wallet:
            raise HTTPException(404, "Wallet not found")
        if amount > wallet.balance:
            raise HTTPException(400, "INSUFFICIENT_BALANCE")

        await self.repo.update_balance(
            wallet_id, balance_delta=-amount, locked_delta=amount
        )

        lock = WalletLock(
            wallet_id=wallet_id,
            amount=amount,
            currency=wallet.currency,
            reason=reason_value,
            source_type=source_type_value,
            source_id=source_id_value,
            reference=reference,
            status="locked",
            metadata_json={"escrow_id": str(escrow_id)} if escrow_id else None,
        )
        await self.repo.save_wallet_lock(lock)

        tx = Transaction(
            wallet_id=wallet_id,
            escrow_id=escrow_id,
            type=self._tx_type_for_lock(reason_value),
            amount=amount,
            currency=wallet.currency,
            status="success",
            reference=reference,
            description=(
                f"Funds locked for {source_type_value}:{source_id_value} "
                f"({reason_value})"
            ),
        )
        return await self.repo.save_transaction(tx)

    async def unlock_funds(
        self,
        wallet_id: uuid.UUID,
        amount: int,
        reference: str,
        escrow_id: Optional[uuid.UUID] = None,
        reason: str | None = None,
        source_type: str | None = None,
        source_id: uuid.UUID | None = None,
    ) -> Transaction:
        """Return locked funds back to available balance (escrow cancelled)."""
        reason_value, source_type_value, source_id_value = self._resolve_lock_context(
            reason=reason,
            source_type=source_type,
            source_id=source_id,
            escrow_id=escrow_id,
        )

        lock = await self.repo.get_active_lock(wallet_id, reference)
        if not lock:
            raise HTTPException(404, "LOCK_NOT_FOUND")
        if lock.source_type != source_type_value or lock.source_id != source_id_value:
            raise HTTPException(400, "LOCK_ASSOCIATION_MISMATCH")
        if amount != lock.amount:
            raise HTTPException(400, "LOCK_AMOUNT_MISMATCH")

        wallet = await self.repo.get_by_id(wallet_id)
        if not wallet:
            raise HTTPException(404, "Wallet not found")
        if amount > wallet.locked_balance:
            raise HTTPException(400, "INSUFFICIENT_LOCKED_BALANCE")

        await self.repo.update_balance(
            wallet_id, balance_delta=amount, locked_delta=-amount
        )
        await self.repo.mark_lock_status(lock, "released")

        tx = Transaction(
            wallet_id=wallet_id,
            escrow_id=escrow_id,
            type=self._tx_type_for_unlock(reason_value),
            amount=amount,
            currency=wallet.currency,
            status="success",
            reference=reference,
            description=(
                f"Locked funds released for {source_type_value}:{source_id_value} "
                f"({reason_value})"
            ),
        )
        return await self.repo.save_transaction(tx)

    async def release_funds(
        self,
        from_wallet_id: uuid.UUID,
        to_wallet_id: uuid.UUID,
        amount: int,
        reference: str,
        escrow_id: Optional[uuid.UUID] = None,
        reason: str | None = None,
        source_type: str | None = None,
        source_id: uuid.UUID | None = None,
    ) -> Transaction:
        """Release *amount* from sender's locked balance to recipient's balance.

        Used when an escrow is completed successfully.
        """
        reason_value, source_type_value, source_id_value = self._resolve_lock_context(
            reason=reason,
            source_type=source_type,
            source_id=source_id,
            escrow_id=escrow_id,
        )

        lock = await self.repo.get_active_lock(from_wallet_id, reference)
        if not lock:
            raise HTTPException(404, "LOCK_NOT_FOUND")
        if lock.source_type != source_type_value or lock.source_id != source_id_value:
            raise HTTPException(400, "LOCK_ASSOCIATION_MISMATCH")
        if amount != lock.amount:
            raise HTTPException(400, "LOCK_AMOUNT_MISMATCH")

        sender = await self.repo.get_by_id(from_wallet_id)
        if not sender:
            raise HTTPException(404, "Sender wallet not found")
        if amount > sender.locked_balance:
            raise HTTPException(400, "INSUFFICIENT_LOCKED_BALANCE")

        recipient = await self.repo.get_by_id(to_wallet_id)
        if not recipient:
            raise HTTPException(404, "Recipient wallet not found")

        # Deduct from sender locked balance
        await self.repo.update_balance(
            from_wallet_id, balance_delta=0, locked_delta=-amount
        )
        # Credit recipient available balance
        await self.repo.update_balance(
            to_wallet_id, balance_delta=amount, locked_delta=0
        )
        await self.repo.mark_lock_status(lock, "captured")

        tx = Transaction(
            wallet_id=from_wallet_id,
            escrow_id=escrow_id,
            type=self._tx_type_for_capture(reason_value),
            amount=amount,
            currency=sender.currency,
            status="success",
            reference=reference,
            description=(
                f"Locked funds captured for {source_type_value}:{source_id_value} "
                f"({reason_value}) to wallet {to_wallet_id}"
            ),
        )
        return await self.repo.save_transaction(tx)

    # ------------------------------------------------------------------
    # Transaction history
    # ------------------------------------------------------------------

    async def get_transactions(
        self,
        wallet_id: uuid.UUID,
        page: int = 1,
        limit: int = 20,
    ) -> dict:
        offset = (page - 1) * limit
        items, total = await self.repo.get_transactions(wallet_id, offset, limit)
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": math.ceil(total / limit) if total else 0,
        }
