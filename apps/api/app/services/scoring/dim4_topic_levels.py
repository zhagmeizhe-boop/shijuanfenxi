"""
L1-L5 anchors for dim4 modeling and solution organization.

dim4 measures solving-level structure inside elementary mathematics: condition
organization, relationship building, tables/diagrams, classification, reverse
reasoning, scheme comparison, construction, and strategy shifts. It must not
represent knowledge breadth, grade band, contest source, or raw difficulty.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


DIM4_TOPIC_LEVELS = {
    "L1": {"score": 2.0, "level": 1, "label": "L1 基础关系"},
    "L2": {"score": 4.0, "level": 2, "label": "L2 简单转化"},
    "L3": {"score": 6.0, "level": 3, "label": "L3 条件组织"},
    "L4": {"score": 8.0, "level": 4, "label": "L4 多关系建模"},
    "L5": {"score": 9.5, "level": 5, "label": "L5 综合构造建模"},
}
DIM4_LEVEL_SOURCE_VALUES = {
    "question_bank",
    "knowledge_anchor",
    "llm_fallback",
    "second_review",
    "review_failed",
}
DIM4_NUMERIC_LEVELS = {str(index): f"L{index}" for index in range(1, 6)}
DIM4_LEVEL_RANK = {f"L{index}": index for index in range(1, 6)}


TOPIC_ALIASES = {
    "牛吃草": "牛吃草",
    "牛吃草问题": "牛吃草",
    "排队增长": "牛吃草",
    "检票排队": "牛吃草",
    "工程问题": "工程问题",
    "合作效率": "工程问题",
    "工作效率": "工程问题",
    "行程问题": "行程相遇追及",
    "相遇问题": "行程相遇追及",
    "追及问题": "行程相遇追及",
    "行程相遇追及": "行程相遇追及",
    "比例": "比例百分数应用",
    "百分数": "比例百分数应用",
    "比例百分数应用": "比例百分数应用",
    "利润折扣": "比例百分数应用",
    "分数裂项": "分数裂项/结构计算",
    "裂项": "分数裂项/结构计算",
    "结构计算": "分数裂项/结构计算",
    "周期问题": "周期问题",
    "周期": "周期问题",
    "图形割补": "图形割补",
    "割补": "图形割补",
    "等积变形": "图形割补",
    "抽屉原理": "抽屉/分类计数",
    "分类计数": "抽屉/分类计数",
    "计数": "抽屉/分类计数",
    "方案比较": "方案比较",
    "最优方案": "方案比较",
    "票价方案": "方案比较",
    "逆推还原": "逆推还原",
    "倒推": "逆推还原",
    "还原问题": "逆推还原",
    "博弈": "博弈策略",
    "博弈策略": "博弈策略",
    "对称策略": "博弈策略",
    "必胜策略": "博弈策略",
    "数论": "数论约束",
    "同余": "数论约束",
    "余数": "数论约束",
    "整除": "数论约束",
    "不变量": "构造论证",
    "染色": "构造论证",
    "构造论证": "构造论证",
    "几何综合": "几何割补",
    "面积比": "图形割补",
}


TOPIC_SCALE_DEFINITIONS = {
    "牛吃草": {
        "L1": "直接给出两组牛数和天数，套增长-消耗基本模型。",
        "L2": "问法、单位或对象名称有轻微变化，但仍可直接列标准关系。",
        "L3": "需要识别排队、检票等伪装场景，或完成一次增长-消耗关系转换，识别后路径基本明确。",
        "L4": "排队增长识别后还要构造中间量、处理窗口/效率变化、多阶段增长或回查多个消耗关系。",
        "L5": "增长模型与全局约束、方案选择或唯一性证明结合。",
    },
    "工程问题": {
        "L1": "直接两人合作或单一效率公式。",
        "L2": "问法、单位或工作量表达略变，仍可直接套单一效率关系。",
        "L3": "单次换班、休息或一次剩余量转换，识别阶段变化后可沿明确路径推进。",
        "L4": "换班识别后还要组织剩余量、处理多阶段协作/效率变化，或回查多个阶段关系。",
        "L5": "工程安排与全局最优、周期轮班或多约束唯一收束结合。",
    },
    "行程相遇追及": {
        "L1": "直接相遇或追及，套速度和公式。",
        "L2": "方向、时间或单位有轻微变化。",
        "L3": "相遇后速度变化、单次往返或一处路程转换，识别后路径基本明确。",
        "L4": "相遇后变化还叠加等待、调头、再往返或多对象多阶段状态联动，需要组织路径关系。",
        "L5": "行程过程与全局约束、周期位置或多方案收束结合。",
    },
    "比例百分数应用": {
        "L1": "直接求百分率、比例或单位量。",
        "L2": "基准量或问法轻微变化。",
        "L3": "百分比变基准、比例分配或利润折扣的一次转化，转化后可直接推进。",
        "L4": "变基准或比例识别后还要反向整理、多阶段折扣/利润/损耗联动或回查多条件。",
        "L5": "比例百分数与全局方案、参数化或最值证明结合。",
    },
    "分数裂项/结构计算": {
        "L1": "直接分数运算或简单通分。",
        "L2": "局部凑整、约分或一处结构识别。",
        "L3": "需要发现裂项、递推或对称消去结构。",
        "L4": "多结构叠加、长式变形或繁分式整体处理。",
        "L5": "长链裂项、递推乘积、参数化通项或全局结构证明。",
    },
    "周期问题": {
        "L1": "直接按周期求余定位。",
        "L2": "周期起点或问法轻微变化。",
        "L3": "需要先识别或构造一个周期，或合并两个简单周期。",
        "L4": "多周期嵌套、状态转移或边界分类回查。",
        "L5": "周期与逆推、全局约束或大范围唯一收束结合。",
    },
    "图形割补": {
        "L1": "直接套面积公式或简单补图。",
        "L2": "一处辅助线、平移或等积替换。",
        "L3": "识别单个几何模型、一次辅助线或一次等积替换后，基本可直接推进。",
        "L4": "几何模型识别后还要割补、辅助线、面积比链或反推，并组织多个图形关系。",
        "L5": "图形构造与全局不变量、最值或证明结合。",
    },
    "抽屉/分类计数": {
        "L1": "直接分类或基础抽屉原理。",
        "L2": "分类边界有轻微变化。",
        "L3": "需要一次重新设类、排除重复、一次容斥或简单有限候选筛选。",
        "L4": "候选筛选后还要约束回查、有限枚举验证、多层分类或构造反例。",
        "L5": "计数与全局构造、极端情况或唯一性证明结合。",
    },
    "方案比较": {
        "L1": "直接比较两个给定方案。",
        "L2": "方案条件有轻微变化。",
        "L3": "需要计算并筛选多个候选方案，筛选标准明确。",
        "L4": "候选比较后还要约束回查、有限分类或方案构造，可包含最优方案判断但无需完整证明。",
        "L5": "需要证明最优、构造所有可行方案或处理开放选择。",
    },
    "逆推还原": {
        "L1": "一步倒推。",
        "L2": "两步常规倒推。",
        "L3": "多步还原、简单倒推或一次分支倒推，路径基本明确。",
        "L4": "倒推后还要重排题目关系、处理状态转移或叠加约束筛选。",
        "L5": "多层嵌套还原、全局一致性或唯一性证明。",
    },
    "博弈策略": {
        "L1": "直接套用已知轮流取物模板。",
        "L2": "规则有轻微变化，但仍能直接识别先后手模板。",
        "L3": "需要识别一次奇偶、对称或配对策略。",
        "L4": "识别博弈结构后还要构造必胜策略、回查规则约束或处理多分支状态。",
        "L5": "需要证明策略最优、唯一性或所有局面的全局收束。",
    },
    "数论约束": {
        "L1": "直接使用整除、余数或质因数基本性质。",
        "L2": "条件有轻微变化，但仍是单一性质套用。",
        "L3": "需要一次同余转换、余数分类或候选筛选。",
        "L4": "数论约束与枚举、回查、构造或多条件联动结合。",
        "L5": "需要全局构造、唯一性证明或参数化数论论证。",
    },
    "构造论证": {
        "L1": "直接验证给定构造。",
        "L2": "只需局部调整或轻度试探。",
        "L3": "需要一次构造、反例或不变量识别。",
        "L4": "构造后还要分类回查、证明可行性或同时满足多个约束。",
        "L5": "需要全局构造、最优性证明、唯一性证明或开放探索。",
    },
}


HIGH_PRIORITY_LEVEL_TERMS = [
    (
        "L5",
        (
            "证明不能更多",
            "为什么不能更多",
            "证明最优",
            "全局最优",
            "全局设计",
            "全局收束",
            "唯一性证明",
            "所有可能",
            "所有可行",
            "开放探索",
            "参数化",
            "通项公式",
        ),
    ),
    (
        "L4",
        (
            "构造中间量",
            "方案构造",
            "有限分类",
            "分类讨论",
            "分类回查",
            "多种方案",
            "最少改动",
            "反向整理",
            "约束回查",
            "多条件联动",
            "窗口效率",
            "效率变化",
            "剩余量联动",
            "调头",
            "等待",
            "多次折扣",
            "多阶段利润",
            "构造反例",
            "最优方案",
            "博弈必胜",
            "对称策略",
            "有限枚举",
            "面积比链",
            "极值构造",
            "定义新运算结构展开",
            "非相邻裂项",
            "长链消去",
            "首尾项提取",
            "差分增量",
            "参数无关",
            "无关量消去",
            "多状态基准切换",
            "新旧基准联动",
            "位置耦合枚举",
            "概率分母构造",
            "总量转化",
        ),
    ),
    (
        "L3",
        (
            "相遇后",
            "换班",
            "单次换班",
            "变基准",
            "一次变基准",
            "增长",
            "伪装",
            "检票",
            "排队",
            "裂项",
            "重组",
            "一次转化",
            "结构重组",
            "构造周期",
            "速度变化",
            "剩余量",
            "倒推",
            "筛选",
            "有限候选",
            "多个候选",
        ),
    ),
    (
        "L2",
        (
            "轻微变化",
            "改问法",
            "单位换算",
            "多一步",
            "两个方案",
        ),
    ),
]


def normalize_dim4_level(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in DIM4_TOPIC_LEVELS:
        return text
    if text in DIM4_NUMERIC_LEVELS:
        return DIM4_NUMERIC_LEVELS[text]
    match = re.search(r"\bL?([1-5])\b", text)
    if match:
        return f"L{match.group(1)}"
    return ""


def normalize_dim4_level_source(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in DIM4_LEVEL_SOURCE_VALUES else ""


def _collect_dim4_signal_text(feature: Dict[str, Any]) -> str:
    values: List[str] = [
        str(feature.get("knowledge_point", "")),
        str(feature.get("evidence_summary", "")),
        str(feature.get("anchor_evidence", "")),
    ]
    for key in (
        "evidence_tags",
        "knowledge_tags",
        "core_knowledge_units",
        "supporting_knowledge_units",
        "method_tags",
    ):
        raw = feature.get(key, [])
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
        elif raw:
            values.append(str(raw))
    return " ".join(values)


def _has_all(text: str, *terms: str) -> bool:
    return all(term in text for term in terms)


def calibrate_dim4_competition_variant_level(
    feature: Dict[str, Any],
    current_level: Any,
) -> Dict[str, str]:
    """Raise only clear topic-internal variant signals; never lower scores."""
    level = normalize_dim4_level(current_level)
    if not level:
        return {}

    text = _collect_dim4_signal_text(feature)
    target = ""
    reason = ""
    variant_signal_group = ""

    l5_signals = (
        ("global_optimal_proof", ("全局最优", "证明")),
        ("uniqueness_proof", ("唯一性", "证明")),
        ("parameterized_generalization", ("参数化", "通项")),
        ("long_chain_structure", ("长链", "全局结构证明")),
        ("long_chain_structure", ("裂项", "通项证明")),
        ("long_chain_structure", ("递推乘积",)),
        ("open_exploration", ("开放探索",)),
        ("winning_strategy_global_check", ("制胜策略", "对手应对")),
        ("winning_strategy_global_check", ("必胜态", "回查")),
        ("winning_strategy_global_check", ("保证获胜",)),
        ("winning_strategy_global_check", ("全局必胜",)),
        ("winning_strategy_global_check", ("博弈树", "全局")),
    )
    l4_signals = (
        ("intermediate_construction", ("构造中间量",)),
        ("intermediate_construction", ("构造", "中间量")),
        ("plan_construction", ("方案构造",)),
        ("bounded_classification_backcheck", ("有限分类", "回查")),
        ("bounded_classification_backcheck", ("分类回查",)),
        ("plan_comparison_backcheck", ("方案比较", "回查")),
        ("plan_comparison_backcheck", ("方案比较", "构造")),
        ("constraint_backcheck", ("约束回查",)),
        ("constraint_backcheck", ("回查", "约束")),
        ("reverse_organization", ("反向整理",)),
        ("reverse_organization", ("反向思考",)),
        ("relation_reorganization", ("重排题目关系",)),
        ("relation_reorganization", ("关系重排",)),
        ("multi_stage_state_change", ("多阶段", "状态")),
        ("multi_condition_coupling", ("多条件联动",)),
        ("finite_enumeration_verification", ("有限枚举", "验证")),
        ("finite_enumeration_verification", ("枚举", "回查")),
        ("defined_operation_structure", ("定义新运算", "裂项")),
        ("defined_operation_structure", ("定义运算", "裂项")),
        ("defined_operation_structure", ("定义新运算", "结构展开")),
        ("defined_operation_structure", ("定义新运算", "倒推关系")),
        ("defined_operation_structure", ("规定一种运算", "结构展开")),
        ("defined_operation_structure", ("规定一种运算", "裂项关系")),
        ("defined_operation_structure", ("自定义运算", "结构展开")),
        ("fraction_telescoping_structure", ("分数裂项", "通项")),
        ("fraction_telescoping_structure", ("非相邻裂项",)),
        ("fraction_telescoping_structure", ("长链消去", "首尾项提取")),
        ("fraction_telescoping_structure", ("裂项", "首尾项")),
        ("fraction_telescoping_structure", ("裂项", "长链")),
        ("increment_invariance", ("差分增量", "参数无关")),
        ("increment_invariance", ("增量关系", "参数无关")),
        ("increment_invariance", ("公式逆向", "参数无关")),
        ("increment_invariance", ("无关量消去",)),
        ("digit_divisibility", ("数位和", "9的倍数")),
        ("digit_divisibility", ("数位整除", "魔术")),
        ("digit_divisibility", ("整除性质", "删去")),
        ("number_theory_constraint", ("余数约束",)),
        ("number_theory_constraint", ("数论约束", "枚举")),
        ("number_theory_constraint", ("同余", "约束")),
        ("number_theory_constraint", ("整除", "回查")),
        ("number_theory_constraint", ("不变量", "构造")),
        ("number_theory_constraint", ("染色", "构造")),
        ("game_strategy", ("博弈", "制胜策略")),
        ("game_strategy", ("博弈", "必胜")),
        ("game_strategy", ("对称策略", "必胜")),
        ("game_strategy", ("博弈", "对称策略")),
        ("game_strategy", ("必胜策略", "回查")),
        ("bounded_search", ("数字谜", "有界试探")),
        ("place_value_constraint", ("字母数字", "位值")),
        ("place_value_constraint", ("平方数约束", "位值")),
        ("counting_constraint", ("抽屉", "组合枚举")),
        ("counting_constraint", ("抽屉", "约束回查")),
        ("counting_constraint", ("容斥", "分类")),
        ("counting_constraint", ("复杂计数",)),
        ("constraint_enumeration", ("约束枚举",)),
        ("spatial_extreme_construction", ("三视图", "极值")),
        ("spatial_extreme_construction", ("三视图", "反向")),
        ("spatial_extreme_construction", ("空间位置", "极值构造")),
        ("geometry_chain", ("辅助线", "面积比链")),
        ("geometry_chain", ("几何割补", "反推")),
        ("geometry_chain", ("割补", "约束回查")),
        ("profit_reverse_organization", ("利润", "成本下降", "降价")),
        ("profit_reverse_organization", ("百分数", "实际利润率", "反向")),
        ("profit_reverse_organization", ("多状态百分数",)),
        ("profit_reverse_organization", ("多状态基准",)),
        ("profit_reverse_organization", ("新旧基准联动",)),
        ("profit_reverse_organization", ("成本下降", "降价", "实际利润率")),
        ("profit_reverse_organization", ("利润率", "成本下降", "降价")),
        ("ratio_global_constraints", ("其余部分之和", "总量转化")),
        ("ratio_global_constraints", ("部分与总和比例", "占总量")),
        ("ratio_global_constraints", ("共同约束", "总量转化")),
        ("ratio_global_constraints", ("多个部分", "其余部分之和")),
        ("ratio_global_constraints", ("整体与部分", "总量转化")),
        ("position_coupled_enumeration", ("位置耦合枚举",)),
        ("position_coupled_enumeration", ("概率分母构造",)),
        ("position_coupled_enumeration", ("被4整除法则", "位置耦合")),
        ("position_coupled_enumeration", ("整除约束", "概率分母")),
        ("proportional_strategy_shift", ("比例结构", "整体法", "多路径")),
        ("rule_strategy", ("规则理解", "逆向推理", "约束满足")),
        ("rule_strategy", ("规则型构造",)),
        ("rule_strategy", ("复杂规则", "约束")),
        ("constructive_proof", ("构造", "证明")),
        ("constructive_proof", ("反例", "构造")),
    )
    l3_signals = (
        ("single_variant_recognition", ("伪装场景",)),
        ("single_reverse_step", ("单次倒推",)),
        ("single_reverse_step", ("简单倒推",)),
        ("single_reverse_step", ("一次倒推",)),
        ("single_phase_change", ("单次换班",)),
        ("single_phase_change", ("简单换班",)),
        ("single_phase_change", ("一次换班",)),
        ("single_phase_change", ("相遇后",)),
        ("single_phase_change", ("简单相遇后变化",)),
        ("base_quantity_shift", ("一次变基准",)),
        ("base_quantity_shift", ("变基准",)),
        ("finite_candidate_screening", ("有限候选",)),
        ("finite_candidate_screening", ("候选筛选",)),
        ("finite_candidate_screening", ("简单候选筛选",)),
        ("finite_candidate_screening", ("筛选",)),
        ("single_modular_transform", ("同余",)),
        ("single_invariant_recognition", ("不变量",)),
        ("single_geometry_model", ("单个几何模型",)),
        ("single_geometry_model", ("单一几何模型",)),
        ("single_geometry_model", ("单个模型",)),
        ("single_geometry_model", ("蝴蝶模型",)),
        ("single_geometry_model", ("燕尾模型",)),
        ("single_geometry_model", ("鸟头模型",)),
        ("single_geometry_model", ("一半模型",)),
        ("single_geometry_model", ("等高共边",)),
        ("spatial_projection", ("三视图", "内部连线")),
        ("spatial_projection", ("三视图", "投影")),
        ("work_rate_relation", ("工程问题", "已完成", "未完成")),
        ("work_rate_relation", ("工程问题", "比例关系")),
        ("concentration_variant", ("浓度", "两次变化")),
        ("concentration_variant", ("浓度", "参数")),
        ("geometry_cut_fill", ("图形割补", "扇形")),
        ("geometry_cut_fill", ("圆", "等积变形")),
        ("geometry_cut_fill", ("组合图形", "阴影")),
        ("geometry_cut_fill", ("辅助线",)),
    )
    organization_signals = (
        ("intermediate_construction", ("构造中间量",)),
        ("intermediate_construction", ("构造", "中间量")),
        ("constraint_backcheck", ("约束回查",)),
        ("constraint_backcheck", ("回查", "约束")),
        ("relation_reorganization", ("重排题目关系",)),
        ("relation_reorganization", ("关系重排",)),
        ("reverse_organization", ("反向整理",)),
        ("comparison_organization", ("候选比较",)),
        ("comparison_organization", ("方案比较",)),
        ("geometry_followup", ("割补",)),
        ("geometry_followup", ("辅助线",)),
        ("geometry_followup", ("面积比链",)),
        ("geometry_followup", ("反推",)),
        ("travel_followup", ("等待",)),
        ("travel_followup", ("调头",)),
        ("travel_followup", ("再往返",)),
        ("bounded_enumeration_verification", ("有限枚举",)),
        ("bounded_enumeration_verification", ("枚举", "验证")),
        ("bounded_enumeration_verification", ("分类枚举",)),
        ("strategy_construction", ("构造",)),
        ("strategy_construction", ("试探",)),
    )

    def _matched_signal_groups(signals: tuple[tuple[str, tuple[str, ...]], ...]) -> List[str]:
        groups: List[str] = []
        for group, terms in signals:
            if group not in groups and _has_all(text, *terms):
                groups.append(group)
        return groups

    l5_matches = _matched_signal_groups(l5_signals)
    l4_matches = _matched_signal_groups(l4_signals)
    l3_matches = _matched_signal_groups(l3_signals)
    organization_matches = _matched_signal_groups(organization_signals)

    if l5_matches:
        target = "L5"
        variant_signal_group = l5_matches[0]
        reason = "明确包含全局收束、证明、参数化或长链结构，按知识点内压轴创新校准。"
    if not target:
        if l4_matches:
            target = "L4"
            variant_signal_group = l4_matches[0]
            reason = "包含反向整理、有限分类回查、方案构造、博弈策略、数论约束或极值构造，至少按知识点内高阶变式校准。"
        elif len(l3_matches) >= 2:
            target = "L4"
            variant_signal_group = "combined_l3_signals"
            reason = "包含两个及以上中度变式信号，已超过单次识别负担，按知识点内高阶变式校准。"
        elif l3_matches and organization_matches:
            target = "L4"
            variant_signal_group = f"{l3_matches[0]}+{organization_matches[0]}"
            reason = "单次变式识别后还需要组织、构造、回查或比较，按知识点内高阶变式校准。"
    if not target:
        if l3_matches:
            target = "L3"
            variant_signal_group = l3_matches[0]
            reason = "包含一次变式识别、单次状态变化、简单候选筛选或单个模型转化，按知识点内中度变式校准。"

    if target and DIM4_LEVEL_RANK[target] > DIM4_LEVEL_RANK[level]:
        return {
            "topic_level": target,
            "previous_level": level,
            "calibrated_level": target,
            "variant_signal_group": variant_signal_group,
            "reason": reason,
            "source": "local_topic_variant",
            "matched_l3_signal_groups": ",".join(l3_matches),
            "organization_signal_groups": ",".join(organization_matches),
        }
    return {}


def canonicalize_dim4_knowledge_point(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text)
    for alias, canonical in TOPIC_ALIASES.items():
        if alias in compact:
            return canonical
    return compact[:32]


def _combined_text(question_text: str, feature: Dict[str, Any]) -> str:
    values: List[str] = [question_text, str(feature.get("evidence_summary", ""))]
    for key in (
        "evidence_tags",
        "knowledge_tags",
        "core_knowledge_units",
        "supporting_knowledge_units",
        "method_tags",
    ):
        raw = feature.get(key, [])
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
    return " ".join(values)


def _level_from_strategy_facts(feature: Dict[str, Any]) -> str:
    shift = str(feature.get("strategy_shift_count") or "")
    breakthrough = str(feature.get("breakthrough_type") or "")
    template = str(feature.get("template_fit") or "")
    construction = str(feature.get("construction_requirement") or "")
    exploration = str(feature.get("exploration_space") or "")
    path = str(feature.get("path_openness") or "")
    global_required = feature.get("global_strategy_required") in (1, "1", True)
    reframe = str(feature.get("representation_reframe") or "")
    dead_end = str(feature.get("dead_end_risk") or "")
    shift_rank = {"0": 0, "1": 1, "2": 2, "3+": 3}.get(shift, -1)

    if (
        exploration == "open"
        or shift == "3+"
        or path == "multiple_answers"
        or (global_required and dead_end == "high" and reframe == "creative")
    ):
        return "L5"
    if (
        construction == "custom_construction"
        or exploration == "branched"
        or template == "non_routine"
        or breakthrough in {"constructive", "exploratory_search"}
        or (
            template == "reframed"
            and (
                shift_rank >= 2
                or construction == "case_construction"
                or path == "multiple_paths"
                or dead_end == "high"
            )
        )
        or (
            reframe == "structural"
            and (path == "multiple_paths" or dead_end == "high")
        )
    ):
        return "L4"
    if (
        breakthrough in {"local_trick", "strategy_shift"}
        or template == "reframed"
        or construction == "case_construction"
        or reframe == "structural"
        or shift == "1"
        or (
            exploration == "bounded"
            and (
                template in {"adapted", "reframed"}
                or path == "multiple_paths"
                or dead_end == "medium"
            )
        )
    ):
        return "L3"
    if template == "adapted" or construction == "simple_setup" or exploration == "bounded":
        return "L2"
    if feature.get("strategy_role") == "core":
        return "L1"
    return ""


def classify_dim4_topic_level(
    knowledge_point: str,
    question_text: str,
    feature: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    canonical = canonicalize_dim4_knowledge_point(knowledge_point)
    if canonical not in TOPIC_SCALE_DEFINITIONS:
        return None

    text = _combined_text(question_text, feature)
    selected_level = ""
    for level, terms in HIGH_PRIORITY_LEVEL_TERMS:
        if any(term in text for term in terms):
            selected_level = level
            break
    if not selected_level:
        selected_level = _level_from_strategy_facts(feature) or "L1"

    definition = TOPIC_SCALE_DEFINITIONS[canonical][selected_level]
    return {
        "knowledge_point": canonical,
        "topic_level": selected_level,
        "level_source": "knowledge_anchor",
        "anchor_evidence": definition,
        "reference_matches": [
            {
                "knowledge_point": canonical,
                "topic_level": selected_level,
                "definition": definition,
            }
        ],
        "fallback_used": False,
    }
