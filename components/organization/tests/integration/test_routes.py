"""Integration tests for Organization HTTP routes."""

from __future__ import annotations

import pytest

AUTH_HEADER = {"Authorization": "Bearer test-token"}

ORG_PAYLOAD = {
    "name": "Acme Corp",
    "slug": "acme-corp",
}


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "organization"


@pytest.mark.asyncio
async def test_create_org(client, mock_messaging):
    r = await client.post("/organizations", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    assert r.status_code == 201
    data = r.json()
    assert data["public_key"].startswith("pk_test_")
    assert data["secret_key"].startswith("sk_test_")
    # Secret key must not be empty
    assert len(data["secret_key"]) > 10
    mock_messaging.assert_awaited_once()
    args = mock_messaging.await_args.args
    assert args[0] == "organization.created"
    assert args[1]["org_id"] == data["id"]
    assert args[1]["owner_id"] == "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_duplicate_name_returns_409(client):
    await client.post("/organizations", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    r2 = await client.post("/organizations", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_list_orgs(client):
    await client.post("/organizations", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    await client.post(
        "/organizations",
        json={**ORG_PAYLOAD, "name": "Beta Inc", "slug": "beta-inc"},
        headers=AUTH_HEADER,
    )
    r = await client.get("/organizations", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert len(r.json()) == 2


@pytest.mark.asyncio
async def test_get_org(client):
    create_r = await client.post("/organizations", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]
    r = await client.get(f"/organizations/{org_id}", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert r.json()["status"] in {
        "pending_verification",
        "active",
        "suspended",
        "deactivated",
    }
    # Secret key NOT returned on GET
    assert "secret_key" not in r.json()


@pytest.mark.asyncio
async def test_rotate_key_returns_new_secret(client):
    create_r = await client.post("/organizations", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]
    old_sk = create_r.json()["secret_key"]
    rotate_r = await client.post(f"/organizations/{org_id}/keys/rotate", headers=AUTH_HEADER)
    assert rotate_r.status_code == 200
    new_sk = rotate_r.json()["secret_key"]
    assert new_sk != old_sk


@pytest.mark.asyncio
async def test_custom_role_creation_not_supported(client):
    create_r = await client.post("/organizations", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]

    role_r = await client.post(
        f"/organizations/{org_id}/roles",
        json={
            "name": "ops_agent",
            "description": "Operations member",
            "permissions": ["escrow.view", "escrow.accept"],
        },
        headers=AUTH_HEADER,
    )
    assert role_r.status_code == 405


@pytest.mark.asyncio
async def test_owner_can_update_system_role_permissions(client):
    create_r = await client.post("/organizations", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]

    update_r = await client.put(
        f"/organizations/{org_id}/roles/admin/permissions",
        json={"permissions": ["escrow.view", "escrow.create"]},
        headers=AUTH_HEADER,
    )
    assert update_r.status_code == 200
    permissions = sorted(update_r.json()["permissions"])
    assert permissions == ["escrow.create", "escrow.view"]


@pytest.mark.asyncio
async def test_owner_can_assign_member_role(client):
    create_r = await client.post("/organizations", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]

    invite_r = await client.post(
        f"/organizations/{org_id}/members",
        json={
            "user_id": "22222222-2222-2222-2222-222222222222",
            "role": "member",
        },
        headers=AUTH_HEADER,
    )
    assert invite_r.status_code == 201

    assign_r = await client.patch(
        f"/organizations/{org_id}/members/22222222-2222-2222-2222-222222222222/role",
        json={"role": "admin"},
        headers=AUTH_HEADER,
    )
    assert assign_r.status_code == 200
    assert assign_r.json()["role"] == "admin"
