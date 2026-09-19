"""集成测试 fixture：使用独立测试库 pharmareg_test（要求本地 MySQL 127.0.0.1:3307 可用）。"""
import os
import time

import pymysql
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 确保模型注册
from app.db.base import Base

TEST_DB_HOST = os.environ.get("TEST_MYSQL_HOST", "127.0.0.1")
TEST_DB_PORT = int(os.environ.get("TEST_MYSQL_PORT", "3307"))
TEST_DB_USER = os.environ.get("TEST_MYSQL_USER", "root")
TEST_DB_PWD = os.environ.get("TEST_MYSQL_PWD", "pharmareg")
TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "pharmareg_test")

SYNC_URL = f"mysql+pymysql://{TEST_DB_USER}:{TEST_DB_PWD}@{TEST_DB_HOST}:{TEST_DB_PORT}/{TEST_DB_NAME}?charset=utf8mb4"
ASYNC_URL = f"mysql+aiomysql://{TEST_DB_USER}:{TEST_DB_PWD}@{TEST_DB_HOST}:{TEST_DB_PORT}/{TEST_DB_NAME}?charset=utf8mb4"

# 测试涉及的清理表（按依赖顺序）
CLEAN_TABLES = [
    "electronic_signatures",
    "audit_logs",
    "batch_holds",
    "capa_records",
    "deviations",
    "change_controls",
    "sys_user_roles",
    "sys_users",
    "sys_role_permissions",
    "sys_roles",
]


def _ensure_database():
    conn = pymysql.connect(host=TEST_DB_HOST, port=TEST_DB_PORT, user=TEST_DB_USER, password=TEST_DB_PWD)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS {TEST_DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
    finally:
        conn.close()


def _create_tables():
    _ensure_database()
    sync_engine = create_engine(SYNC_URL, pool_pre_ping=True)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    time.sleep(0.2)


_ensure_database()
_create_tables()


@pytest_asyncio.fixture
async def db_session():
    # NullPool：每个测试函数使用独立事件循环（pytest-asyncio 默认 function 级），连接按需创建
    engine = create_async_engine(ASYNC_URL, poolclass=None, pool_pre_ping=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            for table in CLEAN_TABLES:
                try:
                    await session.execute(text(f"DELETE FROM `{table}`"))
                except Exception:
                    await session.rollback()
            await session.commit()
            await session.close()
    await engine.dispose()
