"""Proto contract regression tests for admin-auth integration."""

from __future__ import annotations

import pytest
from app.grpc_clients import auth_pb2, auth_pb2_grpc, validate_token


def test_token_response_contains_repeated_scopes_field() -> None:
    scopes_field = auth_pb2.TokenResponse.DESCRIPTOR.fields_by_name["scopes"]

    assert scopes_field.number == 4
    assert scopes_field.label == scopes_field.LABEL_REPEATED
    assert scopes_field.type == scopes_field.TYPE_STRING


@pytest.mark.asyncio
async def test_validate_token_returns_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DummyChannel:
        async def __aenter__(self):  # noqa: ANN204
            return object()

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN204
            return False

    class _DummyStub:
        def __init__(self, channel: object) -> None:
            self.channel = channel

        async def ValidateToken(  # noqa: N802
            self,
            request: auth_pb2.TokenRequest,
            timeout: float,
        ) -> auth_pb2.TokenResponse:
            assert request.token == "token-123"
            assert timeout == 5.0
            return auth_pb2.TokenResponse(
                valid=True,
                user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                role="admin",
                scopes=["users.read", "reports.read"],
            )

    monkeypatch.setattr(
        "app.grpc_clients.grpc.aio.insecure_channel",
        lambda _target: _DummyChannel(),
    )
    monkeypatch.setattr(
        auth_pb2_grpc,
        "AuthValidatorStub",
        _DummyStub,
    )

    result = await validate_token("token-123")

    assert result["user_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert result["role"] == "admin"
    assert result["scopes"] == ["users.read", "reports.read"]
