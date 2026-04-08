"""
Business logic for the Escrow service.

Implements the dispatcher pattern:
  initialize() → create_onetime / create_milestone_escrow / create_recurring

State machine:
  pending  → active | cancelled
    active   → completed | disputed
    disputed → completed | refunded
  completed, cancelled, refunded → (terminal)
"""

from __future__ import annotations

import hashlib
import math
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from app import grpc_clients
from app.db import Escrow, Milestone, RecurringContributor
from app.messaging import publish
from app.models import (
    BaseEscrowCreate,
    EscrowCreateRequest,
    InvitationAcceptRequest,
    InvitationCounterRequest,
    InvitationPrecheckResponse,
    InvitationRejectRequest,
    InvitationResendRequest,
    MilestoneEscrowCreate,
    OneTimeEscrowCreate,
    RecurringEscrowCreate,
)
from app.repository import EscrowRepository
from app.settings import (
    INVITATION_EXPIRY_HOURS,
    MAX_FEE_AMOUNT,
    MIN_FEE_AMOUNT,
    PLATFORM_FEE_PERCENT,
)

# ─── State machine ────────────────────────────────────────────────────────────

# V3 invitation/negotiation states:
# invited -> pending | counter_pending_counterparty | rejected | expired | cancelled
# counter_pending_initiator -> pending | counter_pending_counterparty | cancelled | expired
# counter_pending_counterparty -> pending | counter_pending_initiator | rejected | cancelled | expired

VALID_TRANSITIONS_V3: dict[str, dict[str, list[str]]] = {
    "invited": {
        "initiator": ["cancelled"],
        "counterparty": [
            "pending",
            "counter_pending_counterparty",
            "rejected",
        ],
        "system": ["expired"],
    },
    "counter_pending_initiator": {
        "initiator": [
            "pending",
            "counter_pending_counterparty",
            "cancelled",
        ],
        "counterparty": [],
        "system": ["expired"],
    },
    "counter_pending_counterparty": {
        "initiator": ["cancelled"],
        "counterparty": [
            "pending",
            "counter_pending_initiator",
            "rejected",
        ],
        "system": ["expired"],
    },
    "pending": {
        "initiator": ["cancelled"],
        "counterparty": ["cancelled"],
        "system": ["active"],
    },
    "active": {
        "initiator": ["disputed"],
        "counterparty": ["disputed"],
        "system": ["completed"],
    },
    "disputed": {
        "initiator": [],
        "counterparty": [],
        "admin_or_resolution_engine": ["completed", "refunded"],
    },
    "rejected": {},
    "expired": {},
    "completed": {},
    "cancelled": {},
    "refunded": {},
}
INVITATION_PRECHECK_STATUSES = {
    "invited",
    "counter_pending_initiator",
    "counter_pending_counterparty",
}

COUNTER_PENDING_STATUSES = {
    "counter_pending_initiator",
    "counter_pending_counterparty",
}

INVITATION_WINDOW_STATUSES = {
    "invited",
    "counter_pending_initiator",
    "counter_pending_counterparty",
}


def _calculate_fee(amount: int) -> int:
    """Fee is percentage-based and capped using runtime settings."""
    fee = math.floor(amount * (PLATFORM_FEE_PERCENT / 100))
    return max(MIN_FEE_AMOUNT, min(fee, MAX_FEE_AMOUNT))


def _generate_invite_token() -> str:
    return secrets.token_urlsafe(32)


def _hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _temporary_transaction_ref() -> str:
    return f"invite-{uuid.uuid4()}"


