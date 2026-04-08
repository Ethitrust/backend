"""
Business logic for the Auth service.

Responsibilities:
- signup: create user, generate OTP, sync user profile to User service via gRPC
- login: verify credentials, return JWT
- verify_email: validate OTP, mark user verified
- resend_otp: replace OTP in Redis, publish user.otp_resent
- forgot_password: create short-lived reset token, publish notification event
- reset_password: validate reset token, update password hash
"""

from __future__ import annotations

import logging
import secrets
import string
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from jose import JWTError

from app.db import User
from app.grpc_clients import (
    associate_escrow_with_user,
    sync_user,
    update_email_verifiication_status,
)
from app.messaging import publish
from app.models import LoginRequest, SignupRequest
from app.redis_client import blacklist_token, delete_otp, get_otp, set_otp
from app.repository import AuthRepository
from app.security import (
    create_access_token,
    create_reset_token,
    decode_token,
    hash_password,
    verify_password,
)

logger = logging.getLogger(__name__)


def _generate_otp(length: int = 6) -> str:
    return "".join([secrets.choice(string.digits) for _ in range(length)])


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class AuthService:
    def __init__(self, repo: AuthRepository) -> None:
        self.repo = repo

    async def signup_and_login(self, data: SignupRequest) -> tuple[User, str]:
        user = await self.signup(data)
        if user and data.escrow_id:
            # associate the new user with the escrow if an escrow_id was provided in the signup request
            await associate_escrow_with_user(
                escrow_id=str(data.escrow_id),
                user_id=str(user.id),
            )
        token = await self.login(
            LoginRequest(
                email=data.email,
                password=data.password,
            )
        )
        return user, token

    async def signup(self, data: SignupRequest) -> User:
        existing = await self.repo.get_by_email(data.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists",
            )
        hashed = hash_password(data.password)
        user = await self.repo.create_user(
            email=data.email,
            password_hash=hashed,
            first_name=data.first_name,
            last_name=data.last_name,
        )
        otp = _generate_otp()
        logger.info(
            "signup.generated_otp user_id=%s email=%s otp_length=%s",
            user.id,
            user.email,
            len(otp),
        )
        try:
            await sync_user(
                user_id=str(user.id),
                email=user.email,
                password_hash=user.password_hash,
                first_name=user.first_name,
                last_name=user.last_name,
                role=user.role,
                is_verified=user.is_verified,
                is_banned=user.is_banned,
                kyc_level=0,
                otp=otp,
            )
        except RuntimeError as exc:
            await self.repo.delete_user(user.id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not synchronize user profile",
            ) from exc

        await set_otp(data.email, otp)
        logger.info(
            "signup.otp_stored email=%s event=user.otp_resent",
            data.email,
        )
        await publish(
            routing_key="user.otp_resent",
            payload={"user_id": str(user.id), "email": user.email, "otp": otp},
        )
        logger.info(
            "signup.otp_event_published user_id=%s email=%s event=user.otp_resent",
            user.id,
            user.email,
        )
        return user

    async def login(self, data: LoginRequest) -> str:
        user = await self.repo.get_by_email(data.email)
        # Q: prvent time based attach for future
        if not user or not verify_password(data.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        if user.is_banned:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is banned",
            )
        token = create_access_token(sub=str(user.id), role=user.role)
        payload = decode_token(token)
        jti = payload.get("jti")
        iat = payload.get("iat")
        exp = payload.get("exp")
        # FUTURE: refactor in future maybe simplify - works for now don't touch it
        if (
            not isinstance(jti, str)
            or not jti
            or not isinstance(iat, (int, float))
            or not isinstance(exp, (int, float))
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Token payload missing required claims",
            )

        await self.repo.create_session(
            user_id=user.id,
            jti=jti,
            role=user.role,
            issued_at=datetime.fromtimestamp(iat, tz=timezone.utc),
            expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
        )
        return token

    async def logout(self, token: str) -> None:
        try:
            payload = decode_token(token)
        except JWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            ) from exc

        sub = payload.get("sub")
        jti = payload.get("jti")
        exp = payload.get("exp")
        if (
            not isinstance(sub, str)
            or not isinstance(jti, str)
            or not isinstance(exp, (int, float))
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )

        try:
            user_id = uuid.UUID(sub)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token subject",
            ) from exc

        now = datetime.now(tz=timezone.utc)
        ttl = max(1, int(exp - now.timestamp()))
        await self.repo.revoke_session(user_id, jti, now)
        await blacklist_token(jti, ttl=ttl)

    async def list_sessions(
        self, user_id: str, current_jti: str | None = None
    ) -> list[dict]:
        sessions = await self.repo.list_sessions(uuid.UUID(user_id))
        return [
            {
                "jti": session.jti,
                "role": session.role,
                "issued_at": session.issued_at,
                "expires_at": session.expires_at,
                "revoked_at": session.revoked_at,
                "is_current": bool(current_jti and session.jti == current_jti),
            }
            for session in sessions
        ]

    async def revoke_session_by_jti(self, *, user_id: str, jti: str) -> None:
        session = await self.repo.get_session_by_jti(jti)
        if session is None or str(session.user_id) != user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

        now = datetime.now(tz=timezone.utc)
        if session.revoked_at is not None:
            return

        expires_at = _as_utc(session.expires_at)
        ttl = max(1, int((expires_at - now).total_seconds()))
        await self.repo.revoke_session(session.user_id, jti, now)
        await blacklist_token(jti, ttl=ttl)

    async def verify_email(self, email: str, otp: str) -> None:
        stored_otp = await get_otp(email)
        if not stored_otp or stored_otp != otp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired OTP",
            )
        user = await self.repo.get_by_email(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        await self.repo.set_verified(user.id)
        # sync the auth to user Note: kyc should not be performed before emial verification
        try:
            await update_email_verifiication_status(
                user_id=str(user.id),
                is_verified=True,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not synchronize user profile",
            ) from exc
        await delete_otp(email)

    async def resend_otp(self, email: str) -> None:
        user = await self.repo.get_by_email(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        otp = _generate_otp()
        await set_otp(email, otp)
        logger.info("resend_otp.otp_stored email=%s", email)
        await publish(
            routing_key="user.otp_resent",
            payload={"user_id": str(user.id), "email": email, "otp": otp},
        )
        logger.info(
            "resend_otp.event_published user_id=%s email=%s event=user.otp_resent",
            user.id,
            email,
        )

    async def forgot_password(self, email: str) -> None:
        user = await self.repo.get_by_email(email)
        # Don't leak whether the email exists — always succeed silently.
        if not user:
            return
        reset_token = create_reset_token(sub=str(user.id))
        await publish(
            routing_key="user.password_reset_requested",
            payload={
                "user_id": str(user.id),
                "email": email,
                "reset_token": reset_token,
            },
        )

    async def reset_password(self, token: str, new_password: str) -> None:
        try:
            payload = decode_token(token)
        except JWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token",
            ) from exc

        if payload.get("role") != "reset":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token is not a password-reset token",
            )

        user_id = uuid.UUID(payload["sub"])
        new_hash = hash_password(new_password)
        await self.repo.update_password(user_id, new_hash)
