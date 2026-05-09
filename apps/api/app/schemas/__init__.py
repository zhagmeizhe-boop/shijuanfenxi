"""
Pydantic Schemas for API
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
from enum import Enum
from pydantic import BaseModel, Field


# ==================== Enums ====================

class ParseStatus(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    PARSE_SUCCESS = "parse_success"
    PARSE_FAILED = "parse_failed"
    PARSE_RISK = "parse_risk"
    NEED_REUPLOAD = "need_reupload"
    NEED_MANUAL_REVIEW = "need_manual_review"


class QuestionType(str, Enum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    FILL_BLANK = "fill_blank"
    CALCULATION = "calculation"
    SOLUTION = "solution"
    APPLICATION = "application"
    COMPREHENSIVE = "comprehensive"
    OPEN_ENDED = "open_ended"


class DimensionCode(str, Enum):
    COMPUTATION = "dim1"
    CONCEPT = "dim2"
    LOGIC = "dim3"
    SPATIAL = "dim4"
    APPLICATION = "dim5"
    INNOVATION = "dim6"


# ==================== Sub Models ====================

class SubQuestionResponse(BaseModel):
    question_no: str
    raw_text: str
    score: float
    is_optional: bool = False


class SubItemCandidateResponse(BaseModel):
    candidate_no: str
    raw_text: str
    confidence: float = 0.0
    reason: str = ""
    bbox: Optional[Dict[str, int]] = None


class QuestionBlockResponse(BaseModel):
    page_no: int
    bbox: Dict[str, int]
    line_count: int = 0
    text_density: float = 0.0


class ParseAuditResponse(BaseModel):
    anchor_confidence: float = 0.0
    score_confidence: float = 0.0
    block_completeness: float = 0.0
    cross_page_merged: bool = False
    image_cropped: bool = False
    image_required_hint: bool = False
    image_strategy: str = "text_only"
    score_source: str = "unknown"
    score_reason: str = ""
    formula_enhanced: bool = False
    line_count: int = 0
    warning_codes: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class QuestionCountAuditResponse(BaseModel):
    page_no: int
    zone_key: str
    section_index_raw: str = ""
    detected_count: int = 0
    declared_count: Optional[int] = None
    anchor_numbers: List[str] = Field(default_factory=list)
    missing_numbers: List[str] = Field(default_factory=list)
    duplicate_numbers: List[str] = Field(default_factory=list)
    secondary_pass_used: bool = False
    mismatch_reason: str = ""
    layout_type: str = "single_column"


class ParsedQuestionResponse(BaseModel):
    question_no: str
    question_label_raw: str = ""
    section_index_raw: str = ""
    question_type: QuestionType
    raw_text: str
    score: float
    is_optional: bool = False
    include_in_main_score: bool = True
    parse_confidence: float
    applicable_dims: List[DimensionCode]
    page_no: int = 1
    image_block_url: Optional[str] = None
    block_bbox: Optional[Dict[str, int]] = None
    question_block: Optional[QuestionBlockResponse] = None
    parse_warnings: List[str] = Field(default_factory=list)
    parse_audit: Optional[ParseAuditResponse] = None
    ocr_text_version: str = "v1.0"
    sub_questions: List[SubQuestionResponse] = Field(default_factory=list)
    sub_item_candidates: List[SubItemCandidateResponse] = Field(default_factory=list)


# ==================== Request/Response Models ====================

class PaperAnalyzeRequest(BaseModel):
    """试卷分析请求"""
    paper_name: Optional[str] = Field(None, description="试卷名称")
    grade: Optional[str] = Field(None, description="年级")
    subject: str = Field("数学", description="学科")
    source: Optional[str] = Field(None, description="来源")


class PaperAnalyzeResponse(BaseModel):
    """试卷分析响应"""
    paper_id: str
    parse_status: ParseStatus
    message: str
    estimated_seconds: int


class PaperStatusResponse(BaseModel):
    """试卷状态响应"""
    paper_id: str
    parse_status: ParseStatus
    parse_confidence: float
    need_manual_review: bool
    total_question_count: int
    total_score: float
    created_at: datetime
    updated_at: datetime
    last_stage: Optional[str] = None
    error_message: Optional[str] = None
    progress_current: Optional[int] = None
    progress_total: Optional[int] = None
    progress_message: Optional[str] = None


class ParsedPaperResponse(BaseModel):
    """解析后的试卷响应"""
    paper_id: str
    paper_name: str
    total_question_count: int
    total_score: float
    page_count: int
    parse_status: ParseStatus
    parse_confidence: float
    need_manual_review: bool
    questions: List[ParsedQuestionResponse]
    file_type: str
    source_file_url: str
    report_warnings: List[str] = Field(default_factory=list)
    question_count_audits: List[QuestionCountAuditResponse] = Field(default_factory=list)
    created_at: datetime


class HealthCheckResponse(BaseModel):
    """健康检查响应"""
    status: str
    version: str
    timestamp: datetime
    services: Dict[str, Any]


class ErrorResponse(BaseModel):
    """错误响应"""
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None
