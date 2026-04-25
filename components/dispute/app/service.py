"""Business logic for the Dispute service."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from math import ceil

from fastapi import HTTPException, status

from app import grpc_clients
from app.db import Dispute, DisputeEvidence, DisputeMessage
from app.messaging import publish
from app.models import DisputeCreate, DisputeResolve
from app.repository import DisputeRepository

MODERATOR_ROLES = {"admin", "moderator"}
MUTABLE_DISPUTE_STATUSES = {
    "open_negotiation",
    "settlement_pending_confirmation",
    "escalated_mediation",
}
FINAL_RESOLUTION_STATUSES = {"settled_by_parties", "resolved_buyer", "resolved_seller", "cancelled"}

logger = logging.getLogger(__name__)


class DisputeService:
    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def __init__(self, repo: DisputeRepository) -> None:
        self.repo = repo

    @staticmethod
    async def _resolve_notification_participants(
        escrow_id: uuid.UUID,
        fallback_user_ids: list[str] | None = None,
    ) -> list[str]:
        participant_ids: list[str] = []
        try:
            escrow = await grpc_clients.get_escrow(escrow_id)
            participant_ids = DisputeService._participant_user_ids(escrow)
        except RuntimeError:
            logger.exception(
                "dispute.notification.participants.fetch_failed escrow_id=%s",
                escrow_id,
            )

        for fallback_user_id in fallback_user_ids or []:
            normalized = fallback_user_id.strip()
            if normalized and normalized not in participant_ids:
                participant_ids.append(normalized)

        return participant_ids

    @staticmethod
    async def _publish_to_participants(
        routing_key: str,
        participant_ids: list[str],
        payload: dict,
        actor_user_id: uuid.UUID | None = None,
    ) -> None:
        actor_user_id_str = str(actor_user_id) if actor_user_id else None
        for participant_id in participant_ids:
            event_payload = {
                **payload,
                "user_id": participant_id,
            }
            if actor_user_id_str:
                event_payload["actor_user_id"] = actor_user_id_str
            await publish(routing_key, event_payload)

    @staticmethod
    async def _get_escrow_or_raise(escrow_id: uuid.UUID) -> dict:
        try:
            return await grpc_clients.get_escrow(escrow_id)
        except RuntimeError as exc:
            error_text = str(exc)
            if "not found" in error_text.lower():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Escrow not found",
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to fetch escrow",
            ) from exc

    @staticmethod
    def _participant_user_ids(escrow: dict) -> list[str]:
        participant_ids: list[str] = []
        for key in ("initiator_id", "receiver_id"):
            value = escrow.get(key)
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            if normalized and normalized not in participant_ids:
                participant_ids.append(normalized)
        return participant_ids

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
        escrow = await self._get_escrow_or_raise(escrow_id)
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

        # Transition escrow to disputed with the real participant actor.
        try:
            await grpc_clients.transition_escrow_status(
                escrow_id,
                "disputed",
                actor_id=str(user_id),
            )
        except RuntimeError as exc:
            error_text = str(exc)
            if "cannot transition" in error_text.lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=error_text,
                ) from exc
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to update escrow status to disputed",
            ) from exc

        dispute = Dispute(
            escrow_id=escrow_id,
            raised_by=user_id,
            reason=data.reason,
            description=data.description,
            status="open_negotiation",
        )
        dispute = await self.repo.create(dispute)
        await self._publish_to_participants(
            "dispute.opened",
            self._participant_user_ids(escrow),
            {
                "dispute_id": str(dispute.id),
                "escrow_id": str(escrow_id),
                "raised_by": str(user_id),
                "reason": data.reason,
            },
            actor_user_id=user_id,
        )
        return dispute

    def _assert_negotiation_window_open(self, dispute: Dispute) -> None:
        deadline = self._normalize_datetime(dispute.negotiation_deadline_at)
        if self._now() > deadline:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Negotiation window has expired; escalate dispute for mediation",
            )

    @staticmethod
    def _is_settlement_state(dispute: Dispute) -> bool:
        return dispute.status in {"open_negotiation", "settlement_pending_confirmation"}

    def _assert_dispute_mutable(self, dispute: Dispute) -> None:
        if dispute.status not in MUTABLE_DISPUTE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dispute is no longer open for negotiation actions",
            )

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

        escrow = await self._get_escrow_or_raise(escrow_id)
        self._assert_can_view_or_mutate_dispute(escrow, user_id, actor_role)

        evidence = await self.repo.list_evidence(dispute.id)
        messages = await self.repo.list_messages(dispute.id)
        return {"dispute": dispute, "evidence": evidence, "messages": messages}

    async def get_dispute_for_actor(
        self,
        dispute_id: uuid.UUID,
        user_id: uuid.UUID,
        actor_role: str = "user",
    ) -> dict:
        dispute = await self.repo.get_by_id(dispute_id)
        if dispute is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dispute not found",
            )
        escrow = await self._get_escrow_or_raise(dispute.escrow_id)
        self._assert_can_view_or_mutate_dispute(escrow, user_id, actor_role)
        evidence = await self.repo.list_evidence(dispute.id)
        messages = await self.repo.list_messages(dispute.id)
        return {"dispute": dispute, "evidence": evidence, "messages": messages}

    async def add_message(
        self,
        dispute_id: uuid.UUID,
        user_id: uuid.UUID,
        message_text: str,
        actor_role: str = "user",
        is_system: bool = False,
    ) -> DisputeMessage:
        dispute = await self.repo.get_by_id(dispute_id)
        if dispute is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")

        self._assert_dispute_mutable(dispute)

        escrow = await self._get_escrow_or_raise(dispute.escrow_id)
        self._assert_can_view_or_mutate_dispute(escrow, user_id, actor_role)

        msg = DisputeMessage(
            dispute_id=dispute_id,
            sender_id=user_id,
            message=message_text,
            is_system=is_system,
        )
        msg = await self.repo.add_message(msg)

        await self._publish_to_participants(
            "dispute.message.posted",
            self._participant_user_ids(escrow),
            {
                "dispute_id": str(dispute_id),
                "escrow_id": str(dispute.escrow_id),
                "message_id": str(msg.id),
                "message": msg.message,
                "sender_id": str(user_id),
                "is_system": is_system,
            },
            actor_user_id=user_id,
        )
        return msg

    async def add_evidence(
        self,
        dispute_id: uuid.UUID,
        user_id: uuid.UUID,
        file_url: str,
        file_type: str,
        description: str,
        object_key: str | None = None,
        message_id: uuid.UUID | None = None,
        actor_role: str = "user",
    ) -> DisputeEvidence:
        dispute = await self.repo.get_by_id(dispute_id)
        if dispute is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")

        self._assert_dispute_mutable(dispute)
        escrow = await self._get_escrow_or_raise(dispute.escrow_id)
        self._assert_can_view_or_mutate_dispute(escrow, user_id, actor_role)

        from app.image_analysis import analyze_image_for_tampering
        is_tampered, tamper_metadata = await analyze_image_for_tampering(file_url)

        evidence = DisputeEvidence(
            dispute_id=dispute_id,
            uploaded_by=user_id,
            object_key=object_key,
            file_url=file_url,
            file_type=file_type,
            description=description,
            message_id=message_id,
            is_tampered=is_tampered,
            tamper_metadata=tamper_metadata,
        )
        evidence = await self.repo.add_evidence(evidence)

        await self._publish_to_participants(
            "dispute.evidence.added",
            self._participant_user_ids(escrow),
            {
                "dispute_id": str(dispute_id),
                "escrow_id": str(dispute.escrow_id),
                "added_by": str(user_id),
                "file_type": file_type,
                "description": description,
                "object_key": object_key,
                "is_tampered": is_tampered,
            },
            actor_user_id=user_id,
        )

        return evidence

    async def request_settlement(
        self,
        dispute_id: uuid.UUID,
        requester_id: uuid.UUID,
        actor_role: str = "user",
    ) -> Dispute:
        dispute = await self.repo.get_by_id(dispute_id)
        if dispute is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")
        if not self._is_settlement_state(dispute):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dispute is not in a settlement stage",
            )
        self._assert_negotiation_window_open(dispute)

        escrow = await self._get_escrow_or_raise(dispute.escrow_id)
        self._assert_can_view_or_mutate_dispute(escrow, requester_id, actor_role)

        updated = await self.repo.request_settlement(dispute_id, requester_id)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")

        await self._publish_to_participants(
            "dispute.settlement.requested",
            self._participant_user_ids(escrow),
            {
                "dispute_id": str(dispute_id),
                "escrow_id": str(dispute.escrow_id),
                "requested_by": str(requester_id),
            },
            actor_user_id=requester_id,
        )
        return updated

    async def confirm_settlement(
        self,
        dispute_id: uuid.UUID,
        confirmer_id: uuid.UUID,
        actor_role: str = "user",
    ) -> Dispute:
        dispute = await self.repo.get_by_id(dispute_id)
        if dispute is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")
        if dispute.status != "settlement_pending_confirmation":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No pending settlement request for this dispute",
            )
        if dispute.settlement_requested_by == confirmer_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Settlement confirmation requires the counterparty",
            )

        escrow = await self._get_escrow_or_raise(dispute.escrow_id)
        self._assert_can_view_or_mutate_dispute(escrow, confirmer_id, actor_role)

        settled = await self.repo.confirm_settlement(dispute_id, confirmer_id)
        if settled is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")

        await grpc_clients.transition_escrow_status(dispute.escrow_id, "completed")
        await self._publish_to_participants(
            "dispute.settled.by_parties",
            self._participant_user_ids(escrow),
            {
                "dispute_id": str(dispute_id),
                "escrow_id": str(dispute.escrow_id),
                "requested_by": str(dispute.settlement_requested_by),
                "confirmed_by": str(confirmer_id),
            },
            actor_user_id=confirmer_id,
        )
        return settled

    async def escalate_dispute(
        self,
        dispute_id: uuid.UUID,
        actor_id: uuid.UUID,
        actor_role: str,
        mediator_id: uuid.UUID | None = None,
    ) -> Dispute:
        dispute = await self.repo.get_by_id(dispute_id)
        if dispute is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")
        if dispute.status in FINAL_RESOLUTION_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dispute already closed",
            )

        escrow = await self._get_escrow_or_raise(dispute.escrow_id)
        self._assert_can_view_or_mutate_dispute(escrow, actor_id, actor_role)

        escalated = await self.repo.escalate_to_mediation(dispute_id, mediator_id)
        if escalated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")

        await self._publish_to_participants(
            "dispute.escalated",
            self._participant_user_ids(escrow),
            {
                "dispute_id": str(dispute_id),
                "escrow_id": str(dispute.escrow_id),
                "escalated_by": str(actor_id),
                "assigned_mediator_id": str(mediator_id) if mediator_id else None,
            },
            actor_user_id=actor_id,
        )
        return escalated

    async def auto_escalate_expired_disputes(self, limit: int = 100) -> list[Dispute]:
        disputes = await self.repo.list_expired_negotiations(self._now(), limit=limit)
        results: list[Dispute] = []
        for dispute in disputes:
            escalated = await self.repo.escalate_to_mediation(dispute.id)
            if escalated is None:
                continue
            await self._publish_to_participants(
                "dispute.auto_escalated",
                await self._resolve_notification_participants(
                    escalated.escrow_id,
                    fallback_user_ids=[str(escalated.raised_by)],
                ),
                {
                    "dispute_id": str(escalated.id),
                    "escrow_id": str(escalated.escrow_id),
                    "reason": "negotiation_window_expired",
                },
            )
            results.append(escalated)
        return results

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
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")
        if dispute.status != "escalated_mediation":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dispute must be escalated before mediator decision",
            )

        final_status = f"resolved_{data.resolution}"
        await grpc_clients.release_funds(dispute.escrow_id, data.resolution)
        escrow_status = "completed" if data.resolution == "seller" else "refunded"
        await grpc_clients.transition_escrow_status(dispute.escrow_id, escrow_status)

        dispute = await self.repo.update_status(
            dispute_id,
            final_status,
            resolution_note=data.resolution_note,
            resolved_by=admin_id,
        )

        participant_ids = await self._resolve_notification_participants(
            dispute.escrow_id,
            fallback_user_ids=[str(dispute.raised_by)],
        )
        await self._publish_to_participants(
            "dispute.resolution.requested",
            participant_ids,
            {
                "dispute_id": str(dispute_id),
                "resolution": data.resolution,
                "escrow_id": str(dispute.escrow_id),
                "decided_by": str(admin_id),
                "final": True,
            },
            actor_user_id=admin_id,
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

        final_status = f"resolved_{resolution}"

        if dispute.status == final_status:
            logger.info(
                "dispute.execute_resolution.idempotent dispute_id=%s resolution=%s",
                dispute_id,
                resolution,
            )
            return dispute

        if dispute.status in FINAL_RESOLUTION_STATUSES and dispute.status != final_status:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dispute already resolved with a different outcome",
            )

        if dispute.status != "escalated_mediation":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dispute must be escalated before execution",
            )

        await grpc_clients.release_funds(dispute.escrow_id, resolution)

        escrow_status = "completed" if resolution == "seller" else "refunded"
        await grpc_clients.transition_escrow_status(dispute.escrow_id, escrow_status)

        dispute = await self.repo.update_status(
            dispute_id,
            final_status,
            resolved_by=admin_id,
        )
        participant_ids = await self._resolve_notification_participants(
            dispute.escrow_id,
            fallback_user_ids=[str(dispute.raised_by)],
        )
        await self._publish_to_participants(
            "dispute.resolved",
            participant_ids,
            {
                "dispute_id": str(dispute_id),
                "resolution": resolution,
                "escrow_id": str(dispute.escrow_id),
                "resolved_by": str(admin_id) if admin_id else None,
            },
            actor_user_id=admin_id,
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
        if dispute.status != "open_negotiation":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only open negotiation disputes can be moved to mediation",
            )

        dispute = await self.repo.escalate_to_mediation(dispute_id)
        if dispute is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dispute not found",
            )
        if note:
            dispute = await self.repo.update_status(
                dispute_id,
                dispute.status,
                resolution_note=note,
            )
        participant_ids = await self._resolve_notification_participants(
            dispute.escrow_id,
            fallback_user_ids=[str(dispute.raised_by)],
        )
        await self._publish_to_participants(
            "dispute.under_review",
            participant_ids,
            {
                "dispute_id": str(dispute_id),
                "escrow_id": str(dispute.escrow_id),
                "reviewed_by": str(moderator_id),
                "note": note,
            },
            actor_user_id=moderator_id,
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
        if dispute.status not in {"open_negotiation", "settlement_pending_confirmation"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only open disputes can be cancelled",
            )

        dispute = await self.repo.update_status(dispute_id, "cancelled")
        await grpc_clients.transition_escrow_status(dispute.escrow_id, "active")
        participant_ids = await self._resolve_notification_participants(
            dispute.escrow_id,
            fallback_user_ids=[str(dispute.raised_by)],
        )
        await self._publish_to_participants(
            "dispute.cancelled",
            participant_ids,
            {
                "dispute_id": str(dispute_id),
                "escrow_id": str(dispute.escrow_id),
                "cancelled_by": str(requester_id),
            },
            actor_user_id=requester_id,
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

    async def list_my_disputes(
        self,
        user_id: uuid.UUID,
        status_filter: str | None,
        page: int,
        limit: int,
    ) -> dict:
        offset = (page - 1) * limit
        items, total = await self.repo.list_disputes_by_raiser(
            raised_by=user_id,
            status_filter=status_filter,
            offset=offset,
            limit=limit,
        )
        pages = ceil(total / limit) if limit else 1
        return {
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
        }
