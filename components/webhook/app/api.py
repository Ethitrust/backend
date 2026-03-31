import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.grpc_clients import validate_token
from app.models import DispatchEventRequest, WebhookLogResponse
from app.repository import WebhookRepository
from app.service import WebhookService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])


def get_service(db: AsyncSession = Depends(get_db)) -> WebhookService:
    return WebhookService(repo=WebhookRepository(db))


@router.post("/chapa", status_code=200)
async def receive_chapa(
    request: Request,
    x_chapa_signature: Annotated[str | None, Header()] = None,
    svc: WebhookService = Depends(get_service),
) -> dict:
    """Receive and verify incoming Chapa webhook events."""
    if not x_chapa_signature:
        raise HTTPException(status_code=400, detail="Missing x-chapa-signature header")
    payload = await request.body()
    return await svc.handle_chapa_event(payload, x_chapa_signature)


# @router.post("/stripe", status_code=200)
# async def receive_stripe(
#     request: Request,
#     stripe_signature: Annotated[str | None, Header()] = None,
#     svc: WebhookService = Depends(get_service),
# ) -> dict:
#     """Receive and verify incoming Stripe webhook events."""
#     if not stripe_signature:
#         raise HTTPException(status_code=400, detail="Missing stripe-signature header")
#     payload = await request.body()
#     return await svc.handle_stripe_event(payload, stripe_signature)


@router.post("/dispatch", status_code=202)
async def dispatch_outgoing_event(
    body: DispatchEventRequest,
    authorization: Annotated[str | None, Header()] = None,
    svc: WebhookService = Depends(get_service),
) -> dict:
    """Internal endpoint: dispatch an outgoing webhook event to org subscribers."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    claims = await validate_token(token)
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    await svc.dispatch_event(
        event_type=body.event_type,
        data=body.data,
        org_id=body.org_id,
    )
    return {"status": "queued", "event_type": body.event_type}


@router.get("/logs", response_model=list[WebhookLogResponse])
async def get_webhook_logs(
    offset: int = 0,
    limit: int = 50,
    authorization: Annotated[str | None, Header()] = None,
    svc: WebhookService = Depends(get_service),
) -> list[WebhookLogResponse]:
    """Admin: list webhook logs (paginated)."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    claims = await validate_token(token)
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    logs = await svc.repo.get_logs(offset=offset, limit=limit)
    return [WebhookLogResponse.model_validate(log) for log in logs]
