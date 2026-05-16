"""Dim5 local retrieval for knowledge-scope calibration.

The service builds lightweight retrieval evidence from the existing
ReferenceEntry corpus. It intentionally keeps retrieval as evidence rather
than a final score: final L1-L5 judgement still happens in dim5_canonical.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Sequence

from app.services.parser.reference_standard import (
    DIM5_TOPIC_STRUCTURE_GROUPS,
    GAOSI_QUESTION_SOURCE,
    ReferenceEntry,
)


DIM5_RETRIEVAL_VERSION = "dim5_retrieval_v1"

_SECTION_TO_LEVEL = {
    "interest": "L3",
    "兴趣篇": "L3",
    "extension": "L4",
    "拓展篇": "L4",
    # Section names are retained as audit signals. Challenge/超越篇 is not a
    # standalone L5 trigger; grade and structure/question-level evidence decide.
    "challenge": "L4",
    "超越篇": "L4",
}

_OLD_BAND_TO_LEVEL = {
    "4年级及以前校内课本难度": "L1",
    "5、6年级校内课本难度": "L2",
    "4年级及以前高思导引拓展篇及以下难度": "L3",
    "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度": "L4",
    "高思导引超越篇难度": "L4",
}

_SCOPE_RANK = {
    "knowledge_point": 1,
    "topic_structure": 2,
    "reference_question": 3,
}

_GENERIC_TERMS = {
    "数学",
    "问题",
    "应用题",
    "综合",
    "基础",
    "根据",
    "计算",
    "知识",
}

_DIRECT_FORMULA_PATTERN = re.compile(
    r"(?:直接公式|普通公式|直接代入|套用公式|只需代入|一步公式|"
    r"长方形面积|正方形面积|三角形面积|圆(?:的)?面积|扇形面积|"
    r"长方体体积|正方体体积|圆柱(?:和圆锥)?体积|圆锥体积|"
    r"表面积公式|体积公式|百分数直接应用|直接百分数|"
    r"路程\s*[=＝]|速度\s*[=＝]|时间\s*[=＝])"
)

_ADVANCED_STRUCTURE_SIGNALS = {
    "travel": (
        "多次相遇",
        "第2次相遇",
        "第二次相遇",
        "往返",
        "返回",
        "变速",
        "速度变化",
        "提前",
        "延迟",
        "中点",
        "追上",
        "追及",
        "流水",
        "顺水",
        "逆水",
    ),
    "grazing": ("原有", "生长", "增长", "增加", "流入", "抽干", "消耗", "吃完", "每天"),
    "work_rate": ("合作", "单独", "效率", "轮流", "换班", "共同完成", "工作量"),
    "combinatorics": ("不重不漏", "容斥", "排列", "组合", "分类", "多少种", "方案"),
    "number_theory": ("同余", "余数", "整除", "质因数", "不变量", "倍数", "约数"),
    "sequence": ("周期", "递推", "循环", "第n", "第 n", "第几", "余数"),
    "defined_operation": ("定义", "规定", "新运算", "运算符号", "嵌套"),
    "pigeonhole": ("至少", "保证", "必有", "抽屉", "最不利"),
    "game": ("轮流", "必胜", "必败", "策略", "对称"),
    "advanced_geometry": ("割补", "辅助线", "面积比", "蝴蝶", "燕尾", "鸟头", "沙漏", "阴影"),
}

_L5_ENTRY_SIGNALS = (
    "压轴",
    "小升初压轴",
    "较难",
    "难题",
    "复杂",
    "隐藏结构",
    "多条件",
    "多阶段",
    "分类讨论",
    "反推",
    "回查",
    "模型嵌套",
    "跨专题",
    "七年级核心",
    "初中核心",
    "方程组",
    "一次函数",
    "不等式",
    "整式",
    "有理数",
)

_CHINESE_GRADE_VALUES = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
}

_GROUP_TITLES = {
    "grazing": "牛吃草 / 增长消耗结构",
    "work_rate": "工程效率 / 合作结构",
    "travel": "行程相遇追及结构",
    "concentration": "浓度混合结构",
    "combinatorics": "组合计数结构",
    "number_theory": "数论约束结构",
    "sequence": "周期数列结构",
    "defined_operation": "定义新运算结构",
    "pigeonhole": "抽屉原理结构",
    "game": "博弈策略结构",
    "advanced_geometry": "几何模型结构",
}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _compact_text(value: Any) -> str:
    return re.sub(r"[\s，。；：、,.;:()（）【】\[\]{}<>《》\"'“”‘’]+", "", str(value or ""))


def _unique(items: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _level_rank(level: str) -> int:
    text = str(level or "").strip().upper()
    return int(text[1]) if len(text) == 2 and text.startswith("L") and text[1].isdigit() else 0


def _parse_grade(*values: Any) -> int | None:
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        for char in text:
            if char.isdigit():
                grade = int(char)
                if 1 <= grade <= 7:
                    return grade
        for char, grade in _CHINESE_GRADE_VALUES.items():
            if char in text:
                return grade
    return None


def _has_l5_entry_signal(text: str) -> bool:
    return any(signal in text for signal in _L5_ENTRY_SIGNALS)


def _flatten_profile_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_profile_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_profile_text(item) for item in value)
    return str(value or "")


def _char_ngrams(text: str, size: int) -> set[str]:
    if len(text) < size:
        return {text} if text else set()
    return {text[index : index + size] for index in range(len(text) - size + 1)}


def _question_match_strength(reference_text: str, combined_text: str) -> int:
    """0=no match, 1=partial, 2=high similarity, 3=exact/near-exact."""

    reference_text = _compact_text(reference_text)
    combined_text = _compact_text(combined_text)
    if len(reference_text) < 8 or not combined_text:
        return 0
    if reference_text in combined_text:
        return 3
    size = 3 if len(reference_text) >= 18 else 2
    reference_grams = _char_ngrams(reference_text, size)
    combined_grams = _char_ngrams(combined_text, size)
    if not reference_grams or not combined_grams:
        return 0
    overlap = len(reference_grams & combined_grams)
    ratio = overlap / max(len(reference_grams), 1)
    if ratio >= 0.60 and overlap >= 8:
        return 2
    if ratio >= 0.35 and overlap >= 6:
        return 1
    return 0


class Dim5RetrievalService:
    """Retrieve dim5 local evidence from the existing reference standard."""

    def __init__(self, reference_standard: Any):
        self.reference_standard = reference_standard

    def retrieve(
        self,
        *,
        question_text: str,
        question_summary: str = "",
        analysis_facts: Dict[str, Any] | None = None,
        dim5_feature: Dict[str, Any] | None = None,
        limit_per_scope: int = 5,
        overall_limit: int = 12,
    ) -> Dict[str, Any]:
        analysis_facts = analysis_facts or {}
        dim5_feature = dim5_feature or {}
        combined_text = self._combined_text(
            question_text=question_text,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
            dim5_feature=dim5_feature,
        )
        direct_formula_guard = bool(_DIRECT_FORMULA_PATTERN.search(combined_text))
        query_terms = self._query_terms(combined_text, analysis_facts=analysis_facts, dim5_feature=dim5_feature)

        knowledge_point_candidates = self._knowledge_point_candidates(
            combined_text=combined_text,
            query_terms=query_terms,
            limit=limit_per_scope,
        )
        topic_structure_candidates = self._topic_structure_candidates(
            combined_text=combined_text,
            query_terms=query_terms,
            direct_formula_guard=direct_formula_guard,
            limit=limit_per_scope,
        )
        reference_question_candidates = self._reference_question_candidates(
            combined_text=combined_text,
            dim5_feature=dim5_feature,
            question_text=question_text,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
            limit=limit_per_scope,
        )

        candidates = self._dedupe_candidates(
            [
                *reference_question_candidates,
                *topic_structure_candidates,
                *knowledge_point_candidates,
            ]
        )
        candidates.sort(
            key=lambda item: (
                _SCOPE_RANK.get(str(item.get("match_scope") or ""), 0),
                1 if item.get("can_raise_level") else 0,
                _level_rank(str(item.get("recommended_level") or "")),
                float(item.get("score") or 0.0),
            ),
            reverse=True,
        )
        candidates = candidates[: max(overall_limit, 0)]
        top_recommendation = self._top_recommendation(candidates)

        return {
            "version": DIM5_RETRIEVAL_VERSION,
            "query": {
                "terms": query_terms[:20],
                "direct_formula_guard": direct_formula_guard,
                "text_excerpt": str(question_text or "")[:160],
            },
            "knowledge_point_candidates": knowledge_point_candidates,
            "topic_structure_candidates": topic_structure_candidates,
            "reference_question_candidates": reference_question_candidates,
            "candidates": candidates,
            "top_recommendation": top_recommendation,
            "policy": {
                "knowledge_point_only_can_raise": False,
                "topic_structure_can_raise_to": "L3/L4/L5_with_hard_structure",
                "reference_question_can_raise_to": "L3/L4/L5",
                "direct_formula_caps_at": "L1/L2",
            },
        }

    def _combined_text(
        self,
        *,
        question_text: str,
        question_summary: str,
        analysis_facts: Dict[str, Any],
        dim5_feature: Dict[str, Any],
    ) -> str:
        parts: List[str] = [question_text, question_summary]
        for key in ("core_task", "fact_basis"):
            parts.append(str(analysis_facts.get(key) or ""))
        for key in ("core_knowledge_points", "core_methods", "visual_elements"):
            raw = analysis_facts.get(key, [])
            if isinstance(raw, list):
                parts.extend(str(item) for item in raw if str(item).strip())
        for key in (
            "primary_knowledge_point",
            "canonical_knowledge_point",
            "evidence_summary",
            "competition_signal",
            "knowledge_integration",
            "novel_definition_dependency",
        ):
            parts.append(str(dim5_feature.get(key) or ""))
        for key in (
            "knowledge_tags",
            "core_knowledge_units",
            "supporting_knowledge_units",
            "method_tags",
            "evidence_tags",
            "canonical_alias_hits",
            "canonical_structure_hits",
        ):
            raw = dim5_feature.get(key, [])
            if isinstance(raw, list):
                parts.extend(str(item) for item in raw if str(item).strip())
        return _normalize_text(" ".join(part for part in parts if str(part).strip()))

    def _query_terms(
        self,
        combined_text: str,
        *,
        analysis_facts: Dict[str, Any],
        dim5_feature: Dict[str, Any],
    ) -> List[str]:
        terms: List[str] = []
        for key in ("core_knowledge_points", "core_methods"):
            raw = analysis_facts.get(key, [])
            if isinstance(raw, list):
                terms.extend(str(item).strip() for item in raw if str(item).strip())
        for key in (
            "knowledge_tags",
            "core_knowledge_units",
            "supporting_knowledge_units",
            "method_tags",
            "canonical_alias_hits",
            "canonical_structure_hits",
        ):
            raw = dim5_feature.get(key, [])
            if isinstance(raw, list):
                terms.extend(str(item).strip() for item in raw if str(item).strip())
        for group in DIM5_TOPIC_STRUCTURE_GROUPS.values():
            for term in (*group.get("topics", ()), *group.get("signals", ())):
                normalized = _normalize_text(term)
                if normalized and normalized in combined_text:
                    terms.append(term)
        return [
            item
            for item in _unique(terms)
            if len(_normalize_text(item)) >= 2 and _normalize_text(item) not in _GENERIC_TERMS
        ]

    def _entries(self) -> Sequence[ReferenceEntry]:
        entries = getattr(self.reference_standard, "entries", [])
        return entries if isinstance(entries, list) else []

    def _entry_terms(self, entry: ReferenceEntry) -> List[str]:
        values: List[Any] = [
            entry.title,
            entry.lecture_title,
            entry.topic_category,
            entry.category,
            entry.note,
            entry.track,
        ]
        values.extend(entry.keywords)
        profile = entry.dimension_profiles.get("dim5", {}) if isinstance(entry.dimension_profiles, dict) else {}
        if isinstance(profile, dict):
            for key in ("knowledge_anchor_terms", "core_knowledge_units", "knowledge_tags"):
                raw = profile.get(key, [])
                if isinstance(raw, list):
                    values.extend(raw)
        terms = []
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            terms.append(text)
            compact = _compact_text(text)
            if compact and compact != text:
                terms.append(compact)
        return [
            term
            for term in _unique(terms)
            if len(_normalize_text(term)) >= 2 and _normalize_text(term) not in _GENERIC_TERMS
        ]

    def _matched_terms(
        self,
        entry_terms: Sequence[str],
        combined_text: str,
        query_terms: Sequence[str],
    ) -> List[str]:
        matched: List[str] = []
        for term in entry_terms:
            normalized = _normalize_text(term)
            if normalized and normalized in combined_text:
                matched.append(term)
                continue
            for query_term in query_terms:
                query_norm = _normalize_text(query_term)
                if (
                    normalized
                    and query_norm
                    and len(normalized) >= 2
                    and (normalized in query_norm or query_norm in normalized)
                ):
                    matched.append(term)
                    break
        return _unique(matched)

    @staticmethod
    def _source_family(source: str) -> str:
        if source in {"school", "school_pdf"}:
            return "school"
        if source in {"guide", "gaosi_pdf", GAOSI_QUESTION_SOURCE}:
            return "gaosi"
        if source in {"classic", "competition"}:
            return "olympiad"
        if source == "as_tree":
            return "system"
        return source or "unknown"

    def _recommended_level_for_entry(self, entry: ReferenceEntry, *, match_scope: str) -> str:
        profile = entry.dimension_profiles.get("dim5", {}) if isinstance(entry.dimension_profiles, dict) else {}
        band = str(profile.get("dim5_reference_band") or "").strip() if isinstance(profile, dict) else ""
        family = self._source_family(entry.source)
        grade = _parse_grade(entry.grade, entry.grade_hint, entry.book_name, entry.note)
        entry_text = " ".join(
            str(value or "")
            for value in (
                entry.title,
                entry.lecture_title,
                entry.topic_category,
                entry.category,
                entry.track,
                entry.section_level,
                entry.section_label,
                entry.book_name,
                entry.note,
                " ".join(str(item) for item in entry.keywords),
            )
        )
        if isinstance(profile, dict):
            entry_text = " ".join([entry_text, _flatten_profile_text(profile)])

        if family == "school":
            return "L1" if grade is not None and grade <= 3 else "L2"
        if family == "gaosi":
            if grade is not None and grade <= 4:
                return "L3"
            if match_scope == "reference_question" and grade == 6:
                section_text = f"{entry.section_level} {entry.section_label} {entry.track}"
                if ("challenge" in section_text.lower() or "超越篇" in section_text) or _has_l5_entry_signal(entry_text):
                    return "L5"
            return "L4"
        if family == "olympiad":
            if _has_l5_entry_signal(entry_text) or (grade is not None and grade >= 6 and "压轴" in entry_text):
                return "L5" if match_scope == "reference_question" else "L4"
            if grade is not None and grade <= 4:
                return "L3"
            return "L4"
        if band in _OLD_BAND_TO_LEVEL:
            return _OLD_BAND_TO_LEVEL[band]
        for value in (entry.section_level, entry.section_label, entry.track):
            level = _SECTION_TO_LEVEL.get(str(value or "").strip())
            if level:
                return "L3" if match_scope == "knowledge_point" and level == "L4" else level
        return "L2"

    def _candidate_id(self, *, match_scope: str, source: str, title: str, extra: str = "") -> str:
        raw = "|".join([match_scope, source, title, extra])
        compact = _compact_text(raw)
        return compact[:96] or f"{match_scope}:{source}"

    def _entry_candidate(
        self,
        entry: ReferenceEntry,
        *,
        match_scope: str,
        matched_terms: Sequence[str],
        structure_signals: Sequence[str] = (),
        score: float,
        match_strength: int = 0,
        similarity_type: str = "",
        quality_flags: Sequence[str] = (),
        can_raise_level: bool = False,
        question_text_excerpt: str = "",
    ) -> Dict[str, Any]:
        title = entry.title or entry.lecture_title or entry.topic_category or entry.category
        recommended_level = self._recommended_level_for_entry(entry, match_scope=match_scope)
        source_family = self._source_family(entry.source)
        return {
            "candidate_id": self._candidate_id(
                match_scope=match_scope,
                source=entry.source,
                title=title,
                extra=f"{entry.grade or entry.grade_hint}:{entry.lecture_no}:{entry.question_no}",
            ),
            "match_scope": match_scope,
            "source": entry.source,
            "source_family": source_family,
            "title": title,
            "matched_terms": list(matched_terms),
            "structure_signals": list(structure_signals),
            "grade": entry.grade,
            "grade_hint": entry.grade_hint,
            "book_name": entry.book_name,
            "lecture_no": entry.lecture_no,
            "lecture_title": entry.lecture_title,
            "topic_category": entry.topic_category,
            "section_level": entry.section_level,
            "section_label": entry.section_label,
            "question_no": entry.question_no,
            "page_no": entry.page_no,
            "match_strength": match_strength,
            "similarity_type": similarity_type,
            "quality_flags": list(quality_flags),
            "recommended_level": recommended_level,
            "can_raise_level": bool(can_raise_level),
            "score": round(float(score), 3),
            "question_text_excerpt": question_text_excerpt[:140],
        }

    def _knowledge_point_candidates(
        self,
        *,
        combined_text: str,
        query_terms: Sequence[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for entry in self._entries():
            if entry.source == GAOSI_QUESTION_SOURCE:
                continue
            terms = self._entry_terms(entry)
            matched_terms = self._matched_terms(terms, combined_text, query_terms)
            if not matched_terms:
                continue
            score = sum(len(_normalize_text(term)) for term in matched_terms)
            if self._source_family(entry.source) == "school":
                score += 4
            elif self._source_family(entry.source) == "gaosi":
                score += 2
            candidates.append(
                self._entry_candidate(
                    entry,
                    match_scope="knowledge_point",
                    matched_terms=matched_terms[:8],
                    score=score,
                    can_raise_level=False,
                )
            )
        candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return candidates[: max(limit, 0)]

    def _local_topic_structure_candidates(
        self,
        *,
        combined_text: str,
        direct_formula_guard: bool,
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for group_name, group in DIM5_TOPIC_STRUCTURE_GROUPS.items():
            topic_hits = [
                term for term in group.get("topics", ()) if _normalize_text(term) in combined_text
            ]
            signal_hits = [
                term for term in group.get("signals", ()) if _normalize_text(term) in combined_text
            ]
            advanced_hits = [
                term for term in _ADVANCED_STRUCTURE_SIGNALS.get(group_name, ()) if _normalize_text(term) in combined_text
            ]
            if not topic_hits and len(signal_hits) < 2:
                continue

            recommended_level = "L4" if advanced_hits else "L3"
            if group_name == "travel" and not advanced_hits:
                recommended_level = "L2"
            if group_name in {"defined_operation", "pigeonhole", "game"}:
                recommended_level = "L4"
            if advanced_hits and _has_l5_entry_signal(combined_text):
                recommended_level = "L5"
            if direct_formula_guard and _level_rank(recommended_level) > 2:
                recommended_level = "L2"

            can_raise = (
                not direct_formula_guard
                and _level_rank(recommended_level) >= 3
                and (bool(advanced_hits) or len(signal_hits) >= 3 or bool(topic_hits))
            )
            title = _GROUP_TITLES.get(group_name, group_name)
            matched_terms = _unique([*topic_hits, *signal_hits[:4]])
            structure_signals = _unique([*signal_hits, *advanced_hits])
            score = sum(len(_normalize_text(term)) for term in matched_terms) + len(structure_signals) * 3
            candidates.append(
                {
                    "candidate_id": self._candidate_id(
                        match_scope="topic_structure",
                        source="local_structure_rules",
                        title=title,
                        extra=group_name,
                    ),
                    "match_scope": "topic_structure",
                    "source": "local_structure_rules",
                    "source_family": "local_rules",
                    "title": title,
                    "matched_terms": matched_terms,
                    "structure_signals": structure_signals,
                    "grade": "",
                    "grade_hint": "",
                    "book_name": "",
                    "lecture_no": "",
                    "lecture_title": "",
                    "topic_category": group_name,
                    "section_level": "",
                    "section_label": "",
                    "question_no": "",
                    "page_no": "",
                    "match_strength": 0,
                    "similarity_type": "topic_structure",
                    "quality_flags": [],
                    "recommended_level": recommended_level,
                    "can_raise_level": can_raise,
                    "score": round(float(score), 3),
                    "question_text_excerpt": "",
                }
            )
        candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return candidates

    def _reference_topic_structure_candidates(
        self,
        *,
        combined_text: str,
        query_terms: Sequence[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for entry in self._entries():
            if entry.source == GAOSI_QUESTION_SOURCE:
                continue
            entry_terms = self._entry_terms(entry)
            matched_terms = self._matched_terms(entry_terms, combined_text, query_terms)
            if not matched_terms:
                continue
            structure_signals: List[str] = []
            matched_group_names: List[str] = []
            for group in DIM5_TOPIC_STRUCTURE_GROUPS.values():
                group_topics = tuple(group.get("topics", ()))
                if not any(
                    _normalize_text(topic) in _normalize_text(term)
                    or _normalize_text(term) in _normalize_text(topic)
                    for topic in group_topics
                    for term in matched_terms
                ):
                    continue
                group_name = next(
                    (
                        name
                        for name, candidate_group in DIM5_TOPIC_STRUCTURE_GROUPS.items()
                        if candidate_group is group
                    ),
                    "",
                )
                if group_name:
                    matched_group_names.append(group_name)
                for signal in group.get("signals", ()):
                    if _normalize_text(signal) in combined_text:
                        structure_signals.append(signal)
            structure_signals = _unique(structure_signals)
            if not structure_signals:
                continue
            score = sum(len(_normalize_text(term)) for term in matched_terms) + len(structure_signals) * 3
            recommended_level = self._recommended_level_for_entry(entry, match_scope="topic_structure")
            advanced_hits = [
                signal
                for group_name in matched_group_names
                for signal in _ADVANCED_STRUCTURE_SIGNALS.get(group_name, ())
                if _normalize_text(signal) in combined_text
            ]
            has_advanced_structure = bool(advanced_hits)
            if not has_advanced_structure and self._source_family(entry.source) == "gaosi":
                recommended_level = "L2"
            if has_advanced_structure and _has_l5_entry_signal(combined_text):
                recommended_level = "L5"
            can_raise = (
                has_advanced_structure
                and _level_rank(recommended_level) >= 3
                and self._source_family(entry.source) != "school"
            )
            candidate = self._entry_candidate(
                entry,
                match_scope="topic_structure",
                matched_terms=matched_terms[:8],
                structure_signals=structure_signals[:8],
                score=score,
                can_raise_level=can_raise,
            )
            candidate["recommended_level"] = recommended_level
            candidate["can_raise_level"] = can_raise
            candidates.append(candidate)
        candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return candidates[: max(limit, 0)]

    def _topic_structure_candidates(
        self,
        *,
        combined_text: str,
        query_terms: Sequence[str],
        direct_formula_guard: bool,
        limit: int,
    ) -> List[Dict[str, Any]]:
        candidates = [
            *self._local_topic_structure_candidates(
                combined_text=combined_text,
                direct_formula_guard=direct_formula_guard,
            ),
            *self._reference_topic_structure_candidates(
                combined_text=combined_text,
                query_terms=query_terms,
                limit=limit,
            ),
        ]
        candidates = self._dedupe_candidates(candidates)
        candidates.sort(
            key=lambda item: (
                1 if item.get("can_raise_level") else 0,
                _level_rank(str(item.get("recommended_level") or "")),
                float(item.get("score") or 0.0),
            ),
            reverse=True,
        )
        return candidates[: max(limit, 0)]

    def _quality_flags_for_entry(self, entry: ReferenceEntry, strength: int) -> List[str]:
        flags: List[str] = []
        if entry.ocr_confidence and entry.ocr_confidence < 0.65:
            flags.append("low_ocr_confidence")
        if entry.has_diagram:
            flags.append("has_diagram")
            if 0 < strength < 3:
                flags.append("diagram_partial_match")
        if len(_compact_text(entry.question_text or entry.title)) < 12:
            flags.append("short_question_text")
        return _unique(flags)

    @staticmethod
    def _similarity_type(strength: int) -> str:
        if strength >= 3:
            return "exact/near_exact"
        if strength >= 2:
            return "high_similarity"
        if strength == 1:
            return "partial/audit_only"
        return "none"

    def _recommended_level_for_payload(self, payload: Dict[str, Any], *, match_scope: str) -> str:
        grade = _parse_grade(payload.get("grade"), payload.get("grade_hint"), payload.get("book_name"))
        source_family = self._source_family(str(payload.get("source") or GAOSI_QUESTION_SOURCE))
        section_level = str(payload.get("section_level") or "").strip()
        section_label = str(payload.get("section_label") or "").strip()
        text = _flatten_profile_text(payload)
        if source_family == "school":
            return "L1" if grade is not None and grade <= 3 else "L2"
        if source_family == "gaosi":
            if grade is not None and grade <= 4:
                return "L3"
            if match_scope == "reference_question" and grade == 6:
                section_text = f"{section_level} {section_label}"
                if ("challenge" in section_text.lower() or "超越篇" in section_text) or _has_l5_entry_signal(text):
                    return "L5"
            return "L4"
        if source_family == "olympiad":
            if _has_l5_entry_signal(text):
                return "L5" if match_scope == "reference_question" else "L4"
            if grade is not None and grade <= 4:
                return "L3"
            return "L4"
        band_level = _OLD_BAND_TO_LEVEL.get(str(payload.get("dim5_reference_band") or "").strip())
        if band_level:
            return band_level
        return _SECTION_TO_LEVEL.get(section_level) or _SECTION_TO_LEVEL.get(section_label) or "L4"

    def _candidate_from_reference_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        section_level = str(payload.get("section_level") or "").strip()
        section_label = str(payload.get("section_label") or "").strip()
        recommended_level = self._recommended_level_for_payload(payload, match_scope="reference_question")
        strength = int(payload.get("similarity_strength") or payload.get("match_strength") or 0)
        quality = str(payload.get("match_quality") or "").strip()
        quality_flags = [quality] if quality and quality != "ok" else []
        if payload.get("ocr_confidence") and float(payload.get("ocr_confidence") or 0.0) < 0.65:
            quality_flags.append("low_ocr_confidence")
        if payload.get("has_diagram") and strength < 3:
            quality_flags.append("diagram_partial_match")
        can_raise = bool(payload.get("auto_correction_allowed")) and strength >= 2 and not quality_flags
        if recommended_level == "L5":
            can_raise = can_raise and strength >= 2
        return {
            "candidate_id": self._candidate_id(
                match_scope="reference_question",
                source=str(payload.get("source") or GAOSI_QUESTION_SOURCE),
                title=str(payload.get("lecture_title") or payload.get("topic_category") or ""),
                extra=str(payload.get("question_no") or payload.get("page_no") or ""),
            ),
            "match_scope": "reference_question",
            "source": str(payload.get("source") or GAOSI_QUESTION_SOURCE),
            "source_family": "gaosi",
            "title": str(payload.get("lecture_title") or payload.get("topic_category") or ""),
            "matched_terms": list(payload.get("matched_terms") or payload.get("knowledge_anchor_terms") or []),
            "structure_signals": list(
                (payload.get("structure_profile") or {}).get("structure_signals", [])
                if isinstance(payload.get("structure_profile"), dict)
                else []
            ),
            "grade": str(payload.get("grade") or ""),
            "grade_hint": str(payload.get("grade_hint") or ""),
            "book_name": str(payload.get("book_name") or ""),
            "lecture_no": str(payload.get("lecture_no") or ""),
            "lecture_title": str(payload.get("lecture_title") or ""),
            "topic_category": str(payload.get("topic_category") or ""),
            "section_level": section_level,
            "section_label": section_label,
            "question_no": str(payload.get("question_no") or ""),
            "page_no": str(payload.get("page_no") or ""),
            "match_strength": strength,
            "similarity_type": str(payload.get("similarity_type") or self._similarity_type(strength)),
            "quality_flags": _unique(quality_flags),
            "recommended_level": recommended_level,
            "can_raise_level": can_raise,
            "score": float(strength * 30 + len(payload.get("matched_terms") or [])),
            "question_text_excerpt": str(payload.get("question_text_excerpt") or "")[:140],
        }

    def _reference_question_candidates(
        self,
        *,
        combined_text: str,
        dim5_feature: Dict[str, Any],
        question_text: str,
        question_summary: str,
        analysis_facts: Dict[str, Any],
        limit: int,
    ) -> List[Dict[str, Any]]:
        if hasattr(self.reference_standard, "gaosi_question_candidates"):
            try:
                payloads = self.reference_standard.gaosi_question_candidates(
                    dim5_feature,
                    question_text=question_text,
                    question_summary=question_summary,
                    analysis_facts=analysis_facts,
                    limit=limit,
                )
                return [self._candidate_from_reference_payload(payload) for payload in payloads or []]
            except Exception:
                # Fall through to the self-contained matcher below.
                pass

        candidates: List[Dict[str, Any]] = []
        for entry in self._entries():
            if entry.source != GAOSI_QUESTION_SOURCE:
                continue
            strength = _question_match_strength(entry.question_text or entry.title, combined_text)
            if strength <= 0:
                continue
            entry_terms = self._entry_terms(entry)
            matched_terms = self._matched_terms(entry_terms, combined_text, [])
            quality_flags = self._quality_flags_for_entry(entry, strength)
            recommended_level = self._recommended_level_for_entry(entry, match_scope="reference_question")
            can_raise = strength >= 2 and not quality_flags
            if recommended_level == "L5":
                can_raise = can_raise and strength >= 2
            score = strength * 30 + sum(len(_normalize_text(term)) for term in matched_terms)
            candidates.append(
                self._entry_candidate(
                    entry,
                    match_scope="reference_question",
                    matched_terms=matched_terms[:8],
                    structure_signals=[],
                    score=score,
                    match_strength=strength,
                    similarity_type=self._similarity_type(strength),
                    quality_flags=quality_flags,
                    can_raise_level=can_raise,
                    question_text_excerpt=entry.question_text,
                )
            )
        candidates.sort(
            key=lambda item: (
                int(item.get("match_strength") or 0),
                1 if item.get("can_raise_level") else 0,
                float(item.get("score") or 0.0),
            ),
            reverse=True,
        )
        return candidates[: max(limit, 0)]

    def _dedupe_candidates(self, candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in candidates:
            candidate_id = str(candidate.get("candidate_id") or "").strip()
            if not candidate_id:
                candidate_id = self._candidate_id(
                    match_scope=str(candidate.get("match_scope") or ""),
                    source=str(candidate.get("source") or ""),
                    title=str(candidate.get("title") or ""),
                    extra=str(candidate.get("question_no") or ""),
                )
                candidate["candidate_id"] = candidate_id
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            deduped.append(candidate)
        return deduped

    @staticmethod
    def _top_recommendation(candidates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        for candidate in candidates:
            if candidate.get("can_raise_level") and _level_rank(str(candidate.get("recommended_level") or "")):
                return {
                    "candidate_id": candidate.get("candidate_id", ""),
                    "match_scope": candidate.get("match_scope", ""),
                    "recommended_level": candidate.get("recommended_level", ""),
                    "source": candidate.get("source", ""),
                    "title": candidate.get("title", ""),
                    "can_raise_level": True,
                }
        if not candidates:
            return {}
        candidate = candidates[0]
        return {
            "candidate_id": candidate.get("candidate_id", ""),
            "match_scope": candidate.get("match_scope", ""),
            "recommended_level": candidate.get("recommended_level", ""),
            "source": candidate.get("source", ""),
            "title": candidate.get("title", ""),
            "can_raise_level": False,
        }
