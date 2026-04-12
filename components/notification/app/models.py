"""Pydantic schemas for the Notification service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class NotificationCreate(BaseModel):
    user_id: uuid.UUID
    type: str
    title: str
    body: str
    metadata: Optional[dict[str, Any]] = None


class NotificationResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    type: str
    title: str
    body: str
    invitation_id: Optional[str] = None
    dispute_id: Optional[str] = None
    is_read: bool
    created_at: datetime
    read_at: Optional[datetime]
    model_config = {"from_attributes": True}
