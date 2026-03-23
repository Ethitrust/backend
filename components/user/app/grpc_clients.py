"""
gRPC clients used by the User service.

Since proto-generated stubs are not yet compiled, this module falls back to a
local JWT decode for the validate_token helper so that the service remains
testable without a running Auth service.  In production, replace the body of
`validate_token` with a proper gRPC stub call.
"""

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

_PROTO_DIR = _APP_DIR.parent / "proto"
if str(_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTO_DIR))

proto_module = sys.modules.setdefault("proto", type(sys)("proto"))
proto_paths = list(getattr(proto_module, "__path__", []))
if str(_PROTO_DIR) not in proto_paths:
    proto_module.__path__ = [*proto_paths, str(_PROTO_DIR)]

import proto.auth_pb2 as auth_pb2  # noqa: E402
import proto.auth_pb2_grpc as auth_pb2_grpc  # noqa: E402

# Investigate why it's not used
AUTH_GRPC = os.getenv("AUTH_GRPC", "auth-service:50051")
logger = logging.getLogger(__name__)


async def validate_token(token: str) -> dict:
    """Validate a Bearer token and return user metadata.

    Returns a dict with keys: user_id, role, is_verified, is_banned.

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
        if exc.code() == grpc.StatusCode.UNAVAILABLE:
            logger.error("Auth gRPC unavailable at %s: %s", AUTH_GRPC, exc)
            raise ConnectionError("Auth service unavailable") from exc

        logger.warning("Token validation RPC failed: %s", exc)
        raise PermissionError("Invalid token") from exc

    if not response.valid:
        logger.info("Token validation failed: %s", response)
        raise PermissionError("Invalid token")

    # here hardcode is_verified and is_banned since the Auth service doesn't manage those states yet
    # but it should not be like that in production - either include those states in the token or fetch from User service
    # TODO: decide on a strategy for managing is_verified and is_banned states across services - include in token vs fetch from User service
    return {
        "user_id": response.user_id,
        "role": response.role or "user",
        "is_verified": True,
        "is_banned": False,
    }
