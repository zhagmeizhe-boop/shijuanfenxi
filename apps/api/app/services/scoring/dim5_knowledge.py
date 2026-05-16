"""
维度5：知识点广度评分引擎

题级负责识别知识来源与最高知识门槛；卷级聚合以题级分均值为主，知识来源构成用于解释。
"""

from typing import Any, Dict

from app.services.scoring.base import BaseDimensionScorer, DimensionScore
from app.services.scoring.banded_dimension import _normalize_band, score_banded_dimension
from app.services.scoring.dim5_canonical import (
    DIM5_LEVEL_LABELS,
    DIM5_LEVEL_SCORES,
    classify_dim5_knowledge_scope,
    normalize_dim5_knowledge_level,
)


SCHOOL_LOW_BAND = "4年级及以前校内课本难度"
SCHOOL_HIGH_BAND = "5、6年级校内课本难度"
LOW_GAOSI_BAND = "4年级及以前高思导引拓展篇及以下难度"
HIGH_GAOSI_OR_JUNIOR_BAND = "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度"
BEYOND_BAND = "高思导引超越篇难度"

BAND_RANKS = {
    SCHOOL_LOW_BAND: 1,
    SCHOOL_HIGH_BAND: 2,
    LOW_GAOSI_BAND: 3,
    HIGH_GAOSI_OR_JUNIOR_BAND: 4,
    BEYOND_BAND: 5,
}
RANK_BANDS = {rank: band for band, rank in BAND_RANKS.items()}

DIM5_BUCKET_LABELS = {
    "school": "校内知识",
    "low_gaosi": "三四年级奥数入门",
    "high_gaosi": "五六年级奥数典型专题",
    "junior_bridge": "七年级基础前置",
    "beyond": "六年级奥数较难 / 七年级核心门槛",
    "unknown": "未稳定归类",
}

DIM5_LEVEL_BUCKETS = {
    "L1": "school",
    "L2": "school",
    "L3": "low_gaosi",
    "L4": "high_gaosi",
    "L5": "beyond",
}

_GAOSI_CHALLENGE_SECTION_VALUES = {"challenge", "超越篇"}
_GAOSI_EXTENSION_SECTION_VALUES = {"extension", "拓展篇"}
_GAOSI_INTEREST_SECTION_VALUES = {"interest", "兴趣篇"}
_JUNIOR_SIGNALS = (
    "七年级",
    "7年级",
    "初中",
    "七上",
    "一次方程",
    "有理数",
    "整式",
    "代数式",
    "负数运算",
)

_CHINESE_GRADE_VALUES = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
}

_HIGH_GAOSI_KNOWLEDGE_GROUPS = {
    "defined_operation": ("定义新运算", "规定一种运算", "自定义运算", "运算规则展开"),
    "telescoping": ("裂项", "非相邻裂项", "长链消去", "首尾项提取", "结构求和"),
    "recurrence": ("递推", "差分", "周期数列", "循环周期", "数列求余"),
    "pigeonhole": ("抽屉", "抽屉原理"),
    "combinatorics": ("组合计数", "容斥", "分类计数"),
    "number_theory": ("同余", "整除约束", "余数周期", "不变量", "奇偶性"),
    "game": ("博弈", "必胜", "必败", "对称策略", "制胜策略"),
    "construction": ("极值构造", "规则反推", "染色", "全局构造", "最优性"),
    "advanced_geometry": (
        "几何割补",
        "面积比链",
        "辅助线",
        "复杂几何",
        "鸟头",
        "沙漏",
        "蝴蝶模型",
        "立体极值",
    ),
}

_BEYOND_KNOWLEDGE_GROUPS = {
    "telescoping",
    "recurrence",
    "pigeonhole",
    "combinatorics",
    "number_theory",
    "game",
    "construction",
    "advanced_geometry",
}

_DIRECT_SCHOOL_FORMULA_SIGNALS = (
    "直接公式",
    "普通公式",
    "圆柱圆锥体积比",
    "圆柱和圆锥体积",
    "圆锥体积",
    "圆柱体积",
    "长方形面积",
    "百分数直接应用",
)

_CANONICAL_BOUNDARY_FAMILIES = {
    "application_olympiad_model",
    "geometry_olympiad_model",
    "sequence_olympiad_model",
    "operation_olympiad_model",
    "calculation_olympiad_model",
    "combinatorics_olympiad_model",
    "game_olympiad_model",
    "number_theory_olympiad_model",
    "construction_olympiad_model",
}

