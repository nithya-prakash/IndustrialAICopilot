import enum

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPkMixin


class UserRole(str, enum.Enum):
    technician = "technician"
    supervisor = "supervisor"
    admin = "admin"


class User(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.technician, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    # Scopes documents/conversations/diagnoses to an organization. Plants at the
    # same company share a knowledge base; different tenants never see each
    # other's manuals or diagnoses. No separate Organization table yet — a
    # string is enough until multi-tenant admin features are needed.
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)

    # `diagnosis_sessions` relationship is added once DiagnosisSession lands (Phase 6/7).
