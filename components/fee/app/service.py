"""Business logic for the Fee service."""

from __future__ import annotations

import uuid

from app.db import FeeLedger
from app.grpc_client import get_fee_policy
from app.models import (
    FeeCalculateResponse,
    FeeRecordRequest,
)
from app.repository import FeeRepository
from app.settings import MAX_FEE_AMOUNT, MIN_FEE_AMOUNT, PLATFORM_FEE_PERCENT


class FeeService:
    def __init__(self, repo: FeeRepository) -> None:
        self.repo = repo

    async def calculate_fee(self, amount: int, who_pays: str) -> FeeCalculateResponse:
        normalized_who_pays = who_pays.lower().strip()
        if normalized_who_pays == "both":
            normalized_who_pays = "split"

        try:
            policy = await get_fee_policy(amount, normalized_who_pays)
            fee = int(policy["fee_amount"])
            buyer_fee = int(policy["buyer_fee"])
            seller_fee = int(policy["seller_fee"])
            return FeeCalculateResponse(
                fee_amount=fee,
                buyer_fee=buyer_fee,
                seller_fee=seller_fee,
            )
        except RuntimeError:
            # Admin service unavailable or not configured; use local defaults
            raw = int(amount * PLATFORM_FEE_PERCENT / 100)
            fee = max(MIN_FEE_AMOUNT, min(raw, MAX_FEE_AMOUNT))

        if normalized_who_pays == "buyer":
            return FeeCalculateResponse(fee_amount=fee, buyer_fee=fee, seller_fee=0)
        elif normalized_who_pays == "seller":
            return FeeCalculateResponse(fee_amount=fee, buyer_fee=0, seller_fee=fee)
        elif normalized_who_pays == "split":
            half = fee // 2
            return FeeCalculateResponse(fee_amount=fee, buyer_fee=half, seller_fee=fee - half)

        raise ValueError("who_pays must be one of: buyer, seller, split")

    async def record_fee(self, data: FeeRecordRequest) -> FeeLedger:
        entry = FeeLedger(
            escrow_id=data.escrow_id,
            org_id=data.org_id,
            fee_type=data.fee_type,
            amount=data.fee_amount,
            currency=data.currency,
            paid_by=data.paid_by,
            status="collected",
        )
        return await self.repo.create(entry)

    async def refund_fee(self, escrow_id: uuid.UUID) -> list[FeeLedger]:
        """Mark fees as refunded (buyer-win dispute resolution)."""
        return await self.repo.refund(escrow_id)
