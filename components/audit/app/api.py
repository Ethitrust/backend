"""FastAPI route handlers for the Audit service."""

from __future__ import annotations

import os
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app import grpc_clients
from app.db import get_db
from app.models import AuditLogCreate, AuditLogResponse
from app.repository import AuditRepository
from app.service import AuditService

router = APIRouter(prefix="/audit", tags=["audit"])

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


def get_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(AuditRepository(db))


@router.post(
    "/log", status_code=status.HTTP_201_CREATED, response_model=AuditLogResponse
)
async def create_log(
    body: AuditLogCreate,
    svc: AuditService = Depends(get_service),
):
    """Record an audit log entry (called by other services internally)."""
    log = await svc.log(body)
    return AuditLogResponse.model_validate(log)


@router.get("/logs", response_model=dict)
async def query_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    actor_id: Optional[uuid.UUID] = Query(None),
    resource: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Query audit logs (admin only)."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required"
        )
    svc_inst = AuditService(AuditRepository(None))  # handled by DI below
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Use service directly"
    )


@router.get("/logs/query", response_model=dict)
async def query_logs_v2(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    actor_id: Optional[uuid.UUID] = Query(None),
    resource: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    svc: AuditService = Depends(get_service),
):
    """Query audit logs with filters (admin only)."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required"
        )
    result = await svc.query_logs(page, limit, actor_id, resource, action)
    return {
        "items": [
            AuditLogResponse.model_validate(l).model_dump() for l in result["items"]
        ],
        "total": result["total"],
        "page": result["page"],
        "limit": result["limit"],
    }
