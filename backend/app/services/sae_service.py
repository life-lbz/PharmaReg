from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, StateError
from app.models.compliance import Notification
from app.models.vigilance import SaeReport

SAE_TRANSITIONS: dict[str, set[str]] = {
    "recorded": {"pv_reviewed"},
    "pv_reviewed": {"draft"},
    "draft": {"signed"},
    "signed": {"submitted"},
    "submitted": {"archived"},
    "archived": set(),
}


async def create_sae(db: AsyncSession, req, creator_id: int, tenant_id: int = 1) -> SaeReport:
    now = datetime.now(UTC)
    year = now.year
    result = await db.execute(select(func.count()).select_from(SaeReport).where(SaeReport.tenant_id == tenant_id))
    seq = (result.scalar() or 0) + 1
    sae = SaeReport(
        sae_no=f"SAE-{year}-{seq:04d}",
        subject_no=req.subject_no,
        ae_description=req.ae_description,
        seriousness={"flags": req.seriousness or []},
        status="recorded",
        tenant_id=tenant_id,
    )
    sae.report_deadline_1 = (now + timedelta(hours=24)).isoformat()
    sae.report_deadline_2 = (now + timedelta(days=7)).isoformat()
    db.add(sae)
    await db.flush()
    return sae


async def list_sae(db: AsyncSession, status: str | None = None, page: int = 1, page_size: int = 20, tenant_id: int = 1) -> dict[str, Any]:
    query = select(SaeReport).where(SaeReport.is_deleted == False, SaeReport.tenant_id == tenant_id)
    if status:
        query = query.where(SaeReport.status == status)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(query.order_by(SaeReport.id.desc()).offset((page-1)*page_size).limit(page_size))
    items = []
    now = datetime.now(UTC)
    for s in result.scalars().all():
        d = serialize_sae(s)
        d["remaining_hours"] = _remaining_hours(s.report_deadline_1, now)
        d["urgent"] = d["remaining_hours"] is not None and d["remaining_hours"] <= 4
        items.append(d)
    return {"items": items, "pagination": {"page": page, "page_size": page_size, "total": total}}


def _remaining_hours(deadline: str | None, now: datetime) -> float | None:
    if not deadline:
        return None
    try:
        deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        if deadline_dt.tzinfo is None:
            deadline_dt = deadline_dt.replace(tzinfo=UTC)
        delta = deadline_dt - now
        return round(delta.total_seconds() / 3600, 1)
    except Exception:
        return None


def serialize_sae(s: SaeReport) -> dict[str, Any]:
    return {
        "id": s.id, "sae_no": s.sae_no, "subject_no": s.subject_no,
        "ae_description": s.ae_description, "seriousness": s.seriousness,
        "causality": s.causality, "status": s.status,
        "report_deadline_1": s.report_deadline_1, "report_deadline_2": s.report_deadline_2,
        "draft": s.draft, "pv_reviewer_id": s.pv_reviewer_id,
        "investigator_id": s.investigator_id, "submitted_at": s.submitted_at,
    }


async def get_sae(db: AsyncSession, sae_id: int) -> SaeReport:
    result = await db.execute(select(SaeReport).where(SaeReport.id == sae_id, SaeReport.is_deleted == False))
    sae = result.scalar_one_or_none()
    if not sae:
        raise NotFoundError()
    return sae


async def _check_transition(sae: SaeReport, to_status: str):
    allowed = SAE_TRANSITIONS.get(sae.status, set())
    if to_status not in allowed:
        raise StateError(message=f"非法状态跃迁: {sae.status} -> {to_status}")


async def pv_review(db: AsyncSession, sae_id: int, seriousness: list[str], causality: str, reviewer_id: int) -> dict[str, Any]:
    sae = await get_sae(db, sae_id)
    await _check_transition(sae, "pv_reviewed")
    sae.seriousness = {"flags": seriousness}
    sae.causality = causality
    sae.pv_reviewer_id = reviewer_id
    sae.status = "pv_reviewed"
    await db.flush()
    return {"id": sae.id, "status": sae.status}


async def generate_draft(db: AsyncSession, sae_id: int, draft: dict[str, Any]) -> dict[str, Any]:
    sae = await get_sae(db, sae_id)
    await _check_transition(sae, "draft")
    sae.draft = draft
    sae.status = "draft"
    await db.flush()
    return {"id": sae.id, "status": sae.status}


async def sign_sae(db: AsyncSession, sae_id: int, investigator_id: int) -> dict[str, Any]:
    sae = await get_sae(db, sae_id)
    await _check_transition(sae, "signed")
    sae.investigator_id = investigator_id
    sae.status = "signed"
    await db.flush()
    return {"id": sae.id, "status": sae.status}


async def submit_sae(db: AsyncSession, sae_id: int) -> dict[str, Any]:
    sae = await get_sae(db, sae_id)
    await _check_transition(sae, "submitted")
    sae.status = "submitted"
    sae.submitted_at = datetime.now(UTC).isoformat()
    await db.flush()
    return {"id": sae.id, "status": sae.status}


async def archive_sae(db: AsyncSession, sae_id: int) -> dict[str, Any]:
    sae = await get_sae(db, sae_id)
    await _check_transition(sae, "archived")
    sae.status = "archived"
    await db.flush()
    return {"id": sae.id, "status": sae.status}


async def scan_deadlines(db: AsyncSession, tenant_id: int = 1) -> int:
    result = await db.execute(
        select(SaeReport).where(
            SaeReport.status.in_(["recorded", "pv_reviewed", "draft"]),
            SaeReport.tenant_id == tenant_id,
        )
    )
    saes = result.scalars().all()
    now = datetime.now(UTC)
    count = 0
    for sae in saes:
        remaining = _remaining_hours(sae.report_deadline_1, now)
        if remaining is not None and remaining <= 4:
            n = Notification(
                user_id=sae.pv_reviewer_id or 0,
                type="sae_deadline",
                title=f"SAE {sae.sae_no} 上报时限不足4小时",
                payload={"sae_id": sae.id, "remaining_hours": remaining},
                status="pending",
                tenant_id=tenant_id,
            )
            db.add(n)
            count += 1
    await db.flush()
    return count
