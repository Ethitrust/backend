"""gRPC server for the Audit service."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import grpc
import grpc.aio
from fastapi import HTTPException
from google.protobuf import json_format

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

import proto.audit_pb2 as audit_pb2
import proto.audit_pb2_grpc as audit_pb2_grpc

from app.db import AsyncSessionLocal
from app.models import AuditLogCreate
from app.repository import AuditRepository
from app.service import AuditService

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


def _parse_uuid(value: str, field_name: str) -> uuid.UUID | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        return uuid.UUID(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}") from exc


def _struct_to_dict(value: Any) -> dict[str, Any]:
    parsed = json_format.MessageToDict(
        value,
        preserving_proto_field_name=True,
    )
    return parsed if isinstance(parsed, dict) else {}


class AuditGrpcServicer(audit_pb2_grpc.AuditServiceServicer):
    async def EmitAuditLog(  # noqa: N802
        self,
        request: audit_pb2.EmitAuditLogRequest,
        context: grpc.aio.ServicerContext,
    ) -> audit_pb2.EmitAuditLogResponse:
        action = request.action.strip()
        resource = request.resource.strip()
        if not action:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "action is required")
        if not resource:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "resource is required"
            )

        try:
            actor_id = _parse_uuid(request.actor_id, "actor_id")
            resource_id = _parse_uuid(request.resource_id, "resource_id")
            details = {
                "before": _struct_to_dict(request.before),
                "after": _struct_to_dict(request.after),
                "metadata": _struct_to_dict(request.metadata),
            }

            payload = AuditLogCreate(
                actor_id=actor_id,
                action=action,
                resource=resource,
                resource_id=resource_id,
                details=details,
            )

            async with AsyncSessionLocal() as session:
                service = AuditService(AuditRepository(session))
                log = await service.log(payload)
                await session.commit()

        except HTTPException as exc:
            await context.abort(_http_to_grpc_code(exc.status_code), str(exc.detail))
        except grpc.RpcError:
            raise
        except Exception:
            logger.exception("Unexpected EmitAuditLog failure")
            await context.abort(
                grpc.StatusCode.INTERNAL,
                "Unable to emit audit log",
            )

        return audit_pb2.EmitAuditLogResponse(
            success=True,
            message="audit log stored",
            log_id=str(log.id),
        )


async def serve() -> None:
    server = grpc.aio.server()
    audit_pb2_grpc.add_AuditServiceServicer_to_server(AuditGrpcServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    logger.info("Audit gRPC server starting on port %s", GRPC_PORT)
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop(grace=5)
        logger.info("Audit gRPC server stopped")
