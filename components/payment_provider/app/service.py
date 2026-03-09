"""
Payment provider strategies.

Each provider implements BasePaymentProvider.  Get the right instance via
``get_provider(name)``.

Currently implemented:
  - chapa  (also aliased as "ethitrust")
  - stripe    (stub only)
"""

from __future__ import annotations

import os
import uuid
from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional

import httpx
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------
from pydantic import BaseModel, EmailStr, Field, ValidationError

from app.models import AccountValidation, BankInfo, CheckoutResult, TransferResult


class TransferOptions(BaseModel):
    account_name: str
    account_number: str
    amount: str
    currency: str = Field("ETB", description="ISO currency code, e.g. ETB")
    reference: str
    bank_code: int


class SplitType(str, Enum):
    PERCENTAGE = "percentage"
    FLAT = "flat"


class Customization(BaseModel):
    title: str
    description: str
    logo: Optional[str] = None


class MetaItem(BaseModel):
    key: str
    value: str


class Meta(BaseModel):
    invoices: List[MetaItem]
    payment_reason: Optional[str] = None
    hide_receipt: Optional[bool] = False
    disable_phone_edit: Optional[bool] = False
    custom_receipt_enabled: Optional[bool] = False


class Subaccount(BaseModel):
    id: str
    split_type: SplitType
    split_value: float = Field(
        ..., gt=0, description="Percentage split value, e.g. 20.5 for 20.5%"
    )


class ChapaInitRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone_number: Optional[str] = None

    currency: str
    amount: str
    tx_ref: str

    callback_url: Optional[str] = None
    return_url: Optional[str] = None

    customization: Optional[Customization] = None
    subaccounts: Optional[List[Subaccount]] = None
    meta: Optional[Meta] = None


class ChapaResponseData(BaseModel):
    checkout_url: str


class ChapaInitSuccessResponse(BaseModel):
    status: str
    message: str
    data: ChapaResponseData


class BasePaymentProvider(ABC):
    @abstractmethod
    async def create_checkout(self, request: ChapaInitRequest) -> CheckoutResult: ...

    @abstractmethod
    async def verify_payment(self, reference: str) -> bool: ...

    @abstractmethod
    async def initiate_transfer(self, request: TransferOptions) -> TransferResult: ...

    @abstractmethod
    async def verify_transfer(self, provider_ref: str) -> bool: ...

    @abstractmethod
    async def get_banks(self, currency: str) -> list[BankInfo]: ...

    # @abstractmethod
    # async def validate_account(
    #     self, bank_code: str, account: str, currency: str
    # ) -> AccountValidation: ...


