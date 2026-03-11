"""Pydantic schemas for the Payment Provider service."""

from __future__ import annotations

from pydantic import BaseModel


class CheckoutResult(BaseModel):
    payment_url: str
    transaction_ref: str
    provider: str


class TransferResult(BaseModel):
    success: bool
    provider_ref: str
    message: str


class BankInfo(BaseModel):
    code: str
    name: str


class AccountValidation(BaseModel):
    account_name: str
    account_number: str
    bank_code: str


# ---------- Request bodies ----------


class CheckoutRequest(BaseModel):
    amount: int
    currency: str
    metadata: dict = {}
    provider: str = "chapa"


class ValidateAccountRequest(BaseModel):
    bank_code: str
    account: str
    currency: str
    provider: str = "chapa"


class TransferRequest(BaseModel):
    account_name: str
    account_number: str
    amount: int
    currency: str = "ETB"
    reference: str
    bank_code: str
    provider: str = "chapa"


class TransferVerifyResponse(BaseModel):
    provider_ref: str
    success: bool
    provider: str
    status: str
