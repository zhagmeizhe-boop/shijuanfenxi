from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models import Paper, ParseStatus as ModelParseStatus
from app.schemas import (
    AdminPaperCancelResponse,
    AdminPaperItemResponse,
    AdminPaperListResponse,
    AdminPaperSummaryResponse,
)
from app.tasks import get_celery_app

router = APIRouter()

ADMIN_CANCELLED_STAGE = "admin_cancelled"
ADMIN_CANCELLED_MESSAGE = "管理员手动终止分析"
ADMIN_CANCELLED_SOLUTION = "如需重新分析，请重新上传试卷。"
QUEUE_WAITING_FOR_ACTIVE_DISPLAY = "已有试卷在分析，正在排队等待"
QUEUE_WAITING_FOR_WORKER_DISPLAY = "已进入队列，等待 worker 接手"


STAGE_DISPLAY = {
    "queued": "已进入队列",
    "queued_waiting_for_analysis_slot": QUEUE_WAITING_FOR_ACTIVE_DISPLAY,
    "ocr_parse": "OCR/试卷题目提取",
    "question_persist": "题目信息入库",
    "llm_parse": "题目 LLM 分析",
    "report_build": "报告生成",
    "snapshot_save": "报告保存",
    ADMIN_CANCELLED_STAGE: "管理员终止",
}


@dataclass(frozen=True)
class FailureGuide:
    reason: str
    solution: str


UNKNOWN_FAILURE_GUIDE = FailureGuide(
    reason="未知异常",
    solution="请复制 paper_id，查看 api/worker 日志进一步排查；必要时重新上传试卷。",
)


FAILURE_GUIDES: list[tuple[tuple[str, ...], FailureGuide]] = [
    (
        (ADMIN_CANCELLED_STAGE, ADMIN_CANCELLED_MESSAGE),
        FailureGuide(
            ADMIN_CANCELLED_MESSAGE,
            ADMIN_CANCELLED_SOLUTION,
        ),
    ),
    (
        ("文件为空", "格式", "图片损坏", "超过限制", "页数超过", "上传文件校验失败"),
        FailureGuide(
            "上传文件不符合要求",
            "重新上传 PDF/JPG/PNG；压缩文件或拆分过大的 PDF；确认文件能在本地正常打开。",
        ),
    ),
    (
        ("permission denied", "/app/uploads", "/app/reports", "errno 13"),
        FailureGuide(
            "服务器上传/报告目录没有写入权限",
            "修复宿主机数据目录权限：chown -R 1000:1000 /opt/math-analysis-data/uploads /opt/math-analysis-data/reports，然后重启 api/worker。",
        ),
    ),
    (
        ("redis", "任务派发失败", "queue", "broker", "连接超时"),
        FailureGuide(
            "任务队列或 Redis 不可用",
            "检查 docker compose ps 中 redis 是否 healthy；重启 redis/api/worker；确认 Celery broker 指向 redis://redis:6379/0。",
        ),
    ),
    (
        ("队列已满", "等待分析", "waiting_for_analysis_slot", "空闲槽位"),
        FailureGuide(
            "分析队列已满或正在等待分析资源",
            "等待当前任务完成，不要重复上传；如果长期排队，检查 worker 是否 healthy，必要时清理失败任务或调整队列上限。",
        ),
    ),
    (
        ("all connection attempts failed", "failed to connect", "connection timeout", "connection timed out", "timeout was reached"),
        FailureGuide(
            "LLM 网关网络不可达",
            "在服务器和 worker 容器内执行 curl -I LLM_BASE_URL；确认 ECS 出口 IP 已加入 LLM 网关白名单；检查 LLM_BASE_URL 是否正确。",
        ),
    ),
    (
        ("api key", "未配置", "unauthorized", "invalid api key", "401", "认证失败"),
        FailureGuide(
            "LLM API Key 未配置或认证失败",
            "检查 .env 中 ANTHROPIC_API_KEY 或 MOONSHOT_API_KEY；确认 key 有效；修改后执行 docker compose restart api worker。",
        ),
    ),
    (
        ("429", "rate limit", "quota", "insufficient balance", "额度", "限流"),
        FailureGuide(
            "LLM 网关限流或额度不足",
            "检查 LLM 网关额度和限流策略；降低 VISION_LLM_CONCURRENCY 和 QUESTION_LLM_CONCURRENCY；稍后重试。",
        ),
    ),
    (
        ("vision llm", "页面解析", "未识别到任何题目", "json repair", "视觉大模型", "ocr"),
        FailureGuide(
            "OCR/Vision LLM 页面解析失败",
            "检查 PDF 是否清晰；减少页数；重新导出 PDF；确认 Vision LLM 可用；必要时降低 OCR 并发或提高 OCR 超时。",
        ),
    ),
    (
        ("pymupdf", "渲染 pdf", "生成页面图片", "pdf 页面", "加密"),
        FailureGuide(
            "PDF 渲染失败",
            "确认 Docker 镜像构建完整；重新执行 docker compose up -d --build；检查 PDF 是否加密、损坏或无法正常打开。",
        ),
    ),
    (
        ("题目信息保存失败", "字段长度", "题号", "栏目标题", "入库"),
        FailureGuide(
            "题目信息入库失败",
            "重新上传更规范的 PDF；如果同类文件反复失败，需要优化字段截断和入库容错。",
        ),
    ),
    (
        ("llm 阶段全部失败", "llm request timed out", "llm request failed", "llm 调用失败"),
        FailureGuide(
            "题目 LLM 分析失败",
            "检查 LLM 网关稳定性；降低题目分析并发；稍后重试；如果只是部分题失败，可保留报告并人工复核。",
        ),
    ),
    (
        ("json 解析", "json 修复失败", "json_repair_failed", "响应解析异常", "截断"),
        FailureGuide(
            "LLM 返回 JSON 解析或修复失败",
            "稍后重试；降低并发；检查模型输出是否被网关截断；必要时降低单次输出复杂度。",
        ),
    ),
    (
        ("报告生成", "report_build", "维度评分", "聚合"),
        FailureGuide(
            "报告生成失败",
            "查看该试卷是否已有题目分析结果；检查 worker 日志；必要时重新分析。",
        ),
    ),
    (
        ("snapshot_save", "报告快照", "快照保存"),
        FailureGuide(
            "报告快照保存失败",
            "检查 Postgres 是否 healthy；检查磁盘空间；重启 api/worker 后重试。",
        ),
    ),
    (
        ("pdf 生成失败", "playwright", "chromium", "render_pdf", "浏览器启动"),
        FailureGuide(
            "PDF 报告导出失败",
            "重新构建镜像；确认 Playwright Chromium 下载完整；检查服务器磁盘空间和内存。",
        ),
    ),
    (
        ("任务中断", "worker 退出", "warm shutdown", "oom", "killed"),
        FailureGuide(
            "Worker 中断或容器退出",
            "检查 docker compose ps 和 docker compose logs worker；查看服务器内存；必要时降低并发或升级服务器。",
        ),
    ),
    (
        ("数据库", "postgres", "database", "connection pool", "连接池"),
        FailureGuide(
            "数据库不可用或连接异常",
            "检查 postgres 是否 healthy；重启 postgres/api/worker；确认磁盘未满。",
        ),
    ),
    (
        ("no space left", "disk", "磁盘", "空间不足"),
        FailureGuide(
            "服务器磁盘空间不足",
            "执行 df -h 检查磁盘；清理旧上传文件和旧 Docker 镜像；正式环境扩容系统盘。",
        ),
    ),
]


