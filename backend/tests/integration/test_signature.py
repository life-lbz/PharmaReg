"""电子签名集成测试：PIN 未设置、口令错误、含义不匹配、幂等防重放。"""
import pytest

from app.audit.signature import execute_signature
from app.core.exceptions import IdempotencyConflict, SignatureError, SignatureMeaningError
from app.core.security import hash_password
from app.models.system import SysUser

REVIEW_MEANING = "本人已审核偏差分级与调查结论，批准关闭此偏差记录"


async def _mk_user(db_session, with_pin: bool = True, employee_no="EMP-SIG-001"):
    user = SysUser(
        username=f"siguser_{employee_no}",
        password_hash=hash_password("Login@123456"),
        signature_pin_hash=hash_password("666888") if with_pin else None,
        employee_no=employee_no,
        display_name="签名测试员",
        status="active",
        tenant_id=1,
    )
    db_session.add(user)
    await db_session.flush()
    return user


class TestSignature:
    async def test_sign_without_pin_rejected(self, db_session):
        user = await _mk_user(db_session, with_pin=False, employee_no="EMP-SIG-002")
        with pytest.raises(SignatureError):
            await execute_signature(
                db_session, user, "deviation", 1, REVIEW_MEANING,
                "deviation.review", "123456", None,
            )

    async def test_wrong_pin_rejected(self, db_session):
        user = await _mk_user(db_session, employee_no="EMP-SIG-003")
        with pytest.raises(SignatureError):
            await execute_signature(
                db_session, user, "deviation", 1, REVIEW_MEANING,
                "deviation.review", "000000", None,
            )

    async def test_meaning_mismatch_rejected(self, db_session):
        user = await _mk_user(db_session, employee_no="EMP-SIG-004")
        with pytest.raises(SignatureMeaningError):
            await execute_signature(
                db_session, user, "deviation", 1, "不匹配的含义声明",
                "deviation.review", "666888", None,
            )

    async def test_idempotency_blocks_duplicate(self, db_session):
        user = await _mk_user(db_session, employee_no="EMP-SIG-005")
        sig1 = await execute_signature(
            db_session, user, "deviation", 1, REVIEW_MEANING,
            "deviation.review", "666888", "idem-key-1",
        )
        await db_session.flush()
        with pytest.raises(IdempotencyConflict):
            await execute_signature(
                db_session, user, "deviation", 1, REVIEW_MEANING,
                "deviation.review", "666888", "idem-key-1",
            )
        assert sig1.id is not None

    async def test_successful_sign_flow(self, db_session):
        user = await _mk_user(db_session, employee_no="EMP-SIG-006")
        sig = await execute_signature(
            db_session, user, "deviation", 77, REVIEW_MEANING,
            "deviation.review", "666888", None,
        )
        assert sig.signature_hash  # 记录内容 hash 已绑定
        assert sig.meaning == REVIEW_MEANING
