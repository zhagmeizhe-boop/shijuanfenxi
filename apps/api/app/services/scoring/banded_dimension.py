"""
Band-based scoring helpers shared by dim1/dim2/dim5.
"""

from typing import Any, Dict, Iterable, List

from app.services.scoring.base import DimensionScore


BAND_SCORE_MAP: Dict[str, Dict[str, float]] = {
    "4年级及以前校内课本难度": {"low": 1.0, "mid": 1.5, "high": 2.0},
    "5、6年级校内课本难度": {"low": 2.5, "mid": 3.0, "high": 3.5},
    "4年级及以前高思导引拓展篇及以下难度": {"low": 4.5, "mid": 5.0, "high": 5.5},
    "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度": {
        "low": 6.5,
        "mid": 7.0,
        "high": 7.5,
    },
    "高思导引超越篇难度": {"low": 8.5, "mid": 9.0, "high": 9.5},
}

SUBLEVEL_LABELS = {
    "low": "低位",
    "mid": "中位",
    "high": "高位",
}

_BAND_ALIASES = {
    "5、6年级及以前高思导引拓展篇及以下难度或七年级及以上校内课本难度":
        "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
    "5、6年级高思导引拓展篇及以下难度 或 七年级及以上校内课本难度":
        "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
    "5、6年级高思导引拓展篇及以下难度或七年级及以上校内课本难度":
        "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
    "高思导引超越篇": "高思导引超越篇难度",
}


def _normalize_band(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = " ".join(text.split())
    return _BAND_ALIASES.get(text, text)


def _normalize_sublevel(value: Any) -> str:
    return str(value or "").strip().lower()


def _collect_tags(features: Dict[str, Any], tag_keys: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    collected: List[str] = []

    for key in tag_keys:
        raw_tags = features.get(key, [])
        if not isinstance(raw_tags, list):
            continue
        for item in raw_tags:
            tag = str(item).strip()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            collected.append(tag)
    return collected


def create_not_applicable_result(scorer, evidence: str) -> DimensionScore:
    return DimensionScore(
        dimension_code=scorer.dimension_code,
        score=0.0,
        level=0,
        level_label="N/A",
        evidence=evidence,
        applicable=False,
    )


def sublevel_label(sublevel: str) -> str:
    return SUBLEVEL_LABELS.get(sublevel, sublevel)


def score_banded_dimension(
    scorer,
    features: Dict[str, Any],
    *,
    tag_keys: Iterable[str] = ("evidence_tags",),
    invalid_evidence: str,
) -> DimensionScore:
    band = _normalize_band(features.get("band"))
    sublevel = _normalize_sublevel(features.get("sublevel"))

    if band not in BAND_SCORE_MAP or sublevel not in SUBLEVEL_LABELS:
        return create_not_applicable_result(scorer, invalid_evidence)

    score = BAND_SCORE_MAP[band][sublevel]
    level, level_label = scorer.calculate_level(score)
    evidence_summary = str(features.get("evidence_summary") or "").strip()
    evidence_tags = _collect_tags(features, tag_keys)

    evidence_parts = [f"本题归入“{band}”，档内定位为{sublevel_label(sublevel)}。"]
    if evidence_summary:
        evidence_parts.append(evidence_summary)
    if evidence_tags:
        evidence_parts.append(f"依据标签：{'、'.join(evidence_tags[:6])}")

    details = {
        "band": band,
        "sublevel": sublevel,
        "evidence_summary": evidence_summary,
        "evidence_tags": evidence_tags,
    }
    knowledge_tags = features.get("knowledge_tags", [])
    if isinstance(knowledge_tags, list):
        details["knowledge_tags"] = [
            str(item).strip()
            for item in knowledge_tags
            if str(item).strip()
        ]

    return DimensionScore(
        dimension_code=scorer.dimension_code,
        score=score,
        level=level,
        level_label=level_label,
        evidence=" ".join(evidence_parts).strip(),
        applicable=True,
        details=details,
    )
