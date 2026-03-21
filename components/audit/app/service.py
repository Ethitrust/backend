"""Business logic for the Audit service."""

from __future__ import annotations

import uuid
from typing import Optional

from app.db import AuditLog
from app.models import AuditLogCreate
from app.repository import AuditRepository


class AuditService:
    def __init__(self, repo: AuditRepository) -> None:
        self.repo = repo

    async def log(self, data: AuditLogCreate) -> AuditLog:
        """Append-only audit log entry. Never updates or deletes."""
        entry = AuditLog(
            actor_id=data.actor_id,
            org_id=data.org_id,
            action=data.action,
            resource=data.resource,
            resource_id=data.resource_id,
            details=data.details,
            ip_address=data.ip_address,
            user_agent=data.user_agent,
        )
        return await self.repo.create(entry)

    async def query_logs(
        self,
        page: int,
        limit: int,
        actor_id: Optional[uuid.UUID] = None,
        resource: Optional[str] = None,
        action: Optional[str] = None,
    ) -> dict:
        offset = (page - 1) * limit
        logs, total = await self.repo.list_logs(
            offset, limit, actor_id, resource, action
        )
        return {"items": logs, "total": total, "page": page, "limit": limit}
