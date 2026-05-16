"""
Second-pass review helpers for unstable dimension applicability.

The second pass is only used when initial dimension facts are unstable. A
stable applicable review can create the question-level score directly; an
unresolved review is excluded from the dimension statistics.
"""

from __future__ import annotations

from typing import Any, Dict

from app.services.scoring.base import DimensionScore
from app.services.scoring.dim1_computation import DIM1_LEVELS
from app.services.scoring.dim3_information import DIM3_LEVELS
from app.services.scoring.dim4_topic_levels import DIM4_TOPIC_LEVELS, normalize_dim4_level
from app.services.scoring.dim6_logic import DIM6_LEVELS


SECOND_REVIEW_STATUS_APPLICABLE = "applicable"
SECOND_REVIEW_STATUS_NOT_APPLICABLE = "not_applicable"
SECOND_REVIEW_STATUS_UNRESOLVED = "unresolved"
SECOND_REVIEW_STATUS_FAILED_EXCLUDED = "review_failed_excluded"
SECOND_REVIEW_CONFIDENCE_THRESHOLD = 0.55

SECOND_REVIEW_LEVELS = {
    "dim1": DIM1_LEVELS,
    "dim3": DIM3_LEVELS,
    "dim4": DIM4_TOPIC_LEVELS,
    "dim6": DIM6_LEVELS,
}


def normalize_second_review_level(value: Any) -> str:
    return normalize_dim4_level(value)


def normalize_second_review_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {SECOND_REVIEW_STATUS_APPLICABLE, "include", "included"}:
        return SECOND_REVIEW_STATUS_APPLICABLE
    if text in {SECOND_REVIEW_STATUS_NOT_APPLICABLE, "not applicable", "exclude", "excluded"}:
        return SECOND_REVIEW_STATUS_NOT_APPLICABLE
    return SECOND_REVIEW_STATUS_UNRESOLVED


