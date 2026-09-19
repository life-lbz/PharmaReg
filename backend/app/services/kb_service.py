import hashlib
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, StateError, VersionActivateError
from app.models.regulation import (
    Faq,
    KbVersion,
    RegClause,
    RegDocument,
    RegVersionDiff,
)


async def create_document(db: AsyncSession, req, tenant_id: int = 1) -> RegDocument:
    doc = RegDocument(
        title=req.title,
        doc_type=req.doc_type,
        regulation=req.regulation,
        version_label=req.version_label,
        doc_no=req.doc_no,
        source_file=req.source_file,
        doc_raw=req.doc_raw,
        domain_id=req.domain_id,
        status="draft",
        tenant_id=tenant_id,
    )
    if req.source_file:
        doc.file_hash = hashlib.md5(req.source_file.encode()).hexdigest()
    db.add(doc)
    await db.flush()
    return doc


async def create_version(db: AsyncSession, req, tenant_id: int = 1) -> KbVersion:
    # Milvus 集合名仅允许字母/数字/下划线：prefix 中连字符等转下划线
    safe_prefix = re.sub(r"[^A-Za-z0-9_]", "_", req.collection_prefix)
    version = KbVersion(
        regulation=req.regulation,
        version_label=req.version_label,
        collection_prefix=req.collection_prefix,
        doc_collection=f"doc_{safe_prefix}",
        faq_collection=f"faq_{safe_prefix}",
        case_collection=f"case_{safe_prefix}",
        diff_source_version_id=req.diff_source_version_id,
        status="draft",
        tenant_id=tenant_id,
    )
    db.add(version)
    await db.flush()
    return version


async def list_versions(db: AsyncSession, tenant_id: int = 1) -> list[KbVersion]:
    result = await db.execute(
        select(KbVersion).where(KbVersion.tenant_id == tenant_id).order_by(KbVersion.id.desc())
    )
    return list(result.scalars().all())


async def diff_versions(db: AsyncSession, version_id: int) -> list[RegVersionDiff]:
    version = await db.execute(select(KbVersion).where(KbVersion.id == version_id))
    version = version.scalar_one_or_none()
    if not version:
        raise NotFoundError()
    source_id = version.diff_source_version_id
    if not source_id:
        raise VersionActivateError(message="无对比源版本")

    to_clauses = await db.execute(
        select(RegClause).where(
            RegClause.status == "active",
            RegClause.doc_version == version.version_label,
        )
    )
    to_clauses_list = list(to_clauses.scalars().all())

    from_version = await db.execute(select(KbVersion).where(KbVersion.id == source_id))
    from_version = from_version.scalar_one_or_none()
    from_clauses_list = []
    if from_version:
        from_clauses = await db.execute(
            select(RegClause).where(
                RegClause.status == "active",
                RegClause.doc_version == from_version.version_label,
            )
        )
        from_clauses_list = list(from_clauses.scalars().all())

    from_map = {c.normalized_no: c for c in from_clauses_list if c.normalized_no is not None}
    to_map = {c.normalized_no: c for c in to_clauses_list if c.normalized_no is not None}

    all_nos = set(from_map.keys()) | set(to_map.keys())
    diffs = []
    for no in all_nos:
        from_c = from_map.get(no)
        to_c = to_map.get(no)
        if to_c and not from_c:
            change_type = "added"
        elif from_c and not to_c:
            change_type = "removed"
        elif from_c and to_c and from_c.content != to_c.content:
            change_type = "revised"
        else:
            continue

        diff = RegVersionDiff(
            from_version_id=source_id,
            to_version_id=version_id,
            change_type=change_type,
            from_clause_id=from_c.id if from_c else None,
            to_clause_id=to_c.id if to_c else None,
            old_content=from_c.content if from_c else None,
            new_content=to_c.content if to_c else None,
            match_method="auto",
            match_confidence=1.0 if change_type != "revised" else 0.8,
            review_status="pending",
            tenant_id=version.tenant_id,
        )
        db.add(diff)
        diffs.append(diff)
    await db.flush()
    return diffs


async def review_diff(db: AsyncSession, diff_id: int, review_status: str) -> RegVersionDiff:
    result = await db.execute(select(RegVersionDiff).where(RegVersionDiff.id == diff_id))
    diff = result.scalar_one_or_none()
    if not diff:
        raise NotFoundError()
    diff.review_status = review_status
    await db.flush()
    return diff


async def activate_version(db: AsyncSession, version_id: int, tenant_id: int = 1):
    version = await db.execute(select(KbVersion).where(KbVersion.id == version_id))
    version = version.scalar_one_or_none()
    if not version:
        raise NotFoundError()
    if version.status != "draft":
        raise StateError(message="版本状态不允许激活")

    pending_diffs = await db.execute(
        select(func.count()).select_from(RegVersionDiff).where(
            RegVersionDiff.to_version_id == version_id,
            RegVersionDiff.review_status == "pending",
        )
    )
    pending_count = pending_diffs.scalar() or 0
    if pending_count > 0:
        raise VersionActivateError(message=f"仍有{pending_count}条差异未复核")

    old_active = await db.execute(
        select(KbVersion).where(
            KbVersion.regulation == version.regulation,
            KbVersion.status == "active",
            KbVersion.tenant_id == tenant_id,
        )
    )
    old_version = old_active.scalar_one_or_none()
    if old_version:
        old_version.status = "frozen"
        old_version.frozen_at = func.now()

    version.status = "active"
    version.activated_at = func.now()
    await db.flush()
    return version


async def rollback_version(db: AsyncSession, version_id: int, tenant_id: int = 1):
    version = await db.execute(select(KbVersion).where(KbVersion.id == version_id))
    version = version.scalar_one_or_none()
    if not version:
        raise NotFoundError()

    current_active = await db.execute(
        select(KbVersion).where(
            KbVersion.regulation == version.regulation,
            KbVersion.status == "active",
            KbVersion.tenant_id == tenant_id,
        )
    )
    current = current_active.scalar_one_or_none()
    if current:
        current.status = "frozen"
        current.frozen_at = func.now()

    version.status = "active"
    version.activated_at = func.now()
    await db.flush()
    return version


async def create_faq(db: AsyncSession, req, tenant_id: int = 1) -> Faq:
    faq = Faq(
        question=req.question,
        answer=req.answer,
        kb_version_id=req.kb_version_id,
        clause_refs={"clause_ids": req.clause_refs} if req.clause_refs else None,
        status="approved",
        tenant_id=tenant_id,
    )
    db.add(faq)
    await db.flush()
    return faq


async def invalidate_faq(db: AsyncSession, faq_id: int, superseded_by: int | None = None) -> Faq:
    result = await db.execute(select(Faq).where(Faq.id == faq_id))
    faq = result.scalar_one_or_none()
    if not faq:
        raise NotFoundError()
    faq.status = "invalid"
    faq.superseded_by = superseded_by
    await db.flush()
    return faq
