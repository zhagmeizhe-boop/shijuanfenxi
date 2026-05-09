"""
dim4 practice-innovation scorer.

Primary semantics: identify the knowledge point first, then score how far the
question varies from the basic template inside that knowledge point.
"""

from __future__ import annotations

from typing import Any, Dict

from app.services.scoring.base import BaseDimensionScorer, DimensionScore
from app.services.scoring.dim4_topic_levels import (
    DIM4_TOPIC_LEVELS,
    calibrate_dim4_competition_variant_level,
    normalize_dim4_level,
    normalize_dim4_level_source,
)

STRATEGY_ROLE_VALUES = {"none", "supporting", "core"}
TEMPLATE_FIT_VALUES = {"direct", "adapted", "reframed", "non_routine"}
BREAKTHROUGH_TYPE_VALUES = {
    "none",
    "local_trick",
    "strategy_shift",
    "constructive",
    "exploratory_search",
}
STRATEGY_SHIFT_COUNT_VALUES = {"0", "1", "2", "3+"}
CONSTRUCTION_REQUIREMENT_VALUES = {
    "none",
    "simple_setup",
    "case_construction",
    "custom_construction",
}
EXPLORATION_SPACE_VALUES = {"none", "bounded", "branched", "open"}
REPRESENTATION_REFRAME_VALUES = {"none", "minor", "structural", "creative"}
TRANSFER_DISTANCE_VALUES = {"near", "medium", "far"}
PATH_OPENNESS_VALUES = {"single", "multiple_paths", "multiple_answers"}
DEAD_END_RISK_VALUES = {"low", "medium", "high"}
IMAGE_DEPENDENCY_VALUES = {"none", "helpful", "required"}

DIM4_LEVELS = DIM4_TOPIC_LEVELS
DIM4_NUMERIC_LEVELS = {str(index): f"L{index}" for index in range(1, 6)}


def _normalize_choice(value: Any, allowed: set[str]) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else ""


def _normalize_zero_one(value: Any) -> int | None:
    if value in (0, "0", False):
        return 0
    if value in (1, "1", True):
        return 1
    return None


def _shift_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(value, -1)


