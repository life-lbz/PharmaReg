from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit
from app.audit.signature import execute_signature
from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.system import SysUser
from app.schemas.common import ok
from app.schemas.sae_audit import (
    AddEvidenceRequest,
    ConfirmGapsRequest,
    CreateAuditCheckRequest,
    CreateSaeRequest,
    DraftSaeRequest,
    PvReviewRequest,
    RectifyRequest,
    ReportRequest,
    SignSaeRequest,
    SubmitSaeRequest,
)
from app.services.audit_service import (
    add_evidence,
    confirm_gaps,
    create_audit_check,
    generate_report,
    get_audit_check,
    rectify_item,
)
from app.services.sae_service import (
    archive_sae,
    create_sae,
    generate_draft,
    get_sae,
    list_sae,
    pv_review,
    serialize_sae,
    sign_sae,
    submit_sae,
)

router = APIRouter(prefix="", tags=["SAE与审计准备"])

SAE_SIGN_MEANING = "本人作为研究者确认SAE报告内容真实，承担电子签名法律责任"
SAE_SUBMIT_MEANING = "本人确认提交此SAE报告至申办方及伦理委员会"


def client_ip(request: Request | None) -> str | None:
    return request.client.host if request and request.client else None


# ============ SAE ============

@router.post("/sae")
async def add_sae(req: CreateSaeRequest, request: Request, user: SysUser = Depends(require_permission("sae.manage")), db: AsyncSession = Depends(get_db)):
    sae = await create_sae(db, req, user.id, user.tenant_id)
    await write_audit(db, event_type="sae.record", action="create", actor_id=user.id, object_type="sae_reports", object_id=sae.id, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok({"id": sae.id, "sae_no": sae.sae_no, "status": sae.status,
               "report_deadline_1": sae.report_deadline_1, "report_deadline_2": sae.report_deadline_2})


@router.get("/sae")
async def list_sae_api(status: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: SysUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return ok(await list_sae(db, status, page, page_size, user.tenant_id))


@router.get("/sae/{sae_id}")
async def sae_detail(sae_id: int, user: SysUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    sae = await get_sae(db, sae_id)
    return ok(serialize_sae(sae))


@router.post("/sae/{sae_id}/pv-review")
async def sae_pv_review(sae_id: int, req: PvReviewRequest, request: Request, user: SysUser = Depends(require_permission("sae.review")), db: AsyncSession = Depends(get_db)):
    result = await pv_review(db, sae_id, req.seriousness, req.causality, user.id)
    await write_audit(db, event_type="sae.pv_review", action="pv_review", actor_id=user.id, object_type="sae_reports", object_id=sae_id, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok(result)


@router.post("/sae/{sae_id}/draft")
async def sae_draft(sae_id: int, req: DraftSaeRequest, user: SysUser = Depends(require_permission("sae.review")), db: AsyncSession = Depends(get_db)):
    result = await generate_draft(db, sae_id, req.draft)
    await db.commit()
    return ok(result)


@router.post("/sae/{sae_id}/sign")
async def sae_sign(sae_id: int, req: SignSaeRequest, request: Request, user: SysUser = Depends(require_permission("sae.sign")), db: AsyncSession = Depends(get_db)):
    sig = await execute_signature(db, user, "sae", sae_id, SAE_SIGN_MEANING, "sae.sign", req.signature_pin, req.idempotency_key)
    result = await sign_sae(db, sae_id, user.id)
    await write_audit(db, event_type="sae.sign", action="sign", actor_id=user.id, object_type="sae_reports", object_id=sae_id, after={"signature_id": sig.id}, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok(result)


@router.post("/sae/{sae_id}/submit")
async def sae_submit(sae_id: int, req: SubmitSaeRequest, request: Request, user: SysUser = Depends(require_permission("sae.submit")), db: AsyncSession = Depends(get_db)):
    sig = await execute_signature(db, user, "sae", sae_id, SAE_SUBMIT_MEANING, "sae.submit", req.signature_pin, req.idempotency_key)
    result = await submit_sae(db, sae_id)
    await write_audit(db, event_type="sae.submit", action="submit", actor_id=user.id, object_type="sae_reports", object_id=sae_id, after={"signature_id": sig.id}, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok(result)


@router.post("/sae/{sae_id}/archive")
async def sae_archive(sae_id: int, request: Request, user: SysUser = Depends(require_permission("sae.manage")), db: AsyncSession = Depends(get_db)):
    result = await archive_sae(db, sae_id)
    await write_audit(db, event_type="sae.archive", action="archive", actor_id=user.id, object_type="sae_reports", object_id=sae_id, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok(result)


# ============ 审计准备 ============

@router.get("/audit/checks")
async def list_checks(check_type: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: SysUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.audit_service import list_audit_checks
    return ok(await list_audit_checks(db, check_type, page, page_size, user.tenant_id))


@router.post("/audit/checks")
async def create_check(req: CreateAuditCheckRequest, request: Request, user: SysUser = Depends(require_permission("audit.manage")), db: AsyncSession = Depends(get_db)):
    check = await create_audit_check(db, req.check_type, user.id, user.tenant_id)
    await write_audit(db, event_type="audit.check_create", action="create", actor_id=user.id, object_type="audit_checks", object_id=check.id, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok({"id": check.id, "audit_no": check.audit_no, "status": check.status, "checklist": check.checklist})


@router.get("/audit/checks/{check_id}")
async def check_detail(check_id: int, user: SysUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    check = await get_audit_check(db, check_id)
    return ok({"id": check.id, "audit_no": check.audit_no, "check_type": check.check_type,
               "checklist": check.checklist, "evidence_refs": check.evidence_refs,
               "gaps": check.gaps, "status": check.status})


@router.post("/audit/checks/{check_id}/evidence")
async def add_evidence_api(check_id: int, req: AddEvidenceRequest, user: SysUser = Depends(require_permission("audit.prepare")), db: AsyncSession = Depends(get_db)):
    result = await add_evidence(db, check_id, req.item_id, req.evidence_key, req.description)
    await db.commit()
    return ok(result)


@router.post("/audit/checks/{check_id}/gaps")
async def confirm_gaps_api(check_id: int, req: ConfirmGapsRequest, request: Request, user: SysUser = Depends(require_permission("audit.manage")), db: AsyncSession = Depends(get_db)):
    result = await confirm_gaps(db, check_id, req.gaps)
    await write_audit(db, event_type="audit.gap_confirm", action="confirm_gaps", actor_id=user.id, object_type="audit_checks", object_id=check_id, after=result, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok(result)


@router.put("/audit/checks/{check_id}/rectify")
async def rectify_api(check_id: int, req: RectifyRequest, user: SysUser = Depends(require_permission("audit.prepare")), db: AsyncSession = Depends(get_db)):
    result = await rectify_item(db, check_id, req.item_id, req.rectification)
    await db.commit()
    return ok(result)


@router.post("/audit/checks/{check_id}/report")
async def audit_report(check_id: int, req: ReportRequest, request: Request, user: SysUser = Depends(require_permission("audit.manage")), db: AsyncSession = Depends(get_db)):
    report = await generate_report(db, check_id, req.summary)
    await write_audit(db, event_type="audit.check_report", action="report", actor_id=user.id, object_type="audit_checks", object_id=check_id, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok(report)
