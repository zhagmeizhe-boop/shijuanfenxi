"""
AI 题目解析服务。

当前实现重点：
- 先抽 facts，再解析六维 judgement
- dim1 / dim2 / dim3 仅抽取可审计事实，只有 dim5 继续走参考体系校正
- 多模态失败、JSON 截断、关键字段缺失时显式转入低置信复核路径
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from app.core.config import settings
from app.services.llm.moonshot_client import MoonshotClient
from app.services.ocr.base import ParsedPaper, ParsedQuestion, QuestionType
from app.services.parser.prompts import (
    QUESTION_ANALYSIS_SYSTEM_PROMPT,
    QUESTION_ANALYSIS_USER_PROMPT_TEMPLATE,
)
from app.services.parser.dim5_grounding import (
    DIM5_GROUNDING_VERSION,
    GROUNDING_USE_CONFIDENCE_THRESHOLD,
    Dim5KnowledgeGroundingService,
)
from app.services.parser.dim5_knowledge_graph import (
    Dim5KnowledgeGraphMatcher,
    get_dim5_knowledge_graph_matcher,
)
from app.services.parser.dim5_retrieval import Dim5RetrievalService
from app.services.parser.reference_standard import get_reference_standard
from app.services.scoring.banded_dimension import BAND_SCORE_MAP, _normalize_band, _normalize_sublevel
from app.services.scoring.dim5_canonical import canonicalize_dim5_knowledge, normalize_dim5_knowledge_level
from app.services.scoring.dim4_topic_levels import (
    DIM4_LEVEL_SOURCE_VALUES,
    classify_dim4_topic_level,
    normalize_dim4_level,
    normalize_dim4_level_source,
)

logger = logging.getLogger(__name__)

QUESTION_PARSE_TIMEOUT_SECONDS = 75.0


VISUAL_SIGNAL_PATTERN = re.compile(
    r"(?:如图|下图|下表|统计图|折线图|柱状图|扇形图|表格|三角形|长方形|正方形|圆|圆柱|圆锥|展开图|截面|蝴蝶模型|燕尾模型|一半模型|鸟头|沙漏|割补|等高|共边|格点|三视图|水中浸物|长度计算|角度计算|图形变换)"
)
DIM2_TEXT_SIGNAL_PATTERN = re.compile(
    r"(?:如图|下图|三角形|长方形|正方形|平行四边形|梯形|圆|扇形|立方体|正方体|长方体|圆柱|圆锥|展开图|截面|视图|辅助线|折叠|旋转|平移|对称|蝴蝶模型|燕尾模型|一半模型|鸟头|沙漏|割补|等高|共边|面积比|格点|三视图|水中浸物|长度计算|角度计算|标向|多边形内角和|图形变换)"
)
DIM2_SHORT_GEOMETRY_IMAGE_PATTERN = re.compile(
    "(?:S\\s*\u9634|S\u9634\u5f71|\u9634\u5f71(?:\u90e8\u5206)?(?:\u9762\u79ef)?|"
    "\u5706\u5185\u6700\u5927\u6b63\u65b9\u5f62|\u5185\u63a5\u6b63\u65b9\u5f62|"
    "\u9732\u5728\u5916\u9762\u7684\u9762\u79ef|\u5982\u56fe.*\u6c42\u9762\u79ef|"
    "\u56fe\u4e2d.*\u6c42\u9762\u79ef|\u6c42\\s*S)"
)
DIMENSION_FEATURE_KEYS = {
    "dim1": "dim1_computation",
    "dim2": "dim2_spatial",
    "dim3": "dim3_information",
    "dim4": "dim4_innovation",
    "dim5": "dim5_knowledge",
    "dim6": "dim6_logic",
}
DEFAULT_JSON_RESPONSE_FORMAT = {"type": "json_object"}
JSON_RESPONSE_HEAD_LIMIT = 240
JSON_REPAIR_STATUS_DIRECT = "direct_json_ok"
JSON_REPAIR_STATUS_LOCAL = "local_json_repair_ok"
JSON_REPAIR_STATUS_LLM = "llm_json_repair_ok"
JSON_REPAIR_STATUS_FAILED = "json_repair_failed"
DIM1_TASK_FORM_VALUES = {"explicit", "embedded"}
DIM1_CALC_ROLE_VALUES = {"none", "supporting", "core"}
DIM1_CALC_BUCKET_VALUES = {"pure_calculation", "embedded_calculation"}
DIM1_STEP_CHAIN_VALUES = {"1", "2", "3-4", "5+"}
DIM1_NUMBER_MIX_VALUES = {"plain", "standard", "mixed", "symbolic"}
DIM1_ROUTINE_TRANSFORM_VALUES = {"0", "1", "2", "3+"}
DIM1_STRUCTURAL_METHOD_VALUES = {"none", "shortcut", "olympiad"}
DIM1_ERROR_PRESSURE_VALUES = {"low", "medium", "high"}
DIM1_EMBEDDED_COUNT_VALUES = {"0", "1", "2", "2+", "3+"}
DIM1_CALC_SUBTYPE_VALUES = {
    "arithmetic",
    "equation",
    "proportion_equation",
    "defined_operation",
    "factorial_ratio",
    "fraction_comparison",
    "sequence_series",
    "nested_fraction",
    "structural_identity",
    "pattern_computation",
}
DIM1_STRUCTURE_PATTERN_VALUES = {
    "grouping",
    "common_factor",
    "decimal_scaling",
    "fraction_decimal_percent_conversion",
    "reciprocal_conversion",
    "factorial_cancellation",
    "defined_rule_expansion",
    "telescoping",
    "symmetric_cancellation",
    "recursive_product",
    "continued_fraction",
    "sequence_generalization",
}
DIM1_TERM_COUNT_BAND_VALUES = {"1-2", "3-5", "6-10", "11+"}
DIM1_SYMBOLIC_DEPENDENCY_VALUES = {"none", "single_unknown", "multi_unknown", "parameterized"}
DIM1_REVIEW_CONFIDENCE_THRESHOLD = 0.5
DIM2_TASK_FORM_VALUES = {"nonvisual", "explicit_visual", "geometry_embedded", "text_only_geometry"}
DIM2_SPATIAL_ROLE_VALUES = {"none", "supporting", "core"}
DIM2_FIGURE_COMPLEXITY_VALUES = {
    "none",
    "basic_2d",
    "composite_2d",
    "solid_3d",
    "net_section_multi_view",
}
DIM2_RELATION_HOPS_VALUES = {"1", "2", "3-4", "5+"}
DIM2_HIDDEN_RELATION_COUNT_VALUES = {"0", "1", "2+"}
DIM2_VISUAL_OPERATION_COUNT_VALUES = {"0", "1", "2", "3+"}
DIM2_STRUCTURAL_VISUAL_METHOD_VALUES = {"none", "decomposition", "auxiliary_line", "3d_transform"}
DIM2_MEASUREMENT_DEPENDENCY_VALUES = {"none", "direct", "inferred"}
DIM2_IMAGE_DEPENDENCY_VALUES = {"none", "helpful", "required"}
DIM2_GEOMETRY_MODEL_TYPE_VALUES = {
    "basic_area_formula",
    "reverse_area_edge",
    "butterfly_area",
    "swallowtail_area",
    "half_area",
    "equal_height_area",
    "shared_base_area",
    "equal_area_transform",
    "kite_area",
    "bird_head_sandglass",
    "pyramid_sandglass",
    "cut_and_fill",
    "grid_cut_fill",
    "auxiliary_parallel",
    "area_ratio_chain",
    "composite_area_model",
    "circle_sector_formula",
    "circle_sector_cut_fill",
    "rolling_rotation",
    "solid_formula",
    "water_displacement",
    "surface_three_view",
    "net_cut_join",
    "solid_cut_join",
    "length_translation",
    "directed_length",
    "angle_chasing_triangle",
    "angle_chasing_polygon",
    "polygon_angle_sum",
    "figure_transformation",
    "opposite_faces",
    "geometric_counting",
}
DIM2_GEOMETRY_MODEL_COUNT_VALUES = {"0", "1", "2", "3+"}
DIM2_MODEL_RECOGNITION_ROLE_VALUES = {"none", "supporting", "core"}
DIM2_AREA_RELATION_CHAIN_VALUES = {"none", "single", "multi", "nested"}
DIM2_MODEL_COMBINATION_COMPLEXITY_VALUES = {
    "none",
    "single_model",
    "model_plus_operation",
    "multi_model",
    "nested_model",
}
DIM2_LOW_BARRIER_GEOMETRY_MODEL_TYPES = {
    "basic_area_formula",
    "circle_sector_formula",
    "solid_formula",
    "polygon_angle_sum",
    "opposite_faces",
}
DIM2_REVIEW_CONFIDENCE_THRESHOLD = 0.55
DIM2_GEOMETRY_VISUAL_CATEGORIES = {"geometry_visual", "geometry_context", "spatial_3d", "explicit_visual"}
DIM3_INFORMATION_ROLE_VALUES = {"none", "supporting", "core"}
DIM3_SOURCE_FORM_VALUES = {"text_only", "table_chart", "image_text", "multi_source"}
DIM3_RELEVANT_CONDITION_COUNT_VALUES = {"1-2", "3-4", "5-6", "7+"}
DIM3_DISTRACTOR_PRESSURE_VALUES = {"none", "light", "heavy"}
DIM3_CONDITION_DISTRIBUTION_VALUES = {"compact", "split", "cross_sentence", "cross_modal"}
DIM3_SCENARIO_COMPREHENSION_LOAD_VALUES = {"none", "light", "medium", "heavy"}
DIM3_EXTRACTION_DEPTH_VALUES = {"direct", "selected", "reorganized", "inferred"}
DIM3_REPRESENTATION_CONVERSION_VALUES = {
    "none",
    "direct_mapping",
    "relation_mapping",
    "model_mapping",
    "custom_model",
}
DIM3_CONVERSION_STEP_COUNT_VALUES = {"0", "1", "2", "3+"}
DIM3_QUANTITY_RELATION_STRUCTURE_VALUES = {"none", "single_relation", "multi_relation", "nested_relation"}
DIM3_TARGET_REPRESENTATION_VALUES = {
    "none",
    "direct_formula",
    "table_list",
    "equation_relation",
    "custom_model",
}
DIM3_IMAGE_DEPENDENCY_VALUES = {"none", "helpful", "required"}
DIM3_REVIEW_CONFIDENCE_THRESHOLD = 0.55
DIM3_VISUAL_CATEGORIES = {"table_chart", "multi_part_layout"}
DIM3_APPLICATION_RELATION_TYPE_VALUES = {
    "work_rate",
    "queue_growth",
    "percentage_base_change",
    "concentration_mixture",
    "profit_discount",
    "ratio_allocation",
    "travel_meeting_chasing",
    "chart_table_conversion",
    "average_total",
    "equation_setup",
    "reverse_process",
    "cycle_period",
    "optimization_comparison",
    "multi_object_distribution",
    "conservation_transfer",
    "range_narrowing",
}
DIM3_OBJECT_COUNT_BAND_VALUES = {"1", "2", "3", "4+"}
DIM3_APPLICATION_COUNT_VALUES = {"0", "1", "2", "3+"}
DIM3_BASE_QUANTITY_SHIFT_VALUES = {"none", "single", "multiple"}
DIM3_COMPARISON_CANDIDATE_COUNT_VALUES = {"0", "2", "3+"}
DIM3_SCENARIO_RULE_COUNT_VALUES = {"0", "1", "2", "3+"}
DIM3_PROCESS_STAGE_COUNT_VALUES = {"1", "2", "3", "4+"}
DIM3_FEEDBACK_MECHANISM_VALUES = {"none", "simple", "conditional"}
DIM3_COMPARISON_BASIS_VALUES = {"none", "direct", "implicit", "multi_condition"}
DIM3_DIAGRAM_CORRESPONDENCE_VALUES = {"none", "helpful", "required", "multi_step"}
DIM3_SCENARIO_RULE_TYPE_VALUES = {
    "sequence_order",
    "comparison_basis",
    "feedback_rule",
    "conditional_trigger",
    "diagram_mapping",
    "multi_object_roles",
    "multi_stage_process",
    "custom_rule_system",
}
DIM4_STRATEGY_ROLE_VALUES = {"none", "supporting", "core"}
DIM4_TEMPLATE_FIT_VALUES = {"direct", "adapted", "reframed", "non_routine"}
DIM4_BREAKTHROUGH_TYPE_VALUES = {
    "none",
    "local_trick",
    "strategy_shift",
    "constructive",
    "exploratory_search",
}
DIM4_STRATEGY_SHIFT_COUNT_VALUES = {"0", "1", "2", "3+"}
DIM4_CONSTRUCTION_REQUIREMENT_VALUES = {
    "none",
    "simple_setup",
    "case_construction",
    "custom_construction",
}
DIM4_EXPLORATION_SPACE_VALUES = {"none", "bounded", "branched", "open"}
DIM4_REPRESENTATION_REFRAME_VALUES = {"none", "minor", "structural", "creative"}
DIM4_TRANSFER_DISTANCE_VALUES = {"near", "medium", "far"}
DIM4_PATH_OPENNESS_VALUES = {"single", "multiple_paths", "multiple_answers"}
DIM4_DEAD_END_RISK_VALUES = {"low", "medium", "high"}
DIM4_IMAGE_DEPENDENCY_VALUES = {"none", "helpful", "required"}
DIM4_TOPIC_LEVEL_VALUES = {"L1", "L2", "L3", "L4", "L5"}
DIM4_REVIEW_CONFIDENCE_THRESHOLD = 0.55
DIM4_STRATEGY_SIGNAL_PATTERN = re.compile(
    r"(构造|设计|试一试|找规律|逆向|倒推|换一种|至少有几种|最多有几种|分类|枚举|探索|尝试|不同方案|多种方法|"
    r"博弈|必胜|必败|对称策略|抽屉|容斥|同余|不变量|染色|反例|唯一性|约束回查|候选比较|反向整理|"
    r"有限枚举|几何割补|辅助线|面积比链|极值构造|定义新运算|规定一种运算|非相邻裂项|长链消去|首尾项提取|"
    r"参数无关|无关量消去|位置耦合|概率分母|总量转化|制胜策略)"
)
DIM4_TOPIC_FALLBACK_SYSTEM_PROMPT = """
You only classify dim4 practice innovation inside one elementary math knowledge point.
Return exactly one JSON object. Do not solve the problem.
Judge the question's L1-L5 level inside the given knowledge point only.
Do not use knowledge breadth, grade band, contest source, calculation workload, or long text to raise dim4.
"""
DIM4_TOPIC_FALLBACK_USER_PROMPT_TEMPLATE = """
Question metadata:
- question_no: {question_no}
- question_type: {question_type}
- candidate_knowledge_point: {knowledge_point}

Question text:
{question_text}

Initial analysis facts:
{analysis_facts_json}

Initial dim4_innovation:
{dim4_feature_json}

Local GaoSi question-bank candidates:
{reference_candidates_json}

Use this topic-internal scale:
- L1: base template of this knowledge point, direct method
- L2: light variant only, such as small wording, unit, object-name, or condition-order changes where the same template still applies directly
- L3: single variant recognition or single transformation only, such as one base-quantity shift, one phase/role change, one post-meeting travel change, one geometry-model recognition, simple reverse reasoning, or simple candidate screening; after recognition the solution path is basically clear
- L4: stronger but still common elementary entrance-exam variant: one L3-level signal plus organization/construction/back-check/comparison, or two or more L3-level signals combined; examples include base shift plus reverse profit organization, candidate screening plus constraint back-check, geometry model plus cut-fill/auxiliary-line/area-ratio chain, post-meeting change plus waiting/turning, finite enumeration with verification, or construction of an intermediate quantity
- L5: capstone innovation inside this knowledge point, requiring global design, multiple strategies, open exploration, or strong constraint closure

If a local candidate is exact/near_exact or high_similarity, use it as a same-topic anchor. Do not copy GaoSi section level directly as dim4 level; judge the question's L1-L5 variant level inside the knowledge point.
Non-contest questions may still be L4 when the innovation burden is caused by variant recognition followed by organization, reverse organization, bounded classification with back-check, plan comparison, finite enumeration with verification, geometry-model follow-up restructuring, or intermediate construction. A question should not remain L3 if a single recognized variant must still be organized into a strategy path, and it should not remain L2 once it requires a new representation, reverse organization, candidate screening, or an intermediate construction. Do not raise a direct formula/template problem.
Treat these as L4-or-higher evidence when they are genuine topic-internal burdens: custom operation structure expansion, non-adjacent telescoping, long-chain cancellation with first/last term extraction, difference/increment reasoning with parameter irrelevance, multi-state percentage/profit base switching, coupled position enumeration with divisibility constraints, probability denominator construction, or multiple part-to-rest ratios converted through a shared total. For game strategy, use L5 only when the reason includes global winning-strategy verification such as opponent response, winning-state back-check, or guaranteed win.

Return strict JSON with exactly these keys:
{{
  "knowledge_point": "specific knowledge point",
  "topic_level": "L1|L2|L3|L4|L5",
  "anchor_evidence": "short reason comparing the question to the topic-internal scale",
  "confidence": 0.0
}}
"""
DIM_SECOND_REVIEW_SYSTEM_PROMPT = """
你是一位小学数学教研复评专家。你只复评一个指定维度是否稳定适用以及 L1-L5 等级。
不要完整解题，不要使用试卷名称、WMO、竞赛、省测、高思等来源标签抬分。
使用小学数学表述，不使用算法、信息论、搜索模型等专业术语。
只返回一个 JSON 对象。
"""
DIM_SECOND_REVIEW_USER_PROMPT_TEMPLATE = """
请对下面题目的 {dimension_name} 做二次复评。

题号：{question_no}
OCR识别题型：{question_type}
是否提供题块图片：{has_image}
OCR警告：{ocr_warnings}
解析审计：{parse_audit_summary}

题目原文：
{question_text}

初评可验证事实：
{analysis_facts_json}

初评该维度字段：
{initial_feature_json}

初评适用性结论：
{initial_status_json}

复评口径：
{dimension_criteria}

等级规则：
{level_rules}

输出要求：
- status 只能是 "applicable" / "not_applicable" / "unresolved"。
- applicable 时必须给出 level=L1-L5，score 必须对应 L1=2.0、L2=4.0、L3=6.0、L4=8.0、L5=9.5。
- not_applicable 表示复评确认该维度没有真实负担，score=0.0，level="N/A"。
- unresolved 表示题面、图文或字段仍无法稳定判断，score=0.0，level="N/A"，后续会舍弃该题该维度。
- evidence_summary 只写题目事实，不写“因为是竞赛卷所以难”。
- confidence 是 0-1 小数；低于 0.55 时请返回 unresolved。

严格返回如下 JSON：
{{
  "status": "applicable|not_applicable|unresolved",
  "level": "L1|L2|L3|L4|L5|N/A",
  "score": 0.0,
  "evidence_summary": "一句小学数学语言的事实依据",
  "confidence": 0.0,
  "exclude_reason": "不适用或无法稳定判断时填写"
}}
"""
DIM5_SUBLEVEL_VALUES = {"low", "mid", "high"}
DIM5_KNOWLEDGE_FAMILY_COUNT_VALUES = {"1", "2", "3+"}
DIM5_KNOWLEDGE_INTEGRATION_VALUES = {
    "single",
    "same_family_combo",
    "cross_family_combo",
    "cross_domain_bridge",
}
DIM5_NOVEL_DEFINITION_DEPENDENCY_VALUES = {"none", "local", "strong"}
DIM5_COMPETITION_SIGNAL_VALUES = {"none", "weak", "strong"}
DIM5_VISUAL_DEPENDENCY_VALUES = {"none", "helpful", "required"}
DIM5_GAOSI_SECTION_LEVEL_LABELS = {
    "interest": "兴趣篇",
    "extension": "拓展篇",
    "challenge": "超越篇",
}
DIM5_GAOSI_CLASSIFICATION_SOURCE_VALUES = {
    "question_bank",
    "knowledge_base",
    "llm_retry",
}
DIM5_LOW_GAOSI_BAND = "4年级及以前高思导引拓展篇及以下难度"
DIM5_HIGH_GAOSI_BAND = "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度"
DIM5_BEYOND_BAND = "高思导引超越篇难度"
DIM5_REVIEW_CONFIDENCE_THRESHOLD = 0.55
DIM5_RELIABLE_BAND_SOURCES = {
    "question_bank",
    "knowledge_anchor",
    "topic_structure_match",
    "rule_corrected",
    "rule_corrected_with_review",
    "llm_dim5_retry",
    "gaosi_section_override",
}
DIM5_DIRECT_FORMULA_RETRY_BLOCK_PATTERN = re.compile(
    r"(?:直接公式|普通公式|直接代入|套用公式|长方形面积|三角形面积|圆(?:的)?面积|扇形面积|"
    r"圆柱(?:和圆锥)?体积|圆锥体积|体积比|百分数直接应用|直接百分数)"
)
DIM5_OLYMPIAD_ANCHOR_PATTERN = re.compile(
    r"(?:定义新运算|规定一种运算|裂项|长链消去|递推|差分|抽屉|组合计数|容斥|博弈|"
    r"必胜|不变量|同余|整除约束|极值构造|规则反推|牛吃草|复杂几何|几何割补|"
    r"面积比链|蝴蝶模型|燕尾模型|鸟头|沙漏|奥数|竞赛备考|压轴)"
)
DIM5_BAND_RETRY_SYSTEM_PROMPT = """
You only classify the knowledge-breadth band for one elementary math question.
Return exactly one JSON object. Do not solve the problem.
Only judge the minimum sufficient knowledge level required by the question.
Do not use calculation workload, reasoning chain length, strategy novelty, or overall problem difficulty to raise dim5.
If the question belongs to GaoSi Guide / olympiad / contest-prep / final-challenge style, normalize it as a school grade, olympiad grade, or seventh-grade prerequisite threshold.
Do not map "olympiad", "contest-prep", "GaoSi challenge", or "final challenge" directly to L5; L5 requires hard variant, final-challenge structure, multi-condition coupling, complex case analysis, hidden structure, reverse checking, or a seventh-grade core threshold.
Treat explicit core knowledge anchors such as defined operations, telescoping cancellation, recurrence/difference, pigeonhole principle, combinatorics, game winning strategy, invariant, modular arithmetic, extremal construction, complex geometric cut-and-fill, and rule reverse-engineering as olympiad candidates. Use them to decide between L3/L4/L5 only when the question text or local candidates support that threshold.
"""
DIM5_BAND_RETRY_USER_PROMPT_TEMPLATE = """
Question metadata:
- question_no: {question_no}
- question_type: {question_type}
- has_image: {has_image}

Question text:
{question_text}

Initial analysis facts:
{analysis_facts_json}

Initial dim5_knowledge:
{dim5_feature_json}

If canonical_knowledge_point/canonical_knowledge_family are present in Initial dim5_knowledge, treat them as the normalized knowledge anchor. Use that anchor before relying on free-form knowledge wording.

Local reference candidates:
{reference_candidates_json}

Choose exactly one band from this list:
{band_values_json}

If the question should be classified into GaoSi Guide, also choose:
- gaosi_grade: "3"|"4"|"5"|"6" when supported by candidates or the question; otherwise ""
- gaosi_section_level: "interest"|"extension"|"challenge"
- gaosi_section_label: "兴趣篇"|"拓展篇"|"超越篇"

