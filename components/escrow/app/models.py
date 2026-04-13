"""
Pydantic schemas (request/response models) for the Escrow service.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.settings import (
    DEFAULT_DISPUTE_WINDOW_HOURS,
    DEFAULT_INSPECTION_PERIOD_HOURS,
    DEFAULT_MILESTONE_INSPECTION_HOURS,
)

# ─────────────────────────────────────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────────────────────────────────────


class BaseEscrowCreate(BaseModel):
    escrow_type: Literal["onetime", "milestone", "recurring"]
    title: str = Field(..., max_length=255)
    description: Optional[str] = None
    receiver_id: Optional[uuid.UUID] = None
    receiver_email: Optional[EmailStr] = None
    initiator_role: Literal["buyer", "seller"] = "buyer"
    currency: str = Field(..., min_length=3, max_length=10, pattern=r"^[A-Z]{3,10}$")
    amount: int = Field(..., gt=0)
    acceptance_criteria: Optional[str] = None
    inspection_period: int = Field(DEFAULT_INSPECTION_PERIOD_HOURS, ge=1)
    delivery_date: Optional[datetime] = None
    dispute_window: int = Field(DEFAULT_DISPUTE_WINDOW_HOURS, ge=1)
    how_dispute_handled: Literal["platform"] = "platform"  # , "arbitrator", "mutual"
    who_pays_fees: Literal["buyer", "seller", "split"] = "buyer"

    @model_validator(mode="after")
    def validate_party_shape(self) -> BaseEscrowCreate:
        if self.receiver_id is None and self.receiver_email is None:
            raise ValueError("Either receiver_id or receiver_email is required")

        if self.delivery_date is not None:
            now = datetime.now(timezone.utc)
            delivery = self.delivery_date
            if delivery.tzinfo is None:
                delivery = delivery.replace(tzinfo=timezone.utc)
            if delivery <= now:
                raise ValueError("delivery_date must be in the future")

        return self


class MilestoneCreate(BaseModel):
    title: str
    description: Optional[str] = None
    amount: int = Field(..., gt=0)
    due_date: Optional[datetime] = None
    inspection_hrs: int = Field(DEFAULT_MILESTONE_INSPECTION_HOURS, ge=1)
    sort_order: int = Field(0, ge=0)

    @model_validator(mode="after")
    def validate_due_date(self) -> MilestoneCreate:
        if self.due_date is None:
            return self
        now = datetime.now(timezone.utc)
        due = self.due_date
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if due <= now:
            raise ValueError("milestone due_date must be in the future")
        return self


class OneTimeEscrowCreate(BaseEscrowCreate):
    escrow_type: Literal["onetime"] = "onetime"


class MilestoneEscrowCreate(BaseEscrowCreate):
    escrow_type: Literal["milestone"] = "milestone"
    milestones: list[MilestoneCreate] = Field(..., min_length=1)
    deposit_option: Literal["full", "milestone"] = "full"

    @model_validator(mode="after")
    def validate_amount_matches_milestones(self) -> MilestoneEscrowCreate:
        total = sum(m.amount for m in self.milestones)
        if self.amount != total:
            raise ValueError("For milestone escrow, amount must equal sum(milestones.amount)")
        return self


class RecurringCycleCreate(BaseModel):
    cycle_interval: Literal["daily", "weekly", "monthly"] = "monthly"
    due_day_of_month: Optional[int] = Field(None, ge=1, le=31)
    expected_amount: int = Field(..., gt=0)
    due_date: Optional[datetime] = None
    min_contributors: int = Field(1, ge=1)
    max_contributors: Optional[int] = Field(None, ge=1)

    @model_validator(mode="after")
    def validate_cycle_limits(self) -> RecurringCycleCreate:
        if self.max_contributors is not None and self.max_contributors < self.min_contributors:
            raise ValueError("max_contributors must be >= min_contributors")

        if self.due_date is not None:
            now = datetime.now(timezone.utc)
            due = self.due_date
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if due <= now:
                raise ValueError("cycle due_date must be in the future")
        return self


class RecurringEscrowCreate(BaseEscrowCreate):
    escrow_type: Literal["recurring"] = "recurring"
    cycle: RecurringCycleCreate

    @model_validator(mode="after")
    def validate_amount_matches_cycle(self) -> RecurringEscrowCreate:
        if self.amount != self.cycle.expected_amount:
            raise ValueError("For recurring escrow, amount must equal cycle.expected_amount")
        return self


class BaseOrganizationEscrowCreate(BaseEscrowCreate):
    initiator_role: Literal["seller"] = "seller"


class OneTimeOrganizationEscrowCreate(BaseOrganizationEscrowCreate):
    escrow_type: Literal["onetime"] = "onetime"


class MilestoneOrganizationEscrowCreate(BaseOrganizationEscrowCreate):
    escrow_type: Literal["milestone"] = "milestone"
    milestones: list[MilestoneCreate] = Field(..., min_length=1)
    deposit_option: Literal["full", "milestone"] = "full"

    @model_validator(mode="after")
    def validate_amount_matches_milestones(self) -> MilestoneOrganizationEscrowCreate:
        total = sum(m.amount for m in self.milestones)
        if self.amount != total:
            raise ValueError("For milestone escrow, amount must equal sum(milestones.amount)")
        return self


class RecurringOrganizationEscrowCreate(BaseOrganizationEscrowCreate):
    escrow_type: Literal["recurring"] = "recurring"
    cycle: RecurringCycleCreate

    @model_validator(mode="after")
    def validate_amount_matches_cycle(self) -> RecurringOrganizationEscrowCreate:
        if self.amount != self.cycle.expected_amount:
            raise ValueError("For recurring escrow, amount must equal cycle.expected_amount")
        return self


class ContributorJoinRequest(BaseModel):
    contribution: int = Field(..., gt=0)
    name: Optional[str] = None
    email: Optional[str] = None


class InvitationAcceptRequest(BaseModel):
    invite_token: Optional[str] = None


class InvitationRejectRequest(BaseModel):
    invite_token: Optional[str] = None


class InvitationCounterRequest(BaseModel):
    invite_token: Optional[str] = None
    title: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    amount: Optional[int] = Field(None, gt=0)
    acceptance_criteria: Optional[str] = None
    inspection_period: Optional[int] = Field(None, ge=1)
    delivery_date: Optional[datetime] = None
    dispute_window: Optional[int] = Field(None, ge=1)
    how_dispute_handled: Optional[Literal["platform", "arbitrator", "mutual"]] = None
    who_pays_fees: Optional[Literal["buyer", "seller", "split"]] = None

    @model_validator(mode="after")
    def validate_counter_payload(self) -> InvitationCounterRequest:
        has_changes = any(
            value is not None
            for value in (
                self.title,
                self.description,
                self.amount,
                self.acceptance_criteria,
                self.inspection_period,
                self.delivery_date,
                self.dispute_window,
                self.how_dispute_handled,
                self.who_pays_fees,
            )
        )
        if not has_changes:
            raise ValueError("At least one counter-offer field must be provided")

        if self.delivery_date is not None:
            now = datetime.now(timezone.utc)
            delivery = self.delivery_date
            if delivery.tzinfo is None:
                delivery = delivery.replace(tzinfo=timezone.utc)
            if delivery <= now:
                raise ValueError("delivery_date must be in the future")

        return self


class InvitationResendRequest(BaseModel):
    receiver_email: Optional[EmailStr] = None


class InvitationPrecheckResponse(BaseModel):
    escrow_id: uuid.UUID
    invitation_status: str
    has_account: bool
    next_action: Literal["login", "register"]


# Strict create union – validated at API boundary using escrow_type discriminator
EscrowCreateRequest = Annotated[
    OneTimeEscrowCreate | MilestoneEscrowCreate | RecurringEscrowCreate,
    Field(discriminator="escrow_type"),
]


OrganizationEscrowCreateRequest = Annotated[
    OneTimeOrganizationEscrowCreate
    | MilestoneOrganizationEscrowCreate
    | RecurringOrganizationEscrowCreate,
    Field(discriminator="escrow_type"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Response schemas
# ─────────────────────────────────────────────────────────────────────────────


class EscrowResponse(BaseModel):
    id: uuid.UUID
    transaction_ref: str
    escrow_type: str
    status: str
    status_message: Optional[str] = None
    initiator_actor_type: Literal["user", "organization"]
    initiator_id: Optional[uuid.UUID]
    initiator_org_id: Optional[uuid.UUID]
    receiver_id: Optional[uuid.UUID]
    receiver_email: Optional[str]
    initiator_role: str
    title: str
    description: Optional[str]
    currency: str
    amount: int
    fee_amount: int
    who_pays_fees: str
    offer_version: int
    counter_status: str
    active_counter_offer_version: Optional[int]
    last_countered_by_id: Optional[uuid.UUID]
    last_countered_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    counter_history: list["CounterOfferResponse"] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class CounterOfferResponse(BaseModel):
    id: uuid.UUID
    escrow_id: uuid.UUID
    offer_version: int
    proposed_by_user_id: uuid.UUID
    proposed_to_user_id: uuid.UUID
    status: str
    responded_by_user_id: Optional[uuid.UUID]
    responded_at: Optional[datetime]
    title: str
    description: Optional[str]
    amount: int
    acceptance_criteria: Optional[str]
    inspection_period: int
    delivery_date: Optional[datetime]
    dispute_window: int
    how_dispute_handled: str
    who_pays_fees: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MilestoneResponse(BaseModel):
    id: uuid.UUID
    escrow_id: uuid.UUID
    title: str
    description: Optional[str]
    amount: int
    status: str
    delivered_at: Optional[datetime]
    completed_at: Optional[datetime]
    sort_order: int

    model_config = {"from_attributes": True}


class RecurringContributorResponse(BaseModel):
    id: uuid.UUID
    cycle_id: uuid.UUID
    user_id: Optional[uuid.UUID]
    name: Optional[str]
    email: Optional[str]
    expected_amount: int
    paid_at: Optional[datetime]
    joined_at: datetime

    model_config = {"from_attributes": True}


class InitializeEscrowResponse(BaseModel):
    escrow: EscrowResponse
    payment_url: Optional[str] = None


class PaginatedEscrowResponse(BaseModel):
    items: list[EscrowResponse]
    total: int
    page: int
    limit: int
    pages: int
