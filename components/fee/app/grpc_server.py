"""gRPC server for the Fee service."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
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

import proto.fee_pb2 as fee_pb2
import proto.fee_pb2_grpc as fee_pb2_grpc

from app.db import AsyncSessionLocal
from app.repository import FeeRepository
from app.service import FeeService

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


def _to_proto_entry(entry) -> fee_pb2.FeeLedgerResponse:
    return fee_pb2.FeeLedgerResponse(
        id=str(entry.id),
        escrow_id=str(entry.escrow_id),
        fee_type=entry.fee_type,
        amount=entry.amount,
        currency=entry.currency,
        paid_by=entry.paid_by,
        status=entry.status,
        created_at=entry.created_at.isoformat() if entry.created_at else "",
    )


class FeeGrpcServicer(fee_pb2_grpc.FeeServiceServicer):
    async def RefundFeeForEscrow(  # noqa: N802
        self,
        request: fee_pb2.RefundFeeForEscrowRequest,
        context: grpc.aio.ServicerContext,
    ) -> fee_pb2.RefundFeeForEscrowResponse:
        try:
            escrow_id = uuid.UUID(request.escrow_id)
        except (TypeError, ValueError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid escrow_id")

        async with AsyncSessionLocal() as session:
            svc = FeeService(FeeRepository(session))
            try:
                entries = await svc.refund_fee(escrow_id)
                await session.commit()
            except HTTPException as exc:
                await session.rollback()
                await context.abort(
                    _http_to_grpc_code(exc.status_code), str(exc.detail)
                )
            except Exception:
                await session.rollback()
                logger.exception(
                    "Unexpected RefundFeeForEscrow failure escrow_id=%s", escrow_id
                )
                await context.abort(
                    grpc.StatusCode.INTERNAL,
                    "Unable to refund fee for escrow",
                )

        return fee_pb2.RefundFeeForEscrowResponse(
            items=[_to_proto_entry(entry) for entry in entries],
        )


async def serve() -> None:
    server = grpc.aio.server()
    fee_pb2_grpc.add_FeeServiceServicer_to_server(FeeGrpcServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    logger.info("Fee gRPC server starting on port %s", GRPC_PORT)
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop(grace=5)
        logger.info("Fee gRPC server stopped")
