"""gRPC client stubs for the Dispute service."""

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
import proto.escrow_pb2 as escrow_pb2
import proto.escrow_pb2_grpc as escrow_pb2_grpc
import proto.storage_pb2 as storage_pb2
import proto.storage_pb2_grpc as storage_pb2_grpc
import proto.wallet_pb2 as wallet_pb2
import proto.wallet_pb2_grpc as wallet_pb2_grpc

AUTH_GRPC = os.getenv("AUTH_GRPC", "auth-service:50051")
ESCROW_GRPC = os.getenv("ESCROW_GRPC", "escrow-service:50051")
WALLET_GRPC = os.getenv("WALLET_GRPC", "wallet-service:50051")
STORAGE_GRPC = os.getenv("STORAGE_GRPC", "storage-service:50051")


async def validate_token(token: str) -> dict:
    try:
        async with grpc.aio.insecure_channel(AUTH_GRPC) as channel:
            stub = auth_pb2_grpc.AuthValidatorStub(channel)
            response = await stub.ValidateToken(auth_pb2.TokenRequest(token=token), timeout=5.0)
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


async def get_escrow(escrow_id: uuid.UUID) -> dict:
    """Fetch escrow metadata from Escrow service."""
    request = escrow_pb2.EscrowRequest(escrow_id=str(escrow_id))
    try:
        async with grpc.aio.insecure_channel(ESCROW_GRPC) as channel:
            stub = escrow_pb2_grpc.EscrowServiceStub(channel)
            response = await stub.GetEscrow(request, timeout=8.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(exc.details() or "Failed to fetch escrow") from exc

    return {
        "id": response.escrow_id,
        "status": response.status,
        "escrow_type": response.escrow_type,
        "initiator_id": response.initiator_id,
        "receiver_id": response.receiver_id,
        "initiator_role": response.initiator_role,
        "transaction_ref": response.transaction_ref,
        "amount": response.amount,
        "currency": response.currency,
    }


async def transition_escrow_status(
    escrow_id: uuid.UUID,
    new_status: str,
    actor_id: str = "dispute-service",
) -> dict:
    """Call Escrow service to change escrow status."""
    request = escrow_pb2.TransitionRequest(
        escrow_id=str(escrow_id),
        new_status=new_status,
        actor_id=actor_id,
    )
    try:
        async with grpc.aio.insecure_channel(ESCROW_GRPC) as channel:
            stub = escrow_pb2_grpc.EscrowServiceStub(channel)
            response = await stub.TransitionStatus(request, timeout=8.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(exc.details() or "Failed to transition escrow") from exc

    return {
        "id": response.escrow_id,
        "status": response.status,
        "success": response.success,
        "message": response.message,
    }


async def get_user_wallet(owner_id: str, currency: str) -> str | None:
    """Fetch wallet id by owner and currency from Wallet service."""
    request = wallet_pb2.OwnerWalletRequest(owner_id=owner_id, currency=currency)
    try:
        async with grpc.aio.insecure_channel(WALLET_GRPC) as channel:
            stub = wallet_pb2_grpc.WalletServiceStub(channel)
            response = await stub.GetWalletByOwner(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(exc.details() or "Unable to fetch user wallet") from exc

    if not response.found or not response.wallet_id:
        return None
    return response.wallet_id


async def release_funds(escrow_id: uuid.UUID, resolution: str) -> dict:
    """Call Wallet service to release or refund escrow funds."""
    if resolution not in {"buyer", "seller"}:
        raise ValueError("Resolution must be either 'buyer' or 'seller'")

    escrow = await get_escrow(escrow_id)

    initiator_owner_id = str(escrow.get("initiator_id") or "")
    receiver_owner_id = str(escrow.get("receiver_id") or "")
    initiator_role = str(escrow.get("initiator_role") or "").lower()
    currency = str(escrow.get("currency") or "").upper()
    amount = int(escrow.get("amount") or 0)
    transaction_ref = str(escrow.get("transaction_ref") or "")

    if initiator_role == "buyer":
        buyer_owner_id = initiator_owner_id
        seller_owner_id = receiver_owner_id
    elif initiator_role == "seller":
        buyer_owner_id = receiver_owner_id
        seller_owner_id = initiator_owner_id
    else:
        raise RuntimeError("Unsupported initiator_role for dispute fund release")

    if not buyer_owner_id or not seller_owner_id:
        raise RuntimeError("Escrow participant identifiers are missing")
    if not currency:
        raise RuntimeError("Escrow currency is missing")
    if amount <= 0:
        raise RuntimeError("Escrow amount is invalid")

    buyer_wallet = await get_user_wallet(buyer_owner_id, currency)
    seller_wallet = await get_user_wallet(seller_owner_id, currency)

    if not buyer_wallet:
        raise RuntimeError("Buyer wallet is unavailable")
    if not seller_wallet:
        raise RuntimeError("Seller wallet is unavailable")

    reference = transaction_ref or str(escrow_id)

    if resolution == "buyer":
        # Buyer wins dispute: unlock previously locked escrow funds back to buyer balance.
        request = wallet_pb2.FundsRequest(
            wallet_id=buyer_wallet,
            amount=amount,
            reference=reference,
            reason="ESCROW",
            source_type="ESCROW",
            source_id=str(escrow_id),
            escrow_id=str(escrow_id),
        )
        try:
            async with grpc.aio.insecure_channel(WALLET_GRPC) as channel:
                stub = wallet_pb2_grpc.WalletServiceStub(channel)
                response = await stub.UnlockFunds(request, timeout=8.0)
        except grpc.aio.AioRpcError as exc:
            raise RuntimeError(exc.details() or "Refund unlock failed") from exc

        if not response.success:
            raise RuntimeError(response.message or "Refund unlock failed")

        return {
            "success": True,
            "resolution": resolution,
            "operation": "unlock",
            "message": response.message,
        }

    # Seller wins dispute: capture locked buyer funds to seller wallet.
    request = wallet_pb2.ReleaseRequest(
        from_wallet_id=buyer_wallet,
        to_wallet_id=seller_wallet,
        amount=amount,
        reference=reference,
        escrow_id=str(escrow_id),
        reason="ESCROW",
        source_type="ESCROW",
        source_id=str(escrow_id),
    )
    try:
        async with grpc.aio.insecure_channel(WALLET_GRPC) as channel:
            stub = wallet_pb2_grpc.WalletServiceStub(channel)
            response = await stub.ReleaseFunds(request, timeout=8.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(exc.details() or "Release funds failed") from exc

    if not response.success:
        raise RuntimeError(response.message or "Release funds failed")

    return {
        "success": True,
        "resolution": resolution,
        "operation": "release",
        "message": response.message,
    }


async def generate_storage_upload_url(
    *,
    actor_user_id: str,
    role: str,
    purpose: str,
    object_key: str,
    content_type: str,
    expires_in_seconds: int = 900,
) -> dict:
    """Generate a presigned upload URL via Storage service."""
    request = storage_pb2.PresignUploadRequest(
        actor_user_id=actor_user_id,
        role=role,
        purpose=purpose,
        object_key=object_key,
        content_type=content_type,
        expires_in_seconds=expires_in_seconds,
    )

    try:
        async with grpc.aio.insecure_channel(STORAGE_GRPC) as channel:
            stub = storage_pb2_grpc.StorageServiceStub(channel)
            response = await stub.GeneratePresignedUploadUrl(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        if exc.code() == grpc.StatusCode.INVALID_ARGUMENT:
            raise ValueError(exc.details()) from exc
        raise RuntimeError(f"Storage upload presign failed: {exc.details()}") from exc

    if not response.success:
        raise RuntimeError(response.message or "Storage upload presign failed")

    return {
        "url": response.url,
        "method": response.method,
        "object_key": response.object_key,
        "expires_in_seconds": response.expires_in_seconds,
    }
