"""
Integration tests for Escrow service HTTP routes.
Uses in-memory SQLite via ASGI transport (no live server required).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app import api as escrow_api

AUTH_HEADER = {"Authorization": "Bearer test-token"}
RECEIVER_HEADER = {"Authorization": "Bearer receiver-token"}
OUTSIDER_HEADER = {"Authorization": "Bearer outsider-token"}
ORG_KEY_HEADER = {"Authorization": "Bearer sk_test_org_key"}


# ─── POST /escrow (onetime) ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_onetime_escrow(client):
    """POST /escrow creates invitation-first escrow (no immediate checkout)."""
    payload = {
        "escrow_type": "onetime",
        "title": "Buy gaming laptop",
        "currency": "ETB",
        "amount": 500_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    response = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert response.status_code == 201, response.text
    data = response.json()
    assert "escrow" in data
    assert "payment_url" in data
    assert data["payment_url"] is None
    assert data["escrow"]["escrow_type"] == "onetime"
    assert data["escrow"]["status"] == "invited"
    assert data["escrow"]["currency"] == "ETB"
    assert data["escrow"]["amount"] == 500_000


@pytest.mark.asyncio
async def test_create_onetime_escrow_rejects_low_kyc_outside_development(
    client,
    monkeypatch,
):
    monkeypatch.setattr(escrow_api, "IS_DEVELOPMENT", False)
    monkeypatch.setattr(escrow_api, "KYC_MIN_LEVEL", 1)
    monkeypatch.setattr(
        "app.grpc_clients.get_user_by_id",
        AsyncMock(
            return_value={
                "user_id": "11111111-1111-4111-8111-11111111111a",
                "email": "initiator@example.com",
                "role": "user",
                "is_verified": True,
                "is_banned": False,
                "kyc_level": 0,
            }
        ),
    )

    payload = {
        "escrow_type": "onetime",
        "title": "Blocked by KYC",
        "currency": "ETB",
        "amount": 500_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    response = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_onetime_escrow_allows_low_kyc_in_development(
    client,
    monkeypatch,
):
    monkeypatch.setattr(escrow_api, "IS_DEVELOPMENT", True)
    monkeypatch.setattr(escrow_api, "KYC_MIN_LEVEL", 1)
    monkeypatch.setattr(
        "app.grpc_clients.get_user_by_id",
        AsyncMock(
            return_value={
                "user_id": "11111111-1111-4111-8111-11111111111a",
                "email": "initiator@example.com",
                "role": "user",
                "is_verified": True,
                "is_banned": False,
                "kyc_level": 0,
            }
        ),
    )

    payload = {
        "escrow_type": "onetime",
        "title": "Allowed in dev",
        "currency": "ETB",
        "amount": 500_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    response = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert response.status_code == 201, response.text


# ─── POST /escrow (milestone) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_milestone_escrow(client):
    """POST /escrow with escrow_type=milestone should create escrow + milestones."""
    payload = {
        "escrow_type": "milestone",
        "title": "Build e-commerce site",
        "currency": "ETB",
        "amount": 450_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
        "milestones": [
            {"title": "Design wireframes", "amount": 100_000},
            {"title": "Backend development", "amount": 200_000},
            {"title": "Frontend & launch", "amount": 150_000},
        ],
    }
    response = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["escrow"]["escrow_type"] == "milestone"
    assert data["payment_url"] is None
    # total amount is sum of milestones
    assert data["escrow"]["amount"] == 450_000


@pytest.mark.asyncio
async def test_create_milestone_escrow_amount_mismatch_returns_422(client):
    payload = {
        "escrow_type": "milestone",
        "title": "Build e-commerce site",
        "currency": "ETB",
        "amount": 10_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
        "milestones": [
            {"title": "Design wireframes", "amount": 100_000},
            {"title": "Backend development", "amount": 200_000},
        ],
    }
    response = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert response.status_code == 422


# ─── GET /escrow ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_escrows_empty(client):
    """GET /escrow returns paginated empty list for new user."""
    response = await client.get("/escrow", headers=AUTH_HEADER)
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_list_escrows_returns_created(client):
    """GET /escrow should list escrows created by the user."""
    # Create an escrow first
    payload = {
        "escrow_type": "onetime",
        "title": "Design logo",
        "currency": "USD",
        "amount": 50_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201

    list_resp = await client.get("/escrow", headers=AUTH_HEADER)
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["total"] >= 1
    assert any(e["title"] == "Design logo" for e in data["items"])


@pytest.mark.asyncio
async def test_list_escrows_includes_email_invitations_for_invited_user(client):
    """Invited users should see email-invited escrows before accepting."""
    payload = {
        "escrow_type": "onetime",
        "title": "Email Invite Visibility",
        "currency": "USD",
        "amount": 77_000,
        "initiator_role": "buyer",
        "receiver_email": "receiver@example.com",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201

    list_resp = await client.get("/escrow", headers=RECEIVER_HEADER)
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert any(e["title"] == "Email Invite Visibility" for e in data["items"])


# ─── GET /escrow/{id} ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_escrow_detail(client):
    """GET /escrow/{id} returns full escrow detail."""
    payload = {
        "escrow_type": "onetime",
        "title": "Photography session",
        "currency": "ETB",
        "amount": 80_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201
    escrow_id = create_resp.json()["escrow"]["id"]

    detail_resp = await client.get(f"/escrow/{escrow_id}", headers=AUTH_HEADER)
    assert detail_resp.status_code == 200
    data = detail_resp.json()
    assert data["id"] == escrow_id
    assert data["title"] == "Photography session"


@pytest.mark.asyncio
async def test_get_escrow_detail_allows_email_invited_user(client):
    """Email-invited users should be able to retrieve escrow detail before acceptance."""
    payload = {
        "escrow_type": "onetime",
        "title": "Invited Detail Access",
        "currency": "ETB",
        "amount": 81_000,
        "initiator_role": "buyer",
        "receiver_email": "receiver@example.com",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201
    escrow_id = create_resp.json()["escrow"]["id"]

    detail_resp = await client.get(f"/escrow/{escrow_id}", headers=RECEIVER_HEADER)
    assert detail_resp.status_code == 200
    data = detail_resp.json()
    assert data["id"] == escrow_id
    assert data["title"] == "Invited Detail Access"


@pytest.mark.asyncio
async def test_get_escrow_not_found(client):
    """GET /escrow/{id} with unknown ID returns 404."""
    fake_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    response = await client.get(f"/escrow/{fake_id}", headers=AUTH_HEADER)
    assert response.status_code == 404


# ─── POST /escrow/{id}/cancel ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_escrow(client):
    """POST /escrow/{id}/cancel transitions escrow to cancelled."""
    payload = {
        "escrow_type": "onetime",
        "title": "Cancel me",
        "currency": "ETB",
        "amount": 20_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201
    escrow_id = create_resp.json()["escrow"]["id"]

    cancel_resp = await client.post(f"/escrow/{escrow_id}/cancel", headers=AUTH_HEADER)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_accept_invitation_transitions_to_active_when_wallet_lock_succeeds(
    client,
):
    """Receiver acceptance should lock buyer funds and activate escrow immediately."""
    payload = {
        "escrow_type": "onetime",
        "title": "Invite acceptance",
        "currency": "ETB",
        "amount": 25_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201
    escrow_id = create_resp.json()["escrow"]["id"]

    accept_resp = await client.post(
        f"/escrow/{escrow_id}/accept",
        json={},
        headers=RECEIVER_HEADER,
    )
    assert accept_resp.status_code == 200, accept_resp.text
    data = accept_resp.json()
    assert data["escrow"]["status"] == "active"
    assert data["payment_url"] is None


@pytest.mark.asyncio
async def test_accept_invitation_forbidden_for_initiator(client):
    payload = {
        "escrow_type": "onetime",
        "title": "Initiator should not accept",
        "currency": "ETB",
        "amount": 25_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201
    escrow_id = create_resp.json()["escrow"]["id"]

    accept_resp = await client.post(
        f"/escrow/{escrow_id}/accept",
        json={},
        headers=AUTH_HEADER,
    )
    assert accept_resp.status_code == 403


@pytest.mark.asyncio
async def test_reject_invitation_forbidden_for_initiator(client):
    payload = {
        "escrow_type": "onetime",
        "title": "Initiator should not reject",
        "currency": "ETB",
        "amount": 25_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201
    escrow_id = create_resp.json()["escrow"]["id"]

    reject_resp = await client.post(
        f"/escrow/{escrow_id}/reject",
        json={},
        headers=AUTH_HEADER,
    )
    assert reject_resp.status_code == 403


@pytest.mark.asyncio
async def test_counter_invitation_increments_offer_version(client):
    payload = {
        "escrow_type": "onetime",
        "title": "Counter me",
        "currency": "ETB",
        "amount": 70_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201
    created = create_resp.json()["escrow"]
    escrow_id = created["id"]
    version_before = created["offer_version"]

    counter_resp = await client.post(
        f"/escrow/{escrow_id}/counter",
        json={"amount": 75_000, "description": "Please update terms"},
        headers=RECEIVER_HEADER,
    )
    assert counter_resp.status_code == 200, counter_resp.text
    data = counter_resp.json()
    assert data["amount"] == 75_000
    assert data["offer_version"] == version_before + 1
    assert data["status"] == "counter_pending_counterparty"
    assert data["counter_status"] == "awaiting_initiator"
    assert data["last_countered_by_id"] == "22222222-2222-4222-8222-22222222222b"
    assert len(data["counter_history"]) == 1
    assert data["counter_history"][0]["status"] == "pending_response"


@pytest.mark.asyncio
async def test_counter_history_updates_when_counter_offer_is_accepted(client):
    payload = {
        "escrow_type": "onetime",
        "title": "Negotiation history",
        "currency": "ETB",
        "amount": 40_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201
    escrow_id = create_resp.json()["escrow"]["id"]

    counter_resp = await client.post(
        f"/escrow/{escrow_id}/counter",
        json={"description": "Need better terms", "amount": 45_000},
        headers=RECEIVER_HEADER,
    )
    assert counter_resp.status_code == 200, counter_resp.text

    accept_resp = await client.post(
        f"/escrow/{escrow_id}/accept",
        json={},
        headers=RECEIVER_HEADER,
    )
    assert accept_resp.status_code == 200, accept_resp.text
    assert accept_resp.json()["escrow"]["counter_status"] == "accepted"

    detail_resp = await client.get(f"/escrow/{escrow_id}", headers=AUTH_HEADER)
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()
    assert detail["status"] == "active"
    assert detail["counter_status"] == "accepted"
    assert len(detail["counter_history"]) == 1
    assert detail["counter_history"][0]["status"] == "accepted"
    assert (
        detail["counter_history"][0]["proposed_by_user_id"]
        == "22222222-2222-4222-8222-22222222222b"
    )


@pytest.mark.asyncio
async def test_resend_invitation_email_based(client):
    payload = {
        "escrow_type": "onetime",
        "title": "Email invite",
        "currency": "ETB",
        "amount": 90_000,
        "initiator_role": "buyer",
        "receiver_email": "old-email@example.com",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201, create_resp.text
    escrow_id = create_resp.json()["escrow"]["id"]

    resend_resp = await client.post(
        f"/escrow/{escrow_id}/resend",
        json={"receiver_email": "new-email@example.com"},
        headers=AUTH_HEADER,
    )
    assert resend_resp.status_code == 200, resend_resp.text
    data = resend_resp.json()
    assert data["receiver_email"] == "new-email@example.com"


@pytest.mark.asyncio
async def test_precheck_invitation_returns_login_when_account_exists(
    client, monkeypatch
):
    monkeypatch.setattr(
        "app.service._generate_invite_token", lambda: "known-invite-token"
    )
    monkeypatch.setattr(
        "app.grpc_clients.get_user_by_email",
        AsyncMock(return_value=None),
    )
    payload = {
        "escrow_type": "onetime",
        "title": "Precheck invite",
        "currency": "ETB",
        "amount": 90_000,
        "initiator_role": "buyer",
        "receiver_email": "receiver@example.com",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201, create_resp.text
    escrow_id = create_resp.json()["escrow"]["id"]

    precheck_resp = await client.get(
        f"/escrow/{escrow_id}/invitation/precheck",
        params={"token": "known-invite-token"},
    )
    assert precheck_resp.status_code == 200, precheck_resp.text
    data = precheck_resp.json()
    assert data["escrow_id"] == escrow_id
    assert data["has_account"] is True
    assert data["next_action"] == "login"


@pytest.mark.asyncio
async def test_precheck_invitation_invalid_token_returns_403(client, monkeypatch):
    monkeypatch.setattr(
        "app.service._generate_invite_token", lambda: "known-invite-token"
    )
    payload = {
        "escrow_type": "onetime",
        "title": "Invalid token precheck",
        "currency": "ETB",
        "amount": 90_000,
        "initiator_role": "buyer",
        "receiver_email": "receiver@example.com",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201, create_resp.text
    escrow_id = create_resp.json()["escrow"]["id"]

    precheck_resp = await client.get(
        f"/escrow/{escrow_id}/invitation/precheck",
        params={"token": "bad-invite-token-0001"},
    )
    assert precheck_resp.status_code == 403


@pytest.mark.asyncio
async def test_org_scoped_create_requires_org_api_key(client):
    payload = {
        "escrow_type": "onetime",
        "title": "Org scoped invite",
        "currency": "ETB",
        "amount": 66_000,
        "initiator_role": "seller",
        "seller_type": "organization",
        "org_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "receiver_id": "33333333-3333-4333-8333-33333333333c",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 403


@pytest.mark.asyncio
async def test_org_scoped_create_succeeds_with_org_api_key(client):
    payload = {
        "escrow_type": "onetime",
        "title": "Org key create",
        "currency": "ETB",
        "amount": 66_000,
        "initiator_role": "seller",
        "seller_type": "organization",
        "org_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    create_resp = await client.post("/escrow", json=payload, headers=ORG_KEY_HEADER)
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()["escrow"]
    assert created["initiator_actor_type"] == "organization"
    assert created["initiator_org_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert created["initiator_id"] is None


@pytest.mark.asyncio
async def test_org_api_key_forbidden_on_invitation_response_endpoint(client):
    payload = {
        "escrow_type": "onetime",
        "title": "Org key cannot accept",
        "currency": "ETB",
        "amount": 66_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201, create_resp.text
    escrow_id = create_resp.json()["escrow"]["id"]

    accept_resp = await client.post(
        f"/escrow/{escrow_id}/accept",
        json={},
        headers=ORG_KEY_HEADER,
    )
    assert accept_resp.status_code == 403


@pytest.mark.asyncio
async def test_org_seller_payload_rejects_buyer_initiator_role(client):
    payload = {
        "escrow_type": "onetime",
        "title": "Invalid org buyer role",
        "currency": "ETB",
        "amount": 12_000,
        "initiator_role": "buyer",
        "seller_type": "organization",
        "org_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    response = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_onetime_rejects_receiver_when_receiver_is_organization(
    client, monkeypatch
):
    monkeypatch.setattr(
        "app.grpc_clients.check_organization_exists",
        AsyncMock(return_value=True),
    )
    payload = {
        "escrow_type": "onetime",
        "title": "Org receiver blocked",
        "currency": "ETB",
        "amount": 30_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    response = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert response.status_code == 400
    assert "receiver" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_milestone_rejects_receiver_when_receiver_is_organization(
    client, monkeypatch
):
    monkeypatch.setattr(
        "app.grpc_clients.check_organization_exists",
        AsyncMock(return_value=True),
    )
    payload = {
        "escrow_type": "milestone",
        "title": "Milestone org receiver blocked",
        "currency": "ETB",
        "amount": 200_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
        "milestones": [
            {"title": "Part 1", "amount": 100_000},
            {"title": "Part 2", "amount": 100_000},
        ],
    }
    response = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert response.status_code == 400
    assert "receiver" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_recurring_rejects_receiver_when_receiver_is_organization(
    client, monkeypatch
):
    monkeypatch.setattr(
        "app.grpc_clients.check_organization_exists",
        AsyncMock(return_value=True),
    )
    payload = {
        "escrow_type": "recurring",
        "title": "Recurring org receiver blocked",
        "currency": "ETB",
        "amount": 80_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
        "cycle": {
            "cycle_interval": "monthly",
            "expected_amount": 80_000,
            "min_contributors": 1,
        },
    }
    response = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert response.status_code == 400
    assert "receiver" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cancel_already_cancelled(client):
    """Cancelling a cancelled escrow should return 400 (invalid transition)."""
    payload = {
        "escrow_type": "onetime",
        "title": "Double cancel",
        "currency": "ETB",
        "amount": 10_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    escrow_id = create_resp.json()["escrow"]["id"]

    # First cancel
    await client.post(f"/escrow/{escrow_id}/cancel", headers=AUTH_HEADER)
    # Second cancel should fail
    second = await client.post(f"/escrow/{escrow_id}/cancel", headers=AUTH_HEADER)
    assert second.status_code == 400


# ─── GET /escrow/{id}/milestones ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_milestones(client):
    """GET /escrow/{id}/milestones returns the milestone list for a milestone escrow."""
    payload = {
        "escrow_type": "milestone",
        "title": "App development",
        "currency": "ETB",
        "amount": 150_000,
        "initiator_role": "buyer",
        "receiver_id": "22222222-2222-4222-8222-22222222222b",
        "milestones": [
            {"title": "Sprint 1", "amount": 75_000},
            {"title": "Sprint 2", "amount": 75_000},
        ],
    }
    create_resp = await client.post("/escrow", json=payload, headers=AUTH_HEADER)
    assert create_resp.status_code == 201
    escrow_id = create_resp.json()["escrow"]["id"]

    ms_resp = await client.get(f"/escrow/{escrow_id}/milestones", headers=AUTH_HEADER)
    assert ms_resp.status_code == 200
    milestones = ms_resp.json()
    assert len(milestones) == 2
    titles = {m["title"] for m in milestones}
    assert "Sprint 1" in titles
    assert "Sprint 2" in titles
