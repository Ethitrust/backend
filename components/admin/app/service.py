"""Business logic for the Admin service."""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status

from app import grpc_clients
from app.db import (
    AdminActionLogRecord,
    AdminDisputeQueueRecord,
    AdminPayoutQueueRecord,
    AdminReportJobRecord,
    AdminSavedViewRecord,
    AdminSystemConfigHistoryRecord,
    AdminSystemConfigRecord,
)
from app.models import (
    AdminActionLog,
    AdminActionLogListResponse,
    AdminEscrowSummary,
    AdminUserSummary,
    AnalyticsDisputeThroughputResponse,
    AnalyticsGrowthResponse,
    AnalyticsKpiPoint,
    AnalyticsPayoutHealthResponse,
    AnalyticsVolumeResponse,
    BulkUserBanItemResult,
    BulkUserBanRequest,
    BulkUserBanResponse,
    DisputeDashboardCountersResponse,
    DisputeEvidenceRequestCreate,
    DisputeEvidenceRequestResponse,
    DisputeInternalNoteCreate,
    DisputeInternalNoteResponse,
    DisputeMoveReviewRequest,
    DisputeQueueItem,
    DisputeQueueListResponse,
    DisputeQueueUpdateRequest,
    DisputeResolutionDecisionRequest,
    DisputeResolutionDecisionResponse,
    FinancialDashboardCountersResponse,
    FinancialReconciliationSummaryResponse,
    ModerationNoteCreateRequest,
    ModerationNoteResponse,
    PayoutQueueItem,
    PayoutQueueListResponse,
    PayoutQueueUpdateRequest,
    PayoutRetryRequest,
    PayoutRetryResponse,
    PlatformStats,
    ReportJobCreateRequest,
    ReportJobListResponse,
    ReportJobResponse,
    SavedViewCreateRequest,
    SavedViewListResponse,
    SavedViewResponse,
    SavedViewUpdateRequest,
    SystemConfigDryRunResponse,
    SystemConfigHistoryItem,
    SystemConfigHistoryResponse,
    SystemConfigItem,
    SystemConfigListResponse,
    SystemConfigMutationResponse,
    SystemConfigRollbackRequest,
    SystemConfigUpsertRequest,
    UserAdminView,
    UserModerationTimelineItem,
    UserModerationTimelineResponse,
    UserRiskFlagRequest,
    UserRiskFlagResponse,
    UserVerificationOverrideRequest,
    UserVerificationOverrideResponse,
)
from app.repository import AdminRepository

logger = logging.getLogger(__name__)

_DEFAULT_PLATFORM_FEE_PERCENT = 1.5
_DEFAULT_MIN_FEE_AMOUNT = 100  # 1 birr in smallest denomination
_DEFAULT_MAX_FEE_AMOUNT = 1000  # 10 birr in smallest denomination

_VERIFY_OVERRIDE_ACTION = "users.verification.override"
_BULK_BAN_ACTION = "users.bulk.ban"
_DISPUTE_ACTIVE_STATUSES = {"open", "under_review"}
_SYSTEM_CONFIG_RULES: dict[str, dict[str, Any]] = {
    "fees.platform_fee_percent": {"type": "number", "min": 0.0, "max": 100.0},
    "fees.min_fee_amount": {"type": "int", "min": 0},
    "fees.max_fee_amount": {"type": "int", "min": 0},
    "thresholds.high_risk_payout_amount": {"type": "int", "min": 0},
    "enforcement.require_dual_approval_for_high_risk_actions": {"type": "bool"},
    "enforcement.allow_force_payout_actions": {"type": "bool"},
}


