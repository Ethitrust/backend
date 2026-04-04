"""gRPC boundary tests for payout -> payment-provider transfer calls."""

from __future__ import annotations

from typing import Any

import pytest
from app import grpc_clients


@pytest.fixture(autouse=True)
def mock_grpc():
    """Override autouse fixture from conftest for this boundary test module."""
    yield


@pytest.fixture(autouse=True)
def mock_rabbitmq():
    """Override autouse fixture from conftest for this boundary test module."""
    yield


class _FakeChannel:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


@pytest.mark.asyncio
async def test_chapa_transfer_uses_grpc_initiate_and_verify(monkeypatch):
    captured: dict[str, Any] = {}

    def _fake_insecure_channel(target: str):
        captured["target"] = target
        return _FakeChannel()

    class _Stub:
        def __init__(self, channel: object) -> None:
            self.channel = channel

        async def InitiateTransfer(self, request, timeout: float):  # noqa: N802
            captured["init_request"] = request
            captured["init_timeout"] = timeout
            return grpc_clients.payment_provider_pb2.TransferResponse(
                success=True,
                provider_ref="TRF-123",
                message="Transfer initiated",
                status="success",
            )

        async def VerifyTransfer(self, request, timeout: float):  # noqa: N802
            captured["verify_request"] = request
            captured["verify_timeout"] = timeout
            return grpc_clients.payment_provider_pb2.TransferVerifyResponse(
                success=True,
                status="success",
            )

    monkeypatch.setattr(
        grpc_clients.grpc.aio, "insecure_channel", _fake_insecure_channel
    )
    monkeypatch.setattr(
        grpc_clients.payment_provider_pb2_grpc,
        "PaymentProviderServiceStub",
        _Stub,
    )

    result = await grpc_clients.initiate_bank_transfer(
        bank_code="44",
        account_number="0123456789",
        amount=10000,
        currency="ETB",
        reference="payout-ref-1",
        provider="chapa",
        account_name="Test User",
    )

    assert captured["target"] == grpc_clients.PAYMENT_PROVIDER_GRPC
    assert captured["init_timeout"] == 15.0
    assert captured["verify_timeout"] == 15.0
    assert captured["init_request"].account_name == "Test User"
    assert captured["init_request"].bank_code == 44
    assert captured["verify_request"].provider_ref == "TRF-123"
    assert result == {"provider_ref": "TRF-123", "status": "success"}


@pytest.mark.asyncio
async def test_chapa_transfer_raises_when_initiate_transfer_fails(monkeypatch):
    def _fake_insecure_channel(target: str):
        return _FakeChannel()

    class _Stub:
        def __init__(self, channel: object) -> None:
            self.channel = channel

        async def InitiateTransfer(self, request, timeout: float):  # noqa: N802
            return grpc_clients.payment_provider_pb2.TransferResponse(
                success=False,
                provider_ref="",
                message="upstream failed",
                status="failed",
            )

        async def VerifyTransfer(self, request, timeout: float):  # noqa: N802
            return grpc_clients.payment_provider_pb2.TransferVerifyResponse(
                success=False,
                status="failed",
            )

    monkeypatch.setattr(
        grpc_clients.grpc.aio, "insecure_channel", _fake_insecure_channel
    )
    monkeypatch.setattr(
        grpc_clients.payment_provider_pb2_grpc,
        "PaymentProviderServiceStub",
        _Stub,
    )

    with pytest.raises(RuntimeError, match="upstream failed"):
        await grpc_clients.initiate_bank_transfer(
            bank_code="44",
            account_number="0123456789",
            amount=10000,
            currency="ETB",
            reference="payout-ref-2",
            provider="chapa",
            account_name="Test User",
        )


@pytest.mark.asyncio
async def test_chapa_transfer_raises_when_verify_transfer_fails(monkeypatch):
    def _fake_insecure_channel(target: str):
        return _FakeChannel()

    class _Stub:
        def __init__(self, channel: object) -> None:
            self.channel = channel

        async def InitiateTransfer(self, request, timeout: float):  # noqa: N802
            return grpc_clients.payment_provider_pb2.TransferResponse(
                success=True,
                provider_ref="TRF-999",
                message="Transfer initiated",
                status="processing",
            )

        async def VerifyTransfer(self, request, timeout: float):  # noqa: N802
            return grpc_clients.payment_provider_pb2.TransferVerifyResponse(
                success=False,
                status="failed",
            )

    monkeypatch.setattr(
        grpc_clients.grpc.aio, "insecure_channel", _fake_insecure_channel
    )
    monkeypatch.setattr(
        grpc_clients.payment_provider_pb2_grpc,
        "PaymentProviderServiceStub",
        _Stub,
    )

    with pytest.raises(RuntimeError, match="Transfer verification failed"):
        await grpc_clients.initiate_bank_transfer(
            bank_code="44",
            account_number="0123456789",
            amount=10000,
            currency="ETB",
            reference="payout-ref-3",
            provider="chapa",
            account_name="Test User",
        )
