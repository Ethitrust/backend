"""gRPC client stubs for the Organization service."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import grpc
import grpc.aio

_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

_PROTO_DIR = _APP_DIR.parent / "proto"
if str(_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTO_DIR))

_WALLET_PROTO_DIR = _APP_DIR.parent.parent / "wallet" / "proto"
if str(_WALLET_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_WALLET_PROTO_DIR))

proto_module = sys.modules.setdefault("proto", type(sys)("proto"))
proto_paths = list(getattr(proto_module, "__path__", []))
if str(_PROTO_DIR) not in proto_paths:
    proto_module.__path__ = [*proto_paths, str(_PROTO_DIR)]
wallet_proto_paths = list(getattr(proto_module, "__path__", []))
if str(_WALLET_PROTO_DIR) not in wallet_proto_paths:
    proto_module.__path__ = [*wallet_proto_paths, str(_WALLET_PROTO_DIR)]

import proto.auth_pb2 as auth_pb2
import proto.auth_pb2_grpc as auth_pb2_grpc
import proto.wallet_pb2 as wallet_pb2
import proto.wallet_pb2_grpc as wallet_pb2_grpc

AUTH_GRPC = os.getenv("AUTH_GRPC", "auth-service:50051")
WALLET_GRPC = os.getenv("WALLET_GRPC", "wallet-service:50051")


async def validate_token(token: str) -> dict:
    try:
        async with grpc.aio.insecure_channel(AUTH_GRPC) as channel:
            stub = auth_pb2_grpc.AuthValidatorStub(channel)
            response = await stub.ValidateToken(auth_pb2.TokenRequest(token=token), timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise PermissionError("Invalid token") from exc

    if not response.valid:
        raise PermissionError("Invalid token")

    return {
        "user_id": response.user_id,
        "role": response.role or "user",
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


async def ensure_owner_wallet(owner_id: str, currency: str = "ETB") -> str:

    request = wallet_pb2.OwnerWalletRequest(owner_id=owner_id, currency=currency)
    try:
        async with grpc.aio.insecure_channel(WALLET_GRPC) as channel:
            stub = wallet_pb2_grpc.WalletServiceStub(channel)
            response = await stub.GetWalletByOwner(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to provision organization wallet") from exc

    if not response.found or not response.wallet_id:
        raise RuntimeError("Unable to provision organization wallet")

    return response.wallet_id


async def get_wallet_balance(wallet_id: str) -> dict:
    request = wallet_pb2.BalanceRequest(wallet_id=wallet_id)
    try:
        async with grpc.aio.insecure_channel(WALLET_GRPC) as channel:
            stub = wallet_pb2_grpc.WalletServiceStub(channel)
            response = await stub.GetBalance(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        details = exc.details() or "Unable to fetch wallet balance"
        raise RuntimeError(details) from exc

    return {
        "balance": int(response.balance),
        "locked_balance": int(response.locked_balance),
        "currency": response.currency,
    }


async def deduct_wallet_balance(
    wallet_id: uuid.UUID,
    amount: int,
    reference: str,
    provider: str,
) -> dict:
    request = wallet_pb2.DeductRequest(
        wallet_id=str(wallet_id),
        amount=amount,
        reference=reference,
        provider=provider,
    )
    try:
        async with grpc.aio.insecure_channel(WALLET_GRPC) as channel:
            stub = wallet_pb2_grpc.WalletServiceStub(channel)
            response = await stub.DeductBalance(request, timeout=8.0)
    except grpc.aio.AioRpcError as exc:
        details = exc.details() or "Wallet deduction failed"
        raise RuntimeError(details) from exc

    return {
        "success": response.success,
        "new_balance": int(response.new_balance),
        "message": response.message,
    }
