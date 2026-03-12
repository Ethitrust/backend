"""FastAPI route handlers for the Admin service."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app import grpc_clients
from app.db import get_db
from app.models import (
    AdminActionLogListResponse,
    AnalyticsDisputeThroughputResponse,
    AnalyticsGrowthResponse,
    AnalyticsPayoutHealthResponse,
    AnalyticsVolumeResponse,
    BulkUserBanRequest,
    BulkUserBanResponse,
    DisputeDashboardCountersResponse,
    DisputeEvidenceRequestCreate,
    DisputeEvidenceRequestResponse,
    DisputeInternalNoteCreate,
    DisputeInternalNoteResponse,
    DisputeMoveReviewRequest,
    DisputeQueueItem,
    DisputeQueueListResponse,
    DisputeQueueUpdateRequest,
    DisputeResolutionDecisionRequest,
    DisputeResolutionDecisionResponse,
    FinancialDashboardCountersResponse,
    FinancialReconciliationSummaryResponse,
    ModerationNoteCreateRequest,
    ModerationNoteResponse,
    PayoutQueueItem,
    PayoutQueueListResponse,
    PayoutQueueUpdateRequest,
    PayoutRetryRequest,
    PayoutRetryResponse,
    PlatformStats,
    ReportJobCreateRequest,
    ReportJobListResponse,
    ReportJobResponse,
    SavedViewCreateRequest,
    SavedViewListResponse,
    SavedViewResponse,
    SavedViewUpdateRequest,
    SystemConfigDryRunRequest,
    SystemConfigDryRunResponse,
    SystemConfigHistoryResponse,
    SystemConfigItem,
    SystemConfigListResponse,
    SystemConfigMutationResponse,
    SystemConfigRollbackRequest,
    SystemConfigUpsertRequest,
    UserAdminView,
    UserBanRequest,
    UserModerationTimelineResponse,
    UserRiskFlagRequest,
    UserRiskFlagResponse,
    UserRoleUpdate,
    UserVerificationOverrideRequest,
    UserVerificationOverrideResponse,
)
from app.permissions import has_scope
from app.repository import AdminRepository
from app.service import AdminService

router = APIRouter(prefix="/admin", tags=["admin"])

security = HTTPBearer(auto_error=False)


async def get_current_user(
    authorization: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(security),
    ],
) -> dict:
    if authorization is None or not authorization.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
        )
    try:
        user = await grpc_clients.validate_token(authorization.credentials)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    user = dict(user)
    user["token"] = authorization.credentials
    return user


def require_scope(required_scope: str):
    def _dependency(current_user: dict = Depends(get_current_user)) -> dict:
        if not has_scope(current_user, required_scope):
            role = current_user.get("role", "unknown")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Missing required scope '{required_scope}' for role '{role}'."
                ),
            )
        return current_user

    return _dependency


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> AdminService:
    return AdminService(AdminRepository(db))


def require_idempotency_key(
    x_idempotency_key: Annotated[str | None, Header(alias="X-Idempotency-Key")] = None,
) -> str:
    if x_idempotency_key is None or not x_idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Idempotency-Key header is required",
        )
    return x_idempotency_key.strip()


@router.get("/users", response_model=list[UserAdminView])
async def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    _current_user: dict = Depends(require_scope("users.read")),
    svc: AdminService = Depends(get_service),
):
    """List all platform users (admin/moderator)."""
    offset = (page - 1) * limit
    return await svc.list_users(offset, limit)


@router.patch("/users/{user_id}/role", response_model=UserAdminView)
async def update_user_role(
    user_id: uuid.UUID,
    body: UserRoleUpdate,
    current_user: dict = Depends(require_scope("users.role.update")),
    svc: AdminService = Depends(get_service),
):
    """Change a user's role (admin only)."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.update_role(user_id, body.role, admin_id)


@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: uuid.UUID,
    body: UserBanRequest,
    current_user: dict = Depends(require_scope("users.ban.manage")),
    svc: AdminService = Depends(get_service),
):
    """Ban or unban a user (admin only)."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.ban_user(user_id, body.ban, body.reason, admin_id)


@router.post(
    "/users/{user_id}/verification-override",
    response_model=UserVerificationOverrideResponse,
)
async def override_user_verification(
    user_id: uuid.UUID,
    body: UserVerificationOverrideRequest,
    current_user: dict = Depends(require_scope("users.verify.override")),
    idempotency_key: str = Depends(require_idempotency_key),
    svc: AdminService = Depends(get_service),
):
    """Override a user's verification status with optional dual-approval."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.set_user_verification_override(
        user_id=user_id,
        body=body,
        admin_id=admin_id,
        idempotency_key=idempotency_key,
    )


