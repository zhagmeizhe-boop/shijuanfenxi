import asyncio
import json
import httpx
import pytest

from app.services.llm.moonshot_client import MoonshotClient
from app.services.ocr.base import ParsedQuestion, QuestionType
from app.services.parser.ai_parser import (
    AIParser,
    JSON_REPAIR_STATUS_FAILED,
    JSON_REPAIR_STATUS_LLM,
    JSON_REPAIR_STATUS_LOCAL,
)
from app.services.scoring.banded_dimension import BAND_SCORE_MAP


class StubReferenceStandard:
    def calibrate_feature(self, dim_code, feature, **kwargs):
        normalized = dict(feature or {})
        normalized.setdefault("calibration", {})
        return normalized


class RecordingReferenceStandard(StubReferenceStandard):
    def __init__(self):
        self.calls = []

    def calibrate_feature(self, dim_code, feature, **kwargs):
        self.calls.append(dim_code)
        return super().calibrate_feature(dim_code, feature, **kwargs)


class Dim5ReferenceFillStandard(StubReferenceStandard):
    def calibrate_feature(self, dim_code, feature, **kwargs):
        normalized = super().calibrate_feature(dim_code, feature, **kwargs)
        if dim_code == "dim5":
            normalized.update(
                {
                    "band": list(BAND_SCORE_MAP.keys())[3],
                    "sublevel": "low",
                    "gaosi_grade": "5",
                    "gaosi_section_level": "interest",
                    "gaosi_section_label": "兴趣篇",
                    "gaosi_classification_source": "question_bank",
                }
            )
        return normalized


class Dim4SkeletonCandidateStandard(StubReferenceStandard):
    def __init__(self):
        self.candidate_calls = 0

    def gaosi_question_candidates(self, feature, **kwargs):
        self.candidate_calls += 1
        return [
            {
                "source": "gaosi_question_pdf",
                "book_name": "竞赛数学导引 五年级",
                "grade": "5",
                "lecture_no": "8",
                "lecture_title": "牛吃草问题",
                "section_level": "extension",
                "section_label": "拓展篇",
                "question_no": "3",
                "question_text_excerpt": "检票口每分钟都有人排队，多个窗口按效率检票。",
                "similarity_strength": 2,
                "similarity_type": "high_similarity",
                "match_quality": "ok",
                "auto_correction_allowed": True,
                "auto_dim4_calibration_allowed": False,
                "structure_profile": {"topic_domain": "application"},
                "dim4_profile": {
                    "reference_level": "L4",
                    "profile_confidence": 0.55,
                    "auto_calibration_allowed": False,
                    "profile_source": "local_structure_skeleton",
                },
            }
        ]

    def calibrate_dim4_feature(self, feature, **kwargs):
        normalized = dict(feature or {})
        normalized.setdefault(
            "calibration",
            {"action": "audit_only_unreliable_reference"},
        )
        return normalized


class FakeLLM:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self.error:
            raise self.error
        if self.responses:
            return self.responses.pop(0)
        raise AssertionError("No fake response configured")


def make_parser(fake_llm):
    parser = AIParser.__new__(AIParser)
    parser.llm = fake_llm
    parser.reference_standard = StubReferenceStandard()
    return parser


def make_question(question_no="3"):
    return ParsedQuestion(
        question_no=question_no,
        question_type=QuestionType.CALCULATION,
        raw_text="统计古诗中“春”字出现次数占全诗总字数的百分比。",
        page_no=1,
    )


def valid_payload(question_summary="统计古诗中字出现次数占比"):
    return f"""{{
  "question_summary": "{question_summary}",
  "analysis_facts": {{
    "core_task": "统计指定文字出现次数并计算百分比",
    "core_knowledge_points": ["百分数的意义", "百分数的计算"],
    "core_methods": ["计数", "百分数计算"],
    "visual_elements": [],
    "fact_basis": "题面明确要求统计并计算占比",
    "image_used": 0,
    "has_sub_items": 0
  }},
  "applicable_dimensions": ["dim1", "dim5"],
  "features": {{
    "dim1_computation": {{
      "task_form": "embedded",
      "calc_role": "core",
      "step_chain": "2",
      "number_mix": "standard",
      "routine_transform_count": "1",
      "structural_method": "none",
      "global_view_required": 0,
      "error_pressure": "medium",
      "evidence_summary": "需要完成基础百分数计算",
      "evidence_tags": ["百分数", "求占比"]
    }},
    "dim2_spatial": {{}},
    "dim3_information": {{}},
    "dim4_innovation": {{}},
    "dim5_knowledge": {{
      "band": "4年级及以前校内课本难度",
      "sublevel": "low",
      "evidence_summary": "核心知识点为百分数",
      "knowledge_tags": ["百分数"],
      "core_knowledge_units": ["百分数"],
      "supporting_knowledge_units": ["计数"],
      "knowledge_family_count": "1",
      "knowledge_integration": "single",
      "novel_definition_dependency": "none",
      "competition_signal": "none",
      "applicability_confidence": 0.8,
      "warning": ""
    }},
    "dim6_logic": {{}}
  }},
  "confidence": 0.87,
  "reasoning": "题目核心是统计指定字并计算占比。"
}}"""


