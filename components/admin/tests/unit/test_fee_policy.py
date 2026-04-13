"""Unit tests for admin fee policy resolution."""

from __future__ import annotations

import pytest
from app.service import AdminService


class _Repo:
    def __init__(self, values: dict | None = None):
        self._values = values or {}

    async def list_system_configs(self):
        return [
            type("Row", (), {"config_key": key, "value_json": value})
            for key, value in self._values.items()
        ]


@pytest.mark.asyncio
async def test_resolve_fee_policy_uses_default_bounds_when_no_override():
    svc = AdminService(_Repo({}))
    result = await svc.resolve_fee_policy(amount=1_000_000, who_pays="buyer")

    # raw = 15,000 at 1.5%, but default max is 1,000 (10 birr)
    assert result["fee_amount"] == 1000
    assert result["buyer_fee"] == 1000
    assert result["seller_fee"] == 0
    assert result["used_override"] is False


@pytest.mark.asyncio
async def test_resolve_fee_policy_uses_admin_overrides():
    svc = AdminService(
        _Repo(
            {
                "fees.platform_fee_percent": 2.0,
                "fees.min_fee_amount": 200,
                "fees.max_fee_amount": 500,
            }
        )
    )
    result = await svc.resolve_fee_policy(amount=50_000, who_pays="split")

    # raw = 1,000, clamped to max override 500
    assert result["fee_amount"] == 500
    assert result["buyer_fee"] == 250
    assert result["seller_fee"] == 250
    assert result["used_override"] is True
