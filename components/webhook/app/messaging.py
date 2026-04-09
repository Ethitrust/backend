import json
import logging
import os

import aio_pika

logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
EXCHANGE_NAME = "ethitrust"


async def publish(routing_key: str, payload: dict) -> None:
    """Publish a message to the topic exchange."""
    try:
        conn = await aio_pika.connect_robust(RABBITMQ_URL)
        async with conn:
            channel = await conn.channel()
            exchange = await channel.declare_exchange(
                EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
            )
            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(payload).encode(),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=routing_key,
            )
    except Exception as exc:
        logger.error("Failed to publish %s: %s", routing_key, exc)
        raise


async def start_consumer() -> None:
    """Listen for webhook.outgoing events to deliver to org endpoints."""
    conn = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await conn.channel()
    await channel.set_qos(prefetch_count=5)
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )
    queue = await channel.declare_queue("webhook.outgoing_delivery", durable=True)
    await queue.bind(exchange, routing_key="webhook.outgoing")

    logger.info("Webhook outgoing consumer started, waiting for messages…")
    async with queue.iterator() as messages:
        async for msg in messages:
            async with msg.process():
                try:
                    data = json.loads(msg.body)
                    logger.info(
                        "Delivering outgoing webhook for event=%s org_id=%s",
                        data.get("event_type"),
                        data.get("org_id"),
                    )
                    # In production: lookup org webhook_url + secret, call deliver_webhook
                    # or enqueue Celery task deliver_webhook.delay(...)
                except Exception as exc:
                    logger.exception("Webhook outgoing delivery failed: %s", exc)
