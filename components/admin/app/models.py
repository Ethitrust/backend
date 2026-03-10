"""Pydantic schemas for the Admin service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class UserAdminView(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime | None = None
    model_config = {"from_attributes": True}


class UserRoleUpdate(BaseModel):
    role: str = Field(..., description="admin | moderator | user")


class UserBanRequest(BaseModel):
    reason: str = Field(..., min_length=5)
    ban: bool  # True = ban, False = unban


class PlatformStats(BaseModel):
    total_users: int
    total_escrows: int
    total_transactions: int
    total_volume: int


class AdminActionLog(BaseModel):
    id: uuid.UUID
    admin_id: uuid.UUID
    action: str
    target_type: str
    target_id: uuid.UUID | None = None
    details: dict[str, Any] | None = None
    performed_at: datetime
    model_config = {"from_attributes": True}


class AdminActionLogListResponse(BaseModel):
    items: list[AdminActionLog]
    total: int
    page: int
    limit: int


class UserVerificationOverrideRequest(BaseModel):
    is_verified: bool
    reason: str = Field(..., min_length=5)
    require_dual_approval: bool = False


class UserVerificationOverrideResponse(BaseModel):
    status: Literal["applied", "pending_approval"]
    user_id: uuid.UUID
    is_verified: bool
    reason: str
    idempotency_key: str
    review_case_id: uuid.UUID | None = None


class UserRiskFlagRequest(BaseModel):
    flag: str = Field(..., min_length=2, max_length=100)
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    reason: str = Field(..., min_length=5)
    metadata: dict[str, Any] | None = None


class UserRiskFlagResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    flag: str
    severity: str
    status: str
    reason: str
    created_by: uuid.UUID
    metadata: dict[str, Any] | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class ModerationNoteCreateRequest(BaseModel):
    note: str = Field(..., min_length=3)
    visibility: Literal["internal", "restricted"] = "internal"
    case_id: uuid.UUID | None = None


class ModerationNoteResponse(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID | None = None
    target_type: str
    target_id: uuid.UUID
    note: str
    visibility: str
    created_by: uuid.UUID
    created_at: datetime
    model_config = {"from_attributes": True}


class BulkUserBanRequest(BaseModel):
    user_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=100)
    ban: bool
    reason: str = Field(..., min_length=5)
    require_dual_approval: bool = False
    priority: Literal["low", "normal", "high"] = "high"


class BulkUserBanItemResult(BaseModel):
    user_id: uuid.UUID
    status: Literal["applied", "pending_approval", "failed"]
    message: str
    review_case_id: uuid.UUID | None = None


class BulkUserBanResponse(BaseModel):
    idempotency_key: str
    action: str
    processed: int
    queued: int
    failed: int
    items: list[BulkUserBanItemResult]


class UserModerationTimelineItem(BaseModel):
    item_type: str
    source: str
    occurred_at: datetime
    actor_id: uuid.UUID | None = None
    action: str
    details: dict[str, Any] | None = None


class UserModerationTimelineResponse(BaseModel):
    user_id: uuid.UUID
    profile: dict[str, Any]
    items: list[UserModerationTimelineItem]


class DisputeQueueItem(BaseModel):
    dispute_id: uuid.UUID
    escrow_id: uuid.UUID
    status: str
    reason: str
    raised_by: uuid.UUID
    priority: str
    assignee_id: uuid.UUID | None = None
    sla_due_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    is_sla_breached: bool


class DisputeQueueListResponse(BaseModel):
    items: list[DisputeQueueItem]
    total: int
    page: int
    limit: int


class DisputeQueueUpdateRequest(BaseModel):
    priority: Literal["low", "normal", "high", "critical"] | None = None
    assignee_id: uuid.UUID | None = None
    sla_hours: int | None = Field(default=None, ge=1, le=720)
    note: str | None = Field(default=None, min_length=3)


class DisputeEvidenceRequestCreate(BaseModel):
    requested_from_user_id: uuid.UUID
    note: str = Field(..., min_length=5)
    due_in_hours: int = Field(default=48, ge=1, le=720)


class DisputeEvidenceRequestResponse(BaseModel):
    id: uuid.UUID
    dispute_id: uuid.UUID
    requested_from_user_id: uuid.UUID
    requested_by: uuid.UUID
    note: str
    status: str
    due_at: datetime
    created_at: datetime
    model_config = {"from_attributes": True}


class DisputeInternalNoteCreate(BaseModel):
    note: str = Field(..., min_length=3)


class DisputeInternalNoteResponse(BaseModel):
    id: uuid.UUID
    dispute_id: uuid.UUID
    author_id: uuid.UUID
    note: str
    created_at: datetime
    model_config = {"from_attributes": True}


class DisputeMoveReviewRequest(BaseModel):
    note: str = Field(..., min_length=5)


class DisputeResolutionDecisionRequest(BaseModel):
    escrow_id: uuid.UUID
    resolution: Literal["buyer", "seller"]
    resolution_note: str = Field(..., min_length=5)
    apply_fee_refund: bool = True


class DisputeResolutionDecisionResponse(BaseModel):
    dispute_id: uuid.UUID
    escrow_id: uuid.UUID
    status: str
    resolution: str
    fee_refund_status: str
    rationale_id: uuid.UUID


class DisputeDashboardCountersResponse(BaseModel):
    open: int
    under_review: int
    resolution_pending: int
    resolved: int
    sla_breached: int


class PayoutQueueItem(BaseModel):
    payout_id: uuid.UUID
    user_id: uuid.UUID
    wallet_id: uuid.UUID
    amount: int
    currency: str
    status: str
    provider: str | None = None
    provider_ref: str | None = None
    failure_reason: str | None = None
    priority: str
    assignee_id: uuid.UUID | None = None
    retry_count: int
    last_retry_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PayoutQueueListResponse(BaseModel):
    items: list[PayoutQueueItem]
    total: int
    page: int
    limit: int


class PayoutQueueUpdateRequest(BaseModel):
    priority: Literal["low", "normal", "high", "critical"] | None = None
    assignee_id: uuid.UUID | None = None
    note: str | None = Field(default=None, min_length=3)


class PayoutRetryRequest(BaseModel):
    note: str | None = Field(default=None, min_length=3)


class PayoutRetryResponse(BaseModel):
    payout_id: uuid.UUID
    status: str
    retry_count: int
    last_retry_at: datetime | None = None
    item: PayoutQueueItem


class FinancialDashboardCountersResponse(BaseModel):
    pending: int
    processing: int
    success: int
    failed: int
    retrying: int
    high_priority: int


class FinancialReconciliationSummaryResponse(BaseModel):
    total_transactions: int
    total_volume: int
    pending_amount: int
    processing_amount: int
    success_amount: int
    failed_amount: int
    failed_fee_refunds: int


class SystemConfigItem(BaseModel):
    key: str
    value: Any
    version: int
    updated_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class SystemConfigListResponse(BaseModel):
    items: list[SystemConfigItem]
    total: int


class SystemConfigUpsertRequest(BaseModel):
    value: Any
    reason: str = Field(..., min_length=5)


class SystemConfigDryRunRequest(BaseModel):
    key: str = Field(..., min_length=3, max_length=120)
    value: Any


class SystemConfigDryRunResponse(BaseModel):
    key: str
    valid: bool
    errors: list[str]
    normalized_value: Any
    current_version: int | None = None
    next_version: int | None = None


class SystemConfigRollbackRequest(BaseModel):
    target_version: int = Field(..., ge=1)
    reason: str = Field(..., min_length=5)


class SystemConfigHistoryItem(BaseModel):
    id: uuid.UUID
    key: str
    version: int
    action: str
    previous_value: Any = None
    new_value: Any = None
    changed_by: uuid.UUID
    reason: str
    metadata: dict[str, Any] | None = None
    created_at: datetime
    model_config = {"from_attributes": True}


class SystemConfigHistoryResponse(BaseModel):
    key: str
    items: list[SystemConfigHistoryItem]


class SystemConfigMutationResponse(BaseModel):
    action: str
    item: SystemConfigItem
    history: SystemConfigHistoryItem


class AnalyticsKpiPoint(BaseModel):
    bucket: datetime
    value: float


class AnalyticsGrowthResponse(BaseModel):
    window_days: int
    disputes_created: list[AnalyticsKpiPoint]
    payouts_created: list[AnalyticsKpiPoint]
    payout_volume: list[AnalyticsKpiPoint]


class AnalyticsDisputeThroughputResponse(BaseModel):
    window_days: int
    opened: int
    resolved: int
    resolution_rate: float
    avg_resolution_hours: float | None
    opened_series: list[AnalyticsKpiPoint]
    resolved_series: list[AnalyticsKpiPoint]


class AnalyticsPayoutHealthResponse(BaseModel):
    window_days: int
    pending: int
    processing: int
    success: int
    failed: int
    retrying: int
    success_rate: float
    success_series: list[AnalyticsKpiPoint]
    failed_series: list[AnalyticsKpiPoint]


class AnalyticsVolumeResponse(BaseModel):
    window_days: int
    total_volume: int
    success_volume: int
    failed_volume: int
    volume_series: list[AnalyticsKpiPoint]


class SavedViewCreateRequest(BaseModel):
    module: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., min_length=2, max_length=120)
    filters: dict[str, Any]
    is_shared: bool = False


class SavedViewUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    filters: dict[str, Any] | None = None
    is_shared: bool | None = None


class SavedViewResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    module: str
    name: str
    filters: dict[str, Any]
    is_shared: bool
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class SavedViewListResponse(BaseModel):
    items: list[SavedViewResponse]
    total: int
    page: int
    limit: int


class ReportJobCreateRequest(BaseModel):
    report_type: Literal[
        "growth",
        "dispute_throughput",
        "payout_health",
        "volume",
        "dashboard_snapshot",
    ]
    export_format: Literal["csv", "json"] = "json"
    filters: dict[str, Any] | None = None


class ReportJobResponse(BaseModel):
    id: uuid.UUID
    requested_by: uuid.UUID
    report_type: str
    export_format: str
    filters: dict[str, Any] | None = None
    status: str
    result_url: str | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    model_config = {"from_attributes": True}


class ReportJobListResponse(BaseModel):
    items: list[ReportJobResponse]
    total: int
    page: int
    limit: int
