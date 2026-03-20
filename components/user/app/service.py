import uuid

from fastapi import HTTPException, status

from app.db import User
from app.models import UserUpdateRequest
from app.repository import UserRepository


class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self.repo = repo

    async def get_by_id(self, user_id: uuid.UUID) -> User:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User {user_id} not found",
            )
        return user

    async def get_by_email(self, email: str) -> User | None:
        return await self.repo.get_by_email(email)

    async def update_profile(self, user_id: uuid.UUID, data: UserUpdateRequest) -> User:
        user = await self.get_by_id(user_id)
        update_data = data.model_dump(exclude_none=True)
        return await self.repo.update(user, update_data)

    async def set_kyc_level(self, user_id: uuid.UUID, level: int) -> User:
        if level < 0 or level > 3:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="KYC level must be between 0 and 3",
            )
        user = await self.get_by_id(user_id)
        return await self.repo.update(user, {"kyc_level": level})

    async def ban_user(self, user_id: uuid.UUID, ban: bool) -> User:
        user = await self.get_by_id(user_id)
        return await self.repo.update(user, {"is_banned": ban})

    async def change_role(self, user_id: uuid.UUID, role: str) -> User:
        allowed_roles = {"user", "moderator", "admin"}
        if role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Role must be one of {allowed_roles}",
            )
        user = await self.get_by_id(user_id)
        return await self.repo.update(user, {"role": role})
