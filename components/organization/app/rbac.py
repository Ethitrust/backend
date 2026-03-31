"""Organization RBAC permission catalog and default role templates."""

from __future__ import annotations

from typing import Final

ORG_MEMBER_VIEW: Final[str] = "org.member.view"
ORG_MEMBER_INVITE: Final[str] = "org.member.invite"
ORG_MEMBER_REMOVE: Final[str] = "org.member.remove"
ORG_ROLE_MANAGE: Final[str] = "org.role.manage"
ORG_MEMBER_ROLE_ASSIGN: Final[str] = "org.member.role.assign"
ORG_SETTINGS_WEBHOOK_UPDATE: Final[str] = "org.settings.webhook.update"
ORG_KEYS_ROTATE: Final[str] = "org.keys.rotate"
ESCROW_VIEW: Final[str] = "escrow.view"
ESCROW_CREATE: Final[str] = "escrow.create"
ESCROW_ACCEPT: Final[str] = "escrow.accept"

PERMISSION_CATALOG: Final[tuple[str, ...]] = (
    ORG_MEMBER_VIEW,
    ORG_MEMBER_INVITE,
    ORG_MEMBER_REMOVE,
    ORG_ROLE_MANAGE,
    ORG_MEMBER_ROLE_ASSIGN,
    ORG_SETTINGS_WEBHOOK_UPDATE,
    ORG_KEYS_ROTATE,
    ESCROW_VIEW,
    ESCROW_CREATE,
    ESCROW_ACCEPT,
)

DEFAULT_ROLE_PERMISSIONS: Final[dict[str, tuple[str, ...]]] = {
    "owner": PERMISSION_CATALOG,
    "admin": (
        ORG_MEMBER_VIEW,
        ORG_MEMBER_INVITE,
        ORG_MEMBER_REMOVE,
        ORG_SETTINGS_WEBHOOK_UPDATE,
        ORG_KEYS_ROTATE,
        ESCROW_VIEW,
        ESCROW_CREATE,
        ESCROW_ACCEPT,
    ),
    "member": (ESCROW_VIEW,),
}

SYSTEM_ROLES: Final[tuple[str, ...]] = ("owner", "admin", "member")
