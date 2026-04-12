"""
Data-access layer for the Escrow service.

All queries are async via SQLAlchemy 2.x select/execute API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import CounterOffer, Escrow, Milestone, RecurringContributor, RecurringCycle


class EscrowRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Escrow ────────────────────────────────────────────────────────────────

    async def create(self, **kwargs) -> Escrow:
        escrow = Escrow(**kwargs)
        self.db.add(escrow)
        await self.db.commit()
        await self.db.refresh(escrow)
        return escrow

    async def get_by_id(self, escrow_id: uuid.UUID) -> Escrow | None:
        result = await self.db.execute(select(Escrow).where(Escrow.id == escrow_id))
        return result.scalar_one_or_none()

    async def get_by_ref(self, ref: str) -> Escrow | None:
        result = await self.db.execute(
            select(Escrow).where(Escrow.transaction_ref == ref)
        )
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        user_email: str | None,
        offset: int,
        limit: int,
        status_filter: Optional[str],
    ) -> tuple[list[Escrow], int]:
        participant_filter = or_(
            Escrow.initiator_id == user_id,
            Escrow.receiver_id == user_id,
        )
        invitee_filter = and_(
            Escrow.receiver_id.is_(None),
            Escrow.receiver_email == user_email,
            Escrow.status.in_(
                (
                    "invited",
                    "counter_pending_initiator",
                    "counter_pending_counterparty",
                )
            ),
        )

        base = select(Escrow).where(
            or_(participant_filter, invitee_filter)
            if user_email
            else participant_filter
        )
        if status_filter:
            base = base.where(Escrow.status == status_filter)

        count_q = select(func.count()).select_from(base.subquery())
        total_result = await self.db.execute(count_q)
        total = total_result.scalar_one()

        rows_result = await self.db.execute(
            base.order_by(Escrow.created_at.desc()).offset(offset).limit(limit)
        )
        items = list(rows_result.scalars().all())
        return items, total

    async def update_status(self, escrow: Escrow, status: str) -> Escrow:
        escrow.status = status
        await self.db.commit()
        await self.db.refresh(escrow)
        return escrow

    async def save(self, escrow: Escrow) -> Escrow:
        await self.db.commit()
        await self.db.refresh(escrow)
        return escrow

    async def list_expired_invitations(self, now: datetime) -> list[Escrow]:
        invitation_statuses = (
            "invited",
            "counter_pending_initiator",
            "counter_pending_counterparty",
        )
        result = await self.db.execute(
            select(Escrow).where(
                Escrow.status.in_(invitation_statuses),
                Escrow.invite_expires_at.is_not(None),
                Escrow.invite_expires_at <= now,
            )
        )
        return list(result.scalars().all())

    async def list_pending_unfunded_for_participant(
        self,
        user_id: uuid.UUID,
    ) -> list[Escrow]:
        result = await self.db.execute(
            select(Escrow)
            .where(
                Escrow.status == "pending",
                Escrow.funded_at.is_(None),
                or_(
                    Escrow.initiator_id == user_id,
                    Escrow.receiver_id == user_id,
                ),
            )
            .order_by(Escrow.created_at.asc())
        )
        return list(result.scalars().all())

    async def create_counter_offer(self, **kwargs) -> CounterOffer:
        counter_offer = CounterOffer(**kwargs)
        self.db.add(counter_offer)
        await self.db.commit()
        await self.db.refresh(counter_offer)
        return counter_offer

    async def get_counter_offer_by_version(
        self,
        escrow_id: uuid.UUID,
        offer_version: int,
    ) -> CounterOffer | None:
        result = await self.db.execute(
            select(CounterOffer).where(
                CounterOffer.escrow_id == escrow_id,
                CounterOffer.offer_version == offer_version,
            )
        )
        return result.scalar_one_or_none()

    async def list_counter_offers(self, escrow_id: uuid.UUID) -> list[CounterOffer]:
        result = await self.db.execute(
            select(CounterOffer)
            .where(CounterOffer.escrow_id == escrow_id)
            .order_by(CounterOffer.offer_version.asc(), CounterOffer.created_at.asc())
        )
        return list(result.scalars().all())

    async def save_counter_offer(self, counter_offer: CounterOffer) -> CounterOffer:
        await self.db.commit()
        await self.db.refresh(counter_offer)
        return counter_offer

    # ── Milestone ─────────────────────────────────────────────────────────────

    async def create_milestone(self, **kwargs) -> Milestone:
        milestone = Milestone(**kwargs)
        self.db.add(milestone)
        await self.db.commit()
        await self.db.refresh(milestone)
        return milestone

    async def get_milestones(self, escrow_id: uuid.UUID) -> list[Milestone]:
        result = await self.db.execute(
            select(Milestone)
            .where(Milestone.escrow_id == escrow_id)
            .order_by(Milestone.sort_order)
        )
        return list(result.scalars().all())

    async def get_milestone(self, milestone_id: uuid.UUID) -> Milestone | None:
        result = await self.db.execute(
            select(Milestone).where(Milestone.id == milestone_id)
        )
        return result.scalar_one_or_none()

    async def update_milestone(self, milestone: Milestone, **kwargs) -> Milestone:
        for key, value in kwargs.items():
            setattr(milestone, key, value)
        await self.db.commit()
        await self.db.refresh(milestone)
        return milestone

    # ── Recurring ─────────────────────────────────────────────────────────────

    async def create_recurring_cycle(self, **kwargs) -> RecurringCycle:
        cycle = RecurringCycle(**kwargs)
        self.db.add(cycle)
        await self.db.commit()
        await self.db.refresh(cycle)
        return cycle

    async def get_cycle(self, escrow_id: uuid.UUID) -> RecurringCycle | None:
        result = await self.db.execute(
            select(RecurringCycle).where(RecurringCycle.escrow_id == escrow_id)
        )
        return result.scalar_one_or_none()

    async def get_due_cycles(self, now) -> list[RecurringCycle]:
        result = await self.db.execute(
            select(RecurringCycle).where(
                RecurringCycle.status == "active",
                RecurringCycle.due_date <= now,
            )
        )
        return list(result.scalars().all())

    async def get_contributors(self, cycle_id: uuid.UUID) -> list[RecurringContributor]:
        result = await self.db.execute(
            select(RecurringContributor).where(
                RecurringContributor.cycle_id == cycle_id
            )
        )
        return list(result.scalars().all())

    async def count_contributors(self, cycle_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count()).where(RecurringContributor.cycle_id == cycle_id)
        )
        return result.scalar_one()

    async def add_contributor(self, **kwargs) -> RecurringContributor:
        contributor = RecurringContributor(**kwargs)
        self.db.add(contributor)
        await self.db.commit()
        await self.db.refresh(contributor)
        return contributor
