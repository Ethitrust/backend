"""Business logic for the Dispute service."""

from __future__ import annotations

import logging
import uuid
from math import ceil

from fastapi import HTTPException, status

from app import grpc_clients
from app.db import Dispute, DisputeEvidence
from app.messaging import publish
from app.models import DisputeCreate, DisputeResolve
from app.repository import DisputeRepository

MODERATOR_ROLES = {"admin", "moderator"}
RESOLVABLE_STATUSES = {"open", "under_review"}
PENDING_RESOLUTION_STATUSES = {
    "resolution_pending_buyer",
    "resolution_pending_seller",
}
FINAL_RESOLUTION_STATUSES = {"resolved_buyer", "resolved_seller"}

logger = logging.getLogger(__name__)


class DisputeService:
    def __init__(self, repo: DisputeRepository) -> None:
        self.repo = repo

    @staticmethod
    def _is_admin_or_moderator(role: str) -> bool:
        return role in MODERATOR_ROLES

    @staticmethod
    def _is_escrow_participant(escrow: dict, user_id: uuid.UUID) -> bool:
        actor_id = str(user_id)
        initiator_id = str(escrow.get("initiator_id") or "")
        receiver_id = str(escrow.get("receiver_id") or "")
        return actor_id in {initiator_id, receiver_id}

    def _assert_can_view_or_mutate_dispute(
        self,
        escrow: dict,
        user_id: uuid.UUID,
        actor_role: str,
    ) -> None:
        if self._is_admin_or_moderator(actor_role):
            return
        if self._is_escrow_participant(escrow, user_id):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this dispute",
        )

    async def raise_dispute(
        self,
        escrow_id: uuid.UUID,
        user_id: uuid.UUID,
        data: DisputeCreate,
        actor_role: str = "user",
    ) -> Dispute:
        # Verify escrow exists and is active
        escrow = await grpc_clients.get_escrow(escrow_id)
        if escrow.get("status") != "active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dispute can only be raised on active escrows",
            )
        self._assert_can_view_or_mutate_dispute(escrow, user_id, actor_role)

        # Check if dispute already exists
        existing = await self.repo.get_by_escrow(escrow_id)
        if existing and existing.status not in ("cancelled",):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dispute already exists for this escrow",
            )

        # Transition escrow to disputed
        await grpc_clients.transition_escrow_status(escrow_id, "disputed")

        dispute = Dispute(
            escrow_id=escrow_id,
            raised_by=user_id,
            reason=data.reason,
            description=data.description,
            status="open",
        )
        dispute = await self.repo.create(dispute)
        await publish(
            "dispute.opened",
            {
                "dispute_id": str(dispute.id),
                "escrow_id": str(escrow_id),
                "raised_by": str(user_id),
                "reason": data.reason,
            },
        )
        return dispute

    async def get_dispute(
        self,
        escrow_id: uuid.UUID,
        user_id: uuid.UUID,
        actor_role: str = "user",
    ) -> dict:
        dispute = await self.repo.get_by_escrow(escrow_id)
        if dispute is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No dispute found for this escrow",
            )

        escrow = await grpc_clients.get_escrow(escrow_id)
        self._assert_can_view_or_mutate_dispute(escrow, user_id, actor_role)

        evidence = await self.repo.list_evidence(dispute.id)
        return {"dispute": dispute, "evidence": evidence}

    async def add_evidence(
        self,
        dispute_id: uuid.UUID,
        user_id: uuid.UUID,
        file_url: str,
        file_type: str,
        description: str,
        actor_role: str = "user",
    ) -> DisputeEvidence:
        dispute = await self.repo.get_by_id(dispute_id)
        if dispute is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found"
            )

        escrow = await grpc_clients.get_escrow(dispute.escrow_id)
        self._assert_can_view_or_mutate_dispute(escrow, user_id, actor_role)

        evidence = DisputeEvidence(
            dispute_id=dispute_id,
            uploaded_by=user_id,
            file_url=file_url,
            file_type=file_type,
            description=description,
        )
        return await self.repo.add_evidence(evidence)

    async def resolve_dispute(
        self,
        dispute_id: uuid.UUID,
        admin_id: uuid.UUID,
        admin_role: str,
        data: DisputeResolve,
    ) -> Dispute:
        if not self._is_admin_or_moderator(admin_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin or moderator role required",
            )

        dispute = await self.repo.get_by_id(dispute_id)
        if dispute is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found"
            )
        if dispute.status not in RESOLVABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dispute cannot be resolved in current state",
            )

        new_status = f"resolution_pending_{data.resolution}"  # resolution_pending_buyer | resolution_pending_seller
        dispute = await self.repo.update_status(
            dispute_id,
            new_status,
            resolution_note=data.resolution_note,
        )

        await publish(
            "dispute.resolution.requested",
            {
                "dispute_id": str(dispute_id),
                "resolution": data.resolution,
                "escrow_id": str(dispute.escrow_id),
                "decided_by": str(admin_id),
            },
        )
        return dispute

    async def execute_resolution(
        self,
        dispute_id: uuid.UUID,
        resolution: str,
        admin_id: uuid.UUID | None = None,
    ) -> Dispute:
        if resolution not in {"buyer", "seller"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Resolution must be either 'buyer' or 'seller'",
            )

        dispute = await self.repo.get_by_id(dispute_id)
        if dispute is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dispute not found",
            )

        expected_pending_status = f"resolution_pending_{resolution}"
        final_status = f"resolved_{resolution}"

        if dispute.status == final_status:
            logger.info(
                "dispute.execute_resolution.idempotent dispute_id=%s resolution=%s",
                dispute_id,
                resolution,
            )
            return dispute

        if (
            dispute.status in FINAL_RESOLUTION_STATUSES
            and dispute.status != final_status
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dispute already resolved with a different outcome",
            )

        if (
            dispute.status in PENDING_RESOLUTION_STATUSES
            and dispute.status != expected_pending_status
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Resolution does not match the queued dispute decision",
            )

        if dispute.status != expected_pending_status:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dispute is not queued for execution",
            )

        await grpc_clients.release_funds(dispute.escrow_id, resolution)

        escrow_status = "completed" if resolution == "seller" else "refunded"
        await grpc_clients.transition_escrow_status(dispute.escrow_id, escrow_status)

        dispute = await self.repo.update_status(
            dispute_id,
            final_status,
            resolved_by=admin_id,
        )
        await publish(
            "dispute.resolved",
            {
                "dispute_id": str(dispute_id),
                "resolution": resolution,
                "escrow_id": str(dispute.escrow_id),
                "resolved_by": str(admin_id) if admin_id else None,
            },
        )
        return dispute

    async def mark_under_review(
        self,
        dispute_id: uuid.UUID,
        moderator_id: uuid.UUID,
        moderator_role: str,
        note: str | None = None,
    ) -> Dispute:
        if not self._is_admin_or_moderator(moderator_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin or moderator role required",
            )

        dispute = await self.repo.get_by_id(dispute_id)
        if dispute is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dispute not found",
            )
        if dispute.status != "open":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only open disputes can be moved to under_review",
            )

        dispute = await self.repo.update_status(
            dispute_id,
            "under_review",
            resolution_note=note,
            resolved_by=None,
        )
        await publish(
            "dispute.under_review",
            {
                "dispute_id": str(dispute_id),
                "escrow_id": str(dispute.escrow_id),
                "reviewed_by": str(moderator_id),
                "note": note,
            },
        )
        return dispute

    async def cancel_dispute(
        self,
        dispute_id: uuid.UUID,
        requester_id: uuid.UUID,
    ) -> Dispute:
        dispute = await self.repo.get_by_id(dispute_id)
        if dispute is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dispute not found",
            )
        if dispute.raised_by != requester_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the user who raised the dispute can cancel it",
            )
        if dispute.status != "open":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only open disputes can be cancelled",
            )

        dispute = await self.repo.update_status(dispute_id, "cancelled")
        await grpc_clients.transition_escrow_status(dispute.escrow_id, "active")
        await publish(
            "dispute.cancelled",
            {
                "dispute_id": str(dispute_id),
                "escrow_id": str(dispute.escrow_id),
                "cancelled_by": str(requester_id),
            },
        )
        return dispute

    async def list_disputes(
        self,
        actor_role: str,
        status_filter: str | None,
        page: int,
        limit: int,
    ) -> dict:
        if not self._is_admin_or_moderator(actor_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin or moderator role required",
            )

        offset = (page - 1) * limit
        items, total = await self.repo.list_disputes(status_filter, offset, limit)
        pages = ceil(total / limit) if limit else 1
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
        }
