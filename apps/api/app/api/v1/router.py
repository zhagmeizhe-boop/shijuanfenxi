from fastapi import APIRouter

from app.api.v1.endpoints import papers, report

api_router = APIRouter()

# 试卷相关接口
api_router.include_router(papers.router, prefix="/papers", tags=["papers"])

# 报告相关接口
api_router.include_router(report.router, prefix="/reports", tags=["reports"])