class ChapaProvider(BasePaymentProvider):
    BASE_URL = "https://api.chapa.co"

    def __init__(self) -> None:
        self.secret_key = os.getenv("CHAPA_SECRET_KEY", "")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    async def create_checkout(self, request: ChapaInitRequest) -> CheckoutResult:
        ref = str(uuid.uuid4()).replace("-", "")

        try:
            request = ChapaInitRequest(**request)
        except ValidationError as e:
            raise ValueError(f"Invalid request: {e}")

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.BASE_URL}/v1/transaction/initialize",
                json=request.model_dump(),
                headers=self._headers(),
                timeout=10.0,
            )
            if r.status_code != 200:
                raise HTTPException(502, f"Chapa error: {r.text}")
            data = ChapaInitSuccessResponse(**r.json()).data

            return CheckoutResult(
                payment_url=data.checkout_url,
                transaction_ref=ref,
                provider="chapa",
            )

    async def verify_payment(self, reference: str) -> bool:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {self.secret_key}"}
            # <tx_ref> is the tx_ref that was set by you when initiating a payment.
            r = await client.get(
                f"{self.BASE_URL}/v1/transaction/verify/{reference}",
                headers=headers,
                timeout=10.0,
            )
            if r.status_code != 200:
                return False
            return r.json()["data"]["status"] == "success"

    async def initiate_transfer(self, request: TransferOptions) -> TransferResult:
        try:
            request = TransferOptions(**request)
        except ValidationError as e:
            raise ValueError(f"Invalid transfer options: {e}")

        async with httpx.AsyncClient() as client:
            rec_r = await client.post(
                f"{self.BASE_URL}/v1/transfers",
                json=request.model_dump(),
                headers=self._headers(),
                timeout=10.0,
            )
            rec_r.raise_for_status()
            if rec_r.json()["status"] != "success":
                raise HTTPException(502, "Failed to create transfer recipient")
            return TransferResult(
                success=True,
                provider_ref=rec_r.json()["data"],
                message="Transfer initiated",
            )

    async def verify_transfer(self, provider_ref: str) -> bool:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.BASE_URL}/v1/transfers/verify/{provider_ref}",
                headers=self._headers(),
                timeout=10.0,
            )
            if r.status_code != 200:
                return False
            return r.json()["data"]["status"] == "success"

    async def get_banks(self, currency: str) -> list[BankInfo]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.BASE_URL}/v1/banks",
                headers=self._headers(),
                timeout=10.0,
            )
            r.raise_for_status()
            if r.status_code != 200:
                return []
            return [
                BankInfo(code=b["id"], name=b["name"])
                for b in r.json()["data"]
                if b["is_active"]
            ]

    # async def validate_account(
    #     self, bank_code: str, account: str, currency: str
    # ) -> AccountValidation:
    #     async with httpx.AsyncClient() as client:
    #         headers = {"Authorization": f"Bearer {self.secret_key}"}
    #         r = await client.get(
    #             f"{self.BASE_URL}/bank/resolve?account_number={account}&bank_code={bank_code}",
    #             headers=headers,
    #             timeout=10.0,
    #         )
    #         if r.status_code != 200:
    #             raise HTTPException(
    #                 400, "INVALID_BANK_ACCOUNT: Could not validate bank account"
    #             )
    #         d = r.json()["data"]
    #         return AccountValidation(
    #             account_name=d["account_name"],
    #             account_number=d["account_number"],
    #             bank_code=bank_code,
    #         )


# ---------------------------------------------------------------------------
# Stripe (stub)
# ---------------------------------------------------------------------------


class StripeProvider(BasePaymentProvider):
    """Stub Stripe implementation — replace with real Stripe SDK calls."""

    def __init__(self) -> None:
        self.secret_key = os.getenv("STRIPE_SECRET_KEY", "")

    async def create_checkout(
        self, amount: int, currency: str, metadata: dict
    ) -> CheckoutResult:
        # TODO: implement Stripe Checkout Sessions
        ref = str(uuid.uuid4()).replace("-", "")
        return CheckoutResult(
            payment_url=f"https://checkout.stripe.com/pay/{ref}",
            transaction_ref=ref,
            provider="stripe",
        )

    async def verify_payment(self, reference: str) -> bool:
        return False

    async def initiate_transfer(
        self, bank_code: str, account: str, amount: int, currency: str
    ) -> TransferResult:
        return TransferResult(
            success=False,
            provider_ref="",
            message="Stripe transfers not implemented",
        )

    async def verify_transfer(self, provider_ref: str) -> bool:
        return False

    async def get_banks(self, currency: str) -> list[BankInfo]:
        return []

    async def validate_account(
        self, bank_code: str, account: str, currency: str
    ) -> AccountValidation:
        raise HTTPException(501, "Bank account validation not implemented for Stripe")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

# disabled stripe for now since we don't have an immediate use case for it
_PROVIDER_REGISTRY: dict[str, type[BasePaymentProvider]] = {
    "chapa": ChapaProvider,
    # "stripe": StripeProvider,
}


def get_provider(name: str) -> BasePaymentProvider:
    """Return the concrete provider instance for *name*.

    Raises:
        HTTPException 400: when the name is unknown.
    """
    cls = _PROVIDER_REGISTRY.get(name.lower())
    if not cls:
        raise HTTPException(400, f"Unknown payment provider: {name}")
    return cls()