class AdminService:
    def __init__(self, repo: AdminRepository) -> None:
        self.repo = repo

    async def _emit_mutation_audit(
        self,
        *,
        actor_id: uuid.UUID,
        action: str,
        target_type: str,
        target_id: uuid.UUID,
        before: dict | None = None,
        after: dict | None = None,
        metadata: dict | None = None,
    ) -> None:
        await grpc_clients.emit_audit_log(
            actor_id=actor_id,
            action=action,
            resource=target_type,
            resource_id=target_id,
            before=before,
            after=after,
            metadata=metadata,
        )

    async def _save_idempotent_response(
        self,
        *,
        action: str,
        idempotency_key: str,
        actor_id: uuid.UUID,
        request_payload: dict | None,
        response_payload: dict | None,
    ) -> None:
        await self.repo.save_idempotency_record(
            action=action,
            idempotency_key=idempotency_key,
            actor_id=actor_id,
            request_payload=request_payload,
            response_payload=response_payload,
        )

    async def _log_action(
        self,
        *,
        admin_id: uuid.UUID,
        action: str,
        target_type: str,
        target_id: uuid.UUID | None = None,
        details: dict | None = None,
    ) -> None:
        entry = AdminActionLogRecord(
            admin_id=admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )
        await self.repo.create_action_log(entry)

    async def list_users(self, offset: int, limit: int) -> list[UserAdminView]:
        users = await grpc_clients.get_all_users(offset, limit)
        return [UserAdminView(**u) for u in users]

    @staticmethod
    def _normalize_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value

        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return datetime.now(tz=timezone.utc)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed

        return datetime.now(tz=timezone.utc)

    @staticmethod
    def _status_is_sla_eligible(status_value: str) -> bool:
        return status_value in _DISPUTE_ACTIVE_STATUSES or status_value.startswith(
            "resolution_pending_"
        )

    def _queue_row_to_response(self, row: AdminDisputeQueueRecord) -> DisputeQueueItem:
        now = datetime.now(tz=timezone.utc)
        created_at = self._normalize_datetime(row.created_at)
        updated_at = self._normalize_datetime(row.updated_at)
        sla_due_at = self._normalize_datetime(row.sla_due_at) if row.sla_due_at else None
        is_sla_breached = bool(
            sla_due_at and sla_due_at < now and self._status_is_sla_eligible(row.status)
        )
        return DisputeQueueItem(
            dispute_id=row.dispute_id,
            escrow_id=row.escrow_id,
            status=row.status,
            reason=row.reason,
            raised_by=row.raised_by,
            priority=row.priority,
            assignee_id=row.assignee_id,
            sla_due_at=sla_due_at,
            created_at=created_at,
            updated_at=updated_at,
            is_sla_breached=is_sla_breached,
        )

    def _payout_queue_row_to_response(self, row: AdminPayoutQueueRecord) -> PayoutQueueItem:
        return PayoutQueueItem(
            payout_id=row.payout_id,
            user_id=row.user_id,
            wallet_id=row.wallet_id,
            amount=row.amount,
            currency=row.currency,
            status=row.status,
            provider=row.provider,
            provider_ref=row.provider_ref,
            failure_reason=row.failure_reason,
            priority=row.priority,
            assignee_id=row.assignee_id,
            retry_count=row.retry_count,
            last_retry_at=row.last_retry_at,
            created_at=self._normalize_datetime(row.created_at),
            updated_at=self._normalize_datetime(row.updated_at),
        )

    @staticmethod
    def _normalize_config_key(config_key: str) -> str:
        return config_key.strip().lower()

    @staticmethod
    def _config_target_uuid(config_key: str) -> uuid.UUID:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"admin.system_config:{config_key}")

    def _system_config_row_to_response(self, row: AdminSystemConfigRecord) -> SystemConfigItem:
        return SystemConfigItem(
            key=row.config_key,
            value=row.value_json,
            version=row.version,
            updated_by=row.updated_by,
            created_at=self._normalize_datetime(row.created_at),
            updated_at=self._normalize_datetime(row.updated_at),
        )

    def _system_config_history_row_to_response(
        self, row: AdminSystemConfigHistoryRecord
    ) -> SystemConfigHistoryItem:
        return SystemConfigHistoryItem(
            id=row.id,
            key=row.config_key,
            version=row.version,
            action=row.action,
            previous_value=row.previous_value,
            new_value=row.new_value,
            changed_by=row.changed_by,
            reason=row.reason,
            metadata=row.metadata_json,
            created_at=self._normalize_datetime(row.created_at),
        )

    @staticmethod
    def _day_bucket(value: datetime) -> datetime:
        normalized = value.astimezone(timezone.utc)
        return normalized.replace(hour=0, minute=0, second=0, microsecond=0)

    @staticmethod
    def _build_day_value_map(*, since: datetime, window_days: int) -> dict[datetime, float]:
        return {(since + timedelta(days=offset)): 0.0 for offset in range(window_days)}

    def _daily_points(self, values: dict[datetime, float]) -> list[AnalyticsKpiPoint]:
        return [
            AnalyticsKpiPoint(bucket=bucket, value=round(value, 4))
            for bucket, value in sorted(values.items(), key=lambda item: item[0])
        ]

    @staticmethod
    def _report_job_to_response(row: AdminReportJobRecord) -> ReportJobResponse:
        return ReportJobResponse.model_validate(row)

    @staticmethod
    def _saved_view_to_response(row: AdminSavedViewRecord) -> SavedViewResponse:
        return SavedViewResponse.model_validate(row)

    @staticmethod
    def _as_int(value: Any, *, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed

    def _parse_window_days(self, filters: dict[str, Any] | None, *, default: int = 30) -> int:
        if not filters:
            return default
        parsed = self._as_int(filters.get("window_days"), default=default)
        if parsed < 1 or parsed > 365:
            return default
        return parsed

    @staticmethod
    def _report_payload_to_csv(payload: Any) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["section", "metric", "bucket", "value"])

        def _walk(section: str, value: Any) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    next_section = f"{section}.{key}" if section else key
                    _walk(next_section, nested)
                return

            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and "bucket" in item and "value" in item:
                        writer.writerow([section, "series", item["bucket"], item["value"]])
                    else:
                        writer.writerow([section, "list_item", "", json.dumps(item, default=str)])
                return

            writer.writerow([section, "value", "", value])

        _walk("report", payload)
        return buffer.getvalue()

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        return None

    @staticmethod
    def _coerce_number(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return None

    async def _get_system_config_value_map(self) -> dict[str, Any]:
        rows = await self.repo.list_system_configs()
        return {row.config_key: row.value_json for row in rows}

    def _validate_system_config_value(
        self,
        *,
        config_key: str,
        value: Any,
        existing_values: dict[str, Any],
    ) -> tuple[Any, list[str]]:
        errors: list[str] = []
        rule = _SYSTEM_CONFIG_RULES.get(config_key)
        if rule is None:
            return value, [f"Unsupported system config key '{config_key}'"]

        expected_type = str(rule.get("type"))
        normalized: Any = value

        if expected_type == "bool":
            if not isinstance(value, bool):
                errors.append("Expected a boolean value")
        elif expected_type == "int":
            maybe_int = self._coerce_int(value)
            if maybe_int is None:
                errors.append("Expected an integer value")
            else:
                normalized = maybe_int
        elif expected_type == "number":
            maybe_number = self._coerce_number(value)
            if maybe_number is None:
                errors.append("Expected a numeric value")
            else:
                normalized = maybe_number
        else:
            errors.append("Unsupported config rule type")

        if errors:
            return value, errors

        min_value = rule.get("min")
        max_value = rule.get("max")
        if min_value is not None and normalized < min_value:
            errors.append(f"Value must be >= {min_value}")
        if max_value is not None and normalized > max_value:
            errors.append(f"Value must be <= {max_value}")

        min_fee = (
            normalized
            if config_key == "fees.min_fee_amount"
            else self._coerce_int(existing_values.get("fees.min_fee_amount"))
        )
        max_fee = (
            normalized
            if config_key == "fees.max_fee_amount"
            else self._coerce_int(existing_values.get("fees.max_fee_amount"))
        )
        if min_fee is not None and max_fee is not None and min_fee > max_fee:
            errors.append("fees.min_fee_amount cannot be greater than fees.max_fee_amount")

        return normalized, errors

    async def resolve_fee_policy(
        self,
        *,
        amount: int,
        who_pays: str,
    ) -> dict[str, Any]:
        if amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="amount must be greater than 0",
            )

        normalized_who_pays = who_pays.lower().strip()
        if normalized_who_pays == "both":
            normalized_who_pays = "split"
        if normalized_who_pays not in {"buyer", "seller", "split"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="who_pays must be one of: buyer, seller, split",
            )

        existing_values = await self._get_system_config_value_map()

        raw_percent = self._coerce_number(existing_values.get("fees.platform_fee_percent"))
        raw_min_fee = self._coerce_int(existing_values.get("fees.min_fee_amount"))
        raw_max_fee = self._coerce_int(existing_values.get("fees.max_fee_amount"))

        platform_fee_percent = _DEFAULT_PLATFORM_FEE_PERCENT if raw_percent is None else raw_percent
        platform_fee_percent = min(100.0, max(0.0, platform_fee_percent))

        min_fee_amount = _DEFAULT_MIN_FEE_AMOUNT if raw_min_fee is None else raw_min_fee
        max_fee_amount = _DEFAULT_MAX_FEE_AMOUNT if raw_max_fee is None else raw_max_fee

        if min_fee_amount < 0:
            min_fee_amount = 0
        if max_fee_amount < 0:
            max_fee_amount = 0
        if min_fee_amount > max_fee_amount:
            min_fee_amount = _DEFAULT_MIN_FEE_AMOUNT
            max_fee_amount = _DEFAULT_MAX_FEE_AMOUNT

        raw_fee = int(amount * platform_fee_percent / 100)
        fee_amount = max(min_fee_amount, min(raw_fee, max_fee_amount))

        if normalized_who_pays == "buyer":
            buyer_fee, seller_fee = fee_amount, 0
        elif normalized_who_pays == "seller":
            buyer_fee, seller_fee = 0, fee_amount
        else:
            buyer_fee = fee_amount // 2
            seller_fee = fee_amount - buyer_fee

        used_override = any(
            key in existing_values
            for key in (
                "fees.platform_fee_percent",
                "fees.min_fee_amount",
                "fees.max_fee_amount",
            )
        )

        return {
            "fee_amount": fee_amount,
            "buyer_fee": buyer_fee,
            "seller_fee": seller_fee,
            "platform_fee_percent": float(platform_fee_percent),
            "min_fee_amount": min_fee_amount,
            "max_fee_amount": max_fee_amount,
            "used_override": used_override,
        }

    async def _upsert_queue_from_dispute_payload(self, payload: dict[str, Any]) -> None:
        try:
            dispute_id = uuid.UUID(str(payload["id"]))
            escrow_id = uuid.UUID(str(payload["escrow_id"]))
            raised_by = uuid.UUID(str(payload["raised_by"]))
            status_value = str(payload["status"])
            reason = str(payload["reason"])
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Dispute service returned malformed dispute payload",
            ) from exc

        dispute_created_at = self._normalize_datetime(payload.get("created_at"))
        await self.repo.upsert_dispute_queue_item(
            dispute_id=dispute_id,
            escrow_id=escrow_id,
            status=status_value,
            reason=reason,
            raised_by=raised_by,
            dispute_created_at=dispute_created_at,
        )

    async def _upsert_queue_from_payout_payload(self, payload: dict[str, Any]) -> None:
        try:
            payout_id = uuid.UUID(str(payload["id"]))
            user_id = uuid.UUID(str(payload["user_id"]))
            wallet_id = uuid.UUID(str(payload["wallet_id"]))
            amount = int(payload["amount"])
            currency = str(payload["currency"])
            status_value = str(payload["status"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Payout service returned malformed payout payload",
            ) from exc

        await self.repo.upsert_payout_queue_item(
            payout_id=payout_id,
            user_id=user_id,
            wallet_id=wallet_id,
            amount=amount,
            currency=currency,
            status=status_value,
            provider=str(payload.get("provider")) if payload.get("provider") else None,
            provider_ref=(
                str(payload.get("provider_ref")) if payload.get("provider_ref") else None
            ),
            failure_reason=(
                str(payload.get("failure_reason")) if payload.get("failure_reason") else None
            ),
            payout_created_at=self._normalize_datetime(payload.get("created_at")),
        )

    async def update_role(
        self, user_id: uuid.UUID, role: str, admin_id: uuid.UUID
    ) -> UserAdminView:
        if role not in ("admin", "moderator", "user"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")

        before_role: str | None = None
        try:
            profile = await grpc_clients.get_user_by_id(str(user_id))
            before_role = profile.get("role")
        except RuntimeError:
            logger.exception("unable to fetch current user role for audit user_id=%s", user_id)

        result = await grpc_clients.update_user_role(user_id, role)
        await self._log_action(
            admin_id=admin_id,
            action="user.role_updated",
            target_type="user",
            target_id=user_id,
            details={"previous_role": before_role, "new_role": role},
        )
        await self._emit_mutation_audit(
            actor_id=admin_id,
            action="user.role_updated",
            target_type="user",
            target_id=user_id,
            before={"role": before_role} if before_role is not None else None,
            after={"role": role},
            metadata={"source": "admin-service"},
        )
        return UserAdminView(
            id=uuid.UUID(result["id"]),
            email="",
            role=result["role"],
            is_active=True,
        )

    async def ban_user(
        self, user_id: uuid.UUID, ban: bool, reason: str, admin_id: uuid.UUID
    ) -> dict:
        before_is_banned: bool | None = None
        try:
            profile = await grpc_clients.get_user_by_id(str(user_id))
            before_is_banned = bool(profile.get("is_banned"))
        except RuntimeError:
            logger.exception("unable to fetch current user status for audit user_id=%s", user_id)

        result = await grpc_clients.ban_user(user_id, ban, reason)
        action = "user.banned" if ban else "user.unbanned"
        await self._log_action(
            admin_id=admin_id,
            action=action,
            target_type="user",
            target_id=user_id,
            details={"reason": reason, "ban": ban},
        )
        await self._emit_mutation_audit(
            actor_id=admin_id,
            action=action,
            target_type="user",
            target_id=user_id,
            before=({"is_banned": before_is_banned} if before_is_banned is not None else None),
            after={"is_banned": ban, "is_active": result["is_active"]},
            metadata={"reason": reason, "source": "admin-service"},
        )
        return result

    async def list_dispute_queue(
        self,
        *,
        token: str,
        page: int,
        limit: int,
        status_filter: str | None,
        assignee_id: uuid.UUID | None,
        priority: str | None,
    ) -> DisputeQueueListResponse:
        try:
            upstream = await grpc_clients.list_disputes(
                token=token,
                status_filter=status_filter,
                page=page,
                limit=limit,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to fetch dispute queue from dispute service",
            ) from exc

        for item in upstream.get("items", []):
            await self._upsert_queue_from_dispute_payload(item)

        offset = (page - 1) * limit
        status_filters = [status_filter] if status_filter else None
        rows, total = await self.repo.list_dispute_queue_items(
            offset=offset,
            limit=limit,
            status_filters=status_filters,
            assignee_id=assignee_id,
            priority=priority,
        )
        return DisputeQueueListResponse(
            items=[self._queue_row_to_response(row) for row in rows],
            total=total,
            page=page,
            limit=limit,
        )

    @staticmethod
    def _maybe_uuid(value: Any) -> uuid.UUID | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return uuid.UUID(text)
        except ValueError:
            return None

    @staticmethod
    def _user_summary(profile: dict[str, Any]) -> AdminUserSummary:
        user_id = uuid.UUID(str(profile["user_id"]))
        return AdminUserSummary(
            user_id=user_id,
            email=profile.get("email"),
            role=profile.get("role"),
            is_verified=profile.get("is_verified"),
            is_banned=profile.get("is_banned"),
            kyc_level=int(profile["kyc_level"]) if profile.get("kyc_level") is not None else None,
        )

    async def get_dispute_queue_item_detail(
        self,
        *,
        dispute_id: uuid.UUID,
        token: str,
    ) -> DisputeQueueItem:
        row = await self.repo.get_dispute_queue_item(dispute_id=dispute_id)
        if row is None:
            try:
                upstream = await grpc_clients.list_disputes(
                    token=token,
                    status_filter=None,
                    page=1,
                    limit=200,
                )
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Unable to fetch dispute details from dispute service",
                ) from exc

            for item in upstream.get("items", []):
                await self._upsert_queue_from_dispute_payload(item)

            row = await self.repo.get_dispute_queue_item(dispute_id=dispute_id)
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Dispute queue item not found",
                )

        result = self._queue_row_to_response(row)

        try:
            escrow_payload = await grpc_clients.get_escrow(escrow_id=row.escrow_id)
        except RuntimeError:
            escrow_payload = None

        if escrow_payload is not None:
            initiator_id = self._maybe_uuid(escrow_payload.get("initiator_id"))
            receiver_id = self._maybe_uuid(escrow_payload.get("receiver_id"))
            result.escrow = AdminEscrowSummary(
                escrow_id=uuid.UUID(str(escrow_payload["escrow_id"])),
                status=str(escrow_payload["status"]),
                escrow_type=str(escrow_payload["escrow_type"]),
                initiator_id=initiator_id,
                receiver_id=receiver_id,
                amount=int(escrow_payload["amount"]),
                currency=str(escrow_payload["currency"]),
            )

            try:
                raised_profile = await grpc_clients.get_user_by_id(str(row.raised_by))
                result.raised_by_user = self._user_summary(raised_profile)
            except RuntimeError:
                pass

            if initiator_id is not None:
                try:
                    initiator_profile = await grpc_clients.get_user_by_id(str(initiator_id))
                    result.initiator_user = self._user_summary(initiator_profile)
                except RuntimeError:
                    pass

            if receiver_id is not None:
                try:
                    receiver_profile = await grpc_clients.get_user_by_id(str(receiver_id))
                    result.receiver_user = self._user_summary(receiver_profile)
                except RuntimeError:
                    pass

        return result

    async def update_dispute_queue_item(
        self,
        *,
        dispute_id: uuid.UUID,
        body: DisputeQueueUpdateRequest,
        admin_id: uuid.UUID,
    ) -> DisputeQueueItem:
        before = await self.repo.get_dispute_queue_item(dispute_id=dispute_id)
        if before is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dispute queue item not found",
            )

        sla_due_at = None
        if body.sla_hours is not None:
            sla_due_at = datetime.now(tz=timezone.utc) + timedelta(hours=body.sla_hours)

        updated = await self.repo.update_dispute_queue_item(
            dispute_id=dispute_id,
            priority=body.priority,
            assignee_id=body.assignee_id,
            sla_due_at=sla_due_at,
            note=body.note,
        )
        await self._log_action(
            admin_id=admin_id,
            action="dispute.queue.updated",
            target_type="dispute",
            target_id=dispute_id,
            details={
                "priority": body.priority,
                "assignee_id": str(body.assignee_id) if body.assignee_id else None,
                "sla_hours": body.sla_hours,
                "note": body.note,
            },
        )
        await self._emit_mutation_audit(
            actor_id=admin_id,
            action="dispute.queue.updated",
            target_type="dispute",
            target_id=dispute_id,
            before={
                "priority": before.priority,
                "assignee_id": str(before.assignee_id) if before.assignee_id else None,
                "sla_due_at": before.sla_due_at.isoformat() if before.sla_due_at else None,
            },
            after={
                "priority": updated.priority,
                "assignee_id": str(updated.assignee_id) if updated.assignee_id else None,
                "sla_due_at": updated.sla_due_at.isoformat() if updated.sla_due_at else None,
            },
            metadata={"source": "admin-service"},
        )
        return self._queue_row_to_response(updated)

    async def create_dispute_evidence_request(
        self,
        *,
        dispute_id: uuid.UUID,
        body: DisputeEvidenceRequestCreate,
        admin_id: uuid.UUID,
    ) -> DisputeEvidenceRequestResponse:
        due_at = datetime.now(tz=timezone.utc) + timedelta(hours=body.due_in_hours)
        record = await self.repo.create_dispute_evidence_request(
            dispute_id=dispute_id,
            requested_from_user_id=body.requested_from_user_id,
            requested_by=admin_id,
            note=body.note,
            due_at=due_at,
        )
        await self._log_action(
            admin_id=admin_id,
            action="dispute.evidence.requested",
            target_type="dispute",
            target_id=dispute_id,
            details={
                "requested_from_user_id": str(body.requested_from_user_id),
                "due_at": due_at.isoformat(),
            },
        )
        await self._emit_mutation_audit(
            actor_id=admin_id,
            action="dispute.evidence.requested",
            target_type="dispute",
            target_id=dispute_id,
            after={
                "requested_from_user_id": str(body.requested_from_user_id),
                "due_at": due_at.isoformat(),
            },
            metadata={"source": "admin-service"},
        )
        return DisputeEvidenceRequestResponse.model_validate(record)

    async def add_dispute_internal_note(
        self,
        *,
        dispute_id: uuid.UUID,
        body: DisputeInternalNoteCreate,
        admin_id: uuid.UUID,
    ) -> DisputeInternalNoteResponse:
        note = await self.repo.create_dispute_internal_note(
            dispute_id=dispute_id,
            author_id=admin_id,
            note=body.note,
        )
        await self._log_action(
            admin_id=admin_id,
            action="dispute.internal_note_added",
            target_type="dispute",
            target_id=dispute_id,
            details={"note_length": len(body.note)},
        )
        return DisputeInternalNoteResponse.model_validate(note)

    async def move_dispute_to_review(
        self,
        *,
        dispute_id: uuid.UUID,
        body: DisputeMoveReviewRequest,
        admin_id: uuid.UUID,
        token: str,
    ) -> DisputeQueueItem:
        try:
            dispute_payload = await grpc_clients.mark_dispute_under_review(
                dispute_id=dispute_id,
                token=token,
                note=body.note,
                reviewer_id=admin_id,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to move dispute into review",
            ) from exc

        await self._upsert_queue_from_dispute_payload(dispute_payload)
        updated = await self.repo.update_dispute_queue_item(
            dispute_id=dispute_id,
            assignee_id=admin_id,
            note=body.note,
        )
        await self._log_action(
            admin_id=admin_id,
            action="dispute.review.started",
            target_type="dispute",
            target_id=dispute_id,
            details={"note": body.note},
        )
        await self._emit_mutation_audit(
            actor_id=admin_id,
            action="dispute.review.started",
            target_type="dispute",
            target_id=dispute_id,
            after={"status": updated.status, "assignee_id": str(admin_id)},
            metadata={"source": "admin-service"},
        )
        return self._queue_row_to_response(updated)

    async def decide_dispute_resolution(
        self,
        *,
        dispute_id: uuid.UUID,
        body: DisputeResolutionDecisionRequest,
        admin_id: uuid.UUID,
        token: str,
    ) -> DisputeResolutionDecisionResponse:
        before = await self.repo.get_dispute_queue_item(dispute_id=dispute_id)

        try:
            await grpc_clients.request_dispute_resolution(
                escrow_id=body.escrow_id,
                dispute_id=dispute_id,
                token=token,
                resolution=body.resolution,
                resolution_note=body.resolution_note,
                admin_id=admin_id,
            )
            executed_payload = await grpc_clients.execute_dispute_resolution(
                dispute_id=dispute_id,
                resolution=body.resolution,
                admin_id=admin_id,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to complete dispute resolution workflow",
            ) from exc

        await self._upsert_queue_from_dispute_payload(executed_payload)

        fee_refund_status = "not_applicable"
        if body.resolution == "buyer":
            if body.apply_fee_refund:
                try:
                    refund_entries = await grpc_clients.refund_fee_for_escrow(
                        escrow_id=body.escrow_id
                    )
                    fee_refund_status = "applied" if refund_entries else "no_fee_entries_found"
                except RuntimeError:
                    logger.exception(
                        "fee refund failed for escrow_id=%s dispute_id=%s",
                        body.escrow_id,
                        dispute_id,
                    )
                    fee_refund_status = "failed"
            else:
                fee_refund_status = "skipped"

        rationale = await self.repo.create_dispute_resolution_rationale(
            dispute_id=dispute_id,
            escrow_id=body.escrow_id,
            resolution=body.resolution,
            rationale=body.resolution_note,
            apply_fee_refund=body.apply_fee_refund,
            fee_refund_status=fee_refund_status,
            decided_by=admin_id,
        )

        queue_item = await self.repo.get_dispute_queue_item(dispute_id=dispute_id)
        if queue_item is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to synchronize resolved dispute queue item",
            )

        await self._log_action(
            admin_id=admin_id,
            action="dispute.resolution.executed",
            target_type="dispute",
            target_id=dispute_id,
            details={
                "escrow_id": str(body.escrow_id),
                "resolution": body.resolution,
                "fee_refund_status": fee_refund_status,
                "rationale_id": str(rationale.id),
            },
        )
        await self._emit_mutation_audit(
            actor_id=admin_id,
            action="dispute.resolution.executed",
            target_type="dispute",
            target_id=dispute_id,
            before={"status": before.status if before else None},
            after={"status": queue_item.status, "resolution": body.resolution},
            metadata={"source": "admin-service"},
        )
        return DisputeResolutionDecisionResponse(
            dispute_id=dispute_id,
            escrow_id=body.escrow_id,
            status=queue_item.status,
            resolution=body.resolution,
            fee_refund_status=fee_refund_status,
            rationale_id=rationale.id,
        )

    async def get_dispute_dashboard_counters(self) -> DisputeDashboardCountersResponse:
        counts = await self.repo.get_dispute_dashboard_counts()
        return DisputeDashboardCountersResponse(**counts)

    async def list_payout_queue(
        self,
        *,
        token: str,
        page: int,
        limit: int,
        status_filter: str | None,
        assignee_id: uuid.UUID | None,
        priority: str | None,
        provider: str | None,
    ) -> PayoutQueueListResponse:
        try:
            upstream = await grpc_clients.list_payouts(
                status_filter=status_filter,
                page=page,
                limit=limit,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to fetch payout queue from payout service",
            ) from exc

        for item in upstream.get("items", []):
            await self._upsert_queue_from_payout_payload(item)

        offset = (page - 1) * limit
        rows, total = await self.repo.list_payout_queue_items(
            offset=offset,
            limit=limit,
            status_filter=status_filter,
            assignee_id=assignee_id,
            priority=priority,
            provider=provider,
        )
        return PayoutQueueListResponse(
            items=[self._payout_queue_row_to_response(row) for row in rows],
            total=total,
            page=page,
            limit=limit,
        )

    async def update_payout_queue_item(
        self,
        *,
        payout_id: uuid.UUID,
        body: PayoutQueueUpdateRequest,
        admin_id: uuid.UUID,
    ) -> PayoutQueueItem:
        before = await self.repo.get_payout_queue_item(payout_id=payout_id)
        if before is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payout queue item not found",
            )

        updated = await self.repo.update_payout_queue_item(
            payout_id=payout_id,
            priority=body.priority,
            assignee_id=body.assignee_id,
            note=body.note,
        )
        await self._log_action(
            admin_id=admin_id,
            action="payout.queue.updated",
            target_type="payout",
            target_id=payout_id,
            details={
                "priority": body.priority,
                "assignee_id": str(body.assignee_id) if body.assignee_id else None,
                "note": body.note,
            },
        )
        await self._emit_mutation_audit(
            actor_id=admin_id,
            action="payout.queue.updated",
            target_type="payout",
            target_id=payout_id,
            before={
                "priority": before.priority,
                "assignee_id": str(before.assignee_id) if before.assignee_id else None,
            },
            after={
                "priority": updated.priority,
                "assignee_id": str(updated.assignee_id) if updated.assignee_id else None,
            },
            metadata={"source": "admin-service"},
        )
        return self._payout_queue_row_to_response(updated)

    async def retry_payout_transfer(
        self,
        *,
        payout_id: uuid.UUID,
        body: PayoutRetryRequest,
        admin_id: uuid.UUID,
        token: str,
    ) -> PayoutRetryResponse:
        before = await self.repo.get_payout_queue_item(payout_id=payout_id)
        if before is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payout queue item not found",
            )

        if before.status == "success":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Payout is already successful and cannot be retried",
            )

        try:
            upstream = await grpc_clients.retry_payout_transfer(
                payout_id=payout_id,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to retry payout transfer",
            ) from exc

        await self._upsert_queue_from_payout_payload(upstream)
        updated = await self.repo.increment_payout_retry(
            payout_id=payout_id,
            note=body.note,
            status=str(upstream.get("status") or before.status),
        )

        await self._log_action(
            admin_id=admin_id,
            action="payout.retry.executed",
            target_type="payout",
            target_id=payout_id,
            details={
                "previous_status": before.status,
                "current_status": updated.status,
                "retry_count": updated.retry_count,
                "note": body.note,
            },
        )
        await self._emit_mutation_audit(
            actor_id=admin_id,
            action="payout.retry.executed",
            target_type="payout",
            target_id=payout_id,
            before={"status": before.status, "retry_count": before.retry_count},
            after={"status": updated.status, "retry_count": updated.retry_count},
            metadata={"source": "admin-service"},
        )

        return PayoutRetryResponse(
            payout_id=payout_id,
            status=updated.status,
            retry_count=updated.retry_count,
            last_retry_at=updated.last_retry_at,
            item=self._payout_queue_row_to_response(updated),
        )

    async def get_financial_dashboard_counters(
        self,
    ) -> FinancialDashboardCountersResponse:
        counts = await self.repo.get_financial_dashboard_counts()
        return FinancialDashboardCountersResponse(**counts)

    async def get_financial_reconciliation_summary(
        self,
    ) -> FinancialReconciliationSummaryResponse:
        summary = await self.repo.get_financial_reconciliation_summary()
        summary["failed_fee_refunds"] = await self.repo.get_failed_fee_refund_count()
        return FinancialReconciliationSummaryResponse(**summary)

    async def get_analytics_growth(
        self,
        *,
        window_days: int,
    ) -> AnalyticsGrowthResponse:
        if window_days < 1 or window_days > 365:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="window_days must be between 1 and 365",
            )

        since = self._day_bucket(datetime.now(tz=timezone.utc) - timedelta(days=window_days - 1))
        disputes = await self.repo.list_dispute_queue_since(since=since)
        payouts = await self.repo.list_payout_queue_since(since=since)

        disputes_created = self._build_day_value_map(since=since, window_days=window_days)
        payouts_created = self._build_day_value_map(since=since, window_days=window_days)
        payout_volume = self._build_day_value_map(since=since, window_days=window_days)

        for row in disputes:
            bucket = self._day_bucket(self._normalize_datetime(row.created_at))
            if bucket in disputes_created:
                disputes_created[bucket] += 1

        for row in payouts:
            bucket = self._day_bucket(self._normalize_datetime(row.created_at))
            if bucket in payouts_created:
                payouts_created[bucket] += 1
                payout_volume[bucket] += float(row.amount)

        return AnalyticsGrowthResponse(
            window_days=window_days,
            disputes_created=self._daily_points(disputes_created),
            payouts_created=self._daily_points(payouts_created),
            payout_volume=self._daily_points(payout_volume),
        )

    async def get_analytics_dispute_throughput(
        self,
        *,
        window_days: int,
    ) -> AnalyticsDisputeThroughputResponse:
        if window_days < 1 or window_days > 365:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="window_days must be between 1 and 365",
            )

        since = self._day_bucket(datetime.now(tz=timezone.utc) - timedelta(days=window_days - 1))
        disputes = await self.repo.list_dispute_queue_since(since=since)

        opened_series = self._build_day_value_map(since=since, window_days=window_days)
        resolved_series = self._build_day_value_map(since=since, window_days=window_days)

        opened = 0
        resolved = 0
        resolution_hours: list[float] = []

        for row in disputes:
            created_at = self._normalize_datetime(row.created_at)
            created_bucket = self._day_bucket(created_at)
            if created_bucket in opened_series:
                opened_series[created_bucket] += 1
                opened += 1

            if row.status.startswith("resolved"):
                resolved_at = self._normalize_datetime(row.updated_at)
                resolved_bucket = self._day_bucket(resolved_at)
                if resolved_bucket in resolved_series:
                    resolved_series[resolved_bucket] += 1
                    resolved += 1
                duration_hours = max((resolved_at - created_at).total_seconds() / 3600, 0.0)
                resolution_hours.append(duration_hours)

        resolution_rate = round((resolved / opened) * 100, 2) if opened else 0.0
        avg_resolution_hours = (
            round(sum(resolution_hours) / len(resolution_hours), 2) if resolution_hours else None
        )

        return AnalyticsDisputeThroughputResponse(
            window_days=window_days,
            opened=opened,
            resolved=resolved,
            resolution_rate=resolution_rate,
            avg_resolution_hours=avg_resolution_hours,
            opened_series=self._daily_points(opened_series),
            resolved_series=self._daily_points(resolved_series),
        )

    async def get_analytics_payout_health(
        self,
        *,
        window_days: int,
    ) -> AnalyticsPayoutHealthResponse:
        if window_days < 1 or window_days > 365:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="window_days must be between 1 and 365",
            )

        since = self._day_bucket(datetime.now(tz=timezone.utc) - timedelta(days=window_days - 1))
        payouts = await self.repo.list_payout_queue_since(since=since)

        success_series = self._build_day_value_map(since=since, window_days=window_days)
        failed_series = self._build_day_value_map(since=since, window_days=window_days)

        pending = 0
        processing = 0
        success = 0
        failed = 0
        retrying = 0

        for row in payouts:
            if row.status == "pending":
                pending += 1
            elif row.status == "processing":
                processing += 1
            elif row.status == "success":
                success += 1
            elif row.status == "failed":
                failed += 1

            if row.retry_count > 0 and row.status != "success":
                retrying += 1

            bucket = self._day_bucket(self._normalize_datetime(row.created_at))
            if row.status == "success" and bucket in success_series:
                success_series[bucket] += 1
            if row.status == "failed" and bucket in failed_series:
                failed_series[bucket] += 1

        total = pending + processing + success + failed
        success_rate = round((success / total) * 100, 2) if total else 0.0

        return AnalyticsPayoutHealthResponse(
            window_days=window_days,
            pending=pending,
            processing=processing,
            success=success,
            failed=failed,
            retrying=retrying,
            success_rate=success_rate,
            success_series=self._daily_points(success_series),
            failed_series=self._daily_points(failed_series),
        )

    async def get_analytics_volume(
        self,
        *,
        window_days: int,
    ) -> AnalyticsVolumeResponse:
        if window_days < 1 or window_days > 365:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="window_days must be between 1 and 365",
            )

        since = self._day_bucket(datetime.now(tz=timezone.utc) - timedelta(days=window_days - 1))
        payouts = await self.repo.list_payout_queue_since(since=since)
        volume_series = self._build_day_value_map(since=since, window_days=window_days)

        total_volume = 0
        success_volume = 0
        failed_volume = 0

        for row in payouts:
            amount = int(row.amount)
            total_volume += amount
            if row.status == "success":
                success_volume += amount
            if row.status == "failed":
                failed_volume += amount

            bucket = self._day_bucket(self._normalize_datetime(row.created_at))
            if bucket in volume_series:
                volume_series[bucket] += float(amount)

        return AnalyticsVolumeResponse(
            window_days=window_days,
            total_volume=total_volume,
            success_volume=success_volume,
            failed_volume=failed_volume,
            volume_series=self._daily_points(volume_series),
        )

    async def create_saved_view(
        self,
        *,
        owner_id: uuid.UUID,
        body: SavedViewCreateRequest,
    ) -> SavedViewResponse:
        row = await self.repo.create_saved_view(
            owner_id=owner_id,
            module=body.module,
            name=body.name,
            filters=body.filters,
            is_shared=body.is_shared,
        )
        await self._log_action(
            admin_id=owner_id,
            action="saved_view.created",
            target_type="saved_view",
            target_id=row.id,
            details={
                "module": body.module,
                "name": body.name,
                "is_shared": body.is_shared,
            },
        )
        await self._emit_mutation_audit(
            actor_id=owner_id,
            action="saved_view.created",
            target_type="saved_view",
            target_id=row.id,
            after={"module": row.module, "name": row.name, "is_shared": row.is_shared},
            metadata={"source": "admin-service"},
        )
        return self._saved_view_to_response(row)

    async def list_saved_views(
        self,
        *,
        owner_id: uuid.UUID,
        page: int,
        limit: int,
        module: str | None,
    ) -> SavedViewListResponse:
        offset = (page - 1) * limit
        rows, total = await self.repo.list_saved_views(
            owner_id=owner_id,
            offset=offset,
            limit=limit,
            module=module,
        )
        return SavedViewListResponse(
            items=[self._saved_view_to_response(row) for row in rows],
            total=total,
            page=page,
            limit=limit,
        )

    async def get_saved_view(
        self,
        *,
        view_id: uuid.UUID,
        owner_id: uuid.UUID,
    ) -> SavedViewResponse:
        row = await self.repo.get_saved_view_by_id(view_id=view_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Saved view not found",
            )
        if not row.is_shared and row.owner_id != owner_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not allowed to access this saved view",
            )
        return self._saved_view_to_response(row)

    async def update_saved_view(
        self,
        *,
        view_id: uuid.UUID,
        owner_id: uuid.UUID,
        body: SavedViewUpdateRequest,
    ) -> SavedViewResponse:
        current = await self.repo.get_saved_view_by_id(view_id=view_id)
        if current is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Saved view not found",
            )
        if current.owner_id != owner_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the owner can update this saved view",
            )

        updated = await self.repo.update_saved_view(
            view_id=view_id,
            name=body.name,
            filters=body.filters,
            is_shared=body.is_shared,
        )
        await self._log_action(
            admin_id=owner_id,
            action="saved_view.updated",
            target_type="saved_view",
            target_id=view_id,
            details={
                "name": body.name,
                "has_filters": body.filters is not None,
                "is_shared": body.is_shared,
            },
        )
        await self._emit_mutation_audit(
            actor_id=owner_id,
            action="saved_view.updated",
            target_type="saved_view",
            target_id=view_id,
            before={
                "name": current.name,
                "filters": current.filters,
                "is_shared": current.is_shared,
            },
            after={
                "name": updated.name,
                "filters": updated.filters,
                "is_shared": updated.is_shared,
            },
            metadata={"source": "admin-service"},
        )
        return self._saved_view_to_response(updated)

    async def create_report_job(
        self,
        *,
        requested_by: uuid.UUID,
        body: ReportJobCreateRequest,
    ) -> ReportJobResponse:
        row = await self.repo.create_report_job(
            requested_by=requested_by,
            report_type=body.report_type,
            export_format=body.export_format,
            filters=body.filters,
            status="queued",
        )
        await self._log_action(
            admin_id=requested_by,
            action="report.job.created",
            target_type="report_job",
            target_id=row.id,
            details={
                "report_type": body.report_type,
                "export_format": body.export_format,
            },
        )
        await self._emit_mutation_audit(
            actor_id=requested_by,
            action="report.job.created",
            target_type="report_job",
            target_id=row.id,
            after={"status": row.status, "report_type": row.report_type},
            metadata={"source": "admin-service"},
        )
        return self._report_job_to_response(row)

    async def list_report_jobs(
        self,
        *,
        requested_by: uuid.UUID,
        page: int,
        limit: int,
        report_type: str | None,
        status_filter: str | None,
    ) -> ReportJobListResponse:
        offset = (page - 1) * limit
        rows, total = await self.repo.list_report_jobs(
            requested_by=requested_by,
            offset=offset,
            limit=limit,
            report_type=report_type,
            status_filter=status_filter,
        )
        return ReportJobListResponse(
            items=[self._report_job_to_response(row) for row in rows],
            total=total,
            page=page,
            limit=limit,
        )

    async def get_report_job(
        self,
        *,
        job_id: uuid.UUID,
        requested_by: uuid.UUID,
    ) -> ReportJobResponse:
        row = await self.repo.get_report_job_by_id(job_id=job_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report job not found",
            )
        if row.requested_by != requested_by:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not allowed to access this report job",
            )
        return self._report_job_to_response(row)

    async def _build_report_payload(
        self,
        *,
        report_type: str,
        filters: dict[str, Any] | None,
    ) -> dict[str, Any]:
        window_days = self._parse_window_days(filters)

        if report_type == "growth":
            return (await self.get_analytics_growth(window_days=window_days)).model_dump(
                mode="json"
            )
        if report_type == "dispute_throughput":
            return (
                await self.get_analytics_dispute_throughput(window_days=window_days)
            ).model_dump(mode="json")
        if report_type == "payout_health":
            return (await self.get_analytics_payout_health(window_days=window_days)).model_dump(
                mode="json"
            )
        if report_type == "volume":
            return (await self.get_analytics_volume(window_days=window_days)).model_dump(
                mode="json"
            )
        if report_type == "dashboard_snapshot":
            growth = await self.get_analytics_growth(window_days=window_days)
            dispute = await self.get_analytics_dispute_throughput(window_days=window_days)
            payout = await self.get_analytics_payout_health(window_days=window_days)
            volume = await self.get_analytics_volume(window_days=window_days)
            return {
                "window_days": window_days,
                "growth": growth.model_dump(mode="json"),
                "dispute_throughput": dispute.model_dump(mode="json"),
                "payout_health": payout.model_dump(mode="json"),
                "volume": volume.model_dump(mode="json"),
            }

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported report type '{report_type}'",
        )

    async def run_report_job(
        self,
        *,
        job_id: uuid.UUID,
        requested_by: uuid.UUID,
    ) -> ReportJobResponse:
        row = await self.repo.get_report_job_by_id(job_id=job_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report job not found",
            )
        if row.requested_by != requested_by:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not allowed to run this report job",
            )

        if row.status == "completed":
            return self._report_job_to_response(row)

        await self.repo.update_report_job(job_id=job_id, status="processing")

        try:
            await self._build_report_payload(
                report_type=row.report_type,
                filters=row.filters,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("report job execution failed job_id=%s", job_id)
            failed = await self.repo.update_report_job(
                job_id=job_id,
                status="failed",
                error_message=str(exc),
                completed_at=datetime.now(tz=timezone.utc),
            )
            return self._report_job_to_response(failed)

        completed = await self.repo.update_report_job(
            job_id=job_id,
            status="completed",
            result_url=f"/admin/reports/jobs/{job_id}/download",
            error_message=None,
            completed_at=datetime.now(tz=timezone.utc),
        )
        await self._log_action(
            admin_id=requested_by,
            action="report.job.completed",
            target_type="report_job",
            target_id=job_id,
            details={"report_type": completed.report_type},
        )
        await self._emit_mutation_audit(
            actor_id=requested_by,
            action="report.job.completed",
            target_type="report_job",
            target_id=job_id,
            after={"status": "completed", "result_url": completed.result_url},
            metadata={"source": "admin-service"},
        )
        return self._report_job_to_response(completed)

    async def get_report_job_export(
        self,
        *,
        job_id: uuid.UUID,
        requested_by: uuid.UUID,
    ) -> tuple[str, str, str]:
        row = await self.repo.get_report_job_by_id(job_id=job_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report job not found",
            )
        if row.requested_by != requested_by:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not allowed to access this report export",
            )
        if row.status != "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Report job is not completed yet",
            )

        payload = await self._build_report_payload(
            report_type=row.report_type,
            filters=row.filters,
        )
        if row.export_format == "csv":
            content = self._report_payload_to_csv(payload)
            return (
                content,
                "text/csv",
                f"{row.report_type}_{row.id}.csv",
            )

        return (
            json.dumps(payload, default=str, indent=2),
            "application/json",
            f"{row.report_type}_{row.id}.json",
        )

    async def list_system_configs(self) -> SystemConfigListResponse:
        rows = await self.repo.list_system_configs()
        return SystemConfigListResponse(
            items=[self._system_config_row_to_response(row) for row in rows],
            total=len(rows),
        )

    async def get_system_config(self, *, config_key: str) -> SystemConfigItem:
        normalized_key = self._normalize_config_key(config_key)
        row = await self.repo.get_system_config_item(config_key=normalized_key)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="System config not found",
            )
        return self._system_config_row_to_response(row)

    async def validate_system_config_change(
        self,
        *,
        config_key: str,
        value: Any,
    ) -> SystemConfigDryRunResponse:
        normalized_key = self._normalize_config_key(config_key)
        existing_item = await self.repo.get_system_config_item(config_key=normalized_key)
        existing_values = await self._get_system_config_value_map()
        normalized_value, errors = self._validate_system_config_value(
            config_key=normalized_key,
            value=value,
            existing_values=existing_values,
        )
        is_valid = len(errors) == 0
        current_version = existing_item.version if existing_item else None
        next_version = (existing_item.version + 1) if existing_item else 1
        return SystemConfigDryRunResponse(
            key=normalized_key,
            valid=is_valid,
            errors=errors,
            normalized_value=normalized_value,
            current_version=current_version,
            next_version=next_version if is_valid else None,
        )

    async def upsert_system_config(
        self,
        *,
        config_key: str,
        body: SystemConfigUpsertRequest,
        admin_id: uuid.UUID,
    ) -> SystemConfigMutationResponse:
        normalized_key = self._normalize_config_key(config_key)
        existing = await self.repo.get_system_config_item(config_key=normalized_key)
        dry_run = await self.validate_system_config_change(
            config_key=normalized_key,
            value=body.value,
        )
        if not dry_run.valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"errors": dry_run.errors},
            )

        action = "system_config.created" if existing is None else "system_config.updated"
        config_item, history_item = await self.repo.create_or_update_system_config(
            config_key=normalized_key,
            value=dry_run.normalized_value,
            changed_by=admin_id,
            reason=body.reason,
            action=action,
            metadata={"dry_run": True},
        )

        target_id = self._config_target_uuid(normalized_key)
        await self._log_action(
            admin_id=admin_id,
            action=action,
            target_type="system_config",
            target_id=target_id,
            details={
                "key": normalized_key,
                "version": config_item.version,
                "reason": body.reason,
            },
        )
        await self._emit_mutation_audit(
            actor_id=admin_id,
            action=action,
            target_type="system_config",
            target_id=target_id,
            before=(
                {
                    "value": existing.value_json,
                    "version": existing.version,
                }
                if existing
                else None
            ),
            after={"value": config_item.value_json, "version": config_item.version},
            metadata={
                "key": normalized_key,
                "reason": body.reason,
                "source": "admin-service",
            },
        )

        return SystemConfigMutationResponse(
            action=action,
            item=self._system_config_row_to_response(config_item),
            history=self._system_config_history_row_to_response(history_item),
        )

    async def rollback_system_config(
        self,
        *,
        config_key: str,
        body: SystemConfigRollbackRequest,
        admin_id: uuid.UUID,
    ) -> SystemConfigMutationResponse:
        normalized_key = self._normalize_config_key(config_key)
        current = await self.repo.get_system_config_item(config_key=normalized_key)
        if current is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="System config not found",
            )

        target = await self.repo.get_system_config_history_by_version(
            config_key=normalized_key,
            version=body.target_version,
        )
        if target is None or target.new_value is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target config version not found",
            )

        if body.target_version == current.version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Config is already at the requested version",
            )

        existing_values = await self._get_system_config_value_map()
        normalized_value, errors = self._validate_system_config_value(
            config_key=normalized_key,
            value=target.new_value,
            existing_values=existing_values,
        )
        if errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"errors": errors},
            )

        action = "system_config.rolled_back"
        config_item, history_item = await self.repo.create_or_update_system_config(
            config_key=normalized_key,
            value=normalized_value,
            changed_by=admin_id,
            reason=body.reason,
            action=action,
            metadata={"rolled_back_to_version": body.target_version},
        )

        target_id = self._config_target_uuid(normalized_key)
        await self._log_action(
            admin_id=admin_id,
            action=action,
            target_type="system_config",
            target_id=target_id,
            details={
                "key": normalized_key,
                "version": config_item.version,
                "rolled_back_to_version": body.target_version,
                "reason": body.reason,
            },
        )
        await self._emit_mutation_audit(
            actor_id=admin_id,
            action=action,
            target_type="system_config",
            target_id=target_id,
            before={"value": current.value_json, "version": current.version},
            after={"value": config_item.value_json, "version": config_item.version},
            metadata={
                "key": normalized_key,
                "rolled_back_to_version": body.target_version,
                "reason": body.reason,
                "source": "admin-service",
            },
        )

        return SystemConfigMutationResponse(
            action=action,
            item=self._system_config_row_to_response(config_item),
            history=self._system_config_history_row_to_response(history_item),
        )

    async def list_system_config_history(
        self,
        *,
        config_key: str,
        limit: int,
    ) -> SystemConfigHistoryResponse:
        normalized_key = self._normalize_config_key(config_key)
        rows = await self.repo.list_system_config_history(
            config_key=normalized_key,
            limit=limit,
        )
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="System config history not found",
            )
        return SystemConfigHistoryResponse(
            key=normalized_key,
            items=[self._system_config_history_row_to_response(row) for row in rows],
        )

    async def get_stats(self) -> PlatformStats:
        stats = await grpc_clients.get_platform_stats()
        return PlatformStats(**stats)

    async def add_moderation_note(
        self,
        *,
        user_id: uuid.UUID,
        body: ModerationNoteCreateRequest,
        admin_id: uuid.UUID,
    ) -> ModerationNoteResponse:
        note = await self.repo.add_moderation_note(
            target_type="user",
            target_id=user_id,
            note=body.note,
            created_by=admin_id,
            case_id=body.case_id,
            visibility=body.visibility,
        )
        await self._log_action(
            admin_id=admin_id,
            action="user.moderation_note_added",
            target_type="user",
            target_id=user_id,
            details={
                "visibility": body.visibility,
                "case_id": str(body.case_id) if body.case_id else None,
            },
        )
        await self._emit_mutation_audit(
            actor_id=admin_id,
            action="user.moderation_note_added",
            target_type="user",
            target_id=user_id,
            after={"visibility": body.visibility, "has_case": body.case_id is not None},
            metadata={"source": "admin-service"},
        )
        return ModerationNoteResponse.model_validate(note)

    async def create_user_risk_flag(
        self,
        *,
        user_id: uuid.UUID,
        body: UserRiskFlagRequest,
        admin_id: uuid.UUID,
    ) -> UserRiskFlagResponse:
        flag = await self.repo.create_risk_flag(
            user_id=user_id,
            flag=body.flag,
            severity=body.severity,
            reason=body.reason,
            created_by=admin_id,
            metadata=body.metadata,
            status="active",
        )
        await self._log_action(
            admin_id=admin_id,
            action="user.risk_flag_added",
            target_type="user",
            target_id=user_id,
            details={
                "flag": body.flag,
                "severity": body.severity,
                "reason": body.reason,
            },
        )
        await self._emit_mutation_audit(
            actor_id=admin_id,
            action="user.risk_flag_added",
            target_type="user",
            target_id=user_id,
            after={"flag": body.flag, "severity": body.severity, "status": "active"},
            metadata={"reason": body.reason, "source": "admin-service"},
        )
        return UserRiskFlagResponse(
            id=flag.id,
            user_id=flag.user_id,
            flag=flag.flag,
            severity=flag.severity,
            status=flag.status,
            reason=flag.reason,
            created_by=flag.created_by,
            metadata=flag.metadata_json,
            created_at=flag.created_at,
        )

    async def set_user_verification_override(
        self,
        *,
        user_id: uuid.UUID,
        body: UserVerificationOverrideRequest,
        admin_id: uuid.UUID,
        idempotency_key: str,
    ) -> UserVerificationOverrideResponse:
        existing = await self.repo.get_idempotency_record(
            action=_VERIFY_OVERRIDE_ACTION,
            idempotency_key=idempotency_key,
        )
        if existing and existing.response_payload:
            return UserVerificationOverrideResponse.model_validate(existing.response_payload)

        try:
            profile = await grpc_clients.get_user_by_id(str(user_id))
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to fetch user profile for verification override",
            ) from exc

        review_case_id: uuid.UUID | None = None
        if body.require_dual_approval:
            review_case = await self.repo.create_review_case(
                subject_type="user",
                subject_id=user_id,
                created_by=admin_id,
                priority="high",
                status="pending_approval",
                metadata={
                    "action": "verification_override",
                    "requested_is_verified": body.is_verified,
                    "reason": body.reason,
                    "idempotency_key": idempotency_key,
                },
            )
            review_case_id = review_case.id
            response = UserVerificationOverrideResponse(
                status="pending_approval",
                user_id=user_id,
                is_verified=body.is_verified,
                reason=body.reason,
                idempotency_key=idempotency_key,
                review_case_id=review_case_id,
            )
        else:
            try:
                await grpc_clients.update_user_verification(user_id, body.is_verified)
            except RuntimeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Unable to update user verification status",
                ) from exc

            response = UserVerificationOverrideResponse(
                status="applied",
                user_id=user_id,
                is_verified=body.is_verified,
                reason=body.reason,
                idempotency_key=idempotency_key,
            )

        await self.repo.create_verification_override(
            user_id=user_id,
            is_verified=body.is_verified,
            reason=body.reason,
            overridden_by=admin_id,
            idempotency_key=idempotency_key,
            review_case_id=review_case_id,
        )

        action = (
            "user.verification_override_requested"
            if body.require_dual_approval
            else "user.verification_overridden"
        )
        await self._log_action(
            admin_id=admin_id,
            action=action,
            target_type="user",
            target_id=user_id,
            details={
                "reason": body.reason,
                "requested_is_verified": body.is_verified,
                "require_dual_approval": body.require_dual_approval,
                "review_case_id": str(review_case_id) if review_case_id else None,
            },
        )
        await self._emit_mutation_audit(
            actor_id=admin_id,
            action=action,
            target_type="user",
            target_id=user_id,
            before={"is_verified": bool(profile.get("is_verified", False))},
            after={
                "requested_is_verified": body.is_verified,
                "status": response.status,
            },
            metadata={"reason": body.reason, "source": "admin-service"},
        )

        await self._save_idempotent_response(
            action=_VERIFY_OVERRIDE_ACTION,
            idempotency_key=idempotency_key,
            actor_id=admin_id,
            request_payload=body.model_dump(mode="json"),
            response_payload=response.model_dump(mode="json"),
        )
        return response

    async def bulk_ban_users(
        self,
        *,
        body: BulkUserBanRequest,
        admin_id: uuid.UUID,
        idempotency_key: str,
    ) -> BulkUserBanResponse:
        existing = await self.repo.get_idempotency_record(
            action=_BULK_BAN_ACTION,
            idempotency_key=idempotency_key,
        )
        if existing and existing.response_payload:
            return BulkUserBanResponse.model_validate(existing.response_payload)

        items: list[BulkUserBanItemResult] = []
        processed = 0
        queued = 0
        failed = 0

        for user_id in body.user_ids:
            if body.require_dual_approval:
                review_case = await self.repo.create_review_case(
                    subject_type="user",
                    subject_id=user_id,
                    created_by=admin_id,
                    priority=body.priority,
                    status="pending_approval",
                    metadata={
                        "action": "ban_user" if body.ban else "unban_user",
                        "reason": body.reason,
                        "idempotency_key": idempotency_key,
                    },
                )
                queued += 1
                items.append(
                    BulkUserBanItemResult(
                        user_id=user_id,
                        status="pending_approval",
                        message="Queued for second-level approval",
                        review_case_id=review_case.id,
                    )
                )
                await self._log_action(
                    admin_id=admin_id,
                    action="user.bulk_ban_approval_requested",
                    target_type="user",
                    target_id=user_id,
                    details={
                        "ban": body.ban,
                        "reason": body.reason,
                        "priority": body.priority,
                    },
                )
                await self._emit_mutation_audit(
                    actor_id=admin_id,
                    action="user.bulk_ban_approval_requested",
                    target_type="user",
                    target_id=user_id,
                    after={
                        "requested_ban": body.ban,
                        "approval_status": "pending_approval",
                    },
                    metadata={"reason": body.reason, "source": "admin-service"},
                )
                continue

            try:
                await self.ban_user(
                    user_id=user_id,
                    ban=body.ban,
                    reason=body.reason,
                    admin_id=admin_id,
                )
                processed += 1
                items.append(
                    BulkUserBanItemResult(
                        user_id=user_id,
                        status="applied",
                        message="User moderation status updated",
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive aggregation
                failed += 1
                items.append(
                    BulkUserBanItemResult(
                        user_id=user_id,
                        status="failed",
                        message=str(exc),
                    )
                )

        response = BulkUserBanResponse(
            idempotency_key=idempotency_key,
            action=_BULK_BAN_ACTION,
            processed=processed,
            queued=queued,
            failed=failed,
            items=items,
        )

        await self._save_idempotent_response(
            action=_BULK_BAN_ACTION,
            idempotency_key=idempotency_key,
            actor_id=admin_id,
            request_payload=body.model_dump(mode="json"),
            response_payload=response.model_dump(mode="json"),
        )
        return response

    async def get_user_moderation_timeline(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
    ) -> UserModerationTimelineResponse:
        try:
            profile = await grpc_clients.get_user_by_id(str(user_id))
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to fetch user profile for moderation timeline",
            ) from exc

        logs, _ = await self.repo.list_action_logs(
            offset=0,
            limit=limit,
            target_type="user",
            target_id=user_id,
        )
        notes = await self.repo.list_moderation_notes(
            target_type="user",
            target_id=user_id,
            limit=limit,
        )
        overrides = await self.repo.list_verification_overrides(user_id=user_id, limit=limit)
        risk_flags = await self.repo.list_risk_flags(user_id=user_id, limit=limit)

        timeline_items: list[UserModerationTimelineItem] = []
        for log in logs:
            timeline_items.append(
                UserModerationTimelineItem(
                    item_type="action_log",
                    source="admin",
                    occurred_at=log.performed_at,
                    actor_id=log.admin_id,
                    action=log.action,
                    details=log.details,
                )
            )

        for note in notes:
            timeline_items.append(
                UserModerationTimelineItem(
                    item_type="moderation_note",
                    source="admin",
                    occurred_at=note.created_at,
                    actor_id=note.created_by,
                    action="user.moderation_note_added",
                    details={
                        "note": note.note,
                        "visibility": note.visibility,
                        "case_id": str(note.case_id) if note.case_id else None,
                    },
                )
            )

        for override in overrides:
            timeline_items.append(
                UserModerationTimelineItem(
                    item_type="verification_override",
                    source="admin",
                    occurred_at=override.created_at,
                    actor_id=override.overridden_by,
                    action="user.verification_overridden",
                    details={
                        "is_verified": override.is_verified,
                        "reason": override.reason,
                        "review_case_id": str(override.review_case_id)
                        if override.review_case_id
                        else None,
                    },
                )
            )

        for flag in risk_flags:
            timeline_items.append(
                UserModerationTimelineItem(
                    item_type="risk_flag",
                    source="admin",
                    occurred_at=flag.created_at,
                    actor_id=flag.created_by,
                    action="user.risk_flag_added",
                    details={
                        "flag": flag.flag,
                        "severity": flag.severity,
                        "status": flag.status,
                        "reason": flag.reason,
                        "metadata": flag.metadata_json,
                    },
                )
            )

        timeline_items.sort(key=lambda item: item.occurred_at, reverse=True)
        return UserModerationTimelineResponse(
            user_id=user_id,
            profile={
                "user_id": profile.get("user_id"),
                "email": profile.get("email"),
                "role": profile.get("role"),
                "is_verified": profile.get("is_verified"),
                "is_banned": profile.get("is_banned"),
                "kyc_level": profile.get("kyc_level"),
                "timeline_generated_at": datetime.now(tz=timezone.utc).isoformat(),
            },
            items=timeline_items,
        )

    async def get_action_logs(
        self,
        *,
        page: int,
        limit: int,
        action: str | None = None,
        target_type: str | None = None,
    ) -> AdminActionLogListResponse:
        offset = (page - 1) * limit
        logs, total = await self.repo.list_action_logs(
            offset=offset,
            limit=limit,
            action=action,
            target_type=target_type,
        )
        return AdminActionLogListResponse(
            items=[AdminActionLog.model_validate(log) for log in logs],
            total=total,
            page=page,
            limit=limit,
        )
