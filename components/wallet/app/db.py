"""SQLAlchemy models and async engine setup for the Wallet service."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Literal, Optional

import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost/ethitrust_wallet",
)

engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    locked_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_wallet_balance_non_negative"),
        CheckConstraint(
            "locked_balance >= 0", name="ck_wallet_locked_balance_non_negative"
        ),
        UniqueConstraint("owner_id", "currency", name="uq_wallet_owner_currency"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("wallets.id"), nullable=False, index=True
    )
    escrow_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        pg.UUID(as_uuid=True), nullable=True
    )
    # deposit | payout | escrow_lock | escrow_release | transfer | fee | refund
    type: Mapped[
        Literal[
            "deposit",
            "payout",
            "escrow_lock",
            "escrow_release",
            "transfer",
            "fee",
            "refund",
        ]
    ] = mapped_column(String(30), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    # pending | success | failed
    status: Mapped[str] = mapped_column(String(20), default="pending")
    reference: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WalletLock(Base):
    __tablename__ = "wallet_locks"

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    wallet_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("wallets.id"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    # ESCROW | DISPUTE_HOLD | PAYOUT_REVIEW | COMPLIANCE_HOLD
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    # ESCROW | DISPUTE | PAYOUT | COMPLIANCE | ...
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # locked | released | captured | cancelled
    status: Mapped[str] = mapped_column(String(20), default="locked", nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_wallet_lock_amount_positive"),
        CheckConstraint(
            "status IN ('locked', 'released', 'captured', 'cancelled')",
            name="ck_wallet_lock_status_valid",
        ),
    )


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
