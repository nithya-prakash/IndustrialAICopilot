from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import utcnow


class Tenant(Base):
    """A company workspace. Exists so "who owns this tenant ID" is a
    database fact with a primary-key uniqueness guarantee, not an
    application-level "does any user have this tenant_id yet" check — two
    concurrent sign-ups for the same new workspace can't both win, because
    the second INSERT fails on the primary key.

    Other tables keep their plain `tenant_id` string column rather than a
    foreign key to this one: the isolation boundary is still the
    authenticated user's own `tenant_id`, this table only decides who gets
    to create one (see app/services/auth_service.py:register_workspace)."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
