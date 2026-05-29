from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.db_base import Base


class ParseStatus(PyEnum):
    PENDING = "pending"
    PARSING = "parsing"
    PARSE_SUCCESS = "parse_success"
    PARSE_FAILED = "parse_failed"
    PARSE_RISK = "parse_risk"
    NEED_REUPLOAD = "need_reupload"
    NEED_MANUAL_REVIEW = "need_manual_review"


class QuestionType(PyEnum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    FILL_BLANK = "fill_blank"
    CALCULATION = "calculation"
    SOLUTION = "solution"
    APPLICATION = "application"
    COMPREHENSIVE = "comprehensive"
    OPEN_ENDED = "open_ended"


class DimensionCode(PyEnum):
    COMPUTATION = "dim1"
    CONCEPT = "dim2"
    LOGIC = "dim3"
    SPATIAL = "dim4"
    APPLICATION = "dim5"
    INNOVATION = "dim6"


class ScoreLevel(PyEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class Paper(Base):
    __tablename__ = "paper"

    paper_id = Column(String(36), primary_key=True, comment="试卷ID")
    paper_name = Column(String(255), nullable=False, comment="试卷名称")
    source_file_url = Column(String(500), nullable=False, comment="源文件路径")
    file_type = Column(String(10), nullable=False, comment="文件类型")
    page_count = Column(Integer, nullable=False, default=1, comment="页数")
    total_question_count = Column(Integer, default=0, comment="题目总数")
    total_score = Column(Float, default=0.0, comment="总分")
    parse_status = Column(
        Enum(ParseStatus, values_callable=lambda items: [item.value for item in items]),
        nullable=False,
        default=ParseStatus.PENDING,
        comment="解析状态",
    )
    parse_confidence = Column(Float, default=0.0, comment="解析置信度")
    need_manual_review = Column(Boolean, default=False, comment="是否需要人工复核")
    last_stage = Column(String(64), nullable=True, comment="最近执行阶段")
    error_message = Column(Text, nullable=True, comment="最近错误信息")
    analysis_task_id = Column(String(128), nullable=True, comment="Celery 分析任务ID")
    cancel_requested = Column(Boolean, nullable=False, default=False, comment="是否请求终止分析")
    cancel_requested_at = Column(DateTime, nullable=True, comment="终止分析请求时间")
    progress_current = Column(Integer, nullable=True, comment="褰撳墠杩涘害")
    progress_total = Column(Integer, nullable=True, comment="鎬昏杩涘害")
    progress_message = Column(String(255), nullable=True, comment="杩涘害鎻愮ず")
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    questions = relationship("Question", back_populates="paper", cascade="all, delete-orphan")
    dim_scores = relationship(
        "PaperDimScore",
        back_populates="paper",
        uselist=False,
        cascade="all, delete-orphan",
    )
    report_snapshots = relationship("ReportSnapshot", back_populates="paper")

    __table_args__ = (
        Index("idx_paper_status", "parse_status"),
        Index("idx_paper_created", "created_at"),
    )


class Question(Base):
    __tablename__ = "question"

    question_id = Column(String(36), primary_key=True, comment="题目ID")
    paper_id = Column(String(36), ForeignKey("paper.paper_id", ondelete="CASCADE"), nullable=False)
    parent_item_id = Column(
        String(36),
        ForeignKey("question.question_id"),
        nullable=True,
        comment="父题ID",
    )
    page_no = Column(Integer, nullable=False, default=1, comment="所在页码")
    question_no = Column(String(20), nullable=False, comment="归一化题号")
    question_label_raw = Column(String(50), nullable=True, comment="卷面原样题号")
    section_index_raw = Column(String(100), nullable=True, comment="卷面区块号")
    question_type = Column(Enum(QuestionType), nullable=False, comment="题目类型")
    raw_text = Column(Text, nullable=False, comment="题目原文")
    image_block_url = Column(String(500), nullable=True, comment="题块图片路径")
    score = Column(Float, default=0.0, comment="分值")
    is_optional = Column(Boolean, default=False, comment="是否选做")
    include_in_main_score = Column(Boolean, default=True, comment="是否计入总分")
    parse_confidence = Column(Float, default=0.0, comment="解析置信度")
    applicable_dims = Column(JSON, default=list, comment="适用维度列表")
    ocr_text_version = Column(String(20), default="v1.0", comment="OCR 文本版本")
    created_at = Column(DateTime, default=func.now(), nullable=False)

    paper = relationship("Paper", back_populates="questions")
    parent_question = relationship(
        "Question",
        remote_side="Question.question_id",
        backref="sub_questions",
    )
    question_tag = relationship(
        "QuestionTag",
        back_populates="question",
        uselist=False,
        cascade="all, delete-orphan",
    )
    dim_scores = relationship(
        "QuestionDimScore",
        back_populates="question",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_question_paper", "paper_id"),
        Index("idx_question_page", "page_no"),
    )


class QuestionTag(Base):
    __tablename__ = "question_tag"

    question_id = Column(
        String(36),
        ForeignKey("question.question_id", ondelete="CASCADE"),
        primary_key=True,
    )
    knowledge_points_main = Column(JSON, default=list, comment="主要知识点")
    knowledge_points_aux = Column(JSON, default=list, comment="辅助知识点")
    highest_grade_level = Column(String(20), comment="最高年级线索")
    evidence_text = Column(Text, comment="标注依据文本")
    tag_confidence = Column(Float, default=0.0, comment="标签置信度")
    created_at = Column(DateTime, default=func.now(), nullable=False)

    question = relationship("Question", back_populates="question_tag")


class QuestionDimScore(Base):
    __tablename__ = "question_dim_score"

    question_id = Column(
        String(36),
        ForeignKey("question.question_id", ondelete="CASCADE"),
        primary_key=True,
    )
    dim_code = Column(Enum(DimensionCode), primary_key=True, comment="维度代码")
    dim_score = Column(Float, default=0.0, comment="维度得分")
    dim_level = Column(Enum(ScoreLevel), comment="维度等级")
    is_applicable = Column(Boolean, default=True, comment="是否适用")
    score_evidence = Column(Text, comment="评分依据")
    rule_version = Column(String(20), default="v1.0", comment="评分规则版本")
    confidence = Column(Float, default=0.0, comment="置信度")
    created_at = Column(DateTime, default=func.now(), nullable=False)

    question = relationship("Question", back_populates="dim_scores")

    __table_args__ = (Index("idx_qds_question", "question_id"),)


class PaperDimScore(Base):
    __tablename__ = "paper_dim_score"

    paper_id = Column(
        String(36),
        ForeignKey("paper.paper_id", ondelete="CASCADE"),
        primary_key=True,
    )

    dim1_score = Column(Float, default=0.0, comment="dim1 得分")
    dim2_score = Column(Float, default=0.0, comment="dim2 得分")
    dim3_score = Column(Float, default=0.0, comment="dim3 得分")
    dim4_score = Column(Float, default=0.0, comment="dim4 得分")
    dim5_score = Column(Float, default=0.0, comment="dim5 得分")
    dim6_score = Column(Float, default=0.0, comment="dim6 得分")

    dim1_level = Column(Enum(ScoreLevel), comment="dim1 等级")
    dim2_level = Column(Enum(ScoreLevel), comment="dim2 等级")
    dim3_level = Column(Enum(ScoreLevel), comment="dim3 等级")
    dim4_level = Column(Enum(ScoreLevel), comment="dim4 等级")
    dim5_level = Column(Enum(ScoreLevel), comment="dim5 等级")
    dim6_level = Column(Enum(ScoreLevel), comment="dim6 等级")

    overall_score = Column(Float, default=0.0, comment="综合得分")
    overall_level = Column(Enum(ScoreLevel), comment="综合等级")
    valid_dim_count = Column(Integer, default=6, comment="有效维度数")
    has_sample_warning = Column(Boolean, default=False, comment="是否有样本警告")

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    paper = relationship("Paper", back_populates="dim_scores")


class BenchmarkConfig(Base):
    __tablename__ = "benchmark_config"

    benchmark_id = Column(String(36), primary_key=True, comment="基准ID")
    benchmark_name = Column(String(100), nullable=False, comment="基准名称")
    dim1_avg = Column(Float, default=0.0, comment="dim1 平均分")
    dim2_avg = Column(Float, default=0.0, comment="dim2 平均分")
    dim3_avg = Column(Float, default=0.0, comment="dim3 平均分")
    dim4_avg = Column(Float, default=0.0, comment="dim4 平均分")
    dim5_avg = Column(Float, default=0.0, comment="dim5 平均分")
    dim6_avg = Column(Float, default=0.0, comment="dim6 平均分")
    overall_avg = Column(Float, default=0.0, comment="综合平均分")
    description = Column(Text, comment="描述")
    created_at = Column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (Index("idx_benchmark_name", "benchmark_name"),)


class ReportSnapshot(Base):
    __tablename__ = "report_snapshot"

    report_id = Column(String(36), primary_key=True, comment="报告ID")
    paper_id = Column(
        String(36),
        ForeignKey("paper.paper_id", ondelete="CASCADE"),
        nullable=False,
    )
    report_json = Column(JSON, nullable=False, comment="报告 JSON 数据")
    report_html = Column(Text, comment="报告 HTML")
    report_version = Column(String(20), default="v1.0", comment="报告版本")
    created_at = Column(DateTime, default=func.now(), nullable=False)

    paper = relationship("Paper", back_populates="report_snapshots")

    __table_args__ = (
        Index("idx_report_paper", "paper_id"),
        Index("idx_report_created", "created_at"),
    )
