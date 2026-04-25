"""FastAPI route handlers for the Dispute service."""

from __future__ import annotations

import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app import grpc_clients
from app.db import get_db
from app.models import (
    ConfirmEvidenceUpload,
    DisputeCreate,
    DisputeMessageCreate,
    DisputeMessageResponse,
    DisputeResolve,
    DisputeResponse,
    DisputeReviewRequest,
    DisputeSummaryResponse,
    EvidenceResponse,
    PaginatedDisputeResponse,
    PresignedUploadResponse,
    RequestEvidenceUpload,
    SettlementAction,
)
from app.repository import DisputeRepository
from app.service import DisputeService

dispute_escrow_router = APIRouter(prefix="/dispute", tags=["dispute"])

KYC_MIN_LEVEL = int(os.getenv("KYC_MIN_LEVEL", "1"))

security = HTTPBearer()


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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return user


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> DisputeService:
    return DisputeService(DisputeRepository(db))


@dispute_escrow_router.post(
    "/{escrow_id}/dispute",
    status_code=status.HTTP_201_CREATED,
    response_model=DisputeResponse,
)
async def raise_dispute(
    escrow_id: uuid.UUID,
    body: DisputeCreate,
    current_user: dict = Depends(get_current_user),
    svc: DisputeService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    dispute = await svc.raise_dispute(
        escrow_id,
        user_id,
        body,
        current_user.get("role", "user"),
    )
    return DisputeResponse.model_validate(dispute)


@dispute_escrow_router.get("/{escrow_id}/dispute", response_model=DisputeResponse)
async def get_dispute(
    escrow_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: DisputeService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    result = await svc.get_dispute(
        escrow_id,
        user_id,
        current_user.get("role", "user"),
    )
    d = result["dispute"]
    return DisputeResponse(
        **{c.key: getattr(d, c.key) for c in d.__table__.columns},
        evidence=[EvidenceResponse.model_validate(e) for e in result["evidence"]],
        messages=[DisputeMessageResponse.model_validate(m) for m in result["messages"]],
    )


@dispute_escrow_router.post(
    "/{dispute_id}/messages",
    response_model=DisputeMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_dispute_message(
    dispute_id: uuid.UUID,
    body: DisputeMessageCreate,
    current_user: dict = Depends(get_current_user),
    svc: DisputeService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    message = await svc.add_message(
        dispute_id=dispute_id,
        user_id=user_id,
        message_text=body.message,
        actor_role=current_user.get("role", "user"),
    )
    return DisputeMessageResponse.model_validate(message)


@dispute_escrow_router.post(
    "/{dispute_id}/evidence/presign-upload",
    response_model=PresignedUploadResponse,
)
async def request_evidence_upload_url(
    dispute_id: uuid.UUID,
    body: RequestEvidenceUpload,
    current_user: dict = Depends(get_current_user),
    svc: DisputeService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    await svc.get_dispute_for_actor(
        dispute_id,
        user_id,
        current_user.get("role", "user"),
    )

    try:
        upload = await grpc_clients.generate_storage_upload_url(
            actor_user_id=current_user["user_id"],
            role=current_user.get("role", "user"),
            purpose="dispute",
            object_key=body.object_key,
            content_type=body.content_type,
            expires_in_seconds=body.expires_in_seconds,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to generate storage upload URL",
        ) from exc

    return PresignedUploadResponse(**upload)


@dispute_escrow_router.post(
    "/{escrow_id}/dispute/{dispute_id}/evidence/confirm",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def confirm_evidence_upload(
    escrow_id: uuid.UUID,
    dispute_id: uuid.UUID,
    body: ConfirmEvidenceUpload,
    current_user: dict = Depends(get_current_user),
    svc: DisputeService = Depends(get_service),
):
    _ = escrow_id
    user_id = uuid.UUID(current_user["user_id"])
    evidence = await svc.add_evidence(
        dispute_id=dispute_id,
        user_id=user_id,
        file_url=f"s3://{body.object_key}",
        file_type=body.file_type,
        description=body.description,
        object_key=body.object_key,
        message_id=body.message_id,
        actor_role=current_user.get("role", "user"),
    )
    return EvidenceResponse.model_validate(evidence)


@dispute_escrow_router.post(
    "/{escrow_id}/dispute/{dispute_id}/evidence",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_evidence(
    escrow_id: uuid.UUID,
    dispute_id: uuid.UUID,
    file_url: str = Body(...),
    file_type: str = Body(...),
    description: str = Body(""),
    current_user: dict = Depends(get_current_user),
    svc: DisputeService = Depends(get_service),
):
    _ = escrow_id
    user_id = uuid.UUID(current_user["user_id"])
    evidence = await svc.add_evidence(
        dispute_id,
        user_id,
        file_url,
        file_type,
        description,
        object_key=None,
        message_id=None,
        actor_role=current_user.get("role", "user"),
    )
    return EvidenceResponse.model_validate(evidence)


@dispute_escrow_router.post(
    "/{escrow_id}/dispute/{dispute_id}/resolve",
    response_model=DisputeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resolve_dispute(
    escrow_id: uuid.UUID,
    dispute_id: uuid.UUID,
    body: DisputeResolve,
    current_user: dict = Depends(get_current_user),
    svc: DisputeService = Depends(get_service),
):
    _ = escrow_id
    admin_id = uuid.UUID(current_user["user_id"])
    dispute = await svc.resolve_dispute(
        dispute_id, admin_id, current_user.get("role", "user"), body
    )
    return DisputeResponse.model_validate(dispute)


@dispute_escrow_router.post("/{dispute_id}/settlement/request", response_model=DisputeResponse)
async def request_settlement(
    dispute_id: uuid.UUID,
    body: SettlementAction,
    current_user: dict = Depends(get_current_user),
    svc: DisputeService = Depends(get_service),
):
    requester_id = uuid.UUID(current_user["user_id"])
    await svc.add_message(
        dispute_id=dispute_id,
        user_id=requester_id,
        message_text=f"Settlement requested: {body.note}",
        actor_role=current_user.get("role", "user"),
        is_system=True,
    )
    dispute = await svc.request_settlement(
        dispute_id=dispute_id,
        requester_id=requester_id,
        actor_role=current_user.get("role", "user"),
    )
    return DisputeResponse.model_validate(dispute)


@dispute_escrow_router.post("/{dispute_id}/settlement/confirm", response_model=DisputeResponse)
async def confirm_settlement(
    dispute_id: uuid.UUID,
    body: SettlementAction,
    current_user: dict = Depends(get_current_user),
    svc: DisputeService = Depends(get_service),
):
    confirmer_id = uuid.UUID(current_user["user_id"])
    dispute = await svc.confirm_settlement(
        dispute_id=dispute_id,
        confirmer_id=confirmer_id,
        actor_role=current_user.get("role", "user"),
    )
    await svc.add_message(
        dispute_id=dispute_id,
        user_id=confirmer_id,
        message_text=f"Settlement confirmed: {body.note}",
        actor_role=current_user.get("role", "user"),
        is_system=True,
    )
    return DisputeResponse.model_validate(dispute)


@dispute_escrow_router.post("/{dispute_id}/escalate", response_model=DisputeResponse)
async def escalate_dispute(
    dispute_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: DisputeService = Depends(get_service),
):
    actor_id = uuid.UUID(current_user["user_id"])
    dispute = await svc.escalate_dispute(
        dispute_id=dispute_id,
        actor_id=actor_id,
        actor_role=current_user.get("role", "user"),
    )
    return DisputeResponse.model_validate(dispute)


@dispute_escrow_router.get("", response_model=PaginatedDisputeResponse)
async def list_disputes(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    current_user: dict = Depends(get_current_user),
    svc: DisputeService = Depends(get_service),
):
    result = await svc.list_disputes(
        current_user.get("role", "user"),
        status_filter,
        page,
        limit,
    )
    return PaginatedDisputeResponse(
        items=[DisputeSummaryResponse.model_validate(item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"],
    )


@dispute_escrow_router.get("/me", response_model=PaginatedDisputeResponse)
async def list_my_disputes(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    current_user: dict = Depends(get_current_user),
    svc: DisputeService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    result = await svc.list_my_disputes(
        user_id=user_id,
        status_filter=status_filter,
        page=page,
        limit=limit,
    )
    return PaginatedDisputeResponse(
        items=[DisputeSummaryResponse.model_validate(item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"],
    )


@dispute_escrow_router.post("/{dispute_id}/review", response_model=DisputeResponse)
async def move_dispute_to_review(
    dispute_id: uuid.UUID,
    body: DisputeReviewRequest,
    current_user: dict = Depends(get_current_user),
    svc: DisputeService = Depends(get_service),
):
    reviewer_id = uuid.UUID(current_user["user_id"])
    dispute = await svc.mark_under_review(
        dispute_id,
        reviewer_id,
        current_user.get("role", "user"),
        body.note,
    )
    return DisputeResponse.model_validate(dispute)


@dispute_escrow_router.post("/{dispute_id}/cancel", response_model=DisputeResponse)
async def cancel_dispute(
    dispute_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: DisputeService = Depends(get_service),
):
    requester_id = uuid.UUID(current_user["user_id"])
    dispute = await svc.cancel_dispute(dispute_id, requester_id)
    return DisputeResponse.model_validate(dispute)
