"""
dim4 applicability gating.

dim4 evaluates topic-internal practice innovation. It is tri-state:
- applicable
- review
- not_applicable
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from app.services.scoring.dim4_topic_levels import (
    calibrate_dim4_competition_variant_level,
    normalize_dim4_level,
    normalize_dim4_level_source,
)

DIM4_STATUS_APPLICABLE = "applicable"
DIM4_STATUS_REVIEW = "review"
DIM4_STATUS_NOT_APPLICABLE = "not_applicable"
DIM4_REVIEW_CONFIDENCE_THRESHOLD = 0.55

STRATEGY_ROLE_VALUES = {"none", "supporting", "core"}
TEMPLATE_FIT_VALUES = {"direct", "adapted", "reframed", "non_routine"}
BREAKTHROUGH_TYPE_VALUES = {
    "none",
    "local_trick",
    "strategy_shift",
    "constructive",
    "exploratory_search",
}
STRATEGY_SHIFT_COUNT_VALUES = {"0", "1", "2", "3+"}
CONSTRUCTION_REQUIREMENT_VALUES = {
    "none",
    "simple_setup",
    "case_construction",
    "custom_construction",
}
EXPLORATION_SPACE_VALUES = {"none", "bounded", "branched", "open"}
REPRESENTATION_REFRAME_VALUES = {"none", "minor", "structural", "creative"}
TRANSFER_DISTANCE_VALUES = {"near", "medium", "far"}
PATH_OPENNESS_VALUES = {"single", "multiple_paths", "multiple_answers"}
DEAD_END_RISK_VALUES = {"low", "medium", "high"}
IMAGE_DEPENDENCY_VALUES = {"none", "helpful", "required"}
OCR_DAMAGE_MARKERS = ("残缺", "缺损", "截断", "识别失败", "公式增强识别失败")
STRATEGY_SIGNAL_PATTERN = re.compile(
    r"(构造|设计|试一试|找规律|逆向|倒推|换一种|至少有几种|最多有几种|分类|枚举|探索|尝试|不同方案|多种方法|"
    r"博弈|必胜|必败|对称策略|抽屉|容斥|同余|不变量|染色|反例|唯一性|约束回查|候选比较|反向整理|"
    r"有限枚举|几何割补|辅助线|面积比链|极值构造|定义新运算|规定一种运算|非相邻裂项|长链消去|首尾项提取|"
    r"参数无关|无关量消去|位置耦合|概率分母|总量转化|制胜策略)"
)
LIGHT_VARIANT_PATTERN = re.compile(
    r"(轻微变化|改问法|单位换算|多一步|一次变式|轻度变式|一处辅助线|平移|等积替换|简单设置|简单倒推)"
)


def _normalize_choice(value: Any, allowed: set[str]) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else ""


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


def _truthy_flag(value: Any) -> bool:
    if value in (1, "1", True):
        return True
    return str(value or "").strip().lower() in {"true", "yes", "y"}


def _audit_attr(parse_audit: Any, name: str, default: Any = None) -> Any:
    if parse_audit is None:
        return default
    if isinstance(parse_audit, dict):
        return parse_audit.get(name, default)
    return getattr(parse_audit, name, default)


def _shift_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(value, -1)


def _missing_fields(feature: Dict[str, Any]) -> List[str]:
    checks = {
        "strategy_role": _normalize_choice(feature.get("strategy_role"), STRATEGY_ROLE_VALUES),
        "template_fit": _normalize_choice(feature.get("template_fit"), TEMPLATE_FIT_VALUES),
        "breakthrough_type": _normalize_choice(
            feature.get("breakthrough_type"),
            BREAKTHROUGH_TYPE_VALUES,
        ),
        "strategy_shift_count": _normalize_choice(
            feature.get("strategy_shift_count"),
            STRATEGY_SHIFT_COUNT_VALUES,
        ),
        "construction_requirement": _normalize_choice(
            feature.get("construction_requirement"),
            CONSTRUCTION_REQUIREMENT_VALUES,
        ),
        "exploration_space": _normalize_choice(
            feature.get("exploration_space"),
            EXPLORATION_SPACE_VALUES,
        ),
        "representation_reframe": _normalize_choice(
            feature.get("representation_reframe"),
            REPRESENTATION_REFRAME_VALUES,
        ),
        "transfer_distance": _normalize_choice(
            feature.get("transfer_distance"),
            TRANSFER_DISTANCE_VALUES,
        ),
        "path_openness": _normalize_choice(feature.get("path_openness"), PATH_OPENNESS_VALUES),
        "dead_end_risk": _normalize_choice(feature.get("dead_end_risk"), DEAD_END_RISK_VALUES),
        "global_strategy_required": _normalize_zero_one(feature.get("global_strategy_required")),
        "image_dependency": _normalize_choice(feature.get("image_dependency"), IMAGE_DEPENDENCY_VALUES),
        "evidence_summary": str(feature.get("evidence_summary", "")).strip(),
    }
    return [key for key, value in checks.items() if value in ("", None)]


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
            "strategy_role",
            "template_fit",
            "breakthrough_type",
            "strategy_shift_count",
            "construction_requirement",
            "exploration_space",
            "representation_reframe",
            "transfer_distance",
            "path_openness",
            "dead_end_risk",
            "image_dependency",
            "evidence_summary",
        )
    )


def _has_strategy_signal(raw_text: str) -> bool:
    return bool(STRATEGY_SIGNAL_PATTERN.search(str(raw_text or "")))


def _feature_signal_text(feature: Dict[str, Any], raw_text: str = "") -> str:
    values = [
        str(raw_text or ""),
        str(feature.get("knowledge_point") or ""),
        str(feature.get("evidence_summary") or ""),
        str(feature.get("anchor_evidence") or ""),
    ]
    for key in (
        "evidence_tags",
        "knowledge_tags",
        "core_knowledge_units",
        "supporting_knowledge_units",
        "method_tags",
    ):
        raw = feature.get(key, [])
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if str(item).strip())
        elif raw:
            values.append(str(raw))
    return " ".join(values)


def _has_light_variant_evidence(feature: Dict[str, Any], raw_text: str) -> bool:
    text = _feature_signal_text(feature, raw_text)
    return any(
        [
            bool(LIGHT_VARIANT_PATTERN.search(text)),
            _normalize_choice(feature.get("template_fit"), TEMPLATE_FIT_VALUES) == "adapted",
            _normalize_choice(feature.get("construction_requirement"), CONSTRUCTION_REQUIREMENT_VALUES)
            == "simple_setup",
            _normalize_choice(feature.get("exploration_space"), EXPLORATION_SPACE_VALUES) == "bounded",
            _normalize_choice(feature.get("representation_reframe"), REPRESENTATION_REFRAME_VALUES)
            == "minor",
            _normalize_choice(feature.get("dead_end_risk"), DEAD_END_RISK_VALUES) == "medium",
        ]
    )


def _has_core_innovation_evidence(feature: Dict[str, Any], raw_text: str) -> bool:
    return (
        _normalize_choice(feature.get("strategy_role"), STRATEGY_ROLE_VALUES) == "core"
        and not _is_low_barrier_direct_template(feature)
        and (_has_high_burden_signal(feature) or _has_strategy_signal(raw_text))
    )


def _has_high_burden_signal(feature: Dict[str, Any]) -> bool:
    return any(
        [
            _normalize_choice(feature.get("template_fit"), TEMPLATE_FIT_VALUES)
            in {"reframed", "non_routine"},
            _normalize_choice(feature.get("breakthrough_type"), BREAKTHROUGH_TYPE_VALUES)
            in {"local_trick", "strategy_shift", "constructive", "exploratory_search"},
            _shift_rank(
                _normalize_choice(
                    feature.get("strategy_shift_count"),
                    STRATEGY_SHIFT_COUNT_VALUES,
                )
            )
            >= 2,
            _normalize_choice(
                feature.get("construction_requirement"),
                CONSTRUCTION_REQUIREMENT_VALUES,
            )
            in {"case_construction", "custom_construction"},
            _normalize_choice(feature.get("exploration_space"), EXPLORATION_SPACE_VALUES)
            in {"branched", "open"},
            _normalize_choice(
                feature.get("representation_reframe"),
                REPRESENTATION_REFRAME_VALUES,
            )
            in {"structural", "creative"},
            _normalize_choice(feature.get("transfer_distance"), TRANSFER_DISTANCE_VALUES)
            in {"medium", "far"},
            _normalize_choice(feature.get("path_openness"), PATH_OPENNESS_VALUES)
            in {"multiple_paths", "multiple_answers"},
            _normalize_choice(feature.get("dead_end_risk"), DEAD_END_RISK_VALUES)
            in {"medium", "high"},
            _normalize_zero_one(feature.get("global_strategy_required")) == 1,
        ]
    )


def _has_upper_burden_signal(feature: Dict[str, Any]) -> bool:
    return any(
        [
            _normalize_choice(feature.get("template_fit"), TEMPLATE_FIT_VALUES) == "non_routine",
            _normalize_choice(feature.get("breakthrough_type"), BREAKTHROUGH_TYPE_VALUES)
            in {"constructive", "exploratory_search"},
            _shift_rank(
                _normalize_choice(
                    feature.get("strategy_shift_count"),
                    STRATEGY_SHIFT_COUNT_VALUES,
                )
            )
            >= 2,
            _normalize_choice(
                feature.get("construction_requirement"),
                CONSTRUCTION_REQUIREMENT_VALUES,
            )
            == "custom_construction",
            _normalize_choice(feature.get("exploration_space"), EXPLORATION_SPACE_VALUES)
            in {"branched", "open"},
            _normalize_choice(
                feature.get("representation_reframe"),
                REPRESENTATION_REFRAME_VALUES,
            )
            == "creative",
            _normalize_choice(feature.get("transfer_distance"), TRANSFER_DISTANCE_VALUES) == "far",
            _normalize_choice(feature.get("path_openness"), PATH_OPENNESS_VALUES)
            in {"multiple_paths", "multiple_answers"},
            _normalize_choice(feature.get("dead_end_risk"), DEAD_END_RISK_VALUES) == "high",
        ]
    )


def _is_low_barrier_direct_template(feature: Dict[str, Any]) -> bool:
    return (
        _normalize_choice(feature.get("template_fit"), TEMPLATE_FIT_VALUES) == "direct"
        and _normalize_choice(feature.get("breakthrough_type"), BREAKTHROUGH_TYPE_VALUES) == "none"
        and _shift_rank(
            _normalize_choice(
                feature.get("strategy_shift_count"),
                STRATEGY_SHIFT_COUNT_VALUES,
            )
        )
        == 0
        and _normalize_choice(
            feature.get("construction_requirement"),
            CONSTRUCTION_REQUIREMENT_VALUES,
        )
        == "none"
        and _normalize_choice(feature.get("exploration_space"), EXPLORATION_SPACE_VALUES)
        == "none"
        and _normalize_choice(
            feature.get("representation_reframe"),
            REPRESENTATION_REFRAME_VALUES,
        )
        == "none"
        and _normalize_choice(feature.get("transfer_distance"), TRANSFER_DISTANCE_VALUES)
        == "near"
        and _normalize_choice(feature.get("path_openness"), PATH_OPENNESS_VALUES) == "single"
        and _normalize_choice(feature.get("dead_end_risk"), DEAD_END_RISK_VALUES) == "low"
        and _normalize_zero_one(feature.get("global_strategy_required")) == 0
    )


def _has_internal_conflict(feature: Dict[str, Any], raw_text: str) -> bool:
    strategy_role = _normalize_choice(feature.get("strategy_role"), STRATEGY_ROLE_VALUES)
    template_fit = _normalize_choice(feature.get("template_fit"), TEMPLATE_FIT_VALUES)
    breakthrough_type = _normalize_choice(
        feature.get("breakthrough_type"),
        BREAKTHROUGH_TYPE_VALUES,
    )
    strategy_shift_count = _normalize_choice(
        feature.get("strategy_shift_count"),
        STRATEGY_SHIFT_COUNT_VALUES,
    )
    path_openness = _normalize_choice(feature.get("path_openness"), PATH_OPENNESS_VALUES)
    exploration_space = _normalize_choice(
        feature.get("exploration_space"),
        EXPLORATION_SPACE_VALUES,
    )
    construction_requirement = _normalize_choice(
        feature.get("construction_requirement"),
        CONSTRUCTION_REQUIREMENT_VALUES,
    )

    if strategy_role == "none" and _has_upper_burden_signal(feature):
        return True
    if strategy_role == "supporting" and _has_upper_burden_signal(feature):
        return True
    if template_fit == "direct" and (
        breakthrough_type in {"constructive", "exploratory_search"}
        or exploration_space == "open"
        or construction_requirement == "custom_construction"
        or _shift_rank(strategy_shift_count) >= 2
    ):
        return True
    if path_openness == "multiple_answers" and strategy_role in {"none", "supporting"}:
        return True
    return False


def evaluate_dim4_applicability(
    raw_text: str,
    dim4_feature: Dict[str, Any] | None = None,
    *,
    llm_confidence: float | None = None,
    parse_audit: Any = None,
    used_image: bool = False,
    image_fallback: bool = False,
    parse_warnings: Iterable[str] | None = None,
) -> Dict[str, Any]:
    feature = dim4_feature or {}
    strategy_role = _normalize_choice(feature.get("strategy_role"), STRATEGY_ROLE_VALUES)
    image_dependency = _normalize_choice(feature.get("image_dependency"), IMAGE_DEPENDENCY_VALUES)
    block_completeness = _normalize_float(_audit_attr(parse_audit, "block_completeness"))
    warnings: List[str] = []
    topic_level = normalize_dim4_level(feature.get("topic_level"))
    level_source = normalize_dim4_level_source(feature.get("level_source"))
    local_variant_calibration = (
        calibrate_dim4_competition_variant_level(feature, topic_level)
        if topic_level and level_source != "review_failed"
        else {}
    )
    if local_variant_calibration:
        topic_level = normalize_dim4_level(local_variant_calibration.get("topic_level")) or topic_level

    if level_source == "review_failed":
        reason = str(feature.get("fallback_error") or "").strip()
        warnings.append(reason or "dim4 知识点内等级兜底判定失败。")
        return {
            "status": DIM4_STATUS_REVIEW,
            "reason": "dim4 未能稳定判定该知识点内部 L1-L5 等级，当前题目转入人工复核。",
            "warnings": list(dict.fromkeys(item for item in warnings if item)),
        }

    if topic_level:
        feature_confidence = _normalize_float(feature.get("applicability_confidence"))
        fallback_confidence = (
            _normalize_float(feature.get("fallback_confidence"))
            if feature.get("fallback_used") in (1, "1", True)
            else None
        )
        high_level_complete_facts = (
            topic_level in {"L4", "L5"}
            and feature_confidence == 0.0
            and not _truthy_flag(feature.get("need_manual_review"))
            and not str(feature.get("warning") or "").strip()
            and not _missing_fields(feature)
        )
        if high_level_complete_facts:
            feature_confidence = None
        effective_confidence = (
            fallback_confidence
            if fallback_confidence is not None
            else feature_confidence if feature_confidence is not None else _normalize_float(llm_confidence)
        )
        if effective_confidence is not None and effective_confidence < DIM4_REVIEW_CONFIDENCE_THRESHOLD:
            warnings.append(
                f"dim4 知识点内等级判定置信度低于自动判分阈值（{DIM4_REVIEW_CONFIDENCE_THRESHOLD:.2f}）。"
            )
        if image_dependency == "required" and not used_image:
            warnings.append("dim4 依赖图片，但当前未稳定使用题块图片。")
        if image_dependency == "required" and image_fallback:
            warnings.append("dim4 依赖图片，但当前已回退纯文本分析。")
        if block_completeness is not None and block_completeness < 0.65:
            warnings.append("题块完整度不足，当前 dim4 结果需人工复核。")
        if _has_ocr_damage_signals(parse_warnings):
            warnings.append("dim4 题面存在 OCR 或题块质量问题，当前结果需人工复核。")
        if warnings:
            return {
                "status": DIM4_STATUS_REVIEW,
                "reason": "dim4 知识点内等级判定存在低置信或题块质量风险，当前题目转入人工复核。",
                "warnings": list(dict.fromkeys(item for item in warnings if item)),
            }
        return {
            "status": DIM4_STATUS_APPLICABLE,
            "reason": "已稳定识别题目所属知识点，并完成该知识点内部 L1-L5 创新等级定位，dim4 适用。",
            "warnings": [],
        }

    calibration = feature.get("calibration", {}) if isinstance(feature, dict) else {}
    if feature.get("reference_review_required"):
        reference_warning = str(feature.get("warning") or "").strip()
        if not reference_warning and isinstance(calibration, dict):
            reference_warning = str(calibration.get("warning") or "").strip()
        warnings.append(reference_warning or "相似高思参考题显示策略创新负担，需复核。")
        return {
            "status": DIM4_STATUS_REVIEW,
            "reason": "dim4 当前本地事实判为不适用，但相似高思参考题显示较高策略创新负担，当前题目转入人工复核。",
            "warnings": list(dict.fromkeys(item for item in warnings if item)),
        }

    if not _feature_present(feature) and not _has_strategy_signal(raw_text):
        return {
            "status": DIM4_STATUS_REVIEW,
            "reason": "dim4 缺少稳定的知识点内 L1-L5 判级事实，当前题目转入人工复核。",
            "warnings": ["dim4 未获得可稳定兜底判级的策略创新事实字段。"],
        }

    missing_fields = _missing_fields(feature)
    if missing_fields:
        warnings.append(f"dim4 缺少关键策略创新事实字段：{'、'.join(missing_fields)}。")

    feature_confidence = _normalize_float(feature.get("applicability_confidence"))
    effective_confidence = feature_confidence if feature_confidence is not None else _normalize_float(llm_confidence)
    if (
        effective_confidence is not None
        and effective_confidence < DIM4_REVIEW_CONFIDENCE_THRESHOLD
        and (strategy_role == "core" or _has_high_burden_signal(feature))
    ):
        warnings.append(
            f"dim4 置信度低于自动判分阈值（{DIM4_REVIEW_CONFIDENCE_THRESHOLD:.2f}）。"
        )

    if image_dependency == "required" and not used_image:
        warnings.append("dim4 依赖图片，但当前未稳定使用题块图片。")
    if image_dependency == "required" and image_fallback:
        warnings.append("dim4 依赖图片，但当前已回退纯文本分析。")
    if block_completeness is not None and block_completeness < 0.65:
        warnings.append("题块完整度不足，当前 dim4 结果需人工复核。")
    if _has_ocr_damage_signals(parse_warnings):
        warnings.append("dim4 题面存在 OCR 或题块质量问题，当前结果需人工复核。")
    if _has_internal_conflict(feature, raw_text):
        warnings.append("dim4 策略角色与策略突破特征冲突，当前结果需人工复核。")

    if warnings:
        return {
            "status": DIM4_STATUS_REVIEW,
            "reason": "dim4 策略创新事实缺失、冲突或题块完整性不足，当前题目转入人工复核。",
            "warnings": list(dict.fromkeys(item for item in warnings if item)),
        }

    if strategy_role == "core" and not _is_low_barrier_direct_template(feature):
        return {
            "status": DIM4_STATUS_APPLICABLE,
            "reason": "策略突破、构造或换路负担构成该题核心门槛，dim4 适用。",
            "warnings": [],
        }

    if strategy_role in {"none", "supporting"} or _is_low_barrier_direct_template(feature):
        return {
            "status": DIM4_STATUS_APPLICABLE,
            "reason": "已稳定识别题目属于低创新负担模板或轻度变式，dim4 按 L1/L2 兜底纳入评分。",
            "warnings": [],
        }

    return {
        "status": DIM4_STATUS_REVIEW,
        "reason": "dim4 边界题尚未形成稳定自动判分依据，当前题目转入人工复核。",
        "warnings": ["dim4 边界题缺少稳定自动判级依据。"],
    }
