"""Pydantic schemas for the Dispute service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

DisputeReason = Literal[
    "not_delivered",
    "wrong_item",
    "quality_issue",
    "fraud",
    "other",
]
DisputeResolution = Literal["buyer", "seller"]
DisputeStatus = Literal[
    "open",
    "under_review",
    "resolution_pending_buyer",
    "resolution_pending_seller",
    "resolved_buyer",
    "resolved_seller",
    "cancelled",
]


class DisputeCreate(BaseModel):
    reason: DisputeReason = Field(
        ..., description="not_delivered | wrong_item | quality_issue | fraud | other"
    )
    description: str = Field(..., min_length=10)


class DisputeResolve(BaseModel):
    resolution: DisputeResolution = Field(..., description="buyer | seller")
    resolution_note: str = Field(..., min_length=5)


class DisputeReviewRequest(BaseModel):
    note: str | None = Field(default=None, min_length=5)


class DisputeExecutionRequest(BaseModel):
    resolution: DisputeResolution = Field(..., description="buyer | seller")
    admin_id: uuid.UUID | None = None


class EvidenceResponse(BaseModel):
    id: uuid.UUID
    dispute_id: uuid.UUID
    uploaded_by: uuid.UUID
    file_url: str
    file_type: Optional[str]
    description: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}


class DisputeResponse(BaseModel):
    id: uuid.UUID
    escrow_id: uuid.UUID
    raised_by: uuid.UUID
    reason: DisputeReason
    description: str
    status: DisputeStatus
    resolution_note: Optional[str]
    resolved_by: Optional[uuid.UUID]
    resolved_at: Optional[datetime]
    created_at: datetime
    evidence: list[EvidenceResponse] = Field(default_factory=list)
    model_config = {"from_attributes": True}


class DisputeSummaryResponse(BaseModel):
    id: uuid.UUID
    escrow_id: uuid.UUID
    raised_by: uuid.UUID
    reason: DisputeReason
    status: DisputeStatus
    resolution_note: Optional[str]
    resolved_by: Optional[uuid.UUID]
    resolved_at: Optional[datetime]
    created_at: datetime
    model_config = {"from_attributes": True}


class PaginatedDisputeResponse(BaseModel):
    items: list[DisputeSummaryResponse]
    total: int
    page: int
    limit: int
    pages: int
    model_config = {"from_attributes": True}
