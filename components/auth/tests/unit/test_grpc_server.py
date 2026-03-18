"""Unit tests for auth gRPC server helpers."""

from __future__ import annotations

from app.grpc_server import _extract_scopes


def test_extract_scopes_from_string() -> None:
    payload = {"scopes": "users.read, reports.read  analytics.growth.read"}

    assert _extract_scopes(payload) == [
        "users.read",
        "reports.read",
        "analytics.growth.read",
    ]


def test_extract_scopes_from_iterable() -> None:
    payload = {"scopes": ["users.read", " reports.write ", 123]}

    assert _extract_scopes(payload) == ["users.read", "reports.write", "123"]


def test_extract_scopes_unsupported_type_returns_empty() -> None:
    payload = {"scopes": {"unexpected": "shape"}}

    assert _extract_scopes(payload) == []
