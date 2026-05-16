from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


DATA_PATH = (
    Path(__file__).resolve().parents[3]
    / "config"
    / "scoring"
    / "dim2_geometry_knowledge_base.json"
)

GENERIC_GEOMETRY_TERMS = {
    "",
    "几何",
    "图形",
    "空间",
    "空间想象",
    "几何直观",
    "图形关系",
    "核心几何",
    "几何知识",
    "综合问题",
    "综合题",
    "基本公式",
    "形面积",
    "图形面积",
    "面积关系",
    "面积计算",
    "周长计算",
    "长度计算",
    "体积计算",
    "容积",
    "方形",
    "矩形",
    "平四",
    "圆",
    "正方形",
    "长方形",
    "三角形",
    "平行四边形",
    "梯形",
    "柱体",
    "立方体",
    "长正方体",
    "解决问题",
}

WEAK_SUBSTRING_MATCH_KEYS = {
    "形面积",
    "图形面积",
    "面积",
    "表面积",
    "求面积",
    "求周长",
    "面积关系",
    "面积计算",
    "周长计算",
    "长度计算",
    "体积计算",
}

KNOWLEDGE_RANGE_LABELS = {
    "K1": "校内四年级及以前",
    "K2": "校内五年级",
    "K3": "校内六年级",
    "K4": "高思导引三四年级",
    "K5": "高思导引五六年级",
}

SOURCE_PRIORITY = {
    "analysis_facts.core_knowledge_points": 0,
    "dim2.geometry_model_types": 1,
    "dim2.evidence_tags": 2,
}
AMBIGUOUS_STRICT_SOURCES = {
    "dim2.geometry_model_types",
    "dim2.evidence_tags",
}

CHINESE_GRADE_TO_INT = {
    "一年级": 1,
    "二年级": 2,
    "三年级": 3,
    "四年级": 4,
    "五年级": 5,
    "六年级": 6,
}

GEOMETRY_MODEL_DISPLAY_LABELS = {
    "basic_area_formula": "基本面积公式",
    "reverse_area_edge": "面积反求边长",
    "butterfly_area": "蝴蝶模型",
    "swallowtail_area": "燕尾模型",
    "half_area": "一半模型",
    "equal_height_area": "等高面积关系",
    "shared_base_area": "共底面积关系",
    "equal_area_transform": "等积变形",
    "kite_area": "风筝模型",
    "bird_head_sandglass": "鸟头与沙漏模型",
    "pyramid_sandglass": "金字塔与沙漏模型",
    "cut_and_fill": "割补法",
    "grid_cut_fill": "格点与割补",
    "auxiliary_parallel": "辅助平行线",
    "area_ratio_chain": "面积比例关系",
    "composite_area_model": "组合图形面积",
    "circle_sector_formula": "圆与扇形公式",
    "circle_sector_cut_fill": "圆与扇形割补",
    "rolling_rotation": "滚动与旋转",
    "solid_formula": "立体图形公式",
    "water_displacement": "水位体积",
    "surface_three_view": "三视图与表面积",
    "net_cut_join": "展开图剪拼",
    "solid_cut_join": "立体切拼",
    "length_translation": "线段转化",
    "directed_length": "有向线段",
    "angle_chasing_triangle": "三角形角度追踪",
    "angle_chasing_polygon": "多边形角度追踪",
    "polygon_angle_sum": "多边形内角和",
    "figure_transformation": "图形变换",
    "opposite_faces": "正方体相对面",
    "geometric_counting": "几何计数",
}

