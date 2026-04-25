"""Realtime websocket fanout for dispute events in gateway."""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections import defaultdict

import aio_pika
from fastapi import FastAPI, WebSocket

logger = logging.getLogger(__name__)

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/")
EXCHANGE_NAME = os.getenv("RABBITMQ_EXCHANGE", "ethitrust")
DISPUTE_EVENT_KEYS = (
    "dispute.message.posted",
    "dispute.evidence.added",
    "dispute.settlement.requested",
    "dispute.settled.by_parties",
    "dispute.escalated",
    "dispute.auto_escalated",
)


class RealtimeConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, dispute_id: str) -> None:
        await websocket.accept()
        self._rooms[dispute_id].add(websocket)

    def disconnect(self, websocket: WebSocket, dispute_id: str) -> None:
        connections = self._rooms.get(dispute_id)
        if not connections:
            return
        connections.discard(websocket)
        if not connections:
            self._rooms.pop(dispute_id, None)

    async def broadcast_json(self, dispute_id: str, payload: dict) -> None:
        connections = list(self._rooms.get(dispute_id, set()))
        for websocket in connections:
            try:
                await websocket.send_json(payload)
            except Exception:
                self.disconnect(websocket, dispute_id)

    def active_connections(self, dispute_id: str) -> int:
        return len(self._rooms.get(dispute_id, set()))


async def _handle_dispute_event(
    manager: RealtimeConnectionManager,
    routing_key: str,
    raw_body: bytes,
) -> None:
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("Ignoring malformed realtime event: %s", routing_key)
        return

    dispute_id = body.get("dispute_id")
    if not isinstance(dispute_id, str) or not dispute_id.strip():
        return

    await manager.broadcast_json(
        dispute_id,
        {
            "event": routing_key,
            "dispute_id": dispute_id,
            "payload": body,
        },
    )


async def start_dispute_event_consumer(app: FastAPI) -> None:
    manager: RealtimeConnectionManager = app.state.realtime_manager

    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    exchange = await channel.declare_exchange(
        EXCHANGE_NAME,
        aio_pika.ExchangeType.TOPIC,
        durable=True,
    )

    queue_name = f"gateway.dispute.realtime.{uuid.uuid4()}"
    queue = await channel.declare_queue(
        queue_name,
        durable=False,
        auto_delete=True,
        exclusive=False,
    )
    for routing_key in DISPUTE_EVENT_KEYS:
        await queue.bind(exchange, routing_key=routing_key)

    logger.info("Gateway realtime consumer started on queue=%s", queue_name)
    try:
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process(ignore_processed=True):
                    await _handle_dispute_event(
                        manager,
                        routing_key=message.routing_key,
                        raw_body=message.body,
                    )
    finally:
        await channel.close()
        await connection.close()
        logger.info("Gateway realtime consumer stopped")
