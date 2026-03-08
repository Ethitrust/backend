import pytest


async def test_escrow_expiry_task_calls_service(mock_httpx):
    """check_escrow_inspection_expiry should POST to escrow service and return count."""
    from app.tasks.escrow_tasks import check_escrow_inspection_expiry

    result = check_escrow_inspection_expiry.run()
    mock_httpx.assert_called_once()
    assert result["count"] == 1


async def test_invitation_expiry_task_calls_service(mock_httpx):
    """check_invitation_expiry should POST to invitation-expiry endpoint."""
    from app.tasks.escrow_tasks import check_invitation_expiry

    result = check_invitation_expiry.run()
    mock_httpx.assert_called_once()
    call_url = mock_httpx.call_args[0][0]
    assert "/escrow/internal/process-invitation-expiry" in call_url
    assert result["count"] == 1


async def test_payout_task_calls_service(mock_httpx):
    """process_bank_transfer should POST to payout service for the given payout ID."""
    from app.tasks.payout_tasks import process_bank_transfer

    result = process_bank_transfer.run("payout-uuid-123")
    mock_httpx.assert_called_once()
    call_url = mock_httpx.call_args[0][0]
    assert "payout-uuid-123" in call_url


async def test_recurring_task_calls_service(mock_httpx):
    """process_recurring_cycle_due should POST to escrow service."""
    from app.tasks.recurring_tasks import process_recurring_cycle_due

    result = process_recurring_cycle_due.run()
    mock_httpx.assert_called_once()
    assert result["count"] == 1


async def test_dispute_resolution_task_invalid_resolution(mock_httpx):
    """process_dispute_resolution with invalid resolution returns error status without HTTP call."""
    from app.tasks.dispute_tasks import process_dispute_resolution

    result = process_dispute_resolution.run("d-uuid", "nobody", "admin-uuid")
    assert result["status"] == "invalid_resolution"
    mock_httpx.assert_not_called()


async def test_dispute_resolution_task_calls_execute_endpoint(mock_httpx, monkeypatch):
    """process_dispute_resolution calls dispute execute endpoint with worker token header."""
    from app.tasks import dispute_tasks

    monkeypatch.setattr(dispute_tasks, "DISPUTE_INTERNAL_TOKEN", "worker-internal")

    result = dispute_tasks.process_dispute_resolution.run(
        "dispute-uuid",
        "buyer",
        "admin-uuid",
    )

    assert result == {"count": 1}
    mock_httpx.assert_called_once()

    call_url = mock_httpx.call_args[0][0]
    call_kwargs = mock_httpx.call_args[1]
    assert "/disputes/dispute-uuid/execute-resolution" in call_url
    assert call_kwargs["json"] == {
        "resolution": "buyer",
        "admin_id": "admin-uuid",
    }
    assert call_kwargs["headers"] == {"X-Internal-Token": "worker-internal"}
