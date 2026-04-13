"""
FastAPI route handlers for the Escrow service.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app import grpc_clients
from app.db import get_db
from app.models import (
    CounterOfferResponse,
    EscrowCreateRequest,
    EscrowResponse,
    InitializeEscrowResponse,
    InvitationAcceptRequest,
    InvitationCounterRequest,
    InvitationPrecheckResponse,
    InvitationRejectRequest,
    InvitationResendRequest,
    MilestoneResponse,
    OrganizationEscrowCreateRequest,
    PaginatedEscrowResponse,
)
from app.repository import EscrowRepository
from app.service import EscrowService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/escrow", tags=["escrow"])

ENVIRONMENT = os.getenv("ENVIRONMENT", "production").strip().lower()
IS_DEVELOPMENT = ENVIRONMENT == "development"
KYC_MIN_LEVEL = int(os.getenv("KYC_MIN_LEVEL", "1"))

USER_ESCROW_CREATE_ADAPTER = TypeAdapter(EscrowCreateRequest)
ORG_ESCROW_CREATE_ADAPTER = TypeAdapter(OrganizationEscrowCreateRequest)


# ─── Dependency helpers ───────────────────────────────────────────────────────

security = HTTPBearer(auto_error=False)


def _is_org_secret_key(token: str) -> bool:
    return token.startswith("sk_")


async def get_current_user(
    authorization: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(security),
    ],
) -> dict:
    if authorization is None or not authorization.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
        )

    if _is_org_secret_key(authorization.credentials):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization API keys can only be used on POST /escrow",
        )

    try:
        user = await grpc_clients.validate_token(authorization.credentials)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    logger.info(f"User token validated: {str(user)}")
    try:
        profile = await grpc_clients.get_user_by_id(user["user_id"])
    except RuntimeError as exc:
        logger.error(f"Failed to fetch user profile for user_id {user['user_id']}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify KYC status",
        ) from exc

    logger.info(f"User profile retrieved: {profile}")
    kyc_level = int(profile.get("kyc_level", 0))
    if not IS_DEVELOPMENT and kyc_level < KYC_MIN_LEVEL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "KYC verification is required before accessing this resource. "
                "Please complete KYC first."
            ),
        )

    # user["kyc_level"] = kyc_level
    user["email"] = profile.get("email")
    return user


async def get_create_actor(
    authorization: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(security),
    ],
) -> dict:
    if authorization is None or not authorization.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
        )

    token = authorization.credentials
    if _is_org_secret_key(token):
        try:
            org = await grpc_clients.verify_organization_secret_key(token)
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to verify organization API key",
            ) from exc

        return {
            "actor_type": "organization",
            "org_id": org["org_id"],
            "public_key": org["public_key"],
            "status": org["status"],
        }

    user = await get_current_user(authorization)
    return {
        "actor_type": "user",
        "user_id": user["user_id"],
        "email": user.get("email"),
        "kyc_level": user.get("kyc_level"),
    }


async def get_org_create_actor_from_secret_key(
    x_org_secret_key: Annotated[str | None, Header(alias="X-Org-Secret-Key")],
) -> dict:
    if not x_org_secret_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Org-Secret-Key header",
        )

    try:
        org = await grpc_clients.verify_organization_secret_key(x_org_secret_key)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify organization API key",
        ) from exc

    return {
        "actor_type": "organization",
        "org_id": org["org_id"],
        "public_key": org["public_key"],
        "status": org["status"],
    }


def get_service(db: AsyncSession = Depends(get_db)) -> EscrowService:
    return EscrowService(EscrowRepository(db))


async def build_escrow_response(
    svc: EscrowService,
    escrow,
    include_counter_history: bool = False,
) -> EscrowResponse:
    response = EscrowResponse.model_validate(escrow)
    response.status_message = svc.get_status_message(escrow)
    if not include_counter_history:
        return response

    counter_history = await svc.get_counter_history(escrow.id)
    response.counter_history = [
        CounterOfferResponse.model_validate(item) for item in counter_history
    ]
    return response


@router.post("", status_code=status.HTTP_201_CREATED, response_model=InitializeEscrowResponse)
async def initialize_escrow(
    body: EscrowCreateRequest,
    current_actor: dict = Depends(get_create_actor),
    svc: EscrowService = Depends(get_service),
):
    """Create a new escrow invitation (onetime / milestone / recurring)."""
    initiator_id = uuid.UUID(current_actor["user_id"])
    escrow, payment_url = await svc.initialize(
        data=body,
        actor_type="user",
        initiator_id=initiator_id,
        authenticated_org_id=None,
    )
    return InitializeEscrowResponse(
        escrow=await build_escrow_response(svc, escrow),
        payment_url=payment_url,
    )


@router.post(
    "/organization",
    status_code=status.HTTP_201_CREATED,
    response_model=InitializeEscrowResponse,
)
async def initialize_organization_escrow(
    body: OrganizationEscrowCreateRequest,
    org_actor: dict = Depends(get_org_create_actor_from_secret_key),
    svc: EscrowService = Depends(get_service),
):
    """Create an organization-scoped escrow using X-Org-Secret-Key authentication."""
    escrow, payment_url = await svc.initialize(
        data=body,
        actor_type="organization",
        initiator_id=None,
        authenticated_org_id=uuid.UUID(org_actor["org_id"]),
    )
    return InitializeEscrowResponse(
        escrow=await build_escrow_response(svc, escrow),
        payment_url=payment_url,
    )


@router.get("/{escrow_id}/invitation/precheck", response_model=InvitationPrecheckResponse)
async def precheck_invitation(
    escrow_id: uuid.UUID,
    token: str = Query(..., min_length=16),
    svc: EscrowService = Depends(get_service),
):
    """Public endpoint for invite token validation and account-existence routing checks."""
    return await svc.precheck_invitation(escrow_id, token)


@router.post("/{escrow_id}/accept", response_model=InitializeEscrowResponse)
async def accept_invitation(
    escrow_id: uuid.UUID,
    body: InvitationAcceptRequest,
    current_user: dict = Depends(get_current_user),
    svc: EscrowService = Depends(get_service),
):
    """Receiver accepts an invitation; pending attempts wallet lock and may activate immediately."""
    user_id = uuid.UUID(current_user["user_id"])
    escrow, payment_url = await svc.accept_invitation(escrow_id, user_id, body)
    return InitializeEscrowResponse(
        escrow=await build_escrow_response(svc, escrow, include_counter_history=True),
        payment_url=payment_url,
    )


@router.post("/{escrow_id}/reject", response_model=EscrowResponse)
async def reject_invitation(
    escrow_id: uuid.UUID,
    body: InvitationRejectRequest,
    current_user: dict = Depends(get_current_user),
    svc: EscrowService = Depends(get_service),
):
    """Receiver rejects an escrow invitation (initiator should use cancel)."""
    user_id = uuid.UUID(current_user["user_id"])
    escrow = await svc.reject_invitation(escrow_id, user_id, body)
    return await build_escrow_response(svc, escrow, include_counter_history=True)


@router.post("/{escrow_id}/counter", response_model=EscrowResponse)
async def counter_invitation(
    escrow_id: uuid.UUID,
    body: InvitationCounterRequest,
    current_user: dict = Depends(get_current_user),
    svc: EscrowService = Depends(get_service),
):
    """Counter an escrow invitation with updated terms."""
    user_id = uuid.UUID(current_user["user_id"])
    escrow = await svc.counter_invitation(escrow_id, user_id, body)
    return await build_escrow_response(svc, escrow, include_counter_history=True)


@router.post("/{escrow_id}/resend", response_model=EscrowResponse)
async def resend_invitation(
    escrow_id: uuid.UUID,
    body: InvitationResendRequest,
    current_user: dict = Depends(get_current_user),
    svc: EscrowService = Depends(get_service),
):
    """Resend an invitation (optionally with updated receiver_email for email-based invites)."""
    # CHECK: should only work if escrow is still in 'invitation' state and only initiator can resend, but leaving open for now
    user_id = uuid.UUID(current_user["user_id"])
    escrow = await svc.resend_invitation(escrow_id, user_id, body)
    return await build_escrow_response(svc, escrow)


@router.get("", response_model=PaginatedEscrowResponse)
async def list_escrows(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    current_user: dict = Depends(get_current_user),
    svc: EscrowService = Depends(get_service),
):
    """List escrows for the authenticated user (paginated)."""
    user_id = uuid.UUID(current_user["user_id"])
    result = await svc.get_escrows(
        user_id,
        current_user.get("email"),
        page,
        limit,
        status_filter,
    )
    return PaginatedEscrowResponse(
        items=[await build_escrow_response(svc, e) for e in result["items"]],
        total=result["total"],
        page=result["page"],
        limit=result["limit"],
        pages=result["pages"],
    )


@router.get("/{escrow_id}", response_model=EscrowResponse)
async def get_escrow(
    escrow_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: EscrowService = Depends(get_service),
):
    """Retrieve a single escrow by ID."""
    user_id = uuid.UUID(current_user["user_id"])
    escrow = await svc.get_escrow(escrow_id, user_id, current_user.get("email"))
    return await build_escrow_response(svc, escrow, include_counter_history=True)


# should not be able to cancel after acceptance, but allowing cancellation of pending invites for now
@router.post("/{escrow_id}/cancel", response_model=EscrowResponse)
async def cancel_escrow(
    escrow_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: EscrowService = Depends(get_service),
):
    """Cancel an escrow (unlocks funds)."""
    user_id = uuid.UUID(current_user["user_id"])
    escrow = await svc.cancel_escrow(escrow_id, user_id)
    return await build_escrow_response(svc, escrow)


@router.post("/{escrow_id}/complete", response_model=EscrowResponse)
async def complete_escrow(
    escrow_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: EscrowService = Depends(get_service),
):
    """Mark a one-time escrow as complete (buyer only)."""
    user_id = uuid.UUID(current_user["user_id"])
    escrow = await svc.mark_complete(escrow_id, user_id)
    return await build_escrow_response(svc, escrow)


@router.get("/{escrow_id}/milestones", response_model=list[MilestoneResponse])
async def list_milestones(
    escrow_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: EscrowService = Depends(get_service),
):
    """List milestones for a milestone-type escrow."""
    user_id = uuid.UUID(current_user["user_id"])
    milestones = await svc.get_milestones(escrow_id, user_id)
    return [MilestoneResponse.model_validate(m) for m in milestones]


@router.post(
    "/{escrow_id}/milestones/{milestone_id}/deliver",
    response_model=MilestoneResponse,
)
async def deliver_milestone(
    escrow_id: uuid.UUID,
    milestone_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: EscrowService = Depends(get_service),
):
    """Seller marks a milestone as delivered."""
    user_id = uuid.UUID(current_user["user_id"])
    milestone = await svc.deliver_milestone(escrow_id, milestone_id, user_id)
    return MilestoneResponse.model_validate(milestone)


# should only work if milestone is in 'delivered' state and only buyer can approve, but leaving open for now
@router.post(
    "/{escrow_id}/milestones/{milestone_id}/approve",
    response_model=MilestoneResponse,
)
async def approve_milestone(
    escrow_id: uuid.UUID,
    milestone_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    svc: EscrowService = Depends(get_service),
):
    """Buyer approves a delivered milestone (releases funds)."""
    user_id = uuid.UUID(current_user["user_id"])
    milestone = await svc.approve_milestone(escrow_id, milestone_id, user_id)
    return MilestoneResponse.model_validate(milestone)


# LATER: maybe implement this later but for now we don't need contributor
# @router.post(
#     "/{escrow_id}/contributors/join", response_model=RecurringContributorResponse
# )
# async def join_cycle(
#     escrow_id: uuid.UUID,
#     body: ContributorJoinRequest,
#     current_user: dict = Depends(get_current_user),
#     svc: EscrowService = Depends(get_service),
# ):
#     """Join a recurring escrow cycle as a contributor."""
#     user_id = uuid.UUID(current_user["user_id"])
#     contributor = await svc.join_cycle(escrow_id, user_id, body)
#     return RecurringContributorResponse.model_validate(contributor)
