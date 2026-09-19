from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import hash_password
from app.db.session import get_db
from app.models.system import SysRole, SysUser, SysUserRole
from app.schemas.common import ok, paginate
from app.schemas.user import CreateUserRequest, UpdateUserRequest, UserListItem

router = APIRouter(prefix="/sys/users", tags=["用户管理"])


@router.post("")
async def create_user(
    req: CreateUserRequest,
    user: SysUser = Depends(require_permission("sys.user.manage")),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(SysUser).where(SysUser.username == req.username))
    if existing.scalar_one_or_none():
        raise ValidationError(message="用户名已存在")
    existing_emp = await db.execute(select(SysUser).where(SysUser.employee_no == req.employee_no))
    if existing_emp.scalar_one_or_none():
        raise ValidationError(message="工号已存在")

    new_user = SysUser(
        username=req.username,
        password_hash=hash_password(req.password),
        employee_no=req.employee_no,
        display_name=req.display_name,
        department=req.department,
        must_change_pwd=req.must_change_pwd,
        tenant_id=user.tenant_id,
    )
    db.add(new_user)
    await db.flush()

    for role_code in req.role_codes:
        role_result = await db.execute(select(SysRole).where(SysRole.role_code == role_code))
        role = role_result.scalar_one_or_none()
        if role:
            db.add(SysUserRole(user_id=new_user.id, role_id=role.id, tenant_id=user.tenant_id))

    await db.commit()
    return ok({"id": new_user.id, "username": new_user.username})


@router.get("")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    user: SysUser = Depends(require_permission("sys.user.manage")),
    db: AsyncSession = Depends(get_db),
):
    query = select(SysUser).where(SysUser.is_deleted == False)
    if keyword:
        query = query.where(
            SysUser.username.contains(keyword) | SysUser.display_name.contains(keyword)
        )
    count_query = select(func.count()).select_from(SysUser).where(SysUser.is_deleted == False)
    if keyword:
        count_query = count_query.where(
            SysUser.username.contains(keyword) | SysUser.display_name.contains(keyword)
        )

    total = (await db.execute(count_query)).scalar() or 0
    items_result = await db.execute(
        query.offset((page - 1) * page_size).limit(page_size).order_by(SysUser.id.desc())
    )
    users = items_result.scalars().all()

    items = []
    for u in users:
        roles_result = await db.execute(
            select(SysRole.role_code)
            .join(SysUserRole, SysUserRole.role_id == SysRole.id)
            .where(SysUserRole.user_id == u.id)
        )
        roles = list(roles_result.scalars().all())
        items.append(UserListItem(
            id=u.id, username=u.username, employee_no=u.employee_no,
            display_name=u.display_name, department=u.department, status=u.status, roles=roles,
        ).model_dump())

    return ok(paginate(items, page, page_size, total))


@router.put("/{user_id}")
async def update_user(
    user_id: int,
    req: UpdateUserRequest,
    user: SysUser = Depends(require_permission("sys.user.manage")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(SysUser).where(SysUser.id == user_id, SysUser.is_deleted == False))
    target = result.scalar_one_or_none()
    if not target:
        raise NotFoundError()
    if req.display_name is not None:
        target.display_name = req.display_name
    if req.department is not None:
        target.department = req.department
    if req.status is not None:
        target.status = req.status

    if req.role_codes is not None:
        await db.execute(
            SysUserRole.__table__.delete().where(SysUserRole.user_id == user_id)
        )
        for role_code in req.role_codes:
            role_result = await db.execute(select(SysRole).where(SysRole.role_code == role_code))
            role = role_result.scalar_one_or_none()
            if role:
                db.add(SysUserRole(user_id=user_id, role_id=role.id, tenant_id=target.tenant_id))

    await db.commit()
    return ok({"id": target.id})
