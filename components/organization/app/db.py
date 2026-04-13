"""Database models for the Organization service."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/ethitrust_org"
)
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)

HARDCODED_ORG_ROLES: tuple[str, ...] = ("owner", "admin", "member")
ROLE_CHECK_SQL = "role IN ('owner','admin','member')"


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


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), nullable=False, index=True
    )
    # general
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    # contact info
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    phone_number: Mapped[str | None] = mapped_column(String(20), unique=True)
    address: Mapped[str | None] = mapped_column(String(512))
    # compliance
    tin: Mapped[str | None] = mapped_column(String(50), unique=True)
    kyb_level: Mapped[int] = mapped_column(
        SmallInteger, default=0
    )  # 0 = no KYB, 1 = basic, 2 = enhanced, etc.
    kyb_status: Mapped[Literal["unverified", "pending", "verified", "rejected"]] = mapped_column(
        String(20), default="unverified"
    )
    # risk
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_score: Mapped[int] = mapped_column(SmallInteger, default=0)  # 0-100 risk score
    # security
    public_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    secret_key_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    # settings
    webhook_url: Mapped[str | None] = mapped_column(String(512))
    webhook_secret: Mapped[str | None] = mapped_column(String(255))
    # status
    status: Mapped[Literal["pending_verification", "active", "suspended", "deactivated"]] = (
        mapped_column(String(20), default="pending_verification")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_organization_members_org_user"),
        CheckConstraint(ROLE_CHECK_SQL, name="ck_organization_members_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), nullable=False
    )
    role: Mapped[str] = mapped_column(String(64), default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrganizationRolePermission(Base):
    __tablename__ = "organization_role_permissions"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "role",
            "permission_key",
            name="uq_organization_role_permissions_org_role_permission",
        ),
        CheckConstraint(ROLE_CHECK_SQL, name="ck_organization_role_permissions_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    permission_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