GEOMETRY_MODEL_MATCH_TERMS = {
    "basic_area_formula": (),
    "reverse_area_edge": ("已知面积，求周长", "面积反求边长"),
    "butterfly_area": ("蝴蝶模型与沙漏模型", "蝴蝶模型"),
    "swallowtail_area": ("燕尾模型",),
    "half_area": ("一半模型",),
    "equal_height_area": ("等高面积关系", "等高"),
    "shared_base_area": ("共底面积关系", "共底"),
    "equal_area_transform": ("等积变形", "等面积变换"),
    "kite_area": ("风筝模型",),
    "bird_head_sandglass": ("鸟头与沙漏模型", "鸟头模型", "沙漏模型"),
    "pyramid_sandglass": ("金字塔与沙漏模型", "金字塔模型"),
    "cut_and_fill": ("割补法", "分割添补"),
    "grid_cut_fill": ("格点与割补", "格点图形"),
    "auxiliary_parallel": ("辅助平行线", "平行线"),
    "area_ratio_chain": ("面积比例关系", "面积比"),
    "composite_area_model": ("组合图形面积", "组合图形"),
    "circle_sector_formula": ("圆的面积", "圆与扇形公式", "圆与扇形"),
    "circle_sector_cut_fill": ("圆与扇形割补", "圆与扇形"),
    "rolling_rotation": ("滚动与旋转", "图形旋转"),
    "solid_formula": ("长方体和正方体的体积公式", "立体图形公式"),
    "water_displacement": ("水中浸物", "水位体积"),
    "surface_three_view": ("三视图法求表面积", "三视图"),
    "net_cut_join": ("切拼问题、展开图", "展开图"),
    "solid_cut_join": ("立体几何", "立体切拼"),
    "length_translation": ("长度计算之平移法", "线段转化", "长度转化"),
    "directed_length": ("长度计算之标向法", "有向线段"),
    "angle_chasing_triangle": ("角度计算之三角形相关", "三角形角度计算"),
    "angle_chasing_polygon": ("角度计算之多边形相关", "多边形角度计算"),
    "polygon_angle_sum": ("多边形内角和",),
    "figure_transformation": ("图形变换", "平移和旋转"),
    "opposite_faces": ("正方体相对面问题", "正方体相对面"),
    "geometric_counting": ("几何图形计数",),
}

GEOMETRY_MODEL_DIFFICULTY_HINTS = {
    "surface_three_view": "本题难点在于要从多个视图反推立体结构，并检查可见面或小正方体数量。",
    "solid_cut_join": "本题难点在于要判断切割或拼合后新增、减少的面，再组织表面积或体积关系。",
    "net_cut_join": "本题难点在于要把展开图与折叠后的相邻关系对应起来。",
    "water_displacement": "本题难点在于要把水位变化转化为体积差，并保持底面积和高度关系一致。",
    "circle_sector_cut_fill": "本题难点在于要把圆、扇形和直线形区域重新割补成可计算面积。",
    "cut_and_fill": "本题难点在于要把不规则图形拆补成可比较的基本图形，再组织面积关系。",
    "grid_cut_fill": "本题难点在于要把格点图形拆补成基本图形，并利用格点关系计算面积。",
    "auxiliary_parallel": "本题难点在于要补出辅助关系，把隐藏的平行、等高或面积关系转成可用条件。",
    "area_ratio_chain": "本题难点在于要沿多段面积比例关系连续转化，避免中间比例对应错位。",
    "butterfly_area": "本题难点在于要识别蝴蝶模型，并把对应三角形面积比转成可用关系。",
    "swallowtail_area": "本题难点在于要识别燕尾模型，并准确对应面积比例关系。",
    "half_area": "本题难点在于要识别一半面积关系，并把局部图形转化为整体面积。",
    "equal_height_area": "本题难点在于要抓住等高条件，把底边关系转成面积关系。",
    "shared_base_area": "本题难点在于要抓住共底条件，把高的关系转成面积关系。",
    "equal_area_transform": "本题难点在于要利用等积变形，把不易直接计算的图形转成可比较图形。",
    "kite_area": "本题难点在于要识别风筝模型中的对称和面积分割关系。",
    "bird_head_sandglass": "本题难点在于要区分鸟头与沙漏模型的对应边和对应面积关系。",
    "pyramid_sandglass": "本题难点在于要在金字塔与沙漏结构中连续追踪面积比例。",
    "rolling_rotation": "本题难点在于要把图形滚动或旋转过程转成位置和长度关系。",
    "opposite_faces": "本题难点在于要在展开图中定位正方体相对面，避免把相邻面误判为相对面。",
    "geometric_counting": "本题难点在于要按图形结构分类计数，并避免重复或遗漏。",
    "basic_area_formula": "本题难点在于要准确对应底、高或长、宽，再代入基本面积关系。",
    "solid_formula": "本题难点在于要分清表面积、体积或容积对应的量，并选择正确公式。",
    "circle_sector_formula": "本题难点在于要分清圆、半圆或扇形的周长和面积关系。",
    "composite_area_model": "本题难点在于要把组合图形拆成可计算部分，并重新组织面积关系。",
    "length_translation": "本题难点在于要把分散的线段关系转化到同一条长度链上。",
    "directed_length": "本题难点在于要区分线段方向和增减关系，避免长度关系反向。",
    "angle_chasing_triangle": "本题难点在于要连续追踪三角形中的角度关系。",
    "angle_chasing_polygon": "本题难点在于要把多边形角度关系拆成可追踪的局部关系。",
    "polygon_angle_sum": "本题难点在于要准确使用多边形内角和，并处理拆分后的角度关系。",
    "figure_transformation": "本题难点在于要把平移、旋转或对称前后的图形关系对应起来。",
}


