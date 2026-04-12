"""gRPC client stubs for the Admin service."""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import grpc
import grpc.aio
from google.protobuf import struct_pb2

_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

_PROTO_DIR = _APP_DIR.parent / "proto"
if str(_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTO_DIR))

_ESCROW_PROTO_DIR = _APP_DIR.parent.parent / "escrow" / "proto"
if str(_ESCROW_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_ESCROW_PROTO_DIR))

proto_module = sys.modules.setdefault("proto", type(sys)("proto"))
proto_paths = list(getattr(proto_module, "__path__", []))
if str(_PROTO_DIR) not in proto_paths:
    proto_module.__path__ = [*proto_paths, str(_PROTO_DIR)]
if str(_ESCROW_PROTO_DIR) not in getattr(proto_module, "__path__", []):
    proto_module.__path__ = [*proto_module.__path__, str(_ESCROW_PROTO_DIR)]

import proto.audit_pb2 as audit_pb2
import proto.audit_pb2_grpc as audit_pb2_grpc
import proto.auth_pb2 as auth_pb2
import proto.auth_pb2_grpc as auth_pb2_grpc
import proto.dispute_pb2 as dispute_pb2
import proto.dispute_pb2_grpc as dispute_pb2_grpc
import proto.escrow_pb2 as escrow_pb2
import proto.escrow_pb2_grpc as escrow_pb2_grpc
import proto.fee_pb2 as fee_pb2
import proto.fee_pb2_grpc as fee_pb2_grpc
import proto.payout_pb2 as payout_pb2
import proto.payout_pb2_grpc as payout_pb2_grpc
import proto.user_pb2 as user_pb2
import proto.user_pb2_grpc as user_pb2_grpc

logger = logging.getLogger(__name__)

USER_GRPC = os.getenv("USER_GRPC", "user-service:50051")
AUTH_GRPC = os.getenv("AUTH_GRPC", "auth-service:50051")
PAYOUT_GRPC = os.getenv("PAYOUT_GRPC", "payout-service:50051")
AUDIT_GRPC = os.getenv("AUDIT_GRPC", "audit-service:50051")
DISPUTE_GRPC = os.getenv("DISPUTE_GRPC", "dispute-service:50051")
FEE_GRPC = os.getenv("FEE_GRPC", "fee-service:50051")
ESCROW_GRPC = os.getenv("ESCROW_GRPC", "escrow-service:50051")


# async def update_email_verifiication_status(user_id: str, is_verified: bool):
#     import auth.proto.user_pb2 as user_pb2
#     import auth.proto.user_pb2_grpc as user_pb2_grpc

#     request = user_pb2.UpdateVerificationRequest(
#         user_id=user_id, is_verified=is_verified
#     )


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
        "scopes": list(response.scopes),
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


async def get_all_users(offset: int, limit: int) -> list[dict]:
    request = user_pb2.ListUsersRequest(offset=offset, limit=limit)

    try:
        async with grpc.aio.insecure_channel(USER_GRPC) as channel:
            stub = user_pb2_grpc.UserServiceStub(channel)
            response = await stub.ListUsers(request, timeout=5.0)
            return [
                {
                    "id": user.user_id,
                    "email": user.email,
                    "role": user.role,
                    "is_active": not user.is_banned,
                }
                for user in response.users
            ]
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(f"User service sync failed: {exc.details()}") from exc


