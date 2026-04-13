"""RabbitMQ messaging for the Notification service.

Subscribes to events from other services and creates in-app notifications.
Also publishes email notification events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from urllib.parse import urlencode

import aio_pika
from celery import Celery

from app import grpc_clients

logger = logging.getLogger(__name__)
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
EXCHANGE_NAME = "ethitrust"
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ethitrust.me")
_CELERY_DISPATCH = Celery("notification-dispatch", broker=REDIS_URL, backend=REDIS_URL)


def _parse_json_object(value: object) -> dict | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _candidate_payloads(body: dict) -> list[dict]:
    candidates: list[dict] = [body]
    for key in ("payload", "data", "user", "metadata"):
        value = body.get(key)
        if isinstance(value, dict):
            candidates.append(value)
            continue

        parsed = _parse_json_object(value)
        if parsed is not None:
            candidates.append(parsed)

    return candidates


def _extract_first_nonempty_string(payloads: list[dict], keys: tuple[str, ...]) -> str | None:
    for payload in payloads:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _resolve_user_id(body: dict) -> str | None:
    payloads = _candidate_payloads(body)
    return _extract_first_nonempty_string(
        payloads,
        (
            "user_id",
            "receiver_id",
            "recipient_id",
            "actor_user_id",
            "owner_id",
            "initiator_id",
        ),
    )


def _resolve_user_ids(body: dict) -> list[str]:
    payloads = _candidate_payloads(body)
    keys = (
        "user_id",
        "receiver_id",
        "recipient_id",
        "actor_user_id",
        "owner_id",
        "initiator_id",
    )
    collected: list[str] = []
    for payload in payloads:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str):
                normalized = value.strip()
                if normalized and normalized not in collected:
                    collected.append(normalized)
    return collected


async def publish(routing_key: str, body: dict) -> None:
    try:
        connection = await aio_pika.connect_robust(RABBITMQ_URL)
        async with connection:
            channel = await connection.channel()
            exchange = await channel.declare_exchange(
                EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
            )
            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(body).encode(),
                    content_type="application/json",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=routing_key,
            )
    except Exception:
        logger.exception("Failed to publish %s", routing_key)


def _dispatch_email_task(*, to: str, subject: str, body: str, event: str, metadata: dict) -> None:
    try:
        task = _CELERY_DISPATCH.send_task(
            "app.tasks.email_tasks.send_email_notification",
            kwargs={
                "to": to,
                "subject": subject,
                "html_body": body,
                "template_data": metadata,
                "event": event,
            },
        )
        logger.info(
            "email.dispatch.enqueued event=%s to=%s celery_task_id=%s metadata_keys=%s",
            event,
            to,
            getattr(task, "id", "-"),
            sorted(metadata.keys()),
        )
    except Exception:
        logger.exception("Failed to dispatch email task for event %s", event)


async def _resolve_recipient_email(body: dict, user_id_str: str | None) -> str | None:
    payloads = _candidate_payloads(body)
    direct_email = _extract_first_nonempty_string(
        payloads,
        ("receiver_email", "email", "recipient_email", "to", "user_email"),
    )
    if direct_email:
        return direct_email

    resolved_user_id = (user_id_str or "").strip() or _resolve_user_id(body)
    if not resolved_user_id:
        return None

    try:
        profile = await grpc_clients.get_user_by_id(resolved_user_id)
    except RuntimeError:
        logger.exception("Failed to resolve recipient email for user_id %s", resolved_user_id)
        return None

    email = profile.get("email")
    if isinstance(email, str) and email.strip():
        return email.strip()

    return None


def _enrich_email_metadata(event_type: str, metadata: dict) -> dict:
    enriched = dict(metadata)

    if event_type == "escrow.invite_received":
        escrow_id = enriched.get("escrow_id")
        invite_token = enriched.get("invite_token")
        if isinstance(escrow_id, str):
            base_url = FRONTEND_URL.rstrip("/")
            query_params = {"escrow_id": escrow_id}
            if isinstance(invite_token, str) and invite_token.strip():
                query_params["token"] = invite_token
            query = urlencode(query_params)
            enriched["invitation_url"] = f"{base_url}/invitation?{query}"

    return enriched


_EVENT_TITLES = {
    "user.otp_resent": (
        "Your verification code",
        "A new verification code has been generated for your account.",
    ),
    "user.password_reset_requested": (
        "Password reset requested",
        "Use the reset link we sent to securely update your password.",
    ),
    "user.registered": (
        "Welcome to Ethitrust",
        "Your account has been created successfully.",
    ),
    "organization.created": (
        "Organization Created",
        "Your organization has been created successfully.",
    ),
    "escrow.invite_received": (
        "Escrow Invitation",
        "You have received a new escrow invitation.",
    ),
    "escrow.invite_responded": (
        "Escrow Invitation Updated",
        "An escrow invitation has a new response.",
    ),
    "escrow.invite_countered": (
        "Escrow Counter Offer",
        "An escrow invitation has been countered with new terms.",
    ),
    "escrow.invite_rejected": (
        "Escrow Invitation Rejected",
        "An escrow invitation was rejected.",
    ),
    "escrow.invite_expired": (
        "Escrow Invitation Expired",
        "An escrow invitation has expired and can no longer be accepted.",
    ),
    "escrow.funded": ("Escrow Funded", "Your escrow has been funded successfully."),
    "escrow.completed": (
        "Escrow Completed",
        "Your escrow transaction has been completed.",
    ),
    "dispute.opened": ("Dispute Opened", "A dispute has been raised on your escrow."),
    "dispute.evidence.added": (
        "New Dispute Evidence",
        "New evidence was added to an active dispute.",
    ),
    "dispute.under_review": (
        "Dispute Under Review",
        "A moderator is currently reviewing your dispute.",
    ),
    "dispute.resolution.requested": (
        "Dispute Resolution Proposed",
        "A dispute resolution outcome has been proposed.",
    ),
    "dispute.resolved": ("Dispute Resolved", "Your dispute has been resolved."),
    "dispute.cancelled": (
        "Dispute Cancelled",
        "The dispute has been cancelled.",
    ),
    "payout.success": (
        "Payout Successful",
        "Your payout has been processed successfully.",
    ),
    "payout.failed": (
        "Payout Failed",
        "Your payout could not be processed. Please retry.",
    ),
    "payout.requested": (
        "Payout Requested",
        "Your payout request was received and is being processed.",
    ),
    "wallet.deposit.success": (
        "Wallet Deposit Successful",
        "Your wallet has been funded successfully.",
    ),
    "escrow.created": (
        "Escrow Created",
        "A new escrow has been created.",
    ),
    "escrow.activated": (
        "Escrow Activated",
        "An escrow is now active.",
    ),
    "escrow.cancelled": (
        "Escrow Cancelled",
        "An escrow has been cancelled.",
    ),
    "milestone.delivered": (
        "Milestone Delivered",
        "A milestone has been marked as delivered.",
    ),
    "milestone.approved": (
        "Milestone Approved",
        "A milestone has been approved.",
    ),
    "escrow.contributor_joined": (
        "New Contributor Joined",
        "A contributor has joined your recurring escrow cycle.",
    ),
    "invoice.paid": ("Invoice Paid", "Your invoice has been paid."),
}

_INVITE_RESPONSE_TITLES_BY_ACTION = {
    "accepted": (
        "Escrow Invitation Accepted",
        "Your counterparty accepted the escrow invitation.",
    ),
    "countered": (
        "Escrow Invitation Countered",
        "Your counterparty proposed a counter-offer for the escrow.",
    ),
    "rejected": (
        "Escrow Invitation Rejected",
        "Your counterparty rejected the escrow invitation.",
    ),
}


def _resolve_event_title_and_body(event_type: str, body: dict) -> tuple[str, str]:
    if event_type == "escrow.invite_responded":
        action = body.get("action")
        if isinstance(action, str):
            action_copy = _INVITE_RESPONSE_TITLES_BY_ACTION.get(action.strip().lower())
            if action_copy is not None:
                return action_copy

    if event_type == "dispute.opened":
        return (
            "Dispute Opened",
            "Your counterparty raised a dispute on this escrow.",
        )

    return _EVENT_TITLES.get(event_type, ("Notification", "You have a new notification."))


async def _handle_event(event_type: str, body: dict) -> None:
    """Persist a notification and publish an email trigger."""
    # Lazy import to avoid circular imports at module load
    from app.db import AsyncSessionLocal  # noqa: PLC0415
    from app.models import NotificationCreate  # noqa: PLC0415
    from app.repository import NotificationRepository  # noqa: PLC0415
    from app.service import NotificationService  # noqa: PLC0415

    resolved_user_ids = _resolve_user_ids(body)
    user_id_str = resolved_user_ids[0] if resolved_user_ids else _resolve_user_id(body)
    recipient_email = await _resolve_recipient_email(body, user_id_str)
    logger.info(
        "notification.event.received type=%s user_id=%s recipient_email=%s body_keys=%s",
        event_type,
        user_id_str,
        recipient_email,
        sorted(body.keys()),
    )

    title, notif_body = _resolve_event_title_and_body(event_type, body)

    valid_user_ids: list[uuid.UUID] = []
    for resolved_user_id in resolved_user_ids:
        try:
            valid_user_ids.append(uuid.UUID(resolved_user_id))
        except (ValueError, TypeError):
            logger.warning("Skipping in-app notification; invalid user id: %s", resolved_user_id)

    if valid_user_ids:
        async with AsyncSessionLocal() as session:
            repo = NotificationRepository(session)
            svc = NotificationService(repo)
            for user_id in valid_user_ids:
                await svc.notify(
                    NotificationCreate(
                        user_id=user_id,
                        type=event_type,
                        title=title,
                        body=notif_body,
                        metadata=body,
                    )
                )
            await session.commit()

    email_metadata = _enrich_email_metadata(event_type, body)

    if recipient_email:
        _dispatch_email_task(
            to=recipient_email,
            subject=title,
            body=notif_body,
            event=event_type,
            metadata=email_metadata,
        )
    else:
        logger.warning(
            "Skipping email dispatch for event %s: no recipient email found body=%s",
            event_type,
            body,
        )


async def start_consumer() -> None:
    while True:
        try:
            connection = await aio_pika.connect_robust(RABBITMQ_URL)
            async with connection:
                channel = await connection.channel()
                exchange = await channel.declare_exchange(
                    EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
                )
                queue = await channel.declare_queue("notification_events", durable=True)
                for routing_key in _EVENT_TITLES:
                    await queue.bind(exchange, routing_key=routing_key)

                logger.info(
                    "notification.consumer.started queue=%s routing_keys=%s",
                    "notification_events",
                    sorted(_EVENT_TITLES.keys()),
                )

                async with queue.iterator() as q_iter:
                    async for message in q_iter:
                        async with message.process():
                            try:
                                body = json.loads(message.body)
                                logger.info(
                                    "notification.consumer.message routing_key=%s message_id=%s",
                                    message.routing_key,
                                    message.message_id,
                                )
                                await _handle_event(message.routing_key, body)
                            except Exception:
                                logger.exception("Failed to handle event %s", message.routing_key)
        except Exception:
            logger.exception("Consumer error, retrying in 5s")
            await asyncio.sleep(5)
