"""Unit tests for FeeService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.service import FeeService
from app.settings import MAX_FEE_AMOUNT, MIN_FEE_AMOUNT


def _make_repo():
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.refund = AsyncMock(return_value=[])
    return repo


@pytest.mark.asyncio
async def test_calculate_fee_buyer(monkeypatch):
    async def _fake_policy(amount: int, who_pays: str) -> dict:
        return {
            "fee_amount": 15_000,
            "buyer_fee": 15_000,
            "seller_fee": 0,
            "platform_fee_percent": 1.5,
            "min_fee_amount": MIN_FEE_AMOUNT,
            "max_fee_amount": MAX_FEE_AMOUNT,
            "used_override": False,
        }

    monkeypatch.setattr("app.service.get_fee_policy", _fake_policy)
    svc = FeeService(_make_repo())
    result = await svc.calculate_fee(1_000_000, "buyer")
    # 1.5% of 1_000_000 = 15_000, within cap
    assert result.fee_amount == 15_000
    assert result.buyer_fee == 15_000
    assert result.seller_fee == 0


@pytest.mark.asyncio
async def test_calculate_fee_minimum(monkeypatch):
    async def _fake_policy(amount: int, who_pays: str) -> dict:
        return {
            "fee_amount": MIN_FEE_AMOUNT,
            "buyer_fee": 0,
            "seller_fee": MIN_FEE_AMOUNT,
            "platform_fee_percent": 1.5,
            "min_fee_amount": MIN_FEE_AMOUNT,
            "max_fee_amount": MAX_FEE_AMOUNT,
            "used_override": False,
        }

    monkeypatch.setattr("app.service.get_fee_policy", _fake_policy)
    svc = FeeService(_make_repo())
    result = await svc.calculate_fee(100, "seller")
    # 1.5% of 100 = 1.5 → rounds to 1, but minimum is 100
    assert result.fee_amount == MIN_FEE_AMOUNT


@pytest.mark.asyncio
async def test_calculate_fee_maximum(monkeypatch):
    async def _fake_policy(amount: int, who_pays: str) -> dict:
        return {
            "fee_amount": MAX_FEE_AMOUNT,
            "buyer_fee": MAX_FEE_AMOUNT,
            "seller_fee": 0,
            "platform_fee_percent": 1.5,
            "min_fee_amount": MIN_FEE_AMOUNT,
            "max_fee_amount": MAX_FEE_AMOUNT,
            "used_override": False,
        }

    monkeypatch.setattr("app.service.get_fee_policy", _fake_policy)
    svc = FeeService(_make_repo())
    result = await svc.calculate_fee(1_000_000_000, "buyer")
    assert result.fee_amount == MAX_FEE_AMOUNT


@pytest.mark.asyncio
async def test_calculate_fee_split(monkeypatch):
    async def _fake_policy(amount: int, who_pays: str) -> dict:
        return {
            "fee_amount": 15_000,
            "buyer_fee": 7_500,
            "seller_fee": 7_500,
            "platform_fee_percent": 1.5,
            "min_fee_amount": MIN_FEE_AMOUNT,
            "max_fee_amount": MAX_FEE_AMOUNT,
            "used_override": False,
        }

    monkeypatch.setattr("app.service.get_fee_policy", _fake_policy)
    svc = FeeService(_make_repo())
    result = await svc.calculate_fee(1_000_000, "split")
    assert result.buyer_fee + result.seller_fee == result.fee_amount


@pytest.mark.asyncio
async def test_calculate_fee_split_roughly_half(monkeypatch):
    async def _fake_policy(amount: int, who_pays: str) -> dict:
        return {
            "fee_amount": 15_001,
            "buyer_fee": 7_500,
            "seller_fee": 7_501,
            "platform_fee_percent": 1.5,
            "min_fee_amount": MIN_FEE_AMOUNT,
            "max_fee_amount": MAX_FEE_AMOUNT,
            "used_override": False,
        }

    monkeypatch.setattr("app.service.get_fee_policy", _fake_policy)
    svc = FeeService(_make_repo())
    result = await svc.calculate_fee(1_000_000, "split")
    assert abs(result.buyer_fee - result.seller_fee) <= 1


@pytest.mark.asyncio
async def test_calculate_fee_uses_admin_override(monkeypatch):
    async def _override_policy(amount: int, who_pays: str) -> dict:
        return {
            "fee_amount": 2_000,
            "buyer_fee": 2_000,
            "seller_fee": 0,
            "platform_fee_percent": 2.0,
            "min_fee_amount": 50,
            "max_fee_amount": 20_000,
            "used_override": True,
        }

    monkeypatch.setattr("app.service.get_fee_policy", _override_policy)
    svc = FeeService(_make_repo())
    result = await svc.calculate_fee(100_000, "buyer")
    assert result.fee_amount == 2_000
    assert result.buyer_fee == 2_000
    assert result.seller_fee == 0


@pytest.mark.asyncio
async def test_calculate_fee_falls_back_to_local_defaults_when_admin_unavailable(monkeypatch):
    async def _failing_policy(amount: int, who_pays: str) -> dict:
        raise RuntimeError("admin unavailable")

    monkeypatch.setattr("app.service.get_fee_policy", _failing_policy)
    svc = FeeService(_make_repo())
    result = await svc.calculate_fee(10_000, "buyer")
    # 1.5% is 150 and within local 1-10 birr bounds (100..1000)
    assert result.fee_amount == 150
    assert result.buyer_fee == 150
    assert result.seller_fee == 0
