from __future__ import annotations

import logging
import os
import smtplib
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "noreply@ethitrust.me")

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "email"
JINJA_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "xml")),
)

EVENT_TEMPLATE_MAP: dict[str, str] = {
    "escrow.invite_received": "escrow_invite_received.html",
    "escrow.invite_responded": "escrow_invite_responded.html",
    "escrow.invite_countered": "escrow_invite_countered.html",
    "escrow.invite_rejected": "escrow_invite_rejected.html",
    "escrow.invite_expired": "escrow_invite_expired.html",
    "escrow.funded": "escrow_funded.html",
    "escrow.completed": "escrow_completed.html",
    "dispute.opened": "dispute_opened.html",
    "dispute.resolved": "dispute_resolved.html",
    "payout.success": "payout_success.html",
    "payout.failed": "payout_failed.html",
    "invoice.paid": "invoice_paid.html",
    "user.otp_resent": "otp_resent.html",
    "user.password_reset_requested": "password_reset_requested.html",
    "user.registered": "user_registered.html",
}


def _render_email_body(
    *,
    event: str | None,
    subject: str,
    html_body: str,
    template_data: dict,
) -> str:
    rendered_message = (
        JINJA_ENV.from_string(html_body).render(**template_data) if html_body else ""
    )
    context = {
        "subject": subject,
        "message": rendered_message,
        "event": event,
        "year": datetime.now(UTC).year,
        **template_data,
    }

    template_name = EVENT_TEMPLATE_MAP.get(event or "", "generic_notification.html")
    logger.info(
        "email.render.template_selected event=%s template=%s template_data_keys=%s",
        event,
        template_name,
        sorted(template_data.keys()),
    )
    try:
        template = JINJA_ENV.get_template(template_name)
        return template.render(**context)
    except TemplateNotFound:
        logger.warning("Template %s not found, using generic template", template_name)

    if html_body:
        return JINJA_ENV.from_string(html_body).render(**context)

    fallback = JINJA_ENV.get_template("generic_notification.html")
    return fallback.render(**context)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def send_email_notification(
    self,
    to: str,
    subject: str,
    html_body: str,
    template_data: Optional[dict] = None,
    event: str | None = None,
):
    """
    Send an HTML email notification via SMTP.
    Supports event-driven Jinja2 template rendering.
    Called by the notification service or other components.
    """
    try:
        logger.info(
            "email.send.start task_id=%s event=%s to=%s subject=%s smtp_host=%s smtp_port=%s smtp_user_set=%s smtp_pass_set=%s from_email=%s",
            getattr(self.request, "id", "-"),
            event,
            to,
            subject,
            SMTP_HOST,
            SMTP_PORT,
            bool(SMTP_USER),
            bool(SMTP_PASS),
            FROM_EMAIL,
        )
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = FROM_EMAIL
        msg["To"] = to

        body = _render_email_body(
            event=event,
            subject=subject,
            html_body=html_body,
            template_data=template_data or {},
        )

        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            logger.info(
                "email.smtp.connect task_id=%s host=%s port=%s",
                getattr(self.request, "id", "-"),
                SMTP_HOST,
                SMTP_PORT,
            )
            server.ehlo()
            server.starttls()
            if SMTP_USER and SMTP_PASS:
                logger.info(
                    "email.smtp.login task_id=%s smtp_user=%s",
                    getattr(self.request, "id", "-"),
                    SMTP_USER,
                )
                server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(FROM_EMAIL, to, msg.as_string())

        logger.info(
            "email.send.success task_id=%s event=%s to=%s subject=%s",
            getattr(self.request, "id", "-"),
            event,
            to,
            subject,
        )
        return {"status": "sent"}

    except Exception as exc:
        logger.exception(
            "email.send.failed task_id=%s event=%s to=%s error_type=%s error=%s",
            getattr(self.request, "id", "-"),
            event,
            to,
            exc.__class__.__name__,
            exc,
        )
        raise self.retry(exc=exc)
