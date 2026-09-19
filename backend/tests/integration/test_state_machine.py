"""偏差/变更状态机集成测试：非法跃迁、四眼审批、关闭前置。"""
import pytest

from app.core.exceptions import DeviationCloseError, FourEyeError, StateError
from app.models.quality import Deviation
from app.services.quality_service import (
    approve_change,
    assess_change,
    classify_deviation,
    close_deviation,
    create_change,
    create_deviation,
    investigate_deviation,
    review_deviation,
    submit_deviation_review,
)


class _Req:
    """迷你请求对象，避免引入 Pydantic 依赖。"""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


async def _mk_deviation(db_session, severity="minor"):
    req = _Req(title="温度超标偏差", description="灌装间温度超标", occurred_at=None, area="车间", category="环境")
    dev = await create_deviation(db_session, req, reporter_id=1)
    return dev


class TestDeviationStateMachine:
    async def test_illegal_transition_reported_to_capa_linked(self, db_session):
        dev = await _mk_deviation(db_session)
        with pytest.raises(StateError):
            await review_deviation(db_session, dev.id, True, "直接跳级", 2)

    async def test_illegal_transition_classified_to_closed(self, db_session):
        dev = await _mk_deviation(db_session)
        await classify_deviation(db_session, dev.id, "major", None)
        with pytest.raises(StateError):
            await close_deviation(db_session, dev.id, None)

    async def test_close_requires_verified_capa(self, db_session):
        """关闭前置：CAPA 未验证（甚至未建）时 close 必须报 4102。"""
        dev = await _mk_deviation(db_session)
        await classify_deviation(db_session, dev.id, "major", None)
        await investigate_deviation(db_session, dev.id, {"steps": ["a"]})
        await submit_deviation_review(db_session, dev.id, "根因X")
        await review_deviation(db_session, dev.id, True, "通过", 2)
        assert (await db_session.get(Deviation, dev.id)).status == "capa_linked"
        # 未关联已验证 CAPA -> 关闭被拦截
        with pytest.raises(DeviationCloseError):
            await close_deviation(db_session, dev.id, None)


class TestChangeFourEye:
    async def test_approver_cannot_be_initiator(self, db_session):
        req = _Req(title="设备变更", change_type="设备", description="更换灌装泵")
        change = await create_change(db_session, req, initiator_id=10)
        await assess_change(db_session, change.id, {"impact": "低"}, assessor_id=10)
        # 发起人 10 兼任审批人 -> 4101
        with pytest.raises(FourEyeError):
            await approve_change(db_session, change.id, approver_id=10, comment="自批")

    async def test_approve_success_by_other_approver(self, db_session):
        req = _Req(title="文件变更", change_type="文件", description="更新SOP")
        change = await create_change(db_session, req, initiator_id=10)
        await assess_change(db_session, change.id, {"impact": "低"}, assessor_id=11)
        result = await approve_change(db_session, change.id, approver_id=12, comment="同意")
        assert result["status"] == "approved"

    async def test_assess_requires_submitted_state(self, db_session):
        req = _Req(title="工艺变更", change_type="工艺", description="变更参数")
        change = await create_change(db_session, req, initiator_id=10)
        await assess_change(db_session, change.id, {"impact": "中"}, assessor_id=11)
        # 已 assessed，再 assess 应报 StateError
        with pytest.raises(StateError):
            await assess_change(db_session, change.id, {"impact": "高"}, assessor_id=11)
