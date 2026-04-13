"""Admin gRPC client for fee policy resolution."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import grpc.aio

from app.settings import ADMIN_GRPC_TIMEOUT_SECONDS

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

logger = logging.getLogger(__name__)
ADMIN_GRPC = os.getenv("ADMIN_GRPC", "admin-service:50051")


async def get_fee_policy(amount: int, who_pays: str) -> dict:
    request = admin_pb2.FeePolicyRequest(amount=amount, who_pays=who_pays)
    try:
        async with grpc.aio.insecure_channel(ADMIN_GRPC) as channel:
            stub = admin_pb2_grpc.AdminConfigServiceStub(channel)
            response = await stub.GetFeePolicy(request, timeout=ADMIN_GRPC_TIMEOUT_SECONDS)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(exc.details() or "Unable to resolve fee policy") from exc

    return {
        "fee_amount": int(response.fee_amount),
        "buyer_fee": int(response.buyer_fee),
        "seller_fee": int(response.seller_fee),
        "platform_fee_percent": float(response.platform_fee_percent),
        "min_fee_amount": int(response.min_fee_amount),
        "max_fee_amount": int(response.max_fee_amount),
        "used_override": bool(response.used_override),
    }
