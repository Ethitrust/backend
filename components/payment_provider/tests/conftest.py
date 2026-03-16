"""Test fixtures for the Payment Provider service.

No database — the service is stateless, so we only override HTTP calls via
respx (or unittest.mock) and skip gRPC / RabbitMQ fixtures.
"""

from __future__ import annotations

import pytest
from app.main import app
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