Knowledge-level rule:
- L1: one-to-three-grade school basics.
- L2: four-to-six-grade school core knowledge.
- L3: school synthesis or grade 3/4 olympiad entry models.
- L4: grade 5/6 olympiad typical topics or light seventh-grade prerequisite.
- L5: hard grade 6 olympiad variants, xiaoshengchu final-challenge problems, multi-condition/hidden/reverse-checking structures, or seventh-grade core threshold.

GaoSi section labels are audit fields, not final scoring rules:
- 兴趣篇 usually supports L3 when the actual structure is entry-level.
- 拓展篇 usually supports L3/L4 depending on grade and structure.
- 超越篇 supports L5 only with strong question-level match or hard-structure evidence.

WMO/contest-style knowledge anchors:
- 定义新运算、裂项/长链消去、差分/递推、抽屉、组合计数、博弈必胜、不变量、同余、极值构造、复杂几何割补、规则反推 should usually be classified as olympiad L4 or L5 candidates rather than ordinary school textbook knowledge.
- Direct textbook formula problems, direct percentage applications, and direct cylinder/cone volume-ratio problems must stay in the school band unless a concrete GaoSi question-level candidate or a genuinely advanced knowledge structure supports a higher band.
- Do not use a contest name, file title, or general "olympiad" wording alone to choose challenge/beyond/L5.
- Use medium-relaxed judgement: when a concrete olympiad knowledge point or topic+structure candidate is present, do not keep the question in ordinary school band solely because the original analysis was conservative.

Return strict JSON with exactly these keys:
{{
  "gaosi_grade": "",
  "gaosi_section_level": "",
  "gaosi_section_label": "",
  "band": "one value from the band list",
  "sublevel": "low|mid|high",
  "evidence_summary": "short reason based only on core knowledge threshold",
  "knowledge_tags": ["specific knowledge tags"],
  "core_knowledge_units": ["specific core knowledge units"],
  "primary_knowledge_point": "one most important knowledge point",
  "confidence": 0.0
}}
"""
DIM5_RETRY_LOW_CONFIDENCE_THRESHOLD = 0.55
DIM5_GROUNDED_SELECTION_SYSTEM_PROMPT = """
You are a constrained selector for dimension-5 math knowledge points.
You must choose from the provided knowledge candidates only, or return no_match.
Do not rewrite dim1, dim2, dim3, dim4, or dim6.
Use the original question text first. analysis_facts are only supporting evidence.
If a candidate is marked analysis_facts_only, it cannot be selected with high confidence unless the original question text also supports it.
Return strict JSON only.
"""
DIM5_GROUNDED_SELECTION_USER_PROMPT_TEMPLATE = """
Question metadata:
- question_no: {question_no}
- question_type: {question_type}

Question text:
{question_text}

Neutral analysis_facts:
{analysis_facts_json}

Knowledge candidates:
{candidates_json}

Choose exactly one:
- candidate_id from the candidates
- or "no_match"

