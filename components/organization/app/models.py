"""Pydantic schemas for the Organization service."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class OrgCreate(BaseModel):
    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=100, pattern=r"^[a-z0-9-]+$")


class OrgResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    slug: str
    public_key: str
    status: str
    webhook_url: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class OrgKeyResponse(BaseModel):
    id: uuid.UUID
    public_key: str
    secret_key: str  # Shown ONCE only


class WebhookUpdate(BaseModel):
    webhook_url: str
    webhook_secret: str = Field(..., min_length=16)


class MemberInvite(BaseModel):
    user_id: uuid.UUID
    role: Literal["admin", "member"] = "member"


class MemberRoleUpdate(BaseModel):
    role: Literal["admin", "member"]


class RolePermissionsUpdate(BaseModel):
    permissions: list[str] = Field(default_factory=list)


class RoleResponse(BaseModel):
    role: Literal["owner", "admin", "member"]
    permissions: list[str]
    is_system: bool = True


class OrgWalletResponse(BaseModel):
    org_id: uuid.UUID
    wallet_id: uuid.UUID
    currency: str


class OrgWalletBalanceResponse(OrgWalletResponse):
    balance: int
    locked_balance: int


class OrgWalletWithdrawRequest(BaseModel):
    amount: int = Field(..., gt=0, description="Amount in lowest denomination (kobo/cents)")
    provider: str = Field(default="manual", min_length=1, max_length=50)
    reference: str | None = Field(default=None, min_length=1, max_length=255)


class OrgWalletWithdrawResponse(BaseModel):
    wallet_id: uuid.UUID
    currency: str
    amount: int
    provider: str
    reference: str
    new_balance: int
    message: str | None = None
