"""gRPC client stubs for the Dispute service."""

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

proto_module = sys.modules.setdefault("proto", type(sys)("proto"))
proto_paths = list(getattr(proto_module, "__path__", []))
if str(_PROTO_DIR) not in proto_paths:
    proto_module.__path__ = [*proto_paths, str(_PROTO_DIR)]

import proto.auth_pb2 as auth_pb2
import proto.auth_pb2_grpc as auth_pb2_grpc
import proto.escrow_pb2 as escrow_pb2
import proto.escrow_pb2_grpc as escrow_pb2_grpc

AUTH_GRPC = os.getenv("AUTH_GRPC", "auth-service:50051")
ESCROW_GRPC = os.getenv("ESCROW_GRPC", "escrow-service:50051")
WALLET_GRPC = os.getenv("WALLET_GRPC", "wallet-service:50051")


async def validate_token(token: str) -> dict:
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


async def get_escrow(escrow_id: uuid.UUID) -> dict:
    """Fetch escrow metadata from Escrow service."""
    request = escrow_pb2.EscrowRequest(escrow_id=str(escrow_id))
    try:
        async with grpc.aio.insecure_channel(ESCROW_GRPC) as channel:
            stub = escrow_pb2_grpc.EscrowServiceStub(channel)
            response = await stub.GetEscrow(request, timeout=8.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(exc.details() or "Failed to fetch escrow") from exc

    return {
        "id": response.escrow_id,
        "status": response.status,
        "escrow_type": response.escrow_type,
        "initiator_id": response.initiator_id,
        "receiver_id": response.receiver_id,
        "amount": response.amount,
        "currency": response.currency,
    }


async def transition_escrow_status(escrow_id: uuid.UUID, new_status: str) -> dict:
    """Call Escrow service to change escrow status."""
    request = escrow_pb2.TransitionRequest(
        escrow_id=str(escrow_id),
        new_status=new_status,
        actor_id="dispute-service",
    )
    try:
        async with grpc.aio.insecure_channel(ESCROW_GRPC) as channel:
            stub = escrow_pb2_grpc.EscrowServiceStub(channel)
            response = await stub.TransitionStatus(request, timeout=8.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(exc.details() or "Failed to transition escrow") from exc

    return {
        "id": response.escrow_id,
        "status": response.status,
        "success": response.success,
        "message": response.message,
    }


async def release_funds(escrow_id: uuid.UUID, resolution: str) -> dict:
    """Call Wallet service to release or refund escrow funds."""
    # TODO: real gRPC call
    return {"success": True, "resolution": resolution}
