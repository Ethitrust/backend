"""Pydantic schemas for the Fee service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class FeeCalculateRequest(BaseModel):
    amount: int
    who_pays: Literal["buyer", "seller", "split"]


class FeeCalculateResponse(BaseModel):
    fee_amount: int
    buyer_fee: int
    seller_fee: int


class FeeRecordRequest(BaseModel):
    escrow_id: uuid.UUID
    fee_amount: int
    currency: str
    paid_by: str
    fee_type: str = "escrow_fee"
    org_id: Optional[uuid.UUID] = None


class FeeLedgerResponse(BaseModel):
    id: uuid.UUID
    escrow_id: uuid.UUID
    fee_type: str
    amount: int
    currency: str
    paid_by: str
    status: str
    created_at: datetime
    model_config = {"from_attributes": True}
