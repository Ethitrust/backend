"""Integration tests for Organization HTTP routes."""

from __future__ import annotations

from unittest.mock import AsyncMock

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
    r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    assert r.status_code == 201
    data = r.json()
    assert data["public_key"].startswith("pk_live_")
    assert data["secret_key"].startswith("sk_live_")
    # Secret key must not be empty
    assert len(data["secret_key"]) > 10
    mock_messaging.assert_awaited_once()
    args = mock_messaging.await_args.args
    assert args[0] == "organization.created"
    assert args[1]["org_id"] == data["id"]
    assert args[1]["owner_id"] == "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_create_org_returns_503_when_wallet_provisioning_fails(client, monkeypatch):
    monkeypatch.setattr(
        "app.grpc_clients.ensure_owner_wallet",
        AsyncMock(side_effect=RuntimeError("wallet unavailable")),
    )

    response = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)

    assert response.status_code == 503
    assert response.json()["detail"] == "Unable to provision organization wallet"


@pytest.mark.asyncio
async def test_duplicate_name_returns_409(client):
    await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    r2 = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_list_orgs(client):
    await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    await client.post(
        "/organization",
        json={**ORG_PAYLOAD, "name": "Beta Inc", "slug": "beta-inc"},
        headers=AUTH_HEADER,
    )
    r = await client.get("/organization", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert len(r.json()) == 2


@pytest.mark.asyncio
async def test_get_org(client):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]
    r = await client.get(f"/organization/{org_id}", headers=AUTH_HEADER)
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
async def test_org_member_with_org_read_permission_can_get_org(client, monkeypatch):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]
    member_user_id = "12121212-1212-1212-1212-121212121212"

    invite_r = await client.post(
        f"/organization/{org_id}/members",
        json={"user_id": member_user_id, "role": "member"},
        headers=AUTH_HEADER,
    )
    assert invite_r.status_code == 201

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(return_value={"user_id": member_user_id, "role": "user"}),
    )

    get_r = await client.get(f"/organization/{org_id}", headers=AUTH_HEADER)
    assert get_r.status_code == 200


@pytest.mark.asyncio
async def test_non_member_cannot_get_org(client, monkeypatch):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]
    outsider_user_id = "13131313-1313-1313-1313-131313131313"

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(return_value={"user_id": outsider_user_id, "role": "user"}),
    )

    get_r = await client.get(f"/organization/{org_id}", headers=AUTH_HEADER)
    assert get_r.status_code == 403
    detail = get_r.json()["detail"]
    assert "Missing permission" in detail or "not a member of this organization" in detail


@pytest.mark.asyncio
async def test_rotate_key_returns_new_secret(client):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]
    old_sk = create_r.json()["secret_key"]
    rotate_r = await client.post(f"/organization/{org_id}/keys/rotate", headers=AUTH_HEADER)
    assert rotate_r.status_code == 200
    new_sk = rotate_r.json()["secret_key"]
    assert new_sk != old_sk


@pytest.mark.asyncio
async def test_custom_role_creation_not_supported(client):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]

    role_r = await client.post(
        f"/organization/{org_id}/roles",
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
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]

    update_r = await client.put(
        f"/organization/{org_id}/roles/admin/permissions",
        json={"permissions": ["escrow:read:all", "escrow:deposit"]},
        headers=AUTH_HEADER,
    )
    assert update_r.status_code == 200
    permissions = sorted(update_r.json()["permissions"])
    assert permissions == ["escrow:deposit", "escrow:read:all"]


@pytest.mark.asyncio
async def test_list_roles_returns_hardcoded_system_roles(client):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]

    roles_r = await client.get(f"/organization/{org_id}/roles", headers=AUTH_HEADER)

    assert roles_r.status_code == 200
    payload = roles_r.json()
    assert {item["role"] for item in payload} == {"owner", "admin", "member"}
    assert all(item["is_system"] is True for item in payload)


@pytest.mark.asyncio
async def test_owner_can_assign_member_role(client):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]

    invite_r = await client.post(
        f"/organization/{org_id}/members",
        json={
            "user_id": "22222222-2222-2222-2222-222222222222",
            "role": "member",
        },
        headers=AUTH_HEADER,
    )
    assert invite_r.status_code == 201

    assign_r = await client.patch(
        f"/organization/{org_id}/members/22222222-2222-2222-2222-222222222222/role",
        json={"role": "admin"},
        headers=AUTH_HEADER,
    )
    assert assign_r.status_code == 200
    assert assign_r.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_admin_can_assign_member_role(client, monkeypatch):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]
    admin_user_id = "88888888-8888-8888-8888-888888888888"
    member_user_id = "99999999-9999-9999-9999-999999999999"

    admin_invite_r = await client.post(
        f"/organization/{org_id}/members",
        json={"user_id": admin_user_id, "role": "admin"},
        headers=AUTH_HEADER,
    )
    assert admin_invite_r.status_code == 201

    member_invite_r = await client.post(
        f"/organization/{org_id}/members",
        json={"user_id": member_user_id, "role": "member"},
        headers=AUTH_HEADER,
    )
    assert member_invite_r.status_code == 201

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(return_value={"user_id": admin_user_id, "role": "user"}),
    )

    assign_r = await client.patch(
        f"/organization/{org_id}/members/{member_user_id}/role",
        json={"role": "admin"},
        headers=AUTH_HEADER,
    )
    assert assign_r.status_code == 200
    assert assign_r.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_invite_member_rejects_owner_role(client):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]

    invite_r = await client.post(
        f"/organization/{org_id}/members",
        json={
            "user_id": "66666666-6666-6666-6666-666666666666",
            "role": "owner",
        },
        headers=AUTH_HEADER,
    )

    assert invite_r.status_code == 422