def dim5_retry_test_payload(dim5_overrides=None):
    dim5 = {
        "band": "",
        "sublevel": "",
        "evidence_summary": "",
        "knowledge_tags": ["百分数"],
        "core_knowledge_units": ["百分数的意义"],
        "supporting_knowledge_units": [],
        "knowledge_family_count": "1",
        "knowledge_integration": "single",
        "novel_definition_dependency": "none",
        "competition_signal": "none",
        "applicability_confidence": 0.8,
        "warning": "",
    }
    dim5.update(dim5_overrides or {})
    data = {
        "question_summary": "判断百分数知识门槛",
        "analysis_facts": {
            "core_task": "根据题意判断百分数关系",
            "core_knowledge_points": ["百分数的意义"],
            "core_methods": ["百分数关系识别"],
            "visual_elements": [],
            "fact_basis": "题面核心知识点清晰",
            "image_used": 0,
            "has_sub_items": 0,
        },
        "applicable_dimensions": ["dim5"],
        "features": {
            "dim1_computation": {},
            "dim2_spatial": {},
            "dim3_information": {},
            "dim4_innovation": {},
            "dim5_knowledge": dim5,
            "dim6_logic": {},
        },
        "confidence": 0.86,
        "reasoning": "测试 dim5 缺 band 的二次判定。",
    }
    return json.dumps(data, ensure_ascii=False)


def test_dim1_normalizes_pure_calculation_structural_fields():
    parser = make_parser(FakeLLM())

    feature = parser._normalize_dim1_feature(
        {
            "task_form": "explicit",
            "calc_role": "core",
            "calc_bucket": "pure_calculation",
            "step_chain": "5+",
            "number_mix": "symbolic",
            "routine_transform_count": "3+",
            "structural_method": "olympiad",
            "global_view_required": 1,
            "error_pressure": "high",
            "calc_subtype": "sequence_series",
            "structure_patterns": ["telescoping", "bad_value", "common_factor", "telescoping"],
            "term_count_band": "11+",
            "symbolic_dependency": "parameterized",
            "evidence_summary": "长链裂项求和。",
            "evidence_tags": ["裂项", "长链"],
        }
    )

    assert feature["calc_subtype"] == "sequence_series"
    assert feature["structure_patterns"] == ["telescoping", "common_factor"]
    assert feature["term_count_band"] == "11+"
    assert feature["symbolic_dependency"] == "parameterized"


def test_dim2_normalizes_geometry_model_fields():
    parser = make_parser(FakeLLM())

    feature = parser._normalize_dim2_feature(
        {
            "task_form": "explicit_visual",
            "spatial_role": "core",
            "figure_complexity": "composite_2d",
            "relation_hops": "3-4",
            "hidden_relation_count": "1",
            "visual_operation_count": "2",
            "structural_visual_method": "decomposition",
            "measurement_dependency": "inferred",
            "global_view_required": 1,
            "image_dependency": "required",
            "geometry_model_types": [
                "butterfly_area",
                "bad_value",
                "cut_and_fill",
                "butterfly_area",
                "surface_three_view",
            ],
            "geometry_model_count": "2",
            "model_recognition_role": "core",
            "area_relation_chain": "multi",
            "model_combination_complexity": "model_plus_operation",
            "evidence_summary": "蝴蝶模型叠加割补。",
            "evidence_tags": ["蝴蝶模型", "割补"],
            "applicability_confidence": 0.9,
        }
    )

    assert feature["geometry_model_types"] == ["butterfly_area", "cut_and_fill", "surface_three_view"]
    assert feature["geometry_model_count"] == "2"
    assert feature["model_recognition_role"] == "core"
    assert feature["area_relation_chain"] == "multi"
    assert feature["model_combination_complexity"] == "model_plus_operation"


def test_dim3_normalizes_application_relation_fields():
    parser = make_parser(FakeLLM())

    feature = parser._normalize_dim3_feature(
        {
            "information_role": "core",
            "source_form": "text_only",
            "relevant_condition_count": "5-6",
            "distractor_pressure": "light",
            "condition_distribution": "cross_sentence",
            "extraction_depth": "reorganized",
            "representation_conversion": "relation_mapping",
            "conversion_step_count": "2",
            "quantity_relation_structure": "multi_relation",
            "target_representation": "equation_relation",
            "global_organizing_required": 1,
            "image_dependency": "none",
            "application_relation_types": ["profit_discount", "bad_value", "profit_discount", "work_rate"],
            "object_count_band": "3",
            "state_change_count": "3+",
            "implicit_relation_count": "2",
            "base_quantity_shift": "multiple",
            "comparison_candidate_count": "3+",
            "evidence_summary": "多阶段利润题。",
            "evidence_tags": ["利润", "折扣"],
            "applicability_confidence": 0.9,
        }
    )

    assert feature["application_relation_types"] == ["profit_discount", "work_rate"]
    assert feature["object_count_band"] == "3"
    assert feature["state_change_count"] == "3+"
    assert feature["implicit_relation_count"] == "2"
    assert feature["base_quantity_shift"] == "multiple"
    assert feature["comparison_candidate_count"] == "3+"


def test_parse_response_repairs_unescaped_inner_quotes_locally():
    parser = make_parser(FakeLLM())
    question = make_question("3")
    broken_response = valid_payload('统计古诗中"春"字出现次数占全诗总字数的百分比')

    features = asyncio.run(parser._parse_response_with_repairs(broken_response, question))

    assert features.parse_failed is False
    assert features.json_repair_status == JSON_REPAIR_STATUS_LOCAL
    assert "LLM JSON 已本地修复" in features.warnings
    assert features.need_manual_review is False
    assert features.question_summary == '统计古诗中"春"字出现次数占全诗总字数的百分比'


