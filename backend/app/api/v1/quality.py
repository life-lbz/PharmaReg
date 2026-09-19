from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit
from app.audit.signature import execute_signature
from app.core.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.system import SysUser
from app.schemas.common import ok
from app.schemas.quality import (
    ApproveChangeRequest,
    AssessChangeRequest,
    ClassifyRequest,
    CloseChangeRequest,
    CloseDeviationRequest,
    CreateCapaRequest,
    CreateChangeRequest,
    CreateDeviationRequest,
    ImplementChangeRequest,
    InvestigateRequest,
    ReopenRequest,
    ReviewDeviationRequest,
    SubmitReviewRequest,
    UpdateCapaActionsRequest,
    VerifyCapaRequest,
    VerifyChangeRequest,
)
from app.services.quality_service import (
    approve_change,
    assess_change,
    classify_deviation,
    close_change,
    close_deviation,
    create_capa,
    create_change,
    create_deviation,
    get_deviation,
    implement_change,
    investigate_deviation,
    list_deviations,
    reopen_deviation,
    review_deviation,
    submit_deviation_review,
    update_capa_actions,
    verify_capa,
    verify_change,
)

router = APIRouter(prefix="", tags=["质量模块"])

DEVIATION_MEANING = "本人已审核偏差分级与调查结论，批准关闭此偏差记录"
CHANGE_MEANING = "本人批准此变更申请，已确认影响评估结果"
CAPA_MEANING = "本人确认CAPA措施有效，验证通过"


def client_ip(request: Request | None) -> str | None:
    return request.client.host if request and request.client else None


# ============ 偏差 ============