@dataclass(frozen=True)
class Dim2KnowledgeMatch:
    knowledge_range_level: str = ""
    knowledge_range_label: str = ""
    track: str = ""
    grade: int | None = None
    category: str = ""
    matched_knowledge_points: tuple[str, ...] = ()
    match_sources: tuple[str, ...] = ()
    status: str = "unmatched"

    def to_details(self) -> dict[str, Any]:
        return {
            "knowledge_range_level": self.knowledge_range_level,
            "knowledge_range_label": self.knowledge_range_label,
            "knowledge_range_track": self.track,
            "knowledge_range_grade": self.grade,
            "knowledge_range_category": self.category,
            "matched_geometry_knowledge_points": list(self.matched_knowledge_points),
            "knowledge_range_match_sources": list(self.match_sources),
            "knowledge_range_status": self.status,
        }


@dataclass(frozen=True)
class Dim2DisplayKnowledgeMatch:
    knowledge_points: tuple[str, ...] = ()
    knowledge_range_label: str = ""
    source: str = ""
    status: str = "fallback"

    def to_details(self) -> dict[str, Any]:
        return {
            "display_geometry_knowledge_points": list(self.knowledge_points),
            "display_geometry_knowledge_range_label": self.knowledge_range_label,
            "display_geometry_knowledge_source": self.source,
            "display_geometry_knowledge_status": self.status,
        }


def _normalize_text(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", "", text)
    return text.strip("：:；;，,。.!！?？、")


def _normalize_key(value: object) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", _normalize_text(value)).lower()


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [value]
    return []


def _is_generic_term(value: object) -> bool:
    text = _normalize_text(value)
    return not text or text in GENERIC_GEOMETRY_TERMS


def _grade_to_int(value: object) -> int:
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    if text in CHINESE_GRADE_TO_INT:
        return CHINESE_GRADE_TO_INT[text]
    try:
        return int(text)
    except (TypeError, ValueError):
        return 0


def _range_level_for_entry(entry: dict[str, Any]) -> str:
    source_label = str(entry.get("source_label") or "")
    grade = _grade_to_int(entry.get("grade"))

    if source_label == "校内":
        if 1 <= grade <= 4:
            return "K1"
        if grade == 5:
            return "K2"
        if grade == 6:
            return "K3"
    if source_label == "高思导引":
        if grade in {3, 4}:
            return "K4"
        if grade in {5, 6}:
            return "K5"
    return ""


@lru_cache(maxsize=1)
def _load_entries() -> tuple[dict[str, Any], ...]:
    if not DATA_PATH.exists():
        return ()

    raw_entries = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw_entries, list):
        return ()

    entries: list[dict[str, Any]] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        knowledge_point = _normalize_text(raw.get("knowledge_point"))
        if _is_generic_term(knowledge_point):
            continue
        range_level = _range_level_for_entry(raw)
        if not range_level:
            continue

        match_keys = {_normalize_key(knowledge_point)}
        for alias in _as_list(raw.get("aliases")):
            alias_text = _normalize_text(alias)
            if not _is_generic_term(alias_text):
                match_keys.add(_normalize_key(alias_text))

        entries.append(
            {
                **raw,
                "knowledge_point": knowledge_point,
                "grade_int": _grade_to_int(raw.get("grade")),
                "knowledge_range_level": range_level,
                "knowledge_range_label": KNOWLEDGE_RANGE_LABELS[range_level],
                "match_keys": tuple(key for key in match_keys if key),
            }
        )
    return tuple(entries)


def _candidate_terms(features: dict[str, Any]) -> list[tuple[str, str]]:
    terms: list[tuple[str, str]] = []

    analysis_facts = features.get("analysis_facts", {})
    if isinstance(analysis_facts, dict):
        for item in _as_list(analysis_facts.get("core_knowledge_points")):
            terms.append(("analysis_facts.core_knowledge_points", _normalize_text(item)))

    for model_type in _as_list(features.get("geometry_model_types")):
        model_key = str(model_type or "").strip().lower()
        for term in GEOMETRY_MODEL_MATCH_TERMS.get(model_key, ()):
            terms.append(("dim2.geometry_model_types", _normalize_text(term)))

    for item in _as_list(features.get("evidence_tags")):
        terms.append(("dim2.evidence_tags", _normalize_text(item)))

    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source, term in terms:
        key = (source, _normalize_key(term))
        if key in seen or _is_generic_term(term):
            continue
        seen.add(key)
        deduped.append((source, term))
    return deduped