def test_parse_response_bypasses_dim1_reference_calibration():
    fake_llm = FakeLLM()
    parser = AIParser.__new__(AIParser)
    parser.llm = fake_llm
    parser.reference_standard = RecordingReferenceStandard()
    question = make_question("5")

    features = asyncio.run(parser._parse_response_with_repairs(valid_payload(), question))

    assert features.parse_failed is False
    assert parser.reference_standard.calls == ["dim4", "dim5"]


def test_parse_response_retries_missing_dim5_band_with_llm():
    retry_band = list(BAND_SCORE_MAP.keys())[1]
    fake_llm = FakeLLM(
        responses=[
            json.dumps(
                {
                    "band": retry_band,
                    "sublevel": "mid",
                    "evidence_summary": "核心知识门槛是五六年级百分数关系。",
                    "knowledge_tags": ["百分数"],
                    "core_knowledge_units": ["百分数应用"],
                    "confidence": 0.82,
                },
                ensure_ascii=False,
            )
        ]
    )
    parser = make_parser(fake_llm)
    question = make_question("11")

    features = asyncio.run(parser._parse_response_with_repairs(dim5_retry_test_payload(), question))

    assert features.parse_failed is False
    assert features.dim5_knowledge["band"] == retry_band
    assert features.dim5_knowledge["sublevel"] == "mid"
    assert features.dim5_knowledge["band_source"] == "llm_dim5_retry"
    assert features.dim5_knowledge["dim5_retry_used"] is True
    assert features.dim5_knowledge["dim5_retry_confidence"] == 0.82
    assert "dim5" in features.applicable_dimensions
    assert len(fake_llm.calls) == 1
    assert fake_llm.calls[0]["kwargs"]["max_tokens"] == 1200


def test_parse_response_dim5_retry_writes_gaosi_classification_fields():
    fake_llm = FakeLLM(
        responses=[
            json.dumps(
                {
                    "gaosi_grade": "5",
                    "gaosi_section_level": "extension",
                    "gaosi_section_label": "拓展篇",
                    "band": list(BAND_SCORE_MAP.keys())[1],
                    "sublevel": "low",
                    "evidence_summary": "奥数/竞赛备考来源统一归入五年级高思导引拓展篇。",
                    "knowledge_tags": ["牛吃草问题"],
                    "core_knowledge_units": ["牛吃草问题"],
                    "confidence": 0.86,
                },
                ensure_ascii=False,
            )
        ]
    )
    parser = make_parser(fake_llm)
    question = make_question("11b")

    features = asyncio.run(parser._parse_response_with_repairs(dim5_retry_test_payload(), question))

    assert features.parse_failed is False
    assert features.dim5_knowledge["band"] == list(BAND_SCORE_MAP.keys())[3]
    assert features.dim5_knowledge["sublevel"] == "mid"
    assert features.dim5_knowledge["gaosi_grade"] == "5"
    assert features.dim5_knowledge["gaosi_section_level"] == "extension"
    assert features.dim5_knowledge["gaosi_section_label"] == "拓展篇"
    assert features.dim5_knowledge["gaosi_classification_source"] == "llm_retry"
    assert "Local reference candidates" in fake_llm.calls[0]["messages"][1]["content"]


def test_parse_response_uses_reference_before_dim5_retry_when_available():
    fake_llm = FakeLLM()
    parser = make_parser(fake_llm)
    parser.reference_standard = Dim5ReferenceFillStandard()
    question = make_question("11c")

    features = asyncio.run(parser._parse_response_with_repairs(dim5_retry_test_payload(), question))

    assert features.parse_failed is False
    assert features.dim5_knowledge["band"] == list(BAND_SCORE_MAP.keys())[3]
    assert features.dim5_knowledge["sublevel"] == "low"
    assert features.dim5_knowledge["gaosi_classification_source"] == "question_bank"
    assert "dim5" in features.applicable_dimensions
    assert fake_llm.calls == []


def test_parse_response_does_not_retry_when_dim5_band_is_valid():
    valid_band = list(BAND_SCORE_MAP.keys())[0]
    fake_llm = FakeLLM()
    parser = make_parser(fake_llm)
    question = make_question("12")

    features = asyncio.run(
        parser._parse_response_with_repairs(
            dim5_retry_test_payload({"band": valid_band, "sublevel": "low"}),
            question,
        )
    )

    assert features.parse_failed is False
    assert features.dim5_knowledge["band"] == valid_band
    assert features.dim5_knowledge["sublevel"] == "low"
    assert features.dim5_knowledge["band_source"] == ""
    assert fake_llm.calls == []


def test_parse_response_adds_dim4_l1_for_stable_known_topic_without_llm():
    fake_llm = FakeLLM()
    parser = make_parser(fake_llm)
    question = make_question("12a")

    features = asyncio.run(
        parser._parse_response_with_repairs(
            dim5_retry_test_payload({"band": list(BAND_SCORE_MAP.keys())[0], "sublevel": "low"}),
            question,
        )
    )

    assert features.parse_failed is False
    assert features.dim4_innovation["knowledge_point"] == "比例百分数应用"
    assert features.dim4_innovation["topic_level"] == "L1"
    assert features.dim4_innovation["level_source"] == "knowledge_anchor"
    assert "dim4" in features.applicable_dimensions
    assert fake_llm.calls == []


