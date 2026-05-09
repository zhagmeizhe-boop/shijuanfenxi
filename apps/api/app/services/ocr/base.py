import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

IMAGE_MANIFEST_KIND = "image_pages"


class ParseStatus(str, Enum):
    """解析状态"""
    PENDING = "pending"
    PARSING = "parsing"
    PARSE_SUCCESS = "parse_success"
    PARSE_RISK = "parse_risk"
    NEED_REUPLOAD = "need_reupload"
    NEED_MANUAL_REVIEW = "need_manual_review"


class QuestionType(str, Enum):
    """题目类型"""
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    FILL_BLANK = "fill_blank"
    CALCULATION = "calculation"
    SOLUTION = "solution"
    APPLICATION = "application"
    COMPREHENSIVE = "comprehensive"
    OPEN_ENDED = "open_ended"


class DimensionCode(str, Enum):
    """六维代码"""
    COMPUTATION = "dim1"
    CONCEPT = "dim2"
    LOGIC = "dim3"
    SPATIAL = "dim4"
    APPLICATION = "dim5"
    INNOVATION = "dim6"


@dataclass
class SubQuestion:
    """子题目"""
    question_no: str  # 子题号，如 "a", "b", "1)", "2)"
    raw_text: str
    question_label_raw: str = ""
    score: float = 0.0
    is_optional: bool = False


@dataclass
class QuestionBlock:
    """OCR 题块定位信息。"""

    page_no: int
    bbox: Dict[str, int]
    line_count: int = 0
    text_density: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_no": self.page_no,
            "bbox": self.bbox,
            "line_count": self.line_count,
            "text_density": self.text_density,
        }


@dataclass
class SubItemCandidate:
    """大题内部小问候选块，仅用于分析辅助，不改变对外题数口径。"""

    candidate_no: str
    raw_text: str
    confidence: float = 0.0
    reason: str = ""
    bbox: Optional[Dict[str, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_no": self.candidate_no,
            "raw_text": self.raw_text,
            "confidence": self.confidence,
            "reason": self.reason,
            "bbox": self.bbox,
        }


@dataclass
class ParseAudit:
    """题级 OCR 解析审计信息。"""

    anchor_confidence: float = 0.0
    score_confidence: float = 0.0
    block_completeness: float = 0.0
    cross_page_merged: bool = False
    image_cropped: bool = False
    image_required_hint: bool = False
    image_attach_recommended: bool = False
    image_strategy: str = "text_only"
    visual_category: str = "none"
    visual_reason: str = ""
    score_source: str = "unknown"
    score_reason: str = ""
    formula_enhanced: bool = False
    formula_strategy: str = "text_only"
    line_count: int = 0
    warning_codes: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "anchor_confidence": self.anchor_confidence,
            "score_confidence": self.score_confidence,
            "block_completeness": self.block_completeness,
            "cross_page_merged": self.cross_page_merged,
            "image_cropped": self.image_cropped,
            "image_required_hint": self.image_required_hint,
            "image_attach_recommended": self.image_attach_recommended,
            "image_strategy": self.image_strategy,
            "visual_category": self.visual_category,
            "visual_reason": self.visual_reason,
            "score_source": self.score_source,
            "score_reason": self.score_reason,
            "formula_enhanced": self.formula_enhanced,
            "formula_strategy": self.formula_strategy,
            "line_count": self.line_count,
            "warning_codes": self.warning_codes,
            "notes": self.notes,
        }


@dataclass
class QuestionCountAudit:
    """Question-count audit information for OCR parsing."""

    page_no: int
    zone_key: str
    section_index_raw: str = ""
    detected_count: int = 0
    declared_count: Optional[int] = None
    anchor_numbers: List[str] = field(default_factory=list)
    missing_numbers: List[str] = field(default_factory=list)
    duplicate_numbers: List[str] = field(default_factory=list)
    secondary_pass_used: bool = False
    mismatch_reason: str = ""
    layout_type: str = "single_column"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_no": self.page_no,
            "zone_key": self.zone_key,
            "section_index_raw": self.section_index_raw,
            "detected_count": self.detected_count,
            "declared_count": self.declared_count,
            "anchor_numbers": self.anchor_numbers,
            "missing_numbers": self.missing_numbers,
            "duplicate_numbers": self.duplicate_numbers,
            "secondary_pass_used": self.secondary_pass_used,
            "mismatch_reason": self.mismatch_reason,
            "layout_type": self.layout_type,
        }