class Dim4InnovationScorer(BaseDimensionScorer):
    DIMENSION_CODE = "dim4"
    DIMENSION_NAME = "实践创新"

    def __init__(self):
        super().__init__(config=None)

    @staticmethod
    def _normalize_level_code(value: Any) -> str:
        text = str(value or "").strip().upper()
        if text in DIM4_LEVELS:
            return text
        if text in DIM4_NUMERIC_LEVELS:
            return DIM4_NUMERIC_LEVELS[text]
        return ""

    def _build_score(
        self,
        level_code: str,
        evidence_summary: str,
        *,
        calibration: Dict[str, Any] | None = None,
        calibrated: bool = False,
    ) -> DimensionScore:
        level = DIM4_LEVELS[level_code]
        details: Dict[str, Any] = {"status": "applicable", "dim4_level": level_code}
        if isinstance(calibration, dict) and calibration:
            details["reference_calibration"] = calibration
            details["reference_calibrated"] = calibrated
            if calibration.get("model_level"):
                details["dim4_local_level"] = calibration.get("model_level")
            if calibration.get("reference_level"):
                details["dim4_reference_level"] = calibration.get("reference_level")
            if calibration.get("action"):
                details["reference_calibration_action"] = calibration.get("action")
        evidence = f"{level['label']}：{evidence_summary}"
        if calibrated and isinstance(calibration, dict):
            evidence = f"{evidence} 高思题目级参考画像已校准到 {level_code}。"
        return DimensionScore(
            dimension_code=self.DIMENSION_CODE,
            score=level["score"],
            level=level["level"],
            level_label=level["label"],
            evidence=evidence,
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
            details={"status": "not_applicable", "dim4_level": "N/A"},
        )

    def _calculate_score(self, features: Dict[str, Any]) -> DimensionScore:
        topic_level_code = normalize_dim4_level(features.get("topic_level"))
        level_source = normalize_dim4_level_source(features.get("level_source"))
        if topic_level_code and level_source != "review_failed":
            knowledge_point = str(features.get("knowledge_point") or "").strip()
            anchor_evidence = str(features.get("anchor_evidence") or "").strip()
            evidence_summary = (
                str(features.get("evidence_summary") or "").strip()
                or anchor_evidence
                or "已按知识点内部 L1-L5 标尺完成定位。"
            )
            local_variant_calibration = calibrate_dim4_competition_variant_level(
                features,
                topic_level_code,
            )
            if local_variant_calibration:
                topic_level_code = local_variant_calibration.get("topic_level", topic_level_code)
                calibration_reason = str(local_variant_calibration.get("reason") or "").strip()
                if calibration_reason and calibration_reason not in evidence_summary:
                    evidence_summary = f"{evidence_summary} {calibration_reason}".strip()
            result = self._build_score(
                topic_level_code,
                evidence_summary,
                calibration=features.get("calibration") if isinstance(features.get("calibration"), dict) else None,
            )
            result.details.update(
                {
                    "knowledge_point": knowledge_point,
                    "topic_level": topic_level_code,
                    "level_source": level_source or "knowledge_anchor",
                    "anchor_evidence": anchor_evidence,
                    "fallback_used": features.get("fallback_used") in (1, "1", True),
                }
            )
            if local_variant_calibration:
                result.details["local_variant_calibration"] = local_variant_calibration
                result.details["variant_signal_group"] = local_variant_calibration.get(
                    "variant_signal_group",
                    "",
                )
                result.details["upshift_reason"] = local_variant_calibration.get("reason", "")
                result.details["previous_topic_level"] = local_variant_calibration.get(
                    "previous_level",
                    "",
                )
                result.details["calibrated_topic_level"] = local_variant_calibration.get(
                    "calibrated_level",
                    local_variant_calibration.get("topic_level", ""),
                )
            for key in ("reference_matches", "fallback_confidence", "fallback_error"):
                if features.get(key) not in ("", None, [], {}):
                    result.details[key] = features.get(key)
            if knowledge_point:
                result.evidence = (
                    f"{result.level_label}：知识点“{knowledge_point}”内定位为 "
                    f"{topic_level_code}。{evidence_summary}"
                )
            return result

        strategy_role = _normalize_choice(features.get("strategy_role"), STRATEGY_ROLE_VALUES)
        template_fit = _normalize_choice(features.get("template_fit"), TEMPLATE_FIT_VALUES)
        breakthrough_type = _normalize_choice(
            features.get("breakthrough_type"),
            BREAKTHROUGH_TYPE_VALUES,
        )
        strategy_shift_count = _normalize_choice(
            features.get("strategy_shift_count"),
            STRATEGY_SHIFT_COUNT_VALUES,
        )
        construction_requirement = _normalize_choice(
            features.get("construction_requirement"),
            CONSTRUCTION_REQUIREMENT_VALUES,
        )
        exploration_space = _normalize_choice(
            features.get("exploration_space"),
            EXPLORATION_SPACE_VALUES,
        )
        representation_reframe = _normalize_choice(
            features.get("representation_reframe"),
            REPRESENTATION_REFRAME_VALUES,
        )
        transfer_distance = _normalize_choice(
            features.get("transfer_distance"),
            TRANSFER_DISTANCE_VALUES,
        )
        path_openness = _normalize_choice(
            features.get("path_openness"),
            PATH_OPENNESS_VALUES,
        )
        dead_end_risk = _normalize_choice(features.get("dead_end_risk"), DEAD_END_RISK_VALUES)
        global_strategy_required = _normalize_zero_one(
            features.get("global_strategy_required")
        )
        image_dependency = _normalize_choice(
            features.get("image_dependency"),
            IMAGE_DEPENDENCY_VALUES,
        )
        evidence_summary = str(features.get("evidence_summary", "")).strip()
        calibration = features.get("calibration", {})

        required_values = [
            strategy_role,
            template_fit,
            breakthrough_type,
            strategy_shift_count,
            construction_requirement,
            exploration_space,
            representation_reframe,
            transfer_distance,
            path_openness,
            dead_end_risk,
            image_dependency,
            evidence_summary,
        ]
        if any(value in ("", None) for value in required_values) or global_strategy_required is None:
            return self._invalid_score("dim4 关键策略创新事实不完整，无法自动判级。")

        if strategy_role != "core":
            return self._invalid_score("该题未满足 dim4 的核心策略突破门槛。")

        reference_level_code = self._normalize_level_code(features.get("reference_calibrated_level"))
        if reference_level_code:
            return self._build_score(
                reference_level_code,
                evidence_summary,
                calibration=calibration if isinstance(calibration, dict) else None,
                calibrated=True,
            )

        strategy_shift_rank = _shift_rank(strategy_shift_count)

        if (
            breakthrough_type == "exploratory_search"
            and exploration_space in {"branched", "open"}
            and global_strategy_required == 1
        ) or (
            template_fit == "non_routine"
            and strategy_shift_rank >= 3
            and path_openness in {"multiple_paths", "multiple_answers"}
        ) or (
            transfer_distance == "far"
            and representation_reframe == "creative"
            and dead_end_risk == "high"
        ):
            return self._build_score("L5", evidence_summary, calibration=calibration if isinstance(calibration, dict) else None)

        if (
            breakthrough_type in {"constructive", "exploratory_search"}
            and strategy_shift_rank >= 2
        ) or (
            template_fit == "non_routine"
            and representation_reframe in {"structural", "creative"}
        ) or (
            construction_requirement == "custom_construction"
        ) or (
            exploration_space == "branched"
            and dead_end_risk in {"medium", "high"}
        ) or (
            global_strategy_required == 1
            and transfer_distance == "far"
        ) or (
            template_fit == "reframed"
            and (
                strategy_shift_rank >= 2
                or construction_requirement == "case_construction"
                or path_openness == "multiple_paths"
                or dead_end_risk == "high"
            )
        ) or (
            representation_reframe == "structural"
            and path_openness == "multiple_paths"
        ):
            return self._build_score("L4", evidence_summary, calibration=calibration if isinstance(calibration, dict) else None)

        if (
            breakthrough_type in {"local_trick", "strategy_shift"}
        ) or (
            template_fit == "reframed"
        ) or (
            strategy_shift_rank == 1
        ) or (
            construction_requirement == "case_construction"
        ) or (
            representation_reframe == "structural"
        ) or (
            transfer_distance == "medium"
        ) or (
            exploration_space == "bounded"
            and (
                template_fit in {"adapted", "reframed"}
                or path_openness == "multiple_paths"
                or dead_end_risk == "medium"
            )
        ):
            return self._build_score("L3", evidence_summary, calibration=calibration if isinstance(calibration, dict) else None)

        if (
            template_fit == "adapted"
        ) or (
            construction_requirement == "simple_setup"
        ) or (
            representation_reframe == "minor"
        ) or (
            exploration_space == "bounded"
        ) or (
            dead_end_risk == "medium"
        ):
            return self._build_score("L2", evidence_summary, calibration=calibration if isinstance(calibration, dict) else None)

        return self._build_score("L1", evidence_summary, calibration=calibration if isinstance(calibration, dict) else None)
