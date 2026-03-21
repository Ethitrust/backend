from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import import_module

from app.config import StorageSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignedUrlResult:
    url: str
    method: str
    object_key: str
    expires_in_seconds: int


class StorageService:
    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self._client = self._build_client()

    def _build_client(self):
        boto3 = import_module("boto3")
        return boto3.client(
            service_name="s3",
            endpoint_url=self.settings.endpoint_url,
            aws_access_key_id=self.settings.access_key_id,
            aws_secret_access_key=self.settings.secret_access_key,
            region_name=self.settings.region_name,
        )

    def _normalize_ttl(self, requested_ttl: int) -> int:
        ttl = requested_ttl or self.settings.default_ttl_seconds
        if ttl < 1:
            return 1
        return min(ttl, self.settings.max_ttl_seconds)

    def _validate_key_scope(
        self,
        *,
        actor_user_id: str,
        object_key: str,
        purpose: str,
        role: str,
    ) -> str:
        normalized_key = object_key.strip().lstrip("/")
        if not normalized_key:
            raise ValueError("object_key is required")
        if ".." in normalized_key:
            raise ValueError("object_key cannot contain '..'")
        if len(normalized_key) > 512:
            raise ValueError("object_key is too long")

        normalized_purpose = (purpose or "general").strip().lower()
        normalized_role = (role or "user").strip().lower()

        if normalized_role != "admin":
            required_prefix = f"{normalized_purpose}/{actor_user_id}/"
            if not normalized_key.startswith(required_prefix):
                raise ValueError("object_key is outside of the allowed user scope")

        return normalized_key

    def generate_presigned_upload_url(
        self,
        *,
        actor_user_id: str,
        role: str,
        purpose: str,
        object_key: str,
        content_type: str,
        expires_in_seconds: int,
    ) -> SignedUrlResult:
        normalized_content_type = content_type.strip().lower()
        if not normalized_content_type:
            raise ValueError("content_type is required")

        if normalized_content_type not in self.settings.allowed_upload_content_types:
            raise ValueError("content_type is not allowed")

        normalized_key = self._validate_key_scope(
            actor_user_id=actor_user_id,
            object_key=object_key,
            purpose=purpose,
            role=role,
        )
        ttl = self._normalize_ttl(expires_in_seconds)

        url = self._client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.settings.bucket_name,
                "Key": normalized_key,
                "ContentType": normalized_content_type,
            },
            ExpiresIn=ttl,
        )

        return SignedUrlResult(
            url=url,
            method="PUT",
            object_key=normalized_key,
            expires_in_seconds=ttl,
        )

    def generate_presigned_download_url(
        self,
        *,
        actor_user_id: str,
        role: str,
        purpose: str,
        object_key: str,
        expires_in_seconds: int,
    ) -> SignedUrlResult:
        normalized_key = self._validate_key_scope(
            actor_user_id=actor_user_id,
            object_key=object_key,
            purpose=purpose,
            role=role,
        )
        ttl = self._normalize_ttl(expires_in_seconds)

        url = self._client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.settings.bucket_name,
                "Key": normalized_key,
            },
            ExpiresIn=ttl,
        )

        return SignedUrlResult(
            url=url,
            method="GET",
            object_key=normalized_key,
            expires_in_seconds=ttl,
        )
