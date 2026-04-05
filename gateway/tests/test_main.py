from __future__ import annotations

from gateway.app.main import SERVICE_MAP, _is_kyc_exempt_path, _resolve_target


def test_resolve_target_requires_segment_boundary() -> None:
    assert _resolve_target("/admin/configs") == (
        SERVICE_MAP["/admin"],
        "/admin/configs",
    )
    assert _resolve_target("/admin") == (SERVICE_MAP["/admin"], "/admin")

    assert _resolve_target("/adminx") is None
    assert _resolve_target("/authz/login") is None


def test_admin_paths_are_kyc_exempt() -> None:
    assert _is_kyc_exempt_path("/admin", "GET") is True
    assert _is_kyc_exempt_path("/admin/users", "POST") is True
