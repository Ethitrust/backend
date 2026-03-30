"""Repository layer for the Dispute service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Dispute, DisputeEvidence


class DisputeRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, dispute: Dispute) -> Dispute:
        self.db.add(dispute)
        await self.db.flush()
        await self.db.refresh(dispute)
        return dispute

    async def get_by_id(self, dispute_id: uuid.UUID) -> Optional[Dispute]:
        r = await self.db.execute(select(Dispute).where(Dispute.id == dispute_id))
        return r.scalar_one_or_none()

    async def get_by_escrow(self, escrow_id: uuid.UUID) -> Optional[Dispute]:
        r = await self.db.execute(select(Dispute).where(Dispute.escrow_id == escrow_id))
        return r.scalar_one_or_none()

    async def update_status(
        self,
        dispute_id: uuid.UUID,
        status: str,
        resolution_note: Optional[str] = None,
        resolved_by: Optional[uuid.UUID] = None,
    ) -> Optional[Dispute]:
        dispute = await self.get_by_id(dispute_id)
        if dispute is None:
            return None
        dispute.status = status
        if resolution_note:
            dispute.resolution_note = resolution_note
        if resolved_by:
            dispute.resolved_by = resolved_by
            dispute.resolved_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(dispute)
        return dispute

    async def add_evidence(self, evidence: DisputeEvidence) -> DisputeEvidence:
        self.db.add(evidence)
        await self.db.flush()
        await self.db.refresh(evidence)
        return evidence

    async def list_evidence(self, dispute_id: uuid.UUID) -> list[DisputeEvidence]:
        r = await self.db.execute(
            select(DisputeEvidence).where(DisputeEvidence.dispute_id == dispute_id)
        )
        return list(r.scalars().all())

    async def list_disputes(
        self,
        status_filter: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Dispute], int]:
        query = select(Dispute)
        count_query = select(func.count(Dispute.id))

        if status_filter:
            query = query.where(Dispute.status == status_filter)
            count_query = count_query.where(Dispute.status == status_filter)

        query = query.order_by(Dispute.created_at.desc()).offset(offset).limit(limit)
        rows = await self.db.execute(query)
        count_res = await self.db.execute(count_query)
        return list(rows.scalars().all()), int(count_res.scalar_one() or 0)
