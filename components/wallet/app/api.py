"""HTTP API routes for the Wallet service."""

from __future__ import annotations

import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app import grpc_clients
from app.db import get_db
from app.models import (
    CreateWalletRequest,
    FundRequest,
    PaginatedTransactions,
    TransactionResponse,
    WalletResponse,
)
from app.repository import WalletRepository
from app.service import WalletService

router = APIRouter(prefix="/wallet", tags=["wallet"])

KYC_MIN_LEVEL = int(os.getenv("KYC_MIN_LEVEL", "1"))

security = HTTPBearer(auto_error=False)


async def _enforce_kyc_or_raise(user_id: str) -> int:
    try:
        profile = await grpc_clients.get_user_by_id(user_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify KYC status",
        ) from exc

    kyc_level = int(profile.get("kyc_level", 0))
    if kyc_level < KYC_MIN_LEVEL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "KYC verification is required before accessing this resource. "
                "Please complete KYC first."
            ),
        )
    return kyc_level


async def get_current_user(
    authorization: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(security),
    ],
) -> dict:
    if authorization is None or not authorization.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
        )
    try:
        user = await grpc_clients.validate_token(authorization.credentials)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    kyc_level = await _enforce_kyc_or_raise(user["user_id"])
    user["kyc_level"] = kyc_level
    return user


def _get_service(db: AsyncSession = Depends(get_db)) -> WalletService:
    return WalletService(WalletRepository(db))


# TODO - FUTURE: for future users may have different wallet for different currency
@router.get("", response_model=list[WalletResponse])
async def list_wallets(
    user: dict = Depends(get_current_user),
    service: WalletService = Depends(_get_service),
) -> list[WalletResponse]:
    """Return all wallets belonging to the authenticated user."""
    owner_id = uuid.UUID(user["user_id"])
    wallets = await service.get_wallets(owner_id)
    return [WalletResponse.model_validate(w) for w in wallets]


# wallet should be created automatically when a user signs up, so we can skip the create wallet endpoint for now. We can add it back later if we want to allow users to create multiple wallets for different currencies.
# @router.post("", response_model=WalletResponse, status_code=201)
# async def create_wallet(
#     body: CreateWalletRequest,
#     user: dict = Depends(get_current_user),
#     service: WalletService = Depends(_get_service),
# ) -> WalletResponse:
#     """Create a new wallet for the authenticated user."""
#     owner_id = uuid.UUID(user["user_id"])
#     wallet = await service.create_wallet(owner_id, body.currency.upper())
#     return WalletResponse.model_validate(wallet)


@router.get("/{wallet_id}", response_model=WalletResponse)
async def get_wallet(
    wallet_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    service: WalletService = Depends(_get_service),
) -> WalletResponse:
    """Fetch a specific wallet by ID."""
    wallet = await service.get_balance(wallet_id)
    if wallet.owner_id != uuid.UUID(user["user_id"]) and user.get("role") != "admin":
        raise HTTPException(403, "Access denied")
    return WalletResponse.model_validate(wallet)


@router.get("/{wallet_id}/balance", response_model=WalletResponse)
async def get_balance(
    wallet_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    service: WalletService = Depends(_get_service),
) -> WalletResponse:
    """Return the current balance for a wallet."""
    wallet = await service.get_balance(wallet_id)
    if wallet.owner_id != uuid.UUID(user["user_id"]) and user.get("role") != "admin":
        raise HTTPException(403, "Access denied")
    return WalletResponse.model_validate(wallet)


@router.post("/{wallet_id}/fund", response_model=dict, status_code=202)
async def fund_wallet(
    wallet_id: uuid.UUID,
    body: FundRequest,
    user: dict = Depends(get_current_user),
    service: WalletService = Depends(_get_service),
) -> dict:
    """Initiate a wallet top-up via the payment provider.

    Returns a payment URL that the client should redirect the user to.
    Actual balance credit happens when the ``payment.completed`` event arrives.
    """
    from app.grpc_clients import create_checkout

    wallet = await service.get_balance(wallet_id)
    if wallet.owner_id != uuid.UUID(user["user_id"]):
        raise HTTPException(403, "Access denied")

    checkout = await create_checkout(
        amount=body.amount,
        currency=body.currency.upper(),
        metadata={"wallet_id": str(wallet_id), "user_id": user["user_id"]},
        provider=body.provider,
    )
    return {
        "payment_url": checkout["payment_url"],
        "transaction_ref": checkout["transaction_ref"],
        "provider": checkout["provider"],
        "wallet_id": str(wallet_id),
    }


@router.get("/{wallet_id}/transactions", response_model=PaginatedTransactions)
async def get_transactions(
    wallet_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(get_current_user),
    service: WalletService = Depends(_get_service),
) -> PaginatedTransactions:
    """Return a paginated list of transactions for a wallet."""
    wallet = await service.get_balance(wallet_id)
    if wallet.owner_id != uuid.UUID(user["user_id"]) and user.get("role") != "admin":
        raise HTTPException(403, "Access denied")

    result = await service.get_transactions(wallet_id, page, limit)
    return PaginatedTransactions(
        items=[TransactionResponse.model_validate(tx) for tx in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"],
    )