@router.post("/users/{user_id}/risk-flags", response_model=UserRiskFlagResponse)
async def create_user_risk_flag(
    user_id: uuid.UUID,
    body: UserRiskFlagRequest,
    current_user: dict = Depends(require_scope("users.risk_flags.manage")),
    svc: AdminService = Depends(get_service),
):
    """Create a user risk flag for governance workflows."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.create_user_risk_flag(
        user_id=user_id,
        body=body,
        admin_id=admin_id,
    )


@router.post(
    "/users/{user_id}/moderation-notes",
    response_model=ModerationNoteResponse,
)
async def add_user_moderation_note(
    user_id: uuid.UUID,
    body: ModerationNoteCreateRequest,
    current_user: dict = Depends(require_scope("users.moderation_notes.write")),
    svc: AdminService = Depends(get_service),
):
    """Attach internal moderation notes to a user profile."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.add_moderation_note(
        user_id=user_id,
        body=body,
        admin_id=admin_id,
    )


@router.get("/users/{user_id}/timeline", response_model=UserModerationTimelineResponse)
async def get_user_moderation_timeline(
    user_id: uuid.UUID,
    limit: int = Query(200, ge=1, le=500),
    _current_user: dict = Depends(require_scope("users.timeline.read")),
    svc: AdminService = Depends(get_service),
):
    """Get a unified user moderation timeline (cross-service + admin-local metadata)."""
    return await svc.get_user_moderation_timeline(user_id=user_id, limit=limit)


@router.post("/bulk/users/ban", response_model=BulkUserBanResponse)
async def bulk_ban_users(
    body: BulkUserBanRequest,
    current_user: dict = Depends(require_scope("users.bulk_actions.execute")),
    idempotency_key: str = Depends(require_idempotency_key),
    svc: AdminService = Depends(get_service),
):
    """Execute or queue controlled bulk ban/unban actions with safeguards."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.bulk_ban_users(
        body=body,
        admin_id=admin_id,
        idempotency_key=idempotency_key,
    )


@router.get("/disputes/queue", response_model=DisputeQueueListResponse)
async def list_dispute_queue(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    assignee_id: uuid.UUID | None = Query(None),
    priority: str | None = Query(None),
    current_user: dict = Depends(require_scope("disputes.queue.read")),
    svc: AdminService = Depends(get_service),
):
    """List and synchronize dispute queue items for command-center triage."""
    return await svc.list_dispute_queue(
        token=str(current_user["token"]),
        page=page,
        limit=limit,
        status_filter=status_filter,
        assignee_id=assignee_id,
        priority=priority,
    )


@router.patch("/disputes/{dispute_id}/queue", response_model=DisputeQueueItem)
async def update_dispute_queue_item(
    dispute_id: uuid.UUID,
    body: DisputeQueueUpdateRequest,
    current_user: dict = Depends(require_scope("disputes.queue.update")),
    svc: AdminService = Depends(get_service),
):
    """Update local queue metadata like assignee, priority, and SLA due time."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.update_dispute_queue_item(
        dispute_id=dispute_id,
        body=body,
        admin_id=admin_id,
    )


@router.post(
    "/disputes/{dispute_id}/evidence-requests",
    response_model=DisputeEvidenceRequestResponse,
)
async def create_dispute_evidence_request(
    dispute_id: uuid.UUID,
    body: DisputeEvidenceRequestCreate,
    current_user: dict = Depends(require_scope("disputes.evidence.request")),
    svc: AdminService = Depends(get_service),
):
    """Create an internal evidence request task for a dispute participant."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.create_dispute_evidence_request(
        dispute_id=dispute_id,
        body=body,
        admin_id=admin_id,
    )


@router.post(
    "/disputes/{dispute_id}/internal-notes",
    response_model=DisputeInternalNoteResponse,
)
async def add_dispute_internal_note(
    dispute_id: uuid.UUID,
    body: DisputeInternalNoteCreate,
    current_user: dict = Depends(require_scope("disputes.notes.write")),
    svc: AdminService = Depends(get_service),
):
    """Add private moderation notes for dispute deliberation context."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.add_dispute_internal_note(
        dispute_id=dispute_id,
        body=body,
        admin_id=admin_id,
    )


