"""API Gateway for Ethitrust — reverse-proxies to internal services by path prefix."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import uuid4

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

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
KYC_CACHE_ENABLED = os.getenv("KYC_CACHE_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
KYC_CACHE_TTL_SECONDS = int(os.getenv("KYC_CACHE_TTL_SECONDS", "60"))
KYC_CACHE_PREFIX = os.getenv("KYC_CACHE_PREFIX", "gateway:kyc")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

DEFAULT_UPSTREAM_TIMEOUT_SECONDS = float(
    os.getenv("GATEWAY_DEFAULT_TIMEOUT_SECONDS", "30")
)
INVOICE_TIMEOUT_SECONDS = float(os.getenv("GATEWAY_INVOICE_TIMEOUT_SECONDS", "60"))
KYC_SERVICE_TIMEOUT_SECONDS = float(os.getenv("GATEWAY_KYC_TIMEOUT_SECONDS", "10"))

RETRY_ENABLED = os.getenv("GATEWAY_RETRY_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
RETRY_MAX_ATTEMPTS = int(os.getenv("GATEWAY_RETRY_MAX_ATTEMPTS", "3"))
RETRY_BACKOFF_BASE_SECONDS = float(
    os.getenv("GATEWAY_RETRY_BACKOFF_BASE_SECONDS", "0.2")
)
RETRY_BACKOFF_MAX_SECONDS = float(os.getenv("GATEWAY_RETRY_BACKOFF_MAX_SECONDS", "1.0"))

CIRCUIT_BREAKER_ENABLED = os.getenv(
    "GATEWAY_CIRCUIT_BREAKER_ENABLED", "true"
).lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(
    os.getenv("GATEWAY_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5")
)
CIRCUIT_BREAKER_OPEN_SECONDS = float(
    os.getenv("GATEWAY_CIRCUIT_BREAKER_OPEN_SECONDS", "30")
)

_KYC_EXEMPT_PREFIXES = (
    "/auth",
    "/kyc",
    "/admin",
    "/webhooks",
    "/health",
)

# Sorted by longest prefix first to avoid shorter prefix stealing matches
_SORTED_PREFIXES = sorted(SERVICE_MAP, key=len, reverse=True)

_SERVICE_TIMEOUTS: dict[str, httpx.Timeout] = {
    "/invoice": httpx.Timeout(INVOICE_TIMEOUT_SECONDS),
    "/kyc": httpx.Timeout(KYC_SERVICE_TIMEOUT_SECONDS),
}
_TIMEOUT_PREFIXES = sorted(_SERVICE_TIMEOUTS, key=len, reverse=True)
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


@dataclass(slots=True)
class _CircuitState:
    failures: int = 0
    opened_until_monotonic: float = 0.0


def _resolve_target(path: str) -> tuple[str, str] | None:
    """Return (base_url, upstream_path) for the first matching prefix."""
    for prefix in _SORTED_PREFIXES:
        if path == prefix or path.startswith(f"{prefix}/"):
            return SERVICE_MAP[prefix], path
    return None


def _authorization_header(request: Request) -> str | None:
    return request.headers.get("Authorization")


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return token or None


def _is_probable_org_api_key(token: str) -> bool:
    # Current org secret keys use `sk_`; require no JWT-like dot separators.
    return token.startswith("sk_") and "." not in token


def _token_cache_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _kyc_cache_redis_key(token: str) -> str:
    return f"{KYC_CACHE_PREFIX}:{_token_cache_key(token)}"


async def _get_cached_kyc_level(request: Request, token: str) -> int | None:
    if not KYC_CACHE_ENABLED:
        return None

    redis_client: redis.Redis | None = request.app.state.redis_client
    if redis_client is None:
        return None

    try:
        cached_value = await redis_client.get(_kyc_cache_redis_key(token))
    except redis.RedisError:
        logger.warning("KYC redis cache read failed; falling back to user service")
        return None

    if cached_value is None:
        return None

    try:
        return int(cached_value)
    except ValueError:
        return None


async def _set_cached_kyc_level(request: Request, token: str, kyc_level: int) -> None:
    if not KYC_CACHE_ENABLED:
        return

    redis_client: redis.Redis | None = request.app.state.redis_client
    if redis_client is None:
        return

    try:
        await redis_client.set(
            _kyc_cache_redis_key(token),
            str(kyc_level),
            ex=KYC_CACHE_TTL_SECONDS,
        )
    except redis.RedisError:
        logger.warning("KYC redis cache write failed; continuing without cache")


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
    token = _extract_bearer_token(authorization)
    if token is None:
        return False
    return _is_probable_org_api_key(token)


def _resolve_timeout_for_path(path: str) -> httpx.Timeout:
    for prefix in _TIMEOUT_PREFIXES:
        if path == prefix or path.startswith(f"{prefix}/"):
            return _SERVICE_TIMEOUTS[prefix]
    return httpx.Timeout(DEFAULT_UPSTREAM_TIMEOUT_SECONDS)


def _apply_timeout_to_request(
    upstream_request: httpx.Request,
    timeout: httpx.Timeout,
) -> None:
    """Attach per-request timeout in a way compatible with httpx 0.27.x."""
    upstream_request.extensions["timeout"] = {
        "connect": timeout.connect,
        "read": timeout.read,
        "write": timeout.write,
        "pool": timeout.pool,
    }


def _get_header_case_insensitive(headers: dict[str, str], name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return None


def _append_forwarded_for(
    existing_value: str | None, client_ip: str | None
) -> str | None:
    if not client_ip:
        return existing_value
    if not existing_value:
        return client_ip
    return f"{existing_value}, {client_ip}"


def _apply_forwarding_headers(request: Request, req_headers: dict[str, str]) -> None:
    existing_xff = _get_header_case_insensitive(req_headers, "X-Forwarded-For")
    req_headers["X-Forwarded-For"] = (
        _append_forwarded_for(
            existing_xff,
            request.client.host if request.client else None,
        )
        or ""
    )

    request_id = _get_header_case_insensitive(req_headers, "X-Request-ID")
    req_headers["X-Request-ID"] = request_id or str(uuid4())
    req_headers["X-Forwarded-Proto"] = request.url.scheme

    host_header = _get_header_case_insensitive(req_headers, "Host")
    req_headers["X-Forwarded-Host"] = host_header or request.url.hostname or ""


def _is_retryable_method(method: str) -> bool:
    return method.upper() in _IDEMPOTENT_METHODS


def _circuit_is_open(state: _CircuitState) -> bool:
    return state.opened_until_monotonic > time.monotonic()


def _record_circuit_success(state: _CircuitState) -> None:
    state.failures = 0
    state.opened_until_monotonic = 0.0


def _record_circuit_failure(state: _CircuitState) -> None:
    state.failures += 1
    if state.failures >= CIRCUIT_BREAKER_FAILURE_THRESHOLD:
        state.opened_until_monotonic = time.monotonic() + CIRCUIT_BREAKER_OPEN_SECONDS


async def _send_with_resilience(
    request: Request,
    client: httpx.AsyncClient,
    upstream_request: httpx.Request,
    *,
    service_prefix: str,
    timeout: httpx.Timeout,
) -> httpx.Response:
    method = upstream_request.method.upper()
    retryable = RETRY_ENABLED and _is_retryable_method(method)
    max_attempts = max(1, RETRY_MAX_ATTEMPTS if retryable else 1)

    circuit_map: dict[str, _CircuitState] = request.app.state.circuit_breakers
    state = circuit_map.setdefault(service_prefix, _CircuitState())

    if CIRCUIT_BREAKER_ENABLED and _circuit_is_open(state):
        raise HTTPException(
            status_code=503,
            detail=f"Service temporarily unavailable for {service_prefix}",
        )

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            _apply_timeout_to_request(upstream_request, timeout)
            response = await client.send(
                upstream_request,
                stream=True,
            )

            if retryable and response.status_code >= 500 and attempt < max_attempts:
                await response.aclose()
                delay = min(
                    RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
                    RETRY_BACKOFF_MAX_SECONDS,
                )
                await asyncio.sleep(delay)
                continue

            _record_circuit_success(state)
            return response
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            _record_circuit_failure(state)

            if attempt >= max_attempts:
                break

            delay = min(
                RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
                RETRY_BACKOFF_MAX_SECONDS,
            )
            await asyncio.sleep(delay)

    if isinstance(last_exc, httpx.TimeoutException):
        raise HTTPException(
            status_code=504, detail="Upstream service timed out"
        ) from last_exc
    if isinstance(last_exc, httpx.ConnectError):
        raise HTTPException(
            status_code=502,
            detail="Could not connect to upstream service",
        ) from last_exc
    raise HTTPException(status_code=502, detail="Upstream service request failed")


async def _enforce_kyc_if_required(request: Request) -> None:
    if not KYC_ENFORCEMENT_ENABLED:
        return

    method = request.method.upper()
    path = request.url.path

    if _is_kyc_exempt_path(path, method):
        return

    authorization = _authorization_header(request)
    token = _extract_bearer_token(authorization)
    if token is None:
        return

    if _is_org_api_key_escrow_create(path, method, authorization):
        return

    cached_kyc = await _get_cached_kyc_level(request, token)
    if cached_kyc is not None:
        if cached_kyc < KYC_MIN_LEVEL:
            raise HTTPException(
                status_code=403,
                detail=(
                    "KYC verification is required before accessing this resource. "
                    "Please complete KYC first."
                ),
            )
        return

    client: httpx.AsyncClient = request.app.state.http_client
    try:
        profile_response = await client.get(
            f"{USER_SERVICE_URL.rstrip('/')}/users/me",
            headers={"Authorization": authorization},
            timeout=_resolve_timeout_for_path("/users/me"),
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

    try:
        profile = profile_response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail="Unable to verify KYC status at this time",
        ) from exc

    kyc_level = int(profile.get("kyc_level", 0))
    await _set_cached_kyc_level(request, token, kyc_level)
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
    application.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(DEFAULT_UPSTREAM_TIMEOUT_SECONDS)
    )
    application.state.redis_client = (
        redis.from_url(REDIS_URL, decode_responses=True) if KYC_CACHE_ENABLED else None
    )
    application.state.circuit_breakers = {}
    logger.info("Gateway starting — routing %d services", len(SERVICE_MAP))
    yield
    redis_client: redis.Redis | None = application.state.redis_client
    if redis_client is not None:
        await redis_client.aclose()
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
    _apply_forwarding_headers(request, req_headers)

    client: httpx.AsyncClient = request.app.state.http_client
    timeout = _resolve_timeout_for_path(upstream_path)
    upstream_request = client.build_request(
        method=request.method,
        url=target_url,
        headers=req_headers,
        content=request.stream(),
    )

    try:
        upstream_response = await _send_with_resilience(
            request,
            client,
            upstream_request,
            service_prefix=upstream_path.split("/")[1]
            and f"/{upstream_path.split('/')[1]}",
            timeout=timeout,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502, detail="Could not proxy upstream request"
        ) from exc

    # Filter hop-by-hop response headers
    res_headers = {
        k: v
        for k, v in upstream_response.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }

    return StreamingResponse(
        upstream_response.aiter_bytes(),
        status_code=upstream_response.status_code,
        headers=res_headers,
        background=BackgroundTask(upstream_response.aclose),
    )


@app.get("/health", tags=["health"], include_in_schema=False)
async def health() -> dict:
    return {"status": "ok", "service": "gateway", "routes": len(SERVICE_MAP)}
