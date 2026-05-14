from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


DATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "parser"
    / "dim1_knowledge_points.json"
)

GENERIC_KNOWLEDGE_TERMS = {
    "",
    "计算",
    "校内计算",
    "数字谜",
    "数论",
    "奥数",
    "高思",
    "高思导引",
    "核心计算",
    "核心计算能力",
    "综合问题",
    "综合题",
    "综合题型",
    "基础题型",
    "混合运算",
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
    "dim1.evidence_tags": 1,
    "dim5.core_knowledge_units": 2,
    "dim5.knowledge_tags": 3,
}
TAG_FALLBACK_SOURCES = {"dim1.evidence_tags", "dim5.knowledge_tags"}


@dataclass(frozen=True)
class Dim1KnowledgeMatch:
    knowledge_range_level: str = ""
    knowledge_range_label: str = ""
    track: str = ""
    grade: int | None = None
    branch: str = ""
    matched_knowledge_points: tuple[str, ...] = ()
    match_sources: tuple[str, ...] = ()
    status: str = "unmatched"

    def to_details(self) -> dict[str, Any]:
        return {
            "knowledge_range_level": self.knowledge_range_level,
            "knowledge_range_label": self.knowledge_range_label,
            "knowledge_range_track": self.track,
            "knowledge_range_grade": self.grade,
            "knowledge_range_branch": self.branch,
            "matched_knowledge_points": list(self.matched_knowledge_points),
            "knowledge_range_match_sources": list(self.match_sources),
            "knowledge_range_status": self.status,
        }


