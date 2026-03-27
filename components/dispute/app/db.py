"""Database models for the Dispute service."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Optional

import sqlalchemy.dialects.postgresql as pg
from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/ethitrust_dispute"
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


class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    escrow_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), nullable=False, index=True
    )
    raised_by: Mapped[uuid.UUID] = mapped_column(pg.UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    # not_delivered | wrong_item | quality_issue | fraud | other
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open")
    # open | under_review | resolution_pending_buyer | resolution_pending_seller |
    # resolved_buyer | resolved_seller | cancelled
    resolution_note: Mapped[Optional[str]] = mapped_column(Text)
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(pg.UUID(as_uuid=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DisputeEvidence(Base):
    __tablename__ = "dispute_evidence"

    id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dispute_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), nullable=False, index=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), nullable=False
    )
    file_url: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[Optional[str]] = mapped_column(String(50))
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
