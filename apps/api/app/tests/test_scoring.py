"""
六维评分引擎完整单元测试

重点覆盖各维度本地规则，以及整卷题级/结构化聚合。
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services.report.report_service import ReportService
from app.services.ocr.base import ParseAudit, ParsedQuestion, QuestionType
from app.services.parser.ai_parser import AIParser
from app.services.parser.reference_standard import ReferenceEntry, WorkbookReferenceStandard
from app.services.scoring.dim1_applicability import (
    evaluate_dim1_applicability,
    is_bare_calculation_fill_blank,
)
from app.services.scoring.dim2_applicability import (
    build_dim2_visual_fallback_facts,
    evaluate_dim2_applicability,
)
from app.services.scoring.dim3_applicability import (
    enrich_dim3_text_length_facts,
    evaluate_dim3_applicability,
)
from app.services.scoring.dim4_applicability import evaluate_dim4_applicability
from app.services.scoring.dim6_applicability import evaluate_dim6_applicability
from app.services.scoring.dim1_computation import Dim1ComputationScorer
from app.services.scoring.dim2_spatial import Dim2SpatialScorer
from app.services.scoring.dim3_information import Dim3InformationScorer
from app.services.scoring.dim4_innovation import Dim4InnovationScorer
from app.services.scoring.dim4_topic_levels import classify_dim4_topic_level
from app.services.scoring.dim5_knowledge import Dim5KnowledgeScorer
from app.services.scoring.dim6_logic import Dim6LogicScorer
from app.services.scoring.paper_aggregator import (
    PaperAggregator,
    QuestionDimensionScore,
)


class TestDim1ComputationScorer:
    """测试维度1：数学运算评分器"""

    @pytest.fixture
    def scorer(self):
        return Dim1ComputationScorer()

    @staticmethod
    def _pure_features(**overrides):
        features = {
            "task_form": "explicit",
            "calc_role": "core",
            "calc_bucket": "pure_calculation",
            "step_chain": "1",
            "number_mix": "plain",
            "routine_transform_count": "0",
            "structural_method": "none",
            "global_view_required": 0,
            "error_pressure": "low",
            "calc_subtype": "arithmetic",
            "structure_patterns": [],
            "term_count_band": "1-2",
            "symbolic_dependency": "none",
            "evidence_summary": "纯计算题。",
            "evidence_tags": ["计算"],
        }
        features.update(overrides)
        return features

    def test_l1_direct_computation(self, scorer):
        features = {
            "task_form": "explicit",
            "calc_role": "core",
            "step_chain": "1",
            "number_mix": "plain",
            "routine_transform_count": "0",
            "structural_method": "none",
            "global_view_required": 0,
            "error_pressure": "low",
            "evidence_summary": "仅需完成一次直接整数运算。",
            "evidence_tags": ["整数四则"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 2.0
        assert result.level == 1
        assert result.level_label == "L1 直接运算"

    def test_pure_training_anchor_l2_decimal_mixed_operation(self, scorer):
        result = scorer.score(
            self._pure_features(
                step_chain="2",
                number_mix="standard",
                evidence_summary="类似 18÷1.5＋0.5×24，需要完成常规两步小数计算。",
                evidence_tags=["小数混合运算"],
            )
        )

        assert result.score == 4.0
        assert result.level_label == "L2 常规运算"
        assert result.details["calc_subtype"] == "arithmetic"

    def test_pure_training_anchor_l3_grouping_cancellation(self, scorer):
        result = scorer.score(
            self._pure_features(
                step_chain="3-4",
                number_mix="standard",
                routine_transform_count="1",
                structural_method="shortcut",
                structure_patterns=["grouping"],
                term_count_band="3-5",
                evidence_summary="类似 22.4－8.14－1.86＋7.6，需要先分组凑整。",
                evidence_tags=["分组凑整"],
            )
        )

        assert result.score == 6.0
        assert result.level_label == "L3 结构变形运算"
        assert result.details["structure_patterns"] == ["grouping"]

    def test_pure_training_anchor_l4_common_factor_decimal_scaling(self, scorer):
        result = scorer.score(
            self._pure_features(
                step_chain="3-4",
                number_mix="mixed",
                routine_transform_count="2",
                structural_method="shortcut",
                structure_patterns=["common_factor", "decimal_scaling"],
                term_count_band="3-5",
                evidence_summary="类似 19.98×37 + 199.8×2.3 + 9.99×80，需要识别小数缩放并提公因数。",
                evidence_tags=["小数缩放", "提公因数"],
            )
        )

        assert result.score == 8.0
        assert result.level_label == "L4 复合巧算"

    def test_pure_training_anchor_l3_factorial_cancellation(self, scorer):
        result = scorer.score(
            self._pure_features(
                step_chain="2",
                number_mix="symbolic",
                routine_transform_count="1",
                calc_subtype="factorial_ratio",
                structure_patterns=["factorial_cancellation"],
                evidence_summary="类似 100! / 98!，需要展开相邻阶乘并约分。",
                evidence_tags=["阶乘约分"],
            )
        )

        assert result.score == 6.0
        assert result.level_label == "L3 结构变形运算"

    def test_pure_training_anchor_l4_nested_defined_operation(self, scorer):
        result = scorer.score(
            self._pure_features(
                step_chain="3-4",
                number_mix="symbolic",
                routine_transform_count="2",
                calc_subtype="defined_operation",
                structure_patterns=["defined_rule_expansion"],
                symbolic_dependency="single_unknown",
                evidence_summary="嵌套定义新运算需要多次展开规则后再计算。",
                evidence_tags=["定义新运算", "嵌套展开"],
            )
        )

        assert result.score == 8.0
        assert result.level_label == "L4 复合巧算"

    def test_pure_training_anchor_l4_nested_fraction(self, scorer):
        result = scorer.score(
            self._pure_features(
                step_chain="5+",
                number_mix="mixed",
                routine_transform_count="2",
                calc_subtype="nested_fraction",
                structure_patterns=["continued_fraction"],
                evidence_summary="繁分式需要逐层化简并控制分数运算。",
                evidence_tags=["繁分式"],
            )
        )

        assert result.score == 8.0
        assert result.level_label == "L4 复合巧算"

    def test_pure_training_anchor_l5_long_telescoping_series(self, scorer):
        result = scorer.score(
            self._pure_features(
                step_chain="5+",
                number_mix="symbolic",
                routine_transform_count="3+",
                structural_method="olympiad",
                global_view_required=1,
                calc_subtype="sequence_series",
                structure_patterns=["telescoping"],
                term_count_band="11+",
                evidence_summary="11 项以上裂项求和需要整体识别相消结构。",
                evidence_tags=["裂项相消", "长链求和"],
            )
        )

        assert result.score == 9.5
        assert result.level_label == "L5 高阶结构巧算"

    def test_l3_structural_shortcut(self, scorer):
        features = {
            "task_form": "explicit",
            "calc_role": "core",
            "step_chain": "3-4",
            "number_mix": "mixed",
            "routine_transform_count": "1",
            "structural_method": "shortcut",
            "global_view_required": 0,
            "error_pressure": "medium",
            "evidence_summary": "需要先分组再凑整完成计算。",
            "evidence_tags": ["分组", "凑整"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 6.0
        assert result.level == 3
        assert result.level_label == "L3 结构变形运算"
        assert result.details["structure_patterns"] == []

    def test_l4_long_mixed_chain(self, scorer):
        features = {
            "task_form": "embedded",
            "calc_role": "core",
            "calc_bucket": "embedded_calculation",
            "step_chain": "5+",
            "number_mix": "mixed",
            "routine_transform_count": "1",
            "structural_method": "none",
            "global_view_required": 0,
            "error_pressure": "high",
            "intermediate_quantity_count": "3+",
            "unit_conversion_count": "1",
            "formula_substitution_count": "1",
            "evidence_summary": "需要完成长链条的混合表示计算。",
            "evidence_tags": ["分数小数混合", "长链计算"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.level == 4
        assert result.level_label == "L4 高负担嵌入计算"
        assert result.details["calc_bucket"] == "embedded_calculation"

    def test_l5_olympiad_structure(self, scorer):
        features = {
            "task_form": "embedded",
            "calc_role": "core",
            "calc_bucket": "embedded_calculation",
            "step_chain": "5+",
            "number_mix": "symbolic",
            "routine_transform_count": "3+",
            "structural_method": "olympiad",
            "global_view_required": 1,
            "error_pressure": "high",
            "intermediate_quantity_count": "3+",
            "unit_conversion_count": "0",
            "formula_substitution_count": "2+",
            "evidence_summary": "需要通过高阶结构化拆项与整体视角完成计算。",
            "evidence_tags": ["裂项相消", "整体代换"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 9.5
        assert result.level == 5
        assert result.level_label == "L5 高阶嵌入计算"
        assert result.details["calc_bucket"] == "embedded_calculation"

    def test_embedded_l2_single_relation_computation(self, scorer):
        features = {
            "task_form": "embedded",
            "calc_role": "core",
            "calc_bucket": "embedded_calculation",
            "step_chain": "2",
            "number_mix": "plain",
            "routine_transform_count": "0",
            "structural_method": "none",
            "global_view_required": 0,
            "error_pressure": "medium",
            "intermediate_quantity_count": "1",
            "unit_conversion_count": "0",
            "formula_substitution_count": "0",
            "evidence_summary": "应用题中需要先列出单位率关系再完成两步常规计算。",
            "evidence_tags": ["单位率", "两步计算"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 4.0
        assert result.level == 2
        assert result.level_label == "L2 常规嵌入计算"
        assert result.details["calc_bucket"] == "embedded_calculation"

    def test_embedded_l3_ratio_and_unit_conversion(self, scorer):
        features = {
            "task_form": "embedded",
            "calc_role": "core",
            "calc_bucket": "embedded_calculation",
            "step_chain": "3-4",
            "number_mix": "mixed",
            "routine_transform_count": "1",
            "structural_method": "none",
            "global_view_required": 0,
            "error_pressure": "medium",
            "intermediate_quantity_count": "2",
            "unit_conversion_count": "1",
            "formula_substitution_count": "1",
            "evidence_summary": "需要先完成比例换算，再用分数和百分数连续计算。",
            "evidence_tags": ["比例换算", "混合数式"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 6.0
        assert result.level == 3
        assert result.level_label == "L3 多步嵌入计算"

    def test_embedded_l4_compound_geometry_cost(self, scorer):
        features = {
            "task_form": "embedded",
            "calc_role": "core",
            "calc_bucket": "embedded_calculation",
            "step_chain": "5+",
            "number_mix": "mixed",
            "routine_transform_count": "2",
            "structural_method": "none",
            "global_view_required": 0,
            "error_pressure": "high",
            "intermediate_quantity_count": "3+",
            "unit_conversion_count": "2+",
            "formula_substitution_count": "2+",
            "evidence_summary": "需要连续计算表面积、容积、百分比水量和两项费用。",
            "evidence_tags": ["复合几何计算", "多中间量"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.level == 4
        assert result.level_label == "L4 高负担嵌入计算"

    def test_invalid_features_mark_not_applicable(self, scorer):
        result = scorer.score({"task_form": "explicit", "calc_role": "core"})

        assert result.applicable is False
        assert result.score == 0.0
        assert "关键计算事实不完整" in result.evidence

    def test_not_applicable_short_circuit(self, scorer):
        result = scorer.score({"not_applicable": True})

        assert result.applicable is False
        assert result.score == 0.0


class TestDim1Applicability:
    """测试 dim1 后端适用性门控"""

    def test_lightweight_direct_calculation_is_not_applicable(self):
        result = evaluate_dim1_applicability(
            "calculation",
            "计算：3.2 × 0.5",
            {
                "task_form": "explicit",
                "calc_role": "core",
                "step_chain": "1",
                "number_mix": "plain",
                "routine_transform_count": "0",
                "structural_method": "none",
                "global_view_required": 0,
                "error_pressure": "low",
                "evidence_summary": "直接计算得数。",
            },
            llm_confidence=0.92,
        )

        assert result["status"] == "not_applicable"
        assert "轻量直接计算" in result["reason"]

    def test_equation_concept_identification_is_not_pure_dim1(self):
        result = evaluate_dim1_applicability(
            "choice",
            "下列式子中，是方程的是：x+2>3，x-6，x=0，3+4=7。",
            {
                "task_form": "embedded",
                "calc_role": "none",
                "step_chain": "1",
                "number_mix": "plain",
                "routine_transform_count": "0",
                "structural_method": "none",
                "global_view_required": 0,
                "error_pressure": "low",
                "evidence_summary": "题目要求辨析方程概念，不要求执行计算。",
            },
            llm_confidence=0.93,
        )

        assert result["status"] == "not_applicable"
        assert "核心计算执行负担" in result["reason"]

    def test_lightweight_bare_calculation_fill_blank_is_not_applicable(self):
        assert is_bare_calculation_fill_blank("3.2 × 0.5 = __") is True

        result = evaluate_dim1_applicability(
            "fill_blank",
            "3.2 × 0.5 = __",
            {
                "task_form": "explicit",
                "calc_role": "core",
                "step_chain": "1",
                "number_mix": "plain",
                "routine_transform_count": "0",
                "structural_method": "none",
                "global_view_required": 0,
                "error_pressure": "low",
                "evidence_summary": "裸算式填空。",
            },
            llm_confidence=0.88,
        )

        assert result["status"] == "not_applicable"
        assert "轻量直接计算" in result["reason"]

    def test_application_question_with_core_computation_is_applicable(self):
        result = evaluate_dim1_applicability(
            "application",
            "一辆汽车 3 小时行了 180 千米，平均每小时行多少千米？",
            {
                "task_form": "embedded",
                "calc_role": "core",
                "step_chain": "2",
                "number_mix": "plain",
                "routine_transform_count": "0",
                "structural_method": "none",
                "global_view_required": 0,
                "error_pressure": "low",
                "evidence_summary": "核心门槛是单位率计算。",
            },
            llm_confidence=0.83,
        )

        assert result["status"] == "applicable"

    @pytest.mark.parametrize(
        "override",
        [
            {"step_chain": "2"},
            {"number_mix": "standard"},
            {"number_mix": "mixed"},
            {"routine_transform_count": "1"},
            {"structural_method": "shortcut"},
            {"global_view_required": 1},
            {"error_pressure": "medium"},
        ],
    )
    def test_non_lightweight_core_computation_remains_applicable(self, override):
        feature = {
            "task_form": "explicit",
            "calc_role": "core",
            "step_chain": "1",
            "number_mix": "plain",
            "routine_transform_count": "0",
            "structural_method": "none",
            "global_view_required": 0,
            "error_pressure": "low",
            "evidence_summary": "计算执行负担超过轻量直接计算。",
        }
        feature.update(override)

        result = evaluate_dim1_applicability(
            "calculation",
            "计算：12.5 + 7.5",
            feature,
            llm_confidence=0.9,
        )

        assert result["status"] == "applicable"

    def test_supporting_embedded_computation_is_not_applicable(self):
        result = evaluate_dim1_applicability(
            "solution",
            "观察图形规律，判断第10个图形中黑点个数。",
            {
                "task_form": "embedded",
                "calc_role": "supporting",
                "step_chain": "1",
                "number_mix": "plain",
                "routine_transform_count": "0",
                "structural_method": "none",
                "global_view_required": 0,
                "error_pressure": "low",
                "evidence_summary": "可能需要数点，但核心在规律发现。",
            },
            llm_confidence=0.81,
        )

        assert result["status"] == "not_applicable"

    def test_missing_dim1_facts_go_to_review(self):
        result = evaluate_dim1_applicability(
            "application",
            "求一个数的 25%。",
            {
                "task_form": "embedded",
                "calc_role": "core",
                "evidence_summary": "缺少完整计算事实。",
            },
            llm_confidence=0.86,
        )

        assert result["status"] == "review"
        assert any("关键计算事实字段" in item for item in result["warnings"])

    def test_explicit_calculation_with_supporting_role_goes_to_review(self):
        result = evaluate_dim1_applicability(
            "calculation",
            "计算：12.5 + 7.5",
            {
                "task_form": "explicit",
                "calc_role": "supporting",
                "step_chain": "1",
                "number_mix": "plain",
                "routine_transform_count": "0",
                "structural_method": "none",
                "global_view_required": 0,
                "error_pressure": "low",
                "evidence_summary": "题面显式要求计算。",
            },
            llm_confidence=0.9,
        )

        assert result["status"] == "review"
        assert any("冲突" in item or "显式计算题" in item for item in result["warnings"])

    def test_low_confidence_goes_to_review(self):
        result = evaluate_dim1_applicability(
            "calculation",
            "计算：3.2 × 0.5",
            {
                "task_form": "explicit",
                "calc_role": "core",
                "step_chain": "1",
                "number_mix": "plain",
                "routine_transform_count": "0",
                "structural_method": "none",
                "global_view_required": 0,
                "error_pressure": "low",
                "evidence_summary": "直接计算。",
            },
            llm_confidence=0.32,
        )

        assert result["status"] == "review"
        assert any("置信度" in item for item in result["warnings"])


class TestDim2SpatialScorer:
    """测试维度2：几何直观与空间想象评分器"""

    @pytest.fixture
    def scorer(self):
        return Dim2SpatialScorer()

    @staticmethod
    def _dim2_features(**overrides):
        features = {
            "task_form": "geometry_embedded",
            "spatial_role": "core",
            "figure_complexity": "basic_2d",
            "relation_hops": "2",
            "hidden_relation_count": "0",
            "visual_operation_count": "1",
            "structural_visual_method": "none",
            "measurement_dependency": "direct",
            "global_view_required": 0,
            "image_dependency": "helpful",
            "geometry_model_types": [],
            "geometry_model_count": "0",
            "model_recognition_role": "none",
            "area_relation_chain": "none",
            "model_combination_complexity": "none",
            "evidence_summary": "需要读取图形关系。",
            "evidence_tags": ["图形关系"],
        }
        features.update(overrides)
        return features

    def test_not_applicable_short_circuit(self, scorer):
        result = scorer.score({"not_applicable": True})

        assert result.applicable is False
        assert result.score == 0.0
        assert "不适用" in result.evidence

    def test_l1_direct_visual_reading(self, scorer):
        features = {
            "task_form": "explicit_visual",
            "spatial_role": "core",
            "figure_complexity": "basic_2d",
            "relation_hops": "1",
            "hidden_relation_count": "0",
            "visual_operation_count": "0",
            "structural_visual_method": "none",
            "measurement_dependency": "direct",
            "global_view_required": 0,
            "image_dependency": "helpful",
            "evidence_summary": "只需从图中直接读取一个显式关系。",
            "evidence_tags": ["读图", "显式关系"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 2.0
        assert result.level == 1

    @pytest.mark.parametrize(
        "model_type",
        [
            "butterfly_area",
            "swallowtail_area",
            "half_area",
            "equal_height_area",
            "shared_base_area",
            "bird_head_sandglass",
        ],
    )
    def test_single_stable_area_model_scores_l3(self, scorer, model_type):
        result = scorer.score(
            self._dim2_features(
                geometry_model_types=[model_type],
                geometry_model_count="1",
                model_recognition_role="core",
                area_relation_chain="single",
                model_combination_complexity="single_model",
                evidence_summary="核心门槛是识别小学几何面积模型，而不是直接套公式。",
            )
        )

        assert result.applicable is True
        assert result.score == 6.0
        assert result.level == 3
        assert result.details["geometry_model_types"] == [model_type]

    def test_area_model_plus_cut_and_fill_scores_l4(self, scorer):
        result = scorer.score(
            self._dim2_features(
                figure_complexity="composite_2d",
                relation_hops="3-4",
                hidden_relation_count="1",
                structural_visual_method="decomposition",
                measurement_dependency="inferred",
                geometry_model_types=["butterfly_area", "cut_and_fill"],
                geometry_model_count="2",
                model_recognition_role="core",
                area_relation_chain="multi",
                model_combination_complexity="model_plus_operation",
                evidence_summary="需要先识别蝴蝶面积关系，再结合割补重组阴影面积。",
            )
        )

        assert result.applicable is True
        assert result.score == 8.0
        assert result.level == 4

    def test_nested_area_ratio_model_scores_l5(self, scorer):
        result = scorer.score(
            self._dim2_features(
                figure_complexity="composite_2d",
                relation_hops="3-4",
                hidden_relation_count="2+",
                visual_operation_count="2",
                structural_visual_method="decomposition",
                measurement_dependency="inferred",
                global_view_required=1,
                geometry_model_types=["butterfly_area", "swallowtail_area", "area_ratio_chain"],
                geometry_model_count="3+",
                model_recognition_role="core",
                area_relation_chain="nested",
                model_combination_complexity="nested_model",
                evidence_summary="需要在多个面积模型之间嵌套反推面积比。",
            )
        )

        assert result.applicable is True
        assert result.score == 9.5
        assert result.level == 5

    def test_direct_formula_geometry_without_model_stays_low(self, scorer):
        result = scorer.score(
            self._dim2_features(
                task_form="text_only_geometry",
                figure_complexity="basic_2d",
                relation_hops="1",
                hidden_relation_count="0",
                visual_operation_count="0",
                structural_visual_method="none",
                measurement_dependency="direct",
                image_dependency="none",
                evidence_summary="只需直接代入长方形面积公式。",
            )
        )

        assert result.applicable is True
        assert result.level == 1

    def test_basic_formula_model_does_not_raise_direct_geometry(self, scorer):
        result = scorer.score(
            self._dim2_features(
                task_form="text_only_geometry",
                figure_complexity="basic_2d",
                relation_hops="1",
                hidden_relation_count="0",
                visual_operation_count="0",
                structural_visual_method="none",
                measurement_dependency="direct",
                image_dependency="none",
                geometry_model_types=["basic_area_formula"],
                geometry_model_count="1",
                model_recognition_role="core",
                area_relation_chain="none",
                model_combination_complexity="single_model",
                evidence_summary="知识树中的直线形基本公式直接代入，不构成高负担图形模型识别。",
            )
        )

        assert result.applicable is True
        assert result.level == 1

    @pytest.mark.parametrize(
        "model_type",
        [
            "grid_cut_fill",
            "length_translation",
            "directed_length",
            "angle_chasing_triangle",
            "geometric_counting",
        ],
    )
    def test_knowledge_tree_mid_geometry_patterns_score_l3(self, scorer, model_type):
        result = scorer.score(
            self._dim2_features(
                geometry_model_types=[model_type],
                geometry_model_count="1",
                model_recognition_role="core",
                area_relation_chain="single",
                model_combination_complexity="single_model",
                evidence_summary="知识树几何模块中的中等图形关系模型需要识别后再计算。",
            )
        )

        assert result.applicable is True
        assert result.level == 3

    @pytest.mark.parametrize(
        "model_type",
        [
            "rolling_rotation",
            "water_displacement",
            "surface_three_view",
            "net_cut_join",
            "solid_cut_join",
            "angle_chasing_polygon",
        ],
    )
    def test_knowledge_tree_high_geometry_patterns_score_l4(self, scorer, model_type):
        result = scorer.score(
            self._dim2_features(
                figure_complexity="composite_2d",
                relation_hops="3-4",
                hidden_relation_count="1",
                measurement_dependency="inferred",
                geometry_model_types=[model_type],
                geometry_model_count="1",
                model_recognition_role="core",
                area_relation_chain="single",
                model_combination_complexity="single_model",
                evidence_summary="知识树几何模块中的高负担模型需要跨图形关系重组。",
            )
        )

        assert result.applicable is True
        assert result.level == 4

    def test_wmo_like_basic_three_view_projection_scores_l4(self, scorer):
        result = scorer.score(
            self._dim2_features(
                task_form="explicit_visual",
                figure_complexity="solid_3d",
                relation_hops="3-4",
                hidden_relation_count="1",
                visual_operation_count="2",
                structural_visual_method="3d_transform",
                measurement_dependency="none",
                global_view_required=1,
                image_dependency="required",
                geometry_model_types=["surface_three_view"],
                geometry_model_count="1",
                model_recognition_role="core",
                area_relation_chain="none",
                model_combination_complexity="single_model",
                evidence_summary="透明正方体内部点线投影到左视图，核心负担是三维到视图的空间转换。",
            )
        )

        assert result.applicable is True
        assert result.score == 8.0
        assert result.level == 4

    def test_wmo_like_three_view_extreme_construction_scores_l5(self, scorer):
        result = scorer.score(
            self._dim2_features(
                task_form="explicit_visual",
                figure_complexity="net_section_multi_view",
                relation_hops="3-4",
                hidden_relation_count="2+",
                visual_operation_count="3+",
                structural_visual_method="3d_transform",
                measurement_dependency="none",
                global_view_required=1,
                image_dependency="required",
                geometry_model_types=["surface_three_view", "solid_cut_join"],
                geometry_model_count="2",
                model_recognition_role="core",
                area_relation_chain="none",
                model_combination_complexity="multi_model",
                evidence_summary="根据前视图和左视图反推 27 个小正方体的最少最多涂色情况。",
            )
        )

        assert result.applicable is True
        assert result.score == 9.5
        assert result.level == 5

    def test_l3_composite_geometry(self, scorer):
        features = {
            "task_form": "geometry_embedded",
            "spatial_role": "core",
            "figure_complexity": "composite_2d",
            "relation_hops": "3-4",
            "hidden_relation_count": "1",
            "visual_operation_count": "1",
            "structural_visual_method": "decomposition",
            "measurement_dependency": "inferred",
            "global_view_required": 0,
            "image_dependency": "required",
            "evidence_summary": "需要拆分组合图形并推断隐含长度关系。",
            "evidence_tags": ["组合图形", "拆分"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 6.0
        assert result.level == 3

    def test_l4_auxiliary_line_or_transform(self, scorer):
        features = {
            "task_form": "geometry_embedded",
            "spatial_role": "core",
            "figure_complexity": "solid_3d",
            "relation_hops": "3-4",
            "hidden_relation_count": "1",
            "visual_operation_count": "2",
            "structural_visual_method": "auxiliary_line",
            "measurement_dependency": "inferred",
            "global_view_required": 1,
            "image_dependency": "required",
            "evidence_summary": "需要补辅助线并整体重组空间关系。",
            "evidence_tags": ["辅助线", "空间重组"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.level == 4

    def test_l5_high_order_spatial_reconstruction(self, scorer):
        features = {
            "task_form": "explicit_visual",
            "spatial_role": "core",
            "figure_complexity": "net_section_multi_view",
            "relation_hops": "5+",
            "hidden_relation_count": "2+",
            "visual_operation_count": "3+",
            "structural_visual_method": "3d_transform",
            "measurement_dependency": "inferred",
            "global_view_required": 1,
            "image_dependency": "required",
            "evidence_summary": "需要在展开图、截面和多视图之间做高阶空间重构。",
            "evidence_tags": ["展开图", "截面", "多视图"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 9.5
        assert result.level == 5

    def test_invalid_features_mark_not_applicable(self, scorer):
        result = scorer.score({"task_form": "explicit_visual", "spatial_role": "core"})

        assert result.applicable is False
        assert result.score == 0.0


class TestDim2Applicability:
    def test_core_spatial_question_is_applicable(self):
        result = evaluate_dim2_applicability(
            "如图，求组合图形的阴影面积。",
            {
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
                "evidence_summary": "需要拆分图形并读取图中关系。",
                "applicability_confidence": 0.88,
            },
            llm_confidence=0.88,
            parse_audit={"visual_category": "geometry_visual", "image_required_hint": True},
            used_image=True,
        )

        assert result["status"] == "applicable"

    def test_formula_geometry_is_not_applicable(self):
        result = evaluate_dim2_applicability(
            "已知长方形长 8 厘米，宽 5 厘米，求面积。",
            {
                "task_form": "text_only_geometry",
                "spatial_role": "none",
                "figure_complexity": "basic_2d",
                "relation_hops": "1",
                "hidden_relation_count": "0",
                "visual_operation_count": "0",
                "structural_visual_method": "none",
                "measurement_dependency": "direct",
                "global_view_required": 0,
                "image_dependency": "none",
                "evidence_summary": "只需直接代入面积公式。",
                "applicability_confidence": 0.91,
            },
            llm_confidence=0.91,
            parse_audit={"visual_category": "none"},
            used_image=False,
        )

        assert result["status"] == "not_applicable"

    def test_core_geometry_model_is_applicable_even_when_spatial_role_is_supporting(self):
        result = evaluate_dim2_applicability(
            "如图，利用蝴蝶模型求三角形面积比。",
            {
                "task_form": "explicit_visual",
                "spatial_role": "supporting",
                "figure_complexity": "composite_2d",
                "relation_hops": "2",
                "hidden_relation_count": "0",
                "visual_operation_count": "1",
                "structural_visual_method": "none",
                "measurement_dependency": "inferred",
                "global_view_required": 0,
                "image_dependency": "helpful",
                "geometry_model_types": ["butterfly_area"],
                "geometry_model_count": "1",
                "model_recognition_role": "core",
                "area_relation_chain": "single",
                "model_combination_complexity": "single_model",
                "evidence_summary": "需要识别蝴蝶模型才能转出面积比。",
                "applicability_confidence": 0.86,
            },
            llm_confidence=0.86,
            parse_audit={"visual_category": "geometry_visual"},
            used_image=True,
        )

        assert result["status"] == "applicable"

    def test_non_measurement_three_view_task_is_applicable(self):
        result = evaluate_dim2_applicability(
            "透明正方体内部有若干点和线，画出从左面看到的图形。",
            {
                "task_form": "explicit_visual",
                "spatial_role": "core",
                "figure_complexity": "solid_3d",
                "relation_hops": "3-4",
                "hidden_relation_count": "1",
                "visual_operation_count": "2",
                "structural_visual_method": "3d_transform",
                "measurement_dependency": "none",
                "global_view_required": 1,
                "image_dependency": "required",
                "geometry_model_types": ["surface_three_view"],
                "geometry_model_count": "1",
                "model_recognition_role": "core",
                "area_relation_chain": "none",
                "model_combination_complexity": "single_model",
                "evidence_summary": "该题不做度量计算，核心是三维视图投影关系。",
                "applicability_confidence": 0.88,
            },
            llm_confidence=0.88,
            parse_audit={"visual_category": "geometry_3d", "image_required_hint": True},
            used_image=True,
        )

        assert result["status"] == "applicable"

    def test_basic_formula_model_is_not_applicable_when_direct(self):
        result = evaluate_dim2_applicability(
            "已知三角形底 8，高 5，直接求面积。",
            {
                "task_form": "text_only_geometry",
                "spatial_role": "core",
                "figure_complexity": "basic_2d",
                "relation_hops": "1",
                "hidden_relation_count": "0",
                "visual_operation_count": "0",
                "structural_visual_method": "none",
                "measurement_dependency": "direct",
                "global_view_required": 0,
                "image_dependency": "none",
                "geometry_model_types": ["basic_area_formula"],
                "geometry_model_count": "1",
                "model_recognition_role": "core",
                "area_relation_chain": "none",
                "model_combination_complexity": "single_model",
                "evidence_summary": "只需直接代入三角形面积公式。",
                "applicability_confidence": 0.9,
            },
            llm_confidence=0.9,
            parse_audit={"visual_category": "none"},
            used_image=False,
        )

        assert result["status"] == "not_applicable"

    def test_missing_facts_go_to_review(self):
        result = evaluate_dim2_applicability(
            "如图，判断展开图能否折成立方体。",
            {
                "task_form": "explicit_visual",
                "spatial_role": "core",
                "figure_complexity": "net_section_multi_view",
                "evidence_summary": "缺少完整空间事实。",
            },
            llm_confidence=0.82,
            parse_audit={"visual_category": "spatial_3d", "image_required_hint": True},
            used_image=True,
        )

        assert result["status"] == "review"
        assert any("关键空间事实字段" in item for item in result["warnings"])

    def test_required_image_without_stable_image_use_goes_to_review(self):
        result = evaluate_dim2_applicability(
            "如图，求折叠后相对两个面的编号。",
            {
                "task_form": "explicit_visual",
                "spatial_role": "core",
                "figure_complexity": "net_section_multi_view",
                "relation_hops": "3-4",
                "hidden_relation_count": "1",
                "visual_operation_count": "2",
                "structural_visual_method": "3d_transform",
                "measurement_dependency": "inferred",
                "global_view_required": 1,
                "image_dependency": "required",
                "evidence_summary": "核心依赖展开图折叠想象。",
                "applicability_confidence": 0.9,
            },
            llm_confidence=0.9,
            parse_audit={"visual_category": "spatial_3d", "image_required_hint": True},
            used_image=False,
            image_fallback=True,
        )

        assert result["status"] == "review"
        assert any("依赖图片" in item for item in result["warnings"])

    def test_image_cropped_flag_does_not_block_reliable_dim2(self):
        result = evaluate_dim2_applicability(
            "每个小正方体的棱长为2，求露在外面的面积。",
            {
                "task_form": "explicit_visual",
                "spatial_role": "core",
                "figure_complexity": "solid_3d",
                "relation_hops": "3-4",
                "hidden_relation_count": "2+",
                "visual_operation_count": "3+",
                "structural_visual_method": "decomposition",
                "measurement_dependency": "inferred",
                "global_view_required": 1,
                "image_dependency": "required",
                "evidence_summary": "需要从立体图中识别组合体外露面。",
                "applicability_confidence": 0.95,
            },
            llm_confidence=0.95,
            parse_audit={
                "visual_category": "geometry_context",
                "image_cropped": True,
                "block_completeness": 0.75,
            },
            used_image=True,
        )

        assert result["status"] == "applicable"

    def test_low_block_completeness_still_blocks_required_image_dim2(self):
        result = evaluate_dim2_applicability(
            "如图，求阴影面积。",
            {
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
                "evidence_summary": "需要结合图形拆分阴影面积。",
                "applicability_confidence": 0.9,
            },
            llm_confidence=0.9,
            parse_audit={"visual_category": "geometry_visual", "block_completeness": 0.6},
            used_image=True,
        )

        assert result["status"] == "review"
        assert any("完整度" in item for item in result["warnings"])

    def test_short_shadow_prompt_attaches_image(self):
        parser = AIParser(llm_client=SimpleNamespace())
        question = ParsedQuestion(
            question_no="17",
            question_type=QuestionType.SOLUTION,
            raw_text="17.S阴=",
            image_block_url="question_block.jpg",
            parse_audit=ParseAudit(visual_category="none"),
        )

        assert parser._should_attach_image(question) is True

    def test_solid_geometry_fallback_scores_l4(self):
        facts = build_dim2_visual_fallback_facts(
            "每个小正方体的棱长为2，求露在外面的面积。",
            {},
            parse_audit={"visual_category": "none"},
            has_image=True,
            used_image=True,
        )

        assert facts is not None
        assert facts["figure_complexity"] == "solid_3d"
        score = Dim2SpatialScorer().score(facts)
        assert score.applicable is True
        assert score.level == 4

    def test_circle_square_fallback_scores_l3(self):
        facts = build_dim2_visual_fallback_facts(
            "在一圆中取最大正方形，此圆直径为4，求S阴=",
            {"spatial_role": "none", "applicability_confidence": 0.0},
            parse_audit={"visual_category": "none"},
            has_image=True,
            used_image=True,
        )

        assert facts is not None
        assert facts["hidden_relation_count"] == "1"
        score = Dim2SpatialScorer().score(facts)
        assert score.applicable is True
        assert score.level == 3

    def test_direct_formula_area_does_not_use_visual_fallback(self):
        facts = build_dim2_visual_fallback_facts(
            "已知长方形长 8 厘米，宽 5 厘米，求面积。",
            {"spatial_role": "none", "applicability_confidence": 0.0},
            parse_audit={"visual_category": "geometry_context"},
            has_image=True,
            used_image=False,
        )

        assert facts is None

    def test_water_volume_fallback_scores_l4_without_stable_image_use(self):
        facts = build_dim2_visual_fallback_facts(
            "如图，一个瓶子中装有水，底面积10平方厘米，正放水高6厘米，倒放后空余部分高4厘米，求瓶子的容积。",
            {"spatial_role": "none", "applicability_confidence": 0.0},
            parse_audit={"visual_category": "geometry_context"},
            has_image=True,
            used_image=False,
        )

        assert facts is not None
        assert "water_displacement" in facts["geometry_model_types"]
        score = Dim2SpatialScorer().score(facts)
        assert score.applicable is True
        assert score.level == 4

        applicability = evaluate_dim2_applicability(
            "如图，一个瓶子中装有水，底面积10平方厘米，正放水高6厘米，倒放后空余部分高4厘米，求瓶子的容积。",
            facts,
            llm_confidence=0.7,
            parse_audit={"visual_category": "geometry_context"},
            used_image=False,
        )

        assert applicability["status"] == "applicable"

    def test_rectangle_reverse_area_fallback_scores_l3(self):
        facts = build_dim2_visual_fallback_facts(
            "一个长方形，长减少4米，宽减少2米，面积减少44平方米，剩下部分正好是一个正方形，求原来长方形的面积。",
            {"spatial_role": "none", "applicability_confidence": 0.0},
            parse_audit={"visual_category": "none"},
            has_image=False,
            used_image=False,
        )

        assert facts is not None
        assert facts["fallback_source"] == "geometry_structure"
        assert facts["geometry_model_types"] == ["reverse_area_edge"]
        score = Dim2SpatialScorer().score(facts)
        assert score.applicable is True
        assert score.level == 3

        applicability = evaluate_dim2_applicability(
            "一个长方形，长减少4米，宽减少2米，面积减少44平方米，剩下部分正好是一个正方形，求原来长方形的面积。",
            facts,
            llm_confidence=0.68,
            parse_audit={"visual_category": "none"},
            used_image=False,
        )

        assert applicability["status"] == "applicable"

    def test_cylinder_cone_ratio_does_not_use_visual_fallback(self):
        facts = build_dim2_visual_fallback_facts(
            "一个圆柱和一个圆锥的底面半径之比是2:3，体积之比是4:5，求它们的高之比。",
            {"spatial_role": "none", "applicability_confidence": 0.0},
            parse_audit={"visual_category": "geometry_context"},
            has_image=True,
            used_image=False,
        )

        assert facts is None


class TestDim3InformationScorer:
    """测试维度3：信息提取与转化评分器"""

    @pytest.fixture
    def scorer(self):
        return Dim3InformationScorer()

    @staticmethod
    def _dim3_features(**overrides):
        features = {
            "information_role": "core",
            "source_form": "text_only",
            "relevant_condition_count": "3-4",
            "distractor_pressure": "none",
            "condition_distribution": "compact",
            "extraction_depth": "reorganized",
            "representation_conversion": "relation_mapping",
            "conversion_step_count": "1",
            "quantity_relation_structure": "single_relation",
            "target_representation": "equation_relation",
            "global_organizing_required": 0,
            "image_dependency": "none",
            "application_relation_types": [],
            "object_count_band": "1",
            "state_change_count": "0",
            "implicit_relation_count": "0",
            "base_quantity_shift": "none",
            "comparison_candidate_count": "0",
            "evidence_summary": "需要整理应用题条件并转成数量关系。",
        }
        features.update(overrides)
        return features

    def test_not_applicable_short_circuit(self, scorer):
        result = scorer.score({"not_applicable": True})

        assert result.applicable is False
        assert result.score == 0.0
        assert "不适用" in result.evidence

    def test_l1_direct_extraction(self, scorer):
        features = {
            "information_role": "core",
            "source_form": "text_only",
            "relevant_condition_count": "1-2",
            "distractor_pressure": "none",
            "condition_distribution": "compact",
            "extraction_depth": "direct",
            "representation_conversion": "none",
            "conversion_step_count": "0",
            "quantity_relation_structure": "none",
            "target_representation": "none",
            "global_organizing_required": 0,
            "image_dependency": "none",
            "evidence_summary": "需要先从题干中摘出一个直接可用的关键条件。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 2.0
        assert result.level == 1
        assert result.level_label == "L1 直接提取"

    def test_very_long_core_text_scores_l4_even_when_direct(self, scorer):
        features = {
            "information_role": "core",
            "source_form": "text_only",
            "relevant_condition_count": "1-2",
            "distractor_pressure": "none",
            "condition_distribution": "compact",
            "extraction_depth": "direct",
            "representation_conversion": "direct_mapping",
            "conversion_step_count": "0",
            "quantity_relation_structure": "single_relation",
            "target_representation": "direct_formula",
            "global_organizing_required": 0,
            "image_dependency": "none",
            "text_length_chars": 128,
            "text_length_band": "very_long",
            "text_length_source": "local_raw_text",
            "evidence_summary": "长题干要求持续保持场景对象和数量条件。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.level == 4
        assert result.level_label == "L4 高负担组织"

    def test_long_core_text_scores_at_least_l3(self, scorer):
        features = {
            "information_role": "core",
            "source_form": "text_only",
            "relevant_condition_count": "1-2",
            "distractor_pressure": "none",
            "condition_distribution": "compact",
            "extraction_depth": "direct",
            "representation_conversion": "direct_mapping",
            "conversion_step_count": "0",
            "quantity_relation_structure": "single_relation",
            "target_representation": "direct_formula",
            "global_organizing_required": 0,
            "image_dependency": "none",
            "text_length_chars": 98,
            "text_length_band": "long",
            "text_length_source": "local_raw_text",
            "evidence_summary": "中长题干要求定位和保持多个叙述对象。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 6.0
        assert result.level == 3
        assert result.level_label == "L3 多条件转化"

    def test_l2_single_conversion(self, scorer):
        features = {
            "information_role": "core",
            "source_form": "table_chart",
            "relevant_condition_count": "3-4",
            "distractor_pressure": "light",
            "condition_distribution": "compact",
            "extraction_depth": "selected",
            "representation_conversion": "direct_mapping",
            "conversion_step_count": "0",
            "quantity_relation_structure": "single_relation",
            "target_representation": "direct_formula",
            "global_organizing_required": 0,
            "image_dependency": "required",
            "evidence_summary": "先从统计图读数，再直接代入单一关系式。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 4.0
        assert result.level == 2
        assert result.level_label == "L2 单次转化"

    def test_l3_multi_condition_conversion(self, scorer):
        features = {
            "information_role": "core",
            "source_form": "text_only",
            "relevant_condition_count": "3-4",
            "distractor_pressure": "none",
            "condition_distribution": "cross_sentence",
            "extraction_depth": "reorganized",
            "representation_conversion": "relation_mapping",
            "conversion_step_count": "1",
            "quantity_relation_structure": "multi_relation",
            "target_representation": "equation_relation",
            "global_organizing_required": 0,
            "image_dependency": "none",
            "evidence_summary": "需要跨句整理少量条件并改写成数量关系式。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 6.0
        assert result.level == 3
        assert result.level_label == "L3 多条件转化"

    def test_application_training_anchor_l3_work_rate_base_shift(self, scorer):
        result = scorer.score(
            self._dim3_features(
                relevant_condition_count="3-4",
                extraction_depth="inferred",
                application_relation_types=["work_rate"],
                state_change_count="1",
                implicit_relation_count="1",
                base_quantity_shift="single",
                evidence_summary="类似堰塞湖入水与泄洪延迟题，需要把时间变化转成进出水效率关系。",
            )
        )

        assert result.score == 6.0
        assert result.level_label == "L3 多条件转化"
        assert result.details["application_relation_types"] == ["work_rate"]

    def test_application_training_anchor_l4_queue_growth(self, scorer):
        result = scorer.score(
            self._dim3_features(
                relevant_condition_count="5-6",
                extraction_depth="inferred",
                quantity_relation_structure="multi_relation",
                application_relation_types=["queue_growth"],
                object_count_band="3",
                state_change_count="2",
                implicit_relation_count="2",
                base_quantity_shift="single",
                evidence_summary="类似牛吃草或检票排队题，需要区分原有量、增长量和消耗效率。",
            )
        )

        assert result.score == 8.0
        assert result.level_label == "L4 高负担组织"

    def test_application_training_anchor_l4_profit_discount_multistage(self, scorer):
        result = scorer.score(
            self._dim3_features(
                relevant_condition_count="5-6",
                condition_distribution="cross_sentence",
                extraction_depth="reorganized",
                quantity_relation_structure="multi_relation",
                application_relation_types=["profit_discount"],
                object_count_band="2",
                state_change_count="3+",
                implicit_relation_count="2",
                base_quantity_shift="multiple",
                evidence_summary="多阶段利润折扣题需要保持定价、折扣、手续费、损坏和出售等状态。",
            )
        )

        assert result.score == 8.0
        assert result.level_label == "L4 高负担组织"

    def test_application_training_anchor_l4_travel_speed_change(self, scorer):
        result = scorer.score(
            self._dim3_features(
                relevant_condition_count="5-6",
                extraction_depth="inferred",
                quantity_relation_structure="multi_relation",
                application_relation_types=["travel_meeting_chasing"],
                object_count_band="2",
                state_change_count="2",
                implicit_relation_count="2",
                base_quantity_shift="multiple",
                evidence_summary="多段行程题需要把相遇前后速度变化与剩余路程关系重新组织。",
            )
        )

        assert result.score == 8.0
        assert result.level_label == "L4 高负担组织"

    def test_application_training_anchor_l4_optimization_comparison(self, scorer):
        result = scorer.score(
            self._dim3_features(
                source_form="table_chart",
                relevant_condition_count="5-6",
                extraction_depth="selected",
                target_representation="table_list",
                image_dependency="required",
                application_relation_types=["optimization_comparison", "chart_table_conversion"],
                object_count_band="1",
                state_change_count="1",
                implicit_relation_count="1",
                comparison_candidate_count="3+",
                evidence_summary="票价或定期票方案比较题需要从表格中生成多个候选方案并比较。",
            )
        )

        assert result.score == 8.0
        assert result.level_label == "L4 高负担组织"

    def test_simple_direct_average_total_is_not_raised_above_l2(self, scorer):
        result = scorer.score(
            self._dim3_features(
                relevant_condition_count="1-2",
                extraction_depth="direct",
                representation_conversion="direct_mapping",
                conversion_step_count="0",
                quantity_relation_structure="single_relation",
                target_representation="direct_formula",
                application_relation_types=["average_total"],
                object_count_band="1",
                state_change_count="0",
                implicit_relation_count="0",
                evidence_summary="简单平均数题只需直接读取总量和份数。",
            )
        )

        assert result.score == 4.0
        assert result.level_label == "L2 单次转化"

    def test_l3_hidden_inverse_relation_application(self, scorer):
        features = {
            "information_role": "core",
            "source_form": "text_only",
            "relevant_condition_count": "3-4",
            "distractor_pressure": "none",
            "condition_distribution": "compact",
            "extraction_depth": "inferred",
            "representation_conversion": "direct_mapping",
            "conversion_step_count": "1",
            "quantity_relation_structure": "single_relation",
            "target_representation": "direct_formula",
            "global_organizing_required": 0,
            "image_dependency": "none",
            "evidence_summary": "需要把每小时多 60% 转成效率比，并进一步识别同工作量下时间成反比。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 6.0
        assert result.level == 3
        assert result.level_label == "L3 多条件转化"

    def test_l3_table_secondary_processing(self, scorer):
        features = {
            "information_role": "core",
            "source_form": "table_chart",
            "relevant_condition_count": "3-4",
            "distractor_pressure": "light",
            "condition_distribution": "compact",
            "extraction_depth": "selected",
            "representation_conversion": "direct_mapping",
            "conversion_step_count": "1",
            "quantity_relation_structure": "single_relation",
            "target_representation": "direct_formula",
            "global_organizing_required": 0,
            "image_dependency": "required",
            "evidence_summary": "需要先从表格筛选数据，再计算命中率或单位量后比较。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 6.0
        assert result.level == 3
        assert result.level_label == "L3 多条件转化"

    def test_l4_distributed_scene_organization(self, scorer):
        features = {
            "information_role": "core",
            "source_form": "text_only",
            "relevant_condition_count": "5-6",
            "distractor_pressure": "light",
            "condition_distribution": "cross_sentence",
            "extraction_depth": "reorganized",
            "representation_conversion": "relation_mapping",
            "conversion_step_count": "1",
            "quantity_relation_structure": "multi_relation",
            "target_representation": "equation_relation",
            "global_organizing_required": 0,
            "image_dependency": "none",
            "evidence_summary": "需要从长场景中跨句筛选多个条件并组织成多关系表达。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.level == 4
        assert result.level_label == "L4 高负担组织"

    def test_l4_high_burden_organization(self, scorer):
        features = {
            "information_role": "core",
            "source_form": "multi_source",
            "relevant_condition_count": "5-6",
            "distractor_pressure": "heavy",
            "condition_distribution": "cross_sentence",
            "extraction_depth": "reorganized",
            "representation_conversion": "model_mapping",
            "conversion_step_count": "2",
            "quantity_relation_structure": "multi_relation",
            "target_representation": "equation_relation",
            "global_organizing_required": 1,
            "image_dependency": "helpful",
            "evidence_summary": "需要从多段材料筛选条件并建立等量关系系统。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.level == 4
        assert result.level_label == "L4 高负担组织"

    def test_l5_high_order_reconstruction(self, scorer):
        features = {
            "information_role": "core",
            "source_form": "multi_source",
            "relevant_condition_count": "7+",
            "distractor_pressure": "heavy",
            "condition_distribution": "cross_modal",
            "extraction_depth": "inferred",
            "representation_conversion": "custom_model",
            "conversion_step_count": "3+",
            "quantity_relation_structure": "nested_relation",
            "target_representation": "custom_model",
            "global_organizing_required": 1,
            "image_dependency": "required",
            "evidence_summary": "需要跨模态整合材料并自建表示模型。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 9.5
        assert result.level == 5
        assert result.level_label == "L5 高阶重构建模"

    def test_invalid_features_mark_not_applicable(self, scorer):
        result = scorer.score({"information_role": "core", "source_form": "text_only"})

        assert result.applicable is False
        assert result.score == 0.0
        assert "关键信息提取事实不完整" in result.evidence


class TestDim3Applicability:
    """测试 dim3 后端适用性门控"""

    def test_direct_formula_word_problem_is_not_applicable(self):
        result = evaluate_dim3_applicability(
            "一辆汽车 3 小时行了 180 千米，平均每小时行多少千米？",
            {
                "information_role": "core",
                "source_form": "text_only",
                "relevant_condition_count": "1-2",
                "distractor_pressure": "none",
                "condition_distribution": "compact",
                "extraction_depth": "direct",
                "representation_conversion": "direct_mapping",
                "conversion_step_count": "0",
                "quantity_relation_structure": "single_relation",
                "target_representation": "direct_formula",
                "global_organizing_required": 0,
                "image_dependency": "none",
                "evidence_summary": "直接读取路程和时间后代入公式。",
            },
            llm_confidence=0.92,
        )

        assert result["status"] == "not_applicable"

    def test_application_relation_facts_prevent_low_barrier_exclusion(self):
        result = evaluate_dim3_applicability(
            "为了延长转移时间，开辟泄洪渠道后水位到达坝顶从20天推迟到30天，求每天泄出水量与流入量的关系。",
            {
                "information_role": "core",
                "source_form": "text_only",
                "relevant_condition_count": "1-2",
                "distractor_pressure": "none",
                "condition_distribution": "compact",
                "extraction_depth": "direct",
                "representation_conversion": "direct_mapping",
                "conversion_step_count": "0",
                "quantity_relation_structure": "single_relation",
                "target_representation": "direct_formula",
                "global_organizing_required": 0,
                "image_dependency": "none",
                "application_relation_types": ["work_rate"],
                "object_count_band": "2",
                "state_change_count": "1",
                "implicit_relation_count": "1",
                "base_quantity_shift": "single",
                "comparison_candidate_count": "0",
                "evidence_summary": "需要把时间变化转成进水和泄水效率关系。",
                "applicability_confidence": 0.9,
            },
            llm_confidence=0.9,
        )

        assert result["status"] == "applicable"

    def test_text_length_enrichment_uses_local_raw_text(self):
        raw_text = "甲" * 120
        feature = enrich_dim3_text_length_facts(raw_text, {"information_role": "core"})

        assert feature["text_length_chars"] == 120
        assert feature["text_length_band"] == "very_long"
        assert feature["text_length_source"] == "local_raw_text"

    def test_very_long_core_direct_extraction_is_applicable(self):
        raw_text = "学校组织数学实践活动，甲乙两组分别完成不同任务，需要根据活动安排、人数变化、用时记录和问题要求整理条件。" * 3
        result = evaluate_dim3_applicability(
            raw_text,
            {
                "information_role": "core",
                "source_form": "text_only",
                "relevant_condition_count": "1-2",
                "distractor_pressure": "none",
                "condition_distribution": "compact",
                "extraction_depth": "direct",
                "representation_conversion": "direct_mapping",
                "conversion_step_count": "0",
                "quantity_relation_structure": "single_relation",
                "target_representation": "direct_formula",
                "global_organizing_required": 0,
                "image_dependency": "none",
                "evidence_summary": "题干较长，需要持续保持活动场景和数量条件。",
                "applicability_confidence": 0.92,
            },
            llm_confidence=0.92,
        )

        assert result["status"] == "applicable"
        assert "题干长度" in result["reason"]

    def test_long_core_direct_extraction_is_not_low_barrier(self):
        raw_text = "甲" * 95
        result = evaluate_dim3_applicability(
            raw_text,
            {
                "information_role": "core",
                "source_form": "text_only",
                "relevant_condition_count": "1-2",
                "distractor_pressure": "none",
                "condition_distribution": "compact",
                "extraction_depth": "direct",
                "representation_conversion": "direct_mapping",
                "conversion_step_count": "0",
                "quantity_relation_structure": "single_relation",
                "target_representation": "direct_formula",
                "global_organizing_required": 0,
                "image_dependency": "none",
                "evidence_summary": "中长题干需要信息保持。",
                "applicability_confidence": 0.91,
            },
            llm_confidence=0.91,
        )

        assert result["status"] == "applicable"

    def test_table_chart_reading_is_applicable(self):
        result = evaluate_dim3_applicability(
            "根据统计图回答问题。",
            {
                "information_role": "core",
                "source_form": "table_chart",
                "relevant_condition_count": "3-4",
                "distractor_pressure": "light",
                "condition_distribution": "split",
                "extraction_depth": "selected",
                "representation_conversion": "relation_mapping",
                "conversion_step_count": "1",
                "quantity_relation_structure": "single_relation",
                "target_representation": "table_list",
                "global_organizing_required": 0,
                "image_dependency": "required",
                "evidence_summary": "需要从统计图读取多项数据并整理成表。",
                "applicability_confidence": 0.88,
            },
            llm_confidence=0.88,
            parse_audit={"visual_category": "table_chart", "image_required_hint": True},
            used_image=True,
        )

        assert result["status"] == "applicable"
        assert "核心门槛" in result["reason"]

    def test_missing_facts_go_to_review(self):
        result = evaluate_dim3_applicability(
            "下表记录了三次测量结果，请判断哪次最接近标准值。",
            {
                "information_role": "core",
                "source_form": "table_chart",
                "evidence_summary": "缺少完整提取事实。",
            },
            llm_confidence=0.84,
            parse_audit={"visual_category": "table_chart", "image_required_hint": True},
            used_image=True,
        )

        assert result["status"] == "review"
        assert any("关键信息提取事实字段" in item for item in result["warnings"])

    def test_required_image_without_stable_image_use_goes_to_review(self):
        result = evaluate_dim3_applicability(
            "观察图文材料并回答问题。",
            {
                "information_role": "core",
                "source_form": "image_text",
                "relevant_condition_count": "3-4",
                "distractor_pressure": "light",
                "condition_distribution": "cross_modal",
                "extraction_depth": "selected",
                "representation_conversion": "relation_mapping",
                "conversion_step_count": "2",
                "quantity_relation_structure": "multi_relation",
                "target_representation": "equation_relation",
                "global_organizing_required": 1,
                "image_dependency": "required",
                "evidence_summary": "需要同时读取图片标注和文字条件。",
                "applicability_confidence": 0.9,
            },
            llm_confidence=0.9,
            parse_audit={"visual_category": "multi_part_layout", "image_required_hint": True},
            used_image=False,
            image_fallback=True,
        )

        assert result["status"] == "review"
        assert any("依赖图片" in item or "退回纯文本" in item for item in result["warnings"])

    def test_image_cropped_flag_does_not_block_reliable_dim3(self):
        result = evaluate_dim3_applicability(
            "某校足球赛胜一场得3分，平一场得1分，输了不得分。根据总分和场次求可能方案。",
            {
                "information_role": "core",
                "source_form": "text_only",
                "relevant_condition_count": "5-6",
                "distractor_pressure": "light",
                "condition_distribution": "split",
                "extraction_depth": "reorganized",
                "representation_conversion": "relation_mapping",
                "conversion_step_count": "2",
                "quantity_relation_structure": "multi_relation",
                "target_representation": "equation_relation",
                "global_organizing_required": 1,
                "image_dependency": "none",
                "evidence_summary": "需要整理积分规则、场次和总分并转成数量关系。",
                "applicability_confidence": 0.91,
            },
            llm_confidence=0.91,
            parse_audit={"image_cropped": True, "block_completeness": 0.82},
        )

        assert result["status"] == "applicable"

    def test_low_confidence_low_burden_dim3_is_not_applicable(self):
        result = evaluate_dim3_applicability(
            "已知长方形长8厘米，宽5厘米，求面积。",
            {
                "information_role": "supporting",
                "source_form": "text_only",
                "relevant_condition_count": "1-2",
                "distractor_pressure": "none",
                "condition_distribution": "compact",
                "extraction_depth": "direct",
                "representation_conversion": "direct_mapping",
                "conversion_step_count": "0",
                "quantity_relation_structure": "single_relation",
                "target_representation": "direct_formula",
                "global_organizing_required": 0,
                "image_dependency": "none",
                "evidence_summary": "条件集中且直接代入公式。",
                "applicability_confidence": 0.31,
            },
            llm_confidence=0.31,
        )

        assert result["status"] == "not_applicable"


class TestDim6Applicability:
    def test_core_logic_chain_question_is_applicable(self):
        result = evaluate_dim6_applicability(
            "请分类讨论两种情况，并回查哪一种符合条件。",
            {
                "reasoning_role": "core",
                "chain_span": "3-4",
                "hidden_dependency": "cross_condition",
                "branch_control": "explicit_cases",
                "reversibility": "none",
                "verification_requirement": "constraint_backcheck",
                "abstraction_bridge_count": "1",
                "constraint_coupling": "coupled",
                "global_consistency_required": 1,
                "conclusion_stability": "edge_sensitive",
                "evidence_summary": "需要分类串联条件并回查约束。",
                "applicability_confidence": 0.9,
            },
            llm_confidence=0.9,
        )

        assert result["status"] == "applicable"
        assert "核心门槛" in result["reason"]

    def test_low_barrier_direct_push_is_not_applicable(self):
        result = evaluate_dim6_applicability(
            "根据已知条件直接判断结果是否正确。",
            {
                "reasoning_role": "core",
                "chain_span": "1",
                "hidden_dependency": "none",
                "branch_control": "none",
                "reversibility": "none",
                "verification_requirement": "none",
                "abstraction_bridge_count": "0",
                "constraint_coupling": "single",
                "global_consistency_required": 0,
                "conclusion_stability": "direct",
                "evidence_summary": "条件显式，可一步直推。",
                "applicability_confidence": 0.91,
            },
            llm_confidence=0.91,
        )

        assert result["status"] == "not_applicable"

    def test_missing_logic_facts_go_to_review(self):
        result = evaluate_dim6_applicability(
            "请说明哪种方案满足全部条件。",
            {
                "reasoning_role": "core",
                "chain_span": "3-4",
                "evidence_summary": "缺少完整逻辑事实。",
            },
            llm_confidence=0.88,
        )

        assert result["status"] == "review"
        assert any("关键逻辑事实字段" in item for item in result["warnings"])

    def test_logic_signal_with_damage_goes_to_review(self):
        result = evaluate_dim6_applicability(
            "请分类讨论所有可能情况，并验证结论是否成立。",
            {
                "reasoning_role": "none",
                "chain_span": "1",
                "hidden_dependency": "none",
                "branch_control": "none",
                "reversibility": "none",
                "verification_requirement": "none",
                "abstraction_bridge_count": "0",
                "constraint_coupling": "none",
                "global_consistency_required": 0,
                "conclusion_stability": "direct",
                "evidence_summary": "题面有分类讨论信号，但当前标记偏低。",
                "applicability_confidence": 0.86,
            },
            llm_confidence=0.86,
            parse_audit={"block_completeness": 0.6, "image_cropped": True},
            parse_warnings=["OCR 识别残缺"],
        )

        assert result["status"] == "review"
        assert any(
            "题块完整度不足" in item or "OCR" in item or "分类" in item
            for item in result["warnings"]
        )

    def test_image_cropped_flag_does_not_block_reliable_dim6(self):
        result = evaluate_dim6_applicability(
            "根据积分规则列出可能情况，再逐一回查总场次和总分约束。",
            {
                "reasoning_role": "core",
                "chain_span": "5+",
                "hidden_dependency": "global",
                "branch_control": "multi_branch",
                "reversibility": "none",
                "verification_requirement": "full_consistency",
                "abstraction_bridge_count": "2",
                "constraint_coupling": "nested",
                "global_consistency_required": 1,
                "conclusion_stability": "exhaustive",
                "evidence_summary": "需要枚举分支并用全局约束收束。",
                "applicability_confidence": 0.92,
            },
            llm_confidence=0.92,
            parse_audit={"image_cropped": True, "block_completeness": 0.86},
        )

        assert result["status"] == "applicable"

    def test_low_confidence_low_burden_dim6_is_not_applicable(self):
        result = evaluate_dim6_applicability(
            "直接根据题目给出的等式求结果。",
            {
                "reasoning_role": "supporting",
                "chain_span": "1",
                "hidden_dependency": "none",
                "branch_control": "none",
                "reversibility": "none",
                "verification_requirement": "none",
                "abstraction_bridge_count": "0",
                "constraint_coupling": "single",
                "global_consistency_required": 0,
                "conclusion_stability": "direct",
                "evidence_summary": "条件显式，可一步直推。",
                "applicability_confidence": 0.28,
            },
            llm_confidence=0.28,
        )

        assert result["status"] == "not_applicable"


class TestDim4InnovationScorer:
    """测试维度4：实践创新评分器"""

    @pytest.fixture
    def scorer(self):
        return Dim4InnovationScorer()

    def test_l1_regular_transfer(self, scorer):
        features = {
            "strategy_role": "core",
            "template_fit": "direct",
            "breakthrough_type": "none",
            "strategy_shift_count": "0",
            "construction_requirement": "none",
            "exploration_space": "none",
            "representation_reframe": "none",
            "transfer_distance": "near",
            "path_openness": "single",
            "dead_end_risk": "low",
            "global_strategy_required": 0,
            "image_dependency": "none",
            "evidence_summary": "可以直接沿着常规模板推进，只存在常规迁移。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 2.0
        assert result.level == 1
        assert result.level_label == "L1 基础模板"

    def test_l3_strategy_reframing(self, scorer):
        features = {
            "strategy_role": "core",
            "template_fit": "reframed",
            "breakthrough_type": "strategy_shift",
            "strategy_shift_count": "1",
            "construction_requirement": "none",
            "exploration_space": "bounded",
            "representation_reframe": "structural",
            "transfer_distance": "medium",
            "path_openness": "single",
            "dead_end_risk": "medium",
            "global_strategy_required": 0,
            "image_dependency": "none",
            "evidence_summary": "需要换一个切入角度并重组已有熟题结构。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 6.0
        assert result.level == 3
        assert result.level_label == "L3 中度变式"

    def test_l3_bounded_candidate_screening(self, scorer):
        features = {
            "strategy_role": "core",
            "template_fit": "adapted",
            "breakthrough_type": "none",
            "strategy_shift_count": "0",
            "construction_requirement": "none",
            "exploration_space": "bounded",
            "representation_reframe": "minor",
            "transfer_distance": "near",
            "path_openness": "multiple_paths",
            "dead_end_risk": "medium",
            "global_strategy_required": 0,
            "image_dependency": "none",
            "evidence_summary": "需要在有限候选方案中筛选可行路径。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 6.0
        assert result.level == 3

    def test_l4_reframed_case_construction(self, scorer):
        features = {
            "strategy_role": "core",
            "template_fit": "reframed",
            "breakthrough_type": "strategy_shift",
            "strategy_shift_count": "2",
            "construction_requirement": "case_construction",
            "exploration_space": "bounded",
            "representation_reframe": "structural",
            "transfer_distance": "medium",
            "path_openness": "multiple_paths",
            "dead_end_risk": "medium",
            "global_strategy_required": 0,
            "image_dependency": "none",
            "evidence_summary": "需要改用分类构造并回查多个候选方案。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.level == 4

    def test_l4_constructive_exploration(self, scorer):
        features = {
            "strategy_role": "core",
            "template_fit": "non_routine",
            "breakthrough_type": "constructive",
            "strategy_shift_count": "2",
            "construction_requirement": "custom_construction",
            "exploration_space": "branched",
            "representation_reframe": "structural",
            "transfer_distance": "far",
            "path_openness": "multiple_paths",
            "dead_end_risk": "medium",
            "global_strategy_required": 1,
            "image_dependency": "helpful",
            "evidence_summary": "需要主动构造中间对象并在多条策略路径中选择可行方案。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.level == 4
        assert result.level_label == "L4 高阶变式"

    def test_l5_high_order_innovation(self, scorer):
        features = {
            "strategy_role": "core",
            "template_fit": "non_routine",
            "breakthrough_type": "exploratory_search",
            "strategy_shift_count": "3+",
            "construction_requirement": "custom_construction",
            "exploration_space": "open",
            "representation_reframe": "creative",
            "transfer_distance": "far",
            "path_openness": "multiple_answers",
            "dead_end_risk": "high",
            "global_strategy_required": 1,
            "image_dependency": "none",
            "evidence_summary": "需要在开放探索中多次换路并收束到可行构造。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 9.5
        assert result.level == 5
        assert result.level_label == "L5 压轴创新"

    def test_non_core_strategy_returns_na(self, scorer):
        result = scorer.score(
            {
                "strategy_role": "supporting",
                "template_fit": "adapted",
                "breakthrough_type": "none",
                "strategy_shift_count": "0",
                "construction_requirement": "none",
                "exploration_space": "none",
                "representation_reframe": "minor",
                "transfer_distance": "near",
                "path_openness": "single",
                "dead_end_risk": "low",
                "global_strategy_required": 0,
                "image_dependency": "none",
                "evidence_summary": "主要难点不在策略突破。",
            }
        )

        assert result.applicable is False
        assert result.score == 0.0

    def test_reference_calibrated_level_overrides_local_dim4_level(self, scorer):
        result = scorer.score(
            {
                "strategy_role": "core",
                "template_fit": "reframed",
                "breakthrough_type": "strategy_shift",
                "strategy_shift_count": "1",
                "construction_requirement": "none",
                "exploration_space": "bounded",
                "representation_reframe": "structural",
                "transfer_distance": "medium",
                "path_openness": "single",
                "dead_end_risk": "medium",
                "global_strategy_required": 0,
                "image_dependency": "none",
                "evidence_summary": "本地事实是一次换路重组。",
                "reference_calibrated_level": "L4",
                "calibration": {
                    "action": "calibrated_to_reference",
                    "model_level": "L3",
                    "reference_level": "L4",
                },
            }
        )

        assert result.applicable is True
        assert result.level == 4
        assert result.score == 8.0
        assert result.details["reference_calibrated"] is True
        assert result.details["reference_calibration_action"] == "calibrated_to_reference"

    @pytest.mark.parametrize(
        ("topic_level", "expected_score"),
        [("L1", 2.0), ("L2", 4.0), ("L3", 6.0), ("L4", 8.0), ("L5", 9.5)],
    )
    def test_topic_internal_level_is_primary_dim4_rule(self, scorer, topic_level, expected_score):
        result = scorer.score(
            {
                "knowledge_point": "牛吃草",
                "topic_level": topic_level,
                "level_source": "knowledge_anchor",
                "anchor_evidence": "同一知识点内部锚点判定。",
                "evidence_summary": "按牛吃草知识点内部标尺定位。",
            }
        )

        assert result.applicable is True
        assert result.score == expected_score
        assert result.details["knowledge_point"] == "牛吃草"
        assert result.details["topic_level"] == topic_level
        assert result.details["level_source"] == "knowledge_anchor"

    def test_competition_variant_calibration_raises_defined_operation_telescoping(self, scorer):
        result = scorer.score(
            {
                "knowledge_point": "定义新运算与分数裂项",
                "topic_level": "L3",
                "level_source": "knowledge_anchor",
                "anchor_evidence": "本地锚点原判为中度变式。",
                "evidence_summary": "需要先展开定义新运算，再识别裂项相消结构。",
                "evidence_tags": ["定义新运算", "裂项"],
            }
        )

        assert result.applicable is True
        assert result.score == 8.0
        assert result.details["topic_level"] == "L4"
        assert result.details["local_variant_calibration"]["previous_level"] == "L3"

    def test_competition_variant_calibration_raises_game_strategy(self, scorer):
        result = scorer.score(
            {
                "knowledge_point": "博弈策略",
                "topic_level": "L3",
                "level_source": "knowledge_anchor",
                "anchor_evidence": "需要在规则内寻找稳定策略。",
                "evidence_summary": "两人轮流操作，需要分析博弈制胜策略。",
                "evidence_tags": ["博弈", "制胜策略"],
            }
        )

        assert result.applicable is True
        assert result.level == 4
        assert result.details["local_variant_calibration"]["source"] == "local_topic_variant"
        assert result.details["variant_signal_group"] == "game_strategy"
        assert result.details["previous_topic_level"] == "L3"
        assert result.details["calibrated_topic_level"] == "L4"

    def test_competition_variant_calibration_raises_three_view_projection_to_l3(self, scorer):
        result = scorer.score(
            {
                "knowledge_point": "空间位置",
                "topic_level": "L2",
                "level_source": "knowledge_anchor",
                "anchor_evidence": "原判为轻度视图变式。",
                "evidence_summary": "透明立方体中有内部连线，需要完成三视图投影。",
                "evidence_tags": ["三视图", "内部连线", "投影"],
            }
        )

        assert result.applicable is True
        assert result.score == 6.0
        assert result.details["topic_level"] == "L3"

    def test_competition_variant_calibration_does_not_raise_direct_template(self, scorer):
        result = scorer.score(
            {
                "knowledge_point": "工程问题",
                "topic_level": "L2",
                "level_source": "knowledge_anchor",
                "anchor_evidence": "普通两人合作工程题。",
                "evidence_summary": "直接套效率和公式，不涉及竞赛型结构信号。",
                "evidence_tags": ["工程问题", "直接模板"],
            }
        )

        assert result.applicable is True
        assert result.score == 4.0
        assert "local_variant_calibration" not in result.details

    @pytest.mark.parametrize(
        ("feature_overrides", "expected_level", "expected_group"),
        [
            (
                {
                    "topic_level": "L2",
                    "evidence_summary": "需要先做一次反向整理，把已知结果倒推回原始数量。",
                    "evidence_tags": ["反向整理"],
                },
                4,
                "reverse_organization",
            ),
            (
                {
                    "topic_level": "L2",
                    "evidence_summary": "需要从有限候选中筛选符合条件的方案。",
                    "evidence_tags": ["有限候选", "候选筛选"],
                },
                3,
                "finite_candidate_screening",
            ),
            (
                {
                    "topic_level": "L2",
                    "evidence_summary": "只需要做一次简单倒推，倒回原来的数量。",
                    "evidence_tags": ["简单倒推"],
                },
                3,
                "single_reverse_step",
            ),
            (
                {
                    "topic_level": "L2",
                    "evidence_summary": "只需要识别相遇后速度变化，再沿原关系推进。",
                    "evidence_tags": ["相遇后"],
                },
                3,
                "single_phase_change",
            ),
            (
                {
                    "topic_level": "L2",
                    "evidence_summary": "只需要识别单个几何模型并直接使用面积关系。",
                    "evidence_tags": ["单个几何模型"],
                },
                3,
                "single_geometry_model",
            ),
            (
                {
                    "topic_level": "L3",
                    "evidence_summary": "需要构造中间量，再回查多个条件是否一致。",
                    "evidence_tags": ["构造中间量", "回查"],
                },
                4,
                "intermediate_construction",
            ),
            (
                {
                    "topic_level": "L3",
                    "evidence_summary": "需要进行方案比较并回查约束。",
                    "evidence_tags": ["方案比较", "回查"],
                },
                4,
                "plan_comparison_backcheck",
            ),
            (
                {
                    "topic_level": "L2",
                    "evidence_summary": "需要先做一次变基准，再反向整理成本与利润关系。",
                    "evidence_tags": ["一次变基准", "反向整理"],
                },
                4,
                "reverse_organization",
            ),
            (
                {
                    "topic_level": "L2",
                    "evidence_summary": "需要先筛选有限候选，再做约束回查。",
                    "evidence_tags": ["有限候选", "约束回查"],
                },
                4,
                "constraint_backcheck",
            ),
            (
                {
                    "topic_level": "L2",
                    "evidence_summary": "需要识别单个几何模型，随后割补并组织面积关系。",
                    "evidence_tags": ["单个几何模型", "割补"],
                },
                4,
                "single_geometry_model+geometry_followup",
            ),
            (
                {
                    "topic_level": "L2",
                    "evidence_summary": "需要识别相遇后变化，并处理等待导致的路径组织。",
                    "evidence_tags": ["相遇后", "等待"],
                },
                4,
                "single_phase_change+travel_followup",
            ),
            (
                {
                    "topic_level": "L2",
                    "evidence_summary": "需要先做一次变基准，再进行候选筛选。",
                    "evidence_tags": ["一次变基准", "候选筛选"],
                },
                4,
                "combined_l3_signals",
            ),
            (
                {
                    "topic_level": "L1",
                    "evidence_summary": "需要识别一次变基准后再套比例关系。",
                    "evidence_tags": ["一次变基准"],
                },
                3,
                "base_quantity_shift",
            ),
        ],
    )
    def test_topic_variant_calibration_raises_common_dim4_under_scores(
        self,
        scorer,
        feature_overrides,
        expected_level,
        expected_group,
    ):
        features = {
            "knowledge_point": "比例百分数应用",
            "topic_level": "L2",
            "level_source": "knowledge_anchor",
            "anchor_evidence": "原始锚点偏保守。",
        }
        features.update(feature_overrides)

        result = scorer.score(features)

        assert result.applicable is True
        assert result.level == expected_level
        assert result.details["variant_signal_group"] == expected_group
        assert result.details["upshift_reason"]

    @pytest.mark.parametrize(
        ("feature_overrides", "expected_group"),
        [
            (
                {
                    "knowledge_point": "定义新运算",
                    "topic_level": "L3",
                    "evidence_summary": "需要先完成定义新运算结构展开，再识别倒推关系和裂项关系。",
                    "evidence_tags": ["定义新运算", "结构展开", "倒推关系", "裂项关系"],
                },
                "defined_operation_structure",
            ),
            (
                {
                    "knowledge_point": "分数裂项/结构计算",
                    "topic_level": "L3",
                    "evidence_summary": "需要识别非相邻裂项，完成长链消去并提取首尾项。",
                    "evidence_tags": ["非相邻裂项", "长链消去", "首尾项提取"],
                },
                "fraction_telescoping_structure",
            ),
            (
                {
                    "knowledge_point": "圆的周长与半径关系",
                    "topic_level": "L3",
                    "evidence_summary": "需要用差分增量关系处理周长变化，并识别原半径是参数无关量。",
                    "evidence_tags": ["差分增量", "参数无关", "无关量消去"],
                },
                "increment_invariance",
            ),
            (
                {
                    "knowledge_point": "比例百分数应用",
                    "topic_level": "L2",
                    "evidence_summary": "需要处理多状态百分数和利润率，新旧基准联动，成本下降后再降价。",
                    "evidence_tags": ["多状态百分数", "新旧基准联动", "成本下降", "降价", "实际利润率"],
                },
                "profit_reverse_organization",
            ),
            (
                {
                    "knowledge_point": "比例百分数应用",
                    "topic_level": "L3",
                    "evidence_summary": "多个部分都与其余部分之和形成比例，需要共同约束并转化到同一个总量。",
                    "evidence_tags": ["其余部分之和", "共同约束", "总量转化"],
                },
                "ratio_global_constraints",
            ),
            (
                {
                    "knowledge_point": "抽屉/分类计数",
                    "topic_level": "L3",
                    "evidence_summary": "需要位置耦合枚举，结合整除约束构造概率分母。",
                    "evidence_tags": ["位置耦合枚举", "整除约束", "概率分母构造"],
                },
                "position_coupled_enumeration",
            ),
        ],
    )
    def test_wmo_dim4_l4_signal_calibrations(self, scorer, feature_overrides, expected_group):
        features = {
            "level_source": "knowledge_anchor",
            "anchor_evidence": "原始锚点偏保守。",
        }
        features.update(feature_overrides)

        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.details["topic_level"] == "L4"
        assert result.details["variant_signal_group"] == expected_group

    def test_dim4_game_strategy_requires_global_verification_for_l5(self, scorer):
        local_strategy = scorer.score(
            {
                "knowledge_point": "博弈策略",
                "topic_level": "L3",
                "level_source": "knowledge_anchor",
                "anchor_evidence": "需要在规则内寻找稳定策略。",
                "evidence_summary": "两人轮流操作，需要分析博弈制胜策略。",
                "evidence_tags": ["博弈", "制胜策略"],
            }
        )
        global_strategy = scorer.score(
            {
                "knowledge_point": "博弈策略",
                "topic_level": "L4",
                "level_source": "knowledge_anchor",
                "anchor_evidence": "需要验证必胜策略。",
                "evidence_summary": "需要构造制胜策略，分析对手应对，进行必胜态回查并保证获胜。",
                "evidence_tags": ["制胜策略", "对手应对", "必胜态回查", "保证获胜"],
            }
        )

        assert local_strategy.score == 8.0
        assert local_strategy.details["topic_level"] == "L4"
        assert global_strategy.score == 9.5
        assert global_strategy.details["topic_level"] == "L5"
        assert global_strategy.details["variant_signal_group"] == "winning_strategy_global_check"

    def test_dim4_high_level_zero_confidence_placeholder_can_remain_applicable(self, scorer):
        feature = {
            "knowledge_point": "抽屉/分类计数",
            "topic_level": "L3",
            "level_source": "knowledge_anchor",
            "anchor_evidence": "需要一次重新设类和候选筛选。",
            "strategy_role": "core",
            "template_fit": "adapted",
            "breakthrough_type": "local_trick",
            "strategy_shift_count": "1",
            "construction_requirement": "simple_setup",
            "exploration_space": "bounded",
            "representation_reframe": "minor",
            "transfer_distance": "medium",
            "path_openness": "single",
            "dead_end_risk": "low",
            "global_strategy_required": 1,
            "image_dependency": "helpful",
            "evidence_summary": "需要位置耦合枚举，结合被4整除法则构造概率分母。",
            "evidence_tags": ["位置耦合枚举", "被4整除法则", "概率分母构造"],
            "applicability_confidence": 0.0,
            "need_manual_review": 0,
            "warning": "",
        }

        score = scorer.score(feature)
        status = evaluate_dim4_applicability("密码锁号码需要满足位置与整除约束。", feature, used_image=True)

        assert score.score == 8.0
        assert status["status"] == "applicable"

        feature["applicability_confidence"] = 0.2
        status = evaluate_dim4_applicability("密码锁号码需要满足位置与整除约束。", feature, used_image=True)

        assert status["status"] == "review"

    def test_gaosi_section_label_alone_does_not_raise_dim4_level(self, scorer):
        result = scorer.score(
            {
                "knowledge_point": "工程问题",
                "topic_level": "L2",
                "level_source": "knowledge_anchor",
                "anchor_evidence": "高思候选只作为同知识点参考，不直接决定 dim4 等级。",
                "evidence_summary": "题目条件只是轻微改写，仍能直接套工程模板。",
                "reference_matches": [
                    {
                        "section_label": "超越篇",
                        "match_quality": "partial/audit_only",
                    }
                ],
            }
        )

        assert result.applicable is True
        assert result.score == 4.0
        assert result.details["topic_level"] == "L2"
        assert "local_variant_calibration" not in result.details

    @pytest.mark.parametrize(
        ("knowledge_point", "question_text", "expected_level"),
        [
            (
                "牛吃草问题",
                "检票口每分钟都有人排队进入，已知不同窗口数量下完成检票的时间，求原有队伍人数。",
                "L3",
            ),
            (
                "牛吃草问题",
                "检票口每分钟都有人排队进入，先开两个窗口，后来增加窗口且窗口效率变化，求完成时间。",
                "L4",
            ),
            (
                "工程问题",
                "甲乙合作完成工程，中途甲换班离开，需整理剩余量后求总时间。",
                "L3",
            ),
            (
                "工程问题",
                "甲乙丙多阶段换班协作，效率变化和剩余量联动，求最后完成时间。",
                "L4",
            ),
            (
                "行程问题",
                "甲乙相遇后速度变化，继续行驶一段后求两地距离。",
                "L3",
            ),
            (
                "行程问题",
                "甲乙相遇后又往返、等待并调头，多阶段状态联动后求距离。",
                "L4",
            ),
            (
                "百分数",
                "商品先涨价再打折，需要做一次变基准后求现价。",
                "L3",
            ),
            (
                "百分数",
                "商品经过多次折扣、损耗和利润变化，需要反向整理成本与售价。",
                "L4",
            ),
            (
                "方案比较",
                "比较多个候选方案，计算后筛选费用最低的一种。",
                "L3",
            ),
            (
                "方案比较",
                "先做有限分类，再约束回查并构造最优方案。",
                "L4",
            ),
            (
                "周期问题",
                "先构造周期，再按余数定位第几项。",
                "L3",
            ),
            (
                "周期问题",
                "多个周期嵌套，还要处理边界分类回查。",
                "L4",
            ),
            (
                "博弈策略",
                "两人轮流操作，需要构造对称策略并回查必胜条件。",
                "L4",
            ),
            (
                "数论约束",
                "需要先做同余分类，再枚举候选并约束回查。",
                "L4",
            ),
            (
                "图形割补",
                "识别单个几何模型后，还要添加辅助线并组织面积比链。",
                "L4",
            ),
        ],
    )
    def test_topic_anchor_raises_typical_entrance_exam_variants(
        self,
        knowledge_point,
        question_text,
        expected_level,
    ):
        result = classify_dim4_topic_level(
            knowledge_point,
            question_text,
            {
                "strategy_role": "core",
                "template_fit": "adapted",
                "breakthrough_type": "none",
                "strategy_shift_count": "0",
                "construction_requirement": "none",
                "exploration_space": "none",
                "representation_reframe": "minor",
                "transfer_distance": "near",
                "path_openness": "single",
                "dead_end_risk": "low",
                "global_strategy_required": 0,
                "image_dependency": "none",
                "evidence_summary": "",
            },
        )

        assert result is not None
        assert result["topic_level"] == expected_level

    @pytest.mark.parametrize(
        ("knowledge_point", "question_text"),
        [
            ("工程问题", "甲单独做要6天，乙单独做要9天，两人合作几天完成。"),
            ("行程问题", "甲乙两人同时相向而行，直接根据速度和求相遇时间。"),
            ("方案比较", "直接比较两个给定方案的费用，选较少的一种。"),
        ],
    )
    def test_topic_anchor_keeps_direct_templates_low(
        self,
        knowledge_point,
        question_text,
    ):
        result = classify_dim4_topic_level(
            knowledge_point,
            question_text,
            {
                "strategy_role": "core",
                "template_fit": "direct",
                "breakthrough_type": "none",
                "strategy_shift_count": "0",
                "construction_requirement": "none",
                "exploration_space": "none",
                "representation_reframe": "none",
                "transfer_distance": "near",
                "path_openness": "single",
                "dead_end_risk": "low",
                "global_strategy_required": 0,
                "image_dependency": "none",
                "evidence_summary": "",
            },
        )

        assert result is not None
        assert result["topic_level"] in {"L1", "L2"}

    @pytest.mark.parametrize(
        ("feature_overrides", "expected_level"),
        [
            (
                {
                    "template_fit": "reframed",
                    "breakthrough_type": "strategy_shift",
                    "strategy_shift_count": "1",
                    "exploration_space": "bounded",
                    "dead_end_risk": "medium",
                },
                "L3",
            ),
            (
                {
                    "template_fit": "reframed",
                    "breakthrough_type": "strategy_shift",
                    "strategy_shift_count": "2",
                    "construction_requirement": "case_construction",
                    "path_openness": "multiple_paths",
                    "dead_end_risk": "medium",
                },
                "L4",
            ),
        ],
    )
    def test_strategy_facts_raise_reframed_variants_without_text_keywords(
        self,
        feature_overrides,
        expected_level,
    ):
        feature = {
            "strategy_role": "core",
            "template_fit": "direct",
            "breakthrough_type": "none",
            "strategy_shift_count": "0",
            "construction_requirement": "none",
            "exploration_space": "none",
            "representation_reframe": "none",
            "transfer_distance": "near",
            "path_openness": "single",
            "dead_end_risk": "low",
            "global_strategy_required": 0,
            "image_dependency": "none",
            "evidence_summary": "",
        }
        feature.update(feature_overrides)

        result = classify_dim4_topic_level("工程问题", "常规工程应用题。", feature)

        assert result is not None
        assert result["topic_level"] == expected_level

    def test_dim4_topic_fallback_details_are_recorded(self, scorer):
        result = scorer.score(
            {
                "knowledge_point": "未知专题",
                "topic_level": "L4",
                "level_source": "llm_fallback",
                "anchor_evidence": "需要构造并分类筛选。",
                "fallback_used": True,
                "fallback_confidence": 0.82,
                "evidence_summary": "LLM 兜底判定为知识点内高阶变式。",
            }
        )

        assert result.applicable is True
        assert result.level == 4
        assert result.details["level_source"] == "llm_fallback"
        assert result.details["fallback_used"] is True
        assert result.details["fallback_confidence"] == 0.82


class TestDim4Applicability:
    def test_topic_level_is_applicable_without_legacy_strategy_fields(self):
        result = evaluate_dim4_applicability(
            "典型牛吃草变式题。",
            {
                "knowledge_point": "牛吃草",
                "topic_level": "L3",
                "level_source": "knowledge_anchor",
                "anchor_evidence": "需要识别排队增长伪装。",
                "fallback_used": False,
                "fallback_confidence": 0.0,
            },
            llm_confidence=0.86,
        )

        assert result["status"] == "applicable"

    def test_l1_topic_level_is_excluded_without_core_innovation(self):
        result = evaluate_dim4_applicability(
            "直接套用工程问题效率公式。",
            {
                "knowledge_point": "工程问题",
                "topic_level": "L1",
                "level_source": "knowledge_anchor",
                "strategy_role": "core",
                "template_fit": "direct",
                "breakthrough_type": "none",
                "strategy_shift_count": "0",
                "construction_requirement": "none",
                "exploration_space": "none",
                "representation_reframe": "none",
                "transfer_distance": "near",
                "path_openness": "single",
                "dead_end_risk": "low",
                "global_strategy_required": 0,
                "image_dependency": "none",
                "evidence_summary": "基础模板题。",
                "applicability_confidence": 0.9,
            },
            llm_confidence=0.9,
        )

        assert result["status"] == "not_applicable"
        assert "L1" in result["reason"]

    def test_l2_topic_level_without_light_variant_is_excluded(self):
        result = evaluate_dim4_applicability(
            "普通两人合作工程题。",
            {
                "knowledge_point": "工程问题",
                "topic_level": "L2",
                "level_source": "knowledge_anchor",
                "strategy_role": "core",
                "template_fit": "direct",
                "breakthrough_type": "none",
                "strategy_shift_count": "0",
                "construction_requirement": "none",
                "exploration_space": "none",
                "representation_reframe": "none",
                "transfer_distance": "near",
                "path_openness": "single",
                "dead_end_risk": "low",
                "global_strategy_required": 0,
                "image_dependency": "none",
                "evidence_summary": "缺少轻变式证据。",
                "applicability_confidence": 0.9,
            },
            llm_confidence=0.9,
        )

        assert result["status"] == "not_applicable"
        assert "L2" in result["reason"]

    def test_l2_topic_level_with_light_variant_is_applicable(self):
        result = evaluate_dim4_applicability(
            "工程问题中问法有轻微变化，需要简单设置后再代入。",
            {
                "knowledge_point": "工程问题",
                "topic_level": "L2",
                "level_source": "knowledge_anchor",
                "strategy_role": "core",
                "template_fit": "adapted",
                "breakthrough_type": "none",
                "strategy_shift_count": "0",
                "construction_requirement": "simple_setup",
                "exploration_space": "bounded",
                "representation_reframe": "minor",
                "transfer_distance": "near",
                "path_openness": "single",
                "dead_end_risk": "medium",
                "global_strategy_required": 0,
                "image_dependency": "none",
                "evidence_summary": "有轻度变式和简单设置。",
                "applicability_confidence": 0.9,
            },
            llm_confidence=0.9,
        )

        assert result["status"] == "applicable"

    def test_dim4_review_failed_source_goes_to_review(self):
        result = evaluate_dim4_applicability(
            "需要判断知识点内创新等级。",
            {
                "knowledge_point": "未知专题",
                "topic_level": "",
                "level_source": "review_failed",
                "fallback_used": True,
                "fallback_error": "invalid JSON",
            },
            llm_confidence=0.86,
        )

        assert result["status"] == "review"
        assert any("invalid JSON" in item for item in result["warnings"])

    def test_core_strategy_breakthrough_is_applicable(self):
        result = evaluate_dim4_applicability(
            "先尝试构造一个中间量，再比较不同方案哪条路更稳。",
            {
                "strategy_role": "core",
                "template_fit": "reframed",
                "breakthrough_type": "constructive",
                "strategy_shift_count": "2",
                "construction_requirement": "custom_construction",
                "exploration_space": "branched",
                "representation_reframe": "structural",
                "transfer_distance": "far",
                "path_openness": "multiple_paths",
                "dead_end_risk": "high",
                "global_strategy_required": 1,
                "image_dependency": "none",
                "evidence_summary": "需要主动换路并构造中间对象。",
                "applicability_confidence": 0.86,
            },
            llm_confidence=0.86,
        )

        assert result["status"] == "applicable"

    def test_direct_template_problem_is_not_applicable(self):
        result = evaluate_dim4_applicability(
            "按常规方法求长方形面积。",
            {
                "strategy_role": "core",
                "template_fit": "direct",
                "breakthrough_type": "none",
                "strategy_shift_count": "0",
                "construction_requirement": "none",
                "exploration_space": "none",
                "representation_reframe": "none",
                "transfer_distance": "near",
                "path_openness": "single",
                "dead_end_risk": "low",
                "global_strategy_required": 0,
                "image_dependency": "none",
                "evidence_summary": "只需直接套用常规模板。",
                "applicability_confidence": 0.92,
            },
            llm_confidence=0.92,
        )

        assert result["status"] == "not_applicable"

    def test_missing_dim4_facts_go_to_review(self):
        result = evaluate_dim4_applicability(
            "请设计一种拼法并说明理由。",
            {
                "strategy_role": "core",
                "template_fit": "non_routine",
                "evidence_summary": "缺少完整策略创新事实。",
            },
            llm_confidence=0.8,
        )

        assert result["status"] == "review"
        assert any("关键策略创新事实字段" in item for item in result["warnings"])

    def test_conflicting_direct_template_goes_to_review(self):
        result = evaluate_dim4_applicability(
            "尝试不同构造方案，找出所有满足条件的结果。",
            {
                "strategy_role": "core",
                "template_fit": "direct",
                "breakthrough_type": "exploratory_search",
                "strategy_shift_count": "2",
                "construction_requirement": "custom_construction",
                "exploration_space": "open",
                "representation_reframe": "creative",
                "transfer_distance": "far",
                "path_openness": "multiple_answers",
                "dead_end_risk": "high",
                "global_strategy_required": 1,
                "image_dependency": "none",
                "evidence_summary": "字段组合存在明显冲突。",
                "applicability_confidence": 0.83,
            },
            llm_confidence=0.83,
        )

        assert result["status"] == "review"
        assert any("冲突" in item or "direct" in item for item in result["warnings"])

    def test_image_cropped_flag_does_not_block_reliable_dim4(self):
        result = evaluate_dim4_applicability(
            "需要先换一个角度，把积分情况转成可枚举的方案再筛选。",
            {
                "strategy_role": "core",
                "template_fit": "reframed",
                "breakthrough_type": "strategy_shift",
                "strategy_shift_count": "1",
                "construction_requirement": "case_construction",
                "exploration_space": "bounded",
                "representation_reframe": "structural",
                "transfer_distance": "medium",
                "path_openness": "single",
                "dead_end_risk": "medium",
                "global_strategy_required": 0,
                "image_dependency": "none",
                "evidence_summary": "需要从直接计算改为方案构造与筛选。",
                "applicability_confidence": 0.87,
            },
            llm_confidence=0.87,
            parse_audit={"image_cropped": True, "block_completeness": 0.8},
        )

        assert result["status"] == "applicable"

    def test_low_confidence_low_burden_dim4_is_not_applicable(self):
        result = evaluate_dim4_applicability(
            "按常规模板求平均数。",
            {
                "strategy_role": "supporting",
                "template_fit": "direct",
                "breakthrough_type": "none",
                "strategy_shift_count": "0",
                "construction_requirement": "none",
                "exploration_space": "none",
                "representation_reframe": "none",
                "transfer_distance": "near",
                "path_openness": "single",
                "dead_end_risk": "low",
                "global_strategy_required": 0,
                "image_dependency": "none",
                "evidence_summary": "直接套用常规模板。",
                "applicability_confidence": 0.3,
            },
            llm_confidence=0.3,
        )

        assert result["status"] == "not_applicable"

    def test_reference_review_required_goes_to_review(self):
        result = evaluate_dim4_applicability(
            "按常规模板求平均数。",
            {
                "strategy_role": "core",
                "template_fit": "direct",
                "breakthrough_type": "none",
                "strategy_shift_count": "0",
                "construction_requirement": "none",
                "exploration_space": "none",
                "representation_reframe": "none",
                "transfer_distance": "near",
                "path_openness": "single",
                "dead_end_risk": "low",
                "global_strategy_required": 0,
                "image_dependency": "none",
                "evidence_summary": "直接套用常规模板。",
                "applicability_confidence": 0.9,
                "reference_review_required": True,
                "warning": "相似高思参考题显示策略创新负担，需复核。",
            },
            llm_confidence=0.9,
        )

        assert result["status"] == "review"
        assert any("高思参考题" in item for item in result["warnings"])


class TestDim5ReferenceCalibration:
    @staticmethod
    def _standard(entries):
        standard = WorkbookReferenceStandard.__new__(WorkbookReferenceStandard)
        standard.entries = entries
        return standard

    @staticmethod
    def _challenge_question_entry(**overrides):
        payload = {
            "source": "gaosi_question_pdf",
            "sheet_name": "",
            "category": "高思导引",
            "title": "抽屉原理超越篇例题",
            "track": "高思导引",
            "grade_hint": "6年级",
            "keywords": ("抽屉原理", "组合计数"),
            "grade": "6",
            "section_level": "challenge",
            "section_label": "超越篇",
            "question_no": "1",
            "question_text": "有若干个抽屉和苹果，证明至少有一个抽屉中苹果数量满足指定条件。",
        }
        payload.update(overrides)
        return ReferenceEntry(**payload)

    def test_dim5_challenge_question_strength_at_least_two_enters_beyond(self):
        entry = self._challenge_question_entry()
        standard = self._standard([entry])

        result = standard.calibrate_feature(
            "dim5",
            {
                "band": "5、6年级校内课本难度",
                "sublevel": "mid",
                "core_knowledge_units": ["抽屉原理"],
                "knowledge_tags": ["组合计数"],
            },
            question_text=entry.question_text,
            question_summary="抽屉原理计数题",
            analysis_facts={"core_knowledge_points": ["抽屉原理"]},
        )

        assert result["band"] == "高思导引超越篇难度"
        assert result["gaosi_section_level"] == "challenge"
        assert result["band_source"] == "question_bank"
        assert result["calibration"]["question_level_match_strength"] >= 2

    def test_dim5_diagram_partial_challenge_is_review_only(self):
        entry = self._challenge_question_entry(
            title="圆内阴影面积超越题",
            keywords=("阴影面积", "圆", "组合图形"),
            question_text="如图阴影面积由两个半圆和正方形组合求解",
            has_diagram=True,
        )
        standard = self._standard([entry])

        result = standard.calibrate_feature(
            "dim5",
            {
                "band": "5、6年级校内课本难度",
                "sublevel": "mid",
                "core_knowledge_units": ["圆", "组合图形"],
                "knowledge_tags": ["阴影面积"],
            },
            question_text="如图阴影面积由两个半圆和正方形组合求面积",
            question_summary="组合图形阴影面积",
            analysis_facts={"visual_elements": ["圆", "正方形"]},
        )

        assert result["band"] == "5、6年级校内课本难度"
        assert result["need_manual_review"] is True
        assert "图形依赖" in result["warning"]
        assert result["calibration"]["can_override_model"] is False
        assert result["calibration"]["band_source"] == "audit_only"
        assert "diagram_partial_match" in result["calibration"]["question_level_match_quality"]

    def test_dim5_topic_only_challenge_does_not_force_beyond(self):
        standard = self._standard(
            [
                ReferenceEntry(
                    source="gaosi_pdf",
                    sheet_name="",
                    category="高思导引",
                    title="抽屉原理",
                    track="超越篇",
                    grade_hint="6年级",
                    keywords=("抽屉原理", "组合计数"),
                    question_text="",
                )
            ]
        )

        result = standard.calibrate_feature(
            "dim5",
            {
                "band": "5、6年级校内课本难度",
                "sublevel": "mid",
                "core_knowledge_units": ["抽屉原理"],
                "knowledge_tags": ["组合计数"],
            },
            question_text="用抽屉原理解决组合计数问题。",
            question_summary="抽屉原理",
            analysis_facts={"core_knowledge_points": ["抽屉原理"]},
        )

        assert result["band"] == "5、6年级校内课本难度"
        assert result["calibration"]["band_source"] == "audit_only"
        assert "专题/目录" in result["warning"]

    def test_dim5_olympiad_terms_are_not_lowered_by_generic_school_entry(self):
        challenge = self._challenge_question_entry(
            title="博弈策略超越题",
            keywords=("博弈", "对称策略"),
            question_text="甲乙进行博弈，需要利用对称策略证明先手必胜。",
        )
        school_generic = ReferenceEntry(
            source="school",
            sheet_name="",
            category="校内",
            title="策略",
            track="校内",
            grade_hint="5年级",
            keywords=("策略",),
        )
        standard = self._standard([school_generic, challenge])

        result = standard.calibrate_feature(
            "dim5",
            {
                "band": "5、6年级校内课本难度",
                "sublevel": "mid",
                "core_knowledge_units": ["博弈"],
                "knowledge_tags": ["对称策略"],
                "competition_signal": "strong",
            },
            question_text="甲乙进行博弈，需要利用对称策略证明先手必胜。",
            question_summary="博弈对称策略",
            analysis_facts={"core_methods": ["对称策略"]},
        )

        assert result["band"] == "高思导引超越篇难度"
        assert result["calibration"]["matched_entries"][0]["section_label"] == "超越篇"


class TestDim5Retry:
    class _FakeLLM:
        def __init__(self):
            self.calls = 0

        async def chat(self, *args, **kwargs):
            self.calls += 1
            return json.dumps(
                {
                    "band": "高思导引超越篇难度",
                    "sublevel": "high",
                    "gaosi_grade": "6",
                    "gaosi_section_level": "challenge",
                    "gaosi_section_label": "超越篇",
                    "gaosi_classification_source": "llm_retry",
                    "evidence_summary": "参考候选含高思导引超越篇题目。",
                    "knowledge_tags": ["博弈"],
                    "core_knowledge_units": ["博弈"],
                    "confidence": 0.86,
                },
                ensure_ascii=False,
            )

    class _FakeReference:
        def gaosi_question_candidates(self, *args, **kwargs):
            return [
                {
                    "section_level": "challenge",
                    "section_label": "超越篇",
                    "track": "高思导引",
                    "similarity_strength": 2,
                    "match_quality": "diagram_partial_match",
                }
            ]

    @pytest.mark.asyncio
    async def test_valid_non_beyond_dim5_retries_when_candidate_contains_challenge(self):
        parser = AIParser.__new__(AIParser)
        parser.llm = self._FakeLLM()
        parser.reference_standard = self._FakeReference()
        normalized_features = {
            "dim5_knowledge": {
                "band": "5、6年级校内课本难度",
                "sublevel": "mid",
                "core_knowledge_units": ["博弈"],
                "knowledge_tags": ["对称策略"],
            }
        }
        question = ParsedQuestion(
            question_no="13",
            question_type=QuestionType.SOLUTION,
            raw_text="甲乙博弈，利用对称策略证明先手必胜。",
        )

        await parser._ensure_dim5_band_with_retry(
            normalized_features,
            question=question,
            question_summary="博弈对称策略",
            analysis_facts={"core_knowledge_points": ["博弈"], "core_methods": ["对称策略"]},
            retry_required=False,
        )

        assert parser.llm.calls == 1
        assert normalized_features["dim5_knowledge"]["band"] == "高思导引超越篇难度"
        assert normalized_features["dim5_knowledge"]["gaosi_section_level"] == "challenge"
        assert normalized_features["dim5_knowledge"]["band_source"] == "llm_dim5_retry"


class TestDim5KnowledgeScorer:
    """测试维度5：知识点广度评分器"""

    @pytest.fixture
    def scorer(self):
        return Dim5KnowledgeScorer()

    def test_lowest_grade_level(self, scorer):
        features = {
            "band": "4年级及以前校内课本难度",
            "sublevel": "high",
            "evidence_summary": "本题知识门槛仍停留在四年级及以前课本范围。",
            "knowledge_tags": ["整数四则", "应用题"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 2.0
        assert "整数四则" in result.evidence

    def test_middle_school_equivalent_band(self, scorer):
        features = {
            "band": "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
            "sublevel": "low",
            "evidence_summary": "最高核心知识门槛已达到初中校内或高思拓展层。",
            "evidence_tags": ["比例", "一次方程"],
            "knowledge_tags": ["比例", "一次方程", "行程问题"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 6.5
        assert "一次方程" in result.evidence

    def test_dim5_extra_fact_fields_keep_banded_scoring(self, scorer):
        features = {
            "band": "5、6年级校内课本难度",
            "sublevel": "mid",
            "evidence_summary": "核心知识单元为分数和比例，属于同类量关系整合。",
            "knowledge_tags": ["分数", "比例"],
            "core_knowledge_units": ["分数", "比例"],
            "supporting_knowledge_units": ["数量关系"],
            "knowledge_family_count": "2",
            "knowledge_integration": "same_family_combo",
            "novel_definition_dependency": "none",
            "competition_signal": "none",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 3.0
        assert result.details["band"] == "5、6年级校内课本难度"
        assert result.details["sublevel"] == "mid"
        assert result.details["knowledge_source_bucket"] == "school"

    def test_transcend_level(self, scorer):
        features = {
            "band": "高思导引超越篇难度",
            "sublevel": "mid",
            "evidence_summary": "知识结构明显超过课内与拓展篇上限。",
            "knowledge_tags": ["组合计数", "复杂数论"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 9.0
        assert result.level == 5
        assert result.details["knowledge_source_bucket"] == "beyond"

    def test_junior_bridge_bucket_for_middle_school_signal(self, scorer):
        features = {
            "band": "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
            "sublevel": "mid",
            "evidence_summary": "需要使用七上一次方程作为前置知识。",
            "knowledge_tags": ["一次方程", "比例关系"],
            "core_knowledge_units": ["一次方程"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.details["knowledge_source_bucket"] == "junior_bridge"

    def test_gaosi_guide_book_title_does_not_force_beyond_bucket(self, scorer):
        features = {
            "band": "4年级及以前高思导引拓展篇及以下难度",
            "sublevel": "mid",
            "evidence_summary": "命中高思导引三年级目录。",
            "knowledge_tags": ["找规律"],
            "calibration": {
                "matched_entries": [
                    {
                        "source": "gaosi_pdf",
                        "title": "找规律",
                        "track": "高思导引",
                        "grade_hint": "3年级",
                        "note": "竞赛数学导引 三年级；第4讲；目录OCR页14",
                    }
                ]
            },
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.details["knowledge_source_bucket"] == "low_gaosi"

    def test_classic_or_competition_signals_do_not_force_beyond_bucket(self, scorer):
        features = {
            "band": "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
            "sublevel": "mid",
            "evidence_summary": "命中经典奥数与竞赛备考目录，但未命中超越篇题目。",
            "knowledge_tags": ["牛吃草问题", "经典奥数"],
            "competition_signal": "strong",
            "calibration": {
                "matched_entries": [
                    {"source": "classic", "track": "经典奥数", "grade_hint": "六年级"},
                    {"source": "competition", "track": "竞赛备考", "grade_hint": "六年级"},
                ]
            },
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.details["knowledge_source_bucket"] == "high_gaosi"

    def test_gaosi_extension_section_overrides_low_school_band(self, scorer):
        result = scorer.score(
            {
                "band": "4年级及以前校内课本难度",
                "sublevel": "low",
                "gaosi_grade": "4年级",
                "gaosi_section_level": "extension",
                "gaosi_section_label": "拓展篇",
                "evidence_summary": "题目级高思参考命中四年级拓展篇。",
                "knowledge_tags": ["数论约束"],
            }
        )

        assert result.applicable is True
        assert result.score == 5.0
        assert result.details["band"] == "4年级及以前高思导引拓展篇及以下难度"
        assert result.details["sublevel"] == "mid"
        assert result.details["knowledge_source_bucket"] == "low_gaosi"
        assert result.details["band_source"] == "gaosi_section_override"

    def test_gaosi_extension_section_overrides_high_school_band(self, scorer):
        result = scorer.score(
            {
                "band": "5、6年级校内课本难度",
                "sublevel": "mid",
                "gaosi_grade": "6",
                "gaosi_section_level": "extension",
                "gaosi_section_label": "拓展篇",
                "evidence_summary": "题目级高思参考命中六年级拓展篇。",
                "knowledge_tags": ["博弈策略"],
            }
        )

        assert result.applicable is True
        assert result.score == 7.0
        assert result.details["band"] == "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度"
        assert result.details["sublevel"] == "mid"
        assert result.details["knowledge_source_bucket"] == "high_gaosi"

    def test_gaosi_interest_and_challenge_sections_map_to_expected_buckets(self, scorer):
        interest = scorer.score(
            {
                "band": "4年级及以前校内课本难度",
                "sublevel": "high",
                "gaosi_grade": "三年级",
                "gaosi_section_level": "interest",
                "gaosi_section_label": "兴趣篇",
                "evidence_summary": "题目级高思参考命中三年级兴趣篇。",
                "knowledge_tags": ["枚举"],
            }
        )
        challenge = scorer.score(
            {
                "band": "5、6年级校内课本难度",
                "sublevel": "high",
                "gaosi_grade": "6年级",
                "gaosi_section_level": "challenge",
                "gaosi_section_label": "超越篇",
                "evidence_summary": "题目级高思参考命中六年级超越篇。",
                "knowledge_tags": ["复杂计数"],
            }
        )

        assert interest.applicable is True
        assert interest.score == 4.5
        assert interest.details["knowledge_source_bucket"] == "low_gaosi"
        assert challenge.applicable is True
        assert challenge.score == 9.5
        assert challenge.details["knowledge_source_bucket"] == "beyond"

    def test_explicit_gaosi_challenge_section_can_enter_beyond_bucket(self, scorer):
        features = {
            "band": "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
            "sublevel": "high",
            "evidence_summary": "题目级参考库命中六年级超越篇题目。",
            "gaosi_section_level": "challenge",
            "gaosi_section_label": "超越篇",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.details["knowledge_source_bucket"] == "beyond"

    def test_invalid_knowledge_band(self, scorer):
        result = scorer.score({"band": "未知", "sublevel": "high"})

        assert result.applicable is False
        assert result.score == 0.0


class TestDim6LogicScorer:
    """测试维度6：逻辑链条评分器"""

    @pytest.fixture
    def scorer(self):
        return Dim6LogicScorer()

    def test_l1_direct_linking(self, scorer):
        features = {
            "reasoning_role": "core",
            "chain_span": "1",
            "hidden_dependency": "none",
            "branch_control": "none",
            "reversibility": "none",
            "verification_requirement": "none",
            "abstraction_bridge_count": "0",
            "constraint_coupling": "single",
            "global_consistency_required": 0,
            "conclusion_stability": "direct",
            "evidence_summary": "从显式条件直接串联到结论。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 2.0
        assert result.level_label == "L1 直接串联"

    def test_l3_multi_step_linking(self, scorer):
        features = {
            "reasoning_role": "core",
            "chain_span": "3-4",
            "hidden_dependency": "cross_condition",
            "branch_control": "none",
            "reversibility": "none",
            "verification_requirement": "constraint_backcheck",
            "abstraction_bridge_count": "1",
            "constraint_coupling": "coupled",
            "global_consistency_required": 0,
            "conclusion_stability": "edge_sensitive",
            "evidence_summary": "需要串联多个条件并回查约束。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 6.0
        assert result.level_label == "L3 多步联结"

    def test_l4_branch_and_backcheck(self, scorer):
        features = {
            "reasoning_role": "core",
            "chain_span": "3-4",
            "hidden_dependency": "global",
            "branch_control": "explicit_cases",
            "reversibility": "backward",
            "verification_requirement": "constraint_backcheck",
            "abstraction_bridge_count": "2",
            "constraint_coupling": "coupled",
            "global_consistency_required": 1,
            "conclusion_stability": "edge_sensitive",
            "evidence_summary": "需要分类、回查并维持全局一致。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.level_label == "L4 分支与回查"

    def test_l5_global_multi_branch(self, scorer):
        features = {
            "reasoning_role": "core",
            "chain_span": "5+",
            "hidden_dependency": "global",
            "branch_control": "multi_branch",
            "reversibility": "bidirectional",
            "verification_requirement": "full_consistency",
            "abstraction_bridge_count": "3+",
            "constraint_coupling": "nested",
            "global_consistency_required": 1,
            "conclusion_stability": "exhaustive",
            "evidence_summary": "需要多分支收束并做全局一致性检验。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 9.5
        assert result.level_label == "L5 高阶收束"

    def test_non_core_reasoning_returns_na(self, scorer):
        result = scorer.score(
            {
                "reasoning_role": "supporting",
                "chain_span": "2",
                "hidden_dependency": "local",
                "branch_control": "none",
                "reversibility": "none",
                "verification_requirement": "result_check",
                "abstraction_bridge_count": "0",
                "constraint_coupling": "single",
                "global_consistency_required": 0,
                "conclusion_stability": "edge_sensitive",
                "evidence_summary": "逻辑推进不是核心门槛。",
            }
        )

        assert result.applicable is False
        assert result.score == 0.0

    def test_queue_growth_application_maps_to_l4(self, scorer):
        features = {
            "reasoning_role": "core",
            "chain_span": "3-4",
            "hidden_dependency": "cross_condition",
            "branch_control": "none",
            "reversibility": "none",
            "verification_requirement": "constraint_backcheck",
            "abstraction_bridge_count": "2",
            "constraint_coupling": "coupled",
            "global_consistency_required": 1,
            "conclusion_stability": "edge_sensitive",
            "logic_structure_types": ["queue_growth_chain"],
            "state_transition_count": "2",
            "case_count_band": "none",
            "backtrack_depth": "0",
            "consistency_constraint_count": "2-3",
            "phase_count_band": "3-4",
            "periodic_cycle_dependency": 0,
            "optimization_requirement": "none",
            "evidence_summary": "检票排队题需要串联原有队伍、持续到达和多个检票口消耗关系。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.details["dim6_level"] == "L4"
        assert result.details["logic_structure_types"] == ["queue_growth_chain"]

    def test_simple_work_rate_chain_maps_to_l3(self, scorer):
        features = {
            "reasoning_role": "core",
            "chain_span": "2",
            "hidden_dependency": "local",
            "branch_control": "none",
            "reversibility": "none",
            "verification_requirement": "result_check",
            "abstraction_bridge_count": "1",
            "constraint_coupling": "single",
            "global_consistency_required": 0,
            "conclusion_stability": "edge_sensitive",
            "logic_structure_types": ["work_rate_chain"],
            "state_transition_count": "1",
            "case_count_band": "none",
            "backtrack_depth": "0",
            "consistency_constraint_count": "1",
            "phase_count_band": "2",
            "periodic_cycle_dependency": 0,
            "optimization_requirement": "none",
            "evidence_summary": "普通两人合作工程题只需要局部效率链路推进。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 6.0
        assert result.details["dim6_level"] == "L3"

    def test_multi_stage_profit_chain_maps_to_l4(self, scorer):
        features = {
            "reasoning_role": "core",
            "chain_span": "3-4",
            "hidden_dependency": "cross_condition",
            "branch_control": "none",
            "reversibility": "none",
            "verification_requirement": "constraint_backcheck",
            "abstraction_bridge_count": "2",
            "constraint_coupling": "coupled",
            "global_consistency_required": 1,
            "conclusion_stability": "edge_sensitive",
            "logic_structure_types": ["multi_stage_state_change", "percentage_base_shift_chain"],
            "state_transition_count": "3+",
            "case_count_band": "none",
            "backtrack_depth": "0",
            "consistency_constraint_count": "2-3",
            "phase_count_band": "3-4",
            "periodic_cycle_dependency": 0,
            "optimization_requirement": "none",
            "evidence_summary": "利润题包含标价、寄售、损坏赔偿和剩余出售等连续状态变化。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.details["dim6_level"] == "L4"

    def test_travel_after_meeting_chain_maps_to_l4(self, scorer):
        features = {
            "reasoning_role": "core",
            "chain_span": "3-4",
            "hidden_dependency": "cross_condition",
            "branch_control": "none",
            "reversibility": "none",
            "verification_requirement": "constraint_backcheck",
            "abstraction_bridge_count": "2",
            "constraint_coupling": "coupled",
            "global_consistency_required": 1,
            "conclusion_stability": "edge_sensitive",
            "logic_structure_types": ["travel_meeting_chasing_chain"],
            "state_transition_count": "2",
            "case_count_band": "none",
            "backtrack_depth": "0",
            "consistency_constraint_count": "2-3",
            "phase_count_band": "3-4",
            "periodic_cycle_dependency": 0,
            "optimization_requirement": "none",
            "evidence_summary": "行程题需要处理相遇前后速度变化并回查剩余路程约束。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.details["dim6_level"] == "L4"

    def test_bounded_optimization_comparison_maps_to_l4(self, scorer):
        features = {
            "reasoning_role": "core",
            "chain_span": "3-4",
            "hidden_dependency": "cross_condition",
            "branch_control": "explicit_cases",
            "reversibility": "none",
            "verification_requirement": "constraint_backcheck",
            "abstraction_bridge_count": "1",
            "constraint_coupling": "coupled",
            "global_consistency_required": 1,
            "conclusion_stability": "edge_sensitive",
            "logic_structure_types": ["bounded_case_enumeration", "optimization_comparison"],
            "state_transition_count": "1",
            "case_count_band": "3-5",
            "backtrack_depth": "0",
            "consistency_constraint_count": "2-3",
            "phase_count_band": "2",
            "periodic_cycle_dependency": 0,
            "optimization_requirement": "bounded_choice",
            "evidence_summary": "票价或铺管方案题需要枚举有限方案并回查最优约束。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.details["dim6_level"] == "L4"

    def test_global_nested_constraints_map_to_l5(self, scorer):
        features = {
            "reasoning_role": "core",
            "chain_span": "5+",
            "hidden_dependency": "global",
            "branch_control": "multi_branch",
            "reversibility": "bidirectional",
            "verification_requirement": "full_consistency",
            "abstraction_bridge_count": "3+",
            "constraint_coupling": "nested",
            "global_consistency_required": 1,
            "conclusion_stability": "exhaustive",
            "logic_structure_types": ["global_constraint_system", "reverse_process_chain"],
            "state_transition_count": "3+",
            "case_count_band": "3-5",
            "backtrack_depth": "3+",
            "consistency_constraint_count": "4+",
            "phase_count_band": "5+",
            "periodic_cycle_dependency": 0,
            "optimization_requirement": "none",
            "evidence_summary": "多对象分配题需要嵌套约束、三层以上倒推和全局一致性收束。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 9.5
        assert result.details["dim6_level"] == "L5"

    def test_direct_application_problem_stays_not_applicable_for_dim6(self):
        result = evaluate_dim6_applicability(
            "一件商品单价8元，买3件一共多少元？",
            {
                "reasoning_role": "supporting",
                "chain_span": "1",
                "hidden_dependency": "none",
                "branch_control": "none",
                "reversibility": "none",
                "verification_requirement": "none",
                "abstraction_bridge_count": "0",
                "constraint_coupling": "single",
                "global_consistency_required": 0,
                "conclusion_stability": "direct",
                "logic_structure_types": [],
                "state_transition_count": "0",
                "case_count_band": "none",
                "backtrack_depth": "0",
                "consistency_constraint_count": "0",
                "phase_count_band": "1",
                "periodic_cycle_dependency": 0,
                "optimization_requirement": "none",
                "evidence_summary": "直接代入单价数量关系即可。",
                "applicability_confidence": 0.92,
            },
            llm_confidence=0.92,
        )

        assert result["status"] == "not_applicable"

    def test_ai_parser_normalizes_new_dim6_application_fields(self):
        parser = AIParser(llm_client=SimpleNamespace())

        normalized = parser._normalize_dim6_feature(
            {
                "reasoning_role": "core",
                "chain_span": "3-4",
                "hidden_dependency": "cross_condition",
                "branch_control": "explicit_cases",
                "reversibility": "none",
                "verification_requirement": "constraint_backcheck",
                "abstraction_bridge_count": "2",
                "constraint_coupling": "coupled",
                "global_consistency_required": 1,
                "conclusion_stability": "edge_sensitive",
                "logic_structure_types": [
                    "queue_growth_chain",
                    "unknown_type",
                    "optimization_comparison",
                ],
                "state_transition_count": "3+",
                "case_count_band": "3-5",
                "backtrack_depth": "2",
                "consistency_constraint_count": "4+",
                "phase_count_band": "5+",
                "periodic_cycle_dependency": 1,
                "optimization_requirement": "bounded_choice",
            }
        )

        assert normalized["logic_structure_types"] == [
            "queue_growth_chain",
            "optimization_comparison",
        ]
        assert normalized["state_transition_count"] == "3+"
        assert normalized["case_count_band"] == "3-5"
        assert normalized["backtrack_depth"] == "2"
        assert normalized["consistency_constraint_count"] == "4+"
        assert normalized["phase_count_band"] == "5+"
        assert normalized["periodic_cycle_dependency"] == 1
        assert normalized["optimization_requirement"] == "bounded_choice"


class _LegacyDim6LogicScorer:
    """测试维度6：逻辑链条长度评分器"""

    @pytest.fixture
    def scorer(self):
        return Dim6LogicScorer()

    def test_single_step(self, scorer):
        features = {
            "key_step_count": "1",
            "has_hidden_relation": 0,
            "need_reverse_reasoning": 0,
            "has_branch": 0,
            "need_case_discussion": 0,
            "need_validation": 0,
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score <= 2.0
        assert "1个关键推理步骤" in result.evidence

    def test_six_plus_steps(self, scorer):
        features = {
            "key_step_count": "6+",
            "has_hidden_relation": 1,
            "need_reverse_reasoning": 1,
            "has_branch": 0,
            "need_case_discussion": 0,
            "need_validation": 1,
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score >= 8.0


class TestPaperAggregator:
    """测试试卷汇总引擎"""

    @pytest.fixture
    def aggregator(self):
        return PaperAggregator()

    def test_single_dimension_aggregation(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=5.0,
                dim_scores={"dim1": 6.0},
                applicable_dims=["dim1"],
                question_label_raw="1.",
                question_display_label="1.",
                page_no=1,
                dim_confidences={"dim1": 0.72},
                question_summary="分数混合运算",
                dim_reasons={"dim1": "需要完成分数加减的核心运算"},
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=3.0,
                dim_scores={"dim1": 8.0},
                applicable_dims=["dim1"],
                question_label_raw="（2）",
                question_display_label="（2）",
                page_no=2,
                dim_confidences={"dim1": 0.91},
                question_summary="比例与单位换算",
                dim_reasons={"dim1": "需要跨单位比例换算"},
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim1")

        assert result.dimension_code == "dim1"
        assert result.question_count == 2
        assert result.total_question_score == 8.0
        expected_score = (6.0 + 8.0) / 2
        assert abs(result.paper_score - expected_score) < 0.1
        assert "加权维度分" in result.evidence
        assert result.score_breakdown["pure_calculation"]["question_count"] == 2
        assert result.score_breakdown["pure_calculation"]["weight"] == 1.0
        assert "总分值" not in result.evidence
        assert "复核提示" not in result.evidence
        assert len(result.counted_questions) == 2
        assert result.counted_questions[0]["question_no"] == "2"
        assert result.counted_questions[0]["question_label_raw"] == "（2）"
        assert result.counted_questions[0]["question_display_label"] == "（2）"
        assert result.counted_questions[0]["page_no"] == 2
        assert result.counted_questions[0]["full_reason"] == "需要跨单位比例换算"

    def test_representative_questions_keep_full_reason(self, aggregator):
        full_reason = (
            "L4 高阶结构巧算：需要整体观察后化简。 "
            "依据标签：结构计算、整体化简；核心事实：完整分析需要保留；依据来源：文本。"
        )
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=8.0,
                dim_scores={"dim1": 8.0},
                applicable_dims=["dim1"],
                question_label_raw="1.",
                page_no=1,
                dim_confidences={"dim1": 0.9},
                question_summary="结构计算题",
                dim_reasons={"dim1": full_reason},
            )
        ]

        result = aggregator.aggregate(question_scores, "dim1")
        counted_question = result.counted_questions[0]

        assert counted_question["reason"] == "L4：需要整体观察后化简。 依据：文本"
        assert counted_question["full_reason"] == "L4：需要整体观察后化简"

    def test_representative_questions_strip_level_descriptor_only_at_start(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=8.0,
                dim_scores={"dim2": 8.0},
                applicable_dims=["dim2"],
                question_summary="图形重组",
                dim_reasons={
                    "dim2": "L4 结构变换想象：需要图形重组，正文中仍可说明这是结构变换想象。"
                },
                dim_confidences={"dim2": 0.9},
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=6.0,
                dim_scores={"dim2": 6.0},
                applicable_dims=["dim2"],
                question_summary="图形关系",
                dim_reasons={"dim2": "L3：需要识别两条图形关系。"},
                dim_confidences={"dim2": 0.8},
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim2")

        assert result.counted_questions[0]["full_reason"] == "L4：需要图形重组，正文中仍可说明这是结构变换想象"
        assert result.counted_questions[1]["full_reason"] == "L3：需要识别两条图形关系"

    @staticmethod
    def _dim5_question(index: int, bucket: str, *, competition_signal: str = "") -> QuestionDimensionScore:
        score_by_bucket = {
            "school": 3.0,
            "low_gaosi": 5.0,
            "high_gaosi": 7.0,
            "junior_bridge": 7.0,
            "beyond": 9.0,
            "unknown": 0.0,
        }
        return QuestionDimensionScore(
            question_id=f"q{index}",
            question_no=str(index),
            score=5.0,
            dim_scores={"dim5": score_by_bucket[bucket]},
            applicable_dims=["dim5"],
            question_summary=f"{bucket} 题",
            dim_reasons={"dim5": f"知识来源归类：{bucket}"},
            dim_confidences={"dim5": 0.9},
            dim_statuses={"dim5": "applicable"},
            dim_details={
                "dim5": {
                    "knowledge_source_bucket": bucket,
                    "competition_signal": competition_signal,
                    "knowledge_integration": "single",
                }
            },
        )

    def test_dim5_uses_question_score_average_for_school_heavy_paper(self, aggregator):
        questions = [
            self._dim5_question(index, "school")
            for index in range(1, 10)
        ] + [self._dim5_question(10, "low_gaosi")]

        result = aggregator.aggregate(questions, "dim5")

        assert result.paper_score == pytest.approx(3.2)
        assert result.level == 2
        assert result.score_breakdown["aggregation_rule"] == "题级知识广度均分"
        assert result.score_breakdown["question_score_average"] == pytest.approx(3.2)
        assert result.score_breakdown["question_score_sum"] == pytest.approx(32.0)
        assert "校内教材 90%" in result.evidence
        assert "题级平均分 3.2 分" in result.evidence

    def test_dim5_low_gaosi_mix_keeps_question_average(self, aggregator):
        questions = [
            self._dim5_question(index, "school")
            for index in range(1, 8)
        ] + [
            self._dim5_question(8, "low_gaosi"),
            self._dim5_question(9, "low_gaosi"),
            self._dim5_question(10, "high_gaosi"),
        ]

        result = aggregator.aggregate(questions, "dim5")

        assert result.paper_score == pytest.approx(3.8)
        assert result.level == 2
        assert "低段高思拓展 20%" in result.evidence

    def test_dim5_high_gaosi_mix_keeps_question_average(self, aggregator):
        questions = [
            self._dim5_question(index, "school")
            for index in range(1, 7)
        ] + [
            self._dim5_question(7, "high_gaosi"),
            self._dim5_question(8, "high_gaosi"),
            self._dim5_question(9, "high_gaosi"),
            self._dim5_question(10, "low_gaosi"),
        ]

        result = aggregator.aggregate(questions, "dim5")

        assert result.paper_score == pytest.approx(4.4)
        assert result.level == 3
        assert "高年级高思拓展 30%" in result.evidence

    def test_dim5_junior_bridge_mix_keeps_question_average(self, aggregator):
        questions = [
            self._dim5_question(index, "school")
            for index in range(1, 5)
        ] + [
            self._dim5_question(5, "high_gaosi"),
            self._dim5_question(6, "high_gaosi"),
            self._dim5_question(7, "high_gaosi"),
            self._dim5_question(8, "junior_bridge"),
            self._dim5_question(9, "junior_bridge"),
            self._dim5_question(10, "low_gaosi"),
        ]

        result = aggregator.aggregate(questions, "dim5")

        assert result.paper_score == pytest.approx(5.2)
        assert result.level == 3
        assert "初中前置 20%" in result.evidence

    def test_dim5_beyond_questions_do_not_force_level_5(self, aggregator):
        questions = [
            self._dim5_question(index, "school")
            for index in range(1, 5)
        ] + [
            self._dim5_question(5, "high_gaosi"),
            self._dim5_question(6, "high_gaosi"),
            self._dim5_question(7, "high_gaosi"),
            self._dim5_question(8, "junior_bridge"),
            self._dim5_question(9, "beyond", competition_signal="strong"),
            self._dim5_question(10, "beyond", competition_signal="strong"),
        ]

        result = aggregator.aggregate(questions, "dim5")

        assert result.paper_score == pytest.approx(5.8)
        assert result.level == 3
        assert "高思超越篇 20%" in result.evidence
        assert "超越篇命中 2 道" in result.evidence
        assert result.score_breakdown["bucket_counts"]["beyond"] == 2
        assert result.score_breakdown["bucket_ratios"]["beyond"] == 0.2

    def test_dim5_beyond_mix_has_no_composition_bonus(self, aggregator):
        questions = [
            self._dim5_question(index, "school")
            for index in range(1, 8)
        ] + [
            self._dim5_question(8, "low_gaosi"),
            self._dim5_question(9, "beyond"),
            self._dim5_question(10, "beyond"),
        ]

        result = aggregator.aggregate(questions, "dim5")

        assert result.paper_score == pytest.approx(4.4)
        assert result.score_breakdown["final_score"] == pytest.approx(4.4)
        assert "超越篇加分" not in result.evidence

    def test_dim5_unknown_bucket_without_valid_score_is_excluded_from_average(self, aggregator):
        questions = [
            self._dim5_question(index, "school")
            for index in range(1, 10)
        ] + [self._dim5_question(10, "unknown")]

        result = aggregator.aggregate(questions, "dim5")

        assert result.question_count == 9
        assert result.paper_score == pytest.approx(3.0)
        assert result.score_breakdown["bucket_counts"]["unknown"] == 1
        assert result.score_breakdown["bucket_ratios"]["unknown"] == 0.1
        assert result.score_breakdown["unknown_unscored_count"] == 1
        assert "纳入知识广度均分" in result.evidence
        assert any("未计入知识广度均分" in item for item in result.warning_messages)

    def test_dim5_unknown_bucket_with_valid_score_still_enters_average(self, aggregator):
        unknown = self._dim5_question(10, "unknown")
        unknown.dim_scores["dim5"] = 7.0
        questions = [
            self._dim5_question(index, "school")
            for index in range(1, 10)
        ] + [unknown]

        result = aggregator.aggregate(questions, "dim5")

        assert result.question_count == 10
        assert result.paper_score == pytest.approx(3.4)
        assert result.score_breakdown["bucket_counts"]["unknown"] == 1
        assert result.score_breakdown["unknown_scored_count"] == 1
        assert any("已按题级分计入知识广度均分" in item for item in result.warning_messages)

    def test_dim5_representative_questions_prioritize_score_then_bucket(self, aggregator):
        beyond = self._dim5_question(1, "beyond")
        high = self._dim5_question(2, "high_gaosi")
        junior = self._dim5_question(3, "junior_bridge")
        school = self._dim5_question(4, "school")
        high.dim_scores["dim5"] = 10.0
        junior.dim_scores["dim5"] = 9.5
        school.dim_scores["dim5"] = 9.0
        beyond.dim_scores["dim5"] = 8.0

        result = aggregator.aggregate([high, junior, school, beyond], "dim5")

        assert result.counted_questions[0]["question_no"] == "2"
        assert result.score_breakdown["beyond_question_count"] == 1

        high.dim_scores["dim5"] = 9.0
        beyond.dim_scores["dim5"] = 9.0

        result = aggregator.aggregate([high, beyond], "dim5")

        assert result.counted_questions[0]["question_no"] == "1"

    @staticmethod
    def _dim4_question(
        index: int,
        level: str,
        score: float,
        *,
        status: str = "applicable",
        reason: str = "",
        source: str = "knowledge_anchor",
    ) -> QuestionDimensionScore:
        dim_scores = {"dim4": score} if status == "applicable" else {}
        applicable_dims = ["dim4"] if status == "applicable" else []
        return QuestionDimensionScore(
            question_id=f"q{index}",
            question_no=str(index),
            score=5.0,
            dim_scores=dim_scores,
            applicable_dims=applicable_dims,
            question_summary=f"{level} dim4 题",
            dim_reasons={"dim4": reason or f"{level} 知识点内变式。"},
            dim_confidences={"dim4": 0.9},
            dim_statuses={"dim4": status},
            dim_details={"dim4": {"dim4_level": level, "level_source": source}},
        )

    def test_dim4_aggregation_excludes_l1_noise_and_exposes_breakdown(self, aggregator):
        questions = [
            self._dim4_question(1, "L3", 6.0, reason="L3：一次变式识别。"),
            self._dim4_question(2, "L4", 8.0, reason="L4：构造中间量并约束回查。"),
            self._dim4_question(3, "L5", 9.5, reason="L5：需要全局最优性证明。"),
            self._dim4_question(
                4,
                "L1",
                0.0,
                status="not_applicable",
                reason="dim4 知识点内等级为 L1 基础模板，不计入实践创新均分。",
            ),
            self._dim4_question(
                5,
                "L2",
                0.0,
                status="not_applicable",
                reason="dim4 知识点内等级为 L2，但缺少明确轻变式证据。",
            ),
            self._dim4_question(
                6,
                "L4",
                0.0,
                status="review",
                reason="dim4 策略创新事实缺失，当前题目转入人工复核。",
            ),
        ]

        result = aggregator.aggregate(questions, "dim4")

        assert result.question_count == 3
        assert result.review_question_count == 1
        assert abs(result.paper_score - ((6.0 + 8.0 + 9.5) / 3)) < 0.01
        assert result.score_breakdown["level_counts"] == {
            "L1": 0,
            "L2": 0,
            "L3": 1,
            "L4": 1,
            "L5": 1,
        }
        assert result.score_breakdown["not_applicable_count"] == 2
        assert result.score_breakdown["l1_excluded_count"] == 1
        assert result.score_breakdown["high_level_question_count"] == 2
        assert "L3 1 道、L4 1 道、L5 1 道" in result.evidence
        assert "L1 普通模板题 1 道未计入" in result.evidence

    def test_dim4_wmo_grade6_regression_reaches_eight_without_paper_bonus(self, aggregator):
        scorer = Dim4InnovationScorer()

        def feature(
            knowledge_point: str,
            topic_level: str,
            evidence_summary: str,
            evidence_tags: list[str],
            **overrides,
        ) -> dict:
            base = {
                "knowledge_point": knowledge_point,
                "topic_level": topic_level,
                "level_source": "knowledge_anchor",
                "anchor_evidence": "WMO 复赛同知识点内部变式回归样本。",
                "strategy_role": "core",
                "template_fit": "adapted",
                "breakthrough_type": "local_trick",
                "strategy_shift_count": "1",
                "construction_requirement": "simple_setup",
                "exploration_space": "bounded",
                "representation_reframe": "minor",
                "transfer_distance": "medium",
                "path_openness": "single",
                "dead_end_risk": "medium",
                "global_strategy_required": 0,
                "image_dependency": "none",
                "evidence_summary": evidence_summary,
                "evidence_tags": evidence_tags,
                "applicability_confidence": 0.9,
                "need_manual_review": 0,
                "warning": "",
            }
            base.update(overrides)
            return base

        cases = [
            ("1", feature("定义新运算", "L3", "需要先完成定义新运算结构展开，再识别倒推关系和裂项关系。", ["定义新运算", "结构展开", "倒推关系", "裂项关系"])),
            ("2", feature("逆推还原", "L3", "连续8次减半只需要沿单一路径倒推。", ["连续相同操作", "倒推模板"], strategy_role="supporting", dead_end_risk="low")),
            ("3", feature("分数裂项/结构计算", "L3", "需要识别非相邻裂项，完成长链消去并提取首尾项。", ["非相邻裂项", "长链消去", "首尾项提取"])),
            ("4", feature("圆的周长与半径关系", "L3", "需要用差分增量关系处理周长变化，并识别原半径是参数无关量。", ["差分增量", "参数无关", "无关量消去"])),
            ("5", feature("正方体三视图", "L2", "普通左视图投影，只需要一次空间投影识别。", ["三视图", "内部连线", "投影"], template_fit="direct", breakthrough_type="none", strategy_shift_count="0", construction_requirement="none", representation_reframe="none", transfer_distance="near", dead_end_risk="low", image_dependency="required")),
            ("6", feature("工程问题", "L4", "两个时间点的已完成/未完成比例需要转化并联动。", ["分数比例", "状态联动", "总量转化"])),
            ("7", feature("抽屉/分类计数", "L3", "需要位置耦合枚举，结合整除约束构造概率分母。", ["位置耦合枚举", "整除约束", "概率分母构造"], applicability_confidence=0.0, global_strategy_required=1, image_dependency="helpful")),
            ("8", feature("圆与扇形面积计算", "L4", "需要割补四个扇形并组织面积关系。", ["几何割补", "扇形", "面积组织"], image_dependency="required")),
            ("9", feature("比例百分数应用", "L2", "需要处理多状态百分数和利润率，新旧基准联动，成本下降后再降价。", ["多状态百分数", "新旧基准联动", "成本下降", "降价", "实际利润率"])),
            ("10", feature("浓度问题", "L4", "原溶液、第一次加水、第二次加水三状态联动。", ["多状态基准", "溶质不变", "状态联动"])),
            ("11", feature("9的倍数判定与数位和性质", "L4", "需要把魔术过程转化为9的倍数约束并回查删去数字。", ["数位整除", "魔术", "约束回查"])),
            ("12", feature("抽屉/分类计数", "L4", "需要先枚举满足总价16的方案，再作为抽屉数回查。", ["抽屉", "组合枚举", "约束回查"])),
            ("13", feature("博弈策略", "L4", "需要构造制胜策略，分析对手应对，进行必胜态回查并保证获胜。", ["制胜策略", "对手应对", "必胜态回查", "保证获胜"], template_fit="non_routine", breakthrough_type="strategy_shift", construction_requirement="case_construction", global_strategy_required=1)),
            ("14", feature("抽屉/分类计数", "L4", "需要构造满足安全约束的排列模式并分类讨论。", ["分类讨论", "约束回查", "排列构造"])),
            ("15", feature("数论约束", "L4", "需要用余数包含关系排除并回查多个整除约束。", ["数论约束", "整除", "回查"])),
            ("16", feature("字母代数式与整除性质", "L4", "需要按位值模式筛选候选并回查平方关系。", ["有限候选", "位值", "枚举", "回查"])),
            ("17", feature("比例百分数应用", "L3", "多个部分都与其余部分之和形成比例，需要共同约束并转化到同一个总量。", ["其余部分之和", "共同约束", "总量转化"])),
            ("18", feature("圆与长方形组合图形面积计算", "L4", "等积关系后还要割补并组织阴影面积关系。", ["几何割补", "等积关系", "面积组织"], image_dependency="required")),
            ("19", feature("三视图与立体图形", "L5", "需要在两个视图约束下分别构造最少和最多方案，并全局回查。", ["全局最优", "极值构造", "三视图"], template_fit="reframed", breakthrough_type="constructive", strategy_shift_count="2", construction_requirement="custom_construction", exploration_space="branched", global_strategy_required=1, image_dependency="required")),
            ("20", feature("规则推理与空间位置逆推", "L5", "需要把镭射反射新规则转化为路径约束并全局回查战舰位置。", ["开放探索", "规则型构造", "全局收束"], template_fit="reframed", breakthrough_type="strategy_shift", strategy_shift_count="2", construction_requirement="case_construction", exploration_space="branched", global_strategy_required=1, image_dependency="required")),
        ]

        questions = []
        score_by_question = {}
        status_by_question = {}
        for qno, dim4_feature in cases:
            status = evaluate_dim4_applicability(
                f"WMO 六年级复赛第 {qno} 题",
                dim4_feature,
                llm_confidence=0.9,
                used_image=True,
            )
            result = scorer.score(dim4_feature)
            status_by_question[qno] = status["status"]
            score_by_question[qno] = result.score
            if status["status"] == "applicable":
                questions.append(
                    QuestionDimensionScore(
                        question_id=f"q{qno}",
                        question_no=qno,
                        score=5.0,
                        dim_scores={"dim4": result.score},
                        applicable_dims=["dim4"],
                        dim_reasons={"dim4": result.evidence},
                        dim_confidences={"dim4": 0.9},
                        dim_statuses={"dim4": "applicable"},
                        dim_details={"dim4": result.details},
                    )
                )

        summary = aggregator.aggregate(questions, "dim4")

        for qno in ("1", "3", "4", "7", "9", "17"):
            assert status_by_question[qno] == "applicable"
            assert score_by_question[qno] >= 8.0
        assert score_by_question["13"] == 9.5
        assert score_by_question["2"] == 6.0
        assert score_by_question["5"] <= 6.0
        assert summary.paper_score >= 8.0

    def test_dim4_representative_questions_prioritize_high_levels(self, aggregator):
        l3 = self._dim4_question(1, "L3", 9.5, reason="L3：单次变式识别。")
        l4 = self._dim4_question(2, "L4", 8.0, reason="L4：构造并回查约束。")
        l5 = self._dim4_question(3, "L5", 6.0, reason="L5：开放探索与唯一性证明。")

        result = aggregator.aggregate([l3, l4, l5], "dim4")

        assert [item["question_no"] for item in result.counted_questions] == ["3", "2", "1"]

    def test_review_questions_are_excluded_from_average_but_keep_warning(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=5.0,
                dim_scores={"dim1": 6.0},
                applicable_dims=["dim1"],
                dim_reasons={"dim1": "需要两步常规计算"},
                dim_confidences={"dim1": 0.8},
                dim_statuses={"dim1": "applicable"},
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=6.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim1": "dim1 计算事实缺失，当前题目转入人工复核。"},
                dim_warnings={"dim1": ["dim1 缺少关键计算事实字段：step_chain。"]},
                dim_confidences={"dim1": 0.3},
                dim_statuses={"dim1": "review"},
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim1")

        assert result.question_count == 1
        assert result.review_question_count == 1
        assert result.paper_score == 6.0
        assert not any("进入复核" in item for item in result.warning_messages)

    def test_not_applicable_lightweight_dim1_is_excluded_from_average(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=5.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim1": "该题仅包含轻量直接计算，不计入整卷 dim1 自动均分。"},
                dim_statuses={"dim1": "not_applicable"},
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=6.0,
                dim_scores={"dim1": 8.0},
                applicable_dims=["dim1"],
                dim_reasons={"dim1": "需要完成多步混合计算。"},
                dim_confidences={"dim1": 0.86},
                dim_statuses={"dim1": "applicable"},
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim1")

        assert result.question_count == 1
        assert result.review_question_count == 0
        assert result.paper_score == 8.0
        assert result.total_question_score == 6.0

    @staticmethod
    def _dim1_question(
        index: int,
        score: float,
        bucket: str,
    ) -> QuestionDimensionScore:
        return QuestionDimensionScore(
            question_id=f"q{index}",
            question_no=str(index),
            score=5.0,
            dim_scores={"dim1": score},
            applicable_dims=["dim1"],
            dim_reasons={"dim1": f"{bucket} 计算负担。"},
            dim_confidences={"dim1": 0.9},
            dim_statuses={"dim1": "applicable"},
            dim_details={"dim1": {"calc_bucket": bucket, "dim1_level": "L3"}},
        )

    def test_dim1_weighted_aggregation_uses_70_30_when_pure_has_two_questions(self, aggregator):
        question_scores = [
            self._dim1_question(1, 7.0, "pure_calculation"),
            self._dim1_question(2, 7.8, "pure_calculation"),
            self._dim1_question(3, 3.0, "embedded_calculation"),
            self._dim1_question(4, 4.0, "embedded_calculation"),
        ]

        result = aggregator.aggregate(question_scores, "dim1")

        expected_score = 7.4 * 0.7 + 3.5 * 0.3
        assert abs(result.paper_score - expected_score) < 0.01
        assert result.score_breakdown["pure_calculation"]["weight"] == 0.7
        assert result.score_breakdown["embedded_calculation"]["weight"] == 0.3
        assert "纯计算 2 道" in result.evidence
        assert "嵌入式计算 2 道" in result.evidence

    def test_dim1_weighted_aggregation_uses_50_50_when_only_one_pure_question(self, aggregator):
        question_scores = [
            self._dim1_question(1, 8.0, "pure_calculation"),
            self._dim1_question(2, 4.0, "embedded_calculation"),
        ]

        result = aggregator.aggregate(question_scores, "dim1")

        assert result.paper_score == 6.0
        assert result.score_breakdown["pure_calculation"]["weight"] == 0.5
        assert result.score_breakdown["embedded_calculation"]["weight"] == 0.5

    def test_dim1_embedded_only_can_score_with_evidence_hint(self, aggregator):
        question_scores = [
            self._dim1_question(1, 4.0, "embedded_calculation"),
            self._dim1_question(2, 6.0, "embedded_calculation"),
        ]

        result = aggregator.aggregate(question_scores, "dim1")

        assert result.paper_score == 5.0
        assert result.score_breakdown["pure_calculation"]["weight"] == 0.0
        assert result.score_breakdown["embedded_calculation"]["weight"] == 1.0
        assert "本卷无纯计算专项题" in result.evidence

    def test_representative_questions_prefer_high_confidence_examples(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="4",
                score=5.0,
                dim_scores={"dim2": 4.5},
                applicable_dims=["dim2"],
                question_label_raw="4.",
                section_index_raw="一",
                page_no=1,
                question_summary="基础图形识别",
                dim_reasons={"dim2": "仅文本回退，证据较弱"},
                dim_warnings={"dim2": ["纯文本回退"]},
                dim_confidences={"dim2": 0.92},
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=5.0,
                dim_scores={"dim2": 7.5},
                applicable_dims=["dim2"],
                question_label_raw="二、",
                section_index_raw="二",
                page_no=3,
                question_summary="正方体涂色",
                dim_reasons={"dim2": "核心依赖正方体涂色模型，图像与规则证据一致"},
                dim_confidences={"dim2": 0.95},
            ),
            QuestionDimensionScore(
                question_id="q3",
                question_no="4",
                score=5.0,
                dim_scores={"dim2": 6.8},
                applicable_dims=["dim2"],
                question_label_raw="（4）",
                section_index_raw="二",
                page_no=4,
                question_summary="展开图判断",
                dim_reasons={"dim2": "核心依赖空间展开图判断，图像证据明确"},
                dim_confidences={"dim2": 0.88},
            ),
            QuestionDimensionScore(
                question_id="q4",
                question_no="1",
                score=5.0,
                dim_scores={"dim2": 5.2},
                applicable_dims=["dim2"],
                question_label_raw="1.",
                page_no=2,
                question_summary="证据为空",
                dim_reasons={"dim2": ""},
                dim_confidences={"dim2": 0.97},
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim2")

        assert len(result.counted_questions) == 2
        assert result.counted_questions[0]["question_no"] == "2"
        assert result.counted_questions[0]["question_label_raw"] == "二、"
        assert result.counted_questions[0]["question_display_label"] == "二-2"
        assert result.counted_questions[0]["page_no"] == 3
        assert result.counted_questions[1]["question_no"] == "4"
        assert result.counted_questions[1]["question_label_raw"] == "（4）"
        assert result.counted_questions[1]["question_display_label"] == "二-4"
        assert result.counted_questions[1]["page_no"] == 4
        assert all(item["page_no"] is not None for item in result.counted_questions)

    def test_representative_questions_deduplicate_same_display_label(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="4",
                score=5.0,
                dim_scores={"dim2": 7.5},
                applicable_dims=["dim2"],
                question_label_raw="4.",
                section_index_raw="二",
                page_no=2,
                question_summary="区块二第4题版本A",
                dim_reasons={"dim2": "核心依赖空间关系判断"},
                dim_confidences={"dim2": 0.96},
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="4",
                score=5.0,
                dim_scores={"dim2": 7.2},
                applicable_dims=["dim2"],
                question_label_raw="4.",
                section_index_raw="二",
                page_no=3,
                question_summary="区块二第4题版本B",
                dim_reasons={"dim2": "同一显示标签的备用样例"},
                dim_confidences={"dim2": 0.92},
            ),
            QuestionDimensionScore(
                question_id="q3",
                question_no="5",
                score=5.0,
                dim_scores={"dim2": 6.8},
                applicable_dims=["dim2"],
                question_label_raw="5.",
                section_index_raw="二",
                page_no=4,
                question_summary="区块二第5题",
                dim_reasons={"dim2": "另一道代表题"},
                dim_confidences={"dim2": 0.9},
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim2")

        assert [item["question_display_label"] for item in result.counted_questions] == ["二-4", "二-5"]

    def test_dimension_aggregation_ignores_question_score_weights(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=100.0,
                dim_scores={"dim3": 2.0},
                applicable_dims=["dim3"],
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=1.0,
                dim_scores={"dim3": 8.0},
                applicable_dims=["dim3"],
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim3")

        assert result.question_count == 2
        assert result.paper_score == 5.0

    def test_dimension_aggregation_keeps_same_score_when_all_items_equal(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=2.0,
                dim_scores={"dim3": 6.5},
                applicable_dims=["dim3"],
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=10.0,
                dim_scores={"dim3": 6.5},
                applicable_dims=["dim3"],
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim3")

        assert result.paper_score == 6.5

    def test_empty_dimension(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=5.0,
                dim_scores={"dim1": 6.0},
                applicable_dims=["dim1"],
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim2")

        assert result.question_count == 0
        assert result.paper_score == 0.0
        assert result.level == 0
        assert result.score_status == "not_covered"
        assert "自动评分未覆盖" in result.evidence

    def test_dim2_not_covered_explains_geometry_candidates(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="5",
                score=5.0,
                dim_scores={},
                applicable_dims=[],
                question_summary="如图，瓶子倒放后根据水位求容积。",
                dim_reasons={"dim2": "dim2 空间事实缺失，当前题目转入人工复核。"},
                dim_statuses={"dim2": "review"},
                dim_details={
                    "dim2": {
                        "figure_complexity": "solid_3d",
                        "geometry_model_types": ["water_displacement"],
                    }
                },
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="9",
                score=5.0,
                dim_scores={},
                applicable_dims=[],
                question_summary="普通利润应用题。",
                dim_statuses={"dim2": "not_applicable"},
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim2")

        assert result.question_count == 0
        assert result.score_status == "not_covered"
        assert result.review_question_count == 1
        assert result.score_breakdown["geometry_candidate_count"] == 1
        assert "1 道几何/图形候选题" in result.evidence


class TestDifficultyPositioning:
    """测试难度定位"""

    @pytest.fixture
    def aggregator(self):
        return PaperAggregator()

    def test_report_difficulty_labels_use_new_paper_level_names(self):
        service = ReportService()

        labels = {
            level: service._get_difficulty_label(level)
            for level in range(1, 6)
        }

        assert labels == {
            1: "基础卷",
            2: "提升卷",
            3: "拔高卷",
            4: "选拔卷",
            5: "竞赛卷",
        }

    def test_report_difficulty_thresholds_are_unchanged(self):
        service = ReportService()

        assert service._calculate_difficulty_level(2.0) == 1
        assert service._calculate_difficulty_level(4.0) == 2
        assert service._calculate_difficulty_level(6.0) == 3
        assert service._calculate_difficulty_level(8.0) == 4
        assert service._calculate_difficulty_level(8.1) == 5

    def test_level_3_intermediate(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id=f"q{i}",
                question_no=str(i),
                score=5.0,
                dim_scores={"dim1": 5.0, "dim2": 5.0, "dim3": 6.0},
                applicable_dims=["dim1", "dim2", "dim3"],
            )
            for i in range(5)
        ]

        results = aggregator.aggregate_all_dimensions(question_scores)
        valid_scores = [r.paper_score for r in results.values() if r.level > 0]
        overall_score = sum(valid_scores) / len(valid_scores)

        assert 4.0 <= overall_score <= 6.0


class TestIntegration:
    """集成测试 - 完整评分流程"""

    def test_full_scoring_pipeline(self):
        scorers = {
            "dim1": Dim1ComputationScorer(),
            "dim2": Dim2SpatialScorer(),
            "dim3": Dim3InformationScorer(),
            "dim4": Dim4InnovationScorer(),
            "dim5": Dim5KnowledgeScorer(),
            "dim6": Dim6LogicScorer(),
        }

        question_features = {
            "dim1": {
                "task_form": "embedded",
                "calc_role": "core",
                "step_chain": "3-4",
                "number_mix": "mixed",
                "routine_transform_count": "1",
                "structural_method": "shortcut",
                "global_view_required": 0,
                "error_pressure": "medium",
                "evidence_summary": "需要在应用题语境中完成结构化计算。",
            },
            "dim2": {
                "task_form": "geometry_embedded",
                "spatial_role": "core",
                "figure_complexity": "solid_3d",
                "relation_hops": "2",
                "hidden_relation_count": "0",
                "visual_operation_count": "1",
                "structural_visual_method": "none",
                "measurement_dependency": "direct",
                "global_view_required": 0,
                "image_dependency": "required",
                "evidence_summary": "需要完成圆和立体图形的常规空间判断。",
            },
            "dim5": {
                "band": "5、6年级校内课本难度",
                "sublevel": "high",
                "evidence_summary": "核心知识门槛处于五六年级课内高位。",
                "knowledge_tags": ["圆", "圆柱"],
            },
        }

        scores = {}
        for dim, features in question_features.items():
            result = scorers[dim].score(features)
            scores[dim] = result
            assert result.applicable is True
            assert result.score > 0

        aggregator = PaperAggregator()
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=5.0,
                dim_scores={
                    "dim1": scores["dim1"].score,
                    "dim2": scores["dim2"].score,
                    "dim5": scores["dim5"].score,
                },
                applicable_dims=["dim1", "dim2", "dim5"],
            ),
        ]

        results = aggregator.aggregate_all_dimensions(question_scores)

        assert "dim1" in results
        assert "dim2" in results
        assert "dim5" in results
        assert results["dim1"].paper_score > 0
        assert results["dim2"].paper_score > 0
        assert results["dim5"].paper_score > 0

    def test_multiple_questions_scoring(self):
        scorer = Dim1ComputationScorer()
        aggregator = PaperAggregator()

        questions = [
            {
                "features": {
                    "task_form": "explicit",
                    "calc_role": "core",
                    "step_chain": "1",
                    "number_mix": "plain",
                    "routine_transform_count": "0",
                    "structural_method": "none",
                    "global_view_required": 0,
                    "error_pressure": "low",
                    "evidence_summary": "直接运算。",
                },
                "score": 5.0,
            },
            {
                "features": {
                    "task_form": "explicit",
                    "calc_role": "core",
                    "step_chain": "2",
                    "number_mix": "standard",
                    "routine_transform_count": "1",
                    "structural_method": "none",
                    "global_view_required": 0,
                    "error_pressure": "medium",
                    "evidence_summary": "常规分数运算。",
                },
                "score": 8.0,
            },
            {
                "features": {
                    "task_form": "embedded",
                    "calc_role": "core",
                    "step_chain": "5+",
                    "number_mix": "symbolic",
                    "routine_transform_count": "3+",
                    "structural_method": "olympiad",
                    "global_view_required": 1,
                    "error_pressure": "high",
                    "evidence_summary": "高阶结构巧算。",
                },
                "score": 12.0,
            },
        ]

        question_scores = []
        for i, q in enumerate(questions):
            result = scorer.score(q["features"])
            question_scores.append(
                QuestionDimensionScore(
                    question_id=f"q{i + 1}",
                    question_no=str(i + 1),
                    score=q["score"],
                    dim_scores={"dim1": result.score},
                    applicable_dims=["dim1"],
                )
            )

        summary = aggregator.aggregate(question_scores, "dim1")
        total_score = sum(qs.dim_scores["dim1"] for qs in question_scores)
        expected_score = total_score / len(question_scores)

        assert abs(summary.paper_score - expected_score) < 0.1
        assert summary.question_count == 3
        assert summary.sample_warning is False

    def test_report_overall_score_excludes_na_dimensions(self):
        service = ReportService()
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=10.0,
                dim_scores={
                    "dim2": 7.0,
                    "dim5": 5.0,
                },
                applicable_dims=["dim2", "dim5"],
            ),
        ]

        report = asyncio.run(
            service.generate_report_from_paper(
                paper_id="paper-1",
                question_scores=question_scores,
                paper_title="测试试卷",
            )
        )

        assert report["difficulty_position"]["overall_score"] == 6.0
        na_dimensions = [
            detail for detail in report["dimension_details"] if detail["level"] == 0
        ]
        assert len(na_dimensions) == 4

    def test_wmo_grade6_content_calibration_uses_dim5_average_without_contest_jump(self):
        service = ReportService()
        bucket_scores = {
            "school": 3.0,
            "low_gaosi": 5.0,
            "high_gaosi": 7.0,
            "junior_bridge": 7.0,
            "beyond": 9.0,
        }
        bucket_sequence = [
            "high_gaosi",
            "school",
            "school",
            "low_gaosi",
            "school",
            "low_gaosi",
            "high_gaosi",
            "junior_bridge",
            "beyond",
            "beyond",
        ]
        question_scores = [
            QuestionDimensionScore(
                question_id=f"q{index}",
                question_no=str(index),
                score=5.0,
                dim_scores={"dim5": bucket_scores[bucket]},
                applicable_dims=["dim5"],
                dim_reasons={"dim5": f"按题目内容归入 {bucket}。"},
                dim_confidences={"dim5": 0.9},
                dim_statuses={"dim5": "applicable"},
                dim_details={
                    "dim5": {
                        "knowledge_source_bucket": bucket,
                        "competition_signal": "none",
                        "knowledge_integration": "single",
                    }
                },
            )
            for index, bucket in enumerate(bucket_sequence, start=1)
        ]

        def add_dim(index: int, dim_code: str, score: float, reason: str) -> None:
            question = question_scores[index - 1]
            question.dim_scores[dim_code] = score
            question.applicable_dims.append(dim_code)
            question.dim_reasons[dim_code] = reason
            question.dim_confidences[dim_code] = 0.9
            question.dim_statuses[dim_code] = "applicable"

        add_dim(1, "dim1", 8.7, "定义新运算和裂项结构带来高计算执行负担。")
        for index, score in [(4, 8.0), (5, 8.0), (8, 8.0), (9, 9.5), (10, 8.0)]:
            add_dim(index, "dim2", score, "三维视图、空间极值或复合图形关系是核心门槛。")
        for index in (2, 3, 6):
            add_dim(index, "dim3", 8.0, "需要从复杂题面中提取并转化多重关系。")
        for index, score in [(1, 8.0), (7, 8.0), (8, 8.0), (9, 8.0), (10, 9.5)]:
            add_dim(index, "dim4", score, "包含定义新运算、博弈策略、约束枚举或空间极值构造。")
        for index in (1, 7, 9):
            add_dim(index, "dim6", 7.9, "需要较长逻辑链推进并回查约束。")

        report = asyncio.run(
            service.generate_report_from_paper(
                paper_id="wmo-content-regression",
                question_scores=question_scores,
                paper_title="匿名六年级内容校准样本",
            )
        )

        assert report["difficulty_position"]["overall_score"] == pytest.approx(7.8)
        assert report["difficulty_position"]["level"] == 4
        assert report["difficulty_position"]["label"] == "选拔卷"

    def test_report_includes_dim1_review_warning(self):
        service = ReportService()
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=6.0,
                dim_scores={"dim1": 4.0},
                applicable_dims=["dim1"],
                dim_reasons={"dim1": "常规两步计算"},
                dim_confidences={"dim1": 0.8},
                dim_statuses={"dim1": "applicable"},
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=6.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim1": "dim1 计算事实缺失，当前题目转入人工复核。"},
                dim_warnings={"dim1": ["dim1 缺少关键计算事实字段：step_chain。"]},
                dim_confidences={"dim1": 0.2},
                dim_statuses={"dim1": "review"},
            ),
        ]

        report = asyncio.run(
            service.generate_report_from_paper(
                paper_id="paper-review",
                question_scores=question_scores,
                paper_title="测试试卷",
            )
        )

        assert report["report_warnings"] == []

    def test_report_includes_dim2_review_warning(self):
        service = ReportService()
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=6.0,
                dim_scores={"dim2": 8.0},
                applicable_dims=["dim2"],
                dim_reasons={"dim2": "需要稳定读取图中空间关系"},
                dim_confidences={"dim2": 0.9},
                dim_statuses={"dim2": "applicable"},
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=6.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim2": "dim2 空间事实缺失，当前题目转入人工复核。"},
                dim_warnings={"dim2": ["dim2 缺少关键空间事实字段：relation_hops。"]},
                dim_confidences={"dim2": 0.3},
                dim_statuses={"dim2": "review"},
            ),
        ]

        report = asyncio.run(
            service.generate_report_from_paper(
                paper_id="paper-review-dim2",
                question_scores=question_scores,
                paper_title="测试试卷",
            )
        )

        assert report["report_warnings"] == []

    def test_report_includes_dim3_review_warning(self):
        service = ReportService()
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=6.0,
                dim_scores={"dim3": 6.0},
                applicable_dims=["dim3"],
                dim_reasons={"dim3": "需要整理多条分散条件并转成等量关系。"},
                dim_confidences={"dim3": 0.88},
                dim_statuses={"dim3": "applicable"},
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=6.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim3": "dim3 提取与转化事实缺失，当前题目转入人工复核。"},
                dim_warnings={"dim3": ["dim3 缺少关键信息提取事实字段：condition_distribution。"]},
                dim_confidences={"dim3": 0.31},
                dim_statuses={"dim3": "review"},
            ),
        ]

        report = asyncio.run(
            service.generate_report_from_paper(
                paper_id="paper-review-dim3",
                question_scores=question_scores,
                paper_title="测试试卷",
            )
        )

        assert report["report_warnings"] == []

    def test_report_includes_dim4_review_warning(self):
        service = ReportService()
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=6.0,
                dim_scores={"dim4": 8.0},
                applicable_dims=["dim4"],
                dim_reasons={"dim4": "需要换路并构造中间对象。"},
                dim_confidences={"dim4": 0.84},
                dim_statuses={"dim4": "applicable"},
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=6.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim4": "dim4 策略创新事实缺失，当前题目转入人工复核。"},
                dim_warnings={"dim4": ["dim4 缺少关键策略创新事实字段：strategy_shift_count。"]},
                dim_confidences={"dim4": 0.29},
                dim_statuses={"dim4": "review"},
            ),
        ]

        report = asyncio.run(
            service.generate_report_from_paper(
                paper_id="paper-review-dim4",
                question_scores=question_scores,
                paper_title="测试试卷",
            )
        )

        assert report["report_warnings"] == []

    def test_report_rebuild_restores_dim1_review_status_from_payload(self):
        service = ReportService()
        questions = [
            SimpleNamespace(
                question_id="q1",
                question_no="1",
                question_label_raw="1.",
                section_index_raw="",
                page_no=1,
                raw_text="求 25% 的值。",
                score=5.0,
            )
        ]
        tag_map = {
            "q1": SimpleNamespace(
                evidence_text=json.dumps(
                    {
                        "analysis_facts": {"core_task": "求 25% 的值"},
                        "dimension_statuses": {
                            "dim1": {
                                "status": "review",
                                "reason": "dim1 计算事实缺失，当前题目转入人工复核。",
                                "warnings": ["dim1 缺少关键计算事实字段：step_chain。"],
                                "normalized_facts": {"calc_role": "core"},
                            }
                        },
                    },
                    ensure_ascii=False,
                )
            )
        }
        dim_rows = [
            SimpleNamespace(
                question_id="q1",
                dim_code="dim1",
                dim_score=0.0,
                is_applicable=False,
                score_evidence="dim1 计算事实缺失，当前题目转入人工复核。",
                confidence=0.21,
            )
        ]

        question_scores = service._build_question_scores_from_rows(questions, tag_map, dim_rows)
        aggregated = service.aggregator.aggregate_all_dimensions(question_scores)

        assert question_scores[0].dim_statuses["dim1"] == "review"
        assert aggregated["dim1"].review_question_count == 1
        assert aggregated["dim1"].score_status == "not_covered"
        assert not aggregated["dim1"].warning_messages

    def test_report_rebuild_restores_dim2_review_status_from_payload(self):
        service = ReportService()
        questions = [
            SimpleNamespace(
                question_id="q1",
                question_no="1",
                question_label_raw="1.",
                section_index_raw="",
                page_no=1,
                raw_text="如图，判断展开图能否折成立方体。",
                score=5.0,
            )
        ]
        tag_map = {
            "q1": SimpleNamespace(
                evidence_text=json.dumps(
                    {
                        "analysis_facts": {"core_task": "判断展开图能否折成立方体"},
                        "dimension_statuses": {
                            "dim2": {
                                "status": "review",
                                "reason": "dim2 空间事实缺失，当前题目转入人工复核。",
                                "warnings": ["dim2 缺少关键空间事实字段：relation_hops。"],
                                "normalized_facts": {"spatial_role": "core"},
                            }
                        },
                    },
                    ensure_ascii=False,
                )
            )
        }
        dim_rows = [
            SimpleNamespace(
                question_id="q1",
                dim_code="dim2",
                dim_score=0.0,
                is_applicable=False,
                score_evidence="dim2 空间事实缺失，当前题目转入人工复核。",
                confidence=0.21,
            )
        ]

        question_scores = service._build_question_scores_from_rows(questions, tag_map, dim_rows)
        aggregated = service.aggregator.aggregate_all_dimensions(question_scores)

        assert question_scores[0].dim_statuses["dim2"] == "review"
        assert aggregated["dim2"].review_question_count == 1
        assert aggregated["dim2"].score_status == "not_covered"
        assert not aggregated["dim2"].warning_messages

    def test_report_rebuild_restores_dim3_review_status_from_payload(self):
        service = ReportService()
        questions = [
            SimpleNamespace(
                question_id="q1",
                question_no="1",
                question_label_raw="1.",
                section_index_raw="",
                page_no=1,
                raw_text="根据统计图和文字材料分析销量变化。",
                score=5.0,
            )
        ]
        tag_map = {
            "q1": SimpleNamespace(
                evidence_text=json.dumps(
                    {
                        "analysis_facts": {"core_task": "整理材料并分析销量变化"},
                        "dimension_statuses": {
                            "dim3": {
                                "status": "review",
                                "reason": "dim3 提取与转化事实缺失，当前题目转入人工复核。",
                                "warnings": ["dim3 缺少关键信息提取事实字段：condition_distribution。"],
                                "normalized_facts": {"information_role": "core"},
                            }
                        },
                    },
                    ensure_ascii=False,
                )
            )
        }
        dim_rows = [
            SimpleNamespace(
                question_id="q1",
                dim_code="dim3",
                dim_score=0.0,
                is_applicable=False,
                score_evidence="dim3 提取与转化事实缺失，当前题目转入人工复核。",
                confidence=0.22,
            )
        ]

        question_scores = service._build_question_scores_from_rows(questions, tag_map, dim_rows)
        aggregated = service.aggregator.aggregate_all_dimensions(question_scores)

        assert question_scores[0].dim_statuses["dim3"] == "review"
        assert aggregated["dim3"].review_question_count == 1
        assert aggregated["dim3"].score_status == "not_covered"
        assert not aggregated["dim3"].warning_messages

    def test_report_rebuild_restores_dim4_review_status_from_payload(self):
        service = ReportService()
        questions = [
            SimpleNamespace(
                question_id="q1",
                question_no="1",
                question_label_raw="1.",
                section_index_raw="",
                page_no=1,
                raw_text="尝试不同构造方案并说明哪条路径可行。",
                score=5.0,
            )
        ]
        tag_map = {
            "q1": SimpleNamespace(
                evidence_text=json.dumps(
                    {
                        "analysis_facts": {"core_task": "尝试不同构造方案并选择可行路径"},
                        "dimension_statuses": {
                            "dim4": {
                                "status": "review",
                                "reason": "dim4 策略创新事实缺失，当前题目转入人工复核。",
                                "warnings": ["dim4 缺少关键策略创新事实字段：strategy_shift_count。"],
                                "normalized_facts": {"strategy_role": "core"},
                            }
                        },
                    },
                    ensure_ascii=False,
                )
            )
        }
        dim_rows = [
            SimpleNamespace(
                question_id="q1",
                dim_code="dim4",
                dim_score=0.0,
                is_applicable=False,
                score_evidence="dim4 策略创新事实缺失，当前题目转入人工复核。",
                confidence=0.22,
            )
        ]

        question_scores = service._build_question_scores_from_rows(questions, tag_map, dim_rows)
        aggregated = service.aggregator.aggregate_all_dimensions(question_scores)

        assert question_scores[0].dim_statuses["dim4"] == "review"
        assert aggregated["dim4"].review_question_count == 1
        assert aggregated["dim4"].score_status == "not_covered"
        assert not aggregated["dim4"].warning_messages


    def test_report_includes_dim6_review_warning(self):
        service = ReportService()
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=6.0,
                dim_scores={"dim6": 8.0},
                applicable_dims=["dim6"],
                dim_reasons={"dim6": "需要分类讨论并回查约束。"},
                dim_confidences={"dim6": 0.89},
                dim_statuses={"dim6": "applicable"},
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=6.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim6": "dim6 逻辑事实缺失，当前题目转入人工复核。"},
                dim_warnings={"dim6": ["dim6 缺少关键逻辑事实字段：branch_control。"]},
                dim_confidences={"dim6": 0.28},
                dim_statuses={"dim6": "review"},
            ),
        ]

        report = asyncio.run(
            service.generate_report_from_paper(
                paper_id="paper-review-dim6",
                question_scores=question_scores,
                paper_title="测试试卷",
            )
        )

        assert report["report_warnings"] == []

    def test_report_rebuild_restores_dim6_review_status_from_payload(self):
        service = ReportService()
        questions = [
            SimpleNamespace(
                question_id="q1",
                question_no="1",
                question_label_raw="1.",
                section_index_raw="",
                page_no=1,
                raw_text="请分类讨论所有可能情况，并验证结论是否成立。",
                score=5.0,
            )
        ]
        tag_map = {
            "q1": SimpleNamespace(
                evidence_text=json.dumps(
                    {
                        "analysis_facts": {"core_task": "分类讨论并验证结论"},
                        "dimension_statuses": {
                            "dim6": {
                                "status": "review",
                                "reason": "dim6 逻辑事实缺失，当前题目转入人工复核。",
                                "warnings": ["dim6 缺少关键逻辑事实字段：branch_control。"],
                                "normalized_facts": {"reasoning_role": "core"},
                            }
                        },
                    },
                    ensure_ascii=False,
                )
            )
        }
        dim_rows = [
            SimpleNamespace(
                question_id="q1",
                dim_code="dim6",
                dim_score=0.0,
                is_applicable=False,
                score_evidence="dim6 逻辑事实缺失，当前题目转入人工复核。",
                confidence=0.24,
            )
        ]

        question_scores = service._build_question_scores_from_rows(questions, tag_map, dim_rows)
        aggregated = service.aggregator.aggregate_all_dimensions(question_scores)

        assert question_scores[0].dim_statuses["dim6"] == "review"
        assert aggregated["dim6"].review_question_count == 1
        assert aggregated["dim6"].score_status == "not_covered"
        assert not aggregated["dim6"].warning_messages


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
