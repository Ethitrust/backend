"""
gRPC server for the Payment Provider service.

Exposes:
  - CreateCheckout(CheckoutRequest) → CheckoutResponse
  - VerifyPayment(VerifyRequest) → VerifyResponse
    - InitiateTransfer(TransferRequest) → TransferResponse
    - VerifyTransfer(TransferVerifyRequest) → TransferVerifyResponse

Run `bash scripts/generate_protos.sh` from repo root before starting.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

import grpc
import grpc.aio

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

import proto.payment_provider_pb2 as payment_provider_pb2  # noqa: E402
import proto.payment_provider_pb2_grpc as payment_provider_pb2_grpc  # noqa: E402

from app.service import ChapaInitRequest, TransferOptions, get_provider  # noqa: E402

logger = logging.getLogger(__name__)
GRPC_PORT = int(os.getenv("GRPC_PORT", "50051"))


class PaymentProviderServicer(payment_provider_pb2_grpc.PaymentProviderServiceServicer):
    async def CreateCheckout(
        self,
        request: payment_provider_pb2.CheckoutRequest,
        context: grpc.aio.ServicerContext,
    ) -> payment_provider_pb2.CheckoutResponse:  # noqa: N802
        try:
            metadata: dict = {}
            if request.metadata_json:
                try:
                    metadata = json.loads(request.metadata_json)
                except json.JSONDecodeError:
                    pass

            if not isinstance(metadata, dict):
                metadata = {}

            tx_ref = str(
                metadata.get("tx_ref")
                or metadata.get("transaction_ref")
                or f"wallet-{uuid.uuid4().hex}"
            )

            invoices: list[dict[str, str]] = []
            for key, value in metadata.items():
                if key in {
                    "tx_ref",
                    "transaction_ref",
                    "payment_reason",
                    "hide_receipt",
                    "disable_phone_edit",
                    "custom_receipt_enabled",
                    "invoices",
                }:
                    continue
                invoices.append({"key": str(key), "value": str(value)})

            explicit_invoices = metadata.get("invoices")
            if isinstance(explicit_invoices, list):
                for item in explicit_invoices:
                    if not isinstance(item, dict):
                        continue
                    key = item.get("key")
                    value = item.get("value")
                    if key is None or value is None:
                        continue
                    invoices.append({"key": str(key), "value": str(value)})

            chapa_meta: dict | None = None
            if invoices:
                chapa_meta = {
                    "invoices": invoices,
                    "payment_reason": str(metadata.get("payment_reason"))
                    if metadata.get("payment_reason") is not None
                    else None,
                    "hide_receipt": bool(metadata.get("hide_receipt", False)),
                    "disable_phone_edit": bool(
                        metadata.get("disable_phone_edit", False)
                    ),
                    "custom_receipt_enabled": bool(
                        metadata.get("custom_receipt_enabled", False)
                    ),
                }

            provider = get_provider(request.provider or "chapa")
            request = ChapaInitRequest(
                amount=str(request.amount),
                currency=request.currency or "ETB",
                callback_url=os.getenv(
                    "CHAPA_CALLBACK_URL", "http://localhost:8000/webhook/chapa"
                ),
                return_url=request.return_url
                or os.getenv("FRONTEND_URL", "http://localhost:3000"),
                tx_ref=tx_ref,
                meta=chapa_meta,
            )
            result = await provider.create_checkout(request)
            return payment_provider_pb2.CheckoutResponse(
                payment_url=result.payment_url,
                transaction_ref=result.transaction_ref,
                provider=result.provider,
            )
        except Exception as exc:
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))

    async def VerifyPayment(
        self,
        request: payment_provider_pb2.VerifyRequest,
        context: grpc.aio.ServicerContext,
    ) -> payment_provider_pb2.VerifyResponse:  # noqa: N802
        try:
            provider = get_provider(request.provider or "chapa")
            success = await provider.verify_payment(request.reference)
            return payment_provider_pb2.VerifyResponse(
                success=success, status="success" if success else "failed"
            )
        except Exception as exc:
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))

    async def InitiateTransfer(
        self,
        request: payment_provider_pb2.TransferRequest,
        context: grpc.aio.ServicerContext,
    ) -> payment_provider_pb2.TransferResponse:  # noqa: N802
        try:
            provider = get_provider(request.provider or "chapa")
            transfer_request = TransferOptions(
                account_name=request.account_name,
                account_number=request.account_number,
                amount=str(request.amount),
                currency=request.currency or "ETB",
                reference=request.reference,
                bank_code=int(request.bank_code),
            )
            result = await provider.initiate_transfer(transfer_request)
            return payment_provider_pb2.TransferResponse(
                success=result.success,
                provider_ref=result.provider_ref,
                message=result.message,
                status="success" if result.success else "failed",
            )
        except Exception as exc:
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))

    async def VerifyTransfer(
        self,
        request: payment_provider_pb2.TransferVerifyRequest,
        context: grpc.aio.ServicerContext,
    ) -> payment_provider_pb2.TransferVerifyResponse:  # noqa: N802
        try:
            provider = get_provider(request.provider or "chapa")
            success = await provider.verify_transfer(request.provider_ref)
            return payment_provider_pb2.TransferVerifyResponse(
                success=success,
                status="success" if success else "failed",
            )
        except Exception as exc:
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))


async def serve() -> None:
    server = grpc.aio.server()
    payment_provider_pb2_grpc.add_PaymentProviderServiceServicer_to_server(
        PaymentProviderServicer(), server
    )
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    logger.info("Payment Provider gRPC server starting on port %s", GRPC_PORT)
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop(grace=5)
        logger.info("Payment Provider gRPC server stopped")
