"""
dim1 applicability gating.

dim1 evaluates computation execution burden only.
It is tri-state:
- applicable
- needs_second_review
- not_applicable
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from app.services.ocr.base import QuestionType

DIM1_STATUS_APPLICABLE = "applicable"
DIM1_STATUS_NEEDS_SECOND_REVIEW = "needs_second_review"
DIM1_STATUS_REVIEW = "review"
DIM1_STATUS_NOT_APPLICABLE = "not_applicable"
DIM1_REVIEW_CONFIDENCE_THRESHOLD = 0.5

BLANK_PATTERN = re.compile(r"_{2,}|（\s*）|\(\s*\)|\[\s*\]|□|▢")
FORMULA_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*[+\-*/×xX÷]\s*\d+(?:\.\d+)?")
EXPLICIT_CALCULATION_PATTERN = re.compile(
    r"^\s*(?:\d+[、.．]\s*)?(?:计算|直接写得数|得数|口算|列式计算|简便计算|脱式计算|竖式计算|验算)"
)
OPERATOR_PATTERN = re.compile(r"[+\-*/×xX÷=]")
CHINESE_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")
CALCULATION_CONCEPT_ONLY_PATTERN = re.compile(
    r"(?:下列|下面|以下|哪个|哪一个|判断|选择).{0,12}(?:是|不是|属于).{0,8}(?:方程|等式|算式)"
    r"|(?:是方程的是|不是方程的是|方程的是|等式的是)"
)

STEP_CHAIN_VALUES = {"1", "2", "3-4", "5+"}
NUMBER_MIX_VALUES = {"plain", "standard", "mixed", "symbolic"}
ROUTINE_TRANSFORM_VALUES = {"0", "1", "2", "3+"}
STRUCTURAL_METHOD_VALUES = {"none", "shortcut", "olympiad"}
CALC_ROLE_VALUES = {"none", "supporting", "core"}
TASK_FORM_VALUES = {"explicit", "embedded"}
ERROR_PRESSURE_VALUES = {"low", "medium", "high"}
OCR_DAMAGE_MARKERS = ("OCR", "残缺", "缺损", "截断", "公式损坏", "识别失败", "无法识别")
CROSS_QUESTION_REFERENCE_PATTERN = re.compile(
    r"(?:第\s*)?([0-9]{1,2}|[一二三四五六七八九十]{1,3})\s*题"
    r"|题\s*([0-9]{1,2}|[一二三四五六七八九十]{1,3})"
)


def _normalize_question_type(question_type: Any) -> str:
    if isinstance(question_type, QuestionType):
        return question_type.value
    if hasattr(question_type, "value"):
        return str(question_type.value).strip().lower()
    return str(question_type or "").strip().lower()


def _normalize_text(raw_text: str) -> str:
    return " ".join(str(raw_text or "").split())


def _normalize_choice(value: Any, allowed: set[str]) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else ""


def _normalize_zero_one(value: Any) -> int | None:
    if value in (0, "0", False):
        return 0
    if value in (1, "1", True):
        return 1
    return None


def _normalize_routine_count(value: Any) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in ROUTINE_TRANSFORM_VALUES else ""


def _routine_count_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(str(value or "").strip(), -1)


def _step_chain_rank(value: str) -> int:
    return {"1": 1, "2": 2, "3-4": 3, "5+": 4}.get(str(value or "").strip(), -1)


def _has_ocr_damage_signals(parse_warnings: Iterable[str] | None) -> bool:
    for item in parse_warnings or []:
        text = str(item or "").strip()
        if not text:
            continue
        if any(marker in text for marker in OCR_DAMAGE_MARKERS):
            return True
    return False


def is_bare_calculation_fill_blank(raw_text: str) -> bool:
    text = (raw_text or "").strip()
    if not text or not BLANK_PATTERN.search(text):
        return False

    compact = re.sub(r"\s+", "", text)
    if "=" not in compact and "＝" not in compact:
        return False
    return bool(FORMULA_PATTERN.search(compact))


def _looks_like_explicit_calculation(raw_text: str) -> bool:
    normalized = _normalize_text(raw_text)
    if not normalized:
        return False

    if CALCULATION_CONCEPT_ONLY_PATTERN.search(normalized):
        return False

    if EXPLICIT_CALCULATION_PATTERN.search(normalized):
        return True

    operator_count = len(OPERATOR_PATTERN.findall(normalized))
    chinese_count = len(CHINESE_CHAR_PATTERN.findall(normalized))
    return operator_count >= 2 and chinese_count <= 18


def _dim1_missing_fields(feature: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    checks = {
        "task_form": _normalize_choice(feature.get("task_form"), TASK_FORM_VALUES),
        "calc_role": _normalize_choice(feature.get("calc_role"), CALC_ROLE_VALUES),
        "step_chain": _normalize_choice(feature.get("step_chain"), STEP_CHAIN_VALUES),
        "number_mix": _normalize_choice(feature.get("number_mix"), NUMBER_MIX_VALUES),
        "routine_transform_count": _normalize_routine_count(feature.get("routine_transform_count")),
        "structural_method": _normalize_choice(feature.get("structural_method"), STRUCTURAL_METHOD_VALUES),
        "global_view_required": _normalize_zero_one(feature.get("global_view_required")),
        "error_pressure": _normalize_choice(feature.get("error_pressure"), ERROR_PRESSURE_VALUES),
        "evidence_summary": str(feature.get("evidence_summary", "")).strip(),
    }
    for key, value in checks.items():
        if value in ("", None):
            missing.append(key)
    return missing


def _has_high_burden_signal(feature: Dict[str, Any]) -> bool:
    step_chain = _normalize_choice(feature.get("step_chain"), STEP_CHAIN_VALUES)
    number_mix = _normalize_choice(feature.get("number_mix"), NUMBER_MIX_VALUES)
    structural_method = _normalize_choice(feature.get("structural_method"), STRUCTURAL_METHOD_VALUES)
    routine_transform_count = _normalize_routine_count(feature.get("routine_transform_count"))
    global_view_required = _normalize_zero_one(feature.get("global_view_required"))

    return any(
        [
            _routine_count_rank(routine_transform_count) >= 2,
            structural_method in {"shortcut", "olympiad"},
            global_view_required == 1,
            _step_chain_rank(step_chain) >= 4,
            _step_chain_rank(step_chain) >= 3 and number_mix in {"mixed", "symbolic"},
        ]
    )


def _has_internal_conflict(feature: Dict[str, Any], explicit_calculation: bool) -> bool:
    task_form = _normalize_choice(feature.get("task_form"), TASK_FORM_VALUES)
    calc_role = _normalize_choice(feature.get("calc_role"), CALC_ROLE_VALUES)
    high_burden_signal = _has_high_burden_signal(feature)

    if explicit_calculation and calc_role != "core":
        return True
    if task_form == "explicit" and calc_role != "core":
        return True
    if calc_role == "none" and high_burden_signal:
        return True
    if calc_role == "supporting" and (task_form == "explicit" or high_burden_signal):
        return True
    return False


def _has_cross_question_evidence_leak(raw_text: str, feature: Dict[str, Any]) -> bool:
    evidence_summary = str(feature.get("evidence_summary") or "")
    if not evidence_summary:
        return False

    references = {
        match.group(1) or match.group(2)
        for match in CROSS_QUESTION_REFERENCE_PATTERN.finditer(evidence_summary)
    }
    if len(references) < 2:
        return False

    raw_references = {
        match.group(1) or match.group(2)
        for match in CROSS_QUESTION_REFERENCE_PATTERN.finditer(raw_text or "")
    }
    return not references.issubset(raw_references)


def _is_lightweight_direct_computation(feature: Dict[str, Any]) -> bool:
    return (
        _normalize_choice(feature.get("calc_role"), CALC_ROLE_VALUES) == "core"
        and _normalize_choice(feature.get("step_chain"), STEP_CHAIN_VALUES) == "1"
        and _normalize_choice(feature.get("number_mix"), NUMBER_MIX_VALUES) == "plain"
        and _normalize_routine_count(feature.get("routine_transform_count")) == "0"
        and _normalize_choice(feature.get("structural_method"), STRUCTURAL_METHOD_VALUES) == "none"
        and _normalize_zero_one(feature.get("global_view_required")) == 0
        and _normalize_choice(feature.get("error_pressure"), ERROR_PRESSURE_VALUES) == "low"
    )


def evaluate_dim1_applicability(
    question_type: Any,
    raw_text: str,
    dim1_feature: Dict[str, Any] | None = None,
    llm_confidence: float | None = None,
    parse_warnings: Iterable[str] | None = None,
) -> Dict[str, Any]:
    feature = dim1_feature or {}
    normalized_type = _normalize_question_type(question_type)
    normalized_text = _normalize_text(raw_text)
    explicit_calculation = (
        normalized_type == QuestionType.CALCULATION.value
        or is_bare_calculation_fill_blank(normalized_text)
        or _looks_like_explicit_calculation(normalized_text)
    )

    task_form = _normalize_choice(feature.get("task_form"), TASK_FORM_VALUES)
    calc_role = _normalize_choice(feature.get("calc_role"), CALC_ROLE_VALUES)
    warnings: List[str] = []

    if _has_ocr_damage_signals(parse_warnings):
        warnings.append("dim1 题面存在 OCR 或公式缺损，当前结果需人工复核。")

    missing_fields = _dim1_missing_fields(feature)
    if missing_fields:
        warnings.append(
            "dim1 缺少关键计算事实字段：%s。"
            % "、".join(missing_fields)
        )

    if llm_confidence is not None and llm_confidence < DIM1_REVIEW_CONFIDENCE_THRESHOLD:
        warnings.append(
            f"dim1 置信度低于自动判分阈值（{DIM1_REVIEW_CONFIDENCE_THRESHOLD:.2f}）。"
        )

    if _has_internal_conflict(feature, explicit_calculation):
        warnings.append("dim1 计算角色与计算负担特征冲突，当前结果需人工复核。")

    if _has_cross_question_evidence_leak(normalized_text, feature):
        warnings.append("dim1 证据疑似混入其他题号，当前题目转入人工复核。")

    if warnings:
        return {
            "status": DIM1_STATUS_NEEDS_SECOND_REVIEW,
            "reason": "dim1 计算事实缺失、冲突或 OCR 不稳定，当前题目转入人工复核。",
            "warnings": warnings,
        }

    if _is_lightweight_direct_computation(feature):
        return {
            "status": DIM1_STATUS_NOT_APPLICABLE,
            "reason": "该题仅包含轻量直接计算，不计入整卷 dim1 自动均分。",
            "warnings": [],
        }

    if calc_role == "core" or explicit_calculation:
        return {
            "status": DIM1_STATUS_APPLICABLE,
            "reason": "计算执行是该题的核心门槛，dim1 适用。",
            "warnings": [],
        }

    if calc_role == "none":
        return {
            "status": DIM1_STATUS_NOT_APPLICABLE,
            "reason": "该题没有稳定的核心计算执行负担，dim1 不适用。",
            "warnings": [],
        }

    if task_form == "embedded" and calc_role == "supporting":
        return {
            "status": DIM1_STATUS_NOT_APPLICABLE,
            "reason": "该题中的计算仅为附带步骤，dim1 不适用。",
            "warnings": [],
        }

    return {
        "status": DIM1_STATUS_NOT_APPLICABLE,
        "reason": "dim1 边界题未形成稳定自动判分依据，当前维度不纳入自动评分。",
        "warnings": [],
    }