@router.post("/disputes/{dispute_id}/review", response_model=DisputeQueueItem)
async def move_dispute_to_review(
    dispute_id: uuid.UUID,
    body: DisputeMoveReviewRequest,
    current_user: dict = Depends(require_scope("disputes.review.move")),
    svc: AdminService = Depends(get_service),
):
    """Move dispute status to under-review and assign to current reviewer."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.move_dispute_to_review(
        dispute_id=dispute_id,
        body=body,
        admin_id=admin_id,
        token=str(current_user["token"]),
    )


@router.post(
    "/disputes/{dispute_id}/resolution",
    response_model=DisputeResolutionDecisionResponse,
)
async def decide_dispute_resolution(
    dispute_id: uuid.UUID,
    body: DisputeResolutionDecisionRequest,
    current_user: dict = Depends(require_scope("disputes.resolution.execute")),
    svc: AdminService = Depends(get_service),
):
    """Queue + execute dispute resolution and persist rationale/audit trail."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.decide_dispute_resolution(
        dispute_id=dispute_id,
        body=body,
        admin_id=admin_id,
        token=str(current_user["token"]),
    )


@router.get(
    "/disputes/dashboard/counters",
    response_model=DisputeDashboardCountersResponse,
)
async def get_dispute_dashboard_counters(
    _current_user: dict = Depends(require_scope("disputes.dashboard.read")),
    svc: AdminService = Depends(get_service),
):
    """Return queue counters for command-center summary widgets."""
    return await svc.get_dispute_dashboard_counters()


@router.get("/payouts/queue", response_model=PayoutQueueListResponse)
async def list_payout_queue(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    status_filter: str | None = Query(None, alias="status"),
    assignee_id: uuid.UUID | None = Query(None),
    priority: str | None = Query(None),
    provider: str | None = Query(None),
    current_user: dict = Depends(require_scope("payouts.queue.read")),
    svc: AdminService = Depends(get_service),
):
    """List and synchronize payout queue items for financial operations."""
    return await svc.list_payout_queue(
        token=str(current_user["token"]),
        page=page,
        limit=limit,
        status_filter=status_filter,
        assignee_id=assignee_id,
        priority=priority,
        provider=provider,
    )


@router.patch("/payouts/{payout_id}/queue", response_model=PayoutQueueItem)
async def update_payout_queue_item(
    payout_id: uuid.UUID,
    body: PayoutQueueUpdateRequest,
    current_user: dict = Depends(require_scope("payouts.queue.update")),
    svc: AdminService = Depends(get_service),
):
    """Update local payout queue metadata like assignee and priority."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.update_payout_queue_item(
        payout_id=payout_id,
        body=body,
        admin_id=admin_id,
    )


@router.post("/payouts/{payout_id}/retry", response_model=PayoutRetryResponse)
async def retry_payout_transfer(
    payout_id: uuid.UUID,
    body: PayoutRetryRequest,
    current_user: dict = Depends(require_scope("payouts.retry.execute")),
    svc: AdminService = Depends(get_service),
):
    """Trigger payout transfer retry for failed or stuck payout operations."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.retry_payout_transfer(
        payout_id=payout_id,
        body=body,
        admin_id=admin_id,
        token=str(current_user["token"]),
    )


@router.get(
    "/finance/dashboard/counters",
    response_model=FinancialDashboardCountersResponse,
)
async def get_financial_dashboard_counters(
    _current_user: dict = Depends(require_scope("finance.dashboard.read")),
    svc: AdminService = Depends(get_service),
):
    """Return payout operations counters for finance command-center widgets."""
    return await svc.get_financial_dashboard_counters()


@router.get(
    "/finance/reconciliation/summary",
    response_model=FinancialReconciliationSummaryResponse,
)
async def get_financial_reconciliation_summary(
    _current_user: dict = Depends(require_scope("finance.reconciliation.read")),
    svc: AdminService = Depends(get_service),
):
    """Return financial reconciliation aggregates across payout operations."""
    return await svc.get_financial_reconciliation_summary()


