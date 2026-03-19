"""Redis client helpers for the KYC service.

Used for Fayda OTP transaction alias storage with configurable TTL.
"""

from __future__ import annotations

import json
import os

import redis.asyncio as redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
FAYDA_TX_ALIAS_TTL_SECONDS = int(os.getenv("FAYDA_TX_ALIAS_TTL_SECONDS", "300"))
FAYDA_TX_ALIAS_PREFIX = "kyc:fayda:tx"

redis_client: redis.Redis = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)


def _tx_alias_key(mirrored_transaction_id: str) -> str:
    return f"{FAYDA_TX_ALIAS_PREFIX}:{mirrored_transaction_id}"


async def set_tx_alias(mirrored_id: str, provider_transaction_id: str, fan_or_fin: str) -> None:
    payload = json.dumps({"provider_transaction_id": provider_transaction_id, "fan_or_fin": fan_or_fin})
    await redis_client.setex(_tx_alias_key(mirrored_id), FAYDA_TX_ALIAS_TTL_SECONDS, payload)


async def get_and_delete_tx_alias(
    mirrored_transaction_id: str, fan_or_fin: str
) -> str | None:
    """Return the provider transaction ID if the alias exists and fan_or_fin matches.

    The alias is only consumed (deleted) after a successful match, so a
    mismatched fan_or_fin does not invalidate the session.
    """
    alias_key = _tx_alias_key(mirrored_transaction_id)
    raw_payload = await redis_client.get(alias_key)
    if not raw_payload:
        return None
    mapped: dict = json.loads(raw_payload)
    if mapped.get("fan_or_fin") != fan_or_fin:
        return None
    await redis_client.delete(alias_key)
    return mapped.get("provider_transaction_id")
