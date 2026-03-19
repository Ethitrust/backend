"""Pydantic schemas for the KYC service."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class KYCLookupResponse(BaseModel):
    status: str  # success | not_found | error
    data: Optional[dict[str, Any]] = None
    message: Optional[str] = None
    cached: bool = False


class DriversLicenseRequest(BaseModel):
    license_number: str


class TINRequest(BaseModel):
    tin: str


class FaydaSendOTPRequest(BaseModel):
    fan_or_fin: str


class FaydaVerifyOTPRequest(BaseModel):
    transaction_id: str
    otp: str
    fan_or_fin: str


class FaydaRefreshTokenRequest(BaseModel):
    refresh_token: str


class FaydaActionResponse(BaseModel):
    status: str  # success | error
    data: Optional[dict[str, Any]] = None
    message: Optional[str] = None


class KYCPhotoURLResponse(BaseModel):
    status: str
    data: Optional[dict[str, Any]] = None
    message: Optional[str] = None
