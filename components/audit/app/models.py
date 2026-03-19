"""Pydantic schemas for the Audit service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class AuditLogCreate(BaseModel):
    actor_id: Optional[uuid.UUID] = None
    org_id: Optional[uuid.UUID] = None
    action: str
    resource: str
    resource_id: Optional[uuid.UUID] = None
    details: Optional[dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    actor_id: Optional[uuid.UUID]
    org_id: Optional[uuid.UUID]
    action: str
    resource: str
    resource_id: Optional[uuid.UUID]
    details: Optional[dict]
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}


class AuditLogFilter(BaseModel):
    actor_id: Optional[uuid.UUID] = None
    resource: Optional[str] = None
    action: Optional[str] = None
