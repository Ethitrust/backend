"""
gRPC clients used by the Wallet service.

- validate_token: calls Auth service to decode JWT (falls back to local
  decode while proto stubs are not compiled).
- create_checkout: calls Payment Provider service to initialise a payment
  session (stub returns a fake checkout URL until gRPC stubs are ready).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import grpc
import grpc.aio

_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

_PROTO_DIR = _APP_DIR.parent / "proto"
if str(_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTO_DIR))

proto_module = sys.modules.setdefault("proto", type(sys)("proto"))
proto_paths = list(getattr(proto_module, "__path__", []))
if str(_PROTO_DIR) not in proto_paths:
    proto_module.__path__ = [*proto_paths, str(_PROTO_DIR)]

import proto.auth_pb2 as auth_pb2
import proto.auth_pb2_grpc as auth_pb2_grpc
import proto.payment_provider_pb2 as payment_provider_pb2
import proto.payment_provider_pb2_grpc as payment_provider_pb2_grpc

AUTH_GRPC = os.getenv("AUTH_GRPC", "auth-service:50051")
PAYMENT_GRPC = os.getenv("PAYMENT_GRPC", "payment-provider-service:50051")


async def validate_token(token: str) -> dict:
    """Validate a Bearer JWT and return user metadata.

    Returns:
        dict with keys: user_id, role, is_verified, is_banned.

    Raises:
        PermissionError: when the token is invalid or expired.
    """
    try:
        async with grpc.aio.insecure_channel(AUTH_GRPC) as channel:
            stub = auth_pb2_grpc.AuthValidatorStub(channel)
            response = await stub.ValidateToken(
                auth_pb2.TokenRequest(token=token), timeout=5.0
            )
    except grpc.aio.AioRpcError as exc:
        raise PermissionError("Invalid token") from exc

    if not response.valid:
        raise PermissionError("Invalid token")

    return {
        "user_id": response.user_id,
        "role": response.role or "user",
        "is_verified": True,
        "is_banned": False,
    }


async def get_user_by_id(user_id: str) -> dict:
    request = auth_pb2.UserRequest(user_id=user_id)

    try:
        async with grpc.aio.insecure_channel(AUTH_GRPC) as channel:
            stub = auth_pb2_grpc.AuthValidatorStub(channel)
            response = await stub.GetUserById(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to fetch user profile") from exc

    return {
        "user_id": response.user_id,
        "email": response.email,
        "role": response.role or "user",
        "is_verified": response.is_verified,
        "is_banned": response.is_banned,
        "kyc_level": int(response.kyc_level),
    }


async def create_checkout(
    amount: int,
    currency: str,
    metadata: dict,
    return_url: str,
    provider: str = "chapa",
) -> dict:
    """Call Payment Provider to create a checkout session.

    Calls payment-provider over gRPC to create a checkout session.
    """
    request = payment_provider_pb2.CheckoutRequest(
        amount=amount,
        currency=currency,
        metadata_json=json.dumps(metadata),
        provider=provider,
        return_url=return_url,
    )

    try:
        async with grpc.aio.insecure_channel(PAYMENT_GRPC) as channel:
            stub = payment_provider_pb2_grpc.PaymentProviderServiceStub(channel)
            response = await stub.CreateCheckout(request, timeout=10.0)
    except grpc.aio.AioRpcError as exc:
        details = exc.details() or "Payment provider checkout failed"
        raise RuntimeError(details) from exc

    return {
        "payment_url": response.payment_url,
        "transaction_ref": response.transaction_ref,
        "provider": response.provider or provider,
    }


async def verify_payment(reference: str, provider: str = "chapa") -> bool:
    """Call Payment Provider to verify if a payment reference is settled."""
    request = payment_provider_pb2.VerifyRequest(
        reference=reference,
        provider=provider,
    )

    try:
        async with grpc.aio.insecure_channel(PAYMENT_GRPC) as channel:
            stub = payment_provider_pb2_grpc.PaymentProviderServiceStub(channel)
            response = await stub.VerifyPayment(request, timeout=10.0)
    except grpc.aio.AioRpcError as exc:
        details = exc.details() or "Payment provider verification failed"
        raise RuntimeError(details) from exc

    return bool(response.success)
