from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks
from typing import Optional
import uuid
import shutil
import os

from app.core.config import settings
from app.core.database import get_db
from app.services.upload import UploadService
from app.schemas.upload import UploadResponse, UploadStatus

router = APIRouter()


@router.post("/", response_model=UploadResponse)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    grade: Optional[str] = Form(None),
    subject: Optional[str] = Form("数学"),
):
    """
    上传试卷文件进行分析

    - **file**: 试卷文件 (PDF, PNG, JPG, JPEG)
    - **grade**: 年级 (如: 五年级)
    - **subject**: 学科 (默认: 数学)
    """
    # 生成任务ID
    task_id = str(uuid.uuid4())

    # 验证文件类型
    file_extension = file.filename.split(".")[-1].lower()
    if file_extension not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_extension}. 支持的类型: {', '.join(settings.ALLOWED_EXTENSIONS)}"
        )

    # 验证文件大小
    file_content = await file.read()
    if len(file_content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小超过限制: {len(file_content) / 1024 / 1024:.2f}MB (最大: {settings.MAX_UPLOAD_SIZE / 1024 / 1024}MB)"
        )

    # 保存文件
    upload_dir = os.path.join(settings.UPLOAD_DIR, task_id)
    os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, f"original.{file_extension}")
    with open(file_path, "wb") as f:
        f.write(file_content)

    # 异步处理分析任务
    background_tasks.add_task(
        UploadService.process_upload,
        task_id=task_id,
        file_path=file_path,
        grade=grade,
        subject=subject,
    )

    return UploadResponse(
        task_id=task_id,
        status="pending",
        message="文件上传成功，正在分析中...",
    )


@router.get("/status/{task_id}", response_model=UploadStatus)
async def get_upload_status(task_id: str):
    """
    获取上传任务的状态

    - **task_id**: 上传任务ID
    """
    # 从 Redis 或数据库获取任务状态
    status = await UploadService.get_task_status(task_id)

    if not status:
        raise HTTPException(
            status_code=404,
            detail=f"任务不存在: {task_id}"
        )

    return status
