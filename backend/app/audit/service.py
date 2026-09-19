import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.compliance import AuditLog


def compute_hash(prev_hash: str | None, timestamp: str, actor_id: int | None, action: str, payload: str) -> str:
    raw = f"{prev_hash or ''}{timestamp}{actor_id or ''}{action}{payload}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def write_audit(
    db: AsyncSession,
    event_type: str,
    action: str,
    actor_id: int | None = None,
    object_type: str | None = None,
    object_id: int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
    tenant_id: int = 1,
) -> AuditLog:
    last = await db.execute(
        select(AuditLog).where(AuditLog.tenant_id == tenant_id).order_by(desc(AuditLog.id)).limit(1)
    )
    last_log = last.scalar_one_or_none()
    prev_hash = last_log.hash if last_log else None

    # 统一使用 naive UTC 秒级精度：DateTime 列默认无小数秒，写入值与校验值必须同口径
    # （规格 4.4 可复算前提），否则微秒会被 MySQL 截断导致校验失败。
    ts_dt = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    ts = ts_dt.isoformat()
    payload_str = json.dumps(
        {"before": before, "after": after}, sort_keys=True, ensure_ascii=False, default=str
    )
    h = compute_hash(prev_hash, ts, actor_id, action, payload_str)

    log = AuditLog(
        event_type=event_type,
        actor_id=actor_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        before=before,
        after=after,
        ip=ip,
        prev_hash=prev_hash,
        hash=h,
        created_at=ts_dt,
        tenant_id=tenant_id,
    )
    db.add(log)
    await db.flush()
    return log


async def verify_hash_chain(db: AsyncSession, tenant_id: int = 1) -> bool:
    result = await db.execute(
        select(AuditLog).where(AuditLog.tenant_id == tenant_id).order_by(AuditLog.id)
    )
    logs = result.scalars().all()
    prev_hash = None
    for log in logs:
        ts = log.created_at.isoformat() if log.created_at else ""
        payload_str = json.dumps(
            {"before": log.before, "after": log.after},
            sort_keys=True, ensure_ascii=False, default=str,
        )
        expected = compute_hash(prev_hash, ts, log.actor_id, log.action, payload_str)
        if log.hash != expected:
            return False
        prev_hash = log.hash
    return True