def _require_admin_token(x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token")) -> None:
    expected = (settings.ADMIN_TOKEN or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="后台访问口令未配置")
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="缺少后台访问口令")
    if not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=403, detail="后台访问口令错误")


def stage_display(
    stage: Optional[str],
    parse_status: Optional[ModelParseStatus] = None,
    *,
    has_active_analysis: bool = False,
) -> str:
    if not stage:
        return "未知阶段"

    normalized_status = getattr(parse_status, "value", parse_status)
    if normalized_status == ModelParseStatus.PENDING.value:
        if stage == "queued_waiting_for_analysis_slot":
            return QUEUE_WAITING_FOR_ACTIVE_DISPLAY
        if stage == "queued" and has_active_analysis:
            return QUEUE_WAITING_FOR_ACTIVE_DISPLAY
        if stage == "queued":
            return QUEUE_WAITING_FOR_WORKER_DISPLAY

    return STAGE_DISPLAY.get(stage, stage)


def classify_failure(last_stage: Optional[str], error_message: Optional[str]) -> FailureGuide:
    text = f"{last_stage or ''} {error_message or ''}".lower()
    if not text.strip():
        return FailureGuide(
            "暂无详细错误",
            "后台暂未记录详细错误；请复制 paper_id，查看 api/worker 日志进一步排查。",
        )
    for patterns, guide in FAILURE_GUIDES:
        if any(pattern.lower() in text for pattern in patterns):
            return guide
    return UNKNOWN_FAILURE_GUIDE


def _status_filter(status: str) -> Optional[list[ModelParseStatus]]:
    normalized = status.strip().lower()
    if normalized == "failed":
        return [ModelParseStatus.PARSE_FAILED]
    if normalized == "parsing":
        return [ModelParseStatus.PENDING, ModelParseStatus.PARSING]
    if normalized == "success":
        return [ModelParseStatus.PARSE_SUCCESS]
    return None


def _can_cancel_status(status: ModelParseStatus) -> bool:
    return status in {ModelParseStatus.PENDING, ModelParseStatus.PARSING}


