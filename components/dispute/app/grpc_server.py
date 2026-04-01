"""gRPC server for the Dispute service."""

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

import proto.dispute_pb2 as dispute_pb2
import proto.dispute_pb2_grpc as dispute_pb2_grpc

from app.db import AsyncSessionLocal
from app.models import DisputeResolve
from app.repository import DisputeRepository
from app.service import DisputeService

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


def _to_proto_dispute(dispute) -> dispute_pb2.DisputeResponse:
    return dispute_pb2.DisputeResponse(
        id=str(dispute.id),
        escrow_id=str(dispute.escrow_id),
        raised_by=str(dispute.raised_by),
        reason=dispute.reason,
        description=dispute.description,
        status=dispute.status,
        resolution_note=dispute.resolution_note or "",
        resolved_by=str(dispute.resolved_by) if dispute.resolved_by else "",
        resolved_at=dispute.resolved_at.isoformat() if dispute.resolved_at else "",
        created_at=dispute.created_at.isoformat() if dispute.created_at else "",
    )


class DisputeGrpcServicer(dispute_pb2_grpc.DisputeServiceServicer):
    async def ListDisputes(  # noqa: N802
        self,
        request: dispute_pb2.ListDisputesRequest,
        context: grpc.aio.ServicerContext,
    ) -> dispute_pb2.ListDisputesResponse:
        page = request.page if request.page > 0 else 1
        limit = request.limit if request.limit > 0 else 20
        limit = min(limit, 200)
        status_filter = request.status.strip() or None

        async with AsyncSessionLocal() as session:
            svc = DisputeService(DisputeRepository(session))
            result = await svc.list_disputes(
                actor_role="admin",
                status_filter=status_filter,
                page=page,
                limit=limit,
            )

        items = [_to_proto_dispute(item) for item in result["items"]]
        return dispute_pb2.ListDisputesResponse(
            items=items,
            total=int(result["total"]),
            page=int(result["page"]),
            limit=int(result["limit"]),
            pages=int(result["pages"]),
        )

    async def MarkDisputeUnderReview(  # noqa: N802
        self,
        request: dispute_pb2.MarkDisputeUnderReviewRequest,
        context: grpc.aio.ServicerContext,
    ) -> dispute_pb2.DisputeResponse:
        try:
            dispute_id = uuid.UUID(request.dispute_id)
            reviewer_id = uuid.UUID(request.reviewer_id)
        except (TypeError, ValueError):
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "dispute_id and reviewer_id must be valid UUIDs",
            )

        note = request.note.strip() or None

        async with AsyncSessionLocal() as session:
            svc = DisputeService(DisputeRepository(session))
            try:
                dispute = await svc.mark_under_review(
                    dispute_id=dispute_id,
                    moderator_id=reviewer_id,
                    moderator_role="admin",
                    note=note,
                )
                await session.commit()
            except HTTPException as exc:
                await session.rollback()
                await context.abort(
                    _http_to_grpc_code(exc.status_code), str(exc.detail)
                )
            except Exception:
                await session.rollback()
                logger.exception(
                    "Unexpected MarkDisputeUnderReview failure dispute_id=%s",
                    dispute_id,
                )
                await context.abort(
                    grpc.StatusCode.INTERNAL,
                    "Unable to move dispute to under_review",
                )

        return _to_proto_dispute(dispute)

    async def RequestDisputeResolution(  # noqa: N802
        self,
        request: dispute_pb2.RequestDisputeResolutionRequest,
        context: grpc.aio.ServicerContext,
    ) -> dispute_pb2.DisputeResponse:
        try:
            dispute_id = uuid.UUID(request.dispute_id)
            admin_id = uuid.UUID(request.admin_id)
        except (TypeError, ValueError):
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "dispute_id and admin_id must be valid UUIDs",
            )

        resolution = request.resolution.strip()
        resolution_note = request.resolution_note.strip()
        if not resolution:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "resolution is required"
            )
        if not resolution_note:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "resolution_note is required",
            )

        async with AsyncSessionLocal() as session:
            svc = DisputeService(DisputeRepository(session))
            try:
                dispute = await svc.resolve_dispute(
                    dispute_id=dispute_id,
                    admin_id=admin_id,
                    admin_role="admin",
                    data=DisputeResolve(
                        resolution=resolution,
                        resolution_note=resolution_note,
                    ),
                )
                await session.commit()
            except HTTPException as exc:
                await session.rollback()
                await context.abort(
                    _http_to_grpc_code(exc.status_code), str(exc.detail)
                )
            except Exception:
                await session.rollback()
                logger.exception(
                    "Unexpected RequestDisputeResolution failure dispute_id=%s",
                    dispute_id,
                )
                await context.abort(
                    grpc.StatusCode.INTERNAL,
                    "Unable to queue dispute resolution",
                )

        return _to_proto_dispute(dispute)

    async def ExecuteDisputeResolution(  # noqa: N802
        self,
        request: dispute_pb2.ExecuteDisputeResolutionRequest,
        context: grpc.aio.ServicerContext,
    ) -> dispute_pb2.DisputeResponse:
        try:
            dispute_id = uuid.UUID(request.dispute_id)
        except (TypeError, ValueError):
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid dispute_id")

        resolution = request.resolution.strip()
        if not resolution:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "resolution is required"
            )

        admin_id: uuid.UUID | None = None
        if request.admin_id.strip():
            try:
                admin_id = uuid.UUID(request.admin_id)
            except (TypeError, ValueError):
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT, "Invalid admin_id"
                )

        async with AsyncSessionLocal() as session:
            svc = DisputeService(DisputeRepository(session))
            try:
                dispute = await svc.execute_resolution(
                    dispute_id=dispute_id,
                    resolution=resolution,
                    admin_id=admin_id,
                )
                await session.commit()
            except HTTPException as exc:
                await session.rollback()
                await context.abort(
                    _http_to_grpc_code(exc.status_code), str(exc.detail)
                )
            except Exception:
                await session.rollback()
                logger.exception(
                    "Unexpected ExecuteDisputeResolution failure dispute_id=%s",
                    dispute_id,
                )
                await context.abort(
                    grpc.StatusCode.INTERNAL,
                    "Unable to execute dispute resolution",
                )

        return _to_proto_dispute(dispute)


async def serve() -> None:
    server = grpc.aio.server()
    dispute_pb2_grpc.add_DisputeServiceServicer_to_server(DisputeGrpcServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    logger.info("Dispute gRPC server starting on port %s", GRPC_PORT)
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop(grace=5)
        logger.info("Dispute gRPC server stopped")
