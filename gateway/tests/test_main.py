from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

try:
    from gateway.app.main import (
        DEFAULT_UPSTREAM_TIMEOUT_SECONDS,
        SERVICE_MAP,
        _append_forwarded_for,
        _extract_bearer_token,
        _get_cached_kyc_level,
        _is_kyc_exempt_path,
        _is_org_api_key_escrow_create,
        _is_probable_org_api_key,
        _resolve_target,
        _resolve_timeout_for_path,
        _set_cached_kyc_level,
    )
except ModuleNotFoundError:
    from app.main import (  # type: ignore[no-redef]
        DEFAULT_UPSTREAM_TIMEOUT_SECONDS,
        SERVICE_MAP,
        _append_forwarded_for,
        _extract_bearer_token,
        _get_cached_kyc_level,
        _is_kyc_exempt_path,
        _is_org_api_key_escrow_create,
        _is_probable_org_api_key,
        _resolve_target,
        _resolve_timeout_for_path,
        _set_cached_kyc_level,
    )


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


def test_extract_bearer_token() -> None:
    assert _extract_bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"
    assert _extract_bearer_token("Bearer sk_live_123") == "sk_live_123"
    assert _extract_bearer_token("Basic abc") is None
    assert _extract_bearer_token(None) is None


def test_org_api_key_heuristic_rejects_jwt_like_tokens() -> None:
    assert _is_probable_org_api_key("sk_live_abc123") is True
    assert _is_probable_org_api_key("sk_live_abc.123") is False
    assert _is_probable_org_api_key("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig") is False


def test_org_bypass_only_for_post_escrow() -> None:
    auth = "Bearer sk_live_abc123"
    assert _is_org_api_key_escrow_create("/escrow", "POST", auth) is True
    assert _is_org_api_key_escrow_create("/escrow", "GET", auth) is False
    assert _is_org_api_key_escrow_create("/escrow/items", "POST", auth) is False


def test_resolve_timeout_for_path() -> None:
    assert _resolve_timeout_for_path("/invoice/download").read == 60.0
    assert _resolve_timeout_for_path("/kyc/status").read == 10.0
    assert _resolve_timeout_for_path("/auth/login").read == pytest.approx(
        DEFAULT_UPSTREAM_TIMEOUT_SECONDS
    )


def test_append_forwarded_for() -> None:
    assert _append_forwarded_for(None, "10.0.0.2") == "10.0.0.2"
    assert _append_forwarded_for("1.1.1.1", "10.0.0.2") == "1.1.1.1, 10.0.0.2"
    assert _append_forwarded_for("1.1.1.1", None) == "1.1.1.1"


def test_kyc_cache_set_and_get() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.store: dict[str, str] = {}

        async def get(self, key: str) -> str | None:
            return self.store.get(key)

        async def set(self, key: str, value: str, ex: int | None = None) -> None:
            self.store[key] = value

    state = SimpleNamespace(redis_client=FakeRedis())
    app = SimpleNamespace(state=state)
    request = SimpleNamespace(app=app)

    token = "Bearer-token-value"
    asyncio.run(_set_cached_kyc_level(request, token, 2))
    assert asyncio.run(_get_cached_kyc_level(request, token)) == 2
    assert asyncio.run(_get_cached_kyc_level(request, "different-token")) is None