@router.get("/analytics/growth", response_model=AnalyticsGrowthResponse)
async def get_analytics_growth(
    window_days: int = Query(30, ge=1, le=365),
    _current_user: dict = Depends(require_scope("analytics.growth.read")),
    svc: AdminService = Depends(get_service),
):
    """Return growth-oriented KPI time-series for disputes, payouts, and payout volume."""
    return await svc.get_analytics_growth(window_days=window_days)


@router.get(
    "/analytics/disputes-throughput",
    response_model=AnalyticsDisputeThroughputResponse,
)
async def get_analytics_dispute_throughput(
    window_days: int = Query(30, ge=1, le=365),
    _current_user: dict = Depends(require_scope("analytics.disputes.read")),
    svc: AdminService = Depends(get_service),
):
    """Return dispute throughput KPIs including opened/resolved series and resolution speed."""
    return await svc.get_analytics_dispute_throughput(window_days=window_days)


@router.get("/analytics/payout-health", response_model=AnalyticsPayoutHealthResponse)
async def get_analytics_payout_health(
    window_days: int = Query(30, ge=1, le=365),
    _current_user: dict = Depends(require_scope("analytics.payouts.read")),
    svc: AdminService = Depends(get_service),
):
    """Return payout health KPIs including status mix, retry pressure, and success rate."""
    return await svc.get_analytics_payout_health(window_days=window_days)


@router.get("/analytics/volume", response_model=AnalyticsVolumeResponse)
async def get_analytics_volume(
    window_days: int = Query(30, ge=1, le=365),
    _current_user: dict = Depends(require_scope("analytics.volume.read")),
    svc: AdminService = Depends(get_service),
):
    """Return payout volume analytics with totals and day-level time series."""
    return await svc.get_analytics_volume(window_days=window_days)


@router.post("/saved-views", response_model=SavedViewResponse)
async def create_saved_view(
    body: SavedViewCreateRequest,
    current_user: dict = Depends(require_scope("saved_views.write")),
    svc: AdminService = Depends(get_service),
):
    """Create a saved dashboard/filter view for operations personas."""
    return await svc.create_saved_view(
        owner_id=uuid.UUID(current_user["user_id"]),
        body=body,
    )


@router.get("/saved-views", response_model=SavedViewListResponse)
async def list_saved_views(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    module: str | None = Query(None),
    current_user: dict = Depends(require_scope("saved_views.read")),
    svc: AdminService = Depends(get_service),
):
    """List saved dashboard/filter views available to the caller."""
    return await svc.list_saved_views(
        owner_id=uuid.UUID(current_user["user_id"]),
        page=page,
        limit=limit,
        module=module,
    )


@router.get("/saved-views/{view_id}", response_model=SavedViewResponse)
async def get_saved_view(
    view_id: uuid.UUID,
    current_user: dict = Depends(require_scope("saved_views.read")),
    svc: AdminService = Depends(get_service),
):
    """Get one saved dashboard/filter view by id."""
    return await svc.get_saved_view(
        view_id=view_id,
        owner_id=uuid.UUID(current_user["user_id"]),
    )


@router.patch("/saved-views/{view_id}", response_model=SavedViewResponse)
async def update_saved_view(
    view_id: uuid.UUID,
    body: SavedViewUpdateRequest,
    current_user: dict = Depends(require_scope("saved_views.write")),
    svc: AdminService = Depends(get_service),
):
    """Update saved dashboard/filter view metadata and filters."""
    return await svc.update_saved_view(
        view_id=view_id,
        owner_id=uuid.UUID(current_user["user_id"]),
        body=body,
    )


@router.post("/reports/jobs", response_model=ReportJobResponse)
async def create_report_job(
    body: ReportJobCreateRequest,
    current_user: dict = Depends(require_scope("reports.write")),
    svc: AdminService = Depends(get_service),
):
    """Queue an async report export job (CSV/JSON) for analytics/reporting."""
    return await svc.create_report_job(
        requested_by=uuid.UUID(current_user["user_id"]),
        body=body,
    )


@router.get("/reports/jobs", response_model=ReportJobListResponse)
async def list_report_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    report_type: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    current_user: dict = Depends(require_scope("reports.read")),
    svc: AdminService = Depends(get_service),
):
    """List report jobs created by the caller."""
    return await svc.list_report_jobs(
        requested_by=uuid.UUID(current_user["user_id"]),
        page=page,
        limit=limit,
        report_type=report_type,
        status_filter=status_filter,
    )


