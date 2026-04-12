"""Integration tests for Admin HTTP routes."""

from __future__ import annotations

import pytest

AUTH_HEADER = {"Authorization": "Bearer test-token"}
TARGET_USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TARGET_DISPUTE_ID = "11111111-1111-1111-1111-111111111111"
TARGET_ESCROW_ID = "22222222-2222-2222-2222-222222222222"
TARGET_PAYOUT_ID = "55555555-5555-5555-5555-555555555555"
TARGET_CONFIG_KEY = "fees.platform_fee_percent"


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "admin"


@pytest.mark.asyncio
async def test_list_users(client):
    r = await client.get("/admin/users", headers=AUTH_HEADER)
    assert r.status_code == 200
    assert len(r.json()) >= 1


@pytest.mark.asyncio
async def test_update_role(client, mock_audit_emission):
    r = await client.patch(
        f"/admin/users/{TARGET_USER_ID}/role",
        json={"role": "moderator"},
        headers=AUTH_HEADER,
    )
    assert r.status_code == 200
    assert r.json()["role"] == "moderator"
    assert mock_audit_emission.await_count == 1


@pytest.mark.asyncio
async def test_ban_user(client, mock_audit_emission):
    r = await client.post(
        f"/admin/users/{TARGET_USER_ID}/ban",
        json={"ban": True, "reason": "Violation of terms of service."},
        headers=AUTH_HEADER,
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    assert mock_audit_emission.await_count == 1


@pytest.mark.asyncio
async def test_get_stats(client):
    r = await client.get("/admin/stats", headers=AUTH_HEADER)
    assert r.status_code == 200
    data = r.json()
    assert "total_users" in data
    assert "total_escrows" in data


@pytest.mark.asyncio
async def test_actions_log_created_for_role_update(client):
    update = await client.patch(
        f"/admin/users/{TARGET_USER_ID}/role",
        json={"role": "moderator"},
        headers=AUTH_HEADER,
    )
    assert update.status_code == 200

    logs = await client.get("/admin/actions", headers=AUTH_HEADER)
    assert logs.status_code == 200
    payload = logs.json()
    assert payload["total"] >= 1
    assert any(item["action"] == "user.role_updated" for item in payload["items"])


@pytest.mark.asyncio
async def test_actions_log_filter_by_action(client):
    ban = await client.post(
        f"/admin/users/{TARGET_USER_ID}/ban",
        json={"ban": True, "reason": "Violation of terms of service."},
        headers=AUTH_HEADER,
    )
    assert ban.status_code == 200

    logs = await client.get("/admin/actions?action=user.banned", headers=AUTH_HEADER)
    assert logs.status_code == 200
    payload = logs.json()
    assert payload["total"] >= 1
    assert all(item["action"] == "user.banned" for item in payload["items"])


@pytest.mark.asyncio
async def test_non_admin_forbidden(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "role": "user",
            }
        ),
    )
    r = await client.get("/admin/users", headers=AUTH_HEADER)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_users_read_scope_allows_non_admin_listing(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "role": "user",
                "scopes": ["users.read"],
            }
        ),
    )
    r = await client.get("/admin/users", headers=AUTH_HEADER)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_moderator_can_list_users(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                "role": "moderator",
            }
        ),
    )
    r = await client.get("/admin/users", headers=AUTH_HEADER)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_moderator_cannot_update_role(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                "role": "moderator",
            }
        ),
    )
    r = await client.patch(
        f"/admin/users/{TARGET_USER_ID}/role",
        json={"role": "user"},
        headers=AUTH_HEADER,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_scope_allows_role_update_for_non_admin(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                "role": "user",
                "scopes": ["users.role.update"],
            }
        ),
    )
    r = await client.patch(
        f"/admin/users/{TARGET_USER_ID}/role",
        json={"role": "moderator"},
        headers=AUTH_HEADER,
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_non_admin_cannot_list_action_logs(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "role": "user",
            }
        ),
    )
    r = await client.get("/admin/actions", headers=AUTH_HEADER)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_actions_scope_allows_log_access(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "99999999-9999-9999-9999-999999999999",
                "role": "user",
                "scopes": ["actions.read"],
            }
        ),
    )
    r = await client.get("/admin/actions", headers=AUTH_HEADER)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_verification_override_applied(client):
    headers = {**AUTH_HEADER, "X-Idempotency-Key": "verify-override-1"}
    r = await client.post(
        f"/admin/users/{TARGET_USER_ID}/verification-override",
        json={
            "is_verified": False,
            "reason": "Manual override after governance review.",
            "require_dual_approval": False,
        },
        headers=headers,
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] == "applied"
    assert payload["is_verified"] is False
    assert payload["idempotency_key"] == "verify-override-1"


