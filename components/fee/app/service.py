"""Business logic for the Fee service."""

from __future__ import annotations

import uuid
from typing import Optional

from app.db import FeeLedger
from app.models import (
    FeeCalculateResponse,
    FeeRecordRequest,
)
from app.repository import FeeRepository
from app.settings import MAX_FEE_AMOUNT, MIN_FEE_AMOUNT, PLATFORM_FEE_PERCENT


class FeeService:
    def __init__(self, repo: FeeRepository) -> None:
        self.repo = repo

    def calculate_fee(self, amount: int, who_pays: str) -> FeeCalculateResponse:
        raw = int(amount * PLATFORM_FEE_PERCENT / 100)
        fee = max(MIN_FEE_AMOUNT, min(raw, MAX_FEE_AMOUNT))

        if who_pays == "buyer":
            return FeeCalculateResponse(fee_amount=fee, buyer_fee=fee, seller_fee=0)
        elif who_pays == "seller":
            return FeeCalculateResponse(fee_amount=fee, buyer_fee=0, seller_fee=fee)
        elif who_pays == "both":
            half = fee // 2
            return FeeCalculateResponse(
                fee_amount=fee, buyer_fee=half, seller_fee=fee - half
            )
        else:
            return FeeCalculateResponse(fee_amount=fee, buyer_fee=0, seller_fee=0)

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
