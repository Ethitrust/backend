"""gRPC clients used by the Auth service."""

from __future__ import annotations

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

USER_GRPC = os.getenv("USER_GRPC", "user-service:50051")


async def sync_user(
    *,
    user_id: str,
    email: str,
    password_hash: str,
    first_name: str | None,
    last_name: str | None,
    role: str,
    is_verified: bool,
    is_banned: bool,
    kyc_level: int,
    otp: str,
) -> None:
    """Synchronize a user projection into the User service synchronously."""
    import proto.user_pb2 as user_pb2
    import proto.user_pb2_grpc as user_pb2_grpc

    request = user_pb2.SyncUserRequest(
        user_id=user_id,
        email=email,
        password_hash=password_hash,
        first_name=first_name or "",
        last_name=last_name or "",
        role=role,
        is_verified=is_verified,
        is_banned=is_banned,
        kyc_level=kyc_level,
        otp=otp,
    )

    try:
        async with grpc.aio.insecure_channel(USER_GRPC) as channel:
            stub = user_pb2_grpc.UserServiceStub(channel)
            response = await stub.SyncUser(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(f"User service sync failed: {exc.details()}") from exc

    if not response.success:
        raise RuntimeError(response.message or "User service sync failed")


async def update_email_verification_status(user_id: str, is_verified: bool) -> None:
    import proto.user_pb2 as user_pb2
    import proto.user_pb2_grpc as user_pb2_grpc

    request = user_pb2.UpdateVerificationRequest(
        user_id=user_id, is_verified=is_verified
    )

    try:
        async with grpc.aio.insecure_channel(USER_GRPC) as channel:
            stub = user_pb2_grpc.UserServiceStub(channel)
            if not hasattr(stub, "UpdateVerification"):
                raise RuntimeError(
                    "UserService.UpdateVerification RPC is unavailable in generated stubs. "
                    "Regenerate protobuf files from proto/user.proto."
                )
            response = await stub.UpdateVerification(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(f"User service sync failed: {exc.details()}") from exc

    if not response.success:
        raise RuntimeError(response.message or "User service sync failed")


async def update_user_role(user_id: str, role: str) -> None:
    import proto.user_pb2 as user_pb2
    import proto.user_pb2_grpc as user_pb2_grpc

    request = user_pb2.UpdateRoleRequest(user_id=user_id, role=role)

    try:
        async with grpc.aio.insecure_channel(USER_GRPC) as channel:
            stub = user_pb2_grpc.UserServiceStub(channel)
            if not hasattr(stub, "UpdateRole"):
                raise RuntimeError(
                    "UserService.UpdateRole RPC is unavailable in generated stubs. "
                    "Regenerate protobuf files from proto/user.proto."
                )
            response = await stub.UpdateRole(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(f"User service sync failed: {exc.details()}") from exc

    if not response.success:
        raise RuntimeError(response.message or "User service sync failed")


async def associate_escrow_with_user(user_id: str, escrow_id: str) -> None:
    """Associate a user with an escrow in the User service."""
    import proto.escrow_pb2 as escrow_pb2
    import proto.escrow_pb2_grpc as escrow_pb2_grpc

    request = escrow_pb2.EscrowAssociationRequest(
        escrow_id=escrow_id,
        user_id=user_id,
    )

    try:
        async with grpc.aio.insecure_channel(USER_GRPC) as channel:
            stub = escrow_pb2_grpc.EscrowServiceStub(channel)
            if not hasattr(stub, "AssociateUserWithEscrow"):
                raise RuntimeError(
                    "EscrowService.AssociateUserWithEscrow RPC is unavailable in generated stubs. "
                    "Regenerate protobuf files from proto/escrow.proto."
                )
            response = await stub.AssociateUserWithEscrow(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(f"User service sync failed: {exc.details()}") from exc

    if not response.success:
        raise RuntimeError(response.message or "User service sync failed")


async def update_email_verifiication_status(user_id: str, is_verified: bool) -> None:
    """Backward-compatible alias for a historical misspelling."""
    await update_email_verification_status(user_id=user_id, is_verified=is_verified)
