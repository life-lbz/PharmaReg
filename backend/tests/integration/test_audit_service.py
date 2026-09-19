"""审计服务集成测试：write_audit 哈希链写入与完整性校验。"""
from sqlalchemy import select

from app.audit.service import verify_hash_chain, write_audit
from app.models.compliance import AuditLog


class TestAuditChain:
    async def test_write_and_verify_chain(self, db_session):
        for i in range(3):
            await write_audit(
                db_session,
                event_type="test.event",
                action="do",
                actor_id=1,
                object_type="deviations",
                object_id=i + 1,
                after={"seq": i},
                tenant_id=1,
            )
        await db_session.commit()

        logs = (await db_session.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
        assert len(logs) == 3
        # 链式：后一条 prev_hash 指向前一条 hash
        assert logs[1].prev_hash == logs[0].hash
        assert logs[2].prev_hash == logs[1].hash
        # 完整性校验通过
        assert await verify_hash_chain(db_session, tenant_id=1) is True

    async def test_tamper_detected(self, db_session):
        await write_audit(db_session, event_type="a.b", action="x", actor_id=1, after={"v": 1}, tenant_id=1)
        await write_audit(db_session, event_type="a.b", action="y", actor_id=2, after={"v": 2}, tenant_id=1)
        await db_session.commit()

        log = (await db_session.execute(select(AuditLog).where(AuditLog.action == "x"))).scalar_one()
        log.after = {"v": 999}  # 篡改
        await db_session.commit()

        assert await verify_hash_chain(db_session, tenant_id=1) is False

    async def test_compute_hash_consistency(self, db_session):
        """服务端 compute_hash 与规格公式（sha256(prev||ts||actor||action||payload)）一致。"""
        import hashlib

        from app.audit.service import compute_hash
        from app.core.logging import logger

        h = compute_hash("prev", "2026-01-01T00:00:00+00:00", 7, "sign", '{"a":1}')
        expected = hashlib.sha256(
            b"prev2026-01-01T00:00:00+00:007sign{\"a\":1}"
        ).hexdigest()
        assert h == expected
        logger.info("hash_ok", h=h)
