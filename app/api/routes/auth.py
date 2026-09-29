from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.deps import get_current_user, get_token_claims
from app.core.rate_limit import limiter
from app.core.security import create_access_token
from app.core.token_blocklist import revoke_token
from app.database import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.auth_service import (
    EmailTakenError,
    InvalidCredentialsError,
    TenantTakenError,
    UsernameTakenError,
    authenticate_user,
    register_workspace,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_settings = get_settings()


@router.get("/me", response_model=UserResponse)
async def read_current_user(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(claims: dict[str, Any] = Depends(get_token_claims)) -> None:
    """Revokes the presented token via the Redis blocklist (app/core/token_blocklist.py)
    so it can't be used again before its own expiry — access tokens are
    otherwise stateless/unrevocable once issued."""
    jti = claims.get("jti")
    exp = claims.get("exp")
    if jti and exp:
        await revoke_token(jti, datetime.fromtimestamp(exp, tz=UTC))


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(_settings.rate_limit_auth)
async def register(
    request: Request, payload: RegisterRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    """Creates a new company workspace with the caller as its admin — see
    RegisterRequest. Other users are added by that admin via /api/v1/users."""
    try:
        user = await register_workspace(
            db,
            username=payload.username,
            email=payload.email,
            password=payload.password,
            tenant_id=payload.tenant_id,
        )
    except TenantTakenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workspace already exists — ask its admin to add you",
        ) from exc
    except UsernameTakenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username already registered"
        ) from exc
    except EmailTakenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from exc

    token = create_access_token(subject=user.id, role=user.role.value)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/login", response_model=TokenResponse)
@limiter.limit(_settings.rate_limit_auth)
async def login(
    request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    try:
        user = await authenticate_user(db, username=payload.username, password=payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password"
        ) from exc

    token = create_access_token(subject=user.id, role=user.role.value)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))
