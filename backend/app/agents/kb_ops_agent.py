"""法规库运维 Agent（规格 6.3 专家 Agent：法规库运维）。

职责（只读分析 + 候选产出）：
1. 新规入库差异：扫描 KbVersion 与 RegVersionDiff，汇总各版本待复核差异（added/revised/removed）；
2. FAQ 候选：将"新增/修订"差异条款转化为 FAQ 候选草稿（供人工审核后走 FAQ API）；
3. 激活/冻结提醒：仅提示人工操作，Agent 不执行 activate_version/freeze。

设计约束：
- 复用 kb_service.list_versions 只读接口；差异明细通过 RegVersionDiff 只读查询；
- Agent 严禁写库，激活/冻结/建 FAQ 一律由 API 与人工完成；
- context 已携带 versions/diffs 数据时无需 db；输出确定性、可单测。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.models.regulation import KbVersion, RegVersionDiff
from app.services import kb_service

# FAQ 候选摘要长度上限
_EXCERPT_LEN = 200


def _dget(obj: Any, name: str) -> Any:
    """兼容 ORM 对象与 dict 的字段取值。"""
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _diff_stats(diffs: list[Any]) -> dict[str, int]:
    """汇总一批差异记录的类型与复核状态计数。"""
    stats: dict[str, int] = {"added": 0, "revised": 0, "removed": 0, "pending": 0, "reviewed": 0}
    for diff in diffs:
        change_type = _dget(diff, "change_type") or "revised"
        stats[change_type] = stats.get(change_type, 0) + 1
        if (_dget(diff, "review_status") or "pending") == "pending":
            stats["pending"] += 1
        else:
            stats["reviewed"] += 1
    return stats


def build_faq_candidates(diffs: list[Any], regulation: str, version_label: str) -> list[dict[str, Any]]:
    """将新增/修订差异条款转化为 FAQ 候选（确定性模板组装）。"""
    candidates: list[dict[str, Any]] = []
    for diff in diffs:
        if _dget(diff, "change_type") == "removed":
            continue
        clause_no = "（待核对条款号）"  # 条款号需由 from/to_clause_id 关联 RegClause 后核对
        content = _dget(diff, "new_content") or _dget(diff, "old_content") or ""
        change_type = _dget(diff, "change_type")
        if change_type == "added":
            question = f"{regulation} {version_label} 新增条款 {clause_no} 的要求要点？"
        else:
            question = f"{regulation} {version_label} 对条款 {clause_no} 作了哪些修订？"
        candidates.append(
            {
                "question": question,
                "answer_excerpt": content[:_EXCERPT_LEN] + ("…" if len(content) > _EXCERPT_LEN else ""),
                "source": {"change_type": change_type, "from_clause_id": _dget(diff, "from_clause_id"), "to_clause_id": _dget(diff, "to_clause_id")},
                "status": "candidate",
                "persist_hint": "FAQ 候选须人工审核后由 FAQ API 创建或作废",
            }
        )
    return candidates


def _serialize_version(v: KbVersion) -> dict[str, Any]:
    return {
        "id": v.id,
        "regulation": v.regulation,
        "version_label": v.version_label,
        "collection_prefix": v.collection_prefix,
        "doc_collection": v.doc_collection,
        "faq_collection": v.faq_collection,
        "case_collection": v.case_collection,
        "status": v.status,
        "diff_source_version_id": v.diff_source_version_id,
    }


async def _load_versions_with_diffs(db: AsyncSession, tenant_id: int) -> list[tuple[KbVersion, list[RegVersionDiff]]]:
    """只读：列出版本并统计各版本对应的差异记录。"""
    versions = await kb_service.list_versions(db, tenant_id)
    if not versions:
        return []
    version_ids = [v.id for v in versions]
    result = await db.execute(
        select(RegVersionDiff).where(RegVersionDiff.to_version_id.in_(version_ids))
    )
    diff_rows = list(result.scalars().all())
    by_version: dict[int, list[RegVersionDiff]] = {}
    for diff in diff_rows:
        by_version.setdefault(diff.to_version_id, []).append(diff)
    return [(v, by_version.get(v.id, [])) for v in versions]


class KbOpsAgent(BaseAgent):
    """法规库运维专家 Agent：新规入库差异 / FAQ 候选（激活与冻结仅人工）。"""

    name = "法规库运维"
    description = "新规入库差异汇总与 FAQ 候选草稿；版本激活/冻结仅人工操作"
    tools = ["scan_version_diff", "draft_faq_candidates"]

    async def run(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        db: AsyncSession | None = None,
        tenant_id: int = 1,
    ) -> dict[str, Any]:
        ctx = context or {}

        # 1) 版本扫描：优先 context（已序列化的 versions + diffs），否则读库
        versions = ctx.get("versions")
        diffs_map: dict[int, list[RegVersionDiff]] = {}
        if versions is None and db is not None:
            loaded = await _load_versions_with_diffs(db, tenant_id)
            versions = [_serialize_version(v) for v, _diffs in loaded]
            for v, diffs in loaded:
                diffs_map[v.id] = diffs
        versions = versions or []

        version_scan = []
        all_diffs: list[RegVersionDiff] = []
        for version in versions:
            vid = version.get("id") if isinstance(version, dict) else version.id
            diffs = diffs_map.get(vid, [])
            all_diffs.extend(diffs)
            stats = _diff_stats(diffs)
            status = version.get("status") if isinstance(version, dict) else version.status
            version_label = version.get("version_label") if isinstance(version, dict) else version.version_label
            regulation = version.get("regulation") if isinstance(version, dict) else version.regulation
            hint = ""
            if status == "draft" and stats["pending"] > 0:
                hint = f"存在 {stats['pending']} 条待复核差异，复核通过后由管理员激活"
            elif status == "draft":
                hint = "无待复核差异，可由管理员激活"
            elif status == "active":
                hint = "当前生效版本（冻结需管理员人工操作）"
            version_scan.append(
                {
                    "version_id": vid,
                    "regulation": regulation,
                    "version_label": version_label,
                    "status": status,
                    "diff_stats": stats,
                    "hint": hint,
                }
            )

        # context 模式允许直接传已序列化差异
        ctx_diffs = ctx.get("diffs")
        if isinstance(ctx_diffs, list):
            all_diffs = ctx_diffs  # 仅用于 FAQ 候选
        regulation = ctx.get("regulation") or (version_scan[0]["regulation"] if version_scan else "法规")
        version_label = ctx.get("version_label") or (version_scan[0]["version_label"] if version_scan else "")

        # 2) FAQ 候选：仅对新增/修订差异生成
        faq_candidates = build_faq_candidates(all_diffs, regulation, version_label)

        # 3) 人工动作清单
        human_actions = ["版本激活/冻结/回滚由管理员人工执行（API：activate/rollback）"]
        for item in version_scan:
            if item["status"] == "draft" and item["diff_stats"]["pending"] > 0:
                human_actions.append(
                    f"人工复核 {item['regulation']} {item['version_label']} 的 "
                    f"{item['diff_stats']['pending']} 条差异（review_diff）"
                )
        if faq_candidates:
            human_actions.append("审核 FAQ 候选后由 FAQ API 正式创建")

        return {
            "agent": self.name,
            "output": {
                "version_scan": version_scan,
                "total_versions": len(version_scan),
                "pending_diff_total": sum(v["diff_stats"]["pending"] for v in version_scan),
                "faq_candidates": faq_candidates,
                "faq_candidate_count": len(faq_candidates),
                "human_actions": human_actions,
                "writes_disabled": True,
            },
        }
