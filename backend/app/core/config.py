from pydantic_settings import BaseSettings
from typing import List, Optional
import os


class Settings(BaseSettings):
    """应用配置类"""

    # 应用基础配置
    APP_NAME: str = "小学数学分班考试卷六维分析系统"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1

    # 数据库配置
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/math_analysis"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "math_analysis"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # 连接池配置
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600

    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    # Celery 配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    CELERY_TASK_ALWAYS_EAGER: bool = False  # 开发环境可设为 True

    # JWT 配置
    JWT_SECRET_KEY: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # 文件上传配置
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024  # 10MB
    ALLOWED_EXTENSIONS: List[str] = ["pdf", "png", "jpg", "jpeg"]
    UPLOAD_DIR: str = "/app/uploads"
    TEMP_DIR: str = "/app/temp"

    # OCR 配置
    OCR_PROVIDER: str = "mock"  # mock, baidu, ali, tencent
    OCR_TIMEOUT: int = 30
    OCR_MAX_RETRIES: int = 3

    # 百度 OCR 配置
    BAIDU_OCR_API_KEY: Optional[str] = None
    BAIDU_OCR_SECRET_KEY: Optional[str] = None

    # 阿里 OCR 配置
    ALI_OCR_ACCESS_KEY: Optional[str] = None
    ALI_OCR_ACCESS_SECRET: Optional[str] = None

    # PDF 导出配置
    PLAYWRIGHT_BROWSER_PATH: str = "/usr/bin/chromium"
    PDF_EXPORT_TIMEOUT: int = 60

    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # json, text
    LOG_DIR: str = "/app/logs"

    # CORS 配置
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://frontend:3000"]
    CORS_ALLOW_CREDENTIALS: bool = True

    # 限流配置
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_PERIOD: int = 60  # 秒

    # Sentry 错误追踪
    SENTRY_DSN: Optional[str] = None
    SENTRY_ENVIRONMENT: str = "production"

    # 模型评分配置
    SCORING_VERSION: str = "1.0.0"
    MIN_QUESTIONS_FOR_ANALYSIS: int = 5
    MAX_QUESTIONS_FOR_DETAILED_ANALYSIS: int = 50

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "allow"


def get_settings() -> Settings:
    """获取应用配置"""
    return Settings()


# 全局配置实例
settings = get_settings()
