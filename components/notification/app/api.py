"""FastAPI route handlers for the Notification service."""

from __future__ import annotations

import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app import grpc_clients
from app.db import get_db
from app.models import NotificationCreate, NotificationResponse
from app.repository import NotificationRepository
from app.service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])

KYC_MIN_LEVEL = int(os.getenv("KYC_MIN_LEVEL", "1"))

security = HTTPBearer(auto_error=False)


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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    # kyc_level = await _enforce_kyc_or_raise(user["user_id"])
    # user["kyc_level"] = kyc_level
    return user


def get_service(db: AsyncSession = Depends(get_db)) -> NotificationService:
    return NotificationService(NotificationRepository(db))


@router.get("", response_model=list[NotificationResponse])
async def list_notifications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    svc: NotificationService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    notifs = await svc.list_notifications(user_id, page, limit)
    return [NotificationResponse.model_validate(n) for n in notifs]


@router.patch("/{notif_id}/read", response_model=NotificationResponse)
async def mark_read(
    notif_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: NotificationService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    notif = await svc.mark_read(notif_id, user_id)
    if notif is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found"
        )
    return NotificationResponse.model_validate(notif)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    current_user: dict = Depends(get_current_user),
    svc: NotificationService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    await svc.mark_all_read(user_id)
