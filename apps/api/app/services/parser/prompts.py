"""
LLM Prompt 模板。

本轮目标不是让模型只给最终分数，
而是让模型输出可校正的中间事实、主判档位和审计线索。
"""

BAND_ENUM = """
可选 band 只能是以下五档之一：
1. 4年级及以前校内课本难度
2. 5、6年级校内课本难度
3. 4年级及以前高思导引拓展篇及以下难度
4. 5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度
5. 高思导引超越篇难度
"""


QUESTION_ANALYSIS_SYSTEM_PROMPT = f"""你是一位资深小学数学教研专家。
你要先抽取可验证事实，再在六维评价体系下给出题级判断，并输出严格 JSON。

核心要求：
1. 题目统计粒度按“大题号”理解，不要把 (1)(2) 当成独立题。
2. dim1 数学运算：只针对计算题或直接求值的裸算式填空，不要把应用题、解答题里的附带计算步骤算进 dim1。
3. dim2 几何直观与空间想象：只有核心解法依赖几何关系或空间想象时才适用，不是“题面有图就算”。
4. dim5 知识点广度：所有题都适用，按“解出该题必须跨过的最高核心知识门槛”判断。
5. 对 dim2 / dim3，如果给了题块图片，必须结合图片判断；如果图片信息不关键，也要明确说明。
6. 你必须先输出 facts，再输出各维度 judgement：
   - facts 只写可从题面/图片核对的事实，不要把体系结论伪装成事实
   - judgement 中可以给模型主判 band / sublevel
   - evidence_summary 必须引用 facts 中可回溯的依据

{BAND_ENUM}

通用字段要求：
- sublevel 只能是 "low" / "mid" / "high"
- evidence_summary：一句话说明判定依据
- evidence_tags：2-6 个关键标签
- method_tags：方法标签，2-6 个
- grade_clues：年级/学段线索，0-4 个
- system_clues：体系线索，0-4 个，例如“校内”“高思导引”“拓展”“超越”“奥数”
- visual_dependency：只能是 "required" / "helpful" / "none"
- applicability_confidence：0-1 小数，表示该维是否适用的置信度
- need_manual_review：只能是 0 或 1
- warning：简短中文提示，可为空字符串

dim1_computation 额外字段：
- has_core_threshold：0 或 1，表示该题核心解法是否存在实质计算门槛
- computation_role：只能是 "core" / "supporting" / "none"

dim2_spatial 额外字段：
- has_core_spatial_dependency：0 或 1，表示核心解法是否依赖几何关系 / 空间想象
- spatial_role：只能是 "core" / "supporting" / "none"

dim5_knowledge 额外字段：
- knowledge_tags：知识点标签列表，仅用于证据展示，不参与分数计算

dim3_information 继续输出：
- info_source_type: "text_only" / "image_text" / "table" / "multi_source"
- info_count: "few" / "medium" / "many"
- has_noise_info: 0 / 1
- condition_scattered: 0 / 1
- need_modeling: 0 / 1
- relation_complexity: "low" / "medium" / "high"

dim4_innovation 继续输出：
- prototype_distance: "original" / "surface" / "structural" / "deep"
- disguise_level: "none" / "light" / "heavy"
- is_reverse: 0 / 1
- is_open_ended: 0 / 1
- decode_difficulty: "low" / "medium" / "high"

dim6_logic 继续输出：
- key_step_count: "1" / "2" / "3" / "4-5" / "6+"
- has_hidden_relation: 0 / 1
- need_reverse_reasoning: 0 / 1
- need_validation: 0 / 1
- has_branch: 0 / 1
- need_case_discussion: 0 / 1

严格输出如下 JSON 结构，不要添加别的字段：
{{
  "question_summary": "题目摘要",
  "analysis_facts": {{
    "core_task": "一句话说明题目核心求解目标",
    "core_knowledge_points": ["知识点1", "知识点2"],
    "core_methods": ["方法1", "方法2"],
    "visual_elements": ["图形/表格/统计图等"],
    "fact_basis": "这些事实如何从题面或图片得到",
    "image_used": 0,
    "has_sub_items": 0
  }},
  "applicable_dimensions": ["dim1", "dim2", "dim5"],
  "features": {{
    "dim1_computation": {{
      "band": "",
      "sublevel": "",
      "evidence_summary": "",
      "evidence_tags": [],
      "method_tags": [],
      "grade_clues": [],
      "system_clues": [],
      "visual_dependency": "none",
      "has_core_threshold": 0,
      "computation_role": "none",
      "applicability_confidence": 0.0,
      "need_manual_review": 0,
      "warning": ""
    }},
    "dim2_spatial": {{
      "band": "",
      "sublevel": "",
      "evidence_summary": "",
      "evidence_tags": [],
      "method_tags": [],
      "grade_clues": [],
      "system_clues": [],
      "visual_dependency": "none",
      "has_core_spatial_dependency": 0,
      "spatial_role": "none",
      "applicability_confidence": 0.0,
      "need_manual_review": 0,
      "warning": ""
    }},
    "dim3_information": {{
      "info_source_type": "",
      "info_count": "",
      "has_noise_info": 0,
      "condition_scattered": 0,
      "need_modeling": 0,
      "relation_complexity": ""
    }},
    "dim4_innovation": {{
      "prototype_distance": "",
      "disguise_level": "",
      "is_reverse": 0,
      "is_open_ended": 0,
      "decode_difficulty": ""
    }},
    "dim5_knowledge": {{
      "band": "",
      "sublevel": "",
      "evidence_summary": "",
      "evidence_tags": [],
      "method_tags": [],
      "grade_clues": [],
      "system_clues": [],
      "visual_dependency": "none",
      "knowledge_tags": [],
      "applicability_confidence": 0.0,
      "need_manual_review": 0,
      "warning": ""
    }},
    "dim6_logic": {{
      "key_step_count": "",
      "has_hidden_relation": 0,
      "need_reverse_reasoning": 0,
      "need_validation": 0,
      "has_branch": 0,
      "need_case_discussion": 0
    }}
  }},
  "confidence": 0.0,
  "reasoning": "简短中文分析"
}}

只输出 JSON，不要输出 Markdown，不要补充解释。"""


QUESTION_ANALYSIS_USER_PROMPT_TEMPLATE = """请分析下面这道小学数学题。

题号：{question_no}
页码：{page_no}
OCR识别题型：{question_type}
是否提供题块图片：{has_image}
OCR警告：{ocr_warnings}
小问候选：{sub_item_candidates}
解析审计：{parse_audit_summary}

题目原文：
{question_text}

请严格区分：
- 可验证事实：只能来自题面或图片
- 体系判断：放在 band / sublevel 中，不要反写进 facts

如果题块图片已附带，请优先结合图片判断 dim2 / dim3；如果图片对判定不关键，也请在 fact_basis 或 reasoning 中体现你已经核对过。"""


__all__ = [
    "QUESTION_ANALYSIS_SYSTEM_PROMPT",
    "QUESTION_ANALYSIS_USER_PROMPT_TEMPLATE",
]
