"""规格 6.3 新增 7 个专家 Agent 的单元测试。

覆盖对象：TrainingAgent / DeviationAgent / ChangeAgent / AuditAgent /
SaeAgent / KbOpsAgent / ComplianceAgent，以及 supervisor.AGENT_REGISTRY 接线。

策略：优先构造最小 context（携带所需数据），db 一律传 None，保证不依赖
开发库 3307 也能全绿；Agent 均不写库、不调用 llm_client（确定性输出）。
"""
import os

# 关键：在任何 app.* 模块被 import 前把 LLM 置为 stub，避免非 stub 触发网络调用
os.environ.setdefault("LLM_PROVIDER", "stub")

from datetime import UTC, datetime, timedelta

from app.agents.audit_agent import AuditAgent
from app.agents.change_agent import ChangeAgent
from app.agents.compliance_agent import ComplianceAgent
from app.agents.deviation_agent import DeviationAgent
from app.agents.kb_ops_agent import KbOpsAgent
from app.agents.sae_agent import SaeAgent
from app.agents.supervisor import AGENT_REGISTRY, Supervisor
from app.agents.training_agent import TrainingAgent


def _assert_structure(result: dict) -> dict:
    """公共断言：返回结构必须含非空 agent 与 output。"""
    assert result.get("agent")
    assert result.get("output")
    return result["output"]


# ---------------------------------------------------------------- training


async def test_training_compose_snapshot_from_context():
    bank = [
        {"id": 1, "type": "single", "stem": "问题一", "options": {"A": "a", "B": "b"}, "difficulty": 2, "answer": "A", "position_type": "QA"},
        {"id": 2, "type": "single", "stem": "问题二", "options": {"A": "a", "B": "b"}, "difficulty": 3, "answer": "B", "position_type": "QA"},
        {"id": 3, "type": "judge", "stem": "问题三", "options": None, "difficulty": 4, "answer": "T", "position_type": "QA"},
    ]
    out = _assert_structure(
        await TrainingAgent().run(
            "为QA岗位组一套2题的卷子",
            {"action": "compose", "position_type": "QA", "question_count": 2, "pick_mode": "order", "question_bank": bank},
            None,
        )
    )
    snapshot = out["snapshot"]
    assert snapshot["question_count"] == 2
    assert snapshot["status"] == "snapshot_pending_publish"
    assert all("answer" not in q for q in snapshot["questions"])
    assert snapshot["position_type"] == "QA"


async def test_training_grade_suggestion():
    questions = [
        {"id": 1, "type": "single", "stem": "问题一", "answer": "A"},
        {"id": 2, "type": "judge", "stem": "问题二", "answer": "T"},
    ]
    out = _assert_structure(
        await TrainingAgent().run(
            "批改",
            {"action": "grade", "questions": questions, "answers": {"1": "A", "2": "F"}, "pass_score": 80},
            None,
        )
    )
    grade = out["grade"]
    assert grade["score"] == 50.0
    assert grade["correct"] == 1
    assert grade["wrong"] == 1
    assert grade["passed"] is False


async def test_training_cert_advice():
    cert_matrix = [
        {"employee_no": "E001", "positions": [{"position_type": "QA", "issue_date": "2025-01-01", "expire_date": "2026-09-10", "is_expiring_soon": True}]},
        {"employee_no": "E002", "positions": [{"position_type": "QC", "issue_date": "2026-01-01", "expire_date": "2027-01-01", "is_expiring_soon": False}]},
    ]
    out = _assert_structure(
        await TrainingAgent().run("认证建议", {"action": "cert_advice", "cert_matrix": cert_matrix}, None)
    )
    advice = out["cert_advice"]
    assert advice["expiring_soon_count"] == 1
    assert advice["advice"]
    assert "E001" in advice["advice"][0]


# ---------------------------------------------------------------- deviation


async def test_deviation_classify_critical_and_case_refs():
    cases = [{"id": 9, "dev_no": "DEV-2025-0009", "title": "灌装线无菌污染", "severity": "critical", "status": "closed", "root_cause": "层流异常"}]
    out = _assert_structure(
        await DeviationAgent().run(
            "产品批次出现无菌检验污染，涉及产品放行",
            {"description": "成品无菌检验污染，涉及批次放行与已上市产品", "title": "无菌污染", "similar_cases": cases},
            None,
        )
    )
    assert out["severity_suggestion"]["suggested_severity"] == "critical"
    assert out["case_refs"] == cases
    assert out["investigation_plan_draft"]["timeline_hint"]
    assert out["writes_disabled"] is True