def normalize_second_review_payload(dim_code: str, payload: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = dict(payload or {})
    status = normalize_second_review_status(raw.get("status"))
    level = normalize_second_review_level(raw.get("level"))
    confidence = _normalize_confidence(raw.get("confidence"))
    evidence_summary = str(raw.get("evidence_summary") or "").strip()
    exclude_reason = str(raw.get("exclude_reason") or "").strip()

    if dim_code not in SECOND_REVIEW_LEVELS:
        return _unresolved_payload(dim_code, "复评维度不支持。", raw)

    if status == SECOND_REVIEW_STATUS_APPLICABLE:
        if level not in SECOND_REVIEW_LEVELS[dim_code]:
            return _unresolved_payload(dim_code, "复评返回的等级无效。", raw)
        if confidence < SECOND_REVIEW_CONFIDENCE_THRESHOLD:
            return _unresolved_payload(dim_code, "复评置信度不足。", raw)
        if dim_code == "dim1" and level == "L1":
            return {
                "status": SECOND_REVIEW_STATUS_NOT_APPLICABLE,
                "level": "N/A",
                "score": 0.0,
                "evidence_summary": evidence_summary,
                "confidence": confidence,
                "exclude_reason": (
                    exclude_reason
                    or evidence_summary
                    or "维度1二次复评只补录稳定核心计算负担；L1 轻量直接计算不计入。"
                ),
                "raw_payload": raw,
            }
        if dim_code == "dim6" and level in {"L1", "L2"}:
            return {
                "status": SECOND_REVIEW_STATUS_NOT_APPLICABLE,
                "level": "N/A",
                "score": 0.0,
                "evidence_summary": evidence_summary,
                "confidence": confidence,
                "exclude_reason": (
                    exclude_reason
                    or evidence_summary
                    or "维度6二次复评只补录核心逻辑链条负担；L1/L2 低负担结论不计入。"
                ),
                "raw_payload": raw,
            }
        level_info = SECOND_REVIEW_LEVELS[dim_code][level]
        return {
            "status": SECOND_REVIEW_STATUS_APPLICABLE,
            "level": level,
            "score": float(level_info["score"]),
            "evidence_summary": evidence_summary or "二次复评确认该题在本维度有稳定负担。",
            "confidence": confidence,
            "exclude_reason": "",
            "raw_payload": raw,
        }

    if status == SECOND_REVIEW_STATUS_NOT_APPLICABLE:
        if confidence < SECOND_REVIEW_CONFIDENCE_THRESHOLD:
            return _unresolved_payload(dim_code, "复评排除结论置信度不足。", raw)
        return {
            "status": SECOND_REVIEW_STATUS_NOT_APPLICABLE,
            "level": "N/A",
            "score": 0.0,
            "evidence_summary": evidence_summary,
            "confidence": confidence,
            "exclude_reason": exclude_reason or evidence_summary or "二次复评确认该维度不适用。",
            "raw_payload": raw,
        }

    return _unresolved_payload(dim_code, exclude_reason or evidence_summary or "复评未能形成稳定结论。", raw)


def build_second_review_dimension_score(
    dim_code: str,
    review: Dict[str, Any],
    *,
    initial_feature: Dict[str, Any] | None = None,
    initial_status: Dict[str, Any] | None = None,
) -> DimensionScore:
    normalized = normalize_second_review_payload(dim_code, review)
    if normalized["status"] != SECOND_REVIEW_STATUS_APPLICABLE:
        raise ValueError("second review is not applicable")

    level = normalized["level"]
    level_info = SECOND_REVIEW_LEVELS[dim_code][level]
    evidence_summary = normalized["evidence_summary"]
    level_key = f"{dim_code}_level"
    details: Dict[str, Any] = {
        **(initial_feature or {}),
        "status": "applicable",
        level_key: level,
        "evidence_summary": evidence_summary,
        "second_review_status": SECOND_REVIEW_STATUS_APPLICABLE,
        "second_review_requested": True,
        "second_review_confidence": normalized["confidence"],
        "second_review_evidence": evidence_summary,
        "second_review_raw_payload": normalized.get("raw_payload", {}),
    }
    if dim_code == "dim4":
        details["topic_level"] = level
        details["level_source"] = "second_review"
        if not details.get("anchor_evidence"):
            details["anchor_evidence"] = evidence_summary
    if dim_code == "dim1":
        details["dim1_level"] = level
        details["level_source"] = "second_review"
        if not details.get("calc_bucket"):
            task_form = str(details.get("task_form") or "").strip()
            calc_role = str(details.get("calc_role") or "").strip()
            details["calc_bucket"] = (
                "embedded_calculation"
                if task_form == "embedded" and calc_role == "core"
                else "pure_calculation"
            )
        details.setdefault("rule_family", f"{details['calc_bucket']}_second_review")
    if dim_code == "dim3":
        details["dim3_level"] = level
    if dim_code == "dim6":
        details["dim6_level"] = level
        details["level_source"] = "second_review"
    if initial_status:
        details["initial_applicability_status"] = initial_status

    return DimensionScore(
        dimension_code=dim_code,
        score=float(level_info["score"]),
        level=int(level_info["level"]),
        level_label=str(level_info["label"]),
        evidence=f"{level_info['label']}：{evidence_summary}",
        applicable=True,
        details=details,
    )


def build_second_review_exclusion_details(
    dim_code: str,
    review: Dict[str, Any],
    *,
    initial_feature: Dict[str, Any] | None = None,
    initial_status: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    normalized = normalize_second_review_payload(dim_code, review)
    final_status = (
        SECOND_REVIEW_STATUS_NOT_APPLICABLE
        if normalized["status"] == SECOND_REVIEW_STATUS_NOT_APPLICABLE
        else SECOND_REVIEW_STATUS_FAILED_EXCLUDED
    )
    return {
        **(initial_feature or {}),
        "status": final_status,
        f"{dim_code}_level": "N/A",
        "evidence_summary": normalized.get("evidence_summary", ""),
        "second_review_status": final_status,
        "second_review_requested": True,
        "second_review_confidence": normalized.get("confidence", 0.0),
        "second_review_evidence": normalized.get("evidence_summary", ""),
        "second_review_exclude_reason": normalized.get("exclude_reason", ""),
        "second_review_raw_payload": normalized.get("raw_payload", {}),
        "initial_applicability_status": initial_status or {},
    }


def _normalize_confidence(value: Any) -> float:
    try:
        normalized = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, normalized))


def _unresolved_payload(dim_code: str, reason: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": SECOND_REVIEW_STATUS_UNRESOLVED,
        "level": "N/A",
        "score": 0.0,
        "evidence_summary": "",
        "confidence": _normalize_confidence(raw.get("confidence")),
        "exclude_reason": reason or f"{dim_code} 复评未能形成稳定结论。",
        "raw_payload": raw,
    }
