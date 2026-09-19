from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.exceptions import ForbiddenError
from app.db.session import get_db
from app.models.compliance import AuditLog
from app.models.system import SysUser
from app.schemas.common import ok, paginate

router = APIRouter(prefix="/sys/audit-logs", tags=["审计日志"])


@router.get("")
async def list_audit_logs(
    event_type: str | None = None,
    actor_id: int | None = None,
    object_type: str | None = None,
    action: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.auth_service import get_user_permissions
    perms = await get_user_permissions(db, user.id)
    if "sys.audit.view" not in perms:
        raise ForbiddenError()

    query = select(AuditLog).where(AuditLog.tenant_id == user.tenant_id)
    if event_type:
        query = query.where(AuditLog.event_type == event_type)
    if actor_id:
        query = query.where(AuditLog.actor_id == actor_id)
    if object_type:
        query = query.where(AuditLog.object_type == object_type)
    if action:
        query = query.where(AuditLog.action == action)

    count_query = select(func.count()).select_from(AuditLog).where(AuditLog.tenant_id == user.tenant_id)
    if event_type:
        count_query = count_query.where(AuditLog.event_type == event_type)
    if actor_id:
        count_query = count_query.where(AuditLog.actor_id == actor_id)
    if object_type:
        count_query = count_query.where(AuditLog.object_type == object_type)
    if action:
        count_query = count_query.where(AuditLog.action == action)

    total = (await db.execute(count_query)).scalar() or 0
    items_result = await db.execute(
        query.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    logs = items_result.scalars().all()
    items = [
        {
            "id": log.id,
            "event_type": log.event_type,
            "actor_id": log.actor_id,
            "action": log.action,
            "object_type": log.object_type,
            "object_id": log.object_id,
            "before": log.before,
            "after": log.after,
            "ip": log.ip,
            "hash": log.hash,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
    return ok(paginate(items, page, page_size, total))
