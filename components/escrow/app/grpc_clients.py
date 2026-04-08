"""
gRPC client stubs for the Escrow service.

Real implementations replace the `return True / return None` stubs
with actual gRPC channel calls to the target services.
"""

from __future__ import annotations

import json
import logging
import os
import sys
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
import proto.organization_pb2 as organization_pb2
import proto.organization_pb2_grpc as organization_pb2_grpc
import proto.payment_provider_pb2 as payment_provider_pb2
import proto.payment_provider_pb2_grpc as payment_provider_pb2_grpc
import proto.user_pb2 as user_pb2
import proto.user_pb2_grpc as user_pb2_grpc
import proto.wallet_pb2 as wallet_pb2
import proto.wallet_pb2_grpc as wallet_pb2_grpc

AUTH_GRPC = os.getenv("AUTH_GRPC", "auth-service:50051")
USER_GRPC = os.getenv("USER_GRPC", "user-service:50051")
WALLET_GRPC = os.getenv("WALLET_GRPC", "wallet-service:50051")
PAYMENT_GRPC = os.getenv("PAYMENT_GRPC", "payment-provider-service:50051")
ORGANIZATION_GRPC = os.getenv("ORGANIZATION_GRPC", "organization-service:50051")


logger = logging.getLogger(__name__)


async def validate_token(token: str) -> dict:
    """Decode and validate a JWT access token via the Auth service."""
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
    logger.info(f"Fetching user profile for user_id: {user_id}")
    request = user_pb2.UserRequest(user_id=user_id)
    try:
        async with grpc.aio.insecure_channel(USER_GRPC) as channel:
            stub = user_pb2_grpc.UserServiceStub(channel)
            response = await stub.GetUser(request, timeout=5.0)
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.NOT_FOUND:
            raise None
        raise RuntimeError("Unable to fetch user profile") from e
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to fetch user profile") from exc

    return {
        "user_id": response.user_id,
        "email": response.email,
        "role": response.role or "user",
        "is_verified": response.is_verified,
        "is_banned": response.is_banned,
        "kyc_level": int(response.kyc_level) or 0,
        "full_name": response.full_name,
    }


async def get_user_by_email(email: str) -> dict | None:
    logger.info(f"Fetching user profile for email: {email}")
    request = user_pb2.UserByEmailRequest(email=email)
    try:
        async with grpc.aio.insecure_channel(USER_GRPC) as channel:
            stub = user_pb2_grpc.UserServiceStub(channel)
            response = await stub.GetUserByEmail(request, timeout=5.0)

    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.NOT_FOUND:
            return None
        raise RuntimeError("Unable to fetch user profile by email") from e
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to fetch user profile by email") from exc

    return {
        "user_id": response.user_id,
        "email": response.email,
        "role": response.role or "user",
        "is_verified": response.is_verified,
        "is_banned": response.is_banned,
        "kyc_level": int(response.kyc_level) or 0,
        "full_name": response.full_name,
    }