@router.post("/deviations")
async def add_deviation(req: CreateDeviationRequest, request: Request, user: SysUser = Depends(require_permission("deviation.manage")), db: AsyncSession = Depends(get_db)):
    dev = await create_deviation(db, req, user.id, user.tenant_id)
    await write_audit(db, event_type="deviation.report", action="create", actor_id=user.id, object_type="deviations", object_id=dev.id, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok({"id": dev.id, "dev_no": dev.dev_no, "status": dev.status})


@router.get("/deviations")
async def list_dev_api(status: str | None = None, severity: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: SysUser = Depends(require_permission("deviation.view")), db: AsyncSession = Depends(get_db)):
    return ok(await list_deviations(db, status, severity, page, page_size, user.tenant_id))


@router.get("/deviations/{dev_id}")
async def dev_detail(dev_id: int, user: SysUser = Depends(require_permission("deviation.view")), db: AsyncSession = Depends(get_db)):
    dev = await get_deviation(db, dev_id)
    from app.services.quality_service import serialize_deviation
    return ok(serialize_deviation(dev))


@router.post("/deviations/{dev_id}/classify")
async def classify_dev(dev_id: int, req: ClassifyRequest, request: Request, user: SysUser = Depends(require_permission("deviation.review")), db: AsyncSession = Depends(get_db)):
    result = await classify_deviation(db, dev_id, req.severity, req.classify_result, user.tenant_id)
    await write_audit(db, event_type="deviation.classify", action="classify", actor_id=user.id, object_type="deviations", object_id=dev_id, after=result, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok(result)


@router.post("/deviations/{dev_id}/investigate")
async def investigate_dev(dev_id: int, req: InvestigateRequest, user: SysUser = Depends(require_permission("deviation.manage")), db: AsyncSession = Depends(get_db)):
    result = await investigate_deviation(db, dev_id, req.investigation_plan)
    await db.commit()
    return ok(result)


@router.post("/deviations/{dev_id}/submit-review")
async def submit_review(dev_id: int, req: SubmitReviewRequest, user: SysUser = Depends(require_permission("deviation.manage")), db: AsyncSession = Depends(get_db)):
    result = await submit_deviation_review(db, dev_id, req.root_cause)
    await db.commit()
    return ok(result)


@router.post("/deviations/{dev_id}/review")
async def review_dev(dev_id: int, req: ReviewDeviationRequest, request: Request, user: SysUser = Depends(require_permission("deviation.review")), db: AsyncSession = Depends(get_db)):
    sig = await execute_signature(db, user, "deviation", dev_id, DEVIATION_MEANING, "deviation.review", req.signature_pin, req.idempotency_key)
    result = await review_deviation(db, dev_id, req.approve, req.review_comment, user.id)
    await write_audit(db, event_type="deviation.review", action="review", actor_id=user.id, object_type="deviations", object_id=dev_id, after={**result, "signature_id": sig.id}, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok(result)


@router.post("/deviations/{dev_id}/reopen")
async def reopen_dev(dev_id: int, req: ReopenRequest, request: Request, user: SysUser = Depends(require_permission("deviation.review")), db: AsyncSession = Depends(get_db)):
    result = await reopen_deviation(db, dev_id, req.reason)
    await write_audit(db, event_type="deviation.reopen", action="reopen", actor_id=user.id, object_type="deviations", object_id=dev_id, after={"reason": req.reason}, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok(result)


@router.post("/deviations/{dev_id}/close")
async def close_dev(dev_id: int, req: CloseDeviationRequest, request: Request, user: SysUser = Depends(require_permission("deviation.close")), db: AsyncSession = Depends(get_db)):
    sig = await execute_signature(db, user, "deviation", dev_id, DEVIATION_MEANING, "deviation.review", req.signature_pin, req.idempotency_key)
    result = await close_deviation(db, dev_id, req.review_comment)
    await write_audit(db, event_type="deviation.close", action="close", actor_id=user.id, object_type="deviations", object_id=dev_id, after={**result, "signature_id": sig.id}, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok(result)


# ============ 变更 ============

@router.get("/changes")
async def list_chg(status: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: SysUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.quality_service import list_changes
    return ok(await list_changes(db, status, page, page_size, user.tenant_id))


@router.post("/changes")
async def add_change(req: CreateChangeRequest, request: Request, user: SysUser = Depends(require_permission("change.manage")), db: AsyncSession = Depends(get_db)):
    change = await create_change(db, req, user.id, user.tenant_id)
    await write_audit(db, event_type="change.submit", action="create", actor_id=user.id, object_type="change_controls", object_id=change.id, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok({"id": change.id, "chg_no": change.chg_no, "status": change.status})


@router.get("/capa")
async def list_capa_records(source_type: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: SysUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from app.services.quality_service import list_capas
    return ok(await list_capas(db, source_type, page, page_size, user.tenant_id))


@router.post("/changes/{chg_id}/assess")
async def assess_chg(chg_id: int, req: AssessChangeRequest, request: Request, user: SysUser = Depends(require_permission("change.assess")), db: AsyncSession = Depends(get_db)):
    result = await assess_change(db, chg_id, req.impact_assessment, user.id)
    await write_audit(db, event_type="change.assess", action="assess", actor_id=user.id, object_type="change_controls", object_id=chg_id, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok(result)


@router.post("/changes/{chg_id}/approve")
async def approve_chg(chg_id: int, req: ApproveChangeRequest, request: Request, user: SysUser = Depends(require_permission("change.approve")), db: AsyncSession = Depends(get_db)):
    sig = await execute_signature(db, user, "change", chg_id, CHANGE_MEANING, "change.approve", req.signature_pin, req.idempotency_key)
    result = await approve_change(db, chg_id, user.id, req.approval_comment)
    await write_audit(db, event_type="change.approve", action="approve", actor_id=user.id, object_type="change_controls", object_id=chg_id, after={"signature_id": sig.id}, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok(result)


@router.post("/changes/{chg_id}/implement")
async def implement_chg(chg_id: int, req: ImplementChangeRequest, user: SysUser = Depends(require_permission("change.manage")), db: AsyncSession = Depends(get_db)):
    result = await implement_change(db, chg_id, req.implementation_plan)
    await db.commit()
    return ok(result)


@router.post("/changes/{chg_id}/verify")
async def verify_chg(chg_id: int, req: VerifyChangeRequest, user: SysUser = Depends(require_permission("change.approve")), db: AsyncSession = Depends(get_db)):
    result = await verify_change(db, chg_id, req.verification_result)
    await db.commit()
    return ok(result)


@router.post("/changes/{chg_id}/close")
async def close_chg(chg_id: int, req: CloseChangeRequest, user: SysUser = Depends(require_permission("change.approve")), db: AsyncSession = Depends(get_db)):
    result = await close_change(db, chg_id, req.comment)
    await db.commit()
    return ok(result)


# ============ CAPA ============

@router.post("/capa")
async def add_capa(req: CreateCapaRequest, request: Request, user: SysUser = Depends(require_permission("capa.manage")), db: AsyncSession = Depends(get_db)):
    capa = await create_capa(db, req, user.id, user.tenant_id)
    await write_audit(db, event_type="capa.create", action="create", actor_id=user.id, object_type="capa_records", object_id=capa.id, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok({"id": capa.id, "capa_no": capa.capa_no, "status": capa.status})


@router.put("/capa/{capa_id}/actions")
async def update_actions(capa_id: int, req: UpdateCapaActionsRequest, user: SysUser = Depends(require_permission("capa.manage")), db: AsyncSession = Depends(get_db)):
    capa = await update_capa_actions(db, capa_id, req.actions)
    await db.commit()
    return ok({"id": capa.id, "status": capa.status})


@router.post("/capa/{capa_id}/verify")
async def verify_capa_api(capa_id: int, req: VerifyCapaRequest, request: Request, user: SysUser = Depends(require_permission("capa.manage")), db: AsyncSession = Depends(get_db)):
    sig = await execute_signature(db, user, "capa", capa_id, CAPA_MEANING, "capa.verify", req.signature_pin, req.idempotency_key)
    capa = await verify_capa(db, capa_id, req.effectiveness_check)
    await write_audit(db, event_type="capa.verify", action="verify", actor_id=user.id, object_type="capa_records", object_id=capa_id, after={"signature_id": sig.id}, ip=client_ip(request), tenant_id=user.tenant_id)
    await db.commit()
    return ok({"id": capa.id, "status": capa.status})
