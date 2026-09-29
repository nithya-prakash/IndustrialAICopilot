import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_user_by_email, get_user_by_username
from app.core.security import hash_password, verify_password
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.audit_service import log_event


class UsernameTakenError(Exception):
    pass


class EmailTakenError(Exception):
    pass


class TenantTakenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class UserNotFoundError(Exception):
    pass


class SelfLockoutError(Exception):
    """An admin tried to demote or deactivate their own account — refused so
    a workspace can't be left with nobody able to manage it by accident."""


async def _ensure_unique(db: AsyncSession, *, username: str, email: str) -> None:
    if await get_user_by_username(db, username) is not None:
        raise UsernameTakenError(username)
    if await get_user_by_email(db, email) is not None:
        raise EmailTakenError(email)


async def _commit_new_user(db: AsyncSession, user: User, *, username: str) -> User:
    try:
        await db.commit()
    except IntegrityError as exc:
        # The pre-checks above can race with a concurrent request for the
        # same username/email; the unique indexes are the real guarantee.
        await db.rollback()
        raise UsernameTakenError(username) from exc
    await db.refresh(user)
    return user


async def register_workspace(
    db: AsyncSession, *, username: str, email: str, password: str, tenant_id: str
) -> User:
    """Self-service sign-up: creates a brand-new tenant and makes the caller
    its admin. Joining an existing tenant is never possible from here — that
    is what an admin's POST /api/v1/users is for — so nobody can put
    themselves into someone else's company, at any role."""
    await _ensure_unique(db, username=username, email=email)
    if await db.get(Tenant, tenant_id) is not None:
        raise TenantTakenError(tenant_id)

    db.add(Tenant(id=tenant_id))
    try:
        # Flushed on its own first so a concurrent sign-up for the same
        # tenant fails here on the primary key, distinguishable from a
        # username/email collision at the user insert below.
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise TenantTakenError(tenant_id) from exc

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        role=UserRole.admin,
        tenant_id=tenant_id,
    )
    db.add(user)
    await db.flush()
    await log_event(
        db,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="tenant.created",
        resource_type="tenant",
        resource_id=tenant_id,
        detail={"admin_username": username},
    )
    return await _commit_new_user(db, user, username=username)


async def create_tenant_user(
    db: AsyncSession,
    *,
    admin: User,
    username: str,
    email: str,
    password: str,
    role: UserRole,
) -> User:
    await _ensure_unique(db, username=username, email=email)
    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        role=role,
        tenant_id=admin.tenant_id,
    )
    db.add(user)
    await db.flush()
    await log_event(
        db,
        tenant_id=admin.tenant_id,
        actor_user_id=admin.id,
        action="user.created",
        resource_type="user",
        resource_id=user.id,
        detail={"username": username, "role": role.value},
    )
    return await _commit_new_user(db, user, username=username)


async def list_tenant_users(db: AsyncSession, *, tenant_id: str) -> list[User]:
    result = await db.execute(
        select(User).where(User.tenant_id == tenant_id).order_by(User.created_at)
    )
    return list(result.scalars().all())


async def update_tenant_user(
    db: AsyncSession,
    *,
    admin: User,
    user_id: uuid.UUID,
    role: UserRole | None,
    is_active: bool | None,
) -> User:
    user = await db.get(User, user_id)
    # Another tenant's user is reported exactly like a nonexistent one, so the
    # response can't be used to probe which user IDs exist elsewhere.
    if user is None or user.tenant_id != admin.tenant_id:
        raise UserNotFoundError(str(user_id))
    if user.id == admin.id and (
        (role is not None and role != UserRole.admin) or is_active is False
    ):
        raise SelfLockoutError()

    changes: dict[str, str | bool] = {}
    if role is not None and role != user.role:
        changes["role"] = role.value
        user.role = role
    if is_active is not None and is_active != user.is_active:
        changes["is_active"] = is_active
        user.is_active = is_active

    if changes:
        await log_event(
            db,
            tenant_id=admin.tenant_id,
            actor_user_id=admin.id,
            action="user.updated",
            resource_type="user",
            resource_id=user.id,
            detail=changes,
        )
        await db.commit()
        await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, *, username: str, password: str) -> User:
    user = await get_user_by_username(db, username)
    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError(username)
    return user
