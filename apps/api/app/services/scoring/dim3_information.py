"""
dim3 scenario-comprehension scorer.

The scorer keeps the historical ``dim3_information`` payload key for API
compatibility, but the dimension now measures reading-level scene complexity:
whether pupils can understand the setting, rules, process, feedback,
comparison wording, and text-image correspondence before solving.
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
SCENARIO_RULE_COUNT_VALUES = {"0", "1", "2", "3+"}
PROCESS_STAGE_COUNT_VALUES = {"1", "2", "3", "4+"}
FEEDBACK_MECHANISM_VALUES = {"none", "simple", "conditional"}
COMPARISON_BASIS_VALUES = {"none", "direct", "implicit", "multi_condition"}
DIAGRAM_CORRESPONDENCE_VALUES = {"none", "helpful", "required", "multi_step"}
SCENARIO_RULE_TYPE_VALUES = {
    "sequence_order",
    "comparison_basis",
    "feedback_rule",
    "conditional_trigger",
    "diagram_mapping",
    "multi_object_roles",
    "multi_stage_process",
    "custom_rule_system",
}

DIM3_LEVELS = {
    "L1": {"score": 2.0, "level": 1, "label": "L1 场景直读"},
    "L2": {"score": 4.0, "level": 2, "label": "L2 简单对象过程"},
    "L3": {"score": 6.0, "level": 3, "label": "L3 关键问法理解"},
    "L4": {"score": 8.0, "level": 4, "label": "L4 多场景要素整合"},
    "L5": {"score": 9.5, "level": 5, "label": "L5 复杂规则系统理解"},
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


def _rule_count_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(value, 0)


def _stage_count_rank(value: str) -> int:
    return {"1": 1, "2": 2, "3": 3, "4+": 4}.get(value, 1)


def _feedback_rank(value: str) -> int:
    return {"none": 0, "simple": 1, "conditional": 2}.get(value, 0)


def _comparison_basis_rank(value: str) -> int:
    return {"none": 0, "direct": 1, "implicit": 2, "multi_condition": 3}.get(value, 0)


def _diagram_rank(value: str) -> int:
    return {"none": 0, "helpful": 1, "required": 2, "multi_step": 3}.get(value, 0)


class Dim3InformationScorer(BaseDimensionScorer):
    DIMENSION_CODE = "dim3"
    DIMENSION_NAME = "场景理解复杂度"

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
            image_dependency,
            evidence_summary,
        ]
        if any(value in ("", None) for value in required_values):
            return self._invalid_score("dim3 关键场景理解事实不完整，无法自动判级。")

        if information_role == "none":
            return self._invalid_score("该题没有真实读题场景负担，dim3 不适用。")

        scenario_rule_count = _normalize_choice(
            features.get("scenario_rule_count"),
            SCENARIO_RULE_COUNT_VALUES,
        ) or "0"
        process_stage_count = _normalize_choice(
            features.get("process_stage_count"),
            PROCESS_STAGE_COUNT_VALUES,
        ) or "1"
        feedback_mechanism = _normalize_choice(
            features.get("feedback_mechanism"),
            FEEDBACK_MECHANISM_VALUES,
        ) or "none"
        comparison_basis = _normalize_choice(
            features.get("comparison_basis"),
            COMPARISON_BASIS_VALUES,
        ) or "none"
        diagram_correspondence = _normalize_choice(
            features.get("diagram_correspondence"),
            DIAGRAM_CORRESPONDENCE_VALUES,
        ) or (
            "required"
            if image_dependency == "required"
            else "helpful"
            if image_dependency == "helpful"
            else "none"
        )
        scenario_rule_types = _normalize_choice_list(
            features.get("scenario_rule_types"),
            SCENARIO_RULE_TYPE_VALUES,
        )

        rule_rank = _rule_count_rank(scenario_rule_count)
        stage_rank = max(_stage_count_rank(process_stage_count), state_rank + 1 if state_rank else 1)
        feedback_rank = _feedback_rank(feedback_mechanism)
        comparison_basis_rank = max(_comparison_basis_rank(comparison_basis), comparison_rank)
        diagram_rank = _diagram_rank(diagram_correspondence)
        scenario_rule_set = set(scenario_rule_types)

        application_details.update(
            {
                "scenario_rule_count": scenario_rule_count,
                "process_stage_count": process_stage_count,
                "feedback_mechanism": feedback_mechanism,
                "comparison_basis": comparison_basis,
                "diagram_correspondence": diagram_correspondence,
                "scenario_rule_types": scenario_rule_types,
            }
        )

        scenario_integration_axes: List[str] = []

        def add_integration_axis(axis: str, condition: bool) -> None:
            if condition and axis not in scenario_integration_axes:
                scenario_integration_axes.append(axis)

        add_integration_axis(
            "multi_source_or_cross_modal",
            source_form == "multi_source" or condition_distribution == "cross_modal",
        )
        add_integration_axis(
            "visual_material_mapping",
            source_form in {"table_chart", "image_text"}
            and (
                diagram_rank >= 2
                or scenario_rank >= 2
                or rule_rank >= 1
                or condition_distribution in {"split", "cross_sentence", "cross_modal"}
            ),
        )
        add_integration_axis("multi_object_roles", object_rank >= 3 or "multi_object_roles" in scenario_rule_set)
        add_integration_axis("multi_stage_process", stage_rank >= 2 or "multi_stage_process" in scenario_rule_set)
        add_integration_axis(
            "rule_relationship",
            rule_rank >= 2
            or len(scenario_rule_set) >= 2
            or bool(scenario_rule_set & {"feedback_rule", "conditional_trigger", "custom_rule_system"}),
        )
        add_integration_axis(
            "diagram_rule_mapping",
            diagram_rank >= 2 or "diagram_mapping" in scenario_rule_set,
        )
        add_integration_axis(
            "comparison_basis",
            comparison_basis == "multi_condition"
            or comparison_basis_rank >= 3
            or (
                comparison_basis_rank >= 2
                and (
                    object_rank >= 2
                    or stage_rank >= 2
                    or source_form in {"table_chart", "image_text", "multi_source"}
                )
            ),
        )
        add_integration_axis("feedback_or_range", feedback_rank >= 1 or "range_narrowing" in application_relation_set)
        add_integration_axis(
            "distributed_scene_information",
            condition_distribution in {"split", "cross_sentence", "cross_modal"},
        )
        add_integration_axis(
            "multi_condition_hold",
            relevant_condition_count in {"5-6", "7+"}
            and (scenario_rank >= 2 or rule_rank >= 1 or source_form in {"table_chart", "image_text", "multi_source"}),
        )

        application_details.update(
            {
                "scenario_integration_axes": scenario_integration_axes,
                "scenario_integration_axis_count": len(scenario_integration_axes),
            }
        )

        scene_signal_count = sum(
            int(flag)
            for flag in (
                scenario_rank >= 1,
                source_form in {"table_chart", "image_text", "multi_source"},
                condition_distribution in {"split", "cross_sentence", "cross_modal"},
                object_rank >= 2,
                stage_rank >= 2,
                rule_rank >= 1,
                feedback_rank >= 1,
                comparison_basis_rank >= 1,
                diagram_rank >= 1,
                bool(scenario_rule_set),
            )
        )
        has_real_scene_burden = scene_signal_count >= 1
        if not has_real_scene_burden:
            return self._invalid_score("该题没有真实读题场景负担，dim3 不适用。")

        l5_system_axes = sum(
            int(flag)
            for flag in (
                rule_rank >= 3 or len(scenario_rule_set) >= 3,
                stage_rank >= 3,
                object_rank >= 3,
                feedback_rank >= 2,
                diagram_rank >= 2,
                comparison_basis_rank >= 3,
                "conditional_trigger" in scenario_rule_set,
                "custom_rule_system" in scenario_rule_set,
            )
        )
        if scenario_rank >= 3 and l5_system_axes >= 3 and (
            rule_rank >= 3
            or (
                {"conditional_trigger", "feedback_rule", "custom_rule_system"}.issubset(scenario_rule_set)
                and stage_rank >= 3
            )
        ):
            return self._build_score("L5", evidence_summary, extra_details=application_details)

        if (
            scenario_rank >= 3
            and (
                rule_rank >= 2
                or stage_rank >= 3
                or feedback_rank >= 1
                or diagram_rank >= 2
                or object_rank >= 3
                or comparison_basis_rank >= 2
                or source_form == "multi_source"
                or condition_distribution == "cross_modal"
                or bool(
                    scenario_rule_set
                    & {
                        "feedback_rule",
                        "conditional_trigger",
                        "diagram_mapping",
                        "multi_stage_process",
                        "custom_rule_system",
                    }
                )
                or "range_narrowing" in application_relation_set
            )
        ):
            return self._build_score("L4", evidence_summary, extra_details=application_details)

        l4_axis_count = len(scenario_integration_axes)
        l4_has_core_scene_axis = bool(
            set(scenario_integration_axes)
            & {
                "multi_source_or_cross_modal",
                "multi_object_roles",
                "multi_stage_process",
                "rule_relationship",
                "diagram_rule_mapping",
                "comparison_basis",
                "feedback_or_range",
            }
        )
        if (
            scenario_rank >= 2
            and l4_axis_count >= 3
            and l4_has_core_scene_axis
            and not (scenario_rule_set <= {"comparison_basis"} and l4_axis_count <= 2)
        ) or (
            scenario_rank >= 1
            and l4_axis_count >= 4
            and l4_has_core_scene_axis
        ):
            return self._build_score("L4", evidence_summary, extra_details=application_details)

        if (
            scenario_rank >= 2
            or comparison_basis_rank >= 2
            or condition_distribution in {"split", "cross_sentence"}
            or (
                source_form in {"table_chart", "image_text"}
                and (
                    scenario_rank >= 2
                    or condition_distribution in {"split", "cross_sentence", "cross_modal"}
                    or comparison_basis_rank >= 1
                    or stage_rank >= 2
                    or rule_rank >= 1
                    or relevant_condition_count in {"5-6", "7+"}
                )
            )
            or object_rank >= 3
            or (object_rank >= 2 and scenario_rank >= 2)
            or stage_rank >= 3
            or (stage_rank >= 2 and scenario_rank >= 2)
            or rule_rank >= 1
            or feedback_rank >= 1
            or text_length_band == "long"
            or bool(
                scenario_rule_set
                & {
                    "sequence_order",
                    "comparison_basis",
                    "feedback_rule",
                    "diagram_mapping",
                    "multi_object_roles",
                    "multi_stage_process",
                }
            )
        ):
            return self._build_score("L3", evidence_summary, extra_details=application_details)

        if (
            relevant_condition_count == "3-4"
        ) or (
            distractor_pressure == "light"
        ) or (
            source_form in {"table_chart", "image_text"}
        ) or (
            object_rank >= 2
        ) or (
            stage_rank >= 2
        ):
            return self._build_score("L2", evidence_summary, extra_details=application_details)

        return self._build_score("L1", evidence_summary, extra_details=application_details)
