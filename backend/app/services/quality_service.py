from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DeviationCloseError, FourEyeError, NotFoundError, StateError
from app.models.quality import BatchHold, CapaRecord, ChangeControl, Deviation

SEVERITY_WEIGHT = {"critical": 3, "major": 2, "minor": 1}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "reported": {"classified", "reported"},
    "classified": {"investigating", "reported"},
    "investigating": {"qa_review", "reported"},
    "qa_review": {"capa_linked", "investigating", "reported"},
    "capa_linked": {"closed", "reported"},
    "closed": set(),
}

CHANGE_TRANSITIONS: dict[str, set[str]] = {
    "submitted": {"assessed"},
    "assessed": {"approved"},
    "approved": {"implemented"},
    "implemented": {"verified"},
    "verified": {"closed"},
    "closed": set(),
}


async def create_deviation(db: AsyncSession, req, reporter_id: int, tenant_id: int = 1) -> Deviation:
    now = datetime.now(UTC)
    year = now.year
    result = await db.execute(
        select(func.count()).select_from(Deviation).where(Deviation.tenant_id == tenant_id)
    )
    seq = (result.scalar() or 0) + 1
    dev = Deviation(
        dev_no=f"DEV-{year}-{seq:04d}",
        title=req.title,
        description=req.description,
        occurred_at=req.occurred_at,
        area=req.area,
        category=req.category,
        severity="minor",
        status="reported",
        reporter_id=reporter_id,
        tenant_id=tenant_id,
    )
    db.add(dev)
    await db.flush()
    return dev


async def list_deviations(db: AsyncSession, status: str | None = None, severity: str | None = None, page: int = 1, page_size: int = 20, tenant_id: int = 1) -> dict[str, Any]:
    query = select(Deviation).where(Deviation.is_deleted == False, Deviation.tenant_id == tenant_id)
    if status:
        query = query.where(Deviation.status == status)
    if severity:
        query = query.where(Deviation.severity == severity)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(query.order_by(Deviation.id.desc()).offset((page-1)*page_size).limit(page_size))
    items = [serialize_deviation(d) for d in result.scalars().all()]
    return {"items": items, "pagination": {"page": page, "page_size": page_size, "total": total}}


def serialize_deviation(d: Deviation) -> dict[str, Any]:
    return {
        "id": d.id, "dev_no": d.dev_no, "title": d.title, "description": d.description,
        "area": d.area, "severity": d.severity, "category": d.category, "status": d.status,
        "occurred_at": d.occurred_at, "reporter_id": d.reporter_id,
        "classify_result": d.classify_result, "investigation_plan": d.investigation_plan,
        "root_cause": d.root_cause, "case_refs": d.case_refs, "capa_id": d.capa_id,
        "review_comment": d.review_comment,
    }


async def get_deviation(db: AsyncSession, dev_id: int) -> Deviation:
    result = await db.execute(select(Deviation).where(Deviation.id == dev_id, Deviation.is_deleted == False))
    dev = result.scalar_one_or_none()
    if not dev:
        raise NotFoundError()
    return dev


async def _transition(db: AsyncSession, dev: Deviation, to_status: str):
    allowed = ALLOWED_TRANSITIONS.get(dev.status, set())
    if dev.status == "reported" and to_status == "reported":
        return
    if to_status not in allowed:
        raise StateError(message=f"非法状态跃迁: {dev.status} -> {to_status}")


async def classify_deviation(db: AsyncSession, dev_id: int, severity: str | None, classify_result: dict[str, Any] | None, tenant_id: int = 1) -> dict[str, Any]:
    dev = await get_deviation(db, dev_id)
    await _transition(db, dev, "classified")
    if severity:
        dev.severity = severity
    if classify_result:
        dev.classify_result = classify_result
    dev.status = "classified"
    created_hold = False
    if dev.severity == "critical":
        hold = BatchHold(deviation_id=dev.id, batch_no="TBD", product_name="TBD",
                         hold_reason="重大偏差触发批次挂起", status="held", tenant_id=tenant_id)
        db.add(hold)
        await db.flush()
        created_hold = True
    await db.flush()
    return {"id": dev.id, "status": dev.status, "created_batch_hold": created_hold}


async def investigate_deviation(db: AsyncSession, dev_id: int, investigation_plan: dict[str, Any]) -> dict[str, Any]:
    dev = await get_deviation(db, dev_id)
    await _transition(db, dev, "investigating")
    dev.investigation_plan = investigation_plan
    dev.status = "investigating"
    await db.flush()
    return {"id": dev.id, "status": dev.status}


async def submit_deviation_review(db: AsyncSession, dev_id: int, root_cause: str) -> dict[str, Any]:
    dev = await get_deviation(db, dev_id)
    await _transition(db, dev, "qa_review")
    dev.root_cause = root_cause
    dev.status = "qa_review"
    await db.flush()
    return {"id": dev.id, "status": dev.status}


