"""
Paper-level aggregation helpers.

Current rule:
- each dimension score is the simple average of applicable question scores
- counted_questions should surface representative, auditable examples
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class QuestionDimensionScore:
    question_id: str
    question_no: str
    score: float
    dim_scores: Dict[str, float]
    applicable_dims: List[str]
    question_label_raw: str | None = None
    section_index_raw: str | None = None
    question_display_label: str | None = None
    page_no: int | None = None
    question_summary: str = ""
    dim_reasons: Dict[str, str] = field(default_factory=dict)
    dim_warnings: Dict[str, List[str]] = field(default_factory=dict)
    dim_confidences: Dict[str, float] = field(default_factory=dict)


@dataclass
class PaperDimensionSummary:
    dimension_code: str
    dimension_name: str
    paper_score: float
    level: int
    level_label: str
    total_question_score: float
    question_count: int
    sample_warning: bool
    evidence: str
    warning_messages: List[str] = field(default_factory=list)
    counted_questions: List[Dict[str, object]] = field(default_factory=list)


class PaperAggregator:
    DIMENSION_NAMES = {
        "dim1": "数学运算",
        "dim2": "几何直观与空间想象",
        "dim3": "信息提取与转化",
        "dim4": "实践创新",
        "dim5": "知识广度",
        "dim6": "逻辑链条长度",
    }

    LEVEL_THRESHOLDS = [
        (2.0, 1, "基础"),
        (4.0, 2, "常规"),
        (6.0, 3, "提升"),
        (8.0, 4, "拔高"),
        (10.0, 5, "选拔"),
    ]

    REPRESENTATIVE_LIMIT = 3
    REPRESENTATIVE_CONFIDENCE_THRESHOLD = 0.45
    IMAGE_FALLBACK_HINTS = ("纯文本回退", "多模态分析失败")

    def aggregate(
        self,
        question_scores: List[QuestionDimensionScore],
        dimension_code: str,
    ) -> PaperDimensionSummary:
        applicable_questions = [
            question for question in question_scores if dimension_code in question.applicable_dims
        ]

        total_question_score = sum(question.score for question in applicable_questions)
        question_count = len(applicable_questions)
        sample_warning = 0 < question_count < 2

        if question_count == 0:
            return PaperDimensionSummary(
                dimension_code=dimension_code,
                dimension_name=self.DIMENSION_NAMES.get(dimension_code, dimension_code),
                paper_score=0.0,
                level=0,
                level_label="N/A",
                total_question_score=0.0,
                question_count=0,
                sample_warning=False,
                evidence="该试卷没有适用此维度的题目。",
                warning_messages=[],
                counted_questions=[],
            )

        score_sum = sum(question.dim_scores.get(dimension_code, 0.0) for question in applicable_questions)
        paper_score = score_sum / question_count
        level, level_label = self._calculate_level(paper_score)

        warning_messages: List[str] = []
        for question in applicable_questions:
            warning_messages.extend(question.dim_warnings.get(dimension_code, []))

        if sample_warning:
            warning_messages.append("该维度当前样本题量偏少，整卷结论稳定性有限。")

        deduped_warnings = list(
            dict.fromkeys(message.strip() for message in warning_messages if message.strip())
        )

        evidence = (
            f"共 {question_count} 道相关题目；"
            f"题级平均维度分 {paper_score:.1f} 分，判定为 {level_label}。"
        )

        return PaperDimensionSummary(
            dimension_code=dimension_code,
            dimension_name=self.DIMENSION_NAMES.get(dimension_code, dimension_code),
            paper_score=paper_score,
            level=level,
            level_label=level_label,
            total_question_score=total_question_score,
            question_count=question_count,
            sample_warning=sample_warning,
            evidence=evidence,
            warning_messages=deduped_warnings,
            counted_questions=self._select_representative_questions(applicable_questions, dimension_code),
        )

    def aggregate_all_dimensions(
        self,
        question_scores: List[QuestionDimensionScore],
    ) -> Dict[str, PaperDimensionSummary]:
        return {
            dim_code: self.aggregate(question_scores, dim_code)
            for dim_code in ["dim1", "dim2", "dim3", "dim4", "dim5", "dim6"]
        }

    def _select_representative_questions(
        self,
        applicable_questions: List[QuestionDimensionScore],
        dimension_code: str,
    ) -> List[Dict[str, object]]:
        filtered_questions = [
            question
            for question in applicable_questions
            if not self._is_low_quality_candidate(question, dimension_code)
        ]
        candidates = filtered_questions or applicable_questions

        ranked = sorted(
            candidates,
            key=lambda question: self._representative_sort_key(question, dimension_code),
        )

        selected: List[Dict[str, object]] = []
        seen_display_labels: set[str] = set()

        for question in ranked:
            question_display_label = self._build_question_display_label(question)
            dedupe_key = question_display_label or question.question_id
            if dedupe_key in seen_display_labels:
                continue

            seen_display_labels.add(dedupe_key)
            selected.append(
                {
                    "page_no": question.page_no,
                    "question_no": question.question_no or question.question_id,
                    "question_label_raw": question.question_label_raw or question.question_no or question.question_id,
                    "section_index_raw": question.section_index_raw or "",
                    "question_display_label": question_display_label,
                    "summary": question.question_summary or "",
                    "reason": self._build_display_reason(question, dimension_code),
                }
            )
            if len(selected) >= self.REPRESENTATIVE_LIMIT:
                break

        return selected

    def _is_low_quality_candidate(
        self,
        question: QuestionDimensionScore,
        dimension_code: str,
    ) -> bool:
        reason = (question.dim_reasons.get(dimension_code) or "").strip()
        if not reason:
            return True

        confidence = question.dim_confidences.get(dimension_code, 0.0)
        if confidence and confidence < self.REPRESENTATIVE_CONFIDENCE_THRESHOLD:
            return True

        if dimension_code in {"dim2", "dim3"}:
            warnings = question.dim_warnings.get(dimension_code, [])
            if any(hint in warning for hint in self.IMAGE_FALLBACK_HINTS for warning in warnings):
                return True

        return False

    def _representative_sort_key(
        self,
        question: QuestionDimensionScore,
        dimension_code: str,
    ) -> tuple:
        reason = self._build_display_reason(question, dimension_code)
        warnings = question.dim_warnings.get(dimension_code, [])
        confidence = question.dim_confidences.get(dimension_code, 0.0)

        return (
            -question.dim_scores.get(dimension_code, 0.0),
            -confidence,
            -min(len(reason), 160),
            len(warnings),
            question.page_no if question.page_no is not None else 10**9,
            self._question_no_sort_key(question.question_no),
        )

    @staticmethod
    def _build_display_reason(question: QuestionDimensionScore, dimension_code: str) -> str:
        reason = " ".join((question.dim_reasons.get(dimension_code) or "").split()).strip()
        if not reason:
            return ""

        body = reason
        for marker in ("依据标签：", "核心事实："):
            body = body.split(marker, 1)[0].strip()

        source = ""
        if "依据来源：" in reason:
            source = reason.split("依据来源：", 1)[1].split("。", 1)[0].strip(" 。；;")

        if source:
            return f"{body} 依据：{source}".strip()
        return body

    @staticmethod
    def _question_no_sort_key(question_no: str) -> tuple:
        parts = re.findall(r"\d+|[^\d]+", str(question_no or ""))
        normalized: List[tuple[int, object]] = []
        for part in parts:
            if part.isdigit():
                normalized.append((0, int(part)))
            else:
                normalized.append((1, part))
        return tuple(normalized)

    @staticmethod
    def _build_question_display_label(question: QuestionDimensionScore) -> str:
        explicit_display_label = str(question.question_display_label or "").strip()
        if explicit_display_label:
            return explicit_display_label

        section_index_raw = str(question.section_index_raw or "").strip()
        question_no = str(question.question_no or "").strip()
        if section_index_raw and question_no:
            return f"{section_index_raw}-{question_no}"

        question_label_raw = str(question.question_label_raw or "").strip()
        if question_label_raw:
            return question_label_raw

        return question_no or str(question.question_id or "").strip()

    def _calculate_level(self, score: float) -> tuple[int, str]:
        for threshold, level, label in self.LEVEL_THRESHOLDS:
            if score <= threshold:
                return level, label
        return 5, "选拔"