@dataclass
class ParsedQuestion:
    """解析后的题目"""
    question_no: str  # 题号，如 "1", "2", "3a"
    question_type: QuestionType
    raw_text: str
    question_label_raw: str = ""
    section_index_raw: str = ""
    score: float = 0.0
    is_optional: bool = False
    include_in_main_score: bool = True
    parse_confidence: float = 0.0
    applicable_dims: List[DimensionCode] = field(default_factory=list)
    page_no: int = 1
    image_block_url: Optional[str] = None
    block_bbox: Optional[Dict[str, int]] = None
    question_block: Optional[QuestionBlock] = None
    parse_warnings: List[str] = field(default_factory=list)
    parse_audit: Optional[ParseAudit] = None
    ocr_text_version: str = "v1.0"
    sub_questions: List[SubQuestion] = field(default_factory=list)
    sub_item_candidates: List[SubItemCandidate] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "question_no": self.question_no,
            "question_label_raw": self.question_label_raw,
            "section_index_raw": self.section_index_raw,
            "question_type": self.question_type.value,
            "raw_text": self.raw_text,
            "score": self.score,
            "is_optional": self.is_optional,
            "include_in_main_score": self.include_in_main_score,
            "parse_confidence": self.parse_confidence,
            "applicable_dims": [d.value for d in self.applicable_dims],
            "page_no": self.page_no,
            "image_block_url": self.image_block_url,
            "block_bbox": self.block_bbox,
            "question_block": self.question_block.to_dict() if self.question_block else None,
            "parse_warnings": self.parse_warnings,
            "parse_audit": self.parse_audit.to_dict() if self.parse_audit else None,
            "ocr_text_version": self.ocr_text_version,
            "sub_questions": [
                {
                    "question_no": sq.question_no,
                    "raw_text": sq.raw_text,
                    "score": sq.score,
                    "is_optional": sq.is_optional,
                }
                for sq in self.sub_questions
            ],
            "sub_item_candidates": [candidate.to_dict() for candidate in self.sub_item_candidates],
        }


@dataclass
class ParsedPaper:
    """解析后的试卷"""
    paper_name: str
    total_question_count: int
    total_score: float
    page_count: int
    parse_status: ParseStatus
    parse_confidence: float
    need_manual_review: bool
    questions: List[ParsedQuestion]
    file_type: str
    source_file_url: str
    report_warnings: List[str] = field(default_factory=list)
    question_count_audits: List[QuestionCountAudit] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "paper_name": self.paper_name,
            "total_question_count": self.total_question_count,
            "total_score": self.total_score,
            "page_count": self.page_count,
            "parse_status": self.parse_status.value,
            "parse_confidence": self.parse_confidence,
            "need_manual_review": self.need_manual_review,
            "questions": [q.to_dict() for q in self.questions],
            "file_type": self.file_type,
            "source_file_url": self.source_file_url,
            "report_warnings": self.report_warnings,
            "question_count_audits": [audit.to_dict() for audit in self.question_count_audits],
        }


@dataclass
class OCRUploadConfig:
    """OCR上传配置"""
    max_file_size: int = 50 * 1024 * 1024  # 50MB
    max_pdf_pages: int = 30
    max_image_count: int = 20
    single_image_max_size: int = 10 * 1024 * 1024  # 10MB
    allowed_pdf_extensions: List[str] = field(default_factory=lambda: [".pdf"])
    allowed_image_extensions: List[str] = field(default_factory=lambda: [".jpg", ".jpeg", ".png"])


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    error_message: Optional[str] = None
    parsed_data: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ImageManifestPage:
    """One user-ordered image page from a multi-image upload manifest."""

    page_no: int
    path: str
    original_filename: str = ""
    content_type: str = ""
    size: int = 0


