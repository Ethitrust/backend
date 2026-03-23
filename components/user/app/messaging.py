"""RabbitMQ publisher/consumer for the User service."""

from __future__ import annotations

import json
import logging
import os
import uuid

import aio_pika
from sqlalchemy import select

from app.db import AsyncSessionLocal, User

logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
EXCHANGE_NAME = "ethitrust"
QUEUE_NAME = "user-service-queue"
ROUTING_KEYS = ["user.kyc_updated"]

_connection: aio_pika.abc.AbstractRobustConnection | None = None
_channel: aio_pika.abc.AbstractChannel | None = None
_exchange: aio_pika.abc.AbstractExchange | None = None


async def _get_exchange() -> aio_pika.abc.AbstractExchange:
    global _connection, _channel, _exchange
    if _exchange is None:
        _connection = await aio_pika.connect_robust(RABBITMQ_URL)
        _channel = await _connection.channel()
        _exchange = await _channel.declare_exchange(
            EXCHANGE_NAME,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
    return _exchange


async def publish(routing_key: str, payload: dict) -> None:
    """Publish a JSON event to the ethitrust topic exchange."""
    try:
        exchange = await _get_exchange()
        message = aio_pika.Message(
            body=json.dumps(payload).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await exchange.publish(message, routing_key=routing_key)
        logger.debug("Published %s: %s", routing_key, payload)
    except Exception:
        logger.exception("Failed to publish message %s", routing_key)


async def _handle_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
    async with message.process(requeue=False):
        try:
            body = json.loads(message.body)
            routing_key = message.routing_key
            logger.info("Received event %s: %s", routing_key, body)

            if routing_key == "user.kyc_updated":
                user_id = uuid.UUID(body["user_id"])
                kyc_level = int(body["kyc_level"])
                async with AsyncSessionLocal() as session:
                    result = await session.execute(
                        select(User).where(User.id == user_id)
                    )
                    user = result.scalar_one_or_none()
                    if user:
                        user.kyc_level = kyc_level
                        session.add(user)
                        await session.commit()
                        logger.info(
                            "Updated kyc_level=%s for user %s", kyc_level, user_id
                        )
                    else:
                        logger.warning("kyc_updated: user %s not found", user_id)

        except Exception:
            logger.exception("Error processing message %s", message.routing_key)


async def start_consumer() -> None:
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=10)

        exchange = await channel.declare_exchange(
            EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
        )
        queue = await channel.declare_queue(QUEUE_NAME, durable=True)

        for rk in ROUTING_KEYS:
            await queue.bind(exchange, routing_key=rk)

        logger.info("User consumer started. Listening for: %s", ROUTING_KEYS)
        await queue.consume(_handle_message)

        import asyncio

        await asyncio.Future()  # run forever until cancelled