async def test_deviation_minor_default():
    out = _assert_structure(
        await DeviationAgent().run("记录填写笔误", {"description": "批记录某处数字笔误，已当场更正", "title": "记录笔误"}, None)
    )
    assert out["severity_suggestion"]["suggested_severity"] == "minor"


# ---------------------------------------------------------------- change


async def test_change_assessment_high_with_reg_basis():
    basis = [{"clause_no": "第X条", "content": "变更应评估对产品质量影响", "doc_version": "GMP-2010"}]
    out = _assert_structure(
        await ChangeAgent().run(
            "评估该工艺变更",
            {
                "change": {"chg_no": "CHG-2026-0001", "change_type": "工艺与生产"},
                "title": "关键工艺参数变更",
                "description": "变更无菌灌装关键工艺参数，涉及已上市产品",
                "reg_basis": basis,
            },
            None,
        )
    )
    draft = out["impact_assessment_draft"]
    assert draft["impact_level_suggestion"]["suggested_level"] == "high"
    assert draft["regulatory_basis"] == basis
    assert draft["status"] == "draft"
    assert any("工艺" in area["area"] for area in draft["impact_areas"])


async def test_change_assessment_low():
    out = _assert_structure(
        await ChangeAgent().run(
            "行政类文档模板变更", {"title": "更新行政文件模板", "description": "仅行政文件模板调整，不涉及产品"}, None
        )
    )
    draft = out["impact_assessment_draft"]
    assert draft["impact_level_suggestion"]["suggested_level"] == "low"


# ---------------------------------------------------------------- audit


async def test_audit_gmp_checklist_and_gaps():
    out = _assert_structure(await AuditAgent().run("准备GMP迎检检查表", {"check_type": "gmp"}, None))
    assert out["check_type"] == "gmp"
    assert out["checklist_item_count"] > 0
    assert out["open_gap_count"] > 0
    assert out["open_gap_count"] == out["checklist_item_count"]


async def test_audit_evidence_covered_marks_gap_closed():
    checklist = {
        "sections": [
            {"section": "机构与人员", "items": [{"key": "gmp-1", "text": "质量管理机构与职责是否明确", "type": "verify"}]}
        ]
    }
    audit = {"checklist": checklist, "evidence_refs": {"items": [{"item_key": "gmp-1", "evidence_key": "E-001"}]}}
    out = _assert_structure(await AuditAgent().run("检查表", {"check_type": "gmp", "audit": audit}, None))
    assert out["open_gap_count"] == 0
    assert out["evidence_gap_draft"][0]["covered"] is True


# ---------------------------------------------------------------- sae


async def test_sae_death_24h_7days_deadline():
    onset = "2026-09-03T08:00:00+00:00"
    out = _assert_structure(
        await SaeAgent().run(
            "上报SAE",
            {"subject_no": "SUB-001", "ae_description": "受试者用药后突发死亡", "onset_at": onset, "seriousness_flags": ["death"]},
            None,
        )
    )
    severity = out["severity_assessment"]
    assert severity["urgent_24h"] is True
    assert "死亡" in severity["seriousness_flags"]
    dl = out["deadline_estimate"]
    assert dl["expedited_report_days"] == 7
    assert datetime.fromisoformat(dl["first_deadline_iso"]) - datetime.fromisoformat(onset) == timedelta(hours=24)
    assert "电子签名" in out["report_draft"]["sign_and_submit"] or "人工" in out["report_draft"]["sign_and_submit"]


async def test_sae_hospitalization_15days():
    out = _assert_structure(
        await SaeAgent().run(
            "上报SAE", {"subject_no": "SUB-002", "ae_description": "需住院治疗", "onset_at": "2026-09-03T00:00:00+00:00"}, None
        )
    )
    assert out["deadline_estimate"]["expedited_report_days"] == 15


