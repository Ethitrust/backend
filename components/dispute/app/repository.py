"""Repository layer for the Dispute service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Dispute, DisputeEvidence, DisputeMessage


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

    async def add_message(self, message: DisputeMessage) -> DisputeMessage:
        self.db.add(message)
        await self.db.flush()
        await self.db.refresh(message)
        return message

    async def list_messages(self, dispute_id: uuid.UUID) -> list[DisputeMessage]:
        r = await self.db.execute(
            select(DisputeMessage)
            .where(DisputeMessage.dispute_id == dispute_id)
            .order_by(DisputeMessage.created_at.asc())
        )
        return list(r.scalars().all())

    async def request_settlement(
        self,
        dispute_id: uuid.UUID,
        requester_id: uuid.UUID,
    ) -> Optional[Dispute]:
        dispute = await self.get_by_id(dispute_id)
        if dispute is None:
            return None
        dispute.status = "settlement_pending_confirmation"
        dispute.settlement_requested_by = requester_id
        dispute.settlement_confirmed_by = None
        await self.db.flush()
        await self.db.refresh(dispute)
        return dispute

    async def confirm_settlement(
        self,
        dispute_id: uuid.UUID,
        confirmer_id: uuid.UUID,
    ) -> Optional[Dispute]:
        dispute = await self.get_by_id(dispute_id)
        if dispute is None:
            return None
        dispute.status = "settled_by_parties"
        dispute.settlement_confirmed_by = confirmer_id
        dispute.resolved_by = confirmer_id
        dispute.resolved_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(dispute)
        return dispute

    async def escalate_to_mediation(
        self,
        dispute_id: uuid.UUID,
        mediator_id: uuid.UUID | None = None,
    ) -> Optional[Dispute]:
        dispute = await self.get_by_id(dispute_id)
        if dispute is None:
            return None
        dispute.status = "escalated_mediation"
        dispute.escalated_at = datetime.now(timezone.utc)
        if mediator_id is not None:
            dispute.assigned_mediator_id = mediator_id
        await self.db.flush()
        await self.db.refresh(dispute)
        return dispute

    async def list_expired_negotiations(
        self,
        now: datetime,
        limit: int = 100,
    ) -> list[Dispute]:
        r = await self.db.execute(
            select(Dispute)
            .where(Dispute.status.in_(["open_negotiation", "settlement_pending_confirmation"]))
            .where(Dispute.negotiation_deadline_at < now)
            .order_by(Dispute.negotiation_deadline_at.asc())
            .limit(limit)
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

    async def list_disputes_by_raiser(
        self,
        raised_by: uuid.UUID,
        status_filter: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Dispute], int]:
        query = select(Dispute).where(Dispute.raised_by == raised_by)
        count_query = select(func.count(Dispute.id)).where(Dispute.raised_by == raised_by)

        if status_filter:
            query = query.where(Dispute.status == status_filter)
            count_query = count_query.where(Dispute.status == status_filter)

        query = query.order_by(Dispute.created_at.desc()).offset(offset).limit(limit)
        rows = await self.db.execute(query)
        count_res = await self.db.execute(count_query)
        return list(rows.scalars().all()), int(count_res.scalar_one() or 0)
