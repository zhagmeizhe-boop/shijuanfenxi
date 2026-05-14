"""
dim1 computation burden scorer.

The scorer consumes normalized computation facts and maps them to
L1-L5 fixed representative scores.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.services.scoring.base import BaseDimensionScorer, DimensionScore
from app.services.scoring.dim1_knowledge_range import (
    match_dim1_display_knowledge,
    match_dim1_knowledge_range,
)

STEP_CHAIN_VALUES = {"1", "2", "3-4", "5+"}
NUMBER_MIX_VALUES = {"plain", "standard", "mixed", "symbolic"}
ROUTINE_TRANSFORM_VALUES = {"0", "1", "2", "3+"}
STRUCTURAL_METHOD_VALUES = {"none", "shortcut", "olympiad"}
CALC_ROLE_VALUES = {"none", "supporting", "core"}
TASK_FORM_VALUES = {"explicit", "embedded"}
CALC_BUCKET_VALUES = {"pure_calculation", "embedded_calculation"}
EMBEDDED_COUNT_VALUES = {"0", "1", "2", "2+", "3+"}
CALC_SUBTYPE_VALUES = {
    "arithmetic",
    "equation",
    "proportion_equation",
    "defined_operation",
    "factorial_ratio",
    "fraction_comparison",
    "sequence_series",
    "nested_fraction",
    "structural_identity",
    "pattern_computation",
}
STRUCTURE_PATTERN_VALUES = {
    "grouping",
    "common_factor",
    "decimal_scaling",
    "fraction_decimal_percent_conversion",
    "reciprocal_conversion",
    "factorial_cancellation",
    "defined_rule_expansion",
    "telescoping",
    "symmetric_cancellation",
    "recursive_product",
    "continued_fraction",
    "sequence_generalization",
}
TERM_COUNT_BAND_VALUES = {"1-2", "3-5", "6-10", "11+"}
SYMBOLIC_DEPENDENCY_VALUES = {"none", "single_unknown", "multi_unknown", "parameterized"}

KNOWLEDGE_BURDEN_LEVEL_MATRIX = {
    "K1": {"B1": "L1", "B2": "L1", "B3": "L2", "B4": "L2", "B5": "L3"},
    "K2": {"B1": "L2", "B2": "L2", "B3": "L2", "B4": "L3", "B5": "L4"},
    "K3": {"B1": "L2", "B2": "L3", "B3": "L3", "B4": "L4", "B5": "L4"},
    "K4": {"B1": "L3", "B2": "L3", "B3": "L4", "B4": "L4", "B5": "L5"},
    "K5": {"B1": "L4", "B2": "L4", "B3": "L5", "B4": "L5", "B5": "L5"},
}

DIM1_LEVELS = {
    "L1": {"score": 2.0, "level": 1, "label": "L1 直接运算"},
    "L2": {"score": 4.0, "level": 2, "label": "L2 常规运算"},
    "L3": {"score": 6.0, "level": 3, "label": "L3 结构变形运算"},
    "L4": {"score": 8.0, "level": 4, "label": "L4 复合巧算"},
    "L5": {"score": 9.5, "level": 5, "label": "L5 高阶结构巧算"},
}
EMBEDDED_DIM1_LEVELS = {
    "L1": {"score": 2.0, "level": 1, "label": "L1 轻量嵌入计算"},
    "L2": {"score": 4.0, "level": 2, "label": "L2 常规嵌入计算"},
    "L3": {"score": 6.0, "level": 3, "label": "L3 多步嵌入计算"},
    "L4": {"score": 8.0, "level": 4, "label": "L4 高负担嵌入计算"},
    "L5": {"score": 9.5, "level": 5, "label": "L5 高阶嵌入计算"},
}


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


def _normalize_routine_count(value: Any) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in ROUTINE_TRANSFORM_VALUES else ""


def _normalize_zero_one(value: Any) -> int | None:
    if value in (0, "0", False):
        return 0
    if value in (1, "1", True):
        return 1
    return None


def _routine_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(value, -1)


def _step_rank(value: str) -> int:
    return {"1": 1, "2": 2, "3-4": 3, "5+": 5}.get(value, -1)


def _embedded_count_rank(value: Any) -> int:
    normalized = str(value or "").strip()
    return {"0": 0, "1": 1, "2": 2, "2+": 2, "3+": 3}.get(normalized, 0)


def _term_count_rank(value: str) -> int:
    return {"1-2": 2, "3-5": 5, "6-10": 10, "11+": 11}.get(value, 0)


def infer_calc_bucket(features: Dict[str, Any]) -> str:
    explicit_bucket = _normalize_choice(features.get("calc_bucket"), CALC_BUCKET_VALUES)
    if explicit_bucket:
        return explicit_bucket

    task_form = _normalize_choice(features.get("task_form"), TASK_FORM_VALUES)
    calc_role = _normalize_choice(features.get("calc_role"), CALC_ROLE_VALUES)
    if task_form == "embedded" and calc_role == "core":
        return "embedded_calculation"
    return "pure_calculation"


class Dim1ComputationScorer(BaseDimensionScorer):
    DIMENSION_CODE = "dim1"
    DIMENSION_NAME = "数学运算"

    def __init__(self):
        super().__init__(config=None)

    def _build_score(
        self,
        level_code: str,
        evidence_summary: str,
        *,
        calc_bucket: str = "pure_calculation",
        extra_details: Dict[str, Any] | None = None,
    ) -> DimensionScore:
        level_map = EMBEDDED_DIM1_LEVELS if calc_bucket == "embedded_calculation" else DIM1_LEVELS
        level = level_map[level_code]
        details = {
            "status": "applicable",
            "dim1_level": level_code,
            "calc_bucket": calc_bucket,
            "rule_family": calc_bucket,
        }
        if extra_details:
            details.update(extra_details)
        return DimensionScore(
            dimension_code=self.DIMENSION_CODE,
            score=level["score"],
            level=level["level"],
            level_label=level["label"],
            evidence=f"{level['label']}：{evidence_summary}",
            applicable=True,
            details=details,
        )

    def _invalid_score(self, evidence: str) -> DimensionScore:
        return DimensionScore(
            dimension_code=self.DIMENSION_CODE,
            score=0.0,
            level=0,
            level_label="N/A",
            evidence=evidence,
            applicable=False,
            details={"status": "not_applicable", "dim1_level": "N/A"},
        )

    def _finalize_score(
        self,
        burden_result: DimensionScore,
        features: Dict[str, Any],
        *,
        evidence_summary: str,
        calc_bucket: str,
    ) -> DimensionScore:
        if not burden_result.applicable:
            return burden_result

        burden_dim1_level = str(burden_result.details.get("dim1_level") or f"L{burden_result.level}")
        burden_level = (
            f"B{burden_dim1_level[1:]}"
            if burden_dim1_level.startswith("L")
            else f"B{burden_result.level}"
        )
        level_map = EMBEDDED_DIM1_LEVELS if calc_bucket == "embedded_calculation" else DIM1_LEVELS
        details = dict(burden_result.details)
        details.update(
            {
                "burden_level": burden_level,
                "burden_dim1_level": burden_dim1_level,
                "burden_score": burden_result.score,
                "burden_level_label": burden_result.level_label,
            }
        )

        knowledge_match = match_dim1_knowledge_range(features)
        details.update(knowledge_match.to_details())
        display_knowledge_match = match_dim1_display_knowledge(features, knowledge_match)
        details.update(display_knowledge_match.to_details())

        if not knowledge_match.knowledge_range_level:
            details.update(
                {
                    "dim1_level": burden_dim1_level,
                    "rule_family": f"{calc_bucket}_burden_only",
                    "combined_rule": "burden_only_knowledge_range_unmatched",
                }
            )
            evidence = (
                f"{burden_result.level_label}：知识范围未稳定识别；"
                f"主要依据题目的步骤长度、数字形式和结构变形要求，综合判为{burden_dim1_level}。"
            )
            return DimensionScore(
                dimension_code=self.DIMENSION_CODE,
                score=burden_result.score,
                level=burden_result.level,
                level_label=burden_result.level_label,
                evidence=evidence,
                applicable=True,
                details=details,
            )

        final_level = KNOWLEDGE_BURDEN_LEVEL_MATRIX.get(
            knowledge_match.knowledge_range_level,
            {},
        ).get(burden_level, burden_dim1_level)
        level = level_map[final_level]
        matched_points = "、".join(knowledge_match.matched_knowledge_points[:3]) or "核心计算知识点"
        details.update(
            {
                "dim1_level": final_level,
                "rule_family": f"{calc_bucket}_knowledge_range_matrix",
                "combined_rule": "knowledge_range_burden_matrix",
                "knowledge_burden_matrix_cell": f"{knowledge_match.knowledge_range_level}+{burden_level}",
            }
        )
        evidence = (
            f"{level['label']}：主要考查{knowledge_match.knowledge_range_label}的{matched_points}；"
            f"结合知识范围和运算组织要求，综合判为{final_level}。"
        )
        return DimensionScore(
            dimension_code=self.DIMENSION_CODE,
            score=level["score"],
            level=level["level"],
            level_label=level["label"],
            evidence=evidence,
            applicable=True,
            details=details,
        )

    def _calculate_score(self, features: Dict[str, Any]) -> DimensionScore:
        task_form = _normalize_choice(features.get("task_form"), TASK_FORM_VALUES)
        step_chain = _normalize_choice(features.get("step_chain"), STEP_CHAIN_VALUES)
        number_mix = _normalize_choice(features.get("number_mix"), NUMBER_MIX_VALUES)
        routine_transform_count = _normalize_routine_count(features.get("routine_transform_count"))
        structural_method = _normalize_choice(features.get("structural_method"), STRUCTURAL_METHOD_VALUES)
        calc_role = _normalize_choice(features.get("calc_role"), CALC_ROLE_VALUES)
        global_view_required = _normalize_zero_one(features.get("global_view_required"))
        calc_bucket = infer_calc_bucket(features)
        evidence_summary = str(features.get("evidence_summary", "")).strip()

        required_values = [
            task_form,
            step_chain,
            number_mix,
            routine_transform_count,
            structural_method,
            calc_role,
            evidence_summary,
        ]
        if any(value in ("", None) for value in required_values) or global_view_required is None:
            return self._invalid_score("dim1 关键计算事实不完整，无法自动判级。")

        routine_rank = _routine_rank(routine_transform_count)
        if calc_bucket == "embedded_calculation":
            burden_result = self._score_embedded(
                features,
                step_chain=step_chain,
                number_mix=number_mix,
                routine_rank=routine_rank,
                structural_method=structural_method,
                global_view_required=global_view_required,
                evidence_summary=evidence_summary,
            )
            return self._finalize_score(
                burden_result,
                features,
                evidence_summary=evidence_summary,
                calc_bucket=calc_bucket,
            )

        burden_result = self._score_pure(
            features,
            step_chain=step_chain,
            number_mix=number_mix,
            routine_rank=routine_rank,
            structural_method=structural_method,
            calc_role=calc_role,
            global_view_required=global_view_required,
            evidence_summary=evidence_summary,
        )
        return self._finalize_score(
            burden_result,
            features,
            evidence_summary=evidence_summary,
            calc_bucket=calc_bucket,
        )

    def _score_pure(
        self,
        features: Dict[str, Any],
        *,
        step_chain: str,
        number_mix: str,
        routine_rank: int,
        structural_method: str,
        calc_role: str,
        global_view_required: int,
        evidence_summary: str,
    ) -> DimensionScore:
        calc_subtype = _normalize_choice(features.get("calc_subtype"), CALC_SUBTYPE_VALUES)
        structure_patterns = _normalize_choice_list(features.get("structure_patterns"), STRUCTURE_PATTERN_VALUES)
        pattern_set = set(structure_patterns)
        term_count_band = _normalize_choice(features.get("term_count_band"), TERM_COUNT_BAND_VALUES)
        symbolic_dependency = _normalize_choice(
            features.get("symbolic_dependency"),
            SYMBOLIC_DEPENDENCY_VALUES,
        )
        step_rank = _step_rank(step_chain)
        term_rank = _term_count_rank(term_count_band)
        audit_details = {
            "calc_subtype": calc_subtype,
            "structure_patterns": structure_patterns,
            "term_count_band": term_count_band,
            "symbolic_dependency": symbolic_dependency,
        }

        if (
            structural_method == "olympiad" and global_view_required == 1
        ) or (
            routine_rank >= 3 and step_chain == "5+" and calc_role == "core"
        ) or (
            term_rank >= 11
            and pattern_set
            & {
                "telescoping",
                "symmetric_cancellation",
                "recursive_product",
                "sequence_generalization",
            }
        ) or (
            "recursive_product" in pattern_set and global_view_required == 1
        ) or (
            symbolic_dependency == "parameterized"
            and global_view_required == 1
            and calc_subtype in {"sequence_series", "pattern_computation", "structural_identity"}
        ):
            return self._build_score(
                "L5",
                evidence_summary,
                calc_bucket="pure_calculation",
                extra_details=audit_details,
            )

        if (
            {"common_factor", "decimal_scaling"}.issubset(pattern_set)
        ) or (
            {"common_factor", "fraction_decimal_percent_conversion"}.issubset(pattern_set)
        ) or (
            pattern_set
            & {
                "symmetric_cancellation",
                "continued_fraction",
            }
        ) or (
            calc_subtype == "nested_fraction"
        ) or (
            calc_subtype == "defined_operation"
            and (
                step_rank >= 3
                or routine_rank >= 2
                or global_view_required == 1
            )
        ) or (
            calc_subtype == "sequence_series"
            and (term_rank >= 6 or global_view_required == 1)
        ) or (
            len(pattern_set) >= 2
            and (
                routine_rank >= 2
                or step_rank >= 3
                or global_view_required == 1
            )
        ) or (
            structural_method in {"shortcut", "olympiad"} and routine_rank >= 2
        ) or (
            structural_method in {"shortcut", "olympiad"} and global_view_required == 1
        ) or (
            step_chain == "5+" and number_mix in {"mixed", "symbolic"}
        ):
            return self._build_score(
                "L4",
                evidence_summary,
                calc_bucket="pure_calculation",
                extra_details=audit_details,
            )

        if (
            pattern_set
            & {
                "grouping",
                "common_factor",
                "decimal_scaling",
                "fraction_decimal_percent_conversion",
                "reciprocal_conversion",
                "factorial_cancellation",
                "defined_rule_expansion",
            }
        ) or (
            calc_subtype == "factorial_ratio"
        ) or (
            calc_subtype in {"equation", "proportion_equation"}
            and (
                step_rank >= 3
                or routine_rank >= 1
                or symbolic_dependency in {"multi_unknown", "parameterized"}
            )
        ) or (
            structural_method == "shortcut"
        ) or (
            routine_rank >= 2
        ) or (
            step_chain == "3-4" and number_mix in {"standard", "mixed", "symbolic"}
        ) or (
            number_mix == "mixed" and routine_rank >= 1
        ):
            return self._build_score(
                "L3",
                evidence_summary,
                calc_bucket="pure_calculation",
                extra_details=audit_details,
            )

        if (
            calc_subtype in {"equation", "proportion_equation"}
            and symbolic_dependency in {"", "single_unknown"}
        ) or (
            step_chain == "2"
        ) or (
            number_mix == "standard"
        ) or (
            routine_rank >= 1
        ):
            return self._build_score(
                "L2",
                evidence_summary,
                calc_bucket="pure_calculation",
                extra_details=audit_details,
            )

        return self._build_score(
            "L1",
            evidence_summary,
            calc_bucket="pure_calculation",
            extra_details=audit_details,
        )

    def _score_embedded(
        self,
        features: Dict[str, Any],
        *,
        step_chain: str,
        number_mix: str,
        routine_rank: int,
        structural_method: str,
        global_view_required: int,
        evidence_summary: str,
    ) -> DimensionScore:
        step_rank = _step_rank(step_chain)
        intermediate_rank = _embedded_count_rank(features.get("intermediate_quantity_count"))
        unit_rank = _embedded_count_rank(features.get("unit_conversion_count"))
        formula_rank = _embedded_count_rank(features.get("formula_substitution_count"))
        error_pressure = str(features.get("error_pressure", "")).strip().lower()

        if (
            structural_method == "olympiad"
            and global_view_required == 1
            and step_chain == "5+"
        ) or (
            step_chain == "5+"
            and routine_rank >= 3
            and global_view_required == 1
            and number_mix in {"mixed", "symbolic"}
        ):
            return self._build_score("L5", evidence_summary, calc_bucket="embedded_calculation")

        if (
            step_chain == "5+"
            and (
                error_pressure == "high"
                or intermediate_rank >= 3
                or unit_rank >= 2
                or formula_rank >= 2
                or number_mix in {"mixed", "symbolic"}
            )
        ) or (
            intermediate_rank >= 3
            and (unit_rank >= 1 or formula_rank >= 2 or error_pressure == "high")
        ) or (
            routine_rank >= 2
            and step_rank >= 3
            and error_pressure == "high"
        ):
            return self._build_score("L4", evidence_summary, calc_bucket="embedded_calculation")

        if (
            step_chain == "3-4"
        ) or (
            number_mix == "mixed"
        ) or (
            routine_rank >= 1
        ) or (
            intermediate_rank >= 2
        ) or (
            unit_rank >= 1
        ) or (
            formula_rank >= 2
        ):
            return self._build_score("L3", evidence_summary, calc_bucket="embedded_calculation")

        if (
            step_chain == "2"
        ) or (
            number_mix == "standard"
        ) or (
            intermediate_rank >= 1
        ) or (
            formula_rank >= 1
        ):
            return self._build_score("L2", evidence_summary, calc_bucket="embedded_calculation")

        return self._build_score("L1", evidence_summary, calc_bucket="embedded_calculation")