async def test_sae_scan_urgent_deadline():
    now = datetime.now(UTC)
    near = (now + timedelta(hours=2)).isoformat()
    later = (now + timedelta(days=2)).isoformat()
    reports = [
        {"id": 1, "sae_no": "SAE-2026-0001", "status": "recorded", "report_deadline_1": near},
        {"id": 2, "sae_no": "SAE-2026-0002", "status": "draft", "report_deadline_1": later},
    ]
    out = _assert_structure(await SaeAgent().run("扫描SAE时限", {"scan": True, "reports": reports}, None))
    assert out["mode"] == "scan"
    assert out["urgent_count"] == 1
    urgent = [s for s in out["deadline_scan"] if s["urgent"]]
    assert urgent and urgent[0]["sae_no"] == "SAE-2026-0001"


# ---------------------------------------------------------------- kb_ops


async def test_kb_ops_version_scan_and_faq_candidates():
    versions = [
        {"id": 1, "regulation": "GMP", "version_label": "2010", "status": "active"},
        {"id": 2, "regulation": "GMP", "version_label": "2026", "status": "draft"},
    ]
    diffs = [
        {"change_type": "added", "new_content": "新增计算机化系统数据完整性要求条款。", "review_status": "pending", "from_clause_id": None, "to_clause_id": 9},
        {"change_type": "revised", "new_content": "修订后的偏差处理条款内容。", "review_status": "pending", "from_clause_id": 1, "to_clause_id": 2},
        {"change_type": "removed", "old_content": "已删除内容。", "review_status": "pending", "from_clause_id": 3, "to_clause_id": None},
    ]
    out = _assert_structure(
        await KbOpsAgent().run("新规入库差异", {"versions": versions, "diffs": diffs, "regulation": "GMP", "version_label": "2026"}, None)
    )
    assert out["total_versions"] == 2
    # 仅 added/revised 生成 FAQ 候选；removed 被跳过
    assert out["faq_candidate_count"] == 2
    assert any("新增" in c["question"] for c in out["faq_candidates"])
    assert out["human_actions"] and "人工" in out["human_actions"][0]


async def test_kb_ops_draft_version_hint():
    versions = [
        {"id": 5, "regulation": "GCP", "version_label": "2026", "status": "draft"},
    ]
    out = _assert_structure(await KbOpsAgent().run("扫描版本", {"versions": versions}, None))
    assert out["version_scan"][0]["hint"] == "无待复核差异，可由管理员激活"


# ---------------------------------------------------------------- compliance


async def test_compliance_aggregate_report():
    out = _assert_structure(
        await ComplianceAgent().run(
            "出一份合规聚合报告",
            {
                "training_analytics": {"total_certifications": 10, "valid_certifications": 8, "expiring_soon": 2, "cert_rate": 80.0},
                "cert_matrix": [
                    {"employee_no": "E001", "positions": [{"position_type": "QA", "is_expiring_soon": True}]},
                    {"employee_no": "E002", "positions": [{"position_type": "QC", "is_expiring_soon": False}]},
                ],
                "deviations": [
                    {"severity": "critical", "status": "investigating"},
                    {"severity": "minor", "status": "closed"},
                ],
                "capas": [{"status": "open"}],
                "saes": [{"status": "recorded", "urgent": True}],
                "audits": [{"status": "ongoing", "gaps": {"items": [{"key": "gmp-1", "status": "open"}]}}],
            },
            None,
        )
    )
    assert out["training_section"]["expiring_soon"] == 2
    assert out["quality_section"]["critical_open"] == 1
    assert out["quality_section"]["open_capas"] == 1
    assert out["vigilance_section"]["urgent_deadline_count"] == 1
    assert out["audit_section"]["open_evidence_gaps"] == 1
    assert out["attention_items"] and out["recommendations"]


async def test_compliance_empty_context_still_non_empty():
    out = _assert_structure(await ComplianceAgent().run("报告", {}, None))
    assert out["training_section"]["valid_certifications"] == 0
    assert "无显著合规风险" in out["attention_items"][0]


# ---------------------------------------------------------------- supervisor 接线


async def test_registry_registers_all_ten_agents():
    expected = {"qa", "explain", "path", "deviation", "change", "audit", "sae", "kb_ops", "training", "compliance_analysis"}
    assert expected <= set(AGENT_REGISTRY.keys())
    assert len(AGENT_REGISTRY) == 10


async def test_supervisor_execute_routes_non_qa_agent():
    # trainer 角色不可见 qa，路由会落到 training 或 compliance_analysis
    result = await Supervisor().execute("给我培训分析", ["trainer"], None, {})
    assert result.get("agent") in {"培训考核", "合规分析"}
    assert result.get("output")
