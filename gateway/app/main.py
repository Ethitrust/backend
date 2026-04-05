"""API Gateway for Ethitrust — reverse-proxies to internal services by path prefix."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Service map: path prefix → base URL
SERVICE_MAP: dict[str, str] = {
    "/auth": os.getenv("AUTH_SERVICE_URL", "http://auth-service:8000"),
    "/users": os.getenv("USER_SERVICE_URL", "http://user-service:8000"),
    "/wallet": os.getenv("WALLET_SERVICE_URL", "http://wallet-service:8000"),
    "/escrow": os.getenv("ESCROW_SERVICE_URL", "http://escrow-service:8000"),
    "/invoice": os.getenv("INVOICE_SERVICE_URL", "http://invoice-service:8000"),
    "/payment-link": os.getenv(
        "PAYMENT_LINK_SERVICE_URL", "http://payment-link-service:8000"
    ),
    "/payout": os.getenv("PAYOUT_SERVICE_URL", "http://payout-service:8000"),
    "/kyc": os.getenv("KYC_SERVICE_URL", "http://kyc-service:8000"),
    "/dispute": os.getenv("DISPUTE_SERVICE_URL", "http://dispute-service:8000"),
    "/notifications": os.getenv(
        "NOTIFICATION_SERVICE_URL", "http://notification-service:8000"
    ),
    "/audit": os.getenv("AUDIT_SERVICE_URL", "http://audit-service:8000"),
    "/fee": os.getenv("FEE_SERVICE_URL", "http://fee-service:8000"),
    "/admin": os.getenv("ADMIN_SERVICE_URL", "http://admin-service:8000"),
    "/banks": os.getenv("BANK_SERVICE_URL", "http://bank-service:8000"),
    "/org": os.getenv("ORGANIZATION_SERVICE_URL", "http://organization-service:8000"),
    "/providers": os.getenv(
        "PAYMENT_PROVIDER_URL", "http://payment-provider-service:8000"
    ),
    "/webhooks": os.getenv("WEBHOOK_SERVICE_URL", "http://webhook-service:8000"),
}

USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user-service:8000")
KYC_ENFORCEMENT_ENABLED = os.getenv("KYC_ENFORCEMENT_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
KYC_MIN_LEVEL = int(os.getenv("KYC_MIN_LEVEL", "1"))

_KYC_EXEMPT_PREFIXES = (
    "/auth",
    "/kyc",
    "/admin",
    "/webhooks",
    "/health",
)

# Sorted by longest prefix first to avoid shorter prefix stealing matches
_SORTED_PREFIXES = sorted(SERVICE_MAP, key=len, reverse=True)


def _resolve_target(path: str) -> tuple[str, str] | None:
    """Return (base_url, upstream_path) for the first matching prefix."""
    for prefix in _SORTED_PREFIXES:
        if path == prefix or path.startswith(f"{prefix}/"):
            return SERVICE_MAP[prefix], path
    return None


def _authorization_header(request: Request) -> str | None:
    return request.headers.get("Authorization")


def _is_kyc_exempt_path(path: str, method: str) -> bool:
    if any(path.startswith(prefix) for prefix in _KYC_EXEMPT_PREFIXES):
        return True

    if path == "/users/me" and method in {"GET", "PATCH"}:
        return True

    return False


def _is_org_api_key_escrow_create(
    path: str,
    method: str,
    authorization: str | None,
) -> bool:
    if path != "/escrow" or method != "POST":
        return False
    if not authorization or not authorization.startswith("Bearer "):
        return False
    token = authorization.removeprefix("Bearer ").strip()
    return token.startswith("sk_")


async def _enforce_kyc_if_required(request: Request) -> None:
    if not KYC_ENFORCEMENT_ENABLED:
        return

    method = request.method.upper()
    path = request.url.path

    if _is_kyc_exempt_path(path, method):
        return

    authorization = _authorization_header(request)
    if not authorization or not authorization.startswith("Bearer "):
        return

    if _is_org_api_key_escrow_create(path, method, authorization):
        return

    client: httpx.AsyncClient = request.app.state.http_client
    try:
        profile_response = await client.get(
            f"{USER_SERVICE_URL.rstrip('/')}/users/me",
            headers={"Authorization": authorization},
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="KYC check timed out",
        ) from exc
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not connect to user service for KYC check",
        ) from exc

    if profile_response.status_code == 401:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
        )
    if profile_response.status_code >= 500:
        raise HTTPException(
            status_code=503,
            detail="Unable to verify KYC status at this time",
        )
    if profile_response.status_code != 200:
        raise HTTPException(
            status_code=403,
            detail="Unable to verify KYC status for this account",
        )

    profile = profile_response.json()
    kyc_level = int(profile.get("kyc_level", 0))
    if kyc_level < KYC_MIN_LEVEL:
        raise HTTPException(
            status_code=403,
            detail=(
                "KYC verification is required before accessing this resource. "
                "Please complete KYC first."
            ),
        )


@asynccontextmanager
async def lifespan(application: FastAPI):  # noqa: ANN001
    application.state.http_client = httpx.AsyncClient(timeout=30.0)
    logger.info("Gateway starting — routing %d services", len(SERVICE_MAP))
    yield
    await application.state.http_client.aclose()
    logger.info("Gateway shut down")


app = FastAPI(title="Ethitrust API Gateway", version="0.1.0", lifespan=lifespan)

# Hop-by-hop headers that must not be forwarded
_HOP_BY_HOP = frozenset(
    [
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    ]
)


@app.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]
)
async def proxy(request: Request, path: str) -> Response:
    await _enforce_kyc_if_required(request)

    full_path = f"/{path}"
    target = _resolve_target(full_path)
    if target is None:
        raise HTTPException(
            status_code=404, detail=f"No service found for path: {full_path}"
        )

    base_url, upstream_path = target
    target_url = f"{base_url.rstrip('/')}{upstream_path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    # Filter hop-by-hop request headers
    req_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() != "host"
    }

    body = await request.body()
    client: httpx.AsyncClient = request.app.state.http_client

    try:
        upstream_response = await client.request(
            method=request.method,
            url=target_url,
            headers=req_headers,
            content=body,
        )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream service timed out")
    except httpx.ConnectError:
        raise HTTPException(
            status_code=502, detail="Could not connect to upstream service"
        )

    # Filter hop-by-hop response headers
    res_headers = {
        k: v
        for k, v in upstream_response.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=res_headers,
    )


@app.get("/health", tags=["health"], include_in_schema=False)
async def health() -> dict:
    return {"status": "ok", "service": "gateway", "routes": len(SERVICE_MAP)}
