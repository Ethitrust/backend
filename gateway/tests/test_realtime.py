from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

try:
    from gateway.app.realtime import RealtimeConnectionManager, _handle_dispute_event
except ModuleNotFoundError:
    from app.realtime import (  # type: ignore[no-redef]
        RealtimeConnectionManager,
        _handle_dispute_event,
    )


@pytest.mark.asyncio
async def test_realtime_manager_broadcasts_to_room() -> None:
    manager = RealtimeConnectionManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    ws1.send_json = AsyncMock()
    ws2.send_json = AsyncMock()

    # Bypass websocket.accept contract for unit test by injecting room members directly.
    manager._rooms["d-1"].update({ws1, ws2})  # noqa: SLF001

    payload = {"event": "dispute.message.posted", "dispute_id": "d-1", "payload": {}}
    await manager.broadcast_json("d-1", payload)

    ws1.send_json.assert_awaited_once_with(payload)
    ws2.send_json.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_handle_dispute_event_ignores_invalid_payload() -> None:
    manager = RealtimeConnectionManager()
    manager.broadcast_json = AsyncMock()

    await _handle_dispute_event(manager, "dispute.message.posted", b"not-json")
    manager.broadcast_json.assert_not_called()


@pytest.mark.asyncio
async def test_handle_dispute_event_fanout() -> None:
    manager = RealtimeConnectionManager()
    manager.broadcast_json = AsyncMock()

    await _handle_dispute_event(
        manager,
        "dispute.message.posted",
        b'{"dispute_id":"abc-123","message":"hello"}',
    )

    manager.broadcast_json.assert_awaited_once()
    args, kwargs = manager.broadcast_json.await_args
    assert args[0] == "abc-123"
    assert kwargs == {}
    assert args[1]["event"] == "dispute.message.posted"
    assert args[1]["dispute_id"] == "abc-123"
    assert args[1]["payload"]["message"] == "hello"