Return JSON with exactly these keys:
{{
  "selected_candidate_id": "candidate_id or no_match",
  "confidence": 0.0,
  "evidence": "quote or paraphrase question-text evidence",
  "rejected_candidates": [
    {{"candidate_id": "id", "reason": "why it is not the best match"}}
  ]
}}
"""
DIM6_REASONING_ROLE_VALUES = {"none", "supporting", "core"}
DIM6_CHAIN_SPAN_VALUES = {"1", "2", "3-4", "5+"}
DIM6_HIDDEN_DEPENDENCY_VALUES = {"none", "local", "cross_condition", "global"}
DIM6_BRANCH_CONTROL_VALUES = {"none", "explicit_cases", "multi_branch"}
DIM6_REVERSIBILITY_VALUES = {"none", "backward", "bidirectional"}
DIM6_VERIFICATION_REQUIREMENT_VALUES = {
    "none",
    "result_check",
    "constraint_backcheck",
    "full_consistency",
}
DIM6_ABSTRACTION_BRIDGE_COUNT_VALUES = {"0", "1", "2", "3+"}
DIM6_CONSTRAINT_COUPLING_VALUES = {"none", "single", "coupled", "nested"}
DIM6_CONCLUSION_STABILITY_VALUES = {"direct", "edge_sensitive", "exhaustive"}
DIM6_LOGIC_STRUCTURE_TYPE_VALUES = {
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
DIM6_STATE_TRANSITION_COUNT_VALUES = {"0", "1", "2", "3+"}
DIM6_CASE_COUNT_BAND_VALUES = {"none", "2", "3-5", "6+"}
DIM6_BACKTRACK_DEPTH_VALUES = {"0", "1", "2", "3+"}
DIM6_CONSISTENCY_CONSTRAINT_COUNT_VALUES = {"0", "1", "2-3", "4+"}
DIM6_PHASE_COUNT_BAND_VALUES = {"1", "2", "3-4", "5+"}
DIM6_OPTIMIZATION_REQUIREMENT_VALUES = {"none", "bounded_choice", "global_minmax"}
DIM6_REVIEW_CONFIDENCE_THRESHOLD = 0.55
DIM6_LOGIC_SIGNAL_PATTERN = re.compile(
    r"(分类|分别|讨论|所有可能|符合条件|至少|至多|检验|验证|回查|是否成立|几种不同铺法|"
    r"最少|最小|最大|最优|相遇后|追上|同时到达|每分钟来的|换班|第\d+次|倒回|还原|"
    r"按顺序|周期|循环|增长|排队|检票|调头|往返)"
)

STRICT_JSON_OUTPUT_INSTRUCTIONS = """
Strict JSON output rules:
- Return exactly one JSON object.
- Do not use Markdown fences such as ```json.
- Inside string values, never use raw ASCII double quotes as quotation marks copied from the question text.
- If quotation marks are needed inside string values, use Chinese quotation marks or escaped quotes.
- The response must be parseable by Python json.loads directly.
"""

JSON_REPAIR_SYSTEM_PROMPT = """
You repair malformed JSON only.
Do not re-analyze the question.
Do not add or remove semantic content unless needed to make the JSON valid.
Return exactly one valid JSON object and nothing else.
"""

JSON_REPAIR_SCHEMA_HINT = """
Required top-level keys:
- question_summary: string
- analysis_facts: object
- applicable_dimensions: array
- features: object
- confidence: number
- reasoning: string
"""

JSON_REPAIR_USER_PROMPT_TEMPLATE = """Fix the malformed JSON below.

Rules:
- Preserve the original meaning and field names.
- Only repair JSON syntax and obvious escaping issues.
- Keep the object shape aligned with this schema hint:
{schema_hint}

Original parse error:
{parse_error}

Broken JSON:
{broken_json}
"""


@dataclass
class QuestionFeatures:
    """题目的六维特征数据。"""

    question_id: str
    question_no: str
    question_summary: str
    analysis_facts: Dict[str, Any] = field(default_factory=dict)
    applicable_dimensions: List[str] = field(default_factory=list)

    dim1_computation: Dict[str, Any] = field(default_factory=dict)
    dim2_spatial: Dict[str, Any] = field(default_factory=dict)
    dim3_information: Dict[str, Any] = field(default_factory=dict)
    dim4_innovation: Dict[str, Any] = field(default_factory=dict)
    dim5_knowledge: Dict[str, Any] = field(default_factory=dict)
    dim6_logic: Dict[str, Any] = field(default_factory=dict)

    confidence: float = 0.0
    reasoning: str = ""
    warnings: List[str] = field(default_factory=list)
    need_manual_review: bool = False
    visual_mode: str = "text_only"
    used_image: bool = False
    image_fallback: bool = False
    calibration_audits: Dict[str, Any] = field(default_factory=dict)
    parse_failed: bool = False
    json_repair_status: str = JSON_REPAIR_STATUS_DIRECT

    def get_feature(self, dim_code: str) -> Dict[str, Any]:
        feature_map = {
            "dim1": self.dim1_computation,
            "dim2": self.dim2_spatial,
            "dim3": self.dim3_information,
            "dim4": self.dim4_innovation,
            "dim5": self.dim5_knowledge,
            "dim6": self.dim6_logic,
        }
        return feature_map.get(dim_code, {})


class AIParser:
    """调用 LLM 进行题级六维分析。"""

    def __init__(self, llm_client: Optional[MoonshotClient] = None):
        self.llm = llm_client or self._create_default_client()
        self.reference_standard = get_reference_standard()
        self.dim5_retrieval = Dim5RetrievalService(self.reference_standard)
        self.dim5_grounding = Dim5KnowledgeGroundingService(self.reference_standard)
        self.dim5_graph_matcher = get_dim5_knowledge_graph_matcher()
        logger.info("AIParser 初始化完成")

    def _create_default_client(self) -> MoonshotClient:
        return MoonshotClient(
            model="kimi-k2.5",
            temperature=0.3,
            max_tokens=2800,
        )

    @staticmethod
    def _normalize_feature_dict(value: Any) -> Dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _normalize_analysis_facts(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {}

        facts = {
            "core_task": str(value.get("core_task", "")).strip(),
            "core_knowledge_points": [],
            "core_methods": [],
            "visual_elements": [],
            "fact_basis": str(value.get("fact_basis", "")).strip(),
            "image_used": 1 if value.get("image_used") in (1, True) else 0,
            "has_sub_items": 1 if value.get("has_sub_items") in (1, True) else 0,
        }

        for key in ("core_knowledge_points", "core_methods", "visual_elements"):
            raw = value.get(key, [])
            if isinstance(raw, list):
                facts[key] = [str(item).strip() for item in raw if str(item).strip()]
        return facts

    @staticmethod
    def _feature_confidence(feature: Dict[str, Any]) -> float:
        try:
            return float(feature.get("applicability_confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _normalize_choice(value: Any, allowed: set[str]) -> str:
        normalized = str(value or "").strip().lower()
        return normalized if normalized in allowed else ""

    @staticmethod
    def _normalize_gaosi_grade(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        arabic = re.search(r"([1-9])\s*年级?", text)
        if arabic:
            return arabic.group(1)
        if text in {"1", "2", "3", "4", "5", "6", "7", "8", "9"}:
            return text
        chinese_map = {
            "一": "1",
            "二": "2",
            "三": "3",
            "四": "4",
            "五": "5",
            "六": "6",
            "七": "7",
            "八": "8",
            "九": "9",
        }
        chinese = re.search(r"([一二三四五六七八九])年级?", text)
        if chinese:
            return chinese_map[chinese.group(1)]
        return ""

    @staticmethod
    def _normalize_gaosi_section_level(value: Any) -> str:
        text = str(value or "").strip()
        lowered = text.lower()
        if lowered in DIM5_GAOSI_SECTION_LEVEL_LABELS:
            return lowered
        reverse = {label: level for level, label in DIM5_GAOSI_SECTION_LEVEL_LABELS.items()}
        return reverse.get(text, "")

    @classmethod
    def _normalize_gaosi_section_label(cls, value: Any) -> str:
        level = cls._normalize_gaosi_section_level(value)
        return DIM5_GAOSI_SECTION_LEVEL_LABELS.get(level, "")

    @staticmethod
    def _dim5_gaosi_band_and_sublevel(grade: str, section_level: str) -> Tuple[str, str]:
        if section_level == "challenge":
            return DIM5_BEYOND_BAND, "high"
        if section_level == "interest":
            sublevel = "low"
        elif section_level == "extension":
            sublevel = "mid"
        else:
            return "", ""

        try:
            grade_no = int(grade)
        except (TypeError, ValueError):
            return "", ""
        band = DIM5_LOW_GAOSI_BAND if grade_no <= 4 else DIM5_HIGH_GAOSI_BAND
        return band, sublevel

    @staticmethod
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

    @staticmethod
    def _normalize_zero_one(value: Any) -> int | str:
        if value in (0, "0", False):
            return 0
        if value in (1, "1", True):
            return 1
        return ""

    @staticmethod
    def _normalize_string_list(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _normalize_dict_list(value: Any) -> List[Dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value if isinstance(item, dict)]

    @staticmethod
    def _normalize_optional_dict(value: Any) -> Dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _normalize_confidence(value: Any) -> float:
        try:
            normalized = float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, normalized))

    @staticmethod
    def _normalize_manual_review_flag(value: Any) -> int:
        return 1 if value in (1, "1", True) else 0

    @staticmethod
    def _merge_feature_warning(existing: Any, incoming: str) -> str:
        existing_text = str(existing or "").strip()
        incoming_text = str(incoming or "").strip()
        if not incoming_text:
            return existing_text
        if not existing_text:
            return incoming_text
        if incoming_text in existing_text:
            return existing_text
        return f"{existing_text} {incoming_text}"

    def _normalize_dim1_feature(self, value: Any) -> Dict[str, Any]:
        feature = dict(value) if isinstance(value, dict) else {}
        return {
            "task_form": self._normalize_choice(feature.get("task_form"), DIM1_TASK_FORM_VALUES),
            "calc_role": self._normalize_choice(feature.get("calc_role"), DIM1_CALC_ROLE_VALUES),
            "calc_bucket": self._normalize_choice(feature.get("calc_bucket"), DIM1_CALC_BUCKET_VALUES),
            "step_chain": self._normalize_choice(feature.get("step_chain"), DIM1_STEP_CHAIN_VALUES),
            "number_mix": self._normalize_choice(feature.get("number_mix"), DIM1_NUMBER_MIX_VALUES),
            "routine_transform_count": (
                str(feature.get("routine_transform_count", "")).strip()
                if str(feature.get("routine_transform_count", "")).strip() in DIM1_ROUTINE_TRANSFORM_VALUES
                else ""
            ),
            "structural_method": self._normalize_choice(
                feature.get("structural_method"),
                DIM1_STRUCTURAL_METHOD_VALUES,
            ),
            "global_view_required": self._normalize_zero_one(feature.get("global_view_required")),
            "error_pressure": self._normalize_choice(
                feature.get("error_pressure"),
                DIM1_ERROR_PRESSURE_VALUES,
            ),
            "intermediate_quantity_count": self._normalize_choice(
                feature.get("intermediate_quantity_count"),
                DIM1_EMBEDDED_COUNT_VALUES,
            ),
            "unit_conversion_count": self._normalize_choice(
                feature.get("unit_conversion_count"),
                DIM1_EMBEDDED_COUNT_VALUES,
            ),
            "formula_substitution_count": self._normalize_choice(
                feature.get("formula_substitution_count"),
                DIM1_EMBEDDED_COUNT_VALUES,
            ),
            "calc_subtype": self._normalize_choice(
                feature.get("calc_subtype"),
                DIM1_CALC_SUBTYPE_VALUES,
            ),
            "structure_patterns": self._normalize_choice_list(
                feature.get("structure_patterns"),
                DIM1_STRUCTURE_PATTERN_VALUES,
            ),
            "term_count_band": self._normalize_choice(
                feature.get("term_count_band"),
                DIM1_TERM_COUNT_BAND_VALUES,
            ),
            "symbolic_dependency": self._normalize_choice(
                feature.get("symbolic_dependency"),
                DIM1_SYMBOLIC_DEPENDENCY_VALUES,
            ),
            "evidence_summary": str(feature.get("evidence_summary", "")).strip(),
            "evidence_tags": self._normalize_string_list(feature.get("evidence_tags")),
        }

    def _normalize_dim2_feature(self, value: Any) -> Dict[str, Any]:
        feature = dict(value) if isinstance(value, dict) else {}
        return {
            "task_form": self._normalize_choice(feature.get("task_form"), DIM2_TASK_FORM_VALUES),
            "spatial_role": self._normalize_choice(feature.get("spatial_role"), DIM2_SPATIAL_ROLE_VALUES),
            "figure_complexity": self._normalize_choice(
                feature.get("figure_complexity"),
                DIM2_FIGURE_COMPLEXITY_VALUES,
            ),
            "relation_hops": self._normalize_choice(feature.get("relation_hops"), DIM2_RELATION_HOPS_VALUES),
            "hidden_relation_count": self._normalize_choice(
                feature.get("hidden_relation_count"),
                DIM2_HIDDEN_RELATION_COUNT_VALUES,
            ),
            "visual_operation_count": self._normalize_choice(
                feature.get("visual_operation_count"),
                DIM2_VISUAL_OPERATION_COUNT_VALUES,
            ),
            "structural_visual_method": self._normalize_choice(
                feature.get("structural_visual_method"),
                DIM2_STRUCTURAL_VISUAL_METHOD_VALUES,
            ),
            "measurement_dependency": self._normalize_choice(
                feature.get("measurement_dependency"),
                DIM2_MEASUREMENT_DEPENDENCY_VALUES,
            ),
            "global_view_required": self._normalize_zero_one(feature.get("global_view_required")),
            "image_dependency": self._normalize_choice(
                feature.get("image_dependency"),
                DIM2_IMAGE_DEPENDENCY_VALUES,
            ),
            "geometry_model_types": self._normalize_choice_list(
                feature.get("geometry_model_types"),
                DIM2_GEOMETRY_MODEL_TYPE_VALUES,
            ),
            "geometry_model_count": self._normalize_choice(
                feature.get("geometry_model_count"),
                DIM2_GEOMETRY_MODEL_COUNT_VALUES,
            ),
            "model_recognition_role": self._normalize_choice(
                feature.get("model_recognition_role"),
                DIM2_MODEL_RECOGNITION_ROLE_VALUES,
            ),
            "area_relation_chain": self._normalize_choice(
                feature.get("area_relation_chain"),
                DIM2_AREA_RELATION_CHAIN_VALUES,
            ),
            "model_combination_complexity": self._normalize_choice(
                feature.get("model_combination_complexity"),
                DIM2_MODEL_COMBINATION_COMPLEXITY_VALUES,
            ),
            "evidence_summary": str(feature.get("evidence_summary", "")).strip(),
            "evidence_tags": self._normalize_string_list(feature.get("evidence_tags")),
            "applicability_confidence": self._normalize_confidence(feature.get("applicability_confidence")),
            "need_manual_review": self._normalize_manual_review_flag(feature.get("need_manual_review")),
            "warning": str(feature.get("warning", "")).strip(),
        }

    def _normalize_dim3_feature(self, value: Any) -> Dict[str, Any]:
        feature = dict(value) if isinstance(value, dict) else {}
        return {
            "information_role": self._normalize_choice(
                feature.get("information_role"),
                DIM3_INFORMATION_ROLE_VALUES,
            ),
            "source_form": self._normalize_choice(
                feature.get("source_form"),
                DIM3_SOURCE_FORM_VALUES,
            ),
            "relevant_condition_count": self._normalize_choice(
                feature.get("relevant_condition_count"),
                DIM3_RELEVANT_CONDITION_COUNT_VALUES,
            ),
            "distractor_pressure": self._normalize_choice(
                feature.get("distractor_pressure"),
                DIM3_DISTRACTOR_PRESSURE_VALUES,
            ),
            "condition_distribution": self._normalize_choice(
                feature.get("condition_distribution"),
                DIM3_CONDITION_DISTRIBUTION_VALUES,
            ),
            "scenario_comprehension_load": self._normalize_choice(
                feature.get("scenario_comprehension_load"),
                DIM3_SCENARIO_COMPREHENSION_LOAD_VALUES,
            ) or "none",
            "extraction_depth": self._normalize_choice(
                feature.get("extraction_depth"),
                DIM3_EXTRACTION_DEPTH_VALUES,
            ),
            "representation_conversion": self._normalize_choice(
                feature.get("representation_conversion"),
                DIM3_REPRESENTATION_CONVERSION_VALUES,
            ),
            "conversion_step_count": self._normalize_choice(
                feature.get("conversion_step_count"),
                DIM3_CONVERSION_STEP_COUNT_VALUES,
            ),
            "quantity_relation_structure": self._normalize_choice(
                feature.get("quantity_relation_structure"),
                DIM3_QUANTITY_RELATION_STRUCTURE_VALUES,
            ),
            "target_representation": self._normalize_choice(
                feature.get("target_representation"),
                DIM3_TARGET_REPRESENTATION_VALUES,
            ),
            "global_organizing_required": self._normalize_zero_one(
                feature.get("global_organizing_required")
            ),
            "image_dependency": self._normalize_choice(
                feature.get("image_dependency"),
                DIM3_IMAGE_DEPENDENCY_VALUES,
            ),
            "application_relation_types": self._normalize_choice_list(
                feature.get("application_relation_types"),
                DIM3_APPLICATION_RELATION_TYPE_VALUES,
            ),
            "object_count_band": self._normalize_choice(
                feature.get("object_count_band"),
                DIM3_OBJECT_COUNT_BAND_VALUES,
            ),
            "state_change_count": self._normalize_choice(
                feature.get("state_change_count"),
                DIM3_APPLICATION_COUNT_VALUES,
            ),
            "implicit_relation_count": self._normalize_choice(
                feature.get("implicit_relation_count"),
                DIM3_APPLICATION_COUNT_VALUES,
            ),
            "base_quantity_shift": self._normalize_choice(
                feature.get("base_quantity_shift"),
                DIM3_BASE_QUANTITY_SHIFT_VALUES,
            ),
            "comparison_candidate_count": self._normalize_choice(
                feature.get("comparison_candidate_count"),
                DIM3_COMPARISON_CANDIDATE_COUNT_VALUES,
            ),
            "scenario_rule_count": self._normalize_choice(
                feature.get("scenario_rule_count", "0"),
                DIM3_SCENARIO_RULE_COUNT_VALUES,
            ),
            "process_stage_count": self._normalize_choice(
                feature.get("process_stage_count", "1"),
                DIM3_PROCESS_STAGE_COUNT_VALUES,
            ),
            "feedback_mechanism": self._normalize_choice(
                feature.get("feedback_mechanism", "none"),
                DIM3_FEEDBACK_MECHANISM_VALUES,
            ),
            "comparison_basis": self._normalize_choice(
                feature.get("comparison_basis", "none"),
                DIM3_COMPARISON_BASIS_VALUES,
            ),
            "diagram_correspondence": self._normalize_choice(
                feature.get("diagram_correspondence", "none"),
                DIM3_DIAGRAM_CORRESPONDENCE_VALUES,
            ),
            "scenario_rule_types": self._normalize_choice_list(
                feature.get("scenario_rule_types"),
                DIM3_SCENARIO_RULE_TYPE_VALUES,
            ),
            "evidence_summary": str(feature.get("evidence_summary", "")).strip(),
            "evidence_tags": self._normalize_string_list(feature.get("evidence_tags")),
            "applicability_confidence": self._normalize_confidence(feature.get("applicability_confidence")),
            "need_manual_review": self._normalize_manual_review_flag(feature.get("need_manual_review")),
            "warning": str(feature.get("warning", "")).strip(),
        }

    def _normalize_dim4_feature(self, value: Any) -> Dict[str, Any]:
        feature = dict(value) if isinstance(value, dict) else {}
        return {
            "strategy_role": self._normalize_choice(
                feature.get("strategy_role"),
                DIM4_STRATEGY_ROLE_VALUES,
            ),
            "template_fit": self._normalize_choice(
                feature.get("template_fit"),
                DIM4_TEMPLATE_FIT_VALUES,
            ),
            "breakthrough_type": self._normalize_choice(
                feature.get("breakthrough_type"),
                DIM4_BREAKTHROUGH_TYPE_VALUES,
            ),
            "strategy_shift_count": self._normalize_choice(
                feature.get("strategy_shift_count"),
                DIM4_STRATEGY_SHIFT_COUNT_VALUES,
            ),
            "construction_requirement": self._normalize_choice(
                feature.get("construction_requirement"),
                DIM4_CONSTRUCTION_REQUIREMENT_VALUES,
            ),
            "exploration_space": self._normalize_choice(
                feature.get("exploration_space"),
                DIM4_EXPLORATION_SPACE_VALUES,
            ),
            "representation_reframe": self._normalize_choice(
                feature.get("representation_reframe"),
                DIM4_REPRESENTATION_REFRAME_VALUES,
            ),
            "transfer_distance": self._normalize_choice(
                feature.get("transfer_distance"),
                DIM4_TRANSFER_DISTANCE_VALUES,
            ),
            "path_openness": self._normalize_choice(
                feature.get("path_openness"),
                DIM4_PATH_OPENNESS_VALUES,
            ),
            "dead_end_risk": self._normalize_choice(
                feature.get("dead_end_risk"),
                DIM4_DEAD_END_RISK_VALUES,
            ),
            "global_strategy_required": self._normalize_zero_one(
                feature.get("global_strategy_required")
            ),
            "image_dependency": self._normalize_choice(
                feature.get("image_dependency"),
                DIM4_IMAGE_DEPENDENCY_VALUES,
            ),
            "knowledge_point": str(feature.get("knowledge_point", "")).strip(),
            "topic_level": normalize_dim4_level(feature.get("topic_level")),
            "level_source": normalize_dim4_level_source(feature.get("level_source")),
            "anchor_evidence": str(feature.get("anchor_evidence", "")).strip(),
            "reference_matches": feature.get("reference_matches")
            if isinstance(feature.get("reference_matches"), list)
            else [],
            "fallback_used": feature.get("fallback_used") in (1, "1", True),
            "fallback_confidence": self._normalize_confidence(feature.get("fallback_confidence")),
            "fallback_error": str(feature.get("fallback_error", "")).strip(),
            "reference_calibrated_level": normalize_dim4_level(feature.get("reference_calibrated_level")),
            "evidence_summary": str(feature.get("evidence_summary", "")).strip(),
            "evidence_tags": self._normalize_string_list(feature.get("evidence_tags")),
            "applicability_confidence": self._normalize_confidence(feature.get("applicability_confidence")),
            "need_manual_review": self._normalize_manual_review_flag(feature.get("need_manual_review")),
            "warning": str(feature.get("warning", "")).strip(),
        }

    def _normalize_dim5_feature(self, value: Any) -> Dict[str, Any]:
        feature = dict(value) if isinstance(value, dict) else {}
        return {
            "band": " ".join(str(feature.get("band", "")).strip().split()),
            "sublevel": self._normalize_choice(feature.get("sublevel"), DIM5_SUBLEVEL_VALUES),
            "evidence_summary": str(feature.get("evidence_summary", "")).strip(),
            "evidence_tags": self._normalize_string_list(feature.get("evidence_tags")),
            "method_tags": self._normalize_string_list(feature.get("method_tags")),
            "grade_clues": self._normalize_string_list(feature.get("grade_clues")),
            "system_clues": self._normalize_string_list(feature.get("system_clues")),
            "visual_dependency": self._normalize_choice(
                feature.get("visual_dependency"),
                DIM5_VISUAL_DEPENDENCY_VALUES,
            ),
            "knowledge_tags": self._normalize_string_list(feature.get("knowledge_tags")),
            "core_knowledge_units": self._normalize_string_list(feature.get("core_knowledge_units")),
            "supporting_knowledge_units": self._normalize_string_list(feature.get("supporting_knowledge_units")),
            "knowledge_family_count": self._normalize_choice(
                feature.get("knowledge_family_count"),
                DIM5_KNOWLEDGE_FAMILY_COUNT_VALUES,
            ),
            "knowledge_integration": self._normalize_choice(
                feature.get("knowledge_integration"),
                DIM5_KNOWLEDGE_INTEGRATION_VALUES,
            ),
            "novel_definition_dependency": self._normalize_choice(
                feature.get("novel_definition_dependency"),
                DIM5_NOVEL_DEFINITION_DEPENDENCY_VALUES,
            ),
            "competition_signal": self._normalize_choice(
                feature.get("competition_signal"),
                DIM5_COMPETITION_SIGNAL_VALUES,
            ),
            "applicability_confidence": self._normalize_confidence(feature.get("applicability_confidence")),
            "need_manual_review": self._normalize_manual_review_flag(feature.get("need_manual_review")),
            "warning": str(feature.get("warning", "")).strip(),
            "band_source": str(feature.get("band_source", "")).strip(),
            "dim5_retry_used": feature.get("dim5_retry_used") in (1, "1", True),
            "dim5_retry_confidence": self._normalize_confidence(feature.get("dim5_retry_confidence")),
            "dim5_retry_error": str(feature.get("dim5_retry_error", "")).strip(),
            "dim5_excluded_reason": str(feature.get("dim5_excluded_reason", "")).strip(),
            "gaosi_grade": self._normalize_gaosi_grade(feature.get("gaosi_grade")),
            "gaosi_section_level": self._normalize_gaosi_section_level(
                feature.get("gaosi_section_level") or feature.get("gaosi_section_label")
            ),
            "gaosi_section_label": self._normalize_gaosi_section_label(
                feature.get("gaosi_section_label") or feature.get("gaosi_section_level")
            ),
            "gaosi_classification_source": self._normalize_choice(
                feature.get("gaosi_classification_source"),
                DIM5_GAOSI_CLASSIFICATION_SOURCE_VALUES,
            ),
            "primary_knowledge_point": str(feature.get("primary_knowledge_point", "")).strip(),
            "knowledge_point_source": str(feature.get("knowledge_point_source", "")).strip(),
            "knowledge_level": normalize_dim5_knowledge_level(feature.get("knowledge_level")),
            "canonical_knowledge_domain": str(feature.get("canonical_knowledge_domain", "")).strip(),
            "canonical_knowledge_point": str(feature.get("canonical_knowledge_point", "")).strip(),
            "canonical_knowledge_family": str(feature.get("canonical_knowledge_family", "")).strip(),
            "level_source": str(feature.get("level_source", "")).strip(),
            "level_evidence": str(feature.get("level_evidence", "")).strip(),
            "canonical_match_source": str(feature.get("canonical_match_source", "")).strip(),
            "canonical_match_confidence": self._normalize_confidence(
                feature.get("canonical_match_confidence")
            ),
            "canonical_alias_hits": self._normalize_string_list(feature.get("canonical_alias_hits")),
            "canonical_structure_hits": self._normalize_string_list(
                feature.get("canonical_structure_hits")
            ),
            "canonical_direct_formula_guard": feature.get("canonical_direct_formula_guard")
            in (1, "1", True),
            "dim5_fallback_mode": str(feature.get("dim5_fallback_mode", "")).strip(),
            "dim5_upshift_reason": str(feature.get("dim5_upshift_reason", "")).strip(),
            "knowledge_point_id": str(feature.get("knowledge_point_id", "")).strip(),
            "knowledge_point_name": str(feature.get("knowledge_point_name", "")).strip(),
            "knowledge_domain": str(feature.get("knowledge_domain", "")).strip(),
            "knowledge_track": str(feature.get("knowledge_track", "")).strip(),
            "knowledge_track_label": str(feature.get("knowledge_track_label", "")).strip(),
            "knowledge_grade": str(feature.get("knowledge_grade", "")).strip(),
            "knowledge_grade_label": str(feature.get("knowledge_grade_label", "")).strip(),
            "knowledge_semester": str(feature.get("knowledge_semester", "")).strip(),
            "knowledge_display_name": str(feature.get("knowledge_display_name", "")).strip(),
            "dim5_key_difficulty_explanation": str(
                feature.get("dim5_key_difficulty_explanation", "")
            ).strip(),
            "dim5_structure_facts": self._normalize_dict_list(
                feature.get("dim5_structure_facts")
            ),
            "candidate_knowledge_points": self._normalize_dict_list(
                feature.get("candidate_knowledge_points")
            ),
            "selected_candidate_id": str(feature.get("selected_candidate_id", "")).strip(),
            "rejected_candidates": self._normalize_dict_list(feature.get("rejected_candidates")),
            "confidence_status": str(feature.get("confidence_status", "")).strip(),
            "failure_reason": str(feature.get("failure_reason", "")).strip(),
            "graph_version": str(feature.get("graph_version", "")).strip(),
            "dim5_retrieval_context": self._normalize_optional_dict(
                feature.get("dim5_retrieval_context")
            ),
            "dim5_retrieval_candidates": self._normalize_dict_list(
                feature.get("dim5_retrieval_candidates")
            ),
            "dim5_retrieval_decision": str(feature.get("dim5_retrieval_decision", "")).strip(),
            "accepted_retrieval_candidate_ids": self._normalize_string_list(
                feature.get("accepted_retrieval_candidate_ids")
            ),
            "rejected_retrieval_candidate_ids": self._normalize_string_list(
                feature.get("rejected_retrieval_candidate_ids")
            ),
            "knowledge_grounding_context": self._normalize_optional_dict(
                feature.get("knowledge_grounding_context")
            ),
            "knowledge_grounding_candidates": self._normalize_dict_list(
                feature.get("knowledge_grounding_candidates")
            ),
            "grounded_selection_status": str(feature.get("grounded_selection_status", "")).strip(),
            "selected_knowledge_candidate_id": str(
                feature.get("selected_knowledge_candidate_id", "")
            ).strip(),
            "grounded_canonical_knowledge_point": str(
                feature.get("grounded_canonical_knowledge_point", "")
            ).strip(),
            "grounded_knowledge_domain": str(feature.get("grounded_knowledge_domain", "")).strip(),
            "grounded_knowledge_source_text": str(
                feature.get("grounded_knowledge_source_text", "")
            ).strip(),
            "grounded_knowledge_level": normalize_dim5_knowledge_level(
                feature.get("grounded_knowledge_level")
            ),
            "grounded_confidence": self._normalize_confidence(feature.get("grounded_confidence")),
            "grounded_evidence": str(feature.get("grounded_evidence", "")).strip(),
            "grounded_match_source": str(feature.get("grounded_match_source", "")).strip(),
            "grounded_risk_flags": self._normalize_string_list(feature.get("grounded_risk_flags")),
            "grounded_rejected_candidates": self._normalize_dict_list(
                feature.get("grounded_rejected_candidates")
            ),
            "grounded_selector": str(feature.get("grounded_selector", "")).strip(),
        }

    def _normalize_dim6_feature(self, value: Any) -> Dict[str, Any]:
        feature = dict(value) if isinstance(value, dict) else {}
        return {
            "reasoning_role": self._normalize_choice(
                feature.get("reasoning_role"),
                DIM6_REASONING_ROLE_VALUES,
            ),
            "chain_span": self._normalize_choice(feature.get("chain_span"), DIM6_CHAIN_SPAN_VALUES),
            "hidden_dependency": self._normalize_choice(
                feature.get("hidden_dependency"),
                DIM6_HIDDEN_DEPENDENCY_VALUES,
            ),
            "branch_control": self._normalize_choice(
                feature.get("branch_control"),
                DIM6_BRANCH_CONTROL_VALUES,
            ),
            "reversibility": self._normalize_choice(
                feature.get("reversibility"),
                DIM6_REVERSIBILITY_VALUES,
            ),
            "verification_requirement": self._normalize_choice(
                feature.get("verification_requirement"),
                DIM6_VERIFICATION_REQUIREMENT_VALUES,
            ),
            "abstraction_bridge_count": self._normalize_choice(
                feature.get("abstraction_bridge_count"),
                DIM6_ABSTRACTION_BRIDGE_COUNT_VALUES,
            ),
            "constraint_coupling": self._normalize_choice(
                feature.get("constraint_coupling"),
                DIM6_CONSTRAINT_COUPLING_VALUES,
            ),
            "global_consistency_required": self._normalize_zero_one(
                feature.get("global_consistency_required")
            ),
            "conclusion_stability": self._normalize_choice(
                feature.get("conclusion_stability"),
                DIM6_CONCLUSION_STABILITY_VALUES,
            ),
            "logic_structure_types": self._normalize_choice_list(
                feature.get("logic_structure_types"),
                DIM6_LOGIC_STRUCTURE_TYPE_VALUES,
            ),
            "state_transition_count": self._normalize_choice(
                feature.get("state_transition_count", "0"),
                DIM6_STATE_TRANSITION_COUNT_VALUES,
            ),
            "case_count_band": self._normalize_choice(
                feature.get("case_count_band", "none"),
                DIM6_CASE_COUNT_BAND_VALUES,
            ),
            "backtrack_depth": self._normalize_choice(
                feature.get("backtrack_depth", "0"),
                DIM6_BACKTRACK_DEPTH_VALUES,
            ),
            "consistency_constraint_count": self._normalize_choice(
                feature.get("consistency_constraint_count", "0"),
                DIM6_CONSISTENCY_CONSTRAINT_COUNT_VALUES,
            ),
            "phase_count_band": self._normalize_choice(
                feature.get("phase_count_band", "1"),
                DIM6_PHASE_COUNT_BAND_VALUES,
            ),
            "periodic_cycle_dependency": self._normalize_zero_one(
                feature.get("periodic_cycle_dependency", 0)
            ),
            "optimization_requirement": self._normalize_choice(
                feature.get("optimization_requirement", "none"),
                DIM6_OPTIMIZATION_REQUIREMENT_VALUES,
            ),
            "evidence_summary": str(feature.get("evidence_summary", "")).strip(),
            "evidence_tags": self._normalize_string_list(feature.get("evidence_tags")),
            "applicability_confidence": self._normalize_confidence(feature.get("applicability_confidence")),
            "need_manual_review": self._normalize_manual_review_flag(feature.get("need_manual_review")),
            "warning": str(feature.get("warning", "")).strip(),
        }

    def _normalize_dimension_features(self, feature_map: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {
            "dim1_computation": self._normalize_dim1_feature(feature_map.get("dim1_computation")),
            "dim2_spatial": self._normalize_dim2_feature(feature_map.get("dim2_spatial")),
            "dim3_information": self._normalize_dim3_feature(feature_map.get("dim3_information")),
            "dim4_innovation": self._normalize_dim4_feature(feature_map.get("dim4_innovation")),
            "dim5_knowledge": self._normalize_dim5_feature(feature_map.get("dim5_knowledge")),
            "dim6_logic": self._normalize_dim6_feature(feature_map.get("dim6_logic")),
        }

    @staticmethod
    def _dim1_high_burden_signal(feature: Dict[str, Any]) -> bool:
        structure_patterns = set(feature.get("structure_patterns") or [])
        return any(
            [
                feature.get("routine_transform_count") in {"2", "3+"},
                feature.get("structural_method") in {"shortcut", "olympiad"},
                feature.get("global_view_required") == 1,
                feature.get("step_chain") == "5+",
                feature.get("step_chain") == "3-4" and feature.get("number_mix") in {"mixed", "symbolic"},
                feature.get("intermediate_quantity_count") in {"2", "2+", "3+"},
                feature.get("unit_conversion_count") in {"1", "2", "2+", "3+"},
                feature.get("formula_substitution_count") in {"2", "2+", "3+"},
                feature.get("calc_subtype") in {
                    "defined_operation",
                    "sequence_series",
                    "nested_fraction",
                    "structural_identity",
                },
                bool(
                    structure_patterns
                    & {
                        "telescoping",
                        "symmetric_cancellation",
                        "recursive_product",
                        "continued_fraction",
                        "sequence_generalization",
                    }
                ),
                feature.get("term_count_band") in {"6-10", "11+"},
                feature.get("symbolic_dependency") == "parameterized",
            ]
        )

    def _dim1_validation_warnings(
        self,
        feature: Dict[str, Any],
        *,
        confidence: float,
        question: ParsedQuestion,
    ) -> List[str]:
        warnings: List[str] = []
        required_fields = [
            "task_form",
            "calc_role",
            "step_chain",
            "number_mix",
            "routine_transform_count",
            "structural_method",
            "global_view_required",
            "error_pressure",
            "evidence_summary",
        ]
        missing = [field for field in required_fields if feature.get(field) in ("", None)]
        if missing:
            warnings.append("dim1 缺少关键计算事实字段：%s。" % "、".join(missing))

        if confidence < DIM1_REVIEW_CONFIDENCE_THRESHOLD:
            warnings.append(
                f"dim1 置信度低于自动判分阈值（{DIM1_REVIEW_CONFIDENCE_THRESHOLD:.2f}）。"
            )

        task_form = feature.get("task_form")
        calc_role = feature.get("calc_role")
        high_burden_signal = self._dim1_high_burden_signal(feature)
        if task_form == "explicit" and calc_role != "core":
            warnings.append("dim1 标记为显式计算题，但 calc_role 不是 core。")
        if calc_role == "none" and high_burden_signal:
            warnings.append("dim1 标记为无核心计算，但计算负担特征明显偏高。")
        if calc_role == "supporting" and (task_form == "explicit" or high_burden_signal):
            warnings.append("dim1 标记为 supporting，但计算负担特征与之冲突。")

        for item in getattr(question, "parse_warnings", []) or []:
            text = str(item).strip()
            if any(marker in text for marker in ("OCR", "残缺", "缺损", "截断", "公式", "识别失败")):
                warnings.append("dim1 题面存在 OCR 或公式缺损，当前结果需人工复核。")
                break

        return warnings

    @staticmethod
    def _dim2_relation_rank(value: str) -> int:
        return {"1": 1, "2": 2, "3-4": 3, "5+": 4}.get(str(value or "").strip(), -1)

    @staticmethod
    def _dim2_hidden_relation_rank(value: str) -> int:
        return {"0": 0, "1": 1, "2+": 2}.get(str(value or "").strip(), -1)

    @staticmethod
    def _dim2_visual_operation_rank(value: str) -> int:
        return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(str(value or "").strip(), -1)

    @classmethod
    def _dim2_has_core_geometry_model(cls, feature: Dict[str, Any]) -> bool:
        model_types = set(feature.get("geometry_model_types") or [])
        if model_types and model_types <= DIM2_LOW_BARRIER_GEOMETRY_MODEL_TYPES:
            return feature.get("model_recognition_role") == "core" and (
                feature.get("area_relation_chain") in {"multi", "nested"}
                or feature.get("model_combination_complexity")
                in {"model_plus_operation", "multi_model", "nested_model"}
            )
        return feature.get("model_recognition_role") == "core" and bool(
            model_types
            or feature.get("area_relation_chain") in {"single", "multi", "nested"}
            or feature.get("model_combination_complexity")
            in {"single_model", "model_plus_operation", "multi_model", "nested_model"}
        )

    @classmethod
    def _dim2_has_low_barrier_formula_model(cls, feature: Dict[str, Any]) -> bool:
        model_types = set(feature.get("geometry_model_types") or [])
        return bool(model_types) and model_types <= DIM2_LOW_BARRIER_GEOMETRY_MODEL_TYPES and (
            feature.get("area_relation_chain") in {"", "none"}
            and feature.get("model_combination_complexity") in {"", "none", "single_model"}
        )

    @classmethod
    def _dim2_has_high_burden_signal(cls, feature: Dict[str, Any]) -> bool:
        return any(
            [
                feature.get("figure_complexity") in {"composite_2d", "solid_3d", "net_section_multi_view"},
                cls._dim2_relation_rank(feature.get("relation_hops", "")) >= 3,
                cls._dim2_hidden_relation_rank(feature.get("hidden_relation_count", "")) >= 1,
                cls._dim2_visual_operation_rank(feature.get("visual_operation_count", "")) >= 2,
                feature.get("structural_visual_method") in {"decomposition", "auxiliary_line", "3d_transform"},
                feature.get("measurement_dependency") == "inferred",
                feature.get("global_view_required") == 1,
                feature.get("image_dependency") == "required",
                cls._dim2_has_core_geometry_model(feature),
            ]
        )

    @classmethod
    def _dim2_is_simple_direct_geometry(cls, feature: Dict[str, Any]) -> bool:
        if cls._dim2_has_core_geometry_model(feature):
            return False
        return (
            feature.get("measurement_dependency") == "direct"
            and feature.get("relation_hops") == "1"
            and feature.get("hidden_relation_count") == "0"
            and feature.get("visual_operation_count") == "0"
            and feature.get("structural_visual_method") == "none"
            and feature.get("global_view_required") == 0
        )

    @classmethod
    def _dim2_has_stable_geometry_scope(cls, feature: Dict[str, Any]) -> bool:
        return feature.get("task_form") in {"explicit_visual", "geometry_embedded", "text_only_geometry"} and (
            feature.get("figure_complexity") not in {"", None, "none"}
            or bool(feature.get("geometry_model_types") or [])
        )

    def _dim2_should_validate(self, feature: Dict[str, Any], question: ParsedQuestion) -> bool:
        if any(
            feature.get(key)
            not in ("", None, [], {})
            for key in (
                "task_form",
                "spatial_role",
                "figure_complexity",
                "relation_hops",
                "hidden_relation_count",
                "visual_operation_count",
                "structural_visual_method",
                "measurement_dependency",
                "image_dependency",
                "geometry_model_types",
                "geometry_model_count",
                "model_recognition_role",
                "area_relation_chain",
                "model_combination_complexity",
                "evidence_summary",
            )
        ):
            return True

        audit = getattr(question, "parse_audit", None)
        visual_category = str(getattr(audit, "visual_category", "") or "").strip()
        if visual_category in DIM2_GEOMETRY_VISUAL_CATEGORIES:
            return True
        return bool(DIM2_TEXT_SIGNAL_PATTERN.search(question.raw_text or ""))

    def _dim2_validation_warnings(
        self,
        feature: Dict[str, Any],
        *,
        confidence: float,
        question: ParsedQuestion,
    ) -> List[str]:
        if not self._dim2_should_validate(feature, question):
            return []

        warnings: List[str] = []
        required_fields = [
            "task_form",
            "spatial_role",
            "figure_complexity",
            "relation_hops",
            "hidden_relation_count",
            "visual_operation_count",
            "structural_visual_method",
            "measurement_dependency",
            "global_view_required",
            "image_dependency",
            "evidence_summary",
        ]
        missing = [field for field in required_fields if feature.get(field) in ("", None)]
        if missing:
            warnings.append(f"dim2 缺少关键空间事实字段：{'、'.join(missing)}。")

        dim2_confidence = feature.get("applicability_confidence", 0.0) or confidence
        if dim2_confidence < DIM2_REVIEW_CONFIDENCE_THRESHOLD:
            warnings.append(
                f"dim2 置信度低于自动判分阈值（{DIM2_REVIEW_CONFIDENCE_THRESHOLD:.2f}）。"
            )

        task_form = feature.get("task_form")
        spatial_role = feature.get("spatial_role")
        has_core_model = self._dim2_has_core_geometry_model(feature)
        if spatial_role == "none" and self._dim2_has_high_burden_signal(feature) and not has_core_model:
            warnings.append("dim2 标记为 none，但空间负担特征明显偏高。")
        if task_form == "explicit_visual" and feature.get("image_dependency") == "none":
            warnings.append("dim2 标记为 explicit_visual，但 image_dependency 为 none。")
        if task_form == "nonvisual" and feature.get("image_dependency") == "required":
            warnings.append("dim2 标记为 nonvisual，但 image_dependency 为 required。")
        if task_form == "text_only_geometry" and feature.get("image_dependency") == "required":
            warnings.append("dim2 标记为 text_only_geometry，但 image_dependency 为 required。")

        audit = getattr(question, "parse_audit", None)
        if (
            getattr(audit, "visual_category", "") in DIM2_GEOMETRY_VISUAL_CATEGORIES
            and spatial_role == "none"
            and not has_core_model
        ):
            warnings.append("OCR 视觉类别提示几何/空间题，但 dim2 标记为 none。")
        if getattr(audit, "image_required_hint", False) and feature.get("image_dependency") == "none":
            warnings.append("OCR 审计提示图片很关键，但 dim2 标记为不依赖图片。")

        return warnings

    @staticmethod
    def _dim3_conversion_rank(value: str) -> int:
        return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(str(value or "").strip(), -1)

    @staticmethod
    def _dim3_condition_count_rank(value: str) -> int:
        return {"1-2": 1, "3-4": 2, "5-6": 3, "7+": 4}.get(str(value or "").strip(), -1)

    @staticmethod
    def _dim3_application_count_rank(value: str) -> int:
        return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(str(value or "").strip(), 0)

    @staticmethod
    def _dim3_object_count_rank(value: str) -> int:
        return {"1": 1, "2": 2, "3": 3, "4+": 4}.get(str(value or "").strip(), 0)

    @staticmethod
    def _dim3_comparison_count_rank(value: str) -> int:
        return {"0": 0, "2": 2, "3+": 3}.get(str(value or "").strip(), 0)

    @staticmethod
    def _dim3_scenario_load_rank(value: str) -> int:
        return {"none": 0, "light": 1, "medium": 2, "heavy": 3}.get(str(value or "").strip(), 0)

    @staticmethod
    def _dim3_rule_count_rank(value: str) -> int:
        return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(str(value or "").strip(), 0)

    @staticmethod
    def _dim3_stage_count_rank(value: str) -> int:
        return {"1": 1, "2": 2, "3": 3, "4+": 4}.get(str(value or "").strip(), 1)

    @staticmethod
    def _dim3_feedback_rank(value: str) -> int:
        return {"none": 0, "simple": 1, "conditional": 2}.get(str(value or "").strip(), 0)

    @staticmethod
    def _dim3_comparison_basis_rank(value: str) -> int:
        return {"none": 0, "direct": 1, "implicit": 2, "multi_condition": 3}.get(str(value or "").strip(), 0)

    @staticmethod
    def _dim3_diagram_rank(value: str) -> int:
        return {"none": 0, "helpful": 1, "required": 2, "multi_step": 3}.get(str(value or "").strip(), 0)

    @classmethod
    def _dim3_has_high_burden_signal(cls, feature: Dict[str, Any]) -> bool:
        relation_types = set(feature.get("application_relation_types") or [])
        scenario_rule_types = set(feature.get("scenario_rule_types") or [])
        stage_rank = max(
            cls._dim3_stage_count_rank(feature.get("process_stage_count", "")),
            cls._dim3_application_count_rank(feature.get("state_change_count", "")) + 1,
        )
        comparison_rank = max(
            cls._dim3_comparison_basis_rank(feature.get("comparison_basis", "")),
            cls._dim3_comparison_count_rank(feature.get("comparison_candidate_count", "")),
        )
        return any(
            [
                feature.get("source_form") == "multi_source",
                feature.get("distractor_pressure") == "heavy",
                feature.get("condition_distribution") == "cross_modal",
                feature.get("image_dependency") == "required",
                cls._dim3_scenario_load_rank(feature.get("scenario_comprehension_load", "")) >= 3,
                cls._dim3_rule_count_rank(feature.get("scenario_rule_count", "")) >= 2,
                stage_rank >= 3,
                cls._dim3_feedback_rank(feature.get("feedback_mechanism", "")) >= 1,
                comparison_rank >= 2,
                cls._dim3_diagram_rank(feature.get("diagram_correspondence", "")) >= 2,
                bool(
                    scenario_rule_types
                    & {
                        "feedback_rule",
                        "conditional_trigger",
                        "diagram_mapping",
                        "multi_stage_process",
                        "custom_rule_system",
                    }
                ),
                bool(
                    relation_types
                    & {
                        "optimization_comparison",
                        "range_narrowing",
                    }
                ),
                cls._dim3_object_count_rank(feature.get("object_count_band", "")) >= 3,
            ]
        )

    @classmethod
    def _dim3_is_low_barrier_direct_extraction(cls, feature: Dict[str, Any]) -> bool:
        relation_types = set(feature.get("application_relation_types") or [])
        if cls._dim3_scenario_load_rank(feature.get("scenario_comprehension_load", "")) >= 2:
            return False
        if set(feature.get("scenario_rule_types") or []):
            return False
        if (
            cls._dim3_rule_count_rank(feature.get("scenario_rule_count", "")) >= 1
            or cls._dim3_stage_count_rank(feature.get("process_stage_count", "")) >= 2
            or cls._dim3_feedback_rank(feature.get("feedback_mechanism", "")) >= 1
            or cls._dim3_comparison_basis_rank(feature.get("comparison_basis", "")) >= 1
            or cls._dim3_diagram_rank(feature.get("diagram_correspondence", "")) >= 1
            or feature.get("image_dependency") in {"helpful", "required"}
        ):
            return False
        if relation_types & {"optimization_comparison", "range_narrowing"}:
            return False
        if (
            cls._dim3_object_count_rank(feature.get("object_count_band", "")) >= 2
            or cls._dim3_application_count_rank(feature.get("state_change_count", "")) >= 1
            or cls._dim3_comparison_count_rank(feature.get("comparison_candidate_count", "")) >= 2
        ):
            return False

        return (
            feature.get("source_form") in {"text_only", "table_chart", "image_text"}
            and feature.get("relevant_condition_count") == "1-2"
            and feature.get("distractor_pressure") == "none"
            and feature.get("condition_distribution") == "compact"
            and feature.get("extraction_depth") == "direct"
        )

    def _dim3_should_validate(self, feature: Dict[str, Any], question: ParsedQuestion) -> bool:
        if self._dim3_scenario_load_rank(feature.get("scenario_comprehension_load", "")) >= 1:
            return True

        neutral_values = {
            "relevant_condition_count": {"0"},
            "distractor_pressure": {"none"},
            "condition_distribution": {"compact"},
            "extraction_depth": {"direct"},
            "representation_conversion": {"none", "direct_mapping"},
            "conversion_step_count": {"0"},
            "quantity_relation_structure": {"none", "single_relation"},
            "target_representation": {"none"},
            "image_dependency": {"none"},
            "object_count_band": {"1"},
            "state_change_count": {"0"},
            "implicit_relation_count": {"0"},
            "base_quantity_shift": {"none"},
            "comparison_candidate_count": {"0"},
            "scenario_comprehension_load": {"none"},
            "scenario_rule_count": {"0"},
            "process_stage_count": {"1"},
            "feedback_mechanism": {"none"},
            "comparison_basis": {"none"},
            "diagram_correspondence": {"none"},
        }
        for key in (
            "information_role",
            "source_form",
            "relevant_condition_count",
            "distractor_pressure",
            "condition_distribution",
            "extraction_depth",
            "representation_conversion",
            "conversion_step_count",
            "quantity_relation_structure",
            "target_representation",
            "image_dependency",
            "evidence_summary",
            "application_relation_types",
            "object_count_band",
            "state_change_count",
            "implicit_relation_count",
            "base_quantity_shift",
            "comparison_candidate_count",
            "scenario_comprehension_load",
            "scenario_rule_count",
            "process_stage_count",
            "feedback_mechanism",
            "comparison_basis",
            "diagram_correspondence",
            "scenario_rule_types",
        ):
            value = feature.get(key)
            if value in ("", None, [], {}):
                continue
            if key in neutral_values and str(value) in neutral_values[key]:
                continue
            return True

        audit = getattr(question, "parse_audit", None)
        visual_category = str(getattr(audit, "visual_category", "") or "").strip()
        if visual_category in DIM3_VISUAL_CATEGORIES:
            return True

        raw_text = question.raw_text or ""
        return any(marker in raw_text for marker in ("统计图", "表格", "下表", "下图", "图表"))

    def _dim3_validation_warnings(
        self,
        feature: Dict[str, Any],
        *,
        confidence: float,
        question: ParsedQuestion,
    ) -> List[str]:
        if not self._dim3_should_validate(feature, question):
            return []

        warnings: List[str] = []
        required_fields = [
            "information_role",
            "source_form",
            "scenario_comprehension_load",
            "image_dependency",
            "evidence_summary",
        ]
        missing = [field for field in required_fields if feature.get(field) in ("", None)]
        if missing:
            warnings.append(f"dim3 缺少关键场景理解事实字段：{'、'.join(missing)}。")

        dim3_confidence = feature.get("applicability_confidence", 0.0) or confidence
        information_role = feature.get("information_role")
        if (
            dim3_confidence < DIM3_REVIEW_CONFIDENCE_THRESHOLD
            and (information_role == "core" or self._dim3_has_high_burden_signal(feature))
        ):
            warnings.append(
                f"dim3 置信度低于自动判分阈值（{DIM3_REVIEW_CONFIDENCE_THRESHOLD:.2f}）。"
            )

        if information_role == "none" and self._dim3_has_high_burden_signal(feature):
            warnings.append("dim3 标记为 none，但场景理解负担特征明显偏高。")
        if (
            feature.get("source_form") == "multi_source"
            and feature.get("condition_distribution") == "compact"
            and self._dim3_scenario_load_rank(feature.get("scenario_comprehension_load", "")) <= 1
        ):
            warnings.append("dim3 标记为 multi_source，但场景理解负担明显偏低。")
        if information_role == "core" and self._dim3_is_low_barrier_direct_extraction(feature):
            warnings.append("dim3 标记为 core，但当前更像直接读条件代入的低门槛题。")

        audit = getattr(question, "parse_audit", None)
        if getattr(audit, "visual_category", "") in DIM3_VISUAL_CATEGORIES and information_role == "none":
            warnings.append("OCR 视觉类别提示图表/多段材料题，但 dim3 标记为 none。")
        if getattr(audit, "image_required_hint", False) and feature.get("image_dependency") == "none":
            warnings.append("OCR 审计提示图片或图表很关键，但 dim3 标记为不依赖图片。")

        return warnings

    @staticmethod
    def _dim4_strategy_shift_rank(value: str) -> int:
        return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(str(value or "").strip(), -1)

    @classmethod
    def _dim4_has_high_burden_signal(cls, feature: Dict[str, Any]) -> bool:
        return any(
            [
                feature.get("template_fit") in {"reframed", "non_routine"},
                feature.get("breakthrough_type") in {
                    "local_trick",
                    "strategy_shift",
                    "constructive",
                    "exploratory_search",
                },
                cls._dim4_strategy_shift_rank(feature.get("strategy_shift_count", "")) >= 2,
                feature.get("construction_requirement") in {"case_construction", "custom_construction"},
                feature.get("exploration_space") in {"branched", "open"},
                feature.get("representation_reframe") in {"structural", "creative"},
                feature.get("transfer_distance") in {"medium", "far"},
                feature.get("path_openness") in {"multiple_paths", "multiple_answers"},
                feature.get("dead_end_risk") in {"medium", "high"},
                feature.get("global_strategy_required") == 1,
            ]
        )

    @classmethod
    def _dim4_is_low_barrier_direct_template(cls, feature: Dict[str, Any]) -> bool:
        return (
            feature.get("template_fit") == "direct"
            and feature.get("breakthrough_type") == "none"
            and cls._dim4_strategy_shift_rank(feature.get("strategy_shift_count", "")) == 0
            and feature.get("construction_requirement") == "none"
            and feature.get("exploration_space") == "none"
            and feature.get("representation_reframe") == "none"
            and feature.get("transfer_distance") == "near"
            and feature.get("path_openness") == "single"
            and feature.get("dead_end_risk") == "low"
            and feature.get("global_strategy_required") == 0
        )

    def _dim4_should_validate(self, feature: Dict[str, Any], question: ParsedQuestion) -> bool:
        if any(
            feature.get(key)
            not in ("", None, [], {})
            for key in (
                "strategy_role",
                "template_fit",
                "breakthrough_type",
                "strategy_shift_count",
                "construction_requirement",
                "exploration_space",
                "representation_reframe",
                "transfer_distance",
                "path_openness",
                "dead_end_risk",
                "image_dependency",
                "evidence_summary",
            )
        ):
            return True
        return bool(DIM4_STRATEGY_SIGNAL_PATTERN.search(question.raw_text or ""))

    def _dim4_validation_warnings(
        self,
        feature: Dict[str, Any],
        *,
        confidence: float,
        question: ParsedQuestion,
    ) -> List[str]:
        if (
            normalize_dim4_level(feature.get("topic_level"))
            or normalize_dim4_level_source(feature.get("level_source")) == "review_failed"
        ):
            return []
        if not self._dim4_should_validate(feature, question):
            return []

        warnings: List[str] = []
        required_fields = [
            "strategy_role",
            "template_fit",
            "breakthrough_type",
            "strategy_shift_count",
            "construction_requirement",
            "exploration_space",
            "representation_reframe",
            "transfer_distance",
            "path_openness",
            "dead_end_risk",
            "global_strategy_required",
            "image_dependency",
            "evidence_summary",
        ]
        missing = [field for field in required_fields if feature.get(field) in ("", None)]
        if missing:
            warnings.append(f"dim4 缺少关键建模解题事实字段：{'、'.join(missing)}。")

        dim4_confidence = feature.get("applicability_confidence", 0.0) or confidence
        strategy_role = feature.get("strategy_role")
        if (
            dim4_confidence < DIM4_REVIEW_CONFIDENCE_THRESHOLD
            and (strategy_role == "core" or self._dim4_has_high_burden_signal(feature))
        ):
            warnings.append(
                f"dim4 置信度低于自动判分阈值（{DIM4_REVIEW_CONFIDENCE_THRESHOLD:.2f}）。"
            )

        if strategy_role == "none" and (
            self._dim4_has_high_burden_signal(feature)
            or DIM4_STRATEGY_SIGNAL_PATTERN.search(question.raw_text or "")
        ):
            warnings.append("dim4 标记为 none，但题面或建模解题特征明显偏高。")
        if strategy_role == "supporting" and self._dim4_has_high_burden_signal(feature):
            warnings.append("dim4 标记为 supporting，但建模组织与构造特征明显偏高。")
        if feature.get("template_fit") == "direct" and (
            feature.get("breakthrough_type") in {"constructive", "exploratory_search"}
            or feature.get("exploration_space") == "open"
            or feature.get("construction_requirement") == "custom_construction"
            or self._dim4_strategy_shift_rank(feature.get("strategy_shift_count", "")) >= 2
        ):
            warnings.append("dim4 标记为 direct，但突破类型、构造或探索空间明显偏高。")
        if (
            feature.get("path_openness") == "multiple_answers"
            and strategy_role in {"none", "supporting"}
        ):
            warnings.append("dim4 标记为多答案开放路径，但 strategy_role 偏低。")
        if strategy_role == "core" and self._dim4_is_low_barrier_direct_template(feature):
            warnings.append("dim4 标记为 core，但当前更像直接计算、直接代公式或普通一步应用题。")

        audit = getattr(question, "parse_audit", None)
        if getattr(audit, "image_required_hint", False) and feature.get("image_dependency") == "none":
            warnings.append("OCR 审计提示图片较关键，但 dim4 标记为不依赖图片。")

        for item in getattr(question, "parse_warnings", []) or []:
            text = str(item).strip()
            if any(marker in text for marker in ("残缺", "缺损", "截断", "识别失败", "公式增强识别失败")):
                warnings.append("dim4 题面存在 OCR 或题块质量问题，自动评分结果需要谨慎解读。")
                break

        if getattr(audit, "block_completeness", 1.0) < 0.65:
            warnings.append("题块完整度不足，dim4 自动评分结果需要谨慎解读。")

        return warnings

    @staticmethod
    def _dim6_chain_rank(value: str) -> int:
        return {"1": 1, "2": 2, "3-4": 3, "5+": 4}.get(str(value or "").strip(), -1)

    @staticmethod
    def _dim6_abstraction_rank(value: str) -> int:
        return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(str(value or "").strip(), -1)

    @staticmethod
    def _dim6_state_rank(value: str) -> int:
        return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(str(value or "").strip(), -1)

    @staticmethod
    def _dim6_case_rank(value: str) -> int:
        return {"none": 0, "2": 2, "3-5": 3, "6+": 6}.get(str(value or "").strip(), -1)

    @staticmethod
    def _dim6_backtrack_rank(value: str) -> int:
        return {"0": 0, "1": 1, "2": 2, "3+": 3}.get(str(value or "").strip(), -1)

    @staticmethod
    def _dim6_consistency_rank(value: str) -> int:
        return {"0": 0, "1": 1, "2-3": 2, "4+": 4}.get(str(value or "").strip(), -1)

    @staticmethod
    def _dim6_phase_rank(value: str) -> int:
        return {"1": 1, "2": 2, "3-4": 3, "5+": 5}.get(str(value or "").strip(), -1)

    @classmethod
    def _dim6_has_high_burden_signal(cls, feature: Dict[str, Any]) -> bool:
        structures = set(feature.get("logic_structure_types") or [])
        return any(
            [
                cls._dim6_chain_rank(feature.get("chain_span", "")) >= 3,
                feature.get("hidden_dependency") in {"cross_condition", "global"},
                feature.get("branch_control") in {"explicit_cases", "multi_branch"},
                feature.get("reversibility") in {"backward", "bidirectional"},
                feature.get("verification_requirement") in {"constraint_backcheck", "full_consistency"},
                cls._dim6_abstraction_rank(feature.get("abstraction_bridge_count", "")) >= 2,
                feature.get("constraint_coupling") in {"coupled", "nested"},
                feature.get("global_consistency_required") == 1,
                feature.get("conclusion_stability") == "exhaustive",
                bool(
                    structures
                    & {
                        "queue_growth_chain",
                        "travel_meeting_chasing_chain",
                        "cyclic_schedule_chain",
                        "bounded_case_enumeration",
                        "optimization_comparison",
                        "global_constraint_system",
                    }
                ),
                cls._dim6_state_rank(feature.get("state_transition_count", "0")) >= 2,
                cls._dim6_case_rank(feature.get("case_count_band", "none")) >= 3,
                cls._dim6_backtrack_rank(feature.get("backtrack_depth", "0")) >= 2,
                cls._dim6_consistency_rank(feature.get("consistency_constraint_count", "0")) >= 2,
                cls._dim6_phase_rank(feature.get("phase_count_band", "1")) >= 3,
                feature.get("periodic_cycle_dependency") == 1,
                feature.get("optimization_requirement") in {"bounded_choice", "global_minmax"},
            ]
        )

    @classmethod
    def _dim6_has_structured_burden_signal(cls, feature: Dict[str, Any]) -> bool:
        return any(
            [
                bool(feature.get("logic_structure_types")),
                cls._dim6_state_rank(feature.get("state_transition_count", "0")) > 0,
                cls._dim6_case_rank(feature.get("case_count_band", "none")) > 0,
                cls._dim6_backtrack_rank(feature.get("backtrack_depth", "0")) > 0,
                cls._dim6_consistency_rank(feature.get("consistency_constraint_count", "0")) > 0,
                cls._dim6_phase_rank(feature.get("phase_count_band", "1")) > 1,
                feature.get("periodic_cycle_dependency") == 1,
                feature.get("optimization_requirement") in {"bounded_choice", "global_minmax"},
            ]
        )

    @classmethod
    def _dim6_is_low_barrier_direct_push(cls, feature: Dict[str, Any]) -> bool:
        return (
            feature.get("chain_span") == "1"
            and feature.get("hidden_dependency") == "none"
            and feature.get("branch_control") == "none"
            and feature.get("reversibility") == "none"
            and feature.get("verification_requirement") == "none"
            and feature.get("abstraction_bridge_count") == "0"
            and feature.get("constraint_coupling") in {"none", "single"}
            and feature.get("global_consistency_required") == 0
            and feature.get("conclusion_stability") == "direct"
            and not cls._dim6_has_structured_burden_signal(feature)
        )

    def _dim6_should_validate(self, feature: Dict[str, Any], question: ParsedQuestion) -> bool:
        if any(
            feature.get(key)
            not in ("", None, [], {})
            for key in (
                "reasoning_role",
                "chain_span",
                "hidden_dependency",
                "branch_control",
                "reversibility",
                "verification_requirement",
                "abstraction_bridge_count",
                "constraint_coupling",
                "conclusion_stability",
                "evidence_summary",
            )
        ):
            return True
        if self._dim6_has_structured_burden_signal(feature):
            return True
        return bool(DIM6_LOGIC_SIGNAL_PATTERN.search(question.raw_text or ""))

    def _dim6_validation_warnings(
        self,
        feature: Dict[str, Any],
        *,
        confidence: float,
        question: ParsedQuestion,
    ) -> List[str]:
        if not self._dim6_should_validate(feature, question):
            return []

        warnings: List[str] = []
        required_fields = [
            "reasoning_role",
            "chain_span",
            "hidden_dependency",
            "branch_control",
            "reversibility",
            "verification_requirement",
            "abstraction_bridge_count",
            "constraint_coupling",
            "global_consistency_required",
            "conclusion_stability",
            "evidence_summary",
        ]
        missing = [field for field in required_fields if feature.get(field) in ("", None)]
        if missing:
            warnings.append(f"dim6 缺少关键逻辑事实字段：{'、'.join(missing)}。")

        dim6_confidence = feature.get("applicability_confidence", 0.0) or confidence
        reasoning_role = feature.get("reasoning_role")
        if (
            dim6_confidence < DIM6_REVIEW_CONFIDENCE_THRESHOLD
            and (reasoning_role == "core" or self._dim6_has_high_burden_signal(feature))
        ):
            warnings.append(
                f"dim6 置信度低于自动判分阈值（{DIM6_REVIEW_CONFIDENCE_THRESHOLD:.2f}）。"
            )

        chain_span = feature.get("chain_span")
        if reasoning_role == "none" and (
            self._dim6_has_high_burden_signal(feature)
            or DIM6_LOGIC_SIGNAL_PATTERN.search(question.raw_text or "")
        ):
            warnings.append("dim6 标记为 none，但题面或逻辑负担特征明显偏高。")
        if reasoning_role == "supporting" and self._dim6_has_high_burden_signal(feature):
            warnings.append("dim6 标记为 supporting，但逻辑链条控制特征明显偏高。")
        if chain_span == "1" and (
            feature.get("branch_control") == "multi_branch"
            or feature.get("verification_requirement") == "full_consistency"
            or feature.get("constraint_coupling") == "nested"
        ):
            warnings.append("dim6 链长标记偏低，与多分支或全局一致性特征冲突。")
        if (
            feature.get("branch_control") == "multi_branch"
            and feature.get("constraint_coupling") == "none"
            and feature.get("global_consistency_required") == 0
        ):
            warnings.append("dim6 标记为 multi_branch，但约束耦合和全局一致性信号明显不足。")
        if (
            feature.get("conclusion_stability") == "exhaustive"
            and feature.get("verification_requirement") == "none"
        ):
            warnings.append("dim6 标记为 exhaustive，但 verification_requirement 为 none。")

        for item in getattr(question, "parse_warnings", []) or []:
            text = str(item).strip()
            if any(marker in text for marker in ("残缺", "缺损", "截断", "识别失败", "公式增强识别失败")):
                warnings.append("dim6 题面存在 OCR 或题块质量问题，当前结果需人工复核。")
                break

        audit = getattr(question, "parse_audit", None)
        if getattr(audit, "block_completeness", 1.0) < 0.65:
            warnings.append("题块完整度不足，当前 dim6 结果需人工复核。")

        return warnings

    @staticmethod
    def _dim5_sublevel_rank(value: str) -> int:
        return {"low": 1, "mid": 2, "high": 3}.get(str(value or "").strip(), 0)

    @staticmethod
    def _dim5_family_rank(value: str) -> int:
        return {"1": 1, "2": 2, "3+": 3}.get(str(value or "").strip(), 0)

    def _infer_dim5_sublevel(self, feature: Dict[str, Any]) -> str:
        family_rank = self._dim5_family_rank(feature.get("knowledge_family_count", ""))
        integration = feature.get("knowledge_integration")
        novel_dependency = feature.get("novel_definition_dependency")
        competition_signal = feature.get("competition_signal")

        if (
            family_rank >= 3
            or integration == "cross_domain_bridge"
            or novel_dependency == "strong"
            or competition_signal == "strong"
        ):
            return "high"

        if (
            family_rank >= 2
            or integration in {"same_family_combo", "cross_family_combo"}
            or novel_dependency == "local"
            or competition_signal == "weak"
        ):
            return "mid"

        if feature.get("band") or feature.get("core_knowledge_units") or feature.get("knowledge_tags"):
            return "low"
        return ""

    def _finalize_dim5_feature(
        self,
        feature: Dict[str, Any],
        *,
        analysis_facts: Dict[str, Any],
        question_text: str = "",
        question_summary: str = "",
    ) -> Dict[str, Any]:
        normalized = dict(feature or {})
        primary_knowledge_point = self._dim5_primary_knowledge_point(
            normalized,
            analysis_facts=analysis_facts,
        )
        if primary_knowledge_point and not normalized.get("primary_knowledge_point"):
            normalized["primary_knowledge_point"] = primary_knowledge_point
            normalized["knowledge_point_source"] = self._dim5_primary_knowledge_source(
                primary_knowledge_point,
                normalized,
                analysis_facts=analysis_facts,
            )
        core_units = list(normalized.get("core_knowledge_units") or [])
        if not core_units:
            core_units = self._normalize_string_list(analysis_facts.get("core_knowledge_points"))
            normalized["core_knowledge_units"] = core_units

        knowledge_tags = list(normalized.get("knowledge_tags") or [])
        if not knowledge_tags:
            merged_tags = core_units + list(normalized.get("supporting_knowledge_units") or [])
            if not merged_tags:
                merged_tags = self._normalize_string_list(analysis_facts.get("core_knowledge_points"))
            normalized["knowledge_tags"] = list(dict.fromkeys(tag for tag in merged_tags if tag))

        graph_status = str(normalized.get("confidence_status") or "").strip()
        if graph_status == "confirmed":
            return normalized
        if graph_status in {"review_required", "ambiguous", "broad_category_only"}:
            normalized["knowledge_level"] = ""
            normalized["canonical_knowledge_point"] = ""
            normalized["canonical_knowledge_domain"] = ""
            normalized["primary_knowledge_point"] = ""
            normalized["knowledge_point_source"] = ""
            return normalized

        if normalized.get("dim5_excluded_reason") == "retry_failed":
            normalized["band"] = ""
            normalized["sublevel"] = ""
            normalized["knowledge_level"] = ""
            return normalized

        inferred_sublevel = self._infer_dim5_sublevel(normalized)
        current_sublevel = normalized.get("sublevel", "")
        if not current_sublevel and inferred_sublevel:
            normalized["sublevel"] = inferred_sublevel
        elif current_sublevel and inferred_sublevel:
            gap = abs(
                self._dim5_sublevel_rank(current_sublevel)
                - self._dim5_sublevel_rank(inferred_sublevel)
            )
            if gap >= 2:
                normalized["warning"] = self._merge_feature_warning(
                    normalized.get("warning", ""),
                    "sublevel 与知识整合特征明显冲突，当前结果需人工复核。",
                )
                normalized["need_manual_review"] = 1

        canonical = canonicalize_dim5_knowledge(
            normalized,
            analysis_facts=analysis_facts,
            question_text=question_text,
            question_summary=question_summary,
        )
        if canonical:
            normalized.update(canonical)
            canonical_point = canonical.get("canonical_knowledge_point")
            if canonical_point and not normalized.get("primary_knowledge_point"):
                normalized["primary_knowledge_point"] = canonical_point
                normalized["knowledge_point_source"] = "canonical"
            for key in ("core_knowledge_units", "knowledge_tags"):
                values = list(normalized.get(key) or [])
                if canonical_point and canonical_point not in values:
                    values.insert(0, canonical_point)
                normalized[key] = list(dict.fromkeys(item for item in values if item))
            family = canonical.get("canonical_knowledge_family")
            if family and not normalized.get("dim5_upshift_reason"):
                normalized["dim5_upshift_reason"] = "标准知识点归一后进入相邻高档候选。"

        return normalized

    @staticmethod
    def _dim5_first_nonempty(items: List[str]) -> str:
        return next((item.strip() for item in items if str(item or "").strip()), "")

    def _dim5_primary_knowledge_point(
        self,
        feature: Dict[str, Any],
        *,
        analysis_facts: Dict[str, Any],
    ) -> str:
        candidates: List[str] = []
        raw_points = analysis_facts.get("core_knowledge_points", [])
        if isinstance(raw_points, list):
            candidates.extend(str(item).strip() for item in raw_points if str(item).strip())
        for key in ("core_knowledge_units", "knowledge_tags", "supporting_knowledge_units"):
            raw = feature.get(key, [])
            if isinstance(raw, list):
                candidates.extend(str(item).strip() for item in raw if str(item).strip())
        return self._dim5_first_nonempty(candidates)

    def _dim5_primary_knowledge_source(
        self,
        primary_knowledge_point: str,
        feature: Dict[str, Any],
        *,
        analysis_facts: Dict[str, Any],
    ) -> str:
        if not primary_knowledge_point:
            return ""
        for item in analysis_facts.get("core_knowledge_points", []) or []:
            if str(item).strip() == primary_knowledge_point:
                return "analysis_facts"
        for key, source in (
            ("core_knowledge_units", "core_knowledge_units"),
            ("knowledge_tags", "knowledge_tags"),
            ("supporting_knowledge_units", "supporting_knowledge_units"),
        ):
            for item in feature.get(key, []) or []:
                if str(item).strip() == primary_knowledge_point:
                    return source
        return "derived"

    @classmethod
    def _dim5_combined_signal_text(
        cls,
        feature: Dict[str, Any],
        *,
        analysis_facts: Dict[str, Any],
        question_text: str = "",
        question_summary: str = "",
    ) -> str:
        parts: List[str] = [
            question_text,
            question_summary,
            str(feature.get("primary_knowledge_point") or ""),
            str(feature.get("canonical_knowledge_point") or ""),
            str(feature.get("canonical_knowledge_family") or ""),
            str(feature.get("evidence_summary") or ""),
            str(feature.get("competition_signal") or ""),
        ]
        for key in (
            "knowledge_tags",
            "core_knowledge_units",
            "supporting_knowledge_units",
            "method_tags",
            "evidence_tags",
            "canonical_alias_hits",
            "canonical_structure_hits",
        ):
            raw = feature.get(key, [])
            if isinstance(raw, list):
                parts.extend(str(item) for item in raw if str(item).strip())
        for key in ("core_knowledge_points", "core_methods", "visual_elements"):
            raw = analysis_facts.get(key, [])
            if isinstance(raw, list):
                parts.extend(str(item) for item in raw if str(item).strip())
        parts.append(str(analysis_facts.get("core_task") or ""))
        return " ".join(part for part in parts if str(part).strip())

    @classmethod
    def _dim5_has_direct_formula_guard(
        cls,
        feature: Dict[str, Any],
        *,
        analysis_facts: Dict[str, Any],
        question_text: str = "",
        question_summary: str = "",
    ) -> bool:
        signal_text = cls._dim5_combined_signal_text(
            feature,
            analysis_facts=analysis_facts,
            question_text=question_text,
            question_summary=question_summary,
        )
        return bool(DIM5_DIRECT_FORMULA_RETRY_BLOCK_PATTERN.search(signal_text))

    @classmethod
    def _dim5_has_olympiad_anchor(
        cls,
        feature: Dict[str, Any],
        *,
        analysis_facts: Dict[str, Any],
        question_text: str = "",
        question_summary: str = "",
    ) -> bool:
        signal_text = cls._dim5_combined_signal_text(
            feature,
            analysis_facts=analysis_facts,
            question_text=question_text,
            question_summary=question_summary,
        )
        return bool(DIM5_OLYMPIAD_ANCHOR_PATTERN.search(signal_text))

    @staticmethod
    def _dim5_band_values() -> List[str]:
        return list(BAND_SCORE_MAP.keys())

    @classmethod
    def _dim5_has_valid_band(cls, feature: Dict[str, Any]) -> bool:
        return _normalize_band(feature.get("band")) in BAND_SCORE_MAP

    @classmethod
    def _dim5_has_valid_band_and_sublevel(cls, feature: Dict[str, Any]) -> bool:
        band = _normalize_band(feature.get("band"))
        sublevel = _normalize_sublevel(feature.get("sublevel"))
        return band in BAND_SCORE_MAP and sublevel in DIM5_SUBLEVEL_VALUES

    @staticmethod
    def _dim5_has_valid_knowledge_level(feature: Dict[str, Any]) -> bool:
        return bool(normalize_dim5_knowledge_level(feature.get("knowledge_level")))

    @staticmethod
    def _dim4_has_valid_topic_level(feature: Dict[str, Any]) -> bool:
        return normalize_dim4_level(feature.get("topic_level")) in DIM4_TOPIC_LEVEL_VALUES

    def _dim4_candidate_knowledge_point(
        self,
        *,
        analysis_facts: Dict[str, Any],
        dim4_feature: Dict[str, Any],
        dim5_feature: Dict[str, Any],
    ) -> str:
        candidates: List[str] = []
        candidates.append(str(dim4_feature.get("knowledge_point") or "").strip())
        for key in ("core_knowledge_points", "core_methods"):
            raw = analysis_facts.get(key, [])
            if isinstance(raw, list):
                candidates.extend(str(item).strip() for item in raw if str(item).strip())
        for key in ("core_knowledge_units", "knowledge_tags"):
            raw = dim5_feature.get(key, [])
            if isinstance(raw, list):
                candidates.extend(str(item).strip() for item in raw if str(item).strip())
        return next((item for item in candidates if item), "")

    def _dim4_should_attempt_topic_level(
        self,
        *,
        raw_text: str,
        dim4_feature: Dict[str, Any],
        dim5_feature: Optional[Dict[str, Any]] = None,
        applicable_dimensions: List[Any],
        knowledge_point: str = "",
    ) -> bool:
        level_source = normalize_dim4_level_source(dim4_feature.get("level_source"))
        if self._dim4_has_valid_topic_level(dim4_feature) and level_source in {
            "question_bank",
            "knowledge_anchor",
            "llm_fallback",
        }:
            return False
        if level_source == "review_failed":
            return False

        declared_dim4 = any(
            str(item).strip() == "dim4"
            for item in applicable_dimensions
            if isinstance(applicable_dimensions, list)
        )
        has_dim4_feature_signal = any(
            str(dim4_feature.get(key) or "").strip()
            for key in (
                "strategy_role",
                "template_fit",
                "breakthrough_type",
                "strategy_shift_count",
                "construction_requirement",
                "exploration_space",
                "representation_reframe",
                "path_openness",
                "dead_end_risk",
                "evidence_summary",
                "anchor_evidence",
            )
        )
        has_raw_strategy_signal = bool(DIM4_STRATEGY_SIGNAL_PATTERN.search(str(raw_text or "")))
        has_topic_anchor = bool(
            knowledge_point and classify_dim4_topic_level(knowledge_point, raw_text, dim4_feature)
        )
        if not (
            declared_dim4
            or has_dim4_feature_signal
            or has_raw_strategy_signal
            or has_topic_anchor
            or (dim5_feature and self._dim5_feature_is_beyond(dim5_feature))
        ):
            return False
        if has_topic_anchor:
            return True
        if declared_dim4:
            return True
        if dim4_feature.get("strategy_role") == "core":
            return True
        if self._dim4_has_high_burden_signal(dim4_feature):
            return True
        if dim5_feature and self._dim5_feature_is_beyond(dim5_feature):
            return True
        return has_raw_strategy_signal

    def _apply_dim4_topic_anchor(
        self,
        normalized_features: Dict[str, Dict[str, Any]],
        *,
        question: ParsedQuestion,
        analysis_facts: Dict[str, Any],
    ) -> bool:
        dim4_feature = normalized_features["dim4_innovation"]
        knowledge_point = self._dim4_candidate_knowledge_point(
            analysis_facts=analysis_facts,
            dim4_feature=dim4_feature,
            dim5_feature=normalized_features["dim5_knowledge"],
        )
        if not knowledge_point:
            return False
        anchor = classify_dim4_topic_level(knowledge_point, question.raw_text, dim4_feature)
        if not anchor:
            dim4_feature["knowledge_point"] = knowledge_point
            return False

        merged = dict(dim4_feature)
        merged.update(anchor)
        if not merged.get("evidence_summary"):
            merged["evidence_summary"] = anchor.get("anchor_evidence", "")
        normalized_features["dim4_innovation"] = self._normalize_dim4_feature(merged)
        return True

    def _dim4_reference_candidates_for_fallback(
        self,
        *,
        question: ParsedQuestion,
        analysis_facts: Dict[str, Any],
        dim4_feature: Dict[str, Any],
        knowledge_point: str,
    ) -> List[Dict[str, Any]]:
        if not hasattr(self.reference_standard, "gaosi_question_candidates"):
            return []
        try:
            candidate_feature = dict(dim4_feature or {})
            if knowledge_point and not candidate_feature.get("knowledge_point"):
                candidate_feature["knowledge_point"] = knowledge_point
            return self.reference_standard.gaosi_question_candidates(
                candidate_feature,
                question_text=question.raw_text,
                question_summary=knowledge_point or question.raw_text[:80],
                analysis_facts=analysis_facts,
                limit=5,
            )
        except Exception as exc:
            logger.warning(
                "dim4 reference candidate lookup failed question=%s error=%s",
                question.question_no,
                exc,
            )
            return []

    @staticmethod
    def _has_high_quality_gaosi_candidate(candidates: List[Dict[str, Any]]) -> bool:
        return any(
            int(candidate.get("similarity_strength") or 0) >= 2
            and str(candidate.get("match_quality") or "") == "ok"
            for candidate in candidates
        )

    @classmethod
    def _dim5_feature_is_beyond(cls, feature: Dict[str, Any]) -> bool:
        if _normalize_band(feature.get("band")) == DIM5_BEYOND_BAND:
            return True
        section_level = cls._normalize_gaosi_section_level(
            feature.get("gaosi_section_level") or feature.get("gaosi_section_label")
        )
        return section_level == "challenge"

    @classmethod
    def _dim5_candidate_is_beyond(cls, candidate: Dict[str, Any]) -> bool:
        section_level = cls._normalize_gaosi_section_level(
            candidate.get("section_level")
            or candidate.get("gaosi_section_level")
            or candidate.get("section_label")
            or candidate.get("track")
        )
        if section_level == "challenge":
            return True
        return str(candidate.get("track") or "").strip() == "超越篇"

    @classmethod
    def _has_dim5_beyond_retry_candidate(cls, candidates: List[Dict[str, Any]]) -> bool:
        for candidate in candidates:
            if not cls._dim5_candidate_is_beyond(candidate):
                continue
            strength = int(candidate.get("similarity_strength") or 0)
            quality = str(candidate.get("match_quality") or "").strip()
            if strength >= 2 and quality in {"", "ok", "diagram_partial_match"}:
                return True
        return False

    def _build_dim4_topic_fallback_messages(
        self,
        *,
        question: ParsedQuestion,
        analysis_facts: Dict[str, Any],
        dim4_feature: Dict[str, Any],
        knowledge_point: str,
        reference_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        prompt_text = DIM4_TOPIC_FALLBACK_USER_PROMPT_TEMPLATE.format(
            question_no=question.question_no,
            question_type=getattr(question.question_type, "value", question.question_type),
            knowledge_point=knowledge_point,
            question_text=question.raw_text or "",
            analysis_facts_json=self._dim5_dump_json(
                {
                    "core_task": analysis_facts.get("core_task", ""),
                    "core_knowledge_points": analysis_facts.get("core_knowledge_points", []),
                    "core_methods": analysis_facts.get("core_methods", []),
                }
            ),
            dim4_feature_json=self._dim5_dump_json(dim4_feature),
            reference_candidates_json=self._dim5_dump_json(reference_candidates or []),
        ).strip()

        if self._should_attach_image(question):
            image_data_url = self._load_image_as_data_url(question.image_block_url or "")
            if image_data_url:
                return (
                    [
                        {"role": "system", "content": DIM4_TOPIC_FALLBACK_SYSTEM_PROMPT.strip()},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt_text},
                                {"type": "image_url", "image_url": {"url": image_data_url}},
                            ],
                        },
                    ],
                    True,
                )
        return (
            [
                {"role": "system", "content": DIM4_TOPIC_FALLBACK_SYSTEM_PROMPT.strip()},
                {"role": "user", "content": prompt_text},
            ],
            False,
        )

    def _parse_dim4_topic_fallback_response(self, response: str) -> Dict[str, Any]:
        payload = self._extract_json_body(response)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = json.loads(self._repair_common_json_issues(payload))
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _second_review_dimension_name(dim_code: str) -> str:
        if dim_code == "dim1":
            return "维度1：数学运算"
        if dim_code == "dim3":
            return "维度3：场景理解复杂度"
        if dim_code == "dim4":
            return "维度4：建模解题复杂度"
        if dim_code == "dim6":
            return "维度6：逻辑链条"
        return dim_code

    @staticmethod
    def _second_review_dimension_criteria(dim_code: str) -> str:
        if dim_code == "dim1":
            return (
                "只看计算执行是否构成核心门槛：是否需要完成稳定的算式运算、方程求解、"
                "比例/分数/百分数计算、结构变形、简便运算或嵌入应用题中的核心计算。"
                "重点核对试算验证、余数回查、长链消去、多比例消元、连续公式代入等是否真实存在。"
                "不要把题干长、知识点难、读题理解、建模策略、逻辑推理、辅助计算、"
                "普通概念识别、空间想象或 OCR 不清写成 dim1 依据；也不要沿用其他题号的证据。"
                "二次复评只补录 L2-L5 的核心计算负担；若只是一步直接算、口算、"
                "轻量代入或计算只是辅助步骤，请返回 not_applicable。"
            )
        if dim_code == "dim3":
            return (
                "只看读题层面：学生是否能读懂题目场景、规则、过程、反馈、"
                "比较口径、图文对应。不要把列式、方程、建表、分类、倒推、"
                "构造或解题策略写成 dim3 依据。"
            )
        if dim_code == "dim4":
            return (
                "只看读懂后的解题组织：是否需要整理条件、建立数量关系、"
                "建表/画图、分类、倒推、方案比较、构造、试探或换角度推进。"
                "不要把题干场景包装、来源标签、计算量或知识广度写成 dim4 依据。"
            )
        if dim_code == "dim6":
            return (
                "只看信息已提取、表示已建立、主要方法已选定之后，解法推进、隐含关系串联、"
                "分支控制、倒推、结果检验与约束回查是否构成核心门槛。不要把题干长度、"
                "计算量、知识点难度、方法新颖性、图形识别或普通竖式流程写成 dim6 依据。"
                "二次复评只补录核心逻辑链条题；若只能达到直接观察、直接代入或一两步常规"
                "检验的 L1/L2 负担，请返回 not_applicable。"
            )
        return ""

    @staticmethod
    def _second_review_level_rules(dim_code: str) -> str:
        if dim_code == "dim1":
            return (
                "L1 一步直接计算、口算或轻量代入；L2 常规两步计算、竖式/脱式、"
                "简单方程或常规单位换算；L3 多步嵌入计算、结构变形、分数小数百分数混合、"
                "定义运算展开或常规简便运算；L4 高错误压力计算，包括多阶段百分数/浓度/比例方程、"
                "连续公式代入、结构化裂项、多个中间量、系统性试算或余数回查；"
                "L5 竞赛型计算结构，包括长链裂项/消去、复杂定义运算、多位数字约束试算、"
                "多方程消元、参数化或全局约束下的连续计算。dim1 二次复评只有 L2-L5 可以返回 applicable；"
                "L1 请返回 not_applicable。"
            )
        if dim_code == "dim3":
            return (
                "L1 场景直读；L2 分清简单对象、动作顺序或图中对应；"
                "L3 读懂一个关键问法、比较口径、简单新定义或单一规则；"
                "L4 同时整合多个场景要素，例如对象、阶段、规则、图文对应、"
                "状态变化或比较条件；L5 多规则相互作用、条件触发、反馈判断"
                "或多阶段系统组成完整新规则系统。evidence_summary 必须写清具体"
                "读题要素，不要只泛泛写比较口径理解。"
            )
        if dim_code == "dim4":
            return (
                "L1 建立一个基础关系；L2 一次简单转化、一步方程、一次取数或轻度整理；"
                "L3 整理多条条件，建立常见数量关系、表格、方程、比例关系或简单方案比较；"
                "L4 多阶段、多对象、多关系、多方案、状态变化、倒推或分类框架；"
                "L5 自建整体解题结构，并结合隐藏条件、全局比较/回查、构造、试探、分类或换角度推进。"
            )
        if dim_code == "dim6":
            return (
                "L1 直接判断或一步推出；L2 一两步衔接、局部倒推或结果检验；"
                "L3 连续多步推进、显式分支判断、局部约束回查或简单倒推链；"
                "L4 多分支、多阶段、跨条件串联、倒推回查或约束耦合；"
                "L5 长链条、多条件全局一致性、穷举收束、全局最值或复杂回查。"
                "dim6 二次复评只有 L3-L5 可以返回 applicable；L1/L2 请返回 not_applicable。"
            )
        return ""

    def _build_second_review_messages(
        self,
        *,
        question: ParsedQuestion,
        dim_code: str,
        analysis_facts: Dict[str, Any],
        initial_feature: Dict[str, Any],
        initial_status: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], bool]:
        prompt_text = DIM_SECOND_REVIEW_USER_PROMPT_TEMPLATE.format(
            dimension_name=self._second_review_dimension_name(dim_code),
            question_no=question.question_no,
            question_type=getattr(question.question_type, "value", question.question_type),
            has_image="是" if self._should_attach_image(question) else "否",
            ocr_warnings="；".join(question.parse_warnings) if question.parse_warnings else "无",
            parse_audit_summary=self._format_parse_audit(question),
            question_text=question.raw_text or "",
            analysis_facts_json=self._dim5_dump_json(analysis_facts or {}),
            initial_feature_json=self._dim5_dump_json(initial_feature or {}),
            initial_status_json=self._dim5_dump_json(initial_status or {}),
            dimension_criteria=self._second_review_dimension_criteria(dim_code),
            level_rules=self._second_review_level_rules(dim_code),
        ).strip()

        if self._should_attach_image(question):
            image_data_url = self._load_image_as_data_url(question.image_block_url or "")
            if image_data_url:
                return (
                    [
                        {"role": "system", "content": DIM_SECOND_REVIEW_SYSTEM_PROMPT.strip()},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt_text},
                                {"type": "image_url", "image_url": {"url": image_data_url}},
                            ],
                        },
                    ],
                    True,
                )
        return (
            [
                {"role": "system", "content": DIM_SECOND_REVIEW_SYSTEM_PROMPT.strip()},
                {"role": "user", "content": prompt_text},
            ],
            False,
        )

    def _parse_second_review_response(self, response: str) -> Dict[str, Any]:
        payload = self._extract_json_body(response)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = json.loads(self._repair_common_json_issues(payload))
        if not isinstance(data, dict):
            raise ValueError("second review returned non-object JSON")
        return {
            "status": str(data.get("status") or "").strip().lower(),
            "level": str(data.get("level") or "").strip().upper(),
            "score": data.get("score", 0.0),
            "evidence_summary": str(data.get("evidence_summary") or "").strip(),
            "confidence": self._normalize_confidence(data.get("confidence")),
            "exclude_reason": str(data.get("exclude_reason") or "").strip(),
        }

    async def review_dim3_dim4_applicability(
        self,
        question: ParsedQuestion,
        *,
        dim_code: str,
        analysis_facts: Dict[str, Any],
        initial_feature: Dict[str, Any],
        initial_status: Dict[str, Any],
    ) -> Dict[str, Any]:
        if dim_code not in {"dim1", "dim3", "dim4", "dim6"}:
            raise ValueError("second review only supports dim1/dim3/dim4/dim6")

        messages, used_image = self._build_second_review_messages(
            question=question,
            dim_code=dim_code,
            analysis_facts=analysis_facts,
            initial_feature=initial_feature,
            initial_status=initial_status,
        )
        try:
            response = await self.llm.chat(messages, response_format=DEFAULT_JSON_RESPONSE_FORMAT)
            payload = self._parse_second_review_response(response)
            payload["used_image"] = used_image
            return payload
        except Exception as exc:
            logger.warning(
                "dim second review failed question=%s dim=%s error=%s",
                question.question_no,
                dim_code,
                exc,
            )
            return {
                "status": "unresolved",
                "level": "N/A",
                "score": 0.0,
                "evidence_summary": "",
                "confidence": 0.0,
                "exclude_reason": "题目信息不足或判定不稳定，二次复评未能形成稳定结论。",
                "used_image": used_image if "used_image" in locals() else False,
            }

    def _apply_dim4_topic_fallback_payload(
        self,
        feature: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        topic_level = normalize_dim4_level(payload.get("topic_level"))
        if not topic_level:
            raise ValueError("dim4 fallback returned invalid topic_level")
        confidence = self._normalize_confidence(payload.get("confidence"))
        merged = dict(feature or {})
        merged["knowledge_point"] = str(payload.get("knowledge_point") or merged.get("knowledge_point") or "").strip()
        merged["topic_level"] = topic_level
        merged["level_source"] = "llm_fallback"
        merged["anchor_evidence"] = str(payload.get("anchor_evidence") or "").strip()
        merged["fallback_used"] = True
        merged["fallback_confidence"] = confidence
        if not merged.get("evidence_summary"):
            merged["evidence_summary"] = merged["anchor_evidence"]
        if confidence < DIM4_REVIEW_CONFIDENCE_THRESHOLD:
            merged["warning"] = self._merge_feature_warning(
                merged.get("warning", ""),
                f"dim4 建模解题等级兜底判定置信度低于 {DIM4_REVIEW_CONFIDENCE_THRESHOLD:.2f}，自动评分结果需要谨慎解读。",
            )
        return self._normalize_dim4_feature(merged)

    def _mark_dim4_topic_fallback_failed(
        self,
        feature: Dict[str, Any],
        *,
        fallback_error: str,
    ) -> Dict[str, Any]:
        merged = dict(feature or {})
        merged["topic_level"] = ""
        merged["level_source"] = "review_failed"
        merged["fallback_used"] = True
        merged["fallback_error"] = str(fallback_error or "")[:240]
        merged["warning"] = self._merge_feature_warning(
            merged.get("warning", ""),
            "dim4 建模解题等级兜底判定失败；若缺少稳定建模事实，将不纳入自动评分。",
        )
        merged["applicability_confidence"] = 0.0
        return self._normalize_dim4_feature(merged)

    async def _ensure_dim4_topic_level(
        self,
        normalized_features: Dict[str, Dict[str, Any]],
        *,
        question: ParsedQuestion,
        analysis_facts: Dict[str, Any],
        applicable_dimensions: List[Any],
    ) -> None:
        dim4_feature = normalized_features["dim4_innovation"]
        knowledge_point = self._dim4_candidate_knowledge_point(
            analysis_facts=analysis_facts,
            dim4_feature=dim4_feature,
            dim5_feature=normalized_features["dim5_knowledge"],
        )
        if not self._dim4_should_attempt_topic_level(
            raw_text=question.raw_text,
            dim4_feature=dim4_feature,
            dim5_feature=normalized_features["dim5_knowledge"],
            applicable_dimensions=applicable_dimensions,
            knowledge_point=knowledge_point,
        ):
            return

        if hasattr(self.reference_standard, "calibrate_dim4_feature"):
            try:
                calibrated = self.reference_standard.calibrate_dim4_feature(
                    dim4_feature,
                    question_text=question.raw_text,
                    question_summary=question.raw_text[:80],
                    analysis_facts=analysis_facts,
                )
                if (
                    normalize_dim4_level_source(calibrated.get("level_source")) == "question_bank"
                    and self._dim4_has_valid_topic_level(calibrated)
                ):
                    normalized_features["dim4_innovation"] = self._normalize_dim4_feature(calibrated)
                    return
            except Exception as exc:
                logger.warning(
                    "dim4 question-bank profile calibration failed question=%s error=%s",
                    question.question_no,
                    exc,
                )

        dim4_feature = normalized_features["dim4_innovation"]
        knowledge_point = self._dim4_candidate_knowledge_point(
            analysis_facts=analysis_facts,
            dim4_feature=dim4_feature,
            dim5_feature=normalized_features["dim5_knowledge"],
        )
        reference_candidates = self._dim4_reference_candidates_for_fallback(
            question=question,
            analysis_facts=analysis_facts,
            dim4_feature=dim4_feature,
            knowledge_point=knowledge_point,
        )

        if not self._has_high_quality_gaosi_candidate(reference_candidates):
            if self._apply_dim4_topic_anchor(
                normalized_features,
                question=question,
                analysis_facts=analysis_facts,
            ):
                return
            dim4_feature = normalized_features["dim4_innovation"]
            knowledge_point = self._dim4_candidate_knowledge_point(
                analysis_facts=analysis_facts,
                dim4_feature=dim4_feature,
                dim5_feature=normalized_features["dim5_knowledge"],
            )
            reference_candidates = self._dim4_reference_candidates_for_fallback(
                question=question,
                analysis_facts=analysis_facts,
                dim4_feature=dim4_feature,
                knowledge_point=knowledge_point,
            )

        if reference_candidates:
            dim4_feature = dict(dim4_feature)
            dim4_feature["reference_matches"] = reference_candidates
            normalized_features["dim4_innovation"] = self._normalize_dim4_feature(dim4_feature)
            dim4_feature = normalized_features["dim4_innovation"]
        try:
            messages, used_image = self._build_dim4_topic_fallback_messages(
                question=question,
                analysis_facts=analysis_facts,
                dim4_feature=dim4_feature,
                knowledge_point=knowledge_point,
                reference_candidates=reference_candidates,
            )
            response = await self.llm.chat(
                messages,
                temperature=0.1,
                max_tokens=900,
                response_format=DEFAULT_JSON_RESPONSE_FORMAT,
            )
            payload = self._parse_dim4_topic_fallback_response(response)
            normalized_features["dim4_innovation"] = self._apply_dim4_topic_fallback_payload(
                dim4_feature,
                payload,
            )
            logger.info(
                "dim4 topic fallback succeeded question=%s used_image=%s level=%s",
                question.question_no,
                used_image,
                normalized_features["dim4_innovation"].get("topic_level"),
            )
        except Exception as exc:
            logger.warning(
                "dim4 topic fallback failed question=%s error=%s",
                question.question_no,
                exc,
            )
            normalized_features["dim4_innovation"] = self._mark_dim4_topic_fallback_failed(
                dim4_feature,
                fallback_error=str(exc),
            )

    @staticmethod
    def _dim5_dump_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)

    def _dim5_reference_candidates_for_retry(
        self,
        *,
        question: ParsedQuestion,
        question_summary: str,
        analysis_facts: Dict[str, Any],
        dim5_feature: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        if hasattr(self.reference_standard, "gaosi_question_candidates"):
            try:
                candidates.extend(
                    self.reference_standard.gaosi_question_candidates(
                        dim5_feature,
                        question_text=question.raw_text,
                        question_summary=question_summary,
                        analysis_facts=analysis_facts,
                        limit=5,
                    )
                    or []
                )
            except Exception as exc:
                logger.warning(
                    "dim5 GaoSi question candidate lookup failed question=%s error=%s",
                    question.question_no,
                    exc,
                )

        if hasattr(self.reference_standard, "dim5_topic_structure_candidates"):
            try:
                topic_structure_candidates = self.reference_standard.dim5_topic_structure_candidates(
                    dim5_feature,
                    question_text=question.raw_text,
                    question_summary=question_summary,
                    analysis_facts=analysis_facts,
                    limit=5,
                ) or []
                seen = {
                    (
                        str(candidate.get("source") or ""),
                        str(candidate.get("grade") or candidate.get("grade_hint") or ""),
                        str(candidate.get("lecture_title") or ""),
                        str(candidate.get("section_label") or candidate.get("track") or ""),
                        str(candidate.get("question_no") or ""),
                    )
                    for candidate in candidates
                }
                for candidate in topic_structure_candidates:
                    key = (
                        str(candidate.get("source") or ""),
                        str(candidate.get("grade") or candidate.get("grade_hint") or ""),
                        str(candidate.get("lecture_title") or ""),
                        str(candidate.get("section_label") or candidate.get("track") or ""),
                        str(candidate.get("question_no") or ""),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    candidates.append(candidate)
            except Exception as exc:
                logger.warning(
                    "dim5 topic-structure candidate lookup failed question=%s error=%s",
                    question.question_no,
                    exc,
                )
        if candidates:
            return candidates[:5]

        if not hasattr(self.reference_standard, "match_dimension"):
            return []
        try:
            calibration = self.reference_standard.match_dimension(
                "dim5",
                dim5_feature,
                question_text=question.raw_text,
                question_summary=question_summary,
                analysis_facts=analysis_facts,
            )
        except Exception as exc:
            logger.warning(
                "dim5 reference candidate lookup failed question=%s error=%s",
                question.question_no,
                exc,
            )
            return []

        for entry in getattr(calibration, "matched_entries", [])[:5]:
            candidates.append(
                {
                    "source": getattr(entry, "source", ""),
                    "title": getattr(entry, "title", ""),
                    "track": getattr(entry, "track", ""),
                    "grade_hint": getattr(entry, "grade_hint", ""),
                    "grade": getattr(entry, "grade", ""),
                    "lecture_title": getattr(entry, "lecture_title", ""),
                    "section_level": getattr(entry, "section_level", ""),
                    "section_label": getattr(entry, "section_label", ""),
                    "question_no": getattr(entry, "question_no", ""),
                }
            )
        return candidates

    @classmethod
    def _dim5_has_topic_structure_candidate(cls, candidates: List[Dict[str, Any]]) -> bool:
        return any(
            str(candidate.get("match_scope") or "") == "topic_structure"
            or str(candidate.get("match_action") or "") == "raise_band"
            or bool(candidate.get("dim5_topic_structure_band"))
            for candidate in candidates
        )

    def _dim5_should_retry_for_relaxed_hit(
        self,
        dim5_feature: Dict[str, Any],
        *,
        question: ParsedQuestion,
        question_summary: str,
        analysis_facts: Dict[str, Any],
        reference_candidates: List[Dict[str, Any]],
    ) -> bool:
        if self._dim5_has_direct_formula_guard(
            dim5_feature,
            analysis_facts=analysis_facts,
            question_text=question.raw_text or "",
            question_summary=question_summary,
        ):
            return False
        if self._dim5_feature_is_beyond(dim5_feature):
            return False

        band_source = str(dim5_feature.get("band_source") or "").strip()
        if band_source in DIM5_RELIABLE_BAND_SOURCES:
            return False

        has_gaosi_section = bool(
            self._normalize_gaosi_section_level(
                dim5_feature.get("gaosi_section_level") or dim5_feature.get("gaosi_section_label")
            )
        )
        if has_gaosi_section:
            return False

        if self._dim5_has_topic_structure_candidate(reference_candidates):
            return True
        has_relaxation_context = (
            dim5_feature.get("competition_signal") in {"weak", "strong"}
            or dim5_feature.get("knowledge_integration") in {
                "same_family_combo",
                "cross_family_combo",
                "cross_domain_bridge",
            }
            or dim5_feature.get("novel_definition_dependency") in {"local", "strong"}
        )
        if not has_relaxation_context:
            return False
        return self._dim5_has_olympiad_anchor(
            dim5_feature,
            analysis_facts=analysis_facts,
            question_text=question.raw_text or "",
            question_summary=question_summary,
        )

    def _build_dim5_retry_messages(
        self,
        *,
        question: ParsedQuestion,
        question_summary: str,
        analysis_facts: Dict[str, Any],
        dim5_feature: Dict[str, Any],
        reference_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], bool]:
        if reference_candidates is None:
            reference_candidates = self._dim5_reference_candidates_for_retry(
                question=question,
                question_summary=question_summary,
                analysis_facts=analysis_facts,
                dim5_feature=dim5_feature,
            )
        prompt_text = DIM5_BAND_RETRY_USER_PROMPT_TEMPLATE.format(
            question_no=question.question_no,
            question_type=getattr(question.question_type, "value", question.question_type),
            has_image="yes" if self._should_attach_image(question) else "no",
            question_text=question.raw_text or "",
            analysis_facts_json=self._dim5_dump_json(
                {
                    "core_task": analysis_facts.get("core_task", ""),
                    "core_knowledge_points": analysis_facts.get("core_knowledge_points", []),
                    "core_methods": analysis_facts.get("core_methods", []),
                }
            ),
            dim5_feature_json=self._dim5_dump_json(dim5_feature),
            reference_candidates_json=self._dim5_dump_json(reference_candidates),
            band_values_json=self._dim5_dump_json(self._dim5_band_values()),
        ).strip()

        if self._should_attach_image(question):
            image_data_url = self._load_image_as_data_url(question.image_block_url or "")
            if image_data_url:
                return (
                    [
                        {"role": "system", "content": DIM5_BAND_RETRY_SYSTEM_PROMPT.strip()},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt_text},
                                {"type": "image_url", "image_url": {"url": image_data_url}},
                            ],
                        },
                    ],
                    True,
                )

        return (
            [
                {"role": "system", "content": DIM5_BAND_RETRY_SYSTEM_PROMPT.strip()},
                {"role": "user", "content": prompt_text},
            ],
            False,
        )

    def _parse_dim5_retry_response(self, response: str) -> Dict[str, Any]:
        payload = self._extract_json_body(response)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = json.loads(self._repair_common_json_issues(payload))
        return data if isinstance(data, dict) else {}

    def _apply_dim5_retry_payload(
        self,
        feature: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized_payload = self._normalize_dim5_feature(
            {
                "gaosi_grade": payload.get("gaosi_grade"),
                "gaosi_section_level": payload.get("gaosi_section_level"),
                "gaosi_section_label": payload.get("gaosi_section_label"),
                "gaosi_classification_source": payload.get("gaosi_classification_source"),
                "band": payload.get("band"),
                "sublevel": payload.get("sublevel"),
                "evidence_summary": payload.get("evidence_summary"),
                "knowledge_tags": payload.get("knowledge_tags"),
                "core_knowledge_units": payload.get("core_knowledge_units"),
                "applicability_confidence": payload.get("confidence"),
                "primary_knowledge_point": payload.get("primary_knowledge_point"),
                "knowledge_point_source": payload.get("knowledge_point_source"),
            }
        )
        normalized_payload["band"] = _normalize_band(normalized_payload.get("band"))
        normalized_payload["sublevel"] = _normalize_sublevel(normalized_payload.get("sublevel"))
        gaosi_band, gaosi_sublevel = self._dim5_gaosi_band_and_sublevel(
            normalized_payload.get("gaosi_grade", ""),
            normalized_payload.get("gaosi_section_level", ""),
        )
        if gaosi_band:
            normalized_payload["band"] = gaosi_band
            normalized_payload["sublevel"] = gaosi_sublevel

        if not self._dim5_has_valid_band_and_sublevel(normalized_payload):
            raise ValueError("dim5 retry returned invalid band/sublevel")

        merged = dict(feature or {})
        for key in (
            "band",
            "sublevel",
            "evidence_summary",
            "knowledge_tags",
            "core_knowledge_units",
            "applicability_confidence",
            "gaosi_grade",
            "gaosi_section_level",
            "gaosi_section_label",
            "primary_knowledge_point",
            "knowledge_point_source",
        ):
            value = normalized_payload.get(key)
            if value not in ("", None, [], {}):
                merged[key] = value

        retry_confidence = normalized_payload.get("applicability_confidence", 0.0)
        merged["band_source"] = "llm_dim5_retry"
        merged["gaosi_classification_source"] = "llm_retry"
        merged["dim5_retry_used"] = True
        merged["dim5_retry_confidence"] = retry_confidence
        merged["dim5_fallback_mode"] = "llm_band_retry"
        if not merged.get("dim5_upshift_reason"):
            merged["dim5_upshift_reason"] = "LLM 兜底在核心知识点下完成知识广度档位判定。"
        if retry_confidence < DIM5_RETRY_LOW_CONFIDENCE_THRESHOLD:
            merged["warning"] = self._merge_feature_warning(
                merged.get("warning", ""),
                f"dim5 二次知识档位判定置信度低于 {DIM5_RETRY_LOW_CONFIDENCE_THRESHOLD:.2f}，当前结果需人工复核。",
            )
            merged["need_manual_review"] = 1
        return merged

    def _mark_dim5_retry_failed(
        self,
        feature: Dict[str, Any],
        *,
        retry_error: str,
    ) -> Dict[str, Any]:
        merged = dict(feature or {})
        merged["band"] = ""
        merged["sublevel"] = ""
        merged["band_source"] = "llm_dim5_retry_failed"
        merged["dim5_retry_used"] = True
        merged["dim5_retry_error"] = str(retry_error or "")[:240]
        merged["dim5_excluded_reason"] = "retry_failed"
        merged["applicability_confidence"] = 0.0
        merged["need_manual_review"] = 0
        merged["gaosi_classification_source"] = ""
        return merged

    def _try_fill_dim5_from_reference(
        self,
        normalized_features: Dict[str, Dict[str, Any]],
        *,
        question: ParsedQuestion,
        question_summary: str,
        analysis_facts: Dict[str, Any],
    ) -> bool:
        if not hasattr(self.reference_standard, "calibrate_feature"):
            return False

        dim5_feature = normalized_features["dim5_knowledge"]
        try:
            candidate = self.reference_standard.calibrate_feature(
                "dim5",
                dim5_feature,
                question_text=question.raw_text,
                question_summary=question_summary,
                analysis_facts=analysis_facts,
            )
        except Exception as exc:
            logger.warning(
                "dim5 reference classification failed question=%s error=%s",
                question.question_no,
                exc,
            )
            return False

        normalized_candidate = self._normalize_dim5_feature(candidate)
        if not self._dim5_has_valid_band_and_sublevel(normalized_candidate):
            return False
        normalized_candidate = self._finalize_dim5_feature(
            normalized_candidate,
            analysis_facts=analysis_facts,
            question_text=question.raw_text,
            question_summary=question_summary,
        )

        normalized_features["dim5_knowledge"] = normalized_candidate
        logger.info(
            "dim5 reference classification filled missing band question=%s band=%s",
            question.question_no,
            normalized_candidate.get("band"),
        )
        return True

    async def _ensure_dim5_band_with_retry(
        self,
        normalized_features: Dict[str, Dict[str, Any]],
        *,
        question: ParsedQuestion,
        question_summary: str,
        analysis_facts: Dict[str, Any],
        retry_required: bool = False,
    ) -> None:
        dim5_feature = normalized_features["dim5_knowledge"]
        reference_candidates: Optional[List[Dict[str, Any]]] = None
        optional_beyond_retry = False
        relaxed_retry = False
        if self._dim5_has_valid_knowledge_level(dim5_feature):
            return
        if not retry_required and self._dim5_has_valid_band_and_sublevel(dim5_feature):
            if self._dim5_feature_is_beyond(dim5_feature):
                return
            reference_candidates = self._dim5_reference_candidates_for_retry(
                question=question,
                question_summary=question_summary,
                analysis_facts=analysis_facts,
                dim5_feature=dim5_feature,
            )
            if not self._has_dim5_beyond_retry_candidate(reference_candidates):
                relaxed_retry = self._dim5_should_retry_for_relaxed_hit(
                    dim5_feature,
                    question=question,
                    question_summary=question_summary,
                    analysis_facts=analysis_facts,
                    reference_candidates=reference_candidates,
                )
                if not relaxed_retry:
                    return
            else:
                optional_beyond_retry = True

        if (
            not retry_required
            and not optional_beyond_retry
            and not relaxed_retry
            and self._dim5_has_valid_band_and_sublevel(dim5_feature)
        ):
            return

        messages, used_image = self._build_dim5_retry_messages(
            question=question,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
            dim5_feature=dim5_feature,
            reference_candidates=reference_candidates,
        )
        try:
            response = await self.llm.chat(
                messages,
                temperature=0.1,
                max_tokens=1200,
                response_format=DEFAULT_JSON_RESPONSE_FORMAT,
            )
            payload = self._parse_dim5_retry_response(response)
            normalized_features["dim5_knowledge"] = self._apply_dim5_retry_payload(dim5_feature, payload)
            logger.info(
                "dim5 retry succeeded question=%s used_image=%s band=%s",
                question.question_no,
                used_image,
                normalized_features["dim5_knowledge"].get("band"),
            )
        except Exception as exc:
            logger.warning(
                "dim5 retry failed question=%s error=%s",
                question.question_no,
                exc,
            )
            if optional_beyond_retry and self._dim5_has_valid_band_and_sublevel(dim5_feature):
                kept = dict(dim5_feature)
                kept["dim5_retry_used"] = True
                kept["dim5_retry_error"] = str(exc)[:240]
                kept["band_source"] = kept.get("band_source") or "model_with_beyond_retry_failed"
                kept["warning"] = self._merge_feature_warning(
                    kept.get("warning", ""),
                    "dim5 超越篇候选二次确认失败，已保留模型原始知识档位，当前结果需人工复核。",
                )
                kept["need_manual_review"] = 1
                normalized_features["dim5_knowledge"] = kept
            elif relaxed_retry and self._dim5_has_valid_band_and_sublevel(dim5_feature):
                kept = dict(dim5_feature)
                kept["dim5_retry_used"] = True
                kept["dim5_retry_error"] = str(exc)[:240]
                kept["band_source"] = kept.get("band_source") or "model_with_relaxed_retry_failed"
                kept["dim5_fallback_mode"] = "relaxed_retry_failed_kept_model"
                kept["warning"] = self._merge_feature_warning(
                    kept.get("warning", ""),
                    "dim5 中度放宽二次判定失败，已保留模型原始知识档位，当前结果需人工复核。",
                )
                kept["need_manual_review"] = 1
                normalized_features["dim5_knowledge"] = kept
            else:
                normalized_features["dim5_knowledge"] = self._mark_dim5_retry_failed(
                    dim5_feature,
                    retry_error=str(exc),
                )

    def _dim5_validation_warnings(
        self,
        feature: Dict[str, Any],
        analysis_facts: Dict[str, Any],
        *,
        confidence: float,
    ) -> List[str]:
        warnings: List[str] = []
        if feature.get("dim5_excluded_reason") == "retry_failed":
            return warnings
        has_knowledge_level = self._dim5_has_valid_knowledge_level(feature)
        if not has_knowledge_level and not feature.get("band"):
            warnings.append("dim5 缺少知识门槛 band，当前结果需人工复核。")
        if not has_knowledge_level and not feature.get("sublevel"):
            warnings.append("dim5 缺少档内层级 sublevel，当前结果需人工复核。")

        stable_knowledge_evidence = (
            feature.get("core_knowledge_units")
            or feature.get("knowledge_tags")
            or analysis_facts.get("core_knowledge_points")
        )
        if (feature.get("band") or has_knowledge_level) and not stable_knowledge_evidence:
            warnings.append("dim5 缺少稳定知识点依据，当前结果需人工复核。")

        dim5_confidence = feature.get("applicability_confidence", 0.0) or confidence
        if dim5_confidence < DIM5_REVIEW_CONFIDENCE_THRESHOLD:
            warnings.append(
                f"dim5 置信度低于自动判分阈值（{DIM5_REVIEW_CONFIDENCE_THRESHOLD:.2f}），当前结果需人工复核。"
            )

        if (
            feature.get("knowledge_family_count") == "1"
            and feature.get("knowledge_integration") in {"cross_family_combo", "cross_domain_bridge"}
        ):
            warnings.append("dim5 知识家族数与整合方式冲突，当前结果需人工复核。")

        inferred_sublevel = self._infer_dim5_sublevel(feature)
        current_sublevel = feature.get("sublevel", "")
        if current_sublevel and inferred_sublevel:
            gap = abs(
                self._dim5_sublevel_rank(current_sublevel)
                - self._dim5_sublevel_rank(inferred_sublevel)
            )
            if gap >= 2:
                warnings.append("dim5 sublevel 与知识整合特征明显冲突，当前结果需人工复核。")

        if feature.get("competition_signal") == "strong" and current_sublevel == "low":
            warnings.append("dim5 竞赛信号较强，但 sublevel 标记偏低，当前结果需人工复核。")
        if feature.get("novel_definition_dependency") == "strong" and current_sublevel == "low":
            warnings.append("dim5 新定义依赖较强，但 sublevel 标记偏低，当前结果需人工复核。")

        return warnings

    @classmethod
    def _infer_applicable_dimensions(
        cls,
        features: Dict[str, Dict[str, Any]],
        analysis_facts: Dict[str, Any],
    ) -> List[str]:
        inferred: List[str] = []

        dim1 = features["dim1_computation"]
        if dim1.get("calc_role") == "core":
            inferred.append("dim1")

        dim2 = features["dim2_spatial"]
        if (
            dim2.get("spatial_role") == "core"
            or cls._dim2_has_core_geometry_model(dim2)
            or cls._dim2_has_stable_geometry_scope(dim2)
        ):
            inferred.append("dim2")

        dim3 = features["dim3_information"]
        if dim3.get("information_role") == "core" and not cls._dim3_is_low_barrier_direct_extraction(dim3):
            inferred.append("dim3")

        inferred.append("dim4")

        dim5 = features["dim5_knowledge"]
        if (
            cls._dim5_has_valid_knowledge_level(dim5)
            or (
                dim5.get("dim5_excluded_reason") != "retry_failed"
                and cls._dim5_has_valid_band_and_sublevel(dim5)
            )
        ):
            inferred.append("dim5")

        dim6 = features["dim6_logic"]
        if dim6.get("reasoning_role") == "core" and not cls._dim6_is_low_barrier_direct_push(dim6):
            inferred.append("dim6")

        return inferred

    @staticmethod
    def _load_image_as_data_url(image_path: str) -> Optional[str]:
        try:
            path = Path(image_path)
            if not path.exists() or not path.is_file():
                return None

            mime_type, _ = mimetypes.guess_type(path.name)
            mime_type = mime_type or "image/jpeg"
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"data:{mime_type};base64,{encoded}"
        except Exception as exc:
            logger.warning("读取题块图片失败 %s: %s", image_path, exc)
            return None

    def _should_attach_image(self, question: ParsedQuestion) -> bool:
        if not question.image_block_url:
            return False
        if DIM2_SHORT_GEOMETRY_IMAGE_PATTERN.search(question.raw_text or ""):
            return True
        audit = question.parse_audit
        if audit:
            if audit.image_required_hint or getattr(audit, "image_attach_recommended", False):
                return True
            if getattr(audit, "visual_category", "") in {
                "table_chart",
                "geometry_visual",
                "geometry_context",
                "spatial_3d",
                "explicit_visual",
                "multi_part_layout",
            }:
                return True
        if question.sub_item_candidates:
            return True
        return bool(VISUAL_SIGNAL_PATTERN.search(question.raw_text or ""))

    @staticmethod
    def _format_sub_item_candidates(question: ParsedQuestion) -> str:
        if not question.sub_item_candidates:
            return "无"
        return "；".join(
            f"{candidate.candidate_no}:{candidate.raw_text[:36]}"
            for candidate in question.sub_item_candidates[:4]
        )

    @staticmethod
    def _format_parse_audit(question: ParsedQuestion) -> str:
        if not question.parse_audit:
            return "无"
        audit = question.parse_audit
        notes = [
            f"anchor={audit.anchor_confidence:.2f}",
            f"score={audit.score_confidence:.2f}",
            f"block={audit.block_completeness:.2f}",
            f"image={audit.image_strategy}",
        ]
        if getattr(audit, "visual_category", ""):
            notes.append(f"visual={audit.visual_category}")
        if getattr(audit, "formula_strategy", ""):
            notes.append(f"formula={audit.formula_strategy}")
        if audit.cross_page_merged:
            notes.append("cross_page=1")
        if audit.warning_codes:
            notes.append(f"codes={'/'.join(audit.warning_codes[:4])}")
        return "，".join(notes)

    @staticmethod
    def _build_system_prompt() -> str:
        return f"{QUESTION_ANALYSIS_SYSTEM_PROMPT}\n\n{STRICT_JSON_OUTPUT_INSTRUCTIONS.strip()}"

    def _get_dim5_retrieval_service(self) -> Dim5RetrievalService:
        service = getattr(self, "dim5_retrieval", None)
        if isinstance(service, Dim5RetrievalService):
            return service
        service = Dim5RetrievalService(self.reference_standard)
        self.dim5_retrieval = service
        return service

    def _get_dim5_grounding_service(self) -> Dim5KnowledgeGroundingService:
        service = getattr(self, "dim5_grounding", None)
        if isinstance(service, Dim5KnowledgeGroundingService):
            return service
        service = Dim5KnowledgeGroundingService(self.reference_standard)
        self.dim5_grounding = service
        return service

    def _build_dim5_grounding_context(
        self,
        question: ParsedQuestion,
        *,
        analysis_facts: Optional[Dict[str, Any]] = None,
        max_candidates: int = 8,
    ) -> Dict[str, Any]:
        try:
            return self._get_dim5_grounding_service().ground(
                question_text=question.raw_text or "",
                question_type=str(getattr(question.question_type, "value", question.question_type) or ""),
                analysis_facts=analysis_facts or {},
                max_candidates=max_candidates,
            )
        except Exception as exc:
            logger.warning(
                "dim5 grounding failed question=%s error=%s",
                question.question_no,
                exc,
            )
            return {
                "version": DIM5_GROUNDING_VERSION,
                "query": {"text_excerpt": (question.raw_text or "")[:180]},
                "candidates": [],
                "selection_status": "no_match",
                "selected_candidate_id": "no_match",
                "grounded_canonical_knowledge_point": "",
                "grounded_knowledge_domain": "",
                "grounded_knowledge_source_text": "",
                "grounded_knowledge_level": "",
                "grounded_confidence": 0.0,
                "grounded_match_source": "",
                "grounded_evidence": str(exc)[:240],
                "grounded_risk_flags": ["grounding_error"],
                "grounded_rejected_candidates": [],
                "grounded_selector": "local_grounding_selector",
            }

    def _apply_dim5_grounding(
        self,
        dim5_feature: Dict[str, Any],
        *,
        question: ParsedQuestion,
        analysis_facts: Dict[str, Any],
    ) -> Dict[str, Any]:
        if (
            str((dim5_feature or {}).get("grounded_selector") or "") == "llm_candidate_selector"
            and str((dim5_feature or {}).get("selected_knowledge_candidate_id") or "").strip()
        ):
            return self._normalize_dim5_feature(dim5_feature)
        grounding = self._build_dim5_grounding_context(
            question,
            analysis_facts=analysis_facts,
        )
        merged = dict(dim5_feature or {})
        merged["knowledge_grounding_context"] = {
            "version": grounding.get("version", DIM5_GROUNDING_VERSION),
            "query": grounding.get("query", {}),
            "selection_status": grounding.get("selection_status", ""),
        }
        merged["knowledge_grounding_candidates"] = list(grounding.get("candidates") or [])
        merged["grounded_selection_status"] = str(grounding.get("selection_status") or "").strip()
        merged["selected_knowledge_candidate_id"] = str(
            grounding.get("selected_candidate_id") or ""
        ).strip()
        for key in (
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
            merged[key] = grounding.get(key)
        return self._normalize_dim5_feature(merged)

    def _get_dim5_graph_matcher(self) -> Dim5KnowledgeGraphMatcher:
        service = getattr(self, "dim5_graph_matcher", None)
        if isinstance(service, Dim5KnowledgeGraphMatcher):
            return service
        service = get_dim5_knowledge_graph_matcher()
        self.dim5_graph_matcher = service
        return service

    def _apply_dim5_graph_grounding(
        self,
        dim5_feature: Dict[str, Any],
        *,
        question: ParsedQuestion,
        analysis_facts: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged = dict(dim5_feature or {})
        if str(merged.get("dim5_excluded_reason") or "").strip() == "retry_failed":
            return self._normalize_dim5_feature(merged)
        try:
            graph_result = self._get_dim5_graph_matcher().match(
                question_text=question.raw_text or "",
                question_type=str(getattr(question.question_type, "value", question.question_type) or ""),
                analysis_facts=analysis_facts,
                dim5_feature=merged,
            )
        except Exception as exc:
            logger.warning(
                "dim5 knowledge graph match failed question=%s error=%s",
                question.question_no,
                exc,
            )
            merged["confidence_status"] = "review_required"
            merged["failure_reason"] = f"graph_error:{str(exc)[:160]}"
            merged["need_manual_review"] = 1
            return self._normalize_dim5_feature(merged)

        for key in (
            "graph_version",
            "dim5_structure_facts",
            "candidate_knowledge_points",
            "selected_candidate_id",
            "rejected_candidates",
            "confidence_status",
            "failure_reason",
            "knowledge_point_id",
            "knowledge_point_name",
            "knowledge_domain",
            "knowledge_track",
            "knowledge_track_label",
            "knowledge_grade",
            "knowledge_grade_label",
            "knowledge_semester",
            "knowledge_display_name",
        ):
            merged[key] = graph_result.get(key)

        if graph_result.get("confidence_status") == "confirmed":
            point_name = str(graph_result.get("knowledge_point_name") or "").strip()
            domain = str(graph_result.get("knowledge_domain") or "").strip()
            level = normalize_dim5_knowledge_level(graph_result.get("knowledge_level"))
            confidence = self._normalize_confidence(graph_result.get("confidence"))
            merged["knowledge_level"] = level
            merged["canonical_knowledge_point"] = point_name
            merged["canonical_knowledge_domain"] = domain
            if not str(merged.get("primary_knowledge_point") or "").strip():
                merged["primary_knowledge_point"] = point_name
            merged["knowledge_point_source"] = "dim5_knowledge_graph"
            merged["level_source"] = "dim5_knowledge_graph"
            merged["level_evidence"] = str(graph_result.get("evidence") or "").strip()
            merged["canonical_match_source"] = "dim5_knowledge_graph"
            merged["canonical_match_confidence"] = confidence
            merged["grounded_selection_status"] = "selected"
            merged["selected_knowledge_candidate_id"] = str(
                graph_result.get("selected_candidate_id") or ""
            ).strip()
            merged["grounded_canonical_knowledge_point"] = point_name
            merged["grounded_knowledge_domain"] = domain
            merged["grounded_knowledge_source_text"] = str(
                graph_result.get("knowledge_display_name")
                or graph_result.get("knowledge_track_label")
                or ""
            ).strip()
            merged["grounded_knowledge_level"] = level
            merged["grounded_confidence"] = confidence
            merged["grounded_evidence"] = str(graph_result.get("evidence") or "").strip()
            merged["grounded_match_source"] = "dim5_knowledge_graph"
            merged["grounded_risk_flags"] = []
            merged["grounded_rejected_candidates"] = list(
                graph_result.get("rejected_candidates") or []
            )
            merged["grounded_selector"] = "dim5_knowledge_graph"
            for key in ("core_knowledge_units", "knowledge_tags"):
                values = list(merged.get(key) or [])
                if point_name:
                    values.insert(0, point_name)
                merged[key] = list(dict.fromkeys(item for item in values if item))
        else:
            if graph_result.get("confidence_status") in {
                "review_required",
                "ambiguous",
                "broad_category_only",
            }:
                merged["knowledge_level"] = ""
                merged["canonical_knowledge_point"] = ""
                merged["canonical_knowledge_domain"] = ""
        return self._normalize_dim5_feature(merged)

    @staticmethod
    def _dim5_grounding_high_enough(feature: Dict[str, Any]) -> bool:
        try:
            confidence = float(feature.get("grounded_confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < GROUNDING_USE_CONFIDENCE_THRESHOLD:
            return False
        risks = {
            str(flag).strip()
            for flag in feature.get("grounded_risk_flags", []) or []
            if str(flag).strip()
        }
        return not (
            risks
            & {
                "analysis_facts_only",
                "blocked_number_theory_in_calculation",
                "weak_question_text_match",
                "no_grounded_match",
            }
        )

    def _build_dim5_grounding_selection_messages(
        self,
        *,
        question: ParsedQuestion,
        analysis_facts: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        trimmed_facts = {
            "core_task": analysis_facts.get("core_task", ""),
            "core_knowledge_points": analysis_facts.get("core_knowledge_points", []),
            "core_methods": analysis_facts.get("core_methods", []),
        }
        candidate_payload = [
            {
                "candidate_id": candidate.get("candidate_id", ""),
                "knowledge_point": candidate.get("canonical_knowledge_point", ""),
                "knowledge_domain": candidate.get("knowledge_domain", ""),
                "source_label": candidate.get("source_label", ""),
                "matched_evidence": candidate.get("matched_evidence", []),
                "match_source": candidate.get("match_source", ""),
                "score": candidate.get("score", 0.0),
                "risk_flags": candidate.get("risk_flags", []),
                "rejected_contexts": candidate.get("excluded_contexts", []),
                "confusing_with": candidate.get("confusing_with", []),
            }
            for candidate in candidates[:8]
        ]
        prompt_text = DIM5_GROUNDED_SELECTION_USER_PROMPT_TEMPLATE.format(
            question_no=question.question_no,
            question_type=getattr(question.question_type, "value", question.question_type),
            question_text=question.raw_text or "",
            analysis_facts_json=self._dim5_dump_json(trimmed_facts),
            candidates_json=self._dim5_dump_json(candidate_payload),
        ).strip()
        return [
            {"role": "system", "content": DIM5_GROUNDED_SELECTION_SYSTEM_PROMPT.strip()},
            {"role": "user", "content": prompt_text},
        ]

    def _parse_dim5_grounding_selection_response(self, response: str) -> Dict[str, Any]:
        payload = self._extract_json_body(response)
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = json.loads(self._repair_common_json_issues(payload))
        return data if isinstance(data, dict) else {}

    def _apply_dim5_grounding_selection_payload(
        self,
        feature: Dict[str, Any],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        candidates = list(feature.get("knowledge_grounding_candidates") or [])
        by_id = {
            str(candidate.get("candidate_id") or ""): candidate
            for candidate in candidates
            if isinstance(candidate, dict)
        }
        selected_id = str(payload.get("selected_candidate_id") or "").strip()
        merged = dict(feature or {})
        if selected_id == "no_match" or selected_id not in by_id:
            merged["grounded_selection_status"] = "no_match"
            merged["selected_knowledge_candidate_id"] = "no_match"
            merged["grounded_confidence"] = 0.0
            merged["grounded_evidence"] = str(payload.get("evidence") or "no_match").strip()
            merged["grounded_selector"] = "llm_candidate_selector"
            merged["grounded_risk_flags"] = ["no_grounded_match"]
            return self._normalize_dim5_feature(merged)

        candidate = by_id[selected_id]
        confidence = self._normalize_confidence(payload.get("confidence"))
        risk_flags = self._normalize_string_list(candidate.get("risk_flags"))
        if "analysis_facts_only" in risk_flags:
            confidence = min(confidence, 0.54)
        merged["grounded_selection_status"] = "selected"
        merged["selected_knowledge_candidate_id"] = selected_id
        merged["grounded_canonical_knowledge_point"] = str(
            candidate.get("canonical_knowledge_point") or ""
        ).strip()
        merged["grounded_knowledge_domain"] = str(candidate.get("knowledge_domain") or "").strip()
        merged["grounded_knowledge_source_text"] = str(candidate.get("source_label") or "").strip()
        merged["grounded_knowledge_level"] = normalize_dim5_knowledge_level(
            candidate.get("recommended_level")
        )
        merged["grounded_confidence"] = confidence
        merged["grounded_match_source"] = str(candidate.get("match_source") or "").strip()
        merged["grounded_evidence"] = str(payload.get("evidence") or "").strip() or str(
            "、".join(candidate.get("matched_evidence", [])[:4])
        )
        merged["grounded_risk_flags"] = risk_flags
        merged["grounded_rejected_candidates"] = self._normalize_dict_list(
            payload.get("rejected_candidates")
        )
        merged["grounded_selector"] = "llm_candidate_selector"
        return self._normalize_dim5_feature(merged)

    async def _ensure_dim5_grounding_with_llm(
        self,
        normalized_features: Dict[str, Dict[str, Any]],
        *,
        question: ParsedQuestion,
        analysis_facts: Dict[str, Any],
    ) -> None:
        if not getattr(settings, "DIM5_GROUNDED_LLM_ENABLED", False):
            return
        dim5_feature = normalized_features["dim5_knowledge"]
        candidates = list(dim5_feature.get("knowledge_grounding_candidates") or [])
        if not candidates:
            return
        if self._dim5_grounding_high_enough(dim5_feature):
            return
        messages = self._build_dim5_grounding_selection_messages(
            question=question,
            analysis_facts=analysis_facts,
            candidates=candidates,
        )
        try:
            response = await self.llm.chat(
                messages,
                temperature=0.0,
                max_tokens=900,
                response_format=DEFAULT_JSON_RESPONSE_FORMAT,
            )
            payload = self._parse_dim5_grounding_selection_response(response)
            normalized_features["dim5_knowledge"] = self._apply_dim5_grounding_selection_payload(
                dim5_feature,
                payload,
            )
        except Exception as exc:
            logger.warning(
                "dim5 grounded selector failed question=%s error=%s",
                question.question_no,
                exc,
            )

    def _build_dim5_retrieval_context(
        self,
        question: ParsedQuestion,
        *,
        question_summary: str = "",
        analysis_facts: Optional[Dict[str, Any]] = None,
        dim5_feature: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            return self._get_dim5_retrieval_service().retrieve(
                question_text=question.raw_text or "",
                question_summary=question_summary or (question.raw_text or "")[:120],
                analysis_facts=analysis_facts or {},
                dim5_feature=dim5_feature or {},
                limit_per_scope=3,
                overall_limit=9,
            )
        except Exception as exc:
            logger.warning(
                "dim5 retrieval failed question=%s error=%s",
                question.question_no,
                exc,
            )
            return {
                "version": "dim5_retrieval_v1",
                "query": {"terms": [], "direct_formula_guard": False},
                "candidates": [],
                "knowledge_point_candidates": [],
                "topic_structure_candidates": [],
                "reference_question_candidates": [],
                "top_recommendation": {},
                "error": str(exc)[:240],
            }

    def _attach_dim5_retrieval_context(
        self,
        dim5_feature: Dict[str, Any],
        *,
        question: ParsedQuestion,
        question_summary: str,
        analysis_facts: Dict[str, Any],
    ) -> Dict[str, Any]:
        context = self._build_dim5_retrieval_context(
            question,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
            dim5_feature=dim5_feature,
        )
        merged = dict(dim5_feature or {})
        merged["dim5_retrieval_context"] = context
        merged["dim5_retrieval_candidates"] = list(context.get("candidates") or [])
        return merged

    def _build_prompt(self, question: ParsedQuestion) -> Tuple[List[Dict[str, Any]], bool]:
        system_prompt = self._build_system_prompt()
        prompt_text = QUESTION_ANALYSIS_USER_PROMPT_TEMPLATE.format(
            question_no=question.question_no,
            page_no=question.page_no,
            question_type=getattr(question.question_type, "value", question.question_type),
            has_image="是" if self._should_attach_image(question) else "否",
            ocr_warnings="；".join(question.parse_warnings) if question.parse_warnings else "无",
            sub_item_candidates=self._format_sub_item_candidates(question),
            parse_audit_summary=self._format_parse_audit(question),
            question_text=question.raw_text,
        )

        if self._should_attach_image(question):
            image_data_url = self._load_image_as_data_url(question.image_block_url or "")
            if image_data_url:
                return (
                    [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt_text},
                                {"type": "image_url", "image_url": {"url": image_data_url}},
                            ],
                        },
                    ],
                    True,
                )

        return (
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_text},
            ],
            False,
        )

    @staticmethod
    def _extract_json_body(response: str) -> str:
        json_str = response
        if "```json" in response:
            json_str = response.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in response:
            json_str = response.split("```", 1)[1].split("```", 1)[0]
        return json_str.strip()

    @staticmethod
    def _response_head(response: str, limit: int = JSON_RESPONSE_HEAD_LIMIT) -> str:
        normalized = str(response or "").strip()
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit].rstrip()}..."

    @staticmethod
    def _next_non_whitespace_char(payload: str, start_index: int) -> str:
        index = start_index
        while index < len(payload) and payload[index].isspace():
            index += 1
        return payload[index] if index < len(payload) else ""

    @staticmethod
    def _strip_trailing_commas(payload: str) -> str:
        return re.sub(r",(\s*[}\]])", r"\1", payload)

    def _escape_unescaped_inner_quotes(self, payload: str) -> str:
        result: List[str] = []
        in_string = False
        escape_next = False

        for index, char in enumerate(payload):
            if escape_next:
                result.append(char)
                escape_next = False
                continue

            if char == "\\" and in_string:
                result.append(char)
                escape_next = True
                continue

            if char == '"':
                if not in_string:
                    in_string = True
                    result.append(char)
                    continue

                next_char = self._next_non_whitespace_char(payload, index + 1)
                if next_char in {":", ",", "}", "]", ""}:
                    in_string = False
                    result.append(char)
                else:
                    result.append('\\"')
                continue

            result.append(char)

        return "".join(result)

    def _repair_common_json_issues(self, payload: str) -> str:
        repaired = payload.strip()
        repaired = self._repair_truncated_json(repaired)
        repaired = self._strip_trailing_commas(repaired)
        repaired = self._escape_unescaped_inner_quotes(repaired)
        repaired = self._strip_trailing_commas(repaired)
        return repaired

    def _build_json_repair_messages(
        self,
        payload: str,
        parse_error: str,
    ) -> List[Dict[str, str]]:
        return [
            {"role": "system", "content": JSON_REPAIR_SYSTEM_PROMPT.strip()},
            {
                "role": "user",
                "content": JSON_REPAIR_USER_PROMPT_TEMPLATE.format(
                    schema_hint=JSON_REPAIR_SCHEMA_HINT.strip(),
                    parse_error=parse_error,
                    broken_json=payload,
                ),
            },
        ]

    def _repair_truncated_json(self, payload: str) -> str:
        in_string = False
        escape_next = False
        stack: List[str] = []
        last_safe_pos = 0

        for index, char in enumerate(payload):
            if escape_next:
                escape_next = False
                continue
            if char == "\\" and in_string:
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue

            if char in ("{", "["):
                stack.append(char)
            elif char in ("}", "]"):
                if stack:
                    stack.pop()
                    if not stack:
                        last_safe_pos = index + 1
            elif char == "," and len(stack) == 1:
                last_safe_pos = index

        if not stack:
            return payload

        truncated = payload[:last_safe_pos].rstrip().rstrip(",")
        closing = "".join("}" if token == "{" else "]" for token in reversed(stack))
        repaired = truncated + closing
        logger.warning(
            "LLM JSON 响应疑似截断：原始长度=%s 修复后长度=%s",
            len(payload),
            len(repaired),
        )
        return repaired

    async def _repair_json_with_llm(
        self,
        payload: str,
        parse_error: str,
    ) -> str:
        repair_messages = self._build_json_repair_messages(payload, parse_error)
        return await self.llm.chat(
            repair_messages,
            response_format=DEFAULT_JSON_RESPONSE_FORMAT,
        )

    async def _load_json_response(
        self,
        response: str,
        question: ParsedQuestion,
    ) -> Tuple[Dict[str, Any], str]:
        payload = self._extract_json_body(response)

        try:
            data = json.loads(payload)
            logger.info("%s question=%s", JSON_REPAIR_STATUS_DIRECT, question.question_no)
            return data, JSON_REPAIR_STATUS_DIRECT
        except json.JSONDecodeError as direct_error:
            local_payload = self._repair_common_json_issues(payload)
            if local_payload != payload:
                try:
                    data = json.loads(local_payload)
                    logger.warning(
                        "%s question=%s direct_error=%s",
                        JSON_REPAIR_STATUS_LOCAL,
                        question.question_no,
                        direct_error,
                    )
                    return data, JSON_REPAIR_STATUS_LOCAL
                except json.JSONDecodeError as local_error:
                    local_parse_error = local_error
            else:
                local_parse_error = direct_error

            try:
                repaired_response = await self._repair_json_with_llm(payload, str(local_parse_error))
                repaired_payload = self._repair_common_json_issues(self._extract_json_body(repaired_response))
                data = json.loads(repaired_payload)
                logger.warning(
                    "%s question=%s direct_error=%s",
                    JSON_REPAIR_STATUS_LLM,
                    question.question_no,
                    direct_error,
                )
                return data, JSON_REPAIR_STATUS_LLM
            except Exception as repair_error:
                logger.error(
                    "%s question=%s direct_error=%s local_error=%s repair_error=%s response_head=%s",
                    JSON_REPAIR_STATUS_FAILED,
                    question.question_no,
                    direct_error,
                    local_parse_error,
                    repair_error,
                    self._response_head(response),
                )
                raise repair_error

    @staticmethod
    def _has_required_structure(data: Dict[str, Any]) -> bool:
        if not isinstance(data, dict):
            return False
        if not isinstance(data.get("features"), dict):
            return False
        if not isinstance(data.get("question_summary", ""), str):
            return False
        return True

    def _build_failed_features(
        self,
        question: ParsedQuestion,
        *,
        reason: str,
        warning: Optional[str] = None,
        json_repair_status: str = JSON_REPAIR_STATUS_FAILED,
    ) -> QuestionFeatures:
        warnings = [warning] if warning else []
        return QuestionFeatures(
            question_id="",
            question_no=question.question_no,
            question_summary="解析失败",
            confidence=0.0,
            reasoning=reason,
            warnings=warnings,
            need_manual_review=True,
            visual_mode="failed",
            parse_failed=True,
            json_repair_status=json_repair_status,
        )

    @staticmethod
    def _is_failed_features(features: QuestionFeatures) -> bool:
        return bool(getattr(features, "parse_failed", False))

    def _validate_dimension_features(
        self,
        normalized_features: Dict[str, Dict[str, Any]],
        analysis_facts: Dict[str, Any],
        *,
        confidence: float,
        question: ParsedQuestion,
    ) -> List[str]:
        warnings: List[str] = []

        dim1 = normalized_features["dim1_computation"]
        warnings.extend(self._dim1_validation_warnings(dim1, confidence=confidence, question=question))

        dim2 = normalized_features["dim2_spatial"]
        warnings.extend(self._dim2_validation_warnings(dim2, confidence=confidence, question=question))

        dim3 = normalized_features["dim3_information"]
        warnings.extend(self._dim3_validation_warnings(dim3, confidence=confidence, question=question))

        dim4 = normalized_features["dim4_innovation"]
        warnings.extend(self._dim4_validation_warnings(dim4, confidence=confidence, question=question))

        dim6 = normalized_features["dim6_logic"]
        warnings.extend(self._dim6_validation_warnings(dim6, confidence=confidence, question=question))

        dim5 = normalized_features["dim5_knowledge"]
        warnings.extend(
            self._dim5_validation_warnings(
                dim5,
                analysis_facts,
                confidence=confidence,
            )
        )

        return warnings

    def _apply_reference_calibration(
        self,
        normalized_features: Dict[str, Dict[str, Any]],
        *,
        question: ParsedQuestion,
        question_summary: str,
        analysis_facts: Dict[str, Any],
    ) -> Dict[str, Any]:
        calibration_audits: Dict[str, Any] = {}
        if hasattr(self.reference_standard, "calibrate_dim4_feature"):
            normalized_features["dim4_innovation"] = self.reference_standard.calibrate_dim4_feature(
                normalized_features["dim4_innovation"],
                question_text=question.raw_text,
                question_summary=question_summary,
                analysis_facts=analysis_facts,
            )
        else:
            normalized_features["dim4_innovation"] = self.reference_standard.calibrate_feature(
                "dim4",
                normalized_features["dim4_innovation"],
                question_text=question.raw_text,
                question_summary=question_summary,
                analysis_facts=analysis_facts,
            )
        calibration_audits["dim4"] = normalized_features["dim4_innovation"].get("calibration", {})
        for dim_code, feature_key in (("dim5", "dim5_knowledge"),):
            normalized_features[feature_key] = self.reference_standard.calibrate_feature(
                dim_code,
                normalized_features[feature_key],
                question_text=question.raw_text,
                question_summary=question_summary,
                analysis_facts=analysis_facts,
            )
            normalized_features[feature_key] = self._attach_dim5_retrieval_context(
                normalized_features[feature_key],
                question=question,
                question_summary=question_summary,
                analysis_facts=analysis_facts,
            )
            normalized_features[feature_key] = self._apply_dim5_grounding(
                normalized_features[feature_key],
                question=question,
                analysis_facts=analysis_facts,
            )
            normalized_features[feature_key] = self._apply_dim5_graph_grounding(
                normalized_features[feature_key],
                question=question,
                analysis_facts=analysis_facts,
            )
            normalized_features[feature_key] = self._finalize_dim5_feature(
                normalized_features[feature_key],
                analysis_facts=analysis_facts,
                question_text=question.raw_text,
                question_summary=question_summary,
            )
            calibration_audits[dim_code] = normalized_features[feature_key].get("calibration", {})
        return calibration_audits

    def _build_question_features_from_data(
        self,
        data: Dict[str, Any],
        *,
        question: ParsedQuestion,
        warnings: List[str],
        json_repair_status: str,
    ) -> QuestionFeatures:
        feature_map = data.get("features", {})
        normalized_features = self._normalize_dimension_features(feature_map)
        analysis_facts = self._normalize_analysis_facts(data.get("analysis_facts"))
        confidence = float(data.get("confidence", 0.0) or 0.0)
        question_summary = str(data.get("question_summary", "")).strip() or question.raw_text[:80]
        normalized_features["dim5_knowledge"] = self._attach_dim5_retrieval_context(
            normalized_features["dim5_knowledge"],
            question=question,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
        )
        normalized_features["dim5_knowledge"] = self._apply_dim5_grounding(
            normalized_features["dim5_knowledge"],
            question=question,
            analysis_facts=analysis_facts,
        )
        normalized_features["dim5_knowledge"] = self._apply_dim5_graph_grounding(
            normalized_features["dim5_knowledge"],
            question=question,
            analysis_facts=analysis_facts,
        )
        normalized_features["dim5_knowledge"] = self._finalize_dim5_feature(
            normalized_features["dim5_knowledge"],
            analysis_facts=analysis_facts,
            question_text=question.raw_text,
            question_summary=question_summary,
        )

        if not analysis_facts:
            warnings.append("LLM 未返回稳定 facts，当前结果需人工复核。")

        applicable_dimensions = data.get("applicable_dimensions", [])
        if not isinstance(applicable_dimensions, list):
            applicable_dimensions = []
            warnings.append("LLM 未返回合法的适用维度列表，已按事实和特征字段推断。")

        calibration_audits = self._apply_reference_calibration(
            normalized_features,
            question=question,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
        )

        warnings.extend(
            self._validate_dimension_features(
                normalized_features,
                analysis_facts,
                confidence=confidence,
                question=question,
            )
        )

        inferred_dimensions = self._infer_applicable_dimensions(normalized_features, analysis_facts)
        provided_dimensions: set[str] = set()
        for item in applicable_dimensions:
            dim_code = str(item).strip()
            if dim_code not in DIMENSION_FEATURE_KEYS:
                continue
            if dim_code == "dim5":
                dim5 = normalized_features["dim5_knowledge"]
                if (
                    not self._dim5_has_valid_knowledge_level(dim5)
                    and (
                        dim5.get("dim5_excluded_reason") == "retry_failed"
                        or not self._dim5_has_valid_band_and_sublevel(dim5)
                    )
                ):
                    continue
            provided_dimensions.add(dim_code)
        applicable_dimensions = sorted(
            provided_dimensions | set(inferred_dimensions)
        )
        if not applicable_dimensions:
            warnings.append("LLM 未稳定识别到适用维度，当前结果需人工复核。")

        per_dim_warnings: List[str] = []
        need_manual_review = json_repair_status == JSON_REPAIR_STATUS_LLM or not analysis_facts
        for feature_key, feature in normalized_features.items():
            dim_code = feature_key.split("_", 1)[0]
            warning = str(feature.get("warning", "")).strip()
            if warning:
                per_dim_warnings.append(f"{dim_code} {warning}")
            if dim_code != "dim4" and feature.get("need_manual_review") in (1, True):
                need_manual_review = True
        warnings.extend(per_dim_warnings)

        if any(message.startswith(("dim1 ", "dim2 ", "dim3 ", "dim5 ", "dim6 ")) for message in warnings):
            need_manual_review = True

        return QuestionFeatures(
            question_id="",
            question_no=question.question_no,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
            applicable_dimensions=applicable_dimensions,
            dim1_computation=normalized_features["dim1_computation"],
            dim2_spatial=normalized_features["dim2_spatial"],
            dim3_information=normalized_features["dim3_information"],
            dim4_innovation=normalized_features["dim4_innovation"],
            dim5_knowledge=normalized_features["dim5_knowledge"],
            dim6_logic=normalized_features["dim6_logic"],
            confidence=confidence,
            reasoning=str(data.get("reasoning", "") or "").strip(),
            warnings=warnings,
            need_manual_review=need_manual_review or bool(question.parse_warnings),
            calibration_audits=calibration_audits,
            json_repair_status=json_repair_status,
        )

    async def _build_question_features_from_data_with_retry(
        self,
        data: Dict[str, Any],
        *,
        question: ParsedQuestion,
        warnings: List[str],
        json_repair_status: str,
    ) -> QuestionFeatures:
        feature_map = data.setdefault("features", {})
        normalized_features = self._normalize_dimension_features(feature_map)
        analysis_facts = self._normalize_analysis_facts(data.get("analysis_facts"))
        question_summary = str(data.get("question_summary", "")).strip() or question.raw_text[:80]
        dim5_retry_required = not self._dim5_has_valid_band_and_sublevel(
            normalized_features["dim5_knowledge"]
        )
        dim5_reference_filled = False
        if (
            not self._dim5_has_valid_knowledge_level(normalized_features["dim5_knowledge"])
            and not self._dim5_has_valid_band_and_sublevel(normalized_features["dim5_knowledge"])
        ):
            dim5_reference_filled = self._try_fill_dim5_from_reference(
                normalized_features,
                question=question,
                question_summary=question_summary,
                analysis_facts=analysis_facts,
            )
        await self._ensure_dim5_band_with_retry(
            normalized_features,
            question=question,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
            retry_required=dim5_retry_required and not dim5_reference_filled,
        )
        applicable_dimensions = data.get("applicable_dimensions", [])
        if not isinstance(applicable_dimensions, list):
            applicable_dimensions = []
        await self._ensure_dim4_topic_level(
            normalized_features,
            question=question,
            analysis_facts=analysis_facts,
            applicable_dimensions=applicable_dimensions,
        )
        normalized_features["dim5_knowledge"] = self._apply_dim5_grounding(
            normalized_features["dim5_knowledge"],
            question=question,
            analysis_facts=analysis_facts,
        )
        await self._ensure_dim5_grounding_with_llm(
            normalized_features,
            question=question,
            analysis_facts=analysis_facts,
        )
        normalized_features["dim5_knowledge"] = self._apply_dim5_graph_grounding(
            normalized_features["dim5_knowledge"],
            question=question,
            analysis_facts=analysis_facts,
        )
        feature_map["dim4_innovation"] = normalized_features["dim4_innovation"]
        feature_map["dim5_knowledge"] = normalized_features["dim5_knowledge"]
        return self._build_question_features_from_data(
            data,
            question=question,
            warnings=warnings,
            json_repair_status=json_repair_status,
        )

    def _parse_response(self, response: str, question: ParsedQuestion) -> QuestionFeatures:
        warnings: List[str] = []
        repaired = False

        try:
            payload = self._extract_json_body(response)
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                payload = self._repair_truncated_json(payload)
                data = json.loads(payload)
                repaired = True

            if not self._has_required_structure(data):
                return self._build_failed_features(
                    question,
                    reason="LLM 响应缺少关键字段，无法可靠解析。",
                    warning="LLM 响应结构不完整，已转入人工复核路径。",
                )

            if repaired:
                warnings.append("LLM 响应疑似被截断，本题已自动转入低置信复核路径。")
            return self._build_question_features_from_data(
                data,
                question=question,
                warnings=warnings,
                json_repair_status=(
                    JSON_REPAIR_STATUS_LOCAL if repaired else JSON_REPAIR_STATUS_DIRECT
                ),
            )
        except json.JSONDecodeError as exc:
            logger.error("JSON 解析失败 question=%s response_head=%s", question.question_no, response[:200])
            return self._build_failed_features(question, reason=f"JSON 解析错误: {exc}")
        except Exception as exc:
            logger.error("LLM 响应解析失败 question=%s: %s", question.question_no, exc)
            return self._build_failed_features(question, reason=f"响应解析异常: {exc}")

    async def _parse_response_with_repairs(
        self,
        response: str,
        question: ParsedQuestion,
    ) -> QuestionFeatures:
        warnings: List[str] = []

        try:
            data, json_repair_status = await self._load_json_response(response, question)

            if not self._has_required_structure(data):
                return self._build_failed_features(
                    question,
                    reason="LLM 响应缺少关键字段，无法可靠解析。",
                    warning="LLM 响应结构不完整，已转入人工复核路径。",
                )

            if json_repair_status == JSON_REPAIR_STATUS_LOCAL:
                warnings.append("LLM JSON 已本地修复")
            elif json_repair_status == JSON_REPAIR_STATUS_LLM:
                warnings.append("LLM JSON 已二次修复")
            return await self._build_question_features_from_data_with_retry(
                data,
                question=question,
                warnings=warnings,
                json_repair_status=json_repair_status,
            )
        except json.JSONDecodeError as exc:
            logger.error(
                "JSON repair failed question=%s response_head=%s",
                question.question_no,
                self._response_head(response),
            )
            return self._build_failed_features(
                question,
                reason=f"JSON 解析错误: {exc}",
                warning="LLM JSON 修复失败",
            )
        except Exception as exc:
            logger.error("LLM response parse failed question=%s: %s", question.question_no, exc)
            return self._build_failed_features(
                question,
                reason=f"响应解析异常: {exc}",
                warning="LLM JSON 修复失败",
            )

    async def parse_question(self, question: ParsedQuestion) -> QuestionFeatures:
        logger.info("开始解析题号 %s", question.question_no)
        messages, used_image = self._build_prompt(question)

        try:
            image_fallback = False
            try:
                response = await self.llm.chat(
                    messages,
                    response_format=DEFAULT_JSON_RESPONSE_FORMAT,
                )
            except Exception:
                if not used_image:
                    raise
                image_fallback = True
                logger.warning("题号 %s 多模态调用失败，回退到纯文本分析。", question.question_no)
                messages = [
                    {"role": "system", "content": self._build_system_prompt()},
                    {
                        "role": "user",
                        "content": QUESTION_ANALYSIS_USER_PROMPT_TEMPLATE.format(
                            question_no=question.question_no,
                            page_no=question.page_no,
                            question_type=getattr(question.question_type, "value", question.question_type),
                            has_image="否",
                            ocr_warnings="；".join(question.parse_warnings) if question.parse_warnings else "无",
                            sub_item_candidates=self._format_sub_item_candidates(question),
                            parse_audit_summary=self._format_parse_audit(question),
                            question_text=question.raw_text,
                        ),
                    },
                ]
                response = await self.llm.chat(
                    messages,
                    response_format=DEFAULT_JSON_RESPONSE_FORMAT,
                )

            features = await self._parse_response_with_repairs(response, question)
            features.used_image = used_image and not image_fallback
            features.image_fallback = image_fallback
            features.visual_mode = "multimodal" if features.used_image else ("text_fallback" if image_fallback else "text_only")

            if image_fallback:
                features.warnings.append("多模态分析失败，当前题目按纯文本回退判断。")
                features.need_manual_review = True

            logger.info(
                "题号 %s 解析完成 confidence=%.2f manual_review=%s",
                question.question_no,
                features.confidence,
                features.need_manual_review,
            )
            logger.info(
                "JSON repair status question=%s status=%s",
                question.question_no,
                features.json_repair_status,
            )
            return features
        except Exception as exc:
            logger.error("题号 %s 解析失败: %s", question.question_no, exc)
            return self._build_failed_features(question, reason=f"LLM 调用失败: {exc}")

    async def parse_paper(
        self,
        parsed_paper: ParsedPaper,
        concurrency: int = 5,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]] = None,
        question_timeout_seconds: float = QUESTION_PARSE_TIMEOUT_SECONDS,
    ) -> List[QuestionFeatures]:
        questions = parsed_paper.questions
        total_questions = len(questions)
        batch_started_at = time.monotonic()
        logger.info(
            "Entering llm batch parse total=%s concurrency=%s timeout=%.1fs",
            total_questions,
            concurrency,
            question_timeout_seconds,
        )
        logger.info("开始批量解析试卷，共 %s 题，最大并发 %s", len(questions), concurrency)

        semaphore = asyncio.Semaphore(concurrency)
        progress_lock = asyncio.Lock()
        completed_count = 0

        async def publish_progress(
            question: ParsedQuestion,
            features: QuestionFeatures,
            elapsed_seconds: float,
        ) -> None:
            nonlocal completed_count

            async with progress_lock:
                completed_count += 1
                progress_payload = {
                    "completed": completed_count,
                    "total": total_questions,
                    "question_no": question.question_no,
                    "success": not self._is_failed_features(features),
                    "elapsed_seconds": elapsed_seconds,
                }

            if not progress_callback:
                return

            try:
                maybe_result = progress_callback(progress_payload)
                if asyncio.iscoroutine(maybe_result):
                    await maybe_result
            except Exception as exc:
                logger.warning("Failed to publish llm progress question=%s: %s", question.question_no, exc)

        async def parse_with_semaphore(question: ParsedQuestion) -> QuestionFeatures:
            async with semaphore:
                question_started_at = time.monotonic()
                logger.info("LLM request started question=%s", question.question_no)

                try:
                    features = await asyncio.wait_for(
                        self.parse_question(question),
                        timeout=question_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    elapsed_seconds = time.monotonic() - question_started_at
                    features = self._build_failed_features(
                        question,
                        reason=f"LLM request timed out after {question_timeout_seconds:.0f}s",
                        warning="LLM 超时/异常，已继续处理其他题目。",
                    )
                    logger.warning(
                        "LLM request timed out question=%s elapsed=%.2fs timeout=%.2fs",
                        question.question_no,
                        elapsed_seconds,
                        question_timeout_seconds,
                    )
                    await publish_progress(question, features, elapsed_seconds)
                    return features
                except Exception as exc:
                    elapsed_seconds = time.monotonic() - question_started_at
                    features = self._build_failed_features(
                        question,
                        reason=f"LLM request failed: {exc}",
                        warning="LLM 超时/异常，已继续处理其他题目。",
                    )
                    logger.exception(
                        "LLM request failed question=%s elapsed=%.2fs",
                        question.question_no,
                        elapsed_seconds,
                    )
                    await publish_progress(question, features, elapsed_seconds)
                    return features

                elapsed_seconds = time.monotonic() - question_started_at
                parse_succeeded = not self._is_failed_features(features)
                if parse_succeeded:
                    logger.info(
                        "LLM request finished question=%s success=%s elapsed=%.2fs",
                        question.question_no,
                        True,
                        elapsed_seconds,
                    )
                else:
                    logger.warning(
                        "LLM request finished question=%s success=%s elapsed=%.2fs",
                        question.question_no,
                        False,
                        elapsed_seconds,
                    )

                await publish_progress(question, features, elapsed_seconds)
                return features

        features_list = await asyncio.gather(*(parse_with_semaphore(question) for question in questions))
        success_count = sum(1 for item in features_list if not self._is_failed_features(item))
        repair_status_counts = {
            JSON_REPAIR_STATUS_DIRECT: 0,
            JSON_REPAIR_STATUS_LOCAL: 0,
            JSON_REPAIR_STATUS_LLM: 0,
            JSON_REPAIR_STATUS_FAILED: 0,
        }
        for item in features_list:
            status = getattr(item, "json_repair_status", JSON_REPAIR_STATUS_DIRECT)
            if status in repair_status_counts:
                repair_status_counts[status] += 1
        logger.info("试卷解析完成，成功 %s/%s 题", success_count, len(questions))
        failure_count = total_questions - success_count
        logger.info(
            "LLM batch parse finished success=%s failure=%s total=%s elapsed=%.2fs",
            success_count,
            failure_count,
            total_questions,
            time.monotonic() - batch_started_at,
        )
        logger.info(
            "LLM json repair stats direct=%s local=%s llm=%s failed=%s",
            repair_status_counts[JSON_REPAIR_STATUS_DIRECT],
            repair_status_counts[JSON_REPAIR_STATUS_LOCAL],
            repair_status_counts[JSON_REPAIR_STATUS_LLM],
            repair_status_counts[JSON_REPAIR_STATUS_FAILED],
        )
        return list(features_list)


def create_ai_parser(
    api_key: Optional[str] = None,
    model: str = "claude-sonnet-4-5",
    base_url: str = "https://one-api.aixuexi.com/v1",
    max_tokens: int = 2800,
    timeout: float = 75.0,
    llm_pool: str = "question",
) -> AIParser:
    client = MoonshotClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        temperature=0.3,
        max_tokens=max_tokens,
        timeout=timeout,
        llm_pool=llm_pool,
    )
    return AIParser(llm_client=client)
