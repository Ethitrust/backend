"""
Unit tests for EscrowService business logic.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.db import Escrow, Milestone, RecurringCycle
from app.models import (
    MilestoneEscrowCreate,
    OneTimeEscrowCreate,
    OneTimeOrganizationEscrowCreate,
)
from app.repository import EscrowRepository
from app.service import EscrowService
from fastapi import HTTPException
from pydantic import ValidationError

TEST_USER_ID = uuid.UUID("11111111-1111-4111-8111-11111111111a")
TEST_RECEIVER_ID = uuid.UUID("22222222-2222-4222-8222-22222222222b")
TEST_STRANGER_ID = uuid.UUID("33333333-3333-4333-3333-333333333333")
TEST_ORG_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def make_escrow(**kwargs) -> Escrow:
    defaults = dict(
        id=uuid.uuid4(),
        transaction_ref="ref-" + str(uuid.uuid4()),
        escrow_type="onetime",
        status="invited",
        initiator_actor_type="user",
        initiator_id=TEST_USER_ID,
        initiator_org_id=None,
        receiver_id=TEST_RECEIVER_ID,
        receiver_email=None,
        initiator_role="buyer",
        title="Test Escrow",
        currency="ETB",
        amount=100_000,
        fee_amount=1_500,
        org_id=None,
        who_pays_fees="buyer",
        provider="chapa",
        invite_token_hash=None,
        invite_expires_at=None,
        invite_token_used_at=None,
        offer_version=1,
        counter_status="none",
        active_counter_offer_version=None,
        last_countered_by_id=None,
        last_countered_at=None,
        initiator_accepted_at=None,
        receiver_accepted_at=None,
    )
    defaults.update(kwargs)
    e = Escrow()
    for k, v in defaults.items():
        setattr(e, k, v)
    return e


def make_milestone(**kwargs) -> Milestone:
    defaults = dict(
        id=uuid.uuid4(),
        escrow_id=uuid.uuid4(),
        title="Phase 1",
        amount=50_000,
        status="pending",
        delivered_at=None,
        completed_at=None,
        sort_order=0,
    )
    defaults.update(kwargs)
    m = Milestone()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def repo():
    r = AsyncMock(spec=EscrowRepository)
    return r


@pytest.fixture
def svc(repo):
    return EscrowService(repo)


@pytest.fixture(autouse=True)
def mock_fee_calculation(monkeypatch):
    async def _fake_calculate_fee(amount: int, who_pays: str) -> dict:
        fee = max(100, int(amount * 0.015))
        normalized = who_pays.lower().strip()
        if normalized == "buyer":
            return {"fee_amount": fee, "buyer_fee": fee, "seller_fee": 0}
        if normalized == "seller":
            return {"fee_amount": fee, "buyer_fee": 0, "seller_fee": fee}
        half = fee // 2
        return {"fee_amount": fee, "buyer_fee": half, "seller_fee": fee - half}

    monkeypatch.setattr("app.grpc_clients.calculate_fee", _fake_calculate_fee)


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_initialize_onetime(svc, repo):
    """initialize() with escrow_type=onetime should create invitation without checkout."""
    escrow = make_escrow(escrow_type="onetime")
    repo.create = AsyncMock(return_value=escrow)

    with (
        patch("app.service.publish", AsyncMock()),
    ):
        result_escrow, payment_url = await svc.initialize(
            OneTimeEscrowCreate(
                escrow_type="onetime",
                title="Buy laptop",
                currency="ETB",
                amount=100_000,
                initiator_role="buyer",
                receiver_id=TEST_RECEIVER_ID,
            ),
            "user",
            TEST_USER_ID,
            None,
        )

    assert result_escrow.escrow_type == "onetime"
    assert payment_url is None
    repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_initialize_milestone(svc, repo):
    """initialize() with escrow_type=milestone should create escrow + milestones."""
    escrow = make_escrow(escrow_type="milestone")
    repo.create = AsyncMock(return_value=escrow)
    milestone_obj = make_milestone(escrow_id=escrow.id)
    repo.create_milestone = AsyncMock(return_value=milestone_obj)

    with (
        patch("app.service.publish", AsyncMock()),
    ):
        result_escrow, _ = await svc.initialize(
            MilestoneEscrowCreate(
                escrow_type="milestone",
                title="Build website",
                currency="ETB",
                amount=200_000,
                initiator_role="buyer",
                receiver_id=TEST_RECEIVER_ID,
                milestones=[
                    {"title": "Phase 1", "amount": 100_000},
                    {"title": "Phase 2", "amount": 100_000},
                ],
            ),
            "user",
            TEST_USER_ID,
            None,
        )

    repo.create.assert_awaited_once()
    assert repo.create_milestone.await_count == 2


@pytest.mark.asyncio
async def test_accept_invitation_locks_wallet_and_transitions_to_active(svc, repo):
    escrow = make_escrow(
        status="invited",
        initiator_accepted_at=datetime.now(timezone.utc),
        receiver_accepted_at=None,
        fee_amount=1500,
    )
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.save = AsyncMock(side_effect=lambda model: model)

    with (
        patch("app.grpc_clients.get_user_wallet", AsyncMock(return_value="wallet-1")),
        patch("app.grpc_clients.lock_funds", AsyncMock(return_value=True)),
        patch("app.service.publish", AsyncMock()) as mock_publish,
    ):
        result, payment_url = await svc.accept_invitation(
            escrow.id,
            TEST_RECEIVER_ID,
            MagicMock(invite_token=None),
        )

    assert result.status == "active"
    assert payment_url is None
    mock_publish.assert_any_await(
        "escrow.invite_responded",
        {
            "escrow_id": str(escrow.id),
            "status": "active",
            "offer_version": escrow.offer_version,
            "action": "accepted",
            "actor_user_id": str(TEST_RECEIVER_ID),
            "user_id": str(TEST_USER_ID),
            "receiver_email": escrow.receiver_email,
        },
    )


@pytest.mark.asyncio
async def test_accept_invitation_insufficient_balance_keeps_pending(svc, repo):
    escrow = make_escrow(
        status="invited",
        initiator_accepted_at=datetime.now(timezone.utc),
        receiver_accepted_at=None,
        fee_amount=1500,
    )
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.save = AsyncMock(side_effect=lambda model: model)

    with (
        patch("app.grpc_clients.get_user_wallet", AsyncMock(return_value="wallet-1")),
        patch(
            "app.grpc_clients.lock_funds",
            AsyncMock(side_effect=RuntimeError("INSUFFICIENT_BALANCE")),
        ),
        patch("app.service.publish", AsyncMock()) as mock_publish,
    ):
        result, payment_url = await svc.accept_invitation(
            escrow.id,
            TEST_RECEIVER_ID,
            MagicMock(invite_token=None),
        )

    assert result.status == "pending"
    assert payment_url is None
    mock_publish.assert_any_await(
        "escrow.invite_responded",
        {
            "escrow_id": str(escrow.id),
            "status": "pending",
            "offer_version": escrow.offer_version,
            "action": "accepted",
            "actor_user_id": str(TEST_RECEIVER_ID),
            "user_id": str(TEST_USER_ID),
            "receiver_email": escrow.receiver_email,
        },
    )


@pytest.mark.asyncio
async def test_accept_invitation_forbidden_for_initiator(svc, repo):
    escrow = make_escrow(status="invited")
    repo.get_by_id = AsyncMock(return_value=escrow)

    with pytest.raises(HTTPException) as exc_info:
        await svc.accept_invitation(
            escrow.id,
            TEST_USER_ID,
            MagicMock(invite_token=None),
        )

    assert exc_info.value.status_code == 403
    assert "implicitly accepted" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_reject_invitation_forbidden_for_initiator(svc, repo):
    escrow = make_escrow(status="invited")
    repo.get_by_id = AsyncMock(return_value=escrow)

    with pytest.raises(HTTPException) as exc_info:
        await svc.reject_invitation(
            escrow.id,
            TEST_USER_ID,
            MagicMock(invite_token=None),
        )

    assert exc_info.value.status_code == 403
    assert "cannot reject" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_counter_invitation_increments_version(svc, repo):
    escrow = make_escrow(status="invited", offer_version=1)
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.save = AsyncMock(return_value=escrow)
    repo.create_counter_offer = AsyncMock()

    with patch("app.service.publish", AsyncMock()) as mock_publish:
        result = await svc.counter_invitation(
            escrow.id,
            TEST_RECEIVER_ID,
            MagicMock(
                invite_token=None,
                title=None,
                description="new terms",
                amount=110_000,
                acceptance_criteria=None,
                inspection_period=None,
                delivery_date=None,
                dispute_window=None,
                how_dispute_handled=None,
                who_pays_fees=None,
            ),
        )

    assert result.offer_version == 2
    assert result.amount == 110_000
    assert result.status == "counter_pending_counterparty"
    assert result.counter_status == "awaiting_initiator"
    assert result.last_countered_by_id == TEST_RECEIVER_ID
    repo.create_counter_offer.assert_awaited_once()
    mock_publish.assert_any_await(
        "escrow.invite_responded",
        {
            "escrow_id": str(escrow.id),
            "status": "counter_pending_counterparty",
            "offer_version": result.offer_version,
            "action": "countered",
            "actor_user_id": str(TEST_RECEIVER_ID),
            "user_id": str(TEST_USER_ID),
            "receiver_email": escrow.receiver_email,
        },
    )


@pytest.mark.asyncio
async def test_counter_invitation_marks_previous_as_countered_again(svc, repo):
    escrow = make_escrow(
        status="counter_pending_counterparty",
        offer_version=2,
        active_counter_offer_version=2,
        receiver_id=TEST_RECEIVER_ID,
    )
    pending_counter = MagicMock(status="pending_response")
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.get_counter_offer_by_version = AsyncMock(return_value=pending_counter)
    repo.save_counter_offer = AsyncMock(return_value=pending_counter)
    repo.create_counter_offer = AsyncMock()
    repo.save = AsyncMock(return_value=escrow)

    with patch("app.service.publish", AsyncMock()) as mock_publish:
        result = await svc.counter_invitation(
            escrow.id,
            TEST_RECEIVER_ID,
            MagicMock(
                invite_token=None,
                title=None,
                description="counter again",
                amount=111_000,
                acceptance_criteria=None,
                inspection_period=None,
                delivery_date=None,
                dispute_window=None,
                how_dispute_handled=None,
                who_pays_fees=None,
            ),
        )

    assert pending_counter.status == "countered_again"
    assert result.status == "counter_pending_initiator"
    assert result.counter_status == "awaiting_initiator"
    mock_publish.assert_any_await(
        "escrow.invite_responded",
        {
            "escrow_id": str(escrow.id),
            "status": "counter_pending_initiator",
            "offer_version": result.offer_version,
            "action": "countered",
            "actor_user_id": str(TEST_RECEIVER_ID),
            "user_id": str(TEST_USER_ID),
            "receiver_email": escrow.receiver_email,
        },
    )


@pytest.mark.asyncio
async def test_accept_with_token_binds_receiver_and_invalidates_token(svc, repo):
    escrow = make_escrow(
        receiver_id=None,
        receiver_email="receiver@example.com",
        invite_token_hash="d53f39f9f8af0ec8f6e7f73adf6a257f37a9b6fdb5f7cc8eb8b0f1c8f6ffaf76",
        initiator_accepted_at=datetime.now(timezone.utc),
    )
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.save = AsyncMock(side_effect=lambda model: model)

    with (
        patch(
            "app.service._hash_invite_token",
            return_value="d53f39f9f8af0ec8f6e7f73adf6a257f37a9b6fdb5f7cc8eb8b0f1c8f6ffaf76",
        ),
        patch("app.grpc_clients.get_user_wallet", AsyncMock(return_value="wallet-1")),
        patch("app.grpc_clients.lock_funds", AsyncMock(return_value=True)),
        patch("app.grpc_clients.check_org_membership", AsyncMock(return_value=True)),
        patch("app.service.publish", AsyncMock()),
    ):
        result, _ = await svc.accept_invitation(
            escrow.id,
            TEST_RECEIVER_ID,
            MagicMock(invite_token="plain-invite-token"),
        )

    assert result.status == "active"
    assert escrow.receiver_id == TEST_RECEIVER_ID
    assert escrow.invite_token_hash is None
    assert escrow.invite_token_used_at is not None


@pytest.mark.asyncio
async def test_resend_invitation_refreshes_email_token(svc, repo):
    escrow = make_escrow(receiver_id=None, receiver_email="old@example.com")
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.save = AsyncMock(return_value=escrow)

    with (
        patch("app.service._generate_invite_token", return_value="new-token"),
        patch(
            "app.service._hash_invite_token",
            return_value="hashed-new-token",
        ),
        patch("app.service.publish", AsyncMock()),
    ):
        result = await svc.resend_invitation(
            escrow.id,
            TEST_USER_ID,
            MagicMock(receiver_email="new@example.com"),
        )

    assert result.receiver_email == "new@example.com"
    assert result.invite_token_hash == "hashed-new-token"
    assert result.invite_expires_at is not None


@pytest.mark.asyncio
async def test_precheck_invitation_returns_login_when_account_exists(svc, repo):
    escrow = make_escrow(
        receiver_id=None,
        receiver_email="receiver@example.com",
        invite_token_hash="hashed-token",
        status="invited",
        invite_expires_at=datetime.now(timezone.utc).replace(year=2099),
    )
    repo.get_by_id = AsyncMock(return_value=escrow)

    with (
        patch("app.service._hash_invite_token", return_value="hashed-token"),
        patch("app.grpc_clients.check_email_exists", AsyncMock(return_value=True)),
    ):
        result = await svc.precheck_invitation(escrow.id, "plain-token")

    assert result.has_account is True
    assert result.next_action == "login"


@pytest.mark.asyncio
async def test_precheck_invitation_returns_register_when_account_missing(svc, repo):
    escrow = make_escrow(
        receiver_id=None,
        receiver_email="new-user@example.com",
        invite_token_hash="hashed-token",
        status="counter_pending_counterparty",
        invite_expires_at=datetime.now(timezone.utc).replace(year=2099),
    )
    repo.get_by_id = AsyncMock(return_value=escrow)

    with (
        patch("app.service._hash_invite_token", return_value="hashed-token"),
        patch("app.grpc_clients.check_email_exists", AsyncMock(return_value=False)),
    ):
        result = await svc.precheck_invitation(escrow.id, "plain-token")

    assert result.has_account is False
    assert result.next_action == "register"


@pytest.mark.asyncio
async def test_precheck_invitation_invalid_token_raises_403(svc, repo):
    escrow = make_escrow(
        receiver_id=None,
        receiver_email="receiver@example.com",
        invite_token_hash="expected-hash",
        status="invited",
        invite_expires_at=datetime.now(timezone.utc).replace(year=2099),
    )
    repo.get_by_id = AsyncMock(return_value=escrow)

    with patch("app.service._hash_invite_token", return_value="wrong-hash"):
        with pytest.raises(HTTPException) as exc_info:
            await svc.precheck_invitation(escrow.id, "bad-token")

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_org_scoped_initialize_requires_org_actor(svc, repo):
    with pytest.raises(HTTPException) as exc_info:
        await svc.initialize(
            OneTimeEscrowCreate(
                escrow_type="onetime",
                title="Org scope requires org key",
                currency="ETB",
                amount=25_000,
                initiator_role="seller",
                receiver_id=TEST_RECEIVER_ID,
            ),
            "organization",
            None,
            None,
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_org_actor_can_initialize_individual_seller_payload(svc, repo):
    repo.create = AsyncMock(
        return_value=make_escrow(initiator_id=None, initiator_org_id=TEST_ORG_ID)
    )

    with patch("app.service.publish", AsyncMock()):
        escrow, payment_url = await svc.initialize(
            OneTimeEscrowCreate(
                escrow_type="onetime",
                title="Org seller to individual buyer",
                currency="ETB",
                amount=50,
                initiator_role="seller",
                receiver_email="nahom.network@gmail.com",
            ),
            "organization",
            None,
            TEST_ORG_ID,
        )

    assert payment_url is None
    assert escrow.initiator_org_id == TEST_ORG_ID


@pytest.mark.asyncio
async def test_org_actor_initialize_rejects_buyer_initiator_role(svc, repo):
    with pytest.raises(ValidationError):
        OneTimeOrganizationEscrowCreate(
            escrow_type="onetime",
            title="Org buyer forbidden",
            currency="ETB",
            amount=50,
            initiator_role="buyer",
            receiver_email="nahom.network@gmail.com",
        )


def test_org_schema_defaults_initiator_role_to_seller() -> None:
    model = OneTimeOrganizationEscrowCreate(
        escrow_type="onetime",
        title="Org default seller",
        currency="ETB",
        amount=100_000,
        receiver_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    )
    assert model.initiator_role == "seller"


def test_milestone_initialize_payload_rejects_amount_mismatch():
    """Milestone create payload must have amount equal to sum of milestones."""
    with pytest.raises(ValidationError):
        MilestoneEscrowCreate(
            escrow_type="milestone",
            title="Mismatch",
            currency="ETB",
            amount=100_000,
            initiator_role="buyer",
            milestones=[
                {"title": "Phase 1", "amount": 70_000},
                {"title": "Phase 2", "amount": 50_000},
            ],
        )


def test_onetime_seller_without_org_id_is_valid():
    model = OneTimeEscrowCreate(
        escrow_type="onetime",
        title="Individual seller escrow",
        currency="ETB",
        amount=100_000,
        initiator_role="seller",
        receiver_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    )
    assert model.initiator_role == "seller"


def test_onetime_seller_allows_receiver_individual():
    model = OneTimeEscrowCreate(
        escrow_type="onetime",
        title="Org escrow",
        currency="ETB",
        amount=100_000,
        initiator_role="seller",
        receiver_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    )
    assert model.receiver_id is not None


def test_onetime_buyer_role_is_valid_without_org_payload_field():
    model = OneTimeEscrowCreate(
        escrow_type="onetime",
        title="Buyer role escrow",
        currency="ETB",
        amount=100_000,
        initiator_role="buyer",
        receiver_id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    )
    assert model.initiator_role == "buyer"


@pytest.mark.asyncio
async def test_initialize_rejects_receiver_when_receiver_is_organization(svc, repo):
    with patch("app.grpc_clients.check_organization_exists", AsyncMock(return_value=True)):
        with pytest.raises(HTTPException) as exc_info:
            await svc.initialize(
                OneTimeEscrowCreate(
                    escrow_type="onetime",
                    title="Org receiver blocked",
                    currency="ETB",
                    amount=25_000,
                    initiator_role="buyer",
                    receiver_id=TEST_RECEIVER_ID,
                ),
                "user",
                TEST_USER_ID,
                None,
            )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_invalid_transition(svc, repo):
    """Transitioning pending → completed by initiator should raise HTTP 400."""
    escrow = make_escrow(status="pending")
    repo.update_status = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await svc.transition_status(escrow, "completed", "initiator")

    assert exc_info.value.status_code == 400
    repo.update_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_transition_pending_to_active(svc, repo):
    """Transitioning pending → active should succeed for system actor."""
    escrow = make_escrow(status="pending")
    activated = make_escrow(status="active")
    repo.update_status = AsyncMock(return_value=activated)

    result = await svc.transition_status(escrow, "active", "system")
    assert result.status == "active"
    repo.update_status.assert_awaited_once_with(escrow, "active")


@pytest.mark.asyncio
async def test_activate_pending_escrows_for_buyer_locks_and_activates(svc, repo):
    escrow = make_escrow(
        status="pending",
        funded_at=None,
        initiator_role="buyer",
        initiator_id=TEST_USER_ID,
        receiver_id=TEST_RECEIVER_ID,
    )
    repo.list_pending_unfunded_for_participant = AsyncMock(return_value=[escrow])
    repo.save = AsyncMock(side_effect=lambda model: model)

    with (
        patch("app.grpc_clients.get_user_wallet", AsyncMock(return_value="wallet-1")),
        patch("app.grpc_clients.lock_funds", AsyncMock(return_value=True)) as mock_lock,
        patch("app.service.publish", AsyncMock()) as mock_publish,
    ):
        activated = await svc.activate_pending_escrows_for_buyer(
            TEST_USER_ID,
            trigger_reference="wallet-deposit-ref-1",
        )

    assert activated == 1
    assert escrow.status == "active"
    assert escrow.funded_at is not None
    mock_lock.assert_awaited_once_with(
        wallet_id="wallet-1",
        amount=escrow.amount + escrow.fee_amount,
        reference=escrow.transaction_ref,
        escrow_id=str(escrow.id),
    )
    mock_publish.assert_any_await(
        "escrow.activated",
        {
            "escrow_id": str(escrow.id),
            "transaction_ref": escrow.transaction_ref,
            "activation_source": "wallet_deposit_success",
            "trigger_reference": "wallet-deposit-ref-1",
            "initiator_id": str(escrow.initiator_id),
            "receiver_id": str(escrow.receiver_id),
            "receiver_email": escrow.receiver_email,
        },
    )


@pytest.mark.asyncio
async def test_activate_pending_escrows_for_buyer_insufficient_keeps_pending(svc, repo):
    escrow = make_escrow(
        status="pending",
        funded_at=None,
        initiator_role="buyer",
        initiator_id=TEST_USER_ID,
        receiver_id=TEST_RECEIVER_ID,
    )
    repo.list_pending_unfunded_for_participant = AsyncMock(return_value=[escrow])
    repo.save = AsyncMock(side_effect=lambda model: model)

    with (
        patch("app.grpc_clients.get_user_wallet", AsyncMock(return_value="wallet-1")),
        patch(
            "app.grpc_clients.lock_funds",
            AsyncMock(side_effect=RuntimeError("INSUFFICIENT_BALANCE")),
        ),
        patch("app.service.publish", AsyncMock()) as mock_publish,
    ):
        activated = await svc.activate_pending_escrows_for_buyer(TEST_USER_ID)

    assert activated == 0
    assert escrow.status == "pending"
    assert escrow.funded_at is None
    mock_publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_escrow(svc, repo):
    """cancel_escrow() should transition pending escrow to cancelled and unlock funds."""
    escrow = make_escrow(status="pending", funded_at=datetime.now(timezone.utc))
    cancelled = make_escrow(status="cancelled")
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.update_status = AsyncMock(return_value=cancelled)
    repo.save = AsyncMock(return_value=cancelled)

    with (
        patch("app.grpc_clients.unlock_funds", AsyncMock(return_value=True)) as mock_unlock,
        patch("app.grpc_clients.get_user_wallet", AsyncMock(return_value="wallet-uuid")),
        patch("app.service.publish", AsyncMock()),
    ):
        result = await svc.cancel_escrow(escrow.id, TEST_USER_ID)

    assert result.status == "cancelled"
    mock_unlock.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_escrow_forbidden(svc, repo):
    """A stranger (not initiator or receiver) should receive HTTP 403."""
    escrow = make_escrow(initiator_id=TEST_USER_ID, receiver_id=TEST_RECEIVER_ID)
    repo.get_by_id = AsyncMock(return_value=escrow)

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_escrow(escrow.id, TEST_STRANGER_ID)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_mark_complete(svc, repo):
    """Buyer (initiator with role=buyer) can complete an active escrow."""
    escrow = make_escrow(status="active", initiator_id=TEST_USER_ID, initiator_role="buyer")
    completed = make_escrow(status="completed", initiator_id=TEST_USER_ID, initiator_role="buyer")
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.update_status = AsyncMock(return_value=completed)
    repo.save = AsyncMock(return_value=completed)

    with (
        patch("app.grpc_clients.release_funds", AsyncMock(return_value=True)) as mock_release,
        patch("app.grpc_clients.get_user_wallet", AsyncMock(return_value="wallet-uuid")),
        patch("app.service.publish", AsyncMock()),
    ):
        result = await svc.mark_complete(escrow.id, TEST_USER_ID)

    assert result.status == "completed"
    mock_release.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_complete_fails_when_wallet_missing(svc, repo):
    """Completion should fail and avoid status transition if either wallet is missing."""
    escrow = make_escrow(status="active", initiator_id=TEST_USER_ID, initiator_role="buyer")
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.update_status = AsyncMock()
    repo.save = AsyncMock()

    with (
        patch("app.grpc_clients.get_user_wallet", AsyncMock(return_value=None)),
        patch("app.grpc_clients.release_funds", AsyncMock(return_value=True)) as mock_release,
        patch("app.service.publish", AsyncMock()),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await svc.mark_complete(escrow.id, TEST_USER_ID)

    assert exc_info.value.status_code == 409
    repo.update_status.assert_not_awaited()
    repo.save.assert_not_awaited()
    mock_release.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_complete_release_failure_does_not_persist_completed(svc, repo):
    """Completion should not be persisted when wallet release errors."""
    escrow = make_escrow(status="active", initiator_id=TEST_USER_ID, initiator_role="buyer")
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.update_status = AsyncMock()
    repo.save = AsyncMock()

    with (
        patch("app.grpc_clients.get_user_wallet", AsyncMock(return_value="wallet-uuid")),
        patch(
            "app.grpc_clients.release_funds",
            AsyncMock(side_effect=RuntimeError("release failed")),
        ),
        patch("app.service.publish", AsyncMock()),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await svc.mark_complete(escrow.id, TEST_USER_ID)

    assert exc_info.value.status_code == 503
    repo.update_status.assert_not_awaited()
    repo.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_complete_forbidden_for_non_buyer(svc, repo):
    """Non-buyer should receive HTTP 403 when trying to complete."""
    escrow = make_escrow(
        status="active",
        initiator_id=TEST_USER_ID,
        initiator_role="seller",
        receiver_id=TEST_RECEIVER_ID,
    )
    repo.get_by_id = AsyncMock(return_value=escrow)

    with pytest.raises(HTTPException) as exc_info:
        await svc.mark_complete(escrow.id, TEST_USER_ID)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_mark_complete_allows_receiver_when_initiator_role_is_seller(svc, repo):
    """For seller-initiated escrows, receiver is buyer and can complete when active."""
    escrow = make_escrow(
        status="active",
        initiator_id=TEST_STRANGER_ID,
        initiator_role="seller",
        receiver_id=TEST_USER_ID,
    )
    completed = make_escrow(
        status="completed",
        initiator_id=TEST_STRANGER_ID,
        initiator_role="seller",
        receiver_id=TEST_USER_ID,
    )
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.update_status = AsyncMock(return_value=completed)
    repo.save = AsyncMock(return_value=completed)

    with (
        patch("app.grpc_clients.release_funds", AsyncMock(return_value=True)) as mock_release,
        patch("app.grpc_clients.get_user_wallet", AsyncMock(return_value="wallet-uuid")),
        patch("app.service.publish", AsyncMock()),
    ):
        result = await svc.mark_complete(escrow.id, TEST_USER_ID)

    assert result.status == "completed"
    mock_release.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_complete_organization_initiator_uses_org_wallet_owner(svc, repo):
    """Organization-created seller escrow should release funds to org wallet on completion."""
    escrow = make_escrow(
        status="active",
        initiator_actor_type="organization",
        initiator_id=None,
        initiator_org_id=TEST_ORG_ID,
        initiator_role="seller",
        receiver_id=TEST_USER_ID,
    )
    completed = make_escrow(
        status="completed",
        initiator_actor_type="organization",
        initiator_id=None,
        initiator_org_id=TEST_ORG_ID,
        initiator_role="seller",
        receiver_id=TEST_USER_ID,
    )
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.update_status = AsyncMock(return_value=completed)
    repo.save = AsyncMock(return_value=completed)

    with (
        patch(
            "app.grpc_clients.get_user_wallet",
            AsyncMock(side_effect=["buyer-wallet", "org-wallet"]),
        ) as mock_get_wallet,
        patch("app.grpc_clients.release_funds", AsyncMock(return_value=True)) as mock_release,
        patch("app.service.publish", AsyncMock()),
    ):
        result = await svc.mark_complete(escrow.id, TEST_USER_ID)

    assert result.status == "completed"
    assert mock_get_wallet.await_args_list[0].args == (str(TEST_USER_ID), escrow.currency)
    assert mock_get_wallet.await_args_list[1].args == (str(TEST_ORG_ID), escrow.currency)
    mock_release.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_complete_rejects_non_active_escrow(svc, repo):
    escrow = make_escrow(status="invited", initiator_id=TEST_USER_ID, initiator_role="buyer")
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.update_status = AsyncMock()
    repo.save = AsyncMock()

    with (
        patch("app.grpc_clients.release_funds", AsyncMock(return_value=True)) as mock_release,
        patch("app.service.publish", AsyncMock()),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await svc.mark_complete(escrow.id, TEST_USER_ID)

    assert exc_info.value.status_code == 400
    assert "Cannot complete escrow" in str(exc_info.value.detail)
    repo.update_status.assert_not_awaited()
    repo.save.assert_not_awaited()
    mock_release.assert_not_awaited()


@pytest.mark.asyncio
async def test_deliver_milestone(svc, repo):
    """Seller (receiver) can mark a milestone as delivered."""
    escrow_id = uuid.uuid4()
    escrow = make_escrow(
        id=escrow_id,
        status="active",
        initiator_id=TEST_USER_ID,
        initiator_role="buyer",
        receiver_id=TEST_RECEIVER_ID,
    )
    milestone = make_milestone(escrow_id=escrow_id, status="pending")
    delivered = make_milestone(escrow_id=escrow_id, status="delivered")
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.get_milestone = AsyncMock(return_value=milestone)
    repo.update_milestone = AsyncMock(return_value=delivered)

    with patch("app.service.publish", AsyncMock()):
        result = await svc.deliver_milestone(escrow_id, milestone.id, TEST_RECEIVER_ID)

    assert result.status == "delivered"
    repo.update_milestone.assert_awaited_once()


@pytest.mark.asyncio
async def test_approve_milestone(svc, repo):
    """Buyer can approve a delivered milestone and funds are released."""
    escrow_id = uuid.uuid4()
    milestone_id = uuid.uuid4()
    escrow = make_escrow(
        id=escrow_id,
        status="active",
        initiator_id=TEST_USER_ID,
        initiator_role="buyer",
        receiver_id=TEST_RECEIVER_ID,
    )
    milestone = make_milestone(id=milestone_id, escrow_id=escrow_id, status="delivered")
    approved = make_milestone(id=milestone_id, escrow_id=escrow_id, status="completed")
    all_milestones = [approved]
    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.get_milestone = AsyncMock(return_value=milestone)
    repo.update_milestone = AsyncMock(return_value=approved)
    repo.get_milestones = AsyncMock(return_value=all_milestones)
    repo.update_status = AsyncMock(return_value=make_escrow(status="completed"))
    repo.save = AsyncMock()

    with (
        patch("app.grpc_clients.release_funds", AsyncMock(return_value=True)) as mock_release,
        patch("app.grpc_clients.get_user_wallet", AsyncMock(return_value="wallet-uuid")),
        patch("app.service.publish", AsyncMock()),
    ):
        result = await svc.approve_milestone(escrow_id, milestone_id, TEST_USER_ID)

    assert result.status == "completed"
    mock_release.assert_awaited_once()


@pytest.mark.asyncio
async def test_join_cycle_max_exceeded(svc, repo):
    """Joining when max_contributors is reached should raise HTTP 400."""
    escrow_id = uuid.uuid4()
    cycle_id = uuid.uuid4()
    escrow = make_escrow(id=escrow_id, escrow_type="recurring", status="active")
    cycle = RecurringCycle()
    cycle.id = cycle_id
    cycle.escrow_id = escrow_id
    cycle.max_contributors = 2
    cycle.min_contributors = 1
    cycle.expected_amount = 50_000
    cycle.status = "active"

    repo.get_by_id = AsyncMock(return_value=escrow)
    repo.get_cycle = AsyncMock(return_value=cycle)
    repo.count_contributors = AsyncMock(return_value=2)  # already at max

    req = MagicMock()
    req.contribution = 50_000
    req.name = None
    req.email = None

    with pytest.raises(HTTPException) as exc_info:
        await svc.join_cycle(escrow_id, TEST_USER_ID, req)

    assert exc_info.value.status_code == 400
    assert "Maximum" in exc_info.value.detail
