import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.auth import CreateUserRequest, UpdateUserRequest, UserResponse
from app.services.auth_service import (
    EmailTakenError,
    SelfLockoutError,
    UsernameTakenError,
    UserNotFoundError,
    create_tenant_user,
    list_tenant_users,
    update_tenant_user,
)

router = APIRouter(prefix="/api/v1/users", tags=["users"])

# User management is the only way into an existing workspace (self-service
# /auth/register always creates a new one), so it's admin-only and always
# scoped to the admin's own tenant — never a tenant from the request.
_require_admin = require_roles(UserRole.admin)


@router.get("", response_model=list[UserResponse])
async def list_all(
    admin: User = Depends(_require_admin), db: AsyncSession = Depends(get_db)
) -> list[UserResponse]:
    users = await list_tenant_users(db, tenant_id=admin.tenant_id)
    return [UserResponse.model_validate(u) for u in users]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create(
    payload: CreateUserRequest,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    try:
        user = await create_tenant_user(
            db,
            admin=admin,
            username=payload.username,
            email=payload.email,
            password=payload.password,
            role=payload.role,
        )
    except UsernameTakenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username already registered"
        ) from exc
    except EmailTakenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from exc
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update(
    user_id: uuid.UUID,
    payload: UpdateUserRequest,
    admin: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    try:
        user = await update_tenant_user(
            db, admin=admin, user_id=user_id, role=payload.role, is_active=payload.is_active
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
    except SelfLockoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't demote or deactivate your own admin account",
        ) from exc
    return UserResponse.model_validate(user)
