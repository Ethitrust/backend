"""Security utilities: password hashing, JWT creation/verification."""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext

SECRET_KEY = os.getenv("SECRET_KEY", "changeme-in-production-use-a-long-random-string")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(
    sub: str,
    role: str = "user",
    exp: int = ACCESS_TOKEN_EXPIRE_MINUTES,
    extra_claims: dict | None = None,
) -> str:
    now = datetime.now(tz=timezone.utc)
    claims: dict = {
        "sub": sub,
        "role": role,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=exp),
    }
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)


def create_reset_token(sub: str) -> str:
    """Short-lived (5 min) token used for password reset flows."""
    return create_access_token(sub, role="reset", exp=5)


def decode_token(token: str) -> dict[str, object]:
    """Decode and validate a JWT.

    Raises:
        jose.JWTError: when the token is invalid or expired.
    """
    payload: Mapping[str, object] = jwt.decode(
        token, SECRET_KEY, algorithms=[ALGORITHM]
    )
    return dict(payload)


async def get_current_user_id(authorization: str = Header(...)) -> str:
    """FastAPI dependency — validates Bearer token and returns user id (str UUID)."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
        )
    payload = await get_current_token_payload(authorization)
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return sub


async def get_current_token_payload(authorization: str) -> dict[str, object]:
    """Decode bearer token, enforce blacklist, and return payload."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
        )

    token = authorization.removeprefix("Bearer ")
    from app.redis_client import is_token_blacklisted

    try:
        payload = decode_token(token)
        jti = payload.get("jti")
        if not isinstance(jti, str) or not jti:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing jti",
            )
        if await is_token_blacklisted(jti):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )
        return payload
    except (JWTError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc
