from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_httpx():
    """Mock httpx.post for all task tests — returns a 200 with {"count": 1}."""
    with patch("httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"count": 1}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp
        yield mock_post
