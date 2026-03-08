from email import message_from_string
from unittest.mock import MagicMock, patch


def _extract_html_payload(raw_message: str) -> str:
    message = message_from_string(raw_message)
    payload = message.get_payload()[0]
    return payload.get_payload(decode=True).decode()


def test_deliver_webhook_success():
    """deliver_webhook should return {"status": "delivered"} on HTTP 2xx."""
    from app.tasks.webhook_tasks import deliver_webhook

    with patch("httpx.post") as mock_post:
        resp = MagicMock()
        resp.status_code = 200
        mock_post.return_value = resp
        result = deliver_webhook.run(
            "https://example.com/hooks",
            {"event": "escrow.completed"},
            "secret123",
        )
    assert result["status"] == "delivered"
    assert result["status_code"] == 200
    mock_post.assert_called_once()


def test_deliver_webhook_4xx_no_retry():
    """deliver_webhook should return {"status": "rejected"} on HTTP 4xx without retrying."""
    from app.tasks.webhook_tasks import deliver_webhook

    with patch("httpx.post") as mock_post:
        resp = MagicMock()
        resp.status_code = 404
        mock_post.return_value = resp
        result = deliver_webhook.run(
            "https://example.com/hooks",
            {"event": "test"},
            "secret",
        )
    assert result["status"] == "rejected"
    assert result["status_code"] == 404


def test_send_email_notification():
    """send_email_notification should call SMTP and return {"status": "sent"}."""
    from app.tasks.email_tasks import send_email_notification

    with patch("smtplib.SMTP") as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = lambda s: mock_server
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
        result = send_email_notification.run(
            "user@example.com",
            "Subject",
            "<p>Hello {{name}}</p>",
            {"name": "Ada"},
        )
    assert result["status"] == "sent"
    sent_payload = _extract_html_payload(mock_server.sendmail.call_args[0][2])
    assert "Hello Ada" in sent_payload


def test_send_email_notification_event_template():
    """send_email_notification should render event-specific templates when event is provided."""
    from app.tasks.email_tasks import send_email_notification

    with patch("smtplib.SMTP") as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__ = lambda s: mock_server
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
        result = send_email_notification.run(
            "invited@example.com",
            "Escrow Invitation",
            "",
            {
                "invite_token": "abc123",
                "invitation_url": "https://ethitrust.me/invitation?escrow_id=123&token=abc123",
            },
            "escrow.invite_received",
        )

    assert result["status"] == "sent"
    sent_payload = _extract_html_payload(mock_server.sendmail.call_args[0][2])
    assert "You’ve been invited to an escrow" in sent_payload
    assert "Review Invitation" in sent_payload
    assert (
        "https://ethitrust.me/invitation?escrow_id=123&amp;token=abc123" in sent_payload
    )


def test_celery_beat_schedule_configured():
    """Periodic beat tasks must be present in the Celery schedule conf."""
    from app.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert "check-escrow-inspection-expiry" in schedule
    assert "check-invitation-expiry" in schedule
    assert "process-recurring-cycles" in schedule
    assert (
        schedule["check-escrow-inspection-expiry"]["task"]
        == "app.tasks.escrow_tasks.check_escrow_inspection_expiry"
    )
    assert (
        schedule["check-invitation-expiry"]["task"]
        == "app.tasks.escrow_tasks.check_invitation_expiry"
    )
    assert (
        schedule["process-recurring-cycles"]["task"]
        == "app.tasks.recurring_tasks.process_recurring_cycle_due"
    )
