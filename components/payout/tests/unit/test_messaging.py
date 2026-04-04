"""Unit tests for payout messaging consumer behavior."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from app import messaging


class _FakeMessage:
    def __init__(self, routing_key: str, body: dict):
        self.routing_key = routing_key
        self.body = json.dumps(body).encode()

    @asynccontextmanager
    async def process(self, requeue: bool = False):
        yield


@pytest.mark.asyncio
async def test_handle_message_dispatches_payout_requested(monkeypatch):
    handler = AsyncMock()
    monkeypatch.setattr(messaging, "_handle_payout_requested", handler)

    msg = _FakeMessage(
        routing_key="payout.requested",
        body={"payout_id": "11111111-1111-1111-1111-111111111111"},
    )

    await messaging._handle_message(msg)

    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_message_ignores_unknown_routing_key(monkeypatch):
    handler = AsyncMock()
    monkeypatch.setattr(messaging, "_handle_payout_requested", handler)

    msg = _FakeMessage(routing_key="something.else", body={"hello": "world"})

    await messaging._handle_message(msg)

    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_payout_requested_invalid_uuid_is_safe():
    await messaging._handle_payout_requested({"payout_id": "not-a-uuid"})
