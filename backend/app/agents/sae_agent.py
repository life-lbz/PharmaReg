"""SAE 上报 Agent（规格 6.3 专家 Agent：SAE 上报）。

职责（报告草稿/初判，不写库）：
1. 严重性分级初判（SAE 判定与死亡/危及生命等分型）；
2. 上报时限计算（快速报告 24h 原则 + 按分型 7 天/15 天详细报告时限）；
3. 报告草稿组装（供研究者/申办方人工审阅）。

设计约束：
- 本 Agent 只做初判与草稿。PV 复核（pv_review）、报告草稿生成（generate_draft）、
  电子签名（sign_sae）与提交（submit_sae）必须由人工/PV 走 SAE API 完成；
- 时限扫描为只读计算（读取 serialize_sae/list_sae 结果后按剩余小时计算），
  本 Agent 不创建 Notification（该动作由调度任务 scan_deadlines 负责）；
- context 已携带 SAE 信息时无需 db；输出为确定性规则/模板组装，不依赖 llm_client。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.models.vigilance import SaeReport
from app.services import sae_service

# 严重性分型关键词（在 seriousness flags 或描述中命中即判定）
SERIOUS_FLAG_RULES: dict[str, tuple[tuple[str, ...], str]] = {
    "death": (("death", "死亡", "致死"), "死亡"),
    "life_threatening": (("life_threatening", "危及生命", "life-threatening"), "危及生命"),
    "hospitalization": (("hospitalization", "住院", "延长住院", "hospital"), "需住院/延长住院"),
    "disability": (("disability", "残疾", "致残", "功能丧失"), "致残/永久性损伤"),
    "congenital": (("congenital", "先天", "畸形", "出生缺陷"), "先天异常/出生缺陷"),
    "other_medical_event": (("medical", "重要医学事件", "其他", "其它", "干预", "急诊"), "其他重要医学事件"),
}

# 快速报告时限：死亡/危及生命 24h 内通知研究者并在 7 天内提交详细报告；
# 其它 SAE 15 天内提交详细报告（参考 ICH E2A / 中国 GCP 快速报告要求，具体以 SOP 为准）
URGENT_KEYWORDS = ("death", "死亡", "life_threatening", "危及生命")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def assess_seriousness(ae_description: str, flags: list[str] | None) -> dict[str, Any]:
    """严重性初判：输出 SAE 判定、分型与触发依据。"""
    text = f"{ae_description or ''} {','.join(flags or [])}"
    matched: list[str] = []
    for _key, (aliases, label) in SERIOUS_FLAG_RULES.items():
        if any(a in text for a in aliases):
            matched.append(label)
    if not matched:
        matched = ["其他重要医学事件（需医学判断）"]
    urgent = any(kw in text.lower() for kw in URGENT_KEYWORDS)
    return {
        "is_sae_suspected": True,
        "seriousness_flags": matched,
        "urgent_24h": urgent,
        "note": "初判基于规则关键词；最终分级与因果关系须由 PV/研究者人工确认",
    }


def estimate_deadlines(onset_at: str | None, urgent: bool) -> dict[str, Any]:
    """按分型计算上报时限（确定性）。"""
    try:
        if onset_at:
            base = datetime.fromisoformat(onset_at.replace("Z", "+00:00"))
            if base.tzinfo is None:
                base = base.replace(tzinfo=UTC)
        else:
            base = datetime.now(UTC)
    except (TypeError, ValueError):
        base = datetime.now(UTC)

    first_24h = base + timedelta(hours=24)
    detail_days = 7 if urgent else 15
    detail = base + timedelta(days=detail_days)
    return {
        "base_time": base.isoformat(),
        "notify_within_hours": 24,
        "expedited_report_days": detail_days,
        "first_deadline_iso": first_24h.isoformat(),
        "detail_deadline_iso": detail.isoformat(),
        "reference": "ICH E2A / 中国 GCP 快速报告：获知后 24h 内上报，死亡或危及生命 7 天内提交"
        + "详细报告，其它 SAE 15 天内提交；具体以项目 SOP 与法规为准",
    }


def _build_draft(sae: dict[str, Any], severity: dict[str, Any], deadlines: dict[str, Any]) -> dict[str, Any]:
    """报告草稿模板组装。"""
    text = f"受试者 {sae.get('subject_no') or '（待补）'} 于 {sae.get('onset_at') or '（待补）'} 发生不良事件：{sae.get('ae_description') or '（待补）'}。"
    return {
        "sae_no": sae.get("sae_no") or "SAE-（待编号，由系统生成）",
        "subject_no": sae.get("subject_no"),
        "ae_description": sae.get("ae_description"),
        "narrative": text + " 依据上报内容初步判定为严重不良事件（SAE），具体分型与因果关系待 PV 复核。",
        "seriousness_flags": severity["seriousness_flags"],
        "causality": "unknown（待 PV 评估）",
        "deadlines": deadlines,
        "status": "draft_suggestion",
        "sign_and_submit": "本报告为 AI 草稿；电子签名与提交必须由研究者/申办方人工通过 SAE API 完成",
    }


def _remaining_hours(deadline: str | None, now: datetime) -> float | None:
    """计算距时限剩余小时（与 sae_service 内部实现一致的只读纯函数）。"""
    if not deadline:
        return None
    try:
        deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        if deadline_dt.tzinfo is None:
            deadline_dt = deadline_dt.replace(tzinfo=UTC)
        return round((deadline_dt - now).total_seconds() / 3600, 1)
    except Exception:
        return None


async def _load_reports(db: AsyncSession, tenant_id: int) -> list[dict[str, Any]]:
    """只读：读取进行中的 SAE 报告并补齐剩余时限字段。"""
    result = await db.execute(
        select(SaeReport).where(
            SaeReport.is_deleted == False,
            SaeReport.tenant_id == tenant_id,
            SaeReport.status.in_(["recorded", "pv_reviewed", "draft"]),
        )
    )
    rows = result.scalars().all()
    return [sae_service.serialize_sae(s) for s in rows]


class SaeAgent(BaseAgent):
    """SAE 上报专家 Agent：分级初判 / 时限计算 / 报告草稿（签名提交必须人工）。"""

    name = "SAE 上报"
    description = "SAE 分级初判、上报时限计算与报告草稿；签名与提交必须人工完成"
    tools = ["assess_seriousness", "calc_deadline", "draft_report"]

    async def run(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        db: AsyncSession | None = None,
        tenant_id: int = 1,
    ) -> dict[str, Any]:
        ctx = context or {}
        record = ctx.get("sae") or {}
        ae_description = (
            ctx.get("ae_description")
            or record.get("ae_description")
            or query
            or "（待补录不良事件描述）"
        )
        subject_no = ctx.get("subject_no") or record.get("subject_no")
        onset_at = ctx.get("onset_at") or record.get("onset_at")
        flags = ctx.get("seriousness_flags") or (record.get("seriousness") or {}).get("flags")

        sae = {
            "sae_no": record.get("sae_no"),
            "subject_no": subject_no,
            "ae_description": ae_description,
            "onset_at": onset_at,
        }

        # 批量时限扫描模式（只读计算，不建通知）
        scan_mode = ctx.get("scan") is True
        scan_result: list[dict[str, Any]] = []
        if scan_mode:
            reports = ctx.get("reports")
            if reports is None and db is not None:
                reports = await _load_reports(db, tenant_id)
            now = datetime.now(UTC)
            for r in reports or []:
                remaining = _remaining_hours(r.get("report_deadline_1"), now)
                scan_result.append(
                    {
                        "id": r.get("id"),
                        "sae_no": r.get("sae_no"),
                        "status": r.get("status"),
                        "remaining_hours": remaining,
                        "urgent": remaining is not None and remaining <= 4,
                    }
                )

        severity = assess_seriousness(ae_description, flags)
        deadlines = estimate_deadlines(onset_at, severity["urgent_24h"])
        draft = _build_draft(sae, severity, deadlines)

        return {
            "agent": self.name,
            "output": {
                "mode": "scan" if scan_mode else "assess",
                "severity_assessment": severity,
                "deadline_estimate": deadlines,
                "report_draft": draft,
                "deadline_scan": scan_result,
                "urgent_count": len([s for s in scan_result if s.get("urgent")]),
                "writes_disabled": True,
                "human_actions": [
                    "PV 复核分级与因果关系（pv_review）",
                    "生成正式报告草稿（generate_draft）",
                    "研究者电子签名（sign_sae）",
                    "提交（submit_sae）",
                ],
            },
        }
