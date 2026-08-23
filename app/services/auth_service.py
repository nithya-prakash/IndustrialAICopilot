from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_user_by_email, get_user_by_username
from app.core.security import hash_password, verify_password
from app.models.user import User, UserRole


class UsernameTakenError(Exception):
    pass


class EmailTakenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


async def register_user(
    db: AsyncSession, *, username: str, email: str, password: str, role: UserRole, tenant_id: str
) -> User:
    if await get_user_by_username(db, username) is not None:
        raise UsernameTakenError(username)
    if await get_user_by_email(db, email) is not None:
        raise EmailTakenError(email)

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        role=role,
        tenant_id=tenant_id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, *, username: str, password: str) -> User:
    user = await get_user_by_username(db, username)
    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError(username)
    return user
