"""
报告服务

处理报告数据的获取和生成
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import logging
from sqlalchemy import select

logger = logging.getLogger(__name__)
from app.services.scoring.dim1_computation import Dim1ComputationScorer
from app.services.scoring.dim2_spatial import Dim2SpatialScorer
from app.services.scoring.dim3_information import Dim3InformationScorer
from app.services.scoring.dim4_innovation import Dim4InnovationScorer
from app.services.scoring.dim5_knowledge import Dim5KnowledgeScorer
from app.services.scoring.dim6_logic import Dim6LogicScorer
from app.services.scoring.paper_aggregator import PaperAggregator, QuestionDimensionScore


class ReportService:
    """报告服务"""

    QUESTION_DIFFICULTY_BUCKETS = [
        {
            "key": "basic",
            "label": "基础题",
            "min": None,
            "max": 4.0,
            "description": "主要检查基本概念、直接计算和常规方法。",
        },
        {
            "key": "medium",
            "label": "中等题",
            "min": 4.0,
            "max": 6.0,
            "description": "需要一定转化、综合运用或稳定的解题步骤。",
        },
        {
            "key": "hard",
            "label": "较难题",
            "min": 6.0,
            "max": None,
            "description": "更容易拉开差距，通常涉及复杂条件、方法迁移或多步推理。",
        },
    ]

    PARENT_DIFFICULTY_OPENERS = {
        1: "这张试卷整体比较基础，这是课内基础巩固型试卷，主要看孩子基础概念和常规计算是否过关。",
        2: "这张试卷难度适中，这是课内核心提升型试卷，主要看孩子能不能把学过的知识稳定用出来。",
        3: "这张试卷有一定难度，这是校内期中期末考试难度的试卷，题目有一定变化，适合检验孩子能否稳定拿到中高分。",
        4: "这张试卷难度偏高，这是小升初分班考难度的试卷，题目更绕、步骤更多，会明显考验孩子做难题的稳定性。",
        5: "这张试卷难度很高，这是奥数杯赛竞赛难度的试卷，适合看孩子能不能挑战高难题和竞赛题。",
    }

    POSITION_SUMMARIES = {
        1: "课内基础巩固型试卷，主要看孩子基础概念和常规计算是否过关。",
        2: "课内核心提升型试卷，主要看孩子能不能把学过的知识稳定用出来。",
        3: "校内期中期末考试难度试卷，题目有一定变化，适合检验孩子能否稳定拿到中高分。",
        4: "小升初分班考难度试卷，题目更绕、步骤更多，用来拉开学生差距。",
        5: "奥数杯赛竞赛难度试卷，难度很高，适合挑战高难题和竞赛题。",
    }

    PARENT_DIMENSION_DIFFICULTY_NOTES = {
        "dim1": {
            "short": "计算准确率",
            "detail": "少算错",
        },
        "dim2": {
            "short": "看图找关系",
            "detail": "看懂图形关系",
        },
        "dim3": {
            "short": "读懂题意",
            "detail": "先读懂题意",
        },
        "dim4": {
            "short": "整理条件、找到做法",
            "detail": "整理条件，找到合适做法",
        },
        "dim5": {
            "short": "知识混合使用",
            "detail": "能看出该用什么知识",
        },
        "dim6": {
            "short": "连续推理",
            "detail": "把步骤完整推下去",
        },
    }

    def __init__(self):
        self.aggregator = PaperAggregator()
        self.scorers = {
            "dim1": Dim1ComputationScorer(),
            "dim2": Dim2SpatialScorer(),
            "dim3": Dim3InformationScorer(),
            "dim4": Dim4InnovationScorer(),
            "dim5": Dim5KnowledgeScorer(),
            "dim6": Dim6LogicScorer(),
        }

    @staticmethod
    def _build_question_display_label(
        question_no: str,
        question_label_raw: Optional[str] = None,
        section_index_raw: Optional[str] = None,
    ) -> str:
        normalized_section = str(section_index_raw or "").strip()
        normalized_question_no = str(question_no or "").strip()
        if normalized_section and normalized_question_no:
            return f"{normalized_section}-{normalized_question_no}"

        normalized_raw_label = str(question_label_raw or "").strip()
        if normalized_raw_label:
            return normalized_raw_label

        return normalized_question_no

    @staticmethod
    def _dimension_scores_from_db(dim_scores) -> Dict[str, float]:
        return {
            "dim1": dim_scores.dim1_score,
            "dim2": dim_scores.dim2_score,
            "dim3": dim_scores.dim3_score,
            "dim4": dim_scores.dim4_score,
            "dim5": dim_scores.dim5_score,
            "dim6": dim_scores.dim6_score,
        }

    @staticmethod
    def _safe_json_loads(raw: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(raw or "")
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _sanitize_user_visible_text(text: object) -> str:
        normalized = str(text or "").strip()
        if not normalized:
            return ""

        replacements = {
            "建议人工复核": "建议检查",
            "需要人工复核": "需要检查",
            "需人工复核": "需检查",
            "人工复核": "检查",
            "进入复核": "自动评分未覆盖",
            "转入复核": "自动评分未覆盖",
            "复核提示": "评分提示",
            "复核": "检查",
        }
        for source, target in replacements.items():
            normalized = normalized.replace(source, target)
        return normalized

    @classmethod
    def _sanitize_report_warnings(cls, warnings: Optional[List[Any]]) -> List[str]:
        del warnings
        return []

    @staticmethod
    def _is_score_value_warning(text: str) -> bool:
        score_warning_markers = (
            "缺少明确分值",
            "未识别到明确分值",
            "分值格式无法解析",
        )
        return any(marker in text for marker in score_warning_markers)

    @staticmethod
    def _parse_warning_messages(audit_payload: Dict[str, Any]) -> List[str]:
        warnings: List[str] = []
        for item in audit_payload.get("parse_warnings", []) or []:
            text = str(item).strip()
            if text:
                warnings.append(text)
        for item in audit_payload.get("warnings", []) or []:
            text = str(item).strip()
            if text:
                warnings.append(text)
        if audit_payload.get("image_fallback"):
            warnings.append("多模态分析失败，当前题目按纯文本回退判断。")
        return list(dict.fromkeys(warnings))

    @staticmethod
    def _parse_dimension_statuses(audit_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        raw_statuses = audit_payload.get("dimension_statuses", {})
        return raw_statuses if isinstance(raw_statuses, dict) else {}

    @staticmethod
    def _build_counted_reason(score_evidence: str, audit_payload: Dict[str, Any]) -> str:
        source_parts: List[str] = []
        if audit_payload.get("used_image"):
            source_parts.append("图片")
        elif audit_payload.get("image_fallback"):
            source_parts.append("纯文本回退")
        else:
            source_parts.append("文本")

        calibration_audits = audit_payload.get("calibration_audits", {})
        if isinstance(calibration_audits, dict):
            candidates = []
            for dim_code, payload in calibration_audits.items():
                if isinstance(payload, dict) and payload.get("band_source"):
                    candidates.append(f"{dim_code}:{payload.get('band_source')}")
                elif isinstance(payload, dict) and payload.get("action"):
                    candidates.append(f"{dim_code}:{payload.get('action')}")
            if candidates:
                source_parts.append("规则:" + " / ".join(candidates[:2]))

        reason = (score_evidence or "").strip()
        source_text = f"依据来源：{' / '.join(source_parts)}。"
        if reason:
            return f"{reason} {source_text}".strip()
        return source_text

    def _build_question_scores_from_rows(
        self,
        questions,
        tag_map: Dict[str, Any],
        dim_score_rows,
    ) -> List[QuestionDimensionScore]:
        grouped_dim_rows: Dict[str, List[Any]] = {}
        for row in dim_score_rows:
            grouped_dim_rows.setdefault(row.question_id, []).append(row)

        question_scores: List[QuestionDimensionScore] = []
        for question in questions:
            qid = question.question_id
            audit_payload = self._safe_json_loads(getattr(tag_map.get(qid), "evidence_text", ""))
            rows = grouped_dim_rows.get(qid, [])
            dimension_statuses_payload = self._parse_dimension_statuses(audit_payload)

            dim_scores: Dict[str, float] = {}
            applicable_dims: List[str] = []
            dim_reasons: Dict[str, str] = {}
            dim_warnings: Dict[str, List[str]] = {}
            dim_confidences: Dict[str, float] = {}
            dim_statuses: Dict[str, str] = {}
            dim_details: Dict[str, Dict[str, Any]] = {}
            audit_warnings = self._parse_warning_messages(audit_payload)

            for row in rows:
                dim_code = getattr(row.dim_code, "value", row.dim_code)
                status_payload = dimension_statuses_payload.get(dim_code, {})
                if not isinstance(status_payload, dict):
                    status_payload = {}
                dim_status = (
                    "applicable"
                    if row.is_applicable
                    else str(status_payload.get("status", "not_applicable")).strip() or "not_applicable"
                )
                dim_statuses[dim_code] = dim_status

                combined_warnings = list(
                    dict.fromkeys(
                        audit_warnings
                        + [
                            str(item).strip()
                            for item in status_payload.get("warnings", []) or []
                            if str(item).strip()
                        ]
                    )
                )
                if combined_warnings:
                    dim_warnings[dim_code] = combined_warnings

                if row.is_applicable:
                    dim_scores[dim_code] = row.dim_score
                    applicable_dims.append(dim_code)
                    dim_reasons[dim_code] = self._build_counted_reason(row.score_evidence or "", audit_payload)
                    score_details = status_payload.get("score_details")
                    if isinstance(score_details, dict):
                        dim_details[dim_code] = score_details
                    else:
                        normalized_facts = status_payload.get("normalized_facts")
                        if isinstance(normalized_facts, dict):
                            dim_details[dim_code] = normalized_facts
                    try:
                        dim_confidences[dim_code] = float(row.confidence or 0.0)
                    except (TypeError, ValueError):
                        dim_confidences[dim_code] = 0.0
                elif dim_status in {"review", "needs_second_review"}:
                    dim_reasons[dim_code] = (
                        str(status_payload.get("reason", "")).strip()
                        or str(row.score_evidence or "").strip()
                    )
                    score_details = status_payload.get("score_details")
                    if isinstance(score_details, dict):
                        dim_details[dim_code] = score_details
                    else:
                        normalized_facts = status_payload.get("normalized_facts")
                        if isinstance(normalized_facts, dict):
                            dim_details[dim_code] = normalized_facts
                    try:
                        dim_confidences[dim_code] = float(row.confidence or 0.0)
                    except (TypeError, ValueError):
                        dim_confidences[dim_code] = 0.0
                else:
                    dim_reasons[dim_code] = (
                        str(status_payload.get("reason", "")).strip()
                        or str(row.score_evidence or "").strip()
                    )
                    score_details = status_payload.get("score_details")
                    if isinstance(score_details, dict):
                        dim_details[dim_code] = score_details
                    else:
                        normalized_facts = status_payload.get("normalized_facts")
                        if isinstance(normalized_facts, dict):
                            dim_details[dim_code] = normalized_facts
                    try:
                        dim_confidences[dim_code] = float(row.confidence or 0.0)
                    except (TypeError, ValueError):
                        dim_confidences[dim_code] = 0.0

            if dim_statuses.get("dim4") == "review":
                dim_statuses["dim4"] = "not_applicable"
                dim_reasons["dim4"] = (
                    "dim4 历史记录缺少合法 L1-L5 题级分，已自动未覆盖。"
                )
            if dim_statuses.get("dim4") == "applicable":
                try:
                    dim4_score_value = float(dim_scores.get("dim4"))
                except (TypeError, ValueError):
                    dim4_score_value = 0.0
                if dim4_score_value <= 0:
                    dim_scores.pop("dim4", None)
                    applicable_dims = [item for item in applicable_dims if item != "dim4"]
                    dim_statuses["dim4"] = "not_applicable"
                    dim_reasons["dim4"] = (
                        "dim4 历史记录缺少合法 L1-L5 题级分，已自动未覆盖。"
                    )
            if "dim4" in dim_warnings:
                dim_warnings["dim4"] = [
                    warning
                    for warning in dim_warnings["dim4"]
                    if "人工复核" not in warning and "未计入" not in warning
                ]
                if not dim_warnings["dim4"]:
                    dim_warnings.pop("dim4", None)

            question_scores.append(
                QuestionDimensionScore(
                    question_id=qid,
                    question_no=question.question_no,
                    question_label_raw=(
                        getattr(question, "question_label_raw", None)
                        or audit_payload.get("question_label_raw")
                        or question.question_no
                    ),
                    section_index_raw=(
                        getattr(question, "section_index_raw", None)
                        or audit_payload.get("section_index_raw")
                    ),
                    question_display_label=(
                        audit_payload.get("question_display_label")
                        or self._build_question_display_label(
                            question.question_no,
                            getattr(question, "question_label_raw", None)
                            or audit_payload.get("question_label_raw"),
                            getattr(question, "section_index_raw", None)
                            or audit_payload.get("section_index_raw"),
                        )
                    ),
                    score=question.score,
                    dim_scores=dim_scores,
                    applicable_dims=applicable_dims,
                    page_no=question.page_no,
                    question_summary=(audit_payload.get("analysis_facts", {}) or {}).get("core_task", "") or question.raw_text[:80],
                    dim_reasons=dim_reasons,
                    dim_warnings=dim_warnings,
                    dim_confidences=dim_confidences,
                    dim_statuses=dim_statuses,
                    dim_details=dim_details,
                )
            )

        return question_scores

    @staticmethod
    def _counted_question_lookup_keys(entry: Dict[str, Any]) -> List[tuple[str, str]]:
        keys: List[tuple[str, str]] = []
        for field_name in ("question_display_label", "question_label_raw", "question_no"):
            value = str(entry.get(field_name) or "").strip()
            if value:
                keys.append((field_name, value))
        return list(dict.fromkeys(keys))

    async def _enrich_snapshot_counted_question_full_reasons(
        self,
        db,
        paper_id: str,
        report_json: Dict[str, Any],
        Question,
        QuestionTag,
        QuestionDimScore,
    ) -> None:
        details = report_json.get("dimension_details", [])
        if not isinstance(details, list):
            return

        missing_entries: List[tuple[str, Dict[str, Any]]] = []
        for detail in details:
            if not isinstance(detail, dict):
                continue
            dim_code = str(detail.get("code") or "").strip()
            counted_questions = detail.get("counted_questions", [])
            if not dim_code or not isinstance(counted_questions, list):
                continue
            for entry in counted_questions:
                if isinstance(entry, dict) and not str(entry.get("full_reason") or "").strip():
                    missing_entries.append((dim_code, entry))

        if not missing_entries:
            return

        full_reason_lookup: Dict[tuple[str, str, str], str] = {}
        try:
            question_result = await db.execute(
                select(Question)
                .where(Question.paper_id == paper_id)
                .order_by(Question.page_no.asc(), Question.question_no.asc())
            )
            questions = question_result.scalars().all()

            tag_result = await db.execute(
                select(QuestionTag)
                .join(Question, Question.question_id == QuestionTag.question_id)
                .where(Question.paper_id == paper_id)
            )
            tag_map = {row.question_id: row for row in tag_result.scalars().all()}

            dim_row_result = await db.execute(
                select(QuestionDimScore)
                .join(Question, Question.question_id == QuestionDimScore.question_id)
                .where(Question.paper_id == paper_id)
            )
            dim_score_rows = dim_row_result.scalars().all()

            if questions and dim_score_rows:
                rebuilt_question_scores = self._build_question_scores_from_rows(
                    questions,
                    tag_map,
                    dim_score_rows,
                )
                aggregated = self.aggregator.aggregate_all_dimensions(rebuilt_question_scores)
                for dim_code, summary in aggregated.items():
                    for entry in summary.counted_questions:
                        if not isinstance(entry, dict):
                            continue
                        full_reason = str(
                            entry.get("full_reason") or entry.get("reason") or entry.get("summary") or ""
                        ).strip()
                        if not full_reason:
                            continue
                        for field_name, value in self._counted_question_lookup_keys(entry):
                            full_reason_lookup[(dim_code, field_name, value)] = full_reason
        except Exception as exc:
            logger.warning(
                "补齐报告快照计入题目完整分析失败 paper=%s: %s",
                paper_id,
                exc,
                exc_info=True,
            )

        for dim_code, entry in missing_entries:
            full_reason = ""
            for field_name, value in self._counted_question_lookup_keys(entry):
                full_reason = full_reason_lookup.get((dim_code, field_name, value), "")
                if full_reason:
                    break
            entry["full_reason"] = full_reason or str(
                entry.get("reason") or entry.get("summary") or ""
            ).strip()

    @staticmethod
    def _merge_dimension_report_warnings(
        aggregated: Dict[str, Any],
        report_warnings: Optional[List[str]],
    ) -> List[str]:
        del aggregated
        return ReportService._sanitize_report_warnings(report_warnings)

    def _build_dimension_details_from_aggregated(self, aggregated: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {
                "code": dim_code,
                "name": summary.dimension_name,
                "score": round(summary.paper_score, 1),
                "level": summary.level,
                "level_label": summary.level_label,
                "score_status": getattr(summary, "score_status", "scored"),
                "evidence": summary.evidence,
                "warning": bool(
                    getattr(summary, "score_status", "scored") == "scored"
                    and (summary.warning_messages or summary.sample_warning)
                ),
                "counted_questions": summary.counted_questions,
                "score_breakdown": getattr(summary, "score_breakdown", {}),
            }
            for dim_code, summary in aggregated.items()
        ]

    @staticmethod
    def _safe_float_value(value: Any) -> Optional[float]:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed

    @staticmethod
    def _get_question_field(question_score: Any, field_name: str, default: Any = None) -> Any:
        if isinstance(question_score, dict):
            return question_score.get(field_name, default)
        return getattr(question_score, field_name, default)

    @staticmethod
    def _normalize_question_short_label(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        text = text.replace("（", "(").replace("）", ")").strip()
        section_match = re.match(r"^[第\s]*[一二三四五六七八九十百千万零〇]+[部分卷题组]*[-－—]\s*(.+)$", text)
        if section_match:
            text = section_match.group(1).strip()

        bracket_match = re.match(r"^[\(（\[\【]\s*(.+?)\s*[\)）\]\】]$", text)
        if bracket_match:
            text = bracket_match.group(1).strip()

        question_match = re.match(r"^第\s*(.+?)\s*题$", text)
        if question_match:
            text = question_match.group(1).strip()

        text = re.sub(r"[\s\.．、，,。:：]+$", "", text).strip()
        return text

    @classmethod
    def _question_distribution_item(cls, question_score: Any, average_score: float) -> Dict[str, Any]:
        question_no = str(cls._get_question_field(question_score, "question_no", "") or "").strip()
        question_label_raw = str(
            cls._get_question_field(question_score, "question_label_raw", "") or ""
        ).strip()
        section_index_raw = str(
            cls._get_question_field(question_score, "section_index_raw", "") or ""
        ).strip()
        explicit_display_label = str(
            cls._get_question_field(question_score, "question_display_label", "") or ""
        ).strip()
        question_display_label = (
            explicit_display_label
            or ReportService._build_question_display_label(
                question_no,
                question_label_raw or None,
                section_index_raw or None,
            )
        )
        question_short_label = (
            cls._normalize_question_short_label(question_display_label)
            or cls._normalize_question_short_label(question_label_raw)
            or cls._normalize_question_short_label(question_no)
            or question_display_label
        )

        return {
            "page_no": cls._get_question_field(question_score, "page_no"),
            "question_no": question_no,
            "question_label_raw": question_label_raw,
            "section_index_raw": section_index_raw,
            "question_display_label": question_display_label,
            "question_short_label": question_short_label,
            "average_score": round(average_score, 1),
        }

    @classmethod
    def _question_distribution_sort_key(cls, item: Dict[str, Any]) -> tuple:
        page_no = item.get("page_no")
        try:
            normalized_page_no = int(page_no)
        except (TypeError, ValueError):
            normalized_page_no = 10**9
        label = str(item.get("question_display_label") or item.get("question_no") or "")
        return (normalized_page_no, PaperAggregator._question_no_sort_key(label), label)

    @classmethod
    def _bucket_for_question_average(cls, average_score: float) -> Optional[str]:
        for bucket in cls.QUESTION_DIFFICULTY_BUCKETS:
            min_score = bucket["min"]
            max_score = bucket["max"]
            if min_score is not None and average_score <= float(min_score):
                continue
            if max_score is not None and average_score > float(max_score):
                continue
            return str(bucket["key"])
        return None

    @classmethod
    def _build_question_distribution(
        cls,
        question_scores: Optional[List[Any]],
    ) -> Dict[str, Any]:
        buckets = [
            {
                "key": bucket["key"],
                "label": bucket["label"],
                "description": bucket["description"],
                "count": 0,
                "percentage": 0.0,
                "questions": [],
            }
            for bucket in cls.QUESTION_DIFFICULTY_BUCKETS
        ]
        bucket_by_key = {str(bucket["key"]): bucket for bucket in buckets}

        unclassified_count = 0
        total_count = 0
        for question_score in question_scores or []:
            total_count += 1
            raw_dim_scores = cls._get_question_field(question_score, "dim_scores", {}) or {}
            dim_scores = raw_dim_scores if isinstance(raw_dim_scores, dict) else {}
            raw_applicable_dims = cls._get_question_field(question_score, "applicable_dims", []) or []
            applicable_dims = [
                str(dim_code)
                for dim_code in raw_applicable_dims
                if str(dim_code).strip()
            ]
            if not applicable_dims:
                applicable_dims = [str(dim_code) for dim_code in dim_scores.keys()]

            score_values: List[float] = []
            for dim_code in applicable_dims:
                if dim_code not in dim_scores:
                    continue
                score_value = cls._safe_float_value(dim_scores.get(dim_code))
                if score_value is None:
                    continue
                score_values.append(score_value)

            if not score_values:
                unclassified_count += 1
                continue

            average_score = sum(score_values) / len(score_values)
            bucket_key = cls._bucket_for_question_average(average_score)
            if not bucket_key or bucket_key not in bucket_by_key:
                unclassified_count += 1
                continue

            bucket = bucket_by_key[bucket_key]
            bucket["questions"].append(cls._question_distribution_item(question_score, average_score))

        classified_count = 0
        for bucket in buckets:
            bucket["questions"] = sorted(bucket["questions"], key=cls._question_distribution_sort_key)
            bucket["count"] = len(bucket["questions"])
            classified_count += bucket["count"]

        for bucket in buckets:
            bucket["percentage"] = (
                round(bucket["count"] / classified_count * 100, 1)
                if classified_count
                else 0.0
            )

        return {
            "basis": "question_count",
            "classification": "average_applicable_dimension_score",
            "total_count": total_count,
            "classified_count": classified_count,
            "unclassified_count": unclassified_count,
            "buckets": buckets,
        }

    @staticmethod
    def _join_chinese_phrases(items: List[str]) -> str:
        normalized = [str(item).strip() for item in items if str(item).strip()]
        if not normalized:
            return ""
        if len(normalized) == 1:
            return normalized[0]
        return "、".join(normalized)

    @staticmethod
    def _join_parent_summary_phrases(items: List[str]) -> str:
        normalized = [str(item).strip() for item in items if str(item).strip()]
        if not normalized:
            return ""
        if len(normalized) == 1:
            return normalized[0]
        if len(normalized) == 2:
            return f"{normalized[0]}和{normalized[1]}"
        return f"{'、'.join(normalized[:-1])}和{normalized[-1]}"

    @staticmethod
    def _join_parent_summary_requirements(items: List[str]) -> str:
        normalized = [str(item).strip() for item in items if str(item).strip()]
        if not normalized:
            return ""
        if len(normalized) == 1:
            return normalized[0]
        if len(normalized) == 2:
            return f"{normalized[0]}，并{normalized[1]}"
        return f"{'，'.join(normalized[:-1])}，并{normalized[-1]}"

    @classmethod
    def _parent_summary_structure_intro(
        cls,
        question_distribution: Optional[Dict[str, Any]],
    ) -> str:
        if isinstance(question_distribution, dict):
            buckets = question_distribution.get("buckets")
            if isinstance(buckets, list):
                for bucket in buckets:
                    if not isinstance(bucket, dict) or bucket.get("key") != "hard":
                        continue
                    percentage = cls._safe_float_value(bucket.get("percentage"))
                    if percentage is not None:
                        return f"从题目结构看，较难题约占 {percentage:.1f}%。"
        return "从题目结构看，暂时没有足够的题目难度结构数据。"

    @classmethod
    def _build_parent_summary(
        cls,
        difficulty_level: int,
        dimension_details: List[Dict[str, Any]],
        question_distribution: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        opening = cls.PARENT_DIFFICULTY_OPENERS.get(
            difficulty_level,
            "这张试卷有一定挑战，基础题之外会有一些需要整理条件、转一步弯或综合运用的题。",
        )

        scored_dimensions = []
        for detail in dimension_details:
            level = cls._safe_float_value(detail.get("level"))
            if detail.get("score_status", "scored") != "scored" or level is None or level <= 0:
                continue
            score = cls._safe_float_value(detail.get("score"))
            if score is None:
                continue
            code = str(detail.get("code") or "")
            if code not in cls.PARENT_DIMENSION_DIFFICULTY_NOTES:
                continue
            scored_dimensions.append((score, code))

        dimension_order = {
            code: index
            for index, code in enumerate(PaperAggregator.DIMENSION_NAMES.keys())
        }
        scored_dimensions.sort(
            key=lambda item: (-item[0], dimension_order.get(item[1], 999))
        )
        high_dimensions = [code for score, code in scored_dimensions if score >= 6.0]
        structure_intro = cls._parent_summary_structure_intro(question_distribution)

        if not scored_dimensions or not high_dimensions:
            return [
                opening,
                f"{structure_intro}整体没有特别突出的卡点，重点看孩子能不能稳定完成基础题和中等题。",
            ]

        top_dimensions = high_dimensions[:3]
        short_topics = cls._join_parent_summary_phrases(
            [cls.PARENT_DIMENSION_DIFFICULTY_NOTES[code]["short"] for code in top_dimensions]
        )
        detail_topics = cls._join_parent_summary_requirements(
            [cls.PARENT_DIMENSION_DIFFICULTY_NOTES[code]["detail"] for code in top_dimensions]
        )
        second_sentence = f"{structure_intro}主要卡点在{short_topics}：孩子要{detail_topics}。"
        return [opening, second_sentence]

    @classmethod
    def _ensure_difficulty_position_extensions(
        cls,
        report_json: Dict[str, Any],
        question_scores: Optional[List[Any]] = None,
    ) -> None:
        position = report_json.setdefault("difficulty_position", {})
        if not isinstance(position, dict):
            position = {}
            report_json["difficulty_position"] = position

        try:
            difficulty_level = int(position.get("level") or 0)
        except (TypeError, ValueError):
            difficulty_level = 0
        dimension_details = report_json.get("dimension_details", [])
        if not isinstance(dimension_details, list):
            dimension_details = []

        question_distribution = position.get("question_distribution")
        if not isinstance(question_distribution, dict):
            question_distribution = cls._build_question_distribution(question_scores)
            position["question_distribution"] = question_distribution

        position_summary = position.get("position_summary")
        if not isinstance(position_summary, str) or not position_summary.strip():
            position["position_summary"] = cls._get_position_summary(difficulty_level)

        parent_summary = position.get("parent_summary")
        if not (
            isinstance(parent_summary, list)
            and len([item for item in parent_summary if str(item).strip()]) >= 2
        ):
            position["parent_summary"] = cls._build_parent_summary(
                difficulty_level,
                dimension_details,
                question_distribution,
            )

    async def _load_question_scores_from_db(
        self,
        db,
        paper_id: str,
        Question,
        QuestionTag,
        QuestionDimScore,
    ) -> List[QuestionDimensionScore]:
        question_result = await db.execute(
            select(Question)
            .where(Question.paper_id == paper_id)
            .order_by(Question.page_no.asc(), Question.question_no.asc())
        )
        questions = question_result.scalars().all()

        tag_result = await db.execute(
            select(QuestionTag)
            .join(Question, Question.question_id == QuestionTag.question_id)
            .where(Question.paper_id == paper_id)
        )
        tag_map = {row.question_id: row for row in tag_result.scalars().all()}

        dim_row_result = await db.execute(
            select(QuestionDimScore)
            .join(Question, Question.question_id == QuestionDimScore.question_id)
            .where(Question.paper_id == paper_id)
        )
        dim_score_rows = dim_row_result.scalars().all()

        if not questions or not dim_score_rows:
            return []
        return self._build_question_scores_from_rows(
            questions,
            tag_map,
            dim_score_rows,
        )

    def _build_report_payload(
        self,
        *,
        paper_id: str,
        paper_title: str,
        dimension_details: List[Dict[str, Any]],
        question_scores: Optional[List[Any]] = None,
        generated_at: Optional[str] = None,
        report_warnings: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        valid_dimension_details = [
            detail
            for detail in dimension_details
            if detail.get("score_status", "scored") == "scored" and detail["level"] > 0
        ]
        overall_score = (
            sum(detail["score"] for detail in valid_dimension_details) / len(valid_dimension_details)
            if valid_dimension_details
            else 0.0
        )
        difficulty_level = self._calculate_difficulty_level(overall_score)
        detail_by_code = {detail["code"]: detail for detail in dimension_details}
        question_distribution = self._build_question_distribution(question_scores)
        parent_summary = self._build_parent_summary(
            difficulty_level,
            dimension_details,
            question_distribution,
        )

        return {
            "report_id": paper_id,
            "paper_id": paper_id,
            "paper_title": paper_title,
            "generated_at": generated_at or datetime.now().isoformat(),
            "dimensions": {
                "computation": round(detail_by_code.get("dim1", {}).get("score", 0.0) * 10, 1),
                "concept": round(detail_by_code.get("dim2", {}).get("score", 0.0) * 10, 1),
                "logic": round(detail_by_code.get("dim3", {}).get("score", 0.0) * 10, 1),
                "spatial": round(detail_by_code.get("dim4", {}).get("score", 0.0) * 10, 1),
                "application": round(detail_by_code.get("dim5", {}).get("score", 0.0) * 10, 1),
                "innovation": round(detail_by_code.get("dim6", {}).get("score", 0.0) * 10, 1),
            },
            "dimension_details": dimension_details,
            "report_warnings": self._sanitize_report_warnings(report_warnings),
            "difficulty_position": {
                "level": difficulty_level,
                "label": self._get_difficulty_label(difficulty_level),
                "overall_score": round(overall_score, 1),
                "position_summary": self._get_position_summary(difficulty_level),
                "target_students": self._get_target_students(difficulty_level),
                "description": self._get_difficulty_description(difficulty_level),
                "parent_summary": parent_summary,
                "question_distribution": question_distribution,
                "dimension_distribution": [
                    {"code": "dim1", "name": "计算难度", "percentage": 17, "color": "#3B82F6"},
                    {"code": "dim2", "name": "几何难度", "percentage": 16, "color": "#8B5CF6"},
                    {"code": "dim3", "name": "读题难度", "percentage": 17, "color": "#EC4899"},
                    {"code": "dim4", "name": "解题方法难度", "percentage": 17, "color": "#10B981"},
                    {"code": "dim5", "name": "知识门槛难度", "percentage": 16, "color": "#F59E0B"},
                    {"code": "dim6", "name": "解题链路难度", "percentage": 17, "color": "#EF4444"},
                ],
            },
            "benchmark_comparisons": [],
            "knowledge_points": [],
            "representative_questions": [],
            "overall_summary": (
                f"本试卷综合难度为{self._get_difficulty_label(difficulty_level)}，"
                f"综合评分{round(overall_score, 1)}分。"
            ),
            "recommendations": [
                "根据各维度得分情况，有针对性地进行复习和训练",
                "重点关注得分较低的维度，加强相关知识点的学习",
                "适当练习高难度题目，提升综合解题能力",
            ],
        }

    @staticmethod
    def _score_to_dimension_level(score: float) -> tuple[int, str]:
        if score <= 0:
            return 0, "N/A"
        if score <= 2.0:
            return 1, "简单"
        if score <= 4.0:
            return 2, "较简单"
        if score <= 6.0:
            return 3, "中等"
        if score <= 8.0:
            return 4, "较难"
        return 5, "困难"

    async def get_report_data(self, paper_id: str) -> Optional[Dict[str, Any]]:
        """
        从数据库读取真实报告数据

        Args:
            paper_id: 试卷ID（前端上传后导航使用的 ID）

        Returns:
            Dict: 报告数据，格式与前端 FullReportData 匹配；未找到时返回 None
        """
        from app.core.database import AsyncSessionLocal
        from app.models import Paper, PaperDimScore, Question, QuestionDimScore, QuestionTag, ReportSnapshot

        async with AsyncSessionLocal() as db:
            paper = await db.get(Paper, paper_id)
            if not paper:
                return None

            try:
                snapshot_result = await db.execute(
                    select(ReportSnapshot)
                    .where(ReportSnapshot.paper_id == paper_id)
                    .order_by(ReportSnapshot.created_at.desc())
                )
                latest_snapshot = snapshot_result.scalars().first()
            except Exception as exc:
                latest_snapshot = None
                logger.warning("读取报告快照失败 paper=%s: %s", paper_id, exc, exc_info=True)

            if latest_snapshot and isinstance(latest_snapshot.report_json, dict):
                report_json = dict(latest_snapshot.report_json)
                report_json.setdefault("report_id", latest_snapshot.report_id)
                report_json.setdefault("paper_id", paper_id)
                report_json["paper_title"] = paper.paper_name
                report_json.setdefault("generated_at", latest_snapshot.created_at.isoformat())
                report_json.setdefault("benchmark_comparisons", [])
                report_json.setdefault("knowledge_points", [])
                report_json.setdefault("representative_questions", [])
                report_json["report_warnings"] = []
                for detail in report_json.get("dimension_details", []):
                    detail.setdefault("counted_questions", [])
                    detail.setdefault(
                        "score_status",
                        "not_covered" if int(detail.get("level") or 0) <= 0 else "scored",
                    )
                    if detail.get("score_status") == "not_covered":
                        detail["warning"] = False
                    detail["warning"] = bool(detail.get("warning"))
                rebuilt_question_scores = []
                snapshot_position = report_json.get("difficulty_position", {})
                if not isinstance(snapshot_position, dict) or not isinstance(
                    snapshot_position.get("question_distribution"),
                    dict,
                ):
                    try:
                        rebuilt_question_scores = await self._load_question_scores_from_db(
                            db,
                            paper_id,
                            Question,
                            QuestionTag,
                            QuestionDimScore,
                        )
                    except Exception as exc:
                        logger.warning(
                            "补齐报告快照题目难度分布失败 paper=%s: %s",
                            paper_id,
                            exc,
                            exc_info=True,
                        )
                await self._enrich_snapshot_counted_question_full_reasons(
                    db,
                    paper_id,
                    report_json,
                    Question,
                    QuestionTag,
                    QuestionDimScore,
                )
                self._ensure_difficulty_position_extensions(report_json, rebuilt_question_scores)
                return report_json

            dim_scores = await db.get(PaperDimScore, paper_id)
            if not dim_scores:
                # 试卷存在但评分尚未完成
                return None
            rebuilt_question_scores = await self._load_question_scores_from_db(
                db,
                paper_id,
                Question,
                QuestionTag,
                QuestionDimScore,
            )

        if rebuilt_question_scores:
            aggregated = self.aggregator.aggregate_all_dimensions(rebuilt_question_scores)
            dimension_details = self._build_dimension_details_from_aggregated(aggregated)
            return self._build_report_payload(
                paper_id=paper_id,
                paper_title=paper.paper_name,
                dimension_details=dimension_details,
                question_scores=rebuilt_question_scores,
                report_warnings=self._merge_dimension_report_warnings(aggregated, []),
            )

        scores = self._dimension_scores_from_db(dim_scores)
        dimension_details = []
        for dim_code, summary_score in scores.items():
            level, level_label = self._score_to_dimension_level(summary_score)
            dimension_details.append(
                {
                    "code": dim_code,
                    "name": self.aggregator.DIMENSION_NAMES[dim_code],
                    "score": round(summary_score, 1),
                    "level": level,
                    "level_label": level_label,
                    "score_status": "scored" if level > 0 else "not_covered",
                    "evidence": "",
                    "warning": False,
                    "counted_questions": [],
                }
            )
        return self._build_report_payload(
            paper_id=paper_id,
            paper_title=paper.paper_name,
            dimension_details=dimension_details,
            question_scores=[],
            report_warnings=[],
        )

    def _generate_mock_report(self, report_id: str) -> Dict[str, Any]:
        """生成Mock报告数据"""
        return {
            "report_id": report_id,
            "paper_id": "paper-001",
            "paper_title": "2024年春季六年级数学分班考试卷",
            "generated_at": datetime.now().isoformat(),

            "dimensions": {
                "computation": 75,
                "concept": 82,
                "logic": 68,
                "spatial": 70,
                "application": 65,
                "innovation": 58,
            },

            "dimension_details": [
                {
                    "code": "dim1",
                    "name": "计算难度",
                    "score": 7.5,
                    "level": 4,
                    "level_label": "较难",
                    "evidence": "数值类型为带分数/小数混合，运算层数为3-4层，无变形难度，特殊运算包含分数小数互化，易错程度为中等。基础分7.0，因分数小数互化+0.5。",
                },
                {
                    "code": "dim2",
                    "name": "几何难度",
                    "score": 6.0,
                    "level": 3,
                    "level_label": "中等",
                    "evidence": "图形熟悉度为标准图形，需要添加1条辅助线，图形变换包含单一变换，空间重构程度为中等。非强制规则判定。",
                },
                {
                    "code": "dim3",
                    "name": "读题难度",
                    "score": 8.0,
                    "level": 4,
                    "level_label": "较难",
                    "evidence": "需要读懂图文材料中的对象、规则和对应关系，场景理解负担较高。",
                },
                {
                    "code": "dim4",
                    "name": "解题方法难度",
                    "score": 7.0,
                    "level": 4,
                    "level_label": "较难",
                    "evidence": "读懂后还需要整理条件、构造中间量并组织解题路径，建模解题负担较高。",
                },
                {
                    "code": "dim5",
                    "name": "知识门槛难度",
                    "score": 5.5,
                    "level": 3,
                    "level_label": "中等",
                    "evidence": "最高知识点学段：六年级上册，基础分4.5；去重知识点数：5个，修正分+0.5；因知识点数量达到4-6个，判定为中等水平。",
                    "warning": True,
                },
                {
                    "code": "dim6",
                    "name": "解题链路难度",
                    "score": 8.5,
                    "level": 5,
                    "level_label": "困难",
                    "evidence": "关键步骤数4-5，基础分7.0；存在隐藏关系+0.5，需要反向推理+0.5，需要验证+0.5；因存在分支讨论，最低分限制为6.5。最终得分8.5。",
                },
            ],

            "difficulty_position": {
                "level": 4,
                "label": "选拔卷",
                "overall_score": 7.1,
                "position_summary": "小升初分班考难度试卷，题目更绕、步骤更多，用来拉开学生差距。",
                "target_students": "适合基础扎实、需要面向选拔场景提升综合稳定性的学生。",
                "description": "面向选拔区分阶段，突出多步推进、策略迁移与复杂问题收束。",
                "parent_summary": [
                    "这张试卷难度偏高，这是小升初分班考难度的试卷，题目更绕、步骤更多，会明显考验孩子做难题的稳定性。",
                    "从题目结构看，较难题约占 50.0%。主要卡点在计算准确率、知识混合使用和连续推理：孩子要少算错，能看出该用什么知识，并把步骤完整推下去。",
                ],
                "question_distribution": {
                    "basis": "question_count",
                    "classification": "average_applicable_dimension_score",
                    "total_count": 10,
                    "classified_count": 10,
                    "unclassified_count": 0,
                    "buckets": [
                        {
                            "key": "basic",
                            "label": "基础题",
                            "description": "主要检查基本概念、直接计算和常规方法。",
                            "count": 2,
                            "percentage": 20.0,
                            "questions": [
                                {"question_no": "1", "question_display_label": "1", "average_score": 3.5},
                                {"question_no": "2", "question_display_label": "2", "average_score": 4.0},
                            ],
                        },
                        {
                            "key": "medium",
                            "label": "中等题",
                            "description": "需要一定转化、综合运用或稳定的解题步骤。",
                            "count": 3,
                            "percentage": 30.0,
                            "questions": [
                                {"question_no": "3", "question_display_label": "3", "average_score": 5.0},
                                {"question_no": "4", "question_display_label": "4", "average_score": 5.5},
                                {"question_no": "5", "question_display_label": "5", "average_score": 6.0},
                            ],
                        },
                        {
                            "key": "hard",
                            "label": "较难题",
                            "description": "更容易拉开差距，通常涉及复杂条件、方法迁移或多步推理。",
                            "count": 5,
                            "percentage": 50.0,
                            "questions": [
                                {"question_no": "6", "question_display_label": "6", "average_score": 6.5},
                                {"question_no": "7", "question_display_label": "7", "average_score": 7.0},
                                {"question_no": "8", "question_display_label": "8", "average_score": 7.5},
                                {"question_no": "9", "question_display_label": "9", "average_score": 8.0},
                                {"question_no": "10", "question_display_label": "10", "average_score": 8.5},
                            ],
                        },
                    ],
                },
                "dimension_distribution": [
                    {"code": "dim1", "name": "计算难度", "percentage": 18, "color": "#3B82F6"},
                    {"code": "dim2", "name": "几何难度", "percentage": 16, "color": "#8B5CF6"},
                    {"code": "dim3", "name": "读题难度", "percentage": 20, "color": "#EC4899"},
                    {"code": "dim4", "name": "解题方法难度", "percentage": 14, "color": "#10B981"},
                    {"code": "dim5", "name": "知识门槛难度", "percentage": 16, "color": "#F59E0B"},
                    {"code": "dim6", "name": "解题链路难度", "percentage": 16, "color": "#EF4444"},
                ],
            },

            "benchmark_comparisons": [
                {"name": "区平均分", "score": 6.2, "comparison": "higher", "difference": 0.9},
                {"name": "市重点班", "score": 7.5, "comparison": "lower", "difference": 0.4},
                {"name": "省实验班", "score": 8.1, "comparison": "lower", "difference": 1.0},
            ],

            "knowledge_points": [
                {"id": "kp1", "name": "分数运算", "level": "六年级上册", "count": 5, "related_questions": ["Q1", "Q2", "Q5"]},
                {"id": "kp2", "name": "比和比例", "level": "六年级上册", "count": 3, "related_questions": ["Q3", "Q7"]},
                {"id": "kp3", "name": "圆的认识", "level": "六年级上册", "count": 4, "related_questions": ["Q4", "Q6", "Q8"]},
                {"id": "kp4", "name": "百分数应用", "level": "六年级下册", "count": 2, "related_questions": ["Q9"]},
                {"id": "kp5", "name": "圆柱圆锥", "level": "六年级下册", "count": 3, "related_questions": ["Q10", "Q11"]},
            ],

            "representative_questions": [
                {
                    "id": "Q1",
                    "question_no": "第1题",
                    "content": "计算：\\frac{3}{4} + \\frac{2}{5} - \\frac{1}{2}",
                    "dimension_code": "dim1",
                    "dimension_name": "计算难度",
                    "score": 7.5,
                    "level": 4,
                    "evidence": "分数运算，需要通分，复杂度中等",
                },
                {
                    "id": "Q3",
                    "question_no": "第3题",
                    "content": "甲、乙两数的比是3:5，它们的和是48，求这两个数。",
                    "dimension_code": "dim3",
                    "dimension_name": "读题难度",
                    "score": 8.0,
                    "level": 4,
                    "evidence": "需要读懂文字条件中对象与问题要求的对应关系",
                },
            ],

            "overall_summary": "本试卷整体难度较高，以拔高为主，重点看知识门槛、解题方法组织和解题链路推进能力。计算部分以分数运算为主，几何部分涉及空间判断，读题部分强调规则、过程和比较口径的理解。",
            "recommendations": [
                "建议学生重点复习分数运算和比例应用",
                "加强场景规则理解、条件整理和建模解题训练",
                "适当拓展几何辅助线的添加技巧",
                "关注实际应用题的解题策略",
            ],
        }

    async def generate_report_from_paper(
        self,
        paper_id: str,
        question_scores: List[Dict[str, Any]],
        paper_title: Optional[str] = None,
        dim5_override=None,
        report_warnings: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        从试卷和题目分数生成完整报告

        Args:
            paper_id: 试卷ID
            question_scores: 题目分数列表（六个维度均按题级评分后统一聚合）
            paper_title: 试卷标题
            dim5_override: 兼容旧调用的 dim5 覆盖结果；当前主链路不再依赖

        Returns:
            Dict: 完整报告数据
        """
        from app.services.scoring.paper_aggregator import PaperDimensionSummary

        # 汇总各维度分数
        aggregated = self.aggregator.aggregate_all_dimensions(question_scores)

        # 用试卷级 dim5 覆盖聚合结果
        if dim5_override is not None:
            aggregated["dim5"] = PaperDimensionSummary(
                dimension_code="dim5",
                dimension_name="知识门槛难度",
                paper_score=dim5_override.score,
                level=dim5_override.level,
                level_label=dim5_override.level_label,
                total_question_score=0.0,
                question_count=0,
                sample_warning=False,
                evidence=dim5_override.evidence,
                warning_messages=[],
                counted_questions=[],
            )

        dimension_details = self._build_dimension_details_from_aggregated(aggregated)
        report = self._build_report_payload(
            paper_id=paper_id,
            paper_title=paper_title or f"试卷 {paper_id}",
            dimension_details=dimension_details,
            question_scores=question_scores,
            generated_at=datetime.now().isoformat(),
            report_warnings=self._merge_dimension_report_warnings(aggregated, report_warnings or []),
        )
        report["report_id"] = f"rpt-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        return report

    def _calculate_difficulty_level(self, overall_score: float) -> int:
        """计算难度等级"""
        if overall_score <= 2.0:
            return 1
        elif overall_score <= 4.0:
            return 2
        elif overall_score <= 6.0:
            return 3
        elif overall_score <= 7.0:
            return 4
        else:
            return 5

    def _get_difficulty_label(self, level: int) -> str:
        """获取难度标签"""
        labels = {
            1: "基础卷",
            2: "提升卷",
            3: "拔高卷",
            4: "选拔卷",
            5: "竞赛卷",
        }
        return labels.get(level, "未知")

    @classmethod
    def _get_position_summary(cls, level: int) -> str:
        """获取试卷定位简述"""
        return cls.POSITION_SUMMARIES.get(level, "")

    def _get_target_students(self, level: int) -> str:
        """获取目标学生描述"""
        descriptions = {
            1: "适合基础薄弱、需要巩固基本概念的学生。",
            2: "适合基础一般、希望从课内掌握走向稳定提升的学生。",
            3: "适合基础较好、需要强化综合运用和拔高训练的学生。",
            4: "适合基础扎实、需要面向选拔场景提升综合稳定性的学生。",
            5: "适合成绩优秀、准备挑战竞赛或高强度选拔的学生。",
        }
        return descriptions.get(level, "")

    def _get_difficulty_description(self, level: int) -> str:
        """获取难度描述"""
        descriptions = {
            1: "侧重基础知识的掌握和基本技能的训练",
            2: "注重知识覆盖、基本应用和稳定解题能力",
            3: "强调知识的灵活运用、综合解题和方法迁移",
            4: "突出选拔场景下的复杂问题解决和稳定区分度",
            5: "挑战竞赛型高难思维、跨模块综合和极限解题技巧",
        }
        return descriptions.get(level, "")
