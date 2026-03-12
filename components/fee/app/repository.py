"""Repository layer for the Fee service."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import FeeLedger


class FeeRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, entry: FeeLedger) -> FeeLedger:
        self.db.add(entry)
        await self.db.flush()
        await self.db.refresh(entry)
        return entry

    async def get_by_escrow(self, escrow_id: uuid.UUID) -> list[FeeLedger]:
        r = await self.db.execute(
            select(FeeLedger).where(FeeLedger.escrow_id == escrow_id)
        )
        return list(r.scalars().all())

    async def refund(self, escrow_id: uuid.UUID) -> list[FeeLedger]:
        """Mark all collected fees for escrow as refunded."""
        entries = await self.get_by_escrow(escrow_id)
        for entry in entries:
            if entry.status == "collected":
                entry.status = "refunded"
        await self.db.flush()
        return entries
