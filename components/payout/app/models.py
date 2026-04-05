"""Pydantic schemas for the Payout service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PayoutRequest(BaseModel):
    wallet_id: uuid.UUID
    amount: int = Field(
        ..., gt=0, description="Amount in lowest denomination (kobo/cents)"
    )
    currency: str = Field(..., max_length=10)
    bank_code: str = Field(..., max_length=20)
    account_number: str = Field(..., max_length=30)
    account_name: str = Field(..., max_length=255)
    provider: str = Field("chapa", max_length=50)


class PayoutResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    wallet_id: uuid.UUID
    amount: int
    currency: str
    bank_code: str
    account_number: str
    account_name: str
    status: str
    provider: Optional[str]
    provider_ref: Optional[str]
    failure_reason: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedPayoutResponse(BaseModel):
    items: list[PayoutResponse]
    total: int
    page: int
    limit: int
