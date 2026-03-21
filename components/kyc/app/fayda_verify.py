from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("kyc")
logging.getLogger("httpx").setLevel(logging.INFO)

_shared_client: FaydaVerify | None = None


def get_fayda_client() -> FaydaVerify:
    """Return the shared FaydaVerify client.

    Must be initialised via ``init_fayda_client()`` during app lifespan before use.
    """
    if _shared_client is None:
        raise RuntimeError("FaydaVerify client has not been initialised")
    return _shared_client


async def init_fayda_client() -> FaydaVerify:
    """Create and store the shared FaydaVerify client. Call from app lifespan."""
    global _shared_client
    _shared_client = FaydaVerify()
    return _shared_client


async def close_fayda_client() -> None:
    """Close the shared FaydaVerify client. Call from app lifespan teardown."""
    global _shared_client
    if _shared_client is not None:
        await _shared_client.close()
        _shared_client = None


class FaydaVerify:
    endpoints = {
        "sendOtp": "/api/v2/otp/send-otp",
        "verifyOtp": "/api/v2/otp/verify-otp",
        "refreshToken": "/api/v2/authentication/refresh",
    }

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        """Initialize Fayda client.

        API key/base URL are read from arguments first, then environment:
        - FAYDA_API_KEY
        - FAYDA_BASE_URL
        """
        self.api_key = api_key or os.getenv("FAYDA_API_KEY", "")
        self.base_url = base_url or os.getenv(
            "FAYDA_BASE_URL", "https://fayda-app-backend.fayda.et"
        )
        self.headers = {
            "x-api-key": self.api_key,
            "user-agent": "okhttp/4.12.0",
        }
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=httpx.Timeout(timeout=60.0, connect=30.0),
        )

    async def send_otp(self, fan_or_fin: str) -> dict:
        individual_id_type = "FAN" if len(fan_or_fin) == 16 else "FIN"
        payload = {"individualIdType": individual_id_type, "individualId": fan_or_fin}
        logger.info("Sending OTP for %s", individual_id_type)
        try:
            response = await self.client.post(self.endpoints["sendOtp"], json=payload)
            response.raise_for_status()
            logger.info(
                "OTP sent successfully for %s: %s", individual_id_type, fan_or_fin
            )
            return response.json()
        except httpx.TimeoutException:
            logger.error("Error occurred while sending OTP: request timed out")
            return {"error": "Fayda send-otp request timed out"}
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Error occurred while sending OTP: status=%s body=%s",
                exc.response.status_code,
                exc.response.text,
            )
            return {
                "error": f"Fayda send-otp failed with status {exc.response.status_code}"
            }
        except httpx.RequestError as exc:
            logger.error("Error occurred while sending OTP: %s", repr(exc))
            return {"error": f"Fayda send-otp request failed: {exc.__class__.__name__}"}

    async def verify_otp(self, transaction_id: str, otp: str, fan_or_fin: str) -> dict:
        payload = {
            "individualId": fan_or_fin,
            "otp": otp,
            "transactionId": transaction_id,
        }
        logger.info("Verifying OTP with provider transaction_id=%s", transaction_id)
        try:
            response = await self.client.post(self.endpoints["verifyOtp"], json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            logger.error("Error occurred while verifying OTP: request timed out")
            return {"error": "Fayda verify-otp request timed out"}
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Error occurred while verifying OTP: status=%s body=%s",
                exc.response.status_code,
                exc.response.text,
            )
            return {
                "error": f"Fayda verify-otp failed with status {exc.response.status_code}"
            }
        except httpx.RequestError as exc:
            logger.error("Error occurred while verifying OTP: %s", repr(exc))
            return {
                "error": f"Fayda verify-otp request failed: {exc.__class__.__name__}"
            }

    async def refresh_token(self, refresh_token: str) -> dict:
        payload = {"refreshToken": refresh_token}
        try:
            response = await self.client.post(
                self.endpoints["refreshToken"], json=payload
            )
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException:
            logger.error("Error occurred while refreshing token: request timed out")
            return {"error": "Fayda refresh-token request timed out"}
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Error occurred while refreshing token: status=%s body=%s",
                exc.response.status_code,
                exc.response.text,
            )
            return {
                "error": f"Fayda refresh-token failed with status {exc.response.status_code}"
            }
        except httpx.RequestError as exc:
            logger.error("Error occurred while refreshing token: %s", repr(exc))
            return {
                "error": f"Fayda refresh-token request failed: {exc.__class__.__name__}"
            }

    async def close(self):
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
