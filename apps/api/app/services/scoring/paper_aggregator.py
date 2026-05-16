"""
Paper-level aggregation helpers.

Current rule:
- each dimension score is the simple average of applicable question scores
- dim3 and dim4 use a transparent level-weighted average over applicable scored questions; invalid/missing scores are ignored
- dim5 keeps paper-level knowledge-source composition as explanation, not as the scoring rule
- counted_questions should surface representative, auditable examples
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List

from app.services.scoring.dim2_applicability import classify_dim2_geometry_domain
from app.services.scoring.dim2_knowledge_range import (
    geometry_model_difficulty_hint,
    geometry_model_display_points,
)
from app.services.scoring.dim_second_review import (
    SECOND_REVIEW_STATUS_APPLICABLE,
    SECOND_REVIEW_STATUS_FAILED_EXCLUDED,
    SECOND_REVIEW_STATUS_NOT_APPLICABLE,
)


@dataclass
class QuestionDimensionScore:
    question_id: str
    question_no: str
    score: float
    dim_scores: Dict[str, float]
    applicable_dims: List[str]
    question_label_raw: str | None = None
    section_index_raw: str | None = None
    question_display_label: str | None = None
    page_no: int | None = None
    question_summary: str = ""
    dim_reasons: Dict[str, str] = field(default_factory=dict)
    dim_warnings: Dict[str, List[str]] = field(default_factory=dict)
    dim_confidences: Dict[str, float] = field(default_factory=dict)
    dim_statuses: Dict[str, str] = field(default_factory=dict)
    dim_details: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class PaperDimensionSummary:
    dimension_code: str
    dimension_name: str
    paper_score: float
    level: int
    level_label: str
    total_question_score: float
    question_count: int
    sample_warning: bool
    evidence: str
    warning_messages: List[str] = field(default_factory=list)
    counted_questions: List[Dict[str, object]] = field(default_factory=list)
    review_question_count: int = 0
    score_status: str = "scored"
    score_breakdown: Dict[str, Any] = field(default_factory=dict)


class PaperAggregator:
    DIMENSION_NAMES = {
        "dim1": "数学运算",
        "dim2": "几何直观与空间想象",
        "dim3": "场景理解复杂度",
        "dim4": "建模解题复杂度",
        "dim5": "知识广度",
        "dim6": "逻辑链条",
    }

    LEVEL_THRESHOLDS = [
        (2.0, 1, "基础"),
        (4.0, 2, "常规"),
        (6.0, 3, "提升"),
        (8.0, 4, "拔高"),
        (10.0, 5, "选拔"),
    ]

    REPRESENTATIVE_LIMIT = 3
    REPRESENTATIVE_CONFIDENCE_THRESHOLD = 0.45
    DIMENSION_LEVEL_WEIGHTS = {
        "L1": 1.0,
        "L2": 1.0,
        "L3": 1.0,
        "L4": 1.25,
        "L5": 1.6,
    }
    DIM4_LEVEL_WEIGHTS = DIMENSION_LEVEL_WEIGHTS
    DIM4_PRACTICE_LEVEL_LABELS = {
        "L1": "基础关系",
        "L2": "简单转化",
        "L3": "条件组织",
        "L4": "多关系建模",
        "L5": "综合构造建模",
    }
    DIM4_GENERIC_KNOWLEDGE_POINTS = {
        "知识点",
        "建模解题",
        "创新题",
        "变式题",
        "综合题",
        "应用题",
        "题目",
        "dim4",
    }
    DIM4_SCORE_REASON_FORBIDDEN_FRAGMENTS = (
        "判为",
        "计为",
        "校准",
        "参考画像",
        "题目级参考",
        "level_source",
        "fallback",
        "人工复核",
        "缺失",
        "未计入",
        "未纳入",
        "review",
        "LLM",
        "保守",
        "兜底",
    )
    DIM4_KNOWLEDGE_DIFFICULTY_REASONS = {
        "牛吃草": "难点在于要把原有量、增长量和消耗量分开看，再用中间量串起多个时间段。",
        "工程问题": "难点在于要先重组效率和剩余工作量，再回查不同阶段是否对同一个总量成立。",
        "行程相遇追及": "难点在于要把相遇、追及或速度变化后的状态重新接起来，不能只套单段行程公式。",
        "比例百分数应用": "难点在于要分清新旧基准量，把多阶段变化放到同一个关系里回查。",
        "分数裂项/结构计算": "难点在于要先看出裂项、抵消或整体变形结构，再把长式子压缩成可计算关系。",
        "周期问题": "难点在于要找准周期起点和余数位置，遇到状态变化时还要重新校准循环节。",
        "图形割补": "难点在于要先补出辅助关系或重新拆分图形，再把隐藏的面积关系组织起来。",
        "抽屉/分类计数": "难点在于要先设好分类或候选范围，再逐类回查，避免重复和遗漏。",
        "方案比较": "难点在于要先列出可行方案，再用同一个标准比较，并回查限制条件是否都满足。",
        "逆推还原": "难点在于要倒着重排步骤，把每一步得到的状态接回前一个条件。",
        "博弈策略": "难点在于要倒推必胜或必败状态，并构造对手无法避开的应对策略。",
        "数论约束": "难点在于要把整除、余数和范围条件一起回查，逐步排除不满足条件的数。",
        "构造论证": "难点在于要同时满足多个限制条件，构造后还要检查是否每一步都符合题意。",
    }
    DIM4_STRATEGY_DIFFICULTY_REASONS = {
        "exploratory_search": "难点在于没有现成路径，需要先探索可行方向，再用条件把结果收束住。",
        "constructive": "难点在于要主动构造对象或方案，并逐步检查它是否满足所有限制。",
        "strategy_shift": "难点在于中途要换一种看法或解法，把原条件重新组织后再推进。",
        "local_trick": "难点在于要看出局部突破口，用一个关键中间量或特殊关系打开题目。",
        "custom_construction": "难点在于要自己搭出中间结构，不能直接沿常规模板推进。",
        "case_construction": "难点在于要分情况构造并回查，每一类都不能漏掉。",
        "branched": "难点在于可能路径不止一条，需要筛掉不符合条件的分支。",
        "open": "难点在于探索空间比较开放，需要先缩小范围再证明选择可行。",
    }
    IMAGE_FALLBACK_HINTS = ("纯文本回退", "多模态分析失败")
    DIM2_GEOMETRY_HINTS = (
        "几何",
        "图形",
        "空间",
        "图片",
        "题块",
        "如图",
        "图中",
        "面积",
        "体积",
        "容积",
        "圆柱",
        "圆锥",
        "长方形",
        "正方形",
        "水位",
        "瓶",
    )
    DIM5_BUCKET_LABELS = {
        "school": "校内知识",
        "low_gaosi": "三四年级奥数入门",
        "high_gaosi": "五六年级奥数典型专题",
        "junior_bridge": "七年级基础前置",
        "beyond": "六年级奥数较难 / 七年级核心门槛",
        "unknown": "未稳定归类",
    }
    DIM5_LEVEL_WEIGHTS = {
        "L1": 1,
        "L2": 1,
        "L3": 2,
        "L4": 4,
        "L5": 6,
    }
    DIM1_LEVEL_DIFFICULTY_LABELS = {
        "L1": "简单（2.0）",
        "L2": "较易（4.0）",
        "L3": "中等（6.0）",
        "L4": "较难（8.0）",
        "L5": "困难（9.5）",
    }
    DIM1_COUNTED_QUESTION_LEVEL_NOTES = {
        "L1": "属于基础计算要求，主要看基本运算是否准确。",
        "L2": "属于常规校内计算，主要区分熟练度和准确率。",
        "L3": "有一定转换或多步计算要求，常见失分点是算式落地和运算顺序。",
        "L4": "学习范围或计算量偏高，常见失分点是连续化简和计算准确率。",
        "L5": "属于高强度或拓展计算，容易拉开学生在综合计算上的差距。",
    }
    DIM5_GENERIC_KNOWLEDGE_POINTS = {
        "知识点",
        "数学知识",
        "校内一般知识",
        "综合题",
        "综合问题",
        "高思导引",
        "高思",
        "奥数",
        "专题",
        "应用题",
        "计算",
    }
    DIM5_GRADE_LABELS = {
        "1": "一年级",
        "2": "二年级",
        "3": "三年级",
        "4": "四年级",
        "5": "五年级",
        "6": "六年级",
        "一": "一年级",
        "二": "二年级",
        "三": "三年级",
        "四": "四年级",
        "五": "五年级",
        "六": "六年级",
    }
    DIM5_SCORE_REASON_FORBIDDEN_FRAGMENTS = (
        "命中",
        "参考库",
        "目录",
        "题目级",
        "判为",
        "计为",
        "纠偏",
        "候选",
        "LLM",
        "证据不足",
        "本题归入",
        "知识来源",
        "归类",
        "标准知识点",
        "知识域",
        "综合判为",
        "高思导引",
        "奥数",
        "专题",
        "知识组织",
        "要求较高",
    )
    DIM5_POINT_DIFFICULTY_REASONS = {
        "组合计数": "难点在于要先按对象或步骤分类计数，再检查是否重复或遗漏；涉及容斥时，还要把重叠部分单独扣回。",
        "复杂组合计数": "难点在于计数路径不止一层，需要保证分类不重不漏，并处理容斥或多层选择之间的相互影响。",
        "数论约束": "难点在于要用整除、余数、奇偶或倍数关系缩小范围，再逐步筛掉不满足条件的数。",
        "高阶数论综合": "难点在于要把整除、余数、质因数或范围条件放在一起约束可能的数，通常不能直接代公式求出。",
        "面积比模型": "难点在于要先看出等高、共边、割补或辅助线关系，再把面积关系转成比例关系。",
        "高阶几何综合": "难点在于图形关系往往藏在重构、截面、展开或多步面积比例中，需要先搭出中间关系。",
        "牛吃草模型": "难点在于要同时处理原有量、新增量和消耗量，先分清每单位时间的变化关系。",
        "定义新运算": "难点在于不能按常规运算直接算，要先把题目给出的新规则逐层展开再代入。",
        "裂项与长链消去": "难点在于要把算式改写成前后能抵消的结构，找不到拆分方式就会变成硬算。",
        "递推与差分": "难点在于要从相邻项或相邻变化里找规律，再把局部规律连续推到目标位置。",
        "周期问题": "难点在于要先找准循环节和余数位置，不能只按前几项表面规律直接延伸。",
        "抽屉原理": "难点在于要先设计合适的分类盒子，再用最不利情况说明为什么一定会出现某种结果。",
        "博弈策略": "难点在于要倒推必胜或必败状态，找到对手每一步都无法避开的应对策略。",
        "构造类问题": "难点在于要同时满足多个限制条件，通常需要边试边排除，并检查构造是否真的符合题意。",
        "跨专题综合": "难点在于要把多个模型串起来使用，前一部分得到的关系会继续限制后一部分的选择。",
        "典型应用题入门模型": "难点在于要先把文字条件整理成数量关系，再选择合适的和差倍、还原或盈亏模型。",
        "简单规律与数列": "难点在于要从变化过程里找出稳定规律，再用这个规律定位到指定项或指定位置。",
        "简单枚举与分类": "难点在于要把情况分完整，并保持每一类之间不重复。",
        "图形割补与组合图形": "难点在于要把不规则图形拆成可计算的部分，或通过补形把隐藏面积关系补出来。",
        "数字谜与数阵图入门": "难点在于要利用行列、位置或总和约束逐步试填，不能随意猜数。",
        "高年级校内数与代数": "难点在于要把分数、百分数、比例或方程关系对应清楚，再按校内方法稳定计算。",
        "高年级校内图形公式": "难点在于要先找准半径、直径、高或底面积等关键量，再代入图形公式。",
        "常规数量关系应用": "难点在于要分清速度、效率、单价或浓度等数量关系，再把已知量和所求量对应起来。",
        "统计与可能性": "难点在于要先读准图表或可能性条件，再把数据整理成可计算的数量关系。",
        "因数倍数与质合数": "难点在于要根据因数、倍数、质数或合数条件缩小数字范围，再逐一排除不符合的数。",
        "基础四则与一步应用": "难点在于要准确对应题意和运算，避免把一步数量关系看反。",
        "基础平面图形公式": "难点在于要认清图形对应的长、宽、底或高，再直接使用基础面积公式。",
    }
    DIM5_DOMAIN_DIFFICULTY_REASONS = {
        "counting_combinatorics": "难点在于要把情况分完整，并检查是否有重复或遗漏。",
        "number_theory": "难点在于要用整除、余数或质因数条件不断缩小数字范围。",
        "geometry_spatial": "难点在于要先发现图形中的隐藏关系，再把它转成面积、长度或体积关系。",
        "quantity_application": "难点在于要先把文字条件整理成数量关系，再决定从哪个量入手。",
        "number_operation": "难点在于要先看出算式或数量的结构，再选择更合适的计算方式。",
        "pattern_sequence": "难点在于要找出变化中的稳定规律，再推到指定位置。",
        "logic_strategy_construction": "难点在于要同时照顾多个限制条件，并检查每一步是否还能满足题意。",
        "statistics_probability": "难点在于要先读准数据或可能性条件，再转成可计算关系。",
        "school_general": "难点在于要把题意中的已知量和所用公式对应准确。",
    }
    DIM3_APPLICATION_TASK_LABELS = {
        "chart_table_conversion": "图文对应理解",
        "percentage_base_change": "比较基准理解",
        "reverse_process": "过程顺序理解",
        "multi_object_distribution": "多对象角色理解",
        "equation_setup": "题目问法理解",
        "ratio_allocation": "多对象角色理解",
        "work_rate": "任务场景理解",
        "queue_growth": "过程变化理解",
        "concentration_mixture": "状态变化理解",
        "profit_discount": "规则条件理解",
        "travel_meeting_chasing": "行程过程理解",
        "optimization_comparison": "关键问法理解",
        "conservation_transfer": "转移过程理解",
        "cycle_period": "循环过程理解",
        "average_total": "平均口径理解",
        "range_narrowing": "反馈范围理解",
    }
    DIM3_FORBIDDEN_DISPLAY_FRAGMENTS = (
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
        "数学表示",
        "数量关系",
        "方程",
        "建模",
        "表示转化",
    )
    DIM6_LOGIC_TASK_LABELS = {
        "work_rate_chain": "多步条件推进",
        "queue_growth_chain": "多轮变化整理",
        "multi_stage_state_change": "多轮变化整理",
        "percentage_base_shift_chain": "多轮变化整理",
        "travel_meeting_chasing_chain": "多轮变化整理",
        "cyclic_schedule_chain": "周期位置判断",
        "reverse_process_chain": "倒着推回原条件",
        "bounded_case_enumeration": "多种情况判断",
        "optimization_comparison": "方案比较判断",
        "global_constraint_system": "多条件同时成立",
        "periodic_sequence_position": "周期位置判断",
        "shared_variable_coupling": "多条件同时成立",
    }
    DIM6_FORBIDDEN_DISPLAY_FRAGMENTS = (
        "逻辑负担",
        "约束一致",
        "高阶收束",
        "逻辑链条",
        "依据是",
        "dim6_level",
        "reasoning_role",
        "chain_span",
        "constraint_coupling",
    )

    COUNTED_QUESTION_FULL_REASON_HIDDEN_MARKERS = ("依据标签：", "核心事实：", "依据来源：")

    COUNTED_QUESTION_LEVEL_DESCRIPTOR_PATTERN = re.compile(r"^(L[1-5])(?:\s+[^：:]{1,40})?[：:]\s*(.+)$")
    CJK_TEXT_PATTERN = re.compile(r"[\u4e00-\u9fff]")
    ENGLISH_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")
    ENGLISH_DISPLAY_STOPWORDS = {
        "and",
        "are",
        "but",
        "either",
        "for",
        "from",
        "into",
        "requires",
        "that",
        "the",
        "then",
        "this",
        "through",
        "to",
        "with",
    }

    @classmethod
    def _format_counted_question_analysis(cls, text: object) -> str:
        normalized = " ".join(str(text or "").split()).strip()
        for marker in cls.COUNTED_QUESTION_FULL_REASON_HIDDEN_MARKERS:
            normalized = normalized.split(marker, 1)[0].strip()
        normalized = normalized.rstrip(" 。；;，,")

        match = cls.COUNTED_QUESTION_LEVEL_DESCRIPTOR_PATTERN.match(normalized)
        if match:
            normalized = f"{match.group(1)}：{match.group(2).strip()}"
        return normalized.rstrip(" 。；;，,")

    @classmethod
    def _dim1_level_from_score(cls, score: object) -> str:
        try:
            score_value = float(score or 0.0)
        except (TypeError, ValueError):
            score_value = 0.0
        if score_value >= 9:
            return "L5"
        if score_value >= 8:
            return "L4"
        if score_value >= 6:
            return "L3"
        if score_value >= 4:
            return "L2"
        return "L1"

    @classmethod
    def _dim1_difficulty_label(cls, level_code: str) -> str:
        return cls.DIM1_LEVEL_DIFFICULTY_LABELS.get(level_code, cls.DIM1_LEVEL_DIFFICULTY_LABELS["L1"])

    @classmethod
    def _build_dim1_score_overview(cls, score: object) -> str:
        try:
            score_value = float(score or 0.0)
        except (TypeError, ValueError):
            score_value = 0.0

        if score_value >= 9:
            explanation = "说明本卷计算要求很高，包含较强的多步、结构化或拓展计算，对综合计算能力要求突出。"
        elif score_value >= 8:
            explanation = "说明本卷计算难度较高，计算题和应用题中的核心计算都会拉开学生差距。"
        elif score_value >= 6:
            explanation = "说明本卷有一定计算难度，除准确率外，也考查多步运算和常见转化。"
        elif score_value >= 4:
            explanation = "说明本卷计算难度整体偏常规，重点考查校内计算的熟练度和稳定性。"
        else:
            explanation = "说明本卷计算要求以基础运算为主，主要看基本规则掌握和计算准确率。"
        return f"计算维度，综合得分 {score_value:.1f} 分，{explanation}"

    @classmethod
    def _build_dim2_score_overview(cls, score: object) -> str:
        try:
            score_value = float(score or 0.0)
        except (TypeError, ValueError):
            score_value = 0.0

        if score_value >= 9:
            explanation = "说明本卷几何与空间要求很高，包含高强度空间重构、多视图或高阶几何模型。"
        elif score_value >= 8:
            explanation = "说明本卷几何难度较高，复合图形、隐含关系或空间转换会明显拉开差距。"
        elif score_value >= 6:
            explanation = "说明本卷有一定几何与空间难度，除基本公式外，也考查图形关系整理和模型识别。"
        elif score_value >= 4:
            explanation = "说明本卷以常规图形关系为主，重点考查读图准确性和单步空间转化。"
        else:
            explanation = "说明本卷主要覆盖基础识图和直接几何公式，重点看图形概念和基本关系是否掌握。"
        return f"几何直观与空间想象维度，综合得分 {score_value:.1f} 分，{explanation}"

    @classmethod
    def _build_dim3_score_overview(cls, score: object) -> str:
        try:
            score_value = float(score or 0.0)
        except (TypeError, ValueError):
            score_value = 0.0

        if score_value >= 9:
            explanation = "说明这张试卷在学生读题理解题意上设置了较高难度，不少题目需要完整读懂多条规则、多阶段过程或复杂图文关系。"
        elif score_value >= 8:
            explanation = "说明这张试卷在学生读题理解题意上设置了明显难度，部分题目的场景相对复杂，学生需要先理清对象、阶段、规则或图文关系。"
        elif score_value >= 6:
            explanation = "说明这张试卷在学生读题理解题意上设置了一定难度，部分题目需要先读懂关键问法、比较标准或简单规则。"
        elif score_value >= 4:
            explanation = "说明这张试卷在学生读题和理解题意上有常规要求，部分题目需要分清对象、顺序或图文对应关系。"
        else:
            explanation = "说明这张试卷在学生读题和理解题意上的要求比较基础，大多数题目读完后能较快明白题目在说什么。"
        return f"场景理解复杂度维度，综合得分 {score_value:.1f} 分，{explanation}"

    @classmethod
    def _build_dim4_score_overview(cls, score: object) -> str:
        try:
            score_value = float(score or 0.0)
        except (TypeError, ValueError):
            score_value = 0.0

        if score_value >= 9:
            explanation = "说明本卷在解题思路上难度很高。孩子做核心题时，通常不能只按常规步骤推进，需要先找到关键突破口，再持续检查每一步是否和题目条件一致。"
        elif score_value >= 8:
            explanation = "说明本卷在解题思路上有较明显难度。孩子做这类题时，往往需要先把条件之间的关系理清楚，再选择合适的切入方式逐步推进。"
        elif score_value >= 6:
            explanation = "说明本卷在解题思路上有一定难度。部分题目不是读完就能直接下手，需要孩子先整理已知条件和目标之间的关系，再按较清晰的步骤推进。"
        elif score_value >= 4:
            explanation = "说明本卷在解题思路上的要求整体偏常规。多数题目读懂后可以沿常见思路完成，少量题需要先做简单整理再下手。"
        else:
            explanation = "说明本卷在解题思路上的要求比较基础。多数题目读懂题意后，可以直接找到主要关系并完成解答。"
        return f"综合得分为 {score_value:.1f} 分，{explanation}"

    @classmethod
    def _build_dim6_score_overview(cls, score: object) -> str:
        try:
            score_value = float(score or 0.0)
        except (TypeError, ValueError):
            score_value = 0.0

        if score_value >= 9:
            explanation = "这张试卷有少量解题链条很长的压轴题，通常要连续推进 5 步以上，并检查多个条件。"
        elif score_value >= 8:
            explanation = "这张试卷不少题解题链条较长，通常要连续推进 3-4 步，并穿插分类、倒推或回查。"
        elif score_value >= 6:
            explanation = "这张试卷部分题解题链条有一定长度，通常要把前后条件接起来推进 2-4 步。"
        elif score_value >= 4:
            explanation = "这张试卷整体解题链条偏短，少量题需要 1-2 步衔接。"
        else:
            explanation = "这张试卷多数题解题链条很短，通常读懂条件后一步判断即可。"

        return f"逻辑推理综合得分 {score_value:.1f} 分，{explanation}"

    @staticmethod
    def _dimension_status(question: QuestionDimensionScore, dimension_code: str) -> str:
        explicit_status = str(question.dim_statuses.get(dimension_code, "")).strip()
        if explicit_status:
            return explicit_status
        return "applicable" if dimension_code in question.applicable_dims else "not_applicable"

    @classmethod
    def _second_review_counts(
        cls,
        question_scores: List[QuestionDimensionScore],
        dimension_code: str,
    ) -> Dict[str, int]:
        counts = {
            "second_review_requested_count": 0,
            "second_review_applicable_count": 0,
            "second_review_not_applicable_count": 0,
            "second_review_failed_count": 0,
        }
        for question in question_scores:
            details = question.dim_details.get(dimension_code, {}) if isinstance(question.dim_details, dict) else {}
            if not isinstance(details, dict):
                continue
            status = str(details.get("second_review_status") or "").strip()
            requested = bool(details.get("second_review_requested")) or bool(status)
            if not requested:
                continue
            counts["second_review_requested_count"] += 1
            if status == SECOND_REVIEW_STATUS_APPLICABLE:
                counts["second_review_applicable_count"] += 1
            elif status == SECOND_REVIEW_STATUS_NOT_APPLICABLE:
                counts["second_review_not_applicable_count"] += 1
            elif status == SECOND_REVIEW_STATUS_FAILED_EXCLUDED:
                counts["second_review_failed_count"] += 1
            else:
                counts["second_review_failed_count"] += 1
        return counts

    @classmethod
    def _dim2_has_geometry_candidate(cls, question: QuestionDimensionScore) -> bool:
        details = question.dim_details.get("dim2", {}) or {}
        if details.get("fallback_source") in {"visual_geometry", "geometry_structure"}:
            return True
        if details.get("figure_complexity") not in {"", None, "none"}:
            return True
        if details.get("geometry_model_types"):
            return True
        text = " ".join(
            [
                question.question_summary or "",
                question.dim_reasons.get("dim2", ""),
                " ".join(question.dim_warnings.get("dim2", []) or []),
                str(details.get("evidence_summary", "")),
                " ".join(str(item) for item in details.get("evidence_tags", []) or []),
            ]
        )
        return any(hint in text for hint in cls.DIM2_GEOMETRY_HINTS)

    def aggregate(
        self,
        question_scores: List[QuestionDimensionScore],
        dimension_code: str,
    ) -> PaperDimensionSummary:
        if dimension_code == "dim1":
            return self._aggregate_dim1(question_scores)
        if dimension_code == "dim3":
            return self._aggregate_dim3(question_scores)
        if dimension_code == "dim4":
            return self._aggregate_dim4(question_scores)
        if dimension_code == "dim5":
            return self._aggregate_dim5(question_scores)

        applicable_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, dimension_code) == "applicable"
        ]
        review_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, dimension_code) in {"review", "needs_second_review"}
        ]

        total_question_score = sum(question.score for question in applicable_questions)
        question_count = len(applicable_questions)
        review_question_count = len(review_questions)
        sample_warning = 0 < question_count < 2

        if question_count == 0:
            dim2_geometry_candidate_count = (
                sum(1 for question in question_scores if self._dim2_has_geometry_candidate(question))
                if dimension_code == "dim2"
                else 0
            )
            second_review_counts = self._second_review_counts(question_scores, dimension_code)
            review_failed_excluded_count = sum(
                1
                for question in question_scores
                if self._dimension_status(question, dimension_code) == SECOND_REVIEW_STATUS_FAILED_EXCLUDED
            )
            if dimension_code == "dim2" and dim2_geometry_candidate_count:
                evidence = (
                    f"本卷存在 {dim2_geometry_candidate_count} 道几何/图形候选题，"
                    "但未形成可自动计入 dim2 的稳定空间表征样本；相关题目已排除或转入复核。"
                )
            else:
                evidence = "该维度自动评分未覆盖，未计入综合分。"

            return PaperDimensionSummary(
                dimension_code=dimension_code,
                dimension_name=self.DIMENSION_NAMES.get(dimension_code, dimension_code),
                paper_score=0.0,
                level=0,
                level_label="未覆盖",
                total_question_score=0.0,
                question_count=0,
                sample_warning=False,
                evidence=evidence,
                warning_messages=[],
                counted_questions=[],
                review_question_count=review_question_count,
                score_status="not_covered",
                score_breakdown={
                    "geometry_candidate_count": dim2_geometry_candidate_count,
                    "review_question_count": review_question_count,
                    **second_review_counts,
                    "review_failed_excluded_count": review_failed_excluded_count,
                },
            )

        score_sum = sum(question.dim_scores.get(dimension_code, 0.0) for question in applicable_questions)
        paper_score = score_sum / question_count
        level, level_label = self._calculate_level(paper_score)

        actual_review_question_count = review_question_count
        second_review_counts = self._second_review_counts(question_scores, dimension_code)
        review_failed_excluded_count = sum(
            1
            for question in question_scores
            if self._dimension_status(question, dimension_code) == SECOND_REVIEW_STATUS_FAILED_EXCLUDED
        )
        score_breakdown = {
            **second_review_counts,
            "review_failed_excluded_count": review_failed_excluded_count,
        }
        review_questions = []
        review_question_count = 0
        warning_messages: List[str] = []
        for question in applicable_questions:
            warning_messages.extend(question.dim_warnings.get(dimension_code, []))
        for question in review_questions:
            warning_messages.extend(question.dim_warnings.get(dimension_code, []))

        if review_question_count:
            warning_messages.append(
                f"{self.DIMENSION_NAMES.get(dimension_code, dimension_code)}有 {review_question_count} 道题自动评分未覆盖，未计入均分。"
            )

        if sample_warning:
            warning_messages.append("该维度当前样本题量偏少，整卷结论稳定性有限。")

        deduped_warnings = list(
            dict.fromkeys(message.strip() for message in warning_messages if message.strip())
        )

        if dimension_code == "dim2":
            evidence = self._build_dim2_score_overview(paper_score)
        elif dimension_code == "dim3":
            evidence = self._build_dim3_score_overview(paper_score)
        elif dimension_code == "dim6":
            evidence = self._build_dim6_score_overview(paper_score)
        else:
            evidence = (
                f"共 {question_count} 道相关题目；"
                f"题级平均维度分 {paper_score:.1f} 分，判定为 {level_label}。"
            )

        return PaperDimensionSummary(
            dimension_code=dimension_code,
            dimension_name=self.DIMENSION_NAMES.get(dimension_code, dimension_code),
            paper_score=paper_score,
            level=level,
            level_label=level_label,
            total_question_score=total_question_score,
            question_count=question_count,
            sample_warning=sample_warning,
            evidence=evidence,
            warning_messages=deduped_warnings,
            counted_questions=self._select_representative_questions(applicable_questions, dimension_code),
            review_question_count=actual_review_question_count,
            score_breakdown=score_breakdown,
        )

    @classmethod
    def _dim5_bucket_for_question(cls, question: QuestionDimensionScore) -> str:
        details = question.dim_details.get("dim5", {}) if isinstance(question.dim_details, dict) else {}
        if isinstance(details, dict):
            bucket = str(details.get("knowledge_source_bucket", "")).strip()
            if bucket:
                return bucket

        legacy_score = question.dim_scores.get("dim5")
        if legacy_score is None:
            return "unknown"
        if legacy_score <= 3.5:
            return "school"
        if legacy_score <= 5.5:
            return "low_gaosi"
        if legacy_score <= 7.5:
            return "high_gaosi"
        return "beyond"

    @staticmethod
    def _normalize_dim5_level(value: object) -> str:
        text = str(value or "").strip().upper()
        if text in {"L1", "L2", "L3", "L4", "L5"}:
            return text
        if text in {"1", "2", "3", "4", "5"}:
            return f"L{text}"
        match = re.search(r"\bL?([1-5])\b", text)
        return f"L{match.group(1)}" if match else ""

    @classmethod
    def _dim5_level_for_question(cls, question: QuestionDimensionScore) -> str:
        details = cls._dim5_details_for_question(question)
        for key in ("knowledge_level", "dim5_level"):
            level = cls._normalize_dim5_level(details.get(key))
            if level:
                return level

        score = cls._valid_dim5_question_score(question)
        if score is None:
            reason = question.dim_reasons.get("dim5", "")
            return cls._normalize_dim5_level(reason)
        if score <= 2.5:
            return "L1"
        if score <= 4.5:
            return "L2"
        if score <= 6.5:
            return "L3"
        if score <= 8.5:
            return "L4"
        return "L5"

    @staticmethod
    def _ratio(count: int, total: int) -> float:
        return count / total if total else 0.0

    @staticmethod
    def _valid_dim5_question_score(question: QuestionDimensionScore) -> float | None:
        raw_score = question.dim_scores.get("dim5")
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            return None
        if 0.0 < score <= 10.0:
            return score
        return None

    @staticmethod
    def _dim5_details_for_question(question: QuestionDimensionScore) -> Dict[str, object]:
        details = question.dim_details.get("dim5", {}) if isinstance(question.dim_details, dict) else {}
        return details if isinstance(details, dict) else {}

    @classmethod
    def _dim5_source_for_question(cls, question: QuestionDimensionScore) -> str:
        details = cls._dim5_details_for_question(question)
        if str(details.get("dim5_excluded_reason") or "").strip() == "retry_failed":
            return "llm_dim5_retry_failed"
        if (
            details.get("dim5_retry_used") is True
            and str(details.get("gaosi_classification_source") or "").strip() == "llm_retry"
        ):
            return "llm_dim5_retry"
        source = str(details.get("band_source") or "").strip()
        if source:
            return source
        source = str(details.get("gaosi_classification_source") or "").strip()
        if source:
            return source
        return "model_only"

    @classmethod
    def _dim5_is_topic_structure_upshift(cls, question: QuestionDimensionScore) -> bool:
        details = cls._dim5_details_for_question(question)
        if str(details.get("band_source") or "").strip() == "topic_structure_match":
            return True
        calibration = details.get("calibration", {})
        if not isinstance(calibration, dict):
            return False
        return (
            str(calibration.get("match_scope") or "").strip() == "topic_structure"
            and str(calibration.get("match_action") or "").strip() in {"raise_band", "confirm_model"}
        )

    @staticmethod
    def _dim1_bucket_for_question(question: QuestionDimensionScore) -> str:
        details = question.dim_details.get("dim1", {}) if isinstance(question.dim_details, dict) else {}
        if isinstance(details, dict):
            bucket = str(details.get("calc_bucket", "")).strip()
            if bucket in {"pure_calculation", "embedded_calculation"}:
                return bucket
            if (
                str(details.get("task_form", "")).strip() == "embedded"
                and str(details.get("calc_role", "")).strip() == "core"
            ):
                return "embedded_calculation"
        return "pure_calculation"

    @staticmethod
    def _normalize_dim4_level(value: object) -> str:
        text = str(value or "").strip().upper()
        if text in {"L1", "L2", "L3", "L4", "L5"}:
            return text
        if text in {"1", "2", "3", "4", "5"}:
            return f"L{text}"
        match = re.search(r"\bL?([1-5])\b", text)
        return f"L{match.group(1)}" if match else ""

    @classmethod
    def _dim4_level_for_question(cls, question: QuestionDimensionScore) -> str:
        details = question.dim_details.get("dim4", {}) if isinstance(question.dim_details, dict) else {}
        if isinstance(details, dict):
            for key in ("dim4_level", "calibrated_topic_level", "topic_level", "reference_calibrated_level"):
                level = cls._normalize_dim4_level(details.get(key))
                if level:
                    return level
            calibration = details.get("reference_calibration")
            if isinstance(calibration, dict):
                level = cls._normalize_dim4_level(
                    calibration.get("final_level") or calibration.get("reference_level")
                )
                if level:
                    return level
        score = question.dim_scores.get("dim4")
        if score is None:
            reason = question.dim_reasons.get("dim4", "")
            return cls._normalize_dim4_level(reason)
        if score <= 2.5:
            return "L1"
        if score <= 4.5:
            return "L2"
        if score <= 6.5:
            return "L3"
        if score <= 8.5:
            return "L4"
        return "L5"

    @classmethod
    def _dim4_source_for_question(cls, question: QuestionDimensionScore) -> str:
        details = question.dim_details.get("dim4", {}) if isinstance(question.dim_details, dict) else {}
        if not isinstance(details, dict):
            return "legacy_score"
        calibration = details.get("reference_calibration")
        if isinstance(calibration, dict) and calibration.get("action"):
            return str(calibration.get("action") or "").strip()
        return str(details.get("level_source") or "").strip() or "rule_score"

    @classmethod
    def _dim4_not_applicable_reason(cls, question: QuestionDimensionScore) -> str:
        return " ".join(str(question.dim_reasons.get("dim4", "") or "").split()).strip()

    @classmethod
    def _dim4_is_l1_excluded(cls, question: QuestionDimensionScore) -> bool:
        if cls._dimension_status(question, "dim4") != "not_applicable":
            return False

        level = cls._dim4_level_for_question(question)
        reason = cls._dim4_not_applicable_reason(question)
        if level == "L1":
            return True
        return "L1" in reason and ("基础模板" in reason or "模板" in reason)

    @staticmethod
    def _valid_dim4_question_score(question: QuestionDimensionScore) -> float | None:
        raw_score = question.dim_scores.get("dim4")
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            return None
        if 0.0 < score <= 10.0:
            return score
        return None

    @staticmethod
    def _sanitize_dim4_warning(message: object) -> str:
        text = str(message or "").strip()
        if not text:
            return ""
        replacements = {
            "当前题目转入人工复核": "已按自动规则纳入评分",
            "转入人工复核": "按自动规则纳入评分",
            "当前结果需人工复核": "自动评分结果需要谨慎解读",
            "需人工复核": "需要谨慎解读",
            "需要人工复核": "需要谨慎解读",
            "人工复核": "自动评分提示",
            "复核": "检查",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        return text.replace("未计入均分", "未计入该维度")

    @staticmethod
    def _average_dimension_score(questions: List[QuestionDimensionScore], dimension_code: str) -> float:
        if not questions:
            return 0.0
        return sum(question.dim_scores.get(dimension_code, 0.0) for question in questions) / len(questions)

    @staticmethod
    def _valid_dimension_question_score(
        question: QuestionDimensionScore,
        dimension_code: str,
    ) -> float | None:
        raw_score = question.dim_scores.get(dimension_code)
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            return None
        if 0.0 < score <= 10.0:
            return score
        return None

    @classmethod
    def _dimension_level_weight(cls, level: str) -> float:
        return float(cls.DIMENSION_LEVEL_WEIGHTS.get(level, 1.0))

    def _aggregate_dim3(self, question_scores: List[QuestionDimensionScore]) -> PaperDimensionSummary:
        level_counts = {f"L{index}": 0 for index in range(1, 6)}
        scored_questions: List[QuestionDimensionScore] = []
        raw_score_sum = 0.0
        weighted_score_sum = 0.0
        total_weight = 0.0
        unscored_question_count = 0
        second_review_counts = self._second_review_counts(question_scores, "dim3")

        applicable_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, "dim3") == "applicable"
        ]
        review_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, "dim3") in {"review", "needs_second_review"}
        ]
        not_applicable_count = sum(
            1
            for question in question_scores
            if self._dimension_status(question, "dim3") == "not_applicable"
        )
        failed_excluded_count = sum(
            1
            for question in question_scores
            if self._dimension_status(question, "dim3") == SECOND_REVIEW_STATUS_FAILED_EXCLUDED
        )

        for question in applicable_questions:
            question_score = self._valid_dimension_question_score(question, "dim3")
            if question_score is None:
                unscored_question_count += 1
                continue

            level = self._question_level_code(question, "dim3", question_score)
            if level not in level_counts:
                unscored_question_count += 1
                continue

            level_counts[level] += 1
            scored_questions.append(question)
            raw_score_sum += question_score
            weight = self._dimension_level_weight(level)
            weighted_score_sum += question_score * weight
            total_weight += weight

        question_count = len(scored_questions)
        level_ratios = {
            level: round(self._ratio(count, question_count), 4)
            for level, count in level_counts.items()
        }
        raw_question_average = raw_score_sum / question_count if question_count else 0.0
        weighted_question_average = weighted_score_sum / total_weight if total_weight else 0.0
        breakdown = {
            "level_counts": level_counts,
            "level_ratios": level_ratios,
            "level_weights": self.DIMENSION_LEVEL_WEIGHTS,
            "raw_question_average": round(raw_question_average, 4),
            "weighted_question_average": round(weighted_question_average, 4),
            "weighted_score_sum": round(weighted_score_sum, 4),
            "total_weight": round(total_weight, 4),
            "not_applicable_count": not_applicable_count,
            "review_count": len(review_questions),
            "review_failed_excluded_count": failed_excluded_count,
            **second_review_counts,
            "valid_score_question_count": question_count,
            "unscored_question_count": unscored_question_count,
            "auto_ignored_count": (
                unscored_question_count
                + len(review_questions)
                + not_applicable_count
                + failed_excluded_count
            ),
            "high_level_question_count": level_counts["L4"] + level_counts["L5"],
            "aggregation_rule": "能稳定自动判定 L1-L5 的题纳入场景理解复杂度评分；纯计算、裸公式或无真实读题场景负担的题自动未覆盖；卷级主分按题目等级加权，高等级题权重更高。",
        }

        if question_count == 0:
            zero_warning_messages = (
                ["部分题目因图文信息不足或判定不稳定，未计入该维度。"]
                if second_review_counts["second_review_failed_count"] > 0
                else []
            )
            return PaperDimensionSummary(
                dimension_code="dim3",
                dimension_name=self.DIMENSION_NAMES["dim3"],
                paper_score=0.0,
                level=0,
                level_label="未覆盖",
                total_question_score=0.0,
                question_count=0,
                sample_warning=False,
                evidence="场景理解复杂度暂无可评分题目，未计入综合分。",
                warning_messages=zero_warning_messages,
                counted_questions=[],
                review_question_count=len(review_questions),
                score_status="not_covered",
                score_breakdown=breakdown,
            )

        paper_score = weighted_question_average
        level, level_label = self._calculate_level(paper_score)
        sample_warning = 0 < question_count < 2

        warning_messages: List[str] = []
        for question in scored_questions:
            warning_messages.extend(question.dim_warnings.get("dim3", []))
        if sample_warning:
            warning_messages.append("该维度当前样本题量偏少，整卷结论稳定性有限。")
        if second_review_counts["second_review_failed_count"] > 0:
            warning_messages.append("部分题目因图文信息不足或判定不稳定，未计入该维度。")
        deduped_warnings = list(
            dict.fromkeys(message.strip() for message in warning_messages if message.strip())
        )

        evidence = (
            f"共 {question_count} 道题纳入场景理解复杂度评分；"
            "按题目等级加权，高等级题权重更高；"
            f"权重得分 {paper_score:.1f} 分，判定为 {level_label}。"
        )

        return PaperDimensionSummary(
            dimension_code="dim3",
            dimension_name=self.DIMENSION_NAMES["dim3"],
            paper_score=paper_score,
            level=level,
            level_label=level_label,
            total_question_score=sum(question.score for question in scored_questions),
            question_count=question_count,
            sample_warning=sample_warning,
            evidence=evidence,
            warning_messages=deduped_warnings,
            counted_questions=self._select_representative_questions(scored_questions, "dim3"),
            review_question_count=len(review_questions),
            score_breakdown=breakdown,
        )

    def _aggregate_dim4(self, question_scores: List[QuestionDimensionScore]) -> PaperDimensionSummary:
        level_counts = {f"L{index}": 0 for index in range(1, 6)}
        source_counts: Dict[str, int] = {}
        scored_questions: List[QuestionDimensionScore] = []
        fallback_count = 0
        raw_score_sum = 0.0
        weighted_score_sum = 0.0
        total_weight = 0.0
        ignored_question_count = 0
        not_applicable_count = 0
        review_question_count = 0
        failed_excluded_count = 0
        second_review_counts = self._second_review_counts(question_scores, "dim4")

        for question in question_scores:
            status = self._dimension_status(question, "dim4")
            if status in {"review", "needs_second_review"}:
                review_question_count += 1
                ignored_question_count += 1
                continue
            if status == SECOND_REVIEW_STATUS_FAILED_EXCLUDED:
                failed_excluded_count += 1
                not_applicable_count += 1
                ignored_question_count += 1
                continue
            if status != "applicable":
                not_applicable_count += 1
                ignored_question_count += 1
                continue

            question_score = self._valid_dim4_question_score(question)
            level = self._dim4_level_for_question(question)
            source = self._dim4_source_for_question(question) or "rule_score"
            if question_score is None or level not in level_counts:
                ignored_question_count += 1
                continue

            details = question.dim_details.get("dim4", {}) if isinstance(question.dim_details, dict) else {}
            if (
                source == "conservative_fallback"
                or (isinstance(details, dict) and details.get("fallback_used") is True)
            ):
                fallback_count += 1

            level_counts[level] += 1
            source_counts[source] = source_counts.get(source, 0) + 1
            scored_questions.append(question)
            raw_score_sum += question_score
            weight = self._dimension_level_weight(level)
            weighted_score_sum += question_score * weight
            total_weight += weight

        question_count = len(scored_questions)
        level_ratios = {
            level: round(self._ratio(count, question_count), 4)
            for level, count in level_counts.items()
        }
        raw_question_average = raw_score_sum / question_count if question_count else 0.0
        weighted_question_average = weighted_score_sum / total_weight if total_weight else 0.0
        breakdown = {
            "level_counts": level_counts,
            "level_ratios": level_ratios,
            "source_counts": source_counts,
            "level_weights": self.DIM4_LEVEL_WEIGHTS,
            "raw_question_average": round(raw_question_average, 4),
            "weighted_question_average": round(weighted_question_average, 4),
            "weighted_score_sum": round(weighted_score_sum, 4),
            "total_weight": round(total_weight, 4),
            "not_applicable_count": not_applicable_count,
            "review_count": review_question_count,
            "review_failed_excluded_count": failed_excluded_count,
            **second_review_counts,
            "l1_excluded_count": 0,
            "fallback_count": fallback_count,
            "valid_score_question_count": question_count,
            "unscored_question_count": ignored_question_count,
            "unknown_level_count": ignored_question_count,
            "auto_ignored_count": ignored_question_count,
            "high_level_question_count": level_counts["L4"] + level_counts["L5"],
            "aggregation_rule": "能稳定自动判定 L1-L5 的题纳入建模解题复杂度评分；纯计算、直接代公式或无真实解题组织负担的题自动未覆盖；卷级主分按题目等级加权，高等级题权重更高。",
        }

        if question_count == 0:
            zero_warning_messages = (
                ["部分题目因图文信息不足或判定不稳定，未计入该维度。"]
                if second_review_counts["second_review_failed_count"] > 0
                else []
            )
            return PaperDimensionSummary(
                dimension_code="dim4",
                dimension_name=self.DIMENSION_NAMES["dim4"],
                paper_score=0.0,
                level=0,
                level_label="未覆盖",
                total_question_score=0.0,
                question_count=0,
                sample_warning=False,
                evidence="建模解题复杂度暂无可评分题目，未计入综合分。",
                warning_messages=zero_warning_messages,
                counted_questions=[],
                review_question_count=review_question_count,
                score_status="not_covered",
                score_breakdown=breakdown,
            )

        total_question_score = sum(question.score for question in scored_questions)
        paper_score = weighted_question_average
        level, level_label = self._calculate_level(paper_score)
        sample_warning = 0 < question_count < 2

        warning_messages: List[str] = []
        for question in scored_questions:
            warning_messages.extend(self._sanitize_dim4_warning(item) for item in question.dim_warnings.get("dim4", []))
        if sample_warning:
            warning_messages.append("该维度当前样本题量偏少，整卷结论稳定性有限。")
        if second_review_counts["second_review_failed_count"] > 0:
            warning_messages.append("部分题目因图文信息不足或判定不稳定，未计入该维度。")
        deduped_warnings = list(
            dict.fromkeys(message.strip() for message in warning_messages if message.strip())
        )

        evidence_parts = [
            f"共 {question_count} 道题纳入建模解题复杂度评分",
            "按题目等级加权，高等级题权重更高",
        ]
        evidence_parts.append(f"权重得分 {paper_score:.1f} 分，判定为 {level_label}")
        breakdown["technical_evidence"] = "；".join(evidence_parts) + "。"
        evidence = self._build_dim4_score_overview(paper_score)

        return PaperDimensionSummary(
            dimension_code="dim4",
            dimension_name=self.DIMENSION_NAMES["dim4"],
            paper_score=paper_score,
            level=level,
            level_label=level_label,
            total_question_score=total_question_score,
            question_count=question_count,
            sample_warning=sample_warning,
            evidence=evidence,
            warning_messages=deduped_warnings,
            counted_questions=self._select_representative_questions(scored_questions, "dim4"),
            review_question_count=review_question_count,
            score_breakdown=breakdown,
        )

    def _aggregate_dim1(self, question_scores: List[QuestionDimensionScore]) -> PaperDimensionSummary:
        applicable_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, "dim1") == "applicable"
        ]
        review_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, "dim1") in {"review", "needs_second_review"}
        ]

        question_count = len(applicable_questions)
        review_question_count = len(review_questions)
        second_review_counts = self._second_review_counts(question_scores, "dim1")
        review_failed_excluded_count = sum(
            1
            for question in question_scores
            if self._dimension_status(question, "dim1") == SECOND_REVIEW_STATUS_FAILED_EXCLUDED
        )
        if question_count == 0:
            return PaperDimensionSummary(
                dimension_code="dim1",
                dimension_name=self.DIMENSION_NAMES["dim1"],
                paper_score=0.0,
                level=0,
                level_label="未覆盖",
                total_question_score=0.0,
                question_count=0,
                sample_warning=False,
                evidence="数学运算自动评分未覆盖，未计入综合分。",
                warning_messages=[],
                counted_questions=[],
                review_question_count=review_question_count,
                score_status="not_covered",
                score_breakdown={
                    **second_review_counts,
                    "review_failed_excluded_count": review_failed_excluded_count,
                },
            )

        pure_questions = [
            question
            for question in applicable_questions
            if self._dim1_bucket_for_question(question) == "pure_calculation"
        ]
        embedded_questions = [
            question
            for question in applicable_questions
            if self._dim1_bucket_for_question(question) == "embedded_calculation"
        ]

        pure_average = self._average_dimension_score(pure_questions, "dim1")
        embedded_average = self._average_dimension_score(embedded_questions, "dim1")

        if pure_questions and embedded_questions:
            pure_weight, embedded_weight = (0.7, 0.3) if len(pure_questions) >= 2 else (0.5, 0.5)
            rule_label = "纯计算与嵌入式计算加权"
        elif pure_questions:
            pure_weight, embedded_weight = 1.0, 0.0
            rule_label = "纯计算专项"
        else:
            pure_weight, embedded_weight = 0.0, 1.0
            rule_label = "嵌入式计算估计"

        paper_score = pure_average * pure_weight + embedded_average * embedded_weight
        level, level_label = self._calculate_level(paper_score)
        sample_warning = 0 < question_count < 2

        warning_messages: List[str] = []
        for question in applicable_questions:
            warning_messages.extend(question.dim_warnings.get("dim1", []))
        if sample_warning:
            warning_messages.append("该维度当前样本题量偏少，整卷结论稳定性有限。")
        deduped_warnings = list(
            dict.fromkeys(message.strip() for message in warning_messages if message.strip())
        )

        breakdown = {
            "pure_calculation": {
                "question_count": len(pure_questions),
                "average_score": round(pure_average, 2),
                "weight": pure_weight,
            },
            "embedded_calculation": {
                "question_count": len(embedded_questions),
                "average_score": round(embedded_average, 2),
                "weight": embedded_weight,
            },
            "aggregation_rule": rule_label,
            **second_review_counts,
            "review_failed_excluded_count": review_failed_excluded_count,
        }

        evidence = self._build_dim1_score_overview(paper_score)

        return PaperDimensionSummary(
            dimension_code="dim1",
            dimension_name=self.DIMENSION_NAMES["dim1"],
            paper_score=paper_score,
            level=level,
            level_label=level_label,
            total_question_score=sum(question.score for question in applicable_questions),
            question_count=question_count,
            sample_warning=sample_warning,
            evidence=evidence,
            warning_messages=deduped_warnings,
            counted_questions=self._select_representative_questions(applicable_questions, "dim1"),
            review_question_count=review_question_count,
            score_breakdown=breakdown,
        )

    def _aggregate_dim5(self, question_scores: List[QuestionDimensionScore]) -> PaperDimensionSummary:
        applicable_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, "dim5") == "applicable"
        ]
        review_questions = [
            question
            for question in question_scores
            if self._dimension_status(question, "dim5") == "review"
        ]

        bucket_counts = {bucket: 0 for bucket in self.DIM5_BUCKET_LABELS}
        level_counts = {f"L{index}": 0 for index in range(1, 6)}
        domain_counts: Dict[str, int] = {}
        source_counts: Dict[str, int] = {}
        scored_questions: List[QuestionDimensionScore] = []
        raw_score_sum = 0.0
        weighted_score_sum = 0.0
        total_weight = 0.0
        unscored_applicable_count = 0
        fallback_failed_count = sum(
            1
            for question in question_scores
            if self._dim5_source_for_question(question) == "llm_dim5_retry_failed"
        )
        question_bank_count = 0
        topic_structure_upshift_count = 0
        llm_fallback_count = 0
        for question in applicable_questions:
            bucket = self._dim5_bucket_for_question(question)
            bucket = bucket if bucket in bucket_counts else "unknown"
            bucket_counts[bucket] += 1
            question_score = self._valid_dim5_question_score(question)
            question_level = self._dim5_level_for_question(question)
            if question_score is None:
                unscored_applicable_count += 1
                continue
            if question_level not in level_counts:
                unscored_applicable_count += 1
                continue

            source = self._dim5_source_for_question(question)
            source_counts[source] = source_counts.get(source, 0) + 1
            details = self._dim5_details_for_question(question)
            domain = str(details.get("canonical_knowledge_domain") or "unknown").strip() or "unknown"
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            if source == "question_bank" or str(details.get("gaosi_classification_source") or "").strip() == "question_bank":
                question_bank_count += 1
            if source == "llm_dim5_retry":
                llm_fallback_count += 1
            if self._dim5_is_topic_structure_upshift(question):
                topic_structure_upshift_count += 1
            scored_questions.append(question)
            raw_score_sum += question_score
            level_counts[question_level] += 1
            weight = float(self.DIM5_LEVEL_WEIGHTS.get(question_level, 1))
            weighted_score_sum += question_score * weight
            total_weight += weight

        question_count = len(scored_questions)
        review_question_count = len(review_questions)
        raw_question_average = raw_score_sum / question_count if question_count else 0.0
        weighted_question_average = weighted_score_sum / total_weight if total_weight else 0.0
        level_ratios = {
            level: round(self._ratio(count, question_count), 4)
            for level, count in level_counts.items()
        }
        bucket_ratio_denominator = len(applicable_questions)
        bucket_ratios = {
            bucket: round(self._ratio(count, bucket_ratio_denominator), 4)
            for bucket, count in bucket_counts.items()
        }
        breakdown = {
            "level_weights": dict(self.DIM5_LEVEL_WEIGHTS),
            "level_counts": dict(level_counts),
            "level_ratios": level_ratios,
            "bucket_counts": dict(bucket_counts),
            "bucket_ratios": bucket_ratios,
            "bucket_ratio_denominator": bucket_ratio_denominator,
            "domain_counts": dict(domain_counts),
            "source_counts": dict(source_counts),
            "question_bank_count": question_bank_count,
            "topic_structure_upshift_count": topic_structure_upshift_count,
            "llm_fallback_count": llm_fallback_count,
            "fallback_failed_count": fallback_failed_count,
            "beyond_question_count": level_counts["L5"],
            "aggregation_rule": "知识范围等级加权均分",
            "raw_question_average": round(raw_question_average, 4),
            "weighted_question_average": round(weighted_question_average, 4),
            "question_score_average": round(raw_question_average, 4),
            "question_score_sum": round(raw_score_sum, 4),
            "weighted_score_sum": round(weighted_score_sum, 4),
            "total_weight": round(total_weight, 4),
            "valid_score_question_count": question_count,
            "unscored_applicable_count": unscored_applicable_count,
            "unknown_scored_count": bucket_counts["unknown"]
            - sum(
                1
                for question in applicable_questions
                if self._dim5_bucket_for_question(question) == "unknown"
                and self._valid_dim5_question_score(question) is None
            ),
            "unknown_unscored_count": sum(
                1
                for question in applicable_questions
                if self._dim5_bucket_for_question(question) == "unknown"
                and self._valid_dim5_question_score(question) is None
            ),
            "final_score": weighted_question_average,
        }

        if question_count == 0:
            return PaperDimensionSummary(
                dimension_code="dim5",
                dimension_name=self.DIMENSION_NAMES["dim5"],
                paper_score=0.0,
                level=0,
                level_label="未覆盖",
                total_question_score=0.0,
                question_count=0,
                sample_warning=False,
                evidence="知识广度自动评分未覆盖，未计入综合分。",
                warning_messages=[],
                counted_questions=[],
                review_question_count=review_question_count,
                score_status="not_covered",
                score_breakdown=breakdown,
            )

        paper_score = weighted_question_average
        level, level_label = self._calculate_level(paper_score)

        evidence = (
            f"共 {question_count} 道题纳入知识范围评分；"
            f"按知识范围等级权重计算；"
            f"权重得分 {paper_score:.1f} 分，判定为{level_label}。"
        )

        warning_messages: List[str] = []
        if unscored_applicable_count:
            warning_messages.append(f"有 {unscored_applicable_count} 道题缺少合法题级分或知识范围等级，未计入知识范围评分。")
        for question in applicable_questions:
            warning_messages.extend(question.dim_warnings.get("dim5", []))
        deduped_warnings = list(
            dict.fromkeys(message.strip() for message in warning_messages if message.strip())
        )

        return PaperDimensionSummary(
            dimension_code="dim5",
            dimension_name=self.DIMENSION_NAMES["dim5"],
            paper_score=paper_score,
            level=level,
            level_label=level_label,
            total_question_score=sum(question.score for question in scored_questions),
            question_count=question_count,
            sample_warning=False,
            evidence=evidence,
            warning_messages=deduped_warnings,
            counted_questions=self._select_representative_questions(scored_questions, "dim5"),
            review_question_count=review_question_count,
            score_breakdown=breakdown,
        )

    def aggregate_all_dimensions(
        self,
        question_scores: List[QuestionDimensionScore],
    ) -> Dict[str, PaperDimensionSummary]:
        return {
            dim_code: self.aggregate(question_scores, dim_code)
            for dim_code in ["dim1", "dim2", "dim3", "dim4", "dim5", "dim6"]
        }

    def _select_representative_questions(
        self,
        applicable_questions: List[QuestionDimensionScore],
        dimension_code: str,
    ) -> List[Dict[str, object]]:
        filtered_questions = [
            question
            for question in applicable_questions
            if not self._is_low_quality_candidate(question, dimension_code)
        ]
        candidates = filtered_questions or applicable_questions

        ranked = sorted(
            candidates,
            key=lambda question: self._representative_sort_key(question, dimension_code),
        )

        selected: List[Dict[str, object]] = []
        seen_display_labels: set[str] = set()

        for question in ranked:
            question_display_label = self._build_question_display_label(question)
            dedupe_key = question_display_label or question.question_id
            if dedupe_key in seen_display_labels:
                continue

            dim_score = question.dim_scores.get(dimension_code, 0.0)
            level_code = self._question_level_code(question, dimension_code, dim_score)
            seen_display_labels.add(dedupe_key)
            selected_item = {
                "page_no": question.page_no,
                "question_no": question.question_no or question.question_id,
                "question_label_raw": question.question_label_raw or question.question_no or question.question_id,
                "section_index_raw": question.section_index_raw or "",
                "question_display_label": question_display_label,
                "summary": question.question_summary or "",
                "score": round(dim_score, 1),
                "level_code": level_code,
                "difficulty_label": (
                    self._dim1_difficulty_label(level_code)
                    if dimension_code in {"dim1", "dim2", "dim3", "dim4", "dim5", "dim6"}
                    else ""
                ),
                "reason": self._build_display_reason(question, dimension_code),
                "full_reason": self._build_full_display_reason(question, dimension_code),
            }
            if dimension_code == "dim4":
                selected_item.update(self._dim4_counted_question_fields(question, level_code))
            if dimension_code == "dim5":
                selected_item.update(self._dim5_counted_question_fields(question, level_code))
            selected.append(selected_item)
            if len(selected) >= self.REPRESENTATIVE_LIMIT:
                break

        return selected

    @classmethod
    def _question_level_code(
        cls,
        question: QuestionDimensionScore,
        dimension_code: str,
        dim_score: object,
    ) -> str:
        details = question.dim_details.get(dimension_code, {}) if isinstance(question.dim_details, dict) else {}
        if isinstance(details, dict):
            for key in (f"{dimension_code}_level", "dim1_level", "knowledge_level"):
                level_code = str(details.get(key) or "").strip().upper()
                if level_code in {"L1", "L2", "L3", "L4", "L5"}:
                    return level_code
        if dimension_code == "dim4":
            return cls._dim4_level_for_question(question)
        if dimension_code == "dim1":
            return cls._dim1_level_from_score(dim_score)
        try:
            score_value = float(dim_score or 0.0)
        except (TypeError, ValueError):
            score_value = 0.0
        if score_value >= 9:
            return "L5"
        if score_value >= 8:
            return "L4"
        if score_value >= 6:
            return "L3"
        if score_value >= 4:
            return "L2"
        return "L1"

    @classmethod
    def _dimension_details(cls, question: QuestionDimensionScore, dimension_code: str) -> dict[str, Any]:
        details = question.dim_details.get(dimension_code, {}) if isinstance(question.dim_details, dict) else {}
        return details if isinstance(details, dict) else {}

    @classmethod
    def _dim2_model_types(cls, details: dict[str, Any]) -> set[str]:
        raw_model_types = details.get("geometry_model_types")
        if isinstance(raw_model_types, str):
            raw_items = raw_model_types.replace("，", ",").replace("、", ",").split(",")
        elif isinstance(raw_model_types, list):
            raw_items = raw_model_types
        else:
            raw_items = []
        return {str(item or "").strip().lower() for item in raw_items if str(item or "").strip()}

    @classmethod
    def _dim2_combined_evidence_text(
        cls,
        question: QuestionDimensionScore,
        details: dict[str, Any],
    ) -> str:
        parts: list[str] = [
            question.question_summary or "",
            question.dim_reasons.get("dim2", ""),
            str(details.get("evidence_summary") or ""),
            str(details.get("domain_gate_reason") or ""),
        ]
        for key in (
            "evidence_tags",
            "matched_geometry_knowledge_points",
            "display_geometry_knowledge_points",
        ):
            raw_items = details.get(key)
            if isinstance(raw_items, list):
                parts.extend(str(item or "") for item in raw_items)
        return " ".join(part.strip() for part in parts if str(part or "").strip())

    @classmethod
    def _is_stable_dim2_text_geometry_candidate(cls, question: QuestionDimensionScore) -> bool:
        details = cls._dimension_details(question, "dim2")
        task_form = str(details.get("task_form") or "").strip().lower()
        figure_complexity = str(details.get("figure_complexity") or "").strip().lower()
        image_dependency = str(details.get("image_dependency") or "").strip().lower()
        fallback_source = str(details.get("fallback_source") or "").strip()
        evidence_summary = str(details.get("evidence_summary") or "")
        model_types = cls._dim2_model_types(details)

        has_stable_geometry_facts = (
            task_form in {"explicit_visual", "geometry_embedded", "text_only_geometry"}
            or figure_complexity not in {"", "none"}
            or bool(model_types)
        )
        if not has_stable_geometry_facts:
            return False

        generic_visual_fallback = (
            fallback_source == "visual_geometry"
            and (
                evidence_summary.startswith("图像几何兜底事实")
                or model_types == {"composite_area_model"}
            )
        )
        if generic_visual_fallback:
            return False

        if (
            task_form == "text_only_geometry"
            and image_dependency in {"", "none", "helpful"}
            and (
                figure_complexity == "solid_3d"
                or "solid_formula" in model_types
                or fallback_source == "text_hollow_cylinder_geometry"
            )
        ):
            return True

        domain = str(details.get("geometry_domain_gate") or "").strip()
        if not domain:
            domain, _ = classify_dim2_geometry_domain(
                question.question_summary or question.dim_reasons.get("dim2", ""),
                details,
                parse_audit=None,
            )

        return domain in {"geometry_core", "geometry_area_relation", "solid_geometry"}

    def _is_low_quality_candidate(
        self,
        question: QuestionDimensionScore,
        dimension_code: str,
    ) -> bool:
        reason = (question.dim_reasons.get(dimension_code) or "").strip()
        if not reason:
            return True

        confidence = question.dim_confidences.get(dimension_code, 0.0)
        if confidence and confidence < self.REPRESENTATIVE_CONFIDENCE_THRESHOLD:
            return True

        if dimension_code in {"dim2", "dim3"}:
            warnings = question.dim_warnings.get(dimension_code, [])
            has_image_fallback_warning = any(
                hint in warning for hint in self.IMAGE_FALLBACK_HINTS for warning in warnings
            )
            if (
                has_image_fallback_warning
                and (
                    dimension_code != "dim2"
                    or not self._is_stable_dim2_text_geometry_candidate(question)
                )
            ):
                return True

        return False

    def _representative_sort_key(
        self,
        question: QuestionDimensionScore,
        dimension_code: str,
    ) -> tuple:
        reason = self._build_display_reason(question, dimension_code)
        warnings = question.dim_warnings.get(dimension_code, [])
        confidence = question.dim_confidences.get(dimension_code, 0.0)

        if dimension_code == "dim5":
            level_priority = {
                "L5": 0,
                "L4": 1,
                "L3": 2,
                "L2": 3,
                "L1": 4,
            }
            knowledge_level = self._dim5_level_for_question(question)
            return (
                level_priority.get(knowledge_level, 99),
                -question.dim_scores.get(dimension_code, 0.0),
                -confidence,
                -min(len(reason), 160),
                len(warnings),
                question.page_no if question.page_no is not None else 10**9,
                self._question_no_sort_key(question.question_no),
            )

        if dimension_code == "dim4":
            level_priority = {
                "L5": 0,
                "L4": 1,
                "L3": 2,
                "L2": 3,
                "L1": 4,
            }
            dim4_level = self._dim4_level_for_question(question)
            return (
                level_priority.get(dim4_level, 99),
                -question.dim_scores.get(dimension_code, 0.0),
                -confidence,
                -min(len(reason), 160),
                len(warnings),
                question.page_no if question.page_no is not None else 10**9,
                self._question_no_sort_key(question.question_no),
            )

        if dimension_code == "dim2":
            details = question.dim_details.get("dim2", {}) if isinstance(question.dim_details, dict) else {}
            if not isinstance(details, dict):
                details = {}
            domain = str(details.get("geometry_domain_gate") or "").strip()
            if not domain:
                domain, _ = classify_dim2_geometry_domain(
                    question.question_summary or question.dim_reasons.get("dim2", ""),
                    details,
                    parse_audit=None,
                )
            domain_priority = {
                "geometry_area_relation": 0,
                "solid_geometry": 0,
                "geometry_core": 1,
            }.get(domain, 2)
            fallback_source = str(details.get("fallback_source") or "")
            evidence_summary = str(details.get("evidence_summary") or "")
            generic_visual_fallback = int(
                fallback_source == "visual_geometry"
                and (
                    evidence_summary.startswith("图像几何兜底事实")
                    or details.get("geometry_model_types") == ["composite_area_model"]
                )
            )
            return (
                domain_priority,
                generic_visual_fallback,
                len(warnings),
                -question.dim_scores.get(dimension_code, 0.0),
                -confidence,
                -min(len(reason), 160),
                question.page_no if question.page_no is not None else 10**9,
                self._question_no_sort_key(question.question_no),
            )

        return (
            -question.dim_scores.get(dimension_code, 0.0),
            -confidence,
            -min(len(reason), 160),
            len(warnings),
            question.page_no if question.page_no is not None else 10**9,
            self._question_no_sort_key(question.question_no),
        )

    @classmethod
    def _build_display_reason(cls, question: QuestionDimensionScore, dimension_code: str) -> str:
        if dimension_code == "dim1":
            return cls._build_dim1_counted_question_reason(question)
        if dimension_code == "dim2":
            return cls._build_dim2_counted_question_reason(question)
        if dimension_code == "dim3":
            return cls._build_dim3_counted_question_reason(question)
        if dimension_code == "dim4":
            return cls._build_dim4_counted_question_reason(question)
        if dimension_code == "dim5":
            return cls._build_dim5_counted_question_reason(question)
        if dimension_code == "dim6":
            return cls._build_dim6_counted_question_reason(question)

        reason = " ".join((question.dim_reasons.get(dimension_code) or "").split()).strip()
        if not reason:
            return ""

        body = reason
        for marker in ("依据标签：", "核心事实："):
            body = body.split(marker, 1)[0].strip()

        source = ""
        if "依据来源：" in reason:
            source = reason.split("依据来源：", 1)[1].split("。", 1)[0].strip(" 。；;")

        if source:
            return cls._format_counted_question_analysis(f"{body} 依据：{source}".strip())
        return cls._format_counted_question_analysis(body)

    @classmethod
    def _build_full_display_reason(cls, question: QuestionDimensionScore, dimension_code: str) -> str:
        if dimension_code == "dim1":
            return cls._build_dim1_counted_question_reason(question)
        if dimension_code == "dim2":
            return cls._build_dim2_counted_question_reason(question)
        if dimension_code == "dim3":
            return cls._build_dim3_counted_question_reason(question)
        if dimension_code == "dim4":
            return cls._build_dim4_counted_question_reason(question)
        if dimension_code == "dim5":
            return cls._build_dim5_counted_question_reason(question)
        if dimension_code == "dim6":
            return cls._build_dim6_counted_question_reason(question)
        return cls._format_counted_question_analysis(question.dim_reasons.get(dimension_code) or "")

    @classmethod
    def _dim4_counted_question_fields(
        cls,
        question: QuestionDimensionScore,
        level_code: str = "",
    ) -> Dict[str, str]:
        details = question.dim_details.get("dim4", {}) if isinstance(question.dim_details, dict) else {}
        if not isinstance(details, dict):
            details = {}
        normalized_level = level_code or cls._dim4_level_for_question(question)
        knowledge_point = cls._dim4_knowledge_point_text(question, details)
        practice_level = cls._dim4_practice_level_text(normalized_level)
        return {
            "knowledge_point_text": knowledge_point,
            "practice_level_text": practice_level,
            "score_reason": cls._dim4_score_reason(
                question,
                details,
                normalized_level,
                knowledge_point,
            ),
        }

    @classmethod
    def _build_dim4_counted_question_reason(cls, question: QuestionDimensionScore) -> str:
        level_code = cls._dim4_level_for_question(question)
        fields = cls._dim4_counted_question_fields(question, level_code)
        difficulty = cls._dim1_difficulty_label(level_code)
        knowledge_point = fields["knowledge_point_text"]
        practice_level = fields["practice_level_text"]
        score_reason = fields["score_reason"]

        if knowledge_point and practice_level:
            target = f"本题是{knowledge_point}中的{practice_level}"
        elif knowledge_point:
            target = f"本题是{knowledge_point}的建模解题题"
        elif practice_level:
            target = f"本题属于{practice_level}题"
        else:
            target = "本题属于建模解题题"
        return f"{difficulty}：{target}；{score_reason}"

    @classmethod
    def _dim4_knowledge_point_text(
        cls,
        question: QuestionDimensionScore,
        details: dict[str, Any],
    ) -> str:
        for key in (
            "knowledge_point",
            "canonical_knowledge_point",
            "primary_knowledge_point",
            "topic_knowledge_point",
        ):
            point = cls._clean_dim4_text(details.get(key))
            if cls._is_specific_dim4_knowledge_text(point):
                return point

        for key in ("evidence_tags", "knowledge_tags", "core_knowledge_units"):
            raw_items = details.get(key)
            if not isinstance(raw_items, (list, tuple, set)):
                continue
            points = [
                cls._clean_dim4_text(item)
                for item in raw_items
                if cls._is_specific_dim4_knowledge_text(item)
            ]
            if points:
                return "、".join(dict.fromkeys(points[:2]))

        summary = cls._clean_dim4_text(question.question_summary)
        if cls._is_specific_dim4_knowledge_text(summary):
            return summary
        return ""

    @classmethod
    def _dim4_practice_level_text(cls, level_code: str) -> str:
        return cls.DIM4_PRACTICE_LEVEL_LABELS.get(
            str(level_code or "").strip().upper(),
            "",
        )

    @classmethod
    def _dim4_score_reason(
        cls,
        question: QuestionDimensionScore,
        details: dict[str, Any],
        level_code: str,
        knowledge_point: str,
    ) -> str:
        evidence_note = cls._dim4_note_from_evidence(
            details.get("evidence_summary")
            or details.get("anchor_evidence")
            or question.dim_reasons.get("dim4")
            or ""
        )
        if evidence_note:
            return evidence_note

        template_note = cls._dim4_template_score_reason(details, level_code, knowledge_point)
        if template_note:
            return template_note

        if level_code == "L5":
            return "难点在于要从全局构造或证明可行性，局部算对还不够。"
        if level_code == "L4":
            return "难点在于不能直接套模板，需要构造中间量、分类回查或重组关系。"
        if level_code == "L3":
            return "难点在于要完成一次策略转换或模型迁移，再沿新关系推进。"
        if level_code == "L2":
            return "难点在于要在常规模板上做少量调整，分清变化后的条件。"
        return "难点在于要识别基础模板，并按常规关系直接推进。"

    @classmethod
    def _dim4_template_score_reason(
        cls,
        details: dict[str, Any],
        level_code: str,
        knowledge_point: str,
    ) -> str:
        point_candidates = [
            cls._clean_dim4_text(details.get("knowledge_point")),
            cls._clean_dim4_text(details.get("canonical_knowledge_point")),
            cls._clean_dim4_text(details.get("primary_knowledge_point")),
            cls._clean_dim4_text(knowledge_point),
        ]
        for point in point_candidates:
            if not point:
                continue
            exact_note = cls.DIM4_KNOWLEDGE_DIFFICULTY_REASONS.get(point)
            if exact_note:
                return exact_note
        for point in point_candidates:
            if not point:
                continue
            for key, note in cls.DIM4_KNOWLEDGE_DIFFICULTY_REASONS.items():
                if key in point or point in key:
                    return note

        strategy_candidates = [
            cls._clean_dim4_text(details.get("breakthrough_type")),
            cls._clean_dim4_text(details.get("construction_requirement")),
            cls._clean_dim4_text(details.get("exploration_space")),
        ]
        if details.get("global_strategy_required") in (1, "1", True):
            return "难点在于要从全局检查方案是否成立，局部满足条件还不够。"
        for item in strategy_candidates:
            note = cls.DIM4_STRATEGY_DIFFICULTY_REASONS.get(item)
            if note:
                return note
        shift_count = str(details.get("strategy_shift_count") or "").strip()
        if shift_count in {"2", "3+"}:
            return "难点在于解题过程中不止一次换策略，需要把前后关系重新接上。"
        if shift_count == "1":
            return "难点在于中途要完成一次策略转换，不能一直沿常规模板推进。"
        if str(details.get("template_fit") or "").strip().lower() == "reframed":
            return "难点在于要换一种表示或看法，把原条件重组成可推进的关系。"
        if str(details.get("template_fit") or "").strip().lower() == "non_routine":
            return "难点在于题目不贴合常规模板，需要先判断可行路径。"
        if level_code == "L4":
            return "难点在于不能直接套模板，需要构造中间量、分类回查或重组关系。"
        if level_code == "L5":
            return "难点在于要从全局构造或证明可行性，局部算对还不够。"
        return ""

    @classmethod
    def _dim4_note_from_evidence(cls, value: object) -> str:
        text = cls._clean_dim4_text(value)
        if not text:
            return ""
        for marker in cls.COUNTED_QUESTION_FULL_REASON_HIDDEN_MARKERS:
            text = text.split(marker, 1)[0].strip()
        match = cls.COUNTED_QUESTION_LEVEL_DESCRIPTOR_PATTERN.match(text)
        if match:
            text = match.group(2).strip()
        if "内定位为" in text and "。" in text:
            text = text.split("。", 1)[1].strip()
        text = text.rstrip("。；;，,")
        if not text:
            return ""
        if cls._is_probably_english_display_text(text):
            return ""
        if any(fragment in text for fragment in cls.DIM4_SCORE_REASON_FORBIDDEN_FRAGMENTS):
            return ""
        for prefix in ("本题难点在于", "难点在于"):
            if text.startswith(prefix):
                body = text[len(prefix) :].strip("，,；;。 ")
                return f"难点在于{body}。" if body else ""
        if text.startswith("需要"):
            body = text[2:].strip("，,；;。 ")
            return f"难点在于要{body}。" if body else ""
        if text.startswith("要"):
            return f"难点在于{text}。"
        if text.startswith("只需") or text.startswith("直接") or text.startswith("可以直接"):
            return "难点在于要识别这是一道基础模板题，按常规关系直接推进。"
        return f"难点在于{text}。"

    @classmethod
    def _is_probably_english_display_text(cls, value: object) -> bool:
        text = cls._clean_dim4_text(value)
        if not text:
            return False

        english_words = cls.ENGLISH_WORD_PATTERN.findall(text)
        if not english_words:
            return False

        cjk_count = len(cls.CJK_TEXT_PATTERN.findall(text))
        ascii_letter_count = sum(1 for char in text if char.isascii() and char.isalpha())
        stopword_hits = sum(1 for word in english_words if word.lower() in cls.ENGLISH_DISPLAY_STOPWORDS)
        has_english_sentence = len(english_words) >= 4 or stopword_hits >= 2

        if cjk_count == 0:
            return has_english_sentence or ascii_letter_count >= 20

        return (
            ascii_letter_count >= 30
            and ascii_letter_count > max(12, cjk_count * 2.5)
            and stopword_hits >= 1
        )

    @classmethod
    def _is_specific_dim4_knowledge_text(cls, value: object) -> bool:
        text = cls._clean_dim4_text(value)
        if not text or len(text) < 2:
            return False
        lowered = text.lower()
        if lowered in cls.DIM4_GENERIC_KNOWLEDGE_POINTS or "dim4" in lowered:
            return False
        return text not in cls.DIM4_GENERIC_KNOWLEDGE_POINTS

    @staticmethod
    def _clean_dim4_text(value: object) -> str:
        return " ".join(str(value or "").split()).strip(" 。；;，,")

    @classmethod
    def _dim5_counted_question_fields(
        cls,
        question: QuestionDimensionScore,
        level_code: str = "",
    ) -> Dict[str, str]:
        details = question.dim_details.get("dim5", {}) if isinstance(question.dim_details, dict) else {}
        if not isinstance(details, dict):
            details = {}
        normalized_level = level_code or cls._dim5_level_for_question(question)
        knowledge_point = cls._dim5_knowledge_point_text(question, details)
        knowledge_source = cls._dim5_knowledge_source_text(details)
        return {
            "knowledge_source_text": knowledge_source,
            "knowledge_point_text": knowledge_point,
            "score_reason": cls._dim5_score_reason(
                question,
                details,
                normalized_level,
                knowledge_point,
                knowledge_source,
            ),
        }

    @classmethod
    def _build_dim5_counted_question_reason(cls, question: QuestionDimensionScore) -> str:
        level_code = cls._dim5_level_for_question(question)
        fields = cls._dim5_counted_question_fields(question, level_code)
        difficulty = cls._dim1_difficulty_label(level_code)
        knowledge_source = fields["knowledge_source_text"]
        knowledge_point = fields["knowledge_point_text"]
        score_reason = fields["score_reason"]

        if knowledge_source and knowledge_point:
            target = f"本题属于{knowledge_source}的{knowledge_point}"
        elif knowledge_source:
            target = f"本题属于{knowledge_source}知识范围"
        elif knowledge_point:
            target = f"本题主要考查{knowledge_point}"
        else:
            target = "本题主要考查可识别的核心知识点"
        return f"{difficulty}：{target}；{score_reason}"

    @classmethod
    def _dim5_knowledge_source_text(cls, details: dict[str, Any]) -> str:
        bucket = str(details.get("knowledge_source_bucket") or "").strip()
        band = cls._clean_dim5_text(details.get("band"))
        grade_label = cls._dim5_grade_label(details.get("gaosi_grade"))

        evidence_blob = cls._clean_dim5_text(
            " ".join(
                str(details.get(key) or "")
                for key in (
                    "level_evidence",
                    "evidence_summary",
                    "canonical_knowledge_point",
                    "canonical_alias_hits",
                    "core_knowledge_units",
                    "knowledge_tags",
                )
            )
        )
        has_junior_core = any(
            signal in evidence_blob
            for signal in ("七年级核心", "初中核心", "方程组", "一次函数", "不等式", "整式", "有理数")
        )

        if bucket in {"low_gaosi", "high_gaosi", "beyond"}:
            if bucket == "low_gaosi":
                return f"{grade_label}奥数" if grade_label else "三四年级奥数"
            if bucket == "high_gaosi":
                return f"{grade_label}奥数" if grade_label else "五六年级奥数"
            if has_junior_core:
                return "七年级核心前置"
            return f"{grade_label}奥数较难" if grade_label else "六年级奥数较难"

        if bucket == "junior_bridge":
            return "七年级基础前置"

        if bucket == "school" or "校内" in band:
            return f"{grade_label}校内" if grade_label else "校内"

        if "奥数" in band:
            return f"{grade_label}奥数" if grade_label else "奥数"

        return ""

    @classmethod
    def _dim5_grade_label(cls, value: object) -> str:
        text = cls._clean_dim5_text(value)
        if not text:
            return ""
        if "5、6" in text or "5,6" in text or "五六" in text or "五、六" in text:
            return "五六年级"
        for key, label in cls.DIM5_GRADE_LABELS.items():
            if key in text:
                return f"{label}及以前" if "及以前" in text else label
        return ""

    @classmethod
    def _dim5_grade_label_from_band(cls, band: str) -> str:
        if "5、6年级" in band or "五六年级" in band or "五、六年级" in band:
            return "五六年级"
        if "4年级及以前" in band or "四年级及以前" in band:
            return "四年级及以前"
        return ""

    @classmethod
    def _dim5_knowledge_point_text(
        cls,
        question: QuestionDimensionScore,
        details: dict[str, Any],
    ) -> str:
        for key in ("canonical_knowledge_point", "primary_knowledge_point"):
            point = cls._clean_dim5_text(details.get(key))
            if cls._is_specific_dim5_knowledge_text(point):
                return point

        for key in ("knowledge_tags", "core_knowledge_units", "canonical_alias_hits"):
            points = cls._dim5_specific_terms(details.get(key), limit=2)
            if points:
                return "、".join(points)

        summary = cls._clean_dim5_text(question.question_summary)
        if cls._is_specific_dim5_knowledge_text(summary):
            return summary
        return ""

    @classmethod
    def _dim5_score_reason(
        cls,
        question: QuestionDimensionScore,
        details: dict[str, Any],
        level_code: str,
        knowledge_point: str,
        knowledge_source: str,
    ) -> str:
        evidence_note = cls._dim5_note_from_evidence(
            details.get("level_evidence")
            or details.get("evidence_summary")
            or question.dim_reasons.get("dim5")
            or ""
        )
        if evidence_note:
            return evidence_note

        template_note = cls._dim5_template_score_reason(details, level_code, knowledge_point)
        if template_note:
            return template_note

        if knowledge_source == "初中前置":
            return "难点在于要把初中前置关系转成小学题目里的数量关系。"
        if level_code == "L5":
            return "难点在于要把多个条件或模型放在一起推进，中间一步出错会影响后续判断。"
        if level_code == "L4":
            return "难点在于要先看出题目隐藏的模型关系，再选择对应的方法处理。"
        if level_code == "L3":
            return "难点在于要把校内知识向外延伸一步，先整理关系再计算。"
        if level_code == "L2" or bool(details.get("canonical_direct_formula_guard")):
            return "难点在于要把题目中的已知量和公式关系对应准确。"
        return "难点在于要准确读出题意，并完成基础概念或一步应用。"

    @classmethod
    def _dim5_template_score_reason(
        cls,
        details: dict[str, Any],
        level_code: str,
        knowledge_point: str,
    ) -> str:
        point_candidates = [
            cls._clean_dim5_text(details.get("canonical_knowledge_point")),
            cls._clean_dim5_text(details.get("primary_knowledge_point")),
            cls._clean_dim5_text(knowledge_point),
        ]
        point_candidates.extend(cls._dim5_specific_terms(details.get("knowledge_tags"), limit=3))
        point_candidates.extend(cls._dim5_specific_terms(details.get("core_knowledge_units"), limit=3))
        point_candidates.extend(cls._dim5_specific_terms(details.get("canonical_alias_hits"), limit=3))

        for point in point_candidates:
            if not point:
                continue
            exact_note = cls.DIM5_POINT_DIFFICULTY_REASONS.get(point)
            if exact_note:
                return exact_note

        for point in point_candidates:
            if not point:
                continue
            for key, note in cls.DIM5_POINT_DIFFICULTY_REASONS.items():
                if key in point or point in key:
                    return note

        domain = str(
            details.get("canonical_knowledge_domain")
            or details.get("knowledge_domain")
            or details.get("domain")
            or ""
        ).strip()
        if domain in cls.DIM5_DOMAIN_DIFFICULTY_REASONS:
            return cls.DIM5_DOMAIN_DIFFICULTY_REASONS[domain]

        if level_code == "L5":
            return "难点在于要把多个条件或模型放在一起推进，中间一步出错会影响后续判断。"
        if level_code == "L4":
            return "难点在于要先看出题目隐藏的模型关系，再选择对应的方法处理。"
        return ""

    @classmethod
    def _dim5_note_from_evidence(cls, value: object) -> str:
        text = cls._clean_dim5_text(value)
        if not text:
            return ""
        for marker in cls.COUNTED_QUESTION_FULL_REASON_HIDDEN_MARKERS:
            text = text.split(marker, 1)[0].strip()
        match = cls.COUNTED_QUESTION_LEVEL_DESCRIPTOR_PATTERN.match(text)
        if match:
            text = match.group(2).strip()
        text = text.rstrip("。；;，,")
        if not text:
            return ""
        if any(fragment in text for fragment in cls.DIM5_SCORE_REASON_FORBIDDEN_FRAGMENTS):
            return ""
        for prefix in ("本题难点在于", "难点在于"):
            if text.startswith(prefix):
                body = text[len(prefix) :].strip("，,；;。 ")
                return f"难点在于{body}。" if body else ""
        if text.startswith("需要"):
            body = text[2:].strip("，,；;。 ")
            return f"难点在于要{body}。" if body else ""
        if text.startswith("要"):
            return f"难点在于{text}。"
        if text.startswith("只需") or text.startswith("直接"):
            body = text.strip("，,；;。 ")
            return f"难点在于{body}时容易看错条件。"
        return f"难点在于{text}。"

    @classmethod
    def _dim5_specific_terms(cls, value: object, *, limit: int) -> List[str]:
        if isinstance(value, dict):
            raw_items = value.values()
        elif isinstance(value, (list, tuple, set)):
            raw_items = value
        else:
            raw_items = [value]
        terms: List[str] = []
        for item in raw_items:
            term = cls._clean_dim5_text(item)
            if not cls._is_specific_dim5_knowledge_text(term):
                continue
            if term not in terms:
                terms.append(term)
            if len(terms) >= limit:
                break
        return terms

    @classmethod
    def _is_specific_dim5_knowledge_text(cls, value: object) -> bool:
        text = cls._clean_dim5_text(value)
        return bool(text) and text not in cls.DIM5_GENERIC_KNOWLEDGE_POINTS and len(text) >= 2

    @staticmethod
    def _clean_dim5_text(value: object) -> str:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            return ""
        return (
            text.replace("竞赛数学导引", "奥数")
            .replace("高思导引", "奥数")
            .strip(" 。；;，,")
        )

    @classmethod
    def _build_dim1_counted_question_reason(cls, question: QuestionDimensionScore) -> str:
        score = question.dim_scores.get("dim1", 0.0)
        details = question.dim_details.get("dim1", {}) if isinstance(question.dim_details, dict) else {}
        if not isinstance(details, dict):
            details = {}

        range_label = str(
            details.get("knowledge_range_label")
            or details.get("display_knowledge_range_label")
            or ""
        ).strip()
        points = cls._dim1_display_points(details)

        if range_label and points:
            target = f"{range_label}的{points}"
        elif points:
            target = points
        elif range_label:
            target = f"{range_label}的计算知识"
        else:
            target = cls._dim1_summary_or_fallback_knowledge(question, details)

        dim1_level = str(details.get("dim1_level") or "").strip().upper()
        if not dim1_level:
            dim1_level = cls._dim1_level_from_score(score)

        note = cls.DIM1_COUNTED_QUESTION_LEVEL_NOTES.get(
            dim1_level,
            cls.DIM1_COUNTED_QUESTION_LEVEL_NOTES["L1"],
        )

        return f"{cls._dim1_difficulty_label(dim1_level)}：主要考查{target}；{note}"

    @classmethod
    def _dim1_display_points(cls, details: dict[str, Any]) -> str:
        for key in ("matched_knowledge_points", "display_knowledge_points"):
            raw_points = details.get(key)
            if not isinstance(raw_points, list):
                continue
            points = [
                str(item).strip()
                for item in raw_points
                if cls._is_specific_dim1_knowledge_text(item)
            ]
            if points:
                return "、".join(points[:2])
        return ""

    @classmethod
    def _is_specific_dim1_knowledge_text(cls, value: object) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        generic_terms = {
            "计算",
            "核心计算",
            "核心计算能力",
            "综合问题",
            "综合题",
            "综合题型",
            "基础题型",
        }
        return text not in generic_terms and len(text) >= 2

    @classmethod
    def _dim1_summary_or_fallback_knowledge(
        cls,
        question: QuestionDimensionScore,
        details: dict[str, Any],
    ) -> str:
        summary = str(question.question_summary or "").strip().rstrip("。；;，,")
        if cls._is_specific_dim1_knowledge_text(summary):
            return summary

        calc_subtype = str(details.get("calc_subtype") or "").strip().lower()
        number_mix = str(details.get("number_mix") or "").strip().lower()
        step_chain = str(details.get("step_chain") or "").strip()
        structural_method = str(details.get("structural_method") or "").strip().lower()
        patterns = details.get("structure_patterns") or []
        pattern_set = {str(item or "").strip().lower() for item in patterns if str(item or "").strip()}

        if calc_subtype == "proportion_equation":
            return "比例计算"
        if calc_subtype == "equation":
            return "方程计算"
        if calc_subtype == "defined_operation":
            return "定义新运算"
        if calc_subtype == "sequence_series":
            return "数列计算"
        if calc_subtype == "nested_fraction":
            return "繁分式计算"
        if calc_subtype == "fraction_comparison":
            return "分数比较大小"
        if calc_subtype == "factorial_ratio":
            return "阶乘约分"
        if {
            "fraction_decimal_percent_conversion",
            "reciprocal_conversion",
            "factorial_cancellation",
        } & pattern_set or number_mix in {"mixed", "symbolic"}:
            return "分数小数混合计算"
        if {"common_factor", "grouping", "decimal_scaling"} & pattern_set or structural_method == "shortcut":
            return "凑整与分组计算"
        if step_chain in {"3-4", "5+"}:
            return "多步四则混合运算"
        return "四则运算"

    @classmethod
    def _build_dim2_counted_question_reason(cls, question: QuestionDimensionScore) -> str:
        score = question.dim_scores.get("dim2", 0.0)
        details = question.dim_details.get("dim2", {}) if isinstance(question.dim_details, dict) else {}
        if not isinstance(details, dict):
            details = {}

        range_label = str(
            details.get("knowledge_range_label")
            or details.get("display_geometry_knowledge_range_label")
            or ""
        ).strip()
        range_label = cls._dim2_display_range_label(question, details, range_label)
        points = cls._dim2_display_points(question, details)

        if range_label and points:
            target = f"{range_label}的{points}"
        elif points:
            target = points
        elif range_label:
            target = f"{range_label}的几何知识"
        else:
            target = cls._dim2_summary_or_fallback_knowledge(question, details)

        dim2_level = str(details.get("dim2_level") or "").strip().upper()
        if not dim2_level:
            dim2_level = cls._dim1_level_from_score(score)

        note = cls._dim2_specific_difficulty_note(question, details)
        return f"{cls._dim1_difficulty_label(dim2_level)}：主要考查{target}；{note}"

    @classmethod
    def _dim2_display_points(cls, question: QuestionDimensionScore, details: dict[str, Any]) -> str:
        if cls._dim2_is_cylinder_geometry(question, details):
            return "圆柱表面积与体积、圆环面积"
        if cls._dim2_is_rotation_sector_shadow_geometry(question, details):
            return "旋转图形与圆/扇形阴影面积"

        for key in ("matched_geometry_knowledge_points", "display_geometry_knowledge_points"):
            raw_points = details.get(key)
            if not isinstance(raw_points, list):
                continue
            points = [
                str(item).strip()
                for item in raw_points
                if cls._is_specific_dim2_knowledge_text(item)
            ]
            if points:
                return "、".join(points[:2])

        model_points = [
            point
            for point in geometry_model_display_points(details.get("geometry_model_types"), limit=2)
            if cls._is_specific_dim2_knowledge_text(point)
        ]
        if model_points:
            return "、".join(model_points)

        summary = str(question.question_summary or "").strip().rstrip("。；;，,")
        if cls._is_specific_dim2_knowledge_text(summary):
            return summary
        return ""

    @classmethod
    def _dim2_display_range_label(
        cls,
        question: QuestionDimensionScore,
        details: dict[str, Any],
        current_label: str,
    ) -> str:
        if cls._dim2_is_cylinder_geometry(question, details):
            return "校内六年级"
        if cls._dim2_is_rotation_sector_shadow_geometry(question, details):
            return "校内六年级"
        return current_label

    @classmethod
    def _dim2_is_cylinder_geometry(cls, question: QuestionDimensionScore, details: dict[str, Any]) -> bool:
        model_types = cls._dim2_model_types(details)
        combined_text = cls._dim2_combined_evidence_text(question, details)
        cylinder_markers = ("圆柱", "木桶", "圆环", "内直径", "外直径", "内高", "外高")
        return (
            ("solid_formula" in model_types or str(details.get("figure_complexity") or "") == "solid_3d")
            and any(marker in combined_text for marker in cylinder_markers)
        )

    @classmethod
    def _dim2_is_rotation_sector_shadow_geometry(
        cls,
        question: QuestionDimensionScore,
        details: dict[str, Any],
    ) -> bool:
        model_types = cls._dim2_model_types(details)
        combined_text = cls._dim2_combined_evidence_text(question, details)
        return (
            {"circle_sector_cut_fill", "figure_transformation"}.issubset(model_types)
            and (
                str(details.get("final_level_adjustment_reason") or "")
                == "standard_rotation_sector_shadow_area"
                or ("旋转" in combined_text and ("阴影" in combined_text or "扇形" in combined_text))
            )
        )

    @classmethod
    def _is_specific_dim2_knowledge_text(cls, value: object) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        generic_terms = {
            "几何",
            "图形",
            "空间",
            "空间想象",
            "几何直观",
            "图形关系",
            "几何知识",
            "综合问题",
            "综合题",
        }
        return text not in generic_terms and len(text) >= 2

    @classmethod
    def _dim2_summary_or_fallback_knowledge(
        cls,
        question: QuestionDimensionScore,
        details: dict[str, Any],
    ) -> str:
        summary = str(question.question_summary or "").strip().rstrip("。；;，,")
        if cls._is_specific_dim2_knowledge_text(summary):
            return summary

        model_points = geometry_model_display_points(details.get("geometry_model_types"), limit=1)
        if model_points:
            return model_points[0]

        figure_complexity = str(details.get("figure_complexity") or "").strip().lower()
        structural_method = str(details.get("structural_visual_method") or "").strip().lower()
        if structural_method == "auxiliary_line":
            return "辅助线与图形关系"
        if structural_method == "decomposition":
            return "图形分解与组合"
        if structural_method == "3d_transform":
            return "立体图形空间转换"
        if figure_complexity == "net_section_multi_view":
            return "展开图与多视图"
        if figure_complexity == "solid_3d":
            return "立体图形关系"
        if figure_complexity == "composite_2d":
            return "组合图形关系"
        return "基础图形关系"

    @classmethod
    def _dim2_specific_difficulty_note(
        cls,
        question: QuestionDimensionScore,
        details: dict[str, Any],
    ) -> str:
        evidence_note = cls._dim2_note_from_evidence(
            details.get("evidence_summary")
            or question.dim_reasons.get("dim2")
            or question.question_summary
            or ""
        )
        model_hint = geometry_model_difficulty_hint(details.get("geometry_model_types"))
        if evidence_note and cls._is_specific_dim2_difficulty_note(evidence_note):
            return evidence_note
        if model_hint:
            return model_hint

        structural_method = str(details.get("structural_visual_method") or "").strip().lower()
        relation_hops = str(details.get("relation_hops") or "").strip()
        hidden_relation_count = str(details.get("hidden_relation_count") or "").strip()
        image_dependency = str(details.get("image_dependency") or "").strip().lower()
        figure_complexity = str(details.get("figure_complexity") or "").strip().lower()

        if structural_method == "auxiliary_line":
            return "本题难点在于要补出辅助线或辅助关系，再把隐藏条件转成可用的几何关系。"
        if structural_method == "decomposition":
            return "本题难点在于要把组合图形拆成可计算部分，再重新组织面积或长度关系。"
        if structural_method == "3d_transform":
            return "本题难点在于要把立体结构、展开图或视图信息相互对应。"
        if hidden_relation_count in {"1", "2+"}:
            return "本题难点在于要找出图形中的隐含关系，并把它转成可计算条件。"
        if relation_hops in {"3-4", "5+"}:
            return "本题难点在于要连续整理多段图形关系，避免关系链中断。"
        if figure_complexity in {"solid_3d", "net_section_multi_view"}:
            return "本题难点在于要稳定对应立体图形中的面、棱或视图关系。"
        if image_dependency == "required":
            return "本题难点在于要准确读取图中标注和形状关系，再对应到几何条件。"
        return "本题关键在于准确读取图形条件，并对应到基本几何关系。"

    @classmethod
    def _dim2_note_from_evidence(cls, value: object) -> str:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            return ""
        for marker in cls.COUNTED_QUESTION_FULL_REASON_HIDDEN_MARKERS:
            text = text.split(marker, 1)[0].strip()
        match = cls.COUNTED_QUESTION_LEVEL_DESCRIPTOR_PATTERN.match(text)
        if match:
            text = match.group(2).strip()
        text = re.sub(r"^图像几何兜底事实[：:]", "", text).strip()
        text = re.sub(r"^图形结构兜底事实[：:]", "", text).strip()
        text = text.rstrip("。；;，,")
        if not text:
            return ""
        if "主要考查" in text and "综合判为" in text:
            return ""

        forbidden_fragments = (
            "空间想象要求较高",
            "图形结构偏复杂",
            "适合观察几何能力",
            "常见失分点是读图",
        )
        if any(fragment in text for fragment in forbidden_fragments):
            return ""

        if text.startswith("需要"):
            body = text[2:].strip("，,；;。 ")
            return f"本题难点在于要{body}。"
        if text.startswith("核心负担是"):
            body = text[len("核心负担是") :].strip("，,；;。 ")
            return f"本题难点在于{body}。"
        if text.startswith("核心门槛是"):
            body = text[len("核心门槛是") :].strip("，,；;。 ")
            return f"本题难点在于{body}。"
        if text.startswith("只需") or text.startswith("直接"):
            return f"本题关键在于{text}。"
        return f"本题难点在于{text}。"

    @staticmethod
    def _is_specific_dim2_difficulty_note(note: str) -> bool:
        generic_fragments = (
            "空间想象要求较高",
            "图形结构偏复杂",
            "适合观察几何能力",
            "常见失分点是读图",
            "需要读取图形关系",
        )
        return bool(note.strip()) and not any(fragment in note for fragment in generic_fragments)

    @classmethod
    def _build_dim3_counted_question_reason(cls, question: QuestionDimensionScore) -> str:
        score = question.dim_scores.get("dim3", 0.0)
        details = question.dim_details.get("dim3", {}) if isinstance(question.dim_details, dict) else {}
        if not isinstance(details, dict):
            details = {}

        dim3_level = str(details.get("dim3_level") or "").strip().upper()
        if not dim3_level:
            dim3_level = cls._dim1_level_from_score(score)

        task = cls._dim3_information_task(details)
        note = cls._dim3_specific_processing_note(question, details)
        return f"{cls._dim1_difficulty_label(dim3_level)}：主要考查{task}；{note}"

    @classmethod
    def _dim3_information_task(cls, details: dict[str, Any]) -> str:
        relation_types = cls._dim3_relation_types(details)
        relation_set = set(relation_types)
        source_form = str(details.get("source_form") or "").strip().lower()
        condition_distribution = str(details.get("condition_distribution") or "").strip().lower()
        extraction_depth = str(details.get("extraction_depth") or "").strip().lower()
        representation_conversion = str(details.get("representation_conversion") or "").strip().lower()
        target_representation = str(details.get("target_representation") or "").strip().lower()
        quantity_relation_structure = str(details.get("quantity_relation_structure") or "").strip().lower()
        relevant_condition_count = str(details.get("relevant_condition_count") or "").strip()
        distractor_pressure = str(details.get("distractor_pressure") or "").strip().lower()
        base_quantity_shift = str(details.get("base_quantity_shift") or "").strip().lower()
        object_count_band = str(details.get("object_count_band") or "").strip()
        feedback_mechanism = str(details.get("feedback_mechanism") or "").strip().lower()
        comparison_basis = str(details.get("comparison_basis") or "").strip().lower()
        diagram_correspondence = str(details.get("diagram_correspondence") or "").strip().lower()
        scenario_rule_types = set(cls._dim3_scenario_rule_types(details))
        dim3_level = str(details.get("dim3_level") or "").strip().upper()

        if dim3_level == "L5":
            return "复杂规则系统理解"
        if dim3_level == "L4":
            return "多个场景关系整合"
        if dim3_level == "L3":
            return "关键问法理解"

        if "custom_rule_system" in scenario_rule_types:
            return "新规则系统理解"
        if feedback_mechanism in {"simple", "conditional"} or "feedback_rule" in scenario_rule_types:
            return "反馈规则理解"
        if comparison_basis in {"implicit", "multi_condition"} or "comparison_basis" in scenario_rule_types:
            return "比较口径理解"
        if diagram_correspondence in {"required", "multi_step"} or "diagram_mapping" in scenario_rule_types:
            return "图文规则对应"
        if "conditional_trigger" in scenario_rule_types:
            return "条件触发理解"
        if "multi_stage_process" in scenario_rule_types:
            return "多阶段过程理解"
        if "multi_object_roles" in scenario_rule_types:
            return "多对象角色理解"
        if "sequence_order" in scenario_rule_types:
            return "过程顺序理解"

        if source_form == "multi_source" or condition_distribution == "cross_modal":
            return "多源材料对应"
        if quantity_relation_structure == "nested_relation":
            return "复杂题意关系理解"
        if base_quantity_shift in {"single", "multiple"}:
            return "比较基准理解"

        priority = (
            "chart_table_conversion",
            "percentage_base_change",
            "reverse_process",
            "multi_object_distribution",
            "ratio_allocation",
            "equation_setup",
            "work_rate",
            "queue_growth",
            "concentration_mixture",
            "profit_discount",
            "travel_meeting_chasing",
            "optimization_comparison",
            "range_narrowing",
            "conservation_transfer",
            "cycle_period",
            "average_total",
        )
        for relation_type in priority:
            if relation_type in relation_set:
                return cls.DIM3_APPLICATION_TASK_LABELS[relation_type]

        if source_form in {"table_chart", "image_text"} or target_representation == "table_list":
            return "图文信息对应"
        if representation_conversion in {"relation_mapping", "model_mapping", "custom_model"}:
            return "题意关系理解"
        if target_representation in {"equation_relation", "custom_model"}:
            return "题意关系理解"
        if object_count_band in {"3", "4+"}:
            return "多对象角色理解"
        if condition_distribution in {"split", "cross_sentence"}:
            return "分散场景信息对应"
        if relevant_condition_count in {"5-6", "7+"} or distractor_pressure == "heavy":
            return "多条场景信息保持"
        if extraction_depth in {"selected", "reorganized", "inferred"}:
            return "有效题意筛选"
        return "场景直读"

    @classmethod
    def _dim3_specific_processing_note(
        cls,
        question: QuestionDimensionScore,
        details: dict[str, Any],
    ) -> str:
        evidence_note = cls._dim3_note_from_evidence(
            details.get("evidence_summary")
            or question.dim_reasons.get("dim3")
            or question.question_summary
            or ""
        )
        if evidence_note and cls._is_specific_dim3_processing_note(evidence_note):
            return evidence_note

        relation_set = set(cls._dim3_relation_types(details))
        source_form = str(details.get("source_form") or "").strip().lower()
        condition_distribution = str(details.get("condition_distribution") or "").strip().lower()
        extraction_depth = str(details.get("extraction_depth") or "").strip().lower()
        representation_conversion = str(details.get("representation_conversion") or "").strip().lower()
        target_representation = str(details.get("target_representation") or "").strip().lower()
        quantity_relation_structure = str(details.get("quantity_relation_structure") or "").strip().lower()
        relevant_condition_count = str(details.get("relevant_condition_count") or "").strip()
        distractor_pressure = str(details.get("distractor_pressure") or "").strip().lower()
        base_quantity_shift = str(details.get("base_quantity_shift") or "").strip().lower()
        object_count_band = str(details.get("object_count_band") or "").strip()
        implicit_relation_count = str(details.get("implicit_relation_count") or "").strip()
        comparison_candidate_count = str(details.get("comparison_candidate_count") or "").strip()
        feedback_mechanism = str(details.get("feedback_mechanism") or "").strip().lower()
        comparison_basis = str(details.get("comparison_basis") or "").strip().lower()
        diagram_correspondence = str(details.get("diagram_correspondence") or "").strip().lower()
        scenario_rule_types = set(cls._dim3_scenario_rule_types(details))
        dim3_level = str(details.get("dim3_level") or "").strip().upper()

        if dim3_level == "L5":
            return "本题难点在于要整体读懂题目给出的复杂规则系统，再判断各规则如何同时起作用。"
        if dim3_level == "L4":
            return "本题难点在于要同时整理多个场景关系，分清对象、阶段、规则或图文对应。"
        if dim3_level == "L3":
            return "本题难点在于要读懂题目中的关键问法、比较口径或单一规则。"
        if "custom_rule_system" in scenario_rule_types:
            return "本题难点在于要先读懂题目给出的新规则系统，再判断各规则如何同时起作用。"
        if feedback_mechanism in {"simple", "conditional"} or "feedback_rule" in scenario_rule_types:
            return "本题难点在于要读懂操作后的反馈含义，知道反馈对应哪一种情况。"
        if comparison_basis in {"implicit", "multi_condition"} or "comparison_basis" in scenario_rule_types:
            return "本题难点在于要读懂题目真正比较的口径，避免只按表面数量判断。"
        if diagram_correspondence in {"required", "multi_step"} or "diagram_mapping" in scenario_rule_types:
            return "本题难点在于要把文字规则和图中的对象、位置或流程对应起来。"
        if "conditional_trigger" in scenario_rule_types:
            return "本题难点在于要读懂条件触发关系，分清什么时候使用哪条规则。"
        if "multi_stage_process" in scenario_rule_types:
            return "本题难点在于要按题面过程分阶段理解，不能把不同阶段混在一起。"

        if source_form == "multi_source" or condition_distribution == "cross_modal":
            return "本题难点在于要同时对齐图表、文字或图像信息，先读懂各部分对应关系。"
        if "chart_table_conversion" in relation_set or source_form in {"table_chart", "image_text"}:
            return "本题难点在于要先读懂图表或图文材料中对象、数据和问题之间的对应关系。"
        if "percentage_base_change" in relation_set or base_quantity_shift in {"single", "multiple"}:
            return "本题难点在于要读懂题目中不同阶段分别以谁为标准，避免比较口径混淆。"
        if quantity_relation_structure == "nested_relation":
            return "本题难点在于要先读懂多层题意关系，分清每句话指向的对象和阶段。"
        if representation_conversion == "custom_model" or target_representation == "custom_model":
            return "本题难点在于题面给出了不常见规则，需要先读懂规则含义和适用对象。"
        if "reverse_process" in relation_set:
            return "本题难点在于要按题面过程的先后关系理解，分清原来、变化后和问题所问。"
        if "multi_object_distribution" in relation_set or object_count_band in {"3", "4+"}:
            return "本题难点在于要同时保持多个对象的身份和动作，避免对象之间对应错位。"
        if "optimization_comparison" in relation_set or comparison_candidate_count == "3+":
            return "本题难点在于要先读懂多个选项或方案的比较口径，知道题目要求比较什么。"
        if implicit_relation_count in {"1", "2", "3+"}:
            return "本题难点在于题目问法中有隐含口径，需要先把没有直接说出的意思读出来。"
        if (
            representation_conversion in {"relation_mapping", "model_mapping"}
            or target_representation == "equation_relation"
        ):
            return "本题难点在于要读懂文字条件之间的对应关系，再判断题目到底要求什么。"
        if condition_distribution in {"split", "cross_sentence"}:
            return "本题难点在于相关场景信息分散在不同句子里，需要前后对应起来读。"
        if distractor_pressure == "heavy":
            return "本题难点在于题面有容易误读的信息，需要分清哪些内容真正描述当前问题。"
        if relevant_condition_count in {"5-6", "7+"}:
            return "本题难点在于要保持多条场景信息，分清它们各自对应的对象、阶段或规则。"
        if extraction_depth in {"selected", "reorganized", "inferred"}:
            return "本题难点在于要从文字叙述中筛出真正描述场景和问题要求的信息。"
        return "本题关键在于直接读懂题目场景、对象和问题要求。"

    @classmethod
    def _dim3_note_from_evidence(cls, value: object) -> str:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            return ""
        for marker in cls.COUNTED_QUESTION_FULL_REASON_HIDDEN_MARKERS:
            text = text.split(marker, 1)[0].strip()
        match = cls.COUNTED_QUESTION_LEVEL_DESCRIPTOR_PATTERN.match(text)
        if match:
            text = match.group(2).strip()
        text = text.rstrip("。；;，,")
        if not text:
            return ""
        if "主要考查" in text or any(fragment in text for fragment in cls.DIM3_FORBIDDEN_DISPLAY_FRAGMENTS):
            return ""
        if text.startswith("需要"):
            body = text[2:].strip("，,；;。 ")
            return f"本题难点在于要{body}。"
        if text.startswith("要"):
            body = text[1:].strip("，,；;。 ")
            return f"本题难点在于要{body}。"
        if text.startswith("先"):
            return f"本题难点在于要{text}。"
        if text.startswith("只需") or text.startswith("直接"):
            return f"本题关键在于{text}。"
        return f"本题难点在于{text}。"

    @classmethod
    def _is_specific_dim3_processing_note(cls, note: str) -> bool:
        return bool(note.strip()) and not any(
            fragment in note
            for fragment in cls.DIM3_FORBIDDEN_DISPLAY_FRAGMENTS
        )

    @staticmethod
    def _dim3_relation_types(details: dict[str, Any]) -> List[str]:
        raw_types = details.get("application_relation_types")
        if isinstance(raw_types, str):
            items = raw_types.replace("，", ",").replace("、", ",").split(",")
        elif isinstance(raw_types, list):
            items = raw_types
        else:
            items = []
        return [
            str(item or "").strip().lower()
            for item in items
            if str(item or "").strip()
        ]

    @staticmethod
    def _dim3_scenario_rule_types(details: dict[str, Any]) -> List[str]:
        raw_types = details.get("scenario_rule_types")
        if isinstance(raw_types, str):
            items = raw_types.replace("，", ",").replace("、", ",").split(",")
        elif isinstance(raw_types, list):
            items = raw_types
        else:
            items = []
        return [
            str(item or "").strip().lower()
            for item in items
            if str(item or "").strip()
        ]

    @classmethod
    def _build_dim6_counted_question_reason(cls, question: QuestionDimensionScore) -> str:
        score = question.dim_scores.get("dim6", 0.0)
        details = question.dim_details.get("dim6", {}) if isinstance(question.dim_details, dict) else {}
        if not isinstance(details, dict):
            details = {}

        dim6_level = str(details.get("dim6_level") or "").strip().upper()
        if not dim6_level:
            dim6_level = cls._dim1_level_from_score(score)

        chain_description = cls._dim6_chain_length_description(details, dim6_level)
        student_action = cls._dim6_student_action(question, details)
        return f"{cls._dim1_difficulty_label(dim6_level)}：这题的解题链条{chain_description}；学生需要{student_action}。"

    @classmethod
    def _dim6_chain_length_description(cls, details: dict[str, Any], dim6_level: str) -> str:
        chain_span = str(details.get("chain_span") or "").strip()
        if chain_span == "1":
            return "很短，通常一步判断即可"
        if chain_span == "2":
            return "较短，大约需要连续推进 1-2 步"
        if chain_span == "3-4":
            return "较长，大约需要连续推进 3-4 步"
        if chain_span == "5+":
            if cls._dim6_has_multi_condition_check(details):
                return "很长，通常需要连续推进 5 步以上，并同时检查多个条件"
            return "很长，通常需要连续推进 5 步以上"

        level = str(dim6_level or "").strip().upper()
        if level == "L5":
            return "很长，通常需要多步推进，并伴随分类、倒推、回查或多条件检查"
        if level == "L4":
            return "较长，通常需要多步推进，并伴随分类、倒推、回查或多条件检查"
        if level == "L3":
            return "有一定长度，通常需要把前后条件连续接起来"
        if level == "L2":
            return "较短，通常需要一两步衔接"
        return "很短，通常一步判断即可"

    @classmethod
    def _dim6_has_multi_condition_check(cls, details: dict[str, Any]) -> bool:
        structures = set(cls._dim6_structure_types(details))
        constraint_coupling = str(details.get("constraint_coupling") or "").strip().lower()
        hidden_dependency = str(details.get("hidden_dependency") or "").strip().lower()
        consistency_constraint_count = str(details.get("consistency_constraint_count") or "").strip()
        verification_requirement = str(details.get("verification_requirement") or "").strip().lower()
        return (
            details.get("global_consistency_required") == 1
            or constraint_coupling in {"coupled", "nested"}
            or hidden_dependency in {"cross_condition", "global"}
            or consistency_constraint_count in {"2-3", "4+"}
            or verification_requirement in {"constraint_backcheck", "full_consistency"}
            or bool(structures & {"global_constraint_system", "shared_variable_coupling"})
        )

    @classmethod
    def _dim6_logic_task(cls, details: dict[str, Any]) -> str:
        structures = set(cls._dim6_structure_types(details))
        chain_span = str(details.get("chain_span") or "").strip()
        hidden_dependency = str(details.get("hidden_dependency") or "").strip().lower()
        reversibility = str(details.get("reversibility") or "").strip().lower()
        constraint_coupling = str(details.get("constraint_coupling") or "").strip().lower()
        global_consistency_required = details.get("global_consistency_required")
        state_transition_count = str(details.get("state_transition_count") or "").strip()
        case_count_band = str(details.get("case_count_band") or "").strip()
        backtrack_depth = str(details.get("backtrack_depth") or "").strip()
        consistency_constraint_count = str(details.get("consistency_constraint_count") or "").strip()
        phase_count_band = str(details.get("phase_count_band") or "").strip()
        periodic_cycle_dependency = details.get("periodic_cycle_dependency")
        optimization_requirement = str(details.get("optimization_requirement") or "").strip().lower()

        if structures & {"periodic_sequence_position", "cyclic_schedule_chain"} or periodic_cycle_dependency == 1:
            return "周期位置连续定位"
        if "optimization_comparison" in structures or optimization_requirement in {"bounded_choice", "global_minmax"}:
            return "多个方案比较取舍"
        if "bounded_case_enumeration" in structures or case_count_band in {"2", "3-5", "6+"}:
            return "多种情况逐一判断"
        if (
            "reverse_process_chain" in structures
            or reversibility in {"backward", "bidirectional"}
            or backtrack_depth in {"1", "2", "3+"}
        ):
            return "从结果倒推回原条件"
        if (
            structures & {"global_constraint_system", "shared_variable_coupling"}
            or constraint_coupling in {"coupled", "nested"}
            or global_consistency_required == 1
            or consistency_constraint_count in {"2-3", "4+"}
        ):
            return "多个条件同时对上"
        if (
            structures
            & {
                "queue_growth_chain",
                "multi_stage_state_change",
                "percentage_base_shift_chain",
                "travel_meeting_chasing_chain",
            }
            or state_transition_count in {"2", "3+"}
            or phase_count_band in {"3-4", "5+"}
        ):
            return "多轮变化前后衔接"
        if "work_rate_chain" in structures or chain_span in {"3-4", "5+"} or hidden_dependency in {"cross_condition", "global"}:
            return "连续推出中间结论"
        if chain_span == "2" or hidden_dependency == "local":
            return "连续推出中间结论"
        return "直接条件判断"

    @classmethod
    def _dim6_student_action(
        cls,
        question: QuestionDimensionScore,
        details: dict[str, Any],
    ) -> str:
        if details.get("second_review_status") == SECOND_REVIEW_STATUS_APPLICABLE:
            evidence_note = cls._dim6_note_from_evidence(
                details.get("evidence_summary") or details.get("second_review_evidence") or ""
            )
            if evidence_note and cls._dim6_evidence_has_specific_content(evidence_note):
                return cls._clean_dim6_student_action(evidence_note)

        fact_action = cls._dim6_student_action_from_facts(details)
        if fact_action:
            return fact_action

        evidence_note = cls._dim6_note_from_evidence(
            details.get("evidence_summary")
            or question.dim_reasons.get("dim6")
            or question.question_summary
            or ""
        )
        if evidence_note and cls._dim6_evidence_has_specific_content(evidence_note):
            return cls._clean_dim6_student_action(evidence_note)

        summary = str(question.question_summary or "").strip().rstrip("。；;，,")
        if summary and not any(fragment in summary for fragment in cls.DIM6_FORBIDDEN_DISPLAY_FRAGMENTS):
            return cls._clean_dim6_student_action(f"围绕{summary}，把相关条件一步步接到结论上")
        return "把已有条件一步步接起来，并在最后检查结论是否符合题意"

    @classmethod
    def _dim6_student_action_from_facts(cls, details: dict[str, Any]) -> str:
        structures = set(cls._dim6_structure_types(details))
        chain_span = str(details.get("chain_span") or "").strip()
        hidden_dependency = str(details.get("hidden_dependency") or "").strip().lower()
        reversibility = str(details.get("reversibility") or "").strip().lower()
        constraint_coupling = str(details.get("constraint_coupling") or "").strip().lower()
        global_consistency_required = details.get("global_consistency_required")
        state_transition_count = str(details.get("state_transition_count") or "").strip()
        case_count_band = str(details.get("case_count_band") or "").strip()
        backtrack_depth = str(details.get("backtrack_depth") or "").strip()
        consistency_constraint_count = str(details.get("consistency_constraint_count") or "").strip()
        phase_count_band = str(details.get("phase_count_band") or "").strip()
        periodic_cycle_dependency = details.get("periodic_cycle_dependency")
        optimization_requirement = str(details.get("optimization_requirement") or "").strip().lower()

        has_multiple_conditions = (
            constraint_coupling in {"coupled", "nested"}
            or global_consistency_required == 1
            or consistency_constraint_count in {"2-3", "4+"}
            or hidden_dependency in {"cross_condition", "global"}
        )

        if structures & {"periodic_sequence_position", "cyclic_schedule_chain"} or periodic_cycle_dependency == 1:
            return "找准循环节和目标位置，再把余数对应回具体状态"
        if "optimization_comparison" in structures or optimization_requirement in {"bounded_choice", "global_minmax"}:
            return "先列出可行方案，再按同一个标准比较，并检查限制条件是否都满足"
        if "bounded_case_enumeration" in structures or case_count_band in {"2", "3-5", "6+"}:
            return "把可能情况分完整，逐一代回条件检查，避免漏掉或重复"
        if (
            "reverse_process_chain" in structures
            or reversibility in {"backward", "bidirectional"}
            or backtrack_depth in {"1", "2", "3+"}
        ):
            if has_multiple_conditions:
                return "从结果往前还原每一步，再把还原出的状态代回多个条件检查"
            return "从结果往前还原每一步，再检查是否符合原条件"
        if (
            structures & {"global_constraint_system", "shared_variable_coupling"}
            or has_multiple_conditions
        ):
            return "同时盯住多个条件，先缩小范围，再确认每个条件都成立"
        if (
            structures
            & {
                "queue_growth_chain",
                "multi_stage_state_change",
                "percentage_base_shift_chain",
                "travel_meeting_chasing_chain",
            }
            or state_transition_count in {"2", "3+"}
            or phase_count_band in {"3-4", "5+"}
        ):
            return "按阶段记录变化，把上一阶段的结果接到下一阶段条件中"
        if "work_rate_chain" in structures or chain_span in {"3-4", "5+"} or hidden_dependency in {"cross_condition", "global"}:
            return "把前一步得到的结果接到下一步条件里，连续推出中间结论"
        if chain_span == "2" or hidden_dependency == "local":
            return "把前一步结果接到下一步条件中，再做一次检查"
        return "直接看清条件和问题之间的对应关系"

    @classmethod
    def _clean_dim6_student_action(cls, value: object) -> str:
        text = " ".join(str(value or "").split()).strip().rstrip("。；;，,")
        if not text or any(fragment in text for fragment in cls.DIM6_FORBIDDEN_DISPLAY_FRAGMENTS):
            return "把已有条件一步步接起来，并在最后检查结论是否符合题意"

        prefixes = (
            "学生需要",
            "题目需要",
            "需要",
            "要",
            "难点在于",
            "这题难在",
            "本题难在",
        )
        changed = True
        while changed:
            changed = False
            for prefix in prefixes:
                if text.startswith(prefix):
                    text = text[len(prefix) :].strip(" ，,；;。")
                    changed = True
        return text.rstrip("。；;，,") or "把已有条件一步步接起来，并在最后检查结论是否符合题意"

    @classmethod
    def _dim6_specific_reasoning_evidence(
        cls,
        question: QuestionDimensionScore,
        details: dict[str, Any],
    ) -> str:
        evidence_note = cls._dim6_note_from_evidence(
            details.get("evidence_summary")
            or question.dim_reasons.get("dim6")
            or question.question_summary
            or ""
        )
        if evidence_note and cls._dim6_evidence_has_specific_content(evidence_note):
            return evidence_note

        fact_evidence = cls._dim6_evidence_from_facts(details)
        if fact_evidence:
            return fact_evidence

        summary = str(question.question_summary or "").strip().rstrip("。；;，,")
        if summary:
            return f"题目摘要指向{summary}，需要把相关条件逐步接到最终结论"
        return "题目需要把已有条件逐步接到最终结论"

    @classmethod
    def _dim6_note_from_evidence(cls, value: object) -> str:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            return ""
        for marker in cls.COUNTED_QUESTION_FULL_REASON_HIDDEN_MARKERS:
            text = text.split(marker, 1)[0].strip()
        match = cls.COUNTED_QUESTION_LEVEL_DESCRIPTOR_PATTERN.match(text)
        if match:
            text = match.group(2).strip()
        text = text.rstrip("。；;，,")
        if not text:
            return ""
        if "主要考查" in text or any(fragment in text for fragment in cls.DIM6_FORBIDDEN_DISPLAY_FRAGMENTS):
            return ""

        if text.startswith("需要"):
            text = f"题目需要{text[2:].strip('，,；;。 ')}"
        if text.startswith("要"):
            text = f"题目需要{text[1:].strip('，,；;。 ')}"

        replacements = {
            "多分支": "多种情况",
            "分支": "情况",
            "分类讨论": "多种情况判断",
            "分类": "多种情况",
            "回查": "对应",
            "约束": "条件",
            "全局一致性": "多个条件同时对上",
            "全局一致": "多个条件同时对上",
            "收束": "确定结果",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = text.rstrip("。；;，,")
        return text

    @classmethod
    def _dim6_evidence_from_facts(cls, details: dict[str, Any]) -> str:
        structures = set(cls._dim6_structure_types(details))
        clauses: List[str] = []

        backtrack_depth = str(details.get("backtrack_depth") or "").strip()
        case_count_band = str(details.get("case_count_band") or "").strip()
        consistency_constraint_count = str(details.get("consistency_constraint_count") or "").strip()
        phase_count_band = str(details.get("phase_count_band") or "").strip()
        state_transition_count = str(details.get("state_transition_count") or "").strip()
        chain_span = str(details.get("chain_span") or "").strip()
        optimization_requirement = str(details.get("optimization_requirement") or "").strip().lower()
        periodic_cycle_dependency = details.get("periodic_cycle_dependency")

        if "global_constraint_system" in structures or "shared_variable_coupling" in structures:
            clauses.append("题目属于多对象或共享变量关系")
        if "reverse_process_chain" in structures:
            clauses.append("题面存在倒推还原结构")
        if "bounded_case_enumeration" in structures:
            clauses.append("题面存在有限候选情况")
        if "optimization_comparison" in structures or optimization_requirement in {"bounded_choice", "global_minmax"}:
            clauses.append("题目需要在多个方案中比较取舍")
        if structures & {"queue_growth_chain", "multi_stage_state_change", "percentage_base_shift_chain", "travel_meeting_chasing_chain"}:
            clauses.append("题目包含多轮状态变化")
        if structures & {"periodic_sequence_position", "cyclic_schedule_chain"} or periodic_cycle_dependency == 1:
            clauses.append("题目需要定位周期中的目标位置")

        if backtrack_depth == "3+":
            clauses.append("需要三层以上倒推")
        elif backtrack_depth == "2":
            clauses.append("需要两层倒推")
        elif backtrack_depth == "1":
            clauses.append("需要从结果往前还原一步")

        if case_count_band == "6+":
            clauses.append("需要判断 6 种以上可能情况")
        elif case_count_band == "3-5":
            clauses.append("需要判断 3-5 种可能情况")
        elif case_count_band == "2":
            clauses.append("需要判断 2 种可能情况")

        if consistency_constraint_count == "4+":
            clauses.append("需要同时满足 4 个以上条件")
        elif consistency_constraint_count == "2-3":
            clauses.append("需要同时满足 2-3 个条件")

        if phase_count_band == "5+":
            clauses.append("推进过程有 5 段以上")
        elif phase_count_band == "3-4":
            clauses.append("推进过程有 3-4 段")

        if state_transition_count == "3+":
            clauses.append("包含 3 次以上状态变化")
        elif state_transition_count == "2":
            clauses.append("包含 2 次状态变化")

        if chain_span == "5+":
            clauses.append("推理链需要 5 步以上推进")
        elif chain_span == "3-4":
            clauses.append("推理链需要 3-4 步推进")

        deduped = list(dict.fromkeys(clauses))
        if not deduped:
            return ""
        return "，".join(deduped[:3])

    @classmethod
    def _dim6_evidence_has_specific_content(cls, evidence: str) -> bool:
        text = str(evidence or "").strip()
        if not text:
            return False
        generic_fragments = (
            "旧版分析不应直接展示",
            "本题逻辑链条较长",
            "该题难度较高",
            "综合判为困难",
            "需要串联多个条件并对应条件",
            "需要多种情况、对应并维持多个条件同时对上",
            "需要多种情况确定结果并做多个条件同时对上检验",
        )
        if any(fragment in text for fragment in generic_fragments):
            return False
        concrete_markers = (
            "原有",
            "持续",
            "检票",
            "队伍",
            "到达",
            "消耗",
            "工程",
            "效率",
            "标价",
            "寄售",
            "损坏",
            "出售",
            "相遇",
            "速度",
            "剩余路程",
            "票价",
            "铺管",
            "方案",
            "对象",
            "分配",
            "多对象",
            "倒推",
            "还原",
            "周期",
            "循环",
            "状态",
            "阶段",
            "候选",
            "总量",
            "比例",
            "余量",
            "位置",
            "次数",
            "条件",
            "目标",
        )
        return bool(re.search(r"\d", text)) or any(marker in text for marker in concrete_markers)

    @staticmethod
    def _dim6_structure_types(details: dict[str, Any]) -> List[str]:
        raw_types = details.get("logic_structure_types")
        if isinstance(raw_types, str):
            items = raw_types.replace("，", ",").replace("、", ",").split(",")
        elif isinstance(raw_types, list):
            items = raw_types
        else:
            items = []
        return [
            str(item or "").strip().lower()
            for item in items
            if str(item or "").strip()
        ]

    @staticmethod
    def _question_no_sort_key(question_no: str) -> tuple:
        parts = re.findall(r"\d+|[^\d]+", str(question_no or ""))
        normalized: List[tuple[int, object]] = []
        for part in parts:
            if part.isdigit():
                normalized.append((0, int(part)))
            else:
                normalized.append((1, part))
        return tuple(normalized)

    @staticmethod
    def _build_question_display_label(question: QuestionDimensionScore) -> str:
        explicit_display_label = str(question.question_display_label or "").strip()
        if explicit_display_label:
            return explicit_display_label

        section_index_raw = str(question.section_index_raw or "").strip()
        question_no = str(question.question_no or "").strip()
        if section_index_raw and question_no:
            return f"{section_index_raw}-{question_no}"

        question_label_raw = str(question.question_label_raw or "").strip()
        if question_label_raw:
            return question_label_raw

        return question_no or str(question.question_id or "").strip()

    def _calculate_level(self, score: float) -> tuple[int, str]:
        for threshold, level, label in self.LEVEL_THRESHOLDS:
            if score <= threshold:
                return level, label
        return 5, "选拔"
