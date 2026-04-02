"""Repository layer for the Payout service."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Payout


class PayoutRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, payout: Payout) -> Payout:
        self.db.add(payout)
        await self.db.flush()
        await self.db.refresh(payout)
        return payout

    async def get_by_id(self, payout_id: uuid.UUID) -> Optional[Payout]:
        result = await self.db.execute(select(Payout).where(Payout.id == payout_id))
        return result.scalar_one_or_none()

    async def list_by_user(
        self, user_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[Payout], int]:
        total = (
            await self.db.execute(
                select(func.count(Payout.id)).where(Payout.user_id == user_id)
            )
        ).scalar_one()
        payouts = list(
            (
                await self.db.execute(
                    select(Payout)
                    .where(Payout.user_id == user_id)
                    .order_by(Payout.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return payouts, total

    async def list_all(
        self,
        *,
        offset: int,
        limit: int,
        status_filter: str | None,
    ) -> tuple[list[Payout], int]:
        query = select(Payout)
        count_query = select(func.count(Payout.id))

        if status_filter:
            query = query.where(Payout.status == status_filter)
            count_query = count_query.where(Payout.status == status_filter)

        total = int((await self.db.execute(count_query)).scalar_one())
        payouts = list(
            (
                await self.db.execute(
                    query.order_by(Payout.created_at.desc()).offset(offset).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return payouts, total

    async def update_status(
        self,
        payout_id: uuid.UUID,
        status: str,
        provider_ref: Optional[str] = None,
        failure_reason: Optional[str] = None,
    ) -> Optional[Payout]:
        payout = await self.get_by_id(payout_id)
        if payout is None:
            return None
        payout.status = status
        if provider_ref is not None:
            payout.provider_ref = provider_ref
        if failure_reason is not None:
            payout.failure_reason = failure_reason
        await self.db.flush()
        await self.db.refresh(payout)
        return payout
