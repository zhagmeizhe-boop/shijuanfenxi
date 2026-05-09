from __future__ import annotations

import io
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
from sqlalchemy import func, select
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
from app.services.ocr.base import IMAGE_MANIFEST_KIND
from app.services.ocr.factory import create_ocr_provider, get_ocr_preflight_status
from app.services.ocr.mock_provider import MockOCRProvider
from app.tasks import describe_queue_dispatch_error, enqueue_paper_analysis_task, get_queue_preflight_status

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_ROOT = Path(settings.UPLOAD_DIR)
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

PDF_EXTENSION = ".pdf"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MANIFEST_FILENAME = "input_manifest.json"


@dataclass(frozen=True)
class UploadedFilePayload:
    original_filename: str
    file_extension: str
    content_type: str
    content: bytes

    @property
    def size(self) -> int:
        return len(self.content)


@dataclass(frozen=True)
class AnalysisInput:
    path: Path
    source_file_url: str
    file_type: str
    page_count_hint: int


def _get_ocr_provider():
    return create_ocr_provider()


def _default_paper_name(grade: Optional[str]) -> str:
    grade_label = grade or "未知年级"
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{grade_label}数学试卷 {timestamp}"


def _describe_enqueue_error(exc: Exception) -> str:
    return f"任务派发失败：{describe_queue_dispatch_error(exc)}"


async def _queued_analysis_task_count(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Paper)
        .where(Paper.parse_status.in_([ModelParseStatus.PENDING, ModelParseStatus.PARSING]))
    )
    return int(result.scalar_one() or 0)


async def _enforce_analysis_queue_capacity(db: AsyncSession) -> None:
    max_queued = int(settings.MAX_QUEUED_ANALYSIS_TASKS or 0)
    if max_queued <= 0:
        return

    queued_count = await _queued_analysis_task_count(db)
    if queued_count < max_queued:
        return

    raise HTTPException(
        status_code=429,
        detail=(
            f"当前分析队列已满（{queued_count}/{max_queued}），请稍后再上传。"
            "系统会继续处理已入队任务，此限制用于保护 OCR/LLM 配额和服务器稳定性。"
        ),
    )


async def _enforce_analysis_capacity(db: AsyncSession) -> None:
    await _enforce_analysis_queue_capacity(db)


def _display_size(size: int) -> str:
    return f"{size / 1024 / 1024:.2f}MB"


def _safe_filename(filename: Optional[str], fallback: str) -> str:
    normalized = Path(str(filename or "").strip()).name
    return normalized or fallback


async def _read_upload_payload(upload: UploadFile, fallback_filename: str) -> UploadedFilePayload:
    filename = _safe_filename(upload.filename, fallback_filename)
    file_extension = Path(filename).suffix.lower()
    content = await upload.read()
    return UploadedFilePayload(
        original_filename=filename,
        file_extension=file_extension,
        content_type=upload.content_type or "",
        content=content,
    )


def _is_image_extension(file_extension: str) -> bool:
    return file_extension.lower() in IMAGE_EXTENSIONS


def _raise_bad_upload(detail: str) -> None:
    raise HTTPException(status_code=400, detail=detail)


def _verify_non_empty(payload: UploadedFilePayload) -> None:
    if payload.size <= 0:
        _raise_bad_upload(f"上传文件为空：{payload.original_filename}")


def _verify_image_content(payload: UploadedFilePayload) -> None:
    try:
        with Image.open(io.BytesIO(payload.content)) as image:
            image.verify()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"图片文件无法打开或已损坏：{payload.original_filename}",
        ) from exc


