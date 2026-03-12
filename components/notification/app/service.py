"""Business logic for the Notification service."""

from __future__ import annotations

import json
import uuid

from app.db import Notification
from app.models import NotificationCreate
from app.repository import NotificationRepository


class NotificationService:
    def __init__(self, repo: NotificationRepository) -> None:
        self.repo = repo

    async def notify(self, data: NotificationCreate) -> Notification:
        notif = Notification(
            user_id=data.user_id,
            type=data.type,
            title=data.title,
            body=data.body,
            metadata_=json.dumps(data.metadata) if data.metadata else None,
        )
        return await self.repo.create(notif)

    async def list_notifications(
        self, user_id: uuid.UUID, page: int, limit: int
    ) -> list[Notification]:
        offset = (page - 1) * limit
        return await self.repo.list_for_user(user_id, offset, limit)

    async def mark_read(
        self, notif_id: uuid.UUID, user_id: uuid.UUID
    ) -> Notification | None:
        return await self.repo.mark_read(notif_id, user_id)

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        return await self.repo.mark_all_read(user_id)
