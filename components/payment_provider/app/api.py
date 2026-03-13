"""HTTP API routes for the Payment Provider service."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.models import (
    BankInfo,
    TransferRequest,
    TransferVerifyResponse,
)
from app.service import get_provider

router = APIRouter(prefix="/payment", tags=["payment"])


# INVESTIGATE: do we have any use case where we create a checkout directly by invoking this if not lets remove this and just call the service method directly from the client? since this is basically just a passthrough to the service method and adds extra latency by going through the API layer
# @router.post("/checkout", response_model=CheckoutResult, status_code=201)
# async def create_checkout(body: CheckoutRequest) -> CheckoutResult:
#     """Initialise a payment checkout session and return the redirect URL."""
#     provider = get_provider(body.provider)
#     return await provider.create_checkout(body.amount, body.currency, body.metadata)


@router.get("/verify/{reference}", response_model=dict)
async def verify_payment(
    reference: str,
    provider: str = Query(default="chapa"),
) -> dict:
    """Verify whether a payment reference was settled successfully."""
    prov = get_provider(provider)
    success = await prov.verify_payment(reference)
    return {"reference": reference, "success": success, "provider": provider}


@router.get("/banks", response_model=list[BankInfo])
async def list_banks(
    currency: str = Query(..., description="ISO currency code, e.g. ETB"),
    provider: str = Query(default="chapa"),
) -> list[BankInfo]:
    """Return the list of supported banks for the given currency."""
    prov = get_provider(provider)
    return await prov.get_banks(currency)


# this might not work cause we don't have any usecase for it so lets's comment it out maybe will find a use case for it later
# @router.post("/validate-account", response_model=AccountValidation)
# async def validate_account(body: ValidateAccountRequest) -> AccountValidation:
#     """Validate a bank account number and return the account holder name."""
#     prov = get_provider(body.provider)
#     return await prov.validate_account(body.bank_code, body.account, body.currency)
