"""Redis client helpers for the Auth service.

Used for OTP storage (10-minute TTL) and JWT blacklisting on logout.
"""

from __future__ import annotations

import os

import redis.asyncio as redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

redis_client: redis.Redis = redis.from_url(REDIS_URL, decode_responses=True)

_OTP_PREFIX = "otp:"
_BLACKLIST_PREFIX = "bl:"


async def set_otp(email: str, otp: str, ttl: int = 600) -> None:
    await redis_client.set(f"{_OTP_PREFIX}{email}", otp, ex=ttl)


async def get_otp(email: str) -> str | None:
    return await redis_client.get(f"{_OTP_PREFIX}{email}")


async def delete_otp(email: str) -> None:
    await redis_client.delete(f"{_OTP_PREFIX}{email}")


async def blacklist_token(jti: str, ttl: int | None = None) -> None:
    effective_ttl = ttl if ttl is not None else ACCESS_TOKEN_EXPIRE_MINUTES * 60
    await redis_client.set(f"{_BLACKLIST_PREFIX}{jti}", "1", ex=effective_ttl)


async def is_token_blacklisted(jti: str) -> bool:
    value = await redis_client.get(f"{_BLACKLIST_PREFIX}{jti}")
    return value is not None
