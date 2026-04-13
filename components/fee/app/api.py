"""FastAPI route handlers for the Fee service."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import (
    FeeCalculateRequest,
    FeeCalculateResponse,
    FeeLedgerResponse,
    FeeRecordRequest,
)
from app.repository import FeeRepository
from app.service import FeeService

router = APIRouter(prefix="/fee", tags=["fee"])


def get_service(db: AsyncSession = Depends(get_db)) -> FeeService:
    return FeeService(FeeRepository(db))


@router.post("/calculate", response_model=FeeCalculateResponse)
async def calculate_fee(
    body: FeeCalculateRequest,
    svc: FeeService = Depends(get_service),
):
    """Calculate platform fee for a given amount and payer configuration."""
    return await svc.calculate_fee(body.amount, body.who_pays)