def test_parse_response_retries_when_dim5_sublevel_is_missing():
    valid_band = list(BAND_SCORE_MAP.keys())[0]
    fake_llm = FakeLLM(
        responses=[
            json.dumps(
                {
                    "band": valid_band,
                    "sublevel": "mid",
                    "evidence_summary": "补齐档内层级。",
                    "knowledge_tags": ["百分数"],
                    "core_knowledge_units": ["百分数应用"],
                    "confidence": 0.78,
                },
                ensure_ascii=False,
            )
        ]
    )
    parser = make_parser(fake_llm)
    question = make_question("12b")

    features = asyncio.run(
        parser._parse_response_with_repairs(
            dim5_retry_test_payload({"band": valid_band, "sublevel": ""}),
            question,
        )
    )

    assert features.parse_failed is False
    assert features.dim5_knowledge["band"] == valid_band
    assert features.dim5_knowledge["sublevel"] == "mid"
    assert features.dim5_knowledge["band_source"] == "llm_dim5_retry"
    assert "dim5" in features.applicable_dimensions
    assert len(fake_llm.calls) == 1


def test_parse_response_excludes_dim5_when_retry_is_invalid():
    fake_llm = FakeLLM(responses=["not json"])
    parser = make_parser(fake_llm)
    question = make_question("13")

    features = asyncio.run(parser._parse_response_with_repairs(dim5_retry_test_payload(), question))

    assert features.parse_failed is False
    assert features.dim5_knowledge["band"] == ""
    assert features.dim5_knowledge["sublevel"] == ""
    assert features.dim5_knowledge["band_source"] == "llm_dim5_retry_failed"
    assert features.dim5_knowledge["dim5_retry_used"] is True
    assert features.dim5_knowledge["dim5_excluded_reason"] == "retry_failed"
    assert "dim5" not in features.applicable_dimensions
    assert len(fake_llm.calls) == 1


def test_parse_response_excludes_dim5_when_retry_call_fails_but_keeps_other_dims():
    fake_llm = FakeLLM(error=RuntimeError("dim5 retry unavailable"))
    parser = make_parser(fake_llm)
    question = make_question("13b")
    payload = json.loads(dim5_retry_test_payload())
    payload["applicable_dimensions"] = ["dim1", "dim5"]
    payload["features"]["dim1_computation"] = {
        "task_form": "embedded",
        "calc_role": "core",
        "step_chain": "2",
        "number_mix": "standard",
        "routine_transform_count": "1",
        "structural_method": "none",
        "global_view_required": 0,
        "error_pressure": "medium",
        "evidence_summary": "核心仍需要百分数计算。",
    }

    features = asyncio.run(
        parser._parse_response_with_repairs(json.dumps(payload, ensure_ascii=False), question)
    )

    assert features.parse_failed is False
    assert features.dim5_knowledge["band_source"] == "llm_dim5_retry_failed"
    assert features.dim5_knowledge["dim5_excluded_reason"] == "retry_failed"
    assert "dim5" not in features.applicable_dimensions
    assert "dim1" in features.applicable_dimensions


def test_parse_response_excludes_dim5_when_retry_sublevel_is_invalid():
    retry_band = list(BAND_SCORE_MAP.keys())[1]
    fake_llm = FakeLLM(
        responses=[
            json.dumps(
                {
                    "band": retry_band,
                    "sublevel": "middle",
                    "evidence_summary": "非法档内层级。",
                    "knowledge_tags": ["百分数"],
                    "core_knowledge_units": ["百分数应用"],
                    "confidence": 0.8,
                },
                ensure_ascii=False,
            )
        ]
    )
    parser = make_parser(fake_llm)
    question = make_question("13c")

    features = asyncio.run(parser._parse_response_with_repairs(dim5_retry_test_payload(), question))

    assert features.parse_failed is False
    assert features.dim5_knowledge["band_source"] == "llm_dim5_retry_failed"
    assert features.dim5_knowledge["dim5_excluded_reason"] == "retry_failed"
    assert "dim5" not in features.applicable_dimensions


def test_parse_response_keeps_low_confidence_dim5_retry_applicable_with_warning():
    retry_band = list(BAND_SCORE_MAP.keys())[1]
    fake_llm = FakeLLM(
        responses=[
            json.dumps(
                {
                    "band": retry_band,
                    "sublevel": "low",
                    "evidence_summary": "低置信知识档位判断。",
                    "knowledge_tags": ["百分数"],
                    "core_knowledge_units": ["百分数应用"],
                    "confidence": 0.3,
                },
                ensure_ascii=False,
            )
        ]
    )
    parser = make_parser(fake_llm)
    question = make_question("14")

    features = asyncio.run(parser._parse_response_with_repairs(dim5_retry_test_payload(), question))

    assert features.parse_failed is False
    assert features.dim5_knowledge["band_source"] == "llm_dim5_retry"
    assert features.dim5_knowledge["dim5_retry_confidence"] == 0.3
    assert "dim5" in features.applicable_dimensions
    assert any("dim5" in warning and "置信度" in warning for warning in features.warnings)


