"""Database models for the Fee service."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/ethitrust_fee"
)
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


class FeeLedger(Base):
    __tablename__ = "fee_ledger"

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    escrow_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), nullable=False, index=True
    )
    org_id: Mapped[Optional[uuid.UUID]] = mapped_column(pg.UUID(as_uuid=True))
    fee_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # escrow_fee | payout_fee | dispute_fee
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    paid_by: Mapped[str] = mapped_column(String(20), nullable=False)
    # buyer | seller | both | platform
    status: Mapped[str] = mapped_column(String(20), default="collected")
    # collected | refunded
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
