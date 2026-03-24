from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
from pathlib import Path

import grpc
import grpc.aio

from app.config import get_settings
from app.service import StorageService

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

storage_pb2 = importlib.import_module("proto.storage_pb2")
storage_pb2_grpc = importlib.import_module("proto.storage_pb2_grpc")

logger = logging.getLogger(__name__)
GRPC_PORT = int(os.getenv("GRPC_PORT", "50051"))


class StorageServicer(storage_pb2_grpc.StorageServiceServicer):
    def __init__(self) -> None:
        self.service = StorageService(get_settings())

    async def GeneratePresignedUploadUrl(
        self,
        request,
        context: grpc.aio.ServicerContext,
    ):  # noqa: N802
        try:
            signed = self.service.generate_presigned_upload_url(
                actor_user_id=request.actor_user_id,
                role=request.role,
                purpose=request.purpose,
                object_key=request.object_key,
                content_type=request.content_type,
                expires_in_seconds=request.expires_in_seconds,
            )
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))

        return storage_pb2.PresignUrlResponse(
            success=True,
            message="OK",
            url=signed.url,
            method=signed.method,
            object_key=signed.object_key,
            expires_in_seconds=signed.expires_in_seconds,
        )

    async def GeneratePresignedDownloadUrl(
        self,
        request,
        context: grpc.aio.ServicerContext,
    ):  # noqa: N802
        try:
            signed = self.service.generate_presigned_download_url(
                actor_user_id=request.actor_user_id,
                role=request.role,
                purpose=request.purpose,
                object_key=request.object_key,
                expires_in_seconds=request.expires_in_seconds,
            )
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))

        return storage_pb2.PresignUrlResponse(
            success=True,
            message="OK",
            url=signed.url,
            method=signed.method,
            object_key=signed.object_key,
            expires_in_seconds=signed.expires_in_seconds,
        )


async def serve() -> None:
    server = grpc.aio.server()
    storage_pb2_grpc.add_StorageServiceServicer_to_server(StorageServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    logger.info("Storage gRPC server starting on port %s", GRPC_PORT)
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop(grace=5)
        logger.info("Storage gRPC server stopped")
