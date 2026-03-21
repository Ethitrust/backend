"""FastAPI route handlers for the KYC service."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import grpc_clients
from app.models import (
    DriversLicenseRequest,
    FaydaActionResponse,
    FaydaSendOTPRequest,
    FaydaVerifyOTPRequest,
    KYCLookupResponse,
    KYCPhotoURLResponse,
    TINRequest,
)
from app.service import KYCService

router = APIRouter(prefix="/kyc", tags=["kyc"])

security = HTTPBearer(auto_error=False)

logger = logging.getLogger("kyc.api")


async def get_current_user(
    authorization: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> dict:
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    try:
        return await grpc_clients.validate_token(authorization.credentials)
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc


def get_service() -> KYCService:
    return KYCService()


# Q: maybe implemnet this later or deicard
@router.post("/drivers-license", response_model=KYCLookupResponse)
async def lookup_drivers_license(
    body: DriversLicenseRequest,
    current_user: dict = Depends(get_current_user),
    svc: KYCService = Depends(get_service),
):
    """Verify a driver's license via verifayda."""

    raise NotImplementedError()
    result = await svc.lookup_drivers_license(
        current_user["user_id"], body.license_number
    )
    return KYCLookupResponse(**result)


@router.post("/tin", response_model=KYCLookupResponse)
async def lookup_tin(
    body: TINRequest,
    current_user: dict = Depends(get_current_user),
    svc: KYCService = Depends(get_service),
):
    """Verify a Tax Identification Number via etrade api implement service later."""
    # TODO: implment tin verification using etrade api
    result = await svc.lookup_tin(current_user["user_id"], body.tin)
    return KYCLookupResponse(**result)


@router.post("/fayda/send-otp", response_model=FaydaActionResponse)
async def fayda_send_otp(
    body: FaydaSendOTPRequest,
    current_user: dict = Depends(get_current_user),
    svc: KYCService = Depends(get_service),
):
    """Send OTP to a Fayda FAN/FIN identifier."""
    if await svc.is_user_already_verified(current_user["user_id"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You have already completed Fayda KYC verification.",
        )
    result = await svc.send_fayda_otp(body.fan_or_fin)
    return FaydaActionResponse(**result)


@router.post("/fayda/verify-otp", response_model=FaydaActionResponse)
async def fayda_verify_otp(
    body: FaydaVerifyOTPRequest,
    current_user: dict = Depends(get_current_user),
    svc: KYCService = Depends(get_service),
):
    """Verify OTP for Fayda FAN/FIN; upgrades user KYC level on success."""
    if await svc.is_user_already_verified(current_user["user_id"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You have already completed Fayda KYC verification.",
        )
    result = await svc.verify_fayda_otp(
        user_id=current_user["user_id"],
        transaction_id=body.transaction_id,
        otp=body.otp,
        fan_or_fin=body.fan_or_fin,
    )
    if result.get("status") != "success":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=result.get("message", "Fayda OTP verification failed"),
        )
    return FaydaActionResponse(**result)


@router.get("/me/photo-url", response_model=KYCPhotoURLResponse)
async def get_my_kyc_photo_url(
    current_user: dict = Depends(get_current_user),
    svc: KYCService = Depends(get_service),
):
    result = await svc.get_my_photo_signed_url(
        user_id=current_user["user_id"],
        role=current_user.get("role", "user"),
    )
    if result.get("status") != "success":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.get("message", "KYC photo not found"),
        )
    return KYCPhotoURLResponse(**result)


# @router.post("/fayda/refresh-token", response_model=FaydaActionResponse)
# async def fayda_refresh_token(
#     body: FaydaRefreshTokenRequest,
#     _current_user: dict = Depends(get_current_user),
#     svc: KYCService = Depends(get_service),
# ):
#     """Refresh Fayda token with a refresh token from prior verification."""
#     result = await svc.refresh_fayda_token(body.refresh_token)
#     return FaydaActionResponse(**result)
