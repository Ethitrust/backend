"""FastAPI route handlers for the Payout service."""

from __future__ import annotations

import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app import grpc_clients
from app.db import get_db
from app.models import PaginatedPayoutResponse, PayoutRequest, PayoutResponse
from app.repository import PayoutRepository
from app.service import PayoutService

router = APIRouter(prefix="/payout", tags=["payout"])

KYC_MIN_LEVEL = int(os.getenv("KYC_MIN_LEVEL", "1"))

security = HTTPBearer(auto_error=False)


async def _enforce_kyc_or_raise(user_id: str) -> int:
    try:
        profile = await grpc_clients.get_user_by_id(user_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify KYC status",
        ) from exc

    kyc_level = int(profile.get("kyc_level", 0))
    if kyc_level < KYC_MIN_LEVEL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "KYC verification is required before accessing this resource. "
                "Please complete KYC first."
            ),
        )
    return kyc_level


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

    kyc_level = await _enforce_kyc_or_raise(user["user_id"])
    user["kyc_level"] = kyc_level
    return user


def get_service(db: AsyncSession = Depends(get_db)) -> PayoutService:
    return PayoutService(PayoutRepository(db))


@router.post(
    "/request", status_code=status.HTTP_201_CREATED, response_model=PayoutResponse
)
async def request_payout(
    body: PayoutRequest,
    current_user: dict = Depends(get_current_user),
    svc: PayoutService = Depends(get_service),
):
    """Request a payout to a bank account."""
    user_id = uuid.UUID(current_user["user_id"])
    payout = await svc.request_payout(user_id, body)
    return PayoutResponse.model_validate(payout)


# this might be using a manual trigger to get payout :INVESTIGATE:
@router.post("/bank-transfer/et/{payout_id}", response_model=PayoutResponse)
async def process_bank_transfer(
    payout_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: PayoutService = Depends(get_service),
):
    """Trigger ETB bank transfer (Chapa). Normally called by a worker."""
    payout = await svc.process_bank_transfer(payout_id)
    return PayoutResponse.model_validate(payout)


@router.get("/{payout_id}", response_model=PayoutResponse)
async def get_payout(
    payout_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: PayoutService = Depends(get_service),
):
    """Get the status of a specific payout."""
    user_id = uuid.UUID(current_user["user_id"])
    payout = await svc.get_payout_status(user_id, payout_id)
    return PayoutResponse.model_validate(payout)


@router.get("", response_model=PaginatedPayoutResponse)
async def list_payouts(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    svc: PayoutService = Depends(get_service),
):
    """List payouts for the authenticated user."""
    user_id = uuid.UUID(current_user["user_id"])
    result = await svc.list_payouts(user_id, page, limit)
    return PaginatedPayoutResponse(
        items=[PayoutResponse.model_validate(p) for p in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
    )