_SUBLEVEL_RANKS = {"low": 1, "mid": 2, "high": 3}
_RANK_TO_SUBLEVEL = {1: "low", 2: "mid", 3: "high"}


class Dim5KnowledgeScorer(BaseDimensionScorer):
    """
    维度5：知识点广度评分器

    只看解出题目必须跨过的最高核心知识门槛。
    """

    DIMENSION_CODE = "dim5"
    DIMENSION_NAME = "知识点广度"

    def __init__(self):
        super().__init__(config=None)

    def _get_default_config(self):
        return {
            "max_score": 10.0,
            "score_granularity": 0.5,
        }

    @staticmethod
    def _flatten_text(value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(Dim5KnowledgeScorer._flatten_text(item) for item in value.values())
        if isinstance(value, list):
            return " ".join(Dim5KnowledgeScorer._flatten_text(item) for item in value)
        return str(value or "")

    @classmethod
    def _has_any_signal(cls, feature: Dict[str, Any], signals: tuple[str, ...]) -> bool:
        text_parts = [
            feature.get("evidence_summary", ""),
            feature.get("competition_signal", ""),
            cls._flatten_text(feature.get("knowledge_tags", [])),
            cls._flatten_text(feature.get("core_knowledge_units", [])),
            cls._flatten_text(feature.get("supporting_knowledge_units", [])),
            cls._flatten_text(feature.get("calibration", {}).get("matched_entries", []))
            if isinstance(feature.get("calibration"), dict)
            else "",
        ]
        combined = " ".join(str(part or "") for part in text_parts)
        return any(signal in combined for signal in signals)

    @classmethod
    def _combined_evidence_text(cls, feature: Dict[str, Any]) -> str:
        text_parts = [
            feature.get("evidence_summary", ""),
            feature.get("competition_signal", ""),
            feature.get("knowledge_integration", ""),
            feature.get("novel_definition_dependency", ""),
            cls._flatten_text(feature.get("evidence_tags", [])),
            cls._flatten_text(feature.get("knowledge_tags", [])),
            cls._flatten_text(feature.get("core_knowledge_units", [])),
            cls._flatten_text(feature.get("supporting_knowledge_units", [])),
            feature.get("canonical_knowledge_point", ""),
            feature.get("canonical_knowledge_family", ""),
            cls._flatten_text(feature.get("canonical_alias_hits", [])),
            cls._flatten_text(feature.get("canonical_structure_hits", [])),
            cls._flatten_text(feature.get("analysis_facts", {})),
        ]
        return " ".join(str(part or "") for part in text_parts)

    @classmethod
    def _matched_knowledge_groups(cls, feature: Dict[str, Any]) -> list[str]:
        combined = cls._combined_evidence_text(feature)
        matched: list[str] = []
        for group, signals in _HIGH_GAOSI_KNOWLEDGE_GROUPS.items():
            if any(signal in combined for signal in signals):
                matched.append(group)
        return matched

    @classmethod
    def _has_direct_school_formula_signal(cls, feature: Dict[str, Any]) -> bool:
        combined = cls._combined_evidence_text(feature)
        return any(signal in combined for signal in _DIRECT_SCHOOL_FORMULA_SIGNALS)

    @staticmethod
    def _raise_sublevel_once(value: str) -> str:
        rank = _SUBLEVEL_RANKS.get(str(value or "").strip().lower(), 0)
        if rank <= 0:
            return "mid"
        return _RANK_TO_SUBLEVEL.get(min(rank + 1, 3), "high")

    @classmethod
    def _canonical_boundary_override(cls, features: Dict[str, Any]) -> Dict[str, Any]:
        if cls._has_direct_school_formula_signal(features) or features.get("canonical_direct_formula_guard"):
            return {}

        canonical_point = str(features.get("canonical_knowledge_point") or "").strip()
        canonical_family = str(features.get("canonical_knowledge_family") or "").strip()
        if not canonical_point or canonical_family not in _CANONICAL_BOUNDARY_FAMILIES:
            return {}

        current_band = _normalize_band(features.get("band"))
        current_rank = BAND_RANKS.get(current_band, 0)
        if current_rank <= 0 or current_rank >= BAND_RANKS[BEYOND_BAND]:
            return {}

        confidence = float(features.get("canonical_match_confidence") or 0.0)
        if confidence < 0.65:
            return {}

        source = str(features.get("canonical_match_source") or "").strip()
        structure_supported = (
            source == "topic_and_structure"
            or bool(features.get("canonical_structure_hits"))
            or features.get("competition_signal") in {"weak", "strong"}
            or features.get("knowledge_integration") in {"same_family_combo", "cross_family_combo", "cross_domain_bridge"}
            or features.get("novel_definition_dependency") in {"local", "strong"}
        )
        if not structure_supported:
            return {}

        current_sublevel = str(features.get("sublevel") or "").strip().lower()
        target_band = current_band
        target_sublevel = current_sublevel
        if current_rank < BAND_RANKS[LOW_GAOSI_BAND]:
            target_band = RANK_BANDS.get(current_rank + 1, current_band)
            target_sublevel = "mid" if current_rank >= BAND_RANKS[SCHOOL_HIGH_BAND] else "high"
        elif current_rank == BAND_RANKS[LOW_GAOSI_BAND]:
            if current_sublevel in {"mid", "high"}:
                target_band = HIGH_GAOSI_OR_JUNIOR_BAND
                target_sublevel = "low"
            else:
                target_sublevel = "mid"
        elif current_rank == BAND_RANKS[HIGH_GAOSI_OR_JUNIOR_BAND]:
            target_sublevel = cls._raise_sublevel_once(current_sublevel)

        if target_band == current_band and target_sublevel == current_sublevel:
            return {}

        return {
            "band": target_band,
            "sublevel": target_sublevel,
            "band_source": "canonical_boundary_upshift",
            "dim5_upshift_reason": (
                f"标准知识点“{canonical_point}”命中奥数/高思专题边界，按相邻高档处理。"
            ),
            "canonical_boundary_upshift": {
                "original_band": current_band,
                "original_sublevel": current_sublevel,
                "canonical_knowledge_point": canonical_point,
                "canonical_knowledge_family": canonical_family,
                "canonical_match_source": source,
            },
        }

    @classmethod
    def _knowledge_anchor_override(cls, features: Dict[str, Any]) -> Dict[str, Any]:
        """Conservative local correction for explicit WMO-style knowledge anchors.

        This does not use contest names or file sources. It only reacts to specific
        core knowledge units that are already present in the per-question facts.
        """
        current_band = _normalize_band(features.get("band"))
        current_rank = BAND_RANKS.get(current_band, 0)
        if current_rank <= 0 or current_rank >= BAND_RANKS[BEYOND_BAND]:
            return {}

        if cls._has_direct_school_formula_signal(features):
            return {}

        matched_groups = cls._matched_knowledge_groups(features)
        if not matched_groups:
            return {}

        beyond_group_count = sum(1 for group in matched_groups if group in _BEYOND_KNOWLEDGE_GROUPS)
        strong_competition_structure = (
            features.get("competition_signal") == "strong"
            or features.get("knowledge_integration") in {"cross_family_combo", "cross_domain_bridge"}
            or features.get("novel_definition_dependency") == "strong"
        )
        beyond_override = (
            current_rank >= BAND_RANKS[HIGH_GAOSI_OR_JUNIOR_BAND]
            and beyond_group_count >= 2
            and strong_competition_structure
        )

        if beyond_override:
            sublevel = "high" if beyond_group_count >= 3 else "mid"
            return {
                "band": BEYOND_BAND,
                "sublevel": sublevel,
                "band_source": "knowledge_anchor",
                "knowledge_anchor_override": {
                    "original_band": current_band,
                    "original_sublevel": str(features.get("sublevel") or "").strip().lower(),
                    "matched_groups": matched_groups,
                    "reason": "强竞赛知识锚点组合达到超越篇候选门槛",
                },
            }

        if current_rank < BAND_RANKS[HIGH_GAOSI_OR_JUNIOR_BAND]:
            sublevel = "high" if len(matched_groups) >= 2 else "mid"
            return {
                "band": HIGH_GAOSI_OR_JUNIOR_BAND,
                "sublevel": sublevel,
                "band_source": "knowledge_anchor",
                "knowledge_anchor_override": {
                    "original_band": current_band,
                    "original_sublevel": str(features.get("sublevel") or "").strip().lower(),
                    "matched_groups": matched_groups,
                    "reason": "明确高年级高思/竞赛型知识锚点，不按校内题处理",
                },
            }

        return {}

    @staticmethod
    def _parse_gaosi_grade(value: Any) -> int | None:
        text = str(value or "").strip()
        if not text:
            return None
        for char in text:
            if char.isdigit():
                grade = int(char)
                if 1 <= grade <= 6:
                    return grade
        for char, grade in _CHINESE_GRADE_VALUES.items():
            if char in text:
                return grade
        return None

    @classmethod
    def _band_for_gaosi_grade(cls, grade: int | None) -> str:
        return LOW_GAOSI_BAND if grade is None or grade <= 4 else HIGH_GAOSI_OR_JUNIOR_BAND

    @classmethod
    def _gaosi_section_override(cls, features: Dict[str, Any]) -> Dict[str, Any]:
        section_values = {
            str(features.get("gaosi_section_level") or "").strip(),
            str(features.get("gaosi_section_label") or "").strip(),
        }
        normalized_values = {value.lower() for value in section_values if value}
        section_text = " ".join(value for value in section_values if value)
        grade = cls._parse_gaosi_grade(features.get("gaosi_grade"))

        if normalized_values & _GAOSI_CHALLENGE_SECTION_VALUES or "超越篇" in section_text:
            return {
                "band": BEYOND_BAND,
                "sublevel": "high",
                "gaosi_grade": grade,
                "gaosi_section_level": "challenge",
                "gaosi_section_label": "超越篇",
            }
        if normalized_values & _GAOSI_EXTENSION_SECTION_VALUES or "拓展篇" in section_text:
            return {
                "band": cls._band_for_gaosi_grade(grade),
                "sublevel": "mid",
                "gaosi_grade": grade,
                "gaosi_section_level": "extension",
                "gaosi_section_label": "拓展篇",
            }
        if normalized_values & _GAOSI_INTEREST_SECTION_VALUES or "兴趣篇" in section_text:
            return {
                "band": cls._band_for_gaosi_grade(grade),
                "sublevel": "low",
                "gaosi_grade": grade,
                "gaosi_section_level": "interest",
                "gaosi_section_label": "兴趣篇",
            }
        return {}

    @classmethod
    def classify_source_bucket(cls, features: Dict[str, Any]) -> str:
        """Return the paper-composition bucket used by the dim5 paper-level scorer."""
        knowledge_level = normalize_dim5_knowledge_level(features.get("knowledge_level"))
        if knowledge_level:
            if knowledge_level == "L4" and cls._has_any_signal(features, _JUNIOR_SIGNALS):
                return "junior_bridge"
            return DIM5_LEVEL_BUCKETS.get(knowledge_level, "unknown")

        band = _normalize_band(features.get("band"))
        gaosi_section_values = {
            str(features.get("gaosi_section_level") or "").strip(),
            str(features.get("gaosi_section_label") or "").strip(),
        }

        if band == BEYOND_BAND or bool(gaosi_section_values & _GAOSI_CHALLENGE_SECTION_VALUES):
            return "beyond"

        if band == HIGH_GAOSI_OR_JUNIOR_BAND and cls._has_any_signal(features, _JUNIOR_SIGNALS):
            return "junior_bridge"

        if band in {SCHOOL_LOW_BAND, SCHOOL_HIGH_BAND}:
            return "school"
        if band == LOW_GAOSI_BAND:
            return "low_gaosi"
        if band == HIGH_GAOSI_OR_JUNIOR_BAND:
            return "high_gaosi"
        return "unknown"

    @classmethod
    def _score_by_knowledge_level(cls, features: Dict[str, Any]) -> DimensionScore:
        score_features = dict(features or {})
        if not normalize_dim5_knowledge_level(score_features.get("knowledge_level")):
            score_features.update(
                classify_dim5_knowledge_scope(
                    score_features,
                    analysis_facts=score_features.get("analysis_facts", {})
                    if isinstance(score_features.get("analysis_facts"), dict)
                    else {},
                )
            )

        knowledge_level = normalize_dim5_knowledge_level(score_features.get("knowledge_level"))
        if not knowledge_level:
            return DimensionScore(
                dimension_code=cls.DIMENSION_CODE,
                score=0.0,
                level=0,
                level_label="N/A",
                evidence="题目缺少可读知识点，维度5需人工复核。",
                applicable=False,
                details={
                    "level_source": "unreadable_or_empty",
                    "dim5_excluded_reason": "missing_readable_knowledge_point",
                },
            )

        question_score = DIM5_LEVEL_SCORES[knowledge_level]
        level_rank = int(knowledge_level[1])
        level_label = f"{knowledge_level} {DIM5_LEVEL_LABELS[knowledge_level]}"
        domain = str(score_features.get("canonical_knowledge_domain") or "school_general").strip()
        canonical_point = str(
            score_features.get("canonical_knowledge_point")
            or score_features.get("primary_knowledge_point")
            or "校内一般知识"
        ).strip()
        level_evidence = str(score_features.get("level_evidence") or "").strip()
        evidence_summary = str(score_features.get("evidence_summary") or "").strip()

        details: Dict[str, Any] = {
            "knowledge_level": knowledge_level,
            "dim5_level": knowledge_level,
            "canonical_knowledge_domain": domain,
            "canonical_knowledge_point": canonical_point,
            "level_source": str(score_features.get("level_source") or "canonical_rule").strip(),
            "level_evidence": level_evidence,
            "knowledge_source_bucket": cls.classify_source_bucket(score_features),
            "knowledge_source_label": DIM5_BUCKET_LABELS.get(
                cls.classify_source_bucket(score_features),
                cls.classify_source_bucket(score_features),
            ),
            "evidence_summary": evidence_summary,
        }
        for key in (
            "band",
            "sublevel",
            "band_source",
            "dim5_retry_used",
            "dim5_retry_confidence",
            "dim5_retry_error",
            "dim5_excluded_reason",
            "gaosi_grade",
            "gaosi_section_level",
            "gaosi_section_label",
            "gaosi_classification_source",
            "primary_knowledge_point",
            "knowledge_point_source",
            "canonical_knowledge_family",
            "canonical_match_source",
            "canonical_match_confidence",
            "canonical_alias_hits",
            "canonical_structure_hits",
            "canonical_direct_formula_guard",
            "dim5_fallback_mode",
            "dim5_upshift_reason",
            "calibration",
            "core_knowledge_units",
            "knowledge_tags",
            "supporting_knowledge_units",
            "competition_signal",
            "knowledge_integration",
            "novel_definition_dependency",
            "dim5_retrieval_context",
            "dim5_retrieval_candidates",
            "dim5_retrieval_decision",
            "accepted_retrieval_candidate_ids",
            "rejected_retrieval_candidate_ids",
            "knowledge_grounding_context",
            "knowledge_grounding_candidates",
            "grounded_selection_status",
            "selected_knowledge_candidate_id",
            "grounded_canonical_knowledge_point",
            "grounded_knowledge_domain",
            "grounded_knowledge_source_text",
            "grounded_knowledge_level",
            "grounded_confidence",
            "grounded_evidence",
            "grounded_match_source",
            "grounded_risk_flags",
            "grounded_rejected_candidates",
            "grounded_selector",
        ):
            if score_features.get(key) not in ("", None, [], {}):
                details[key] = score_features.get(key)

        evidence_parts = [
            f"本题归入 {knowledge_level}（{DIM5_LEVEL_LABELS[knowledge_level]}）",
            f"标准知识点：{canonical_point}",
            f"知识域：{domain}",
        ]
        if level_evidence:
            evidence_parts.append(level_evidence)
        elif evidence_summary:
            evidence_parts.append(evidence_summary)
        knowledge_tags = score_features.get("knowledge_tags")
        if isinstance(knowledge_tags, list) and knowledge_tags:
            evidence_parts.append(
                "依据标签：" + "、".join(str(item).strip() for item in knowledge_tags[:6] if str(item).strip())
            )

        return DimensionScore(
            dimension_code=cls.DIMENSION_CODE,
            score=question_score,
            level=level_rank,
            level_label=level_label,
            evidence="；".join(evidence_parts) + "。",
            applicable=True,
            details=details,
        )

    def _calculate_score(self, features: Dict[str, Any]) -> DimensionScore:
        return self._score_by_knowledge_level(features)

        score_features = dict(features)
        section_override = self._gaosi_section_override(score_features)
        if section_override:
            original_band = _normalize_band(score_features.get("band"))
            original_sublevel = str(score_features.get("sublevel") or "").strip().lower()
            score_features["band"] = section_override["band"]
            score_features["sublevel"] = section_override["sublevel"]
            score_features["band_source"] = "gaosi_section_override"
            score_features.setdefault("gaosi_classification_source", "knowledge_base")
            if section_override.get("gaosi_grade") is not None:
                score_features["gaosi_grade"] = section_override["gaosi_grade"]
            score_features["gaosi_section_level"] = section_override["gaosi_section_level"]
            score_features["gaosi_section_label"] = section_override["gaosi_section_label"]
            section_override = {
                **section_override,
                "original_band": original_band,
                "original_sublevel": original_sublevel,
            }

        knowledge_anchor_override = {}
        if not section_override:
            knowledge_anchor_override = self._knowledge_anchor_override(score_features)
            if knowledge_anchor_override:
                score_features["band"] = knowledge_anchor_override["band"]
                score_features["sublevel"] = knowledge_anchor_override["sublevel"]
                score_features["band_source"] = knowledge_anchor_override["band_source"]

        canonical_boundary_override = {}
        if not section_override and not knowledge_anchor_override:
            canonical_boundary_override = self._canonical_boundary_override(score_features)
            if canonical_boundary_override:
                score_features["band"] = canonical_boundary_override["band"]
                score_features["sublevel"] = canonical_boundary_override["sublevel"]
                score_features["band_source"] = canonical_boundary_override["band_source"]
                score_features["dim5_upshift_reason"] = canonical_boundary_override["dim5_upshift_reason"]

        result = score_banded_dimension(
            self,
            score_features,
            tag_keys=("evidence_tags", "knowledge_tags"),
            invalid_evidence="LLM 未返回合法的知识点广度档位或档内层级，无法计算此维度分数。",
        )
        if not result.applicable:
            return result

        bucket = self.classify_source_bucket(score_features)
        result.details["knowledge_source_bucket"] = bucket
        result.details["knowledge_source_label"] = DIM5_BUCKET_LABELS.get(bucket, bucket)
        result.details["competition_signal"] = str(score_features.get("competition_signal") or "").strip()
        result.details["knowledge_integration"] = str(score_features.get("knowledge_integration") or "").strip()
        for key in (
            "band_source",
            "dim5_retry_used",
            "dim5_retry_confidence",
            "dim5_retry_error",
            "dim5_excluded_reason",
            "gaosi_grade",
            "gaosi_section_level",
            "gaosi_section_label",
            "gaosi_classification_source",
            "primary_knowledge_point",
            "knowledge_point_source",
            "canonical_knowledge_point",
            "canonical_knowledge_family",
            "canonical_match_source",
            "canonical_match_confidence",
            "canonical_alias_hits",
            "canonical_structure_hits",
            "canonical_direct_formula_guard",
            "dim5_fallback_mode",
            "dim5_upshift_reason",
        ):
            if score_features.get(key) not in ("", None, [], {}):
                result.details[key] = score_features.get(key)
        if score_features.get("calibration") not in ("", None, [], {}):
            result.details["calibration"] = score_features.get("calibration")
        if section_override:
            result.details["gaosi_section_override"] = section_override
        if knowledge_anchor_override:
            result.details["knowledge_anchor_override"] = knowledge_anchor_override[
                "knowledge_anchor_override"
            ]
        if canonical_boundary_override:
            result.details["canonical_boundary_upshift"] = canonical_boundary_override[
                "canonical_boundary_upshift"
            ]
        calibration = score_features.get("calibration", {})
        if isinstance(calibration, dict) and calibration.get("question_level_match"):
            matched_entries = calibration.get("matched_entries", [])
            first_entry = matched_entries[0] if isinstance(matched_entries, list) and matched_entries else {}
            if isinstance(first_entry, dict):
                result.details["gaosi_reference_section"] = str(
                    first_entry.get("section_label") or first_entry.get("track") or ""
                ).strip()
                result.details["gaosi_reference_question"] = str(
                    first_entry.get("question_no") or ""
                ).strip()
                result.details["gaosi_reference_quality"] = str(
                    calibration.get("question_level_match_quality") or ""
                ).strip()
        result.details["core_knowledge_units"] = [
            str(item).strip()
            for item in score_features.get("core_knowledge_units", []) or []
            if str(item).strip()
        ]
        result.evidence = (
            f"{result.evidence} 知识来源归类：{result.details['knowledge_source_label']}。"
        ).strip()
        return result
