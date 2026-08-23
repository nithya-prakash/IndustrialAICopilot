from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.audit import AuditLogResponse
from app.services.audit_service import list_audit_logs

router = APIRouter(prefix="/api/v1/audit-logs", tags=["audit"])

_require_admin = require_roles(UserRole.admin)


@router.get("", response_model=list[AuditLogResponse])
async def list_all(
    resource_type: str | None = None,
    resource_id: str | None = None,
    user: User = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[AuditLogResponse]:
    logs = await list_audit_logs(
        db, tenant_id=user.tenant_id, resource_type=resource_type, resource_id=resource_id
    )
    return [
        AuditLogResponse(
            id=log.id,
            actor_user_id=log.actor_user_id,
            action=log.action,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            detail=log.detail or {},
            created_at=log.created_at,
        )
        for log in logs
    ]