def _validate_upload_payload(payload: UploadedFilePayload, ocr_provider, *, require_image: bool) -> None:
    _verify_non_empty(payload)

    if payload.file_extension not in settings.ALLOWED_EXTENSIONS:
        _raise_bad_upload(
            f"不支持的文件格式：{payload.file_extension}。支持格式：{', '.join(settings.ALLOWED_EXTENSIONS)}"
        )

    is_pdf = payload.file_extension == PDF_EXTENSION
    if require_image and is_pdf:
        _raise_bad_upload("多图片上传只支持 JPG/JPEG/PNG，不支持 PDF。")
    if require_image and not _is_image_extension(payload.file_extension):
        _raise_bad_upload("多图片上传只支持 JPG/JPEG/PNG。")

    validation = ocr_provider.validate_upload(
        file_path=payload.original_filename,
        file_size=payload.size,
        file_extension=payload.file_extension,
        is_pdf=is_pdf,
    )
    if not validation.is_valid:
        _raise_bad_upload(validation.error_message or "上传文件校验失败")

    if _is_image_extension(payload.file_extension):
        _verify_image_content(payload)


def _validate_total_upload_size(payloads: List[UploadedFilePayload]) -> None:
    total_size = sum(payload.size for payload in payloads)
    if total_size > settings.MAX_UPLOAD_SIZE:
        _raise_bad_upload(
            f"上传文件总大小超过限制：{_display_size(total_size)} (最大: {_display_size(settings.MAX_UPLOAD_SIZE)})"
        )


