import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import WebhookLog
from app.models import OutgoingEventPayload
from app.repository import WebhookRepository

CHAPA_SECRET = os.getenv("CHAPA_WEBHOOK_SECRET", "")
CHAPA_WEBHOOK_SECRET_HASH = os.getenv("CHAPA_WEBHOOK_SECRET_HASH", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")


class WebhookService:
    def __init__(self, repo: WebhookRepository):
        self.repo = repo

    @staticmethod
    def _payment_completed_payload(
        reference: str,
        amount: int,
        currency: str,
        metadata: dict | None = None,
    ) -> dict:
        payload = {
            "reference": reference,
            # Backward compatibility for consumers still reading transaction_ref
            "transaction_ref": reference,
            "amount": amount,
            "currency": currency,
        }
        if metadata:
            payload["metadata"] = metadata
            wallet_id = metadata.get("wallet_id")
            if wallet_id:
                payload["wallet_id"] = wallet_id
        return payload

    async def handle_chapa_event(self, payload: bytes, signature: str) -> dict:
        """Verify HMAC, parse event, publish internal event via RabbitMQ."""
        secret = CHAPA_WEBHOOK_SECRET_HASH
        computed = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
        if not hmac.compare_digest(computed, signature):
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

        data = json.loads(payload)
        event_type = data.get("event", "unknown")
        await self.repo.save_log(
            direction="incoming", event=event_type, payload=data, status="received"
        )

        from app.messaging import publish

        if event_type == "charge.success":
            payment_data = data.get("data", {})
            await publish(
                "payment.completed",
                self._payment_completed_payload(
                    reference=payment_data["reference"],
                    amount=int(payment_data["amount"]),
                    currency=payment_data["currency"],
                    metadata=payment_data.get("meta") or payment_data.get("metadata"),
                ),
            )
        elif event_type == "transfer.success":
            await publish("payout.completed", {"reference": data["data"]["reference"]})
        elif event_type == "transfer.failed":
            await publish(
                "payout.failed",
                {
                    "reference": data["data"]["reference"],
                    "reason": data["data"].get("gateway_response", ""),
                },
            )

        return {"status": "processed"}

    async def handle_stripe_event(self, payload: bytes, signature: str) -> dict:
        """Verify Stripe timestamp-based HMAC signature, parse event."""
        parts = dict(item.split("=", 1) for item in signature.split(",") if "=" in item)
        timestamp = parts.get("t", "")
        v1 = parts.get("v1", "")
        signed_payload = f"{timestamp}.{payload.decode()}"
        computed = hmac.new(
            STRIPE_WEBHOOK_SECRET.encode(),
            signed_payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(computed, v1):
            raise HTTPException(
                status_code=400, detail="Invalid Stripe webhook signature"
            )

        data = json.loads(payload)
        event_type = data.get("type", "unknown")
        await self.repo.save_log(
            direction="incoming", event=event_type, payload=data, status="received"
        )

        from app.messaging import publish

        if event_type == "payment_intent.succeeded":
            obj = data["data"]["object"]
            meta = obj.get("metadata", {})
            await publish(
                "payment.completed",
                self._payment_completed_payload(
                    reference=meta.get("reference", ""),
                    amount=int(obj["amount"]),
                    currency=obj["currency"],
                    metadata=meta,
                ),
            )

        return {"status": "processed"}

    async def dispatch_event(
        self,
        event_type: str,
        data: dict,
        org_id: uuid.UUID | None,
    ) -> None:
        """Queue outgoing webhook delivery to org's webhook URL via RabbitMQ."""
        payload = OutgoingEventPayload(
            event=event_type,
            data=data,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ).model_dump()

        from app.messaging import publish

        await publish(
            "webhook.outgoing",
            {
                "event_type": event_type,
                "payload": payload,
                "org_id": str(org_id) if org_id else None,
            },
        )

    @staticmethod
    def verify_signature(payload: bytes, sig: str, secret: str) -> bool:
        """Verify an HMAC-SHA256 signature against a payload and shared secret."""
        computed = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed, sig)

    async def deliver_webhook(
        self,
        log_id: uuid.UUID,
        target_url: str,
        payload: dict,
        secret: str,
    ) -> bool:
        """Deliver outgoing webhook with HMAC signature. Returns True on success."""
        import httpx

        sig = hmac.new(
            secret.encode(), json.dumps(payload).encode(), hashlib.sha256
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Ethitrust-Signature": sig,
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(
                target_url, json=payload, headers=headers, timeout=10.0
            )
            return r.status_code < 400
