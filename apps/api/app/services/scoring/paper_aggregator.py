"""
Paper-level aggregation helpers.

Current rule:
- each dimension score is the simple average of applicable question scores
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
    def _average_dimension_score(questions: List[QuestionDimensionScore], dimension_code: str) -> float:
        if not questions:
            return 0.0
        return sum(question.dim_scores.get(dimension_code, 0.0) for question in questions) / len(questions)

    def _aggregate_dim4(self, question_scores: List[QuestionDimensionScore]) -> PaperDimensionSummary:
        applicable_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, "dim4") == "applicable"
        ]
        review_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, "dim4") == "review"
        ]
        not_applicable_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, "dim4") == "not_applicable"
        ]

        level_counts = {f"L{index}": 0 for index in range(1, 6)}
        source_counts: Dict[str, int] = {}
        unknown_level_count = 0
        for question in applicable_questions:
            level = self._dim4_level_for_question(question)
            if level in level_counts:
                level_counts[level] += 1
            else:
                unknown_level_count += 1

            source = self._dim4_source_for_question(question) or "rule_score"
            source_counts[source] = source_counts.get(source, 0) + 1

        question_count = len(applicable_questions)
        review_question_count = len(review_questions)
        not_applicable_count = len(not_applicable_questions)
        l1_excluded_count = sum(1 for question in not_applicable_questions if self._dim4_is_l1_excluded(question))

        level_ratios = {
            level: round(self._ratio(count, question_count), 4)
            for level, count in level_counts.items()
        }
        breakdown = {
            "level_counts": level_counts,
            "level_ratios": level_ratios,
            "source_counts": source_counts,
            "not_applicable_count": not_applicable_count,
            "review_count": review_question_count,
            "l1_excluded_count": l1_excluded_count,
            "unknown_level_count": unknown_level_count,
            "high_level_question_count": level_counts["L4"] + level_counts["L5"],
            "aggregation_rule": "仅统计明确适用 dim4 的知识点内变式题；L1 普通模板题不进入均分。",
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
                evidence="实践创新自动评分未覆盖，未计入综合分。",
                warning_messages=[],
                counted_questions=[],
                review_question_count=review_question_count,
                score_status="not_covered",
                score_breakdown=breakdown,
            )

        score_sum = sum(question.dim_scores.get("dim4", 0.0) for question in applicable_questions)
        total_question_score = sum(question.score for question in applicable_questions)
        paper_score = score_sum / question_count
        level, level_label = self._calculate_level(paper_score)
        sample_warning = 0 < question_count < 2

        warning_messages: List[str] = []
        for question in applicable_questions:
            warning_messages.extend(question.dim_warnings.get("dim4", []))
        if review_question_count:
            warning_messages.append(f"实践创新有 {review_question_count} 道题转入人工复核，未计入均分。")
        if sample_warning:
            warning_messages.append("该维度当前样本题量偏少，整卷结论稳定性有限。")
        deduped_warnings = list(
            dict.fromkeys(message.strip() for message in warning_messages if message.strip())
        )

        evidence_parts = [
            f"共 {question_count} 道题计入实践创新均分",
            f"L3 {level_counts['L3']} 道、L4 {level_counts['L4']} 道、L5 {level_counts['L5']} 道",
            f"排除不适用题 {not_applicable_count} 道",
        ]
        if l1_excluded_count:
            evidence_parts.append(f"其中 L1 普通模板题 {l1_excluded_count} 道未计入")
        if review_question_count:
            evidence_parts.append(f"人工复核 {review_question_count} 道未计入")
        evidence_parts.append(f"题级均分 {paper_score:.1f} 分，判定为 {level_label}")
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
            counted_questions=self._select_representative_questions(applicable_questions, "dim4"),
            review_question_count=review_question_count,
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
        scored_questions: List[QuestionDimensionScore] = []
        score_sum = 0.0
        unscored_applicable_count = 0
        unknown_scored_count = 0
        unknown_unscored_count = 0
        for question in applicable_questions:
            bucket = self._dim5_bucket_for_question(question)
            bucket = bucket if bucket in bucket_counts else "unknown"
            bucket_counts[bucket] += 1
            question_score = self._valid_dim5_question_score(question)
            if question_score is None:
                unscored_applicable_count += 1
                if bucket == "unknown":
                    unknown_unscored_count += 1
                continue
            scored_questions.append(question)
            score_sum += question_score
            if bucket == "unknown":
                unknown_scored_count += 1

        question_count = len(scored_questions)
        review_question_count = len(review_questions)
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
                score_breakdown={
                    "bucket_counts": dict(bucket_counts),
                    "bucket_ratios": {},
                    "bucket_ratio_denominator": len(applicable_questions),
                    "valid_score_question_count": 0,
                    "unscored_applicable_count": unscored_applicable_count,
                    "unknown_scored_count": unknown_scored_count,
                    "unknown_unscored_count": unknown_unscored_count,
                    "aggregation_rule": "题级知识广度均分",
                },
            )

        paper_score = score_sum / question_count
        level, level_label = self._calculate_level(paper_score)

        bucket_ratio_denominator = len(applicable_questions)
        bucket_ratios = {
            bucket: round(self._ratio(count, bucket_ratio_denominator), 4)
            for bucket, count in bucket_counts.items()
        }
        breakdown = {
            "bucket_counts": dict(bucket_counts),
            "bucket_ratios": bucket_ratios,
            "bucket_ratio_denominator": bucket_ratio_denominator,
            "beyond_question_count": bucket_counts["beyond"],
            "aggregation_rule": "题级知识广度均分",
            "question_score_average": round(paper_score, 4),
            "question_score_sum": round(score_sum, 4),
            "valid_score_question_count": question_count,
            "unscored_applicable_count": unscored_applicable_count,
            "unknown_scored_count": unknown_scored_count,
            "unknown_unscored_count": unknown_unscored_count,
            "final_score": paper_score,
        }

        percentage_parts = [
            f"{self.DIM5_BUCKET_LABELS[bucket]} {bucket_ratios[bucket]:.0%}"
            for bucket in ("school", "low_gaosi", "high_gaosi", "junior_bridge", "beyond")
        ]
        evidence = (
            f"共 {question_count} 道纳入知识广度均分；"
            f"题级平均分 {paper_score:.1f} 分，判定为{level_label}。"
            f"超越篇命中 {bucket_counts['beyond']} 道；"
            f"知识来源构成：{'，'.join(percentage_parts)}。"
        )

        warning_messages: List[str] = []
        if bucket_counts["unknown"]:
            if unknown_scored_count and unknown_unscored_count:
                warning_messages.append(
                    f"有 {bucket_counts['unknown']} 道题知识来源未稳定归类；其中 "
                    f"{unknown_scored_count} 道已按题级分计入均分，"
                    f"{unknown_unscored_count} 道因缺少合法题级分未计入均分。"
                )
            elif unknown_scored_count:
                warning_messages.append(
                    f"有 {unknown_scored_count} 道题知识来源未稳定归类，但已按题级分计入知识广度均分。"
                )
            else:
                warning_messages.append(
                    f"有 {unknown_unscored_count} 道题知识来源未稳定归类，且缺少合法题级分，未计入知识广度均分。"
                )
        elif unscored_applicable_count:
            warning_messages.append(f"有 {unscored_applicable_count} 道题缺少合法题级分，未计入知识广度均分。")
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
            bucket_priority = {
                "beyond": 0,
                "junior_bridge": 1,
                "high_gaosi": 2,
                "low_gaosi": 3,
                "school": 4,
                "unknown": 5,
            }
            bucket = self._dim5_bucket_for_question(question)
            return (
                -question.dim_scores.get(dimension_code, 0.0),
                bucket_priority.get(bucket, 99),
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
