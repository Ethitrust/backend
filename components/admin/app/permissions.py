"""Permission helpers for granular admin scopes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

AVAILABLE_SCOPES: set[str] = {
    "users.read",
    "users.role.update",
    "users.ban.manage",
    "users.verify.override",
    "users.risk_flags.manage",
    "users.moderation_notes.write",
    "users.timeline.read",
    "users.bulk_actions.execute",
    "disputes.queue.read",
    "disputes.queue.update",
    "disputes.evidence.request",
    "disputes.notes.write",
    "disputes.review.move",
    "disputes.resolution.execute",
    "disputes.dashboard.read",
    "payouts.queue.read",
    "payouts.queue.update",
    "payouts.retry.execute",
    "finance.dashboard.read",
    "finance.reconciliation.read",
    "analytics.growth.read",
    "analytics.disputes.read",
    "analytics.payouts.read",
    "analytics.volume.read",
    "config.read",
    "config.validate",
    "config.write",
    "config.rollback",
    "config.history.read",
    "stats.read",
    "actions.read",
    "moderation.notes.write",
    "review_cases.write",
    "saved_views.read",
    "saved_views.write",
    "reports.read",
    "reports.write",
}

DEFAULT_SCOPES_BY_ROLE: dict[str, set[str]] = {
    "admin": {
        "users.read",
        "users.role.update",
        "users.ban.manage",
        "users.verify.override",
        "users.risk_flags.manage",
        "users.moderation_notes.write",
        "users.timeline.read",
        "users.bulk_actions.execute",
        "disputes.queue.read",
        "disputes.queue.update",
        "disputes.evidence.request",
        "disputes.notes.write",
        "disputes.review.move",
        "disputes.resolution.execute",
        "disputes.dashboard.read",
        "payouts.queue.read",
        "payouts.queue.update",
        "payouts.retry.execute",
        "finance.dashboard.read",
        "finance.reconciliation.read",
        "analytics.growth.read",
        "analytics.disputes.read",
        "analytics.payouts.read",
        "analytics.volume.read",
        "config.read",
        "config.validate",
        "config.write",
        "config.rollback",
        "config.history.read",
        "stats.read",
        "actions.read",
        "moderation.notes.write",
        "review_cases.write",
        "saved_views.read",
        "saved_views.write",
        "reports.read",
        "reports.write",
    },
    "moderator": {
        "users.read",
        "stats.read",
        "users.moderation_notes.write",
        "users.timeline.read",
        "disputes.queue.read",
        "disputes.notes.write",
        "disputes.review.move",
        "disputes.dashboard.read",
        "payouts.queue.read",
        "finance.dashboard.read",
        "analytics.growth.read",
        "analytics.disputes.read",
        "analytics.payouts.read",
        "analytics.volume.read",
        "config.read",
        "config.validate",
        "config.history.read",
        "saved_views.read",
        "reports.read",
    },
    "user": set(),
}


def _normalize_scopes(raw_scopes: Any) -> set[str]:
    if raw_scopes is None:
        return set()

    if isinstance(raw_scopes, str):
        candidates: Iterable[str] = raw_scopes.replace(",", " ").split()
    elif isinstance(raw_scopes, Iterable):
        candidates = [str(item) for item in raw_scopes]
    else:
        return set()

    return {scope.strip() for scope in candidates if scope and scope.strip()}


def resolve_scopes(user: Mapping[str, Any]) -> set[str]:
    role = str(user.get("role", "user")).lower()
    explicit_scopes = _normalize_scopes(user.get("scopes"))
    default_scopes = DEFAULT_SCOPES_BY_ROLE.get(role, set())
    return explicit_scopes | default_scopes


def has_scope(user: Mapping[str, Any], required_scope: str) -> bool:
    scopes = resolve_scopes(user)
    if "*" in scopes or required_scope in scopes:
        return True

    parts = required_scope.split(".")
    for i in range(1, len(parts)):
        wildcard_scope = f"{'.'.join(parts[:i])}.*"
        if wildcard_scope in scopes:
            return True

    return False
