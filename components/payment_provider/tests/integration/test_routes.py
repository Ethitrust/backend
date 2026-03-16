"""Integration tests for Payment Provider HTTP routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCreateCheckout:
    @pytest.mark.asyncio
    async def test_checkout_success(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {"authorization_url": "https://checkout.chapa.com/testref"}
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            response = await client.post(
                "/payment/checkout",
                json={
                    "amount": 50000,
                    "currency": "ETB",
                    "metadata": {},
                    "provider": "chapa",
                },
            )

        assert response.status_code == 201
        data = response.json()
        assert data["payment_url"] == "https://checkout.chapa.com/testref"
        assert data["provider"] == "chapa"

    @pytest.mark.asyncio
    async def test_checkout_unknown_provider_returns_400(self, client):
        response = await client.post(
            "/payment/checkout",
            json={"amount": 50000, "currency": "ETB", "provider": "unknown"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_checkout_upstream_error_returns_502(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            response = await client.post(
                "/payment/checkout",
                json={"amount": 50000, "currency": "ETB", "provider": "chapa"},
            )

        assert response.status_code == 502


class TestVerifyPayment:
    @pytest.mark.asyncio
    async def test_verify_success(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"status": "success"}}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            response = await client.get("/payment/verify/testref123?provider=chapa")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["reference"] == "testref123"

    @pytest.mark.asyncio
    async def test_verify_failed_payment(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"status": "failed"}}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            response = await client.get("/payment/verify/failedref?provider=chapa")

        assert response.status_code == 200
        assert response.json()["success"] is False

    @pytest.mark.asyncio
    async def test_health_endpoint(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["service"] == "payment_provider"
