from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app import messaging


@pytest.mark.asyncio
async def test_resolve_recipient_email_prefers_receiver_email(monkeypatch):
    mock_get_user = AsyncMock(return_value={"email": "from-user@example.com"})
    monkeypatch.setattr("app.grpc_clients.get_user_by_id", mock_get_user)

    email = await messaging._resolve_recipient_email(
        {"receiver_email": "invitee@example.com", "email": "fallback@example.com"},
        None,
    )

    assert email == "invitee@example.com"
    mock_get_user.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_recipient_email_uses_user_lookup(monkeypatch):
    mock_get_user = AsyncMock(return_value={"email": "resolved@example.com"})
    monkeypatch.setattr("app.grpc_clients.get_user_by_id", mock_get_user)

    email = await messaging._resolve_recipient_email(
        {"some": "payload"},
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )

    assert email == "resolved@example.com"
    mock_get_user.assert_awaited_once_with("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.mark.asyncio
async def test_resolve_recipient_email_reads_nested_payload_email(monkeypatch):
    mock_get_user = AsyncMock(return_value={"email": "from-user@example.com"})
    monkeypatch.setattr("app.grpc_clients.get_user_by_id", mock_get_user)

    email = await messaging._resolve_recipient_email(
        {
            "payload": {
                "user_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "email": "nested@example.com",
            }
        },
        None,
    )

    assert email == "nested@example.com"
    mock_get_user.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_recipient_email_uses_nested_user_id_lookup(monkeypatch):
    mock_get_user = AsyncMock(return_value={"email": "lookup@example.com"})
    monkeypatch.setattr("app.grpc_clients.get_user_by_id", mock_get_user)

    email = await messaging._resolve_recipient_email(
        {
            "data": {
                "user_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            }
        },
        None,
    )

    assert email == "lookup@example.com"
    mock_get_user.assert_awaited_once_with("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def test_dispatch_email_task_invokes_workers_task(monkeypatch):
    captured: dict[str, object] = {}

    class FakeCelery:
        def send_task(self, name: str, kwargs: dict) -> None:
            captured["name"] = name
            captured["kwargs"] = kwargs

    monkeypatch.setattr("app.messaging._CELERY_DISPATCH", FakeCelery())

    messaging._dispatch_email_task(
        to="user@example.com",
        subject="Escrow Invitation",
        body="You have received a new escrow invitation.",
        event="escrow.invite_received",
        metadata={"escrow_id": "123"},
    )

    assert captured["name"] == "app.tasks.email_tasks.send_email_notification"
    assert captured["kwargs"] == {
        "to": "user@example.com",
        "subject": "Escrow Invitation",
        "html_body": "You have received a new escrow invitation.",
        "template_data": {"escrow_id": "123"},
        "event": "escrow.invite_received",
    }


def test_enrich_email_metadata_builds_invitation_url(monkeypatch):
    monkeypatch.setattr("app.messaging.FRONTEND_URL", "https://ethitrust.me")

    enriched = messaging._enrich_email_metadata(
        "escrow.invite_received",
        {
            "escrow_id": "escrow-123",
            "invite_token": "token-xyz",
        },
    )

    assert enriched["invitation_url"] == (
        "https://ethitrust.me/invitation?escrow_id=escrow-123&token=token-xyz"
    )


def test_enrich_email_metadata_builds_invitation_url_without_token(monkeypatch):
    monkeypatch.setattr("app.messaging.FRONTEND_URL", "https://ethitrust.me")

    enriched = messaging._enrich_email_metadata(
        "escrow.invite_received",
        {
            "escrow_id": "escrow-123",
            "initiator_actor_type": "organization",
        },
    )

    assert enriched["invitation_url"] == "https://ethitrust.me/invitation?escrow_id=escrow-123"


def test_event_titles_include_auth_email_events() -> None:
    assert "user.otp_resent" in messaging._EVENT_TITLES
    assert "user.password_reset_requested" in messaging._EVENT_TITLES
    assert "wallet.deposit.success" in messaging._EVENT_TITLES
    assert "dispute.evidence.added" in messaging._EVENT_TITLES
    assert "dispute.under_review" in messaging._EVENT_TITLES
    assert "dispute.resolution.requested" in messaging._EVENT_TITLES
    assert "dispute.cancelled" in messaging._EVENT_TITLES
    assert "payout.requested" in messaging._EVENT_TITLES
    assert "organization.created" in messaging._EVENT_TITLES
    assert "escrow.activated" in messaging._EVENT_TITLES
    assert "escrow.cancelled" in messaging._EVENT_TITLES
    assert "milestone.delivered" in messaging._EVENT_TITLES
    assert "milestone.approved" in messaging._EVENT_TITLES


@pytest.mark.parametrize(
    ("action", "expected_title", "expected_body"),
    [
        (
            "accepted",
            "Escrow Invitation Accepted",
            "Your counterparty accepted the escrow invitation.",
        ),
        (
            "countered",
            "Escrow Invitation Countered",
            "Your counterparty proposed a counter-offer for the escrow.",
        ),
        (
            "rejected",
            "Escrow Invitation Rejected",
            "Your counterparty rejected the escrow invitation.",
        ),
    ],
)
def test_resolve_event_title_and_body_for_invite_responses(
    action: str,
    expected_title: str,
    expected_body: str,
) -> None:
    title, body = messaging._resolve_event_title_and_body(
        "escrow.invite_responded",
        {"action": action},
    )

    assert title == expected_title
    assert body == expected_body


def test_resolve_event_title_and_body_for_dispute_opened() -> None:
    title, body = messaging._resolve_event_title_and_body("dispute.opened", {})

    assert title == "Dispute Opened"
    assert body == "Your counterparty raised a dispute on this escrow."


def test_event_titles_include_counterparty_counter_event() -> None:
    assert "escrow.invite_countered" in messaging._EVENT_TITLES


def test_resolve_user_ids_supports_multi_recipient_payload() -> None:
    body = {
        "initiator_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "receiver_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "owner_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
    }

    resolved = messaging._resolve_user_ids(body)

    assert resolved == [
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    ]
