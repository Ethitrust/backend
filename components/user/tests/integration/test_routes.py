"""Integration tests for User service REST routes."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

FIXED_UUID = uuid.UUID(int=0)
TOKEN = "Bearer valid.token.here"


@pytest.mark.asyncio
async def test_get_me_returns_200(client, mock_user):
    """GET /users/me returns 200 with a valid user in DB."""
    await mock_user(email="me@example.com", user_id=FIXED_UUID)

    with patch(
        "app.grpc_clients.validate_token",
        new_callable=AsyncMock,
        return_value={
            "user_id": str(FIXED_UUID),
            "role": "user",
            "is_verified": True,
            "is_banned": False,
        },
    ):
        response = await client.get("/users/me", headers={"Authorization": TOKEN})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "me@example.com"
    assert body["id"] == str(FIXED_UUID)


@pytest.mark.asyncio
async def test_get_me_unauthorized_without_token(client):
    """GET /users/me returns 401 when Authorization header is missing."""
    response = await client.get("/users/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_patch_me_updates_name(client, mock_user):
    """PATCH /users/me updates first_name and last_name."""
    await mock_user(email="patch@example.com", user_id=FIXED_UUID)

    with patch(
        "app.grpc_clients.validate_token",
        new_callable=AsyncMock,
        return_value={
            "user_id": str(FIXED_UUID),
            "role": "user",
            "is_verified": True,
            "is_banned": False,
        },
    ):
        response = await client.patch(
            "/users/me",
            json={"first_name": "Updated", "last_name": "Name"},
            headers={"Authorization": TOKEN},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["first_name"] == "Updated"
    assert body["last_name"] == "Name"


@pytest.mark.asyncio
async def test_get_user_by_id(client, mock_user):
    """GET /users/{user_id} returns the user for admin access."""
    await mock_user(email="admin@example.com", user_id=FIXED_UUID)

    with patch(
        "app.grpc_clients.validate_token",
        new_callable=AsyncMock,
        return_value={
            "user_id": str(FIXED_UUID),
            "role": "admin",
            "is_verified": True,
            "is_banned": False,
        },
    ):
        response = await client.get(
            f"/users/{FIXED_UUID}",
            headers={"Authorization": TOKEN},
        )

    assert response.status_code == 200
    assert response.json()["id"] == str(FIXED_UUID)
