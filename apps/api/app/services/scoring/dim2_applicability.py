"""
dim2 applicability gating.

dim2 evaluates spatial burden only.
It is tri-state:
- applicable
- review
- not_applicable
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

DIM2_STATUS_APPLICABLE = "applicable"
DIM2_STATUS_REVIEW = "review"
DIM2_STATUS_NOT_APPLICABLE = "not_applicable"
DIM2_REVIEW_CONFIDENCE_THRESHOLD = 0.55

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
GEOMETRY_VISUAL_CATEGORIES = {
    "geometry_visual",
    "geometry_context",
    "spatial_3d",
    "geometry_3d",
    "3d_geometry",
    "explicit_visual",
}
OCR_DAMAGE_MARKERS = ("OCR", "残缺", "缺损", "截断", "识别失败")
GEOMETRY_NOUN_PATTERN = re.compile(
    r"(三角形|长方形|正方形|平行四边形|梯形|圆|扇形|立方体|正方体|长方体|圆柱|圆锥|展开图|截面|视图|蝴蝶模型|燕尾模型|一半模型|鸟头|沙漏|割补|等高|共边|格点|三视图|水中浸物|长度计算|角度计算|图形变换)"
)
LOW_BARRIER_GEOMETRY_MODEL_TYPES = {
    "basic_area_formula",
    "circle_sector_formula",
    "solid_formula",
    "polygon_angle_sum",
    "opposite_faces",
}
SHORT_GEOMETRY_IMAGE_PATTERN = re.compile(
    "(?:S\\s*\u9634|S\u9634\u5f71|\u9634\u5f71(?:\u90e8\u5206)?(?:\u9762\u79ef)?|"
    "\u5706\u5185\u6700\u5927\u6b63\u65b9\u5f62|\u5185\u63a5\u6b63\u65b9\u5f62|"
    "\u9732\u5728\u5916\u9762\u7684\u9762\u79ef|\u5982\u56fe.*\u6c42\u9762\u79ef|"
    "\u56fe\u4e2d.*\u6c42\u9762\u79ef|\u6c42\\s*S)"
)
SPATIAL_3D_IMAGE_PATTERN = re.compile(
    "(?:\u9732\u5728\u5916\u9762|\u5c0f\u6b63\u65b9\u4f53|\u6b63\u65b9\u4f53|"
    "\u957f\u65b9\u4f53|\u68f1\u957f|\u7acb\u4f53|\u8868\u9762\u79ef)"
)
CIRCLE_SQUARE_IMAGE_PATTERN = re.compile(
    "(?:\u5706\u5185\u6700\u5927\u6b63\u65b9\u5f62|\u5185\u63a5\u6b63\u65b9\u5f62|"
    "\u5706.*\u6b63\u65b9\u5f62|\u6b63\u65b9\u5f62.*\u5706)"
)
WATER_VOLUME_IMAGE_PATTERN = re.compile(
    "(?:(?=.*(?:\u74f6(?:\u5b50)?|\u88c5\u6c34|\u6c34\u4f4d|\u5012\u653e|\u5012\u7f6e|\u5706\u67f1\u5bb9\u5668))"
    "(?=.*(?:\u6c34|\u5bb9\u79ef|\u4f53\u79ef|\u5e95\u9762\u79ef|\u5398\u7c73))|"
    "\u6c34.*\u5398\u7c73|\u5398\u7c73.*\u6c34)"
)
MEASUREMENT_IMAGE_PATTERN = re.compile(
    "(?=.*(?:\u5982\u56fe|\u56fe\u4e2d|\u6807\u660e\u7684\u6570\u636e|\u56fe\u793a))"
    "(?=.*(?:\u5398\u7c73|\u5e73\u65b9\u5398\u7c73|\u5e73\u65b9\u7c73|\u5bb9\u79ef|"
    "\u4f53\u79ef|\u5e95\u9762\u79ef|\u9762\u79ef|\u6c34))"
)
RECTANGLE_REVERSE_AREA_PATTERN = re.compile(
    "(?=.*\u957f\u65b9\u5f62)(?=.*\u957f(?:\u51cf\u5c11|\u7f29\u77ed))"
    "(?=.*\u5bbd(?:\u51cf\u5c11|\u7f29\u77ed))(?=.*\u9762\u79ef.*\u51cf\u5c11)"
    "(?=.*\u6b63\u65b9\u5f62)"
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
        "task_form": _normalize_choice(feature.get("task_form"), TASK_FORM_VALUES),
        "spatial_role": _normalize_choice(feature.get("spatial_role"), SPATIAL_ROLE_VALUES),
        "figure_complexity": _normalize_choice(feature.get("figure_complexity"), FIGURE_COMPLEXITY_VALUES),
        "relation_hops": _normalize_choice(feature.get("relation_hops"), RELATION_HOPS_VALUES),
        "hidden_relation_count": _normalize_choice(
            feature.get("hidden_relation_count"),
            HIDDEN_RELATION_COUNT_VALUES,
        ),
        "visual_operation_count": _normalize_choice(
            feature.get("visual_operation_count"),
            VISUAL_OPERATION_COUNT_VALUES,
        ),
        "structural_visual_method": _normalize_choice(
            feature.get("structural_visual_method"),
            STRUCTURAL_VISUAL_METHOD_VALUES,
        ),
        "measurement_dependency": _normalize_choice(
            feature.get("measurement_dependency"),
            MEASUREMENT_DEPENDENCY_VALUES,
        ),
        "global_view_required": _normalize_zero_one(feature.get("global_view_required")),
        "image_dependency": _normalize_choice(feature.get("image_dependency"), IMAGE_DEPENDENCY_VALUES),
        "evidence_summary": str(feature.get("evidence_summary", "")).strip(),
    }
    return [key for key, value in checks.items() if value in ("", None)]


def _has_geometry_signal(raw_text: str, parse_audit: Any) -> bool:
    visual_category = str(_audit_attr(parse_audit, "visual_category", "") or "").strip()
    text = str(raw_text or "")
    if visual_category in GEOMETRY_VISUAL_CATEGORIES:
        return True
    if SHORT_GEOMETRY_IMAGE_PATTERN.search(text):
        return True
    if WATER_VOLUME_IMAGE_PATTERN.search(text):
        return True
    if MEASUREMENT_IMAGE_PATTERN.search(text):
        return True
    if RECTANGLE_REVERSE_AREA_PATTERN.search(text):
        return True
    return bool(GEOMETRY_NOUN_PATTERN.search(text))


def has_dim2_short_geometry_signal(raw_text: str) -> bool:
    """Return True for terse image-backed geometry prompts such as S阴=."""
    return bool(SHORT_GEOMETRY_IMAGE_PATTERN.search(str(raw_text or "")))


def _has_visual_fallback_signal(raw_text: str, parse_audit: Any) -> bool:
    visual_category = str(_audit_attr(parse_audit, "visual_category", "") or "").strip()
    text = str(raw_text or "")
    return (
        visual_category in {"geometry_visual", "spatial_3d"}
        or bool(_audit_attr(parse_audit, "image_required_hint", False))
        or has_dim2_short_geometry_signal(text)
        or bool(WATER_VOLUME_IMAGE_PATTERN.search(text))
        or bool(MEASUREMENT_IMAGE_PATTERN.search(text))
    )


def _feature_present(feature: Dict[str, Any]) -> bool:
    return any(
        str(feature.get(key, "")).strip()
        for key in (
            "task_form",
            "spatial_role",
            "figure_complexity",
            "relation_hops",
            "hidden_relation_count",
            "visual_operation_count",
            "structural_visual_method",
            "measurement_dependency",
            "image_dependency",
            "geometry_model_count",
            "model_recognition_role",
            "area_relation_chain",
            "model_combination_complexity",
            "evidence_summary",
        )
    ) or bool(_normalize_choice_list(feature.get("geometry_model_types"), GEOMETRY_MODEL_TYPE_VALUES))


def _should_replace_with_visual_fallback(feature: Dict[str, Any]) -> bool:
    spatial_role = _normalize_choice(feature.get("spatial_role"), SPATIAL_ROLE_VALUES)
    confidence = _normalize_float(feature.get("applicability_confidence"))
    return (
        not _feature_present(feature)
        or bool(_missing_fields(feature))
        or spatial_role in {"", "none"}
        or (confidence is not None and confidence < DIM2_REVIEW_CONFIDENCE_THRESHOLD)
    )


def build_dim2_visual_fallback_facts(
    raw_text: str,
    dim2_feature: Dict[str, Any] | None = None,
    *,
    parse_audit: Any = None,
    has_image: bool = False,
    used_image: bool = False,
    image_fallback: bool = False,
) -> Dict[str, Any] | None:
    """Build conservative dim2 facts for image-backed geometry prompts.

    This is intentionally narrow: it only activates when an image exists or was
    used, the prompt/audit has strong geometry-image signals, and the LLM facts
    are missing, low-confidence, or incorrectly marked as spatial_role=none.
    """
    feature = dim2_feature or {}
    text = str(raw_text or "")
    if RECTANGLE_REVERSE_AREA_PATTERN.search(text) and _should_replace_with_visual_fallback(feature):
        return {
            "task_form": "geometry_embedded",
            "spatial_role": "core",
            "figure_complexity": "composite_2d",
            "relation_hops": "2",
            "hidden_relation_count": "1",
            "visual_operation_count": "1",
            "structural_visual_method": "decomposition",
            "measurement_dependency": "inferred",
            "global_view_required": 1,
            "image_dependency": "helpful",
            "geometry_model_types": ["reverse_area_edge"],
            "geometry_model_count": "1",
            "model_recognition_role": "core",
            "area_relation_chain": "single",
            "model_combination_complexity": "single_model",
            "evidence_summary": "图形结构兜底事实：长方形长宽同时减少且剩余为正方形，需要把面积减少量转成边长关系。",
            "evidence_tags": ["图形结构兜底", "长方形面积", "反推边长", "剩余正方形"],
            "applicability_confidence": 0.68,
            "need_manual_review": 0,
            "warning": "",
            "fallback_source": "geometry_structure",
        }

    if image_fallback or not (has_image or used_image):
        return None
    if not _has_visual_fallback_signal(raw_text, parse_audit):
        return None
    if not _should_replace_with_visual_fallback(feature):
        return None

    if WATER_VOLUME_IMAGE_PATTERN.search(text):
        return {
            "task_form": "explicit_visual",
            "spatial_role": "core",
            "figure_complexity": "solid_3d",
            "relation_hops": "3-4",
            "hidden_relation_count": "2+",
            "visual_operation_count": "2",
            "structural_visual_method": "3d_transform",
            "measurement_dependency": "inferred",
            "global_view_required": 1,
            "image_dependency": "required",
            "geometry_model_types": ["water_displacement", "solid_formula"],
            "geometry_model_count": "1",
            "model_recognition_role": "core",
            "area_relation_chain": "multi",
            "model_combination_complexity": "model_plus_operation",
            "evidence_summary": "图像几何兜底事实：瓶子装水、正放/倒放或水位数据需要结合图中高度与底面积关系反推容积。",
            "evidence_tags": ["图像几何兜底", "瓶子容积", "水位关系", "立体体积"],
            "applicability_confidence": 0.7,
            "need_manual_review": 0,
            "warning": "",
            "fallback_source": "visual_geometry",
            "image_block_available": 1,
        }

    if MEASUREMENT_IMAGE_PATTERN.search(text):
        return {
            "task_form": "explicit_visual",
            "spatial_role": "core",
            "figure_complexity": "composite_2d",
            "relation_hops": "3-4",
            "hidden_relation_count": "1",
            "visual_operation_count": "1",
            "structural_visual_method": "decomposition",
            "measurement_dependency": "inferred",
            "global_view_required": 0,
            "image_dependency": "required",
            "geometry_model_types": ["composite_area_model"],
            "geometry_model_count": "1",
            "model_recognition_role": "core",
            "area_relation_chain": "single",
            "model_combination_complexity": "single_model",
            "evidence_summary": "图像几何兜底事实：题面要求依据图中标明数据和长度/面积单位读取几何关系。",
            "evidence_tags": ["图像几何兜底", "图中数据", "几何测量"],
            "applicability_confidence": 0.62,
            "need_manual_review": 0,
            "warning": "",
            "fallback_source": "visual_geometry",
            "image_block_available": 1,
        }

    if SPATIAL_3D_IMAGE_PATTERN.search(text):
        return {
            "task_form": "explicit_visual",
            "spatial_role": "core",
            "figure_complexity": "solid_3d",
            "relation_hops": "3-4",
            "hidden_relation_count": "2+",
            "visual_operation_count": "2",
            "structural_visual_method": "decomposition",
            "measurement_dependency": "inferred",
            "global_view_required": 1,
            "image_dependency": "required",
            "evidence_summary": "图像几何兜底事实：题面指向立体图形外露面或表面积判断，需要读取三维结构和遮挡关系。",
            "evidence_tags": ["图像几何兜底", "立体图形", "外露面"],
            "applicability_confidence": 0.68,
            "need_manual_review": 0,
            "warning": "",
            "fallback_source": "visual_geometry",
        }

    if CIRCLE_SQUARE_IMAGE_PATTERN.search(text):
        return {
            "task_form": "explicit_visual",
            "spatial_role": "core",
            "figure_complexity": "basic_2d",
            "relation_hops": "2",
            "hidden_relation_count": "1",
            "visual_operation_count": "1",
            "structural_visual_method": "none",
            "measurement_dependency": "inferred",
            "global_view_required": 1,
            "image_dependency": "helpful",
            "evidence_summary": "图像几何兜底事实：题面指向圆与正方形的叠合关系，需要识别内接/最大正方形的隐含几何关系。",
            "evidence_tags": ["图像几何兜底", "圆", "正方形"],
            "applicability_confidence": 0.66,
            "need_manual_review": 0,
            "warning": "",
            "fallback_source": "visual_geometry",
        }

    return {
        "task_form": "explicit_visual",
        "spatial_role": "core",
        "figure_complexity": "composite_2d",
        "relation_hops": "3-4",
        "hidden_relation_count": "1",
        "visual_operation_count": "1",
        "structural_visual_method": "decomposition",
        "measurement_dependency": "inferred",
        "global_view_required": 0,
        "image_dependency": "required",
        "evidence_summary": "图像几何兜底事实：题面为短文本图形题，需要结合题块图片读取阴影或组合图形关系。",
        "evidence_tags": ["图像几何兜底", "阴影面积", "组合图形"],
        "applicability_confidence": 0.66,
        "need_manual_review": 0,
        "warning": "",
        "fallback_source": "visual_geometry",
    }


def _has_ocr_damage_signals(parse_warnings: Iterable[str] | None) -> bool:
    for item in parse_warnings or []:
        text = str(item or "").strip()
        if text and any(marker in text for marker in OCR_DAMAGE_MARKERS):
            return True
    return False


def _relation_rank(value: str) -> int:
    return {"1": 1, "2": 2, "3-4": 3, "5+": 4}.get(value, -1)


def _hidden_relation_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2+": 2}.get(value, -1)


def _visual_operation_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(value, -1)


def _has_core_geometry_model(feature: Dict[str, Any]) -> bool:
    model_role = _normalize_choice(feature.get("model_recognition_role"), MODEL_RECOGNITION_ROLE_VALUES)
    model_types = _normalize_choice_list(feature.get("geometry_model_types"), GEOMETRY_MODEL_TYPE_VALUES)
    area_relation_chain = _normalize_choice(feature.get("area_relation_chain"), AREA_RELATION_CHAIN_VALUES)
    model_complexity = _normalize_choice(
        feature.get("model_combination_complexity"),
        MODEL_COMBINATION_COMPLEXITY_VALUES,
    )
    if model_types and all(item in LOW_BARRIER_GEOMETRY_MODEL_TYPES for item in model_types):
        return (
            model_role == "core"
            and (
                area_relation_chain in {"multi", "nested"}
                or model_complexity in {"model_plus_operation", "multi_model", "nested_model"}
            )
        )
    return model_role == "core" and bool(
        model_types
        or area_relation_chain in {"single", "multi", "nested"}
        or model_complexity in {"single_model", "model_plus_operation", "multi_model", "nested_model"}
    )


def _has_low_barrier_formula_model(feature: Dict[str, Any]) -> bool:
    model_types = _normalize_choice_list(feature.get("geometry_model_types"), GEOMETRY_MODEL_TYPE_VALUES)
    area_relation_chain = _normalize_choice(feature.get("area_relation_chain"), AREA_RELATION_CHAIN_VALUES)
    model_complexity = _normalize_choice(
        feature.get("model_combination_complexity"),
        MODEL_COMBINATION_COMPLEXITY_VALUES,
    )
    return bool(model_types) and all(
        item in LOW_BARRIER_GEOMETRY_MODEL_TYPES for item in model_types
    ) and area_relation_chain in {"", "none"} and model_complexity in {"", "none", "single_model"}


def _is_non_measurement_spatial_view(feature: Dict[str, Any]) -> bool:
    """True for view/projection tasks whose burden is spatial, not measurement."""
    figure_complexity = _normalize_choice(feature.get("figure_complexity"), FIGURE_COMPLEXITY_VALUES)
    structural_visual_method = _normalize_choice(
        feature.get("structural_visual_method"),
        STRUCTURAL_VISUAL_METHOD_VALUES,
    )
    image_dependency = _normalize_choice(feature.get("image_dependency"), IMAGE_DEPENDENCY_VALUES)
    model_types = _normalize_choice_list(feature.get("geometry_model_types"), GEOMETRY_MODEL_TYPE_VALUES)
    return (
        figure_complexity in {"solid_3d", "net_section_multi_view"}
        and structural_visual_method == "3d_transform"
        and image_dependency == "required"
        and any(item in {"surface_three_view", "solid_cut_join", "net_cut_join"} for item in model_types)
    )


def _simple_direct_geometry(feature: Dict[str, Any]) -> bool:
    if _has_core_geometry_model(feature):
        return False
    return (
        _normalize_choice(feature.get("measurement_dependency"), MEASUREMENT_DEPENDENCY_VALUES) == "direct"
        and _normalize_choice(feature.get("relation_hops"), RELATION_HOPS_VALUES) == "1"
        and _normalize_choice(feature.get("hidden_relation_count"), HIDDEN_RELATION_COUNT_VALUES) == "0"
        and _normalize_choice(feature.get("visual_operation_count"), VISUAL_OPERATION_COUNT_VALUES) == "0"
        and _normalize_choice(feature.get("structural_visual_method"), STRUCTURAL_VISUAL_METHOD_VALUES) == "none"
        and _normalize_zero_one(feature.get("global_view_required")) == 0
    )


def _has_high_burden_signal(feature: Dict[str, Any]) -> bool:
    return any(
        [
            _normalize_choice(feature.get("figure_complexity"), FIGURE_COMPLEXITY_VALUES)
            in {"composite_2d", "solid_3d", "net_section_multi_view"},
            _relation_rank(_normalize_choice(feature.get("relation_hops"), RELATION_HOPS_VALUES)) >= 3,
            _hidden_relation_rank(
                _normalize_choice(feature.get("hidden_relation_count"), HIDDEN_RELATION_COUNT_VALUES)
            )
            >= 1,
            _visual_operation_rank(
                _normalize_choice(feature.get("visual_operation_count"), VISUAL_OPERATION_COUNT_VALUES)
            )
            >= 2,
            _normalize_choice(feature.get("structural_visual_method"), STRUCTURAL_VISUAL_METHOD_VALUES)
            in {"decomposition", "auxiliary_line", "3d_transform"},
            _normalize_choice(feature.get("measurement_dependency"), MEASUREMENT_DEPENDENCY_VALUES) == "inferred",
            _normalize_zero_one(feature.get("global_view_required")) == 1,
            _normalize_choice(feature.get("image_dependency"), IMAGE_DEPENDENCY_VALUES) == "required",
            _has_core_geometry_model(feature),
        ]
    )


def _has_internal_conflict(feature: Dict[str, Any], parse_audit: Any) -> bool:
    task_form = _normalize_choice(feature.get("task_form"), TASK_FORM_VALUES)
    spatial_role = _normalize_choice(feature.get("spatial_role"), SPATIAL_ROLE_VALUES)
    figure_complexity = _normalize_choice(feature.get("figure_complexity"), FIGURE_COMPLEXITY_VALUES)
    image_dependency = _normalize_choice(feature.get("image_dependency"), IMAGE_DEPENDENCY_VALUES)
    measurement_dependency = _normalize_choice(feature.get("measurement_dependency"), MEASUREMENT_DEPENDENCY_VALUES)
    relation_hops = _normalize_choice(feature.get("relation_hops"), RELATION_HOPS_VALUES)
    hidden_relation_count = _normalize_choice(feature.get("hidden_relation_count"), HIDDEN_RELATION_COUNT_VALUES)
    visual_operation_count = _normalize_choice(feature.get("visual_operation_count"), VISUAL_OPERATION_COUNT_VALUES)
    structural_visual_method = _normalize_choice(
        feature.get("structural_visual_method"),
        STRUCTURAL_VISUAL_METHOD_VALUES,
    )
    visual_category = str(_audit_attr(parse_audit, "visual_category", "") or "").strip()

    has_core_model = _has_core_geometry_model(feature)

    if spatial_role == "none" and _has_high_burden_signal(feature) and not has_core_model:
        return True
    if spatial_role == "core" and _simple_direct_geometry(feature) and not _has_low_barrier_formula_model(feature):
        return True
    if task_form == "explicit_visual" and image_dependency == "none":
        return True
    if task_form == "nonvisual" and image_dependency == "required":
        return True
    if task_form == "text_only_geometry" and image_dependency == "required":
        return True
    if image_dependency == "required" and figure_complexity == "none":
        return True
    if measurement_dependency == "none" and not _is_non_measurement_spatial_view(feature) and (
        relation_hops in {"2", "3-4", "5+"}
        or hidden_relation_count in {"1", "2+"}
        or visual_operation_count in {"1", "2", "3+"}
        or structural_visual_method != "none"
    ):
        return True
    if visual_category in GEOMETRY_VISUAL_CATEGORIES and spatial_role == "none" and not has_core_model:
        return True
    return False


def evaluate_dim2_applicability(
    raw_text: str,
    dim2_feature: Dict[str, Any] | None = None,
    *,
    llm_confidence: float | None = None,
    parse_audit: Any = None,
    used_image: bool = False,
    image_fallback: bool = False,
    parse_warnings: Iterable[str] | None = None,
) -> Dict[str, Any]:
    feature = dim2_feature or {}
    task_form = _normalize_choice(feature.get("task_form"), TASK_FORM_VALUES)
    spatial_role = _normalize_choice(feature.get("spatial_role"), SPATIAL_ROLE_VALUES)
    image_dependency = _normalize_choice(feature.get("image_dependency"), IMAGE_DEPENDENCY_VALUES)
    image_block_available = _normalize_zero_one(feature.get("image_block_available")) == 1
    model_recognition_role = _normalize_choice(
        feature.get("model_recognition_role"),
        MODEL_RECOGNITION_ROLE_VALUES,
    )
    visual_category = str(_audit_attr(parse_audit, "visual_category", "") or "").strip()
    block_completeness = _normalize_float(_audit_attr(parse_audit, "block_completeness"))
    warnings: List[str] = []

    has_geometry_signal = _has_geometry_signal(raw_text, parse_audit)
    feature_present = any(
        str(feature.get(key, "")).strip()
        for key in (
            "task_form",
            "spatial_role",
            "figure_complexity",
            "relation_hops",
            "hidden_relation_count",
            "visual_operation_count",
            "structural_visual_method",
            "measurement_dependency",
            "image_dependency",
            "evidence_summary",
        )
    )
    if not feature_present and not has_geometry_signal:
        return {
            "status": DIM2_STATUS_NOT_APPLICABLE,
            "reason": "该题没有稳定的图形直观或空间想象负担，dim2 不适用。",
            "warnings": [],
        }

    missing_fields = _missing_fields(feature)
    if missing_fields:
        warnings.append(f"dim2 缺少关键空间事实字段：{'、'.join(missing_fields)}。")

    feature_confidence = _normalize_float(feature.get("applicability_confidence"))
    effective_confidence = feature_confidence if feature_confidence is not None else _normalize_float(llm_confidence)
    if effective_confidence is not None and effective_confidence < DIM2_REVIEW_CONFIDENCE_THRESHOLD:
        warnings.append(
            f"dim2 置信度低于自动判分阈值（{DIM2_REVIEW_CONFIDENCE_THRESHOLD:.2f}）。"
        )

    if image_dependency == "required" and not used_image and not image_block_available:
        warnings.append("dim2 依赖图片，但当前未稳定使用题块图片。")
    if image_dependency == "required" and image_fallback:
        warnings.append("dim2 依赖图片，但当前已退回纯文本分析。")
    if _audit_attr(parse_audit, "image_required_hint", False) and not used_image:
        warnings.append("OCR 审计提示该题需要图片，但当前未稳定使用图片。")
    if block_completeness is not None and block_completeness < 0.65 and image_dependency == "required":
        warnings.append("题块完整度不足，当前 dim2 结果需人工复核。")
    if (
        visual_category in {"geometry_visual", "geometry_context", "spatial_3d"}
        and spatial_role == "none"
        and not _has_core_geometry_model(feature)
    ):
        warnings.append("OCR 视觉类别提示几何/空间题，但 dim2 标记为 none。")
    if parse_audit is not None and _audit_attr(parse_audit, "image_required_hint", False) and image_fallback:
        warnings.append("题目被 OCR 判定为依赖图片，但多模态调用未稳定成功。")
    if _has_ocr_damage_signals(parse_warnings) and (spatial_role == "core" or image_dependency == "required"):
        warnings.append("dim2 题面存在 OCR 或图片质量问题，当前结果需人工复核。")
    if _has_internal_conflict(feature, parse_audit):
        warnings.append("dim2 空间角色与空间负担特征冲突，当前结果需人工复核。")

    if warnings:
        return {
            "status": DIM2_STATUS_REVIEW,
            "reason": "dim2 空间事实缺失、冲突或图像依赖不稳定，当前题目转入人工复核。",
            "warnings": list(dict.fromkeys(item for item in warnings if item)),
        }

    if (spatial_role == "core" or model_recognition_role == "core") and not _simple_direct_geometry(feature):
        return {
            "status": DIM2_STATUS_APPLICABLE,
            "reason": "空间表征或图形关系读取构成该题核心门槛，dim2 适用。",
            "warnings": [],
        }

    if (
        spatial_role == "none"
        or task_form == "nonvisual"
        or spatial_role == "supporting"
        or _simple_direct_geometry(feature)
    ):
        return {
            "status": DIM2_STATUS_NOT_APPLICABLE,
            "reason": "该题的图形或空间因素不是核心门槛，dim2 不适用。",
            "warnings": [],
        }

    return {
        "status": DIM2_STATUS_NOT_APPLICABLE,
        "reason": "dim2 边界题尚未形成稳定自动判分依据，当前维度不纳入自动评分。",
        "warnings": [],
    }