class BaseOCRProvider(ABC):
    """
    OCR Provider 抽象基类

    所有 OCR 实现都需要继承此类，实现统一的接口
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self.upload_config = OCRUploadConfig()

    @abstractmethod
    async def parse(self, file_path: str, **kwargs) -> ParsedPaper:
        """
        解析试卷文件

        Args:
            file_path: 文件路径
            **kwargs: 额外的解析参数

        Returns:
            ParsedPaper: 解析后的试卷数据
        """
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        健康检查

        Returns:
            dict: 健康状态
        """
        pass

    @classmethod
    def is_image_manifest_path(cls, file_path: str) -> bool:
        """Return True when file_path points to a multi-image upload manifest."""
        path = Path(file_path)
        if path.suffix.lower() != ".json":
            return False

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False

        return isinstance(payload, dict) and payload.get("kind") == IMAGE_MANIFEST_KIND

    @classmethod
    def load_image_manifest_pages(cls, file_path: str) -> List[ImageManifestPage]:
        """Load ordered image pages from a multi-image upload manifest."""
        manifest_path = Path(file_path).resolve()
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("kind") != IMAGE_MANIFEST_KIND:
            raise ValueError(f"不是有效的图片上传清单: {file_path}")

        raw_pages = payload.get("pages")
        if not isinstance(raw_pages, list) or not raw_pages:
            raise ValueError("图片上传清单没有可解析的页面")

        pages: List[ImageManifestPage] = []
        for index, item in enumerate(raw_pages, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"图片上传清单第 {index} 页格式无效")

            raw_path = str(item.get("path") or item.get("stored_path") or "").strip()
            if not raw_path:
                raise ValueError(f"图片上传清单第 {index} 页缺少文件路径")

            page_path = Path(raw_path)
            if not page_path.is_absolute():
                page_path = manifest_path.parent / page_path
            page_path = page_path.resolve()
            if not page_path.exists():
                raise ValueError(f"图片上传清单第 {index} 页文件不存在: {page_path}")

            try:
                page_no = int(item.get("page_no") or index)
            except (TypeError, ValueError):
                page_no = index

            try:
                size = int(item.get("size") or page_path.stat().st_size)
            except (OSError, TypeError, ValueError):
                size = 0

            pages.append(
                ImageManifestPage(
                    page_no=page_no,
                    path=str(page_path),
                    original_filename=str(item.get("original_filename") or ""),
                    content_type=str(item.get("content_type") or ""),
                    size=size,
                )
            )

        return pages

    def validate_upload(
        self,
        file_path: str,
        file_size: int,
        file_extension: str,
        is_pdf: bool = False,
    ) -> ValidationResult:
        """
        验证上传文件

        Args:
            file_path: 文件路径
            file_size: 文件大小（字节）
            file_extension: 文件扩展名
            is_pdf: 是否为PDF

        Returns:
            ValidationResult: 验证结果
        """
        # 检查文件大小
        if file_size > self.upload_config.max_file_size:
            return ValidationResult(
                is_valid=False,
                error_message=f"文件大小超过限制: {file_size / 1024 / 1024:.2f}MB (最大: {self.upload_config.max_file_size / 1024 / 1024}MB)"
            )

        # 检查文件类型
        if is_pdf:
            if file_extension.lower() not in self.upload_config.allowed_pdf_extensions:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"不支持的PDF格式: {file_extension}"
                )
        else:
            if file_extension.lower() not in self.upload_config.allowed_image_extensions:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"不支持的图片格式: {file_extension}"
                )

            # 检查单张图片大小
            if file_size > self.upload_config.single_image_max_size:
                return ValidationResult(
                    is_valid=False,
                    error_message=f"图片大小超过限制: {file_size / 1024 / 1024:.2f}MB (最大: {self.upload_config.single_image_max_size / 1024 / 1024}MB)"
                )

        return ValidationResult(is_valid=True)

    def validate_pdf_pages(self, page_count: int) -> ValidationResult:
        """验证PDF页数"""
        if page_count > self.upload_config.max_pdf_pages:
            return ValidationResult(
                is_valid=False,
                error_message=f"PDF页数超过限制: {page_count}页 (最大: {self.upload_config.max_pdf_pages}页)"
            )
        return ValidationResult(is_valid=True)

    def validate_image_count(self, image_count: int) -> ValidationResult:
        """验证图片数量"""
        if image_count > self.upload_config.max_image_count:
            return ValidationResult(
                is_valid=False,
                error_message=f"图片数量超过限制: {image_count}张 (最大: {self.upload_config.max_image_count}张)"
            )
        return ValidationResult(is_valid=True)

    def determine_parse_status(self, confidence: float, has_errors: bool = False) -> ParseStatus:
        """
        根据置信度确定解析状态

        Args:
            confidence: 置信度 0-1
            has_errors: 是否有错误

        Returns:
            ParseStatus: 解析状态
        """
        if has_errors:
            return ParseStatus.NEED_REUPLOAD

        if confidence >= 0.95:
            return ParseStatus.PARSE_SUCCESS
        elif confidence >= 0.85:
            return ParseStatus.PARSE_RISK
        elif confidence >= 0.70:
            return ParseStatus.NEED_MANUAL_REVIEW
        else:
            return ParseStatus.NEED_REUPLOAD

    def needs_manual_review(self, parse_status: ParseStatus) -> bool:
        """判断是否需要人工复核"""
        return parse_status in [
            ParseStatus.PARSE_RISK,
            ParseStatus.NEED_MANUAL_REVIEW,
        ]
