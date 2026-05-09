"""
维度5：知识点广度评分引擎

题级负责识别知识来源与最高知识门槛；卷级聚合以题级分均值为主，知识来源构成用于解释。
"""

from typing import Any, Dict

from app.services.scoring.base import BaseDimensionScorer, DimensionScore
from app.services.scoring.banded_dimension import _normalize_band, score_banded_dimension


SCHOOL_LOW_BAND = "4年级及以前校内课本难度"
SCHOOL_HIGH_BAND = "5、6年级校内课本难度"
LOW_GAOSI_BAND = "4年级及以前高思导引拓展篇及以下难度"
HIGH_GAOSI_OR_JUNIOR_BAND = "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度"
BEYOND_BAND = "高思导引超越篇难度"

DIM5_BUCKET_LABELS = {
    "school": "校内教材",
    "low_gaosi": "低段高思拓展",
    "high_gaosi": "高年级高思拓展",
    "junior_bridge": "初中前置",
    "beyond": "高思超越篇",
    "unknown": "未稳定归类",
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

    def _calculate_score(self, features: Dict[str, Any]) -> DimensionScore:
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
        ):
            if score_features.get(key) not in ("", None, [], {}):
                result.details[key] = score_features.get(key)
        if section_override:
            result.details["gaosi_section_override"] = section_override
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
