"""Data-access layer for the Wallet service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Transaction, Wallet, WalletLock


class WalletRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Wallet queries
    # ------------------------------------------------------------------

    async def get_by_id(self, wallet_id: uuid.UUID) -> Optional[Wallet]:
        result = await self.db.execute(select(Wallet).where(Wallet.id == wallet_id))
        return result.scalar_one_or_none()

    async def get_by_owner(self, owner_id: uuid.UUID) -> list[Wallet]:
        result = await self.db.execute(
            select(Wallet).where(Wallet.owner_id == owner_id)
        )
        return list(result.scalars().all())

    async def get_by_owner_currency(
        self, owner_id: uuid.UUID, currency: str
    ) -> Optional[Wallet]:
        result = await self.db.execute(
            select(Wallet).where(
                Wallet.owner_id == owner_id, Wallet.currency == currency
            )
        )
        return result.scalar_one_or_none()

    async def create(self, owner_id: uuid.UUID, currency: str) -> Wallet:
        wallet = Wallet(owner_id=owner_id, currency=currency)
        self.db.add(wallet)
        await self.db.flush()
        await self.db.refresh(wallet)
        return wallet

    async def update_balance(
        self,
        wallet_id: uuid.UUID,
        balance_delta: int,
        locked_delta: int,
    ) -> Wallet:
        """Fetch the wallet with a FOR UPDATE lock, mutate, and flush.

        Returns the updated wallet instance.
        """
        result = await self.db.execute(
            select(Wallet).where(Wallet.id == wallet_id).with_for_update()
        )
        wallet = result.scalar_one()
        wallet.balance += balance_delta
        wallet.locked_balance += locked_delta
        self.db.add(wallet)
        await self.db.flush()
        await self.db.refresh(wallet)
        return wallet

    # ------------------------------------------------------------------
    # Transaction queries
    # ------------------------------------------------------------------

    async def get_lock_by_reference(self, reference: str) -> Optional[WalletLock]:
        result = await self.db.execute(
            select(WalletLock).where(WalletLock.reference == reference)
        )
        return result.scalar_one_or_none()

    async def get_active_lock(
        self, wallet_id: uuid.UUID, reference: str
    ) -> Optional[WalletLock]:
        result = await self.db.execute(
            select(WalletLock)
            .where(
                WalletLock.wallet_id == wallet_id,
                WalletLock.reference == reference,
                WalletLock.status == "locked",
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def save_wallet_lock(self, lock: WalletLock) -> WalletLock:
        self.db.add(lock)
        await self.db.flush()
        await self.db.refresh(lock)
        return lock

    async def mark_lock_status(self, lock: WalletLock, status: str) -> WalletLock:
        lock.status = status
        lock.released_at = datetime.now(timezone.utc)
        self.db.add(lock)
        await self.db.flush()
        await self.db.refresh(lock)
        return lock

    async def save_transaction(self, tx: Transaction) -> Transaction:
        self.db.add(tx)
        await self.db.flush()
        await self.db.refresh(tx)
        return tx

    async def get_transaction_by_reference(
        self, reference: str
    ) -> Optional[Transaction]:
        result = await self.db.execute(
            select(Transaction).where(Transaction.reference == reference)
        )
        return result.scalar_one_or_none()

    async def get_transaction_by_wallet_reference(
        self,
        wallet_id: uuid.UUID,
        reference: str,
    ) -> Optional[Transaction]:
        result = await self.db.execute(
            select(Transaction).where(
                Transaction.wallet_id == wallet_id,
                Transaction.reference == reference,
            )
        )
        return result.scalar_one_or_none()

    async def get_transactions(
        self, wallet_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[Transaction], int]:
        count_result = await self.db.execute(
            select(func.count()).where(Transaction.wallet_id == wallet_id)
        )
        total = count_result.scalar_one()

        txs_result = await self.db.execute(
            select(Transaction)
            .where(Transaction.wallet_id == wallet_id)
            .order_by(Transaction.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(txs_result.scalars().all()), total
