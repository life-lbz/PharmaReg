"""偏差处理 Agent（规格 6.3 专家 Agent：偏差处理）。

职责（全部为 AI 建议，不写库）：
1. 分级建议：依据偏差描述中的关键词给出 critical / major / minor 分级初判与理由；
2. 案例检索：检索同类历史偏差记录，供调查参考（仅只读查询）；
3. 调查计划：按分级输出"人机料法环"调查计划草案与时限建议。

设计约束：
- Agent 层严禁写库。分级确认（classify）、调查计划落库（investigate）等动作
  由偏差 API 与人工完成；
- 当 context 已携带偏差/历史案例数据时无需 db 即可返回；仅数据缺失且 db 可用时，
  复用 quality_service 的只读查询或直查 Deviation 表补齐。
- 输出为确定性规则/模板组装，不依赖 llm_client。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.models.quality import Deviation

# 分级关键词（在描述命中即加分/判定）
CRITICAL_KEYWORDS = (
    "产品放行", "批次放行", "已上市", "市场", "召回", "患者", "无菌", "污染",
    "数据完整性", "重大", "造假", "交叉污染", "微生物", "假药", "劣药",
)
MAJOR_KEYWORDS = (
    "关键工艺", "工艺参数", "超限", "oos", "ooe", "未按sop", "违反",
    "验证失败", "关键设备", "中间体", "混批", "混料", "产量异常", "偏差处理不当",
)


def classify_severity(description: str) -> dict[str, Any]:
    """依据描述关键词给出偏差严重度初判（critical/major/minor）。"""
    text = description or ""
    critical_hits = [kw for kw in CRITICAL_KEYWORDS if kw in text]
    major_hits = [kw for kw in MAJOR_KEYWORDS if kw in text]

    if critical_hits:
        severity = "critical"
        reasons = [f"命中关键质量/放行相关特征：{kw}" for kw in critical_hits[:5]]
    elif major_hits:
        severity = "major"
        reasons = [f"命中关键工艺/合规偏离特征：{kw}" for kw in major_hits[:5]]
    else:
        severity = "minor"
        reasons = ["未命中关键特征词，初步按一般偏差处理"]

    # 置信度：命中越多置信越高；仅做演示性确定性评分
    confidence = min(0.95, 0.6 + 0.1 * len(critical_hits) + 0.05 * len(major_hits))
    if severity == "minor":
        confidence = 0.6
    return {
        "suggested_severity": severity,
        "keywords": critical_hits or major_hits,
        "reasons": reasons,
        "confidence": round(confidence, 2),
        "note": "分级为 AI 建议，需 QA 复核确认后通过偏差 API（classify）正式写入",
    }


def build_investigation_plan(severity: str, title: str, description: str) -> dict[str, Any]:
    """按分级输出调查计划草案（人机料法环 + 5-Why/鱼骨图）。"""
    if severity == "critical":
        steps = [
            "立即隔离相关批次/区域，暂停放行并评估批次影响范围",
            "24 小时内向 QA/管理层通报，必要时启动紧急调查与召回评估",
            "成立跨部门调查组，冻结相关记录与留样",
            "按人机料法环五维度收集证据（人员访谈/设备日志/物料台账/方法记录/环境监测）",
            "使用 5-Why / 鱼骨图定位根因",
            "根因确认后评估 CAPA 与批次处置（报废/返工/让步放行）",
            "关闭前由 QA 复核调查完整性并电子签名",
        ]
        timeline = "建议 7 日内完成初步调查；涉及放行影响需 48 小时内给出阶段结论"
        extra = {"batch_hold": "critical 级别建议立即评估批次挂起（API：create_batch_hold）"}
    elif severity == "major":
        steps = [
            "隔离受影响批次/记录，评估偏差对关键质量属性的影响",
            "3 日内完成证据收集与初步分析",
            "按人机料法环五维度调查，必要时成立专项小组",
            "使用 5-Why 定位根因并复核类似偏差历史",
            "评估是否需要 CAPA 与再验证/再培训",
        ]
        timeline = "建议 14 日内完成调查并给出结论"
        extra = {}
    else:
        steps = [
            "记录偏差现象、发生时间与涉及批次/区域",
            "排查直接原因（人员操作/设备波动/记录差错）",
            "必要时补充证据后关闭；无需 CAPA 则说明理由",
        ]
        timeline = "建议 30 日内完成调查并关闭"
        extra = {}

    return {
        "title": title,
        "description": description,
        "dimensions": ["人", "机", "料", "法", "环"],
        "tools": ["5-Why", "鱼骨图（因果图）"],
        "steps": steps,
        "timeline_hint": timeline,
        "severity_specific": extra,
        "capa_suggestion": "根因确认后评估是否需要发起 CAPA（偏差 API create_capa 关联）",
        "note": "调查计划为 AI 草案，落库由偏差 API（investigate）与人工完成",
    }


async def search_similar_cases(
    db: AsyncSession, keywords: list[str], tenant_id: int, limit: int = 5
) -> list[dict[str, Any]]:
    """只读：按关键词检索历史偏差作为同类案例参考。"""
    terms = [kw for kw in keywords if kw]
    if not terms:
        return []
    stmt = (
        select(Deviation)
        .where(
            Deviation.is_deleted == False,
            Deviation.tenant_id == tenant_id,
            or_(*[Deviation.title.contains(t) for t in terms], *[Deviation.description.contains(t) for t in terms]),
        )
        .order_by(Deviation.id.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        {
            "id": d.id,
            "dev_no": d.dev_no,
            "title": d.title,
            "severity": d.severity,
            "category": d.category,
            "status": d.status,
            "root_cause": d.root_cause,
            "capa_id": d.capa_id,
        }
        for d in result.scalars().all()
    ]


class DeviationAgent(BaseAgent):
    """偏差处理专家 Agent：分级建议 / 案例检索 / 调查计划草案（只读）。"""

    name = "偏差处理"
    description = "偏差严重度分级建议、同类案例检索与调查计划草案；不写库"
    tools = ["classify_severity", "search_case", "draft_investigation_plan"]

    async def run(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        db: AsyncSession | None = None,
        tenant_id: int = 1,
    ) -> dict[str, Any]:
        ctx = context or {}
        # 兼容两种传参：顶层字段或嵌套在 deviation 记录里
        record = ctx.get("deviation")
        description = ctx.get("description") or (record or {}).get("description") or query
        title = ctx.get("title") or (record or {}).get("title") or "偏差调查"
        category = ctx.get("category") or (record or {}).get("category")

        severity_advice = classify_severity(description)
        suggested = severity_advice["suggested_severity"]

        # 案例检索：优先使用 context 提供的历史案例
        case_refs = ctx.get("similar_cases") or ctx.get("case_refs")
        if case_refs is None and db is not None:
            matched_keywords = severity_advice["keywords"] or [title]
            case_refs = await search_similar_cases(db, matched_keywords[:2], tenant_id)
        case_refs = list(case_refs or [])

        plan = build_investigation_plan(suggested, title, description)

        return {
            "agent": self.name,
            "output": {
                "mode": "advise",
                "deviation": {
                    "title": title,
                    "description": description,
                    "category": category,
                    "current_severity": (record or {}).get("severity"),
                    "current_status": (record or {}).get("status"),
                },
                "severity_suggestion": severity_advice,
                "case_refs": case_refs,
                "case_ref_count": len(case_refs),
                "investigation_plan_draft": plan,
                "writes_disabled": True,
                "persist_hint": "分级确认请调用 classify 接口；调查计划请调用 investigate 接口；本 Agent 仅给建议",
            },
        }
