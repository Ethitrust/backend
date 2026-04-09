"""
gRPC client stubs for the Payout service.

Calls:
  - Auth service:    validate_token
  - Wallet service:  deduct_balance (synchronous; before payout is queued)
"""

from __future__ import annotations

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

import proto.auth_pb2 as auth_pb2
import proto.auth_pb2_grpc as auth_pb2_grpc
import proto.payment_provider_pb2 as payment_provider_pb2
import proto.payment_provider_pb2_grpc as payment_provider_pb2_grpc
import proto.wallet_pb2 as wallet_pb2
import proto.wallet_pb2_grpc as wallet_pb2_grpc

AUTH_GRPC = os.getenv("AUTH_GRPC", "auth-service:50051")
WALLET_GRPC = os.getenv("WALLET_GRPC", "wallet-service:50051")
PAYMENT_PROVIDER_GRPC = os.getenv(
    "PAYMENT_PROVIDER_GRPC", "payment-provider-service:50051"
)


async def validate_token(token: str) -> dict:
    """Decode and validate a JWT access token."""
    try:
        async with grpc.aio.insecure_channel(AUTH_GRPC) as channel:
            stub = auth_pb2_grpc.AuthValidatorStub(channel)
            response = await stub.ValidateToken(
                auth_pb2.TokenRequest(token=token), timeout=5.0
            )
    except grpc.aio.AioRpcError as exc:
        raise PermissionError("Invalid token") from exc

    if not response.valid:
        raise PermissionError("Invalid token")

    return {
        "user_id": response.user_id,
        "role": response.role or "user",
    }


async def get_user_by_id(user_id: str) -> dict:
    request = auth_pb2.UserRequest(user_id=user_id)

    try:
        async with grpc.aio.insecure_channel(AUTH_GRPC) as channel:
            stub = auth_pb2_grpc.AuthValidatorStub(channel)
            response = await stub.GetUserById(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to fetch user profile") from exc

    return {
        "user_id": response.user_id,
        "email": response.email,
        "role": response.role or "user",
        "is_verified": response.is_verified,
        "is_banned": response.is_banned,
        "kyc_level": int(response.kyc_level),
    }


async def deduct_wallet_balance(
    wallet_id: uuid.UUID,
    amount: int,
    reference: str,
    provider: str,
) -> dict:
    """
    Call Wallet service to atomically deduct balance before payout.

    In production this is a gRPC call to wallet-service:50051.
    Returns {"success": True, "new_balance": <int>} or raises on failure.
    """
    request = wallet_pb2.DeductRequest(
        wallet_id=str(wallet_id),
        amount=amount,
        reference=reference,
        provider=provider,
    )
    try:
        async with grpc.aio.insecure_channel(WALLET_GRPC) as channel:
            stub = wallet_pb2_grpc.WalletServiceStub(channel)
            response = await stub.DeductBalance(request, timeout=8.0)
    except grpc.aio.AioRpcError as exc:
        details = exc.details() or "Wallet deduction failed"
        raise RuntimeError(details) from exc

    return {
        "success": response.success,
        "new_balance": response.new_balance,
        "message": response.message,
    }


async def credit_wallet_balance(
    wallet_id: uuid.UUID,
    amount: int,
    reference: str,
    currency: str,
    provider: str,
) -> dict:
    """Credit wallet balance back (used for payout reversal/refund)."""
    request = wallet_pb2.FundRequest(
        wallet_id=str(wallet_id),
        amount=amount,
        reference=reference,
        currency=currency,
        provider=provider,
    )
    try:
        async with grpc.aio.insecure_channel(WALLET_GRPC) as channel:
            stub = wallet_pb2_grpc.WalletServiceStub(channel)
            response = await stub.FundWallet(request, timeout=8.0)
    except grpc.aio.AioRpcError as exc:
        details = exc.details() or "Wallet reversal failed"
        raise RuntimeError(details) from exc

    return {
        "success": response.success,
        "message": response.message,
    }


async def initiate_bank_transfer(
    bank_code: str,
    account_number: str,
    amount: int,
    currency: str,
    reference: str,
    provider: str = "chapa",
    account_name: str | None = None,
) -> dict:
    """
    Call Payment Provider service to initiate a bank transfer.

    Returns {"provider_ref": str, "status": "processing"}.
    """
    provider_name = (provider or "chapa").strip().lower()

    if provider_name == "manual":
        return {
            "provider_ref": f"MANUAL-{reference}",
            "status": "processing",
        }

    if provider_name == "chapa":
        try:
            async with grpc.aio.insecure_channel(PAYMENT_PROVIDER_GRPC) as channel:
                stub = payment_provider_pb2_grpc.PaymentProviderServiceStub(channel)
                transfer_resp = await stub.InitiateTransfer(
                    payment_provider_pb2.TransferRequest(
                        account_name=account_name or "Payout Beneficiary",
                        account_number=account_number,
                        amount=amount,
                        currency=currency,
                        reference=reference,
                        bank_code=int(bank_code),
                        provider="chapa",
                    ),
                    timeout=15.0,
                )

                if not transfer_resp.success or not transfer_resp.provider_ref:
                    raise RuntimeError(
                        transfer_resp.message or "Transfer initiation failed"
                    )

                verify_resp = await stub.VerifyTransfer(
                    payment_provider_pb2.TransferVerifyRequest(
                        provider_ref=transfer_resp.provider_ref,
                        provider="chapa",
                    ),
                    timeout=15.0,
                )

                if not verify_resp.success:
                    raise RuntimeError("Transfer verification failed")

                return {
                    "provider_ref": transfer_resp.provider_ref,
                    "status": verify_resp.status or "success",
                }
        except ValueError as exc:
            raise RuntimeError("Invalid bank code") from exc
        except grpc.aio.AioRpcError as exc:
            details = exc.details() or "Payment provider transfer call failed"
            raise RuntimeError(details) from exc

    raise RuntimeError(f"Unsupported payout provider: {provider_name}")
