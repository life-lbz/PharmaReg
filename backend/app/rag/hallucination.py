import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.models.regulation import RegClause
from app.rag.llm_client import llm_client
from app.rag.prompts import load_prompt

CLAUSE_PATTERN = re.compile(r"第[一二三四五六七八九十百零\d]+条")
# 校验角色 prompt 版本化（docs/prompts/claim_verifier.md），缺失时回退内嵌
CLAIM_VERIFIER_SYSTEM = load_prompt("claim_verifier") or (
    "你是合规校验助手。判断声明是否被上下文支持，只回答 yes 或 no。"
)


async def verify_clause_existence(db: AsyncSession, draft_answer: str) -> dict[str, Any]:
    clauses_found = CLAUSE_PATTERN.findall(draft_answer)
    if not clauses_found:
        return {"total": 0, "hit": 0, "miss": 0, "missed": [], "hit_rate": 1.0}

    total = len(clauses_found)
    hit = 0
    missed: list[str] = []

    for clause_no in clauses_found:
        result = await db.execute(
            select(RegClause).where(RegClause.clause_no.contains(clause_no), RegClause.status == "active")
        )
        if result.scalar_one_or_none():
            hit += 1
        else:
            missed.append(clause_no)

    hit_rate = hit / total if total > 0 else 1.0
    return {"total": total, "hit": hit, "miss": total - hit, "missed": missed, "hit_rate": hit_rate}


def split_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[。；！？\n])", text)
    return [s.strip() for s in sentences if s.strip() and len(s.strip()) > 5]


async def verify_claims(
    db: AsyncSession,
    sentences: list[str],
    context: list[dict[str, Any]],
) -> dict[str, Any]:
    verified = 0
    unverified: list[str] = []

    context_text = "\n".join([c.get("text", "") for c in context[:5]])

    for sentence in sentences:
        if not CLAUSE_PATTERN.search(sentence) and not any(
            kw in sentence for kw in ["必须", "应当", "不得", "禁止", "要求", "规定"]
        ):
            verified += 1
            continue

        try:
            verdict = await llm_client.chat([
                {"role": "system", "content": CLAIM_VERIFIER_SYSTEM},
                {"role": "user", "content": f"声明：{sentence}\n\n上下文：{context_text}\n\n该声明是否有上下文依据？"},
            ], temperature=0.0)
            if "yes" in verdict.lower():
                verified += 1
            else:
                unverified.append(sentence)
        except Exception as e:
            logger.warning("claim_verify_failed", error=str(e))
            unverified.append(sentence)

    total = len(sentences)
    pass_rate = verified / total if total > 0 else 1.0
    return {
        "total": total,
        "verified": verified,
        "unverified": unverified,
        "pass_rate": pass_rate,
    }


async def verify_claims_stub(
    sentences: list[str],
    context: list[dict[str, Any]],
) -> dict[str, Any]:
    """确定性声明校验（stub 模式）：句子能在召回上下文中逐字找到即视为有依据。

    用于无 LLM 生成/裁判的联调路径；与 verify_claims 输出结构一致。
    """
    context_text = "\n".join([c.get("text", "") for c in context[:8]])
    verified = 0
    unverified: list[str] = []

    for sentence in sentences:
        if len(sentence) <= 5:
            verified += 1
            continue
        if sentence in context_text:
            verified += 1
        elif not CLAUSE_PATTERN.search(sentence) and not any(
            kw in sentence for kw in ["必须", "应当", "不得", "禁止", "要求", "规定", "建议"]
        ):
            verified += 1
        else:
            unverified.append(sentence)

    total = len(sentences)
    pass_rate = verified / total if total > 0 else 1.0
    return {
        "total": total,
        "verified": verified,
        "unverified": unverified,
        "pass_rate": pass_rate,
    }


def compute_confidence(
    rerank_score: float,
    clause_hit_rate: float,
    claim_pass_rate: float,
) -> float:
    score = (
        0.5 * min(rerank_score, 1.0) +
        0.3 * clause_hit_rate +
        0.2 * claim_pass_rate
    )
    return round(score, 4)


def should_block(confidence: float, has_unverified: bool, unverified_ratio: float) -> bool:
    if confidence < 0.6:
        return True
    if unverified_ratio > 0.3:
        return True
    return False