def _match_quality(candidate_key: str, entry: dict[str, Any]) -> int:
    if not candidate_key:
        return 0
    best = 0
    for match_key in entry.get("match_keys") or ():
        if not match_key:
            continue
        if candidate_key == match_key:
            best = max(best, 4)
        elif (
            match_key in candidate_key
            and len(match_key) >= 4
            and match_key not in WEAK_SUBSTRING_MATCH_KEYS
        ):
            best = max(best, 3)
        elif (
            candidate_key in match_key
            and len(candidate_key) >= 4
            and candidate_key not in WEAK_SUBSTRING_MATCH_KEYS
        ):
            best = max(best, 2)
    return best


def _range_rank(range_level: str) -> int:
    return {"K1": 1, "K2": 2, "K3": 3, "K4": 4, "K5": 5}.get(range_level, 0)


def _is_displayable_term(value: object) -> bool:
    text = _normalize_text(value)
    return bool(text) and not _is_generic_term(text) and len(_normalize_key(text)) >= 2


def _best_matches(candidates: Iterable[tuple[str, str]]) -> list[tuple[int, int, int, dict[str, Any], str]]:
    raw_matches: list[tuple[int, int, int, dict[str, Any], str, int, str]] = []
    for source, term in candidates:
        candidate_key = _normalize_key(term)
        if not candidate_key:
            continue
        source_priority = SOURCE_PRIORITY.get(source, 99)
        for entry in _load_entries():
            quality = _match_quality(candidate_key, entry)
            if not quality:
                continue
            raw_matches.append(
                (
                    _range_rank(str(entry["knowledge_range_level"])),
                    quality,
                    -source_priority,
                    entry,
                    source,
                    source_priority,
                    candidate_key,
                )
            )
    if not raw_matches:
        return []

    stable_matches: list[tuple[int, int, int, dict[str, Any], str, int, str]] = []
    candidate_best_quality: dict[tuple[str, str], int] = {}
    candidate_ranges: dict[tuple[str, str], set[str]] = {}
    for _, quality, _, entry, source, _, candidate_key in raw_matches:
        if source in AMBIGUOUS_STRICT_SOURCES:
            key = (source, candidate_key)
            best_quality = candidate_best_quality.get(key, 0)
            if quality > best_quality:
                candidate_best_quality[key] = quality
                candidate_ranges[key] = {str(entry["knowledge_range_level"])}
            elif quality == best_quality:
                candidate_ranges.setdefault(key, set()).add(str(entry["knowledge_range_level"]))

    for match in raw_matches:
        _, quality, _, _, source, _, candidate_key = match
        if source in AMBIGUOUS_STRICT_SOURCES:
            key = (source, candidate_key)
            if quality != candidate_best_quality.get(key, 0):
                continue
            if len(candidate_ranges.get(key, set())) != 1:
                continue
        stable_matches.append(match)

    if not stable_matches:
        return []

    best_source_priority = min(item[5] for item in stable_matches)
    matches = [item[:5] for item in stable_matches if item[5] == best_source_priority]
    matches.sort(key=lambda item: (item[1], item[0], item[2]), reverse=True)
    return matches


def _best_display_matches(candidates: Iterable[tuple[str, str]]) -> list[tuple[int, int, int, dict[str, Any], str]]:
    matches: list[tuple[int, int, int, dict[str, Any], str]] = []
    for source, term in candidates:
        if not _is_displayable_term(term):
            continue
        candidate_key = _normalize_key(term)
        source_priority = SOURCE_PRIORITY.get(source, 99)
        for entry in _load_entries():
            if not _is_displayable_term(entry.get("knowledge_point")):
                continue
            quality = _match_quality(candidate_key, entry)
            if not quality:
                continue
            matches.append(
                (
                    -source_priority,
                    quality,
                    _range_rank(str(entry["knowledge_range_level"])),
                    entry,
                    source,
                )
            )
    matches.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return matches


