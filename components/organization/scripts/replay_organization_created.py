from __future__ import annotations

import argparse
import asyncio
import logging

from app.db import AsyncSessionLocal, Organization
from app.messaging import publish
from sqlalchemy import select

logger = logging.getLogger(__name__)


async def replay_organization_created(*, dry_run: bool) -> int:
    """Replay organization.created events for existing organizations.

    This script is safe to re-run because wallet auto-creation is idempotent.
    """
    emitted = 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Organization.id, Organization.owner_id))
        rows = result.all()

    for org_id, owner_id in rows:
        payload = {"org_id": str(org_id), "owner_id": str(owner_id)}
        if dry_run:
            logger.info("[dry-run] organization.created %s", payload)
        else:
            await publish("organization.created", payload)
            logger.info("organization.created emitted %s", payload)
        emitted += 1

    return emitted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay organization.created events for existing organizations",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print events without publishing to RabbitMQ",
    )
    return parser.parse_args()


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    count = await replay_organization_created(dry_run=args.dry_run)
    logger.info("Done. processed=%s", count)


if __name__ == "__main__":
    asyncio.run(_main())
