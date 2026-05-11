"""
Paper-level aggregation helpers.

Current rule:
- each dimension score is the simple average of applicable question scores
- dim4 uses a level-weighted average over automatically scored questions; invalid/missing scores are ignored without review
- dim5 keeps paper-level knowledge-source composition as explanation, not as the scoring rule
- counted_questions should surface representative, auditable examples
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List


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
    dim_statuses: Dict[str, str] = field(default_factory=dict)
    dim_details: Dict[str, Dict[str, Any]] = field(default_factory=dict)


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
    review_question_count: int = 0
    score_status: str = "scored"
    score_breakdown: Dict[str, Any] = field(default_factory=dict)


class PaperAggregator:
    DIMENSION_NAMES = {
        "dim1": "数学运算",
        "dim2": "几何直观与空间想象",
        "dim3": "信息提取与转化",
        "dim4": "实践创新",
        "dim5": "知识广度",
        "dim6": "逻辑链条",
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
    DIM4_LEVEL_WEIGHTS = {
        "L1": 1,
        "L2": 2,
        "L3": 7,
        "L4": 12,
        "L5": 15,
    }
    IMAGE_FALLBACK_HINTS = ("纯文本回退", "多模态分析失败")
    DIM2_GEOMETRY_HINTS = (
        "几何",
        "图形",
        "空间",
        "图片",
        "题块",
        "如图",
        "图中",
        "面积",
        "体积",
        "容积",
        "圆柱",
        "圆锥",
        "长方形",
        "正方形",
        "水位",
        "瓶",
    )
    DIM5_BUCKET_LABELS = {
        "school": "校内教材",
        "low_gaosi": "低段高思拓展",
        "high_gaosi": "高年级高思拓展",
        "junior_bridge": "初中前置",
        "beyond": "高思超越篇",
        "unknown": "未稳定归类",
    }
    DIM5_LEVEL_WEIGHTS = {
        "L1": 1,
        "L2": 1,
        "L3": 2,
        "L4": 4,
        "L5": 6,
    }

    COUNTED_QUESTION_FULL_REASON_HIDDEN_MARKERS = ("依据标签：", "核心事实：", "依据来源：")

    COUNTED_QUESTION_LEVEL_DESCRIPTOR_PATTERN = re.compile(r"^(L[1-5])\s+[^：:]{1,40}[：:]\s*(.+)$")

    @classmethod
    def _format_counted_question_analysis(cls, text: object) -> str:
        normalized = " ".join(str(text or "").split()).strip()
        for marker in cls.COUNTED_QUESTION_FULL_REASON_HIDDEN_MARKERS:
            normalized = normalized.split(marker, 1)[0].strip()
        normalized = normalized.rstrip(" 。；;，,")

        match = cls.COUNTED_QUESTION_LEVEL_DESCRIPTOR_PATTERN.match(normalized)
        if match:
            normalized = f"{match.group(1)}：{match.group(2).strip()}"
        return normalized.rstrip(" 。；;，,")

    @staticmethod
    def _dimension_status(question: QuestionDimensionScore, dimension_code: str) -> str:
        explicit_status = str(question.dim_statuses.get(dimension_code, "")).strip()
        if explicit_status:
            return explicit_status
        return "applicable" if dimension_code in question.applicable_dims else "not_applicable"

    @classmethod
    def _dim2_has_geometry_candidate(cls, question: QuestionDimensionScore) -> bool:
        details = question.dim_details.get("dim2", {}) or {}
        if details.get("fallback_source") in {"visual_geometry", "geometry_structure"}:
            return True
        if details.get("figure_complexity") not in {"", None, "none"}:
            return True
        if details.get("geometry_model_types"):
            return True
        text = " ".join(
            [
                question.question_summary or "",
                question.dim_reasons.get("dim2", ""),
                " ".join(question.dim_warnings.get("dim2", []) or []),
                str(details.get("evidence_summary", "")),
                " ".join(str(item) for item in details.get("evidence_tags", []) or []),
            ]
        )
        return any(hint in text for hint in cls.DIM2_GEOMETRY_HINTS)

    def aggregate(
        self,
        question_scores: List[QuestionDimensionScore],
        dimension_code: str,
    ) -> PaperDimensionSummary:
        if dimension_code == "dim1":
            return self._aggregate_dim1(question_scores)
        if dimension_code == "dim4":
            return self._aggregate_dim4(question_scores)
        if dimension_code == "dim5":
            return self._aggregate_dim5(question_scores)

        applicable_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, dimension_code) == "applicable"
        ]
        review_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, dimension_code) == "review"
        ]

        total_question_score = sum(question.score for question in applicable_questions)
        question_count = len(applicable_questions)
        review_question_count = len(review_questions)
        sample_warning = 0 < question_count < 2

        if question_count == 0:
            dim2_geometry_candidate_count = (
                sum(1 for question in question_scores if self._dim2_has_geometry_candidate(question))
                if dimension_code == "dim2"
                else 0
            )
            if dimension_code == "dim2" and dim2_geometry_candidate_count:
                evidence = (
                    f"本卷存在 {dim2_geometry_candidate_count} 道几何/图形候选题，"
                    "但未形成可自动计入 dim2 的稳定空间表征样本；相关题目已排除或转入复核。"
                )
            else:
                evidence = "该维度自动评分未覆盖，未计入综合分。"

            return PaperDimensionSummary(
                dimension_code=dimension_code,
                dimension_name=self.DIMENSION_NAMES.get(dimension_code, dimension_code),
                paper_score=0.0,
                level=0,
                level_label="未覆盖",
                total_question_score=0.0,
                question_count=0,
                sample_warning=False,
                evidence=evidence,
                warning_messages=[],
                counted_questions=[],
                review_question_count=review_question_count,
                score_status="not_covered",
                score_breakdown={
                    "geometry_candidate_count": dim2_geometry_candidate_count,
                    "review_question_count": review_question_count,
                },
            )

        score_sum = sum(question.dim_scores.get(dimension_code, 0.0) for question in applicable_questions)
        paper_score = score_sum / question_count
        level, level_label = self._calculate_level(paper_score)

        actual_review_question_count = review_question_count
        review_questions = []
        review_question_count = 0
        warning_messages: List[str] = []
        for question in applicable_questions:
            warning_messages.extend(question.dim_warnings.get(dimension_code, []))
        for question in review_questions:
            warning_messages.extend(question.dim_warnings.get(dimension_code, []))

        if review_question_count:
            warning_messages.append(
                f"{self.DIMENSION_NAMES.get(dimension_code, dimension_code)}有 {review_question_count} 道题自动评分未覆盖，未计入均分。"
            )

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
            review_question_count=actual_review_question_count,
        )

    @classmethod
    def _dim5_bucket_for_question(cls, question: QuestionDimensionScore) -> str:
        details = question.dim_details.get("dim5", {}) if isinstance(question.dim_details, dict) else {}
        if isinstance(details, dict):
            bucket = str(details.get("knowledge_source_bucket", "")).strip()
            if bucket:
                return bucket

        legacy_score = question.dim_scores.get("dim5")
        if legacy_score is None:
            return "unknown"
        if legacy_score <= 3.5:
            return "school"
        if legacy_score <= 5.5:
            return "low_gaosi"
        if legacy_score <= 7.5:
            return "high_gaosi"
        return "beyond"

    @staticmethod
    def _normalize_dim5_level(value: object) -> str:
        text = str(value or "").strip().upper()
        if text in {"L1", "L2", "L3", "L4", "L5"}:
            return text
        if text in {"1", "2", "3", "4", "5"}:
            return f"L{text}"
        match = re.search(r"\bL?([1-5])\b", text)
        return f"L{match.group(1)}" if match else ""

    @classmethod
    def _dim5_level_for_question(cls, question: QuestionDimensionScore) -> str:
        details = cls._dim5_details_for_question(question)
        for key in ("knowledge_level", "dim5_level"):
            level = cls._normalize_dim5_level(details.get(key))
            if level:
                return level

        score = cls._valid_dim5_question_score(question)
        if score is None:
            reason = question.dim_reasons.get("dim5", "")
            return cls._normalize_dim5_level(reason)
        if score <= 2.5:
            return "L1"
        if score <= 4.5:
            return "L2"
        if score <= 6.5:
            return "L3"
        if score <= 8.5:
            return "L4"
        return "L5"

    @staticmethod
    def _ratio(count: int, total: int) -> float:
        return count / total if total else 0.0

    @staticmethod
    def _valid_dim5_question_score(question: QuestionDimensionScore) -> float | None:
        raw_score = question.dim_scores.get("dim5")
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            return None
        if 0.0 < score <= 10.0:
            return score
        return None

    @staticmethod
    def _dim5_details_for_question(question: QuestionDimensionScore) -> Dict[str, object]:
        details = question.dim_details.get("dim5", {}) if isinstance(question.dim_details, dict) else {}
        return details if isinstance(details, dict) else {}

    @classmethod
    def _dim5_source_for_question(cls, question: QuestionDimensionScore) -> str:
        details = cls._dim5_details_for_question(question)
        if str(details.get("dim5_excluded_reason") or "").strip() == "retry_failed":
            return "llm_dim5_retry_failed"
        if (
            details.get("dim5_retry_used") is True
            and str(details.get("gaosi_classification_source") or "").strip() == "llm_retry"
        ):
            return "llm_dim5_retry"
        source = str(details.get("band_source") or "").strip()
        if source:
            return source
        source = str(details.get("gaosi_classification_source") or "").strip()
        if source:
            return source
        return "model_only"

    @classmethod
    def _dim5_is_topic_structure_upshift(cls, question: QuestionDimensionScore) -> bool:
        details = cls._dim5_details_for_question(question)
        if str(details.get("band_source") or "").strip() == "topic_structure_match":
            return True
        calibration = details.get("calibration", {})
        if not isinstance(calibration, dict):
            return False
        return (
            str(calibration.get("match_scope") or "").strip() == "topic_structure"
            and str(calibration.get("match_action") or "").strip() in {"raise_band", "confirm_model"}
        )

    @staticmethod
    def _dim1_bucket_for_question(question: QuestionDimensionScore) -> str:
        details = question.dim_details.get("dim1", {}) if isinstance(question.dim_details, dict) else {}
        if isinstance(details, dict):
            bucket = str(details.get("calc_bucket", "")).strip()
            if bucket in {"pure_calculation", "embedded_calculation"}:
                return bucket
            if (
                str(details.get("task_form", "")).strip() == "embedded"
                and str(details.get("calc_role", "")).strip() == "core"
            ):
                return "embedded_calculation"
        return "pure_calculation"

    @staticmethod
    def _normalize_dim4_level(value: object) -> str:
        text = str(value or "").strip().upper()
        if text in {"L1", "L2", "L3", "L4", "L5"}:
            return text
        if text in {"1", "2", "3", "4", "5"}:
            return f"L{text}"
        match = re.search(r"\bL?([1-5])\b", text)
        return f"L{match.group(1)}" if match else ""

    @classmethod
    def _dim4_level_for_question(cls, question: QuestionDimensionScore) -> str:
        details = question.dim_details.get("dim4", {}) if isinstance(question.dim_details, dict) else {}
        if isinstance(details, dict):
            for key in ("dim4_level", "calibrated_topic_level", "topic_level", "reference_calibrated_level"):
                level = cls._normalize_dim4_level(details.get(key))
                if level:
                    return level
            calibration = details.get("reference_calibration")
            if isinstance(calibration, dict):
                level = cls._normalize_dim4_level(
                    calibration.get("final_level") or calibration.get("reference_level")
                )
                if level:
                    return level
        score = question.dim_scores.get("dim4")
        if score is None:
            reason = question.dim_reasons.get("dim4", "")
            return cls._normalize_dim4_level(reason)
        if score <= 2.5:
            return "L1"
        if score <= 4.5:
            return "L2"
        if score <= 6.5:
            return "L3"
        if score <= 8.5:
            return "L4"
        return "L5"

    @classmethod
    def _dim4_source_for_question(cls, question: QuestionDimensionScore) -> str:
        details = question.dim_details.get("dim4", {}) if isinstance(question.dim_details, dict) else {}
        if not isinstance(details, dict):
            return "legacy_score"
        calibration = details.get("reference_calibration")
        if isinstance(calibration, dict) and calibration.get("action"):
            return str(calibration.get("action") or "").strip()
        return str(details.get("level_source") or "").strip() or "rule_score"

    @classmethod
    def _dim4_not_applicable_reason(cls, question: QuestionDimensionScore) -> str:
        return " ".join(str(question.dim_reasons.get("dim4", "") or "").split()).strip()

    @classmethod
    def _dim4_is_l1_excluded(cls, question: QuestionDimensionScore) -> bool:
        if cls._dimension_status(question, "dim4") != "not_applicable":
            return False

        level = cls._dim4_level_for_question(question)
        reason = cls._dim4_not_applicable_reason(question)
        if level == "L1":
            return True
        return "L1" in reason and ("基础模板" in reason or "模板" in reason)

    @staticmethod
    def _valid_dim4_question_score(question: QuestionDimensionScore) -> float | None:
        raw_score = question.dim_scores.get("dim4")
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            return None
        if 0.0 < score <= 10.0:
            return score
        return None

    @staticmethod
    def _sanitize_dim4_warning(message: object) -> str:
        text = str(message or "").strip()
        if not text:
            return ""
        replacements = {
            "当前题目转入人工复核": "已按自动规则纳入评分",
            "转入人工复核": "按自动规则纳入评分",
            "当前结果需人工复核": "自动评分结果需要谨慎解读",
            "需人工复核": "需要谨慎解读",
            "需要人工复核": "需要谨慎解读",
            "人工复核": "自动评分提示",
            "复核": "检查",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        return text.replace("未计入均分", "已按保守规则计入")

    @staticmethod
    def _average_dimension_score(questions: List[QuestionDimensionScore], dimension_code: str) -> float:
        if not questions:
            return 0.0
        return sum(question.dim_scores.get(dimension_code, 0.0) for question in questions) / len(questions)

    def _aggregate_dim4(self, question_scores: List[QuestionDimensionScore]) -> PaperDimensionSummary:
        level_counts = {f"L{index}": 0 for index in range(1, 6)}
        source_counts: Dict[str, int] = {}
        scored_questions: List[QuestionDimensionScore] = []
        fallback_count = 0
        raw_score_sum = 0.0
        weighted_score_sum = 0.0
        total_weight = 0.0
        ignored_question_count = 0

        for question in question_scores:
            question_score = self._valid_dim4_question_score(question)
            level = self._dim4_level_for_question(question)
            source = self._dim4_source_for_question(question) or "rule_score"
            if question_score is None or level not in level_counts:
                ignored_question_count += 1
                continue

            details = question.dim_details.get("dim4", {}) if isinstance(question.dim_details, dict) else {}
            if (
                source == "conservative_fallback"
                or (isinstance(details, dict) and details.get("fallback_used") is True)
            ):
                fallback_count += 1

            level_counts[level] += 1
            source_counts[source] = source_counts.get(source, 0) + 1
            scored_questions.append(question)
            raw_score_sum += question_score
            weight = float(self.DIM4_LEVEL_WEIGHTS.get(level, 1))
            weighted_score_sum += question_score * weight
            total_weight += weight

        question_count = len(scored_questions)
        level_ratios = {
            level: round(self._ratio(count, question_count), 4)
            for level, count in level_counts.items()
        }
        raw_question_average = raw_score_sum / question_count if question_count else 0.0
        weighted_question_average = weighted_score_sum / total_weight if total_weight else 0.0
        breakdown = {
            "level_counts": level_counts,
            "level_ratios": level_ratios,
            "source_counts": source_counts,
            "level_weights": self.DIM4_LEVEL_WEIGHTS,
            "raw_question_average": round(raw_question_average, 4),
            "weighted_question_average": round(weighted_question_average, 4),
            "weighted_score_sum": round(weighted_score_sum, 4),
            "total_weight": round(total_weight, 4),
            "not_applicable_count": 0,
            "review_count": 0,
            "l1_excluded_count": 0,
            "fallback_count": fallback_count,
            "valid_score_question_count": question_count,
            "unscored_question_count": ignored_question_count,
            "unknown_level_count": ignored_question_count,
            "auto_ignored_count": ignored_question_count,
            "high_level_question_count": level_counts["L4"] + level_counts["L5"],
            "aggregation_rule": "能稳定自动判定 L1-L5 的题纳入实践创新评分；无法自动判定的题自动未覆盖；卷级主分按高阶创新等级权重计算。",
        }

        if question_count == 0:
            return PaperDimensionSummary(
                dimension_code="dim4",
                dimension_name=self.DIMENSION_NAMES["dim4"],
                paper_score=0.0,
                level=0,
                level_label="未覆盖",
                total_question_score=0.0,
                question_count=0,
                sample_warning=False,
                evidence="实践创新暂无可评分题目，未计入综合分。",
                warning_messages=[],
                counted_questions=[],
                review_question_count=0,
                score_status="not_covered",
                score_breakdown=breakdown,
            )

        total_question_score = sum(question.score for question in scored_questions)
        paper_score = weighted_question_average
        level, level_label = self._calculate_level(paper_score)
        sample_warning = 0 < question_count < 2

        warning_messages: List[str] = []
        for question in scored_questions:
            warning_messages.extend(self._sanitize_dim4_warning(item) for item in question.dim_warnings.get("dim4", []))
        if sample_warning:
            warning_messages.append("该维度当前样本题量偏少，整卷结论稳定性有限。")
        deduped_warnings = list(
            dict.fromkeys(message.strip() for message in warning_messages if message.strip())
        )

        evidence_parts = [
            f"共 {question_count} 道题纳入实践创新评分",
            "按高阶创新等级权重计算",
        ]
        evidence_parts.append(f"权重得分 {paper_score:.1f} 分，判定为 {level_label}")
        evidence = "；".join(evidence_parts) + "。"

        return PaperDimensionSummary(
            dimension_code="dim4",
            dimension_name=self.DIMENSION_NAMES["dim4"],
            paper_score=paper_score,
            level=level,
            level_label=level_label,
            total_question_score=total_question_score,
            question_count=question_count,
            sample_warning=sample_warning,
            evidence=evidence,
            warning_messages=deduped_warnings,
            counted_questions=self._select_representative_questions(scored_questions, "dim4"),
            review_question_count=0,
            score_breakdown=breakdown,
        )

    def _aggregate_dim1(self, question_scores: List[QuestionDimensionScore]) -> PaperDimensionSummary:
        applicable_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, "dim1") == "applicable"
        ]
        review_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, "dim1") == "review"
        ]

        question_count = len(applicable_questions)
        review_question_count = len(review_questions)
        if question_count == 0:
            return PaperDimensionSummary(
                dimension_code="dim1",
                dimension_name=self.DIMENSION_NAMES["dim1"],
                paper_score=0.0,
                level=0,
                level_label="未覆盖",
                total_question_score=0.0,
                question_count=0,
                sample_warning=False,
                evidence="数学运算自动评分未覆盖，未计入综合分。",
                warning_messages=[],
                counted_questions=[],
                review_question_count=review_question_count,
                score_status="not_covered",
            )

        pure_questions = [
            question
            for question in applicable_questions
            if self._dim1_bucket_for_question(question) == "pure_calculation"
        ]
        embedded_questions = [
            question
            for question in applicable_questions
            if self._dim1_bucket_for_question(question) == "embedded_calculation"
        ]

        pure_average = self._average_dimension_score(pure_questions, "dim1")
        embedded_average = self._average_dimension_score(embedded_questions, "dim1")

        if pure_questions and embedded_questions:
            pure_weight, embedded_weight = (0.7, 0.3) if len(pure_questions) >= 2 else (0.5, 0.5)
            rule_label = "纯计算与嵌入式计算加权"
        elif pure_questions:
            pure_weight, embedded_weight = 1.0, 0.0
            rule_label = "纯计算专项"
        else:
            pure_weight, embedded_weight = 0.0, 1.0
            rule_label = "嵌入式计算估计"

        paper_score = pure_average * pure_weight + embedded_average * embedded_weight
        level, level_label = self._calculate_level(paper_score)
        sample_warning = 0 < question_count < 2

        warning_messages: List[str] = []
        for question in applicable_questions:
            warning_messages.extend(question.dim_warnings.get("dim1", []))
        if sample_warning:
            warning_messages.append("该维度当前样本题量偏少，整卷结论稳定性有限。")
        deduped_warnings = list(
            dict.fromkeys(message.strip() for message in warning_messages if message.strip())
        )

        breakdown = {
            "pure_calculation": {
                "question_count": len(pure_questions),
                "average_score": round(pure_average, 2),
                "weight": pure_weight,
            },
            "embedded_calculation": {
                "question_count": len(embedded_questions),
                "average_score": round(embedded_average, 2),
                "weight": embedded_weight,
            },
            "aggregation_rule": rule_label,
        }

        evidence_parts = [
            f"共 {question_count} 道相关题目",
            (
                f"纯计算 {len(pure_questions)} 道，均分 {pure_average:.1f}，"
                f"权重 {pure_weight:.0%}"
            ),
            (
                f"嵌入式计算 {len(embedded_questions)} 道，均分 {embedded_average:.1f}，"
                f"权重 {embedded_weight:.0%}"
            ),
            f"加权维度分 {paper_score:.1f} 分，判定为 {level_label}",
        ]
        if embedded_questions and not pure_questions:
            evidence_parts.append("本卷无纯计算专项题，dim1 由嵌入式计算估计")
        evidence = "；".join(evidence_parts) + "。"

        return PaperDimensionSummary(
            dimension_code="dim1",
            dimension_name=self.DIMENSION_NAMES["dim1"],
            paper_score=paper_score,
            level=level,
            level_label=level_label,
            total_question_score=sum(question.score for question in applicable_questions),
            question_count=question_count,
            sample_warning=sample_warning,
            evidence=evidence,
            warning_messages=deduped_warnings,
            counted_questions=self._select_representative_questions(applicable_questions, "dim1"),
            review_question_count=review_question_count,
            score_breakdown=breakdown,
        )

    def _aggregate_dim5(self, question_scores: List[QuestionDimensionScore]) -> PaperDimensionSummary:
        applicable_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, "dim5") == "applicable"
        ]
        review_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, "dim5") == "review"
        ]

        bucket_counts = {bucket: 0 for bucket in self.DIM5_BUCKET_LABELS}
        level_counts = {f"L{index}": 0 for index in range(1, 6)}
        domain_counts: Dict[str, int] = {}
        source_counts: Dict[str, int] = {}
        scored_questions: List[QuestionDimensionScore] = []
        raw_score_sum = 0.0
        weighted_score_sum = 0.0
        total_weight = 0.0
        unscored_applicable_count = 0
        fallback_failed_count = sum(
            1
            for question in question_scores
            if self._dim5_source_for_question(question) == "llm_dim5_retry_failed"
        )
        question_bank_count = 0
        topic_structure_upshift_count = 0
        llm_fallback_count = 0
        for question in applicable_questions:
            bucket = self._dim5_bucket_for_question(question)
            bucket = bucket if bucket in bucket_counts else "unknown"
            bucket_counts[bucket] += 1
            question_score = self._valid_dim5_question_score(question)
            question_level = self._dim5_level_for_question(question)
            if question_score is None:
                unscored_applicable_count += 1
                continue
            if question_level not in level_counts:
                unscored_applicable_count += 1
                continue

            source = self._dim5_source_for_question(question)
            source_counts[source] = source_counts.get(source, 0) + 1
            details = self._dim5_details_for_question(question)
            domain = str(details.get("canonical_knowledge_domain") or "unknown").strip() or "unknown"
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            if source == "question_bank" or str(details.get("gaosi_classification_source") or "").strip() == "question_bank":
                question_bank_count += 1
            if source == "llm_dim5_retry":
                llm_fallback_count += 1
            if self._dim5_is_topic_structure_upshift(question):
                topic_structure_upshift_count += 1
            scored_questions.append(question)
            raw_score_sum += question_score
            level_counts[question_level] += 1
            weight = float(self.DIM5_LEVEL_WEIGHTS.get(question_level, 1))
            weighted_score_sum += question_score * weight
            total_weight += weight

        question_count = len(scored_questions)
        review_question_count = len(review_questions)
        raw_question_average = raw_score_sum / question_count if question_count else 0.0
        weighted_question_average = weighted_score_sum / total_weight if total_weight else 0.0
        level_ratios = {
            level: round(self._ratio(count, question_count), 4)
            for level, count in level_counts.items()
        }
        bucket_ratio_denominator = len(applicable_questions)
        bucket_ratios = {
            bucket: round(self._ratio(count, bucket_ratio_denominator), 4)
            for bucket, count in bucket_counts.items()
        }
        breakdown = {
            "level_weights": dict(self.DIM5_LEVEL_WEIGHTS),
            "level_counts": dict(level_counts),
            "level_ratios": level_ratios,
            "bucket_counts": dict(bucket_counts),
            "bucket_ratios": bucket_ratios,
            "bucket_ratio_denominator": bucket_ratio_denominator,
            "domain_counts": dict(domain_counts),
            "source_counts": dict(source_counts),
            "question_bank_count": question_bank_count,
            "topic_structure_upshift_count": topic_structure_upshift_count,
            "llm_fallback_count": llm_fallback_count,
            "fallback_failed_count": fallback_failed_count,
            "beyond_question_count": level_counts["L5"],
            "aggregation_rule": "知识范围等级加权均分",
            "raw_question_average": round(raw_question_average, 4),
            "weighted_question_average": round(weighted_question_average, 4),
            "question_score_average": round(raw_question_average, 4),
            "question_score_sum": round(raw_score_sum, 4),
            "weighted_score_sum": round(weighted_score_sum, 4),
            "total_weight": round(total_weight, 4),
            "valid_score_question_count": question_count,
            "unscored_applicable_count": unscored_applicable_count,
            "unknown_scored_count": bucket_counts["unknown"]
            - sum(
                1
                for question in applicable_questions
                if self._dim5_bucket_for_question(question) == "unknown"
                and self._valid_dim5_question_score(question) is None
            ),
            "unknown_unscored_count": sum(
                1
                for question in applicable_questions
                if self._dim5_bucket_for_question(question) == "unknown"
                and self._valid_dim5_question_score(question) is None
            ),
            "final_score": weighted_question_average,
        }

        if question_count == 0:
            return PaperDimensionSummary(
                dimension_code="dim5",
                dimension_name=self.DIMENSION_NAMES["dim5"],
                paper_score=0.0,
                level=0,
                level_label="未覆盖",
                total_question_score=0.0,
                question_count=0,
                sample_warning=False,
                evidence="知识广度自动评分未覆盖，未计入综合分。",
                warning_messages=[],
                counted_questions=[],
                review_question_count=review_question_count,
                score_status="not_covered",
                score_breakdown=breakdown,
            )

        paper_score = weighted_question_average
        level, level_label = self._calculate_level(paper_score)

        evidence = (
            f"共 {question_count} 道题纳入知识范围评分；"
            f"按知识范围等级权重计算；"
            f"权重得分 {paper_score:.1f} 分，判定为{level_label}。"
        )

        warning_messages: List[str] = []
        if unscored_applicable_count:
            warning_messages.append(f"有 {unscored_applicable_count} 道题缺少合法题级分或知识范围等级，未计入知识范围评分。")
        for question in applicable_questions:
            warning_messages.extend(question.dim_warnings.get("dim5", []))
        deduped_warnings = list(
            dict.fromkeys(message.strip() for message in warning_messages if message.strip())
        )

        return PaperDimensionSummary(
            dimension_code="dim5",
            dimension_name=self.DIMENSION_NAMES["dim5"],
            paper_score=paper_score,
            level=level,
            level_label=level_label,
            total_question_score=sum(question.score for question in scored_questions),
            question_count=question_count,
            sample_warning=False,
            evidence=evidence,
            warning_messages=deduped_warnings,
            counted_questions=self._select_representative_questions(scored_questions, "dim5"),
            review_question_count=review_question_count,
            score_breakdown=breakdown,
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
                    "full_reason": self._build_full_display_reason(question, dimension_code),
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

        if dimension_code == "dim5":
            level_priority = {
                "L5": 0,
                "L4": 1,
                "L3": 2,
                "L2": 3,
                "L1": 4,
            }
            knowledge_level = self._dim5_level_for_question(question)
            return (
                level_priority.get(knowledge_level, 99),
                -question.dim_scores.get(dimension_code, 0.0),
                -confidence,
                -min(len(reason), 160),
                len(warnings),
                question.page_no if question.page_no is not None else 10**9,
                self._question_no_sort_key(question.question_no),
            )

        if dimension_code == "dim4":
            level_priority = {
                "L5": 0,
                "L4": 1,
                "L3": 2,
                "L2": 3,
                "L1": 4,
            }
            dim4_level = self._dim4_level_for_question(question)
            return (
                level_priority.get(dim4_level, 99),
                -question.dim_scores.get(dimension_code, 0.0),
                -confidence,
                -min(len(reason), 160),
                len(warnings),
                question.page_no if question.page_no is not None else 10**9,
                self._question_no_sort_key(question.question_no),
            )

        return (
            -question.dim_scores.get(dimension_code, 0.0),
            -confidence,
            -min(len(reason), 160),
            len(warnings),
            question.page_no if question.page_no is not None else 10**9,
            self._question_no_sort_key(question.question_no),
        )

    @classmethod
    def _build_display_reason(cls, question: QuestionDimensionScore, dimension_code: str) -> str:
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
            return cls._format_counted_question_analysis(f"{body} 依据：{source}".strip())
        return cls._format_counted_question_analysis(body)

    @classmethod
    def _build_full_display_reason(cls, question: QuestionDimensionScore, dimension_code: str) -> str:
        return cls._format_counted_question_analysis(question.dim_reasons.get(dimension_code) or "")

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
