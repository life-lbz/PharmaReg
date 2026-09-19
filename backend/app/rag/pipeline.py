from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import RetrievalError
from app.models.regulation import Faq, RegClause
from app.rag.hallucination import (
    compute_confidence,
    should_block,
    split_sentences,
    verify_claims,
    verify_claims_stub,
    verify_clause_existence,
)
from app.rag.llm_client import llm_client
from app.rag.prompts import load_prompt
from app.rag.retriever import classify_intent, retrieve
from app.rag.stub_llm import build_stub_answer

# 规格 5.4：Prompt 版本化存放于 docs/prompts/，此处加载（缺失时回退内嵌模板并告警）
SYSTEM_PROMPT = load_prompt("role_qa")
FAQ_SYSTEM_PROMPT = load_prompt("role_faq")

# stub 模式下证据相关性门控（bge-reranker 输出 ~[0,1]，命中通常 >0.8，无关通常 <0.05）
RERANK_MIN_EVIDENCE = 0.45


async def build_context(candidates: list[dict[str, Any]]) -> str:
    context_parts = []
    for c in candidates:
        context_parts.append(f"[{c.get('channel', 'doc')}] {c['text']}")
    return "\n\n".join(context_parts)


async def build_citations(db: AsyncSession, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations = []
    for c in candidates:
        entity_id = c.get("entity_id")
        if c.get("channel") == "doc" and entity_id:
            result = await db.execute(select(RegClause).where(RegClause.id == entity_id))
            clause = result.scalar_one_or_none()
            if clause:
                citations.append({
                    "clause_id": clause.id,
                    "clause_no": clause.clause_no,
                    "excerpt": c["text"][:200],
                    "collection": c.get("doc_version", ""),
                })
        elif c.get("channel") == "faq" and entity_id:
            result = await db.execute(select(Faq).where(Faq.id == entity_id))
            faq = result.scalar_one_or_none()
            if faq:
                citations.append({
                    "clause_id": faq.clause_refs.get("clause_ids", [])[0] if faq.clause_refs else None,
                    "clause_no": "FAQ",
                    "excerpt": faq.answer[:200],
                    "collection": "faq",
                })
    return citations


async def rag_answer(
    db: AsyncSession,
    query: str,
    history: list[dict] | None = None,
    channels: list[str] | None = None,
    tenant_id: int = 1,
) -> dict[str, Any]:
    scenario, weights = classify_intent(query)
    candidates = await retrieve(db, query, history, channels, tenant_id)

    if not candidates:
        raise RetrievalError(message="检索结果为空")

    faq_hit = next((c for c in candidates if c.get("channel") == "faq"), None)
    if faq_hit and faq_hit.get("rerank_score", 0) > 0.85:
        context = await build_context([faq_hit])
        if settings.LLM_PROVIDER == "stub":
            answer = await build_stub_answer(query, [faq_hit], faq_mode=True)
        else:
            answer = await llm_client.chat([
                {"role": "system", "content": FAQ_SYSTEM_PROMPT},
                {"role": "user", "content": f"问题：{query}\n\n标准口径：{context}"},
            ])
        citations = await build_citations(db, [faq_hit])
        return {
            "answer": answer,
            "mode": "faq",
            "confidence": 0.95,
            "citations": citations,
            "unverified_claims": [],
        }

    context = await build_context(candidates)
    if settings.LLM_PROVIDER == "stub":
        # stub：证据抽取式编排（见 stub_llm.py），答案 100% 可溯源
        draft = await build_stub_answer(query, candidates)
    else:
        draft = await llm_client.chat([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"问题：{query}\n\n检索上下文：\n{context}"},
        ])

    clause_result = await verify_clause_existence(db, draft)
    sentences = split_sentences(draft)
    if settings.LLM_PROVIDER == "stub":
        claim_result = await verify_claims_stub(sentences, candidates)
    else:
        claim_result = await verify_claims(db, sentences, candidates)

    top_rerank = max((c.get("rerank_score", 0.0) for c in candidates), default=0.0)
    confidence = compute_confidence(
        top_rerank, clause_result["hit_rate"], claim_result["pass_rate"]
    )

    unverified_ratio = 1.0 - claim_result["pass_rate"]
    blocked = should_block(confidence, len(claim_result["unverified"]) > 0, unverified_ratio)

    citations = await build_citations(db, candidates)

    # stub 模式证据门：检索相关度过低视为证据不足（无 LLM 幻觉，但仍须避免无关原文被当作答案）
    if settings.LLM_PROVIDER == "stub" and top_rerank < RERANK_MIN_EVIDENCE:
        return {
            "answer": draft,
            "mode": "needs_human_review",
            "confidence": min(confidence, 0.59),
            "citations": [],
            "unverified_claims": ["检索证据与问题相关性不足，请人工确认口径"],
        }

    if blocked:
        return {
            "answer": draft,
            "mode": "needs_human_review",
            "confidence": confidence,
            "citations": citations,
            "unverified_claims": claim_result["unverified"],
        }

    return {
        "answer": draft,
        "mode": "retrieval",
        "confidence": confidence,
        "citations": citations,
        "unverified_claims": claim_result["unverified"],
    }


async def rag_answer_stream(
    db: AsyncSession,
    query: str,
    history: list[dict] | None = None,
    channels: list[str] | None = None,
    tenant_id: int = 1,
) -> AsyncIterator[dict[str, Any]]:
    scenario, weights = classify_intent(query)
    candidates = await retrieve(db, query, history, channels, tenant_id)

    if not candidates:
        yield {"type": "error", "code": "5002"}
        return

    context = await build_context(candidates)
    citations = await build_citations(db, candidates)

    yield {"type": "citation", "citations": citations}

    full_answer = ""
    if settings.LLM_PROVIDER == "stub":
        # stub：非流式编排，按块模拟 SSE 输出
        full_answer = await build_stub_answer(query, candidates)
        for i in range(0, len(full_answer), 40):
            yield {"type": "delta", "content": full_answer[i : i + 40]}
    else:
        async for delta in llm_client.chat_stream([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"问题：{query}\n\n检索上下文：\n{context}"},
        ]):
            full_answer += delta
            yield {"type": "delta", "content": delta}

    clause_result = await verify_clause_existence(db, full_answer)
    sentences = split_sentences(full_answer)
    if settings.LLM_PROVIDER == "stub":
        claim_result = await verify_claims_stub(sentences, candidates)
    else:
        claim_result = await verify_claims(db, sentences, candidates)

    top_rerank = max((c.get("rerank_score", 0.0) for c in candidates), default=0.0)
    confidence = compute_confidence(
        top_rerank, clause_result["hit_rate"], claim_result["pass_rate"]
    )

    unverified_ratio = 1.0 - claim_result["pass_rate"]
    blocked = should_block(confidence, len(claim_result["unverified"]) > 0, unverified_ratio)

    # stub 模式证据门（与 rag_answer 一致）：相关度过低 → 不直接展示
    if settings.LLM_PROVIDER == "stub" and top_rerank < RERANK_MIN_EVIDENCE:
        yield {
            "type": "flag",
            "flag": "needs_human_review",
            "confidence": min(confidence, 0.59),
            "unverified_claims": [f"检索证据与问题相关性不足（相关度 {top_rerank:.3f}），请人工确认口径"],
        }
        return

    if blocked:
        yield {
            "type": "flag",
            "flag": "needs_human_review",
            "confidence": confidence,
            "unverified_claims": claim_result["unverified"],
        }
    else:
        yield {"type": "done", "confidence": confidence}
