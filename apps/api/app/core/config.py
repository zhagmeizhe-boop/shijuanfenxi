from typing import List, Optional
import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings

from app.core.path_utils import normalize_database_url, resolve_runtime_path


class Settings(BaseSettings):
    """应用配置"""

    # 应用信息
    APP_NAME: str = "数学试卷六维分析系统"
    APP_VERSION: str = "0.1.0"
    APP_DESCRIPTION: str = "小学数学分班考试卷六维分析系统 API"

    # 环境配置
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # 服务器配置
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_WORKERS: int = 1

    # 安全配置
    SECRET_KEY: str = Field(default="your-secret-key-change-this-in-production")
    JWT_SECRET_KEY: str = Field(default="your-jwt-secret-key-change-this")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # 数据库配置 - 开发环境使用 SQLite
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./math_analysis.db"
    )
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "math_analysis"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # 数据库连接池
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 3600

    # Redis配置
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    # Celery配置
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    CELERY_TASK_ALWAYS_EAGER: bool = False
    TASK_STALE_MINUTES: int = 15

    # OCR配置
    OCR_PROVIDER: str = "mock"  # mock, baidu, ali
    OCR_TIMEOUT: int = 30
    OCR_MAX_RETRIES: int = 3

    # 百度OCR
    BAIDU_OCR_APP_ID: Optional[str] = None
    BAIDU_OCR_API_KEY: Optional[str] = None
    BAIDU_OCR_SECRET_KEY: Optional[str] = None
    POPPLER_PATH: Optional[str] = None  # Windows 下 poppler bin 目录路径

    # 阿里OCR
    ALI_OCR_ACCESS_KEY: Optional[str] = None
    ALI_OCR_ACCESS_SECRET: Optional[str] = None

    # LLM 配置
    LLM_PROVIDER: str = "claude"  # claude, moonshot, openai
    LLM_BASE_URL: str = "https://one-api.aixuexi.com/v1"
    ANTHROPIC_API_KEY: Optional[str] = None
    CLAUDE_MODEL: str = "claude-sonnet-4-5"
    CLAUDE_TEMPERATURE: float = 0.3
    CLAUDE_MAX_TOKENS: int = 2000
    CLAUDE_TIMEOUT: float = 60.0
    # Moonshot (保留兼容)
    MOONSHOT_API_KEY: Optional[str] = None
    MOONSHOT_MODEL: str = "moonshot-v1-8k"
    MOONSHOT_TEMPERATURE: float = 0.3
    MOONSHOT_MAX_TOKENS: int = 2000
    MOONSHOT_TIMEOUT: float = 30.0

    # 文件上传配置
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50MB
    MAX_PDF_PAGES: int = 30
    MAX_IMAGE_COUNT: int = 20
    SINGLE_IMAGE_MAX_SIZE: int = 10 * 1024 * 1024  # 10MB
    ALLOWED_EXTENSIONS: List[str] = [".pdf", ".jpg", ".jpeg", ".png"]
    UPLOAD_DIR: str = "./uploads"
    REPORT_OUTPUT_DIR: str = "./reports"

    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    # CORS配置
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    CORS_ALLOW_CREDENTIALS: bool = True

    class Config:
        env_file = [".env", "../../.env"]
        case_sensitive = True
        extra = "allow"


@lru_cache()
def get_settings() -> Settings:
    """获取配置（缓存）"""
    loaded = Settings()
    loaded.DATABASE_URL = normalize_database_url(loaded.DATABASE_URL)
    loaded.UPLOAD_DIR = str(resolve_runtime_path(loaded.UPLOAD_DIR))
    loaded.REPORT_OUTPUT_DIR = str(resolve_runtime_path(loaded.REPORT_OUTPUT_DIR))
    return loaded


# 全局配置实例
settings = get_settings()
