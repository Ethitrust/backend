"""Proto contract regression tests for auth token validation responses."""

from __future__ import annotations

from app.grpc_server import auth_pb2


def test_token_response_scopes_field_shape() -> None:
    scopes_field = auth_pb2.TokenResponse.DESCRIPTOR.fields_by_name["scopes"]

    assert scopes_field.number == 4
    assert scopes_field.label == scopes_field.LABEL_REPEATED
    assert scopes_field.type == scopes_field.TYPE_STRING


def test_token_response_scopes_round_trip_serialization() -> None:
    original = auth_pb2.TokenResponse(
        valid=True,
        user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        role="admin",
        scopes=["users.read", "analytics.growth.read"],
    )

    encoded = original.SerializeToString()
    parsed = auth_pb2.TokenResponse()
    parsed.ParseFromString(encoded)

    assert parsed.valid is True
    assert parsed.user_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert parsed.role == "admin"
    assert list(parsed.scopes) == ["users.read", "analytics.growth.read"]
