"""gRPC server for the Admin service."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import grpc
import grpc.aio
from fastapi import HTTPException

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

import proto.admin_pb2 as admin_pb2
import proto.admin_pb2_grpc as admin_pb2_grpc

from app.db import AsyncSessionLocal
from app.repository import AdminRepository
from app.service import AdminService

logger = logging.getLogger(__name__)
GRPC_PORT = int(os.getenv("GRPC_PORT", "50051"))


def _http_to_grpc_code(status_code: int) -> grpc.StatusCode:
    if status_code == 400:
        return grpc.StatusCode.INVALID_ARGUMENT
    if status_code == 404:
        return grpc.StatusCode.NOT_FOUND
    if status_code == 409:
        return grpc.StatusCode.FAILED_PRECONDITION
    return grpc.StatusCode.INTERNAL


class AdminConfigGrpcServicer(admin_pb2_grpc.AdminConfigServiceServicer):
    async def GetFeePolicy(  # noqa: N802
        self,
        request: admin_pb2.FeePolicyRequest,
        context: grpc.aio.ServicerContext,
    ) -> admin_pb2.FeePolicyResponse:
        async with AsyncSessionLocal() as session:
            svc = AdminService(AdminRepository(session))
            try:
                policy = await svc.resolve_fee_policy(
                    amount=request.amount,
                    who_pays=request.who_pays,
                )
            except HTTPException as exc:
                await context.abort(_http_to_grpc_code(exc.status_code), str(exc.detail))
            except Exception:
                logger.exception(
                    "Unexpected GetFeePolicy failure amount=%s who_pays=%s",
                    request.amount,
                    request.who_pays,
                )
                await context.abort(grpc.StatusCode.INTERNAL, "Unable to resolve fee policy")

        return admin_pb2.FeePolicyResponse(
            fee_amount=policy["fee_amount"],
            buyer_fee=policy["buyer_fee"],
            seller_fee=policy["seller_fee"],
            platform_fee_percent=policy["platform_fee_percent"],
            min_fee_amount=policy["min_fee_amount"],
            max_fee_amount=policy["max_fee_amount"],
            used_override=policy["used_override"],
        )


async def serve() -> None:
    server = grpc.aio.server()
    admin_pb2_grpc.add_AdminConfigServiceServicer_to_server(AdminConfigGrpcServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    logger.info("Admin gRPC server starting on port %s", GRPC_PORT)
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop(grace=5)
        logger.info("Admin gRPC server stopped")
