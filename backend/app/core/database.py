from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from typing import AsyncGenerator
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# 创建异步引擎
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    echo=settings.DEBUG,  # 仅在调试模式下打印 SQL
    future=True,
)

# 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# 声明基类
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    获取数据库会话的依赖函数

    使用方式:
        @app.get("/items")
        async def read_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database transaction failed: {e}")
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    初始化数据库，创建所有表
    仅在开发环境或首次部署时使用
    """
    async with engine.begin() as conn:
        # 仅在 DEBUG 模式下删除所有表（危险操作）
        if settings.DEBUG and settings.ENVIRONMENT == "development":
            logger.warning("Dropping all tables (DEBUG mode only)")
            await conn.run_sync(Base.metadata.drop_all)

        logger.info("Creating all tables...")
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized successfully")


async def close_db() -> None:
    """关闭数据库连接"""
    await engine.dispose()
    logger.info("Database connections closed")


# 数据库健康检查
async def check_db_health() -> dict:
    """
    检查数据库健康状态

    Returns:
        dict: 包含健康状态、响应时间等信息
    """
    import time

    start_time = time.time()
    try:
        async with AsyncSessionLocal() as session:
            # 执行一个简单的查询
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))

        response_time = (time.time() - start_time) * 1000  # 转换为毫秒

        return {
            "status": "healthy",
            "response_time_ms": round(response_time, 2),
            "message": "Database connection is healthy",
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "response_time_ms": None,
            "message": f"Database connection failed: {str(e)}",
        }