def test_parse_response_marks_manual_review_for_dim3_warnings():
    parser = make_parser(FakeLLM())
    question = make_question("8")
    payload = """{
  "question_summary": "根据统计图分析销量变化",
  "analysis_facts": {
    "core_task": "从统计图和文字中整理销量变化关系",
    "core_knowledge_points": ["统计图", "数量关系"],
    "core_methods": ["读图", "整理条件"],
    "visual_elements": ["统计图"],
    "fact_basis": "题面提供统计图和说明文字",
    "image_used": 0,
    "has_sub_items": 0
  },
  "applicable_dimensions": ["dim3", "dim5"],
  "features": {
    "dim1_computation": {},
    "dim2_spatial": {},
    "dim3_information": {
      "information_role": "core",
      "source_form": "table_chart",
      "evidence_summary": "缺少完整的信息提取事实",
      "applicability_confidence": 0.4,
      "need_manual_review": 0,
      "warning": ""
    },
    "dim4_innovation": {},
    "dim5_knowledge": {
      "band": "4年级及以前校内课本难度",
      "sublevel": "low",
      "evidence_summary": "核心知识点为统计图",
      "knowledge_tags": ["统计图"],
      "applicability_confidence": 0.8,
      "warning": ""
    },
    "dim6_logic": {}
  },
  "confidence": 0.74,
  "reasoning": "需要从图表中提取条件。"
}"""

    features = asyncio.run(parser._parse_response_with_repairs(payload, question))

    assert features.parse_failed is False
    assert features.need_manual_review is True
    assert any(item.startswith("dim3 ") for item in features.warnings)


def test_parse_response_marks_manual_review_for_dim4_warnings():
    parser = make_parser(FakeLLM())
    question = ParsedQuestion(
        question_no="10",
        question_type=QuestionType.APPLICATION,
        raw_text="尝试不同构造方案，找出所有满足条件的结果。",
        page_no=1,
    )
    payload = """{
  "question_summary": "尝试不同构造方案并找出所有结果",
  "analysis_facts": {
    "core_task": "尝试不同构造方案并筛出满足条件的所有结果",
    "core_knowledge_points": ["构造", "分类讨论"],
    "core_methods": ["试探", "构造"],
    "visual_elements": [],
    "fact_basis": "题面明确要求尝试不同方案并找出所有结果",
    "image_used": 0,
    "has_sub_items": 0
  },
  "applicable_dimensions": ["dim4", "dim5"],
  "features": {
    "dim1_computation": {},
    "dim2_spatial": {},
    "dim3_information": {},
    "dim4_innovation": {
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
      "evidence_summary": "字段组合存在明显冲突",
      "evidence_tags": ["构造", "探索"],
      "applicability_confidence": 0.82,
      "need_manual_review": 0,
      "warning": ""
    },
    "dim5_knowledge": {
      "band": "4年级及以前校内课本难度",
      "sublevel": "low",
      "evidence_summary": "核心知识门槛不高",
      "knowledge_tags": ["构造"],
      "applicability_confidence": 0.8,
      "warning": ""
    },
    "dim6_logic": {}
  },
  "confidence": 0.78,
  "reasoning": "题面核心在策略尝试与构造。"
}"""

    features = asyncio.run(parser._parse_response_with_repairs(payload, question))

    assert features.parse_failed is False
    assert features.need_manual_review is True
    assert any(item.startswith("dim4 ") for item in features.warnings)


def test_parse_response_fills_dim4_topic_level_from_local_anchor():
    parser = make_parser(FakeLLM())
    question = ParsedQuestion(
        question_no="10a",
        question_type=QuestionType.APPLICATION,
        raw_text="检票口每分钟都有新人排队进入，已知两个开放窗口的检票时间，求增加窗口后的完成时间。",
        page_no=1,
    )
    payload = """{
  "question_summary": "检票排队增长问题",
  "analysis_facts": {
    "core_task": "把检票排队转成边增长边消耗关系",
    "core_knowledge_points": ["牛吃草问题"],
    "core_methods": ["增长-消耗关系"],
    "visual_elements": [],
    "fact_basis": "题面存在排队增长与检票消耗",
    "image_used": 0,
    "has_sub_items": 0
  },
  "applicable_dimensions": ["dim4", "dim5"],
  "features": {
    "dim1_computation": {},
    "dim2_spatial": {},
    "dim3_information": {},
    "dim4_innovation": {
      "knowledge_point": "牛吃草问题",
      "topic_level": "L5",
      "level_source": "",
      "anchor_evidence": "",
      "reference_matches": [],
      "fallback_used": 0,
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
      "evidence_summary": "需要识别检票排队增长是牛吃草伪装场景",
      "evidence_tags": ["牛吃草", "排队增长"],
      "applicability_confidence": 0.86,
      "need_manual_review": 0,
      "warning": ""
    },
    "dim5_knowledge": {
      "band": "5、6年级校内课本难度",
      "sublevel": "mid",
      "evidence_summary": "核心知识点为排队增长关系",
      "knowledge_tags": ["牛吃草问题"],
      "core_knowledge_units": ["牛吃草问题"],
      "applicability_confidence": 0.8,
      "warning": ""
    },
    "dim6_logic": {}
  },
  "confidence": 0.84,
  "reasoning": "测试 dim4 本地知识点锚点。"
}"""

    features = asyncio.run(parser._parse_response_with_repairs(payload, question))

    assert features.parse_failed is False
    assert features.dim4_innovation["knowledge_point"] == "牛吃草"
    assert features.dim4_innovation["topic_level"] == "L3"
    assert features.dim4_innovation["level_source"] == "knowledge_anchor"
    assert features.dim4_innovation["fallback_used"] is False
    assert "dim4" in features.applicable_dimensions
    assert parser.llm.calls == []


