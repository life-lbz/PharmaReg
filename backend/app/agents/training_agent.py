"""培训考核 Agent（规格 6.3 专家 Agent：培训考核）。

职责（均为建议/草稿性质，落库由培训 API 完成）：
1. 抽题组卷：按岗位类别（position_type）从题库抽取试题，返回"组卷快照"，
   真实发布试卷由 POST /training/exams（API）完成；
2. 在线批改：比对考生答案与标准答案，输出预评分与通过/未通过建议，
   成绩落库逻辑位于 training_service.submit_exam 内，本 Agent 不触碰；
3. 认证建议：基于证书矩阵（cert_matrix）与到期信息，输出复训/再认证建议。

设计约束：
- Agent 层严禁写库（只读）。当 context 已携带足够数据时无需 db 即可返回；
  仅当数据缺失且 db 可用时，使用只读查询（list_questions / get_cert_matrix
  / get_analytics）补全。
- 输出完全由确定性规则与模板组装，不依赖 llm_client，可在 stub 环境下单测。
"""
from __future__ import annotations

import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import BaseAgent
from app.models.training import Question
from app.services import training_service

# 与 create_exam assist 模式保持一致：默认组卷题量
DEFAULT_QUESTION_COUNT = 20
DEFAULT_PASS_SCORE = 80.0

ACTIONS = ("compose", "grade", "cert_advice", "auto")
_ACTION_ALIASES = {
    "compose": ("compose", "组卷", "抽题", "出卷", "组卷快照", "snapshot"),
    "grade": ("grade", "批改", "判分", "评分", "预评"),
    "cert_advice": ("cert_advice", "cert", "认证", "建议", "到期提醒"),
}


def _resolve_action(action: str | None) -> str:
    """把用户/调用方传入的动作别名归一为 ACTIONS 之一。"""
    if not action or action == "auto":
        return "auto"
    lower = str(action).lower()
    for canonical, aliases in _ACTION_ALIASES.items():
        if lower in aliases:
            return canonical
    return "auto"


async def _load_active_questions(
    db: AsyncSession, position_type: str | None, tenant_id: int
) -> list[Question]:
    """只读：加载某岗位类别的启用中题目（作为组卷候选池）。"""
    stmt = select(Question).where(
        Question.status == "active",
        Question.is_deleted == False,
        Question.tenant_id == tenant_id,
    )
    if position_type:
        stmt = stmt.where(Question.position_type == position_type)
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _bank_from_context(context: dict[str, Any]) -> list[dict[str, Any]]:
    """从 context 读取调用方传入的题库（无需 db 的模式）。"""
    bank = context.get("question_bank")
    if not isinstance(bank, list):
        return []
    position_type = context.get("position_type")
    if position_type:
        return [q for q in bank if not q.get("position_type") or q["position_type"] == position_type]
    return list(bank)


def _question_item(q: Question | dict[str, Any]) -> dict[str, Any]:
    """将 ORM / dict 题目序列化为不携带标准答案的展示项。"""
    if isinstance(q, dict):
        return {
            "id": q.get("id"),
            "type": q.get("type"),
            "stem": q.get("stem"),
            "options": q.get("options"),
            "difficulty": q.get("difficulty"),
        }
    return {
        "id": q.id,
        "type": q.type,
        "stem": q.stem,
        "options": q.options,
        "difficulty": q.difficulty,
    }


def _compose_snapshot(context: dict[str, Any], bank: list[Any], db_used: bool) -> dict[str, Any]:
    """确定性组卷：从题库中抽题并输出组卷快照（不含答案、不落库）。"""
    position_type = context.get("position_type") or "通用"
    question_count = int(context.get("question_count") or DEFAULT_QUESTION_COUNT)
    if question_count <= 0:
        question_count = DEFAULT_QUESTION_COUNT

    total = len(bank)
    if total == 0:
        return {
            "status": "empty",
            "message": "题库为空，无法组卷；请先维护题目或放宽过滤条件",
            "question_count": 0,
            "questions": [],
        }

    if context.get("pick_mode") == "order" or total <= question_count:
        picked = list(bank[:question_count])
    else:
        # 与 auto_generate_questions 的随机抽题保持同风格；可传 seed 保证可复现
        rng = random.Random(context.get("seed")) if context.get("seed") is not None else random
        picked = rng.sample(bank, question_count)

    items = [_question_item(q) for q in picked]
    difficulty_map: dict[str, int] = {}
    type_map: dict[str, int] = {}
    for item in items:
        diff = item.get("difficulty") or 3
        difficulty_map[f"level_{diff}"] = difficulty_map.get(f"level_{diff}", 0) + 1
        qtype = item.get("type") or "unknown"
        type_map[qtype] = type_map.get(qtype, 0) + 1

    return {
        "title": context.get("title") or f"{position_type}岗位考核-组卷快照",
        "position_type": position_type,
        "pass_score": float(context.get("pass_score") or DEFAULT_PASS_SCORE),
        "question_count": len(items),
        "difficulty_profile": difficulty_map,
        "type_profile": type_map,
        "questions": items,
        "source": "db_active_pool" if db_used else "context_bank",
        "status": "snapshot_pending_publish",
        "persist_hint": "组卷快照仅作预览；请调用 POST /training/exams 由 API 创建并发布试卷",
    }


