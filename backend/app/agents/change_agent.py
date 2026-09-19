"""变更评估 Agent（规格 6.3 专家 Agent：变更评估）。

职责（仅草稿）：
1. 依据变更类型与描述给出影响等级（high/medium/low）初判；
2. 生成影响评估初稿：覆盖生产/质量/验证/文件/培训/注册等影响面；
3. 检索法规条款依据（RegClause 只读查询）供四眼评估参考。

设计约束：
- 本 Agent 只输出"影响评估初稿"，正式评估（assess_change）与四眼审批
  （approve_change）由变更 API 与人工完成，Agent 不写库；
- context 已携带数据时无需 db 即可返回；法规依据缺失且 db 可用时通过
  RegClause 只读检索补齐。
- 输出为确定性规则/模板组装，不依赖 llm_client。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.models.regulation import RegClause

# 变更类型 → 影响面/检索主题词（用于法规依据检索）
CHANGE_TYPE_TERMS: dict[str, dict[str, Any]] = {
    "工艺与生产": {
        "keywords": ["工艺", "生产", "处方", "批量", "参数", "关键工艺"],
        "impact_areas": ["生产工艺", "质量属性", "验证", "注册/备案"],
    },
    "厂房与设施": {
        "keywords": ["厂房", "设施", "空调", "洁净区", "水系统", "压缩空气", "设备"],
        "impact_areas": ["厂房设施", "HVAC/公用系统", "设备确认", "环境监测"],
    },
    "检验方法": {
        "keywords": ["检验方法", "分析方法", "质量标准", "稳定性", "仪器"],
        "impact_areas": ["QC 检验", "分析方法验证", "质量标准", "稳定性考察"],
    },
    "物料与供应商": {
        "keywords": ["物料", "原料", "辅料", "供应商", "包材"],
        "impact_areas": ["物料供应", "供应商管理", "来料检验", "仓储"],
    },
    "计算机化系统": {
        "keywords": ["计算机化", "系统", "软件", "数据", "电子记录", "LIMS", "MES"],
        "impact_areas": ["计算机化系统验证", "数据完整性", "电子签名/审计追踪"],
    },
    "包装与标签": {
        "keywords": ["包装", "标签", "说明书", "装箱"],
        "impact_areas": ["包装工艺", "标签内容合规", "条码/防伪"],
    },
    "其它变更": {
        "keywords": [],
        "impact_areas": ["文件", "行政", "培训"],
    },
}

HIGH_LEVEL_KEYWORDS = ("无菌", "注册", "已上市", "关键工艺", "分析方法", "计算机化系统", "数据完整性", "批量放大")
MEDIUM_LEVEL_KEYWORDS = ("厂房", "设备", "物料", "供应商", "包装", "标签", "洁净区", "公用系统")


def _match_change_type(text: str) -> tuple[str, dict[str, Any]]:
    """按关键词把变更分类到 CHANGE_TYPE_TERMS 的某个类别。"""
    for name, spec in CHANGE_TYPE_TERMS.items():
        if name == "其它变更":
            continue
        if any(kw in text for kw in spec["keywords"]):
            return name, spec
    return "其它变更", CHANGE_TYPE_TERMS["其它变更"]


def assess_impact_level(title: str, description: str, change_type: str) -> dict[str, Any]:
    """确定性规则：给出影响等级初判与理由。"""
    text = f"{title} {description}"
    high_hits = [kw for kw in HIGH_LEVEL_KEYWORDS if kw in text]
    medium_hits = [kw for kw in MEDIUM_LEVEL_KEYWORDS if kw in text]

    if high_hits:
        level = "high"
        reasons = [f"涉及高影响要素：{kw}" for kw in high_hits[:5]]
        suggestions = [
            "需开展风险评估并补充工艺验证/确认（必要时稳定性与注册备案评估）",
            "评估对已上市产品放行与供应的潜在影响",
            "由跨部门（QA/注册/验证/生产）评审并走四眼审批",
        ]
    elif medium_hits or change_type not in ("其它变更",):
        level = "medium"
        reasons = [f"涉及中影响要素：{kw}" for kw in medium_hits[:5]] or [f"变更类别：{change_type}"]
        suggestions = [
            "开展针对性确认/验证与人员培训",
            "更新相关文件并评估对现有验证状态的回归影响",
        ]
    else:
        level = "low"
        reasons = ["未命中高/中影响要素，初步判定为低影响变更"]
        suggestions = ["更新相关文件并完成评审后即可实施"]

    return {
        "suggested_level": level,
        "reasons": reasons,
        "suggestions": suggestions,
        "note": "等级与评估均为 AI 初稿，须经 assess_change 接口与四眼审批确认",
    }


def _impact_areas(category_name: str, spec: dict[str, Any]) -> list[dict[str, str]]:
    """按变更类别展开影响面清单。"""
    return [
        {"area": area, "action": "评估变更对该领域文件/状态的影响并留痕"}
        for area in spec["impact_areas"]
    ]


async def _fetch_reg_basis(db: AsyncSession, terms: list[str], tenant_id: int, limit: int = 5) -> list[dict[str, Any]]:
    """只读：按主题词检索现行法规条款作为依据引用。"""
    if not terms:
        return []
    stmt = (
        select(RegClause)
        .where(
            RegClause.status == "active",
            RegClause.is_deleted == False,
            RegClause.tenant_id == tenant_id,
            or_(*[RegClause.content.contains(t) for t in terms]),
        )
        .order_by(RegClause.normalized_no)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        {
            "clause_id": c.id,
            "clause_no": c.clause_no,
            "content": c.content[:200],
            "doc_version": c.doc_version,
        }
        for c in result.scalars().all()
    ]


class ChangeAgent(BaseAgent):
    """变更评估专家 Agent：影响评估初稿（含法规依据检索，仅草稿不落库）。"""

    name = "变更评估"
    description = "变更影响评估初稿与法规依据检索；正式评估与四眼审批走变更 API"
    tools = ["draft_impact_assessment", "search_reg_basis"]

    async def run(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        db: AsyncSession | None = None,
        tenant_id: int = 1,
    ) -> dict[str, Any]:
        ctx = context or {}
        record = ctx.get("change") or {}
        title = ctx.get("title") or record.get("title") or query
        description = ctx.get("description") or record.get("description") or title
        change_type = ctx.get("change_type") or record.get("change_type") or "其它变更"
        chg_no = ctx.get("chg_no") or record.get("chg_no")

        category_name, category_spec = _match_change_type(f"{title} {description} {change_type}")
        level = assess_impact_level(title, description, change_type)

        # 法规依据：优先 context 提供，否则读库检索
        basis = ctx.get("reg_basis")
        if basis is None and db is not None:
            terms = category_spec["keywords"] or ["变更", "验证"]
            terms = terms + ["变更控制", "验证"]
            basis = await _fetch_reg_basis(db, list(dict.fromkeys(terms)), tenant_id)
        if not basis:
            basis = [{"note": "未检索到直接条款引用，请人工核对现行 GMP/GSP 变更控制条款"}]

        draft = {
            "title": title,
            "chg_no": chg_no,
            "change_type": category_name,
            "raw_change_type": change_type,
            "description": description,
            "impact_level_suggestion": level,
            "impact_areas": _impact_areas(category_name, category_spec),
            "verification_suggestion": level["suggestions"],
            "regulatory_basis": basis,
            "reg_basis_count": len(basis),
            "status": "draft",
            "persist_hint": "评估初稿为草稿；正式评估请调用变更 API（assess_change/approve_change）并四眼审批",
        }
        return {"agent": self.name, "output": {"impact_assessment_draft": draft, "writes_disabled": True}}
