"""Pydantic schemas for the Organization service."""

from __future__ import annotations

import uuid
from datetime import datetime

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
    role: str = Field(default="member", min_length=1, max_length=64)


class MemberRoleUpdate(BaseModel):
    role: str = Field(..., min_length=1, max_length=64)


class RolePermissionsUpdate(BaseModel):
    permissions: list[str] = Field(default_factory=list)


class RoleResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str | None
    is_system: bool
    permissions: list[str]
    created_at: datetime
    model_config = {"from_attributes": True}
