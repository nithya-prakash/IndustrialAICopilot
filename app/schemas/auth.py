import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole

Username = Annotated[str, Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")]
Password = Annotated[str, Field(min_length=8, max_length=128)]


class RegisterRequest(BaseModel):
    """Self-service sign-up creates a NEW company workspace, and the person
    signing up becomes its admin. There is deliberately no `role` field and
    no way to join an existing tenant here — `extra="forbid"` makes a
    request that tries (e.g. `"role": "admin"`) fail loudly with a 422
    rather than being silently ignored. Everyone else in a workspace is
    added by that workspace's admin via POST /api/v1/users."""

    model_config = ConfigDict(extra="forbid")

    username: Username
    email: EmailStr
    password: Password
    tenant_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")


class CreateUserRequest(BaseModel):
    """Admin-only: add a user to the admin's own workspace. The tenant is
    never taken from the request — always the calling admin's."""

    model_config = ConfigDict(extra="forbid")

    username: Username
    email: EmailStr
    password: Password
    role: UserRole = UserRole.technician


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: UserRole | None = None
    is_active: bool | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: EmailStr
    role: UserRole
    is_active: bool
    tenant_id: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
