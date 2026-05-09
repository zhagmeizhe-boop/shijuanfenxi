"""
dim3 applicability gating.

dim3 evaluates information extraction and representation conversion burden.
It is tri-state:
- applicable
- review
- not_applicable
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

DIM3_STATUS_APPLICABLE = "applicable"
DIM3_STATUS_REVIEW = "review"
DIM3_STATUS_NOT_APPLICABLE = "not_applicable"
DIM3_REVIEW_CONFIDENCE_THRESHOLD = 0.55

INFORMATION_ROLE_VALUES = {"none", "supporting", "core"}
SOURCE_FORM_VALUES = {"text_only", "table_chart", "image_text", "multi_source"}
RELEVANT_CONDITION_COUNT_VALUES = {"1-2", "3-4", "5-6", "7+"}
DISTRACTOR_PRESSURE_VALUES = {"none", "light", "heavy"}
CONDITION_DISTRIBUTION_VALUES = {"compact", "split", "cross_sentence", "cross_modal"}
EXTRACTION_DEPTH_VALUES = {"direct", "selected", "reorganized", "inferred"}
REPRESENTATION_CONVERSION_VALUES = {
    "none",
    "direct_mapping",
    "relation_mapping",
    "model_mapping",
    "custom_model",
}
CONVERSION_STEP_COUNT_VALUES = {"0", "1", "2", "3+"}
QUANTITY_RELATION_STRUCTURE_VALUES = {"none", "single_relation", "multi_relation", "nested_relation"}
TARGET_REPRESENTATION_VALUES = {
    "none",
    "direct_formula",
    "table_list",
    "equation_relation",
    "custom_model",
}
IMAGE_DEPENDENCY_VALUES = {"none", "helpful", "required"}
TEXT_LENGTH_BAND_VALUES = {"short", "medium", "long", "very_long"}
APPLICATION_RELATION_TYPE_VALUES = {
    "work_rate",
    "queue_growth",
    "percentage_base_change",
    "concentration_mixture",
    "profit_discount",
    "ratio_allocation",
    "travel_meeting_chasing",
    "chart_table_conversion",
    "average_total",
    "equation_setup",
    "reverse_process",
    "cycle_period",
    "optimization_comparison",
    "multi_object_distribution",
    "conservation_transfer",
}
OBJECT_COUNT_BAND_VALUES = {"1", "2", "3", "4+"}
APPLICATION_COUNT_VALUES = {"0", "1", "2", "3+"}
BASE_QUANTITY_SHIFT_VALUES = {"none", "single", "multiple"}
COMPARISON_CANDIDATE_COUNT_VALUES = {"0", "2", "3+"}
DIM3_VISUAL_CATEGORIES = {"table_chart", "multi_part_layout"}
OCR_DAMAGE_MARKERS = ("残缺", "缺损", "截断", "识别失败", "公式增强识别失败")


def _normalize_choice(value: Any, allowed: set[str]) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else ""


def _normalize_choice_list(value: Any, allowed: set[str]) -> List[str]:
    if isinstance(value, str):
        raw_items: Iterable[Any] = value.replace("，", ",").replace("、", ",").split(",")
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []

    normalized: List[str] = []
    for item in raw_items:
        candidate = str(item or "").strip().lower()
        if candidate in allowed and candidate not in normalized:
            normalized.append(candidate)
    return normalized


def _normalize_zero_one(value: Any) -> int | None:
    if value in (0, "0", False):
        return 0
    if value in (1, "1", True):
        return 1
    return None


def _normalize_float(value: Any) -> float | None:
    if value in ("", None):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _non_space_length(raw_text: str) -> int:
    return len("".join(str(raw_text or "").split()))


def classify_dim3_text_length(raw_text: str) -> str:
    length = _non_space_length(raw_text)
    if length >= 120:
        return "very_long"
    if length >= 90:
        return "long"
    if length >= 45:
        return "medium"
    return "short"


def enrich_dim3_text_length_facts(raw_text: str, feature: Dict[str, Any] | None) -> Dict[str, Any]:
    enriched = dict(feature or {})
    enriched["text_length_chars"] = _non_space_length(raw_text)
    enriched["text_length_band"] = classify_dim3_text_length(raw_text)
    enriched["text_length_source"] = "local_raw_text"
    return enriched


def _audit_attr(parse_audit: Any, name: str, default: Any = None) -> Any:
    if parse_audit is None:
        return default
    if isinstance(parse_audit, dict):
        return parse_audit.get(name, default)
    return getattr(parse_audit, name, default)


def _missing_fields(feature: Dict[str, Any]) -> List[str]:
    checks = {
        "information_role": _normalize_choice(feature.get("information_role"), INFORMATION_ROLE_VALUES),
        "source_form": _normalize_choice(feature.get("source_form"), SOURCE_FORM_VALUES),
        "relevant_condition_count": _normalize_choice(
            feature.get("relevant_condition_count"),
            RELEVANT_CONDITION_COUNT_VALUES,
        ),
        "distractor_pressure": _normalize_choice(
            feature.get("distractor_pressure"),
            DISTRACTOR_PRESSURE_VALUES,
        ),
        "condition_distribution": _normalize_choice(
            feature.get("condition_distribution"),
            CONDITION_DISTRIBUTION_VALUES,
        ),
        "extraction_depth": _normalize_choice(
            feature.get("extraction_depth"),
            EXTRACTION_DEPTH_VALUES,
        ),
        "representation_conversion": _normalize_choice(
            feature.get("representation_conversion"),
            REPRESENTATION_CONVERSION_VALUES,
        ),
        "conversion_step_count": _normalize_choice(
            feature.get("conversion_step_count"),
            CONVERSION_STEP_COUNT_VALUES,
        ),
        "quantity_relation_structure": _normalize_choice(
            feature.get("quantity_relation_structure"),
            QUANTITY_RELATION_STRUCTURE_VALUES,
        ),
        "target_representation": _normalize_choice(
            feature.get("target_representation"),
            TARGET_REPRESENTATION_VALUES,
        ),
        "global_organizing_required": _normalize_zero_one(feature.get("global_organizing_required")),
        "image_dependency": _normalize_choice(feature.get("image_dependency"), IMAGE_DEPENDENCY_VALUES),
        "evidence_summary": str(feature.get("evidence_summary", "")).strip(),
    }
    return [key for key, value in checks.items() if value in ("", None)]


def _count_rank(value: str) -> int:
    return {"1-2": 1, "3-4": 2, "5-6": 3, "7+": 4}.get(value, -1)


def _conversion_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(value, -1)


def _application_count_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(str(value or "").strip(), 0)


def _object_count_rank(value: str) -> int:
    return {"1": 1, "2": 2, "3": 3, "4+": 4}.get(str(value or "").strip(), 0)


def _comparison_candidate_rank(value: str) -> int:
    return {"0": 0, "2": 2, "3+": 3}.get(str(value or "").strip(), 0)


def _has_ocr_damage_signals(parse_warnings: Iterable[str] | None) -> bool:
    for item in parse_warnings or []:
        text = str(item or "").strip()
        if text and any(marker in text for marker in OCR_DAMAGE_MARKERS):
            return True
    return False


def _feature_present(feature: Dict[str, Any]) -> bool:
    return any(
        str(feature.get(key, "")).strip()
        for key in (
            "information_role",
            "source_form",
            "relevant_condition_count",
            "distractor_pressure",
            "condition_distribution",
            "extraction_depth",
            "representation_conversion",
            "conversion_step_count",
            "quantity_relation_structure",
            "target_representation",
            "image_dependency",
            "evidence_summary",
            "application_relation_types",
            "object_count_band",
            "state_change_count",
            "implicit_relation_count",
            "base_quantity_shift",
            "comparison_candidate_count",
        )
    )


def _has_dim3_signal(raw_text: str, parse_audit: Any) -> bool:
    visual_category = str(_audit_attr(parse_audit, "visual_category", "") or "").strip()
    if visual_category in DIM3_VISUAL_CATEGORIES:
        return True
    normalized_text = str(raw_text or "")
    return any(marker in normalized_text for marker in ("统计图", "表格", "下表", "下图", "图表"))


def _has_high_burden_signal(feature: Dict[str, Any]) -> bool:
    relation_types = set(
        _normalize_choice_list(
            feature.get("application_relation_types"),
            APPLICATION_RELATION_TYPE_VALUES,
        )
    )
    return any(
        [
            _normalize_choice(feature.get("source_form"), SOURCE_FORM_VALUES) == "multi_source",
            _count_rank(
                _normalize_choice(
                    feature.get("relevant_condition_count"),
                    RELEVANT_CONDITION_COUNT_VALUES,
                )
            )
            >= 3,
            _normalize_choice(feature.get("distractor_pressure"), DISTRACTOR_PRESSURE_VALUES) == "heavy",
            _normalize_choice(
                feature.get("condition_distribution"),
                CONDITION_DISTRIBUTION_VALUES,
            )
            in {"split", "cross_sentence", "cross_modal"},
            _normalize_choice(feature.get("extraction_depth"), EXTRACTION_DEPTH_VALUES)
            in {"reorganized", "inferred"},
            _normalize_choice(
                feature.get("representation_conversion"),
                REPRESENTATION_CONVERSION_VALUES,
            )
            in {"relation_mapping", "model_mapping", "custom_model"},
            _conversion_rank(
                _normalize_choice(
                    feature.get("conversion_step_count"),
                    CONVERSION_STEP_COUNT_VALUES,
                )
            )
            >= 2,
            _normalize_choice(
                feature.get("quantity_relation_structure"),
                QUANTITY_RELATION_STRUCTURE_VALUES,
            )
            in {"multi_relation", "nested_relation"},
            _normalize_choice(
                feature.get("target_representation"),
                TARGET_REPRESENTATION_VALUES,
            )
            in {"table_list", "equation_relation", "custom_model"},
            _normalize_zero_one(feature.get("global_organizing_required")) == 1,
            _normalize_choice(feature.get("image_dependency"), IMAGE_DEPENDENCY_VALUES) == "required",
            bool(
                relation_types
                & {
                    "queue_growth",
                    "travel_meeting_chasing",
                    "profit_discount",
                    "concentration_mixture",
                    "optimization_comparison",
                    "reverse_process",
                    "conservation_transfer",
                    "multi_object_distribution",
                }
            ),
            _object_count_rank(_normalize_choice(feature.get("object_count_band"), OBJECT_COUNT_BAND_VALUES)) >= 3,
            _application_count_rank(
                _normalize_choice(feature.get("state_change_count"), APPLICATION_COUNT_VALUES)
            )
            >= 2,
            _application_count_rank(
                _normalize_choice(feature.get("implicit_relation_count"), APPLICATION_COUNT_VALUES)
            )
            >= 2,
            _normalize_choice(feature.get("base_quantity_shift"), BASE_QUANTITY_SHIFT_VALUES)
            in {"single", "multiple"},
            _comparison_candidate_rank(
                _normalize_choice(feature.get("comparison_candidate_count"), COMPARISON_CANDIDATE_COUNT_VALUES)
            )
            >= 3,
        ]
    )


def _is_low_barrier_direct_extraction(feature: Dict[str, Any]) -> bool:
    text_length_band = _normalize_choice(feature.get("text_length_band"), TEXT_LENGTH_BAND_VALUES)
    if text_length_band in {"long", "very_long"}:
        return False

    relation_types = set(
        _normalize_choice_list(
            feature.get("application_relation_types"),
            APPLICATION_RELATION_TYPE_VALUES,
        )
    )
    if relation_types - {"average_total"}:
        return False
    if (
        _object_count_rank(_normalize_choice(feature.get("object_count_band"), OBJECT_COUNT_BAND_VALUES)) >= 2
        or _application_count_rank(
            _normalize_choice(feature.get("state_change_count"), APPLICATION_COUNT_VALUES)
        )
        >= 1
        or _application_count_rank(
            _normalize_choice(feature.get("implicit_relation_count"), APPLICATION_COUNT_VALUES)
        )
        >= 1
        or _normalize_choice(feature.get("base_quantity_shift"), BASE_QUANTITY_SHIFT_VALUES)
        in {"single", "multiple"}
        or _comparison_candidate_rank(
            _normalize_choice(feature.get("comparison_candidate_count"), COMPARISON_CANDIDATE_COUNT_VALUES)
        )
        >= 2
    ):
        return False

    return (
        _normalize_choice(feature.get("source_form"), SOURCE_FORM_VALUES) in {"text_only", "table_chart", "image_text"}
        and _normalize_choice(
            feature.get("relevant_condition_count"),
            RELEVANT_CONDITION_COUNT_VALUES,
        )
        == "1-2"
        and _normalize_choice(feature.get("distractor_pressure"), DISTRACTOR_PRESSURE_VALUES) == "none"
        and _normalize_choice(
            feature.get("condition_distribution"),
            CONDITION_DISTRIBUTION_VALUES,
        )
        == "compact"
        and _normalize_choice(feature.get("extraction_depth"), EXTRACTION_DEPTH_VALUES) == "direct"
        and _normalize_choice(
            feature.get("representation_conversion"),
            REPRESENTATION_CONVERSION_VALUES,
        )
        in {"none", "direct_mapping"}
        and _normalize_choice(
            feature.get("target_representation"),
            TARGET_REPRESENTATION_VALUES,
        )
        in {"none", "direct_formula", "table_list"}
        and _normalize_choice(
            feature.get("quantity_relation_structure"),
            QUANTITY_RELATION_STRUCTURE_VALUES,
        )
        in {"none", "single_relation"}
        and _conversion_rank(
            _normalize_choice(
                feature.get("conversion_step_count"),
                CONVERSION_STEP_COUNT_VALUES,
            )
        )
        <= 1
        and _normalize_zero_one(feature.get("global_organizing_required")) == 0
    )


def _needs_visual_material(feature: Dict[str, Any], parse_audit: Any) -> bool:
    source_form = _normalize_choice(feature.get("source_form"), SOURCE_FORM_VALUES)
    image_dependency = _normalize_choice(feature.get("image_dependency"), IMAGE_DEPENDENCY_VALUES)
    visual_category = str(_audit_attr(parse_audit, "visual_category", "") or "").strip()
    return (
        image_dependency == "required"
        or source_form in {"image_text", "multi_source", "table_chart"}
        or visual_category in DIM3_VISUAL_CATEGORIES
    )


def _has_internal_conflict(feature: Dict[str, Any], parse_audit: Any) -> bool:
    information_role = _normalize_choice(feature.get("information_role"), INFORMATION_ROLE_VALUES)
    source_form = _normalize_choice(feature.get("source_form"), SOURCE_FORM_VALUES)
    condition_distribution = _normalize_choice(
        feature.get("condition_distribution"),
        CONDITION_DISTRIBUTION_VALUES,
    )
    conversion_step_count = _normalize_choice(
        feature.get("conversion_step_count"),
        CONVERSION_STEP_COUNT_VALUES,
    )
    image_dependency = _normalize_choice(feature.get("image_dependency"), IMAGE_DEPENDENCY_VALUES)
    visual_category = str(_audit_attr(parse_audit, "visual_category", "") or "").strip()

    if information_role == "none" and _has_high_burden_signal(feature):
        return True
    if (
        source_form == "multi_source"
        and condition_distribution == "compact"
        and conversion_step_count == "0"
    ):
        return True
    if image_dependency == "required" and source_form == "text_only":
        return True
    if visual_category in DIM3_VISUAL_CATEGORIES and information_role == "none":
        return True
    return False


def evaluate_dim3_applicability(
    raw_text: str,
    dim3_feature: Dict[str, Any] | None = None,
    *,
    llm_confidence: float | None = None,
    parse_audit: Any = None,
    used_image: bool = False,
    image_fallback: bool = False,
    parse_warnings: Iterable[str] | None = None,
) -> Dict[str, Any]:
    feature = enrich_dim3_text_length_facts(raw_text, dim3_feature)
    information_role = _normalize_choice(feature.get("information_role"), INFORMATION_ROLE_VALUES)
    image_dependency = _normalize_choice(feature.get("image_dependency"), IMAGE_DEPENDENCY_VALUES)
    visual_category = str(_audit_attr(parse_audit, "visual_category", "") or "").strip()
    block_completeness = _normalize_float(_audit_attr(parse_audit, "block_completeness"))
    warnings: List[str] = []

    if not _feature_present(feature) and not _has_dim3_signal(raw_text, parse_audit):
        return {
            "status": DIM3_STATUS_NOT_APPLICABLE,
            "reason": "该题没有稳定的信息提取与表示转化负担，dim3 不适用。",
            "warnings": [],
        }

    missing_fields = _missing_fields(feature)
    if missing_fields:
        warnings.append(f"dim3 缺少关键信息提取事实字段：{'、'.join(missing_fields)}。")

    feature_confidence = _normalize_float(feature.get("applicability_confidence"))
    effective_confidence = feature_confidence if feature_confidence is not None else _normalize_float(llm_confidence)
    if (
        effective_confidence is not None
        and effective_confidence < DIM3_REVIEW_CONFIDENCE_THRESHOLD
        and (information_role == "core" or _has_high_burden_signal(feature))
    ):
        warnings.append(
            f"dim3 置信度低于自动判分阈值（{DIM3_REVIEW_CONFIDENCE_THRESHOLD:.2f}）。"
        )

    if image_dependency == "required" and not used_image:
        warnings.append("dim3 依赖图片或图表，但当前未稳定使用题块图片。")
    if _needs_visual_material(feature, parse_audit) and image_fallback:
        warnings.append("dim3 依赖图表或图文材料，但当前已退回纯文本分析。")
    if _audit_attr(parse_audit, "image_required_hint", False) and not used_image:
        warnings.append("OCR 审计提示该题需要图片或图表，但当前未稳定使用图片。")
    if visual_category in DIM3_VISUAL_CATEGORIES and information_role == "none":
        warnings.append("OCR 视觉类别提示图表/多段材料题，但 dim3 标记为 none。")
    if block_completeness is not None and block_completeness < 0.65 and _needs_visual_material(feature, parse_audit):
        warnings.append("题块完整度不足，当前 dim3 结果需人工复核。")
    if _has_ocr_damage_signals(parse_warnings) and (
        information_role == "core" or _needs_visual_material(feature, parse_audit)
    ):
        warnings.append("dim3 题面存在 OCR 或图片质量问题，当前结果需人工复核。")
    if _has_internal_conflict(feature, parse_audit):
        warnings.append("dim3 信息角色与提取/转化负担特征冲突，当前结果需人工复核。")

    if warnings:
        return {
            "status": DIM3_STATUS_REVIEW,
            "reason": "dim3 提取与转化事实缺失、冲突或图表依赖不稳定，当前题目转入人工复核。",
            "warnings": list(dict.fromkeys(item for item in warnings if item)),
        }

    text_length_band = _normalize_choice(feature.get("text_length_band"), TEXT_LENGTH_BAND_VALUES)
    if information_role == "core" and text_length_band == "very_long":
        return {
            "status": DIM3_STATUS_APPLICABLE,
            "reason": "题干长度达到长应用题门槛，信息保持与条件定位构成 dim3 核心负担。",
            "warnings": [],
        }

    if information_role == "core" and not _is_low_barrier_direct_extraction(feature):
        return {
            "status": DIM3_STATUS_APPLICABLE,
            "reason": "有效条件抽取与表示转化构成该题核心门槛，dim3 适用。",
            "warnings": [],
        }

    if information_role in {"none", "supporting"} or _is_low_barrier_direct_extraction(feature):
        return {
            "status": DIM3_STATUS_NOT_APPLICABLE,
            "reason": "该题的信息提取与表示转化不是核心门槛，dim3 不适用。",
            "warnings": [],
        }

    return {
        "status": DIM3_STATUS_NOT_APPLICABLE,
        "reason": "dim3 边界题尚未形成稳定自动判分依据，当前维度不纳入自动评分。",
        "warnings": [],
    }