async def review_deviation(db: AsyncSession, dev_id: int, approve: bool, comment: str | None, reviewer_id: int) -> dict[str, Any]:
    dev = await get_deviation(db, dev_id)
    if approve:
        await _transition(db, dev, "capa_linked")
        dev.status = "capa_linked"
    else:
        await _transition(db, dev, "investigating")
        dev.status = "investigating"
    dev.reviewer_id = reviewer_id
    dev.review_comment = comment
    await db.flush()
    return {"id": dev.id, "status": dev.status}


async def reopen_deviation(db: AsyncSession, dev_id: int, reason: str) -> dict[str, Any]:
    dev = await get_deviation(db, dev_id)
    if dev.status == "reported":
        raise StateError(message="偏差已在 reported 状态")
    dev.status = "reported"
    dev.review_comment = reason
    await db.flush()
    return {"id": dev.id, "status": dev.status}


async def close_deviation(db: AsyncSession, dev_id: int, comment: str | None) -> dict[str, Any]:
    dev = await get_deviation(db, dev_id)
    await _transition(db, dev, "closed")
    if dev.status == "capa_linked":
        if not dev.capa_id:
            raise DeviationCloseError(message="偏差尚未关联CAPA，无法关闭")
        capa = (await db.execute(select(CapaRecord).where(CapaRecord.id == dev.capa_id))).scalar_one_or_none()
        if not capa or capa.status != "verified":
            raise DeviationCloseError(message="CAPA未验证，无法关闭偏差")
        holds = (await db.execute(select(BatchHold).where(BatchHold.deviation_id == dev.id, BatchHold.status == "held"))).scalars().all()
        if holds:
            raise DeviationCloseError(message="存在未解除的批次挂起")
    dev.status = "closed"
    dev.review_comment = comment
    await db.flush()
    return {"id": dev.id, "status": dev.status}


async def create_batch_hold(db: AsyncSession, deviation_id: int, batch_no: str, product_name: str | None, hold_reason: str | None, tenant_id: int = 1) -> BatchHold:
    await get_deviation(db, deviation_id)
    hold = BatchHold(deviation_id=deviation_id, batch_no=batch_no, product_name=product_name,
                     hold_reason=hold_reason, status="held", tenant_id=tenant_id)
    db.add(hold)
    await db.flush()
    return hold


async def release_batch_hold(db: AsyncSession, hold_id: int) -> BatchHold:
    result = await db.execute(select(BatchHold).where(BatchHold.id == hold_id))
    hold = result.scalar_one_or_none()
    if not hold:
        raise NotFoundError()
    if hold.status == "released":
        raise StateError(message="批次已解除挂起")
    dev = await get_deviation(db, hold.deviation_id)
    if dev.status != "closed":
        raise DeviationCloseError(message="偏差关闭前不得解除批次挂起")
    hold.status = "released"
    await db.flush()
    return hold


async def list_changes(db: AsyncSession, status: str | None = None, page: int = 1, page_size: int = 20, tenant_id: int = 1) -> dict[str, Any]:
    query = select(ChangeControl).where(ChangeControl.is_deleted == False, ChangeControl.tenant_id == tenant_id)
    if status:
        query = query.where(ChangeControl.status == status)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(query.order_by(ChangeControl.id.desc()).offset((page-1)*page_size).limit(page_size))
    items = [
        {
            "id": c.id, "chg_no": c.chg_no, "title": c.title, "change_type": c.change_type,
            "description": c.description, "impact_level": c.impact_level, "status": c.status,
            "initiator_id": c.initiator_id, "approver_id": c.approver_id,
        }
        for c in result.scalars().all()
    ]
    return {"items": items, "pagination": {"page": page, "page_size": page_size, "total": total}}


async def list_capas(db: AsyncSession, source_type: str | None = None, page: int = 1, page_size: int = 20, tenant_id: int = 1) -> dict[str, Any]:
    query = select(CapaRecord).where(CapaRecord.is_deleted == False, CapaRecord.tenant_id == tenant_id)
    if source_type:
        query = query.where(CapaRecord.source_type == source_type)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(query.order_by(CapaRecord.id.desc()).offset((page-1)*page_size).limit(page_size))
    items = [
        {
            "id": c.id, "capa_no": c.capa_no, "source_type": c.source_type, "source_id": c.source_id,
            "title": c.title, "root_cause": c.root_cause, "actions": c.actions, "status": c.status,
        }
        for c in result.scalars().all()
    ]
    return {"items": items, "pagination": {"page": page, "page_size": page_size, "total": total}}


async def create_change(db: AsyncSession, req, initiator_id: int, tenant_id: int = 1) -> ChangeControl:
    year = datetime.now(UTC).year
    result = await db.execute(select(func.count()).select_from(ChangeControl).where(ChangeControl.tenant_id == tenant_id))
    seq = (result.scalar() or 0) + 1
    change = ChangeControl(chg_no=f"CHG-{year}-{seq:04d}", title=req.title, change_type=req.change_type,
                           description=req.description, status="submitted", initiator_id=initiator_id, tenant_id=tenant_id)
    db.add(change)
    await db.flush()
    return change