def _grade_answers(context: dict[str, Any]) -> dict[str, Any]:
    """确定性批改：将 answers 与题目标准答案比对，逻辑对齐 submit_exam。"""
    questions = context.get("questions") or []
    answers = context.get("answers") or {}
    if not questions or not answers:
        return {"status": "empty", "message": "缺少题目或答案，无法批改", "score": None}

    pass_score = float(context.get("pass_score") or DEFAULT_PASS_SCORE)
    correct = 0
    total = len(questions)
    details = []
    for raw in questions:
        qid = str(raw.get("id") if isinstance(raw, dict) else raw.id)
        q_answer = raw.get("answer") if isinstance(raw, dict) else raw.answer
        user_answer = str(answers.get(qid) or "").strip()
        standard = str(q_answer or "").strip()
        right = bool(standard) and user_answer == standard
        if right:
            correct += 1
        details.append(
            {
                "question_id": qid,
                "correct": right,
                "user_answer": user_answer,
                "standard_answer": standard,
            }
        )

    score = round(correct / total * 100, 1)
    passed = score >= pass_score
    return {
        "total": total,
        "correct": correct,
        "wrong": total - correct,
        "score": score,
        "pass_score": pass_score,
        "passed": passed,
        "details": details,
        "status": "suggestion",
        "persist_hint": "本结果仅为 AI 预评分建议；成绩记录请由考试提交 API（submit_exam）完成",
    }


def _cert_advice(cert_matrix: list[dict[str, Any]]) -> dict[str, Any]:
    """基于证书矩阵生成认证到期提醒与复训建议。"""
    expiring: list[dict[str, Any]] = []
    for row in cert_matrix or []:
        employee_no = row.get("employee_no")
        for pos in row.get("positions") or []:
            if pos.get("is_expiring_soon"):
                expiring.append(
                    {
                        "employee_no": employee_no,
                        "position_type": pos.get("position_type"),
                        "issue_date": pos.get("issue_date"),
                        "expire_date": pos.get("expire_date"),
                    }
                )
    advice = []
    if not expiring:
        advice.append("当前无 30 天内到期的认证，继续按培训计划开展复训即可。")
    for item in expiring:
        advice.append(
            f"{item['employee_no']} 的 {item['position_type']} 认证将于 {item['expire_date']} "
            "到期，建议安排复训与再认证考核。"
        )
    return {
        "valid_certifications": len(cert_matrix or []),
        "expiring_soon_count": len(expiring),
        "expiring_soon": expiring,
        "advice": advice,
        "persist_hint": "认证签发由 POST /training/certifications API 与人工完成，本 Agent 仅给建议",
    }


class TrainingAgent(BaseAgent):
    """培训考核专家 Agent：组卷快照 / 批改建议 / 认证建议（只读）。"""

    name = "培训考核"
    description = "抽题组卷快照、在线批改建议与认证到期提醒；写操作由培训 API 完成"
    tools = ["compose_exam_snapshot", "grade_suggestion", "cert_advice"]

    async def run(
        self,
        query: str,
        context: dict[str, Any] | None = None,
        db: AsyncSession | None = None,
        tenant_id: int = 1,
    ) -> dict[str, Any]:
        ctx = context or {}
        action = _resolve_action(ctx.get("action"))
        position_type = ctx.get("position_type")
        if action == "auto":
            if ctx.get("answers") and ctx.get("questions"):
                action = "grade"
            elif ctx.get("question_bank") or position_type or db is not None:
                action = "compose"
            elif ctx.get("cert_matrix"):
                action = "cert_advice"
            else:
                action = "compose"

        output: dict[str, Any] = {
            "action": action,
            "position_type": position_type,
            "query": query,
            "snapshot": None,
            "grade": None,
            "cert_advice": None,
            "writes_delegated_to_api": True,
        }

        if action == "grade":
            output["grade"] = _grade_answers(ctx)
            # 同一次调用若同时给证书矩阵，则附加认证建议
            if ctx.get("cert_matrix"):
                output["cert_advice"] = _cert_advice(ctx.get("cert_matrix") or [])

        elif action == "cert_advice":
            cert_matrix = ctx.get("cert_matrix")
            if cert_matrix is None and db is not None:
                cert_matrix = await training_service.get_cert_matrix(db, ctx.get("department"), tenant_id)
            output["cert_advice"] = _cert_advice(cert_matrix or [])

        else:  # compose
            bank = _bank_from_context(ctx)
            db_used = False
            if not bank and db is not None:
                active = await _load_active_questions(db, position_type, tenant_id)
                bank = active
                db_used = True
            output["snapshot"] = _compose_snapshot(ctx, bank, db_used)

        return {"agent": self.name, "output": output}
