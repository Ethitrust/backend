from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class StorageSettings:
    bucket_name: str
    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    region_name: str
    default_ttl_seconds: int
    max_ttl_seconds: int
    allowed_upload_content_types: tuple[str, ...]


def _split_csv(raw: str) -> tuple[str, ...]:
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


def get_settings() -> StorageSettings:
    allowed_types_raw = os.getenv(
        "ALLOWED_UPLOAD_CONTENT_TYPES",
        "image/png,image/jpeg,image/jpg,application/pdf",
    )

    return StorageSettings(
        bucket_name=os.getenv("S3_BUCKET_NAME", "ethitrust-private"),
        endpoint_url=os.getenv(
            "S3_ENDPOINT_URL", "https://<ACCOUNT_ID>.r2.cloudflarestorage.com"
        ),
        access_key_id=os.getenv("AWS_ACCESS_KEY_ID", ""),
        secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
        region_name=os.getenv("AWS_REGION", "auto"),
        default_ttl_seconds=int(os.getenv("PRESIGNED_URL_TTL", "900")),
        max_ttl_seconds=int(os.getenv("PRESIGNED_URL_MAX_TTL", "900")),
        allowed_upload_content_types=_split_csv(allowed_types_raw),
    )
