"""
SQLAlchemy ORM models for the Escrow service.

Tables:
  - escrows            (core escrow record)
  - milestones         (for milestone-type escrows)
  - recurring_cycles   (for recurring-type escrows)
  - recurring_contributors (participants in a cycle)
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Literal, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.settings import (
    DEFAULT_DISPUTE_WINDOW_HOURS,
    DEFAULT_INSPECTION_PERIOD_HOURS,
    DEFAULT_MILESTONE_INSPECTION_HOURS,
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost/ethitrust_escrow",
)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session_factory() as session:
        yield session


# ─────────────────────────────────────────────────────────────────────────────
# Escrow
# ─────────────────────────────────────────────────────────────────────────────


class Escrow(Base):
    __tablename__ = "escrows"
    __table_args__ = (
        CheckConstraint(
            "escrow_type IN ('onetime', 'milestone', 'recurring')",
            name="ck_escrows_type",
        ),
        CheckConstraint(
            "status IN ('invited', 'counter_pending_initiator', 'counter_pending_counterparty', 'rejected', 'expired', 'pending', 'active', 'completed', 'disputed', 'cancelled', 'refunded')",
            name="ck_escrows_status",
        ),
        CheckConstraint(
            "counter_status IN ('none', 'awaiting_initiator', 'awaiting_counterparty', 'accepted', 'rejected')",
            name="ck_escrows_counter_status",
        ),
        CheckConstraint(
            "initiator_role IN ('buyer', 'seller', 'broker')",
            name="ck_escrows_initiator_role",
        ),
        CheckConstraint(
            "initiator_actor_type IN ('user', 'organization')",
            name="ck_escrows_initiator_actor_type",
        ),
        CheckConstraint(
            "((initiator_actor_type = 'user' AND initiator_id IS NOT NULL AND initiator_org_id IS NULL) OR (initiator_actor_type = 'organization' AND initiator_id IS NULL AND initiator_org_id IS NOT NULL))",
            name="ck_escrows_initiator_actor_consistency",
        ),
        CheckConstraint(
            "who_pays_fees IN ('buyer', 'seller', 'split')",
            name="ck_escrows_who_pays_fees",
        ),
        CheckConstraint(
            "how_dispute_handled IN ('platform', 'arbitrator', 'mutual')",
            name="ck_escrows_dispute_handled",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    transaction_ref: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    escrow_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[
        Literal[
            "invited",
            "counter_pending_initiator",
            "counter_pending_counterparty",
            "rejected",
            "expired",
            "pending",  # TODO: investigate when to use 'pending' vs 'active'
            "active",
            "completed",
            "disputed",
            "cancelled",
            "refunded",
        ]
    ] = mapped_column(String(30), default="invited", nullable=False)
    initiator_actor_type: Mapped[Literal["user", "organization"]] = mapped_column(
        String(20), default="user", nullable=False
    )
    initiator_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        pg.UUID(as_uuid=True), nullable=True, index=True
    )
    initiator_org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        pg.UUID(as_uuid=True), nullable=True, index=True
    )
    receiver_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        pg.UUID(as_uuid=True), nullable=True
    )
    receiver_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    initiator_role: Mapped[str] = mapped_column(
        String(20), default="buyer", nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    acceptance_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    inspection_period: Mapped[int] = mapped_column(
        Integer,
        default=DEFAULT_INSPECTION_PERIOD_HOURS,
        nullable=False,
    )
    delivery_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dispute_window: Mapped[int] = mapped_column(
        Integer,
        default=DEFAULT_DISPUTE_WINDOW_HOURS,
        nullable=False,
    )
    # For now let's not use "arbitrator", "mutual" let's just use "platform" and handle disputes in-platform, but keeping the option open for future handling methods
    how_dispute_handled: Mapped[Literal["platform"]] = mapped_column(
        String(20), default="platform", nullable=False
    )
    who_pays_fees: Mapped[Literal["buyer", "seller", "split"]] = mapped_column(
        String(10), default="buyer", nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), default="chapa", nullable=False)
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        pg.UUID(as_uuid=True), nullable=True
    )
    invite_token_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    invite_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invite_token_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    offer_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    counter_status: Mapped[
        Literal[
            "none",
            "awaiting_initiator",
            "awaiting_counterparty",
            "accepted",
            "rejected",
        ]
    ] = mapped_column(String(30), default="none", nullable=False)
    active_counter_offer_version: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    last_countered_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        pg.UUID(as_uuid=True), nullable=True
    )
    last_countered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    initiator_accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    receiver_accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    funded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Milestone
# ─────────────────────────────────────────────────────────────────────────────


class Milestone(Base):
    __tablename__ = "milestones"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'delivered', 'completed', 'disputed')",
            name="ck_milestones_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    escrow_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("escrows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    due_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    inspection_hrs: Mapped[int] = mapped_column(
        Integer,
        default=DEFAULT_MILESTONE_INSPECTION_HOURS,
        nullable=False,
    )
    status: Mapped[
        Literal["pending", "in_progress", "delivered", "completed", "disputed"]
    ] = mapped_column(String(30), default="pending", nullable=False)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class CounterOffer(Base):
    __tablename__ = "counter_offers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_response', 'accepted', 'rejected', 'countered_again')",
            name="ck_counter_offers_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    escrow_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("escrows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    offer_version: Mapped[int] = mapped_column(Integer, nullable=False)
    proposed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), nullable=False
    )
    proposed_to_user_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), nullable=False
    )
    status: Mapped[
        Literal["pending_response", "accepted", "rejected", "countered_again"]
    ] = mapped_column(
        String(30),
        default="pending_response",
        nullable=False,
    )
    responded_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        pg.UUID(as_uuid=True), nullable=True
    )
    responded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    acceptance_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    inspection_period: Mapped[int] = mapped_column(Integer, nullable=False)
    delivery_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dispute_window: Mapped[int] = mapped_column(Integer, nullable=False)
    how_dispute_handled: Mapped[str] = mapped_column(String(20), nullable=False)
    who_pays_fees: Mapped[str] = mapped_column(String(10), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# Recurring Cycle
# ─────────────────────────────────────────────────────────────────────────────


class RecurringCycle(Base):
    __tablename__ = "recurring_cycles"
    __table_args__ = (
        CheckConstraint(
            "cycle_interval IN ('daily', 'weekly', 'monthly')",
            name="ck_recurring_cycle_interval",
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'completed')",
            name="ck_recurring_cycle_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    escrow_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("escrows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cycle_interval: Mapped[Literal["daily", "weekly", "monthly"]] = mapped_column(
        String(20), default="monthly", nullable=False
    )
    due_day_of_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expected_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    due_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    min_contributors: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_contributors: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[Literal["pending", "active", "completed"]] = mapped_column(
        String(20), default="pending", nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# Recurring Contributor
# ─────────────────────────────────────────────────────────────────────────────


class RecurringContributor(Base):
    __tablename__ = "recurring_contributors"

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("recurring_cycles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        pg.UUID(as_uuid=True), nullable=True
    )
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    expected_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
