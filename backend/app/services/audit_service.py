from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.audit_prep import AuditCheck

CHECKLIST_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "gmp": [
        {"section": "机构与人员", "items": [
            {"key": "gmp-1", "text": "质量管理机构与职责是否明确", "type": "verify"},
            {"key": "gmp-2", "text": "关键人员资质与培训记录是否完整", "type": "document"},
        ]},
        {"section": "厂房与设备", "items": [
            {"key": "gmp-3", "text": "厂房设施是否符合生产要求", "type": "verify"},
            {"key": "gmp-4", "text": "设备校准与维护记录是否可追溯", "type": "document"},
        ]},
        {"section": "生产管理", "items": [
            {"key": "gmp-5", "text": "批生产记录是否完整且符合规范", "type": "document"},
            {"key": "gmp-6", "text": "偏差处理是否按规定执行", "type": "verify"},
        ]},
    ],
    "gcp": [
        {"section": "伦理与知情同意", "items": [
            {"key": "gcp-1", "text": "伦理委员会批件是否在有效期内", "type": "document"},
            {"key": "gcp-2", "text": "知情同意书签署是否规范", "type": "verify"},
        ]},
        {"section": "数据与记录", "items": [
            {"key": "gcp-3", "text": "CRF填写是否与源数据一致", "type": "verify"},
            {"key": "gcp-4", "text": "SAE报告时限是否符合GCP要求", "type": "verify"},
        ]},
    ],
    "iso": [
        {"section": "质量体系", "items": [
            {"key": "iso-1", "text": "质量手册与程序文件是否受控", "type": "document"},
            {"key": "iso-2", "text": "内审与管理评审是否按期执行", "type": "verify"},
        ]},
    ],
}

AUDIT_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"ongoing"},
    "ongoing": {"rectifying", "reported"},
    "rectifying": {"reported"},
    "reported": {"archived"},
    "archived": set(),
}


async def list_audit_checks(db: AsyncSession, check_type: str | None = None, page: int = 1, page_size: int = 20, tenant_id: int = 1) -> dict[str, Any]:
    query = select(AuditCheck).where(AuditCheck.is_deleted == False, AuditCheck.tenant_id == tenant_id)
    if check_type:
        query = query.where(AuditCheck.check_type == check_type)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(query.order_by(AuditCheck.id.desc()).offset((page-1)*page_size).limit(page_size))
    items = [
        {
            "id": c.id, "audit_no": c.audit_no, "check_type": c.check_type,
            "status": c.status, "round_no": c.round_no,
            "checklist": c.checklist, "evidence_refs": c.evidence_refs, "gaps": c.gaps,
        }
        for c in result.scalars().all()
    ]
    return {"items": items, "pagination": {"page": page, "page_size": page_size, "total": total}}


async def create_audit_check(db: AsyncSession, check_type: str, owner_id: int, tenant_id: int = 1) -> AuditCheck:
    year = datetime.now(UTC).year
    result = await db.execute(select(func.count()).select_from(AuditCheck).where(AuditCheck.tenant_id == tenant_id))
    seq = (result.scalar() or 0) + 1
    template = CHECKLIST_TEMPLATES.get(check_type, [])
    check = AuditCheck(
        audit_no=f"AUD-{year}-{seq:04d}",
        check_type=check_type,
        checklist={"sections": template},
        evidence_refs={"items": []},
        gaps={"items": []},
        status="ongoing",
        owner_id=owner_id,
        tenant_id=tenant_id,
    )
    db.add(check)
    await db.flush()
    return check


async def get_audit_check(db: AsyncSession, check_id: int) -> AuditCheck:
    result = await db.execute(select(AuditCheck).where(AuditCheck.id == check_id, AuditCheck.is_deleted == False))
    check = result.scalar_one_or_none()
    if not check:
        raise NotFoundError()
    return check


async def add_evidence(db: AsyncSession, check_id: int, item_key: str, evidence_key: str, description: str | None) -> dict[str, Any]:
    check = await get_audit_check(db, check_id)
    items = check.evidence_refs or {"items": []}
    items.setdefault("items", []).append({
        "item_key": item_key, "evidence_key": evidence_key, "description": description,
        "added_at": datetime.now(UTC).isoformat(),
    })
    check.evidence_refs = items
    await db.flush()
    return {"id": check.id, "evidence_count": len(items["items"])}


async def confirm_gaps(db: AsyncSession, check_id: int, gaps: list[dict[str, Any]]) -> dict[str, Any]:
    check = await get_audit_check(db, check_id)
    check.gaps = {"items": gaps}
    if check.status == "ongoing":
        check.status = "rectifying"
    await db.flush()
    return {"id": check.id, "gap_count": len(gaps), "status": check.status}


async def rectify_item(db: AsyncSession, check_id: int, item_key: str, rectification: str) -> dict[str, Any]:
    check = await get_audit_check(db, check_id)
    gaps = check.gaps or {"items": []}
    for gap in gaps["items"]:
        if gap.get("key") == item_key:
            gap["rectification"] = rectification
            gap["status"] = "rectified"
    check.gaps = gaps
    await db.flush()
    return {"id": check.id}


async def generate_report(db: AsyncSession, check_id: int, summary: str | None) -> dict[str, Any]:
    check = await get_audit_check(db, check_id)
    gaps = (check.gaps or {}).get("items", [])
    evidence = (check.evidence_refs or {}).get("items", [])
    open_gaps = [g for g in gaps if g.get("status") != "rectified"]
    report = {
        "audit_no": check.audit_no,
        "check_type": check.check_type,
        "summary": summary or "审计完成",
        "total_gaps": len(gaps),
        "open_gaps": len(open_gaps),
        "evidence_count": len(evidence),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    if check.status != "reported":
        check.status = "reported"
    await db.flush()
    return report
