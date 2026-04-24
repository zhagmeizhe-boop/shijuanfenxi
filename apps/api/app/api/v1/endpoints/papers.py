from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models import Paper, ParseStatus as ModelParseStatus
from app.schemas import (
    PaperAnalyzeResponse,
    PaperStatusResponse,
    ParseStatus as SchemaParseStatus,
    ParsedPaperResponse,
)
from app.services.ocr.factory import OCRProviderFactory
from app.services.ocr.mock_provider import MockOCRProvider
from app.tasks import describe_queue_dispatch_error, enqueue_paper_analysis_task, get_queue_preflight_status

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_ROOT = Path(settings.UPLOAD_DIR)
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


def _get_ocr_provider():
    try:
        return OCRProviderFactory.create_provider(
            provider_name=settings.OCR_PROVIDER,
            config={
                "app_id": settings.BAIDU_OCR_APP_ID,
                "api_key": settings.BAIDU_OCR_API_KEY,
                "secret_key": settings.BAIDU_OCR_SECRET_KEY,
                "poppler_path": settings.POPPLER_PATH,
            }
            if settings.OCR_PROVIDER == "baidu"
            else {},
        )
    except Exception as exc:
        logger.warning("创建 OCR Provider 失败，降级为 MockProvider: %s", exc)
        return MockOCRProvider()


ocr_provider = _get_ocr_provider()


def _default_paper_name(grade: Optional[str]) -> str:
    grade_label = grade or "未知年级"
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{grade_label}数学试卷 {timestamp}"


def _describe_enqueue_error(exc: Exception) -> str:
    return f"任务派发失败：{describe_queue_dispatch_error(exc)}"


@router.post(
    "/analyze",
    response_model=PaperAnalyzeResponse,
    summary="分析试卷",
    description="上传试卷文件（PDF/图片）并创建后台分析任务",
)
async def analyze_paper(
    file: UploadFile = File(..., description="试卷文件（PDF/JPG/PNG）"),
    paper_name: Optional[str] = Form(None, description="试卷名称"),
    grade: Optional[str] = Form(None, description="年级"),
    subject: str = Form("数学", description="学科"),
    source: Optional[str] = Form(None, description="来源"),
    db: AsyncSession = Depends(get_db),
):
    del subject, source

    original_filename = file.filename or "upload.pdf"
    file_extension = Path(original_filename).suffix.lower()
    if file_extension not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式：{file_extension}。支持格式：{', '.join(settings.ALLOWED_EXTENSIONS)}",
        )

    file_content = await file.read()
    validation = ocr_provider.validate_upload(
        file_path=original_filename,
        file_size=len(file_content),
        file_extension=file_extension,
        is_pdf=file_extension == ".pdf",
    )
    if not validation.is_valid:
        raise HTTPException(status_code=400, detail=validation.error_message)

    paper_id = str(uuid.uuid4())
    upload_dir = UPLOAD_ROOT / paper_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = (upload_dir / f"original{file_extension}").resolve()
    file_path.write_bytes(file_content)

    db_paper = Paper(
        paper_id=paper_id,
        paper_name=paper_name or _default_paper_name(grade),
        source_file_url=str(file_path),
        file_type=file_extension.lstrip("."),
        page_count=0,
        total_question_count=0,
        total_score=0.0,
        parse_status=ModelParseStatus.PENDING,
        parse_confidence=0.0,
        need_manual_review=False,
        last_stage="upload_saved",
        error_message=None,
    )
    db.add(db_paper)
    await db.commit()
    await db.refresh(db_paper)

    queue_status = get_queue_preflight_status()
    if not queue_status["queue_ready"]:
        error_message = f"任务派发失败：{queue_status['message']}"
        db_paper.parse_status = ModelParseStatus.PARSE_FAILED
        db_paper.error_message = error_message
        await db.commit()
        logger.error(
            "试卷分析任务预检失败 paper=%s broker=%s backend=%s detail=%s",
            paper_id,
            queue_status["broker_url"],
            queue_status["backend_url"],
            error_message,
        )
        raise HTTPException(status_code=503, detail=error_message)

    try:
        task_id = enqueue_paper_analysis_task(paper_id=paper_id, file_path=str(file_path))
        logger.info(
            "试卷分析任务已派发 paper=%s task_id=%s broker=%s backend=%s",
            paper_id,
            task_id,
            queue_status["broker_url"],
            queue_status["backend_url"],
        )
    except Exception as exc:
        error_message = _describe_enqueue_error(exc)
        db_paper.parse_status = ModelParseStatus.PARSE_FAILED
        db_paper.error_message = error_message
        await db.commit()
        logger.error(
            "试卷分析任务派发失败 paper=%s stage=send_task broker=%s backend=%s detail=%s",
            paper_id,
            queue_status["broker_url"],
            queue_status["backend_url"],
            error_message,
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail=error_message) from exc

    return PaperAnalyzeResponse(
        paper_id=paper_id,
        parse_status=SchemaParseStatus.PENDING,
        message="试卷上传成功，已进入分析队列",
        estimated_seconds=120,
    )


