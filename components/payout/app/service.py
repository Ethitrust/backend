"""Business logic for the Payout service."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status

from app import grpc_clients
from app.db import Payout
from app.messaging import publish
from app.models import PayoutRequest
from app.repository import PayoutRepository


class PayoutService:
    def __init__(self, repo: PayoutRepository) -> None:
        self.repo = repo

    async def request_payout(self, user_id: uuid.UUID, data: PayoutRequest) -> Payout:
        reference = str(uuid.uuid4())

        # Deduct balance from wallet synchronously (gRPC)
        deduct_result = await grpc_clients.deduct_wallet_balance(
            data.wallet_id, data.amount, reference
        )
        # here it should be more verbose like if invalid wallet, insufficient balance, etc. but for simplicity we just check success
        # TODO: FUTURE: Implement proper error handling based on gRPC response (e.g., distinguish between insufficient balance vs. invalid wallet)
        if not deduct_result.get("success"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="INSUFFICIENT_BALANCE",
            )

        payout = Payout(
            user_id=user_id,
            wallet_id=data.wallet_id,
            amount=data.amount,
            currency=data.currency,
            bank_code=data.bank_code,
            account_number=data.account_number,
            account_name=data.account_name,
            status="pending",
            provider=data.provider,
        )
        payout = await self.repo.create(payout)

        # Queue async bank transfer via RabbitMQ
        await publish(
            "payout.requested",
            {
                "payout_id": str(payout.id),
                "user_id": str(user_id),
                "wallet_id": str(data.wallet_id),
                "amount": data.amount,
                "currency": data.currency,
                "bank_code": data.bank_code,
                "account_number": data.account_number,
                "account_name": data.account_name,
                "provider": data.provider,
                "reference": reference,
            },
        )
        return payout

    async def process_bank_transfer(self, payout_id: uuid.UUID) -> Payout:
        """Perform the actual bank transfer (called by Celery worker or async)."""
        payout = await self.repo.get_by_id(payout_id)
        if payout is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Payout not found"
            )

        await self.repo.update_status(payout_id, "processing")

        try:
            result = await grpc_clients.initiate_bank_transfer(
                bank_code=payout.bank_code,
                account_number=payout.account_number,
                account_name=payout.account_name,
                amount=payout.amount,
                currency=payout.currency,
                reference=str(payout_id),
                provider=payout.provider or "chapa",
            )
            updated = await self.repo.update_status(
                payout_id, "success", provider_ref=result["provider_ref"]
            )
            await publish(
                "payout.success",
                {"payout_id": str(payout_id), "user_id": str(payout.user_id)},
            )
        except Exception as exc:
            reversal_succeeded = False
            reversal_error: str | None = None
            reversal_reference = f"payout-reversal-{payout_id}"

            try:
                reversal_result = await grpc_clients.credit_wallet_balance(
                    wallet_id=payout.wallet_id,
                    amount=payout.amount,
                    reference=reversal_reference,
                    currency=payout.currency,
                )
                if not reversal_result.get("success"):
                    raise RuntimeError("REVERSAL_NOT_APPLIED")
                reversal_succeeded = True
            except Exception as reversal_exc:
                reversal_error = str(reversal_exc)

            failure_reason = str(exc)
            if not reversal_succeeded:
                failure_reason = f"{failure_reason}; REVERSAL_FAILED: {reversal_error}"

            updated = await self.repo.update_status(
                payout_id, "failed", failure_reason=failure_reason
            )
            await publish(
                "payout.failed",
                {
                    "payout_id": str(payout_id),
                    "user_id": str(payout.user_id),
                    "reason": str(exc),
                    "reversal_succeeded": reversal_succeeded,
                    "reversal_error": reversal_error,
                },
            )

        return updated

    async def get_payout_status(
        self, user_id: uuid.UUID, payout_id: uuid.UUID
    ) -> Payout:
        payout = await self.repo.get_by_id(payout_id)
        if payout is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Payout not found"
            )
        if payout.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )
        return payout

    async def list_payouts(self, user_id: uuid.UUID, page: int, limit: int) -> dict:
        offset = (page - 1) * limit
        payouts, total = await self.repo.list_by_user(user_id, offset, limit)
        return {"items": payouts, "total": total, "page": page, "limit": limit}

    async def list_all_payouts(
        self,
        *,
        page: int,
        limit: int,
        status_filter: str | None,
    ) -> dict:
        offset = (page - 1) * limit
        payouts, total = await self.repo.list_all(
            offset=offset,
            limit=limit,
            status_filter=status_filter,
        )
        pages = (total + limit - 1) // limit if total else 0
        return {
            "items": payouts,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": pages,
        }