def _display_fallback_from_features(features: dict[str, Any]) -> str:
    for model_type in _as_list(features.get("geometry_model_types")):
        model_key = str(model_type or "").strip().lower()
        label = GEOMETRY_MODEL_DISPLAY_LABELS.get(model_key)
        if label:
            return label

    figure_complexity = str(features.get("figure_complexity") or "").strip().lower()
    structural_method = str(features.get("structural_visual_method") or "").strip().lower()
    if structural_method == "auxiliary_line":
        return "辅助线与图形关系"
    if structural_method == "decomposition":
        return "图形分解与组合"
    if structural_method == "3d_transform":
        return "立体图形空间转换"
    if figure_complexity == "solid_3d":
        return "立体图形关系"
    if figure_complexity == "net_section_multi_view":
        return "展开图与多视图"
    if figure_complexity == "composite_2d":
        return "组合图形关系"
    return "基础图形关系"


def geometry_model_difficulty_hint(model_types: object) -> str:
    for model_type in _as_list(model_types):
        model_key = str(model_type or "").strip().lower()
        hint = GEOMETRY_MODEL_DIFFICULTY_HINTS.get(model_key)
        if hint:
            return hint
    return ""


def geometry_model_display_points(model_types: object, *, limit: int = 2) -> list[str]:
    points: list[str] = []
    for model_type in _as_list(model_types):
        model_key = str(model_type or "").strip().lower()
        label = GEOMETRY_MODEL_DISPLAY_LABELS.get(model_key)
        if label and label not in points:
            points.append(label)
        if len(points) >= limit:
            break
    return points


def match_dim2_knowledge_range(features: dict[str, Any]) -> Dim2KnowledgeMatch:
    candidates = _candidate_terms(features)
    matches = _best_matches(candidates)
    if not matches:
        return Dim2KnowledgeMatch()

    highest_range = matches[0][3]["knowledge_range_level"]
    top_entries: list[dict[str, Any]] = []
    top_sources: list[str] = []
    seen_points: set[str] = set()
    for _, _, _, entry, source in matches:
        if entry["knowledge_range_level"] != highest_range:
            continue
        point = str(entry["knowledge_point"])
        if point in seen_points:
            continue
        seen_points.add(point)
        top_entries.append(entry)
        top_sources.append(source)
        if len(top_entries) >= 3:
            break

    primary = top_entries[0]
    return Dim2KnowledgeMatch(
        knowledge_range_level=str(primary["knowledge_range_level"]),
        knowledge_range_label=str(primary["knowledge_range_label"]),
        track=str(primary.get("source_label") or ""),
        grade=int(primary.get("grade_int") or 0),
        category=str(primary.get("category") or ""),
        matched_knowledge_points=tuple(str(item["knowledge_point"]) for item in top_entries),
        match_sources=tuple(dict.fromkeys(top_sources)),
        status="matched",
    )


def match_dim2_display_knowledge(
    features: dict[str, Any],
    strict_match: Dim2KnowledgeMatch | None = None,
) -> Dim2DisplayKnowledgeMatch:
    if strict_match and strict_match.matched_knowledge_points:
        return Dim2DisplayKnowledgeMatch(
            knowledge_points=strict_match.matched_knowledge_points[:3],
            knowledge_range_label=strict_match.knowledge_range_label,
            source="strict_knowledge_range",
            status="strict",
        )

    candidates = _candidate_terms(features)
    matches = _best_display_matches(candidates)
    if matches:
        top_entries: list[dict[str, Any]] = []
        top_sources: list[str] = []
        seen_points: set[str] = set()
        for _, _, _, entry, source in matches:
            point = str(entry["knowledge_point"])
            if point in seen_points:
                continue
            seen_points.add(point)
            top_entries.append(entry)
            top_sources.append(source)
            if len(top_entries) >= 3:
                break

        primary = top_entries[0]
        return Dim2DisplayKnowledgeMatch(
            knowledge_points=tuple(str(item["knowledge_point"]) for item in top_entries),
            knowledge_range_label=str(primary.get("knowledge_range_label") or ""),
            source="loose_knowledge_match:" + ",".join(dict.fromkeys(top_sources)),
            status="loose_matched",
        )

    model_points = geometry_model_display_points(features.get("geometry_model_types"), limit=3)
    if model_points:
        return Dim2DisplayKnowledgeMatch(
            knowledge_points=tuple(model_points),
            source="geometry_model_fallback",
            status="fallback",
        )

    return Dim2DisplayKnowledgeMatch(
        knowledge_points=(_display_fallback_from_features(features),),
        source="feature_fallback",
        status="fallback",
    )
