from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

try:
    import redis.asyncio as _redis_asyncio  # noqa: F401
except ModuleNotFoundError:
    redis_module = types.ModuleType("redis")
    redis_asyncio_module = types.ModuleType("redis.asyncio")

    class _RedisError(Exception):
        pass

    class _Redis:
        pass

    redis_asyncio_module.RedisError = _RedisError
    redis_asyncio_module.Redis = _Redis
    redis_module.asyncio = redis_asyncio_module
    sys.modules["redis"] = redis_module
    sys.modules["redis.asyncio"] = redis_asyncio_module

try:
    from gateway.app import main
except ModuleNotFoundError:
    from app import main  # type: ignore[no-redef]


def _request(path: str, method: str = "GET", authorization: str | None = None):
    headers: dict[str, str] = {}
    if authorization is not None:
        headers["Authorization"] = authorization

    return SimpleNamespace(
        method=method,
        url=SimpleNamespace(path=path),
        headers=headers,
        app=SimpleNamespace(state=SimpleNamespace(http_client=None)),
    )


@pytest.mark.asyncio
async def test_kyc_middleware_bypasses_in_development(monkeypatch) -> None:
    monkeypatch.setattr(main, "IS_DEVELOPMENT", True)
    monkeypatch.setattr(main, "KYC_ENFORCEMENT_ENABLED", True)

    request = _request("/escrow", "POST", "Bearer some-token")
    await main._enforce_kyc_if_required(request)


@pytest.mark.asyncio
async def test_kyc_middleware_still_checks_policy_outside_development(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main, "IS_DEVELOPMENT", False)
    monkeypatch.setattr(main, "KYC_ENFORCEMENT_ENABLED", True)

    # No auth header means middleware should safely no-op, not bypass because of env.
    request = _request("/escrow", "POST")
    await main._enforce_kyc_if_required(request)
