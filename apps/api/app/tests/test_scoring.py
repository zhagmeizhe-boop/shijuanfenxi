"""
六维评分引擎完整单元测试

重点覆盖 dim1/dim2/dim5 的 band-based 评分规则，以及整卷题级平均聚合。
"""

import asyncio

import pytest

from app.services.report.report_service import ReportService
from app.services.scoring.dim1_applicability import (
    evaluate_dim1_applicability,
    is_bare_calculation_fill_blank,
)
from app.services.scoring.dim1_computation import Dim1ComputationScorer
from app.services.scoring.dim2_spatial import Dim2SpatialScorer
from app.services.scoring.dim3_information import Dim3InformationScorer
from app.services.scoring.dim4_innovation import Dim4InnovationScorer
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

    def test_simplest_question(self, scorer):
        features = {
            "band": "4年级及以前校内课本难度",
            "sublevel": "low",
            "evidence_summary": "只涉及四年级及以前课本中的基础整数运算。",
            "evidence_tags": ["整数四则"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 1.0
        assert result.level == 1
        assert "4年级及以前校内课本难度" in result.evidence

    def test_medium_complexity(self, scorer):
        features = {
            "band": "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
            "sublevel": "mid",
            "evidence_summary": "核心门槛已经达到高思拓展或初中校内计算难度。",
            "evidence_tags": ["分数方程", "比例换算"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 7.0
        assert result.evidence != ""

    def test_highest_complexity(self, scorer):
        features = {
            "band": "高思导引超越篇难度",
            "sublevel": "high",
            "evidence_summary": "需要跨越竞赛拓展级别的复杂计算组织。",
            "evidence_tags": ["复杂构造", "多轮换元"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 9.5
        assert result.level == 5
        assert "高思导引超越篇难度" in result.evidence

    def test_alias_band_is_normalized(self, scorer):
        features = {
            "band": "5、6年级高思导引拓展篇及以下难度或七年级及以上校内课本难度",
            "sublevel": "high",
            "evidence_summary": "同义写法也应被系统接受。",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 7.5

    def test_invalid_band_marks_not_applicable(self, scorer):
        result = scorer.score({"band": "未知难度", "sublevel": "mid"})

        assert result.applicable is False
        assert result.score == 0.0
        assert "无法计算" in result.evidence

    def test_not_applicable_short_circuit(self, scorer):
        result = scorer.score({"not_applicable": True})

        assert result.applicable is False
        assert result.score == 0.0


class TestDim1Applicability:
    """测试 dim1 后端适用性门控"""

    def test_calculation_question_is_applicable(self):
        applicable, reason = evaluate_dim1_applicability("calculation", "计算：3.2 × 0.5")

        assert applicable is True
        assert "显式计算任务" in reason

    def test_bare_calculation_fill_blank_is_applicable(self):
        assert is_bare_calculation_fill_blank("3.2 × 0.5 = __") is True

        applicable, reason = evaluate_dim1_applicability("fill_blank", "3.2 × 0.5 = __")

        assert applicable is True
        assert "显式计算任务" in reason

    def test_lightly_worded_fill_blank_is_not_applicable(self):
        text = "一袋糖果有 3.2 千克，平均分成 5 份，每份是（ ）千克"

        assert is_bare_calculation_fill_blank(text) is False

        applicable, reason = evaluate_dim1_applicability("fill_blank", text)

        assert applicable is False
        assert "dim1 不适用" in reason

    def test_application_question_with_core_computation_is_not_applicable(self):
        applicable, reason = evaluate_dim1_applicability(
            "application",
            "一辆汽车 3 小时行了 180 千米，平均每小时行多少千米？",
            {
                "has_core_threshold": 1,
                "computation_role": "core",
                "evidence_summary": "需要完成单位率计算才能解题",
                "band": "5、6年级校内课本难度",
                "sublevel": "mid",
            },
            ["dim1"],
        )

        assert applicable is False
        assert "dim1 不适用" in reason

    def test_supporting_computation_does_not_self_prove_applicability(self):
        applicable, reason = evaluate_dim1_applicability(
            "solution",
            "观察图形规律，判断第10个图形中黑点个数。",
            {
                "band": "5、6年级校内课本难度",
                "sublevel": "low",
                "computation_role": "supporting",
                "applicability_confidence": 0.8,
                "evidence_summary": "最终可能要数点，但核心在于规律发现。",
            },
            ["dim1"],
        )

        assert applicable is False
        assert "dim1 不适用" in reason


class TestDim2SpatialScorer:
    """测试维度2：几何直观与空间想象评分器"""

    @pytest.fixture
    def scorer(self):
        return Dim2SpatialScorer()

    def test_not_geometry(self, scorer):
        result = scorer.score({"not_applicable": True})

        assert result.applicable is False
        assert result.score == 0.0
        assert "不适用" in result.evidence

    def test_simplest_geometry(self, scorer):
        features = {
            "band": "4年级及以前校内课本难度",
            "sublevel": "mid",
            "evidence_summary": "仅涉及长方形、正方形面积周长的基础几何。",
            "evidence_tags": ["周长", "面积"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 1.5
        assert result.level == 1

    def test_complex_geometry(self, scorer):
        features = {
            "band": "高思导引超越篇难度",
            "sublevel": "low",
            "evidence_summary": "需要多步骤综合几何模型与空间想象。",
            "evidence_tags": ["七大模型", "空间想象"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 8.5
        assert result.level == 5

    def test_3d_geometry(self, scorer):
        features = {
            "band": "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
            "sublevel": "high",
            "evidence_summary": "立体图形展开与截面分析达到第四档上沿。",
            "evidence_tags": ["展开图", "截面"],
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 7.5

    def test_invalid_geometry_band(self, scorer):
        result = scorer.score({"band": "", "sublevel": "mid"})

        assert result.applicable is False
        assert result.score == 0.0


class TestDim3InformationScorer:
    """测试维度3：信息提取与转化评分器"""

    @pytest.fixture
    def scorer(self):
        return Dim3InformationScorer()

    def test_simplest_info_processing(self, scorer):
        features = {
            "info_source_type": "text_only",
            "info_count": "few",
            "has_noise_info": 0,
            "condition_scattered": 0,
            "need_modeling": 0,
            "relation_complexity": "low",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 1.0
        assert result.level == 1
        assert "强制规则" in result.evidence

    def test_medium_complexity(self, scorer):
        features = {
            "info_source_type": "image_text",
            "info_count": "medium",
            "has_noise_info": 0,
            "condition_scattered": 1,
            "need_modeling": 1,
            "relation_complexity": "medium",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert 4.0 <= result.score <= 7.0


class TestDim4InnovationScorer:
    """测试维度4：实践与创新评分器"""

    @pytest.fixture
    def scorer(self):
        return Dim4InnovationScorer()

    def test_textbook_prototype(self, scorer):
        features = {
            "is_textbook_prototype": 1,
            "has_context_disguise": 0,
            "is_reverse_question": 0,
            "is_open_ended": 0,
            "need_strategy_selection": 0,
            "innovation_level": "low",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.score == 1.0
        assert result.level == 1

    def test_open_ended_question(self, scorer):
        features = {
            "is_textbook_prototype": 0,
            "has_context_disguise": 1,
            "is_reverse_question": 0,
            "is_open_ended": 1,
            "need_strategy_selection": 1,
            "innovation_level": "high",
        }
        result = scorer.score(features)

        assert result.applicable is True
        assert result.level == 5


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

    def test_invalid_knowledge_band(self, scorer):
        result = scorer.score({"band": "未知", "sublevel": "high"})

        assert result.applicable is False
        assert result.score == 0.0


class TestDim6LogicScorer:
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
        assert "关键步骤数1" in result.evidence

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
        assert "题级平均维度分" in result.evidence
        assert "总分值" not in result.evidence
        assert "复核提示" not in result.evidence
        assert len(result.counted_questions) == 2
        assert result.counted_questions[0]["question_no"] == "2"
        assert result.counted_questions[0]["question_label_raw"] == "（2）"
        assert result.counted_questions[0]["question_display_label"] == "（2）"
        assert result.counted_questions[0]["page_no"] == 2

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
                dim_scores={"dim5": 6.5},
                applicable_dims=["dim5"],
            ),
            QuestionDimensionScore(
                question_id="q2",
                question_no="2",
                score=10.0,
                dim_scores={"dim5": 6.5},
                applicable_dims=["dim5"],
            ),
        ]

        result = aggregator.aggregate(question_scores, "dim5")

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
        assert "没有适用此维度的题目" in result.evidence


class TestDifficultyPositioning:
    """测试难度定位"""

    @pytest.fixture
    def aggregator(self):
        return PaperAggregator()

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
                "band": "4年级及以前高思导引拓展篇及以下难度",
                "sublevel": "high",
                "evidence_summary": "需要在拓展题语境下完成关键计算。",
            },
            "dim2": {
                "band": "5、6年级校内课本难度",
                "sublevel": "mid",
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
                    "band": "4年级及以前校内课本难度",
                    "sublevel": "low",
                },
                "score": 5.0,
            },
            {
                "features": {
                    "band": "5、6年级校内课本难度",
                    "sublevel": "mid",
                },
                "score": 8.0,
            },
            {
                "features": {
                    "band": "高思导引超越篇难度",
                    "sublevel": "high",
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
