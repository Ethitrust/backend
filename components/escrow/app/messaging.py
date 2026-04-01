"""
RabbitMQ publisher and consumer for the Escrow service.

Publishes:  escrow.created, escrow.cancelled, escrow.completed,
            milestone.delivered, milestone.approved,
            escrow.contributor_joined
Consumes:   payment.completed  → ignored for escrow activation (wallet-topup flow)
"""

from __future__ import annotations

import json
import logging
import os
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

    payment.completed is ignored for escrow activation.
    """
    if key == "payment.completed":
        transaction_ref = data.get("transaction_ref") or data.get("reference")
        logger.info(
            "Ignoring payment.completed for escrow activation (ref=%s)",
            transaction_ref,
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
        await queue.bind(exchange, routing_key="payment.#")

        logger.info("Escrow consumer started, listening on queue '%s'", QUEUE_NAME)
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    try:
                        body = json.loads(message.body)
                        routing_key = message.routing_key or ""
                        await handle_event(routing_key, body)
                    except Exception:
                        logger.exception(
                            "Error handling message with key=%s", message.routing_key
                        )
