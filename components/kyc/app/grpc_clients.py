"""gRPC clients used by the KYC service."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import grpc
import grpc.aio

_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

USER_GRPC = os.getenv("USER_GRPC", "user-service:50051")
AUTH_GRPC = os.getenv("AUTH_GRPC", "auth-service:50051")
STORAGE_GRPC = os.getenv("STORAGE_GRPC", "storage-service:50051")

_PROTO_DIR = _APP_DIR.parent / "proto"
if str(_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTO_DIR))

proto_module = sys.modules.setdefault("proto", type(sys)("proto"))
proto_paths = list(getattr(proto_module, "__path__", []))
if str(_PROTO_DIR) not in proto_paths:
    proto_module.__path__ = [*proto_paths, str(_PROTO_DIR)]

import proto.auth_pb2 as auth_pb2
import proto.auth_pb2_grpc as auth_pb2_grpc
import proto.storage_pb2 as storage_pb2
import proto.storage_pb2_grpc as storage_pb2_grpc
import proto.user_pb2 as user_pb2
import proto.user_pb2_grpc as user_pb2_grpc

logger = logging.getLogger(__name__)


async def validate_token(token: str) -> dict:
    """Validate caller token with Auth service."""
    try:
        async with grpc.aio.insecure_channel(AUTH_GRPC) as channel:
            stub = auth_pb2_grpc.AuthValidatorStub(channel)
            response = await stub.ValidateToken(
                auth_pb2.TokenRequest(token=token), timeout=5.0
            )
    except grpc.aio.AioRpcError as exc:
        if exc.code() == grpc.StatusCode.UNAVAILABLE:
            logger.error("Auth gRPC unavailable at %s: %s", AUTH_GRPC, exc)
            raise ConnectionError("Auth service unavailable") from exc

        logger.warning("Token validation RPC failed: %s", exc)
        raise PermissionError("Invalid token") from exc

    if not response.valid:
        raise PermissionError("Invalid token")

    return {
        "user_id": response.user_id,
        "role": response.role or "user",
    }


async def set_kyc_level(user_id: str, level: int) -> None:
    """Update user KYC level synchronously in User service."""
    request = user_pb2.SetKycLevelRequest(user_id=user_id, level=level)

    try:
        async with grpc.aio.insecure_channel(USER_GRPC) as channel:
            stub = user_pb2_grpc.UserServiceStub(channel)
            response = await stub.SetKycLevel(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(f"User service KYC update failed: {exc.details()}") from exc

    if not response.success:
        raise RuntimeError(response.message or "Failed to update KYC level")


async def generate_storage_upload_url(
    *,
    actor_user_id: str,
    role: str,
    purpose: str,
    object_key: str,
    content_type: str,
    expires_in_seconds: int = 900,
) -> dict:
    request = storage_pb2.PresignUploadRequest(
        actor_user_id=actor_user_id,
        role=role,
        purpose=purpose,
        object_key=object_key,
        content_type=content_type,
        expires_in_seconds=expires_in_seconds,
    )

    try:
        async with grpc.aio.insecure_channel(STORAGE_GRPC) as channel:
            stub = storage_pb2_grpc.StorageServiceStub(channel)
            response = await stub.GeneratePresignedUploadUrl(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        if exc.code() == grpc.StatusCode.INVALID_ARGUMENT:
            raise ValueError(exc.details()) from exc
        raise RuntimeError(f"Storage upload presign failed: {exc.details()}") from exc

    if not response.success:
        raise RuntimeError(response.message or "Storage upload presign failed")

    return {
        "url": response.url,
        "method": response.method,
        "object_key": response.object_key,
        "expires_in_seconds": response.expires_in_seconds,
    }


async def generate_storage_download_url(
    *,
    actor_user_id: str,
    role: str,
    purpose: str,
    object_key: str,
    expires_in_seconds: int = 900,
) -> dict:
    request = storage_pb2.PresignDownloadRequest(
        actor_user_id=actor_user_id,
        role=role,
        purpose=purpose,
        object_key=object_key,
        expires_in_seconds=expires_in_seconds,
    )

    try:
        async with grpc.aio.insecure_channel(STORAGE_GRPC) as channel:
            stub = storage_pb2_grpc.StorageServiceStub(channel)
            response = await stub.GeneratePresignedDownloadUrl(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        if exc.code() == grpc.StatusCode.INVALID_ARGUMENT:
            raise ValueError(exc.details()) from exc
        raise RuntimeError(f"Storage download presign failed: {exc.details()}") from exc

    if not response.success:
        raise RuntimeError(response.message or "Storage download presign failed")

    return {
        "url": response.url,
        "method": response.method,
        "object_key": response.object_key,
        "expires_in_seconds": response.expires_in_seconds,
    }
