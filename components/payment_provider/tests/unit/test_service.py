"""Unit tests for payment provider service strategies."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.service import ChapaProvider, StripeProvider, get_provider
from fastapi import HTTPException


class TestGetProvider:
    def test_chapa_by_name(self):
        prov = get_provider("chapa")
        assert isinstance(prov, ChapaProvider)

    def test_ethitrust_alias_returns_chapa(self):
        prov = get_provider("ethitrust")
        assert isinstance(prov, ChapaProvider)

    def test_stripe_by_name(self):
        prov = get_provider("stripe")
        assert isinstance(prov, StripeProvider)

    def test_unknown_provider_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            get_provider("unknown_provider")
        assert exc_info.value.status_code == 400
        assert "unknown_provider" in exc_info.value.detail.lower()


class TestChapaProviderCheckout:
    @pytest.mark.asyncio
    async def test_create_checkout_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"authorization_url": "https://checkout.chapa.com/abc123"}
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            provider = ChapaProvider()
            result = await provider.create_checkout(100000, "ETB", {"order_id": "x"})

        assert result.payment_url == "https://checkout.chapa.com/abc123"
        assert result.provider == "chapa"
        assert len(result.transaction_ref) > 0

    @pytest.mark.asyncio
    async def test_create_checkout_upstream_error_raises_502(self):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            provider = ChapaProvider()
            with pytest.raises(HTTPException) as exc_info:
                await provider.create_checkout(100000, "ETB", {})

        assert exc_info.value.status_code == 502


class TestStripeProviderCheckout:
    @pytest.mark.asyncio
    async def test_create_checkout_returns_stripe_provider(self):
        provider = StripeProvider()
        result = await provider.create_checkout(5000, "USD", {})
        assert result.provider == "stripe"
        assert "stripe.com" in result.payment_url

    @pytest.mark.asyncio
    async def test_verify_payment_returns_false(self):
        provider = StripeProvider()
        result = await provider.verify_payment("any_ref")
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_account_raises_501(self):
        provider = StripeProvider()
        with pytest.raises(HTTPException) as exc_info:
            await provider.validate_account("044", "0123456789", "ETB")
        assert exc_info.value.status_code == 501
