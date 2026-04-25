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
    "open_negotiation",
    "settlement_pending_confirmation",
    "settled_by_parties",
    "escalated_mediation",
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


class DisputeMessageCreate(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class DisputeMessageResponse(BaseModel):
    id: uuid.UUID
    dispute_id: uuid.UUID
    sender_id: uuid.UUID
    message: str
    is_system: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class RequestEvidenceUpload(BaseModel):
    object_key: str = Field(..., min_length=3, max_length=512)
    content_type: str = Field(..., min_length=3, max_length=100)
    expires_in_seconds: int = Field(default=900, ge=1, le=3600)


class ConfirmEvidenceUpload(BaseModel):
    object_key: str = Field(..., min_length=3, max_length=512)
    file_type: str = Field(..., min_length=3, max_length=100)
    description: str = Field(default="", max_length=1000)
    message_id: uuid.UUID | None = None


class PresignedUploadResponse(BaseModel):
    url: str
    method: str
    object_key: str
    expires_in_seconds: int


class SettlementAction(BaseModel):
    note: str = Field(..., min_length=3, max_length=1000)


class DisputeAccessCheckResponse(BaseModel):
    allowed: bool
    dispute_id: uuid.UUID
    escrow_id: uuid.UUID


class MediatorDecisionRequest(BaseModel):
    resolution: DisputeResolution = Field(..., description="buyer | seller")
    rationale: str = Field(..., min_length=5, max_length=2000)


class DisputeExecutionRequest(BaseModel):
    resolution: DisputeResolution = Field(..., description="buyer | seller")
    admin_id: uuid.UUID | None = None


class EvidenceResponse(BaseModel):
    id: uuid.UUID
    dispute_id: uuid.UUID
    uploaded_by: uuid.UUID
    object_key: Optional[str] = None
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
    negotiation_started_at: datetime
    negotiation_deadline_at: datetime
    escalated_at: Optional[datetime]
    assigned_mediator_id: Optional[uuid.UUID]
    settlement_requested_by: Optional[uuid.UUID]
    settlement_confirmed_by: Optional[uuid.UUID]
    created_at: datetime
    evidence: list[EvidenceResponse] = Field(default_factory=list)
    messages: list[DisputeMessageResponse] = Field(default_factory=list)
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
    negotiation_deadline_at: datetime
    assigned_mediator_id: Optional[uuid.UUID]
    created_at: datetime
    model_config = {"from_attributes": True}


class PaginatedDisputeResponse(BaseModel):
    items: list[DisputeSummaryResponse]
    total: int
    page: int
    limit: int
    pages: int
    model_config = {"from_attributes": True}
