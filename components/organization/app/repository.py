"""Repository layer for the Organization service."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import (
    Organization,
    OrganizationMember,
    OrganizationRole,
    OrganizationRolePermission,
)
from app.rbac import DEFAULT_ROLE_PERMISSIONS, SYSTEM_ROLES


class OrgRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def name_exists(self, name: str) -> bool:
        r = await self.db.execute(select(Organization).where(Organization.name == name))
        return r.scalar_one_or_none() is not None

    async def slug_exists(self, slug: str) -> bool:
        r = await self.db.execute(select(Organization).where(Organization.slug == slug))
        return r.scalar_one_or_none() is not None

    async def create(self, org: Organization) -> Organization:
        self.db.add(org)
        await self.db.flush()
        await self.db.refresh(org)
        return org

    async def get_by_id(self, org_id: uuid.UUID) -> Organization | None:
        r = await self.db.execute(select(Organization).where(Organization.id == org_id))
        return r.scalar_one_or_none()

    async def get_by_public_key(self, pk: str) -> Organization | None:
        r = await self.db.execute(
            select(Organization).where(Organization.public_key == pk)
        )
        return r.scalar_one_or_none()

    async def list_for_secret_key_verification(
        self,
        is_test: bool | None = None,
    ) -> list[Organization]:
        query = select(Organization)
        if is_test is True:
            query = query.where(Organization.public_key.like("pk_test_%"))
        elif is_test is False:
            query = query.where(Organization.public_key.like("pk_live_%"))

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_by_owner(self, owner_id: uuid.UUID) -> list[Organization]:
        r = await self.db.execute(
            select(Organization).where(Organization.owner_id == owner_id)
        )
        return list(r.scalars().all())

    async def update_webhook(
        self, org_id: uuid.UUID, url: str, secret: str
    ) -> Organization | None:
        org = await self.get_by_id(org_id)
        if org:
            org.webhook_url = url
            org.webhook_secret = secret
            await self.db.flush()
            await self.db.refresh(org)
        return org

    async def update_secret_key_hash(
        self, org_id: uuid.UUID, new_hash: str, new_pk: str
    ) -> Organization | None:
        org = await self.get_by_id(org_id)
        if org:
            org.secret_key_hash = new_hash
            org.public_key = new_pk
            await self.db.flush()
            await self.db.refresh(org)
        return org

    async def get_member(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> OrganizationMember | None:
        r = await self.db.execute(
            select(OrganizationMember).where(
                OrganizationMember.org_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        return r.scalar_one_or_none()

    async def add_member(self, member: OrganizationMember) -> OrganizationMember:
        self.db.add(member)
        await self.db.flush()
        await self.db.refresh(member)
        return member

    async def upsert_member_role(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str,
    ) -> OrganizationMember:
        member = await self.get_member(org_id, user_id)
        if member is None:
            member = OrganizationMember(org_id=org_id, user_id=user_id, role=role)
            return await self.add_member(member)

        member.role = role
        await self.db.flush()
        await self.db.refresh(member)
        return member

    async def remove_member(self, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
        member = await self.get_member(org_id, user_id)
        if member:
            await self.db.delete(member)
            await self.db.flush()

    async def list_roles(self, org_id: uuid.UUID) -> list[OrganizationRole]:
        r = await self.db.execute(
            select(OrganizationRole)
            .where(OrganizationRole.org_id == org_id)
            .order_by(OrganizationRole.created_at.asc())
        )
        return list(r.scalars().all())

    async def get_role_by_name(
        self,
        org_id: uuid.UUID,
        role_name: str,
    ) -> OrganizationRole | None:
        r = await self.db.execute(
            select(OrganizationRole).where(
                OrganizationRole.org_id == org_id,
                OrganizationRole.name == role_name,
            )
        )
        return r.scalar_one_or_none()

    async def create_role(
        self,
        org_id: uuid.UUID,
        name: str,
        description: str | None,
        is_system: bool = False,
    ) -> OrganizationRole:
        role = OrganizationRole(
            org_id=org_id,
            name=name,
            description=description,
            is_system=is_system,
        )
        self.db.add(role)
        await self.db.flush()
        await self.db.refresh(role)
        return role

    async def delete_role(self, role: OrganizationRole) -> None:
        await self.db.delete(role)
        await self.db.flush()

    async def set_role_permissions(
        self,
        role_id: uuid.UUID,
        permissions: list[str],
    ) -> list[OrganizationRolePermission]:
        await self.db.execute(
            delete(OrganizationRolePermission).where(
                OrganizationRolePermission.role_id == role_id
            )
        )
        records: list[OrganizationRolePermission] = []
        for permission_key in permissions:
            record = OrganizationRolePermission(
                role_id=role_id,
                permission_key=permission_key,
            )
            self.db.add(record)
            records.append(record)

        await self.db.flush()
        return records

    async def list_permissions_for_role(self, role_id: uuid.UUID) -> list[str]:
        r = await self.db.execute(
            select(OrganizationRolePermission.permission_key).where(
                OrganizationRolePermission.role_id == role_id
            )
        )
        return list(r.scalars().all())

    async def list_permissions_for_role_name(
        self,
        org_id: uuid.UUID,
        role_name: str,
    ) -> list[str]:
        role = await self.get_role_by_name(org_id, role_name)
        if role is None:
            return []
        return await self.list_permissions_for_role(role.id)

    async def ensure_default_roles(self, org_id: uuid.UUID) -> None:
        """Ensure default system roles exist, without overwriting customized permissions."""
        existing_roles = await self.list_roles(org_id)
        existing_by_name = {role.name: role for role in existing_roles}

        for role_name in SYSTEM_ROLES:
            role = existing_by_name.get(role_name)
            if role is None:
                role = await self.create_role(
                    org_id=org_id,
                    name=role_name,
                    description=f"System role: {role_name}",
                    is_system=True,
                )
                existing_by_name[role_name] = role
                await self.set_role_permissions(
                    role.id,
                    sorted(DEFAULT_ROLE_PERMISSIONS[role_name]),
                )

    async def is_role_used(self, org_id: uuid.UUID, role_name: str) -> bool:
        r = await self.db.execute(
            select(OrganizationMember).where(
                OrganizationMember.org_id == org_id,
                OrganizationMember.role == role_name,
            )
        )
        return r.scalar_one_or_none() is not None

    async def is_member(self, org_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        org = await self.get_by_id(org_id)
        if org is None:
            return False
        if org.owner_id == user_id:
            return True

        member = await self.get_member(org_id, user_id)
        return member is not None
