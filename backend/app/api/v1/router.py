from fastapi import APIRouter

from app.api.v1.endpoints import upload, analysis, papers, health

api_router = APIRouter()

# 健康检查
api_router.include_router(health.router, prefix="/health", tags=["health"])

# 文件上传
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])

# 分析报告
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])

# 试卷管理
api_router.include_router(papers.router, prefix="/papers", tags=["papers"])
