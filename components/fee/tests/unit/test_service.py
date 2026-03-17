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


def test_calculate_fee_buyer():
    svc = FeeService(_make_repo())
    result = svc.calculate_fee(1_000_000, "buyer")
    # 1.5% of 1_000_000 = 15_000, within cap
    assert result.fee_amount == 15_000
    assert result.buyer_fee == 15_000
    assert result.seller_fee == 0


def test_calculate_fee_minimum():
    svc = FeeService(_make_repo())
    result = svc.calculate_fee(100, "seller")
    # 1.5% of 100 = 1.5 → rounds to 1, but minimum is 100
    assert result.fee_amount == MIN_FEE_AMOUNT


def test_calculate_fee_maximum():
    svc = FeeService(_make_repo())
    result = svc.calculate_fee(1_000_000_000, "buyer")
    assert result.fee_amount == MAX_FEE_AMOUNT


def test_calculate_fee_both_split():
    svc = FeeService(_make_repo())
    result = svc.calculate_fee(1_000_000, "both")
    assert result.buyer_fee + result.seller_fee == result.fee_amount


def test_calculate_fee_both_roughly_half():
    svc = FeeService(_make_repo())
    result = svc.calculate_fee(1_000_000, "both")
    assert abs(result.buyer_fee - result.seller_fee) <= 1