def test_parse_response_uses_dim4_llm_fallback_for_uncovered_topic():
    fake_llm = FakeLLM(
        responses=[
            json.dumps(
                {
                    "knowledge_point": "鸡兔同笼",
                    "topic_level": "L4",
                    "anchor_evidence": "需要构造假设并分类回查。",
                    "confidence": 0.82,
                },
                ensure_ascii=False,
            )
        ]
    )
    parser = make_parser(fake_llm)
    question = ParsedQuestion(
        question_no="10b",
        question_type=QuestionType.APPLICATION,
        raw_text="鸡兔同笼变式，需要自己构造假设并分类回查所有可能。",
        page_no=1,
    )
    payload = json.loads(valid_payload("鸡兔同笼变式"))
    payload["applicable_dimensions"] = ["dim4", "dim5"]
    payload["analysis_facts"]["core_knowledge_points"] = ["鸡兔同笼"]
    payload["features"]["dim4_innovation"] = {
        "knowledge_point": "鸡兔同笼",
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
        "image_dependency": "none",
        "evidence_summary": "需要构造假设并分类回查。",
        "applicability_confidence": 0.84,
    }
    payload["features"]["dim5_knowledge"] = {
        "band": "5、6年级校内课本难度",
        "sublevel": "mid",
        "evidence_summary": "核心知识点为鸡兔同笼。",
        "knowledge_tags": ["鸡兔同笼"],
        "core_knowledge_units": ["鸡兔同笼"],
        "applicability_confidence": 0.8,
    }

    features = asyncio.run(
        parser._parse_response_with_repairs(json.dumps(payload, ensure_ascii=False), question)
    )

    assert features.parse_failed is False
    assert features.dim4_innovation["topic_level"] == "L4"
    assert features.dim4_innovation["level_source"] == "llm_fallback"
    assert features.dim4_innovation["fallback_used"] is True
    assert features.dim4_innovation["fallback_confidence"] == 0.82
    assert "dim4" in features.applicable_dimensions


def test_parse_response_uses_gaosi_candidate_before_dim4_local_anchor():
    fake_llm = FakeLLM(
        responses=[
            json.dumps(
                {
                    "knowledge_point": "牛吃草问题",
                    "topic_level": "L4",
                    "anchor_evidence": "相似高思题库候选显示该题是排队增长场景变式，需要先转化增长-消耗模型再组织窗口效率。",
                    "confidence": 0.84,
                },
                ensure_ascii=False,
            )
        ]
    )
    parser = make_parser(fake_llm)
    parser.reference_standard = Dim4SkeletonCandidateStandard()
    question = ParsedQuestion(
        question_no="10bb",
        question_type=QuestionType.APPLICATION,
        raw_text="检票口每分钟都有新人排队进入，已知两个开放窗口的检票时间，求增加窗口后的完成时间。",
    )
    payload = json.loads(valid_payload("检票排队增长变式"))
    payload["applicable_dimensions"] = ["dim4", "dim5"]
    payload["analysis_facts"]["core_knowledge_points"] = ["牛吃草问题"]
    payload["features"]["dim4_innovation"] = {
        "knowledge_point": "牛吃草问题",
        "strategy_role": "core",
        "template_fit": "reframed",
        "breakthrough_type": "strategy_shift",
        "strategy_shift_count": "1",
        "applicability_confidence": 0.84,
    }
    payload["features"]["dim5_knowledge"] = {
        "band": "5、6年级校内课本难度",
        "sublevel": "mid",
        "evidence_summary": "核心知识点为牛吃草问题。",
        "knowledge_tags": ["牛吃草问题"],
        "core_knowledge_units": ["牛吃草问题"],
        "applicability_confidence": 0.84,
    }

    features = asyncio.run(
        parser._parse_response_with_repairs(json.dumps(payload, ensure_ascii=False), question)
    )

    assert features.parse_failed is False
    assert features.dim4_innovation["topic_level"] == "L4"
    assert features.dim4_innovation["level_source"] == "llm_fallback"
    assert features.dim4_innovation["reference_matches"][0]["similarity_type"] == "high_similarity"
    fallback_prompt = fake_llm.calls[0]["messages"][1]["content"]
    assert "Local GaoSi question-bank candidates" in fallback_prompt
    assert "Non-contest questions may still be L4" in fallback_prompt
    assert "Do not copy GaoSi section level directly as dim4 level" in fallback_prompt
    assert "dim4" in features.applicable_dimensions


