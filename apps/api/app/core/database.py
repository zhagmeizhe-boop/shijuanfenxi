"""
Database configuration and session management
"""
import os
from typing import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db_base import Base
import app.models  # noqa: F401

DATABASE_URL = settings.DATABASE_URL

# SQLite 不支持连接池参数，按驱动分别配置
_is_sqlite = DATABASE_URL.startswith("sqlite")
_engine_kwargs = dict(
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
)
if not _is_sqlite:
    _engine_kwargs.update(
        pool_size=20,
        max_overflow=30,
        pool_pre_ping=True,
        pool_recycle=3600,
    )

# 创建异步引擎
engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for FastAPI to get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Initialize database tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_runtime_schema)


async def close_db():
    """Close database connections"""
    await engine.dispose()


def _ensure_runtime_schema(sync_conn) -> None:
    inspector = inspect(sync_conn)
    table_names = set(inspector.get_table_names())
    if "paper" not in table_names:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("paper")}
    runtime_columns = {
        "last_stage": "ALTER TABLE paper ADD COLUMN last_stage VARCHAR(64)",
        "error_message": "ALTER TABLE paper ADD COLUMN error_message TEXT",
    }

    for column_name, sql in runtime_columns.items():
        if column_name in existing_columns:
            continue
        sync_conn.execute(text(sql))

    if "question" not in table_names:
        return

    question_columns = {column["name"] for column in inspector.get_columns("question")}
    question_runtime_columns = {
        "question_label_raw": "ALTER TABLE question ADD COLUMN question_label_raw VARCHAR(50)",
        "section_index_raw": "ALTER TABLE question ADD COLUMN section_index_raw VARCHAR(20)",
    }

    for column_name, sql in question_runtime_columns.items():
        if column_name in question_columns:
            continue
        sync_conn.execute(text(sql))