@pytest.mark.asyncio
async def test_verification_override_dual_approval_queue(client):
    headers = {**AUTH_HEADER, "X-Idempotency-Key": "verify-override-2"}
    r = await client.post(
        f"/admin/users/{TARGET_USER_ID}/verification-override",
        json={
            "is_verified": True,
            "reason": "Escalated account restoration review.",
            "require_dual_approval": True,
        },
        headers=headers,
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] == "pending_approval"
    assert payload["review_case_id"] is not None


@pytest.mark.asyncio
async def test_user_timeline_contains_risk_flag_and_note(client):
    risk = await client.post(
        f"/admin/users/{TARGET_USER_ID}/risk-flags",
        json={
            "flag": "multiple_failed_kyc_submissions",
            "severity": "high",
            "reason": "Three failed KYC submissions in 24h.",
            "metadata": {"window_hours": 24, "attempts": 3},
        },
        headers=AUTH_HEADER,
    )
    assert risk.status_code == 200

    note = await client.post(
        f"/admin/users/{TARGET_USER_ID}/moderation-notes",
        json={
            "note": "Escalate to trust and safety for manual review.",
            "visibility": "internal",
        },
        headers=AUTH_HEADER,
    )
    assert note.status_code == 200

    timeline = await client.get(f"/admin/users/{TARGET_USER_ID}/timeline", headers=AUTH_HEADER)
    assert timeline.status_code == 200
    payload = timeline.json()
    item_types = {item["item_type"] for item in payload["items"]}
    assert "risk_flag" in item_types
    assert "moderation_note" in item_types


