import re

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthError, ForbiddenError, TenantError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.system import SysRolePermission, SysUser, SysUserRole


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> SysUser:
    auth_header = request.headers.get("Authorization", "")
    match = re.match(r"^Bearer\s+(.+)$", auth_header)
    if not match:
        raise AuthError()
    payload = decode_access_token(match.group(1))
    user_id = int(payload["sub"])
    tenant_id = int(payload.get("tenant_id", 1))
    result = await db.execute(select(SysUser).where(SysUser.id == user_id, SysUser.is_deleted == False))
    user = result.scalar_one_or_none()
    if not user or user.status != "active":
        raise AuthError()
    if tenant_id != user.tenant_id:
        raise TenantError()
    request.state.current_user = user
    request.state.tenant_id = tenant_id
    request.state.user_roles = payload.get("roles", [])
    return user


async def get_user_permissions(user: SysUser, db: AsyncSession) -> set[str]:
    role_result = await db.execute(
        select(SysRolePermission.permission_code)
        .join(SysUserRole, SysUserRole.role_id == SysRolePermission.role_id)
        .where(SysUserRole.user_id == user.id)
    )
    return set(role_result.scalars().all())


def require_permission(permission: str):
    async def checker(
        request: Request,
        user: SysUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> SysUser:
        permissions: set[str] = request.state.permissions if hasattr(request.state, "permissions") else set()
        if not permissions:
            permissions = await get_user_permissions(user, db)
            request.state.permissions = permissions
        if permission not in permissions:
            raise ForbiddenError(extra={"required": permission})
        return user
    return checker


def require_scope(tenant_id: int):
    async def checker(request: Request) -> None:
        current_tenant = getattr(request.state, "tenant_id", None)
        if current_tenant is not None and current_tenant != tenant_id:
            raise TenantError()
    return checker
