"""Unit tests for admin permission scope resolution."""

from __future__ import annotations

from app.permissions import has_scope, resolve_scopes


def test_resolve_scopes_includes_role_defaults() -> None:
    user = {"role": "moderator"}

    scopes = resolve_scopes(user)

    assert "users.read" in scopes
    assert "disputes.queue.read" in scopes
    assert "analytics.growth.read" in scopes


def test_resolve_scopes_merges_explicit_scope_string() -> None:
    user = {
        "role": "user",
        "scopes": "reports.read, analytics.growth.read saved_views.read",
    }

    scopes = resolve_scopes(user)

    assert scopes == {"reports.read", "analytics.growth.read", "saved_views.read"}


def test_has_scope_honors_wildcard_namespace() -> None:
    user = {"role": "user", "scopes": ["analytics.*"]}

    assert has_scope(user, "analytics.growth.read") is True
    assert has_scope(user, "analytics.disputes.read") is True
    assert has_scope(user, "users.read") is False


def test_has_scope_honors_global_wildcard() -> None:
    user = {"role": "user", "scopes": ["*"]}

    assert has_scope(user, "users.bulk_actions.execute") is True
