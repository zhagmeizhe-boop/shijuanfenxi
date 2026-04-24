from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import time

from app.core.config import settings
from app.core.database import init_db, close_db, check_db_health
from app.api.v1.router import api_router

# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理

    - 启动时：初始化数据库连接、创建表
    - 关闭时：清理资源
    """
    logger.info("Starting up application...")

    # 初始化数据库
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        # 不阻止应用启动，但记录错误

    yield

    # 清理资源
    logger.info("Shutting down application...")
    await close_db()
    logger.info("Application shutdown complete")


# 创建 FastAPI 应用
def create_application() -> FastAPI:
    """创建并配置 FastAPI 应用"""

    app = FastAPI(
        title=settings.APP_NAME,
        description="小学数学分班考试卷六维分析系统 API",
        version=settings.APP_VERSION,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # 配置 CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(api_router, prefix="/api")

    # 添加中间件
    register_middlewares(app)

    # 注册异常处理器
    register_exception_handlers(app)

    return app


def register_middlewares(app: FastAPI) -> None:
    """注册中间件"""

    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        """添加处理时间头部"""
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        return response

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        """添加请求 ID"""
        import uuid
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def register_exception_handlers(app: FastAPI) -> None:
    """注册异常处理器"""

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """全局异常处理器"""
        logger.error(f"Global exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": 500,
                "message": "Internal server error",
                "detail": str(exc) if settings.DEBUG else None,
            },
        )


# 创建应用实例
app = create_application()


@app.get("/health")
async def health_check():
    """健康检查端点"""
    db_health = await check_db_health()

    return {
        "status": "healthy" if db_health["status"] == "healthy" else "degraded",
        "version": settings.APP_VERSION,
        "database": db_health,
        "timestamp": time.time(),
    }


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=settings.WORKERS if not settings.DEBUG else 1,
    )
