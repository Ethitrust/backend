"""gRPC server for the Escrow service."""

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

import proto.escrow_pb2 as escrow_pb2  # noqa: E402
import proto.escrow_pb2_grpc as escrow_pb2_grpc  # noqa: E402
from app.db import async_session_factory  # noqa: E402
from app.repository import EscrowRepository  # noqa: E402
from app.service import EscrowService  # noqa: E402

logger = logging.getLogger(__name__)
GRPC_PORT = int(os.getenv("GRPC_PORT", "50051"))


def _svc(session) -> EscrowService:
    return EscrowService(EscrowRepository(session))


def _map_http_to_grpc_status(status_code: int) -> grpc.StatusCode:
    if status_code == 400:
        return grpc.StatusCode.INVALID_ARGUMENT
    if status_code == 403:
        return grpc.StatusCode.PERMISSION_DENIED
    if status_code == 404:
        return grpc.StatusCode.NOT_FOUND
    if status_code == 409:
        return grpc.StatusCode.FAILED_PRECONDITION
    if status_code == 503:
        return grpc.StatusCode.UNAVAILABLE
    return grpc.StatusCode.INTERNAL


def _to_escrow_response(
    escrow,
    *,
    success: bool = True,
    message: str = "",
) -> escrow_pb2.EscrowResponse:
    return escrow_pb2.EscrowResponse(
        escrow_id=str(escrow.id),
        status=escrow.status,
        escrow_type=escrow.escrow_type,
        initiator_id=str(escrow.initiator_id),
        receiver_id=str(escrow.receiver_id) if escrow.receiver_id else "",
        amount=escrow.amount,
        currency=escrow.currency,
        success=success,
        message=message,
    )


class EscrowServicer(escrow_pb2_grpc.EscrowServiceServicer):
    async def GetEscrow(
        self,
        request: escrow_pb2.EscrowRequest,
        context: grpc.aio.ServicerContext,
    ) -> escrow_pb2.EscrowResponse:  # noqa: N802
        try:
            escrow_id = uuid.UUID(request.escrow_id)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid escrow_id")

        async with async_session_factory() as session:
            escrow = await EscrowRepository(session).get_by_id(escrow_id)

        if escrow is None:
            await context.abort(grpc.StatusCode.NOT_FOUND, "Escrow not found")

        return _to_escrow_response(escrow)

    async def TransitionStatus(
        self,
        request: escrow_pb2.TransitionRequest,
        context: grpc.aio.ServicerContext,
    ) -> escrow_pb2.EscrowResponse:  # noqa: N802
        try:
            escrow_id = uuid.UUID(request.escrow_id)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid escrow_id")

        new_status = request.new_status.strip()
        if not new_status:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "new_status is required"
            )

        actor_id = request.actor_id.strip()
        if not actor_id:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "actor_id is required"
            )

        try:
            async with async_session_factory() as session:
                service = _svc(session)
                escrow = await service.repo.get_by_id(escrow_id)
                if escrow is None:
                    await context.abort(grpc.StatusCode.NOT_FOUND, "Escrow not found")

                actor: str
                if actor_id in {
                    "initiator",
                    "counterparty",
                    "system",
                    "admin_or_resolution_engine",
                }:
                    actor = actor_id
                elif actor_id == "dispute-service":
                    actor = "admin_or_resolution_engine"
                else:
                    try:
                        user_id = uuid.UUID(actor_id)
                    except ValueError:
                        await context.abort(
                            grpc.StatusCode.INVALID_ARGUMENT,
                            "actor_id must be a role token or UUID",
                        )

                    resolved_actor = service._resolve_actor_for_user(escrow, user_id)
                    if resolved_actor is None:
                        await context.abort(
                            grpc.StatusCode.PERMISSION_DENIED,
                            "Actor is not allowed to transition this escrow",
                        )
                    actor = resolved_actor

                updated = await service.transition_status(escrow, new_status, actor)
                return _to_escrow_response(updated)

        except HTTPException as exc:
            await context.abort(
                _map_http_to_grpc_status(exc.status_code),
                str(exc.detail),
            )
        except grpc.RpcError:
            raise
        except Exception as exc:
            logger.exception("Unexpected TransitionStatus error")
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))

    async def AssociateUserWithEscrow(
        self,
        request: escrow_pb2.EscrowAssociationRequest,
        context: grpc.aio.ServicerContext,
    ) -> escrow_pb2.EscrowAssociationResponse:  # noqa: N802
        try:
            escrow_id = uuid.UUID(request.escrow_id)
            user_id = uuid.UUID(request.user_id)
        except ValueError:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "escrow_id and user_id must be valid UUIDs",
            )

        try:
            async with async_session_factory() as session:
                repo = EscrowRepository(session)
                escrow = await repo.get_by_id(escrow_id)
                if escrow is None:
                    await context.abort(grpc.StatusCode.NOT_FOUND, "Escrow not found")

                if escrow.receiver_id is not None:
                    if escrow.receiver_id == user_id:
                        return escrow_pb2.EscrowAssociationResponse(
                            success=True,
                            message="User already associated with escrow",
                        )
                    return escrow_pb2.EscrowAssociationResponse(
                        success=False,
                        message="Escrow is already associated with another user",
                    )

                if escrow.initiator_id == user_id:
                    return escrow_pb2.EscrowAssociationResponse(
                        success=False,
                        message="Initiator cannot be associated as counterparty",
                    )

                escrow.receiver_id = user_id
                await repo.save(escrow)

            return escrow_pb2.EscrowAssociationResponse(
                success=True,
                message="User associated with escrow",
            )
        except grpc.RpcError:
            raise
        except Exception as exc:
            logger.exception("Unexpected AssociateUserWithEscrow error")
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))


async def serve() -> None:
    server = grpc.aio.server()
    escrow_pb2_grpc.add_EscrowServiceServicer_to_server(EscrowServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    logger.info("Escrow gRPC server starting on port %s", GRPC_PORT)
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop(grace=5)
        logger.info("Escrow gRPC server stopped")
