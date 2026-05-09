"""
dim6 applicability gating.

dim6 evaluates logic-chain burden only.
It is tri-state:
- applicable
- review
- not_applicable
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

DIM6_STATUS_APPLICABLE = "applicable"
DIM6_STATUS_REVIEW = "review"
DIM6_STATUS_NOT_APPLICABLE = "not_applicable"
DIM6_REVIEW_CONFIDENCE_THRESHOLD = 0.55

REASONING_ROLE_VALUES = {"none", "supporting", "core"}
CHAIN_SPAN_VALUES = {"1", "2", "3-4", "5+"}
HIDDEN_DEPENDENCY_VALUES = {"none", "local", "cross_condition", "global"}
BRANCH_CONTROL_VALUES = {"none", "explicit_cases", "multi_branch"}
REVERSIBILITY_VALUES = {"none", "backward", "bidirectional"}
VERIFICATION_REQUIREMENT_VALUES = {
    "none",
    "result_check",
    "constraint_backcheck",
    "full_consistency",
}
ABSTRACTION_BRIDGE_COUNT_VALUES = {"0", "1", "2", "3+"}
CONSTRAINT_COUPLING_VALUES = {"none", "single", "coupled", "nested"}
CONCLUSION_STABILITY_VALUES = {"direct", "edge_sensitive", "exhaustive"}
LOGIC_STRUCTURE_TYPE_VALUES = {
    "work_rate_chain",
    "queue_growth_chain",
    "multi_stage_state_change",
    "percentage_base_shift_chain",
    "travel_meeting_chasing_chain",
    "cyclic_schedule_chain",
    "reverse_process_chain",
    "bounded_case_enumeration",
    "optimization_comparison",
    "global_constraint_system",
    "periodic_sequence_position",
    "shared_variable_coupling",
}
STATE_TRANSITION_COUNT_VALUES = {"0", "1", "2", "3+"}
CASE_COUNT_BAND_VALUES = {"none", "2", "3-5", "6+"}
BACKTRACK_DEPTH_VALUES = {"0", "1", "2", "3+"}
CONSISTENCY_CONSTRAINT_COUNT_VALUES = {"0", "1", "2-3", "4+"}
PHASE_COUNT_BAND_VALUES = {"1", "2", "3-4", "5+"}
OPTIMIZATION_REQUIREMENT_VALUES = {"none", "bounded_choice", "global_minmax"}
OCR_DAMAGE_MARKERS = ("残缺", "缺损", "截断", "识别失败", "公式增强识别失败")
LOGIC_SIGNAL_PATTERN = re.compile(
    r"(分类|分别|讨论|所有可能|符合条件|至少|至多|检验|验证|回查|是否成立|几种不同铺法|"
    r"最少|最小|最大|最优|相遇后|追上|同时到达|每分钟来的|换班|第\d+次|倒回|还原|"
    r"按顺序|周期|循环|增长|排队|检票|调头|往返)"
)


def _normalize_choice(value: Any, allowed: set[str]) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else ""


def _normalize_choice_list(value: Any, allowed: set[str]) -> List[str]:
    if isinstance(value, str):
        raw_items = value.replace("，", ",").replace("、", ",").split(",")
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


def _audit_attr(parse_audit: Any, name: str, default: Any = None) -> Any:
    if parse_audit is None:
        return default
    if isinstance(parse_audit, dict):
        return parse_audit.get(name, default)
    return getattr(parse_audit, name, default)


def _missing_fields(feature: Dict[str, Any]) -> List[str]:
    checks = {
        "reasoning_role": _normalize_choice(feature.get("reasoning_role"), REASONING_ROLE_VALUES),
        "chain_span": _normalize_choice(feature.get("chain_span"), CHAIN_SPAN_VALUES),
        "hidden_dependency": _normalize_choice(
            feature.get("hidden_dependency"),
            HIDDEN_DEPENDENCY_VALUES,
        ),
        "branch_control": _normalize_choice(feature.get("branch_control"), BRANCH_CONTROL_VALUES),
        "reversibility": _normalize_choice(feature.get("reversibility"), REVERSIBILITY_VALUES),
        "verification_requirement": _normalize_choice(
            feature.get("verification_requirement"),
            VERIFICATION_REQUIREMENT_VALUES,
        ),
        "abstraction_bridge_count": _normalize_choice(
            feature.get("abstraction_bridge_count"),
            ABSTRACTION_BRIDGE_COUNT_VALUES,
        ),
        "constraint_coupling": _normalize_choice(
            feature.get("constraint_coupling"),
            CONSTRAINT_COUPLING_VALUES,
        ),
        "global_consistency_required": _normalize_zero_one(
            feature.get("global_consistency_required")
        ),
        "conclusion_stability": _normalize_choice(
            feature.get("conclusion_stability"),
            CONCLUSION_STABILITY_VALUES,
        ),
        "evidence_summary": str(feature.get("evidence_summary", "")).strip(),
    }
    return [key for key, value in checks.items() if value in ("", None)]


def _chain_rank(value: str) -> int:
    return {"1": 1, "2": 2, "3-4": 3, "5+": 4}.get(value, -1)


def _abstraction_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(value, -1)


def _state_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(value, -1)


def _case_rank(value: str) -> int:
    return {"none": 0, "2": 2, "3-5": 3, "6+": 6}.get(value, -1)


def _backtrack_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(value, -1)


def _consistency_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2-3": 2, "4+": 4}.get(value, -1)


def _phase_rank(value: str) -> int:
    return {"1": 1, "2": 2, "3-4": 3, "5+": 5}.get(value, -1)


def _has_ocr_damage_signals(parse_warnings: Iterable[str] | None) -> bool:
    for item in parse_warnings or []:
        text = str(item or "").strip()
        if text and any(marker in text for marker in OCR_DAMAGE_MARKERS):
            return True
    return False


def _feature_present(feature: Dict[str, Any]) -> bool:
    base_present = any(
        str(feature.get(key, "")).strip()
        for key in (
            "reasoning_role",
            "chain_span",
            "hidden_dependency",
            "branch_control",
            "reversibility",
            "verification_requirement",
            "abstraction_bridge_count",
            "constraint_coupling",
            "conclusion_stability",
            "evidence_summary",
        )
    )
    structured_present = any(
        [
            bool(_normalize_choice_list(feature.get("logic_structure_types"), LOGIC_STRUCTURE_TYPE_VALUES)),
            _state_rank(
                _normalize_choice(feature.get("state_transition_count"), STATE_TRANSITION_COUNT_VALUES)
                or "0"
            )
            > 0,
            _case_rank(_normalize_choice(feature.get("case_count_band"), CASE_COUNT_BAND_VALUES) or "none")
            > 0,
            _backtrack_rank(_normalize_choice(feature.get("backtrack_depth"), BACKTRACK_DEPTH_VALUES) or "0")
            > 0,
            _consistency_rank(
                _normalize_choice(
                    feature.get("consistency_constraint_count"),
                    CONSISTENCY_CONSTRAINT_COUNT_VALUES,
                )
                or "0"
            )
            > 0,
            _phase_rank(_normalize_choice(feature.get("phase_count_band"), PHASE_COUNT_BAND_VALUES) or "1")
            > 1,
            _normalize_zero_one(feature.get("periodic_cycle_dependency")) == 1,
            _normalize_choice(feature.get("optimization_requirement"), OPTIMIZATION_REQUIREMENT_VALUES)
            in {"bounded_choice", "global_minmax"},
        ]
    )
    return base_present or structured_present


def _has_logic_signal(raw_text: str) -> bool:
    return bool(LOGIC_SIGNAL_PATTERN.search(str(raw_text or "")))


def _has_high_burden_signal(feature: Dict[str, Any]) -> bool:
    structures = set(
        _normalize_choice_list(feature.get("logic_structure_types"), LOGIC_STRUCTURE_TYPE_VALUES)
    )
    state_transition_count = _normalize_choice(
        feature.get("state_transition_count"),
        STATE_TRANSITION_COUNT_VALUES,
    )
    case_count_band = _normalize_choice(feature.get("case_count_band"), CASE_COUNT_BAND_VALUES)
    backtrack_depth = _normalize_choice(feature.get("backtrack_depth"), BACKTRACK_DEPTH_VALUES)
    consistency_constraint_count = _normalize_choice(
        feature.get("consistency_constraint_count"),
        CONSISTENCY_CONSTRAINT_COUNT_VALUES,
    )
    phase_count_band = _normalize_choice(feature.get("phase_count_band"), PHASE_COUNT_BAND_VALUES)
    periodic_cycle_dependency = _normalize_zero_one(feature.get("periodic_cycle_dependency"))
    optimization_requirement = _normalize_choice(
        feature.get("optimization_requirement"),
        OPTIMIZATION_REQUIREMENT_VALUES,
    )
    return any(
        [
            _chain_rank(_normalize_choice(feature.get("chain_span"), CHAIN_SPAN_VALUES)) >= 3,
            _normalize_choice(feature.get("hidden_dependency"), HIDDEN_DEPENDENCY_VALUES)
            in {"cross_condition", "global"},
            _normalize_choice(feature.get("branch_control"), BRANCH_CONTROL_VALUES)
            in {"explicit_cases", "multi_branch"},
            _normalize_choice(feature.get("reversibility"), REVERSIBILITY_VALUES)
            in {"backward", "bidirectional"},
            _normalize_choice(
                feature.get("verification_requirement"),
                VERIFICATION_REQUIREMENT_VALUES,
            )
            in {"constraint_backcheck", "full_consistency"},
            _abstraction_rank(
                _normalize_choice(
                    feature.get("abstraction_bridge_count"),
                    ABSTRACTION_BRIDGE_COUNT_VALUES,
                )
            )
            >= 2,
            _normalize_choice(feature.get("constraint_coupling"), CONSTRAINT_COUPLING_VALUES)
            in {"coupled", "nested"},
            _normalize_zero_one(feature.get("global_consistency_required")) == 1,
            _normalize_choice(feature.get("conclusion_stability"), CONCLUSION_STABILITY_VALUES)
            == "exhaustive",
            bool(
                structures
                & {
                    "queue_growth_chain",
                    "travel_meeting_chasing_chain",
                    "cyclic_schedule_chain",
                    "bounded_case_enumeration",
                    "optimization_comparison",
                    "global_constraint_system",
                }
            ),
            _state_rank(state_transition_count) >= 2,
            _case_rank(case_count_band) >= 3,
            _backtrack_rank(backtrack_depth) >= 2,
            _consistency_rank(consistency_constraint_count) >= 2,
            _phase_rank(phase_count_band) >= 3,
            periodic_cycle_dependency == 1,
            optimization_requirement in {"bounded_choice", "global_minmax"},
        ]
    )


def _is_low_barrier_direct_push(feature: Dict[str, Any]) -> bool:
    structures = _normalize_choice_list(feature.get("logic_structure_types"), LOGIC_STRUCTURE_TYPE_VALUES)
    state_transition_count = _normalize_choice(
        feature.get("state_transition_count"),
        STATE_TRANSITION_COUNT_VALUES,
    )
    case_count_band = _normalize_choice(feature.get("case_count_band"), CASE_COUNT_BAND_VALUES)
    backtrack_depth = _normalize_choice(feature.get("backtrack_depth"), BACKTRACK_DEPTH_VALUES)
    consistency_constraint_count = _normalize_choice(
        feature.get("consistency_constraint_count"),
        CONSISTENCY_CONSTRAINT_COUNT_VALUES,
    )
    phase_count_band = _normalize_choice(feature.get("phase_count_band"), PHASE_COUNT_BAND_VALUES)
    periodic_cycle_dependency = _normalize_zero_one(feature.get("periodic_cycle_dependency"))
    optimization_requirement = _normalize_choice(
        feature.get("optimization_requirement"),
        OPTIMIZATION_REQUIREMENT_VALUES,
    )
    return (
        _normalize_choice(feature.get("chain_span"), CHAIN_SPAN_VALUES) == "1"
        and _normalize_choice(feature.get("hidden_dependency"), HIDDEN_DEPENDENCY_VALUES) == "none"
        and _normalize_choice(feature.get("branch_control"), BRANCH_CONTROL_VALUES) == "none"
        and _normalize_choice(feature.get("reversibility"), REVERSIBILITY_VALUES) == "none"
        and _normalize_choice(
            feature.get("verification_requirement"),
            VERIFICATION_REQUIREMENT_VALUES,
        )
        == "none"
        and _normalize_choice(
            feature.get("abstraction_bridge_count"),
            ABSTRACTION_BRIDGE_COUNT_VALUES,
        )
        == "0"
        and _normalize_choice(feature.get("constraint_coupling"), CONSTRAINT_COUPLING_VALUES)
        in {"none", "single"}
        and _normalize_zero_one(feature.get("global_consistency_required")) == 0
        and _normalize_choice(feature.get("conclusion_stability"), CONCLUSION_STABILITY_VALUES)
        == "direct"
        and not structures
        and _state_rank(state_transition_count or "0") <= 0
        and _case_rank(case_count_band or "none") <= 0
        and _backtrack_rank(backtrack_depth or "0") <= 0
        and _consistency_rank(consistency_constraint_count or "0") <= 1
        and _phase_rank(phase_count_band or "1") <= 1
        and periodic_cycle_dependency in (None, 0)
        and optimization_requirement in ("", "none")
    )


def _has_internal_conflict(feature: Dict[str, Any], raw_text: str) -> bool:
    reasoning_role = _normalize_choice(feature.get("reasoning_role"), REASONING_ROLE_VALUES)
    chain_span = _normalize_choice(feature.get("chain_span"), CHAIN_SPAN_VALUES)
    branch_control = _normalize_choice(feature.get("branch_control"), BRANCH_CONTROL_VALUES)
    verification_requirement = _normalize_choice(
        feature.get("verification_requirement"),
        VERIFICATION_REQUIREMENT_VALUES,
    )
    constraint_coupling = _normalize_choice(
        feature.get("constraint_coupling"),
        CONSTRAINT_COUPLING_VALUES,
    )
    global_consistency_required = _normalize_zero_one(feature.get("global_consistency_required"))
    conclusion_stability = _normalize_choice(
        feature.get("conclusion_stability"),
        CONCLUSION_STABILITY_VALUES,
    )

    if reasoning_role == "none" and (_has_high_burden_signal(feature) or _has_logic_signal(raw_text)):
        return True
    if reasoning_role == "supporting" and _has_high_burden_signal(feature):
        return True
    if chain_span == "1" and (
        branch_control == "multi_branch"
        or verification_requirement == "full_consistency"
        or constraint_coupling == "nested"
    ):
        return True
    if branch_control == "multi_branch" and constraint_coupling == "none" and global_consistency_required == 0:
        return True
    if conclusion_stability == "exhaustive" and verification_requirement == "none":
        return True
    return False


def evaluate_dim6_applicability(
    raw_text: str,
    dim6_feature: Dict[str, Any] | None = None,
    *,
    llm_confidence: float | None = None,
    parse_audit: Any = None,
    parse_warnings: Iterable[str] | None = None,
) -> Dict[str, Any]:
    feature = dim6_feature or {}
    reasoning_role = _normalize_choice(feature.get("reasoning_role"), REASONING_ROLE_VALUES)
    block_completeness = _normalize_float(_audit_attr(parse_audit, "block_completeness"))
    warnings: List[str] = []

    if not _feature_present(feature) and not _has_logic_signal(raw_text):
        return {
            "status": DIM6_STATUS_NOT_APPLICABLE,
            "reason": "该题没有稳定的核心逻辑推进与论证控制负担，dim6 不适用。",
            "warnings": [],
        }

    missing_fields = _missing_fields(feature)
    if missing_fields:
        warnings.append(f"dim6 缺少关键逻辑事实字段：{'、'.join(missing_fields)}。")

    feature_confidence = _normalize_float(feature.get("applicability_confidence"))
    effective_confidence = feature_confidence if feature_confidence is not None else _normalize_float(llm_confidence)
    if (
        effective_confidence is not None
        and effective_confidence < DIM6_REVIEW_CONFIDENCE_THRESHOLD
        and (reasoning_role == "core" or _has_high_burden_signal(feature))
    ):
        warnings.append(
            f"dim6 置信度低于自动判分阈值（{DIM6_REVIEW_CONFIDENCE_THRESHOLD:.2f}）。"
        )

    if block_completeness is not None and block_completeness < 0.65:
        warnings.append("题块完整度不足，当前 dim6 结果需人工复核。")
    if _has_ocr_damage_signals(parse_warnings):
        warnings.append("dim6 题面存在 OCR 或题块质量问题，当前结果需人工复核。")
    if _has_logic_signal(raw_text) and reasoning_role in {"none", "supporting"}:
        warnings.append("题面存在明显分类、回查或分支信号，但 dim6 标记偏低。")
    if _has_internal_conflict(feature, raw_text):
        warnings.append("dim6 逻辑角色与链条控制特征冲突，当前结果需人工复核。")

    if warnings:
        return {
            "status": DIM6_STATUS_REVIEW,
            "reason": "dim6 逻辑事实缺失、冲突或题块完整性不足，当前题目转入人工复核。",
            "warnings": list(dict.fromkeys(item for item in warnings if item)),
        }

    if reasoning_role == "core" and not _is_low_barrier_direct_push(feature):
        return {
            "status": DIM6_STATUS_APPLICABLE,
            "reason": "解法推进、隐含关系串联或结果回查构成该题核心门槛，dim6 适用。",
            "warnings": [],
        }

    if reasoning_role in {"none", "supporting"} or _is_low_barrier_direct_push(feature):
        return {
            "status": DIM6_STATUS_NOT_APPLICABLE,
            "reason": "该题的逻辑推进与论证控制不是核心门槛，dim6 不适用。",
            "warnings": [],
        }

    return {
        "status": DIM6_STATUS_NOT_APPLICABLE,
        "reason": "dim6 边界题尚未形成稳定自动判分依据，当前维度不纳入自动评分。",
        "warnings": [],
    }
