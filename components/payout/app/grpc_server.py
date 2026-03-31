"""gRPC server for the Payout service."""

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
_PROTO_DIR = _APP_DIR.parent / "proto"
if str(_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTO_DIR))

proto_module = sys.modules.setdefault("proto", type(sys)("proto"))
proto_paths = list(getattr(proto_module, "__path__", []))
if str(_PROTO_DIR) not in proto_paths:
    proto_module.__path__ = [*proto_paths, str(_PROTO_DIR)]

import proto.payout_pb2 as payout_pb2
import proto.payout_pb2_grpc as payout_pb2_grpc

from app.db import AsyncSessionLocal, Payout
from app.repository import PayoutRepository
from app.service import PayoutService

logger = logging.getLogger(__name__)
GRPC_PORT = int(os.getenv("GRPC_PORT", "50051"))


def _http_to_grpc_code(status_code: int) -> grpc.StatusCode:
    if status_code == 400:
        return grpc.StatusCode.INVALID_ARGUMENT
    if status_code == 403:
        return grpc.StatusCode.PERMISSION_DENIED
    if status_code == 404:
        return grpc.StatusCode.NOT_FOUND
    if status_code == 409:
        return grpc.StatusCode.FAILED_PRECONDITION
    return grpc.StatusCode.INTERNAL


def _payout_to_proto(payout: Payout) -> payout_pb2.PayoutResponse:
    return payout_pb2.PayoutResponse(
        id=str(payout.id),
        user_id=str(payout.user_id),
        wallet_id=str(payout.wallet_id),
        amount=int(payout.amount),
        currency=payout.currency,
        bank_code=payout.bank_code,
        account_number=payout.account_number,
        account_name=payout.account_name,
        status=payout.status,
        provider=payout.provider or "",
        provider_ref=payout.provider_ref or "",
        failure_reason=payout.failure_reason or "",
        created_at=payout.created_at.isoformat(),
        updated_at=payout.updated_at.isoformat(),
    )


class PayoutGrpcServicer(payout_pb2_grpc.PayoutServiceServicer):
    """Implements the internal payout gRPC surface."""

    async def ListPayouts(  # noqa: N802
        self,
        request: payout_pb2.ListPayoutsRequest,
        context: grpc.aio.ServicerContext,
    ) -> payout_pb2.ListPayoutsResponse:
        page = request.page if request.page > 0 else 1
        limit = request.limit if request.limit > 0 else 20
        limit = min(limit, 200)
        status_filter = request.status.strip() or None

        async with AsyncSessionLocal() as session:
            svc = PayoutService(PayoutRepository(session))
            result = await svc.list_all_payouts(
                page=page,
                limit=limit,
                status_filter=status_filter,
            )

        items = [_payout_to_proto(item) for item in result["items"]]
        return payout_pb2.ListPayoutsResponse(
            items=items,
            total=int(result["total"]),
            page=int(result["page"]),
            limit=int(result["limit"]),
            pages=int(result["pages"]),
        )

    async def RetryPayoutTransfer(  # noqa: N802
        self,
        request: payout_pb2.RetryPayoutTransferRequest,
        context: grpc.aio.ServicerContext,
    ) -> payout_pb2.PayoutResponse:
        try:
            payout_id = uuid.UUID(request.payout_id)
        except (TypeError, ValueError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid payout_id")

        async with AsyncSessionLocal() as session:
            svc = PayoutService(PayoutRepository(session))
            try:
                payout = await svc.process_bank_transfer(payout_id)
                await session.commit()
            except HTTPException as exc:
                await session.rollback()
                await context.abort(
                    _http_to_grpc_code(exc.status_code), str(exc.detail)
                )
            except Exception:
                await session.rollback()
                logger.exception("Payout retry failed payout_id=%s", payout_id)
                await context.abort(
                    grpc.StatusCode.INTERNAL,
                    "Unable to retry payout transfer",
                )

        return _payout_to_proto(payout)


async def serve() -> None:
    server = grpc.aio.server()
    payout_pb2_grpc.add_PayoutServiceServicer_to_server(PayoutGrpcServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    logger.info("Payout gRPC server starting on port %s", GRPC_PORT)
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop(grace=5)
        logger.info("Payout gRPC server stopped")
