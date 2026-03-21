"""Repository for KYC identity claim persistence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import KYCFanClaim, KYCIdentityRecord, async_session_factory


class KYCClaimRepository:
    async def get_fan_claim(self, fan_or_fin: str) -> KYCFanClaim | None:
        async with async_session_factory() as session:
            result = await session.execute(
                select(KYCFanClaim).where(KYCFanClaim.fan == fan_or_fin)
            )
            return result.scalar_one_or_none()

    async def create_fan_claim(self, user_id: str, fan_or_fin: str) -> KYCFanClaim:
        claim = KYCFanClaim(user_id=uuid.UUID(user_id), fan=fan_or_fin)
        async with async_session_factory() as session:
            session.add(claim)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise ValueError("FAN_OR_FIN_ALREADY_CLAIMED") from exc
            await session.refresh(claim)
            return claim

    async def upsert_identity_record(
        self,
        *,
        user_id: str,
        fan: str,
        full_name: str | None,
        phone: str | None,
        email: str | None,
        photo_object_key: str | None,
        front_id_object_key: str | None,
        back_id_object_key: str | None,
        metadata: dict,
    ) -> KYCIdentityRecord:
        user_uuid = uuid.UUID(user_id)
        async with async_session_factory() as session:
            result = await session.execute(
                select(KYCIdentityRecord).where(KYCIdentityRecord.user_id == user_uuid)
            )
            record = result.scalar_one_or_none()
            if record is None:
                record = KYCIdentityRecord(
                    user_id=user_uuid,
                    fan=fan,
                    full_name=full_name,
                    phone=phone,
                    email=email,
                    photo_object_key=photo_object_key,
                    front_id_object_key=front_id_object_key,
                    back_id_object_key=back_id_object_key,
                    meta=metadata,
                )
                session.add(record)
            else:
                record.fan = fan
                record.full_name = full_name
                record.phone = phone
                record.email = email
                record.photo_object_key = photo_object_key
                record.front_id_object_key = front_id_object_key
                record.back_id_object_key = back_id_object_key
                record.meta = metadata
                session.add(record)

            await session.commit()
            await session.refresh(record)
            return record

    async def get_identity_record_by_user_id(
        self, user_id: str
    ) -> KYCIdentityRecord | None:
        user_uuid = uuid.UUID(user_id)
        async with async_session_factory() as session:
            result = await session.execute(
                select(KYCIdentityRecord).where(KYCIdentityRecord.user_id == user_uuid)
            )
            return result.scalar_one_or_none()
