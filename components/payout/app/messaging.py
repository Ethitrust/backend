"""RabbitMQ messaging for the Payout service."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid

import aio_pika

logger = logging.getLogger(__name__)
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
EXCHANGE_NAME = "ethitrust"
QUEUE_NAME = "payout-service-events"
ROUTING_KEYS = ["payout.requested"]


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
            logger.info("Published event %s", routing_key)
    except Exception:
        logger.exception("Failed to publish event %s", routing_key)


async def _handle_payout_requested(body: dict) -> None:
    payout_id_raw = body.get("payout_id")
    if not isinstance(payout_id_raw, str) or not payout_id_raw.strip():
        logger.warning("payout.requested missing payout_id: body=%s", body)
        return

    try:
        payout_id = uuid.UUID(payout_id_raw)
    except ValueError:
        logger.error("payout.requested invalid payout_id=%s", payout_id_raw)
        return

    # Lazy imports avoid circular imports at module load.
    from app.db import AsyncSessionLocal  # noqa: PLC0415
    from app.repository import PayoutRepository  # noqa: PLC0415
    from app.service import PayoutService  # noqa: PLC0415

    async with AsyncSessionLocal() as session:
        repo = PayoutRepository(session)
        svc = PayoutService(repo)
        try:
            payout = await svc.process_bank_transfer(payout_id)
            await session.commit()
            logger.info(
                "Processed payout.requested payout_id=%s status=%s provider=%s",
                payout_id,
                payout.status,
                payout.provider,
            )
        except Exception:
            await session.rollback()
            logger.exception(
                "Failed processing payout.requested payout_id=%s", payout_id
            )


async def _handle_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
    async with message.process(requeue=False):
        try:
            body = json.loads(message.body)
            routing_key = message.routing_key
            logger.info("Received event %s", routing_key)

            if routing_key == "payout.requested":
                await _handle_payout_requested(body)
            else:
                logger.debug("Ignoring unmatched routing key: %s", routing_key)
        except Exception:
            logger.exception("Error handling message %s", message.routing_key)


async def start_consumer() -> None:
    """Consume payout events and execute async transfer processing."""
    while True:
        try:
            connection = await aio_pika.connect_robust(RABBITMQ_URL)
            async with connection:
                channel = await connection.channel()
                await channel.set_qos(prefetch_count=10)

                exchange = await channel.declare_exchange(
                    EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
                )
                queue = await channel.declare_queue(QUEUE_NAME, durable=True)
                for routing_key in ROUTING_KEYS:
                    await queue.bind(exchange, routing_key=routing_key)

                logger.info(
                    "Payout consumer started queue=%s routing_keys=%s",
                    QUEUE_NAME,
                    ROUTING_KEYS,
                )

                await queue.consume(_handle_message)
                await asyncio.Future()
        except Exception:
            logger.exception("Payout consumer error; retrying in 5 seconds")
            await asyncio.sleep(5)
