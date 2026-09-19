"""合规分析 Agent（规格 6.3 专家 Agent：合规分析）。

职责（只读聚合报告）：
1. 聚合培训认证（证书有效数/到期数/认证率）与质量（偏差分级分布、未关闭偏差、
   未关闭 CAPA）、药物警戒（SAE 状态分布、紧急时限）、审计（进行中检查单、未闭合缺口）；
2. 输出"培训与合规"聚合报告：关键指标、关注点与建议。

设计约束：
- 仅做只读聚合（可复用 training_service.get_analytics/get_cert_matrix、
  quality_service.list_deviations/list_changes/list_capas、sae_service.list_sae、
  audit_service.list_audit_checks 等只读服务，或在 context 中直接传入各域数据）；
- Agent 层严禁写库；报告不含任何写操作。
- 输出为确定性规则/模板组装，不依赖 llm_client。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.services import audit_service, quality_service, sae_service, training_service

# 偏差/SAE/审计记录中的状态集
DEVIATION_OPEN_STATUS = ("reported", "classified", "investigating", "qa_review", "capa_linked")
SAE_ACTIVE_STATUS = ("recorded", "pv_reviewed", "draft", "signed")
AUDIT_OPEN_STATUS = ("draft", "ongoing", "rectifying")


def _freq(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    """统计列表记录中某字段的取值频率（dict 兼容）。"""
    counts: dict[str, int] = {}
    for row in rows or []:
        value = row.get(key) if isinstance(row, dict) else getattr(row, key, None)
        value = value or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return counts


def _open_gap_count(audits: list[dict[str, Any]]) -> int:
    """统计审计检查单中状态为 open 的缺口数量。"""
    total = 0
    for item in audits or []:
        gaps = (item.get("gaps") or {}).get("items") or [] if isinstance(item, dict) else []
        total += len([g for g in gaps if g.get("status") != "rectified" and g.get("status") != "covered"])
    return total


class ComplianceAgent(BaseAgent):
    """合规分析专家 Agent：培训与合规只读聚合报告。"""

    name = "合规分析"
    description = "培训认证与质量/警戒/审计数据的只读聚合分析报告"
    tools = ["aggregate_training", "aggregate_quality", "report"]

    async def run(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        db: AsyncSession | None = None,
        tenant_id: int = 1,
    ) -> dict[str, Any]:
        ctx = context or {}

        # ---------- 1. 培训认证指标 ----------
        analytics = ctx.get("training_analytics")
        cert_matrix = ctx.get("cert_matrix")
        if (analytics is None or cert_matrix is None) and db is not None:
            if analytics is None:
                analytics = await training_service.get_analytics(db, tenant_id)
            if cert_matrix is None:
                cert_matrix = await training_service.get_cert_matrix(db, None, tenant_id)
        analytics = analytics or {"total_certifications": 0, "valid_certifications": 0, "expiring_soon": 0, "cert_rate": 0}
        cert_matrix = cert_matrix or []
        expiring_certs = [
            {"employee_no": row.get("employee_no"), "positions": [
                p for p in (row.get("positions") or []) if p.get("is_expiring_soon")
            ]}
            for row in cert_matrix
            if any(p.get("is_expiring_soon") for p in (row.get("positions") or []))
        ]

        # ---------- 2. 质量域指标 ----------
        deviations = ctx.get("deviations")
        changes = ctx.get("changes")
        capas = ctx.get("capas")
        if (deviations is None or changes is None or capas is None) and db is not None:
            if deviations is None:
                deviations = (await quality_service.list_deviations(db, page_size=200, tenant_id=tenant_id))["items"]
            if changes is None:
                changes = (await quality_service.list_changes(db, page_size=200, tenant_id=tenant_id))["items"]
            if capas is None:
                capas = (await quality_service.list_capas(db, page_size=200, tenant_id=tenant_id))["items"]
        deviations = deviations or []
        changes = changes or []
        capas = capas or []

        dev_severity = _freq(deviations, "severity")
        dev_status = _freq(deviations, "status")
        open_deviations = sum(v for k, v in dev_status.items() if k in DEVIATION_OPEN_STATUS)
        critical_open = sum(
            1 for d in deviations if (d.get("severity") == "critical" and (d.get("status") in DEVIATION_OPEN_STATUS))
        )
        open_capas = sum(1 for c in capas if (c.get("status") or "open") not in ("closed", "verified"))

        # ---------- 3. 药物警戒域指标 ----------
        saes = ctx.get("saes")
        if saes is None and db is not None:
            saes = (await sae_service.list_sae(db, page_size=200, tenant_id=tenant_id))["items"]
        saes = saes or []
        sae_status = _freq(saes, "status")
        urgent_saes = [s for s in saes if s.get("urgent")]

        # ---------- 4. 审计域指标 ----------
        audits = ctx.get("audits")
        if audits is None and db is not None:
            audits = (await audit_service.list_audit_checks(db, page_size=200, tenant_id=tenant_id))["items"]
        audits = audits or []
        audit_status = _freq(audits, "status")
        open_checks = sum(v for k, v in audit_status.items() if k in AUDIT_OPEN_STATUS)
        open_gaps = _open_gap_count(audits)

        # ---------- 5. 关注点与建议 ----------
        attention: list[str] = []
        recommendations: list[str] = []
        if int(analytics.get("expiring_soon") or 0) > 0:
            attention.append(f"有 {analytics['expiring_soon']} 项认证将在 30 天内到期")
            recommendations.append("安排到期认证人员的复训与再认证考核")
        if critical_open:
            attention.append(f"存在 {critical_open} 条未关闭的 critical 偏差")
            recommendations.append("优先推进重大偏差调查并关联 CAPA")
        if open_capas:
            attention.append(f"存在 {open_capas} 项未关闭 CAPA")
            recommendations.append("跟进 CAPA 行动项与有效性验证")
        if urgent_saes:
            attention.append(f"存在 {len(urgent_saes)} 条 SAE 上报时限不足 4 小时")
            recommendations.append("立即提醒 PV/研究者完成 SAE 快速报告（人工签名提交）")
        if open_gaps:
            attention.append(f"审计检查单仍有 {open_gaps} 项证据缺口未闭合")
            recommendations.append("按审计缺口清单补充证据并复核")
        if not attention:
            attention.append("当前无显著合规风险信号，建议按计划开展例行监控")

        summary = (
            f"合规聚合报告：有效认证 {analytics.get('valid_certifications', 0)} 项"
            f"（到期 {analytics.get('expiring_soon', 0)}）；未关闭偏差 {open_deviations} 条"
            f"（critical {critical_open}）；未关闭 CAPA {open_capas} 项；"
            f"紧急时限 SAE {len(urgent_saes)} 条；审计证据缺口 {open_gaps} 项。"
        )

        return {
            "agent": self.name,
            "output": {
                "scope": "培训与合规聚合分析（只读）",
                "summary": summary,
                "training_section": {
                    "total_certifications": analytics.get("total_certifications"),
                    "valid_certifications": analytics.get("valid_certifications"),
                    "expiring_soon": analytics.get("expiring_soon"),
                    "cert_rate": analytics.get("cert_rate"),
                    "expiring_certificates": expiring_certs,
                },
                "quality_section": {
                    "deviation_by_severity": dev_severity,
                    "open_deviations": open_deviations,
                    "critical_open": critical_open,
                    "change_by_status": _freq(changes, "status"),
                    "open_capas": open_capas,
                },
                "vigilance_section": {"sae_by_status": sae_status, "urgent_deadline_count": len(urgent_saes)},
                "audit_section": {
                    "audit_checks_by_status": audit_status,
                    "open_audit_checks": open_checks,
                    "open_evidence_gaps": open_gaps,
                },
                "attention_items": attention,
                "recommendations": recommendations,
                "writes_disabled": True,
            },
        }