async def update_user_role(user_id: uuid.UUID, role: str) -> dict:
    request = user_pb2.UpdateRoleRequest(user_id=str(user_id), role=role)

    try:
        async with grpc.aio.insecure_channel(USER_GRPC) as channel:
            stub = user_pb2_grpc.UserServiceStub(channel)
            response = await stub.UpdateRole(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(f"User service sync failed: {exc.details()}") from exc

    if not response.success:
        raise RuntimeError(response.message or "User service sync failed")

    return {
        "id": str(user_id),
        "role": role,
    }


async def ban_user(user_id: uuid.UUID, ban: bool, reason: str) -> dict:
    request = user_pb2.BanUserRequest(user_id=str(user_id), ban=ban, reason=reason)

    try:
        async with grpc.aio.insecure_channel(USER_GRPC) as channel:
            stub = user_pb2_grpc.UserServiceStub(channel)
            response = await stub.BanUser(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(f"User service sync failed: {exc.details()}") from exc

    if not response.success:
        raise RuntimeError(response.message or "User service sync failed")

    return {
        "id": str(user_id),
        "is_active": not ban,
    }


async def update_user_verification(user_id: uuid.UUID, is_verified: bool) -> dict:
    request = user_pb2.UpdateVerificationRequest(
        user_id=str(user_id),
        is_verified=is_verified,
    )

    try:
        async with grpc.aio.insecure_channel(USER_GRPC) as channel:
            stub = user_pb2_grpc.UserServiceStub(channel)
            response = await stub.UpdateVerification(request, timeout=5.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(f"User verification sync failed: {exc.details()}") from exc

    if not response.success:
        raise RuntimeError(response.message or "User verification sync failed")

    return {
        "id": str(user_id),
        "is_verified": is_verified,
    }


async def get_platform_stats() -> dict:
    """Aggregate currently available platform stats from existing gRPC services."""
    request = user_pb2.ListUsersRequest(offset=0, limit=1)
    total_users = 0

    try:
        async with grpc.aio.insecure_channel(USER_GRPC) as channel:
            stub = user_pb2_grpc.UserServiceStub(channel)
            response = await stub.ListUsers(request, timeout=5.0)
            total_users = response.total
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError(f"User service stats fetch failed: {exc.details()}") from exc

    return {
        "total_users": total_users,
        "total_escrows": 0,
        "total_transactions": 0,
        "total_volume": 0,
    }


def _dict_to_struct(data: dict[str, Any] | None) -> struct_pb2.Struct:
    struct = struct_pb2.Struct()
    normalized = data or {}
    try:
        struct.update(normalized)
    except Exception:
        struct.update(json.loads(json.dumps(normalized, default=str)))
    return struct


async def emit_audit_log(
    *,
    actor_id: uuid.UUID,
    action: str,
    resource: str,
    resource_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    request = audit_pb2.EmitAuditLogRequest(
        actor_id=str(actor_id),
        action=action,
        resource=resource,
        resource_id=str(resource_id) if resource_id else "",
        before=_dict_to_struct(before),
        after=_dict_to_struct(after),
        metadata=_dict_to_struct(metadata),
    )

    try:
        async with grpc.aio.insecure_channel(AUDIT_GRPC) as channel:
            stub = audit_pb2_grpc.AuditServiceStub(channel)
            response = await stub.EmitAuditLog(request, timeout=5.0)
            if not response.success:
                logger.warning(
                    "audit grpc call returned success=False action=%s resource=%s resource_id=%s",
                    action,
                    resource,
                    resource_id,
                )
    except Exception:
        logger.exception(
            "failed to emit audit log action=%s resource=%s resource_id=%s",
            action,
            resource,
            resource_id,
        )


async def list_payouts(
    *,
    status_filter: str | None,
    page: int,
    limit: int,
) -> dict[str, Any]:
    request = payout_pb2.ListPayoutsRequest(
        status=status_filter or "",
        page=page,
        limit=limit,
    )

    try:
        async with grpc.aio.insecure_channel(PAYOUT_GRPC) as channel:
            stub = payout_pb2_grpc.PayoutServiceStub(channel)
            response = await stub.ListPayouts(request, timeout=10.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to list payouts from payout service") from exc

    items: list[dict[str, Any]] = []
    for item in response.items:
        items.append(
            {
                "id": item.id,
                "user_id": item.user_id,
                "wallet_id": item.wallet_id,
                "amount": int(item.amount),
                "currency": item.currency,
                "bank_code": item.bank_code,
                "account_number": item.account_number,
                "account_name": item.account_name,
                "status": item.status,
                "provider": item.provider or None,
                "provider_ref": item.provider_ref or None,
                "failure_reason": item.failure_reason or None,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
        )

    return {
        "items": items,
        "total": int(response.total),
        "page": int(response.page),
        "limit": int(response.limit),
        "pages": int(response.pages),
    }


async def retry_payout_transfer(*, payout_id: uuid.UUID) -> dict[str, Any]:
    request = payout_pb2.RetryPayoutTransferRequest(payout_id=str(payout_id))

    try:
        async with grpc.aio.insecure_channel(PAYOUT_GRPC) as channel:
            stub = payout_pb2_grpc.PayoutServiceStub(channel)
            response = await stub.RetryPayoutTransfer(request, timeout=12.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to retry payout transfer") from exc

    return {
        "id": response.id,
        "user_id": response.user_id,
        "wallet_id": response.wallet_id,
        "amount": int(response.amount),
        "currency": response.currency,
        "bank_code": response.bank_code,
        "account_number": response.account_number,
        "account_name": response.account_name,
        "status": response.status,
        "provider": response.provider or None,
        "provider_ref": response.provider_ref or None,
        "failure_reason": response.failure_reason or None,
        "created_at": response.created_at,
        "updated_at": response.updated_at,
    }


def _dispute_response_to_dict(item: dispute_pb2.DisputeResponse) -> dict[str, Any]:
    return {
        "id": item.id,
        "escrow_id": item.escrow_id,
        "raised_by": item.raised_by,
        "reason": item.reason,
        "description": item.description,
        "status": item.status,
        "resolution_note": item.resolution_note or None,
        "resolved_by": item.resolved_by or None,
        "resolved_at": item.resolved_at or None,
        "created_at": item.created_at,
    }


async def list_disputes(
    *,
    token: str,
    status_filter: str | None,
    page: int,
    limit: int,
) -> dict[str, Any]:
    _ = token
    request = dispute_pb2.ListDisputesRequest(
        status=status_filter or "",
        page=page,
        limit=limit,
    )

    try:
        async with grpc.aio.insecure_channel(DISPUTE_GRPC) as channel:
            stub = dispute_pb2_grpc.DisputeServiceStub(channel)
            response = await stub.ListDisputes(request, timeout=10.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to list disputes from dispute service") from exc

    return {
        "items": [_dispute_response_to_dict(item) for item in response.items],
        "total": int(response.total),
        "page": int(response.page),
        "limit": int(response.limit),
        "pages": int(response.pages),
    }


async def mark_dispute_under_review(
    *,
    dispute_id: uuid.UUID,
    token: str,
    note: str,
    reviewer_id: uuid.UUID,
) -> dict[str, Any]:
    _ = token
    request = dispute_pb2.MarkDisputeUnderReviewRequest(
        dispute_id=str(dispute_id),
        reviewer_id=str(reviewer_id),
        note=note,
    )

    try:
        async with grpc.aio.insecure_channel(DISPUTE_GRPC) as channel:
            stub = dispute_pb2_grpc.DisputeServiceStub(channel)
            response = await stub.MarkDisputeUnderReview(request, timeout=10.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to move dispute to review") from exc

    return _dispute_response_to_dict(response)


async def request_dispute_resolution(
    *,
    escrow_id: uuid.UUID,
    dispute_id: uuid.UUID,
    token: str,
    resolution: str,
    resolution_note: str,
    admin_id: uuid.UUID,
) -> dict[str, Any]:
    _ = escrow_id
    _ = token
    request = dispute_pb2.RequestDisputeResolutionRequest(
        dispute_id=str(dispute_id),
        admin_id=str(admin_id),
        resolution=resolution,
        resolution_note=resolution_note,
    )

    try:
        async with grpc.aio.insecure_channel(DISPUTE_GRPC) as channel:
            stub = dispute_pb2_grpc.DisputeServiceStub(channel)
            response = await stub.RequestDisputeResolution(request, timeout=12.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to queue dispute resolution") from exc

    return _dispute_response_to_dict(response)


async def execute_dispute_resolution(
    *,
    dispute_id: uuid.UUID,
    resolution: str,
    admin_id: uuid.UUID,
) -> dict[str, Any]:
    request = dispute_pb2.ExecuteDisputeResolutionRequest(
        dispute_id=str(dispute_id),
        resolution=resolution,
        admin_id=str(admin_id),
    )

    try:
        async with grpc.aio.insecure_channel(DISPUTE_GRPC) as channel:
            stub = dispute_pb2_grpc.DisputeServiceStub(channel)
            response = await stub.ExecuteDisputeResolution(request, timeout=12.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to execute dispute resolution") from exc

    return _dispute_response_to_dict(response)


async def refund_fee_for_escrow(*, escrow_id: uuid.UUID) -> list[dict[str, Any]]:
    request = fee_pb2.RefundFeeForEscrowRequest(escrow_id=str(escrow_id))

    try:
        async with grpc.aio.insecure_channel(FEE_GRPC) as channel:
            stub = fee_pb2_grpc.FeeServiceStub(channel)
            response = await stub.RefundFeeForEscrow(request, timeout=8.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to refund fee for escrow") from exc

    return [
        {
            "id": item.id,
            "escrow_id": item.escrow_id,
            "fee_type": item.fee_type,
            "amount": int(item.amount),
            "currency": item.currency,
            "paid_by": item.paid_by,
            "status": item.status,
            "created_at": item.created_at,
        }
        for item in response.items
    ]


async def get_escrow(*, escrow_id: uuid.UUID) -> dict[str, Any]:
    request = escrow_pb2.EscrowRequest(escrow_id=str(escrow_id))

    try:
        async with grpc.aio.insecure_channel(ESCROW_GRPC) as channel:
            stub = escrow_pb2_grpc.EscrowServiceStub(channel)
            response = await stub.GetEscrow(request, timeout=8.0)
    except grpc.aio.AioRpcError as exc:
        raise RuntimeError("Unable to fetch escrow details") from exc

    return {
        "escrow_id": response.escrow_id,
        "status": response.status,
        "escrow_type": response.escrow_type,
        "initiator_id": response.initiator_id or None,
        "receiver_id": response.receiver_id or None,
        "amount": int(response.amount),
        "currency": response.currency,
    }
