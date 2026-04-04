import hashlib
import hmac
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient


@pytest.fixture()
def chapa_secret(monkeypatch):
    secret = "testsecret"
    monkeypatch.setenv("CHAPA_WEBHOOK_SECRET", secret)
    return secret


@pytest.fixture()
def stripe_secret(monkeypatch):
    secret = "stripesecret"
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)
    return secret


@pytest.fixture()
def mock_repo():
    repo = MagicMock()
    repo.save_log = AsyncMock(return_value=MagicMock())
    repo.update_log_status = AsyncMock()
    repo.get_logs = AsyncMock(return_value=[])
    return repo
