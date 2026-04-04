from __future__ import annotations

import uuid

import pytest
from app.models import OrgCreate
from app.repository import OrgRepository
from app.service import OrgService


@pytest.mark.asyncio
async def test_verify_secret_key_returns_org_for_valid_key(db):
    service = OrgService(OrgRepository(db))
    owner_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

    org, secret_key = await service.create_org(
        owner_id,
        OrgCreate(name="Verify Key Org", slug="verify-key-org", is_test=True),
    )
    await db.commit()

    matched = await service.verify_secret_key(secret_key)

    assert matched is not None
    assert matched.id == org.id


@pytest.mark.asyncio
async def test_verify_secret_key_returns_none_for_invalid_key(db):
    service = OrgService(OrgRepository(db))
    owner_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

    await service.create_org(
        owner_id,
        OrgCreate(name="Invalid Key Org", slug="invalid-key-org", is_test=True),
    )
    await db.commit()

    matched = await service.verify_secret_key("sk_test_invalid_value")

    assert matched is None
