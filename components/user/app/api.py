import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app import grpc_clients
from app.db import get_db
from app.models import UserResponse, UserUpdateRequest
from app.repository import UserRepository
from app.service import UserService

router = APIRouter(prefix="/users", tags=["users"])

security = HTTPBearer(auto_error=False)


async def get_current_user(
    authorization: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> dict:
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    try:
        user = await grpc_clients.validate_token(authorization.credentials)
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    return user


def get_service(db: Annotated[AsyncSession, Depends(get_db)]) -> UserService:
    return UserService(UserRepository(db))


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[dict, Depends(get_current_user)],
    service: Annotated[UserService, Depends(get_service)],
) -> UserResponse:
    user = await service.get_by_id(uuid.UUID(current_user["user_id"]))
    return UserResponse.model_validate(user)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: UserUpdateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    service: Annotated[UserService, Depends(get_service)],
) -> UserResponse:
    user = await service.update_profile(uuid.UUID(current_user["user_id"]), body)
    return UserResponse.model_validate(user)
