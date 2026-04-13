"""
RabbitMQ publisher and consumer for the Escrow service.

Publishes:  escrow.created, escrow.cancelled, escrow.completed,
            milestone.delivered, milestone.approved,
            escrow.contributor_joined
Consumes:   wallet.deposit.success → retries pending escrow wallet lock
            payment.completed      → compatibility fallback for older emitters
            user.registered        → binds pending email invitations to new user_id
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import TYPE_CHECKING

import aio_pika

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
EXCHANGE_NAME = "ethitrust"
QUEUE_NAME = "escrow-service"

_connection: aio_pika.abc.AbstractRobustConnection | None = None
_channel: aio_pika.abc.AbstractChannel | None = None
_exchange: aio_pika.abc.AbstractExchange | None = None


async def _get_exchange() -> aio_pika.abc.AbstractExchange:
    global _connection, _channel, _exchange
    if _exchange is None:
        _connection = await aio_pika.connect_robust(RABBITMQ_URL)
        _channel = await _connection.channel()
        _exchange = await _channel.declare_exchange(
            EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
        )
    return _exchange


async def publish(routing_key: str, payload: dict) -> None:
    """Publish a JSON message to the ethitrust topic exchange."""
    try:
        exchange = await _get_exchange()
        message = aio_pika.Message(
            body=json.dumps(payload, default=str).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await exchange.publish(message, routing_key=routing_key)
        logger.debug("Published %s: %s", routing_key, payload)
    except Exception:
        logger.exception("Failed to publish message %s", routing_key)


async def handle_event(key: str, data: dict) -> None:
    """
    Process an incoming event from the message broker.

    Funding events trigger pending-escrow lock retries for the funded buyer.
    """
    if key == "user.registered":
        user_id_raw = data.get("user_id")
        user_email = data.get("email")
        if not user_id_raw or not isinstance(user_email, str) or not user_email.strip():
            logger.info("%s ignored; user_id/email missing", key)
            return

        try:
            user_id = uuid.UUID(str(user_id_raw))
        except ValueError:
            logger.warning("%s ignored; invalid user_id=%s", key, user_id_raw)
            return

        from app.db import async_session_factory  # noqa: PLC0415
        from app.repository import EscrowRepository  # noqa: PLC0415
        from app.service import EscrowService  # noqa: PLC0415

        async with async_session_factory() as session:
            repo = EscrowRepository(session)
            service = EscrowService(repo)
            associated = await service.associate_pending_invitations_for_user_email(
                user_id=user_id,
                user_email=user_email,
            )
            logger.info(
                "Processed %s for user=%s email=%s associated_pending_invitations=%s",
                key,
                user_id,
                user_email,
                associated,
            )
        return

    if key not in {"wallet.deposit.success", "payment.completed"}:
        return

    user_id_raw = data.get("user_id")
    if user_id_raw is None and isinstance(data.get("metadata"), dict):
        user_id_raw = data["metadata"].get("user_id")

    transaction_ref = data.get("transaction_ref") or data.get("reference")
    if not user_id_raw:
        logger.info(
            "%s ignored for escrow activation; user_id missing (ref=%s)",
            key,
            transaction_ref,
        )
        return

    try:
        buyer_id = uuid.UUID(str(user_id_raw))
    except ValueError:
        logger.warning("%s ignored; invalid user_id=%s", key, user_id_raw)
        return

    from app.db import async_session_factory  # noqa: PLC0415
    from app.repository import EscrowRepository  # noqa: PLC0415
    from app.service import EscrowService  # noqa: PLC0415

    async with async_session_factory() as session:
        repo = EscrowRepository(session)
        service = EscrowService(repo)
        activated = await service.activate_pending_escrows_for_buyer(
            buyer_id=buyer_id,
            trigger_reference=str(transaction_ref) if transaction_ref else None,
        )
        logger.info(
            "Processed %s for buyer=%s ref=%s activated_pending_escrows=%s",
            key,
            buyer_id,
            transaction_ref,
            activated,
        )


async def start_consumer() -> None:
    """Start long-running RabbitMQ consumer for payment events."""
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=10)
        exchange = await channel.declare_exchange(
            EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
        )
        queue = await channel.declare_queue(QUEUE_NAME, durable=True)
        await queue.bind(exchange, routing_key="wallet.deposit.success")
        await queue.bind(exchange, routing_key="payment.#")
        await queue.bind(exchange, routing_key="user.registered")

        logger.info("Escrow consumer started, listening on queue '%s'", QUEUE_NAME)
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    try:
                        body = json.loads(message.body)
                        routing_key = message.routing_key or ""
                        await handle_event(routing_key, body)
                    except Exception:
                        logger.exception("Error handling message with key=%s", message.routing_key)