def test_parse_response_dim4_fallback_failure_marks_review_failed():
    fake_llm = FakeLLM(responses=["not json"])
    parser = make_parser(fake_llm)
    question = ParsedQuestion(
        question_no="10c",
        question_type=QuestionType.APPLICATION,
        raw_text="鸡兔同笼变式，需要自己构造假设并分类回查所有可能。",
        page_no=1,
    )
    payload = json.loads(valid_payload("鸡兔同笼变式"))
    payload["applicable_dimensions"] = ["dim4", "dim5"]
    payload["analysis_facts"]["core_knowledge_points"] = ["鸡兔同笼"]
    payload["features"]["dim4_innovation"] = {
        "knowledge_point": "鸡兔同笼",
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
        "image_dependency": "none",
        "evidence_summary": "需要构造假设并分类回查。",
        "applicability_confidence": 0.84,
    }
    payload["features"]["dim5_knowledge"] = {
        "band": "5、6年级校内课本难度",
        "sublevel": "mid",
        "evidence_summary": "核心知识点为鸡兔同笼。",
        "knowledge_tags": ["鸡兔同笼"],
        "core_knowledge_units": ["鸡兔同笼"],
        "applicability_confidence": 0.8,
    }

    features = asyncio.run(
        parser._parse_response_with_repairs(json.dumps(payload, ensure_ascii=False), question)
    )

    assert features.parse_failed is False
    assert features.dim4_innovation["level_source"] == "review_failed"
    assert features.dim4_innovation["fallback_used"] is True
    assert "dim4" not in features.applicable_dimensions
    assert any(item.startswith("dim4 ") for item in features.warnings)


def test_parse_response_marks_manual_review_for_dim6_warnings():
    parser = make_parser(FakeLLM())
    question = make_question("12")
    payload = """{
  "question_summary": "分类讨论并验证结论",
  "analysis_facts": {
    "core_task": "分类讨论所有可能情况并验证最终结论",
    "core_knowledge_points": ["分类讨论"],
    "core_methods": ["分情况分析", "结果检验"],
    "visual_elements": [],
    "fact_basis": "题面明确要求分类讨论和验证",
    "image_used": 0,
    "has_sub_items": 0
  },
  "applicable_dimensions": ["dim6", "dim5"],
  "features": {
    "dim1_computation": {},
    "dim2_spatial": {},
    "dim3_information": {},
    "dim4_innovation": {},
    "dim5_knowledge": {
      "band": "4年级及以前校内课本难度",
      "sublevel": "low",
      "evidence_summary": "核心知识点为分类讨论",
      "knowledge_tags": ["分类讨论"],
      "applicability_confidence": 0.8,
      "warning": ""
    },
    "dim6_logic": {
      "reasoning_role": "core",
      "chain_span": "1",
      "hidden_dependency": "none",
      "branch_control": "multi_branch",
      "reversibility": "none",
      "verification_requirement": "full_consistency",
      "abstraction_bridge_count": "0",
      "constraint_coupling": "none",
      "global_consistency_required": 0,
      "conclusion_stability": "direct",
      "evidence_summary": "字段组合存在明显冲突",
      "evidence_tags": ["分类讨论", "验证"],
      "applicability_confidence": 0.82,
      "need_manual_review": 0,
      "warning": ""
    }
  },
  "confidence": 0.78,
  "reasoning": "题目要求分类讨论并检查结论。"
}"""

    features = asyncio.run(parser._parse_response_with_repairs(payload, question))

    assert features.parse_failed is False
    assert features.need_manual_review is True
    assert any(item.startswith("dim6 ") for item in features.warnings)


def test_parse_response_retries_dim5_sublevel_from_knowledge_anchors():
    retry_band = list(BAND_SCORE_MAP.keys())[1]
    parser = make_parser(
        FakeLLM(
            responses=[
                json.dumps(
                    {
                        "band": retry_band,
                        "sublevel": "mid",
                        "evidence_summary": "比例和百分数组合，档内定位为中位。",
                        "knowledge_tags": ["比例", "百分数"],
                        "core_knowledge_units": ["比例", "百分数"],
                        "confidence": 0.84,
                    },
                    ensure_ascii=False,
                )
            ]
        )
    )
    question = ParsedQuestion(
        question_no="16",
        question_type=QuestionType.APPLICATION,
        raw_text="甲乙两数的比是 3:5，其中甲数占总数的百分之几？",
        page_no=1,
    )
    payload = """{
  "question_summary": "组合比例与百分数求解",
  "analysis_facts": {
    "core_task": "组织比例和百分数关系后求未知量",
    "core_knowledge_points": ["比例", "百分数"],
    "core_methods": ["整理条件", "列关系"],
    "visual_elements": [],
    "fact_basis": "题面给出比例和百分数条件",
    "image_used": 0,
    "has_sub_items": 0
  },
  "applicable_dimensions": ["dim5"],
  "features": {
    "dim1_computation": {
      "task_form": "embedded",
      "calc_role": "supporting",
      "step_chain": "1",
      "number_mix": "plain",
      "routine_transform_count": "0",
      "structural_method": "none",
      "global_view_required": 0,
      "error_pressure": "low",
      "evidence_summary": "题目可能涉及一步基础计算，但核心门槛不在 dim1。",
      "evidence_tags": ["一步计算"]
    },
    "dim2_spatial": {},
    "dim3_information": {},
    "dim4_innovation": {},
    "dim5_knowledge": {
      "band": "5、6年级校内课本难度",
      "sublevel": "",
      "evidence_summary": "核心知识单元为比例和百分数，需要跨知识家族整理。",
      "knowledge_tags": ["比例", "百分数"],
      "core_knowledge_units": ["比例", "百分数"],
      "supporting_knowledge_units": ["数量关系"],
      "knowledge_family_count": "2",
      "knowledge_integration": "cross_family_combo",
      "novel_definition_dependency": "none",
      "competition_signal": "none",
      "applicability_confidence": 0.84,
      "warning": ""
    },
    "dim6_logic": {}
  },
  "confidence": 0.81,
  "reasoning": "题目核心知识门槛是比例与百分数的组合。"
}"""

    features = asyncio.run(parser._parse_response_with_repairs(payload, question))

    assert features.parse_failed is False
    assert features.dim5_knowledge["sublevel"] == "mid"
    assert features.dim5_knowledge["band_source"] == "llm_dim5_retry"
    assert features.need_manual_review is False