@dataclass(frozen=True)
class Dim1DisplayKnowledgeMatch:
    knowledge_points: tuple[str, ...] = ()
    knowledge_range_label: str = ""
    source: str = ""
    status: str = "fallback"

    def to_details(self) -> dict[str, Any]:
        return {
            "display_knowledge_points": list(self.knowledge_points),
            "display_knowledge_range_label": self.knowledge_range_label,
            "display_knowledge_source": self.source,
            "display_knowledge_status": self.status,
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
    return not text or text in GENERIC_KNOWLEDGE_TERMS


def _range_level_for_entry(entry: dict[str, Any]) -> str:
    track = str(entry.get("track") or "")
    try:
        grade = int(entry.get("grade") or 0)
    except (TypeError, ValueError):
        grade = 0

    if track == "校内":
        if 1 <= grade <= 4:
            return "K1"
        if grade == 5:
            return "K2"
        if grade == 6:
            return "K3"
    if track == "高思导引":
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
    entries: list[dict[str, Any]] = []
    if not isinstance(raw_entries, list):
        return ()

    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        knowledge_point = _normalize_text(raw.get("knowledge_point"))
        if _is_generic_term(knowledge_point):
            continue
        range_level = _range_level_for_entry(raw)
        if not range_level:
            continue
        entries.append(
            {
                **raw,
                "knowledge_point": knowledge_point,
                "knowledge_key": _normalize_key(knowledge_point),
                "knowledge_range_level": range_level,
                "knowledge_range_label": KNOWLEDGE_RANGE_LABELS[range_level],
            }
        )
    return tuple(entries)


def _candidate_terms(features: dict[str, Any]) -> list[tuple[str, str]]:
    terms: list[tuple[str, str]] = []

    analysis_facts = features.get("analysis_facts", {})
    if isinstance(analysis_facts, dict):
        for item in _as_list(analysis_facts.get("core_knowledge_points")):
            terms.append(("analysis_facts.core_knowledge_points", _normalize_text(item)))

    for item in _as_list(features.get("evidence_tags")):
        terms.append(("dim1.evidence_tags", _normalize_text(item)))

    dim5 = features.get("dim5_knowledge", {})
    if isinstance(dim5, dict):
        for item in _as_list(dim5.get("core_knowledge_units")):
            terms.append(("dim5.core_knowledge_units", _normalize_text(item)))
        for item in _as_list(dim5.get("knowledge_tags")):
            terms.append(("dim5.knowledge_tags", _normalize_text(item)))

    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source, term in terms:
        key = (source, _normalize_key(term))
        if key in seen or _is_generic_term(term):
            continue
        seen.add(key)
        deduped.append((source, term))
    return deduped


def _match_quality(candidate_key: str, knowledge_key: str) -> int:
    if not candidate_key or not knowledge_key:
        return 0
    if candidate_key == knowledge_key:
        return 3
    if knowledge_key in candidate_key and len(knowledge_key) >= 3:
        return 2
    if candidate_key in knowledge_key and len(candidate_key) >= 4:
        return 1
    return 0


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
            quality = _match_quality(candidate_key, str(entry.get("knowledge_key") or ""))
            if not quality:
                continue
            if source in TAG_FALLBACK_SOURCES and quality != 3:
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
    tag_ranges: dict[tuple[str, str], set[str]] = {}
    for _, _, _, entry, source, _, candidate_key in raw_matches:
        if source in TAG_FALLBACK_SOURCES:
            tag_ranges.setdefault((source, candidate_key), set()).add(str(entry["knowledge_range_level"]))

    for match in raw_matches:
        _, _, _, _, source, _, candidate_key = match
        if source in TAG_FALLBACK_SOURCES and len(tag_ranges.get((source, candidate_key), set())) != 1:
            continue
        stable_matches.append(match)

    if not stable_matches:
        return []

    best_source_priority = min(item[5] for item in stable_matches)
    matches = [item[:5] for item in stable_matches if item[5] == best_source_priority]
    matches.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return matches


def _best_display_matches(candidates: Iterable[tuple[str, str]]) -> list[tuple[int, int, int, dict[str, Any], str]]:
    matches: list[tuple[int, int, int, dict[str, Any], str]] = []
    for source, term in candidates:
        if not _is_displayable_term(term):
            continue
        candidate_key = _normalize_key(term)
        source_priority = SOURCE_PRIORITY.get(source, 99)
        for entry in _load_entries():
            knowledge_point = str(entry.get("knowledge_point") or "")
            if not _is_displayable_term(knowledge_point):
                continue
            quality = _match_quality(candidate_key, str(entry.get("knowledge_key") or ""))
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
    calc_subtype = str(features.get("calc_subtype") or "").strip().lower()
    number_mix = str(features.get("number_mix") or "").strip().lower()
    step_chain = str(features.get("step_chain") or "").strip()
    structural_method = str(features.get("structural_method") or "").strip().lower()
    patterns = features.get("structure_patterns") or []
    pattern_set = {str(item or "").strip().lower() for item in patterns if str(item or "").strip()}

    if calc_subtype == "proportion_equation":
        return "比例计算"
    if calc_subtype == "equation":
        return "方程计算"
    if calc_subtype == "defined_operation":
        return "定义新运算"
    if calc_subtype == "sequence_series":
        return "数列计算"
    if calc_subtype == "nested_fraction":
        return "繁分式计算"
    if calc_subtype == "fraction_comparison":
        return "分数比较大小"
    if calc_subtype == "factorial_ratio":
        return "阶乘约分"
    if {
        "fraction_decimal_percent_conversion",
        "reciprocal_conversion",
        "factorial_cancellation",
    } & pattern_set or number_mix in {"mixed", "symbolic"}:
        return "分数小数混合计算"
    if {"common_factor", "grouping", "decimal_scaling"} & pattern_set or structural_method == "shortcut":
        return "凑整与分组计算"
    if step_chain in {"3-4", "5+"}:
        return "多步四则混合运算"
    return "四则运算"


def match_dim1_knowledge_range(features: dict[str, Any]) -> Dim1KnowledgeMatch:
    candidates = _candidate_terms(features)
    matches = _best_matches(candidates)
    if not matches:
        return Dim1KnowledgeMatch()

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
    return Dim1KnowledgeMatch(
        knowledge_range_level=str(primary["knowledge_range_level"]),
        knowledge_range_label=str(primary["knowledge_range_label"]),
        track=str(primary.get("track") or ""),
        grade=int(primary.get("grade") or 0),
        branch=str(primary.get("branch") or ""),
        matched_knowledge_points=tuple(str(item["knowledge_point"]) for item in top_entries),
        match_sources=tuple(dict.fromkeys(top_sources)),
        status="matched",
    )


def match_dim1_display_knowledge(
    features: dict[str, Any],
    strict_match: Dim1KnowledgeMatch | None = None,
) -> Dim1DisplayKnowledgeMatch:
    if strict_match and strict_match.matched_knowledge_points:
        return Dim1DisplayKnowledgeMatch(
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
        return Dim1DisplayKnowledgeMatch(
            knowledge_points=tuple(str(item["knowledge_point"]) for item in top_entries),
            knowledge_range_label=str(primary.get("knowledge_range_label") or ""),
            source="loose_knowledge_match:" + ",".join(dict.fromkeys(top_sources)),
            status="loose_matched",
        )

    raw_candidate_sources = {"analysis_facts.core_knowledge_points", "dim5.core_knowledge_units"}
    for source, term in candidates:
        if source in raw_candidate_sources and _is_displayable_term(term):
            return Dim1DisplayKnowledgeMatch(
                knowledge_points=(_normalize_text(term),),
                source=f"raw_candidate:{source}",
                status="raw_candidate",
            )

    return Dim1DisplayKnowledgeMatch(
        knowledge_points=(_display_fallback_from_features(features),),
        source="feature_fallback",
        status="fallback",
    )
