"""
gRPC server for the Auth service.

Exposes:
  - ValidateToken(TokenRequest) → TokenResponse
  - GetUserById(UserRequest) → UserResponse

Run `bash scripts/generate_protos.sh` from repo root before starting this service.
The Dockerfile runs it automatically during build.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

import grpc
import grpc.aio
from jose import JWTError
from sqlalchemy import select

_APP_DIR = Path(__file__).resolve().parent
_PROTO_DIR = _APP_DIR.parent / "proto"
if str(_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTO_DIR))

proto_module = sys.modules.setdefault("proto", type(sys)("proto"))
proto_paths = list(getattr(proto_module, "__path__", []))
if str(_PROTO_DIR) not in proto_paths:
    proto_module.__path__ = [*proto_paths, str(_PROTO_DIR)]

import proto.auth_pb2 as auth_pb2
import proto.auth_pb2_grpc as auth_pb2_grpc

from app.db import AsyncSessionLocal, User
from app.redis_client import is_token_blacklisted
from app.security import decode_token

logger = logging.getLogger(__name__)
GRPC_PORT = int(os.getenv("GRPC_PORT", "50051"))


def _extract_scopes(payload: dict[str, object]) -> list[str]:
    raw_scopes = payload.get("scopes")
    if raw_scopes is None:
        return []

    if isinstance(raw_scopes, str):
        return [
            scope.strip()
            for scope in raw_scopes.replace(",", " ").split()
            if scope.strip()
        ]

    if isinstance(raw_scopes, (list, tuple, set)):
        return [scope for scope in (str(item).strip() for item in raw_scopes) if scope]

    return []


class AuthValidatorServicer(auth_pb2_grpc.AuthValidatorServicer):
    """Implements the AuthValidator gRPC service."""

    async def ValidateToken(
        self, request: auth_pb2.TokenRequest, context: grpc.aio.ServicerContext
    ) -> auth_pb2.TokenResponse:  # noqa: N802
        if not request.token:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Token is required")

        logger.debug("Received token validation request")

        try:
            payload = decode_token(request.token)

            jti = payload.get("jti")
            if not isinstance(jti, str) or not jti:
                await context.abort(
                    grpc.StatusCode.UNAUTHENTICATED, "Token missing jti"
                )

            if await is_token_blacklisted(jti):
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, "Token revoked")
        except JWTError as exc:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, str(exc))

        user_id = payload.get("sub")
        if not isinstance(user_id, str) or not user_id:
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED, "Invalid token subject"
            )

        role = payload.get("role")
        role_value = role if isinstance(role, str) and role else "user"
        scopes = _extract_scopes(payload)

        return auth_pb2.TokenResponse(
            valid=True,
            user_id=user_id,
            role=role_value,
            scopes=scopes,
        )

    async def GetUserById(
        self, request: auth_pb2.UserRequest, context: grpc.aio.ServicerContext
    ) -> auth_pb2.UserResponse:  # noqa: N802
        try:
            user_id = uuid.UUID(request.user_id)
        except (ValueError, AttributeError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid user_id")

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

        if not user:
            await context.abort(grpc.StatusCode.NOT_FOUND, "User not found")

        return auth_pb2.UserResponse(
            user_id=str(user.id),
            email=user.email,
            role=user.role,
            is_verified=user.is_verified,
            is_banned=user.is_banned,
            kyc_level=getattr(user, "kyc_level", 0),
        )

    async def CheckEmailExists(
        self, request: auth_pb2.EmailRequest, context: grpc.aio.ServicerContext
    ) -> auth_pb2.EmailExistsResponse:  # noqa: N802
        email = (request.email or "").strip().lower()
        if not email:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Email is required")

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()

        if not user:
            return auth_pb2.EmailExistsResponse(exists=False, user_id="")

        return auth_pb2.EmailExistsResponse(exists=True, user_id=str(user.id))


async def serve() -> None:
    server = grpc.aio.server()
    auth_pb2_grpc.add_AuthValidatorServicer_to_server(AuthValidatorServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    logger.info("Auth gRPC server starting on port %s", GRPC_PORT)
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop(grace=5)
        logger.info("Auth gRPC server stopped")
