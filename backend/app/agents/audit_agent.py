"""审计准备 Agent（规格 6.3 专家 Agent：审计准备）。

职责（仅草稿）：
1. 依据检查类型（gmp/gcp/iso）生成审计检查表草稿；
2. 逐项起草证据需求并识别证据缺口（evidence gap）；
3. 输出迎检风险关注点。

设计约束：
- 检查表模板复用 audit_service.CHECKLIST_TEMPLATES（与 API 建单一致）；
- context 已携带 audit 记录/evidence 时无需 db 即可返回；数据缺失且 db 可用时
  通过 list_audit_checks/get_audit_check 只读补齐；
- 创建审计单、挂接证据、确认缺口均由审计 API 完成，Agent 不写库。
- 输出为确定性规则/模板组装，不依赖 llm_client。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.services import audit_service

# item 类型 → 建议证据种类
EVIDENCE_KIND: dict[str, list[str]] = {
    "verify": ["现场检查", "关键人员访谈", "过程观察记录"],
    "document": ["受控文件", "操作/批/检验记录", "培训记录", "验证报告"],
}


def _build_evidence_gaps(audit: dict[str, Any] | None) -> list[dict[str, Any]]:
    """依据检查表逐项识别证据缺口（已收集证据以 key 匹配标记为已覆盖）。"""
    checklist = (audit or {}).get("checklist") or {}
    sections = checklist.get("sections") or []
    collected = set()
    for ref in ((audit or {}).get("evidence_refs") or {}).get("items") or []:
        if ref.get("item_key"):
            collected.add(ref["item_key"])

    gaps: list[dict[str, Any]] = []
    for section in sections:
        for item in section.get("items") or []:
            key = item.get("key")
            if not key:
                continue
            if key in collected:
                gaps.append(
                    {"key": key, "text": item.get("text"), "covered": True, "status": "covered"}
                )
            else:
                gaps.append(
                    {
                        "key": key,
                        "text": item.get("text"),
                        "covered": False,
                        "required_evidence": EVIDENCE_KIND.get(item.get("type", "document"), []),
                        "status": "open",
                    }
                )
    return gaps


class AuditAgent(BaseAgent):
    """审计准备专家 Agent：检查表与证据缺口草稿（只读）。"""

    name = "审计准备"
    description = "迎检检查表与证据缺口草稿生成；建单/挂接证据走审计 API"
    tools = ["build_checklist_draft", "draft_evidence_gaps"]

    async def run(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        db: AsyncSession | None = None,
        tenant_id: int = 1,
    ) -> dict[str, Any]:
        ctx = context or {}
        # 推断检查类型：context 优先，其次 query 关键词，默认 gmp
        check_type = (ctx.get("check_type") or "").lower()
        if not check_type:
            lowered = query.lower()
            if "gcp" in lowered or "临床" in lowered:
                check_type = "gcp"
            elif "iso" in lowered or "体系" in lowered or "9001" in lowered:
                check_type = "iso"
            else:
                check_type = "gmp"
        if check_type not in audit_service.CHECKLIST_TEMPLATES:
            check_type = "gmp"

        audit = ctx.get("audit") or {}
        # 若 audit 已带检查表则使用；否则使用标准模板
        if not (audit or {}).get("checklist"):
            sections = audit_service.CHECKLIST_TEMPLATES.get(check_type, [])
            audit = {**(audit or {}), "checklist": {"sections": sections}}

        # 读库补充（例如传入 audit_id 拉取既有审计单状态）
        if not ctx.get("audit") and ctx.get("audit_id") and db is not None:
            try:
                existing = await audit_service.get_audit_check(db, int(ctx["audit_id"]))
                audit = {
                    "id": existing.id,
                    "audit_no": existing.audit_no,
                    "check_type": existing.check_type,
                    "status": existing.status,
                    "round_no": existing.round_no,
                    "checklist": existing.checklist,
                    "evidence_refs": existing.evidence_refs,
                    "gaps": existing.gaps,
                }
                check_type = existing.check_type or check_type
            except Exception:
                # 找不到记录时保持模板草稿
                audit = audit or {}

        gaps = _build_evidence_gaps(audit)
        open_gaps = [g for g in gaps if g.get("status") == "open"]

        total_items = sum(len(s.get("items") or []) for s in (audit.get("checklist") or {}).get("sections") or [])

        return {
            "agent": self.name,
            "output": {
                "check_type": check_type,
                "audit": {
                    "audit_no": audit.get("audit_no"),
                    "status": audit.get("status") or "draft",
                    "round_no": audit.get("round_no"),
                },
                "checklist_draft": audit.get("checklist"),
                "checklist_item_count": total_items,
                "evidence_gap_draft": gaps,
                "open_gap_count": len(open_gaps),
                "risk_attention": [
                    "对 document 类检查项，迎检前确认记录可追溯且受控",
                    "对 verify 类检查项，安排关键人员现场应答演练",
                ],
                "writes_disabled": True,
                "persist_hint": "创建审计检查单请调用审计 API（create_audit_check），挂接证据与确认缺口亦走 API，本 Agent 仅出草稿",
            },
        }
