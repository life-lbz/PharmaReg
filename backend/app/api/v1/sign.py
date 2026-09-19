from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import write_audit
from app.audit.signature import execute_signature
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.system import SysUser
from app.schemas.common import ok
from app.schemas.signature import SignRequest, SignResponse

router = APIRouter(prefix="/sys", tags=["电子签名"])


@router.post("/sign")
async def sign(
    req: SignRequest,
    request: Request,
    user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sig = await execute_signature(
        db,
        user=user,
        record_type=req.record_type,
        record_id=req.record_id,
        meaning=req.meaning,
        action_type=req.action_type,
        signature_pin=req.signature_pin,
        idempotency_key=req.idempotency_key,
    )
    await write_audit(
        db,
        event_type="sign.executed",
        action="sign",
        actor_id=user.id,
        object_type=req.record_type,
        object_id=req.record_id,
        after={"signature_id": sig.id, "meaning": req.meaning},
        ip=request.client.host if request.client else None,
        tenant_id=user.tenant_id,
    )
    await db.commit()
    return ok(SignResponse(
        id=sig.id,
        record_type=sig.record_type,
        record_id=sig.record_id,
        signer_id=sig.signer_id,
        action_type=sig.action_type,
        signed_at=sig.created_at.isoformat() if sig.created_at else None,
    ).model_dump())
