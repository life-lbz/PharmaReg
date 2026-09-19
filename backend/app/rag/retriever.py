from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.ingestion.embedder import embedder, reranker
from app.models.regulation import Faq, KbVersion
from app.rag.milvus_client import search_vectors

FAQ_KEYWORDS = ["口径", "怎么办", "如何处理", "怎么理解", "标准", "要求是"]
CASE_KEYWORDS = ["案例", "案例", "历史", "发生过", "之前"]


def classify_intent(query: str) -> tuple[str, dict[str, float]]:
    scenario = "qa"
    weights = {"doc": 0.7, "faq": 0.2, "case": 0.1}

    if any(k in query for k in FAQ_KEYWORDS):
        scenario = "faq_match"
        weights = {"doc": 0.3, "faq": 0.6, "case": 0.1}
    elif any(k in query for k in CASE_KEYWORDS):
        scenario = "deviation"
        weights = {"doc": 0.3, "faq": 0.1, "case": 0.6}

    return scenario, weights


async def rewrite_query(query: str, history: list[dict] | None = None) -> list[str]:
    queries = [query]
    if history:
        last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
        if last_user and last_user != query:
            queries.append(f"{last_user} {query}")

    abbrev_map = {
        "GMP": "药品生产质量管理规范",
        "GCP": "药物临床试验质量管理规范",
        "ICH": "人用药品注册技术国际协调会议",
    }
    for abbr, full in abbrev_map.items():
        for i, q in enumerate(queries):
            if abbr in q and full not in q:
                queries.append(q.replace(abbr, full))
                break
    return queries[:2]


async def get_active_versions(db: AsyncSession, regulation: str | None = None, tenant_id: int = 1) -> list[KbVersion]:
    """返回全部激活版本（不同法规可并行激活），按激活时间倒序。"""
    query = select(KbVersion).where(KbVersion.status == "active", KbVersion.tenant_id == tenant_id)
    if regulation:
        query = query.where(KbVersion.regulation == regulation)
    query = query.order_by(KbVersion.activated_at.desc(), KbVersion.id.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


async def search_faq(db: AsyncSession, query: str, collection: str | None = None) -> list[dict[str, Any]]:
    query_embed = await embedder.embed_single(query)
    collection = collection or "faq_default"

    hits = await search_vectors(collection, query_embed, top_k=10)
    if not hits:
        result = await db.execute(
            select(Faq).where(Faq.status == "approved").limit(5)
        )
        faqs = result.scalars().all()
        return [{"entity_id": f.id, "text": f"{f.question} {f.answer}", "score": 0.5} for f in faqs]
    return hits


async def search_doc(db: AsyncSession, query: str, collection: str | None = None, tenant_id: int = 1) -> list[dict[str, Any]]:
    query_embed = await embedder.embed_single(query)
    collection = collection or "doc_default"
    hits = await search_vectors(collection, query_embed, top_k=40, tenant_id=tenant_id)
    return hits


async def search_case(db: AsyncSession, query: str, collection: str | None = None, tenant_id: int = 1) -> list[dict[str, Any]]:
    query_embed = await embedder.embed_single(query)
    collection = collection or "case_default"
    hits = await search_vectors(collection, query_embed, top_k=40, tenant_id=tenant_id)
    return hits


def _pre_prune_candidates(
    candidates: list[dict[str, Any]], per_channel: int = 8
) -> list[dict[str, Any]]:
    """重排前预剪枝：跨 query/版本候选可达 50+，全量送 rerank 会超时。

    按通道先取向量分 top-k，控制重排输入规模（doc/faq/case 各自保留）。
    """
    by_channel: dict[str, list[dict[str, Any]]] = {}
    for c in candidates:
        by_channel.setdefault(c.get("channel", "doc"), []).append(c)
    pruned: list[dict[str, Any]] = []
    for items in by_channel.values():
        items.sort(key=lambda x: x.get("score", 0), reverse=True)
        pruned.extend(items[:per_channel])
    return pruned


async def retrieve(
    db: AsyncSession,
    query: str,
    history: list[dict] | None = None,
    channels: list[str] | None = None,
    tenant_id: int = 1,
) -> list[dict[str, Any]]:
    if channels is None:
        channels = ["doc", "faq", "case"]

    queries = await rewrite_query(query, history)
    versions = await get_active_versions(db, tenant_id=tenant_id)

    all_candidates: list[dict[str, Any]] = []
    seen_texts: set[str] = set()

    for q in queries:
        for version in versions:
            if "doc" in channels and version.doc_collection:
                for h in await search_doc(db, q, version.doc_collection, tenant_id):
                    key = h["text"][:100]
                    if key not in seen_texts:
                        h["channel"] = "doc"
                        all_candidates.append(h)
                        seen_texts.add(key)

            if "faq" in channels and version.faq_collection:
                for h in await search_faq(db, q, version.faq_collection):
                    key = h["text"][:100]
                    if key not in seen_texts:
                        h["channel"] = "faq"
                        all_candidates.append(h)
                        seen_texts.add(key)

            if "case" in channels and version.case_collection:
                for h in await search_case(db, q, version.case_collection, tenant_id):
                    key = h["text"][:100]
                    if key not in seen_texts:
                        h["channel"] = "case"
                        all_candidates.append(h)
                        seen_texts.add(key)

    # 无激活版本时兜底查询默认集合
    if not versions:
        for q in queries:
            if "doc" in channels:
                for h in await search_doc(db, q, None, tenant_id):
                    key = h["text"][:100]
                    if key not in seen_texts:
                        h["channel"] = "doc"
                        all_candidates.append(h)
                        seen_texts.add(key)

    if not all_candidates:
        return []

    pruned = _pre_prune_candidates(all_candidates)
    doc_texts = [c["text"] for c in pruned]
    try:
        # top_n 覆盖全部候选：避免仅 top8 有 rerank 分、其余回退向量分混入排序，
        # 导致证据门控被未重排候选的余弦分绕过（打分耗时不变，仅多返回序号）
        rerank_results = await reranker.rerank(query, doc_texts, top_n=len(doc_texts))
        for r in rerank_results:
            idx = r.get("index", 0)
            if idx < len(pruned):
                pruned[idx]["rerank_score"] = r.get("relevance_score", 0.0)
        pruned.sort(key=lambda x: x.get("rerank_score", 0.0), reverse=True)
    except Exception as e:
        logger.warning("rerank_failed", error=str(e), candidates=len(pruned))
        pruned.sort(key=lambda x: x.get("score", 0), reverse=True)

    return pruned[:8]
