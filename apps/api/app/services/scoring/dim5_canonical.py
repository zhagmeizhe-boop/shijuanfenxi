"""Dim5 knowledge-scope normalization.

This layer turns free-form LLM knowledge labels into stable internal fields:
canonical knowledge point, knowledge domain, and L1-L5 knowledge-scope level.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


DIM5_KNOWLEDGE_DOMAINS = {
    "number_operation",
    "quantity_application",
    "geometry_spatial",
    "pattern_sequence",
    "counting_combinatorics",
    "number_theory",
    "logic_strategy_construction",
    "statistics_probability",
    "school_general",
}

DIM5_LEVEL_SCORES = {
    "L1": 2.0,
    "L2": 4.0,
    "L3": 6.0,
    "L4": 8.0,
    "L5": 9.5,
}

DIM5_LEVEL_LABELS = {
    "L1": "一至三年级校内基础",
    "L2": "四至六年级校内核心",
    "L3": "校内综合 / 三四年级奥数入门",
    "L4": "五六年级奥数典型专题 / 七年级基础前置",
    "L5": "六年级奥数较难题 / 小升初压轴 / 七年级核心门槛",
}


@dataclass(frozen=True)
class CanonicalKnowledgeRule:
    point: str
    domain: str
    level: str
    family: str
    aliases: tuple[str, ...]
    structure_aliases: tuple[str, ...] = ()
    evidence: str = ""


DIRECT_FORMULA_PATTERN = re.compile(
    r"(?:直接公式|普通公式|直接代入|套用公式|只需代入|一步公式|"
    r"长方形面积|正方形面积|三角形面积|圆(?:的)?面积|扇形面积|"
    r"长方体体积|正方体体积|圆柱(?:和圆锥)?体积|圆锥体积|"
    r"表面积公式|体积公式|百分数直接应用|直接百分数)"
)

L5_STRUCTURE_PATTERN = re.compile(
    r"(?:多模型|多个模型|模型嵌套|嵌套模型|跨专题|综合压轴|小升初压轴|压轴|"
    r"六年级奥数较难|较难变式|隐藏结构|多条件联动|多阶段建模|复杂分类|分类讨论|反推回查|"
    r"复杂容斥|复杂计数|复杂组合计数|数论综合|同余.*不变量|不变量.*同余|高阶数论|不定方程|进位制|取整|"
    r"全局必胜|全局制胜|完整状态回查|复杂面积比链|复杂立体|截面|展开图|"
    r"七年级核心|初中核心|七上核心|二元一次|一次函数|方程组|不等式|整式|有理数)"
)


CANONICAL_KNOWLEDGE_RULES: tuple[CanonicalKnowledgeRule, ...] = (
    # L5: high-order contest / cross-topic knowledge.
    CanonicalKnowledgeRule(
        point="博弈策略与必胜策略",
        domain="logic_strategy_construction",
        level="L5",
        family="game_olympiad_model",
        aliases=("博弈策略与必胜策略", "博弈必胜策略", "全局制胜策略", "制胜策略", "必胜策略"),
        structure_aliases=("玩家", "棋子", "轮流", "无法移动", "输掉游戏", "对称策略"),
        evidence="核心门槛是构造能保证获胜的博弈策略。",
    ),
    CanonicalKnowledgeRule(
        point="跨专题综合",
        domain="logic_strategy_construction",
        level="L5",
        family="cross_topic_competition",
        aliases=("跨专题", "综合压轴", "小升初压轴", "多个奥数模型", "模型嵌套", "多模型组合", "隐藏结构", "多条件联动"),
        structure_aliases=("全局", "回查", "综合", "嵌套"),
        evidence="需要跨专题、多模型组合或压轴型隐藏结构，知识门槛达到 L5。",
    ),
    CanonicalKnowledgeRule(
        point="高阶数论综合",
        domain="number_theory",
        level="L5",
        family="advanced_number_theory",
        aliases=("数论综合", "高阶数论", "同余不变量", "不变量同余", "不定方程", "进位制", "取整符号", "模运算综合"),
        structure_aliases=("构造", "反推", "联合", "综合"),
        evidence="数论约束与构造、反推或不变量等联合成为核心门槛。",
    ),
    CanonicalKnowledgeRule(
        point="复杂组合计数",
        domain="counting_combinatorics",
        level="L5",
        family="advanced_combinatorics",
        aliases=("复杂组合计数", "复杂计数", "复杂容斥", "计数综合", "排列组合综合", "多层分类"),
        structure_aliases=("不重不漏", "多层", "容斥", "综合"),
        evidence="计数知识超过单一入门模型，需要综合组织。",
    ),
    CanonicalKnowledgeRule(
        point="高阶几何综合",
        domain="geometry_spatial",
        level="L5",
        family="advanced_geometry_competition",
        aliases=("高阶面积比链", "复杂几何综合", "复杂立体几何", "多视图", "截面", "展开图"),
        structure_aliases=("重构", "链", "嵌套", "整体"),
        evidence="几何知识范围达到复杂综合或空间重构层级。",
    ),
    # L4: named olympiad topics and models.
    CanonicalKnowledgeRule(
        point="分数裂项求和",
        domain="number_operation",
        level="L4",
        family="calculation_olympiad_model",
        aliases=("分数裂项求和", "裂项相消", "分数裂项", "长链求和", "连续分式求和"),
        structure_aliases=("求和", "省略号", "分母连续", "首尾项"),
        evidence="核心门槛是识别分数裂项相消结构。",
    ),
    CanonicalKnowledgeRule(
        point="三视图与立体图形",
        domain="geometry_spatial",
        level="L4",
        family="geometry_spatial_model",
        aliases=("三视图与立体图形", "正方体投影", "三视图", "左视图", "正视图", "空间投影"),
        structure_aliases=("正方体", "立体图形", "从左面", "从前面", "观察", "看到的图形"),
        evidence="核心门槛是把立体结构投影到指定观察方向。",
    ),
    CanonicalKnowledgeRule(
        point="抽屉原理与组合枚举",
        domain="counting_combinatorics",
        level="L4",
        family="combinatorics_olympiad_model",
        aliases=("抽屉原理与组合枚举", "抽屉原理", "整数拆分", "组合枚举", "最不利原则"),
        structure_aliases=("至少有", "完全相同", "分类", "枚举", "保证"),
        evidence="核心门槛是先枚举分类盒子，再用抽屉原理保证结论。",
    ),
    CanonicalKnowledgeRule(
        point="三视图空间极值构造",
        domain="geometry_spatial",
        level="L4",
        family="geometry_spatial_model",
        aliases=("三视图空间极值构造", "空间极值构造", "三视图极值", "立体图形极值"),
        structure_aliases=("三视图", "透明积木", "从前面", "从左面", "最少", "最多"),
        evidence="核心门槛是在多个视图约束下构造最少和最多方案。",
    ),
    CanonicalKnowledgeRule(
        point="牛吃草模型",
        domain="quantity_application",
        level="L4",
        family="application_olympiad_model",
        aliases=("牛吃草", "增长与消耗", "原有量", "新增量", "消耗量", "排队检票", "检票排队", "进出水"),
        structure_aliases=("原有量", "新增量", "消耗量", "单位时间", "同时变化"),
        evidence="命中典型奥数增长与消耗模型。",
    ),
    CanonicalKnowledgeRule(
        point="面积比模型",
        domain="geometry_spatial",
        level="L4",
        family="geometry_olympiad_model",
        aliases=(
            "面积比",
            "面积比例",
            "等高面积",
            "等高",
            "共边",
            "同底",
            "蝴蝶模型",
            "蝴蝶",
            "燕尾模型",
            "燕尾",
            "鸟头",
            "沙漏",
            "一半模型",
            "半面积",
            "等积变形",
            "风筝模型",
        ),
        structure_aliases=("比例", "割补", "辅助线", "阴影面积", "三角形面积"),
        evidence="命中典型奥数面积比/面积模型。",
    ),
    CanonicalKnowledgeRule(
        point="定义新运算",
        domain="number_operation",
        level="L4",
        family="operation_olympiad_model",
        aliases=("定义新运算", "规定一种运算", "自定义运算", "新运算", "算符", "运算规则"),
        structure_aliases=("规则展开", "嵌套", "代入规则"),
        evidence="核心知识点是奥数常见的新定义运算。",
    ),
    CanonicalKnowledgeRule(
        point="裂项与长链消去",
        domain="number_operation",
        level="L4",
        family="calculation_olympiad_model",
        aliases=("裂项", "长链消去", "非相邻裂项", "首尾项", "结构求和", "分数裂项"),
        structure_aliases=("求和", "抵消", "分解"),
        evidence="核心门槛是结构化裂项或消去。",
    ),
    CanonicalKnowledgeRule(
        point="递推与差分",
        domain="pattern_sequence",
        level="L4",
        family="sequence_olympiad_model",
        aliases=("递推", "差分", "相邻差", "数列递推", "增量", "复杂周期余数"),
        structure_aliases=("前一项", "后一项", "规律", "余数"),
        evidence="命中递推、差分或复杂周期专题。",
    ),
    CanonicalKnowledgeRule(
        point="周期问题",
        domain="pattern_sequence",
        level="L3",
        family="entry_pattern_sequence",
        aliases=("简单周期", "周期规律", "周期问题", "循环规律", "周期余数"),
        structure_aliases=("第n", "第 n", "位置", "循环节", "求余"),
        evidence="属于校内延伸的周期与规律专题。",
    ),
    CanonicalKnowledgeRule(
        point="抽屉原理",
        domain="counting_combinatorics",
        level="L4",
        family="combinatorics_olympiad_model",
        aliases=("抽屉", "抽屉原理", "最不利", "至少有", "保证有"),
        structure_aliases=("分类", "分组", "保证"),
        evidence="命中典型奥数抽屉原理。",
    ),
    CanonicalKnowledgeRule(
        point="组合计数",
        domain="counting_combinatorics",
        level="L4",
        family="combinatorics_olympiad_model",
        aliases=("组合计数", "容斥", "排列组合", "分类计数", "乘法原理", "加法原理", "计数原理"),
        structure_aliases=("分类", "不重不漏", "方案数", "可能性"),
        evidence="命中奥数计数或容斥入门专题。",
    ),
    CanonicalKnowledgeRule(
        point="博弈策略",
        domain="logic_strategy_construction",
        level="L4",
        family="game_olympiad_model",
        aliases=("博弈", "必胜", "必败", "对称策略", "制胜策略", "游戏策略"),
        structure_aliases=("先手", "后手", "保证获胜", "应对"),
        evidence="命中典型奥数博弈策略。",
    ),
    CanonicalKnowledgeRule(
        point="数论约束",
        domain="number_theory",
        level="L4",
        family="number_theory_olympiad_model",
        aliases=("数论约束", "同余", "整除约束", "余数周期", "奇偶性", "不变量", "倍数约束", "整除特征"),
        structure_aliases=("余数", "整除", "模", "不变"),
        evidence="命中奥数数论约束专题。",
    ),
    CanonicalKnowledgeRule(
        point="构造类问题",
        domain="logic_strategy_construction",
        level="L4",
        family="construction_olympiad_model",
        aliases=("构造", "规则反推", "极值构造", "染色", "全局构造", "最优", "试填"),
        structure_aliases=("满足条件", "方案", "最大", "最小", "验证"),
        evidence="核心知识点是构造、规则反推或策略组织。",
    ),
    # L3: school extension / entry-level topics.
    CanonicalKnowledgeRule(
        point="倍半递推与倒推还原",
        domain="pattern_sequence",
        level="L3",
        family="entry_pattern_sequence",
        aliases=("倍半递推与倒推还原", "倍半递推", "连续减半", "连续按一半变化", "指数型变化"),
        structure_aliases=("一半", "每小时", "小时后", "倒推", "逆推"),
        evidence="核心门槛是沿连续倍半变化从末端倒推初始量。",
    ),
    CanonicalKnowledgeRule(
        point="数字性质与9的倍数判定",
        domain="number_theory",
        level="L3",
        family="entry_number_theory",
        aliases=("数字性质与9的倍数判定", "9的倍数判定", "数位和性质", "数字和性质", "整除性质"),
        structure_aliases=("四位数", "数字之和", "数位", "删去数字", "被删去"),
        evidence="核心门槛是把数位和转化为 9 的倍数整除性质。",
    ),
    CanonicalKnowledgeRule(
        point="比例整体关系",
        domain="quantity_application",
        level="L3",
        family="entry_application_model",
        aliases=("比例整体关系", "整体与部分关系", "比例关系", "部分与整体", "整体量转化"),
        structure_aliases=("之和的比", "销售总量", "总量", "方程思想"),
        evidence="核心门槛是把部分与其余部分之比统一到整体量。",
    ),
    CanonicalKnowledgeRule(
        point="典型应用题入门模型",
        domain="quantity_application",
        level="L3",
        family="entry_application_model",
        aliases=("和差倍", "年龄问题", "还原问题", "盈亏问题", "鸡兔同笼", "植树问题", "间隔问题", "阵列"),
        structure_aliases=("多步", "关系", "转化"),
        evidence="属于小升初常见专题化应用题。",
    ),
    CanonicalKnowledgeRule(
        point="简单规律与数列",
        domain="pattern_sequence",
        level="L3",
        family="entry_pattern_sequence",
        aliases=("简单周期", "周期规律", "数表规律", "等差数列", "找规律", "循环规律"),
        structure_aliases=("第n", "位置", "项"),
        evidence="属于校内延伸的规律/数列专题。",
    ),
    CanonicalKnowledgeRule(
        point="简单枚举与分类",
        domain="counting_combinatorics",
        level="L3",
        family="entry_counting",
        aliases=("简单枚举", "枚举", "分类讨论", "加法原理入门", "乘法原理入门"),
        structure_aliases=("分类", "情况", "方案"),
        evidence="属于入门计数或分类讨论。",
    ),
    CanonicalKnowledgeRule(
        point="图形割补与组合图形",
        domain="geometry_spatial",
        level="L3",
        family="entry_geometry_transform",
        aliases=("简单割补", "割补", "格点", "组合图形", "阴影面积", "图形拼接"),
        structure_aliases=("面积", "分割", "补形"),
        evidence="属于校内延伸的组合图形或简单割补。",
    ),
    CanonicalKnowledgeRule(
        point="数字谜与数阵图入门",
        domain="logic_strategy_construction",
        level="L3",
        family="entry_logic_construction",
        aliases=("数字谜", "数阵图", "幻方", "填数", "简单统筹", "优化", "最值尝试"),
        structure_aliases=("试填", "约束", "推断"),
        evidence="属于入门逻辑构造或统筹优化专题。",
    ),
    # L2: high-grade school core.
    CanonicalKnowledgeRule(
        point="高年级校内数与代数",
        domain="number_operation",
        level="L2",
        family="school_high_number",
        aliases=("分数乘除", "百分数", "比和比例", "比例方程", "简易方程", "小数分数混合运算"),
        structure_aliases=("常规应用", "方程", "比例"),
        evidence="属于五六年级校内核心知识。",
    ),
    CanonicalKnowledgeRule(
        point="高年级校内图形公式",
        domain="geometry_spatial",
        level="L2",
        family="school_high_geometry",
        aliases=("圆", "扇形", "长方体", "正方体", "圆柱", "圆锥", "表面积", "体积", "容积"),
        structure_aliases=("公式", "半径", "直径", "高"),
        evidence="属于五六年级校内图形与空间公式应用。",
    ),
    CanonicalKnowledgeRule(
        point="常规数量关系应用",
        domain="quantity_application",
        level="L2",
        family="school_high_application",
        aliases=("行程问题", "工程问题", "浓度问题", "经济问题", "折扣", "利润", "总价", "单价"),
        structure_aliases=("常规", "比例", "速度", "效率"),
        evidence="属于高年级校内常规数量关系应用。",
    ),
    CanonicalKnowledgeRule(
        point="统计与可能性",
        domain="statistics_probability",
        level="L2",
        family="school_high_statistics",
        aliases=("统计图", "条形统计图", "折线统计图", "扇形统计图", "平均数", "可能性", "概率"),
        structure_aliases=("读图", "数据", "统计"),
        evidence="属于校内统计与可能性知识。",
    ),
    CanonicalKnowledgeRule(
        point="因数倍数与质合数",
        domain="number_theory",
        level="L2",
        family="school_high_number_theory",
        aliases=("因数", "倍数", "质数", "合数", "最大公因数", "最小公倍数"),
        structure_aliases=("课内", "常规"),
        evidence="属于校内因数倍数与质合数应用。",
    ),
    # L1: direct elementary knowledge.
    CanonicalKnowledgeRule(
        point="基础四则与一步应用",
        domain="number_operation",
        level="L1",
        family="school_basic",
        aliases=("加减乘除", "整数四则", "整数计算", "小数计算", "分数直接计算", "单位换算", "时间", "人民币", "一步应用题"),
        structure_aliases=("一步", "直接"),
        evidence="只需直接调用基础校内知识。",
    ),
    CanonicalKnowledgeRule(
        point="基础平面图形公式",
        domain="geometry_spatial",
        level="L1",
        family="school_basic_geometry",
        aliases=("长方形", "正方形", "三角形面积", "长方形面积", "正方形面积", "基础测量", "位置", "方向"),
        structure_aliases=("直接公式", "直接代入"),
        evidence="只需基础图形公式或事实。",
    ),
)

DOMAIN_FALLBACK_RULES: tuple[tuple[str, str, str], ...] = (
    ("geometry_spatial", "几何图形知识", "L2"),
    ("statistics_probability", "统计与可能性", "L2"),
    ("number_theory", "数论基础", "L3"),
    ("counting_combinatorics", "计数基础", "L3"),
    ("pattern_sequence", "规律与数列", "L3"),
    ("logic_strategy_construction", "逻辑策略构造", "L3"),
    ("quantity_application", "数量关系应用", "L2"),
    ("number_operation", "数与运算", "L1"),
    ("school_general", "校内一般知识", "L1"),
)

DOMAIN_SIGNAL_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("geometry_spatial", ("几何", "图形", "面积", "体积", "圆", "三角形", "长方形", "正方形", "立体", "空间")),
    ("statistics_probability", ("统计", "平均数", "可能性", "概率", "数据", "统计图")),
    ("number_theory", ("整除", "余数", "质数", "合数", "因数", "倍数", "奇偶", "同余")),
    ("counting_combinatorics", ("计数", "枚举", "排列", "组合", "容斥", "方案数", "分类")),
    ("pattern_sequence", ("规律", "周期", "数列", "递推", "循环", "第n")),
    ("logic_strategy_construction", ("逻辑", "构造", "策略", "博弈", "数字谜", "数阵", "幻方", "最值")),
    ("quantity_application", ("应用题", "行程", "工程", "浓度", "利润", "折扣", "速度", "效率", "比例")),
    ("number_operation", ("计算", "运算", "分数", "小数", "整数", "百分数", "方程")),
)

OLD_BAND_TO_LEVEL = {
    "4年级及以前校内课本难度": "L1",
    "5、6年级校内课本难度": "L2",
    "4年级及以前高思导引拓展篇及以下难度": "L3",
    "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度": "L4",
    # Legacy "超越篇" band is retained as audit input only. It no longer
    # directly forces L5; L5 needs concrete hard-structure evidence below.
    "高思导引超越篇难度": "L4",
}


def normalize_dim5_knowledge_level(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in DIM5_LEVEL_SCORES:
        return text
    if text in {"1", "2", "3", "4", "5"}:
        return f"L{text}"
    match = re.search(r"\bL?([1-5])\b", text)
    return f"L{match.group(1)}" if match else ""


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_text(item) for item in value)
    return str(value or "")


def _collect_signal_parts(
    feature: Dict[str, Any],
    *,
    analysis_facts: Dict[str, Any],
    question_text: str = "",
    question_summary: str = "",
) -> List[str]:
    parts: List[str] = [question_text, question_summary]
    for key in (
        "primary_knowledge_point",
        "canonical_knowledge_point",
        "canonical_knowledge_domain",
        "evidence_summary",
        "knowledge_integration",
        "novel_definition_dependency",
        "competition_signal",
    ):
        parts.append(str(feature.get(key) or ""))
    for key in (
        "knowledge_tags",
        "core_knowledge_units",
        "supporting_knowledge_units",
        "method_tags",
        "evidence_tags",
        "canonical_alias_hits",
        "canonical_structure_hits",
    ):
        parts.append(_flatten_text(feature.get(key, [])))
    for key in ("core_knowledge_points", "core_methods", "visual_elements", "core_task"):
        parts.append(_flatten_text(analysis_facts.get(key, "")))
    return [part for part in parts if str(part).strip()]


def _unique(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        normalized = str(item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _level_rank(level: str) -> int:
    normalized = normalize_dim5_knowledge_level(level)
    return int(normalized[1]) if normalized else 0


def _pick_domain(combined: str) -> str:
    for domain, signals in DOMAIN_SIGNAL_RULES:
        if any(signal in combined for signal in signals):
            return domain
    return "school_general"


def _fallback_for_domain(domain: str) -> tuple[str, str]:
    for candidate_domain, point, level in DOMAIN_FALLBACK_RULES:
        if candidate_domain == domain:
            return point, level
    return "校内一般知识", "L1"


def _old_band_level(feature: Dict[str, Any]) -> str:
    band = " ".join(str(feature.get("band") or "").strip().split())
    if not band:
        return ""
    if band in OLD_BAND_TO_LEVEL:
        return OLD_BAND_TO_LEVEL[band]
    if "超越篇" in band:
        return "L4"
    if "高思" in band or "七年级" in band or "初中" in band:
        return "L4"
    if "5、6年级" in band or "五" in band or "六" in band:
        return "L2"
    if "4年级" in band or "四" in band:
        return "L1"
    return ""


def _l5_supported(feature: Dict[str, Any], combined: str, *, base_level: str = "") -> bool:
    if L5_STRUCTURE_PATTERN.search(combined):
        return True
    if _level_rank(base_level) >= 5:
        return True
    family = str(feature.get("canonical_knowledge_family") or "").strip()
    if family in {
        "cross_topic_competition",
        "advanced_number_theory",
        "advanced_combinatorics",
        "advanced_geometry_competition",
    }:
        return True
    return (
        feature.get("competition_signal") == "strong"
        and feature.get("knowledge_integration") in {"cross_family_combo", "cross_domain_bridge"}
    )


def _as_dict_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _retrieval_candidates(feature: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    context = feature.get("dim5_retrieval_context")
    if isinstance(context, dict):
        candidates.extend(_as_dict_list(context.get("candidates")))
        for key in (
            "reference_question_candidates",
            "topic_structure_candidates",
            "knowledge_point_candidates",
        ):
            candidates.extend(_as_dict_list(context.get(key)))
    candidates.extend(_as_dict_list(feature.get("dim5_retrieval_candidates")))

    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        if not candidate_id:
            candidate_id = "|".join(
                str(candidate.get(key) or "")
                for key in ("match_scope", "source", "title", "question_no")
            )
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        deduped.append(candidate)
    return deduped


def _candidate_level(candidate: Dict[str, Any]) -> str:
    return normalize_dim5_knowledge_level(candidate.get("recommended_level"))


def _candidate_quality_flags(candidate: Dict[str, Any]) -> set[str]:
    raw = candidate.get("quality_flags")
    if isinstance(raw, list):
        return {str(item).strip() for item in raw if str(item).strip()}
    text = str(raw or "").strip()
    return {part.strip() for part in text.split(",") if part.strip()}


def _candidate_l5_supported(candidate: Dict[str, Any]) -> bool:
    text = _flatten_text(
        [
            candidate.get("title"),
            candidate.get("matched_terms"),
            candidate.get("structure_signals"),
            candidate.get("grade"),
            candidate.get("grade_hint"),
            candidate.get("section_label"),
            candidate.get("section_level"),
            candidate.get("question_text_excerpt"),
        ]
    )
    return bool(L5_STRUCTURE_PATTERN.search(text))


def _retrieval_override(
    feature: Dict[str, Any],
    *,
    direct_formula_guard: bool,
) -> Dict[str, Any]:
    candidates = _retrieval_candidates(feature)
    if not candidates:
        return {}

    def candidate_sort_key(candidate: Dict[str, Any]) -> tuple[int, int, int, int]:
        scope_rank = {
            "knowledge_point": 1,
            "topic_structure": 2,
            "reference_question": 3,
        }.get(str(candidate.get("match_scope") or ""), 0)
        return (
            1 if candidate.get("can_raise_level") else 0,
            scope_rank,
            _level_rank(_candidate_level(candidate)),
            int(float(candidate.get("score") or 0.0)),
        )

    for candidate in sorted(candidates, key=candidate_sort_key, reverse=True):
        level = _candidate_level(candidate)
        if not level:
            continue
        scope = str(candidate.get("match_scope") or "").strip()
        flags = _candidate_quality_flags(candidate)
        can_raise = bool(candidate.get("can_raise_level"))
        if direct_formula_guard and _level_rank(level) > 2:
            continue
        if scope == "knowledge_point":
            continue
        if scope == "reference_question":
            strength = int(candidate.get("match_strength") or 0)
            if not can_raise or strength < 2 or flags:
                continue
        elif scope == "topic_structure":
            if not can_raise or not candidate.get("structure_signals"):
                continue
            if _level_rank(level) > 4 and not _candidate_l5_supported(candidate):
                level = "L4"
        else:
            continue

        return {
            "knowledge_level": level,
            "level_source": f"retrieval_{scope}",
            "level_evidence": _retrieval_evidence(candidate),
            "canonical_match_source": scope,
            "canonical_match_confidence": 0.9
            if scope == "reference_question"
            else 0.82,
            "canonical_alias_hits": _unique(candidate.get("matched_terms") or []),
            "canonical_structure_hits": _unique(candidate.get("structure_signals") or []),
            "retrieval_candidate_id": str(candidate.get("candidate_id") or ""),
        }
    return {}


def _retrieval_evidence(candidate: Dict[str, Any]) -> str:
    scope = str(candidate.get("match_scope") or "")
    title = str(candidate.get("title") or "").strip()
    level = _candidate_level(candidate)
    if scope == "reference_question":
        section = str(candidate.get("section_label") or candidate.get("section_level") or "").strip()
        strength = candidate.get("similarity_type") or candidate.get("match_strength") or ""
        return f"本地题目级参考命中 {title or '高思参考题'}{('（' + section + '）') if section else ''}，匹配强度 {strength}，支持 {level}。"
    if scope == "topic_structure":
        signals = "、".join(str(item) for item in (candidate.get("structure_signals") or [])[:4])
        return f"本地专题结构命中 {title or '专题结构'}{('：' + signals) if signals else ''}，支持 {level}。"
    return "本地知识点检索提供辅助证据。"


def _grounded_risk_flags(feature: Dict[str, Any]) -> set[str]:
    raw = feature.get("grounded_risk_flags")
    if isinstance(raw, list):
        return {str(item).strip() for item in raw if str(item).strip()}
    text = str(raw or "").strip()
    return {part.strip() for part in text.split(",") if part.strip()}


def _grounded_override(feature: Dict[str, Any]) -> Dict[str, Any]:
    try:
        confidence = float(feature.get("grounded_confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    point = str(feature.get("grounded_canonical_knowledge_point") or "").strip()
    domain = str(feature.get("grounded_knowledge_domain") or "").strip()
    level = normalize_dim5_knowledge_level(feature.get("grounded_knowledge_level"))
    if not point or domain not in DIM5_KNOWLEDGE_DOMAINS or not level:
        return {}
    if confidence < 0.55:
        return {}
    risks = _grounded_risk_flags(feature)
    if risks & {
        "analysis_facts_only",
        "blocked_number_theory_in_calculation",
        "blocked_number_theory_without_terms",
        "conflicting_question_structure",
        "missing_necessary_structure",
        "generic_calculation_over_specific_structure",
        "generic_geometry_over_spatial_view",
        "weak_evidence",
        "weak_question_text_match",
        "weak_reference_match",
        "no_grounded_match",
    }:
        return {}
    evidence = str(feature.get("grounded_evidence") or "").strip()
    return {
        "canonical_knowledge_point": point,
        "canonical_knowledge_domain": domain,
        "canonical_knowledge_family": str(
            feature.get("canonical_knowledge_family") or "grounded_candidate"
        ).strip(),
        "knowledge_level": level,
        "level_source": "grounded_knowledge_candidate",
        "level_evidence": evidence or "维度5知识库候选选择命中题面证据。",
        "canonical_match_source": str(
            feature.get("grounded_match_source") or "grounded_candidate"
        ).strip(),
        "canonical_match_confidence": confidence,
        "canonical_alias_hits": _unique([point]),
        "canonical_structure_hits": [],
        "canonical_direct_formula_guard": bool(feature.get("canonical_direct_formula_guard")),
    }


def _score_rule(rule: CanonicalKnowledgeRule, combined: str) -> tuple[int, List[str], List[str]]:
    alias_hits = [alias for alias in rule.aliases if alias and alias in combined]
    if not alias_hits:
        return 0, [], []
    structure_hits = [alias for alias in rule.structure_aliases if alias and alias in combined]
    score = sum(len(alias) for alias in alias_hits) + sum(len(alias) for alias in structure_hits)
    score += _level_rank(rule.level) * 3
    if structure_hits:
        score += 8
    return score, _unique(alias_hits), _unique(structure_hits)


def classify_dim5_knowledge_scope(
    feature: Dict[str, Any],
    *,
    analysis_facts: Dict[str, Any] | None = None,
    question_text: str = "",
    question_summary: str = "",
) -> Dict[str, Any]:
    grounded = _grounded_override(feature)
    if grounded:
        return grounded

    parts = _collect_signal_parts(
        feature,
        analysis_facts=analysis_facts or {},
        question_text=question_text,
        question_summary=question_summary,
    )
    combined = " ".join(parts)
    direct_formula_guard = bool(DIRECT_FORMULA_PATTERN.search(combined))
    retrieval_override = _retrieval_override(
        feature,
        direct_formula_guard=direct_formula_guard,
    )

    explicit_level = normalize_dim5_knowledge_level(feature.get("knowledge_level"))
    explicit_domain = str(feature.get("canonical_knowledge_domain") or "").strip()
    explicit_point = str(feature.get("canonical_knowledge_point") or "").strip()
    if explicit_level and explicit_domain in DIM5_KNOWLEDGE_DOMAINS and explicit_point:
        final_level = explicit_level
        level_source = str(feature.get("level_source") or "").strip() or "model"
        level_evidence = str(feature.get("level_evidence") or "").strip() or "LLM 已给出知识范围档位。"
        canonical_match_source = str(feature.get("canonical_match_source") or "").strip() or "model"
        canonical_match_confidence = float(feature.get("canonical_match_confidence") or 0.72)
        alias_hits = _unique(feature.get("canonical_alias_hits") or [])
        structure_hits = _unique(feature.get("canonical_structure_hits") or [])
        if retrieval_override and _level_rank(retrieval_override["knowledge_level"]) > _level_rank(final_level):
            final_level = retrieval_override["knowledge_level"]
            level_source = retrieval_override["level_source"]
            level_evidence = retrieval_override["level_evidence"]
            canonical_match_source = retrieval_override["canonical_match_source"]
            canonical_match_confidence = retrieval_override["canonical_match_confidence"]
            alias_hits = _unique([*alias_hits, *retrieval_override["canonical_alias_hits"]])
            structure_hits = _unique([*structure_hits, *retrieval_override["canonical_structure_hits"]])
        if final_level == "L5" and not _l5_supported(feature, combined):
            final_level = "L4"
            level_source = "minimum_sufficient_level_guard"
            level_evidence = "未见压轴变式、多条件联动、复杂分类讨论或七年级核心门槛，仅作为五六年级奥数/前置层级处理。"
        if direct_formula_guard and _level_rank(final_level) > 2:
            final_level = "L2" if explicit_domain in {"geometry_spatial", "quantity_application", "statistics_probability"} else "L1"
            level_source = "direct_formula_guard"
            level_evidence = "题目为直接公式/直接代入，不因本地检索或模型候选升到高阶知识范围。"
        return {
            "canonical_knowledge_point": explicit_point,
            "canonical_knowledge_domain": explicit_domain,
            "canonical_knowledge_family": str(feature.get("canonical_knowledge_family") or "").strip(),
            "knowledge_level": final_level,
            "level_source": level_source,
            "level_evidence": level_evidence,
            "canonical_match_source": canonical_match_source,
            "canonical_match_confidence": canonical_match_confidence,
            "canonical_alias_hits": alias_hits,
            "canonical_structure_hits": structure_hits,
            "canonical_direct_formula_guard": direct_formula_guard
            or bool(feature.get("canonical_direct_formula_guard")),
        }

    gaosi_section_text = " ".join(
        str(feature.get(key) or "")
        for key in ("gaosi_section_level", "gaosi_section_label")
    )
    section_only_challenge = "challenge" in gaosi_section_text.lower() or "超越篇" in gaosi_section_text

    candidates: List[tuple[int, CanonicalKnowledgeRule, List[str], List[str]]] = []
    if combined:
        for rule in CANONICAL_KNOWLEDGE_RULES:
            score, alias_hits, structure_hits = _score_rule(rule, combined)
            if score:
                candidates.append((score, rule, alias_hits, structure_hits))

    old_level = _old_band_level(feature)

    if candidates:
        candidates.sort(key=lambda item: (item[0], _level_rank(item[1].level)), reverse=True)
        _, rule, alias_hits, structure_hits = candidates[0]
        level = rule.level
        source = "topic_and_structure" if structure_hits else "alias"
        confidence = 0.90 if structure_hits and len(alias_hits) >= 2 else 0.78 if structure_hits else 0.68

        # Direct formula problems must stay in the school range even if they contain
        # broad geometry keywords such as ratio, cylinder, or cone.
        if direct_formula_guard and _level_rank(level) >= 4:
            domain = rule.domain if rule.domain in DIM5_KNOWLEDGE_DOMAINS else _pick_domain(combined)
            point, fallback_level = _fallback_for_domain(domain)
            level = "L2" if domain in {"geometry_spatial", "quantity_application", "statistics_probability"} else fallback_level
            return {
                "canonical_knowledge_point": point,
                "canonical_knowledge_domain": domain,
                "canonical_knowledge_family": "direct_formula_guard",
                "knowledge_level": level,
                "level_source": "direct_formula_guard",
                "level_evidence": "题目为直接公式/直接代入，不因奥数关键词升到高阶知识范围。",
                "canonical_match_source": source,
                "canonical_match_confidence": confidence,
                "canonical_alias_hits": alias_hits,
                "canonical_structure_hits": structure_hits,
                "canonical_direct_formula_guard": True,
            }

        if (
            (_l5_supported(feature, combined, base_level=level) and _level_rank(level) >= 4)
            or (
                _level_rank(level) >= 4
                and feature.get("competition_signal") == "strong"
                and feature.get("knowledge_integration") in {"cross_family_combo", "cross_domain_bridge"}
            )
        ):
            level = "L5"
        elif old_level and _level_rank(old_level) > _level_rank(level):
            # Reference-library hits remain calibration signals, but are expressed
            # as knowledge-scope levels instead of GaoSi user-facing bands.
            level = old_level
        if retrieval_override and _level_rank(retrieval_override["knowledge_level"]) > _level_rank(level):
            level = retrieval_override["knowledge_level"]
            source = retrieval_override["canonical_match_source"]
            confidence = max(confidence, retrieval_override["canonical_match_confidence"])
            alias_hits = _unique([*alias_hits, *retrieval_override["canonical_alias_hits"]])
            structure_hits = _unique([*structure_hits, *retrieval_override["canonical_structure_hits"]])
            level_source = retrieval_override["level_source"]
            level_evidence = retrieval_override["level_evidence"]
        else:
            level_source = "canonical_rule"
            level_evidence = rule.evidence or DIM5_LEVEL_LABELS[level]
            if section_only_challenge and level != "L5":
                level_evidence = (
                    "高思篇章只作为审计线索；未见压轴变式、多条件联动、复杂分类讨论或七年级核心门槛，"
                    f"按最小充分知识层级归入 {level}。"
                )

        return {
            "canonical_knowledge_point": rule.point,
            "canonical_knowledge_domain": rule.domain,
            "canonical_knowledge_family": rule.family,
            "knowledge_level": level,
            "level_source": level_source,
            "level_evidence": level_evidence,
            "canonical_match_source": source,
            "canonical_match_confidence": confidence,
            "canonical_alias_hits": alias_hits,
            "canonical_structure_hits": structure_hits,
            "canonical_direct_formula_guard": direct_formula_guard,
        }

    domain = explicit_domain if explicit_domain in DIM5_KNOWLEDGE_DOMAINS else _pick_domain(combined)
    point, fallback_level = _fallback_for_domain(domain)
    level = old_level or fallback_level
    if _l5_supported(feature, combined):
        level = "L5"
    if retrieval_override and _level_rank(retrieval_override["knowledge_level"]) > _level_rank(level):
        level = retrieval_override["knowledge_level"]
        level_source = retrieval_override["level_source"]
        level_evidence = retrieval_override["level_evidence"]
        match_source = retrieval_override["canonical_match_source"]
        match_confidence = retrieval_override["canonical_match_confidence"]
        alias_hits = retrieval_override["canonical_alias_hits"]
        structure_hits = retrieval_override["canonical_structure_hits"]
    else:
        level_source = "domain_fallback" if not old_level else "legacy_band_calibration"
        level_evidence = "未命中具体标准知识点，按知识域和参考库信号保守兜底，保证可读题目进入评分。"
        match_source = "domain_fallback" if not old_level else "legacy_band_calibration"
        match_confidence = 0.58 if combined else 0.45
        alias_hits = []
        structure_hits = []
    if direct_formula_guard and _level_rank(level) > 2:
        level = "L2" if domain in {"geometry_spatial", "quantity_application", "statistics_probability"} else "L1"
        level_source = "direct_formula_guard"
        level_evidence = "题目为直接公式/直接代入，不因本地检索或模型候选升到高阶知识范围。"

    return {
        "canonical_knowledge_point": explicit_point or str(feature.get("primary_knowledge_point") or "").strip() or point,
        "canonical_knowledge_domain": domain,
        "canonical_knowledge_family": str(feature.get("canonical_knowledge_family") or "").strip() or "domain_fallback",
        "knowledge_level": level,
        "level_source": level_source,
        "level_evidence": level_evidence,
        "canonical_match_source": match_source,
        "canonical_match_confidence": match_confidence,
        "canonical_alias_hits": alias_hits,
        "canonical_structure_hits": structure_hits,
        "canonical_direct_formula_guard": direct_formula_guard,
    }


def canonicalize_dim5_knowledge(
    feature: Dict[str, Any],
    *,
    analysis_facts: Dict[str, Any],
    question_text: str = "",
    question_summary: str = "",
) -> Dict[str, Any]:
    """Return canonical dim5 knowledge metadata for all readable questions."""

    return classify_dim5_knowledge_scope(
        feature,
        analysis_facts=analysis_facts,
        question_text=question_text,
        question_summary=question_summary,
    )
