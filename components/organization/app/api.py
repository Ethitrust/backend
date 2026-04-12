"""FastAPI route handlers for the Organization service."""

from __future__ import annotations

import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app import grpc_clients
from app.db import get_db
from app.models import (
    MemberInvite,
    MemberRoleUpdate,
    OrgCreate,
    OrgKeyResponse,
    OrgResponse,
    RolePermissionsUpdate,
    RoleResponse,
    WebhookUpdate,
)
from app.repository import OrgRepository
from app.service import OrgService

router = APIRouter(prefix="/organization", tags=["organizations"])

KYC_MIN_LEVEL = int(os.getenv("KYC_MIN_LEVEL", "1"))

security = HTTPBearer(auto_error=False)


# async def _enforce_kyc_or_raise(user_id: str) -> int:
#     try:
#         profile = await grpc_clients.get_user_by_id(user_id)
#     except RuntimeError as exc:
#         raise HTTPException(503, "Unable to verify KYC status") from exc

#     kyc_level = int(profile.get("kyc_level", 0))
#     if kyc_level < KYC_MIN_LEVEL:
#         raise HTTPException(
#             403,
#             "KYC verification is required before accessing this resource. Please complete KYC first.",
#         )
#     return kyc_level


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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    # kyc_level = await _enforce_kyc_or_raise(user["user_id"])
    # user["kyc_level"] = kyc_level
    return user


def get_service(db: AsyncSession = Depends(get_db)) -> OrgService:
    return OrgService(OrgRepository(db))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OrgKeyResponse)
async def create_org(
    body: OrgCreate,
    current_user: dict = Depends(get_current_user),
    svc: OrgService = Depends(get_service),
):
    """Create an organization. Secret key is returned ONCE."""
    user_id = uuid.UUID(current_user["user_id"])
    org, sk = await svc.create_org(user_id, body)
    return OrgKeyResponse(id=org.id, public_key=org.public_key, secret_key=sk)


@router.get("", response_model=list[OrgResponse])
async def list_orgs(
    current_user: dict = Depends(get_current_user),
    svc: OrgService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    orgs = await svc.list_orgs(user_id)
    return [OrgResponse.model_validate(o) for o in orgs]


@router.get("/{org_id}", response_model=OrgResponse)
async def get_org(
    org_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: OrgService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    org = await svc.get_org(org_id, user_id)
    return OrgResponse.model_validate(org)


# TODO: implement proper access control for the org-member should not be accessable by just any user
@router.post("/{org_id}/keys/rotate", response_model=OrgKeyResponse)
async def rotate_key(
    org_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: OrgService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    org, sk = await svc.rotate_secret_key(org_id, user_id)
    return OrgKeyResponse(id=org.id, public_key=org.public_key, secret_key=sk)


# TODO: implement proper access control for the org-member should not be accessable by just any user
@router.patch("/{org_id}/webhook", response_model=OrgResponse)
async def update_webhook(
    org_id: uuid.UUID,
    body: WebhookUpdate,
    current_user: dict = Depends(get_current_user),
    svc: OrgService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    org = await svc.update_webhook(org_id, user_id, body)
    return OrgResponse.model_validate(org)


# TODO: implement proper access control for the org-member should not be accessable by just any user
@router.post("/{org_id}/members", status_code=status.HTTP_201_CREATED)
async def invite_member(
    org_id: uuid.UUID,
    body: MemberInvite,
    current_user: dict = Depends(get_current_user),
    svc: OrgService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    member = await svc.invite_member(org_id, user_id, body)
    return {
        "id": str(member.id),
        "org_id": str(member.org_id),
        "user_id": str(member.user_id),
        "role": member.role,
    }


@router.patch("/{org_id}/members/{target_user_id}/role")
async def update_member_role(
    org_id: uuid.UUID,
    target_user_id: uuid.UUID,
    body: MemberRoleUpdate,
    current_user: dict = Depends(get_current_user),
    svc: OrgService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    member = await svc.assign_member_role(
        org_id=org_id,
        user_id=user_id,
        target_user_id=target_user_id,
        role_name=body.role,
    )
    return {
        "id": str(member.id),
        "org_id": str(member.org_id),
        "user_id": str(member.user_id),
        "role": member.role,
    }


@router.get("/{org_id}/roles", response_model=list[RoleResponse])
async def list_roles(
    org_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: OrgService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    roles = await svc.list_roles(org_id=org_id, user_id=user_id)
    return [RoleResponse(**role) for role in roles]


@router.put("/{org_id}/roles/{role_name}/permissions", response_model=RoleResponse)
async def update_role_permissions(
    org_id: uuid.UUID,
    role_name: str,
    body: RolePermissionsUpdate,
    current_user: dict = Depends(get_current_user),
    svc: OrgService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    role = await svc.update_role_permissions(
        org_id=org_id,
        user_id=user_id,
        role_name=role_name,
        data=body,
    )
    return RoleResponse(**role)


# TODO: implement proper access control for the org-member should not be accessable by just any user
# only can remove their own member and only org creator aor admin can remove member admin can't remove admin or promot one and org creator can demote/promot/delete admin/user
@router.delete("/{org_id}/members/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: uuid.UUID,
    target_user_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: OrgService = Depends(get_service),
):
    user_id = uuid.UUID(current_user["user_id"])
    await svc.remove_member(org_id, user_id, target_user_id)


@router.get("/{org_id}/members/{user_id}/exists")
async def check_member_exists(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    svc: OrgService = Depends(get_service),
):
    """Internal endpoint: check whether a user belongs to an organization."""
    is_member = await svc.is_member(org_id, user_id)
    return {"is_member": is_member}
