"""
Database configuration and session management
"""
import os
from typing import AsyncGenerator
from urllib.parse import urlsplit

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
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_pre_ping=True,
        pool_recycle=settings.DB_POOL_RECYCLE,
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


def _service_kind(url: str) -> str:
    scheme = urlsplit(url).scheme.lower()
    if "+" in scheme:
        scheme = scheme.split("+", 1)[1]
    return scheme or "unknown"


def _sanitize_database_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme:
        return url

    host = parsed.hostname or "local-file"
    netloc = host
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    if parsed.username:
        netloc = f"{parsed.username}:***@{netloc}"

    return f"{parsed.scheme}://{netloc}{parsed.path or ''}"


async def get_database_preflight_status() -> dict[str, object]:
    """Return a production-friendly database readiness snapshot."""
    safe_url = _sanitize_database_url(DATABASE_URL)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        return {
            "database_ready": False,
            "message": f"数据库不可用：{exc.__class__.__name__}: {str(exc).strip() or exc.__class__.__name__}",
            "database_kind": _service_kind(DATABASE_URL),
            "database_url": safe_url,
        }

    return {
        "database_ready": True,
        "message": f"数据库可用（{safe_url}）",
        "database_kind": _service_kind(DATABASE_URL),
        "database_url": safe_url,
    }


def _ensure_runtime_schema(sync_conn) -> None:
    inspector = inspect(sync_conn)
    table_names = set(inspector.get_table_names())
    if "paper" not in table_names:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("paper")}
    runtime_columns = {
        "last_stage": "ALTER TABLE paper ADD COLUMN last_stage VARCHAR(64)",
        "error_message": "ALTER TABLE paper ADD COLUMN error_message TEXT",
        "analysis_task_id": "ALTER TABLE paper ADD COLUMN analysis_task_id VARCHAR(128)",
        "cancel_requested": "ALTER TABLE paper ADD COLUMN cancel_requested BOOLEAN DEFAULT FALSE NOT NULL",
        "cancel_requested_at": "ALTER TABLE paper ADD COLUMN cancel_requested_at TIMESTAMP",
        "progress_current": "ALTER TABLE paper ADD COLUMN progress_current INTEGER",
        "progress_total": "ALTER TABLE paper ADD COLUMN progress_total INTEGER",
        "progress_message": "ALTER TABLE paper ADD COLUMN progress_message VARCHAR(255)",
    }

    for column_name, sql in runtime_columns.items():
        if column_name in existing_columns:
            continue
        sync_conn.execute(text(sql))

    if "question" not in table_names:
        return

    question_column_info = {column["name"]: column for column in inspector.get_columns("question")}
    question_columns = set(question_column_info)
    question_runtime_columns = {
        "question_label_raw": "ALTER TABLE question ADD COLUMN question_label_raw VARCHAR(50)",
        "section_index_raw": "ALTER TABLE question ADD COLUMN section_index_raw VARCHAR(100)",
    }

    for column_name, sql in question_runtime_columns.items():
        if column_name in question_columns:
            continue
        sync_conn.execute(text(sql))

    section_column = question_column_info.get("section_index_raw")
    section_length = getattr(section_column.get("type"), "length", None) if section_column else None
    if sync_conn.dialect.name == "postgresql" and section_length and section_length < 100:
        sync_conn.execute(text("ALTER TABLE question ALTER COLUMN section_index_raw TYPE VARCHAR(100)"))
