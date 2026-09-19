import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import LLMError, NotFoundError
from app.core.logging import logger
from app.ingestion.chunker import chunk_clause
from app.ingestion.embedder import embedder
from app.ingestion.parser import extract_sections_and_clauses, normalize_clause_no
from app.models.regulation import KbVersion, RegClause, RegDocument, RegSection
from app.rag.milvus_client import ensure_collection, get_milvus, insert_vectors

BATCH_SIZE = 32


async def _resolve_collection(db: AsyncSession, doc: RegDocument, version_label: str) -> str | None:
    """按 (regulation, version_label) 取最新版本集合；无版本时按命名规则推导（不激活检索）。"""
    result = await db.execute(
        select(KbVersion)
        .where(
            KbVersion.regulation == doc.regulation,
            KbVersion.version_label == version_label,
            KbVersion.tenant_id == doc.tenant_id,
        )
        .order_by(KbVersion.id.desc())
        .limit(1)
    )
    version = result.scalar_one_or_none()
    if version and version.doc_collection:
        return version.doc_collection
    safe = re.sub(r"[^A-Za-z0-9_]", "_", version_label)
    return f"doc_{doc.regulation}_{safe}"


async def ingest_document(db: AsyncSession, doc_id: int, raw_text: str | None = None) -> dict[str, Any]:
    result = await db.execute(select(RegDocument).where(RegDocument.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError()

    if not raw_text:
        raw_text = doc.doc_raw or doc.source_file
        if not raw_text:
            raise LLMError(message="文档无全文内容（doc_raw 为空且无源文件）")

    clauses_data = extract_sections_and_clauses(raw_text)
    if not clauses_data:
        raise LLMError(message="未能从文档中提取条款")

    version_label = doc.version_label or "default"
    collection = await _resolve_collection(db, doc, version_label)
    sections_created = 0
    clauses_created = 0
    chunks_created = 0

    section_map: dict[str, int] = {}
    for cl in clauses_data:
        sec_no = cl.get("section_no")
        if sec_no and sec_no not in section_map:
            section = RegSection(
                doc_id=doc.id,
                section_no=sec_no,
                title=cl.get("section_title"),
                tenant_id=doc.tenant_id,
            )
            db.add(section)
            await db.flush()
            section_map[sec_no] = section.id
            sections_created += 1

    clause_chunks: list[dict[str, Any]] = []
    for cl in clauses_data:
        section_id = section_map.get(cl["section_no"]) if cl.get("section_no") else None
        normalized = normalize_clause_no(cl["clause_no"])
        clause = RegClause(
            section_id=section_id,
            clause_no=cl["clause_no"],
            normalized_no=normalized,
            content=cl["content"],
            doc_version=version_label,
            status="active",
            tenant_id=doc.tenant_id,
        )
        db.add(clause)
        await db.flush()
        clauses_created += 1

        chunks = chunk_clause(clause.id, cl["content"], cl["clause_no"])
        for chunk in chunks:
            chunk["doc_id"] = doc.id
            clause_chunks.append(chunk)

    indexed_ok = True
    # 规格 8.4：先提交关系库（调用方 commit），再写向量；向量失败重试告警，索引不完整标记
    try:
        client = get_milvus()
        texts = [c["text"] for c in clause_chunks]
        for i in range(0, len(texts), BATCH_SIZE):
            batch_texts = texts[i:i + BATCH_SIZE]
            batch_meta = clause_chunks[i:i + BATCH_SIZE]
            if not batch_texts:
                continue
            vectors = await embedder.embed(batch_texts)
            ensure_collection(client, collection, dim=embedder.dim)
            metadata = [
                {
                    "entity_id": meta["clause_id"],
                    "text": meta["text"],
                    "doc_version": version_label,
                    "tenant_id": doc.tenant_id,
                }
                for meta in batch_meta
            ]
            await insert_vectors(collection, vectors, metadata)
            chunks_created += len(batch_texts)
    except Exception as e:
        indexed_ok = False
        logger.error("vector_index_failed", doc_id=doc.id, collection=collection, error=str(e))

    doc.status = "active"
    await db.flush()

    return {
        "doc_id": doc.id,
        "collection": collection,
        "indexed": indexed_ok,
        "sections_created": sections_created,
        "clauses_created": clauses_created,
        "chunks_created": chunks_created,
    }