def _write_multi_image_manifest(upload_dir: Path, payloads: List[UploadedFilePayload]) -> AnalysisInput:
    source_dir = upload_dir / "source_images"
    source_dir.mkdir(parents=True, exist_ok=True)

    pages = []
    for index, payload in enumerate(payloads, start=1):
        stored_filename = f"page_{index:03d}{payload.file_extension}"
        stored_path = (source_dir / stored_filename).resolve()
        stored_path.write_bytes(payload.content)
        pages.append(
            {
                "page_no": index,
                "original_filename": payload.original_filename,
                "stored_filename": stored_filename,
                "path": str(stored_path),
                "content_type": payload.content_type,
                "size": payload.size,
                "extension": payload.file_extension,
            }
        )

    manifest_path = (upload_dir / MANIFEST_FILENAME).resolve()
    manifest = {
        "kind": IMAGE_MANIFEST_KIND,
        "version": 1,
        "pages": pages,
        "total_size": sum(payload.size for payload in payloads),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return AnalysisInput(
        path=manifest_path,
        source_file_url=str(manifest_path),
        file_type="images",
        page_count_hint=len(payloads),
    )


async def _prepare_analysis_input(
    *,
    upload_dir: Path,
    ocr_provider,
    file: Optional[UploadFile],
    files: Optional[List[UploadFile]],
) -> AnalysisInput:
    multi_uploads = [item for item in (files or []) if item and item.filename]
    has_single_file = bool(file and file.filename)

    if has_single_file and multi_uploads:
        _raise_bad_upload("请使用 file 上传单个 PDF/图片，或使用 files 上传多张图片，不能同时使用。")
    if not has_single_file and not multi_uploads:
        _raise_bad_upload("请上传 PDF 或 JPG/PNG 图片。")

    if has_single_file and file is not None:
        payload = await _read_upload_payload(file, "upload.pdf")
        _validate_upload_payload(payload, ocr_provider, require_image=False)
        _validate_total_upload_size([payload])

        file_path = (upload_dir / f"original{payload.file_extension}").resolve()
        file_path.write_bytes(payload.content)
        return AnalysisInput(
            path=file_path,
            source_file_url=str(file_path),
            file_type=payload.file_extension.lstrip("."),
            page_count_hint=1 if _is_image_extension(payload.file_extension) else 0,
        )

    payloads = [
        await _read_upload_payload(upload, f"page_{index:03d}.jpg")
        for index, upload in enumerate(multi_uploads, start=1)
    ]
    image_count_validation = ocr_provider.validate_image_count(len(payloads))
    if not image_count_validation.is_valid:
        _raise_bad_upload(image_count_validation.error_message or "图片数量超过限制")

    for payload in payloads:
        _validate_upload_payload(payload, ocr_provider, require_image=True)
    _validate_total_upload_size(payloads)

    return _write_multi_image_manifest(upload_dir, payloads)


@router.post(
    "/analyze",
    response_model=PaperAnalyzeResponse,
    summary="分析试卷",
    description="上传试卷文件（PDF/图片）并创建后台分析任务",
)
async def analyze_paper(
    file: Optional[UploadFile] = File(None, description="单个试卷文件（PDF/JPG/PNG）"),
    files: Optional[List[UploadFile]] = File(None, description="多张试卷图片（JPG/PNG，按页序重复提交）"),
    paper_name: Optional[str] = Form(None, description="试卷名称"),
    grade: Optional[str] = Form(None, description="年级"),
    subject: str = Form("数学", description="学科"),
    source: Optional[str] = Form(None, description="来源"),
    db: AsyncSession = Depends(get_db),
):
    del subject, source

    try:
        ocr_provider = _get_ocr_provider()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"OCR provider 初始化失败: {exc}") from exc

    await _enforce_analysis_queue_capacity(db)

    paper_id = str(uuid.uuid4())
    upload_dir = UPLOAD_ROOT / paper_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    analysis_input = await _prepare_analysis_input(
        upload_dir=upload_dir,
        ocr_provider=ocr_provider,
        file=file,
        files=files,
    )

    db_paper = Paper(
        paper_id=paper_id,
        paper_name=paper_name or _default_paper_name(grade),
        source_file_url=analysis_input.source_file_url,
        file_type=analysis_input.file_type,
        page_count=analysis_input.page_count_hint,
        total_question_count=0,
        total_score=0.0,
        parse_status=ModelParseStatus.PENDING,
        parse_confidence=0.0,
        need_manual_review=False,
        last_stage="queued",
        error_message=None,
        progress_message="已进入分析队列，等待 worker 处理",
    )
    db.add(db_paper)
    await db.commit()
    await db.refresh(db_paper)

    ocr_status = await get_ocr_preflight_status()
    if not ocr_status["ocr_ready"]:
        error_message = f"OCR 不可用：{ocr_status['message']}"
        db_paper.parse_status = ModelParseStatus.PARSE_FAILED
        db_paper.error_message = error_message
        await db.commit()
        logger.error(
            "Paper OCR preflight failed paper=%s provider=%s detail=%s",
            paper_id,
            ocr_status["provider"],
            error_message,
        )
        raise HTTPException(status_code=503, detail=error_message)

    queue_status = get_queue_preflight_status()
    if not queue_status["queue_ready"]:
        error_message = f"任务派发失败：{queue_status['message']}"
        db_paper.parse_status = ModelParseStatus.PARSE_FAILED
        db_paper.error_message = error_message
        await db.commit()
        logger.error(
            "Paper analysis queue preflight failed paper=%s provider=%s broker=%s backend=%s detail=%s",
            paper_id,
            settings.OCR_PROVIDER,
            queue_status["broker_url"],
            queue_status["backend_url"],
            error_message,
        )
        raise HTTPException(status_code=503, detail=error_message)

    try:
        task_id = enqueue_paper_analysis_task(paper_id=paper_id, file_path=str(analysis_input.path))
        logger.info(
            "Paper analysis task enqueued paper=%s task_id=%s ocr=%s broker=%s backend=%s",
            paper_id,
            task_id,
            settings.OCR_PROVIDER,
            queue_status["broker_url"],
            queue_status["backend_url"],
        )
    except Exception as exc:
        error_message = _describe_enqueue_error(exc)
        db_paper.parse_status = ModelParseStatus.PARSE_FAILED
        db_paper.error_message = error_message
        await db.commit()
        logger.error(
            "Paper analysis task enqueue failed paper=%s ocr=%s broker=%s backend=%s detail=%s",
            paper_id,
            settings.OCR_PROVIDER,
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
        progress_current=paper.progress_current,
        progress_total=paper.progress_total,
        progress_message=paper.progress_message,
    )


@router.get(
    "/{paper_id}/result",
    response_model=ParsedPaperResponse,
    summary="获取试卷解析结果",
    description="返回一个 mock 解析结果，用于开发调试。",
)
async def get_paper_result(paper_id: str):
    parsed_paper = await MockOCRProvider().parse(
        file_path=f"/tmp/mock_{paper_id}.pdf",
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
        report_warnings=parsed_paper.report_warnings,
        question_count_audits=[audit.to_dict() for audit in parsed_paper.question_count_audits],
        created_at=datetime.now(),
    )