def test_parse_response_marks_manual_review_for_dim5_warnings():
    parser = make_parser(FakeLLM())
    question = make_question("18")
    payload = """{
  "question_summary": "新定义数列综合求值",
  "analysis_facts": {
    "core_task": "理解新定义后结合多个知识关系求解",
    "core_knowledge_points": ["数列", "绝对值", "分式"],
    "core_methods": ["整体代换"],
    "visual_elements": [],
    "fact_basis": "题面明确给出新定义和多条约束",
    "image_used": 0,
    "has_sub_items": 0
  },
  "applicable_dimensions": ["dim5"],
  "features": {
    "dim1_computation": {},
    "dim2_spatial": {},
    "dim3_information": {},
    "dim4_innovation": {},
    "dim5_knowledge": {
      "band": "4年级及以前校内课本难度",
      "sublevel": "low",
      "evidence_summary": "核心知识单元和整合信号明显偏高。",
      "knowledge_tags": ["数列", "新定义"],
      "core_knowledge_units": ["数列", "绝对值", "分式"],
      "supporting_knowledge_units": ["整体代换"],
      "knowledge_family_count": "3+",
      "knowledge_integration": "cross_domain_bridge",
      "novel_definition_dependency": "strong",
      "competition_signal": "strong",
      "applicability_confidence": 0.86,
      "warning": ""
    },
    "dim6_logic": {}
  },
  "confidence": 0.8,
  "reasoning": "题目门槛不是单一课内知识。"
}"""

    features = asyncio.run(parser._parse_response_with_repairs(payload, question))

    assert features.parse_failed is False
    assert features.need_manual_review is True
    assert any(item.startswith("dim5 ") for item in features.warnings)


def test_parse_response_repairs_with_llm_fallback():
    repaired_response = valid_payload("判断统计图类型")
    fake_llm = FakeLLM(responses=[repaired_response])
    parser = make_parser(fake_llm)
    question = make_question("14")
    broken_response = """{
  "question_summary": "判断哪种统计图既能反映增减变化又能反映数据多少"
  "analysis_facts": {
    "core_task": "从四个选项中选择统计图类型",
    "core_knowledge_points": ["统计图的特点"],
    "core_methods": ["比较特征"],
    "visual_elements": [],
    "fact_basis": "题面给出选项",
    "image_used": 0,
    "has_sub_items": 0
  },
  "applicable_dimensions": ["dim5"],
  "features": {
    "dim1_computation": {},
    "dim2_spatial": {},
    "dim3_information": {},
    "dim4_innovation": {},
    "dim5_knowledge": {
      "band": "4年级及以前校内课本难度",
      "sublevel": "low",
      "evidence_summary": "考查统计图特点",
      "knowledge_tags": ["统计图"],
      "applicability_confidence": 0.8,
      "warning": ""
    },
    "dim6_logic": {}
  },
  "confidence": 0.72,
  "reasoning": "需要识别不同统计图的特点。"
}"""

    features = asyncio.run(parser._parse_response_with_repairs(broken_response, question))

    assert features.parse_failed is False
    assert features.json_repair_status == JSON_REPAIR_STATUS_LLM
    assert "LLM JSON 已二次修复" in features.warnings
    assert features.need_manual_review is True
    assert len(fake_llm.calls) == 1
    assert fake_llm.calls[0]["kwargs"]["response_format"] == {"type": "json_object"}


def test_parse_response_marks_failed_when_all_repairs_fail():
    fake_llm = FakeLLM(responses=['{"broken": '])
    parser = make_parser(fake_llm)
    question = make_question("21")
    broken_response = """{
  "question_summary": "定义新运算"数列价值""
  "analysis_facts": {"core_task": "理解定义"}
}"""

    features = asyncio.run(parser._parse_response_with_repairs(broken_response, question))

    assert features.parse_failed is True
    assert features.json_repair_status == JSON_REPAIR_STATUS_FAILED
    assert "LLM JSON 修复失败" in features.warnings


def test_moonshot_client_retries_without_response_format(monkeypatch):
    client = MoonshotClient(
        api_key="test-key",
        model="test-model",
        base_url="https://example.com/v1",
    )
    payloads = []

    async def fake_post(payload):
        payloads.append(payload)
        if len(payloads) == 1:
            request = httpx.Request("POST", "https://example.com/v1/chat/completions")
            response = httpx.Response(
                400,
                request=request,
                text='{"error":{"message":"response_format is not supported"}}',
            )
            raise httpx.HTTPStatusError("unsupported", request=request, response=response)
        return {
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        }

    monkeypatch.setattr(client, "_post_chat_completion", fake_post)

    content = asyncio.run(
        client.chat(
            messages=[{"role": "user", "content": "hello"}],
            response_format={"type": "json_object"},
        )
    )

    assert content == '{"ok": true}'
    assert len(payloads) == 2
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in payloads[1]
