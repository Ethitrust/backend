"""Organization RBAC permission catalog and default role templates."""

from __future__ import annotations

from typing import Final

ORG_READ: Final[str] = "org:read"
ORG_MANAGE: Final[str] = "org:manage"
ORG_DELETE: Final[str] = "org:delete"

USER_READ: Final[str] = "user:read"
USER_INVITE: Final[str] = "user:invite"
USER_REMOVE: Final[str] = "user:remove"
USER_ROLE_CHANGE: Final[str] = "user:role:change"

APIKEY_CREATE: Final[str] = "apikey:create"
APIKEY_READ: Final[str] = "apikey:read"
APIKEY_ROTATE: Final[str] = "apikey:rotate"
APIKEY_REVOKE: Final[str] = "apikey:revoke"
APIKEY_SCOPE_ASSIGN: Final[str] = "apikey:scope:assign"

ESCROW_READ_OWN: Final[str] = "escrow:read:own"
ESCROW_READ_ALL: Final[str] = "escrow:read:all"
ESCROW_LIST_ALL: Final[str] = "escrow:list:all"
ESCROW_DEPOSIT: Final[str] = "escrow:deposit"
ESCROW_RELEASE: Final[str] = "escrow:release"
ESCROW_REFUND: Final[str] = "escrow:refund"
ESCROW_CANCEL: Final[str] = "escrow:cancel"
ESCROW_MODIFY: Final[str] = "escrow:modify"
ESCROW_WEBHOOK_OVERRIDE: Final[str] = "escrow:webhook:override"

DISPUTE_RAISE: Final[str] = "dispute:raise"
DISPUTE_READ_OWN: Final[str] = "dispute:read:own"
DISPUTE_READ_ALL: Final[str] = "dispute:read:all"
DISPUTE_EVIDENCE_UPLOAD: Final[str] = "dispute:evidence:upload"
DISPUTE_RESOLVE: Final[str] = "dispute:resolve"
DISPUTE_CANCEL: Final[str] = "dispute:cancel"

RULE_CONFIGURE: Final[str] = "rule:configure"
RULE_MULTI_SIG_CONFIGURE: Final[str] = "rule:multi-sig:configure"

WEBHOOK_MANAGE: Final[str] = "webhook:manage"
WEBHOOK_TEST: Final[str] = "webhook:test"

AUDIT_READ: Final[str] = "audit:read"
AUDIT_EXPORT: Final[str] = "audit:export"

BALANCE_READ: Final[str] = "balance:read"
BALANCE_PAYOUT_REQUEST: Final[str] = "balance:payout:request"

FEE_READ: Final[str] = "fee:read"
FEE_WAIVE: Final[str] = "fee:waive"

COMPLIANCE_REPORT: Final[str] = "compliance:report"
ADMIN_ALL: Final[str] = "admin:all"

PERMISSION_CATALOG: Final[tuple[str, ...]] = (
    ORG_READ,
    ORG_MANAGE,
    ORG_DELETE,
    USER_READ,
    USER_INVITE,
    USER_REMOVE,
    USER_ROLE_CHANGE,
    APIKEY_CREATE,
    APIKEY_READ,
    APIKEY_ROTATE,
    APIKEY_REVOKE,
    APIKEY_SCOPE_ASSIGN,
    ESCROW_READ_OWN,
    ESCROW_READ_ALL,
    ESCROW_LIST_ALL,
    ESCROW_DEPOSIT,
    ESCROW_RELEASE,
    ESCROW_REFUND,
    ESCROW_CANCEL,
    ESCROW_MODIFY,
    ESCROW_WEBHOOK_OVERRIDE,
    DISPUTE_RAISE,
    DISPUTE_READ_OWN,
    DISPUTE_READ_ALL,
    DISPUTE_EVIDENCE_UPLOAD,
    DISPUTE_RESOLVE,
    DISPUTE_CANCEL,
    RULE_CONFIGURE,
    RULE_MULTI_SIG_CONFIGURE,
    WEBHOOK_MANAGE,
    WEBHOOK_TEST,
    AUDIT_READ,
    AUDIT_EXPORT,
    BALANCE_READ,
    BALANCE_PAYOUT_REQUEST,
    FEE_READ,
    FEE_WAIVE,
    COMPLIANCE_REPORT,
    ADMIN_ALL,
)

DEFAULT_ROLE_PERMISSIONS: Final[dict[str, tuple[str, ...]]] = {
    "owner": PERMISSION_CATALOG,
    "admin": (
        ORG_READ,
        ORG_MANAGE,
        USER_READ,
        USER_INVITE,
        USER_REMOVE,
        USER_ROLE_CHANGE,
        APIKEY_CREATE,
        APIKEY_READ,
        APIKEY_ROTATE,
        APIKEY_REVOKE,
        APIKEY_SCOPE_ASSIGN,
        ESCROW_READ_OWN,
        ESCROW_READ_ALL,
        ESCROW_LIST_ALL,
        ESCROW_DEPOSIT,
        ESCROW_RELEASE,
        ESCROW_REFUND,
        ESCROW_CANCEL,
        ESCROW_MODIFY,
        ESCROW_WEBHOOK_OVERRIDE,
        DISPUTE_RAISE,
        DISPUTE_READ_OWN,
        DISPUTE_READ_ALL,
        DISPUTE_EVIDENCE_UPLOAD,
        DISPUTE_RESOLVE,
        DISPUTE_CANCEL,
        RULE_CONFIGURE,
        RULE_MULTI_SIG_CONFIGURE,
        WEBHOOK_MANAGE,
        WEBHOOK_TEST,
        AUDIT_READ,
        AUDIT_EXPORT,
        BALANCE_READ,
        BALANCE_PAYOUT_REQUEST,
        FEE_READ,
        COMPLIANCE_REPORT,
    ),
    "member": (
        ORG_READ,
        ESCROW_READ_OWN,
        ESCROW_DEPOSIT,
        DISPUTE_RAISE,
        DISPUTE_READ_OWN,
        DISPUTE_EVIDENCE_UPLOAD,
    ),
}

SYSTEM_ROLES: Final[tuple[str, ...]] = ("owner", "admin", "member")
