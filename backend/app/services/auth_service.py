import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthError, ValidationError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.system import SysRole, SysRolePermission, SysUser, SysUserRole


async def authenticate_user(db: AsyncSession, username: str, password: str) -> tuple[SysUser, str]:
    result = await db.execute(
        select(SysUser).where(SysUser.username == username, SysUser.is_deleted == False)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise AuthError(message="用户名或密码错误")
    if user.status != "active":
        raise AuthError(message="账号已禁用")
    if user.locked_until and user.locked_until > datetime.now(UTC):
        raise AuthError(message="账号已锁定，请稍后再试")

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= 5:
            user.locked_until = datetime.now(UTC) + timedelta(minutes=15)
            user.failed_login_count = 0
        await db.flush()
        raise AuthError(message="用户名或密码错误")

    user.failed_login_count = 0
    user.last_login_at = datetime.now(UTC)
    await db.flush()

    roles = await get_user_roles(db, user.id)
    token = create_access_token(user.id, roles, user.tenant_id)
    return user, token


async def get_user_roles(db: AsyncSession, user_id: int) -> list[str]:
    result = await db.execute(
        select(SysRole.role_code)
        .join(SysUserRole, SysUserRole.role_id == SysRole.id)
        .where(SysUserRole.user_id == user_id)
    )
    return list(result.scalars().all())


async def get_user_permissions(db: AsyncSession, user_id: int) -> set[str]:
    result = await db.execute(
        select(SysRolePermission.permission_code)
        .join(SysUserRole, SysUserRole.role_id == SysRolePermission.role_id)
        .where(SysUserRole.user_id == user_id)
    )
    return set(result.scalars().all())


async def change_password(db: AsyncSession, user: SysUser, old_pwd: str, new_pwd: str):
    if not verify_password(old_pwd, user.password_hash):
        raise ValidationError(message="旧密码错误")
    if len(new_pwd) < 12:
        raise ValidationError(message="密码至少12位")
    has_upper = any(c.isupper() for c in new_pwd)
    has_lower = any(c.islower() for c in new_pwd)
    has_digit = any(c.isdigit() for c in new_pwd)
    has_special = any(not c.isalnum() for c in new_pwd)
    types_count = sum([has_upper, has_lower, has_digit, has_special])
    if types_count < 3:
        raise ValidationError(message="密码需包含大写字母、小写字母、数字、特殊字符中的至少三类")
    user.password_hash = hash_password(new_pwd)
    user.must_change_pwd = False
    await db.flush()


async def set_signature_pin(db: AsyncSession, user: SysUser, pin: str, old_pin: str | None = None):
    if user.signature_pin_hash:
        if not old_pin:
            raise ValidationError(message="请输入旧签名口令")
        if not verify_password(old_pin, user.signature_pin_hash):
            raise ValidationError(message="旧签名口令错误")
    if len(pin) < 6:
        raise ValidationError(message="签名口令至少6位")
    user.signature_pin_hash = hash_password(pin)
    await db.flush()


def generate_jti() -> str:
    return str(uuid.uuid4())
