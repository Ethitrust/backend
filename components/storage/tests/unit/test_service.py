from __future__ import annotations

import pytest
from app.config import StorageSettings
from app.service import StorageService


class _FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, int]] = []

    def generate_presigned_url(
        self, operation: str, Params: dict, ExpiresIn: int
    ) -> str:  # noqa: N803
        self.calls.append((operation, Params, ExpiresIn))
        return f"https://example.com/{Params['Key']}?op={operation}&ttl={ExpiresIn}"


@pytest.fixture
def svc(monkeypatch) -> tuple[StorageService, _FakeS3Client]:
    settings = StorageSettings(
        bucket_name="ethitrust-private",
        endpoint_url="https://example.r2.cloudflarestorage.com",
        access_key_id="ak",
        secret_access_key="sk",
        region_name="auto",
        default_ttl_seconds=900,
        max_ttl_seconds=900,
        allowed_upload_content_types=("image/png", "image/jpeg"),
    )
    fake_client = _FakeS3Client()

    monkeypatch.setattr(StorageService, "_build_client", lambda self: fake_client)

    service = StorageService(settings)
    return service, fake_client


def test_generate_upload_url_enforces_key_scope(svc):
    service, _ = svc

    with pytest.raises(ValueError, match="outside of the allowed user scope"):
        service.generate_presigned_upload_url(
            actor_user_id="u1",
            role="user",
            purpose="kyc",
            object_key="kyc/u2/photo.jpg",
            content_type="image/jpeg",
            expires_in_seconds=300,
        )


def test_generate_upload_url_rejects_disallowed_content_type(svc):
    service, _ = svc

    with pytest.raises(ValueError, match="content_type is not allowed"):
        service.generate_presigned_upload_url(
            actor_user_id="u1",
            role="user",
            purpose="kyc",
            object_key="kyc/u1/photo.gif",
            content_type="image/gif",
            expires_in_seconds=300,
        )


def test_generate_upload_url_signs_with_ttl_cap(svc):
    service, fake_client = svc

    result = service.generate_presigned_upload_url(
        actor_user_id="u1",
        role="user",
        purpose="kyc",
        object_key="kyc/u1/photo.jpg",
        content_type="image/jpeg",
        expires_in_seconds=3600,
    )

    assert result.method == "PUT"
    assert result.expires_in_seconds == 900
    assert fake_client.calls[0][0] == "put_object"
    assert fake_client.calls[0][2] == 900


def test_generate_download_url_admin_can_access_any_prefix(svc):
    service, fake_client = svc

    result = service.generate_presigned_download_url(
        actor_user_id="admin-id",
        role="admin",
        purpose="kyc",
        object_key="kyc/other-user/photo.jpg",
        expires_in_seconds=600,
    )

    assert result.method == "GET"
    assert result.expires_in_seconds == 600
    assert fake_client.calls[-1][0] == "get_object"