@router.get("/reports/jobs/{job_id}", response_model=ReportJobResponse)
async def get_report_job(
    job_id: uuid.UUID,
    current_user: dict = Depends(require_scope("reports.read")),
    svc: AdminService = Depends(get_service),
):
    """Get one report job by id."""
    return await svc.get_report_job(
        job_id=job_id,
        requested_by=uuid.UUID(current_user["user_id"]),
    )


@router.post("/reports/jobs/{job_id}/run", response_model=ReportJobResponse)
async def run_report_job(
    job_id: uuid.UUID,
    current_user: dict = Depends(require_scope("reports.write")),
    svc: AdminService = Depends(get_service),
):
    """Execute a queued report job and mark it as completed/failed."""
    return await svc.run_report_job(
        job_id=job_id,
        requested_by=uuid.UUID(current_user["user_id"]),
    )


@router.get("/reports/jobs/{job_id}/download")
async def download_report_job(
    job_id: uuid.UUID,
    current_user: dict = Depends(require_scope("reports.read")),
    svc: AdminService = Depends(get_service),
):
    """Download completed report content in its requested export format."""
    content, media_type, filename = await svc.get_report_job_export(
        job_id=job_id,
        requested_by=uuid.UUID(current_user["user_id"]),
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/configs", response_model=SystemConfigListResponse)
async def list_system_configs(
    _current_user: dict = Depends(require_scope("config.read")),
    svc: AdminService = Depends(get_service),
):
    """List current system policy/config key-values and versions."""
    return await svc.list_system_configs()


@router.get("/configs/{config_key}", response_model=SystemConfigItem)
async def get_system_config(
    config_key: str,
    _current_user: dict = Depends(require_scope("config.read")),
    svc: AdminService = Depends(get_service),
):
    """Get one system config value by key."""
    return await svc.get_system_config(config_key=config_key)


@router.post("/configs/validate", response_model=SystemConfigDryRunResponse)
async def validate_system_config_change(
    body: SystemConfigDryRunRequest,
    _current_user: dict = Depends(require_scope("config.validate")),
    svc: AdminService = Depends(get_service),
):
    """Dry-run validation for a system config mutation without persistence."""
    return await svc.validate_system_config_change(
        config_key=body.key,
        value=body.value,
    )


@router.put("/configs/{config_key}", response_model=SystemConfigMutationResponse)
async def upsert_system_config(
    config_key: str,
    body: SystemConfigUpsertRequest,
    current_user: dict = Depends(require_scope("config.write")),
    svc: AdminService = Depends(get_service),
):
    """Create or update a system config with versioned history and auditing."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.upsert_system_config(
        config_key=config_key,
        body=body,
        admin_id=admin_id,
    )


@router.post(
    "/configs/{config_key}/rollback", response_model=SystemConfigMutationResponse
)
async def rollback_system_config(
    config_key: str,
    body: SystemConfigRollbackRequest,
    current_user: dict = Depends(require_scope("config.rollback")),
    svc: AdminService = Depends(get_service),
):
    """Rollback a system config by promoting a previous version into a new version."""
    admin_id = uuid.UUID(current_user["user_id"])
    return await svc.rollback_system_config(
        config_key=config_key,
        body=body,
        admin_id=admin_id,
    )


@router.get("/configs/{config_key}/history", response_model=SystemConfigHistoryResponse)
async def list_system_config_history(
    config_key: str,
    limit: int = Query(100, ge=1, le=500),
    _current_user: dict = Depends(require_scope("config.history.read")),
    svc: AdminService = Depends(get_service),
):
    """Return versioned change history for a system config key."""
    return await svc.list_system_config_history(config_key=config_key, limit=limit)


@router.get("/stats", response_model=PlatformStats)
async def get_stats(
    _current_user: dict = Depends(require_scope("stats.read")),
    svc: AdminService = Depends(get_service),
):
    """Aggregate platform statistics."""
    return await svc.get_stats()


@router.get("/actions", response_model=AdminActionLogListResponse)
async def list_admin_actions(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    action: str | None = Query(None),
    target_type: str | None = Query(None),
    _current_user: dict = Depends(require_scope("actions.read")),
    svc: AdminService = Depends(get_service),
):
    """List admin actions with pagination and optional filters (admin only)."""
    return await svc.get_action_logs(
        page=page,
        limit=limit,
        action=action,
        target_type=target_type,
    )