@pytest.mark.asyncio
async def test_bulk_ban_requires_idempotency_key(client):
    r = await client.post(
        "/admin/bulk/users/ban",
        json={
            "user_ids": [TARGET_USER_ID],
            "ban": True,
            "reason": "Bulk moderation request triggered.",
            "require_dual_approval": False,
            "priority": "high",
        },
        headers=AUTH_HEADER,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_bulk_ban_idempotency_replay(client, monkeypatch):
    from unittest.mock import AsyncMock

    async def _mock_ban(user_id, ban: bool, reason: str):
        return {"id": str(user_id), "is_active": not ban}

    ban_mock = AsyncMock(side_effect=_mock_ban)
    monkeypatch.setattr("app.grpc_clients.ban_user", ban_mock)

    headers = {**AUTH_HEADER, "X-Idempotency-Key": "bulk-ban-1"}
    body = {
        "user_ids": [
            "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        ],
        "ban": True,
        "reason": "Bulk governance action due to policy breach.",
        "require_dual_approval": False,
        "priority": "high",
    }
    first = await client.post("/admin/bulk/users/ban", json=body, headers=headers)
    second = await client.post("/admin/bulk/users/ban", json=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert ban_mock.await_count == 2


@pytest.mark.asyncio
async def test_bulk_ban_dual_approval_queues_cases(client):
    headers = {**AUTH_HEADER, "X-Idempotency-Key": "bulk-ban-queue-1"}
    r = await client.post(
        "/admin/bulk/users/ban",
        json={
            "user_ids": [
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            ],
            "ban": True,
            "reason": "Needs dual approval for high-risk operation.",
            "require_dual_approval": True,
            "priority": "high",
        },
        headers=headers,
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["queued"] == 2
    assert payload["processed"] == 0
    assert all(item["status"] == "pending_approval" for item in payload["items"])


@pytest.mark.asyncio
async def test_dispute_queue_list_syncs_remote_items(client):
    r = await client.get("/admin/disputes/queue", headers=AUTH_HEADER)
    assert r.status_code == 200

    payload = r.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["dispute_id"] == TARGET_DISPUTE_ID
    assert payload["items"][0]["status"] == "open"


@pytest.mark.asyncio
async def test_dispute_queue_item_detail_includes_escrow_and_users(client):
    sync = await client.get("/admin/disputes/queue", headers=AUTH_HEADER)
    assert sync.status_code == 200

    detail = await client.get(f"/admin/disputes/{TARGET_DISPUTE_ID}", headers=AUTH_HEADER)
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["dispute_id"] == TARGET_DISPUTE_ID
    assert payload["escrow"]["escrow_id"] == TARGET_ESCROW_ID
    assert payload["escrow"]["status"] == "disputed"
    assert payload["raised_by_user"]["user_id"] == "33333333-3333-3333-3333-333333333333"
    assert payload["initiator_user"]["user_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert payload["receiver_user"]["user_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.mark.asyncio
async def test_dispute_queue_update_metadata(client):
    sync = await client.get("/admin/disputes/queue", headers=AUTH_HEADER)
    assert sync.status_code == 200

    update = await client.patch(
        f"/admin/disputes/{TARGET_DISPUTE_ID}/queue",
        json={
            "priority": "critical",
            "assignee_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "sla_hours": 12,
            "note": "Escalated due to monetary impact.",
        },
        headers=AUTH_HEADER,
    )
    assert update.status_code == 200
    payload = update.json()
    assert payload["priority"] == "critical"
    assert payload["assignee_id"] == "cccccccc-cccc-cccc-cccc-cccccccccccc"
    assert payload["sla_due_at"] is not None


@pytest.mark.asyncio
async def test_dispute_evidence_request_created(client):
    r = await client.post(
        f"/admin/disputes/{TARGET_DISPUTE_ID}/evidence-requests",
        json={
            "requested_from_user_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "note": "Please submit delivery proof and signed receipt.",
            "due_in_hours": 24,
        },
        headers=AUTH_HEADER,
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["dispute_id"] == TARGET_DISPUTE_ID
    assert payload["status"] == "pending"


@pytest.mark.asyncio
async def test_dispute_move_to_review(client):
    r = await client.post(
        f"/admin/disputes/{TARGET_DISPUTE_ID}/review",
        json={"note": "Assigning this case for manual fraud review."},
        headers=AUTH_HEADER,
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["dispute_id"] == TARGET_DISPUTE_ID
    assert payload["status"] == "under_review"


@pytest.mark.asyncio
async def test_dispute_resolution_executes_and_refunds_fee(client, mock_dispute_clients):
    r = await client.post(
        f"/admin/disputes/{TARGET_DISPUTE_ID}/resolution",
        json={
            "escrow_id": TARGET_ESCROW_ID,
            "resolution": "buyer",
            "resolution_note": "Seller could not provide proof of fulfillment.",
            "apply_fee_refund": True,
        },
        headers=AUTH_HEADER,
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["dispute_id"] == TARGET_DISPUTE_ID
    assert payload["escrow_id"] == TARGET_ESCROW_ID
    assert payload["status"] == "resolved_buyer"
    assert payload["fee_refund_status"] == "applied"
    assert mock_dispute_clients["request_dispute_resolution"].await_count == 1
    assert mock_dispute_clients["execute_dispute_resolution"].await_count == 1
    assert mock_dispute_clients["refund_fee_for_escrow"].await_count == 1


@pytest.mark.asyncio
async def test_dispute_dashboard_counters(client):
    sync = await client.get("/admin/disputes/queue", headers=AUTH_HEADER)
    assert sync.status_code == 200

    counters = await client.get("/admin/disputes/dashboard/counters", headers=AUTH_HEADER)
    assert counters.status_code == 200
    payload = counters.json()
    assert payload["open"] >= 1
    assert payload["under_review"] >= 0
    assert payload["resolved"] >= 0


@pytest.mark.asyncio
async def test_payout_queue_list_syncs_remote_items(client):
    r = await client.get("/admin/payouts/queue", headers=AUTH_HEADER)
    assert r.status_code == 200

    payload = r.json()
    assert payload["total"] >= 1
    assert payload["items"][0]["payout_id"] == TARGET_PAYOUT_ID
    assert payload["items"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_payout_queue_update_metadata(client):
    sync = await client.get("/admin/payouts/queue", headers=AUTH_HEADER)
    assert sync.status_code == 200

    update = await client.patch(
        f"/admin/payouts/{TARGET_PAYOUT_ID}/queue",
        json={
            "priority": "critical",
            "assignee_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "note": "Escalated payout retry due to SLA pressure.",
        },
        headers=AUTH_HEADER,
    )
    assert update.status_code == 200
    payload = update.json()
    assert payload["priority"] == "critical"
    assert payload["assignee_id"] == "cccccccc-cccc-cccc-cccc-cccccccccccc"


@pytest.mark.asyncio
async def test_payout_retry_executes_and_tracks_retry_count(client, mock_payout_clients):
    sync = await client.get("/admin/payouts/queue", headers=AUTH_HEADER)
    assert sync.status_code == 200

    retry = await client.post(
        f"/admin/payouts/{TARGET_PAYOUT_ID}/retry",
        json={"note": "Manual retry approved by treasury."},
        headers=AUTH_HEADER,
    )
    assert retry.status_code == 200
    payload = retry.json()
    assert payload["payout_id"] == TARGET_PAYOUT_ID
    assert payload["status"] == "processing"
    assert payload["retry_count"] == 1
    assert payload["item"]["status"] == "processing"
    assert mock_payout_clients["retry_payout_transfer"].await_count == 1


@pytest.mark.asyncio
async def test_financial_dashboard_and_reconciliation(client):
    sync = await client.get("/admin/payouts/queue", headers=AUTH_HEADER)
    assert sync.status_code == 200

    counters = await client.get("/admin/finance/dashboard/counters", headers=AUTH_HEADER)
    assert counters.status_code == 200
    counters_payload = counters.json()
    assert counters_payload["failed"] >= 1

    reconciliation = await client.get("/admin/finance/reconciliation/summary", headers=AUTH_HEADER)
    assert reconciliation.status_code == 200
    reconciliation_payload = reconciliation.json()
    assert reconciliation_payload["total_transactions"] >= 1
    assert reconciliation_payload["failed_amount"] >= 125000
    assert "failed_fee_refunds" in reconciliation_payload


@pytest.mark.asyncio
async def test_scope_allows_finance_dashboard_access(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "99999999-9999-9999-9999-999999999999",
                "role": "user",
                "scopes": ["finance.dashboard.read"],
            }
        ),
    )
    r = await client.get("/admin/finance/dashboard/counters", headers=AUTH_HEADER)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_system_config_dry_run_validation(client):
    r = await client.post(
        "/admin/configs/validate",
        json={"key": TARGET_CONFIG_KEY, "value": 2.5},
        headers=AUTH_HEADER,
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["key"] == TARGET_CONFIG_KEY
    assert payload["valid"] is True
    assert payload["next_version"] == 1


@pytest.mark.asyncio
async def test_system_config_upsert_get_and_history(client):
    upsert = await client.put(
        f"/admin/configs/{TARGET_CONFIG_KEY}",
        json={"value": 1.75, "reason": "Adjusting fee policy for Q2 operations."},
        headers=AUTH_HEADER,
    )
    assert upsert.status_code == 200
    upsert_payload = upsert.json()
    assert upsert_payload["action"] in {
        "system_config.created",
        "system_config.updated",
    }
    assert upsert_payload["item"]["key"] == TARGET_CONFIG_KEY

    get_config = await client.get(f"/admin/configs/{TARGET_CONFIG_KEY}", headers=AUTH_HEADER)
    assert get_config.status_code == 200
    config_payload = get_config.json()
    assert config_payload["value"] == 1.75
    assert config_payload["version"] >= 1

    history = await client.get(f"/admin/configs/{TARGET_CONFIG_KEY}/history", headers=AUTH_HEADER)
    assert history.status_code == 200
    history_payload = history.json()
    assert history_payload["key"] == TARGET_CONFIG_KEY
    assert len(history_payload["items"]) >= 1


@pytest.mark.asyncio
async def test_system_config_rollback(client):
    key = "thresholds.high_risk_payout_amount"

    first = await client.put(
        f"/admin/configs/{key}",
        json={"value": 250000, "reason": "Initial high-risk payout threshold."},
        headers=AUTH_HEADER,
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["item"]["version"] == 1

    second = await client.put(
        f"/admin/configs/{key}",
        json={"value": 300000, "reason": "Raise threshold after fraud model update."},
        headers=AUTH_HEADER,
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["item"]["version"] == 2

    rollback = await client.post(
        f"/admin/configs/{key}/rollback",
        json={
            "target_version": 1,
            "reason": "Reverting threshold pending risk committee review.",
        },
        headers=AUTH_HEADER,
    )
    assert rollback.status_code == 200
    rollback_payload = rollback.json()
    assert rollback_payload["action"] == "system_config.rolled_back"
    assert rollback_payload["item"]["version"] == 3
    assert rollback_payload["item"]["value"] == 250000


@pytest.mark.asyncio
async def test_system_config_invalid_value_rejected(client):
    r = await client.put(
        "/admin/configs/fees.min_fee_amount",
        json={"value": -5, "reason": "Testing invalid fee floor input."},
        headers=AUTH_HEADER,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_scope_allows_config_read(client, monkeypatch):
    from unittest.mock import AsyncMock

    seed = await client.put(
        f"/admin/configs/{TARGET_CONFIG_KEY}",
        json={"value": 1.6, "reason": "Seeding config before scope-read check."},
        headers=AUTH_HEADER,
    )
    assert seed.status_code == 200

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "99999999-9999-9999-9999-999999999999",
                "role": "user",
                "scopes": ["config.read"],
            }
        ),
    )

    read = await client.get(f"/admin/configs/{TARGET_CONFIG_KEY}", headers=AUTH_HEADER)
    assert read.status_code == 200


@pytest.mark.asyncio
async def test_analytics_growth_and_volume_endpoints(client):
    disputes_sync = await client.get("/admin/disputes/queue", headers=AUTH_HEADER)
    assert disputes_sync.status_code == 200
    payouts_sync = await client.get("/admin/payouts/queue", headers=AUTH_HEADER)
    assert payouts_sync.status_code == 200

    growth = await client.get("/admin/analytics/growth?window_days=30", headers=AUTH_HEADER)
    assert growth.status_code == 200
    growth_payload = growth.json()
    assert growth_payload["window_days"] == 30
    assert len(growth_payload["disputes_created"]) == 30
    assert len(growth_payload["payout_volume"]) == 30

    volume = await client.get("/admin/analytics/volume?window_days=30", headers=AUTH_HEADER)
    assert volume.status_code == 200
    volume_payload = volume.json()
    assert volume_payload["window_days"] == 30
    assert volume_payload["total_volume"] >= 125000
    assert len(volume_payload["volume_series"]) == 30


@pytest.mark.asyncio
async def test_analytics_dispute_throughput_and_payout_health(client):
    disputes_sync = await client.get("/admin/disputes/queue", headers=AUTH_HEADER)
    assert disputes_sync.status_code == 200
    payouts_sync = await client.get("/admin/payouts/queue", headers=AUTH_HEADER)
    assert payouts_sync.status_code == 200

    dispute_throughput = await client.get(
        "/admin/analytics/disputes-throughput?window_days=30",
        headers=AUTH_HEADER,
    )
    assert dispute_throughput.status_code == 200
    dispute_payload = dispute_throughput.json()
    assert dispute_payload["window_days"] == 30
    assert "resolution_rate" in dispute_payload
    assert len(dispute_payload["opened_series"]) == 30

    payout_health = await client.get(
        "/admin/analytics/payout-health?window_days=30",
        headers=AUTH_HEADER,
    )
    assert payout_health.status_code == 200
    payout_payload = payout_health.json()
    assert payout_payload["window_days"] == 30
    assert "success_rate" in payout_payload
    assert len(payout_payload["failed_series"]) == 30


@pytest.mark.asyncio
async def test_saved_views_lifecycle(client):
    create = await client.post(
        "/admin/saved-views",
        json={
            "module": "analytics",
            "name": "Dispute Ops Daily",
            "filters": {"window_days": 14, "status": ["open", "under_review"]},
            "is_shared": True,
        },
        headers=AUTH_HEADER,
    )
    assert create.status_code == 200
    create_payload = create.json()
    view_id = create_payload["id"]
    assert create_payload["module"] == "analytics"
    assert create_payload["is_shared"] is True

    listed = await client.get("/admin/saved-views?module=analytics", headers=AUTH_HEADER)
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["total"] >= 1
    assert any(item["id"] == view_id for item in listed_payload["items"])

    fetched = await client.get(f"/admin/saved-views/{view_id}", headers=AUTH_HEADER)
    assert fetched.status_code == 200
    fetched_payload = fetched.json()
    assert fetched_payload["name"] == "Dispute Ops Daily"

    updated = await client.patch(
        f"/admin/saved-views/{view_id}",
        json={
            "name": "Dispute Ops Weekly",
            "filters": {"window_days": 7, "status": ["open"]},
            "is_shared": False,
        },
        headers=AUTH_HEADER,
    )
    assert updated.status_code == 200
    updated_payload = updated.json()
    assert updated_payload["name"] == "Dispute Ops Weekly"
    assert updated_payload["is_shared"] is False


@pytest.mark.asyncio
async def test_report_jobs_lifecycle_and_download(client):
    disputes_sync = await client.get("/admin/disputes/queue", headers=AUTH_HEADER)
    assert disputes_sync.status_code == 200
    payouts_sync = await client.get("/admin/payouts/queue", headers=AUTH_HEADER)
    assert payouts_sync.status_code == 200

    create = await client.post(
        "/admin/reports/jobs",
        json={
            "report_type": "dashboard_snapshot",
            "export_format": "json",
            "filters": {"window_days": 14},
        },
        headers=AUTH_HEADER,
    )
    assert create.status_code == 200
    create_payload = create.json()
    job_id = create_payload["id"]
    assert create_payload["status"] == "queued"

    listed = await client.get("/admin/reports/jobs", headers=AUTH_HEADER)
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["total"] >= 1
    assert any(item["id"] == job_id for item in listed_payload["items"])

    fetched = await client.get(f"/admin/reports/jobs/{job_id}", headers=AUTH_HEADER)
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "queued"

    run = await client.post(f"/admin/reports/jobs/{job_id}/run", headers=AUTH_HEADER)
    assert run.status_code == 200
    run_payload = run.json()
    assert run_payload["status"] == "completed"
    assert run_payload["result_url"] is not None

    download = await client.get(f"/admin/reports/jobs/{job_id}/download", headers=AUTH_HEADER)
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/json")
    assert "attachment; filename=" in download.headers["content-disposition"]


@pytest.mark.asyncio
async def test_scope_allows_analytics_growth_read(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "99999999-9999-9999-9999-999999999999",
                "role": "user",
                "scopes": ["analytics.growth.read"],
            }
        ),
    )
    r = await client.get("/admin/analytics/growth", headers=AUTH_HEADER)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_scope_allows_reports_read_list(client, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "99999999-9999-9999-9999-999999999999",
                "role": "user",
                "scopes": ["reports.read"],
            }
        ),
    )
    r = await client.get("/admin/reports/jobs", headers=AUTH_HEADER)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_feature_flag_can_disable_users_module(client, monkeypatch):
    monkeypatch.setenv("ADMIN_FEATURE_USERS_ENABLED", "false")

    response = await client.get("/admin/users", headers=AUTH_HEADER)

    assert response.status_code == 503
    assert "currently disabled" in response.json()["detail"]


@pytest.mark.asyncio
async def test_emergency_read_only_blocks_mutations(client, monkeypatch):
    monkeypatch.setenv("ADMIN_EMERGENCY_READ_ONLY", "true")

    list_response = await client.get("/admin/users", headers=AUTH_HEADER)
    assert list_response.status_code == 200

    ban_response = await client.post(
        f"/admin/users/{TARGET_USER_ID}/ban",
        json={"ban": True, "reason": "Emergency-mode enforcement check."},
        headers=AUTH_HEADER,
    )
    assert ban_response.status_code == 503
    assert "emergency read-only mode" in ban_response.json()["detail"]


@pytest.mark.asyncio
async def test_shadow_read_headers_for_sampled_gets(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SHADOW_READ_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SHADOW_USERS_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SHADOW_READ_SAMPLE_RATE", "1.0")

    response = await client.get("/admin/users", headers=AUTH_HEADER)

    assert response.status_code == 200
    assert response.headers["X-Admin-Shadow-Read"] == "enabled"


_RBAC_SCOPE_MATRIX = [
    (
        "GET",
        "/admin/users",
        None,
        {},
        "users.read",
    ),
    (
        "GET",
        "/admin/finance/dashboard/counters",
        None,
        {},
        "finance.dashboard.read",
    ),
    (
        "GET",
        "/admin/reports/jobs",
        None,
        {},
        "reports.read",
    ),
    (
        "PATCH",
        f"/admin/users/{TARGET_USER_ID}/role",
        {"role": "moderator"},
        {},
        "users.role.update",
    ),
    (
        "POST",
        f"/admin/users/{TARGET_USER_ID}/ban",
        {"ban": True, "reason": "Scope-matrix ban policy test reason."},
        {},
        "users.ban.manage",
    ),
    (
        "POST",
        "/admin/bulk/users/ban",
        {
            "user_ids": [
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            ],
            "ban": True,
            "reason": "Scope matrix bulk moderation request.",
            "require_dual_approval": False,
            "priority": "high",
        },
        {"X-Idempotency-Key": "rbac-bulk-ban-1"},
        "users.bulk_actions.execute",
    ),
    (
        "PUT",
        "/admin/configs/fees.platform_fee_percent",
        {"value": 2.25, "reason": "Scope matrix config update test."},
        {},
        "config.write",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,body,extra_headers,required_scope",
    _RBAC_SCOPE_MATRIX,
)
async def test_scope_matrix_allows_authorized_requests(
    client,
    monkeypatch,
    method: str,
    path: str,
    body: dict | None,
    extra_headers: dict,
    required_scope: str,
):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "12121212-1212-1212-1212-121212121212",
                "role": "user",
                "scopes": [required_scope],
            }
        ),
    )

    headers = {**AUTH_HEADER, **extra_headers}
    response = await client.request(method=method, url=path, json=body, headers=headers)

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,body,extra_headers,_required_scope",
    _RBAC_SCOPE_MATRIX,
)
async def test_scope_matrix_denies_requests_without_scope(
    client,
    monkeypatch,
    method: str,
    path: str,
    body: dict | None,
    extra_headers: dict,
    _required_scope: str,
):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.grpc_clients.validate_token",
        AsyncMock(
            return_value={
                "user_id": "12121212-1212-1212-1212-121212121212",
                "role": "user",
                "scopes": [],
            }
        ),
    )

    headers = {**AUTH_HEADER, **extra_headers}
    response = await client.request(method=method, url=path, json=body, headers=headers)

    assert response.status_code == 403
