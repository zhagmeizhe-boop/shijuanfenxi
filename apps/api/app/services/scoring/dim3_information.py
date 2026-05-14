"""
dim3 information extraction and conversion burden scorer.

The scorer consumes normalized information-extraction facts and maps them to
L1-L5 fixed representative scores.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.services.scoring.base import BaseDimensionScorer, DimensionScore

INFORMATION_ROLE_VALUES = {"none", "supporting", "core"}
SOURCE_FORM_VALUES = {"text_only", "table_chart", "image_text", "multi_source"}
RELEVANT_CONDITION_COUNT_VALUES = {"1-2", "3-4", "5-6", "7+"}
DISTRACTOR_PRESSURE_VALUES = {"none", "light", "heavy"}
CONDITION_DISTRIBUTION_VALUES = {"compact", "split", "cross_sentence", "cross_modal"}
SCENARIO_COMPREHENSION_LOAD_VALUES = {"none", "light", "medium", "heavy"}
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
    "range_narrowing",
}
OBJECT_COUNT_BAND_VALUES = {"1", "2", "3", "4+"}
APPLICATION_COUNT_VALUES = {"0", "1", "2", "3+"}
BASE_QUANTITY_SHIFT_VALUES = {"none", "single", "multiple"}
COMPARISON_CANDIDATE_COUNT_VALUES = {"0", "2", "3+"}

DIM3_LEVELS = {
    "L1": {"score": 2.0, "level": 1, "label": "L1 直接提取"},
    "L2": {"score": 4.0, "level": 2, "label": "L2 单次转化"},
    "L3": {"score": 6.0, "level": 3, "label": "L3 多条件转化"},
    "L4": {"score": 8.0, "level": 4, "label": "L4 高负担组织"},
    "L5": {"score": 9.5, "level": 5, "label": "L5 高阶重构建模"},
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


def _normalize_zero_one(value: Any) -> int | None:
    if value in (0, "0", False):
        return 0
    if value in (1, "1", True):
        return 1
    return None


def _conversion_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(value, -1)


def _condition_count_rank(value: str) -> int:
    return {"1-2": 1, "3-4": 2, "5-6": 3, "7+": 4}.get(value, -1)


def _application_count_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(value, 0)


def _object_count_rank(value: str) -> int:
    return {"1": 1, "2": 2, "3": 3, "4+": 4}.get(value, 0)


def _comparison_candidate_rank(value: str) -> int:
    return {"0": 0, "2": 2, "3+": 3}.get(value, 0)


def _scenario_load_rank(value: str) -> int:
    return {"none": 0, "light": 1, "medium": 2, "heavy": 3}.get(value, 0)


class Dim3InformationScorer(BaseDimensionScorer):
    DIMENSION_CODE = "dim3"
    DIMENSION_NAME = "信息提取与转化"

    def __init__(self):
        super().__init__(config=None)

    def _build_score(
        self,
        level_code: str,
        evidence_summary: str,
        *,
        extra_details: Dict[str, Any] | None = None,
    ) -> DimensionScore:
        level = DIM3_LEVELS[level_code]
        details = {"status": "applicable", "dim3_level": level_code}
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
            details={"status": "not_applicable", "dim3_level": "N/A"},
        )

    def _calculate_score(self, features: Dict[str, Any]) -> DimensionScore:
        information_role = _normalize_choice(features.get("information_role"), INFORMATION_ROLE_VALUES)
        source_form = _normalize_choice(features.get("source_form"), SOURCE_FORM_VALUES)
        relevant_condition_count = _normalize_choice(
            features.get("relevant_condition_count"),
            RELEVANT_CONDITION_COUNT_VALUES,
        )
        distractor_pressure = _normalize_choice(
            features.get("distractor_pressure"),
            DISTRACTOR_PRESSURE_VALUES,
        )
        condition_distribution = _normalize_choice(
            features.get("condition_distribution"),
            CONDITION_DISTRIBUTION_VALUES,
        )
        scenario_comprehension_load = _normalize_choice(
            features.get("scenario_comprehension_load"),
            SCENARIO_COMPREHENSION_LOAD_VALUES,
        ) or "none"
        extraction_depth = _normalize_choice(features.get("extraction_depth"), EXTRACTION_DEPTH_VALUES)
        representation_conversion = _normalize_choice(
            features.get("representation_conversion"),
            REPRESENTATION_CONVERSION_VALUES,
        )
        conversion_step_count = _normalize_choice(
            features.get("conversion_step_count"),
            CONVERSION_STEP_COUNT_VALUES,
        )
        quantity_relation_structure = _normalize_choice(
            features.get("quantity_relation_structure"),
            QUANTITY_RELATION_STRUCTURE_VALUES,
        )
        target_representation = _normalize_choice(
            features.get("target_representation"),
            TARGET_REPRESENTATION_VALUES,
        )
        global_organizing_required = _normalize_zero_one(features.get("global_organizing_required"))
        image_dependency = _normalize_choice(features.get("image_dependency"), IMAGE_DEPENDENCY_VALUES)
        text_length_band = _normalize_choice(features.get("text_length_band"), TEXT_LENGTH_BAND_VALUES)
        application_relation_types = _normalize_choice_list(
            features.get("application_relation_types"),
            APPLICATION_RELATION_TYPE_VALUES,
        )
        application_relation_set = set(application_relation_types)
        object_count_band = _normalize_choice(features.get("object_count_band"), OBJECT_COUNT_BAND_VALUES)
        state_change_count = _normalize_choice(features.get("state_change_count"), APPLICATION_COUNT_VALUES)
        implicit_relation_count = _normalize_choice(features.get("implicit_relation_count"), APPLICATION_COUNT_VALUES)
        base_quantity_shift = _normalize_choice(features.get("base_quantity_shift"), BASE_QUANTITY_SHIFT_VALUES)
        comparison_candidate_count = _normalize_choice(
            features.get("comparison_candidate_count"),
            COMPARISON_CANDIDATE_COUNT_VALUES,
        )
        evidence_summary = str(features.get("evidence_summary", "")).strip()
        normalized_fact_details = {
            "information_role": information_role,
            "source_form": source_form,
            "relevant_condition_count": relevant_condition_count,
            "distractor_pressure": distractor_pressure,
            "condition_distribution": condition_distribution,
            "scenario_comprehension_load": scenario_comprehension_load,
            "extraction_depth": extraction_depth,
            "representation_conversion": representation_conversion,
            "conversion_step_count": conversion_step_count,
            "quantity_relation_structure": quantity_relation_structure,
            "target_representation": target_representation,
            "global_organizing_required": global_organizing_required,
            "image_dependency": image_dependency,
            "text_length_band": text_length_band,
            "evidence_summary": evidence_summary,
        }
        application_details = {
            **normalized_fact_details,
            "application_relation_types": application_relation_types,
            "object_count_band": object_count_band,
            "state_change_count": state_change_count,
            "implicit_relation_count": implicit_relation_count,
            "base_quantity_shift": base_quantity_shift,
            "comparison_candidate_count": comparison_candidate_count,
        }
        object_rank = _object_count_rank(object_count_band)
        state_rank = _application_count_rank(state_change_count)
        implicit_rank = _application_count_rank(implicit_relation_count)
        comparison_rank = _comparison_candidate_rank(comparison_candidate_count)
        scenario_rank = _scenario_load_rank(scenario_comprehension_load)

        required_values = [
            information_role,
            source_form,
            relevant_condition_count,
            distractor_pressure,
            condition_distribution,
            extraction_depth,
            representation_conversion,
            conversion_step_count,
            quantity_relation_structure,
            target_representation,
            image_dependency,
            evidence_summary,
        ]
        if any(value in ("", None) for value in required_values) or global_organizing_required is None:
            return self._invalid_score("dim3 关键信息提取事实不完整，无法自动判级。")

        if information_role != "core":
            return self._invalid_score("该题未满足 dim3 的核心信息提取与转化门槛。")

        if (
            representation_conversion == "custom_model"
            and target_representation == "custom_model"
            and quantity_relation_structure == "nested_relation"
            and global_organizing_required == 1
        ) or (
            source_form == "multi_source"
            and condition_distribution == "cross_modal"
            and conversion_step_count == "3+"
            and information_role == "core"
        ) or (
            {"reverse_process", "conservation_transfer"}.issubset(application_relation_set)
            and quantity_relation_structure == "nested_relation"
            and global_organizing_required == 1
            and state_rank >= 3
        ) or (
            scenario_comprehension_load == "heavy"
            and quantity_relation_structure == "nested_relation"
            and global_organizing_required == 1
            and _conversion_rank(conversion_step_count) >= 2
        ):
            return self._build_score("L5", evidence_summary, extra_details=application_details)

        if (
            representation_conversion in {"model_mapping", "custom_model"}
            and target_representation in {"equation_relation", "custom_model"}
            and conversion_step_count in {"2", "3+"}
        ) or (
            relevant_condition_count in {"5-6", "7+"}
            and condition_distribution in {"split", "cross_sentence", "cross_modal"}
            and extraction_depth in {"reorganized", "inferred"}
        ) or (
            quantity_relation_structure in {"multi_relation", "nested_relation"}
            and (
                distractor_pressure == "heavy"
                or global_organizing_required == 1
                or _conversion_rank(conversion_step_count) >= 2
            )
        ) or (
            source_form == "multi_source"
            and condition_distribution in {"cross_sentence", "cross_modal"}
            and extraction_depth in {"reorganized", "inferred"}
        ) or (
            text_length_band == "very_long"
        ) or (
            "queue_growth" in application_relation_set
            and (implicit_rank >= 2 or state_rank >= 2 or base_quantity_shift in {"single", "multiple"})
        ) or (
            "travel_meeting_chasing" in application_relation_set
            and (state_rank >= 2 or implicit_rank >= 2 or base_quantity_shift == "multiple")
        ) or (
            "profit_discount" in application_relation_set
            and (state_rank >= 2 or implicit_rank >= 2 or object_rank >= 2)
        ) or (
            "concentration_mixture" in application_relation_set
            and (state_rank >= 2 or base_quantity_shift in {"single", "multiple"})
        ) or (
            "optimization_comparison" in application_relation_set
            and comparison_rank >= 3
        ) or (
            "multi_object_distribution" in application_relation_set
            and object_rank >= 3
            and implicit_rank >= 2
        ) or (
            "reverse_process" in application_relation_set
            and state_rank >= 3
        ) or (
            len(application_relation_set) >= 2
            and (
                state_rank >= 2
                or implicit_rank >= 2
                or object_rank >= 3
                or comparison_rank >= 3
            )
        ) or (
            scenario_comprehension_load == "heavy"
            and (
                relevant_condition_count in {"5-6", "7+"}
                or condition_distribution in {"split", "cross_sentence", "cross_modal"}
                or source_form in {"image_text", "multi_source"}
                or state_rank >= 2
                or implicit_rank >= 2
                or object_rank >= 3
                or comparison_rank >= 3
                or global_organizing_required == 1
            )
        ):
            return self._build_score("L4", evidence_summary, extra_details=application_details)

        if (
            representation_conversion in {"relation_mapping", "model_mapping"}
        ) or (
            extraction_depth in {"reorganized", "inferred"}
            and representation_conversion in {"direct_mapping", "relation_mapping"}
            and (
                _conversion_rank(conversion_step_count) >= 1
                or target_representation in {"direct_formula", "equation_relation", "table_list"}
                or quantity_relation_structure == "single_relation"
            )
        ) or (
            source_form in {"table_chart", "image_text"}
            and extraction_depth in {"selected", "reorganized", "inferred"}
            and _conversion_rank(conversion_step_count) >= 1
            and _condition_count_rank(relevant_condition_count) >= 2
        ) or (
            condition_distribution in {"split", "cross_sentence"}
        ) or (
            relevant_condition_count in {"5-6", "7+"}
        ) or (
            quantity_relation_structure == "multi_relation"
        ) or (
            target_representation in {"table_list", "equation_relation"}
            and _conversion_rank(conversion_step_count) >= 1
        ) or (
            text_length_band == "long"
        ) or (
            bool(
                application_relation_set
                & {
                    "work_rate",
                    "percentage_base_change",
                    "concentration_mixture",
                    "profit_discount",
                    "ratio_allocation",
                    "travel_meeting_chasing",
                    "chart_table_conversion",
                    "equation_setup",
                    "reverse_process",
                    "cycle_period",
                    "multi_object_distribution",
                    "conservation_transfer",
                }
            )
        ) or (
            object_rank >= 2
        ) or (
            state_rank >= 1
        ) or (
            implicit_rank >= 1
        ) or (
            base_quantity_shift in {"single", "multiple"}
        ) or (
            comparison_rank >= 2
        ) or (
            scenario_rank >= 2
        ) or (
            "range_narrowing" in application_relation_set
        ):
            return self._build_score("L3", evidence_summary, extra_details=application_details)

        if (
            relevant_condition_count == "3-4"
        ) or (
            distractor_pressure == "light"
        ) or (
            conversion_step_count == "1"
        ) or (
            source_form in {"table_chart", "image_text"}
            and target_representation in {"direct_formula", "table_list"}
        ) or (
            scenario_comprehension_load == "light"
        ) or (
            quantity_relation_structure == "single_relation"
        ):
            return self._build_score("L2", evidence_summary, extra_details=application_details)

        return self._build_score("L1", evidence_summary, extra_details=application_details)