@router.get(
    "/{paper_id}/status",
    response_model=PaperStatusResponse,
    summary="查询试卷分析状态",
    description="根据试卷 ID 查询当前分析进度和状态",
)
async def get_paper_status(
    paper_id: str,
    db: AsyncSession = Depends(get_db),
):
    paper = await db.get(Paper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")

    return PaperStatusResponse(
        paper_id=paper_id,
        parse_status=paper.parse_status,
        parse_confidence=paper.parse_confidence,
        need_manual_review=paper.need_manual_review,
        total_question_count=paper.total_question_count,
        total_score=paper.total_score,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
        last_stage=paper.last_stage,
        error_message=paper.error_message,
    )


@router.get(
    "/{paper_id}/result",
    response_model=ParsedPaperResponse,
    summary="获取试卷解析结果",
    description="获取完整的试卷解析结果（当前仍使用 Mock 返回）",
)
async def get_paper_result(paper_id: str):
    mock_file_path = f"/tmp/mock_{paper_id}.pdf"
    parsed_paper = await ocr_provider.parse(
        file_path=mock_file_path,
        paper_name="2024年小学五年级数学分班考试",
        paper_id=paper_id,
        page_count=6,
    )

    return ParsedPaperResponse(
        paper_id=paper_id,
        paper_name=parsed_paper.paper_name,
        total_question_count=parsed_paper.total_question_count,
        total_score=parsed_paper.total_score,
        page_count=parsed_paper.page_count,
        parse_status=parsed_paper.parse_status,
        parse_confidence=parsed_paper.parse_confidence,
        need_manual_review=parsed_paper.need_manual_review,
        questions=[
            {
                "question_no": question.question_no,
                "question_label_raw": getattr(question, "question_label_raw", "") or "",
                "section_index_raw": getattr(question, "section_index_raw", "") or "",
                "question_type": question.question_type,
                "raw_text": question.raw_text,
                "score": question.score,
                "is_optional": question.is_optional,
                "include_in_main_score": question.include_in_main_score,
                "parse_confidence": question.parse_confidence,
                "applicable_dims": question.applicable_dims,
                "page_no": question.page_no,
                "image_block_url": question.image_block_url,
                "block_bbox": question.block_bbox,
                "question_block": question.question_block.to_dict() if question.question_block else None,
                "parse_warnings": question.parse_warnings,
                "parse_audit": question.parse_audit.to_dict() if question.parse_audit else None,
                "ocr_text_version": question.ocr_text_version,
                "sub_questions": [
                    {
                        "question_no": sub.question_no,
                        "raw_text": sub.raw_text,
                        "score": sub.score,
                        "is_optional": sub.is_optional,
                    }
                    for sub in question.sub_questions
                ],
                "sub_item_candidates": [candidate.to_dict() for candidate in question.sub_item_candidates],
            }
            for question in parsed_paper.questions
        ],
        file_type=parsed_paper.file_type,
        source_file_url=parsed_paper.source_file_url,
        created_at=datetime.now(),
    )
