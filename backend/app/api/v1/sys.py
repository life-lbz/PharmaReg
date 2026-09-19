import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.redis import get_redis
from app.db.session import get_db
from app.models.system import SysUser
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    SetSignaturePinRequest,
    TokenResponse,
    UserInfo,
)
from app.schemas.common import ok
from app.services.auth_service import (
    authenticate_user,
    change_password,
    get_user_permissions,
    get_user_roles,
    set_signature_pin,
)

router = APIRouter(prefix="/sys/auth", tags=["系统认证"])


@router.post("/login")
async def login(req: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    user, token = await authenticate_user(db, req.username, req.password)
    await db.commit()
    return ok(TokenResponse(access_token=token, expires_in=settings.JWT_EXPIRE_MINUTES * 60).model_dump())


@router.post("/logout")
async def logout(request: Request):
    auth_header = request.headers.get("Authorization", "")
    import re
    match = re.match(r"^Bearer\s+(.+)$", auth_header)
    if match:
        from app.core.security import decode_access_token
        payload = decode_access_token(match.group(1))
        jti = payload.get("jti", str(uuid.uuid4()))
        redis = await get_redis()
        ttl = settings.JWT_EXPIRE_MINUTES * 60
        await redis.set(f"bl:{jti}", "1", ex=ttl)
    return ok({"message": "已登出"})


@router.get("/me")
async def me(user: SysUser = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    roles = await get_user_roles(db, user.id)
    permissions = list(await get_user_permissions(db, user.id))
    return ok(UserInfo(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        employee_no=user.employee_no,
        department=user.department,
        roles=roles,
        permissions=permissions,
    ).model_dump())


@router.put("/password")
async def update_password(
    req: ChangePasswordRequest,
    user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await change_password(db, user, req.old_password, req.new_password)
    await db.commit()
    return ok({"message": "密码已修改"})


@router.put("/signature-pin")
async def update_signature_pin(
    req: SetSignaturePinRequest,
    user: SysUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await set_signature_pin(db, user, req.pin, req.old_pin)
    await db.commit()
    return ok({"message": "签名口令已设置"})