def _revoke_queued_task(task_id: Optional[str]) -> None:
    normalized = str(task_id or "").strip()
    if not normalized:
        return

    try:
        get_celery_app().control.revoke(normalized, terminate=False)
    except Exception:
        # Cancellation should still update the paper state even if Celery cannot revoke
        # a queued message. The worker checks cancel_requested before doing work.
        return


async def _count_statuses(db: AsyncSession) -> tuple[AdminPaperSummaryResponse, bool]:
    result = await db.execute(select(Paper.parse_status, func.count()).group_by(Paper.parse_status))
    counts: dict[str, int] = {}
    for status, count in result.all():
        key = getattr(status, "value", status)
        counts[str(key)] = int(count or 0)

    return (
        AdminPaperSummaryResponse(
            total=sum(counts.values()),
            parsing=counts.get(ModelParseStatus.PENDING.value, 0) + counts.get(ModelParseStatus.PARSING.value, 0),
            success=counts.get(ModelParseStatus.PARSE_SUCCESS.value, 0),
            failed=counts.get(ModelParseStatus.PARSE_FAILED.value, 0),
        ),
        counts.get(ModelParseStatus.PARSING.value, 0) > 0,
    )


@router.get("/papers", response_model=AdminPaperListResponse)
async def list_admin_papers(
    _: None = Depends(_require_admin_token),
    db: AsyncSession = Depends(get_db),
    status: str = Query("failed", pattern="^(failed|parsing|success|all)$"),
    keyword: str = Query("", max_length=255),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    summary, has_active_analysis = await _count_statuses(db)

    filters = []
    status_value = _status_filter(status)
    if status_value is not None:
        filters.append(Paper.parse_status.in_(status_value))

    normalized_keyword = keyword.strip()
    if normalized_keyword:
        pattern = f"%{normalized_keyword}%"
        filters.append(or_(Paper.paper_name.ilike(pattern), Paper.paper_id.ilike(pattern)))

    count_stmt = select(func.count()).select_from(Paper)
    list_stmt = select(Paper).order_by(Paper.created_at.desc())
    if filters:
        count_stmt = count_stmt.where(*filters)
        list_stmt = list_stmt.where(*filters)

    total_result = await db.execute(count_stmt)
    total = int(total_result.scalar_one() or 0)

    result = await db.execute(list_stmt.offset((page - 1) * page_size).limit(page_size))
    papers = list(result.scalars().all())

    items: list[AdminPaperItemResponse] = []
    for paper in papers:
        guide: Optional[FailureGuide] = None
        if paper.parse_status == ModelParseStatus.PARSE_FAILED:
            guide = classify_failure(paper.last_stage, paper.error_message)

        items.append(
            AdminPaperItemResponse(
                paper_id=paper.paper_id,
                paper_name=paper.paper_name,
                parse_status=paper.parse_status,
                last_stage=paper.last_stage,
                stage_display=stage_display(
                    paper.last_stage,
                    paper.parse_status,
                    has_active_analysis=has_active_analysis,
                ),
                error_message=paper.error_message,
                failure_reason_display=guide.reason if guide else None,
                failure_solution_display=guide.solution if guide else None,
                cancel_requested=bool(getattr(paper, "cancel_requested", False)),
                cancel_requested_at=getattr(paper, "cancel_requested_at", None),
                can_cancel=_can_cancel_status(paper.parse_status),
                total_question_count=paper.total_question_count or 0,
                created_at=paper.created_at,
                updated_at=paper.updated_at,
            )
        )

    return AdminPaperListResponse(
        summary=summary,
        items=items,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/papers/{paper_id}/cancel", response_model=AdminPaperCancelResponse)
async def cancel_admin_paper(
    paper_id: str,
    _: None = Depends(_require_admin_token),
    db: AsyncSession = Depends(get_db),
):
    paper = await db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")

    if not _can_cancel_status(paper.parse_status):
        raise HTTPException(status_code=409, detail="当前试卷已结束，不能终止分析")

    now = datetime.utcnow()
    paper.cancel_requested = True
    paper.cancel_requested_at = now

    _revoke_queued_task(getattr(paper, "analysis_task_id", None))

    if paper.parse_status == ModelParseStatus.PENDING:
        paper.parse_status = ModelParseStatus.PARSE_FAILED
        paper.last_stage = ADMIN_CANCELLED_STAGE
        paper.error_message = ADMIN_CANCELLED_MESSAGE
        paper.progress_current = None
        paper.progress_total = None
        paper.progress_message = None
        message = "已终止排队中的分析任务"
    else:
        paper.progress_message = "管理员已请求终止，等待当前阶段安全退出"
        message = "已请求终止分析，当前阶段结束后会安全退出"

    await db.commit()
    await db.refresh(paper)

    return AdminPaperCancelResponse(
        paper_id=paper.paper_id,
        parse_status=paper.parse_status,
        cancel_requested=bool(paper.cancel_requested),
        message=message,
    )
