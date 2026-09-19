"""质量/培训服务覆盖测试：完整状态机主链 + 培训考核认证主链（测试库事务，training 表自清理）。"""
import pytest
from sqlalchemy import text

from app.models.quality import Deviation
from app.services.quality_service import (
    approve_change,
    assess_change,
    classify_deviation,
    close_change,
    close_deviation,
    create_batch_hold,
    create_capa,
    create_change,
    create_deviation,
    get_change,
    get_deviation,
    implement_change,
    investigate_deviation,
    list_capas,
    list_changes,
    list_deviations,
    release_batch_hold,
    reopen_deviation,
    review_deviation,
    submit_deviation_review,
    update_capa_actions,
    verify_capa,
    verify_change,
)
from app.services.training_service import (
    auto_generate_questions,
    create_exam,
    create_question,
    get_analytics,
    get_cert_matrix,
    get_exam,
    issue_certification,
    list_exams,
    list_questions,
    start_exam,
    submit_exam,
    update_question,
)

TRAIN_CLEAN = ["exam_records", "certifications", "exams", "questions"]


class _Req:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


@pytest.fixture
def _req():
    return _Req


class TestDeviationFullFlow:
    async def test_full_flow_to_close_with_capa(self, db_session, _req):
        # 上报 -> 列表/详情 -> 分级 -> 调查 -> 提交审核 -> 审核(签名)-> CAPA 验证 -> 关闭 -> 重开
        req = _Req(title="灌装间温度超标", description="温度达 28℃ 超出范围",
                   occurred_at=None, area="车间-灌装", category="环境监控")
        dev = await create_deviation(db_session, req, reporter_id=1)
        assert dev.status == "reported"

        listed = await list_deviations(db_session, severity="minor")
        assert listed["pagination"]["total"] >= 1
        assert (await get_deviation(db_session, dev.id)).id == dev.id

        await classify_deviation(db_session, dev.id, "major", {"basis": "影响无菌保证"})
        assert (await db_session.get(Deviation, dev.id)).status == "classified"

        await investigate_deviation(db_session, dev.id, {"steps": ["检查空调", "复核记录"]})
        await submit_deviation_review(db_session, dev.id, "除湿机组故障")
        await review_deviation(db_session, dev.id, True, "审核通过转CAPA", 2)
        assert (await db_session.get(Deviation, dev.id)).status == "capa_linked"

        # CAPA 主链
        capa_req = _Req(source_type="deviation", source_id=dev.id,
                        title="空调机组整改", root_cause="除湿机组故障")
        capa = await create_capa(db_session, capa_req, creator_id=1)
        await update_capa_actions(db_session, capa.id, [{"owner": "eng1", "desc": "更换机组", "done": True}])
        capas = await list_capas(db_session, source_type="deviation")
        assert capas["pagination"]["total"] >= 1
        await verify_capa(db_session, capa.id, {"effective": True})

        closed = await close_deviation(db_session, dev.id, "CAPA 已验证，关闭")
        assert closed["status"] == "closed"

        # 批次挂起/解除（释放仅允许偏差已关闭后）
        hold = await create_batch_hold(db_session, dev.id, "B20260903", "某注射剂", "待评估")
        await release_batch_hold(db_session, hold.id)

        reopened = await reopen_deviation(db_session, dev.id, "复检发现残留问题")
        assert reopened["status"] == "reported"


class TestChangeFullFlow:
    async def test_full_flow_to_close(self, db_session, _req):
        req = _Req(title="灌装工艺参数变更", change_type="工艺", description="调整灌装速度范围")
        chg = await create_change(db_session, req, initiator_id=10)
        assert (await get_change(db_session, chg.id)).id == chg.id

        await assess_change(db_session, chg.id, {"impact": "中", "affected": ["工艺"]}, assessor_id=11)
        await approve_change(db_session, chg.id, approver_id=12, comment="同意")
        await implement_change(db_session, chg.id, {"steps": ["更新SOP", "培训"]})
        await verify_change(db_session, chg.id, {"result": "合格"})
        result = await close_change(db_session, chg.id, "已完成")
        assert result["status"] == "closed"

        changed_list = await list_changes(db_session, status="closed")
        assert changed_list["pagination"]["total"] >= 1


class TestTrainingFlow:
    async def test_full_training_flow(self, db_session, _req):
        # 清理 training 相关表（db_session 清理清单不含这些表）
        try:
            # 建题 -> 列表/更新 -> 自动组卷 -> 发布 -> 开考 -> 交卷 -> 发证 -> 矩阵/统计
            q1 = await create_question(db_session, _Req(
                position_type="QA", section_id=None, type="single", stem="GMP 的制定目的是什么？",
                options={"A": "a", "B": "b"}, answer="A", difficulty=2, status="active"))
            q2 = await create_question(db_session, _Req(
                position_type="QA", section_id=None, type="judge", stem="批记录保存至少 1 年？",
                options={"A": "对", "B": "错"}, answer="B", difficulty=1, status="active"))
            assert q1.id and q2.id

            bank = await list_questions(db_session, position_type="QA")
            assert bank["pagination"]["total"] >= 2
            await update_question(db_session, q1.id,
                                  _Req(stem=None, options=None, answer=None, difficulty=3, status="active"))

            ids = await auto_generate_questions(db_session, "QA", 20)
            assert set(ids) <= {q1.id, q2.id}

            exam = await create_exam(db_session, _Req(
                title="QA 上岗考核", position_type="QA", pass_score=80.0,
                scope=None, question_ids=None, assist=True, start_at=None, end_at=None))
            assert exam.status == "published"
            listed = await list_exams(db_session, position_type="QA")
            assert listed["pagination"]["total"] >= 1
            assert (await get_exam(db_session, exam.id)).id == exam.id

            started = await start_exam(db_session, exam.id, "EMP-QA001")
            rec_id = started["record_id"]
            q_map = {str(q["id"]): q for q in started["questions"]}
            right = {str(q1.id): "A", str(q2.id): "B"}
            payload = {qid: right[qid] for qid in q_map}
            submitted = await submit_exam(db_session, rec_id, payload)
            assert submitted["passed"] is True

            cert = await issue_certification(db_session, _Req(
                exam_record_id=rec_id, employee_no="EMP-QA001", position_type="QA"))
            assert cert.status == "valid"

            matrix = await get_cert_matrix(db_session)
            assert any(m["employee_no"] == "EMP-QA001" for m in matrix)
            analytics = await get_analytics(db_session)
            assert analytics["total_certifications"] >= 1
        finally:
            for t in TRAIN_CLEAN:
                try:
                    await db_session.execute(text(f"DELETE FROM `{t}`"))
                except Exception:
                    await db_session.rollback()
