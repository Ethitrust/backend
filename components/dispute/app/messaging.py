"""RabbitMQ messaging for the Dispute service."""

from __future__ import annotations

import json
import logging
import os

import aio_pika

logger = logging.getLogger(__name__)
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
EXCHANGE_NAME = "ethitrust"


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


async def start_consumer() -> None:
    import asyncio  # noqa: PLC0415

    logger.info("Dispute consumer started (no subscriptions)")
    await asyncio.Future()
