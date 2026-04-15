from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

try:
    from app.db import AsyncSessionLocal
    from app.grpc_clients import (
        sync_user,
        update_email_verification_status,
        update_user_role,
    )
    from app.repository import AuthRepository
    from app.security import hash_password
except ModuleNotFoundError:
    script_dir = Path(__file__).resolve().parent
    component_root = script_dir.parent
    if str(component_root) not in sys.path:
        sys.path.insert(0, str(component_root))
    from app.db import AsyncSessionLocal
    from app.grpc_clients import (
        sync_user,
        update_email_verification_status,
        update_user_role,
    )
    from app.repository import AuthRepository
    from app.security import hash_password

logger = logging.getLogger(__name__)


async def create_or_promote_admin(
    *,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    dry_run: bool,
) -> tuple[str, str]:
    normalized_email = email.strip().lower()
    if not normalized_email:
        raise ValueError("email is required")

    if not password:
        raise ValueError("password is required")

    async with AsyncSessionLocal() as session:
        repo = AuthRepository(session)
        user = await repo.get_by_email(normalized_email)
        action = "promoted"

        if user is None:
            user = await repo.create_user(
                email=normalized_email,
                password_hash=hash_password(password),
                first_name=first_name,
                last_name=last_name,
            )
            action = "created"

        user.role = "admin"
        user.is_verified = True
        session.add(user)

        if dry_run:
            await session.rollback()
            logger.info(
                "[dry-run] would_%s_admin email=%s user_id=%s",
                action,
                normalized_email,
                user.id,
            )
            return action, str(user.id)

        try:
            if action == "created":
                await sync_user(
                    user_id=str(user.id),
                    email=user.email,
                    password_hash=user.password_hash,
                    first_name=user.first_name,
                    last_name=user.last_name,
                    role=user.role,
                    is_verified=user.is_verified,
                    is_banned=user.is_banned,
                    kyc_level=1,
                    otp="",
                )
            else:
                await update_user_role(user_id=str(user.id), role="admin")
                await update_email_verification_status(
                    user_id=str(user.id),
                    is_verified=True,
                )

            await session.commit()
        except Exception:
            await session.rollback()
            raise

    logger.info(
        "%s_admin_success email=%s user_id=%s",
        action,
        normalized_email,
        user.id,
    )
    return action, str(user.id)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or promote an admin user in the Auth service",
    )
    parser.add_argument("-e", "--email", required=True, help="Admin email")
    parser.add_argument("-p", "--password", required=True, help="Admin password")
    parser.add_argument("-f", "--first-name", required=True, help="First name")
    parser.add_argument("-l", "--last-name", required=True, help="Last name")
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Preview operation without committing changes",
    )
    return parser.parse_args()


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    action, user_id = await create_or_promote_admin(
        email=args.email,
        password=args.password,
        first_name=args.first_name,
        last_name=args.last_name,
        dry_run=args.dry_run,
    )
    logger.info("done action=%s user_id=%s", action, user_id)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
