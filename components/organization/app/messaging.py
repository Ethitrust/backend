"""RabbitMQ publishing helpers for Organization service events."""

from __future__ import annotations

import json
import os

import aio_pika

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
EXCHANGE_NAME = "ethitrust"


async def publish(routing_key: str, payload: dict) -> None:
    """Publish an event to the shared Ethitrust topic exchange."""
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            EXCHANGE_NAME,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        await exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode(),
                content_type="application/json",
            ),
            routing_key=routing_key,
        )
