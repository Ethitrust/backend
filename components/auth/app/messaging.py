"""
RabbitMQ publisher and consumer for the Auth service.

The Auth service primarily publishes events; it optionally consumes auth.*
events for internal fanout (e.g., invalidation patterns).
"""

from __future__ import annotations

import json
import logging
import os

import aio_pika

logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
EXCHANGE_NAME = "ethitrust"

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
        logger.info(
            "rabbitmq.publish.attempt routing_key=%s payload_keys=%s",
            routing_key,
            sorted(payload.keys()),
        )
        exchange = await _get_exchange()
        message = aio_pika.Message(
            body=json.dumps(payload).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await exchange.publish(message, routing_key=routing_key)
        logger.info(
            "rabbitmq.publish.success routing_key=%s payload_email=%s payload_user_id=%s",
            routing_key,
            payload.get("email"),
            payload.get("user_id"),
        )
    except Exception:
        logger.exception("Failed to publish message %s", routing_key)


async def start_consumer() -> None:
    """Optional consumer for auth.* self-events (e.g., audit logging)."""
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=10)
        exchange = await channel.declare_exchange(
            EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
        )
        queue = await channel.declare_queue("auth-self-queue", durable=True)
        await queue.bind(exchange, routing_key="auth.*")

        logger.info("Auth consumer started — listening for auth.* events")

        async with queue.iterator() as it:
            async for message in it:
                async with message.process():
                    logger.info(
                        "Auth self-event [%s]: %s",
                        message.routing_key,
                        message.body.decode(),
                    )
