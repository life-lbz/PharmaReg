import asyncio
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from app.audit.service import verify_hash_chain
from app.core.logging import logger
from app.db.session import AsyncSessionLocal
from app.models.compliance import AuditLog, Notification
from app.models.training import Certification
from app.services.sae_service import scan_deadlines


async def run_sae_deadline_scan():
    async with AsyncSessionLocal() as db:
        count = await scan_deadlines(db)
        await db.commit()
        logger.info("sae_deadline_scan", created_notifications=count)


async def run_cert_expiry_scan():
    async with AsyncSessionLocal() as db:
        expiry_limit = date.today() + timedelta(days=30)
        result = await db.execute(
            select(Certification).where(
                Certification.status == "valid",
                Certification.expire_date <= expiry_limit,
                Certification.expire_date >= date.today(),
            )
        )
        certs = result.scalars().all()
        for cert in certs:
            n = Notification(
                user_id=0,
                type="cert_expiry",
                title=f"岗位认证 {cert.position_type}（{cert.employee_no}）即将到期",
                payload={
                    "certification_id": cert.id,
                    "employee_no": cert.employee_no,
                    "expire_date": cert.expire_date.isoformat(),
                },
                status="pending",
                tenant_id=cert.tenant_id,
            )
            db.add(n)
        await db.commit()
        logger.info("cert_expiry_scan", notifications=len(certs))


async def _latest_system_notification(db, notif_type: str) -> Notification | None:
    """查询最近一条系统级（user_id=0）同类型通知，用于当天幂等去重。

    幂等策略：同一天（UTC 自然日，见 payload.check_date）只留痕一条，
    重复执行直接跳过，避免巡检通知在通知表无限膨胀。
    """
    result = await db.execute(
        select(Notification)
        .where(
            Notification.user_id == 0,
            Notification.type == notif_type,
            Notification.is_deleted == False,
        )
        .order_by(Notification.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _audit_chain_verify(db) -> tuple[int, list[int]]:
    """逐租户执行审计日志哈希链完整性校验（只读，不改 audit_logs）。

    与 app/audit/service.py 的 write_audit / verify_hash_chain 同口径：
    同租户按 id 升序逐条复算 sha256(prev_hash || timestamp || actor_id ||
    action || payload_json)，链上首条 prev_hash 为空；返回 (通过条数, 校验失败的租户)。
    """
    tenant_ids = list((await db.execute(select(AuditLog.tenant_id).distinct())).scalars().all())
    verified_count = 0
    failed_tenant_ids: list[int] = []
    for tenant_id in tenant_ids or [1]:
        total = int(
            (
                await db.execute(
                    select(func.count()).select_from(AuditLog).where(AuditLog.tenant_id == tenant_id)
                )
            ).scalar()
            or 0
        )
        verified_count += total
        if total and not await verify_hash_chain(db, tenant_id=tenant_id):
            failed_tenant_ids.append(tenant_id)
    return verified_count, failed_tenant_ids


async def run_audit_hash_verify() -> dict:
    """每日审计日志哈希链完整性校验（规格 1.3/10.3 审计运维闭环）。

    全程只读审计表，校验结果写入系统 Notification（user_id=0,
    type="audit_integrity"，payload 含 verified_count 与检查时间）；
    保留策略为“告警 + 留痕”，不修改、不删除任何审计数据。
    """
    async with AsyncSessionLocal() as db:
        verified_count, failed_tenant_ids = await _audit_chain_verify(db)
        now_utc = datetime.now(UTC)
        check_date = now_utc.date().isoformat()
        checked_at = now_utc.replace(tzinfo=None, microsecond=0).isoformat()
        valid = not failed_tenant_ids
        payload = {
            "check_date": check_date,
            "checked_at": checked_at,
            "verified_count": verified_count,
            "valid": valid,
            "failed_tenant_ids": failed_tenant_ids,
        }
        last = await _latest_system_notification(db, "audit_integrity")
        if last and (last.payload or {}).get("check_date") == check_date:
            logger.info("audit_hash_verify_skip", check_date=check_date, verified_count=verified_count)
            return {**payload, "written": False}
        n = Notification(
            user_id=0,
            type="audit_integrity",
            title=(
                "审计日志哈希链完整性校验通过"
                if valid
                else "审计日志哈希链完整性校验失败（存在断裂）"
            ),
            payload=payload,
            status="pending",
            tenant_id=1,
        )
        db.add(n)
        await db.commit()
        logger.info(
            "audit_hash_verify",
            check_date=check_date,
            verified_count=verified_count,
            valid=valid,
        )
        return {**payload, "written": True, "notification_id": n.id}


async def run_audit_retention_archive() -> dict:
    """审计保留策略巡检（规格审计记录保留≥5年）。

    查询 created_at 早于 5 年前的 audit_logs，按年份聚合计数生成归档摘要，
    写入系统 Notification（user_id=0, type="audit_retention"）。
    策略为“告警 + 留痕”：不物理删除、不迁移，由人工确认归档动作。
    """
    async with AsyncSessionLocal() as db:
        now_utc = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        cutoff = now_utc.replace(year=now_utc.year - 5)
        rows = (
            await db.execute(
                select(func.year(AuditLog.created_at).label("log_year"), func.count())
                .where(AuditLog.created_at < cutoff)
                .group_by(func.year(AuditLog.created_at))
            )
        ).all()
        by_year = {str(r[0]): int(r[1]) for r in rows}
        expired_count = sum(by_year.values())
        check_date = now_utc.date().isoformat()
        payload = {
            "check_date": check_date,
            "checked_at": now_utc.isoformat(),
            "retention_years": 5,
            "cutoff_at": cutoff.isoformat(),
            "expired_count": expired_count,
            "by_year": by_year,
            "policy": "alert_and_trace_only_no_delete",
        }
        last = await _latest_system_notification(db, "audit_retention")
        if last and (last.payload or {}).get("check_date") == check_date:
            logger.info("audit_retention_skip", check_date=check_date, expired_count=expired_count)
            return {**payload, "written": False}
        n = Notification(
            user_id=0,
            type="audit_retention",
            title=(
                "审计记录保留巡检：无超过5年保留期的记录"
                if expired_count == 0
                else f"审计记录保留巡检：{expired_count} 条已超过5年保留期（待人工归档）"
            ),
            payload=payload,
            status="pending",
            tenant_id=1,
        )
        db.add(n)
        await db.commit()
        logger.info("audit_retention", check_date=check_date, expired_count=expired_count)
        return {**payload, "written": True, "notification_id": n.id}


async def run_all_workers():
    await run_sae_deadline_scan()
    await run_cert_expiry_scan()
    await run_audit_hash_verify()
    await run_audit_retention_archive()


if __name__ == "__main__":
    asyncio.run(run_all_workers())
