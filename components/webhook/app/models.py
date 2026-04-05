import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class OutgoingEventPayload(BaseModel):
    event: str
    data: dict
    timestamp: str  # ISO format


class WebhookLogResponse(BaseModel):
    id: uuid.UUID
    direction: str
    event: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DispatchEventRequest(BaseModel):
    event_type: str
    data: dict
    org_id: Optional[uuid.UUID] = None
