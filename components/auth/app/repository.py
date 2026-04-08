from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AuthSession, User


class AuthRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create_user(
        self,
        email: str,
        password_hash: str,
        first_name: str,
        last_name: str,
    ) -> User:
        user = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=password_hash,
            first_name=first_name,
            last_name=last_name,
            is_verified=False,
            role="user",
        )
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def delete_user(self, user_id: uuid.UUID) -> bool:
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return False
        await self.db.delete(user)
        await self.db.flush()
        return True

    async def set_verified(self, user_id: uuid.UUID) -> None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.is_verified = True
            self.db.add(user)
            await self.db.flush()

    async def update_password(self, user_id: uuid.UUID, new_hash: str) -> None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.password_hash = new_hash
            self.db.add(user)
            await self.db.flush()

    async def create_session(
        self,
        *,
        user_id: uuid.UUID,
        jti: str,
        role: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> AuthSession:
        session = AuthSession(
            user_id=user_id,
            jti=jti,
            role=role,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        self.db.add(session)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def list_sessions(self, user_id: uuid.UUID) -> list[AuthSession]:
        result = await self.db.execute(
            select(AuthSession)
            .where(AuthSession.user_id == user_id)
            .order_by(AuthSession.issued_at.desc())
        )
        return list(result.scalars().all())

    async def get_session_by_jti(self, jti: str) -> AuthSession | None:
        result = await self.db.execute(
            select(AuthSession).where(AuthSession.jti == jti)
        )
        return result.scalar_one_or_none()

    async def revoke_session(
        self, user_id: uuid.UUID, jti: str, revoked_at: datetime
    ) -> bool:
        result = await self.db.execute(
            select(AuthSession).where(
                AuthSession.user_id == user_id,
                AuthSession.jti == jti,
            )
        )
        session = result.scalar_one_or_none()
        if session is None:
            return False
        session.revoked_at = revoked_at
        self.db.add(session)
        await self.db.flush()
        return True
