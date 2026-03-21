"""Repository layer for the Audit service."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AuditLog


class AuditRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, log: AuditLog) -> AuditLog:
        """Append-only insert. Never update or delete."""
        self.db.add(log)
        await self.db.flush()
        await self.db.refresh(log)
        return log

    async def list_logs(
        self,
        offset: int,
        limit: int,
        actor_id: Optional[uuid.UUID] = None,
        resource: Optional[str] = None,
        action: Optional[str] = None,
    ) -> tuple[list[AuditLog], int]:
        query = select(AuditLog)
        count_query = select(func.count(AuditLog.id))
        if actor_id:
            query = query.where(AuditLog.actor_id == actor_id)
            count_query = count_query.where(AuditLog.actor_id == actor_id)
        if resource:
            query = query.where(AuditLog.resource == resource)
            count_query = count_query.where(AuditLog.resource == resource)
        if action:
            query = query.where(AuditLog.action == action)
            count_query = count_query.where(AuditLog.action == action)

        total = (await self.db.execute(count_query)).scalar_one()
        logs = list(
            (
                await self.db.execute(
                    query.order_by(AuditLog.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return logs, total
