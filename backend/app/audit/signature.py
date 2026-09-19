import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import IdempotencyConflict, SignatureError, SignatureMeaningError
from app.core.security import verify_password
from app.models.compliance import ElectronicSignature
from app.models.system import SysUser

SIGNATURE_MEANINGS = {
    "deviation.review": "本人已审核偏差分级与调查结论，批准关闭此偏差记录",
    "change.approve": "本人批准此变更申请，已确认影响评估结果",
    "sae.sign": "本人作为研究者确认SAE报告内容真实，承担电子签名法律责任",
    "sae.submit": "本人确认提交此SAE报告至申办方及伦理委员会",
    "product.release": "本人作为质量受权人批准放行此批次产品",
    "kb.activate": "本人确认激活此法规版本集合，承担版本切换责任",
    "kb.rollback": "本人确认回滚此法规版本至上一冻结版本",
    "capa.verify": "本人确认CAPA措施有效，验证通过",
}


async def execute_signature(
    db: AsyncSession,
    user: SysUser,
    record_type: str,
    record_id: int,
    meaning: str,
    action_type: str,
    signature_pin: str,
    idempotency_key: str | None = None,
) -> ElectronicSignature:
    if idempotency_key:
        existing = await db.execute(
            select(ElectronicSignature).where(
                ElectronicSignature.idempotency_key == idempotency_key
            )
        )
        existing_sig = existing.scalar_one_or_none()
        if existing_sig:
            raise IdempotencyConflict(extra={"existing_id": existing_sig.id})

    if not user.signature_pin_hash:
        raise SignatureError(message="签名口令未设置")

    if not verify_password(signature_pin, user.signature_pin_hash):
        raise SignatureError(message="签名口令错误")

    expected_meaning = SIGNATURE_MEANINGS.get(action_type)
    if expected_meaning and meaning != expected_meaning:
        raise SignatureMeaningError(extra={"expected": expected_meaning})

    content_hash = hashlib.sha256(
        f"{record_type}:{record_id}:{user.id}:{meaning}".encode()
    ).hexdigest()

    sig = ElectronicSignature(
        record_type=record_type,
        record_id=record_id,
        signer_id=user.id,
        meaning=meaning,
        action_type=action_type,
        signature_hash=content_hash,
        idempotency_key=idempotency_key,
        tenant_id=user.tenant_id,
    )
    db.add(sig)
    await db.flush()
    return sig
