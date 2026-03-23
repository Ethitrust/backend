"""
gRPC server for the User service.

Exposes:
  - GetUser(UserRequest) → UserResponse
  - SetKycLevel(SetKycLevelRequest) → StatusResponse
  - UpdateRole(UpdateRoleRequest) → StatusResponse
  - BanUser(BanUserRequest) → StatusResponse
  - ListUsers(ListUsersRequest) → ListUsersResponse

Run `bash scripts/generate_protos.sh` from repo root before starting.
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
from sqlalchemy import select

from app.db import AsyncSessionLocal, User
from app.messaging import publish

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

import proto.user_pb2 as user_pb2
import proto.user_pb2_grpc as user_pb2_grpc

logger = logging.getLogger(__name__)
GRPC_PORT = int(os.getenv("GRPC_PORT", "50051"))


def _user_to_proto(user: User) -> user_pb2.UserResponse:
    return user_pb2.UserResponse(
        user_id=str(user.id),
        email=user.email,
        role=user.role,
        is_verified=user.is_verified,
        is_banned=user.is_banned,
        kyc_level=getattr(user, "kyc_level", 0),
        full_name=getattr(user, "full_name", "") or "",
    )


class UserServicer(user_pb2_grpc.UserServiceServicer):
    async def SyncUser(
        self, request: user_pb2.SyncUserRequest, context: grpc.aio.ServicerContext
    ) -> user_pb2.StatusResponse:  # noqa: N802
        try:
            user_id = uuid.UUID(request.user_id)
        except (ValueError, AttributeError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid user_id")

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

            if user is None:
                user = User(
                    id=user_id,
                    email=request.email,
                    password_hash=request.password_hash,
                    first_name=request.first_name or None,
                    last_name=request.last_name or None,
                    role=request.role or "user",
                    is_verified=request.is_verified,
                    is_banned=request.is_banned,
                    kyc_level=request.kyc_level,
                )
                session.add(user)
            else:
                user.email = request.email
                user.password_hash = request.password_hash
                user.first_name = request.first_name or None
                user.last_name = request.last_name or None
                user.role = request.role or user.role
                user.is_verified = request.is_verified
                user.is_banned = request.is_banned
                user.kyc_level = request.kyc_level
                session.add(user)

            await session.commit()

        # Q: is this really necessary since we're using grpc what is the point of publishing it using rabbitmq
        await publish(
            routing_key="user.registered",
            payload={
                "user_id": str(user_id),
                "email": request.email,
                "first_name": request.first_name,
                "last_name": request.last_name,
                "role": request.role,
                "is_verified": request.is_verified,
                "is_banned": request.is_banned,
                "kyc_level": request.kyc_level,
                "otp": request.otp,
            },
        )

        return user_pb2.StatusResponse(success=True, message="User synchronized")

    async def GetUser(
        self, request: user_pb2.UserRequest, context: grpc.aio.ServicerContext
    ) -> user_pb2.UserResponse:  # noqa: N802
        try:
            user_id = uuid.UUID(request.user_id)
        except (ValueError, AttributeError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid user_id")

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()

        if not user:
            await context.abort(grpc.StatusCode.NOT_FOUND, "User not found")

        return _user_to_proto(user)

    async def SetKycLevel(
        self, request: user_pb2.SetKycLevelRequest, context: grpc.aio.ServicerContext
    ) -> user_pb2.StatusResponse:  # noqa: N802
        try:
            user_id = uuid.UUID(request.user_id)
        except (ValueError, AttributeError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid user_id")

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                await context.abort(grpc.StatusCode.NOT_FOUND, "User not found")
            user.kyc_level = request.level
            await session.commit()

        return user_pb2.StatusResponse(
            success=True, message=f"KYC level set to {request.level}"
        )

    async def UpdateRole(
        self, request: user_pb2.UpdateRoleRequest, context: grpc.aio.ServicerContext
    ) -> user_pb2.StatusResponse:  # noqa: N802
        if request.role not in ("admin", "moderator", "user"):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid role")

        try:
            user_id = uuid.UUID(request.user_id)
        except (ValueError, AttributeError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid user_id")

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                await context.abort(grpc.StatusCode.NOT_FOUND, "User not found")
            user.role = request.role
            await session.commit()

        return user_pb2.StatusResponse(
            success=True, message=f"Role updated to {request.role}"
        )

    async def BanUser(
        self, request: user_pb2.BanUserRequest, context: grpc.aio.ServicerContext
    ) -> user_pb2.StatusResponse:  # noqa: N802
        try:
            user_id = uuid.UUID(request.user_id)
        except (ValueError, AttributeError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid user_id")

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                await context.abort(grpc.StatusCode.NOT_FOUND, "User not found")
            user.is_banned = request.ban
            await session.commit()

        action = "banned" if request.ban else "unbanned"
        return user_pb2.StatusResponse(success=True, message=f"User {action}")

    async def ListUsers(
        self, request: user_pb2.ListUsersRequest, context: grpc.aio.ServicerContext
    ) -> user_pb2.ListUsersResponse:  # noqa: N802
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).offset(request.offset).limit(request.limit or 50)
            )
            users = list(result.scalars().all())
            from sqlalchemy import func
            from sqlalchemy import select as sa_select

            count_result = await session.execute(sa_select(func.count(User.id)))
            total = count_result.scalar_one()

        return user_pb2.ListUsersResponse(
            users=[_user_to_proto(u) for u in users],
            total=total,
        )

    async def UpdateVerification(
        self,
        request: user_pb2.UpdateVerificationRequest,
        context: grpc.aio.ServicerContext,
    ) -> user_pb2.StatusResponse:  # noqa: N802
        try:
            user_id = uuid.UUID(request.user_id)
        except (ValueError, AttributeError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid user_id")

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                await context.abort(grpc.StatusCode.NOT_FOUND, "User not found")
            user.is_verified = request.is_verified
            await session.commit()

        action = "verified" if request.is_verified else "unverified"
        return user_pb2.StatusResponse(success=True, message=f"User {action}")

    async def SyncEmailVerification(
        self,
        request: user_pb2.UpdateVerificationRequest,
        context: grpc.aio.ServicerContext,
    ) -> user_pb2.StatusResponse:  # noqa: N802
        """Backward-compatible alias for old method naming."""
        return await self.UpdateVerification(request, context)

    async def GetUserByEmail(
        self,
        request: user_pb2.GetUserByEmailRequest,
        context: grpc.aio.ServicerContext,
    ) -> user_pb2.UserResponse:  # noqa: N802
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.email == request.email)
            )
            user = result.scalar_one_or_none()

        if not user:
            await context.abort(grpc.StatusCode.NOT_FOUND, "User not found")

        return _user_to_proto(user)


async def serve() -> None:
    server = grpc.aio.server()
    user_pb2_grpc.add_UserServiceServicer_to_server(UserServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    logger.info("User gRPC server starting on port %s", GRPC_PORT)
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop(grace=5)
        logger.info("User gRPC server stopped")
