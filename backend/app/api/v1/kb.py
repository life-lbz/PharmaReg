from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit
from app.audit.signature import execute_signature
from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.system import SysUser
from app.schemas.common import ok
from app.schemas.kb import (
    ActivateVersionRequest,
    CreateDocumentRequest,
    CreateFaqRequest,
    CreateVersionRequest,
    DiffReviewRequest,
    InvalidateFaqRequest,
)
from app.services.ingestion_service import ingest_document
from app.services.kb_service import (
    activate_version,
    create_document,
    create_faq,
    create_version,
    diff_versions,
    invalidate_faq,
    list_versions,
    review_diff,
    rollback_version,
)

router = APIRouter(prefix="/kb", tags=["法规库"])


@router.post("/documents")
async def upload_document(
    req: CreateDocumentRequest,
    request: Request,
    user: SysUser = Depends(require_permission("kb.manage")),
    db: AsyncSession = Depends(get_db),
):
    doc = await create_document(db, req, user.tenant_id)
    await write_audit(
        db, event_type="kb.upload", action="create", actor_id=user.id,
        object_type="reg_documents", object_id=doc.id,
        ip=request.client.host if request.client else None, tenant_id=user.tenant_id,
    )
    await db.commit()
    return ok({"id": doc.id, "title": doc.title, "status": doc.status})


@router.post("/documents/{doc_id}/ingest")
async def trigger_ingest(
    doc_id: int,
    raw_text: str | None = None,
    request: Request = None,
    user: SysUser = Depends(require_permission("kb.manage")),
    db: AsyncSession = Depends(get_db),
):
    result = await ingest_document(db, doc_id, raw_text)
    await write_audit(
        db, event_type="kb.ingest", action="ingest", actor_id=user.id,
        object_type="reg_documents", object_id=doc_id, after=result,
        ip=request.client.host if request else None, tenant_id=user.tenant_id,
    )
    await db.commit()
    return ok(result)


@router.get("/versions")
async def get_versions(
    user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    versions = await list_versions(db, user.tenant_id)
    return ok([
        {
            "id": v.id,
            "regulation": v.regulation,
            "version_label": v.version_label,
            "collection_prefix": v.collection_prefix,
            "status": v.status,
            "activated_at": v.activated_at.isoformat() if v.activated_at else None,
            "frozen_at": v.frozen_at.isoformat() if v.frozen_at else None,
        }
        for v in versions
    ])


@router.post("/versions")
async def add_version(
    req: CreateVersionRequest,
    user: SysUser = Depends(require_permission("kb.manage")),
    db: AsyncSession = Depends(get_db),
):
    version = await create_version(db, req, user.tenant_id)
    await db.commit()
    return ok({"id": version.id, "status": version.status})


@router.post("/versions/{version_id}/diff")
async def trigger_diff(
    version_id: int,
    user: SysUser = Depends(require_permission("kb.manage")),
    db: AsyncSession = Depends(get_db),
):
    diffs = await diff_versions(db, version_id)
    await db.commit()
    return ok([
        {
            "id": d.id,
            "change_type": d.change_type,
            "from_clause_id": d.from_clause_id,
            "to_clause_id": d.to_clause_id,
            "review_status": d.review_status,
        }
        for d in diffs
    ])


@router.put("/version-diffs/{diff_id}/review")
async def review_version_diff(
    diff_id: int,
    req: DiffReviewRequest,
    user: SysUser = Depends(require_permission("kb.manage")),
    db: AsyncSession = Depends(get_db),
):
    diff = await review_diff(db, diff_id, req.review_status)
    await write_audit(
        db, event_type="kb.diff_review", action="review", actor_id=user.id,
        object_type="reg_version_diffs", object_id=diff.id,
        after={"review_status": req.review_status}, tenant_id=user.tenant_id,
    )
    await db.commit()
    return ok({"id": diff.id, "review_status": diff.review_status})


@router.post("/versions/{version_id}/activate")
async def activate(
    version_id: int,
    req: ActivateVersionRequest,
    request: Request,
    user: SysUser = Depends(require_permission("kb.activate")),
    db: AsyncSession = Depends(get_db),
):
    sig = await execute_signature(db, user, "kb_version", version_id,
                                  "本人确认激活此法规版本集合，承担版本切换责任",
                                  "kb.activate", req.signature_pin, req.idempotency_key)
    version = await activate_version(db, version_id, user.tenant_id)
    await write_audit(
        db, event_type="kb.activate", action="activate", actor_id=user.id,
        object_type="kb_versions", object_id=version.id,
        after={"status": "active", "signature_id": sig.id, "reason": req.reason},
        ip=request.client.host if request else None, tenant_id=user.tenant_id,
    )
    await db.commit()
    return ok({"id": version.id, "status": version.status})


@router.post("/versions/{version_id}/rollback")
async def rollback(
    version_id: int,
    req: ActivateVersionRequest,
    request: Request,
    user: SysUser = Depends(require_permission("kb.activate")),
    db: AsyncSession = Depends(get_db),
):
    if not req.reason:
        from app.core.exceptions import ValidationError
        raise ValidationError(message="回滚必须填写原因")
    sig = await execute_signature(db, user, "kb_version", version_id,
                                  "本人确认回滚此法规版本至上一冻结版本",
                                  "kb.rollback", req.signature_pin, req.idempotency_key)
    version = await rollback_version(db, version_id, user.tenant_id)
    await write_audit(
        db, event_type="kb.rollback", action="rollback", actor_id=user.id,
        object_type="kb_versions", object_id=version.id,
        after={"status": "active", "signature_id": sig.id, "reason": req.reason},
        ip=request.client.host if request else None, tenant_id=user.tenant_id,
    )
    await db.commit()
    return ok({"id": version.id, "status": version.status})


@router.post("/faqs")
async def publish_faq(
    req: CreateFaqRequest,
    user: SysUser = Depends(require_permission("faq.approve")),
    db: AsyncSession = Depends(get_db),
):
    faq = await create_faq(db, req, user.tenant_id)
    await write_audit(
        db, event_type="kb.faq_publish", action="publish", actor_id=user.id,
        object_type="faqs", object_id=faq.id, tenant_id=user.tenant_id,
    )
    await db.commit()
    return ok({"id": faq.id, "status": faq.status})


@router.put("/faqs/{faq_id}/invalidate")
async def invalidate(
    faq_id: int,
    req: InvalidateFaqRequest,
    user: SysUser = Depends(require_permission("faq.approve")),
    db: AsyncSession = Depends(get_db),
):
    faq = await invalidate_faq(db, faq_id, req.superseded_by)
    await write_audit(
        db, event_type="kb.faq_invalidate", action="invalidate", actor_id=user.id,
        object_type="faqs", object_id=faq.id, tenant_id=user.tenant_id,
    )
    await db.commit()
    return ok({"id": faq.id, "status": faq.status})
