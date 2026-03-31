"""Business logic for the Organization service."""

from __future__ import annotations

import logging
import secrets
import uuid

from fastapi import HTTPException, status
from passlib.context import CryptContext

from app.db import Organization, OrganizationMember
from app.messaging import publish
from app.models import (
    MemberInvite,
    OrgCreate,
    RolePermissionsUpdate,
    WebhookUpdate,
)
from app.rbac import (
    ORG_KEYS_ROTATE,
    ORG_MEMBER_INVITE,
    ORG_MEMBER_REMOVE,
    ORG_SETTINGS_WEBHOOK_UPDATE,
    PERMISSION_CATALOG,
)
from app.repository import OrgRepository

pwd_ctx = CryptContext(schemes=["argon2"], deprecated="auto")
logger = logging.getLogger(__name__)


def _generate_key_pair(is_test: bool = False) -> tuple[str, str]:
    mode = "test" if is_test else "live"
    public_key = f"pk_{mode}_{secrets.token_hex(32)}"
    secret_key = f"sk_{mode}_{secrets.token_hex(32)}"
    return public_key, secret_key


class OrgService:
    def __init__(self, repo: OrgRepository) -> None:
        self.repo = repo

    @staticmethod
    def _validate_permissions(permissions: list[str]) -> list[str]:
        allowed = set(PERMISSION_CATALOG)
        invalid = sorted(
            {permission for permission in permissions if permission not in allowed}
        )
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown permission(s): {', '.join(invalid)}",
            )
        return sorted(set(permissions))

    async def _require_org(self, org_id: uuid.UUID) -> Organization:
        org = await self.repo.get_by_id(org_id)
        if org is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )
        return org

    async def _require_owner(
        self, org_id: uuid.UUID, actor_id: uuid.UUID
    ) -> Organization:
        org = await self._require_org(org_id)
        if org.owner_id != actor_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the organization owner can perform this action",
            )
        return org

    async def _get_actor_role(self, org_id: uuid.UUID, actor_id: uuid.UUID) -> str:
        org = await self._require_org(org_id)
        if org.owner_id == actor_id:
            return "owner"

        member = await self.repo.get_member(org_id, actor_id)
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization",
            )
        return member.role

    async def _require_permission(
        self,
        org_id: uuid.UUID,
        actor_id: uuid.UUID,
        permission: str,
    ) -> None:
        role_name = await self._get_actor_role(org_id, actor_id)
        permissions = await self.repo.list_permissions_for_role_name(org_id, role_name)
        if permission not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission '{permission}'",
            )

    async def create_org(
        self, owner_id: uuid.UUID, data: OrgCreate
    ) -> tuple[Organization, str]:
        """Returns (org, plain_secret_key). Secret key shown once."""
        if await self.repo.name_exists(data.name):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Organization name already taken",
            )
        if await self.repo.slug_exists(data.slug):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Slug already taken"
            )

        pk, sk = _generate_key_pair(data.is_test)
        org = Organization(
            owner_id=owner_id,
            name=data.name,
            slug=data.slug,
            public_key=pk,
            secret_key_hash=pwd_ctx.hash(sk),
        )
        org = await self.repo.create(org)

        await self.repo.ensure_default_roles(org.id)

        # Add owner as member
        member = OrganizationMember(org_id=org.id, user_id=owner_id, role="owner")
        await self.repo.add_member(member)

        try:
            await publish(
                "organization.created",
                {
                    "org_id": str(org.id),
                    "owner_id": str(owner_id),
                },
            )
        except Exception:
            logger.exception(
                "Failed to publish organization.created event for org_id=%s",
                org.id,
            )

        return org, sk

    async def get_org(self, org_id: uuid.UUID, user_id: uuid.UUID) -> Organization:
        org = await self._require_org(org_id)
        if org.owner_id == user_id:
            return org

        member = await self.repo.get_member(org_id, user_id)
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )
        return org

    async def list_orgs(self, user_id: uuid.UUID) -> list[Organization]:
        return await self.repo.list_by_owner(user_id)

    async def rotate_secret_key(
        self, org_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[Organization, str]:
        await self.repo.ensure_default_roles(org_id)
        await self._require_permission(org_id, user_id, ORG_KEYS_ROTATE)
        org = await self._require_org(org_id)
        pk, sk = _generate_key_pair("test" in org.public_key)
        org = await self.repo.update_secret_key_hash(org_id, pwd_ctx.hash(sk), pk)
        return org, sk

    async def update_webhook(
        self, org_id: uuid.UUID, user_id: uuid.UUID, data: WebhookUpdate
    ) -> Organization:
        await self.repo.ensure_default_roles(org_id)
        await self._require_permission(org_id, user_id, ORG_SETTINGS_WEBHOOK_UPDATE)
        return await self.repo.update_webhook(
            org_id, data.webhook_url, data.webhook_secret
        )

    async def invite_member(
        self, org_id: uuid.UUID, user_id: uuid.UUID, data: MemberInvite
    ) -> OrganizationMember:
        await self.repo.ensure_default_roles(org_id)
        await self._require_permission(org_id, user_id, ORG_MEMBER_INVITE)

        role = await self.repo.get_role_by_name(org_id, data.role)
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found",
            )

        member = OrganizationMember(org_id=org_id, user_id=data.user_id, role=data.role)
        return await self.repo.add_member(member)

    async def remove_member(
        self, org_id: uuid.UUID, user_id: uuid.UUID, target_user_id: uuid.UUID
    ) -> None:
        await self.repo.ensure_default_roles(org_id)
        await self._require_permission(org_id, user_id, ORG_MEMBER_REMOVE)

        org = await self._require_org(org_id)
        if org.owner_id == target_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The organization owner cannot be removed",
            )

        await self.repo.remove_member(org_id, target_user_id)

    async def list_roles(self, org_id: uuid.UUID, user_id: uuid.UUID):
        await self._require_owner(org_id, user_id)
        await self.repo.ensure_default_roles(org_id)

        roles = await self.repo.list_roles(org_id)
        result: list[dict] = []
        for role in roles:
            permissions = await self.repo.list_permissions_for_role(role.id)
            result.append(
                {
                    "id": role.id,
                    "org_id": role.org_id,
                    "name": role.name,
                    "description": role.description,
                    "is_system": role.is_system,
                    "permissions": sorted(permissions),
                    "created_at": role.created_at,
                }
            )
        return result

    async def update_role_permissions(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        role_name: str,
        data: RolePermissionsUpdate,
    ) -> dict:
        await self._require_owner(org_id, user_id)
        await self.repo.ensure_default_roles(org_id)

        role = await self.repo.get_role_by_name(org_id, role_name)
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found",
            )

        if not role.is_system:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only system role permissions can be modified",
            )

        permissions = self._validate_permissions(data.permissions)
        await self.repo.set_role_permissions(role.id, permissions)

        return {
            "id": role.id,
            "org_id": role.org_id,
            "name": role.name,
            "description": role.description,
            "is_system": role.is_system,
            "permissions": permissions,
            "created_at": role.created_at,
        }

    async def assign_member_role(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        target_user_id: uuid.UUID,
        role_name: str,
    ) -> OrganizationMember:
        org = await self._require_owner(org_id, user_id)
        await self.repo.ensure_default_roles(org_id)

        role = await self.repo.get_role_by_name(org_id, role_name)
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role not found",
            )

        if target_user_id == org.owner_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Owner role cannot be reassigned",
            )

        return await self.repo.upsert_member_role(org_id, target_user_id, role_name)

    async def is_member(self, org_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        return await self.repo.is_member(org_id, user_id)

    async def verify_secret_key(self, raw_sk: str) -> Organization | None:
        if raw_sk.startswith("sk_test_"):
            scope = True
        elif raw_sk.startswith("sk_live_"):
            scope = False
        else:
            return None

        orgs = await self.repo.list_for_secret_key_verification(scope)
        for org in orgs:
            try:
                if pwd_ctx.verify(raw_sk, org.secret_key_hash):
                    return org
            except Exception:
                logger.exception(
                    "Secret key verification failed unexpectedly for org_id=%s",
                    org.id,
                )
        return None

    async def get_by_public_key(self, pk: str) -> Organization | None:
        return await self.repo.get_by_public_key(pk)
