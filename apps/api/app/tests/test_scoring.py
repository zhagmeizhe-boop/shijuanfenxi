"""
六维评分引擎完整单元测试

重点覆盖各维度本地规则，以及整卷题级/结构化聚合。
"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.report.report_service import ReportService
from app.services.ocr.base import ParseAudit, ParsedQuestion, QuestionType
from app.services.parser.ai_parser import AIParser
from app.services.parser.dim5_grounding import Dim5KnowledgeGroundingService
from app.services.parser.dim5_retrieval import Dim5RetrievalService
from app.services.parser.reference_standard import ReferenceEntry, WorkbookReferenceStandard, get_reference_standard
from app.services.scoring.dim1_applicability import (
    evaluate_dim1_applicability,
    is_bare_calculation_fill_blank,
)
from app.services.scoring.dim2_applicability import (
    build_dim2_text_geometry_fallback_facts,
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
from app.services.scoring.dim5_canonical import (
    DIM5_KNOWLEDGE_DOMAINS,
    DIM5_LEVEL_SCORES,
    canonicalize_dim5_knowledge,
    classify_dim5_knowledge_scope,
)
from app.services.scoring.dim5_knowledge import Dim5KnowledgeScorer
from app.services.scoring.dim6_logic import Dim6LogicScorer
from app.services.scoring.dim_second_review import (
    build_second_review_dimension_score,
    build_second_review_exclusion_details,
    normalize_second_review_payload,
)
from app.services.scoring.paper_aggregator import (
    PaperAggregator,
    QuestionDimensionScore,
)

WMO_DIM2_GEOMETRY_CASES = [
    (
        "5",
        (
            "\u5c06\u900f\u660e\u6b63\u65b9\u4f53\u7684\u90e8\u5206\u9876\u70b9"
            "\u548c\u68f1\u7684\u4e2d\u70b9\u8fde\u8d77\u6765\u5f97\u5230\u5982"
            "\u4e0b\u56fe\uff0c\u4ece\u5de6\u9762\u89c2\u5bdf\u8be5\u6b63"
            "\u65b9\u4f53\uff0c\u770b\u5230\u7684\u56fe\u5f62\u662f\uff08  \uff09\u3002"
        ),
        5,
    ),
    (
        "8",
        (
            "\u4e0b\u56fe\u6b63\u65b9\u5f62\u7684\u8fb9\u957f\u4e3a20\u5398"
            "\u7c73\uff0c\u56fe\u4e2d\u9634\u5f71\u90e8\u5206\u7684\u9762"
            "\u79ef\u662f\uff08  \uff09\u5e73\u65b9\u5398\u7c73\u3002\uff08"
            "\u03c0\u53d63.14\uff09 [\u56fe\u5f62\uff1a\u6b63\u65b9"
            "\u5f62\u5185\u542b\u56db\u4e2a\u6247\u5f62\u7ec4\u6210\u7684"
            "\u9634\u5f71\u56fe\u6848] A.189.5 B.214.5 C.230 D.242.5"
        ),
        4,
    ),
    (
        "18",
        (
            "\u5982\u56fe\u6240\u793a\uff0c\u5706\u7684\u534a\u5f84\u4e3a2"
            "\u5398\u7c73\uff0c\u5706\u7684\u9762\u79ef\u4e0e\u957f\u65b9"
            "\u5f62OABC\u7684\u9762\u79ef\u76f8\u7b49\u3002(\u03c0\u53d63.14) "
            "\u7b2c\u4e00\u95ee\uff1a\u7ebf\u6bb5OC\u7684\u957f\u5ea6"
            "\u662f______\u5398\u7c73\u3002(4\u5206) \u7b2c\u4e8c\u95ee\uff1a"
            "\u56fe\u4e2d\u9634\u5f71\u90e8\u5206\u7684\u9762\u79ef\u662f"
            "______\u5e73\u65b9\u5398\u7c73\u3002(6\u5206)"
        ),
        4,
    ),
    (
        "19",
        (
            "\u4ece\u5de6\u56fe\u7acb\u4f53\u56fe\u5f62\u768427\u4e2a\u900f"
            "\u660e\u79ef\u6728\u4e2d\uff0c\u9009\u82e5\u5e72\u4e2a\u7528"
            "\u7eff\u8272\u79ef\u6728\uff08\u4e0d\u900f\u660e\uff09\u66ff"
            "\u6362\u540e\uff0c\u4ece\u524d\u9762\u548c\u5de6\u9762\u770b"
            "\u5230\u7684\u56fe\u5f62\u5982\u53f3\u56fe\u6240\u793a\u3002 "
            "\u7b2c\u4e00\u95ee\uff1a\u6700\u5c11\u53ef\u4ee5\u7528______"
            "\u4e2a\u7eff\u8272\u79ef\u6728\u3002(6\u5206) \u7b2c\u4e8c"
            "\u95ee\uff1a\u6700\u591a\u53ef\u4ee5\u7528______\u4e2a\u7eff"
            "\u8272\u79ef\u6728\u3002(4\u5206)"
        ),
        5,
    ),
]

WMO31_DIM2_REGRESSION_TEXTS = {
    "5": (
        "远古时期，人们通过在绳子上打结来记录数量，即“结绳计数”。如图所示，"
        "一个村庄的捕猎人在从右到左依次排列的绳子上打结，满五进一，用来记录捕获的野兔数量。"
    ),
    "6": (
        "如果杆秤中心点离两侧物体的质量与它们到中心点的距离的乘积相同，杆秤就可以是一条水平直线。"
        "下图中每根杆秤都是一条水平直线，那么“？”处的质量是（ ）。"
    ),
    "12": (
        "如图，将三角形 ABD 绕 B 点顺时针旋转 90°，得到三角形 CBE。"
        "已知 AB=10 厘米，BE=4 厘米，则图中阴影部分的面积是（ ）平方厘米。（π 取 3.14）"
    ),
    "14": (
        "如图，四边形ABCD的对角线AC与BD相交于O，边BC上有一点E，BE：EC=7：5。"
        "三角形ABO的面积为36，三角形ADO的面积为18，三角形CDO的面积为24。则三角形AED的面积是（ ）。"
    ),
    "17": (
        "思思采摘了一些葡萄，放入一个圆柱形木桶里酿葡萄酒。桶的底面外直径是48cm，内直径是40cm，"
        "外高是50cm，内高是40cm。（π取3）(1)思思准备给木桶的盖子和侧面进行装饰，"
        "装饰部分的面积是多少平方厘米？（5分）(2)放到一定的时候，发酵出了一款好喝的葡萄酒，酒水的高度"
    ),
    "20": (
        "光线总是沿着直线方向前进，而当光线遇到平面镜就会以90度反射，改变前进方向。"
        "如图1所示，双面镜子按45°放置，红线表示光线沿箭头方向射入时，光线的传播路径。"
        "图3是一个长260米，宽150米的幽灵之家，幽灵从烟囱A进入，从哪一个烟囱飞出幽灵之家？"
    ),
}


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

    def test_dim1_defined_operation_with_fraction_transform_reaches_l4(self, scorer):
        result = scorer.score(
            self._pure_features(
                step_chain="3-4",
                number_mix="symbolic",
                routine_transform_count="1",
                calc_subtype="defined_operation",
                structure_patterns=["defined_rule_expansion"],
                symbolic_dependency="single_unknown",
                evidence_summary="需要先展开定义运算，再通分并做结构变形求出方框中的数。",
                evidence_tags=["定义运算", "分数通分", "结构变形"],
            )
        )

        assert result.score == 8.0
        assert result.level_label == "L4 复合巧算"

    def test_dim1_complex_long_telescoping_can_reach_l5_before_aggregation(self, scorer):
        result = scorer.score(
            self._pure_features(
                step_chain="5+",
                number_mix="symbolic",
                routine_transform_count="2",
                structural_method="shortcut",
                global_view_required=1,
                calc_subtype="sequence_series",
                structure_patterns=["telescoping"],
                term_count_band="6-10",
                evidence_summary="需要识别长链裂项相消结构，提取首尾项后再完成分数化简。",
                evidence_tags=["长链裂项", "相消", "首尾项"],
            )
        )

        assert result.score == 9.5
        assert result.level_label == "L5 高阶结构巧算"

    def test_dim1_embedded_multistage_percentage_reaches_l4(self, scorer):
        result = scorer.score(
            {
                "task_form": "embedded",
                "calc_role": "core",
                "calc_bucket": "embedded_calculation",
                "step_chain": "3-4",
                "number_mix": "mixed",
                "routine_transform_count": "1",
                "structural_method": "none",
                "global_view_required": 0,
                "error_pressure": "high",
                "intermediate_quantity_count": "2",
                "unit_conversion_count": "0",
                "formula_substitution_count": "0",
                "calc_subtype": "proportion_equation",
                "symbolic_dependency": "single_unknown",
                "evidence_summary": "利润率题需要处理成本变化和价格变化，连续完成百分数方程计算。",
                "evidence_tags": ["利润率", "成本变化", "价格变化"],
            }
        )

        assert result.score == 8.0
        assert result.level_label == "L4 高负担嵌入计算"

    def test_dim1_embedded_multi_ratio_elimination_can_reach_l5(self, scorer):
        result = scorer.score(
            {
                "task_form": "embedded",
                "calc_role": "core",
                "calc_bucket": "embedded_calculation",
                "step_chain": "5+",
                "number_mix": "symbolic",
                "routine_transform_count": "2",
                "structural_method": "none",
                "global_view_required": 1,
                "error_pressure": "high",
                "intermediate_quantity_count": "3+",
                "unit_conversion_count": "0",
                "formula_substitution_count": "0",
                "calc_subtype": "proportion_equation",
                "symbolic_dependency": "multi_unknown",
                "evidence_summary": "三组比例关系需要联立方程组并消元，最后反推总量。",
                "evidence_tags": ["三组比例", "联立", "消元"],
            }
        )

        assert result.score == 9.5
        assert result.level_label == "L5 高阶嵌入计算"

    def test_dim1_digit_constraint_trial_division_reaches_l5(self, scorer):
        result = scorer.score(
            self._pure_features(
                step_chain="5+",
                number_mix="symbolic",
                routine_transform_count="2",
                structural_method="shortcut",
                global_view_required=1,
                calc_subtype="pattern_computation",
                symbolic_dependency="multi_unknown",
                evidence_summary="多位数字母除法需要逐位试商，结合数字约束反复试算验证。",
                evidence_tags=["多位数", "逐位", "试算", "数字约束"],
            )
        )

        assert result.score == 9.5
        assert result.level_label == "L5 高阶结构巧算"

    def test_dim1_direct_geometry_formula_stays_l3_or_below(self, scorer):
        result = scorer.score(
            {
                "task_form": "embedded",
                "calc_role": "core",
                "calc_bucket": "embedded_calculation",
                "step_chain": "3-4",
                "number_mix": "standard",
                "routine_transform_count": "0",
                "structural_method": "none",
                "global_view_required": 0,
                "error_pressure": "medium",
                "intermediate_quantity_count": "1",
                "unit_conversion_count": "0",
                "formula_substitution_count": "2+",
                "calc_subtype": "arithmetic",
                "symbolic_dependency": "none",
                "evidence_summary": "普通圆面积和长方形面积公式代入后做两三步小数计算。",
                "evidence_tags": ["圆面积公式", "公式代入"],
            }
        )

        assert result.score == 6.0
        assert result.level_label == "L3 多步嵌入计算"

    @pytest.mark.parametrize(
        ("knowledge_point", "burden_overrides", "expected_k", "expected_b", "expected_l"),
        [
            ("三位数乘两位数", {}, "K1", "B1", "L1"),
            ("三位数乘两位数", {"step_chain": "2", "number_mix": "standard"}, "K1", "B2", "L1"),
            (
                "三位数乘两位数",
                {
                    "step_chain": "5+",
                    "number_mix": "symbolic",
                    "routine_transform_count": "3+",
                    "structural_method": "olympiad",
                    "global_view_required": 1,
                    "calc_subtype": "sequence_series",
                    "structure_patterns": ["telescoping"],
                    "term_count_band": "11+",
                },
                "K1",
                "B5",
                "L3",
            ),
            (
                "小数乘法计算",
                {
                    "step_chain": "3-4",
                    "number_mix": "mixed",
                    "routine_transform_count": "2",
                    "structural_method": "shortcut",
                    "structure_patterns": ["common_factor", "decimal_scaling"],
                },
                "K2",
                "B4",
                "L3",
            ),
            (
                "小数乘法计算",
                {
                    "step_chain": "5+",
                    "number_mix": "symbolic",
                    "routine_transform_count": "3+",
                    "structural_method": "olympiad",
                    "global_view_required": 1,
                    "calc_subtype": "sequence_series",
                    "structure_patterns": ["telescoping"],
                    "term_count_band": "11+",
                },
                "K2",
                "B5",
                "L4",
            ),
            ("解比例", {}, "K3", "B1", "L2"),
            (
                "解比例",
                {
                    "step_chain": "3-4",
                    "number_mix": "mixed",
                    "routine_transform_count": "2",
                    "structural_method": "shortcut",
                    "structure_patterns": ["common_factor", "decimal_scaling"],
                },
                "K3",
                "B4",
                "L4",
            ),
            (
                "解比例",
                {
                    "step_chain": "5+",
                    "number_mix": "symbolic",
                    "routine_transform_count": "3+",
                    "structural_method": "olympiad",
                    "global_view_required": 1,
                    "calc_subtype": "sequence_series",
                    "structure_patterns": ["telescoping"],
                    "term_count_band": "11+",
                },
                "K3",
                "B5",
                "L4",
            ),
            ("四则运算一", {}, "K4", "B1", "L3"),
            (
                "四则运算一",
                {
                    "step_chain": "5+",
                    "number_mix": "symbolic",
                    "routine_transform_count": "3+",
                    "structural_method": "olympiad",
                    "global_view_required": 1,
                    "calc_subtype": "sequence_series",
                    "structure_patterns": ["telescoping"],
                    "term_count_band": "11+",
                },
                "K4",
                "B5",
                "L5",
            ),
            ("分数与循环小数", {}, "K5", "B1", "L4"),
            (
                "分数与循环小数",
                {
                    "step_chain": "3-4",
                    "number_mix": "standard",
                    "routine_transform_count": "1",
                    "structural_method": "shortcut",
                    "structure_patterns": ["grouping"],
                    "term_count_band": "3-5",
                },
                "K5",
                "B3",
                "L5",
            ),
        ],
    )
    def test_knowledge_range_and_burden_matrix(
        self,
        scorer,
        knowledge_point,
        burden_overrides,
        expected_k,
        expected_b,
        expected_l,
    ):
        features = self._pure_features(
            evidence_summary="用于校验知识范围与计算负担矩阵。",
            evidence_tags=["计算"],
            analysis_facts={"core_knowledge_points": [knowledge_point]},
            **burden_overrides,
        )

        result = scorer.score(features)

        assert result.applicable is True
        assert result.details["knowledge_range_level"] == expected_k
        assert result.details["burden_level"] == expected_b
        assert result.details["dim1_level"] == expected_l
        assert result.details["combined_rule"] == "knowledge_range_burden_matrix"
        assert result.details["knowledge_burden_matrix_cell"] == f"{expected_k}+{expected_b}"
        assert result.details["matched_knowledge_points"]
        assert f"综合判为{expected_l}" in result.evidence

    def test_knowledge_range_unmatched_falls_back_to_burden_level(self, scorer):
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
                evidence_summary="无法稳定识别计算知识范围，但计算负担很高。",
                evidence_tags=["不存在的知识点"],
            )
        )

        assert result.applicable is True
        assert result.details["knowledge_range_status"] == "unmatched"
        assert result.details["burden_level"] == "B5"
        assert result.details["dim1_level"] == "L5"
        assert result.details["display_knowledge_points"] == ["数列计算"]
        assert result.details["display_knowledge_status"] == "fallback"
        assert result.details["combined_rule"] == "burden_only_knowledge_range_unmatched"
        assert "知识范围未稳定识别" in result.evidence

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

    def test_cross_question_dim1_evidence_leak_goes_to_second_review(self):
        result = evaluate_dim1_applicability(
            "single_choice",
            "透明正方体部分顶点和棱中点连线，求从左面观察所得图形。",
            {
                "task_form": "embedded",
                "calc_role": "core",
                "calc_bucket": "embedded_calculation",
                "step_chain": "3-4",
                "number_mix": "mixed",
                "routine_transform_count": "1",
                "structural_method": "none",
                "global_view_required": 0,
                "error_pressure": "medium",
                "evidence_summary": "题2需要逆推初始质量，题3需要裂项求和，题4需要圆周长计算。",
                "evidence_tags": ["三视图"],
            },
            llm_confidence=0.9,
        )

        assert result["status"] == "needs_second_review"
        assert any("混入其他题号" in warning for warning in result["warnings"])

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

        assert result["status"] == "needs_second_review"
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

        assert result["status"] == "needs_second_review"
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

        assert result["status"] == "needs_second_review"
        assert any("置信度" in item for item in result["warnings"])

    def test_dim1_second_review_l2_builds_score_and_l1_is_excluded(self):
        l2_review = {
            "status": "applicable",
            "level": "L2",
            "score": 4.0,
            "evidence_summary": "需要两步常规计算并完成竖式验算",
            "confidence": 0.84,
            "exclude_reason": "",
        }
        l1_review = {
            "status": "applicable",
            "level": "L1",
            "score": 2.0,
            "evidence_summary": "只需一步直接口算",
            "confidence": 0.9,
            "exclude_reason": "",
        }
        low_confidence = {
            "status": "applicable",
            "level": "L2",
            "score": 4.0,
            "evidence_summary": "判断不稳定",
            "confidence": 0.42,
            "exclude_reason": "",
        }

        normalized_l2 = normalize_second_review_payload("dim1", l2_review)
        score = build_second_review_dimension_score(
            "dim1",
            l2_review,
            initial_feature={"task_form": "explicit", "calc_role": "core"},
            initial_status={"status": "needs_second_review"},
        )
        normalized_l1 = normalize_second_review_payload("dim1", l1_review)
        normalized_low_confidence = normalize_second_review_payload("dim1", low_confidence)

        assert normalized_l2["status"] == "applicable"
        assert normalized_l2["score"] == 4.0
        assert score.dimension_code == "dim1"
        assert score.score == 4.0
        assert score.details["dim1_level"] == "L2"
        assert score.details["level_source"] == "second_review"
        assert normalized_l1["status"] == "not_applicable"
        assert normalized_l1["score"] == 0.0
        assert normalized_low_confidence["status"] == "unresolved"


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
            "equal_area_transform",
            "kite_area",
            "bird_head_sandglass",
            "pyramid_sandglass",
        ],
    )
    def test_single_olympiad_area_model_uses_knowledge_range_matrix(self, scorer, model_type):
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
        expected_level = 4 if model_type == "shared_base_area" else 5
        expected_score = 8.0 if expected_level == 4 else 9.5
        assert result.score == expected_score
        assert result.level == expected_level
        assert result.details["spatial_burden_level"] == "S4"
        if model_type == "shared_base_area":
            assert result.details["knowledge_range_status"] == "unmatched"
            assert result.details["combined_rule"] == "spatial_burden_only_knowledge_range_unmatched"
        else:
            assert result.details["knowledge_range_level"] == "K5"
            assert result.details["combined_rule"] == "knowledge_range_spatial_burden_matrix"
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
        assert result.score == 9.5
        assert result.level == 5
        assert result.details["knowledge_range_level"] == "K5"
        assert result.details["spatial_burden_level"] == "S4"
        assert result.details["knowledge_spatial_matrix_cell"] == "K5+S4"

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

    def test_stable_direct_formula_geometry_scores_l1_even_when_role_none(self, scorer):
        result = scorer.score(
            self._dim2_features(
                task_form="text_only_geometry",
                spatial_role="none",
                figure_complexity="basic_2d",
                relation_hops="1",
                hidden_relation_count="0",
                visual_operation_count="0",
                structural_visual_method="none",
                measurement_dependency="direct",
                image_dependency="none",
                geometry_model_types=["basic_area_formula"],
                geometry_model_count="1",
                model_recognition_role="none",
                area_relation_chain="none",
                model_combination_complexity="none",
                evidence_summary="直接套用长方形面积公式。",
            )
        )

        assert result.applicable is True
        assert result.score == 2.0
        assert result.level == 1

    @pytest.mark.parametrize(
        "knowledge_point,expected_k,burden_overrides,expected_spatial_burden,expected_level",
        [
            ("观察物体（一）", "K1", {}, "S2", 1),
            (
                "观察物体（一）",
                "K1",
                {"relation_hops": "5+", "hidden_relation_count": "2+"},
                "S5",
                3,
            ),
            (
                "平行四边形的面积计算公式",
                "K2",
                {
                    "relation_hops": "3-4",
                    "hidden_relation_count": "1",
                    "visual_operation_count": "2",
                    "structural_visual_method": "auxiliary_line",
                    "measurement_dependency": "inferred",
                },
                "S4",
                3,
            ),
            (
                "圆的认识",
                "K3",
                {
                    "relation_hops": "1",
                    "visual_operation_count": "0",
                    "image_dependency": "helpful",
                },
                "S1",
                2,
            ),
            (
                "圆的认识",
                "K3",
                {
                    "relation_hops": "3-4",
                    "hidden_relation_count": "1",
                    "visual_operation_count": "2",
                    "structural_visual_method": "auxiliary_line",
                    "measurement_dependency": "inferred",
                },
                "S4",
                4,
            ),
            (
                "格点与割补",
                "K4",
                {
                    "relation_hops": "1",
                    "visual_operation_count": "0",
                    "image_dependency": "helpful",
                },
                "S1",
                3,
            ),
            (
                "格点与割补",
                "K4",
                {"relation_hops": "5+", "hidden_relation_count": "2+"},
                "S5",
                5,
            ),
            (
                "立体几何",
                "K5",
                {
                    "relation_hops": "1",
                    "visual_operation_count": "0",
                    "image_dependency": "helpful",
                },
                "S1",
                4,
            ),
            (
                "立体几何",
                "K5",
                {
                    "figure_complexity": "composite_2d",
                    "relation_hops": "3-4",
                    "hidden_relation_count": "1",
                    "structural_visual_method": "decomposition",
                    "measurement_dependency": "inferred",
                },
                "S3",
                5,
            ),
        ],
    )
    def test_knowledge_range_and_spatial_burden_matrix(
        self,
        scorer,
        knowledge_point,
        expected_k,
        burden_overrides,
        expected_spatial_burden,
        expected_level,
    ):
        result = scorer.score(
            self._dim2_features(
                analysis_facts={"core_knowledge_points": [knowledge_point]},
                evidence_tags=[],
                **burden_overrides,
            )
        )

        assert result.applicable is True
        assert result.level == expected_level
        assert result.details["knowledge_range_level"] == expected_k
        assert result.details["spatial_burden_level"] == expected_spatial_burden
        assert result.details["combined_rule"] == "knowledge_range_spatial_burden_matrix"

    def test_knowledge_range_unmatched_falls_back_to_spatial_burden(self, scorer):
        result = scorer.score(
            self._dim2_features(
                relation_hops="3-4",
                hidden_relation_count="1",
                structural_visual_method="decomposition",
                measurement_dependency="inferred",
                evidence_summary="需要拆分图形关系。",
                evidence_tags=[],
            )
        )

        assert result.applicable is True
        assert result.level == 3
        assert result.details["spatial_burden_level"] == "S3"
        assert result.details["knowledge_range_status"] == "unmatched"
        assert result.details["combined_rule"] == "spatial_burden_only_knowledge_range_unmatched"

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
    def test_knowledge_tree_mid_geometry_patterns_use_k4_matrix(self, scorer, model_type):
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
        assert result.level == 4
        assert result.score == 8.0
        assert result.details["knowledge_range_level"] == "K4"
        assert result.details["spatial_burden_level"] == "S3"

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
    def test_knowledge_tree_high_geometry_patterns_use_matrix(self, scorer, model_type):
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
        expected_level = 4 if model_type == "angle_chasing_polygon" else 5
        assert result.level == expected_level
        assert result.score == (8.0 if expected_level == 4 else 9.5)
        assert result.details["knowledge_range_level"] == (
            "K4" if model_type == "angle_chasing_polygon" else "K5"
        )
        assert result.details["spatial_burden_level"] == "S4"

    def test_wmo_like_basic_three_view_projection_scores_l5_after_knowledge_range(self, scorer):
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
        assert result.score == 9.5
        assert result.level == 5
        assert result.details["knowledge_range_level"] == "K5"
        assert result.details["spatial_burden_level"] == "S4"

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

    def test_formula_geometry_is_applicable_as_low_burden_geometry(self):
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

        assert result["status"] == "applicable"

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

    def test_basic_formula_model_is_applicable_when_direct(self):
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

        assert result["status"] == "applicable"

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

        assert result["status"] == "needs_second_review"
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

        assert result["status"] == "needs_second_review"
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

        assert result["status"] == "needs_second_review"
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

    def test_solid_geometry_fallback_scores_l5_after_knowledge_range(self):
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
        assert score.level == 5
        assert score.details["knowledge_range_level"] == "K5"
        assert score.details["spatial_burden_level"] == "S4"

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

    def test_direct_formula_text_geometry_fallback_scores_l1(self):
        raw_text = "\u5df2\u77e5\u957f\u65b9\u5f62\u957f 8 \u5398\u7c73\uff0c\u5bbd 5 \u5398\u7c73\uff0c\u6c42\u9762\u79ef\u3002"
        facts = build_dim2_text_geometry_fallback_facts(
            raw_text,
            {"spatial_role": "none", "applicability_confidence": 0.0},
        )

        assert facts is not None
        assert facts["fallback_source"] == "text_geometry_formula"
        assert facts["geometry_model_types"] == ["basic_area_formula"]
        applicability = evaluate_dim2_applicability(raw_text, facts, llm_confidence=0.72)
        assert applicability["status"] == "applicable"
        score = Dim2SpatialScorer().score(facts)
        assert score.applicable is True
        assert score.level == 1

    def test_water_volume_fallback_scores_l5_without_stable_image_use(self):
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
        assert score.level == 5
        assert score.details["knowledge_range_level"] == "K5"
        assert score.details["spatial_burden_level"] == "S4"

        applicability = evaluate_dim2_applicability(
            "如图，一个瓶子中装有水，底面积10平方厘米，正放水高6厘米，倒放后空余部分高4厘米，求瓶子的容积。",
            facts,
            llm_confidence=0.7,
            parse_audit={"visual_category": "geometry_context"},
            used_image=False,
        )

        assert applicability["status"] == "applicable"

    def test_rectangle_reverse_area_fallback_uses_k1_s3_matrix(self):
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
        assert score.level == 2
        assert score.details["knowledge_range_level"] == "K1"
        assert score.details["spatial_burden_level"] == "S3"

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

    @pytest.mark.parametrize(
        ("question_no", "parse_audit"),
        [
            ("5", {"visual_category": "diagram", "image_required_hint": True}),
            ("6", {"visual_category": "diagram", "image_required_hint": True}),
            ("20", {"visual_category": "diagram", "image_required_hint": True}),
        ],
    )
    def test_wmo31_non_geometry_diagrams_do_not_enter_dim2(self, question_no, parse_audit):
        raw_text = WMO31_DIM2_REGRESSION_TEXTS[question_no]
        facts = build_dim2_visual_fallback_facts(
            raw_text,
            {"spatial_role": "none", "applicability_confidence": 0.0},
            parse_audit=parse_audit,
            has_image=True,
            used_image=True,
        )

        assert facts is None
        applicability = evaluate_dim2_applicability(
            raw_text,
            {},
            llm_confidence=0.9,
            parse_audit=parse_audit,
            used_image=True,
        )

        assert applicability["status"] == "not_applicable"

    def test_wmo31_rotation_shadow_uses_specific_dim2_fallback(self):
        raw_text = WMO31_DIM2_REGRESSION_TEXTS["12"]
        facts = build_dim2_visual_fallback_facts(
            raw_text,
            {"spatial_role": "none", "applicability_confidence": 0.0},
            parse_audit={"visual_category": "geometry", "image_required_hint": True},
            has_image=True,
            used_image=True,
        )

        assert facts is not None
        assert facts["fallback_source"] == "visual_geometry_rotation_shadow"
        assert facts["geometry_domain_gate"] == "geometry_area_relation"
        assert "circle_sector_cut_fill" in facts["geometry_model_types"]
        applicability = evaluate_dim2_applicability(
            raw_text,
            facts,
            llm_confidence=facts["applicability_confidence"],
            parse_audit={"visual_category": "geometry", "image_required_hint": True},
            used_image=True,
        )

        assert applicability["status"] == "applicable"
        score = Dim2SpatialScorer().score(facts)
        assert score.applicable is True
        assert score.score == pytest.approx(6.0)
        assert score.details["dim2_level"] == "L3"
        assert score.details["final_level_adjustment_reason"] == "standard_rotation_sector_shadow_area"

    def test_simple_rotation_recognition_is_not_promoted_to_l3(self):
        score = Dim2SpatialScorer().score(
            {
                "task_form": "explicit_visual",
                "spatial_role": "core",
                "figure_complexity": "basic_2d",
                "relation_hops": "1",
                "hidden_relation_count": "0",
                "visual_operation_count": "1",
                "structural_visual_method": "none",
                "measurement_dependency": "direct",
                "global_view_required": 0,
                "image_dependency": "helpful",
                "geometry_model_types": ["figure_transformation"],
                "geometry_model_count": "1",
                "model_recognition_role": "supporting",
                "area_relation_chain": "none",
                "model_combination_complexity": "single_model",
                "evidence_summary": "直接识别旋转后的对应位置。",
            }
        )

        assert score.applicable is True
        assert score.score < 6.0
        assert "final_level_adjustment_reason" not in score.details

    def test_wmo31_quadrilateral_area_ratio_counts_even_when_llm_image_use_failed(self):
        raw_text = WMO31_DIM2_REGRESSION_TEXTS["14"]
        facts = build_dim2_visual_fallback_facts(
            raw_text,
            {"spatial_role": "none", "applicability_confidence": 0.0},
            parse_audit={"visual_category": "geometry", "image_required_hint": True},
            has_image=True,
            used_image=False,
        )

        assert facts is not None
        assert facts["fallback_source"] == "visual_geometry_area_ratio"
        assert facts["image_block_available"] == 1
        assert "area_ratio_chain" in facts["geometry_model_types"]
        applicability = evaluate_dim2_applicability(
            raw_text,
            facts,
            llm_confidence=facts["applicability_confidence"],
            parse_audit={"visual_category": "geometry", "image_required_hint": True},
            used_image=False,
            parse_warnings=["LLM 超时/异常，已继续处理其他题目。"],
        )

        assert applicability["status"] == "applicable"

    def test_wmo31_hollow_cylinder_counts_despite_truncated_second_part(self):
        raw_text = WMO31_DIM2_REGRESSION_TEXTS["17"]
        facts = build_dim2_text_geometry_fallback_facts(
            raw_text,
            {"spatial_role": "none", "applicability_confidence": 0.0},
        )

        assert facts is not None
        assert facts["fallback_source"] == "text_hollow_cylinder_geometry"
        assert facts["geometry_domain_gate"] == "solid_geometry"
        applicability = evaluate_dim2_applicability(
            raw_text,
            facts,
            llm_confidence=facts["applicability_confidence"],
            parse_audit={"visual_category": "none", "image_required_hint": False},
            used_image=False,
            parse_warnings=["题目(2)小问文字被截断，raw_text不完整"],
        )

        assert applicability["status"] == "applicable"

    def test_wmo_geometry_questions_use_deterministic_dim2_fallback(self):
        scorer = Dim2SpatialScorer()

        for question_no, raw_text, expected_level in WMO_DIM2_GEOMETRY_CASES:
            facts = build_dim2_visual_fallback_facts(
                raw_text,
                {"spatial_role": "none", "applicability_confidence": 0.0},
                parse_audit={"visual_category": "geometry_context"},
                has_image=True,
                used_image=False,
            )

            assert facts is not None, question_no
            applicability = evaluate_dim2_applicability(
                raw_text,
                facts,
                llm_confidence=facts["applicability_confidence"],
                parse_audit={"visual_category": "geometry_context"},
                used_image=False,
            )
            score = scorer.score(facts)

            assert applicability["status"] == "applicable", question_no
            assert score.applicable is True, question_no
            assert score.level == expected_level, question_no
            assert facts["fallback_source"] == "visual_geometry"
            assert facts["model_recognition_role"] == "core"


class TestDim3InformationScorer:
    """测试维度3：场景理解复杂度评分器"""

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
            "scenario_comprehension_load": "medium",
            "extraction_depth": "direct",
            "representation_conversion": "none",
            "conversion_step_count": "0",
            "quantity_relation_structure": "none",
            "target_representation": "none",
            "global_organizing_required": 0,
            "image_dependency": "none",
            "application_relation_types": [],
            "object_count_band": "1",
            "state_change_count": "0",
            "implicit_relation_count": "0",
            "base_quantity_shift": "none",
            "comparison_candidate_count": "0",
            "scenario_rule_count": "0",
            "process_stage_count": "1",
            "feedback_mechanism": "none",
            "comparison_basis": "none",
            "diagram_correspondence": "none",
            "scenario_rule_types": [],
            "text_length_band": "medium",
            "evidence_summary": "需要读懂题目场景和问题要求。",
        }
        features.update(overrides)
        return features

    def test_not_applicable_short_circuit(self, scorer):
        result = scorer.score({"not_applicable": True})

        assert result.applicable is False
        assert result.score == 0.0
        assert "不适用" in result.evidence

    def test_pure_direct_formula_is_not_applicable(self, scorer):
        result = scorer.score(
            self._dim3_features(
                scenario_comprehension_load="none",
                relevant_condition_count="1-2",
                text_length_band="short",
                evidence_summary="直接读取长和宽，套面积公式。",
            )
        )

        assert result.applicable is False
        assert result.score == 0.0

    def test_l1_direct_scene_reading(self, scorer):
        result = scorer.score(
            self._dim3_features(
                scenario_comprehension_load="light",
                relevant_condition_count="1-2",
                text_length_band="medium",
                evidence_summary="场景很直接，读完即可知道对象和动作。",
            )
        )

        assert result.applicable is True
        assert result.score == 2.0
        assert result.level_label == "L1 场景直读"

    def test_l2_simple_object_process_or_chart_mapping(self, scorer):
        result = scorer.score(
            self._dim3_features(
                source_form="table_chart",
                relevant_condition_count="3-4",
                scenario_comprehension_load="light",
                image_dependency="required",
                diagram_correspondence="helpful",
                evidence_summary="需要分清表中项目和题目所问对象的对应关系。",
            )
        )

        assert result.score == 4.0
        assert result.level_label == "L2 简单对象过程"

    def test_l3_throwing_bags_comparison_wording(self, scorer):
        result = scorer.score(
            self._dim3_features(
                source_form="table_chart",
                scenario_comprehension_load="medium",
                comparison_candidate_count="3+",
                comparison_basis="implicit",
                scenario_rule_types=["comparison_basis"],
                evidence_summary="投沙包题需要读懂“水平最高”是按同一口径比较表现，而不是直接看命中个数。",
            )
        )

        assert result.score == 6.0
        assert result.level_label == "L3 关键问法理解"

    def test_l4_valve_feedback_range_scene(self, scorer):
        result = scorer.score(
            self._dim3_features(
                source_form="image_text",
                scenario_comprehension_load="heavy",
                image_dependency="required",
                application_relation_types=["range_narrowing"],
                object_count_band="3",
                state_change_count="2",
                process_stage_count="3",
                feedback_mechanism="simple",
                diagram_correspondence="required",
                scenario_rule_count="2",
                scenario_rule_types=["feedback_rule", "diagram_mapping", "multi_stage_process"],
                evidence_summary="关阀门找漏水题需要读懂阀门操作、水表反馈、漏水范围和管线图对应关系。",
            )
        )

        assert result.score == 8.0
        assert result.level_label == "L4 多场景要素整合"
        assert result.details["scenario_integration_axis_count"] >= 3

    def test_l4_multi_element_scene_without_feedback_system(self, scorer):
        result = scorer.score(
            self._dim3_features(
                source_form="image_text",
                scenario_comprehension_load="medium",
                image_dependency="required",
                object_count_band="3",
                process_stage_count="2",
                scenario_rule_count="1",
                diagram_correspondence="required",
                scenario_rule_types=["diagram_mapping", "multi_object_roles", "multi_stage_process"],
                evidence_summary="结绳计数题需要同时读懂满五进一规则、从右到左的位置顺序和图文结点对应。",
            )
        )

        assert result.score == 8.0
        assert result.level_label == "L4 多场景要素整合"
        assert set(result.details["scenario_integration_axes"]) >= {
            "visual_material_mapping",
            "multi_object_roles",
            "multi_stage_process",
            "diagram_rule_mapping",
        }

    def test_l4_multi_stage_state_change_and_distributed_conditions(self, scorer):
        result = scorer.score(
            self._dim3_features(
                scenario_comprehension_load="medium",
                relevant_condition_count="5-6",
                condition_distribution="cross_sentence",
                object_count_band="3",
                state_change_count="2",
                process_stage_count="3",
                comparison_basis="implicit",
                scenario_rule_types=["multi_object_roles", "multi_stage_process", "comparison_basis"],
                evidence_summary="利润变化题需要同时读懂原状态、新状态、成本售价利润率三个对象和前后比较口径。",
            )
        )

        assert result.score == 8.0
        assert result.level_label == "L4 多场景要素整合"

    def test_l3_single_new_definition_stays_l3(self, scorer):
        result = scorer.score(
            self._dim3_features(
                scenario_comprehension_load="medium",
                relevant_condition_count="3-4",
                scenario_rule_count="1",
                scenario_rule_types=["sequence_order"],
                evidence_summary="相邻质数题只需要读懂差为2的质数对这个简单新定义。",
            )
        )

        assert result.score == 6.0
        assert result.level_label == "L3 关键问法理解"

    def test_l3_single_diagram_mapping_stays_l3(self, scorer):
        result = scorer.score(
            self._dim3_features(
                source_form="image_text",
                scenario_comprehension_load="medium",
                image_dependency="required",
                diagram_correspondence="required",
                scenario_rule_types=["diagram_mapping"],
                evidence_summary="从左面观察立体图题主要读懂一个观察方向和图形对应关系。",
            )
        )

        assert result.score == 6.0
        assert result.level_label == "L3 关键问法理解"

    def test_l4_robot_same_workload_time_comparison(self, scorer):
        result = scorer.score(
            self._dim3_features(
                scenario_comprehension_load="heavy",
                object_count_band="2",
                state_change_count="1",
                comparison_candidate_count="2",
                comparison_basis="multi_condition",
                scenario_rule_count="2",
                scenario_rule_types=["comparison_basis", "multi_object_roles"],
                evidence_summary="垃圾分拣机器人题需要读懂同量任务下用时比较和效率含义，容易误读比较口径。",
            )
        )

        assert result.score == 8.0

    def test_l4_double_circle_graphic_rule(self, scorer):
        result = scorer.score(
            self._dim3_features(
                source_form="image_text",
                scenario_comprehension_load="heavy",
                image_dependency="required",
                diagram_correspondence="required",
                scenario_rule_count="2",
                scenario_rule_types=["custom_rule_system", "diagram_mapping"],
                evidence_summary="双圆共生题需要读懂自定义图形设计规则，并把文字规则对应到图形位置。",
            )
        )

        assert result.score == 8.0

    def test_l5_multi_rule_coupon_system(self, scorer):
        result = scorer.score(
            self._dim3_features(
                source_form="multi_source",
                relevant_condition_count="7+",
                distractor_pressure="heavy",
                condition_distribution="cross_modal",
                scenario_comprehension_load="heavy",
                image_dependency="required",
                object_count_band="3",
                state_change_count="3+",
                process_stage_count="4+",
                feedback_mechanism="conditional",
                comparison_candidate_count="3+",
                comparison_basis="multi_condition",
                diagram_correspondence="multi_step",
                scenario_rule_count="3+",
                scenario_rule_types=[
                    "custom_rule_system",
                    "conditional_trigger",
                    "feedback_rule",
                    "multi_stage_process",
                ],
                evidence_summary="多规则积分券跨天使用题需要整体读懂规则、触发条件、阶段变化和反馈判断。",
            )
        )

        assert result.score == 9.5
        assert result.level_label == "L5 复杂规则系统理解"

    def test_old_conversion_fields_do_not_raise_dim3(self, scorer):
        result = scorer.score(
            self._dim3_features(
                scenario_comprehension_load="none",
                text_length_band="short",
                representation_conversion="custom_model",
                target_representation="custom_model",
                quantity_relation_structure="nested_relation",
                conversion_step_count="3+",
                global_organizing_required=1,
                evidence_summary="只有解题建模复杂，题面场景本身不复杂。",
            )
        )

        assert result.applicable is False

    def test_invalid_features_mark_not_applicable(self, scorer):
        result = scorer.score({"information_role": "core", "source_form": "text_only"})

        assert result.applicable is False
        assert result.score == 0.0
        assert "关键场景理解事实不完整" in result.evidence


class TestDim3Applicability:
    """测试 dim3 场景理解适用性门控"""

    def test_direct_formula_word_problem_is_not_applicable(self):
        result = evaluate_dim3_applicability(
            "一辆汽车 3 小时行了 180 千米，平均每小时行多少千米？",
            {
                "information_role": "core",
                "source_form": "text_only",
                "scenario_comprehension_load": "none",
                "image_dependency": "none",
                "evidence_summary": "直接读取路程和时间后代入公式。",
                "applicability_confidence": 0.92,
            },
            llm_confidence=0.92,
        )

        assert result["status"] == "not_applicable"

    def test_simple_life_scene_enters_dim3_l1_band(self):
        result = evaluate_dim3_applicability(
            "小明有5个苹果，又买了3个，现在一共有多少个？",
            {
                "information_role": "supporting",
                "source_form": "text_only",
                "scenario_comprehension_load": "light",
                "image_dependency": "none",
                "evidence_summary": "有简单生活场景，需要分清对象和动作，但读题负担很轻。",
                "applicability_confidence": 0.92,
            },
            llm_confidence=0.92,
        )

        assert result["status"] == "applicable"
        assert "低档纳入评分" in result["reason"]

    def test_simple_object_order_or_diagram_mapping_enters_dim3_l2_band(self):
        result = evaluate_dim3_applicability(
            "根据图中排队顺序，判断小红前面有几人。",
            {
                "information_role": "supporting",
                "source_form": "image_text",
                "scenario_comprehension_load": "light",
                "image_dependency": "helpful",
                "object_count_band": "2",
                "process_stage_count": "2",
                "diagram_correspondence": "helpful",
                "scenario_rule_types": ["sequence_order", "diagram_mapping"],
                "evidence_summary": "需要对应图中人物和前后顺序，但规则线性。",
                "applicability_confidence": 0.9,
            },
            llm_confidence=0.9,
            used_image=True,
        )

        assert result["status"] == "applicable"

    def test_scenario_feedback_burden_is_applicable(self):
        result = evaluate_dim3_applicability(
            "16户人家中有一户管道漏水，关闭某处阀门后根据水表是否显示用水判断漏水在哪一段，至少关闭几次才能确定位置？",
            {
                "information_role": "core",
                "source_form": "image_text",
                "scenario_comprehension_load": "heavy",
                "image_dependency": "required",
                "application_relation_types": ["range_narrowing"],
                "object_count_band": "3",
                "state_change_count": "2",
                "process_stage_count": "3",
                "feedback_mechanism": "simple",
                "diagram_correspondence": "required",
                "scenario_rule_count": "2",
                "scenario_rule_types": ["feedback_rule", "diagram_mapping"],
                "evidence_summary": "需要读懂关阀门后的水表反馈如何对应漏水范围。",
                "applicability_confidence": 0.9,
            },
            llm_confidence=0.9,
            used_image=True,
        )

        assert result["status"] == "applicable"

    def test_default_none_scenario_does_not_make_empty_feature_present(self):
        result = evaluate_dim3_applicability(
            "1 + 1 = ?",
            {"scenario_comprehension_load": "none"},
            llm_confidence=0.9,
        )

        assert result["status"] == "not_applicable"
        assert result["warnings"] == []

    def test_text_length_enrichment_uses_local_raw_text(self):
        raw_text = "甲" * 120
        feature = enrich_dim3_text_length_facts(raw_text, {"information_role": "core"})

        assert feature["text_length_chars"] == 120
        assert feature["text_length_band"] == "very_long"
        assert feature["text_length_source"] == "local_raw_text"

    def test_long_text_without_scene_burden_is_not_applicable(self):
        raw_text = "甲" * 130
        result = evaluate_dim3_applicability(
            raw_text,
            {
                "information_role": "core",
                "source_form": "text_only",
                "scenario_comprehension_load": "none",
                "image_dependency": "none",
                "evidence_summary": "只是重复文字，没有真实场景规则负担。",
                "applicability_confidence": 0.91,
            },
            llm_confidence=0.91,
        )

        assert result["status"] == "not_applicable"

    def test_table_chart_rule_mapping_is_applicable(self):
        result = evaluate_dim3_applicability(
            "根据统计图回答“平均表现最好”的队伍。",
            {
                "information_role": "core",
                "source_form": "table_chart",
                "scenario_comprehension_load": "medium",
                "image_dependency": "required",
                "comparison_basis": "implicit",
                "diagram_correspondence": "required",
                "scenario_rule_types": ["comparison_basis", "diagram_mapping"],
                "evidence_summary": "需要读懂统计图和“平均表现最好”的比较口径。",
                "applicability_confidence": 0.88,
            },
            llm_confidence=0.88,
            parse_audit={"visual_category": "table_chart", "image_required_hint": True},
            used_image=True,
        )

        assert result["status"] == "applicable"
        assert "核心读题门槛" in result["reason"]

    def test_missing_scene_facts_need_second_review(self):
        result = evaluate_dim3_applicability(
            "下表记录了三次测量结果，请判断哪次最接近标准值。",
            {
                "information_role": "core",
                "source_form": "table_chart",
                "evidence_summary": "缺少完整场景事实。",
            },
            llm_confidence=0.84,
            parse_audit={"visual_category": "table_chart", "image_required_hint": True},
            used_image=True,
        )

        assert result["status"] == "needs_second_review"
        assert "二次复评" in result["reason"]
        assert any("关键场景理解事实字段" in item for item in result["warnings"])

    def test_required_image_without_stable_image_use_needs_second_review(self):
        result = evaluate_dim3_applicability(
            "观察图文材料并回答问题。",
            {
                "information_role": "core",
                "source_form": "image_text",
                "scenario_comprehension_load": "heavy",
                "image_dependency": "required",
                "diagram_correspondence": "required",
                "scenario_rule_types": ["diagram_mapping"],
                "evidence_summary": "需要同时读取图片标注和文字规则。",
                "applicability_confidence": 0.9,
            },
            llm_confidence=0.9,
            parse_audit={"visual_category": "multi_part_layout", "image_required_hint": True},
            used_image=False,
            image_fallback=True,
        )

        assert result["status"] == "needs_second_review"
        assert any("依赖图片" in item or "退回纯文本" in item for item in result["warnings"])

    def test_source_label_does_not_change_dim3_score(self):
        scorer = Dim3InformationScorer()
        feature = {
            "information_role": "core",
            "source_form": "table_chart",
            "scenario_comprehension_load": "medium",
            "image_dependency": "required",
            "comparison_basis": "implicit",
            "diagram_correspondence": "required",
            "scenario_rule_types": ["comparison_basis", "diagram_mapping"],
            "evidence_summary": "需要读懂表格和隐含比较口径。",
        }

        base = scorer.score(feature)
        with_source = scorer.score({**feature, "paper_name": "WMO/竞赛/省测"})

        assert base.score == with_source.score
        assert base.level == with_source.level


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

        assert result["status"] == "needs_second_review"
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

        assert result["status"] == "needs_second_review"
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


    def test_dim6_second_review_applicable_payload_builds_score(self):
        review = {
            "status": "applicable",
            "level": "L3",
            "score": 6.0,
            "evidence_summary": "needs branch reasoning and condition backcheck",
            "confidence": 0.82,
            "exclude_reason": "",
        }

        normalized = normalize_second_review_payload("dim6", review)
        score = build_second_review_dimension_score(
            "dim6",
            review,
            initial_feature={"reasoning_role": "supporting"},
            initial_status={"status": "needs_second_review"},
        )

        assert normalized["status"] == "applicable"
        assert normalized["score"] == 6.0
        assert score.dimension_code == "dim6"
        assert score.score == 6.0
        assert score.applicable is True
        assert score.details["dim6_level"] == "L3"
        assert score.details["level_source"] == "second_review"
        assert score.details["evidence_summary"] == "needs branch reasoning and condition backcheck"

    def test_dim6_second_review_excludes_not_applicable_and_low_confidence(self):
        not_applicable = normalize_second_review_payload(
            "dim6",
            {
                "status": "not_applicable",
                "level": "N/A",
                "score": 0.0,
                "evidence_summary": "ordinary vertical calculation flow",
                "confidence": 0.78,
                "exclude_reason": "",
            },
        )
        low_burden_applicable = normalize_second_review_payload(
            "dim6",
            {
                "status": "applicable",
                "level": "L2",
                "score": 4.0,
                "evidence_summary": "only direct observation and one routine check",
                "confidence": 0.86,
                "exclude_reason": "",
            },
        )
        low_confidence = normalize_second_review_payload(
            "dim6",
            {
                "status": "applicable",
                "level": "L3",
                "score": 6.0,
                "evidence_summary": "unstable judgement",
                "confidence": 0.42,
                "exclude_reason": "",
            },
        )
        exclusion = build_second_review_exclusion_details(
            "dim6",
            low_confidence["raw_payload"],
            initial_feature={"reasoning_role": "core"},
            initial_status={"status": "needs_second_review"},
        )

        assert not_applicable["status"] == "not_applicable"
        assert low_burden_applicable["status"] == "not_applicable"
        assert low_burden_applicable["score"] == 0.0
        assert low_confidence["status"] == "unresolved"
        assert exclusion["status"] == "review_failed_excluded"
        assert exclusion["dim6_level"] == "N/A"


class TestDim4InnovationScorer:
    """测试维度4：建模解题复杂度评分器"""

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
        assert result.level_label == "L1 基础关系"

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
        assert result.level_label == "L3 条件组织"

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
        assert result.level_label == "L4 多关系建模"

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
        assert result.level_label == "L5 综合构造建模"

    def test_non_core_strategy_gets_low_level_fallback(self, scorer):
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

        assert result.applicable is True
        assert result.score == 4.0
        assert result.level == 2

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

    def test_source_label_does_not_change_dim4_score(self, scorer):
        feature = {
            "knowledge_point": "方案比较",
            "topic_level": "L4",
            "level_source": "knowledge_anchor",
            "anchor_evidence": "需要整理多个方案并按同一标准比较。",
            "evidence_summary": "需要整理多个方案并按同一标准比较。",
        }

        base = scorer.score(feature)
        with_source = scorer.score({**feature, "paper_name": "WMO/竞赛/省测"})

        assert base.score == with_source.score
        assert base.level == with_source.level

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

    def test_dim4_high_level_zero_confidence_placeholder_can_remain_applicable_but_low_confidence_needs_review(self, scorer):
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

        assert status["status"] == "needs_second_review"
        assert "置信度低于" in " ".join(status["warnings"])

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
                "anchor_evidence": "需要整理增长量、消耗量和剩余量之间的关系。",
                "fallback_used": False,
                "fallback_confidence": 0.0,
            },
            llm_confidence=0.86,
        )

        assert result["status"] == "applicable"

    def test_topic_level_without_modeling_fact_is_not_applicable(self):
        result = evaluate_dim4_applicability(
            "直接套用平均数公式。",
            {
                "knowledge_point": "平均数",
                "topic_level": "L3",
                "level_source": "knowledge_anchor",
                "anchor_evidence": "参考等级为 L3。",
                "fallback_used": False,
                "fallback_confidence": 0.0,
            },
            llm_confidence=0.86,
        )

        assert result["status"] == "not_applicable"
        assert "没有形成稳定的建模解题负担" in result["reason"]

    def test_l1_direct_topic_level_is_not_applicable_without_modeling_burden(self):
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
        assert "没有形成稳定的建模解题负担" in result["reason"]

    def test_l1_basic_quantity_relation_is_applicable(self):
        result = evaluate_dim4_applicability(
            "小明买3支笔共12元，求每支笔多少元。",
            {
                "knowledge_point": "基础数量关系",
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
                "evidence_summary": "读懂后需要建立总价、数量和单价之间的基础数量关系。",
                "applicability_confidence": 0.9,
            },
            llm_confidence=0.9,
        )

        assert result["status"] == "applicable"

    def test_l2_topic_level_without_light_variant_is_not_applicable(self):
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

    def test_dim4_review_failed_source_without_strategy_signal_stays_excluded(self):
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

        assert result["status"] == "not_applicable"
        assert "自动未覆盖" in result["reason"]
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
        assert "没有形成稳定的建模解题负担" in result["reason"]

    def test_missing_dim4_facts_need_second_review(self):
        result = evaluate_dim4_applicability(
            "请设计一种拼法并说明理由。",
            {
                "strategy_role": "core",
                "template_fit": "non_routine",
                "evidence_summary": "缺少完整建模解题事实。",
            },
            llm_confidence=0.8,
        )

        assert result["status"] == "needs_second_review"
        assert "二次复评" in result["reason"]
        assert any("关键建模解题事实字段" in item for item in result["warnings"])

    def test_conflicting_direct_template_needs_second_review(self):
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

        assert result["status"] == "needs_second_review"
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

    def test_reference_review_required_does_not_override_direct_template(self):
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
                "warning": "相似高思参考题显示建模解题负担，需复核。",
            },
            llm_confidence=0.9,
        )

        assert result["status"] == "not_applicable"
        assert "不能只凭参考来源" in result["reason"]


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

    @pytest.mark.asyncio
    async def test_partial_challenge_candidate_does_not_trigger_dim5_retry(self):
        class WeakReference:
            def gaosi_question_candidates(self, *args, **kwargs):
                return [
                    {
                        "section_level": "challenge",
                        "section_label": "超越篇",
                        "track": "高思导引",
                        "similarity_strength": 1,
                        "match_quality": "partial/audit_only",
                    }
                ]

        parser = AIParser.__new__(AIParser)
        parser.llm = self._FakeLLM()
        parser.reference_standard = WeakReference()
        normalized_features = {
            "dim5_knowledge": {
                "band": "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
                "sublevel": "mid",
                "core_knowledge_units": ["比例关系"],
                "knowledge_tags": ["比例关系"],
            }
        }
        question = ParsedQuestion(
            question_no="6",
            question_type=QuestionType.FILL_BLANK,
            raw_text="根据比例关系与方程条件整理数量关系后求未知数。",
        )

        await parser._ensure_dim5_band_with_retry(
            normalized_features,
            question=question,
            question_summary="比例关系",
            analysis_facts={"core_knowledge_points": ["比例关系"]},
            retry_required=False,
        )

        assert parser.llm.calls == 0
        assert normalized_features["dim5_knowledge"]["band"] == (
            "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度"
        )


class TestDim5RetrievalService:
    def _service(self, entries):
        return Dim5RetrievalService(SimpleNamespace(entries=entries))

    def test_basic_travel_structure_stays_school_core(self):
        service = self._service(
            [
                ReferenceEntry(
                    source="school",
                    sheet_name="校内",
                    category="数量关系",
                    title="行程问题",
                    track="校内",
                    grade_hint="5年级",
                    keywords=("行程问题", "相遇问题", "速度", "路程", "时间"),
                ),
                ReferenceEntry(
                    source="guide",
                    sheet_name="高思导引章节序",
                    category="应用题",
                    title="行程问题一",
                    track="高思导引",
                    grade_hint="5年级",
                    keywords=("行程问题", "相遇问题"),
                ),
            ]
        )

        context = service.retrieve(
            question_text="甲乙两地相距240千米，两车同时相向而行，甲车每小时60千米，乙车每小时40千米，几小时后相遇？"
        )

        structure = context["topic_structure_candidates"][0]
        assert structure["match_scope"] == "topic_structure"
        assert structure["recommended_level"] == "L2"
        assert structure["can_raise_level"] is False
        assert any(candidate["source_family"] == "school" for candidate in context["knowledge_point_candidates"])

    def test_advanced_travel_structure_can_raise_to_l4(self):
        service = self._service([])

        context = service.retrieve(
            question_text=(
                "甲乙两人分别从A、B两地同时出发，第一次相遇后继续往返，"
                "第二次相遇在中点附近；如果甲提前1小时出发，相遇点发生变化。"
            )
        )

        top = context["top_recommendation"]
        assert top["match_scope"] == "topic_structure"
        assert top["recommended_level"] == "L4"
        assert top["can_raise_level"] is True

    def test_exact_gaosi_question_match_can_raise_by_section(self):
        service = self._service(
            [
                ReferenceEntry(
                    source="gaosi_question_pdf",
                    sheet_name="高思题库",
                    category="应用题",
                    title="牛吃草问题",
                    track="拓展篇",
                    grade="5",
                    book_name="竞赛数学导引 五年级",
                    lecture_no="12",
                    lecture_title="牛吃草问题",
                    section_level="extension",
                    section_label="拓展篇",
                    question_no="4",
                    question_text="一片草地每天都在均匀生长，15头牛8天可以吃完，20头牛5天可以吃完，问多少头牛4天可以吃完？",
                    ocr_confidence=0.95,
                    dimension_profiles={
                        "dim5": {
                            "knowledge_anchor_terms": ["牛吃草问题"],
                            "dim5_reference_band": "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
                            "dim5_reference_sublevel": "mid",
                        }
                    },
                )
            ]
        )

        context = service.retrieve(
            question_text="一片草地每天都在均匀生长，15头牛8天可以吃完，20头牛5天可以吃完，问多少头牛4天可以吃完？"
        )

        question_candidate = context["reference_question_candidates"][0]
        assert question_candidate["match_scope"] == "reference_question"
        assert question_candidate["match_strength"] == 3
        assert question_candidate["recommended_level"] == "L4"
        assert question_candidate["can_raise_level"] is True

    def test_direct_formula_caps_local_structure_candidate(self):
        service = self._service([])

        context = service.retrieve(
            question_text="直接代入圆柱体积公式计算：圆柱底面积是12平方厘米，高是5厘米，体积是多少？"
        )

        assert context["query"]["direct_formula_guard"] is True
        assert all(
            candidate["recommended_level"] in {"L1", "L2"}
            or candidate["can_raise_level"] is False
            for candidate in context["candidates"]
        )


class TestDim5KnowledgeGroundingService:
    def _service(self, entries=None):
        return Dim5KnowledgeGroundingService(SimpleNamespace(entries=entries or []))

    @staticmethod
    def _weak_fragment_entries():
        return [
            ReferenceEntry(
                source="gaosi_question_pdf",
                sheet_name="",
                category="",
                title="简单规律与数列",
                track="",
                keywords=("10", "12", "13", "14", "15", "20", "25", "30", "52", "81", "120"),
                dimension_profiles={"dim5": {"knowledge_tags": ["简单规律与数列"]}},
            ),
            ReferenceEntry(
                source="gaosi_question_pdf",
                sheet_name="",
                category="",
                title="高阶数论综合",
                track="",
                keywords=("ab", "abc", "ade", "de", "34"),
                dimension_profiles={"dim5": {"knowledge_tags": ["高阶数论综合"]}},
            ),
        ]

    @pytest.mark.parametrize(
        "question_text",
        [
            "(5/6 * 10.68 + 8.52 * 5/6) / 1 3/5",
            "68.1 + 53 * 6.81 - 0.13 * 681",
            "68.1 + 53 \u00d7 6.81 - 0.13 \u00d7 681",
        ],
    )
    def test_pure_calculation_prefers_distributive_law_over_number_theory(
        self,
        question_text,
    ):
        service = self._service()

        result = service.ground(
            question_text=question_text,
            question_type="calculation",
            analysis_facts={
                "core_knowledge_points": ["因数倍数与质合数"],
                "core_methods": ["提取公因数"],
            },
        )

        assert result["grounded_canonical_knowledge_point"] == "乘法分配律与简便计算"
        assert result["grounded_confidence"] >= 0.70
        assert result["grounded_risk_flags"] == []
        assert all(
            candidate["canonical_knowledge_point"] != "因数倍数与质合数"
            or "blocked_number_theory_in_calculation" in candidate["risk_flags"]
            or candidate["match_source"] == "analysis_facts_only"
            for candidate in result["candidates"]
        )

    def test_analysis_facts_only_candidate_is_risk_flagged_and_low_confidence(self):
        service = self._service()

        result = service.ground(
            question_text="这道题的原题文本缺失，只保留了题号。",
            question_type="calculation",
            analysis_facts={
                "core_knowledge_points": ["因数倍数与质合数"],
                "core_methods": ["整除"],
            },
        )

        assert result["grounded_confidence"] < 0.55
        assert "analysis_facts_only" in result["grounded_risk_flags"]
        assert any(
            "analysis_facts_only" in candidate["risk_flags"]
            for candidate in result["candidates"]
        )

    def test_real_number_theory_question_still_selects_factor_multiple_prime(self):
        service = self._service()

        result = service.ground(
            question_text="一个两位数既是 6 的倍数，又有 4 个因数，判断它可能是多少。",
            question_type="application",
            analysis_facts={},
        )

        assert result["grounded_canonical_knowledge_point"] == "因数倍数与质合数"
        assert result["grounded_confidence"] >= 0.55
        assert "blocked_number_theory_in_calculation" not in result["grounded_risk_flags"]

    def test_profit_problem_rejects_numeric_sequence_fragment_match(self):
        service = self._service(self._weak_fragment_entries())

        result = service.ground(
            question_text=(
                "商品甲在进价的基础上加价20%出售获利30元，商品乙在进价的基础上加价25%后"
                "与甲商品的销售价一样，则乙商品的进价是（  ）元。A.100 B.120 C.125 D.144"
            ),
            question_type="application",
            analysis_facts={
                "core_knowledge_points": ["百分数应用", "利润问题", "等量关系"],
                "core_methods": ["列方程"],
            },
        )

        assert result["grounded_canonical_knowledge_point"] in {"利润折扣问题", "比例百分数应用"}
        assert result["grounded_canonical_knowledge_point"] != "简单规律与数列"
        assert result["grounded_confidence"] >= 0.55
        assert any("weak_evidence" in candidate["risk_flags"] for candidate in result["candidates"])

    def test_work_rate_problem_rejects_numeric_sequence_fragment_match(self):
        service = self._service(self._weak_fragment_entries())

        result = service.ground(
            question_text=(
                "某工程由甲单独做20天完成，由乙单独做30天完成，开始时甲、乙两人合作，"
                "中途甲因有事走了几天，经过15天才完成工程，甲中途走了（  ）天。A.2 B.3 C.5 D.10"
            ),
            question_type="application",
            analysis_facts={
                "core_knowledge_points": ["工程问题", "工作效率", "合作与中断"],
                "core_methods": ["列方程"],
            },
        )

        assert result["grounded_canonical_knowledge_point"] == "工程效率问题"
        assert result["grounded_confidence"] >= 0.55
        assert all(
            candidate["canonical_knowledge_point"] != "简单规律与数列"
            or "weak_evidence" in candidate["risk_flags"]
            or "conflicting_question_structure" in candidate["risk_flags"]
            for candidate in result["candidates"]
        )

    def test_geometry_folding_problem_rejects_letter_fragment_number_theory_match(self):
        service = self._service(self._weak_fragment_entries())

        result = service.ground(
            question_text=(
                "如图，点D、E分别是△ABC的边AB、AC的中点，连接DE，将△ADE沿DE翻折，"
                "点A正落在BC边的点F上，若△ABC的面积是34，则△FDE的面积是______。"
            ),
            question_type="geometry",
            analysis_facts={
                "core_knowledge_points": ["三角形中位线定理", "图形翻折对称性质", "三角形面积关系"],
                "core_methods": ["几何面积关系"],
            },
        )

        assert result["grounded_canonical_knowledge_point"] == "三角形中位线与翻折面积"
        assert result["grounded_knowledge_domain"] == "geometry_spatial"
        assert result["grounded_canonical_knowledge_point"] != "高阶数论综合"
        assert any("weak_evidence" in candidate["risk_flags"] for candidate in result["candidates"])

    def test_grazing_slot_requires_growth_and_consumption_structure(self):
        service = self._service()

        result = service.ground(
            question_text="一片草地原有草量，每天均匀生长，若干头牛每天吃草，最后吃完。",
            question_type="application",
            analysis_facts={},
        )

        assert result["grounded_canonical_knowledge_point"] == "牛吃草模型"
        assert result["grounded_confidence"] >= 0.70
        assert result["grounded_match_source"] == "structure"

    @pytest.mark.parametrize(
        (
            "question_text",
            "analysis_facts",
            "expected_point",
            "expected_level",
            "wrong_points",
        ),
        [
            (
                "一块冰，每小时失去其质量的一半，八小时后其质量为 9/64 千克，那么这块冰一开始的质量是（  ）千克。 A.3 B.24 C.36 D.48",
                {"core_knowledge_points": ["倒推还原", "分数乘除", "指数变化"], "core_methods": ["逆推"]},
                "倍半递推与倒推还原",
                "L3",
                {"行程问题"},
            ),
            (
                "计算：3/(2×7) + 3/(7×12) + 3/(12×17) + ... + 3/(47×52) = （  ）。 A. 5/52 B. 15/52 C. 75/52 D. 81/260",
                {"core_knowledge_points": ["分数裂项求和", "等差数列通项", "数列求和"], "core_methods": ["裂项相消"]},
                "分数裂项求和",
                "L4",
                {"小数分数混合运算"},
            ),
            (
                "将透明正方体的部分顶点和棱的中点连起来得到如下图，从左面观察该正方体，看到的图形是（  ）。",
                {"core_knowledge_points": ["三视图", "正方体", "左视图", "投影"], "core_methods": ["空间想象"]},
                "三视图与立体图形",
                "L4",
                {"高年级校内图形公式"},
            ),
            (
                "魔术师让观众在心里想一个四位数写在纸上，不让任何人看见。再让观众用这个四位数减去各个数位上的数字之和，得到的结果仍然是一个四位数，再将得到的结果任意删去一个非零的数字，最后说出剩下的3个数字，这名观众说出剩下的数字是3，5，7。那么被删去的数字是（  ）。 A.5 B.4 C.3 D.2",
                {"core_knowledge_points": ["数字和性质", "9的倍数判定", "整除性质"], "core_methods": ["数字性质"]},
                "数字性质与9的倍数判定",
                "L3",
                {"还原与盈亏问题"},
            ),
            (
                "某旅游团56人在快餐店就餐，该店备有9种菜，每份单价分别为4、5、6、7、8、9、10、11、12元，该旅游团领队交代：每人可选不同的菜，但金额都正好是16元，且每种菜最多只能买一份。这样，该团成员中，购菜品种完全相同的至少有（  ）人。 A.9 B.10 C.11 D.12",
                {"core_knowledge_points": ["抽屉原理", "整数拆分", "组合枚举"], "core_methods": ["最不利原则"]},
                "抽屉原理与组合枚举",
                "L4",
                {"还原与盈亏问题"},
            ),
            (
                "按照下面的规则，欧欧和小泉分别选一种颜色的棋子（黑色或白色），在棋盘上移动棋子。如果欧欧选择的是黑色棋子，此时轮到他移动棋子，他若想获胜，需要采取的制胜策略是（  ）。 规则：①黑色棋子只能向右移动，白色棋子只能向左移动。②每个玩家每次可以将棋子移动任意格数（注意移动的棋子不能跳过其他棋子）。③最后无法移动棋子的玩家输掉游戏。",
                {"core_knowledge_points": ["博弈必胜策略", "对称策略", "状态镜像"], "core_methods": ["制胜策略"]},
                "博弈策略与必胜策略",
                "L5",
                {"还原与盈亏问题"},
            ),
            (
                "某公司一月到四月的产品销售量有如下关系：一月的销售量与二、三、四月的销售量之和的比是1:4；二月的销售量与一、三、四月的销售量之和的比是1:3；三月的销售量与一、二、四月的销售量之和的比是1:2。四月的销售量是455台，那么这四个月的销售总量是_______台。",
                {"core_knowledge_points": ["比例关系", "方程组", "整体与部分关系"], "core_methods": ["比例转化"]},
                "比例整体关系",
                "L3",
                {"高年级校内数与代数"},
            ),
            (
                "从左图立体图形的27个透明积木中，选若干个用绿色积木（不透明）替换后，从前面和左面看到的图形如右图所示。第一问：最少可以用______个绿色积木。第二问：最多可以用______个绿色积木。",
                {"core_knowledge_points": ["三视图", "立体图形", "空间想象", "极值分析"], "core_methods": ["空间极值构造"]},
                "三视图空间极值构造",
                "L4",
                {"典型应用题入门模型"},
            ),
        ],
    )
    def test_wmo_26_structure_slots_override_generic_or_weak_matches(
        self,
        question_text,
        analysis_facts,
        expected_point,
        expected_level,
        wrong_points,
    ):
        service = Dim5KnowledgeGroundingService(get_reference_standard())

        result = service.ground(
            question_text=question_text,
            question_type="competition",
            analysis_facts=analysis_facts,
        )

        assert result["grounded_canonical_knowledge_point"] == expected_point
        assert result["grounded_knowledge_level"] == expected_level
        assert result["grounded_confidence"] >= 0.70
        assert result["grounded_match_source"] in {"structure", "question_text+structure", "both"}
        assert result["grounded_canonical_knowledge_point"] not in wrong_points
        assert not result["grounded_risk_flags"]


class TestDim5KnowledgeScorer:
    """测试维度5：知识点广度评分器"""

    @pytest.fixture
    def scorer(self):
        return Dim5KnowledgeScorer()

    @pytest.mark.parametrize(
        ("analysis_facts", "question_text", "expected_point"),
        [
            (
                {"core_knowledge_points": ["增长与消耗"], "core_methods": ["排队检票"]},
                "原有队伍每分钟新增若干人，同时每分钟检票若干人。",
                "牛吃草模型",
            ),
            (
                {"core_knowledge_points": ["等高面积比"], "core_methods": ["共边面积比"]},
                "图中需要利用蝴蝶模型和燕尾模型求阴影面积。",
                "面积比模型",
            ),
            (
                {"core_knowledge_points": ["循环规律"], "core_methods": ["周期余数"]},
                "按周期排列，求第 n 项的位置。",
                "周期问题",
            ),
            (
                {"core_knowledge_points": ["倍半递推与倒推还原"], "core_methods": ["逆推"]},
                "每小时失去一半，八小时后已知末端质量。",
                "倍半递推与倒推还原",
            ),
            (
                {"core_knowledge_points": ["数字性质与9的倍数判定"], "core_methods": ["数位和"]},
                "四位数减去各个数位上的数字之和后，再删去一个数字。",
                "数字性质与9的倍数判定",
            ),
            (
                {"core_knowledge_points": ["三视图空间极值构造"], "core_methods": ["空间极值构造"]},
                "根据从前面和左面看到的图形，求透明积木替换的最少和最多个数。",
                "三视图空间极值构造",
            ),
        ],
    )
    def test_dim5_canonicalizes_free_form_knowledge_points(
        self,
        analysis_facts,
        question_text,
        expected_point,
    ):
        canonical = canonicalize_dim5_knowledge(
            {"knowledge_tags": []},
            analysis_facts=analysis_facts,
            question_text=question_text,
        )

        assert canonical["canonical_knowledge_point"] == expected_point
        assert canonical["canonical_match_confidence"] >= 0.65

    def test_dim5_reference_knowledge_terms_map_to_domain_and_level(self):
        reference_files = [
            "app/services/parser/reference_standard_school_pdf_data.json",
            "app/services/parser/reference_standard_gaosi_pdf_data.json",
            "app/services/parser/reference_standard_gaosi_question_data.json",
            "app/services/parser/reference_standard_data.json",
        ]

        def collect_strings(value):
            if isinstance(value, dict):
                for key in (
                    "topic",
                    "title",
                    "knowledge_point",
                    "knowledge",
                    "chapter",
                    "section",
                    "name",
                    "track",
                ):
                    text = str(value.get(key) or "").strip()
                    if text:
                        yield text
                for item in value.values():
                    yield from collect_strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from collect_strings(item)
            elif isinstance(value, str) and value.strip():
                yield value.strip()

        checked_terms = set()
        for relative_path in reference_files:
            data = json.loads(Path(relative_path).read_text(encoding="utf-8"))
            for term in collect_strings(data):
                if term in checked_terms:
                    continue
                checked_terms.add(term)
                result = classify_dim5_knowledge_scope(
                    {"knowledge_tags": [term]},
                    analysis_facts={"core_knowledge_points": [term]},
                )
                assert result["canonical_knowledge_domain"] in DIM5_KNOWLEDGE_DOMAINS
                assert result["knowledge_level"] in DIM5_LEVEL_SCORES

        assert checked_terms

    def test_canonical_boundary_upshift_chooses_higher_adjacent_band(self, scorer):
        result = scorer.score(
            {
                "band": "4年级及以前高思导引拓展篇及以下难度",
                "sublevel": "high",
                "evidence_summary": "等高面积比与割补共同出现，处于拓展到高年级高思边界。",
                "knowledge_tags": ["面积比"],
                "canonical_knowledge_point": "面积比模型",
                "canonical_knowledge_family": "geometry_olympiad_model",
                "canonical_match_source": "topic_and_structure",
                "canonical_match_confidence": 0.88,
                "canonical_alias_hits": ["面积比", "等高"],
                "canonical_structure_hits": ["割补"],
            }
        )

        assert result.applicable is True
        assert result.score == 8.0
        assert result.details["knowledge_level"] == "L4"
        assert result.details["canonical_knowledge_domain"] == "geometry_spatial"
        assert result.details["canonical_knowledge_point"] == "面积比模型"

    def test_canonical_boundary_upshift_does_not_raise_direct_formula(self, scorer):
        result = scorer.score(
            {
                "band": "5、6年级校内课本难度",
                "sublevel": "high",
                "evidence_summary": "直接代入圆柱圆锥体积比公式。",
                "knowledge_tags": ["圆柱圆锥体积比"],
                "canonical_knowledge_point": "面积比模型",
                "canonical_knowledge_family": "geometry_olympiad_model",
                "canonical_match_source": "topic_and_structure",
                "canonical_match_confidence": 0.88,
                "canonical_alias_hits": ["面积比"],
                "canonical_structure_hits": ["比例"],
                "canonical_direct_formula_guard": True,
            }
        )

        assert result.applicable is True
        assert result.score == 4.0
        assert result.details["knowledge_level"] == "L2"
        assert result.details["canonical_direct_formula_guard"] is True

    def test_retrieval_topic_structure_can_raise_conservative_band(self, scorer):
        result = scorer.score(
            {
                "band": "5、6年级校内课本难度",
                "sublevel": "mid",
                "evidence_summary": "模型初判为普通行程问题。",
                "knowledge_tags": ["行程问题"],
                "dim5_retrieval_context": {
                    "candidates": [
                        {
                            "candidate_id": "topic_structure:travel",
                            "match_scope": "topic_structure",
                            "source": "local_structure_rules",
                            "title": "行程相遇追及结构",
                            "matched_terms": ["行程", "相遇"],
                            "structure_signals": ["多次相遇", "往返", "相遇点变化"],
                            "recommended_level": "L4",
                            "can_raise_level": True,
                            "score": 32,
                        }
                    ]
                },
            }
        )

        assert result.applicable is True
        assert result.score == 8.0
        assert result.details["knowledge_level"] == "L4"
        assert result.details["level_source"] == "retrieval_topic_structure"

    def test_retrieval_partial_question_match_is_audit_only(self, scorer):
        result = scorer.score(
            {
                "band": "5、6年级校内课本难度",
                "sublevel": "mid",
                "evidence_summary": "仅有普通速度关系。",
                "knowledge_tags": ["速度", "相遇问题"],
                "dim5_retrieval_context": {
                    "candidates": [
                        {
                            "candidate_id": "reference_question:partial",
                            "match_scope": "reference_question",
                            "source": "gaosi_question_pdf",
                            "title": "行程问题一",
                            "matched_terms": ["相遇问题"],
                            "structure_signals": [],
                            "section_level": "challenge",
                            "section_label": "超越篇",
                            "match_strength": 1,
                            "quality_flags": [],
                            "recommended_level": "L5",
                            "can_raise_level": False,
                            "score": 12,
                        }
                    ]
                },
            }
        )

        assert result.applicable is True
        assert result.details["knowledge_level"] == "L2"
        assert result.score == 4.0

    def test_retrieval_direct_formula_guard_blocks_high_candidate(self, scorer):
        result = scorer.score(
            {
                "band": "5、6年级校内课本难度",
                "sublevel": "high",
                "evidence_summary": "直接代入圆柱体积公式。",
                "knowledge_tags": ["圆柱体积", "高思导引"],
                "dim5_retrieval_context": {
                    "candidates": [
                        {
                            "candidate_id": "reference_question:challenge",
                            "match_scope": "reference_question",
                            "source": "gaosi_question_pdf",
                            "title": "立体几何超越篇",
                            "matched_terms": ["圆柱体积"],
                            "structure_signals": ["体积"],
                            "section_level": "challenge",
                            "section_label": "超越篇",
                            "match_strength": 3,
                            "quality_flags": [],
                            "recommended_level": "L5",
                            "can_raise_level": True,
                            "score": 90,
                        }
                    ]
                },
            }
        )

        assert result.applicable is True
        assert result.details["knowledge_level"] == "L2"
        assert result.details["canonical_direct_formula_guard"] is True

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
        assert result.score == 8.0
        assert result.details["knowledge_level"] == "L4"
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
        assert result.score == 4.0
        assert result.details["band"] == "5、6年级校内课本难度"
        assert result.details["knowledge_level"] == "L2"
        assert result.details["knowledge_source_bucket"] == "school"

    def test_transcend_level(self, scorer):
        features = {
            "band": "高思导引超越篇难度",
            "sublevel": "mid",
            "evidence_summary": "小升初压轴题，需要复杂组合计数和多条件分类讨论。",
            "knowledge_tags": ["复杂组合计数", "分类讨论"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 9.5
        assert result.level == 5
        assert result.details["knowledge_source_bucket"] == "beyond"

    def test_junior_bridge_bucket_for_middle_school_signal(self, scorer):
        features = {
            "band": "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
            "sublevel": "mid",
            "evidence_summary": "需要使用七上一次方程作为基础前置知识。",
            "knowledge_tags": ["一次方程", "比例关系"],
            "core_knowledge_units": ["一次方程"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.details["knowledge_level"] == "L4"
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
        assert result.details["knowledge_level"] == "L4"
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
        assert result.score == 8.0
        assert result.details["knowledge_level"] == "L4"
        assert result.details["knowledge_source_bucket"] == "high_gaosi"

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
        assert result.score == 8.0
        assert result.details["knowledge_level"] == "L4"
        assert result.details["knowledge_source_bucket"] == "high_gaosi"

    def test_gaosi_interest_and_hard_grade6_challenge_map_to_expected_levels(self, scorer):
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
                "evidence_summary": "题目级参考命中六年级较难变式，需要复杂计数。",
                "knowledge_tags": ["复杂计数"],
            }
        )

        assert interest.applicable is True
        assert interest.score == 6.0
        assert interest.details["knowledge_level"] == "L3"
        assert interest.details["knowledge_source_bucket"] == "low_gaosi"
        assert challenge.applicable is True
        assert challenge.score == 9.5
        assert challenge.details["knowledge_source_bucket"] == "beyond"

    def test_explicit_gaosi_challenge_section_alone_does_not_enter_beyond_bucket(self, scorer):
        features = {
            "band": "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
            "sublevel": "high",
            "evidence_summary": "题目级参考库命中六年级超越篇题目。",
            "gaosi_section_level": "challenge",
            "gaosi_section_label": "超越篇",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.details["knowledge_level"] == "L4"
        assert result.details["knowledge_source_bucket"] == "high_gaosi"

    def test_wmo_anchor_promotes_school_band_to_high_gaosi_not_beyond(self, scorer):
        features = {
            "band": "5、6年级校内课本难度",
            "sublevel": "mid",
            "evidence_summary": "题目核心是抽屉原理与组合计数，不是普通校内应用题。",
            "knowledge_tags": ["抽屉原理", "组合计数"],
            "core_knowledge_units": ["抽屉原理"],
            "competition_signal": "none",
        }

        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.details["knowledge_level"] == "L4"
        assert result.details["knowledge_source_bucket"] == "high_gaosi"

    def test_wmo_strong_anchor_can_promote_high_gaosi_to_beyond(self, scorer):
        features = {
            "band": "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
            "sublevel": "mid",
            "evidence_summary": "需要博弈必胜策略、对称策略和不变量共同保证全局制胜。",
            "knowledge_tags": ["博弈必胜", "对称策略", "不变量"],
            "core_knowledge_units": ["博弈", "不变量"],
            "knowledge_integration": "cross_family_combo",
            "competition_signal": "strong",
        }

        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 9.5
        assert result.details["knowledge_level"] == "L5"
        assert result.details["knowledge_source_bucket"] == "beyond"

    def test_wmo_contest_word_does_not_promote_direct_formula_problem(self, scorer):
        features = {
            "band": "5、6年级校内课本难度",
            "sublevel": "high",
            "evidence_summary": "WMO样本中的直接圆柱圆锥体积比公式题。",
            "knowledge_tags": ["圆柱圆锥体积比"],
            "core_knowledge_units": ["圆柱和圆锥体积"],
            "competition_signal": "strong",
        }

        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 4.0
        assert result.details["knowledge_level"] == "L2"
        assert result.details["knowledge_source_bucket"] == "school"

    def test_invalid_knowledge_band(self, scorer):
        result = scorer.score({"band": "未知", "sublevel": "high"})

        assert result.applicable is True
        assert result.score == 2.0
        assert result.details["knowledge_level"] == "L1"


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
        assert result.level_label == "L1 直接判断"

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
        assert result.level_label == "L3 连续多步"

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
        assert result.level_label == "L4 分类倒推回查"

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
        assert result.level_label == "L5 复合压轴推理"

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

    def test_multi_stage_profit_chain_maps_to_l5_after_recalibration(self, scorer):
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
        assert result.score == 9.5
        assert result.details["dim6_level"] == "L5"
        assert result.details["dim6_level_reason_code"] == "state_changes_with_condition_pressure"

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

    def test_bounded_optimization_comparison_maps_to_l5_after_recalibration(self, scorer):
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
        assert result.score == 9.5
        assert result.details["dim6_level"] == "L5"
        assert result.details["dim6_level_reason_code"] == "case_backcheck_with_condition_pressure"

    def test_simple_bounded_enumeration_without_backcheck_stays_l4(self, scorer):
        features = {
            "reasoning_role": "core",
            "chain_span": "3-4",
            "hidden_dependency": "local",
            "branch_control": "explicit_cases",
            "reversibility": "none",
            "verification_requirement": "result_check",
            "abstraction_bridge_count": "1",
            "constraint_coupling": "single",
            "global_consistency_required": 0,
            "conclusion_stability": "edge_sensitive",
            "logic_structure_types": ["bounded_case_enumeration"],
            "state_transition_count": "1",
            "case_count_band": "3-5",
            "backtrack_depth": "0",
            "consistency_constraint_count": "1",
            "phase_count_band": "2",
            "periodic_cycle_dependency": 0,
            "optimization_requirement": "none",
            "evidence_summary": "只需要列出有限情况并做简单检查。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.0
        assert result.details["dim6_level"] == "L4"

    def test_long_chain_with_backcheck_maps_to_l5_after_recalibration(self, scorer):
        features = {
            "reasoning_role": "core",
            "chain_span": "5+",
            "hidden_dependency": "cross_condition",
            "branch_control": "none",
            "reversibility": "none",
            "verification_requirement": "constraint_backcheck",
            "abstraction_bridge_count": "2",
            "constraint_coupling": "coupled",
            "global_consistency_required": 1,
            "conclusion_stability": "edge_sensitive",
            "logic_structure_types": ["shared_variable_coupling"],
            "state_transition_count": "2",
            "case_count_band": "none",
            "backtrack_depth": "0",
            "consistency_constraint_count": "2-3",
            "phase_count_band": "3-4",
            "periodic_cycle_dependency": 0,
            "optimization_requirement": "none",
            "evidence_summary": "需要连续推进五步以上，并把中间结论代回多个条件检查。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 9.5
        assert result.details["dim6_level"] == "L5"
        assert result.details["dim6_level_reason_code"] == "long_chain_with_backcheck"

    def test_two_layer_reverse_process_with_multiple_conditions_maps_to_l5(self, scorer):
        features = {
            "reasoning_role": "core",
            "chain_span": "3-4",
            "hidden_dependency": "cross_condition",
            "branch_control": "none",
            "reversibility": "backward",
            "verification_requirement": "constraint_backcheck",
            "abstraction_bridge_count": "2",
            "constraint_coupling": "coupled",
            "global_consistency_required": 1,
            "conclusion_stability": "edge_sensitive",
            "logic_structure_types": ["reverse_process_chain"],
            "state_transition_count": "2",
            "case_count_band": "none",
            "backtrack_depth": "2",
            "consistency_constraint_count": "2-3",
            "phase_count_band": "3-4",
            "periodic_cycle_dependency": 0,
            "optimization_requirement": "none",
            "evidence_summary": "需要两层倒推，并把还原出的结果代回多个条件。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 9.5
        assert result.details["dim6_level"] == "L5"
        assert result.details["dim6_level_reason_code"] == "reverse_backtrack_with_multiple_conditions"

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
        assert result.evidence == (
            "计算维度，综合得分 7.0 分，"
            "说明本卷有一定计算难度，除准确率外，也考查多步运算和常见转化。"
        )
        assert result.score_breakdown["pure_calculation"]["question_count"] == 2
        assert result.score_breakdown["pure_calculation"]["weight"] == 1.0
        assert "总分值" not in result.evidence
        assert "复核提示" not in result.evidence
        assert "计入数学运算评分" not in result.evidence
        assert "纯计算题" not in result.evidence
        assert "权重" not in result.evidence
        assert len(result.counted_questions) == 2
        assert result.counted_questions[0]["question_no"] == "2"
        assert result.counted_questions[0]["question_label_raw"] == "（2）"
        assert result.counted_questions[0]["question_display_label"] == "（2）"
        assert result.counted_questions[0]["page_no"] == 2
        assert result.counted_questions[0]["score"] == 8.0
        assert result.counted_questions[0]["level_code"] == "L4"
        assert result.counted_questions[0]["difficulty_label"] == "较难（8.0）"
        assert result.counted_questions[0]["full_reason"].startswith("较难（8.0）：主要考查比例与单位换算")
        assert "核心计算能力" not in result.counted_questions[0]["full_reason"]

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

        assert counted_question["reason"].startswith("较难（8.0）：主要考查结构计算题")
        assert counted_question["full_reason"].startswith("较难（8.0）：主要考查结构计算题")
        assert counted_question["difficulty_label"] == "较难（8.0）"
        assert "核心计算能力" not in counted_question["reason"]
        assert "高阶结构巧算" not in counted_question["reason"]
        assert "依据：文本" not in counted_question["reason"]

    def test_dim1_counted_question_level_notes_are_teacher_readable(self, aggregator):
        cases = [
            ("L1", 2.0, "简单（2.0）", "属于基础计算要求，主要看基本运算是否准确。"),
            ("L2", 4.0, "较易（4.0）", "属于常规校内计算，主要区分熟练度和准确率。"),
            ("L3", 6.0, "中等（6.0）", "有一定转换或多步计算要求，常见失分点是算式落地和运算顺序。"),
            ("L4", 8.0, "较难（8.0）", "学习范围或计算量偏高，常见失分点是连续化简和计算准确率。"),
            ("L5", 9.5, "困难（9.5）", "属于高强度或拓展计算，容易拉开学生在综合计算上的差距。"),
        ]
        forbidden_terms = ["方法选择", "步骤组织", "计算稳定性", "适合观察", "核心计算能力"]

        for level_code, score, difficulty_label, expected_note in cases:
            question = QuestionDimensionScore(
                question_id=f"q-{level_code}",
                question_no=level_code,
                score=score,
                dim_scores={"dim1": score},
                applicable_dims=["dim1"],
                question_summary="核心计算能力",
                dim_reasons={"dim1": "旧版分析不应直接展示。"},
                dim_confidences={"dim1": 0.9},
                dim_details={
                    "dim1": {
                        "dim1_level": level_code,
                        "display_knowledge_range_label": "校内五年级",
                        "display_knowledge_points": ["小数四则混合运算"],
                    }
                },
            )

            reason = aggregator._build_dim1_counted_question_reason(question)

            assert (
                reason
                == f"{difficulty_label}：主要考查校内五年级的小数四则混合运算；{expected_note}"
            )
            for term in forbidden_terms:
                assert term not in reason

    def test_dim1_score_overview_explains_score_bands(self, aggregator):
        cases = [
            (
                2.0,
                "计算维度，综合得分 2.0 分，"
                "说明本卷计算要求以基础运算为主，主要看基本规则掌握和计算准确率。",
            ),
            (
                4.0,
                "计算维度，综合得分 4.0 分，"
                "说明本卷计算难度整体偏常规，重点考查校内计算的熟练度和稳定性。",
            ),
            (
                6.0,
                "计算维度，综合得分 6.0 分，"
                "说明本卷有一定计算难度，除准确率外，也考查多步运算和常见转化。",
            ),
            (
                8.6,
                "计算维度，综合得分 8.6 分，"
                "说明本卷计算难度较高，计算题和应用题中的核心计算都会拉开学生差距。",
            ),
            (
                9.5,
                "计算维度，综合得分 9.5 分，"
                "说明本卷计算要求很高，包含较强的多步、结构化或拓展计算，对综合计算能力要求突出。",
            ),
        ]

        for score, expected in cases:
            overview = aggregator._build_dim1_score_overview(score)

            assert overview == expected
            assert "计入数学运算评分" not in overview
            assert "纯计算题" not in overview
            assert "权重" not in overview

    def test_dim2_representative_questions_use_specific_counted_wording(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=8.0,
                dim_scores={"dim2": 8.0},
                applicable_dims=["dim2"],
                question_summary="图形重组",
                dim_reasons={
                    "dim2": "L4 结构变换想象：需要把格点图形拆补成基本图形，再利用面积关系计算。"
                },
                dim_confidences={"dim2": 0.9},
                dim_details={
                    "dim2": {
                        "dim2_level": "L4",
                        "display_geometry_knowledge_range_label": "高思导引四年级",
                        "display_geometry_knowledge_points": ["格点与割补"],
                        "geometry_model_types": ["grid_cut_fill"],
                        "evidence_summary": "需要把格点图形拆补成基本图形，再利用面积关系计算。",
                    }
                },
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
                dim_details={
                    "dim2": {
                        "dim2_level": "L3",
                        "display_geometry_knowledge_range_label": "校内六年级",
                        "display_geometry_knowledge_points": ["辅助线与面积关系"],
                    }
                },
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim2")

        assert result.counted_questions[0]["full_reason"] == (
            "较难（8.0）：主要考查高思导引四年级的格点与割补；"
            "本题难点在于要把格点图形拆补成基本图形，再利用面积关系计算。"
        )
        assert result.counted_questions[1]["full_reason"] == (
            "中等（6.0）：主要考查校内六年级的辅助线与面积关系；"
            "本题难点在于要识别两条图形关系。"
        )
        forbidden_terms = [
            "空间想象要求较高",
            "图形结构偏复杂",
            "适合观察几何能力",
            "常见失分点是读图",
            "空间负担为",
            "knowledge_range_level",
            "dim2_level",
        ]
        for counted_question in result.counted_questions:
            for term in forbidden_terms:
                assert term not in counted_question["full_reason"]

    def test_dim3_score_overview_explains_scene_comprehension_bands(self, aggregator):
        cases = [
            (
                2.0,
                "场景理解复杂度维度，综合得分 2.0 分，"
                "说明这张试卷在学生读题和理解题意上的要求比较基础，大多数题目读完后能较快明白题目在说什么。",
            ),
            (
                4.0,
                "场景理解复杂度维度，综合得分 4.0 分，"
                "说明这张试卷在学生读题和理解题意上有常规要求，部分题目需要分清对象、顺序或图文对应关系。",
            ),
            (
                6.0,
                "场景理解复杂度维度，综合得分 6.0 分，"
                "说明这张试卷在学生读题理解题意上设置了一定难度，部分题目需要先读懂关键问法、比较标准或简单规则。",
            ),
            (
                8.6,
                "场景理解复杂度维度，综合得分 8.6 分，"
                "说明这张试卷在学生读题理解题意上设置了明显难度，部分题目的场景相对复杂，学生需要先理清对象、阶段、规则或图文关系。",
            ),
            (
                9.5,
                "场景理解复杂度维度，综合得分 9.5 分，"
                "说明这张试卷在学生读题理解题意上设置了较高难度，不少题目需要完整读懂多条规则、多阶段过程或复杂图文关系。",
            ),
        ]

        for score, expected in cases:
            overview = aggregator._build_dim3_score_overview(score)

            assert overview == expected
            assert "共 " not in overview
            assert "题级平均" not in overview
            assert "按题目等级加权" not in overview
            assert "高等级题" not in overview

    def test_dim3_representative_questions_use_scene_comprehension_wording(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=8.0,
                dim_scores={"dim3": 8.0},
                applicable_dims=["dim3"],
                question_summary="百分数变化应用",
                dim_reasons={"dim3": "旧版分析不应直接展示。"},
                dim_confidences={"dim3": 0.9},
                dim_details={
                    "dim3": {
                        "dim3_level": "L4",
                        "comparison_basis": "implicit",
                        "scenario_rule_types": ["comparison_basis"],
                        "evidence_summary": "需要分清变化前后的比较基准，避免把不同阶段的口径直接合并。",
                    }
                },
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=6.0,
                dim_scores={"dim3": 6.0},
                applicable_dims=["dim3"],
                question_summary="表格信息比较",
                dim_reasons={"dim3": "L3 比较口径理解：需要先读懂表格和单位量比较口径。"},
                dim_confidences={"dim3": 0.8},
                dim_details={
                    "dim3": {
                        "dim3_level": "L3",
                        "source_form": "table_chart",
                        "diagram_correspondence": "required",
                        "comparison_basis": "implicit",
                        "scenario_rule_types": ["comparison_basis", "diagram_mapping"],
                        "evidence_summary": "需要先读懂表格和单位量比较口径。",
                    }
                },
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim3")

        assert result.evidence == (
            "共 2 道题纳入场景理解复杂度评分；"
            "按题目等级加权，高等级题权重更高；"
            "权重得分 7.1 分，判定为 拔高。"
        )
        assert result.counted_questions[0]["difficulty_label"] == "较难（8.0）"
        assert result.counted_questions[0]["full_reason"] == (
            "较难（8.0）：主要考查多个场景关系整合；"
            "本题难点在于要分清变化前后的比较基准，避免把不同阶段的口径直接合并。"
        )
        assert result.counted_questions[1]["full_reason"] == (
            "中等（6.0）：主要考查关键问法理解；"
            "本题难点在于要先读懂表格和单位量比较口径。"
        )
        forbidden_terms = [
            "信息提取与转化负担较高",
            "信息处理能力要求较高",
            "题干较长",
            "信息量较大",
            "适合观察信息提取能力",
            "需要较强的信息整合能力",
            "dim3_level",
            "information_role",
            "representation_conversion",
            "quantity_relation_structure",
            "evidence_summary",
        ]
        for counted_question in result.counted_questions:
            for term in forbidden_terms:
                assert term not in counted_question["full_reason"]

    def test_dim6_score_overview_explains_logic_chain_evaluation_point(self, aggregator):
        cases = [
            (
                2.0,
                "逻辑推理综合得分 2.0 分，这张试卷多数题解题链条很短，通常读懂条件后一步判断即可。",
            ),
            (
                4.0,
                "逻辑推理综合得分 4.0 分，这张试卷整体解题链条偏短，少量题需要 1-2 步衔接。",
            ),
            (
                6.0,
                "逻辑推理综合得分 6.0 分，这张试卷部分题解题链条有一定长度，通常要把前后条件接起来推进 2-4 步。",
            ),
            (
                8.6,
                "逻辑推理综合得分 8.6 分，这张试卷不少题解题链条较长，通常要连续推进 3-4 步，并穿插分类、倒推或回查。",
            ),
            (
                9.5,
                "逻辑推理综合得分 9.5 分，这张试卷有少量解题链条很长的压轴题，通常要连续推进 5 步以上，并检查多个条件。",
            ),
        ]

        for score, expected in cases:
            overview = aggregator._build_dim6_score_overview(score)

            assert overview == expected
            assert "共 " not in overview
            assert "题级平均" not in overview
            assert "解题链条" in overview

    def test_dim6_representative_questions_explain_teacher_readable_logic_task(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q0",
                question_no="0",
                score=9.5,
                dim_scores={"dim6": 9.5},
                applicable_dims=["dim6"],
                question_summary="多对象分配倒推题",
                dim_reasons={"dim6": "旧版分析不应直接展示。"},
                dim_confidences={"dim6": 0.95},
                dim_details={
                    "dim6": {
                        "dim6_level": "L5",
                        "chain_span": "5+",
                        "logic_structure_types": ["global_constraint_system", "reverse_process_chain"],
                        "backtrack_depth": "3+",
                        "consistency_constraint_count": "4+",
                        "phase_count_band": "5+",
                        "evidence_summary": "多对象分配题需要嵌套约束、三层以上倒推和全局一致性收束。",
                    }
                },
            ),
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=8.0,
                dim_scores={"dim6": 8.0},
                applicable_dims=["dim6"],
                question_summary="分类判断题",
                dim_reasons={"dim6": "旧版分析不应直接展示。"},
                dim_confidences={"dim6": 0.9},
                dim_details={
                    "dim6": {
                        "dim6_level": "L4",
                        "logic_structure_types": ["bounded_case_enumeration"],
                        "case_count_band": "3-5",
                        "evidence_summary": "需要分类、回查并维持全局一致。",
                    }
                },
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=6.0,
                dim_scores={"dim6": 6.0},
                applicable_dims=["dim6"],
                question_summary="连续条件题",
                dim_reasons={"dim6": "旧版分析不应直接展示。"},
                dim_confidences={"dim6": 0.8},
                dim_details={
                    "dim6": {
                        "dim6_level": "L3",
                        "chain_span": "3-4",
                        "logic_structure_types": ["work_rate_chain"],
                        "evidence_summary": "需要把前一步结果接到下一步条件中。",
                    }
                },
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim6")

        assert result.evidence == (
            "逻辑推理综合得分 7.8 分，这张试卷部分题解题链条有一定长度，通常要把前后条件接起来推进 2-4 步。"
        )
        assert result.counted_questions[0]["difficulty_label"] == "困难（9.5）"
        assert result.counted_questions[0]["full_reason"] == (
            "困难（9.5）：这题的解题链条很长，通常需要连续推进 5 步以上，并同时检查多个条件；"
            "学生需要从结果往前还原每一步，再把还原出的状态代回多个条件检查。"
        )
        assert result.counted_questions[1]["full_reason"] == (
            "较难（8.0）：这题的解题链条较长，通常需要多步推进，并伴随分类、倒推、回查或多条件检查；"
            "学生需要把可能情况分完整，逐一代回条件检查，避免漏掉或重复。"
        )
        assert result.counted_questions[2]["full_reason"] == (
            "中等（6.0）：这题的解题链条较长，大约需要连续推进 3-4 步；"
            "学生需要把前一步得到的结果接到下一步条件里，连续推出中间结论。"
        )
        forbidden_terms = [
            "逻辑负担",
            "约束一致",
            "高阶收束",
            "依据是",
            "dim6_level",
            "reasoning_role",
            "chain_span",
            "constraint_coupling",
        ]
        for counted_question in result.counted_questions:
            assert "这题的解题链条" in counted_question["full_reason"]
            assert "学生需要" in counted_question["full_reason"]
            for term in forbidden_terms:
                assert term not in counted_question["full_reason"]
            assert "该题难度较高" not in counted_question["full_reason"]
            assert "综合判为困难" not in counted_question["full_reason"]

    def test_dim6_second_review_results_only_count_stable_applicable_questions(self, aggregator):
        questions = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=5.0,
                dim_scores={"dim6": 6.0},
                applicable_dims=["dim6"],
                dim_reasons={"dim6": "second review applicable"},
                dim_statuses={"dim6": "applicable"},
                dim_details={
                    "dim6": {
                        "dim6_level": "L3",
                        "level_source": "second_review",
                        "evidence_summary": "需要枚举24的因数分解方案，逐一计算周长，比较最小值",
                        "second_review_requested": True,
                        "second_review_status": "applicable",
                    }
                },
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=5.0,
                dim_scores={"dim6": 6.0},
                applicable_dims=["dim6"],
                dim_reasons={"dim6": "initial applicable"},
                dim_statuses={"dim6": "applicable"},
                dim_details={"dim6": {"dim6_level": "L3"}},
            ),
            QuestionDimensionScore(
                question_id="q3",
                question_no="3",
                score=5.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim6": "second review not applicable"},
                dim_statuses={"dim6": "not_applicable"},
                dim_details={
                    "dim6": {
                        "second_review_requested": True,
                        "second_review_status": "not_applicable",
                    }
                },
            ),
            QuestionDimensionScore(
                question_id="q4",
                question_no="4",
                score=5.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim6": "second review unresolved"},
                dim_statuses={"dim6": "review_failed_excluded"},
                dim_details={
                    "dim6": {
                        "second_review_requested": True,
                        "second_review_status": "review_failed_excluded",
                    }
                },
            ),
        ]

        result = aggregator.aggregate(questions, "dim6")

        assert result.question_count == 2
        assert result.paper_score == pytest.approx(6.0)
        assert [item["question_no"] for item in result.counted_questions] == ["1", "2"]
        assert "枚举24" in result.counted_questions[0]["full_reason"]
        assert result.score_breakdown["second_review_requested_count"] == 3
        assert result.score_breakdown["second_review_applicable_count"] == 1
        assert result.score_breakdown["second_review_not_applicable_count"] == 1
        assert result.score_breakdown["second_review_failed_count"] == 1
        assert result.score_breakdown["review_failed_excluded_count"] == 1

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

        assert result.paper_score == pytest.approx(37 / 11)
        assert result.level == 2
        assert result.score_breakdown["aggregation_rule"] == "知识范围等级加权均分"
        assert result.score_breakdown["question_score_average"] == pytest.approx(3.2)
        assert result.score_breakdown["question_score_sum"] == pytest.approx(32.0)
        assert result.score_breakdown["weighted_question_average"] == pytest.approx(3.3636)
        assert result.score_breakdown["level_weights"] == {"L1": 1, "L2": 1, "L3": 2, "L4": 4, "L5": 6}
        assert "纳入知识范围评分" in result.evidence
        assert "权重得分 3.4 分" in result.evidence

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

        assert result.paper_score == pytest.approx(4.6)
        assert result.level == 3
        assert result.score_breakdown["raw_question_average"] == pytest.approx(3.8)

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

        assert result.paper_score == pytest.approx(5.6)
        assert result.level == 3
        assert result.score_breakdown["raw_question_average"] == pytest.approx(4.4)

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

        assert result.paper_score == pytest.approx(162 / 26)
        assert result.level == 4
        assert result.score_breakdown["raw_question_average"] == pytest.approx(5.2)

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

        assert result.paper_score == pytest.approx(7.25)
        assert result.level == 4
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

        assert result.paper_score == pytest.approx(139 / 21)
        assert result.score_breakdown["final_score"] == pytest.approx(139 / 21)
        assert "超越篇" not in result.evidence

    def test_dim5_wmo_26_updated_level_mix_recalculates_to_7_5(self, aggregator):
        wmo_questions = [
            ("2", 6.0, "L3", "倍半递推与倒推还原", "pattern_sequence"),
            ("3", 8.0, "L4", "分数裂项求和", "number_operation"),
            ("5", 8.0, "L4", "三视图与立体图形", "geometry_spatial"),
            ("6", 6.0, "L3", "数论约束", "number_theory"),
            ("10", 6.0, "L3", "数量关系应用", "quantity_application"),
            ("11", 6.0, "L3", "数字性质与9的倍数判定", "number_theory"),
            ("12", 8.0, "L4", "抽屉原理与组合枚举", "counting_combinatorics"),
            ("13", 9.5, "L5", "博弈策略与必胜策略", "logic_strategy_construction"),
            ("14", 8.0, "L4", "组合计数", "counting_combinatorics"),
            ("15", 6.0, "L3", "数量关系应用", "quantity_application"),
            ("17", 6.0, "L3", "比例整体关系", "quantity_application"),
            ("18", 4.0, "L2", "校内数与运算", "number_operation"),
            ("19", 8.0, "L4", "三视图空间极值构造", "geometry_spatial"),
        ]
        questions = [
            QuestionDimensionScore(
                question_id=f"wmo-{question_no}",
                question_no=question_no,
                score=5.0,
                dim_scores={"dim5": score},
                applicable_dims=["dim5"],
                question_summary=f"第{question_no}题",
                dim_reasons={"dim5": f"{level} {point}"},
                dim_confidences={"dim5": 0.9},
                dim_statuses={"dim5": "applicable"},
                dim_details={
                    "dim5": {
                        "knowledge_source_bucket": "school"
                        if level == "L2"
                        else ("beyond" if level == "L5" else "high_gaosi"),
                        "knowledge_level": level,
                        "canonical_knowledge_point": point,
                        "canonical_knowledge_domain": domain,
                        "grounded_canonical_knowledge_point": point,
                        "grounded_knowledge_domain": domain,
                        "grounded_confidence": 0.9,
                        "grounded_risk_flags": [],
                    }
                },
            )
            for question_no, score, level, point, domain in wmo_questions
        ]

        result = aggregator.aggregate(questions, "dim5")

        assert result.question_count == 13
        assert result.paper_score == pytest.approx(293 / 39)
        assert round(result.paper_score, 1) == 7.5
        assert result.score_breakdown["weighted_score_sum"] == pytest.approx(293)
        assert result.score_breakdown["total_weight"] == pytest.approx(39)

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
        assert "纳入知识范围评分" in result.evidence
        assert any("未计入知识范围评分" in item for item in result.warning_messages)

    def test_dim5_unknown_bucket_with_valid_score_still_enters_average(self, aggregator):
        unknown = self._dim5_question(10, "unknown")
        unknown.dim_scores["dim5"] = 7.0
        questions = [
            self._dim5_question(index, "school")
            for index in range(1, 10)
        ] + [unknown]

        result = aggregator.aggregate(questions, "dim5")

        assert result.question_count == 10
        assert result.paper_score == pytest.approx(55 / 13)
        assert result.score_breakdown["bucket_counts"]["unknown"] == 1
        assert result.score_breakdown["unknown_scored_count"] == 1

    def test_dim5_breakdown_tracks_hit_sources_and_retry_failures(self, aggregator):
        question_bank = self._dim5_question(1, "high_gaosi")
        question_bank.dim_details["dim5"]["band_source"] = "question_bank"
        question_bank.dim_details["dim5"]["gaosi_classification_source"] = "question_bank"

        topic_structure = self._dim5_question(2, "high_gaosi")
        topic_structure.dim_details["dim5"]["band_source"] = "topic_structure_match"

        llm_fallback = self._dim5_question(3, "beyond")
        llm_fallback.dim_details["dim5"]["band_source"] = "llm_dim5_retry"

        retry_failed = QuestionDimensionScore(
            question_id="q4",
            question_no="4",
            score=5.0,
            dim_scores={},
            applicable_dims=[],
            question_summary="dim5 兜底失败题",
            dim_reasons={"dim5": "dim5 retry failed"},
            dim_statuses={"dim5": "not_applicable"},
            dim_details={
                "dim5": {
                    "band_source": "llm_dim5_retry_failed",
                    "dim5_excluded_reason": "retry_failed",
                }
            },
        )

        result = aggregator.aggregate(
            [question_bank, topic_structure, llm_fallback, retry_failed],
            "dim5",
        )

        assert result.question_count == 3
        assert result.score_breakdown["source_counts"] == {
            "question_bank": 1,
            "topic_structure_match": 1,
            "llm_dim5_retry": 1,
        }
        assert result.score_breakdown["question_bank_count"] == 1
        assert result.score_breakdown["topic_structure_upshift_count"] == 1
        assert result.score_breakdown["llm_fallback_count"] == 1
        assert result.score_breakdown["fallback_failed_count"] == 1

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
        assert result.score_breakdown["beyond_question_count"] == 3

        high.dim_scores["dim5"] = 9.0
        beyond.dim_scores["dim5"] = 9.0

        result = aggregator.aggregate([high, beyond], "dim5")

        assert result.counted_questions[0]["question_no"] == "2"

    def test_dim5_counted_questions_expose_structured_display_fields(self, aggregator):
        question = self._dim5_question(1, "high_gaosi")
        question.dim_scores["dim5"] = 8.0
        question.dim_details["dim5"].update(
            {
                "knowledge_level": "L4",
                "canonical_knowledge_point": "面积比模型",
                "gaosi_grade": "6",
                "level_evidence": "需要识别等高、共边或割补关系，并把图形面积关系转化为比例关系",
            }
        )

        result = aggregator.aggregate([question], "dim5")
        counted_question = result.counted_questions[0]

        assert counted_question["difficulty_label"] == "较难（8.0）"
        assert counted_question["knowledge_source_text"] == "六年级奥数"
        assert counted_question["knowledge_point_text"] == "面积比模型"
        assert counted_question["score_reason"] == (
            "难点在于要识别等高、共边或割补关系，并把图形面积关系转化为比例关系。"
        )
        assert counted_question["reason"] == (
            "较难（8.0）：本题属于六年级奥数的面积比模型；"
            "难点在于要识别等高、共边或割补关系，并把图形面积关系转化为比例关系。"
        )
        assert "因此计为" not in counted_question["score_reason"]

    def test_dim5_counted_question_prefers_grounded_point_and_source(self, aggregator):
        question = self._dim5_question(1, "high_gaosi")
        question.dim_scores["dim5"] = 4.0
        question.dim_details["dim5"].update(
            {
                "knowledge_level": "L2",
                "canonical_knowledge_point": "因数倍数与质合数",
                "canonical_knowledge_domain": "number_theory",
                "gaosi_grade": "3",
                "grounded_canonical_knowledge_point": "乘法分配律与简便计算",
                "grounded_knowledge_domain": "number_operation",
                "grounded_knowledge_source_text": "校内数与运算",
                "grounded_confidence": 0.91,
                "grounded_evidence": "题面是纯计算，出现乘法与加减组合，并存在共同因数或小数缩放。",
                "grounded_risk_flags": [],
            }
        )

        result = aggregator.aggregate([question], "dim5")
        counted_question = result.counted_questions[0]

        assert counted_question["knowledge_point_text"] == "乘法分配律与简便计算"
        assert counted_question["knowledge_source_text"] == "校内数与运算"
        assert counted_question["knowledge_source_text"] != "三年级奥数"

    def test_dim5_representative_questions_filter_weak_grounded_candidates(self, aggregator):
        weak = self._dim5_question(1, "beyond")
        weak.dim_scores["dim5"] = 10.0
        weak.dim_details["dim5"].update(
            {
                "knowledge_level": "L5",
                "canonical_knowledge_point": "高阶数论综合",
                "grounded_canonical_knowledge_point": "高阶数论综合",
                "grounded_knowledge_domain": "number_theory",
                "grounded_confidence": 0.95,
                "grounded_risk_flags": ["weak_evidence", "conflicting_question_structure"],
            }
        )
        clean = self._dim5_question(2, "high_gaosi")
        clean.dim_scores["dim5"] = 8.0
        clean.dim_details["dim5"].update(
            {
                "knowledge_level": "L4",
                "canonical_knowledge_point": "工程效率问题",
                "grounded_canonical_knowledge_point": "工程效率问题",
                "grounded_knowledge_domain": "quantity_application",
                "grounded_confidence": 0.86,
                "grounded_risk_flags": [],
            }
        )

        result = aggregator.aggregate([weak, clean], "dim5")

        assert [item["question_no"] for item in result.counted_questions] == ["2"]

    def test_dim5_counted_question_source_uses_bucket_grade_band_when_explicit_grade_missing(self, aggregator):
        question = self._dim5_question(1, "high_gaosi")
        question.dim_scores["dim5"] = 8.0
        question.dim_details["dim5"].update(
            {
                "knowledge_level": "L4",
                "canonical_knowledge_point": "面积比模型",
                "band": "五六年级高思导引拓展篇",
                "canonical_alias_hits": ["面积比", "割补"],
            }
        )

        result = aggregator.aggregate([question], "dim5")
        counted_question = result.counted_questions[0]

        assert counted_question["knowledge_source_text"] == "五六年级奥数"
        assert "奥数" in counted_question["reason"]

    def test_dim5_counted_question_normalizes_unknown_olympiad_display_and_uses_specific_reason(self, aggregator):
        question = self._dim5_question(1, "beyond")
        question.dim_scores["dim5"] = 9.5
        question.dim_details["dim5"].update(
            {
                "knowledge_level": "L5",
                "knowledge_point_name": "博弈策略与必胜策略",
                "canonical_knowledge_point": "博弈策略与必胜策略",
                "canonical_knowledge_domain": "logic_strategy_construction",
                "knowledge_track": "olympiad",
                "knowledge_track_label": "奥数",
                "knowledge_grade": "unknown",
                "knowledge_grade_label": "年级未确认",
                "knowledge_display_name": "奥数年级未确认：博弈策略与必胜策略",
                "dim5_structure_facts": [
                    {"fact_key": "game_rule", "evidence": "轮流移动棋子"},
                    {"fact_key": "winning_strategy", "evidence": "制胜策略"},
                ],
            }
        )

        result = aggregator.aggregate([question], "dim5")
        counted_question = result.counted_questions[0]

        assert counted_question["knowledge_display_name"] == "奥数知识：博弈策略与必胜策略"
        assert "年级未确认" not in counted_question["reason"]
        assert "最终胜负" in counted_question["score_reason"]
        assert "必胜" in counted_question["score_reason"]

    def test_dim5_counted_question_replaces_audit_evidence_with_counting_difficulty(self, aggregator):
        question = self._dim5_question(1, "high_gaosi")
        question.dim_scores["dim5"] = 8.0
        question.dim_details["dim5"].update(
            {
                "knowledge_level": "L4",
                "canonical_knowledge_point": "组合计数",
                "canonical_knowledge_domain": "counting_combinatorics",
                "evidence_summary": "命中高思导引计数或容斥入门专题",
            }
        )

        result = aggregator.aggregate([question], "dim5")
        score_reason = result.counted_questions[0]["score_reason"]

        assert "分类计数" in score_reason
        assert "重复或遗漏" in score_reason
        assert "容斥" in score_reason
        for forbidden in ("命中", "高思导引", "专题", "因此计为", "计为"):
            assert forbidden not in score_reason

    def test_dim5_counted_question_uses_number_theory_difficulty_template(self, aggregator):
        question = self._dim5_question(1, "beyond")
        question.dim_scores["dim5"] = 9.5
        question.dim_details["dim5"].update(
            {
                "knowledge_level": "L5",
                "canonical_knowledge_point": "高阶数论综合",
                "canonical_knowledge_domain": "number_theory",
            }
        )

        result = aggregator.aggregate([question], "dim5")
        score_reason = result.counted_questions[0]["score_reason"]

        assert "整除" in score_reason
        assert "余数" in score_reason
        assert "质因数" in score_reason
        assert "直接代公式" in score_reason
        assert "综合运用" not in score_reason
        assert "高阶知识" not in score_reason

    def test_dim5_counted_question_uses_school_formula_difficulty_template(self, aggregator):
        question = self._dim5_question(1, "school")
        question.dim_scores["dim5"] = 4.0
        question.dim_details["dim5"].update(
            {
                "knowledge_level": "L2",
                "canonical_knowledge_point": "高年级校内图形公式",
                "canonical_knowledge_domain": "geometry_spatial",
                "canonical_direct_formula_guard": True,
            }
        )

        result = aggregator.aggregate([question], "dim5")
        score_reason = result.counted_questions[0]["score_reason"]

        assert "半径" in score_reason
        assert "高" in score_reason
        assert "图形公式" in score_reason
        assert score_reason.startswith("难点在于")

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

    def test_dim4_aggregation_includes_stable_l1_l2_and_exposes_breakdown(self, aggregator):
        questions = [
            self._dim4_question(1, "L3", 6.0, reason="L3：一次变式识别。"),
            self._dim4_question(2, "L4", 8.0, reason="L4：构造中间量并约束回查。"),
            self._dim4_question(3, "L5", 9.5, reason="L5：需要全局最优性证明。"),
            self._dim4_question(
                4,
                "L1",
                2.0,
                reason="L1：基础模板题。",
            ),
            self._dim4_question(
                5,
                "L2",
                4.0,
                reason="L2：轻度变式题。",
            ),
            self._dim4_question(
                6,
                "L4",
                0.0,
                status="review",
                reason="dim4 建模解题事实缺失，当前题目自动未覆盖。",
            ),
        ]

        result = aggregator.aggregate(questions, "dim4")

        assert result.question_count == 5
        assert result.review_question_count == 1
        expected_weighted = (
            2.0 * 1
            + 4.0 * 1
            + 6.0 * 1
            + 8.0 * 1.25
            + 9.5 * 1.6
        ) / (1 + 1 + 1 + 1.25 + 1.6)
        assert result.paper_score == pytest.approx(expected_weighted)
        assert result.score_breakdown["level_counts"] == {
            "L1": 1,
            "L2": 1,
            "L3": 1,
            "L4": 1,
            "L5": 1,
        }
        assert result.score_breakdown["not_applicable_count"] == 0
        assert result.score_breakdown["review_count"] == 1
        assert result.score_breakdown["l1_excluded_count"] == 0
        assert result.score_breakdown["valid_score_question_count"] == 5
        assert result.score_breakdown["fallback_count"] == 0
        assert result.score_breakdown["auto_ignored_count"] == 1
        assert result.score_breakdown["high_level_question_count"] == 2
        assert result.score_breakdown["level_weights"] == {
            "L1": 1.0,
            "L2": 1.0,
            "L3": 1.0,
            "L4": 1.25,
            "L5": 1.6,
        }
        assert result.score_breakdown["raw_question_average"] == pytest.approx(
            (2.0 + 4.0 + 6.0 + 8.0 + 9.5) / 5,
            abs=0.0001,
        )
        assert result.score_breakdown["weighted_question_average"] == pytest.approx(
            expected_weighted,
            abs=0.0001,
        )
        assert "综合得分为" in result.evidence
        assert "在解题思路上有一定难度" in result.evidence
        assert "建模解题复杂度评分" not in result.evidence
        assert "按题目等级加权" not in result.evidence
        assert "权重得分" not in result.evidence
        assert "自动未覆盖" not in result.evidence
        assert "兜底" not in result.evidence
        assert "人工复核" not in result.evidence

    def test_dim4_aggregation_uses_all_twenty_stable_topic_levels(self, aggregator):
        level_scores = {"L1": 2.0, "L2": 4.0, "L3": 6.0, "L4": 8.0, "L5": 9.5}
        level_weights = {"L1": 1.0, "L2": 1.0, "L3": 1.0, "L4": 1.25, "L5": 1.6}
        levels = ["L1"] * 4 + ["L2"] * 5 + ["L3"] * 6 + ["L4"] * 4 + ["L5"]
        questions = [
            self._dim4_question(index, level, level_scores[level])
            for index, level in enumerate(levels, start=1)
        ]

        result = aggregator.aggregate(questions, "dim4")

        assert result.question_count == 20
        assert result.score_breakdown["valid_score_question_count"] == 20
        assert result.score_breakdown["level_counts"] == {
            "L1": 4,
            "L2": 5,
            "L3": 6,
            "L4": 4,
            "L5": 1,
        }
        expected_weighted = sum(level_scores[level] * level_weights[level] for level in levels) / sum(
            level_weights[level] for level in levels
        )
        assert result.paper_score == pytest.approx(expected_weighted)
        assert "综合得分为" in result.evidence

    def test_dim4_review_and_missing_score_are_auto_ignored(self, aggregator):
        questions = [
            self._dim4_question(1, "L1", 2.0),
            self._dim4_question(2, "L4", 8.0),
            self._dim4_question(
                3,
                "L3",
                0.0,
                status="review",
                reason="dim4 建模解题事实缺失，当前题目自动未覆盖。",
            ),
            self._dim4_question(
                4,
                "L2",
                0.0,
                status="not_applicable",
                reason="缺少合法题级分。",
            ),
        ]

        result = aggregator.aggregate(questions, "dim4")

        assert result.question_count == 2
        assert result.paper_score == pytest.approx((2.0 * 1 + 8.0 * 1.25) / (1 + 1.25))
        assert result.score_breakdown["raw_question_average"] == pytest.approx(5.0)
        assert result.review_question_count == 1
        assert result.score_breakdown["fallback_count"] == 0
        assert result.score_breakdown["unscored_question_count"] == 2
        assert result.score_breakdown["auto_ignored_count"] == 2
        assert all(
            "人工复核" not in item
            and "未计入" not in item
            and "未纳入评分" not in item
            and "兜底" not in item
            and "自动未覆盖" not in item
            for item in result.warning_messages
        )

    def test_dim4_second_review_breakdown_counts_and_excludes_unresolved(self, aggregator):
        questions = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=5.0,
                dim_scores={"dim4": 9.5},
                applicable_dims=["dim4"],
                dim_reasons={"dim4": "二次复评确认需要自建整体解题结构。"},
                dim_statuses={"dim4": "applicable"},
                dim_details={
                    "dim4": {
                        "dim4_level": "L5",
                        "level_source": "second_review",
                        "second_review_requested": True,
                        "second_review_status": "applicable",
                    }
                },
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=5.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim4": "复评确认只是直接代公式。"},
                dim_statuses={"dim4": "not_applicable"},
                dim_details={
                    "dim4": {
                        "second_review_requested": True,
                        "second_review_status": "not_applicable",
                    }
                },
            ),
            QuestionDimensionScore(
                question_id="q3",
                question_no="3",
                score=5.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim4": "图文信息不足，未计入该维度。"},
                dim_statuses={"dim4": "review_failed_excluded"},
                dim_details={
                    "dim4": {
                        "second_review_requested": True,
                        "second_review_status": "review_failed_excluded",
                    }
                },
            ),
        ]

        result = aggregator.aggregate(questions, "dim4")

        assert result.question_count == 1
        assert result.score_breakdown["second_review_requested_count"] == 3
        assert result.score_breakdown["second_review_applicable_count"] == 1
        assert result.score_breakdown["second_review_not_applicable_count"] == 1
        assert result.score_breakdown["second_review_failed_count"] == 1
        assert result.score_breakdown["review_failed_excluded_count"] == 1
        assert result.score_breakdown["source_counts"] == {"second_review": 1}
        assert any("判定不稳定" in item for item in result.warning_messages)

    def test_dim4_weighted_score_matches_wmo_full_twenty_distribution(self, aggregator):
        level_scores = {"L1": 2.0, "L2": 4.0, "L3": 6.0, "L4": 8.0, "L5": 9.5}
        levels = ["L1"] + ["L2"] * 3 + ["L3"] * 4 + ["L4"] * 10 + ["L5"] * 2
        questions = [
            self._dim4_question(index, level, level_scores[level])
            for index, level in enumerate(levels, start=1)
        ]

        result = aggregator.aggregate(questions, "dim4")

        assert result.question_count == 20
        assert result.score_breakdown["level_counts"] == {
            "L1": 1,
            "L2": 3,
            "L3": 4,
            "L4": 10,
            "L5": 2,
        }
        level_weights = {"L1": 1.0, "L2": 1.0, "L3": 1.0, "L4": 1.25, "L5": 1.6}
        expected_weighted = sum(level_scores[level] * level_weights[level] for level in levels) / sum(
            level_weights[level] for level in levels
        )
        assert result.paper_score == pytest.approx(expected_weighted)

    def test_dim4_weighted_score_matches_guangda_full_distribution(self, aggregator):
        level_scores = {"L1": 2.0, "L2": 4.0, "L3": 6.0, "L4": 8.0, "L5": 9.5}
        levels = ["L1"] * 7 + ["L2"] * 5 + ["L3"] * 5 + ["L4"] * 6
        questions = [
            self._dim4_question(index, level, level_scores[level])
            for index, level in enumerate(levels, start=1)
        ]

        result = aggregator.aggregate(questions, "dim4")

        assert result.question_count == 23
        assert result.score_breakdown["level_counts"] == {
            "L1": 7,
            "L2": 5,
            "L3": 5,
            "L4": 6,
            "L5": 0,
        }
        level_weights = {"L1": 1.0, "L2": 1.0, "L3": 1.0, "L4": 1.25, "L5": 1.6}
        expected_weighted = sum(level_scores[level] * level_weights[level] for level in levels) / sum(
            level_weights[level] for level in levels
        )
        assert result.paper_score == pytest.approx(expected_weighted)

    def test_dim4_weighted_score_matches_wmo_grade6_calibration_distribution(self, aggregator):
        level_scores = {"L3": 6.0, "L4": 8.0, "L5": 9.5}
        level_weights = {"L1": 1.0, "L2": 1.0, "L3": 1.0, "L4": 1.25, "L5": 1.6}
        levels = ["L3"] * 3 + ["L4"] * 8 + ["L5"] * 4
        questions = [
            self._dim4_question(index, level, level_scores[level])
            for index, level in enumerate(levels, start=1)
        ]

        result = aggregator.aggregate(questions, "dim4")

        expected_weighted = sum(level_scores[level] * level_weights[level] for level in levels) / sum(
            level_weights[level] for level in levels
        )
        assert result.question_count == 15
        assert result.score_breakdown["level_counts"] == {
            "L1": 0,
            "L2": 0,
            "L3": 3,
            "L4": 8,
            "L5": 4,
        }
        assert result.score_breakdown["raw_question_average"] == pytest.approx(8.0)
        assert result.paper_score == pytest.approx(expected_weighted)
        assert result.paper_score >= 8.05
        assert round(result.paper_score, 1) == 8.2

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

    def test_dim4_counted_questions_expose_structured_display_fields(self, aggregator):
        question = self._dim4_question(1, "L5", 9.5)
        question.dim_details["dim4"].update(
            {
                "knowledge_point": "数论约束",
                "topic_level": "L5",
                "evidence_summary": "需要把整除、余数和范围条件一起回查，逐步排除不满足条件的数。",
            }
        )

        result = aggregator.aggregate([question], "dim4")
        counted_question = result.counted_questions[0]

        assert counted_question["difficulty_label"] == "困难（9.5）"
        assert counted_question["knowledge_point_text"] == "数论约束"
        assert counted_question["practice_level_text"] == "综合构造建模"
        assert counted_question["score_reason"] == (
            "难点在于要把整除、余数和范围条件一起回查，逐步排除不满足条件的数。"
        )
        assert counted_question["reason"] == (
            "困难（9.5）：本题是数论约束中的综合构造建模；"
            "难点在于要把整除、余数和范围条件一起回查，逐步排除不满足条件的数。"
        )

    def test_dim4_counted_question_filters_audit_evidence_and_uses_template(self, aggregator):
        question = self._dim4_question(1, "L5", 9.5)
        question.dim_details["dim4"].update(
            {
                "knowledge_point": "数论约束",
                "topic_level": "L5",
                "evidence_summary": "高思题目级参考画像已校准到 L5。",
            }
        )

        result = aggregator.aggregate([question], "dim4")
        score_reason = result.counted_questions[0]["score_reason"]

        assert "整除" in score_reason
        assert "余数" in score_reason
        assert "逐步排除" in score_reason
        for forbidden in ("校准", "参考画像", "判为", "计为", "人工复核"):
            assert forbidden not in score_reason

    def test_dim4_counted_question_filters_english_display_evidence(self, aggregator):
        question = self._dim4_question(1, "L4", 8.0)
        question.dim_details["dim4"].update(
            {
                "knowledge_point": "多次反射路径",
                "topic_level": "L4",
                "evidence_summary": (
                    "This problem requires understanding the 90-degree reflection rule, then "
                    "applying coordinate management through multiple reflections."
                ),
            }
        )

        result = aggregator.aggregate([question], "dim4")
        counted_question = result.counted_questions[0]

        assert counted_question["score_reason"] == (
            "难点在于不能直接套模板，需要构造中间量、分类回查或重组关系。"
        )
        assert "This problem" not in counted_question["reason"]
        assert "requires understanding" not in counted_question["full_reason"]

    def test_dim4_counted_question_keeps_chinese_reason_with_short_english_tokens(self, aggregator):
        question = self._dim4_question(1, "L4", 8.0)
        question.dim_details["dim4"].update(
            {
                "knowledge_point": "反射路径",
                "topic_level": "L4",
                "evidence_summary": "需要结合 A/B 点、L4 路径和 90-degree 角度关系回查边界。",
            }
        )

        result = aggregator.aggregate([question], "dim4")
        score_reason = result.counted_questions[0]["score_reason"]

        assert score_reason == "难点在于要结合 A/B 点、L4 路径和 90-degree 角度关系回查边界。"

    def test_dim4_counted_question_uses_geometry_variant_template(self, aggregator):
        question = self._dim4_question(1, "L4", 8.0)
        question.dim_details["dim4"].update(
            {
                "knowledge_point": "图形割补",
                "topic_level": "L4",
                "evidence_summary": "综合判为 L4 多关系建模。",
            }
        )

        result = aggregator.aggregate([question], "dim4")
        counted_question = result.counted_questions[0]

        assert counted_question["difficulty_label"] == "较难（8.0）"
        assert counted_question["practice_level_text"] == "多关系建模"
        assert "辅助关系" in counted_question["score_reason"]
        assert "面积关系" in counted_question["score_reason"]
        assert "判为" not in counted_question["score_reason"]

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

    def test_dim1_second_review_results_only_count_stable_applicable_questions(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=5.0,
                dim_scores={"dim1": 4.0},
                applicable_dims=["dim1"],
                dim_reasons={"dim1": "second review applicable"},
                dim_statuses={"dim1": "applicable"},
                dim_details={
                    "dim1": {
                        "dim1_level": "L2",
                        "calc_bucket": "pure_calculation",
                        "level_source": "second_review",
                        "second_review_requested": True,
                        "second_review_status": "applicable",
                    }
                },
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=5.0,
                dim_scores={"dim1": 8.0},
                applicable_dims=["dim1"],
                dim_reasons={"dim1": "initial applicable"},
                dim_statuses={"dim1": "applicable"},
                dim_details={"dim1": {"dim1_level": "L4", "calc_bucket": "pure_calculation"}},
            ),
            QuestionDimensionScore(
                question_id="q3",
                question_no="3",
                score=5.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim1": "low burden second review"},
                dim_statuses={"dim1": "not_applicable"},
                dim_details={
                    "dim1": {
                        "second_review_requested": True,
                        "second_review_status": "not_applicable",
                    }
                },
            ),
            QuestionDimensionScore(
                question_id="q4",
                question_no="4",
                score=5.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim1": "second review unresolved"},
                dim_statuses={"dim1": "review_failed_excluded"},
                dim_details={
                    "dim1": {
                        "second_review_requested": True,
                        "second_review_status": "review_failed_excluded",
                    }
                },
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim1")

        assert result.question_count == 2
        assert result.paper_score == pytest.approx(6.0)
        assert [item["question_no"] for item in result.counted_questions] == ["2", "1"]
        assert result.score_breakdown["second_review_requested_count"] == 3
        assert result.score_breakdown["second_review_applicable_count"] == 1
        assert result.score_breakdown["second_review_not_applicable_count"] == 1
        assert result.score_breakdown["second_review_failed_count"] == 1
        assert result.score_breakdown["review_failed_excluded_count"] == 1

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
        assert result.evidence.startswith("计算维度，综合得分 6.2 分")
        assert "有一定计算难度" in result.evidence
        assert "纯计算题" not in result.evidence
        assert "应用题中的核心计算" not in result.evidence

    def test_dim1_wmo26_calibrated_distribution_reaches_target_band(self, aggregator):
        question_scores = [
            self._dim1_question(1, 8.0, "pure_calculation"),
            self._dim1_question(3, 8.0, "pure_calculation"),
            self._dim1_question(4, 6.0, "pure_calculation"),
            self._dim1_question(7, 6.0, "pure_calculation"),
            self._dim1_question(15, 6.0, "pure_calculation"),
            self._dim1_question(16, 9.5, "pure_calculation"),
            self._dim1_question(2, 8.0, "embedded_calculation"),
            self._dim1_question(6, 6.0, "embedded_calculation"),
            self._dim1_question(8, 8.0, "embedded_calculation"),
            self._dim1_question(9, 8.0, "embedded_calculation"),
            self._dim1_question(10, 8.0, "embedded_calculation"),
            self._dim1_question(17, 9.5, "embedded_calculation"),
            self._dim1_question(18, 6.0, "embedded_calculation"),
        ]

        result = aggregator.aggregate(question_scores, "dim1")

        assert result.question_count == 13
        assert 7.3 <= result.paper_score <= 7.7
        assert all(question["question_no"] != "5" for question in result.counted_questions)

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
        assert result.evidence.startswith("计算维度，综合得分 5.0 分")
        assert "计算难度整体偏常规" in result.evidence
        assert "应用题中的核心计算" not in result.evidence

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
        assert result.paper_score == pytest.approx((2.0 * 1.0 + 8.0 * 1.25) / (1.0 + 1.25))
        assert result.score_breakdown["raw_question_average"] == pytest.approx(5.0)
        assert result.score_breakdown["level_weights"] == {
            "L1": 1.0,
            "L2": 1.0,
            "L3": 1.0,
            "L4": 1.25,
            "L5": 1.6,
        }

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

    def test_dim3_weighted_score_matches_wmo_grade6_calibration_distribution(self, aggregator):
        score_to_level = {6.0: "L3", 8.0: "L4", 9.5: "L5"}
        scores = [6.0, 6.0] + [8.0] * 8 + [9.5] * 2
        level_weights = {"L1": 1.0, "L2": 1.0, "L3": 1.0, "L4": 1.25, "L5": 1.6}
        question_scores = [
            QuestionDimensionScore(
                question_id=f"q{index}",
                question_no=str(index),
                score=5.0,
                dim_scores={"dim3": score},
                applicable_dims=["dim3"],
                dim_reasons={"dim3": "需要读懂题目场景、规则或比较口径。"},
                dim_confidences={"dim3": 0.9},
                dim_statuses={"dim3": "applicable"},
                dim_details={"dim3": {"dim3_level": score_to_level[score]}},
            )
            for index, score in enumerate(scores, start=1)
        ]

        result = aggregator.aggregate(question_scores, "dim3")

        expected_weighted = sum(score * level_weights[score_to_level[score]] for score in scores) / sum(
            level_weights[score_to_level[score]] for score in scores
        )
        assert result.score_breakdown["level_counts"] == {
            "L1": 0,
            "L2": 0,
            "L3": 2,
            "L4": 8,
            "L5": 2,
        }
        assert result.score_breakdown["raw_question_average"] == pytest.approx(7.9167, abs=0.0001)
        assert result.paper_score == pytest.approx(expected_weighted)
        assert result.paper_score >= 8.05
        assert round(result.paper_score, 1) == 8.1
        assert "按题目等级加权，高等级题权重更高" in result.evidence

    def test_dim3_second_review_breakdown_counts_and_excludes_unresolved(self, aggregator):
        questions = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=5.0,
                dim_scores={"dim3": 8.0},
                applicable_dims=["dim3"],
                dim_reasons={"dim3": "二次复评确认需要读懂反馈规则。"},
                dim_statuses={"dim3": "applicable"},
                dim_details={
                    "dim3": {
                        "dim3_level": "L4",
                        "second_review_requested": True,
                        "second_review_status": "applicable",
                    }
                },
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=5.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim3": "图文信息不足，未计入该维度。"},
                dim_statuses={"dim3": "review_failed_excluded"},
                dim_details={
                    "dim3": {
                        "second_review_requested": True,
                        "second_review_status": "review_failed_excluded",
                    }
                },
            ),
            QuestionDimensionScore(
                question_id="q3",
                question_no="3",
                score=5.0,
                dim_scores={},
                applicable_dims=[],
                dim_reasons={"dim3": "复评确认没有真实读题场景负担。"},
                dim_statuses={"dim3": "not_applicable"},
                dim_details={
                    "dim3": {
                        "second_review_requested": True,
                        "second_review_status": "not_applicable",
                    }
                },
            ),
        ]

        result = aggregator.aggregate(questions, "dim3")

        assert result.question_count == 1
        assert result.score_breakdown["second_review_requested_count"] == 3
        assert result.score_breakdown["second_review_applicable_count"] == 1
        assert result.score_breakdown["second_review_not_applicable_count"] == 1
        assert result.score_breakdown["second_review_failed_count"] == 1
        assert result.score_breakdown["review_failed_excluded_count"] == 1
        assert any("判定不稳定" in item for item in result.warning_messages)

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

    def test_dim2_aggregation_includes_simple_geometry_scores(self, aggregator):
        question_scores = [
            QuestionDimensionScore(
                question_id="q1",
                question_no="1",
                score=2.0,
                dim_scores={"dim2": 2.0},
                applicable_dims=["dim2"],
                question_summary="直接套用长方形面积公式。",
                dim_reasons={"dim2": "L1：直接公式。"},
                dim_statuses={"dim2": "applicable"},
                dim_details={"dim2": {"dim2_level": "L1", "geometry_model_types": ["basic_area_formula"]}},
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=2.0,
                dim_scores={"dim2": 2.0},
                applicable_dims=["dim2"],
                question_summary="直接套用长方体体积公式。",
                dim_reasons={"dim2": "L1：直接公式。"},
                dim_statuses={"dim2": "applicable"},
                dim_details={"dim2": {"dim2_level": "L1", "geometry_model_types": ["solid_formula"]}},
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim2")

        assert result.question_count == 2
        assert result.score_status == "scored"
        assert result.paper_score == pytest.approx(2.0)

    def test_dim2_aggregation_stably_counts_wmo_geometry_fallbacks(self, aggregator):
        scorer = Dim2SpatialScorer()
        question_scores = []

        for question_no, raw_text, _expected_level in WMO_DIM2_GEOMETRY_CASES:
            facts = build_dim2_visual_fallback_facts(
                raw_text,
                {"spatial_role": "none", "applicability_confidence": 0.0},
                parse_audit={"visual_category": "geometry_context"},
                has_image=True,
                used_image=False,
            )
            assert facts is not None, question_no

            applicability = evaluate_dim2_applicability(
                raw_text,
                facts,
                llm_confidence=facts["applicability_confidence"],
                parse_audit={"visual_category": "geometry_context"},
                used_image=False,
            )
            score = scorer.score(facts)

            question_scores.append(
                QuestionDimensionScore(
                    question_id=f"q{question_no}",
                    question_no=question_no,
                    score=5.0,
                    dim_scores={"dim2": score.score},
                    applicable_dims=["dim2"],
                    question_summary=f"WMO geometry question {question_no}",
                    dim_reasons={"dim2": score.evidence},
                    dim_confidences={"dim2": facts["applicability_confidence"]},
                    dim_statuses={"dim2": applicability["status"]},
                    dim_details={"dim2": {**facts, **score.details}},
                )
            )

        result = aggregator.aggregate(question_scores, "dim2")

        assert result.question_count == 4
        assert result.score_status == "scored"
        assert result.review_question_count == 0
        assert result.paper_score == pytest.approx(8.75)

    def test_dim2_wmo31_regression_counts_geometry_and_excludes_non_geometry_diagrams(self, aggregator):
        scorer = Dim2SpatialScorer()
        question_scores = []
        audits = {
            "5": {"visual_category": "diagram", "image_required_hint": True},
            "6": {"visual_category": "diagram", "image_required_hint": True},
            "12": {"visual_category": "geometry", "image_required_hint": True},
            "14": {"visual_category": "geometry", "image_required_hint": True},
            "17": {"visual_category": "none", "image_required_hint": False},
            "20": {"visual_category": "diagram", "image_required_hint": True},
        }

        for question_no, raw_text in WMO31_DIM2_REGRESSION_TEXTS.items():
            feature_seed = {"spatial_role": "none", "applicability_confidence": 0.0}
            facts = build_dim2_text_geometry_fallback_facts(raw_text, feature_seed)
            if not facts:
                facts = build_dim2_visual_fallback_facts(
                    raw_text,
                    feature_seed,
                    parse_audit=audits[question_no],
                    has_image=True,
                    used_image=question_no == "12",
                )
            applicability = evaluate_dim2_applicability(
                raw_text,
                facts or {},
                llm_confidence=(facts or {}).get("applicability_confidence", 0.9),
                parse_audit=audits[question_no],
                used_image=question_no == "12",
                parse_warnings=(
                    ["题目(2)小问文字被截断，raw_text不完整"]
                    if question_no == "17"
                    else ["LLM 超时/异常，已继续处理其他题目。"] if question_no == "14" else []
                ),
            )
            if applicability["status"] != "applicable":
                continue

            score = scorer.score(facts or {})
            assert score.applicable is True, question_no
            question_scores.append(
                QuestionDimensionScore(
                    question_id=f"wmo31-q{question_no}",
                    question_no=question_no,
                    score=5.0,
                    dim_scores={"dim2": score.score},
                    applicable_dims=["dim2"],
                    page_no=1 if int(question_no) <= 12 else 2,
                    question_label_raw=f"{question_no}.",
                    question_summary=raw_text,
                    dim_reasons={"dim2": score.evidence},
                    dim_warnings=(
                        {"dim2": ["多模态分析失败，当前题目按纯文本回退判断。"]}
                        if question_no == "17"
                        else {}
                    ),
                    dim_confidences={"dim2": (facts or {}).get("applicability_confidence", 0.9)},
                    dim_statuses={"dim2": applicability["status"]},
                    dim_details={"dim2": {**(facts or {}), **score.details}},
                )
            )

        result = aggregator.aggregate(question_scores, "dim2")

        assert {item.question_no for item in question_scores} == {"12", "14", "17"}
        assert result.question_count == 3
        assert {item["question_no"] for item in result.counted_questions} == {"12", "14", "17"}
        assert {"5", "6", "20"}.isdisjoint(
            {item["question_no"] for item in result.counted_questions}
        )
        counted_by_no = {str(item["question_no"]): item for item in result.counted_questions}
        assert counted_by_no["12"]["score"] == pytest.approx(6.0)
        assert counted_by_no["12"]["difficulty_label"] == "中等（6.0）"
        assert "旋转图形" in counted_by_no["12"]["full_reason"]
        assert "阴影面积" in counted_by_no["12"]["full_reason"]
        assert "平移和旋转" not in counted_by_no["12"]["full_reason"]
        assert "四年级及以前" not in counted_by_no["12"]["full_reason"]
        assert "圆柱" in counted_by_no["17"]["full_reason"]
        assert "长方体和正方体" not in counted_by_no["17"]["full_reason"]
        assert "校内六年级" in counted_by_no["17"]["full_reason"]

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

    def test_report_difficulty_thresholds_put_scores_above_7_in_competition(self):
        service = ReportService()

        assert service._calculate_difficulty_level(2.0) == 1
        assert service._calculate_difficulty_level(4.0) == 2
        assert service._calculate_difficulty_level(6.0) == 3
        assert service._calculate_difficulty_level(7.0) == 4
        assert service._calculate_difficulty_level(7.1) == 5

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
            "school": 3.5,
            "low_gaosi": 5.5,
            "high_gaosi": 7.5,
            "junior_bridge": 7.5,
            "beyond": 9.0,
        }
        bucket_sequence = [
            "high_gaosi",
            "beyond",
            "beyond",
            "school",
            "high_gaosi",
            "low_gaosi",
            "beyond",
            "high_gaosi",
            "beyond",
            "beyond",
            "beyond",
            "high_gaosi",
            "beyond",
            "beyond",
            "beyond",
            "high_gaosi",
            "beyond",
            "beyond",
            "junior_bridge",
            "beyond",
        ]
        source_by_bucket = {
            "school": "model_only",
            "low_gaosi": "knowledge_anchor",
            "high_gaosi": "knowledge_anchor",
            "junior_bridge": "knowledge_anchor",
            "beyond": "llm_dim5_retry",
        }
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
                        "band_source": source_by_bucket[bucket],
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
                paper_title="第26届WMO地方复赛6年级内容校准样本",
            )
        )

        dim5 = next(detail for detail in report["dimension_details"] if detail["code"] == "dim5")

        assert 8.0 <= dim5["score"] <= 9.0
        assert dim5["score"] == pytest.approx(8.5)
        assert dim5["score_breakdown"]["valid_score_question_count"] == 20
        assert dim5["score_breakdown"]["level_counts"]["L5"] == 12
        assert (
            dim5["score_breakdown"]["bucket_counts"]["high_gaosi"]
            + dim5["score_breakdown"]["bucket_counts"]["junior_bridge"]
            + dim5["score_breakdown"]["bucket_counts"]["beyond"]
        ) == 18
        assert dim5["score_breakdown"]["unscored_applicable_count"] == 0
        assert "按知识范围等级权重计算" in dim5["evidence"]
        assert all(
            question_scores[index - 1].dim_details["dim5"]["band_source"]
            in {"knowledge_anchor", "question_bank", "llm_dim5_retry", "model_only"}
            for index in range(1, 21)
        )
        assert all(
            question.dim_details["dim5"]["band_source"]
            in {"knowledge_anchor", "question_bank", "llm_dim5_retry"}
            for question in question_scores
            if question.dim_details["dim5"]["knowledge_source_bucket"] == "beyond"
        )
        assert report["difficulty_position"]["overall_score"] == pytest.approx(8.3)
        assert report["difficulty_position"]["level"] == 5
        assert report["difficulty_position"]["label"] == "竞赛卷"

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
                dim_reasons={"dim3": "dim3 场景理解事实缺失，当前题目转入人工复核。"},
                dim_warnings={"dim3": ["dim3 缺少关键场景理解事实字段：condition_distribution。"]},
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
                dim_reasons={"dim4": "dim4 建模解题事实缺失，当前题目转入人工复核。"},
                dim_warnings={"dim4": ["dim4 缺少关键建模解题事实字段：strategy_shift_count。"]},
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
                                "reason": "dim3 场景理解事实缺失，当前题目转入人工复核。",
                                "warnings": ["dim3 缺少关键场景理解事实字段：condition_distribution。"],
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
                score_evidence="dim3 场景理解事实缺失，当前题目转入人工复核。",
                confidence=0.22,
            )
        ]

        question_scores = service._build_question_scores_from_rows(questions, tag_map, dim_rows)
        aggregated = service.aggregator.aggregate_all_dimensions(question_scores)

        assert question_scores[0].dim_statuses["dim3"] == "review"
        assert aggregated["dim3"].review_question_count == 1
        assert aggregated["dim3"].score_status == "not_covered"
        assert not aggregated["dim3"].warning_messages

    def test_report_rebuild_converts_dim4_review_payload_to_not_applicable(self):
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
                                "reason": "dim4 建模解题事实缺失，当前题目转入人工复核。",
                                "warnings": ["dim4 缺少关键建模解题事实字段：strategy_shift_count。"],
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
                score_evidence="dim4 建模解题事实缺失，当前题目转入人工复核。",
                confidence=0.22,
            )
        ]

        question_scores = service._build_question_scores_from_rows(questions, tag_map, dim_rows)
        aggregated = service.aggregator.aggregate_all_dimensions(question_scores)

        assert question_scores[0].dim_statuses["dim4"] == "not_applicable"
        assert "dim4" not in question_scores[0].dim_scores
        assert "dim4" not in question_scores[0].applicable_dims
        assert aggregated["dim4"].review_question_count == 0
        assert aggregated["dim4"].question_count == 0
        assert aggregated["dim4"].score_status == "not_covered"
        assert aggregated["dim4"].score_breakdown["auto_ignored_count"] == 1
        assert all("人工复核" not in item and "未计入" not in item for item in aggregated["dim4"].warning_messages)


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
