"""Business logic for the KYC service."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Optional
from uuid import uuid4

import httpx

from app import grpc_clients
from app.fayda_verify import get_fayda_client
from app.redis_client import get_and_delete_tx_alias, set_tx_alias
from app.repository import KYCClaimRepository

logger = logging.getLogger(__name__)

KYC_API_KEY = os.getenv("KYC_API_KEY", "")
KYC_API_URL = os.getenv("KYC_API_URL", "https://api.verifayda.com/v1")

# Simple in-memory cache (replace with Redis in production)
_cache: dict[str, dict] = {}


def _cache_key(lookup_type: str, value: str) -> str:
    return hashlib.sha256(f"{lookup_type}:{value}".encode()).hexdigest()


class KYCService:
    def __init__(self, claim_repo: KYCClaimRepository | None = None) -> None:
        self.claim_repo = claim_repo or KYCClaimRepository()

    async def is_user_already_verified(self, user_id: str) -> bool:
        record = await self.claim_repo.get_identity_record_by_user_id(user_id)
        return record is not None

    @staticmethod
    def _is_success(result: dict) -> bool:
        return isinstance(result, dict) and "error" not in result

    async def _lookup_cached(self, lookup_type: str, identifier: str) -> Optional[dict]:
        key = _cache_key(lookup_type, identifier)
        return _cache.get(key)

    async def _cache_result(
        self, lookup_type: str, identifier: str, result: dict
    ) -> None:
        key = _cache_key(lookup_type, identifier)
        _cache[key] = result

    async def _call_provider(self, endpoint: str, params: dict) -> dict:
        """Call verifayda KYC provider."""
        if not KYC_API_KEY:
            # Stub for development / testing
            return {"status": "success", "data": {"verified": True, **params}}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{KYC_API_URL}/{endpoint}",
                    params=params,
                    headers={"Authorization": f"Bearer {KYC_API_KEY}"},
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("KYC provider error: %s", exc)
            return {"status": "error", "message": "KYC_PROVIDER_ERROR"}
        except Exception as exc:
            logger.exception("KYC lookup failed")
            return {"status": "error", "message": str(exc)}

    @staticmethod
    async def _issue_mirrored_transaction_id(
        provider_transaction_id: str, fan_or_fin: str
    ) -> str:
        mirrored_id = str(uuid4())
        await set_tx_alias(mirrored_id, provider_transaction_id, fan_or_fin)
        return mirrored_id

    @staticmethod
    async def _resolve_mirrored_transaction_id(
        mirrored_transaction_id: str, fan_or_fin: str
    ) -> Optional[str]:
        return await get_and_delete_tx_alias(mirrored_transaction_id, fan_or_fin)

    async def lookup_drivers_license(self, user_id: str, license_number: str) -> dict:
        cached = await self._lookup_cached("drivers_license", license_number)
        if cached:
            return {**cached, "cached": True}

        result = await self._call_provider(
            "drivers-license", {"license_number": license_number}
        )
        if result.get("status") == "success":
            await self._cache_result("drivers_license", license_number, result)
            await grpc_clients.set_kyc_level(user_id, 1)
        return {**result, "cached": False}

    async def lookup_tin(self, user_id: str, tin: str) -> dict:
        raise NotImplementedError()
        cached = await self._lookup_cached("tin", tin)
        if cached:
            return {**cached, "cached": True}

        result = await self._call_provider("tin", {"tin": tin})
        if result.get("status") == "success":
            await self._cache_result("tin", tin, result)
            await grpc_clients.set_kyc_level(user_id, 1)
        return {**result, "cached": False}

    async def send_fayda_otp(self, fan_or_fin: str) -> dict:
        fayda = get_fayda_client()
        result = await fayda.send_otp(fan_or_fin)
        if self._is_success(result):
            provider_transaction_id = result.get("transactionId")
            if not provider_transaction_id:
                return {
                    "status": "error",
                    "message": "Fayda response missing transactionId",
                    "data": result,
                }

            try:
                mirrored_transaction_id = await self._issue_mirrored_transaction_id(
                    provider_transaction_id, fan_or_fin
                )

                logger.info(
                    "Issued mirrored transaction id %s for provider transaction id %s and fan_or_fin %s",
                    mirrored_transaction_id,
                    provider_transaction_id,
                    fan_or_fin,
                )
            except Exception:
                logger.exception("Failed to persist mirrored transaction id in Redis")
                return {
                    "status": "error",
                    "message": "Unable to initialize OTP session",
                    "data": None,
                }
            safe_result = dict(result)
            safe_result["transactionId"] = mirrored_transaction_id
            return {
                "status": "success",
                "data": safe_result,
                "message": "OTP sent successfully",
            }
        return {
            "status": "error",
            "message": result.get("error", "Failed to send OTP"),
            "data": result,
        }

    async def verify_fayda_otp(
        self,
        user_id: str,
        transaction_id: str,
        otp: str,
        fan_or_fin: str,
    ) -> dict:
        normalized_fan_or_fin = fan_or_fin.strip().upper()
        existing_claim = await self.claim_repo.get_fan_claim(normalized_fan_or_fin)
        if existing_claim and str(existing_claim.user_id) != user_id:
            return {
                "status": "error",
                "message": "This FAN has already been used for KYC verification.",
                "data": None,
            }

        try:
            provider_transaction_id = await self._resolve_mirrored_transaction_id(
                transaction_id, normalized_fan_or_fin
            )
        except Exception:
            logger.exception("Failed to resolve mirrored transaction id from Redis")
            return {
                "status": "error",
                "message": "Unable to verify OTP session",
                "data": None,
            }
        if not provider_transaction_id:
            return {
                "status": "error",
                "message": "Invalid or expired transaction id",
                "data": None,
            }

        fayda = get_fayda_client()
        logger.info(
            "Verifying Fayda OTP for transaction_id=%s, provider_transaction_id=%s",
            transaction_id,
            provider_transaction_id,
        )
        result = await fayda.verify_otp(provider_transaction_id, otp, fan_or_fin)

        logger.info(
            "Fayda OTP verification result for user_id=%s, fan_or_fin=%s:",
            user_id,
            fan_or_fin,
        )
        user_data = result.get("user", {}).get("data")
        if user_data:
            if existing_claim is None:
                try:
                    await self.claim_repo.create_fan_claim(
                        user_id=user_id,
                        fan_or_fin=normalized_fan_or_fin,
                    )
                except ValueError:
                    return {
                        "status": "error",
                        "message": "This FAN has already been used for KYC verification.",
                        "data": None,
                    }

            photo_object_key: str | None = None
            photo_base64 = user_data.get("photo")
            if isinstance(photo_base64, str) and photo_base64.strip():
                try:
                    photo_bytes, content_type, extension = self._decode_base64_image(
                        photo_base64
                    )
                    photo_object_key = f"kyc/{user_id}/fayda/photo.{extension}"
                    upload_url_payload = await grpc_clients.generate_storage_upload_url(
                        actor_user_id=user_id,
                        role="user",
                        purpose="kyc",
                        object_key=photo_object_key,
                        content_type=content_type,
                        expires_in_seconds=900,
                    )
                    await self._upload_photo_via_signed_url(
                        url=upload_url_payload["url"],
                        payload=photo_bytes,
                        content_type=content_type,
                    )
                except Exception:
                    logger.exception(
                        "Failed to upload Fayda photo to object storage for user_id=%s",
                        user_id,
                    )
                    photo_object_key = None

            front_id_photo_object_key: str | None = None
            front_base64 = user_data.get("fronts")
            if isinstance(front_base64, str) and front_base64.strip():
                logger.warning(
                    "Fayda provided 'fronts' as a single string for user_id=%s, treating it as one image",
                    user_id,
                )
                try:
                    photo_bytes, content_type, extension = self._decode_base64_image(
                        front_base64
                    )
                    front_id_photo_object_key = (
                        f"kyc/{user_id}/fayda/front_id_photo.{extension}"
                    )
                    upload_url_payload = await grpc_clients.generate_storage_upload_url(
                        actor_user_id=user_id,
                        role="user",
                        purpose="kyc",
                        object_key=front_id_photo_object_key,
                        content_type=content_type,
                        expires_in_seconds=900,
                    )
                    await self._upload_photo_via_signed_url(
                        url=upload_url_payload["url"],
                        payload=photo_bytes,
                        content_type=content_type,
                    )
                except Exception:
                    logger.exception(
                        "Failed to upload Fayda photo to object storage for user_id=%s",
                        user_id,
                    )
                    front_id_photo_object_key = None

            back_id_photo_object_key: str | None = None
            back_base64 = user_data.get("backs")
            if isinstance(back_base64, str) and back_base64.strip():
                logger.warning(
                    "Fayda provided 'backs' as a single string for user_id=%s, treating it as one image",
                    user_id,
                )
                try:
                    photo_bytes, content_type, extension = self._decode_base64_image(
                        back_base64
                    )
                    back_id_photo_object_key = (
                        f"kyc/{user_id}/fayda/back_id_photo.{extension}"
                    )
                    upload_url_payload = await grpc_clients.generate_storage_upload_url(
                        actor_user_id=user_id,
                        role="user",
                        purpose="kyc",
                        object_key=back_id_photo_object_key,
                        content_type=content_type,
                        expires_in_seconds=900,
                    )
                    await self._upload_photo_via_signed_url(
                        url=upload_url_payload["url"],
                        payload=photo_bytes,
                        content_type=content_type,
                    )
                except Exception:
                    logger.exception(
                        "Failed to upload Fayda photo to object storage for user_id=%s",
                        user_id,
                    )
                    back_id_photo_object_key = None
            raw_payload = dict(user_data)
            raw_payload.pop("photo", None)
            raw_payload.pop("fronts", None)
            raw_payload.pop("backs", None)
            raw_payload.pop("UIN", None)
            raw_payload.pop("QRCodes", None)
            await self.claim_repo.upsert_identity_record(
                user_id=user_id,
                fan=user_data.get("vid") or normalized_fan_or_fin,
                full_name=user_data.get("fullName_eng")
                or user_data.get("fullName_amh"),
                phone=user_data.get("phone"),
                email=user_data.get("email"),
                photo_object_key=photo_object_key,
                front_id_object_key=front_id_photo_object_key,
                back_id_object_key=back_id_photo_object_key,
                metadata=raw_payload,
            )

            await grpc_clients.set_kyc_level(user_id, 1)
            return {
                "status": "success",
                "data": {
                    "photo_object_key": photo_object_key,
                    "front_object_key": front_id_photo_object_key,
                    "back_object_key": back_id_photo_object_key,
                },
                "message": "OTP verified successfully",
            }

        return {
            "status": "error",
            "message": result.get("error", "Failed to verify OTP"),
            "data": result,
        }

    async def get_my_photo_signed_url(self, user_id: str, role: str = "user") -> dict:
        record = await self.claim_repo.get_identity_record_by_user_id(user_id)
        if record is None or not record.photo_object_key:
            return {
                "status": "error",
                "message": "No KYC photo has been stored for this user.",
                "data": None,
            }

        signed = await grpc_clients.generate_storage_download_url(
            actor_user_id=user_id,
            role=role,
            purpose="kyc",
            object_key=record.photo_object_key,
            expires_in_seconds=900,
        )
        return {
            "status": "success",
            "message": "Signed URL generated successfully",
            "data": signed,
        }

    @staticmethod
    def _decode_base64_image(photo_base64: str) -> tuple[bytes, str, str]:
        cleaned = photo_base64.strip()
        content_type: str | None = None

        if cleaned.lower().startswith("data:") and ";base64," in cleaned:
            header, cleaned = cleaned.split(",", maxsplit=1)
            media_type = header[5:].split(";", maxsplit=1)[0].strip().lower()
            if media_type.startswith("image/"):
                content_type = media_type

        missing_padding = len(cleaned) % 4
        if missing_padding:
            cleaned += "=" * (4 - missing_padding)
        payload = base64.b64decode(cleaned)

        detected_content_type = content_type or KYCService._infer_image_content_type(
            payload
        )
        extension = KYCService._content_type_to_extension(detected_content_type)
        return payload, detected_content_type, extension

    @staticmethod
    def _infer_image_content_type(payload: bytes) -> str:
        if payload.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if payload.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if payload.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
            return "image/webp"
        if payload.startswith(b"BM"):
            return "image/bmp"
        if payload.startswith((b"II*\x00", b"MM\x00*")):
            return "image/tiff"
        raise ValueError("Unsupported or unknown base64 image format")

    @staticmethod
    def _content_type_to_extension(content_type: str) -> str:
        mapping = {
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/png": "png",
            "image/gif": "gif",
            "image/webp": "webp",
            "image/bmp": "bmp",
            "image/tiff": "tiff",
        }
        return mapping.get(content_type.lower(), "bin")

    @staticmethod
    def _normalize_base64_images(value: object) -> list[str]:
        if isinstance(value, str) and value.strip():
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, str) and item.strip()]
        return []

    @staticmethod
    async def _upload_photo_via_signed_url(
        *,
        url: str,
        payload: bytes,
        content_type: str,
    ) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(
                url,
                content=payload,
                headers={"Content-Type": content_type},
            )
            response.raise_for_status()

    async def refresh_fayda_token(self, refresh_token: str) -> dict:
        fayda = get_fayda_client()
        result = await fayda.refresh_token(refresh_token)
        if self._is_success(result):
            return {
                "status": "success",
                "data": result,
                "message": "Token refreshed successfully",
            }
        return {
            "status": "error",
            "message": result.get("error", "Failed to refresh token"),
            "data": result,
        }