async def get_change(db: AsyncSession, chg_id: int) -> ChangeControl:
    result = await db.execute(select(ChangeControl).where(ChangeControl.id == chg_id, ChangeControl.is_deleted == False))
    change = result.scalar_one_or_none()
    if not change:
        raise NotFoundError()
    return change


async def assess_change(db: AsyncSession, chg_id: int, impact_assessment: dict[str, Any], assessor_id: int) -> dict[str, Any]:
    change = await get_change(db, chg_id)
    if change.status != "submitted":
        raise StateError(message=f"非法状态跃迁: {change.status} -> assessed")
    change.impact_assessment = impact_assessment
    change.assessor_id = assessor_id
    change.status = "assessed"
    await db.flush()
    return {"id": change.id, "status": change.status}


async def approve_change(db: AsyncSession, chg_id: int, approver_id: int, comment: str | None) -> dict[str, Any]:
    change = await get_change(db, chg_id)
    if change.status != "assessed":
        raise StateError(message=f"非法状态跃迁: {change.status} -> approved")
    if change.initiator_id == approver_id:
        raise FourEyeError(message="发起人不能作为审批人")
    change.approver_id = approver_id
    change.approval_comment = comment
    change.status = "approved"
    await db.flush()
    return {"id": change.id, "status": change.status}


async def implement_change(db: AsyncSession, chg_id: int, implementation_plan: dict[str, Any]) -> dict[str, Any]:
    change = await get_change(db, chg_id)
    if change.status != "approved":
        raise StateError(message=f"非法状态跃迁: {change.status} -> implemented")
    change.implementation_plan = implementation_plan
    change.status = "implemented"
    await db.flush()
    return {"id": change.id, "status": change.status}


async def verify_change(db: AsyncSession, chg_id: int, verification_result: dict[str, Any]) -> dict[str, Any]:
    change = await get_change(db, chg_id)
    if change.status != "implemented":
        raise StateError(message=f"非法状态跃迁: {change.status} -> verified")
    change.impact_assessment = {**(change.impact_assessment or {}), "verification": verification_result}
    change.status = "verified"
    await db.flush()
    return {"id": change.id, "status": change.status}


async def close_change(db: AsyncSession, chg_id: int, comment: str | None) -> dict[str, Any]:
    change = await get_change(db, chg_id)
    if change.status != "verified":
        raise StateError(message=f"非法状态跃迁: {change.status} -> closed")
    if change.capa_id:
        capa = (await db.execute(select(CapaRecord).where(CapaRecord.id == change.capa_id))).scalar_one_or_none()
        if capa and capa.status != "verified":
            raise DeviationCloseError(message="关联CAPA未验证")
    change.approval_comment = comment or change.approval_comment
    change.status = "closed"
    await db.flush()
    return {"id": change.id, "status": change.status}


async def create_capa(db: AsyncSession, req, creator_id: int, tenant_id: int = 1) -> CapaRecord:
    existing = await db.execute(select(CapaRecord).where(CapaRecord.source_type == req.source_type, CapaRecord.source_id == req.source_id, CapaRecord.is_deleted == False))
    if existing.scalar_one_or_none():
        raise StateError(message="该来源已关联CAPA")
    year = datetime.now(UTC).year
    result = await db.execute(select(func.count()).select_from(CapaRecord).where(CapaRecord.tenant_id == tenant_id))
    seq = (result.scalar() or 0) + 1
    capa = CapaRecord(capa_no=f"CAPA-{year}-{seq:04d}", source_type=req.source_type, source_id=req.source_id,
                      title=req.title, root_cause=req.root_cause, status="open", tenant_id=tenant_id)
    db.add(capa)
    await db.flush()
    if req.source_type == "deviation":
        dev = await get_deviation(db, req.source_id)
        dev.capa_id = capa.id
    elif req.source_type == "change":
        change = await get_change(db, req.source_id)
        change.capa_id = capa.id
    return capa


async def update_capa_actions(db: AsyncSession, capa_id: int, actions: list[dict[str, Any]]) -> CapaRecord:
    result = await db.execute(select(CapaRecord).where(CapaRecord.id == capa_id, CapaRecord.is_deleted == False))
    capa = result.scalar_one_or_none()
    if not capa:
        raise NotFoundError()
    if capa.status == "closed":
        raise StateError(message="CAPA已关闭")
    capa.actions = {"items": actions}
    capa.status = "in_progress"
    await db.flush()
    return capa


async def verify_capa(db: AsyncSession, capa_id: int, effectiveness_check: dict[str, Any]) -> CapaRecord:
    result = await db.execute(select(CapaRecord).where(CapaRecord.id == capa_id, CapaRecord.is_deleted == False))
    capa = result.scalar_one_or_none()
    if not capa:
        raise NotFoundError()
    capa.effectiveness_check = effectiveness_check
    capa.status = "verified"
    await db.flush()
    return capa