class EscrowService:
    def __init__(self, repo: EscrowRepository) -> None:
        self.repo = repo

    def _resolve_buyer_and_seller_ids(
        self,
        escrow: Escrow,
    ) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        """Resolve buyer/seller participants based on initiator_role."""
        if escrow.initiator_role == "buyer":
            return escrow.initiator_id, escrow.receiver_id
        if escrow.initiator_role == "seller":
            return escrow.receiver_id, escrow.initiator_id
        # broker and other future roles: fall back to initiator as payer for now
        return escrow.initiator_id, escrow.receiver_id

    def _resolve_actor_for_user(
        self,
        escrow: Escrow,
        user_id: uuid.UUID,
        user_email: str | None = None,
    ) -> str | None:
        if user_id == escrow.initiator_id:
            return "initiator"
        if escrow.receiver_id is not None and user_id == escrow.receiver_id:
            return "counterparty"
        if (
            user_email
            and escrow.receiver_email
            and escrow.receiver_email.lower() == user_email.lower()
        ):
            return "counterparty"
        return None

    def _assert_transition_allowed(
        self,
        current_status: str,
        new_status: str,
        actor: str,
    ) -> None:
        allowed = VALID_TRANSITIONS_V3.get(current_status, {}).get(actor, [])
        if new_status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Actor '{actor}' cannot transition from "
                    f"'{current_status}' to '{new_status}'"
                ),
            )

    # ── Core dispatcher ───────────────────────────────────────────────────────

    async def initialize(
        self,
        data: EscrowCreateRequest,
        actor_type: str,
        initiator_id: uuid.UUID | None,
        authenticated_org_id: uuid.UUID | None,
    ) -> tuple[Escrow, str | None]:
        """
        Route to the correct sub-handler based on escrow_type.
        Returns (escrow, payment_url).
        """
        self._enforce_organization_role_rules(data)
        await self._normalize_and_validate_receiver(data)

        if data.seller_type == "organization":
            if actor_type != "organization":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Organization-scoped escrow creation requires organization API key authentication",
                )
            if authenticated_org_id is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Unable to resolve authenticated organization",
                )
            if data.org_id != authenticated_org_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Payload org_id does not match authenticated organization",
                )

            initiator_actor_type = "organization"
            create_initiator_id = None
            create_initiator_org_id = authenticated_org_id
        else:
            if actor_type != "user" or initiator_id is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User bearer authentication is required for individual escrow creation",
                )
            initiator_actor_type = "user"
            create_initiator_id = initiator_id
            create_initiator_org_id = None

        if isinstance(data, OneTimeEscrowCreate):
            return await self.create_onetime(
                data,
                create_initiator_id,
                initiator_actor_type,
                create_initiator_org_id,
            )
        if isinstance(data, MilestoneEscrowCreate):
            return await self.create_milestone_escrow(
                data,
                create_initiator_id,
                initiator_actor_type,
                create_initiator_org_id,
            )
        if isinstance(data, RecurringEscrowCreate):
            return await self.create_recurring(
                data,
                create_initiator_id,
                initiator_actor_type,
                create_initiator_org_id,
            )

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown escrow_type: {data.escrow_type}",
        )

    def _enforce_organization_role_rules(self, data: BaseEscrowCreate) -> None:
        if data.seller_type == "organization" and data.initiator_role != "seller":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Organization-scoped escrow can only be initiated as seller "
                    "(initiator_role='seller')"
                ),
            )

    async def _normalize_and_validate_receiver(self, data: BaseEscrowCreate) -> None:
        if data.receiver_id is None and data.receiver_email is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either receiver_id or receiver_email must be provided",
            )
        if data.receiver_id is not None and data.receiver_email is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Provide either receiver_id or receiver_email, not both",
            )

        if data.receiver_email is not None:
            receiver_user = await grpc_clients.get_user_by_email(
                str(data.receiver_email)
            )
            if receiver_user:
                data.receiver_id = uuid.UUID(receiver_user["user_id"])
                data.receiver_email = receiver_user["email"]

            return

        if data.receiver_id is not None:
            try:
                receiver_profile = await grpc_clients.get_user_by_id(
                    str(data.receiver_id)
                )
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Unable to verify receiver profile",
                ) from exc

            if receiver_profile is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="receiver_id does not correspond to a valid user",
                )

            data.receiver_email = receiver_profile["email"]

            return

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid request provided"
        )

    # ── Pagination helper ─────────────────────────────────────────────────────

    async def get_escrows(
        self,
        user_id: uuid.UUID,
        user_email: str | None,
        page: int,
        limit: int,
        status_filter: str | None,
    ) -> dict:
        offset = (page - 1) * limit
        items, total = await self.repo.list_by_user(
            user_id,
            user_email,
            offset,
            limit,
            status_filter,
        )
        pages = math.ceil(total / limit) if limit else 1
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
        }

    # ── Single escrow access ──────────────────────────────────────────────────

    def _is_invited_email_viewer(
        self,
        escrow: Escrow,
        user_email: str | None,
    ) -> bool:
        if not user_email or not escrow.receiver_email:
            return False

        return (
            escrow.receiver_id is None
            and escrow.status in INVITATION_PRECHECK_STATUSES
            and escrow.receiver_email.lower() == user_email.lower()
        )

    async def get_escrow(
        self,
        escrow_id: uuid.UUID,
        user_id: uuid.UUID,
        user_email: str | None = None,
    ) -> Escrow:
        escrow = await self.repo.get_by_id(escrow_id)
        if not escrow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Escrow not found"
            )
        if (
            escrow.initiator_id != user_id
            and escrow.receiver_id != user_id
            and not self._is_invited_email_viewer(escrow, user_email)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this escrow",
            )
        return escrow

    # ── State machine ─────────────────────────────────────────────────────────

    async def transition_status(
        self,
        escrow: Escrow,
        new_status: str,
        actor: str,
    ) -> Escrow:
        self._assert_transition_allowed(escrow.status, new_status, actor)
        return await self.repo.update_status(escrow, new_status)

    async def _attempt_wallet_lock_and_transition(
        self,
        escrow: Escrow,
        actor: str,
    ) -> tuple[Escrow, str | None]:
        """Move escrow to pending and attempt immediate wallet lock.

        If buyer has sufficient balance, lock funds and activate escrow immediately.
        Otherwise escrow remains pending until wallet is funded.
        """
        self._assert_transition_allowed(escrow.status, "pending", actor)
        escrow.status = "pending"
        escrow = await self.repo.save(escrow)
        await publish(
            "escrow.created",
            {
                "escrow_id": str(escrow.id),
                "escrow_type": escrow.escrow_type,
                "amount": escrow.amount,
                "offer_version": escrow.offer_version,
            },
        )

        buyer_id, _ = self._resolve_buyer_and_seller_ids(escrow)
        if buyer_id is None:
            return escrow, None

        buyer_wallet_id = await grpc_clients.get_user_wallet(
            str(buyer_id), escrow.currency
        )
        if not buyer_wallet_id:
            return escrow, None

        try:
            await grpc_clients.lock_funds(
                wallet_id=buyer_wallet_id,
                amount=escrow.amount,
                reference=escrow.transaction_ref,
                escrow_id=str(escrow.id),
            )
        except RuntimeError as exc:
            if "INSUFFICIENT_BALANCE" in str(exc):
                return escrow, None
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to lock buyer wallet funds",
            ) from exc

        self._assert_transition_allowed(escrow.status, "active", "system")
        escrow.status = "active"
        escrow.funded_at = datetime.now(timezone.utc)
        escrow = await self.repo.save(escrow)
        await publish(
            "escrow.activated",
            {
                "escrow_id": str(escrow.id),
                "transaction_ref": escrow.transaction_ref,
                "activation_source": "wallet_lock",
            },
        )
        return escrow, None

    # ── Cancel ────────────────────────────────────────────────────────────────

    async def cancel_escrow(self, escrow_id: uuid.UUID, user_id: uuid.UUID) -> Escrow:
        escrow = await self.get_escrow(escrow_id, user_id)
        was_funded = escrow.funded_at is not None
        if escrow.status not in {
            "invited",
            "counter_pending_initiator",
            "counter_pending_counterparty",
            "pending",
        }:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot cancel escrow with status '{escrow.status}'",
            )

        if escrow.status == "invited" and user_id != escrow.initiator_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only initiator can cancel an invited escrow",
            )

        if escrow.status in COUNTER_PENDING_STATUSES and user_id != escrow.initiator_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only initiator can cancel while invitation negotiation is pending",
            )

        actor = self._resolve_actor_for_user(escrow, user_id)
        if actor is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only escrow participants can cancel",
            )

        escrow = await self.transition_status(escrow, "cancelled", actor)
        escrow.cancelled_at = datetime.now(timezone.utc)
        await self.repo.save(escrow)

        buyer_id, _ = self._resolve_buyer_and_seller_ids(escrow)
        if was_funded and escrow.transaction_ref and buyer_id:
            wallet_id = await grpc_clients.get_user_wallet(
                str(buyer_id), escrow.currency
            )
            if wallet_id:
                await grpc_clients.unlock_funds(
                    wallet_id=wallet_id,
                    amount=escrow.amount,
                    reference=escrow.transaction_ref,
                    escrow_id=str(escrow.id),
                )

        await publish(
            "escrow.cancelled",
            {
                "escrow_id": str(escrow.id),
                "transaction_ref": escrow.transaction_ref,
                "initiator_id": (
                    str(escrow.initiator_id) if escrow.initiator_id else None
                ),
                "initiator_org_id": (
                    str(escrow.initiator_org_id) if escrow.initiator_org_id else None
                ),
                "receiver_id": str(escrow.receiver_id) if escrow.receiver_id else None,
                "amount": escrow.amount,
                "currency": escrow.currency,
            },
        )
        return escrow

    # ── One-time ──────────────────────────────────────────────────────────────

    async def create_onetime(
        self,
        data: OneTimeEscrowCreate,
        initiator_id: uuid.UUID | None,
        initiator_actor_type: str,
        initiator_org_id: uuid.UUID | None,
    ) -> tuple[Escrow, str | None]:
        fee = _calculate_fee(data.amount)
        now = datetime.now(timezone.utc)
        invite_token = _generate_invite_token() if data.receiver_id is None else None
        invite_token_hash = (
            _hash_invite_token(invite_token) if invite_token is not None else None
        )
        escrow = await self.repo.create(
            transaction_ref=_temporary_transaction_ref(),
            escrow_type="onetime",
            status="invited",
            initiator_actor_type=initiator_actor_type,
            initiator_id=initiator_id,
            initiator_org_id=initiator_org_id,
            receiver_id=data.receiver_id,
            receiver_email=data.receiver_email,  # always gonna be a receiver email
            org_id=data.org_id,
            initiator_role=data.initiator_role,
            title=data.title,
            description=data.description,
            currency=data.currency,
            amount=data.amount,
            fee_amount=fee,
            acceptance_criteria=data.acceptance_criteria,
            inspection_period=data.inspection_period,
            delivery_date=data.delivery_date,
            dispute_window=data.dispute_window,
            how_dispute_handled=data.how_dispute_handled,
            who_pays_fees=data.who_pays_fees,
            provider=data.provider,
            invite_token_hash=invite_token_hash,
            invite_expires_at=now + timedelta(hours=INVITATION_EXPIRY_HOURS),
            initiator_accepted_at=now if initiator_id is not None else None,
            is_test=data.is_test,
        )
        await publish(
            "escrow.invite_received",
            {
                "escrow_id": str(escrow.id),
                "escrow_type": "onetime",
                "amount": escrow.amount,
                "initiator_actor_type": escrow.initiator_actor_type,
                "initiator_org_id": (
                    str(escrow.initiator_org_id) if escrow.initiator_org_id else None
                ),
                "receiver_id": str(escrow.receiver_id) if escrow.receiver_id else None,
                "receiver_email": escrow.receiver_email,
                "invite_token": invite_token,
                "offer_version": escrow.offer_version,
            },
        )
        return escrow, None

    async def mark_complete(self, escrow_id: uuid.UUID, user_id: uuid.UUID) -> Escrow:
        escrow = await self.get_escrow(escrow_id, user_id)
        if escrow.initiator_id != user_id or escrow.initiator_role != "buyer":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the buyer (initiator) can mark an escrow as complete",
            )
        escrow = await self.transition_status(escrow, "completed", "system")
        escrow.completed_at = datetime.now(timezone.utc)
        await self.repo.save(escrow)

        buyer_id, seller_id = self._resolve_buyer_and_seller_ids(escrow)
        buyer_wallet = (
            await grpc_clients.get_user_wallet(str(buyer_id), escrow.currency)
            if buyer_id
            else None
        )
        seller_wallet = (
            await grpc_clients.get_user_wallet(str(seller_id), escrow.currency)
            if seller_id
            else None
        )
        if buyer_wallet and seller_wallet:
            await grpc_clients.release_funds(
                from_wallet_id=buyer_wallet,
                to_wallet_id=seller_wallet,
                amount=escrow.amount,
                reference=escrow.transaction_ref,
                escrow_id=str(escrow.id),
            )

        await publish(
            "escrow.completed",
            {
                "escrow_id": str(escrow.id),
                "transaction_ref": escrow.transaction_ref,
                "amount": escrow.amount,
                "currency": escrow.currency,
            },
        )
        return escrow

    # ── Milestone ─────────────────────────────────────────────────────────────

    async def create_milestone_escrow(
        self,
        data: MilestoneEscrowCreate,
        initiator_id: uuid.UUID | None,
        initiator_actor_type: str,
        initiator_org_id: uuid.UUID | None,
    ) -> tuple[Escrow, str | None]:
        total_amount = sum(m.amount for m in data.milestones)
        fee = _calculate_fee(total_amount)
        now = datetime.now(timezone.utc)
        invite_token = _generate_invite_token() if data.receiver_id is None else None
        invite_token_hash = (
            _hash_invite_token(invite_token) if invite_token is not None else None
        )
        escrow = await self.repo.create(
            transaction_ref=_temporary_transaction_ref(),
            escrow_type="milestone",
            status="invited",
            initiator_actor_type=initiator_actor_type,
            initiator_id=initiator_id,
            initiator_org_id=initiator_org_id,
            receiver_id=data.receiver_id,
            receiver_email=(str(data.receiver_email) if data.receiver_email else None),
            org_id=data.org_id,
            initiator_role=data.initiator_role,
            title=data.title,
            description=data.description,
            currency=data.currency,
            amount=total_amount,
            fee_amount=fee,
            acceptance_criteria=data.acceptance_criteria,
            inspection_period=data.inspection_period,
            delivery_date=data.delivery_date,
            dispute_window=data.dispute_window,
            how_dispute_handled=data.how_dispute_handled,
            who_pays_fees=data.who_pays_fees,
            provider=data.provider,
            invite_token_hash=invite_token_hash,
            invite_expires_at=now + timedelta(hours=INVITATION_EXPIRY_HOURS),
            initiator_accepted_at=now if initiator_id is not None else None,
            is_test=data.is_test,
        )
        for ms in data.milestones:
            await self.repo.create_milestone(
                escrow_id=escrow.id,
                title=ms.title,
                description=ms.description,
                amount=ms.amount,
                due_date=ms.due_date,
                inspection_hrs=ms.inspection_hrs,
                sort_order=ms.sort_order,
            )
        await publish(
            "escrow.invite_received",
            {
                "escrow_id": str(escrow.id),
                "escrow_type": "milestone",
                "amount": total_amount,
                "milestone_count": len(data.milestones),
                "initiator_actor_type": escrow.initiator_actor_type,
                "initiator_org_id": (
                    str(escrow.initiator_org_id) if escrow.initiator_org_id else None
                ),
                "receiver_id": str(escrow.receiver_id) if escrow.receiver_id else None,
                "receiver_email": escrow.receiver_email,
                "invite_token": invite_token,
                "offer_version": escrow.offer_version,
            },
        )
        return escrow, None

    async def deliver_milestone(
        self,
        escrow_id: uuid.UUID,
        milestone_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Milestone:
        escrow = await self.get_escrow(escrow_id, user_id)
        # The seller is the receiver (or the initiator when role is "seller")
        is_seller = escrow.receiver_id == user_id or (
            escrow.initiator_id == user_id and escrow.initiator_role == "seller"
        )
        if not is_seller:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the seller can mark a milestone as delivered",
            )
        milestone = await self.repo.get_milestone(milestone_id)
        if not milestone or milestone.escrow_id != escrow_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Milestone not found"
            )
        if milestone.status not in ("pending", "in_progress"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot deliver milestone in status '{milestone.status}'",
            )
        milestone = await self.repo.update_milestone(
            milestone,
            status="delivered",
            delivered_at=datetime.now(timezone.utc),
        )
        await publish(
            "milestone.delivered",
            {"escrow_id": str(escrow_id), "milestone_id": str(milestone_id)},
        )
        return milestone

    async def approve_milestone(
        self,
        escrow_id: uuid.UUID,
        milestone_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Milestone:
        escrow = await self.get_escrow(escrow_id, user_id)
        is_buyer = escrow.initiator_id == user_id and escrow.initiator_role == "buyer"
        if not is_buyer:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the buyer can approve a milestone",
            )
        milestone = await self.repo.get_milestone(milestone_id)
        if not milestone or milestone.escrow_id != escrow_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Milestone not found"
            )
        if milestone.status != "delivered":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Milestone must be delivered before it can be approved",
            )
        milestone = await self.repo.update_milestone(
            milestone,
            status="completed",
            completed_at=datetime.now(timezone.utc),
        )

        # Release funds for this milestone
        receiver_wallet = (
            await grpc_clients.get_user_wallet(str(escrow.receiver_id), escrow.currency)
            if escrow.receiver_id
            else None
        )
        initiator_wallet = await grpc_clients.get_user_wallet(
            str(escrow.initiator_id), escrow.currency
        )
        if initiator_wallet and receiver_wallet:
            await grpc_clients.release_funds(
                from_wallet_id=initiator_wallet,
                to_wallet_id=receiver_wallet,
                amount=milestone.amount,
                reference=escrow.transaction_ref,
                escrow_id=str(escrow.id),
            )

        # Check if all milestones are completed → complete the escrow
        all_milestones = await self.repo.get_milestones(escrow_id)
        all_done = all(m.status == "completed" for m in all_milestones)
        if all_done:
            escrow = await self.transition_status(escrow, "completed", "system")
            escrow.completed_at = datetime.now(timezone.utc)
            await self.repo.save(escrow)
            await publish(
                "escrow.completed",
                {
                    "escrow_id": str(escrow_id),
                    "transaction_ref": escrow.transaction_ref,
                },
            )

        await publish(
            "milestone.approved",
            {"escrow_id": str(escrow_id), "milestone_id": str(milestone_id)},
        )
        return milestone

    async def get_milestones(
        self, escrow_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[Milestone]:
        await self.get_escrow(escrow_id, user_id)
        return await self.repo.get_milestones(escrow_id)

    # ── Recurring ─────────────────────────────────────────────────────────────

    async def create_recurring(
        self,
        data: RecurringEscrowCreate,
        initiator_id: uuid.UUID | None,
        initiator_actor_type: str,
        initiator_org_id: uuid.UUID | None,
    ) -> tuple[Escrow, str | None]:
        fee = _calculate_fee(data.cycle.expected_amount)
        now = datetime.now(timezone.utc)
        invite_token = _generate_invite_token() if data.receiver_id is None else None
        invite_token_hash = (
            _hash_invite_token(invite_token) if invite_token is not None else None
        )
        escrow = await self.repo.create(
            transaction_ref=_temporary_transaction_ref(),
            escrow_type="recurring",
            status="invited",
            initiator_actor_type=initiator_actor_type,
            initiator_id=initiator_id,
            initiator_org_id=initiator_org_id,
            receiver_id=data.receiver_id,
            receiver_email=(str(data.receiver_email) if data.receiver_email else None),
            org_id=data.org_id,
            initiator_role=data.initiator_role,
            title=data.title,
            description=data.description,
            currency=data.currency,
            amount=data.cycle.expected_amount,
            fee_amount=fee,
            acceptance_criteria=data.acceptance_criteria,
            inspection_period=data.inspection_period,
            delivery_date=data.delivery_date,
            dispute_window=data.dispute_window,
            how_dispute_handled=data.how_dispute_handled,
            who_pays_fees=data.who_pays_fees,
            provider=data.provider,
            invite_token_hash=invite_token_hash,
            invite_expires_at=now + timedelta(hours=INVITATION_EXPIRY_HOURS),
            initiator_accepted_at=now if initiator_id is not None else None,
            is_test=data.is_test,
        )
        await self.repo.create_recurring_cycle(
            escrow_id=escrow.id,
            cycle_interval=data.cycle.cycle_interval,
            due_day_of_month=data.cycle.due_day_of_month,
            expected_amount=data.cycle.expected_amount,
            due_date=data.cycle.due_date,
            min_contributors=data.cycle.min_contributors,
            max_contributors=data.cycle.max_contributors,
        )
        await publish(
            "escrow.invite_received",
            {
                "escrow_id": str(escrow.id),
                "escrow_type": "recurring",
                "amount": escrow.amount,
                "initiator_actor_type": escrow.initiator_actor_type,
                "initiator_org_id": (
                    str(escrow.initiator_org_id) if escrow.initiator_org_id else None
                ),
                "receiver_id": str(escrow.receiver_id) if escrow.receiver_id else None,
                "receiver_email": escrow.receiver_email,
                "invite_token": invite_token,
                "offer_version": escrow.offer_version,
            },
        )
        return escrow, None

    async def precheck_invitation(
        self,
        escrow_id: uuid.UUID,
        invite_token: str,
    ) -> InvitationPrecheckResponse:
        escrow = await self.repo.get_by_id(escrow_id)
        if not escrow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Escrow not found",
            )

        if escrow.receiver_email is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation precheck is only available for email invitations",
            )

        if escrow.status in {
            "rejected",
            "expired",
            "cancelled",
            "completed",
            "refunded",
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Escrow invitation is in terminal state '{escrow.status}'",
            )

        if escrow.status not in INVITATION_PRECHECK_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Escrow invitation cannot be checked in status '{escrow.status}'",
            )

        if escrow.invite_token_used_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Invite token has already been used",
            )

        if escrow.invite_expires_at:
            expires_at = escrow.invite_expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                escrow.status = "expired"
                await self.repo.save(escrow)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Escrow invitation has expired",
                )

        token_hash = _hash_invite_token(invite_token) if invite_token else None
        if not token_hash or escrow.invite_token_hash != token_hash:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid invitation token",
            )

        try:
            has_account = await grpc_clients.check_email_exists(escrow.receiver_email)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to verify invited account status",
            ) from exc

        return InvitationPrecheckResponse(
            escrow_id=escrow.id,
            invitation_status=escrow.status,
            has_account=has_account,
            next_action="login" if has_account else "register",
        )

    def _is_participant(self, escrow: Escrow, user_id: uuid.UUID) -> bool:
        return escrow.initiator_id == user_id or escrow.receiver_id == user_id

    async def _bind_invited_receiver_if_needed(
        self,
        escrow: Escrow,
        user_id: uuid.UUID,
        invite_token: str | None,
    ) -> None:
        if escrow.receiver_id is not None:
            return
        if user_id == escrow.initiator_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Initiator cannot claim counterparty invitation",
            )

        if escrow.invite_token_used_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Invite token has already been used",
            )

        token_hash = _hash_invite_token(invite_token) if invite_token else None
        if not token_hash or escrow.invite_token_hash != token_hash:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A valid invite token is required for this invitation",
            )

        escrow.receiver_id = user_id
        escrow.invite_token_used_at = datetime.now(timezone.utc)
        escrow.invite_token_hash = None
        await self.repo.save(escrow)

    async def _ensure_can_act_on_invitation(
        self,
        escrow: Escrow,
        user_id: uuid.UUID,
        invite_token: str | None,
    ) -> Escrow:
        if escrow.status in {
            "rejected",
            "expired",
            "cancelled",
            "completed",
            "refunded",
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Escrow invitation is in terminal state '{escrow.status}'",
            )

        if escrow.invite_expires_at:
            expires_at = escrow.invite_expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                escrow.status = "expired"
                await self.repo.save(escrow)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Escrow invitation has expired",
                )

        await self._bind_invited_receiver_if_needed(escrow, user_id, invite_token)
        if not self._is_participant(escrow, user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this escrow invitation",
            )
        return escrow

    def _expected_counter_responder(self, escrow: Escrow) -> uuid.UUID | None:
        if escrow.status == "counter_pending_initiator":
            return escrow.initiator_id
        if escrow.status == "counter_pending_counterparty":
            return escrow.receiver_id
        return None

    async def _mark_active_counter_offer_response(
        self,
        escrow: Escrow,
        response_status: str,
        responder_id: uuid.UUID,
        responded_at: datetime,
    ) -> None:
        if escrow.active_counter_offer_version is None:
            return

        counter_offer = await self.repo.get_counter_offer_by_version(
            escrow.id,
            escrow.active_counter_offer_version,
        )
        if counter_offer is None or counter_offer.status != "pending_response":
            return

        counter_offer.status = response_status
        counter_offer.responded_by_user_id = responder_id
        counter_offer.responded_at = responded_at
        await self.repo.save_counter_offer(counter_offer)

    async def get_counter_history(self, escrow_id: uuid.UUID):
        return await self.repo.list_counter_offers(escrow_id)

    async def accept_invitation(
        self,
        escrow_id: uuid.UUID,
        user_id: uuid.UUID,
        body: InvitationAcceptRequest,
    ) -> tuple[Escrow, str | None]:
        escrow = await self.repo.get_by_id(escrow_id)
        if not escrow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Escrow not found",
            )

        escrow = await self._ensure_can_act_on_invitation(
            escrow, user_id, body.invite_token
        )
        now = datetime.now(timezone.utc)

        if escrow.status == "invited" and user_id == escrow.initiator_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Initiator is implicitly accepted for the original invitation",
            )

        expected_responder = self._expected_counter_responder(escrow)
        if expected_responder is not None and expected_responder != user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A pending counter-offer is awaiting the other participant's response",
            )

        actor = self._resolve_actor_for_user(escrow, user_id)
        if actor is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only escrow participants can accept invitations",
            )

        if escrow.status in COUNTER_PENDING_STATUSES:
            await self._mark_active_counter_offer_response(
                escrow,
                "accepted",
                user_id,
                now,
            )
            escrow.counter_status = "accepted"
            escrow.active_counter_offer_version = None

        if user_id == escrow.initiator_id:
            escrow.initiator_accepted_at = now
        else:
            escrow.receiver_accepted_at = now

        # V3: acceptance is final in invitation window:
        # - invited + counterparty accept => pending (initiator implicit acceptance)
        # - counter_pending_* + waiting actor accept => pending
        escrow, payment_url = await self._attempt_wallet_lock_and_transition(
            escrow,
            actor,
        )
        await publish(
            "escrow.invite_responded",
            {
                "escrow_id": str(escrow.id),
                "status": escrow.status,
                "offer_version": escrow.offer_version,
            },
        )
        return escrow, payment_url

    async def reject_invitation(
        self,
        escrow_id: uuid.UUID,
        user_id: uuid.UUID,
        body: InvitationRejectRequest,
    ) -> Escrow:
        escrow = await self.repo.get_by_id(escrow_id)
        if not escrow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Escrow not found",
            )

        if user_id == escrow.initiator_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Initiator cannot reject their own invitation. Use cancel instead.",
            )

        escrow = await self._ensure_can_act_on_invitation(
            escrow, user_id, body.invite_token
        )
        if escrow.status not in {
            "invited",
            "counter_pending_counterparty",
        }:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot reject an escrow in status '{escrow.status}'",
            )

        if (
            escrow.status == "counter_pending_counterparty"
            and user_id != escrow.receiver_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only the pending counterparty can reject this counter-offer",
            )

        actor = self._resolve_actor_for_user(escrow, user_id)
        if actor is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only escrow participants can reject invitations",
            )
        self._assert_transition_allowed(escrow.status, "rejected", actor)

        escrow.status = "rejected"
        escrow = await self.repo.save(escrow)
        await publish(
            "escrow.invite_rejected",
            {
                "escrow_id": str(escrow.id),
                "offer_version": escrow.offer_version,
            },
        )
        return escrow

    async def counter_invitation(
        self,
        escrow_id: uuid.UUID,
        user_id: uuid.UUID,
        body: InvitationCounterRequest,
    ) -> Escrow:
        escrow = await self.repo.get_by_id(escrow_id)
        if not escrow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Escrow not found",
            )

        # check if escrow is in a state that can be countered
        if escrow.status not in {
            "invited",
            "counter_pending_initiator",
            "counter_pending_counterparty",
        }:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot counter an escrow in status '{escrow.status}'",
            )

        escrow = await self._ensure_can_act_on_invitation(
            escrow, user_id, body.invite_token
        )
        now = datetime.now(timezone.utc)

        expected_responder = self._expected_counter_responder(escrow)
        if expected_responder is not None and expected_responder != user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A pending counter-offer is awaiting the other participant's response",
            )

        actor = self._resolve_actor_for_user(escrow, user_id)
        if actor is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only escrow participants can counter invitations",
            )

        if escrow.status == "invited" and user_id == escrow.initiator_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Initiator cannot counter the original offer they created",
            )

        if expected_responder is not None:
            await self._mark_active_counter_offer_response(
                escrow,
                "countered_again",
                user_id,
                now,
            )

        proposed_to_user_id = (
            escrow.receiver_id
            if user_id == escrow.initiator_id
            else escrow.initiator_id
        )
        if proposed_to_user_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Counter-offer target is not available",
            )

        if body.amount is not None and escrow.escrow_type in {"milestone", "recurring"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="amount counter is currently supported only for onetime escrows",
            )

        if body.title is not None:
            escrow.title = body.title
        if body.description is not None:
            escrow.description = body.description
        if body.amount is not None:
            escrow.amount = body.amount
            escrow.fee_amount = _calculate_fee(body.amount)
        if body.acceptance_criteria is not None:
            escrow.acceptance_criteria = body.acceptance_criteria
        if body.inspection_period is not None:
            escrow.inspection_period = body.inspection_period
        if body.delivery_date is not None:
            escrow.delivery_date = body.delivery_date
        if body.dispute_window is not None:
            escrow.dispute_window = body.dispute_window
        if body.how_dispute_handled is not None:
            escrow.how_dispute_handled = body.how_dispute_handled
        if body.who_pays_fees is not None:
            escrow.who_pays_fees = body.who_pays_fees

        escrow.offer_version += 1
        if escrow.status == "invited":
            next_status = "counter_pending_counterparty"
        else:
            next_status = (
                "counter_pending_counterparty"
                if user_id == escrow.initiator_id
                else "counter_pending_initiator"
            )
        self._assert_transition_allowed(escrow.status, next_status, actor)
        escrow.status = next_status
        escrow.counter_status = (
            "awaiting_counterparty"
            if user_id == escrow.initiator_id
            else "awaiting_initiator"
        )
        escrow.active_counter_offer_version = escrow.offer_version
        escrow.last_countered_by_id = user_id
        escrow.last_countered_at = now
        if user_id == escrow.initiator_id:
            escrow.initiator_accepted_at = now
            escrow.receiver_accepted_at = None
        else:
            escrow.receiver_accepted_at = now
            escrow.initiator_accepted_at = None

        await self.repo.create_counter_offer(
            escrow_id=escrow.id,
            offer_version=escrow.offer_version,
            proposed_by_user_id=user_id,
            proposed_to_user_id=proposed_to_user_id,
            status="pending_response",
            title=escrow.title,
            description=escrow.description,
            amount=escrow.amount,
            acceptance_criteria=escrow.acceptance_criteria,
            inspection_period=escrow.inspection_period,
            delivery_date=escrow.delivery_date,
            dispute_window=escrow.dispute_window,
            how_dispute_handled=escrow.how_dispute_handled,
            who_pays_fees=escrow.who_pays_fees,
        )

        escrow = await self.repo.save(escrow)
        await publish(
            "escrow.invite_countered",
            {
                "escrow_id": str(escrow.id),
                "offer_version": escrow.offer_version,
                "countered_by": str(user_id),
                "counter_status": escrow.counter_status,
            },
        )
        return escrow

    async def resend_invitation(
        self,
        escrow_id: uuid.UUID,
        user_id: uuid.UUID,
        body: InvitationResendRequest,
    ) -> Escrow:
        escrow = await self.repo.get_by_id(escrow_id)
        if not escrow:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Escrow not found",
            )

        if user_id != escrow.initiator_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the initiator can resend an invitation",
            )

        if (
            escrow.status != "invited"
        ):  # LATER: maybe we should use enums for better type safety here
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot resend invitation in status '{escrow.status}'",
            )

        now = datetime.now(timezone.utc)
        invite_token: str | None = None
        if escrow.receiver_id is None:
            if body.receiver_email is not None:
                escrow.receiver_email = str(body.receiver_email)
            invite_token = _generate_invite_token()
            escrow.invite_token_hash = _hash_invite_token(invite_token)
            escrow.invite_token_used_at = None

        escrow.receiver_accepted_at = None
        escrow.invite_expires_at = now + timedelta(hours=INVITATION_EXPIRY_HOURS)
        escrow.counter_status = "none"
        escrow.active_counter_offer_version = None
        escrow.status = "invited"
        escrow = await self.repo.save(escrow)

        await publish(
            "escrow.invite_received",
            {
                "escrow_id": str(escrow.id),
                "escrow_type": escrow.escrow_type,
                "amount": escrow.amount,
                "receiver_id": str(escrow.receiver_id) if escrow.receiver_id else None,
                "receiver_email": escrow.receiver_email,
                "invite_token": invite_token,
                "offer_version": escrow.offer_version,
                "resent": True,
            },
        )

        return escrow

    async def join_cycle(
        self,
        escrow_id: uuid.UUID,
        user_id: uuid.UUID,
        req,
    ) -> RecurringContributor:
        escrow = await self.get_escrow(escrow_id, user_id)
        if escrow.escrow_type != "recurring":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only recurring escrows support contributors",
            )
        cycle = await self.repo.get_cycle(escrow_id)
        if not cycle:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cycle not found"
            )

        if cycle.max_contributors is not None:
            count = await self.repo.count_contributors(cycle.id)
            if count >= cycle.max_contributors:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Maximum number of contributors reached",
                )

        wallet_id = await grpc_clients.get_user_wallet(str(user_id), escrow.currency)
        if wallet_id:
            await grpc_clients.lock_funds(
                wallet_id=wallet_id,
                amount=req.contribution,
                reference=escrow.transaction_ref,
                escrow_id=str(escrow.id),
            )

        contributor = await self.repo.add_contributor(
            cycle_id=cycle.id,
            user_id=user_id,
            name=req.name,
            email=req.email,
            expected_amount=req.contribution,
        )
        await publish(
            "escrow.contributor_joined",
            {
                "escrow_id": str(escrow_id),
                "cycle_id": str(cycle.id),
                "user_id": str(user_id),
                "contribution": req.contribution,
            },
        )
        return contributor

    async def process_due_cycles(self) -> int:
        """
        Find all active cycles whose due_date has passed and attempt to release
        funds if min_contributors have joined.  Returns the count processed.
        Called by a Celery beat task.
        """
        now = datetime.now(timezone.utc)
        due_cycles = await self.repo.get_due_cycles(now)
        processed = 0
        for cycle in due_cycles:
            count = await self.repo.count_contributors(cycle.id)
            if count >= cycle.min_contributors:
                escrow = await self.repo.get_by_id(cycle.escrow_id)
                if escrow and escrow.status == "active":
                    await self.transition_status(escrow, "completed", "system")
                    escrow.completed_at = now
                    await self.repo.save(escrow)
                    await publish(
                        "escrow.completed",
                        {
                            "escrow_id": str(escrow.id),
                            "transaction_ref": escrow.transaction_ref,
                            "trigger": "due_cycle",
                        },
                    )
                    processed += 1
        return processed

    async def process_expired_invitations(self) -> int:
        """Expire stale invitation-state escrows for worker scheduling."""
        now = datetime.now(timezone.utc)
        expired_candidates = await self.repo.list_expired_invitations(now)
        processed = 0

        for escrow in expired_candidates:
            self._assert_transition_allowed(escrow.status, "expired", "system")
            escrow.status = "expired"
            await self.repo.save(escrow)
            await publish(
                "escrow.invite_expired",
                {
                    "escrow_id": str(escrow.id),
                    "offer_version": escrow.offer_version,
                },
            )
            processed += 1

        return processed
