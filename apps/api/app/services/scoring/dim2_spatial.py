"""
dim2 spatial burden scorer.

The scorer consumes normalized spatial facts and maps them to
L1-L5 fixed representative scores.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.services.scoring.base import BaseDimensionScorer, DimensionScore

TASK_FORM_VALUES = {"nonvisual", "explicit_visual", "geometry_embedded", "text_only_geometry"}
SPATIAL_ROLE_VALUES = {"none", "supporting", "core"}
FIGURE_COMPLEXITY_VALUES = {
    "none",
    "basic_2d",
    "composite_2d",
    "solid_3d",
    "net_section_multi_view",
}
RELATION_HOPS_VALUES = {"1", "2", "3-4", "5+"}
HIDDEN_RELATION_COUNT_VALUES = {"0", "1", "2+"}
VISUAL_OPERATION_COUNT_VALUES = {"0", "1", "2", "3+"}
STRUCTURAL_VISUAL_METHOD_VALUES = {"none", "decomposition", "auxiliary_line", "3d_transform"}
MEASUREMENT_DEPENDENCY_VALUES = {"none", "direct", "inferred"}
IMAGE_DEPENDENCY_VALUES = {"none", "helpful", "required"}
GEOMETRY_MODEL_TYPE_VALUES = {
    "basic_area_formula",
    "reverse_area_edge",
    "butterfly_area",
    "swallowtail_area",
    "half_area",
    "equal_height_area",
    "shared_base_area",
    "equal_area_transform",
    "kite_area",
    "bird_head_sandglass",
    "pyramid_sandglass",
    "cut_and_fill",
    "grid_cut_fill",
    "auxiliary_parallel",
    "area_ratio_chain",
    "composite_area_model",
    "circle_sector_formula",
    "circle_sector_cut_fill",
    "rolling_rotation",
    "solid_formula",
    "water_displacement",
    "surface_three_view",
    "net_cut_join",
    "solid_cut_join",
    "length_translation",
    "directed_length",
    "angle_chasing_triangle",
    "angle_chasing_polygon",
    "polygon_angle_sum",
    "figure_transformation",
    "opposite_faces",
    "geometric_counting",
}
GEOMETRY_MODEL_COUNT_VALUES = {"0", "1", "2", "3+"}
MODEL_RECOGNITION_ROLE_VALUES = {"none", "supporting", "core"}
AREA_RELATION_CHAIN_VALUES = {"none", "single", "multi", "nested"}
MODEL_COMBINATION_COMPLEXITY_VALUES = {
    "none",
    "single_model",
    "model_plus_operation",
    "multi_model",
    "nested_model",
}
STABLE_AREA_MODEL_TYPES = {
    "butterfly_area",
    "swallowtail_area",
    "half_area",
    "equal_height_area",
    "shared_base_area",
    "equal_area_transform",
    "kite_area",
    "bird_head_sandglass",
    "grid_cut_fill",
    "circle_sector_cut_fill",
    "length_translation",
    "directed_length",
    "angle_chasing_triangle",
    "figure_transformation",
    "geometric_counting",
}
LOW_BARRIER_GEOMETRY_MODEL_TYPES = {
    "basic_area_formula",
    "circle_sector_formula",
    "solid_formula",
    "polygon_angle_sum",
    "opposite_faces",
}
HIGH_BURDEN_GEOMETRY_MODEL_TYPES = {
    "pyramid_sandglass",
    "rolling_rotation",
    "water_displacement",
    "surface_three_view",
    "net_cut_join",
    "solid_cut_join",
    "angle_chasing_polygon",
}

DIM2_LEVELS = {
    "L1": {"score": 2.0, "level": 1, "label": "L1 直接识图"},
    "L2": {"score": 4.0, "level": 2, "label": "L2 单关系识图"},
    "L3": {"score": 6.0, "level": 3, "label": "L3 复合图形关系"},
    "L4": {"score": 8.0, "level": 4, "label": "L4 结构变换想象"},
    "L5": {"score": 9.5, "level": 5, "label": "L5 高阶空间重构"},
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


def _relation_rank(value: str) -> int:
    return {"1": 1, "2": 2, "3-4": 3, "5+": 4}.get(value, -1)


def _hidden_relation_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2+": 2}.get(value, -1)


def _visual_operation_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(value, -1)


def _model_count_rank(value: str, model_types: List[str]) -> int:
    if value == "3+":
        return 3
    if value in {"0", "1", "2"}:
        return int(value)
    return min(len(model_types), 3)


class Dim2SpatialScorer(BaseDimensionScorer):
    DIMENSION_CODE = "dim2"
    DIMENSION_NAME = "几何直观与空间想象"

    def __init__(self):
        super().__init__(config=None)

    def _build_score(
        self,
        level_code: str,
        evidence_summary: str,
        details: Dict[str, Any] | None = None,
    ) -> DimensionScore:
        level = DIM2_LEVELS[level_code]
        score_details = {"status": "applicable", "dim2_level": level_code}
        if details:
            score_details.update(details)
        return DimensionScore(
            dimension_code=self.DIMENSION_CODE,
            score=level["score"],
            level=level["level"],
            level_label=level["label"],
            evidence=f"{level['label']}：{evidence_summary}",
            applicable=True,
            details=score_details,
        )

    def _invalid_score(self, evidence: str) -> DimensionScore:
        return DimensionScore(
            dimension_code=self.DIMENSION_CODE,
            score=0.0,
            level=0,
            level_label="N/A",
            evidence=evidence,
            applicable=False,
            details={"status": "not_applicable", "dim2_level": "N/A"},
        )

    def _calculate_score(self, features: Dict[str, Any]) -> DimensionScore:
        task_form = _normalize_choice(features.get("task_form"), TASK_FORM_VALUES)
        spatial_role = _normalize_choice(features.get("spatial_role"), SPATIAL_ROLE_VALUES)
        figure_complexity = _normalize_choice(features.get("figure_complexity"), FIGURE_COMPLEXITY_VALUES)
        relation_hops = _normalize_choice(features.get("relation_hops"), RELATION_HOPS_VALUES)
        hidden_relation_count = _normalize_choice(
            features.get("hidden_relation_count"),
            HIDDEN_RELATION_COUNT_VALUES,
        )
        visual_operation_count = _normalize_choice(
            features.get("visual_operation_count"),
            VISUAL_OPERATION_COUNT_VALUES,
        )
        structural_visual_method = _normalize_choice(
            features.get("structural_visual_method"),
            STRUCTURAL_VISUAL_METHOD_VALUES,
        )
        measurement_dependency = _normalize_choice(
            features.get("measurement_dependency"),
            MEASUREMENT_DEPENDENCY_VALUES,
        )
        global_view_required = _normalize_zero_one(features.get("global_view_required"))
        image_dependency = _normalize_choice(features.get("image_dependency"), IMAGE_DEPENDENCY_VALUES)
        geometry_model_types = _normalize_choice_list(
            features.get("geometry_model_types"),
            GEOMETRY_MODEL_TYPE_VALUES,
        )
        geometry_model_count = _normalize_choice(
            features.get("geometry_model_count"),
            GEOMETRY_MODEL_COUNT_VALUES,
        )
        model_recognition_role = _normalize_choice(
            features.get("model_recognition_role"),
            MODEL_RECOGNITION_ROLE_VALUES,
        ) or "none"
        area_relation_chain = _normalize_choice(
            features.get("area_relation_chain"),
            AREA_RELATION_CHAIN_VALUES,
        ) or "none"
        model_combination_complexity = _normalize_choice(
            features.get("model_combination_complexity"),
            MODEL_COMBINATION_COMPLEXITY_VALUES,
        ) or "none"
        evidence_summary = str(features.get("evidence_summary", "")).strip()

        required_values = [
            task_form,
            spatial_role,
            figure_complexity,
            relation_hops,
            hidden_relation_count,
            visual_operation_count,
            structural_visual_method,
            measurement_dependency,
            image_dependency,
            evidence_summary,
        ]
        if any(value in ("", None) for value in required_values) or global_view_required is None:
            return self._invalid_score("dim2 关键空间事实不完整，无法自动判级。")

        effective_spatial_core = spatial_role == "core" or model_recognition_role == "core"
        if not effective_spatial_core:
            return self._invalid_score("该题未满足 dim2 的核心空间负担条件。")

        relation_rank = _relation_rank(relation_hops)
        hidden_relation_rank = _hidden_relation_rank(hidden_relation_count)
        visual_operation_rank = _visual_operation_rank(visual_operation_count)
        model_count_rank = _model_count_rank(geometry_model_count, geometry_model_types)
        stable_model_count = len([item for item in geometry_model_types if item in STABLE_AREA_MODEL_TYPES])
        high_burden_model_count = len(
            [item for item in geometry_model_types if item in HIGH_BURDEN_GEOMETRY_MODEL_TYPES]
        )
        has_only_low_barrier_model = bool(geometry_model_types) and all(
            item in LOW_BARRIER_GEOMETRY_MODEL_TYPES for item in geometry_model_types
        )
        has_stable_area_model = stable_model_count > 0
        has_model_operation_combo = (
            model_combination_complexity in {"model_plus_operation", "multi_model", "nested_model"}
            or (model_count_rank >= 2 and ("cut_and_fill" in geometry_model_types or "area_ratio_chain" in geometry_model_types))
            or ("cut_and_fill" in geometry_model_types and has_stable_area_model)
            or (structural_visual_method in {"decomposition", "auxiliary_line"} and has_stable_area_model)
        )
        details = {
            "geometry_model_types": geometry_model_types,
            "geometry_model_count": geometry_model_count or ("3+" if model_count_rank >= 3 else str(model_count_rank)),
            "model_recognition_role": model_recognition_role,
            "area_relation_chain": area_relation_chain,
            "model_combination_complexity": model_combination_complexity,
        }

        if (
            structural_visual_method == "3d_transform"
            and global_view_required == 1
            and figure_complexity in {"solid_3d", "net_section_multi_view"}
            and (
                relation_hops == "5+"
                or visual_operation_count == "3+"
                or model_combination_complexity in {"multi_model", "nested_model"}
                or model_count_rank >= 2
            )
        ) or (
            relation_hops == "5+" and hidden_relation_count == "2+" and effective_spatial_core
        ) or (
            model_recognition_role == "core"
            and (
                model_combination_complexity == "nested_model"
                or (area_relation_chain == "nested" and model_count_rank >= 2)
                or (model_count_rank >= 3 and hidden_relation_count == "2+" and global_view_required == 1)
            )
        ):
            return self._build_score("L5", evidence_summary, details)

        if (
            structural_visual_method in {"auxiliary_line", "3d_transform"}
            and visual_operation_count in {"2", "3+"}
        ) or (
            figure_complexity in {"solid_3d", "net_section_multi_view"}
            and relation_hops in {"3-4", "5+"}
        ) or (
            global_view_required == 1
            and hidden_relation_count in {"1", "2+"}
            and relation_hops in {"3-4", "5+"}
        ) or (
            model_recognition_role == "core"
            and (
                has_model_operation_combo
                or model_count_rank >= 2
                or area_relation_chain == "multi"
                or ("area_ratio_chain" in geometry_model_types and hidden_relation_count in {"1", "2+"})
                or (has_stable_area_model and visual_operation_count in {"2", "3+"})
                or high_burden_model_count > 0
            )
        ):
            return self._build_score("L4", evidence_summary, details)

        if (
            structural_visual_method in {"decomposition", "auxiliary_line"}
        ) or (
            hidden_relation_count in {"1", "2+"}
        ) or (
            measurement_dependency == "inferred"
        ) or (
            relation_hops == "3-4"
            and figure_complexity in {"composite_2d", "solid_3d", "net_section_multi_view"}
        ) or (
            model_recognition_role == "core"
            and (
                has_stable_area_model
                or (area_relation_chain == "single" and not has_only_low_barrier_model)
                or ("area_ratio_chain" in geometry_model_types and not has_only_low_barrier_model)
            )
        ):
            return self._build_score("L3", evidence_summary, details)

        if (
            relation_hops == "2"
        ) or (
            figure_complexity == "composite_2d"
        ) or (
            visual_operation_count == "1"
        ) or (
            image_dependency == "required" and measurement_dependency == "direct"
        ):
            return self._build_score("L2", evidence_summary, details)

        if relation_rank < 0 or hidden_relation_rank < 0 or visual_operation_rank < 0:
            return self._invalid_score("dim2 空间事实取值非法，无法自动判级。")

        return self._build_score("L1", evidence_summary, details)
