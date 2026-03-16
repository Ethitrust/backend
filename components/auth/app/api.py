"""Route handlers for the Auth service."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import (
    ForgotPasswordRequest,
    LoginRequest,
    OTPVerifyRequest,
    ResetPasswordRequest,
    SessionOut,
    SignupRequest,
    SignupResponse,
    TokenResponse,
    UserOut,
    UserResponse,
)
from app.repository import AuthRepository
from app.security import decode_token, get_current_token_payload, get_current_user_id
from app.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(
    auto_error=False
)  # For automatic OpenAPI documentation of the Authorization header


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
        user = decode_token(authorization.credentials)
        return user
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


async def get_current_token(
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
    return authorization.credentials


def get_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(AuthRepository(db))


@router.post(
    "/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED
)
async def signup(
    body: SignupRequest,
    service: AuthService = Depends(get_service),
) -> SignupResponse:
    user, token = await service.signup_and_login(body)
    return SignupResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            role=user.role,
            is_verified=user.is_verified,
            is_banned=user.is_banned,
            created_at=user.created_at,
        ),
        token=TokenResponse(access_token=token),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    service: AuthService = Depends(get_service),
) -> TokenResponse:
    token = await service.login(body)
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    authorization: Annotated[str, Depends(get_current_token)],
    service: AuthService = Depends(get_service),
) -> dict:
    await service.logout(authorization)
    return {"detail": "Logged out successfully"}


@router.get(
    "/sessions", response_model=list[SessionOut], status_code=status.HTTP_200_OK
)
async def list_sessions(
    authorization: Annotated[str, Depends(get_current_token)],
    current_user_id: str = Depends(get_current_user_id),
    service: AuthService = Depends(get_service),
) -> list[SessionOut]:
    payload = await get_current_token_payload(f"Bearer {authorization}")
    current_jti = payload.get("jti") if isinstance(payload.get("jti"), str) else None
    sessions = await service.list_sessions(current_user_id, current_jti=current_jti)
    return [SessionOut(**session) for session in sessions]


@router.post("/sessions/{jti}/revoke", status_code=status.HTTP_200_OK)
async def revoke_session(
    jti: str,
    current_user_id: str = Depends(get_current_user_id),
    service: AuthService = Depends(get_service),
) -> dict:
    await service.revoke_session_by_jti(user_id=current_user_id, jti=jti)
    return {"detail": "Session revoked successfully"}


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(
    body: OTPVerifyRequest,
    service: AuthService = Depends(get_service),
) -> dict:
    await service.verify_email(email=str(body.email), otp=body.otp)
    return {"detail": "Email verified successfully"}


@router.post("/resend-otp", status_code=status.HTTP_200_OK)
async def resend_otp(
    body: ForgotPasswordRequest,
    service: AuthService = Depends(get_service),
) -> dict:
    await service.resend_otp(email=str(body.email))
    return {"detail": "OTP resent"}


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(
    body: ForgotPasswordRequest,
    service: AuthService = Depends(get_service),
) -> dict:
    await service.forgot_password(email=str(body.email))
    return {"detail": "If that email exists, a reset link has been sent"}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    body: ResetPasswordRequest,
    service: AuthService = Depends(get_service),
) -> dict:
    await service.reset_password(token=body.token, new_password=body.new_password)
    return {"detail": "Password updated successfully"}


@router.get("/me", response_model=UserOut)
async def get_me(
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    import uuid as _uuid

    repo = AuthRepository(db)
    user = await repo.get_by_id(_uuid.UUID(current_user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return UserOut.model_validate(user)
