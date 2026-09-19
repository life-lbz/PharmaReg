from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.compliance import Notification
from app.models.system import SysUser
from app.schemas.common import ok, paginate

router = APIRouter(prefix="/sys/notifications", tags=["通知"])


@router.get("")
async def list_notifications(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Notification).where(Notification.user_id == user.id)
    if status:
        query = query.where(Notification.status == status)
    count_query = select(func.count()).select_from(Notification).where(Notification.user_id == user.id)
    if status:
        count_query = count_query.where(Notification.status == status)

    total = (await db.execute(count_query)).scalar() or 0
    items_result = await db.execute(
        query.order_by(Notification.id.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    notifications = items_result.scalars().all()
    items = [
        {
            "id": n.id,
            "type": n.type,
            "title": n.title,
            "payload": n.payload,
            "channel": n.channel,
            "status": n.status,
            "trigger_at": n.trigger_at.isoformat() if n.trigger_at else None,
        }
        for n in notifications
    ]
    return ok(paginate(items, page, page_size, total))


@router.put("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        from app.core.exceptions import NotFoundError
        raise NotFoundError()
    notification.status = "read"
    await db.commit()
    return ok({"id": notification.id, "status": "read"})
