import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import WebhookLog


class WebhookRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def save_log(
        self,
        direction: str,
        event: str,
        payload: dict,
        status: str,
        org_id: Optional[uuid.UUID] = None,
        target_url: Optional[str] = None,
    ) -> WebhookLog:
        log = WebhookLog(
            direction=direction,
            event=event,
            payload=payload,
            status=status,
            org_id=org_id,
            target_url=target_url,
        )
        self.db.add(log)
        await self.db.flush()
        await self.db.refresh(log)
        return log

    async def update_log_status(self, log_id: uuid.UUID, status: str) -> None:
        result = await self.db.execute(
            select(WebhookLog).where(WebhookLog.id == log_id)
        )
        log = result.scalar_one_or_none()
        if log:
            log.status = status
            await self.db.flush()

    async def get_logs(self, offset: int, limit: int) -> list[WebhookLog]:
        result = await self.db.execute(
            select(WebhookLog)
            .order_by(WebhookLog.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())
