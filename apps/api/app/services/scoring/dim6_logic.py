"""
dim6 logic-chain burden scorer.

The scorer consumes normalized logic facts and maps them to
L1-L5 fixed representative scores.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.services.scoring.base import BaseDimensionScorer, DimensionScore

REASONING_ROLE_VALUES = {"none", "supporting", "core"}
CHAIN_SPAN_VALUES = {"1", "2", "3-4", "5+"}
HIDDEN_DEPENDENCY_VALUES = {"none", "local", "cross_condition", "global"}
BRANCH_CONTROL_VALUES = {"none", "explicit_cases", "multi_branch"}
REVERSIBILITY_VALUES = {"none", "backward", "bidirectional"}
VERIFICATION_REQUIREMENT_VALUES = {
    "none",
    "result_check",
    "constraint_backcheck",
    "full_consistency",
}
ABSTRACTION_BRIDGE_COUNT_VALUES = {"0", "1", "2", "3+"}
CONSTRAINT_COUPLING_VALUES = {"none", "single", "coupled", "nested"}
CONCLUSION_STABILITY_VALUES = {"direct", "edge_sensitive", "exhaustive"}
LOGIC_STRUCTURE_TYPE_VALUES = {
    "work_rate_chain",
    "queue_growth_chain",
    "multi_stage_state_change",
    "percentage_base_shift_chain",
    "travel_meeting_chasing_chain",
    "cyclic_schedule_chain",
    "reverse_process_chain",
    "bounded_case_enumeration",
    "optimization_comparison",
    "global_constraint_system",
    "periodic_sequence_position",
    "shared_variable_coupling",
}
STATE_TRANSITION_COUNT_VALUES = {"0", "1", "2", "3+"}
CASE_COUNT_BAND_VALUES = {"none", "2", "3-5", "6+"}
BACKTRACK_DEPTH_VALUES = {"0", "1", "2", "3+"}
CONSISTENCY_CONSTRAINT_COUNT_VALUES = {"0", "1", "2-3", "4+"}
PHASE_COUNT_BAND_VALUES = {"1", "2", "3-4", "5+"}
OPTIMIZATION_REQUIREMENT_VALUES = {"none", "bounded_choice", "global_minmax"}

DIM6_LEVELS = {
    "L1": {"score": 2.0, "level": 1, "label": "L1 直接串联"},
    "L2": {"score": 4.0, "level": 2, "label": "L2 局部推演"},
    "L3": {"score": 6.0, "level": 3, "label": "L3 多步联结"},
    "L4": {"score": 8.0, "level": 4, "label": "L4 分支与回查"},
    "L5": {"score": 9.5, "level": 5, "label": "L5 高阶收束"},
}


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


def _abstraction_rank(value: str) -> int:
    return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(value, -1)


def _band_rank(value: str, mapping: Dict[str, int]) -> int:
    return mapping.get(value, -1)


class Dim6LogicScorer(BaseDimensionScorer):
    DIMENSION_CODE = "dim6"
    DIMENSION_NAME = "逻辑链条"

    def __init__(self):
        super().__init__(config=None)

    def _build_score(
        self,
        level_code: str,
        evidence_summary: str,
        normalized_details: Dict[str, Any] | None = None,
    ) -> DimensionScore:
        level = DIM6_LEVELS[level_code]
        details = {"status": "applicable", "dim6_level": level_code}
        if normalized_details:
            details.update(normalized_details)
        return DimensionScore(
            dimension_code=self.DIMENSION_CODE,
            score=level["score"],
            level=level["level"],
            level_label=level["label"],
            evidence=f"{level['label']}：{evidence_summary}",
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
            details={"status": "not_applicable", "dim6_level": "N/A"},
        )

    def _calculate_score(self, features: Dict[str, Any]) -> DimensionScore:
        reasoning_role = _normalize_choice(features.get("reasoning_role"), REASONING_ROLE_VALUES)
        chain_span = _normalize_choice(features.get("chain_span"), CHAIN_SPAN_VALUES)
        hidden_dependency = _normalize_choice(
            features.get("hidden_dependency"),
            HIDDEN_DEPENDENCY_VALUES,
        )
        branch_control = _normalize_choice(features.get("branch_control"), BRANCH_CONTROL_VALUES)
        reversibility = _normalize_choice(features.get("reversibility"), REVERSIBILITY_VALUES)
        verification_requirement = _normalize_choice(
            features.get("verification_requirement"),
            VERIFICATION_REQUIREMENT_VALUES,
        )
        abstraction_bridge_count = _normalize_choice(
            features.get("abstraction_bridge_count"),
            ABSTRACTION_BRIDGE_COUNT_VALUES,
        )
        constraint_coupling = _normalize_choice(
            features.get("constraint_coupling"),
            CONSTRAINT_COUPLING_VALUES,
        )
        global_consistency_required = _normalize_zero_one(
            features.get("global_consistency_required")
        )
        conclusion_stability = _normalize_choice(
            features.get("conclusion_stability"),
            CONCLUSION_STABILITY_VALUES,
        )
        logic_structure_types = _normalize_choice_list(
            features.get("logic_structure_types"),
            LOGIC_STRUCTURE_TYPE_VALUES,
        )
        state_transition_count = _normalize_choice(
            features.get("state_transition_count"),
            STATE_TRANSITION_COUNT_VALUES,
        )
        case_count_band = _normalize_choice(features.get("case_count_band"), CASE_COUNT_BAND_VALUES)
        backtrack_depth = _normalize_choice(features.get("backtrack_depth"), BACKTRACK_DEPTH_VALUES)
        consistency_constraint_count = _normalize_choice(
            features.get("consistency_constraint_count"),
            CONSISTENCY_CONSTRAINT_COUNT_VALUES,
        )
        phase_count_band = _normalize_choice(features.get("phase_count_band"), PHASE_COUNT_BAND_VALUES)
        periodic_cycle_dependency = _normalize_zero_one(features.get("periodic_cycle_dependency"))
        optimization_requirement = _normalize_choice(
            features.get("optimization_requirement"),
            OPTIMIZATION_REQUIREMENT_VALUES,
        )
        evidence_summary = str(features.get("evidence_summary", "")).strip()

        required_values = [
            reasoning_role,
            chain_span,
            hidden_dependency,
            branch_control,
            reversibility,
            verification_requirement,
            abstraction_bridge_count,
            constraint_coupling,
            conclusion_stability,
            evidence_summary,
        ]
        if any(value in ("", None) for value in required_values) or global_consistency_required is None:
            return self._invalid_score("dim6 关键逻辑事实不完整，无法自动判级。")

        if reasoning_role != "core":
            return self._invalid_score("该题未满足 dim6 的核心逻辑推进门槛。")

        abstraction_rank = _abstraction_rank(abstraction_bridge_count)
        state_rank = _band_rank(state_transition_count, {"0": 0, "1": 1, "2": 2, "3+": 3})
        case_rank = _band_rank(case_count_band, {"none": 0, "2": 2, "3-5": 3, "6+": 6})
        backtrack_rank = _band_rank(backtrack_depth, {"0": 0, "1": 1, "2": 2, "3+": 3})
        consistency_rank = _band_rank(
            consistency_constraint_count,
            {"0": 0, "1": 1, "2-3": 2, "4+": 4},
        )
        phase_rank = _band_rank(phase_count_band, {"1": 1, "2": 2, "3-4": 3, "5+": 5})
        structures = set(logic_structure_types)
        normalized_details = {
            "reasoning_role": reasoning_role,
            "chain_span": chain_span,
            "hidden_dependency": hidden_dependency,
            "branch_control": branch_control,
            "reversibility": reversibility,
            "verification_requirement": verification_requirement,
            "abstraction_bridge_count": abstraction_bridge_count,
            "constraint_coupling": constraint_coupling,
            "global_consistency_required": global_consistency_required,
            "conclusion_stability": conclusion_stability,
            "logic_structure_types": logic_structure_types,
            "state_transition_count": state_transition_count or "0",
            "case_count_band": case_count_band or "none",
            "backtrack_depth": backtrack_depth or "0",
            "consistency_constraint_count": consistency_constraint_count or "0",
            "phase_count_band": phase_count_band or "1",
            "periodic_cycle_dependency": 0
            if periodic_cycle_dependency is None
            else periodic_cycle_dependency,
            "optimization_requirement": optimization_requirement or "none",
            "evidence_summary": evidence_summary,
        }

        if (
            branch_control == "multi_branch"
            and hidden_dependency == "global"
            and global_consistency_required == 1
        ) or (
            chain_span == "5+"
            and constraint_coupling == "nested"
            and verification_requirement == "full_consistency"
        ) or (
            reversibility == "bidirectional"
            and abstraction_rank >= 3
            and conclusion_stability == "exhaustive"
        ) or (
            "global_constraint_system" in structures
            and consistency_rank >= 4
            and (
                constraint_coupling == "nested"
                or global_consistency_required == 1
                or verification_requirement == "full_consistency"
            )
        ) or (
            backtrack_rank >= 3
            and (
                constraint_coupling == "nested"
                or state_rank >= 3
                or "reverse_process_chain" in structures
            )
        ) or (
            case_rank >= 6
            and (
                verification_requirement == "full_consistency"
                or conclusion_stability == "exhaustive"
                or optimization_requirement == "global_minmax"
            )
        ):
            return self._build_score("L5", evidence_summary, normalized_details)

        if (
            branch_control in {"explicit_cases", "multi_branch"}
            and verification_requirement in {"constraint_backcheck", "full_consistency"}
        ) or (
            branch_control == "multi_branch"
            and constraint_coupling in {"coupled", "nested"}
        ) or (
            hidden_dependency == "global"
            and chain_span in {"3-4", "5+"}
        ) or (
            reversibility in {"backward", "bidirectional"}
            and chain_span in {"3-4", "5+"}
        ) or (
            "queue_growth_chain" in structures
        ) or (
            "travel_meeting_chasing_chain" in structures
            and (state_rank >= 2 or hidden_dependency in {"cross_condition", "global"})
        ) or (
            "cyclic_schedule_chain" in structures
            and (phase_rank >= 3 or periodic_cycle_dependency == 1)
        ) or (
            "optimization_comparison" in structures
            and optimization_requirement in {"bounded_choice", "global_minmax"}
        ) or (
            "multi_stage_state_change" in structures
            and state_rank >= 3
        ) or (
            "percentage_base_shift_chain" in structures
            and state_rank >= 2
        ) or (
            "reverse_process_chain" in structures
            and backtrack_rank >= 2
        ) or (
            "bounded_case_enumeration" in structures
            and (case_rank >= 3 or verification_requirement in {"constraint_backcheck", "full_consistency"})
        ) or (
            "global_constraint_system" in structures
            and consistency_rank >= 2
        ) or (
            "shared_variable_coupling" in structures
            and consistency_rank >= 2
            and (state_rank >= 2 or phase_rank >= 3)
        ) or (
            "work_rate_chain" in structures
            and (phase_rank >= 3 or state_rank >= 2 or consistency_rank >= 2)
        ):
            return self._build_score("L4", evidence_summary, normalized_details)

        if (
            branch_control == "explicit_cases"
        ) or (
            hidden_dependency == "cross_condition"
        ) or (
            verification_requirement in {"constraint_backcheck", "full_consistency"}
        ) or (
            abstraction_rank >= 2
        ) or (
            chain_span == "3-4"
        ) or (
            constraint_coupling == "coupled"
        ) or (
            structures
            & {
                "work_rate_chain",
                "percentage_base_shift_chain",
                "travel_meeting_chasing_chain",
                "reverse_process_chain",
                "periodic_sequence_position",
                "shared_variable_coupling",
                "multi_stage_state_change",
            }
        ) or (
            state_rank >= 2
        ) or (
            backtrack_rank >= 1
        ) or (
            consistency_rank >= 2
        ) or (
            phase_rank >= 3
        ) or (
            periodic_cycle_dependency == 1
        ):
            return self._build_score("L3", evidence_summary, normalized_details)

        if (
            chain_span == "2"
        ) or (
            hidden_dependency == "local"
        ) or (
            reversibility == "backward"
        ) or (
            verification_requirement == "result_check"
        ) or (
            abstraction_rank == 1
        ) or (
            conclusion_stability == "edge_sensitive"
        ) or (
            state_rank == 1
        ) or (
            consistency_rank == 1
        ) or (
            phase_rank == 2
        ):
            return self._build_score("L2", evidence_summary, normalized_details)

        return self._build_score("L1", evidence_summary, normalized_details)
