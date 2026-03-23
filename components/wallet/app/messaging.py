"""
RabbitMQ consumer for the Wallet service.

Listens to the ``ethitrust`` topic exchange for:
  - ``payment.completed``  → credit the wallet with the paid amount.
  - ``user.registered``    → auto-create an ETB wallet for the new user.
    - ``organization.created`` → auto-create an ETB wallet for the new organization.
"""

from __future__ import annotations

import json
import logging
import os
import uuid

import aio_pika

from app.db import AsyncSessionLocal
from app.repository import WalletRepository
from app.service import WalletService

logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
EXCHANGE_NAME = "ethitrust"
QUEUE_NAME = "wallet-service-queue"
ROUTING_KEYS = ["payment.completed", "user.registered", "organization.created"]


async def _handle_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
    async with message.process(requeue=False):
        try:
            body = json.loads(message.body)
            routing_key = message.routing_key
            logger.info("Received event %s: %s", routing_key, body)

            if routing_key == "payment.completed":
                await _handle_payment_completed(body)

            elif routing_key == "user.registered":
                await _handle_user_registered(body)

            elif routing_key == "organization.created":
                await _handle_organization_created(body)

        except Exception:
            logger.exception("Error processing message %s", message.routing_key)


async def _handle_payment_completed(body: dict) -> None:
    """Credit the wallet indicated in the payment metadata."""
    wallet_id_str = body.get("wallet_id") or body.get("metadata", {}).get("wallet_id")
    reference = body.get("reference") or body.get("transaction_ref")
    amount = int(body.get("amount", 0))
    currency = body.get("currency", "ETB")

    if not wallet_id_str or not reference or amount <= 0:
        logger.warning("payment.completed: missing required fields — body=%s", body)
        return

    try:
        wallet_id = uuid.UUID(wallet_id_str)
    except ValueError:
        logger.error("payment.completed: invalid wallet_id=%s", wallet_id_str)
        return

    async with AsyncSessionLocal() as session:
        repo = WalletRepository(session)
        svc = WalletService(repo)
        try:
            tx = await svc.fund_wallet(wallet_id, amount, reference, currency)
            await session.commit()
            logger.info(
                "Wallet %s funded: amount=%s ref=%s tx=%s",
                wallet_id,
                amount,
                reference,
                tx.id,
            )
        except Exception:
            await session.rollback()
            logger.exception("Failed to fund wallet %s", wallet_id)


async def _handle_user_registered(body: dict) -> None:
    """Auto-create an ETB wallet for every new user."""
    user_id_str = body.get("user_id")
    if not user_id_str:
        logger.warning("user.registered: missing user_id — body=%s", body)
        return

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        logger.error("user.registered: invalid user_id=%s", user_id_str)
        return

    async with AsyncSessionLocal() as session:
        repo = WalletRepository(session)
        svc = WalletService(repo)
        try:
            wallet = await svc.create_wallet(user_id, "ETB")
            await session.commit()
            logger.info("Auto-created ETB wallet %s for user %s", wallet.id, user_id)
        except Exception:
            await session.rollback()
            # Wallet may already exist — log warning but don't crash
            logger.warning("Could not auto-create ETB wallet for user %s", user_id)


async def _handle_organization_created(body: dict) -> None:
    """Auto-create an ETB wallet for every new organization."""
    org_id_str = body.get("org_id")
    if not org_id_str:
        logger.warning("organization.created: missing org_id — body=%s", body)
        return

    try:
        org_id = uuid.UUID(org_id_str)
    except ValueError:
        logger.error("organization.created: invalid org_id=%s", org_id_str)
        return

    async with AsyncSessionLocal() as session:
        repo = WalletRepository(session)
        svc = WalletService(repo)
        try:
            wallet = await svc.create_wallet(org_id, "ETB")
            await session.commit()
            logger.info(
                "Auto-created ETB wallet %s for organization %s", wallet.id, org_id
            )
        except Exception:
            await session.rollback()
            # Wallet may already exist — log warning but don't crash
            logger.warning(
                "Could not auto-create ETB wallet for organization %s", org_id
            )


async def publish(routing_key: str, body: dict) -> None:
    """Publish an event to the ethitrust exchange.

    Lightweight helper used internally and in integration tests.
    """
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
            ),
            routing_key=routing_key,
        )


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

        logger.info("Wallet consumer started. Listening for: %s", ROUTING_KEYS)
        await queue.consume(_handle_message)

        import asyncio  # noqa: PLC0415

        await asyncio.Future()  # run forever