async def check_email_exists(email: str) -> bool:
    """Check if an account already exists for the given email via Auth gRPC."""
    request = auth_pb2.EmailRequest(email=email)
    try:
        async with grpc.aio.insecure_channel(AUTH_GRPC) as channel:
            stub = auth_pb2_grpc.AuthValidatorStub(channel)
            response = await stub.CheckEmailExists(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to verify invited account status") from exc

    return bool(response.exists)


async def lock_funds(
    wallet_id: str,
    amount: int,
    reference: str,
    escrow_id: str | None = None,
) -> bool:
    """gRPC call to wallet service to lock (hold) funds in escrow."""
    request = wallet_pb2.FundsRequest(
        wallet_id=wallet_id,
        amount=amount,
        reference=reference,
        reason="ESCROW",
        source_type="ESCROW",
        source_id=escrow_id or "",
        escrow_id=escrow_id or "",
    )
    try:
        async with grpc.aio.insecure_channel(WALLET_GRPC) as channel:
            stub = wallet_pb2_grpc.WalletServiceStub(channel)
            response = await stub.LockFunds(request, timeout=8.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(exc.details() or "Lock funds failed") from exc

    return response.success


async def unlock_funds(
    wallet_id: str,
    amount: int,
    reference: str,
    escrow_id: str | None = None,
) -> bool:
    """gRPC call to wallet service to release a hold (cancel/refund)."""
    request = wallet_pb2.FundsRequest(
        wallet_id=wallet_id,
        amount=amount,
        reference=reference,
        reason="ESCROW",
        source_type="ESCROW",
        source_id=escrow_id or "",
        escrow_id=escrow_id or "",
    )
    try:
        async with grpc.aio.insecure_channel(WALLET_GRPC) as channel:
            stub = wallet_pb2_grpc.WalletServiceStub(channel)
            response = await stub.UnlockFunds(request, timeout=8.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(exc.details() or "Unlock funds failed") from exc

    return response.success


async def release_funds(
    from_wallet_id: str,
    to_wallet_id: str,
    amount: int,
    reference: str,
    escrow_id: str | None = None,
) -> bool:
    """gRPC call to wallet service to transfer locked funds to the receiver."""
    request = wallet_pb2.ReleaseRequest(
        from_wallet_id=from_wallet_id,
        to_wallet_id=to_wallet_id,
        amount=amount,
        reference=reference,
        escrow_id=escrow_id or "",
        reason="ESCROW",
        source_type="ESCROW",
        source_id=escrow_id or "",
    )
    try:
        async with grpc.aio.insecure_channel(WALLET_GRPC) as channel:
            stub = wallet_pb2_grpc.WalletServiceStub(channel)
            response = await stub.ReleaseFunds(request, timeout=8.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(exc.details() or "Release funds failed") from exc

    return response.success


async def create_checkout(
    amount: int,
    currency: str,
    metadata: dict,
    provider: str = "chapa",
) -> dict:
    """gRPC call to payment-provider service to create a checkout session."""
    request = payment_provider_pb2.CheckoutRequest(
        amount=amount,
        currency=currency,
        metadata_json=json.dumps(metadata),
        provider=provider,
    )

    try:
        async with grpc.aio.insecure_channel(PAYMENT_GRPC) as channel:
            stub = payment_provider_pb2_grpc.PaymentProviderServiceStub(channel)
            response = await stub.CreateCheckout(request, timeout=10.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(exc.details() or "Create checkout failed") from exc

    return {
        "payment_url": response.payment_url,
        "transaction_ref": response.transaction_ref,
        "provider": response.provider or provider,
    }


async def get_user_wallet(user_id: str, currency: str) -> str | None:
    """Fetch the wallet id by owner + currency, returning None if not found."""
    request = wallet_pb2.OwnerWalletRequest(owner_id=user_id, currency=currency)
    try:
        async with grpc.aio.insecure_channel(WALLET_GRPC) as channel:
            stub = wallet_pb2_grpc.WalletServiceStub(channel)
            response = await stub.GetWalletByOwner(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(exc.details() or "Unable to fetch user wallet") from exc

    if not response.found or not response.wallet_id:
        return None
    return response.wallet_id


async def check_org_membership(user_id: str, org_id: str) -> bool:
    """Synchronous inter-service membership check for org-scoped escrows."""
    request = organization_pb2.OrgMembershipRequest(user_id=user_id, org_id=org_id)
    try:
        async with grpc.aio.insecure_channel(ORGANIZATION_GRPC) as channel:
            stub = organization_pb2_grpc.OrganizationServiceStub(channel)
            response = await stub.CheckOrgMembership(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to verify organization membership") from exc

    return response.is_member


async def check_organization_exists(org_id: str) -> bool:
    """Check if an organization id exists via Organization service."""
    request = organization_pb2.OrganizationExistsRequest(org_id=org_id)
    try:
        async with grpc.aio.insecure_channel(ORGANIZATION_GRPC) as channel:
            stub = organization_pb2_grpc.OrganizationServiceStub(channel)
            response = await stub.CheckOrganizationExists(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to verify organization existence") from exc

    return bool(response.exists)


async def verify_organization_secret_key(secret_key: str) -> dict:
    """Verify an organization secret API key and return org identity metadata."""
    request = organization_pb2.VerifySecretKeyRequest(secret_key=secret_key)
    try:
        async with grpc.aio.insecure_channel(ORGANIZATION_GRPC) as channel:
            stub = organization_pb2_grpc.OrganizationServiceStub(channel)
            response = await stub.VerifySecretKey(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to verify organization secret key") from exc

    if not response.valid:
        raise PermissionError("Invalid organization API key")

    return {
        "org_id": response.org_id,
        "public_key": response.public_key,
        "status": response.status,
        "is_test": bool(response.is_test),
    }
