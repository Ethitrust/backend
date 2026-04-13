"""
gRPC server for the Wallet service.

Exposes:
  - LockFunds, UnlockFunds, ReleaseFunds, FundWallet, GetBalance, DeductBalance

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

import proto.wallet_pb2 as wallet_pb2
import proto.wallet_pb2_grpc as wallet_pb2_grpc

from app.db import AsyncSessionLocal
from app.repository import WalletRepository
from app.service import WalletService

logger = logging.getLogger(__name__)
GRPC_PORT = int(os.getenv("GRPC_PORT", "50051"))


def _svc(session) -> WalletService:
    return WalletService(WalletRepository(session))


class WalletServicer(wallet_pb2_grpc.WalletServiceServicer):
    async def GetWalletByOwner(
        self,
        request: wallet_pb2.OwnerWalletRequest,
        context: grpc.aio.ServicerContext,
    ) -> wallet_pb2.OwnerWalletResponse:  # noqa: N802
        try:
            owner_id = uuid.UUID(request.owner_id)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid owner_id")

        currency = request.currency.strip().upper()
        if not currency:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Currency is required")

        try:
            async with AsyncSessionLocal() as session:
                svc = _svc(session)
                wallet = await svc.get_wallet_by_owner_currency(
                    owner_id,
                    currency,
                )
                if wallet is None:
                    try:
                        wallet = await svc.create_wallet(owner_id, currency)
                    except HTTPException as exc:
                        if exc.status_code == 409:
                            await session.rollback()
                            wallet = await svc.get_wallet_by_owner_currency(owner_id, currency)
                        else:
                            raise
                    else:
                        await session.commit()
            if wallet is None:
                return wallet_pb2.OwnerWalletResponse(found=False, wallet_id="")
            return wallet_pb2.OwnerWalletResponse(found=True, wallet_id=str(wallet.id))
        except Exception as exc:
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))

    async def LockFunds(
        self, request: wallet_pb2.FundsRequest, context: grpc.aio.ServicerContext
    ) -> wallet_pb2.FundsResponse:  # noqa: N802
        try:
            wallet_id = uuid.UUID(request.wallet_id)
            escrow_id = uuid.UUID(request.escrow_id) if request.escrow_id else None
            source_id = uuid.UUID(request.source_id) if request.source_id else None
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid UUID")
        try:
            async with AsyncSessionLocal() as session:
                await _svc(session).lock_funds(
                    wallet_id,
                    request.amount,
                    request.reference,
                    escrow_id,
                    request.reason or None,
                    request.source_type or None,
                    source_id,
                )
                await session.commit()
            return wallet_pb2.FundsResponse(success=True, message="Funds locked")
        except Exception as exc:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))

    async def UnlockFunds(
        self, request: wallet_pb2.FundsRequest, context: grpc.aio.ServicerContext
    ) -> wallet_pb2.FundsResponse:  # noqa: N802
        try:
            wallet_id = uuid.UUID(request.wallet_id)
            escrow_id = uuid.UUID(request.escrow_id) if request.escrow_id else None
            source_id = uuid.UUID(request.source_id) if request.source_id else None
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid UUID")
        try:
            async with AsyncSessionLocal() as session:
                await _svc(session).unlock_funds(
                    wallet_id,
                    request.amount,
                    request.reference,
                    escrow_id,
                    request.reason or None,
                    request.source_type or None,
                    source_id,
                )
                await session.commit()
            return wallet_pb2.FundsResponse(success=True, message="Funds unlocked")
        except Exception as exc:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))

    async def ReleaseFunds(
        self, request: wallet_pb2.ReleaseRequest, context: grpc.aio.ServicerContext
    ) -> wallet_pb2.FundsResponse:  # noqa: N802
        try:
            from_id = uuid.UUID(request.from_wallet_id)
            to_id = uuid.UUID(request.to_wallet_id)
            escrow_id = uuid.UUID(request.escrow_id) if request.escrow_id else None
            source_id = uuid.UUID(request.source_id) if request.source_id else None
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid UUID")
        try:
            async with AsyncSessionLocal() as session:
                await _svc(session).release_funds(
                    from_id,
                    to_id,
                    request.amount,
                    request.reference,
                    escrow_id,
                    request.reason or None,
                    request.source_type or None,
                    source_id,
                )
                await session.commit()
            return wallet_pb2.FundsResponse(success=True, message="Funds released")
        except Exception as exc:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))

    async def FundWallet(
        self, request: wallet_pb2.FundRequest, context: grpc.aio.ServicerContext
    ) -> wallet_pb2.FundsResponse:  # noqa: N802
        try:
            wallet_id = uuid.UUID(request.wallet_id)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid wallet_id")
        try:
            async with AsyncSessionLocal() as session:
                tx = await _svc(session).fund_wallet(
                    wallet_id,
                    request.amount,
                    request.reference,
                    request.currency,
                    request.provider,
                )
                await session.commit()
            return wallet_pb2.FundsResponse(success=True, message=str(tx.id))
        except Exception as exc:
            await context.abort(grpc.StatusCode.INTERNAL, str(exc))

    async def GetBalance(
        self, request: wallet_pb2.BalanceRequest, context: grpc.aio.ServicerContext
    ) -> wallet_pb2.BalanceResponse:  # noqa: N802
        try:
            wallet_id = uuid.UUID(request.wallet_id)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid wallet_id")
        try:
            async with AsyncSessionLocal() as session:
                wallet = await _svc(session).get_balance(wallet_id)
            return wallet_pb2.BalanceResponse(
                balance=wallet.balance,
                locked_balance=wallet.locked_balance,
                currency=wallet.currency,
            )
        except Exception as exc:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(exc))

    async def DeductBalance(
        self, request: wallet_pb2.DeductRequest, context: grpc.aio.ServicerContext
    ) -> wallet_pb2.DeductResponse:  # noqa: N802
        try:
            wallet_id = uuid.UUID(request.wallet_id)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid wallet_id")
        try:
            async with AsyncSessionLocal() as session:
                wallet = await _svc(session).deduct_balance(
                    wallet_id,
                    request.amount,
                    request.reference,
                    request.provider,
                )
                await session.commit()
            return wallet_pb2.DeductResponse(success=True, new_balance=wallet.balance)
        except Exception as exc:
            await context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(exc))


async def serve() -> None:
    server = grpc.aio.server()
    wallet_pb2_grpc.add_WalletServiceServicer_to_server(WalletServicer(), server)
    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    logger.info("Wallet gRPC server starting on port %s", GRPC_PORT)
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        await server.stop(grace=5)
        logger.info("Wallet gRPC server stopped")
