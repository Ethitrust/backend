"""Unit tests for dispute service business logic."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.service import DisputeService
from fastapi import HTTPException


@pytest.fixture
def repo() -> SimpleNamespace:
    return SimpleNamespace(
        create=AsyncMock(),
        get_by_id=AsyncMock(),
        get_by_escrow=AsyncMock(),
        update_status=AsyncMock(),
        add_evidence=AsyncMock(),
        list_evidence=AsyncMock(),
        list_disputes=AsyncMock(),
        list_disputes_by_raiser=AsyncMock(),
    )


@pytest.fixture
def service(repo: SimpleNamespace) -> DisputeService:
    return DisputeService(repo)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_raise_dispute_requires_escrow_participant(service, repo, monkeypatch):
    escrow_id = uuid.uuid4()
    actor_id = uuid.uuid4()

    monkeypatch.setattr(
        "app.service.grpc_clients.get_escrow",
        AsyncMock(
            return_value={
                "status": "active",
                "initiator_id": str(uuid.uuid4()),
                "receiver_id": str(uuid.uuid4()),
            }
        ),
    )

    with pytest.raises(HTTPException) as exc:
        await service.raise_dispute(
            escrow_id,
            actor_id,
            SimpleNamespace(reason="fraud", description="A" * 12),
        )

    assert exc.value.status_code == 403
    repo.get_by_escrow.assert_not_called()


@pytest.mark.asyncio
async def test_raise_dispute_publishes_targeted_notifications(service, repo, monkeypatch):
    escrow_id = uuid.uuid4()
    initiator_id = uuid.uuid4()
    receiver_id = uuid.uuid4()

    monkeypatch.setattr(
        "app.service.grpc_clients.get_escrow",
        AsyncMock(
            return_value={
                "status": "active",
                "initiator_id": str(initiator_id),
                "receiver_id": str(receiver_id),
            }
        ),
    )
    monkeypatch.setattr(
        "app.service.grpc_clients.transition_escrow_status",
        AsyncMock(return_value={"success": True}),
    )

    publish_mock = AsyncMock()
    monkeypatch.setattr("app.service.publish", publish_mock)

    dispute = SimpleNamespace(id=uuid.uuid4(), escrow_id=escrow_id, status="open")
    repo.get_by_escrow.return_value = None
    repo.create.return_value = dispute

    await service.raise_dispute(
        escrow_id,
        receiver_id,
        SimpleNamespace(reason="quality", description="Work did not meet criteria."),
    )

    assert publish_mock.await_count == 2
    published_user_ids = {call.args[1]["user_id"] for call in publish_mock.await_args_list}
    assert published_user_ids == {str(initiator_id), str(receiver_id)}
    for call in publish_mock.await_args_list:
        assert call.args[0] == "dispute.opened"
        payload = call.args[1]
        assert payload["actor_user_id"] == str(receiver_id)
        assert payload["raised_by"] == str(receiver_id)
        assert payload["escrow_id"] == str(escrow_id)


@pytest.mark.asyncio
async def test_raise_dispute_uses_disputing_user_as_transition_actor(
    service,
    repo,
    monkeypatch,
):
    escrow_id = uuid.uuid4()
    actor_id = uuid.uuid4()

    monkeypatch.setattr(
        "app.service.grpc_clients.get_escrow",
        AsyncMock(
            return_value={
                "status": "active",
                "initiator_id": str(actor_id),
                "receiver_id": str(uuid.uuid4()),
            }
        ),
    )

    transition_mock = AsyncMock(return_value={"success": True})
    monkeypatch.setattr("app.service.grpc_clients.transition_escrow_status", transition_mock)
    monkeypatch.setattr("app.service.publish", AsyncMock())

    repo.get_by_escrow.return_value = None
    repo.create.return_value = SimpleNamespace(id=uuid.uuid4(), escrow_id=escrow_id, status="open")

    await service.raise_dispute(
        escrow_id,
        actor_id,
        SimpleNamespace(reason="fraud", description="Evidence attached."),
    )

    transition_mock.assert_awaited_once_with(
        escrow_id,
        "disputed",
        actor_id=str(actor_id),
    )


@pytest.mark.asyncio
async def test_mark_under_review_requires_moderator_role(service):
    with pytest.raises(HTTPException) as exc:
        await service.mark_under_review(
            uuid.uuid4(),
            uuid.uuid4(),
            "user",
            "Needs moderator attention",
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_cancel_dispute_allows_only_raiser(service, repo):
    dispute = SimpleNamespace(
        id=uuid.uuid4(),
        escrow_id=uuid.uuid4(),
        raised_by=uuid.uuid4(),
        status="open",
    )
    repo.get_by_id.return_value = dispute

    with pytest.raises(HTTPException) as exc:
        await service.cancel_dispute(dispute.id, uuid.uuid4())

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_resolve_buyer_marks_dispute_as_pending(service, repo, monkeypatch):
    dispute_id = uuid.uuid4()
    escrow_id = uuid.uuid4()
    initiator_id = uuid.uuid4()
    receiver_id = uuid.uuid4()

    repo.get_by_id.return_value = SimpleNamespace(
        id=dispute_id,
        escrow_id=escrow_id,
        raised_by=initiator_id,
        status="open",
    )
    repo.update_status.return_value = SimpleNamespace(
        id=dispute_id,
        escrow_id=escrow_id,
        raised_by=initiator_id,
        status="resolution_pending_buyer",
    )

    release_mock = AsyncMock(return_value={"success": True})
    transition_mock = AsyncMock(return_value={"success": True})
    publish_mock = AsyncMock()

    monkeypatch.setattr("app.service.grpc_clients.release_funds", release_mock)
    monkeypatch.setattr(
        "app.service.grpc_clients.transition_escrow_status",
        transition_mock,
    )
    monkeypatch.setattr(
        "app.service.grpc_clients.get_escrow",
        AsyncMock(
            return_value={
                "initiator_id": str(initiator_id),
                "receiver_id": str(receiver_id),
            }
        ),
    )
    monkeypatch.setattr("app.service.publish", publish_mock)

    dispute = await service.resolve_dispute(
        dispute_id,
        uuid.uuid4(),
        "admin",
        SimpleNamespace(
            resolution="buyer",
            resolution_note="Buyer evidence is decisive.",
        ),
    )

    assert dispute.status == "resolution_pending_buyer"
    release_mock.assert_not_awaited()
    transition_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_resolution_transitions_escrow_and_marks_resolved(
    service,
    repo,
    monkeypatch,
):
    dispute_id = uuid.uuid4()
    escrow_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    initiator_id = uuid.uuid4()
    receiver_id = uuid.uuid4()

    repo.get_by_id.return_value = SimpleNamespace(
        id=dispute_id,
        escrow_id=escrow_id,
        raised_by=initiator_id,
        status="resolution_pending_buyer",
    )
    repo.update_status.return_value = SimpleNamespace(
        id=dispute_id,
        escrow_id=escrow_id,
        raised_by=initiator_id,
        status="resolved_buyer",
    )

    release_mock = AsyncMock(return_value={"success": True})
    transition_mock = AsyncMock(return_value={"success": True})
    publish_mock = AsyncMock()

    monkeypatch.setattr("app.service.grpc_clients.release_funds", release_mock)
    monkeypatch.setattr(
        "app.service.grpc_clients.transition_escrow_status",
        transition_mock,
    )
    monkeypatch.setattr(
        "app.service.grpc_clients.get_escrow",
        AsyncMock(
            return_value={
                "initiator_id": str(initiator_id),
                "receiver_id": str(receiver_id),
            }
        ),
    )
    monkeypatch.setattr("app.service.publish", publish_mock)

    dispute = await service.execute_resolution(dispute_id, "buyer", admin_id)

    assert dispute.status == "resolved_buyer"
    release_mock.assert_awaited_once_with(escrow_id, "buyer")
    transition_mock.assert_awaited_once_with(escrow_id, "refunded")
    assert publish_mock.await_count == 2


@pytest.mark.asyncio
async def test_add_evidence_publishes_targeted_notifications(service, repo, monkeypatch):
    dispute_id = uuid.uuid4()
    escrow_id = uuid.uuid4()
    initiator_id = uuid.uuid4()
    receiver_id = uuid.uuid4()

    dispute = SimpleNamespace(
        id=dispute_id,
        escrow_id=escrow_id,
        raised_by=initiator_id,
        status="open",
    )
    repo.get_by_id.return_value = dispute

    monkeypatch.setattr(
        "app.service.grpc_clients.get_escrow",
        AsyncMock(
            return_value={
                "status": "disputed",
                "initiator_id": str(initiator_id),
                "receiver_id": str(receiver_id),
            }
        ),
    )

    publish_mock = AsyncMock()
    monkeypatch.setattr("app.service.publish", publish_mock)

    evidence = SimpleNamespace(id=uuid.uuid4(), dispute_id=dispute_id)
    repo.add_evidence.return_value = evidence

    result = await service.add_evidence(
        dispute_id=dispute_id,
        user_id=receiver_id,
        file_url="https://files.example/evidence.png",
        file_type="image/png",
        description="Proof of delivery issue",
    )

    assert result is evidence
    assert publish_mock.await_count == 2
    published_user_ids = {call.args[1]["user_id"] for call in publish_mock.await_args_list}
    assert published_user_ids == {str(initiator_id), str(receiver_id)}
    for call in publish_mock.await_args_list:
        assert call.args[0] == "dispute.evidence.added"
        payload = call.args[1]
        assert payload["dispute_id"] == str(dispute_id)
        assert payload["escrow_id"] == str(escrow_id)
        assert payload["actor_user_id"] == str(receiver_id)
        assert payload["added_by"] == str(receiver_id)


@pytest.mark.asyncio
async def test_execute_resolution_is_idempotent_when_already_resolved(
    service,
    repo,
    monkeypatch,
):
    dispute_id = uuid.uuid4()
    escrow_id = uuid.uuid4()
    dispute = SimpleNamespace(
        id=dispute_id,
        escrow_id=escrow_id,
        raised_by=uuid.uuid4(),
        status="resolved_seller",
    )
    repo.get_by_id.return_value = dispute

    release_mock = AsyncMock(return_value={"success": True})
    transition_mock = AsyncMock(return_value={"success": True})
    monkeypatch.setattr("app.service.grpc_clients.release_funds", release_mock)
    monkeypatch.setattr(
        "app.service.grpc_clients.transition_escrow_status",
        transition_mock,
    )

    result = await service.execute_resolution(dispute_id, "seller", uuid.uuid4())

    assert result is dispute
    release_mock.assert_not_awaited()
    transition_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_disputes_returns_pagination_payload(service, repo):
    dispute = SimpleNamespace(
        id=uuid.uuid4(),
        escrow_id=uuid.uuid4(),
        raised_by=uuid.uuid4(),
        reason="fraud",
        status="open",
        resolution_note=None,
        resolved_by=None,
        resolved_at=None,
        created_at=None,
    )
    repo.list_disputes.return_value = ([dispute], 1)

    result = await service.list_disputes("admin", "open", 1, 20)

    assert result["total"] == 1
    assert result["pages"] == 1
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_list_my_disputes_returns_pagination_payload(service, repo):
    actor_id = uuid.uuid4()
    dispute = SimpleNamespace(
        id=uuid.uuid4(),
        escrow_id=uuid.uuid4(),
        raised_by=actor_id,
        reason="fraud",
        status="open",
        resolution_note=None,
        resolved_by=None,
        resolved_at=None,
        created_at=None,
    )
    repo.list_disputes_by_raiser.return_value = ([dispute], 1)

    result = await service.list_my_disputes(actor_id, "open", 1, 20)

    repo.list_disputes_by_raiser.assert_awaited_once_with(
        raised_by=actor_id,
        status_filter="open",
        offset=0,
        limit=20,
    )
    assert result["total"] == 1
    assert result["pages"] == 1
    assert len(result["items"]) == 1
