"""Repository layer for the Notification service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Notification


class NotificationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, notif: Notification) -> Notification:
        self.db.add(notif)
        await self.db.flush()
        await self.db.refresh(notif)
        return notif

    async def list_for_user(
        self, user_id: uuid.UUID, offset: int, limit: int
    ) -> list[Notification]:
        r = await self.db.execute(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(r.scalars().all())

    async def mark_read(
        self, notif_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[Notification]:
        r = await self.db.execute(
            select(Notification).where(
                Notification.id == notif_id, Notification.user_id == user_id
            )
        )
        notif = r.scalar_one_or_none()
        if notif is None:
            return None
        notif.is_read = True
        notif.read_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(notif)
        return notif

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        r = await self.db.execute(
            select(Notification).where(
                Notification.user_id == user_id, Notification.is_read == False
            )  # noqa: E712
        )
        notifs = list(r.scalars().all())
        now = datetime.now(timezone.utc)
        for n in notifs:
            n.is_read = True
            n.read_at = now
        await self.db.flush()
        return len(notifs)
