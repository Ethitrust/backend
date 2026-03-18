"""Pydantic schemas for the Wallet service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class WalletResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    currency: str
    balance: int
    locked_balance: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TransactionResponse(BaseModel):
    id: uuid.UUID
    wallet_id: uuid.UUID
    escrow_id: Optional[uuid.UUID]
    type: str
    amount: int
    currency: str
    status: str
    reference: str
    description: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# for now we should only support one currency ETB
class CreateWalletRequest(BaseModel):
    currency: Literal["ETB"] = Field(..., max_length=10)


# TODO: providers should not be hardcoded, we should have a separate service for handling the payment providers and their configurations. This will help us keep the payment provider data separate from the wallet data and also make it easier to manage and query the payment provider data in the future. We can have a separate database for storing the payment provider data and a separate API for managing the payment provider data.
class FundRequest(BaseModel):
    amount: int = Field(..., gt=0)
    currency: Literal["ETB"] = Field(..., max_length=10)
    provider: str = "chapa"


class PaginatedTransactions(BaseModel):
    items: list[TransactionResponse]
    total: int
    page: int
    limit: int
    pages: int
