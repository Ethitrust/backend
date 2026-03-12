"""Repository layer for the Admin service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import (
    AdminActionLogRecord,
    AdminDisputeEvidenceRequestRecord,
    AdminDisputeInternalNoteRecord,
    AdminDisputeQueueRecord,
    AdminDisputeResolutionRationaleRecord,
    AdminIdempotencyKeyRecord,
    AdminModerationNoteRecord,
    AdminPayoutQueueRecord,
    AdminReportJobRecord,
    AdminReviewCaseRecord,
    AdminRiskFlagRecord,
    AdminSavedViewRecord,
    AdminSystemConfigHistoryRecord,
    AdminSystemConfigRecord,
    AdminVerificationOverrideRecord,
)


class AdminRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_action_log(
        self, log: AdminActionLogRecord
    ) -> AdminActionLogRecord:
        self.db.add(log)
        await self.db.flush()
        await self.db.refresh(log)
        return log

    async def list_action_logs(
        self,
        offset: int,
        limit: int,
        action: str | None = None,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
    ) -> tuple[list[AdminActionLogRecord], int]:
        query = select(AdminActionLogRecord)
        count_query = select(func.count(AdminActionLogRecord.id))

        if action:
            query = query.where(AdminActionLogRecord.action == action)
            count_query = count_query.where(AdminActionLogRecord.action == action)

        if target_type:
            query = query.where(AdminActionLogRecord.target_type == target_type)
            count_query = count_query.where(
                AdminActionLogRecord.target_type == target_type
            )

        if target_id:
            query = query.where(AdminActionLogRecord.target_id == target_id)
            count_query = count_query.where(AdminActionLogRecord.target_id == target_id)

        total = (await self.db.execute(count_query)).scalar_one()
        logs = list(
            (
                await self.db.execute(
                    query.order_by(AdminActionLogRecord.performed_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return logs, total

    async def create_review_case(
        self,
        *,
        subject_type: str,
        subject_id: uuid.UUID,
        created_by: uuid.UUID,
        assignee_id: uuid.UUID | None = None,
        priority: str = "normal",
        status: str = "open",
        metadata: dict | None = None,
        escalated_from_case_id: uuid.UUID | None = None,
    ) -> AdminReviewCaseRecord:
        case = AdminReviewCaseRecord(
            subject_type=subject_type,
            subject_id=subject_id,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
            created_by=created_by,
            escalated_from_case_id=escalated_from_case_id,
            metadata_json=metadata,
        )
        self.db.add(case)
        await self.db.flush()
        await self.db.refresh(case)
        return case

    async def add_moderation_note(
        self,
        *,
        target_type: str,
        target_id: uuid.UUID,
        note: str,
        created_by: uuid.UUID,
        case_id: uuid.UUID | None = None,
        visibility: str = "internal",
    ) -> AdminModerationNoteRecord:
        entry = AdminModerationNoteRecord(
            case_id=case_id,
            target_type=target_type,
            target_id=target_id,
            note=note,
            visibility=visibility,
            created_by=created_by,
        )
        self.db.add(entry)
        await self.db.flush()
        await self.db.refresh(entry)
        return entry

    async def list_moderation_notes(
        self,
        *,
        target_type: str,
        target_id: uuid.UUID,
        limit: int = 200,
    ) -> list[AdminModerationNoteRecord]:
        query = (
            select(AdminModerationNoteRecord)
            .where(AdminModerationNoteRecord.target_type == target_type)
            .where(AdminModerationNoteRecord.target_id == target_id)
            .order_by(AdminModerationNoteRecord.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create_saved_view(
        self,
        *,
        owner_id: uuid.UUID,
        module: str,
        name: str,
        filters: dict,
        is_shared: bool = False,
    ) -> AdminSavedViewRecord:
        view = AdminSavedViewRecord(
            owner_id=owner_id,
            module=module,
            name=name,
            filters=filters,
            is_shared=is_shared,
        )
        self.db.add(view)
        await self.db.flush()
        await self.db.refresh(view)
        return view

    async def list_saved_views(
        self,
        *,
        owner_id: uuid.UUID,
        offset: int,
        limit: int,
        module: str | None = None,
    ) -> tuple[list[AdminSavedViewRecord], int]:
        query = select(AdminSavedViewRecord).where(
            or_(
                AdminSavedViewRecord.owner_id == owner_id,
                AdminSavedViewRecord.is_shared.is_(True),
            )
        )
        count_query = select(func.count(AdminSavedViewRecord.id)).where(
            or_(
                AdminSavedViewRecord.owner_id == owner_id,
                AdminSavedViewRecord.is_shared.is_(True),
            )
        )

        if module:
            query = query.where(AdminSavedViewRecord.module == module)
            count_query = count_query.where(AdminSavedViewRecord.module == module)

        total = int((await self.db.execute(count_query)).scalar_one() or 0)
        rows = (
            (
                await self.db.execute(
                    query.order_by(AdminSavedViewRecord.updated_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def get_saved_view_by_id(
        self,
        *,
        view_id: uuid.UUID,
    ) -> AdminSavedViewRecord | None:
        result = await self.db.execute(
            select(AdminSavedViewRecord).where(AdminSavedViewRecord.id == view_id)
        )
        return result.scalar_one_or_none()

    async def update_saved_view(
        self,
        *,
        view_id: uuid.UUID,
        name: str | None = None,
        filters: dict | None = None,
        is_shared: bool | None = None,
    ) -> AdminSavedViewRecord:
        view = await self.get_saved_view_by_id(view_id=view_id)
        if view is None:
            raise ValueError("Saved view not found")

        if name is not None:
            view.name = name
        if filters is not None:
            view.filters = filters
        if is_shared is not None:
            view.is_shared = is_shared

        await self.db.flush()
        await self.db.refresh(view)
        return view

    async def create_report_job(
        self,
        *,
        requested_by: uuid.UUID,
        report_type: str,
        export_format: str,
        filters: dict | None = None,
        status: str = "queued",
    ) -> AdminReportJobRecord:
        job = AdminReportJobRecord(
            requested_by=requested_by,
            report_type=report_type,
            export_format=export_format,
            filters=filters,
            status=status,
        )
        self.db.add(job)
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def get_report_job_by_id(
        self,
        *,
        job_id: uuid.UUID,
    ) -> AdminReportJobRecord | None:
        result = await self.db.execute(
            select(AdminReportJobRecord).where(AdminReportJobRecord.id == job_id)
        )
        return result.scalar_one_or_none()

    async def list_report_jobs(
        self,
        *,
        requested_by: uuid.UUID,
        offset: int,
        limit: int,
        report_type: str | None = None,
        status_filter: str | None = None,
    ) -> tuple[list[AdminReportJobRecord], int]:
        query = select(AdminReportJobRecord).where(
            AdminReportJobRecord.requested_by == requested_by
        )
        count_query = select(func.count(AdminReportJobRecord.id)).where(
            AdminReportJobRecord.requested_by == requested_by
        )

        if report_type:
            query = query.where(AdminReportJobRecord.report_type == report_type)
            count_query = count_query.where(
                AdminReportJobRecord.report_type == report_type
            )

        if status_filter:
            query = query.where(AdminReportJobRecord.status == status_filter)
            count_query = count_query.where(
                AdminReportJobRecord.status == status_filter
            )

        total = int((await self.db.execute(count_query)).scalar_one() or 0)
        rows = (
            (
                await self.db.execute(
                    query.order_by(AdminReportJobRecord.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def update_report_job(
        self,
        *,
        job_id: uuid.UUID,
        status: str,
        result_url: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> AdminReportJobRecord:
        job = await self.get_report_job_by_id(job_id=job_id)
        if job is None:
            raise ValueError("Report job not found")

        job.status = status
        job.result_url = result_url
        job.error_message = error_message
        job.completed_at = completed_at

        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def list_system_configs(self) -> list[AdminSystemConfigRecord]:
        result = await self.db.execute(
            select(AdminSystemConfigRecord).order_by(AdminSystemConfigRecord.config_key)
        )
        return list(result.scalars().all())

    async def get_system_config_item(
        self,
        *,
        config_key: str,
    ) -> AdminSystemConfigRecord | None:
        result = await self.db.execute(
            select(AdminSystemConfigRecord).where(
                AdminSystemConfigRecord.config_key == config_key
            )
        )
        return result.scalar_one_or_none()

    async def create_or_update_system_config(
        self,
        *,
        config_key: str,
        value: Any,
        changed_by: uuid.UUID,
        reason: str,
        action: str = "config.updated",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[AdminSystemConfigRecord, AdminSystemConfigHistoryRecord]:
        existing = await self.get_system_config_item(config_key=config_key)
        previous_value = existing.value_json if existing else None
        version = (existing.version + 1) if existing else 1

        if existing is None:
            config_item = AdminSystemConfigRecord(
                config_key=config_key,
                value_json=value,
                version=version,
                updated_by=changed_by,
            )
            self.db.add(config_item)
        else:
            existing.value_json = value
            existing.version = version
            existing.updated_by = changed_by
            config_item = existing

        history_item = AdminSystemConfigHistoryRecord(
            config_key=config_key,
            version=version,
            action=action,
            previous_value=previous_value,
            new_value=value,
            changed_by=changed_by,
            reason=reason,
            metadata_json=metadata,
        )
        self.db.add(history_item)
        await self.db.flush()
        await self.db.refresh(config_item)
        await self.db.refresh(history_item)
        return config_item, history_item

    async def list_system_config_history(
        self,
        *,
        config_key: str,
        limit: int = 100,
    ) -> list[AdminSystemConfigHistoryRecord]:
        result = await self.db.execute(
            select(AdminSystemConfigHistoryRecord)
            .where(AdminSystemConfigHistoryRecord.config_key == config_key)
            .order_by(AdminSystemConfigHistoryRecord.version.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_system_config_history_by_version(
        self,
        *,
        config_key: str,
        version: int,
    ) -> AdminSystemConfigHistoryRecord | None:
        result = await self.db.execute(
            select(AdminSystemConfigHistoryRecord)
            .where(AdminSystemConfigHistoryRecord.config_key == config_key)
            .where(AdminSystemConfigHistoryRecord.version == version)
        )
        return result.scalar_one_or_none()

    async def create_verification_override(
        self,
        *,
        user_id: uuid.UUID,
        is_verified: bool,
        reason: str,
        overridden_by: uuid.UUID,
        idempotency_key: str,
        review_case_id: uuid.UUID | None = None,
    ) -> AdminVerificationOverrideRecord:
        record = AdminVerificationOverrideRecord(
            user_id=user_id,
            is_verified=is_verified,
            reason=reason,
            overridden_by=overridden_by,
            idempotency_key=idempotency_key,
            review_case_id=review_case_id,
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def list_verification_overrides(
        self,
        *,
        user_id: uuid.UUID,
        limit: int = 200,
    ) -> list[AdminVerificationOverrideRecord]:
        query = (
            select(AdminVerificationOverrideRecord)
            .where(AdminVerificationOverrideRecord.user_id == user_id)
            .order_by(AdminVerificationOverrideRecord.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create_risk_flag(
        self,
        *,
        user_id: uuid.UUID,
        flag: str,
        severity: str,
        reason: str,
        created_by: uuid.UUID,
        metadata: dict | None = None,
        status: str = "active",
    ) -> AdminRiskFlagRecord:
        record = AdminRiskFlagRecord(
            user_id=user_id,
            flag=flag,
            severity=severity,
            status=status,
            reason=reason,
            created_by=created_by,
            metadata_json=metadata,
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def list_risk_flags(
        self,
        *,
        user_id: uuid.UUID,
        limit: int = 200,
    ) -> list[AdminRiskFlagRecord]:
        query = (
            select(AdminRiskFlagRecord)
            .where(AdminRiskFlagRecord.user_id == user_id)
            .order_by(AdminRiskFlagRecord.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_idempotency_record(
        self,
        *,
        action: str,
        idempotency_key: str,
    ) -> AdminIdempotencyKeyRecord | None:
        query = (
            select(AdminIdempotencyKeyRecord)
            .where(AdminIdempotencyKeyRecord.action == action)
            .where(AdminIdempotencyKeyRecord.idempotency_key == idempotency_key)
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def save_idempotency_record(
        self,
        *,
        action: str,
        idempotency_key: str,
        actor_id: uuid.UUID,
        request_payload: dict | None,
        response_payload: dict | None,
    ) -> AdminIdempotencyKeyRecord:
        record = AdminIdempotencyKeyRecord(
            action=action,
            idempotency_key=idempotency_key,
            actor_id=actor_id,
            request_payload=request_payload,
            response_payload=response_payload,
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def upsert_dispute_queue_item(
        self,
        *,
        dispute_id: uuid.UUID,
        escrow_id: uuid.UUID,
        status: str,
        reason: str,
        raised_by: uuid.UUID,
        dispute_created_at: datetime,
    ) -> AdminDisputeQueueRecord:
        existing = await self.get_dispute_queue_item(dispute_id=dispute_id)
        if existing:
            existing.status = status
            existing.reason = reason
            existing.raised_by = raised_by
            existing.escrow_id = escrow_id
            existing.created_at = dispute_created_at
            await self.db.flush()
            await self.db.refresh(existing)
            return existing

        record = AdminDisputeQueueRecord(
            dispute_id=dispute_id,
            escrow_id=escrow_id,
            status=status,
            reason=reason,
            raised_by=raised_by,
            priority="normal",
            created_at=dispute_created_at,
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def get_dispute_queue_item(
        self,
        *,
        dispute_id: uuid.UUID,
    ) -> AdminDisputeQueueRecord | None:
        query = select(AdminDisputeQueueRecord).where(
            AdminDisputeQueueRecord.dispute_id == dispute_id
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_dispute_queue_items(
        self,
        *,
        offset: int,
        limit: int,
        status_filters: list[str] | None = None,
        assignee_id: uuid.UUID | None = None,
        priority: str | None = None,
    ) -> tuple[list[AdminDisputeQueueRecord], int]:
        query = select(AdminDisputeQueueRecord)
        count_query = select(func.count(AdminDisputeQueueRecord.id))

        if status_filters:
            query = query.where(AdminDisputeQueueRecord.status.in_(status_filters))
            count_query = count_query.where(
                AdminDisputeQueueRecord.status.in_(status_filters)
            )

        if assignee_id:
            query = query.where(AdminDisputeQueueRecord.assignee_id == assignee_id)
            count_query = count_query.where(
                AdminDisputeQueueRecord.assignee_id == assignee_id
            )

        if priority:
            query = query.where(AdminDisputeQueueRecord.priority == priority)
            count_query = count_query.where(
                AdminDisputeQueueRecord.priority == priority
            )

        total = int((await self.db.execute(count_query)).scalar_one() or 0)
        rows = (
            (
                await self.db.execute(
                    query.order_by(AdminDisputeQueueRecord.updated_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def update_dispute_queue_item(
        self,
        *,
        dispute_id: uuid.UUID,
        priority: str | None = None,
        assignee_id: uuid.UUID | None = None,
        sla_due_at: datetime | None = None,
        note: str | None = None,
    ) -> AdminDisputeQueueRecord:
        item = await self.get_dispute_queue_item(dispute_id=dispute_id)
        if item is None:
            raise ValueError("Dispute queue item not found")

        if priority is not None:
            item.priority = priority
        item.assignee_id = assignee_id
        if sla_due_at is not None:
            item.sla_due_at = sla_due_at

        metadata = item.metadata_json or {}
        if note:
            metadata["last_queue_note"] = note
        item.metadata_json = metadata
        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def create_dispute_evidence_request(
        self,
        *,
        dispute_id: uuid.UUID,
        requested_from_user_id: uuid.UUID,
        requested_by: uuid.UUID,
        note: str,
        due_at: datetime,
    ) -> AdminDisputeEvidenceRequestRecord:
        entry = AdminDisputeEvidenceRequestRecord(
            dispute_id=dispute_id,
            requested_from_user_id=requested_from_user_id,
            requested_by=requested_by,
            note=note,
            status="pending",
            due_at=due_at,
        )
        self.db.add(entry)
        await self.db.flush()
        await self.db.refresh(entry)
        return entry

    async def create_dispute_internal_note(
        self,
        *,
        dispute_id: uuid.UUID,
        author_id: uuid.UUID,
        note: str,
    ) -> AdminDisputeInternalNoteRecord:
        entry = AdminDisputeInternalNoteRecord(
            dispute_id=dispute_id,
            author_id=author_id,
            note=note,
        )
        self.db.add(entry)
        await self.db.flush()
        await self.db.refresh(entry)
        return entry

    async def create_dispute_resolution_rationale(
        self,
        *,
        dispute_id: uuid.UUID,
        escrow_id: uuid.UUID,
        resolution: str,
        rationale: str,
        apply_fee_refund: bool,
        fee_refund_status: str,
        decided_by: uuid.UUID,
    ) -> AdminDisputeResolutionRationaleRecord:
        entry = AdminDisputeResolutionRationaleRecord(
            dispute_id=dispute_id,
            escrow_id=escrow_id,
            resolution=resolution,
            rationale=rationale,
            apply_fee_refund=apply_fee_refund,
            fee_refund_status=fee_refund_status,
            decided_by=decided_by,
        )
        self.db.add(entry)
        await self.db.flush()
        await self.db.refresh(entry)
        return entry

    async def get_dispute_dashboard_counts(self) -> dict[str, int]:
        now = datetime.now(tz=timezone.utc)

        open_count = int(
            (
                await self.db.execute(
                    select(func.count(AdminDisputeQueueRecord.id)).where(
                        AdminDisputeQueueRecord.status == "open"
                    )
                )
            ).scalar_one()
            or 0
        )

        under_review_count = int(
            (
                await self.db.execute(
                    select(func.count(AdminDisputeQueueRecord.id)).where(
                        AdminDisputeQueueRecord.status == "under_review"
                    )
                )
            ).scalar_one()
            or 0
        )

        resolution_pending_count = int(
            (
                await self.db.execute(
                    select(func.count(AdminDisputeQueueRecord.id)).where(
                        AdminDisputeQueueRecord.status.like("resolution_pending_%")
                    )
                )
            ).scalar_one()
            or 0
        )

        resolved_count = int(
            (
                await self.db.execute(
                    select(func.count(AdminDisputeQueueRecord.id)).where(
                        AdminDisputeQueueRecord.status.like("resolved_%")
                    )
                )
            ).scalar_one()
            or 0
        )

        sla_breached_count = int(
            (
                await self.db.execute(
                    select(func.count(AdminDisputeQueueRecord.id)).where(
                        and_(
                            AdminDisputeQueueRecord.sla_due_at.is_not(None),
                            AdminDisputeQueueRecord.sla_due_at < now,
                            or_(
                                AdminDisputeQueueRecord.status == "open",
                                AdminDisputeQueueRecord.status == "under_review",
                                AdminDisputeQueueRecord.status.like(
                                    "resolution_pending_%"
                                ),
                            ),
                        )
                    )
                )
            ).scalar_one()
            or 0
        )

        return {
            "open": open_count,
            "under_review": under_review_count,
            "resolution_pending": resolution_pending_count,
            "resolved": resolved_count,
            "sla_breached": sla_breached_count,
        }

    async def upsert_payout_queue_item(
        self,
        *,
        payout_id: uuid.UUID,
        user_id: uuid.UUID,
        wallet_id: uuid.UUID,
        amount: int,
        currency: str,
        status: str,
        provider: str | None,
        provider_ref: str | None,
        failure_reason: str | None,
        payout_created_at: datetime,
    ) -> AdminPayoutQueueRecord:
        existing = await self.get_payout_queue_item(payout_id=payout_id)
        if existing:
            existing.user_id = user_id
            existing.wallet_id = wallet_id
            existing.amount = amount
            existing.currency = currency
            existing.status = status
            existing.provider = provider
            existing.provider_ref = provider_ref
            existing.failure_reason = failure_reason
            existing.created_at = payout_created_at
            await self.db.flush()
            await self.db.refresh(existing)
            return existing

        record = AdminPayoutQueueRecord(
            payout_id=payout_id,
            user_id=user_id,
            wallet_id=wallet_id,
            amount=amount,
            currency=currency,
            status=status,
            provider=provider,
            provider_ref=provider_ref,
            failure_reason=failure_reason,
            priority="normal",
            created_at=payout_created_at,
        )
        self.db.add(record)
        await self.db.flush()
        await self.db.refresh(record)
        return record

    async def get_payout_queue_item(
        self,
        *,
        payout_id: uuid.UUID,
    ) -> AdminPayoutQueueRecord | None:
        query = select(AdminPayoutQueueRecord).where(
            AdminPayoutQueueRecord.payout_id == payout_id
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_payout_queue_items(
        self,
        *,
        offset: int,
        limit: int,
        status_filter: str | None = None,
        assignee_id: uuid.UUID | None = None,
        priority: str | None = None,
        provider: str | None = None,
    ) -> tuple[list[AdminPayoutQueueRecord], int]:
        query = select(AdminPayoutQueueRecord)
        count_query = select(func.count(AdminPayoutQueueRecord.id))

        if status_filter:
            query = query.where(AdminPayoutQueueRecord.status == status_filter)
            count_query = count_query.where(
                AdminPayoutQueueRecord.status == status_filter
            )

        if assignee_id:
            query = query.where(AdminPayoutQueueRecord.assignee_id == assignee_id)
            count_query = count_query.where(
                AdminPayoutQueueRecord.assignee_id == assignee_id
            )

        if priority:
            query = query.where(AdminPayoutQueueRecord.priority == priority)
            count_query = count_query.where(AdminPayoutQueueRecord.priority == priority)

        if provider:
            query = query.where(AdminPayoutQueueRecord.provider == provider)
            count_query = count_query.where(AdminPayoutQueueRecord.provider == provider)

        total = int((await self.db.execute(count_query)).scalar_one() or 0)
        rows = (
            (
                await self.db.execute(
                    query.order_by(AdminPayoutQueueRecord.updated_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def update_payout_queue_item(
        self,
        *,
        payout_id: uuid.UUID,
        priority: str | None = None,
        assignee_id: uuid.UUID | None = None,
        note: str | None = None,
    ) -> AdminPayoutQueueRecord:
        item = await self.get_payout_queue_item(payout_id=payout_id)
        if item is None:
            raise ValueError("Payout queue item not found")

        if priority is not None:
            item.priority = priority
        item.assignee_id = assignee_id

        metadata = item.metadata_json or {}
        if note:
            metadata["last_queue_note"] = note
        item.metadata_json = metadata
        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def increment_payout_retry(
        self,
        *,
        payout_id: uuid.UUID,
        note: str | None = None,
        status: str | None = None,
    ) -> AdminPayoutQueueRecord:
        item = await self.get_payout_queue_item(payout_id=payout_id)
        if item is None:
            raise ValueError("Payout queue item not found")

        item.retry_count = int(item.retry_count or 0) + 1
        item.last_retry_at = datetime.now(tz=timezone.utc)
        if status is not None:
            item.status = status

        metadata = item.metadata_json or {}
        if note:
            metadata["last_retry_note"] = note
        item.metadata_json = metadata

        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def get_financial_dashboard_counts(self) -> dict[str, int]:
        pending = int(
            (
                await self.db.execute(
                    select(func.count(AdminPayoutQueueRecord.id)).where(
                        AdminPayoutQueueRecord.status == "pending"
                    )
                )
            ).scalar_one()
            or 0
        )
        processing = int(
            (
                await self.db.execute(
                    select(func.count(AdminPayoutQueueRecord.id)).where(
                        AdminPayoutQueueRecord.status == "processing"
                    )
                )
            ).scalar_one()
            or 0
        )
        success = int(
            (
                await self.db.execute(
                    select(func.count(AdminPayoutQueueRecord.id)).where(
                        AdminPayoutQueueRecord.status == "success"
                    )
                )
            ).scalar_one()
            or 0
        )
        failed = int(
            (
                await self.db.execute(
                    select(func.count(AdminPayoutQueueRecord.id)).where(
                        AdminPayoutQueueRecord.status == "failed"
                    )
                )
            ).scalar_one()
            or 0
        )
        retrying = int(
            (
                await self.db.execute(
                    select(func.count(AdminPayoutQueueRecord.id)).where(
                        AdminPayoutQueueRecord.retry_count > 0,
                        AdminPayoutQueueRecord.status != "success",
                    )
                )
            ).scalar_one()
            or 0
        )
        high_priority = int(
            (
                await self.db.execute(
                    select(func.count(AdminPayoutQueueRecord.id)).where(
                        AdminPayoutQueueRecord.priority.in_(["high", "critical"]),
                        AdminPayoutQueueRecord.status != "success",
                    )
                )
            ).scalar_one()
            or 0
        )

        return {
            "pending": pending,
            "processing": processing,
            "success": success,
            "failed": failed,
            "retrying": retrying,
            "high_priority": high_priority,
        }

    async def list_dispute_queue_since(
        self,
        *,
        since: datetime,
    ) -> list[AdminDisputeQueueRecord]:
        result = await self.db.execute(
            select(AdminDisputeQueueRecord).where(
                AdminDisputeQueueRecord.created_at >= since
            )
        )
        return list(result.scalars().all())

    async def list_payout_queue_since(
        self,
        *,
        since: datetime,
    ) -> list[AdminPayoutQueueRecord]:
        result = await self.db.execute(
            select(AdminPayoutQueueRecord).where(
                AdminPayoutQueueRecord.created_at >= since
            )
        )
        return list(result.scalars().all())

    async def get_financial_reconciliation_summary(self) -> dict[str, int]:
        (
            total_transactions,
            total_volume,
            pending_amount,
            processing_amount,
            success_amount,
            failed_amount,
        ) = (
            await self.db.execute(
                select(
                    func.count(AdminPayoutQueueRecord.id),
                    func.coalesce(func.sum(AdminPayoutQueueRecord.amount), 0),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    AdminPayoutQueueRecord.status == "pending",
                                    AdminPayoutQueueRecord.amount,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    AdminPayoutQueueRecord.status == "processing",
                                    AdminPayoutQueueRecord.amount,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    AdminPayoutQueueRecord.status == "success",
                                    AdminPayoutQueueRecord.amount,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    AdminPayoutQueueRecord.status == "failed",
                                    AdminPayoutQueueRecord.amount,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                )
            )
        ).one()

        return {
            "total_transactions": int(total_transactions or 0),
            "total_volume": int(total_volume or 0),
            "pending_amount": int(pending_amount or 0),
            "processing_amount": int(processing_amount or 0),
            "success_amount": int(success_amount or 0),
            "failed_amount": int(failed_amount or 0),
        }

    async def get_failed_fee_refund_count(self) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count(AdminDisputeResolutionRationaleRecord.id)).where(
                        AdminDisputeResolutionRationaleRecord.fee_refund_status
                        == "failed"
                    )
                )
            ).scalar_one()
            or 0
        )
