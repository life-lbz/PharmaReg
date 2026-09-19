import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.base import Base
from app.db.session import AsyncSessionLocal, engine
from app.models.system import SysRole, SysRolePermission, SysUser, SysUserRole

ROLES = [
    ("operator", "生产操作人员", "gmp", "车间操作工、批记录填写员"),
    ("qc", "QC 检验人员", "gmp", "实验室检验员"),
    ("qa", "QA 质量保证人员", "gmp", "QA 专员、质量受权人（QP）"),
    ("engineer", "设备与设施工程师", "gmp", "设备工程师、公用系统工程师"),
    ("investigator", "研究者", "gcp", "主要研究者（PI）、副研究者"),
    ("crc", "临床协调员", "gcp", "机构 CRC"),
    ("cra", "临床监查员", "gcp", "申办方派驻 CRA"),
    ("pv", "药物警戒专员", "gcp", "PV 专员"),
    ("trainer", "培训管理员", "common", "GMP / GCP 培训专员"),
    ("compliance", "内审与法规事务管理员", "common", "内审员、法规事务专员"),
    ("admin", "系统管理员", "system", "系统管理员（内置）"),
]

PERMISSION_MATRIX = {
    "operator": ["qa.ask", "training.take"],
    "qc": ["qa.ask", "deviation.view", "document.search"],
    "qa": [
        "qa.ask", "deviation.view", "deviation.review", "deviation.manage",
        "deviation.close", "capa.manage", "product.release",
    ],
    "engineer": ["qa.ask", "deviation.view", "document.search"],
    "investigator": ["qa.ask", "sae.review", "sae.sign"],
    "crc": ["qa.ask", "training.take", "sae.view"],
    "cra": ["qa.ask", "audit.prepare", "sae.assist"],
    "pv": ["qa.ask", "sae.review", "sae.deadline", "sae.submit", "sae.manage"],
    "trainer": ["training.manage", "cert.issue", "matrix.export"],
    "compliance": [
        "kb.manage", "kb.activate", "faq.approve", "audit.manage",
        "sys.audit.view", "qa.ask", "document.search",
        "change.assess", "change.approve", "change.manage",
    ],
    "admin": ["*"],
}

ALL_PERMISSIONS = [
    "qa.ask", "training.take", "training.manage", "cert.issue", "matrix.export",
    "deviation.view", "deviation.review", "deviation.manage", "deviation.close",
    "document.search", "sae.view", "sae.review", "sae.sign", "sae.assist",
    "sae.deadline", "sae.submit", "sae.manage",
    "audit.prepare", "audit.manage",
    "kb.manage", "kb.activate", "kb.view", "faq.approve",
    "change.assess", "change.approve", "change.manage",
    "capa.manage", "product.release",
    "sys.audit.view", "sys.user.manage",
]


async def seed_all():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await seed_roles(db)
        await seed_admin(db)
        await seed_permissions(db)
        await db.commit()


async def seed_roles(db: AsyncSession):
    from sqlalchemy import select
    for code, name, scope, desc in ROLES:
        existing = await db.execute(select(SysRole).where(SysRole.role_code == code))
        if not existing.scalar_one_or_none():
            db.add(SysRole(role_code=code, role_name=name, scope=scope, description=desc))


async def seed_admin(db: AsyncSession):
    from sqlalchemy import select
    existing = await db.execute(select(SysUser).where(SysUser.username == "admin"))
    if not existing.scalar_one_or_none():
        admin = SysUser(
            username="admin",
            password_hash=hash_password("Admin@123456"),
            employee_no="ADMIN-001",
            display_name="系统管理员",
            department="IT",
            status="active",
            must_change_pwd=False,
            tenant_id=1,
        )
        db.add(admin)
        await db.flush()
        admin_role = await db.execute(select(SysRole).where(SysRole.role_code == "admin"))
        role = admin_role.scalar_one_or_none()
        if role:
            db.add(SysUserRole(user_id=admin.id, role_id=role.id, tenant_id=1))


async def seed_permissions(db: AsyncSession):
    from sqlalchemy import select
    roles = (await db.execute(select(SysRole))).scalars().all()
    role_map = {r.role_code: r.id for r in roles}

    for role_code, perms in PERMISSION_MATRIX.items():
        role_id = role_map.get(role_code)
        if not role_id:
            continue
        if perms == ["*"]:
            for perm in ALL_PERMISSIONS:
                existing = await db.execute(
                    select(SysRolePermission).where(
                        SysRolePermission.role_id == role_id,
                        SysRolePermission.permission_code == perm,
                    )
                )
                if not existing.scalar_one_or_none():
                    db.add(SysRolePermission(
                        role_id=role_id, permission_code=perm, tenant_id=1,
                    ))
        else:
            for perm in perms:
                existing = await db.execute(
                    select(SysRolePermission).where(
                        SysRolePermission.role_id == role_id,
                        SysRolePermission.permission_code == perm,
                    )
                )
                if not existing.scalar_one_or_none():
                    db.add(SysRolePermission(
                        role_id=role_id, permission_code=perm, tenant_id=1,
                    ))


if __name__ == "__main__":
    asyncio.run(seed_all())
