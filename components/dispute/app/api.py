"""FastAPI route handlers for the Dispute service."""

from __future__ import annotations

import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app import grpc_clients
from app.db import get_db
from app.models import (
    DisputeCreate,
    DisputeExecutionRequest,
    DisputeResolve,
    DisputeResponse,
    DisputeReviewRequest,
    DisputeSummaryResponse,
    EvidenceResponse,
    PaginatedDisputeResponse,
)
from app.repository import DisputeRepository
from app.service import DisputeService

dispute_escrow_router = APIRouter(prefix="/dispute", tags=["dispute"])

KYC_MIN_LEVEL = int(os.getenv("KYC_MIN_LEVEL", "1"))
DISPUTE_INTERNAL_TOKEN = os.getenv("DISPUTE_INTERNAL_TOKEN", "").strip()

security = HTTPBearer()


# async def _enforce_kyc_or_raise(user_id: str) -> int:
#     try:
#         profile = await grpc_clients.get_user_by_id(user_id)
#     except RuntimeError as exc:
#         raise HTTPException(503, "Unable to verify KYC status") from exc

#     kyc_level = int(profile.get("kyc_level", 0))
#     if kyc_level < KYC_MIN_LEVEL:
#         raise HTTPException(
#             403,
#             "KYC verification is required before accessing this resource. Please complete KYC first.",
#         )
#     return kyc_level


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

    # kyc_level = await _enforce_kyc_or_raise(user["user_id"])
    # user["kyc_level"] = kyc_level
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
    )


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
    user_id = uuid.UUID(current_user["user_id"])
    # TODO: we should make sure the file is uploaded to out storage
    evidence = await svc.add_evidence(
        dispute_id,
        user_id,
        file_url,
        file_type,
        description,
        current_user.get("role", "user"),
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
    admin_id = uuid.UUID(current_user["user_id"])
    dispute = await svc.resolve_dispute(
        dispute_id, admin_id, current_user.get("role", "user"), body
    )
    return DisputeResponse.model_validate(dispute)


# should be done from admin side not here sho we should remove it or
# if the user who initiated the dispute is canceling the dispute
# we should handle it another way


# findout what the goal is here
@dispute_escrow_router.post("/{dispute_id}/execute-resolution", response_model=DisputeResponse)
async def execute_resolution(
    dispute_id: uuid.UUID,
    body: DisputeExecutionRequest,
    svc: DisputeService = Depends(get_service),
    internal_token: Annotated[
        str | None,
        Header(alias="X-Internal-Token"),
    ] = None,
):
    if DISPUTE_INTERNAL_TOKEN and internal_token != DISPUTE_INTERNAL_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal token",
        )

    dispute = await svc.execute_resolution(
        dispute_id,
        body.resolution,
        body.admin_id,
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