@pytest.mark.asyncio
async def test_owner_permission_toggle_can_restrict_admin_rotate_key(client, monkeypatch):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]
    admin_user_id = "77777777-7777-7777-7777-777777777777"

    invite_r = await client.post(
        f"/organization/{org_id}/members",
        json={"user_id": admin_user_id, "role": "admin"},
        headers=AUTH_HEADER,
    )
    assert invite_r.status_code == 201

    update_r = await client.put(
        f"/organization/{org_id}/roles/admin/permissions",
        json={"permissions": ["escrow:read:all"]},
        headers=AUTH_HEADER,
    )
    assert update_r.status_code == 200

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(return_value={"user_id": admin_user_id, "role": "user"}),
    )

    rotate_r = await client.post(f"/organization/{org_id}/keys/rotate", headers=AUTH_HEADER)
    assert rotate_r.status_code == 403
    assert "Missing permission" in rotate_r.json()["detail"]


@pytest.mark.asyncio
async def test_owner_can_get_org_wallet(client):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]

    wallet_r = await client.get(f"/organization/{org_id}/wallet", headers=AUTH_HEADER)

    assert wallet_r.status_code == 200
    data = wallet_r.json()
    assert data["org_id"] == org_id
    assert data["currency"] == "ETB"


@pytest.mark.asyncio
async def test_owner_can_get_org_wallet_balance(client):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]

    balance_r = await client.get(f"/organization/{org_id}/wallet/balance", headers=AUTH_HEADER)

    assert balance_r.status_code == 200
    data = balance_r.json()
    assert data["org_id"] == org_id
    assert data["balance"] == 100000
    assert data["locked_balance"] == 10000


@pytest.mark.asyncio
async def test_owner_can_withdraw_from_org_wallet(client):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]

    withdraw_r = await client.post(
        f"/organization/{org_id}/wallet/withdraw",
        json={"amount": 5000, "provider": "manual"},
        headers=AUTH_HEADER,
    )

    assert withdraw_r.status_code == 200
    data = withdraw_r.json()
    assert data["amount"] == 5000
    assert data["provider"] == "manual"
    assert data["new_balance"] == 95000
    assert data["reference"].startswith("org-withdraw-")


@pytest.mark.asyncio
async def test_org_admin_can_access_wallet_endpoints(client, monkeypatch):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]
    admin_user_id = "33333333-3333-3333-3333-333333333333"

    invite_r = await client.post(
        f"/organization/{org_id}/members",
        json={"user_id": admin_user_id, "role": "admin"},
        headers=AUTH_HEADER,
    )
    assert invite_r.status_code == 201

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(return_value={"user_id": admin_user_id, "role": "user"}),
    )

    wallet_r = await client.get(f"/organization/{org_id}/wallet", headers=AUTH_HEADER)
    balance_r = await client.get(
        f"/organization/{org_id}/wallet/balance",
        headers=AUTH_HEADER,
    )

    assert wallet_r.status_code == 200
    assert balance_r.status_code == 200


@pytest.mark.asyncio
async def test_org_member_cannot_access_wallet_endpoints(client, monkeypatch):
    create_r = await client.post("/organization", json=ORG_PAYLOAD, headers=AUTH_HEADER)
    org_id = create_r.json()["id"]
    member_user_id = "44444444-4444-4444-4444-444444444444"

    invite_r = await client.post(
        f"/organization/{org_id}/members",
        json={"user_id": member_user_id, "role": "member"},
        headers=AUTH_HEADER,
    )
    assert invite_r.status_code == 201

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(return_value={"user_id": member_user_id, "role": "user"}),
    )

    wallet_r = await client.get(f"/organization/{org_id}/wallet", headers=AUTH_HEADER)
    withdraw_r = await client.post(
        f"/organization/{org_id}/wallet/withdraw",
        json={"amount": 2000, "provider": "manual"},
        headers=AUTH_HEADER,
    )

    assert wallet_r.status_code == 403
    assert withdraw_r.status_code == 403
