"""Build and audit the Dim5 structured knowledge graph.

This script deliberately does not promote raw reference titles into approved
knowledge points. It validates the approved graph, summarizes local sources,
and writes a review queue for broad or ambiguous candidate terms.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.parser.dim5_knowledge_graph import (  # noqa: E402
    DIM5_GRAPH_PATH,
    Dim5KnowledgeGraph,
)


REFERENCE_FILES = (
    "reference_standard_data.json",
    "reference_standard_gaosi_question_data.json",
    "reference_standard_gaosi_pdf_data.json",
    "reference_standard_school_pdf_data.json",
)

GENERIC_TERMS = {
    "计算问题",
    "计数问题",
    "几何问题",
    "组合问题",
    "应用题",
    "综合应用",
    "数论综合",
    "数学思想",
    "专题训练",
    "拓展篇",
    "兴趣篇",
    "超越篇",
}
SCHOOL_TRACK = "校内"
SCHOOL_NODE_PREFIX = "dim5.school"
GAOSI_NODE_PREFIX = "dim5.gaosi"
SCHOOL_REVIEW_LIMIT = 500
DIM2_GEOMETRY_KB = ROOT / "config" / "scoring" / "dim2_geometry_knowledge_base.json"
SCHOOL_GENERIC_TERMS = GENERIC_TERMS | {
    "应用题",
    "计算",
    "几何",
    "基础",
    "进阶",
    "拔高",
    "解决问题",
    "总复习",
    "整理和复习",
    "数学广角",
}
CHINESE_GRADE_MAP = {
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
}
GRADE_LABELS = {
    "1": "一年级",
    "2": "二年级",
    "3": "三年级",
    "4": "四年级",
    "5": "五年级",
    "6": "六年级",
    "7": "七年级",
}
SCHOOL_FACT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("school_average_division", ("平均分", "平均", "每份", "每组", "每人")),
    ("school_unit_division_context", ("每层", "每组", "每个", "每人", "每份", "一层高", "耗时", "按照这样的制作效率")),
    ("school_division_estimation", ("除法估算", "估算", "约等于", "近似")),
    ("school_vertical_division", ("竖式", "笔算", "验算")),
    ("school_quotient_digit", ("商的位数", "商是几位数", "商是两位数", "商是三位数", "商中间", "商末尾")),
    ("school_one_digit_divisor", ("除数是一位数", "除以一位数", "一位数除")),
    ("school_division", ("除法", "除数", "被除数", "商", "余数", "除以", "平均分")),
    ("school_zero_operation", ("0的运算", "有关0", "中间有0", "末尾有0")),
    ("school_mixed_operation", ("混合运算", "四则运算", "运算顺序", "脱式", "递等式")),
    ("school_parentheses_order", ("括号", "小括号", "中括号", "先算")),
    ("school_operation_law", ("结合律", "交换律", "分配律", "运算定律", "简便运算")),
    ("school_addition_subtraction", ("加法", "减法", "加减", "加、减")),
    ("school_multiplication", ("乘法", "乘以", "多位数乘", "两位数乘")),
    ("school_fraction", ("分数", "几分之", "真分数", "假分数", "带分数", "通分", "约分")),
    ("school_decimal", ("小数", "小数点", "十分位", "百分位")),
    ("school_equation", ("方程", "未知数", "解方程")),
    ("school_division_representation", ("计算方法", "点阵图", "算盘图", "数的分解", "分解计算", "多种方法")),
    ("school_comparison", ("比较大小", "填上", "大于", "小于", "等于")),
    ("school_multiplicative_relation", ("倍数关系", "几倍", "扩大到", "缩小到")),
    ("school_translation", ("平移", "火箭升空", "电梯", "升降", "直线运动")),
    ("school_rotation", ("旋转", "荡秋千", "风车", "转动", "钟摆", "车轮", "开关门")),
    ("school_geometry_motion", ("运动现象", "图形的运动", "物体运动", "平移", "旋转", "火箭升空", "荡秋千")),
    ("school_axisymmetry", ("轴对称", "对称轴", "对称图形")),
    ("school_irregular_perimeter", ("不规则图形", "平移法", "多边形", "组合图形")),
    ("school_rectangle_square", ("长方形", "正方形", "长和宽", "边长")),
    ("school_perimeter", ("周长", "围一圈", "边长之和")),
    ("school_square_tiling_perimeter", ("小正方形", "拼成", "拼接", "共边", "周长最小", "周长最大")),
    ("school_rectangle_property", ("围成一个长方形", "围成长方形", "表示点", "点的位置", "长方形的性质")),
    ("school_area", ("面积", "平方厘米", "平方米", "平方分米")),
    ("school_volume", ("体积", "容积", "立方厘米", "立方米", "长方体", "正方体", "圆柱", "圆锥")),
    ("school_statistics", ("统计图", "统计表", "平均数", "条形统计图", "折线统计图")),
    ("school_probability", ("可能性", "一定", "不可能", "随机")),
)
GAOSI_BROAD_TOPICS = {
    "计算问题",
    "计数问题",
    "几何问题",
    "组合问题",
    "应用题",
}
GAOSI_HIGH_LEVEL_TOPIC_FRAGMENTS = (
    "综合",
    "构造",
    "不定方程",
    "进位制",
    "概率初步",
    "逻辑推理二",
    "计数综合三",
    "计数综合四",
    "数论综合",
    "几何综合",
)
GAOSI_FACT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gaosi_arithmetic", ("四则", "计算", "简便", "算式", "运算", "比较与估算", "分数计算", "循环小数")),
    ("gaosi_vertical_puzzle", ("竖式", "横式", "数字谜", "算符", "填数", "□", "空格")),
    ("gaosi_digit_puzzle", ("数字谜", "数字问题", "数位", "个位", "十位", "百位", "数字和")),
    ("gaosi_enumeration", ("枚举", "列举", "情况", "多少种", "几种", "方案", "共有多少")),
    ("gaosi_counting_principle", ("加法原理", "乘法原理", "分类", "分步")),
    ("gaosi_permutation_combination", ("排列", "组合", "选", "安排", "排队")),
    ("gaosi_inclusion_exclusion", ("包含", "排除", "重复", "重叠", "至少一个", "都", "既")),
    ("gaosi_geometric_counting", ("几何计数", "图中有多少", "三角形个数", "正方形个数", "长方形个数")),
    ("gaosi_number_theory", ("数论", "整除", "余数", "约数", "倍数", "质数", "合数", "同余", "不定方程")),
    ("gaosi_remainder", ("余数", "除以", "同余")),
    ("gaosi_divisibility", ("整除", "约数", "倍数", "质数", "合数", "因数")),
    ("gaosi_equation", ("方程", "未知数", "x", "X")),
    ("gaosi_word_relation", ("和差倍", "和倍", "差倍", "倍分", "几倍", "相差")),
    ("gaosi_basic_application", ("基本应用题", "应用题拓展", "应用题综合", "一共", "还剩", "多", "少")),
    ("gaosi_chicken_rabbit", ("鸡兔同笼", "鸡", "兔", "头", "脚", "腿")),
    ("gaosi_surplus_deficit", ("盈亏", "多", "少", "不够", "剩下")),
    ("gaosi_reverse_age", ("还原", "倒推", "年龄", "今年", "岁")),
    ("gaosi_average", ("平均数", "平均")),
    ("gaosi_work_rate", ("工程", "合作", "单独", "共同完成", "工作效率", "总工程量", "剩余工程")),
    ("gaosi_grazing_clock", ("牛吃草", "钟表", "时针", "分针", "草")),
    ("gaosi_travel", ("行程", "速度", "路程", "相遇", "追及", "流水")),
    ("gaosi_concentration_profit", ("浓度", "盐水", "溶液", "经济", "利润", "折扣", "进价", "售价")),
    ("gaosi_ratio", ("比例", "正比例", "反比例", "之比", "比是")),
    ("gaosi_geometry_basic", ("几何图形", "长度", "角度", "直线形", "图形认知")),
    ("gaosi_cut_paste", ("剪拼", "割补", "格点", "面积", "等积", "蝴蝶", "燕尾")),
    ("gaosi_lattice", ("格点", "方格", "网格", "点阵")),
    ("gaosi_circle_sector", ("圆", "扇形", "半径", "直径", "圆心角")),
    ("gaosi_solid_geometry", ("立体", "正方体", "长方体", "圆柱", "圆锥", "表面积", "体积")),
    ("gaosi_sequence", ("周期", "规律", "数列", "数表", "等差", "找规律")),
    ("gaosi_interval_array", ("间隔", "阵列", "植树", "队列")),
    ("gaosi_magic_square", ("幻方", "数阵", "数阵图")),
    ("gaosi_logic", ("逻辑", "推理", "真假", "条件", "智巧")),
    ("gaosi_optimization", ("统筹", "对策", "最值", "最多", "最少", "最大", "最小", "最优")),
    ("gaosi_construction", ("构造", "论证", "证明", "存在", "任意")),
    ("gaosi_probability", ("概率", "可能性", "随机")),
)
CURATED_SCHOOL_TOPICS: tuple[Dict[str, Any], ...] = (
    {
        "knowledge_point_id": "dim5.school.3.integer_division",
        "name": "整数除法",
        "domain": "number_operation",
        "level": "L1",
        "grade": "3",
        "semester": "下册",
        "aliases": ["除法运算", "除数是一位数的除法", "口算除法", "笔算除法", "商的位数", "商是几位数", "整百整十数除法"],
        "required_fact_groups": [["school_division", "school_unit_division_context"]],
        "source_refs": ["school_reference:reference_standard_data.json:三年级下册:第二章 除数是一位数的除法"],
    },
    {
        "knowledge_point_id": "dim5.school.3.division_estimation",
        "name": "除法估算",
        "domain": "number_operation",
        "level": "L1",
        "grade": "3",
        "semester": "下册",
        "aliases": ["除数是一位数的除法估算", "估算", "近似", "大约", "整百数近似"],
        "required_fact_groups": [["school_division"], ["school_division_estimation"]],
        "source_refs": ["school_reference:reference_standard_data.json:三年级下册:除数是一位数的除法估算"],
    },
    {
        "knowledge_point_id": "dim5.school.3.average_division",
        "name": "平均分应用",
        "domain": "quantity_application",
        "level": "L1",
        "grade": "3",
        "semester": "下册",
        "aliases": ["平均分", "平均问题", "普通除法应用", "除法中求平均问题"],
        "required_fact_groups": [["school_average_division"]],
        "source_refs": ["school_reference:reference_standard_data.json:三年级下册:除法中求平均问题"],
    },
    {
        "knowledge_point_id": "dim5.school.3.division_meaning_methods",
        "name": "除法的意义与计算方法",
        "domain": "number_operation",
        "level": "L1",
        "grade": "3",
        "semester": "下册",
        "aliases": ["除法的意义", "除法计算方法", "点阵图", "算盘图", "分解计算"],
        "required_fact_groups": [["school_division_representation"]],
        "source_refs": ["school_reference:reference_standard_data.json:三年级下册:除法的意义与计算方法"],
    },
    {
        "knowledge_point_id": "dim5.school.3.translation_rotation",
        "name": "平移和旋转",
        "domain": "geometry_spatial",
        "level": "L1",
        "grade": "3",
        "semester": "unknown",
        "aliases": ["运动现象分类", "平移", "旋转", "图形的运动"],
        "required_fact_groups": [["school_geometry_motion"], ["school_translation", "school_rotation"]],
        "source_refs": ["school_reference:dim2_geometry_knowledge_base.json:平移和旋转"],
    },
    {
        "knowledge_point_id": "dim5.school.3.rectangle_square_perimeter",
        "name": "长方形和正方形周长",
        "domain": "geometry_spatial",
        "level": "L1",
        "grade": "3",
        "semester": "上册",
        "aliases": ["长方形和正方形的周长", "正方形周长公式", "周长计算", "边长之和"],
        "required_fact_groups": [["school_perimeter", "school_square_tiling_perimeter"], ["school_rectangle_square", "school_square_tiling_perimeter"]],
        "source_refs": ["school_reference:reference_standard_data.json:三年级上册:第七章 长方形和正方形"],
    },
    {
        "knowledge_point_id": "dim5.school.3.rectangle_property",
        "name": "长方形的特征",
        "domain": "geometry_spatial",
        "level": "L1",
        "grade": "3",
        "semester": "上册",
        "aliases": ["长方形性质", "长方形的性质", "围成长方形", "点的位置关系"],
        "required_fact_groups": [["school_rectangle_property"]],
        "source_refs": ["school_reference:reference_standard_data.json:三年级上册:长方形的特征"],
    },
    {
        "knowledge_point_id": "dim5.school.3.number_comparison",
        "name": "数的大小比较",
        "domain": "number_operation",
        "level": "L1",
        "grade": "3",
        "semester": "unknown",
        "aliases": ["比较大小", "填上大于小于等于", "算式比较大小"],
        "required_fact_groups": [["school_comparison"]],
        "source_refs": ["school_reference:reference_standard_data.json:三年级:数的大小比较"],
    },
    {
        "knowledge_point_id": "dim5.school.3.chained_multiplication_parentheses",
        "name": "连乘运算顺序",
        "domain": "number_operation",
        "level": "L1",
        "grade": "3",
        "semester": "unknown",
        "aliases": ["连乘运算", "括号作用", "先算什么", "乘法结合律"],
        "required_fact_groups": [["school_multiplication"], ["school_parentheses_order"]],
        "source_refs": ["school_reference:reference_standard_data.json:三年级:连乘运算顺序"],
    },
    {
        "knowledge_point_id": "dim5.school.3.vertical_one_digit_division",
        "name": "除数是一位数的竖式计算",
        "domain": "number_operation",
        "level": "L1",
        "grade": "3",
        "semester": "下册",
        "aliases": ["竖式计算", "笔算除法", "除法验算", "除数是一位数的除法"],
        "required_fact_groups": [["school_division"], ["school_vertical_division"]],
        "source_refs": ["school_reference:reference_standard_data.json:三年级下册:除数是一位数的笔算除法"],
    },
    {
        "knowledge_point_id": "dim5.school.3.irregular_perimeter",
        "name": "不规则图形周长",
        "domain": "geometry_spatial",
        "level": "L1",
        "grade": "3",
        "semester": "上册",
        "aliases": ["多边形周长", "平移法求不规则图形周长", "组合图形周长"],
        "required_fact_groups": [["school_perimeter"], ["school_irregular_perimeter"]],
        "source_refs": ["school_reference:reference_standard_data.json:三年级上册:平移法求不规则图形周长"],
    },
    {
        "knowledge_point_id": "dim5.school.3.zero_operation",
        "name": "0的运算性质",
        "domain": "number_operation",
        "level": "L1",
        "grade": "3",
        "semester": "unknown",
        "aliases": ["0 的运算性质", "0的乘法性质", "有关0的运算", "中间有0", "末尾有0"],
        "required_fact_groups": [["school_zero_operation"]],
        "source_refs": ["school_reference:reference_standard_data.json:三年级:有关0的运算"],
    },
    {
        "knowledge_point_id": "dim5.school.3.mixed_operation_parentheses",
        "name": "混合运算与括号",
        "domain": "number_operation",
        "level": "L1",
        "grade": "3",
        "semester": "unknown",
        "aliases": ["混合运算", "括号运算", "括号作用", "运算顺序"],
        "required_fact_groups": [["school_mixed_operation"], ["school_parentheses_order"]],
        "source_refs": ["school_reference:reference_standard_data.json:校内:混合运算"],
    },
    {
        "knowledge_point_id": "dim5.school.4.multiplication_laws",
        "name": "乘法运算定律",
        "domain": "number_operation",
        "level": "L2",
        "grade": "4",
        "semester": "下册",
        "aliases": ["乘法结合律", "乘法交换律", "乘法分配律", "连乘运算顺序", "简便运算"],
        "required_fact_groups": [["school_operation_law"]],
        "source_refs": ["school_reference:reference_standard_data.json:四年级下册:第三章 运算定律"],
    },
    {
        "knowledge_point_id": "dim5.school.3.axisymmetry",
        "name": "轴对称图形",
        "domain": "geometry_spatial",
        "level": "L1",
        "grade": "3",
        "semester": "unknown",
        "aliases": ["轴对称", "对称轴", "对称图形"],
        "required_fact_groups": [["school_axisymmetry"]],
        "source_refs": ["school_reference:dim2_geometry_knowledge_base.json:轴对称图形"],
    },
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def as_entries(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("entries", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def collect_candidate_terms(entries: Iterable[Dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for entry in entries:
        for key in ("topic_category", "lecture_title", "category", "title"):
            term = str(entry.get(key) or "").strip()
            if term:
                counter[term] += 1
    return counter


def clean_school_term(value: Any) -> str:
    text = " ".join(str(value or "").replace("※", "").split()).strip()
    text = re.sub(r"^第[一二三四五六七八九十]+章\s*", "", text)
    text = re.sub(r"^\d+\s*", "", text)
    text = text.replace("（", "(").replace("）", ")")
    text = re.sub(r"\((一|二|三|四|五|六|七|八|九|十)\)", "", text)
    text = text.strip(" -_/、，,。；;:")
    return text


def normalize_school_grade(value: Any) -> str:
    text = str(value or "").strip()
    for digit in ("1", "2", "3", "4", "5", "6", "7"):
        if digit in text:
            return digit
    for key, digit in CHINESE_GRADE_MAP.items():
        if f"{key}年级" in text or f"{key}阶" in text:
            return digit
    return ""


def normalize_school_semester(value: Any) -> str:
    text = str(value or "").strip()
    if "上" in text:
        return "上册"
    if "下" in text:
        return "下册"
    return "unknown"


def school_level_for_grade(grade: str) -> str:
    if grade in {"1", "2", "3"}:
        return "L1"
    if grade in {"4", "5", "6"}:
        return "L2"
    return ""


def school_domain_for_text(blob: str) -> str:
    if any(term in blob for term in ("因数", "倍数", "质数", "合数", "约数", "公因数", "公倍数")):
        return "number_theory"
    if any(term in blob for term in ("周长", "面积", "体积", "容积", "图形", "几何", "长方形", "正方形", "三角形", "圆", "平移", "旋转", "轴对称")):
        return "geometry_spatial"
    if any(term in blob for term in ("统计", "平均数", "可能性", "概率")):
        return "statistics_probability"
    if any(term in blob for term in ("规律", "周期", "数列", "找规律")):
        return "pattern_sequence"
    if any(term in blob for term in ("平均", "比例", "比", "应用", "归一", "归总", "工程", "行程", "浓度", "经济")):
        return "quantity_application"
    if any(term in blob for term in ("加", "减", "乘", "除", "分数", "小数", "方程", "运算", "计算")):
        return "number_operation"
    return "school_general"


def gaosi_domain_for_text(blob: str) -> str:
    if any(term in blob for term in ("数论", "整除", "余数", "约数", "倍数", "质数", "合数", "不定方程", "进位制")):
        return "number_theory"
    if any(term in blob for term in ("几何", "图形", "长度", "角度", "剪拼", "割补", "格点", "直线形", "圆", "扇形", "立体")):
        return "geometry_spatial"
    if any(term in blob for term in ("枚举", "计数", "排列", "组合", "包含", "排除", "抽屉", "概率", "加法原理", "乘法原理", "分类", "分步")):
        return "counting_combinatorics"
    if any(term in blob for term in ("周期", "规律", "数列", "数表", "等差", "间隔", "阵列")):
        return "pattern_sequence"
    if any(term in blob for term in ("逻辑", "统筹", "对策", "最值", "构造", "论证", "智巧")):
        return "logic_strategy_construction"
    if any(term in blob for term in ("工程", "行程", "浓度", "经济", "比例", "和差倍", "盈亏", "还原", "年龄", "鸡兔", "应用题", "平均数", "牛吃草")):
        return "quantity_application"
    if any(term in blob for term in ("四则", "计算", "竖式", "横式", "小数", "分数", "算符", "数字谜", "方程")):
        return "number_operation"
    return "school_general"


def school_aliases(entry: Dict[str, Any], point_name: str) -> List[str]:
    aliases: List[str] = []
    for key in ("category", "title", "note"):
        value = clean_school_term(entry.get(key))
        if value and value != point_name:
            aliases.append(value)
    keywords = entry.get("keywords") or []
    if isinstance(keywords, list):
        aliases.extend(clean_school_term(item) for item in keywords)
    aliases.append(point_name)
    aliases = [item for item in aliases if item and item not in SCHOOL_GENERIC_TERMS and len(item) > 1]
    return list(dict.fromkeys(aliases))[:16]


def school_fact_groups(point_name: str, aliases: Sequence[str], category: str) -> List[List[str]]:
    blob = " ".join([point_name, category, *aliases])
    matched = [fact_key for fact_key, terms in SCHOOL_FACT_RULES if any(term in blob for term in terms)]
    if "school_vertical_division" in matched and not any(
        term in point_name for term in ("竖式", "笔算", "验算", "列竖式")
    ):
        matched.remove("school_vertical_division")
    if not matched:
        return []

    groups: List[List[str]] = []

    def add_group(*keys: str) -> None:
        group = [key for key in keys if key in matched]
        if group and group not in groups:
            groups.append(group)

    if "school_division" in matched:
        add_group("school_division", "school_unit_division_context")
        add_group("school_average_division")
        add_group("school_division_estimation")
        add_group("school_vertical_division")
        add_group("school_quotient_digit")
        add_group("school_division_representation")
    elif "school_unit_division_context" in matched:
        add_group("school_unit_division_context")
    elif "school_multiplication" in matched:
        add_group("school_multiplication")
    elif "school_addition_subtraction" in matched:
        add_group("school_addition_subtraction")

    add_group("school_zero_operation")
    add_group("school_average_division")
    add_group("school_mixed_operation")
    add_group("school_parentheses_order")
    add_group("school_operation_law")
    add_group("school_fraction")
    add_group("school_decimal")
    add_group("school_equation")
    add_group("school_comparison")
    add_group("school_division_representation")
    add_group("school_multiplicative_relation")

    if "school_geometry_motion" in matched:
        add_group("school_geometry_motion")
        add_group("school_translation", "school_rotation")
    add_group("school_axisymmetry")
    if "school_perimeter" in matched:
        add_group("school_perimeter", "school_square_tiling_perimeter")
        add_group("school_rectangle_square", "school_square_tiling_perimeter")
        add_group("school_irregular_perimeter")
    add_group("school_rectangle_property")
    add_group("school_area")
    add_group("school_volume")
    add_group("school_statistics")
    add_group("school_probability")

    if not groups:
        groups.append([matched[0]])
    return groups


def school_node_id(grade: str, point_name: str, category: str) -> str:
    digest = hashlib.sha1(f"{grade}|{category}|{point_name}".encode("utf-8")).hexdigest()[:12]
    return f"{SCHOOL_NODE_PREFIX}.{grade}.{digest}"


def school_display_name(grade: str, point_name: str) -> str:
    return f"校内{GRADE_LABELS.get(grade, '年级未确认')}：{point_name}"


def curated_school_topic_nodes() -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for item in CURATED_SCHOOL_TOPICS:
        grade = str(item.get("grade") or "").strip()
        point_name = clean_school_term(item.get("name") or "")
        nodes.append(
            {
                "knowledge_point_id": str(item.get("knowledge_point_id") or "").strip(),
                "name": point_name,
                "domain": str(item.get("domain") or "school_general").strip(),
                "level": str(item.get("level") or school_level_for_grade(grade)).strip(),
                "quality_status": "approved",
                "knowledge_track": "school",
                "knowledge_track_label": "校内",
                "knowledge_grade": grade,
                "knowledge_grade_label": GRADE_LABELS.get(grade, "年级未确认"),
                "knowledge_semester": str(item.get("semester") or "unknown").strip(),
                "knowledge_display_name": school_display_name(grade, point_name),
                "aliases": list(dict.fromkeys(clean_school_term(alias) for alias in item.get("aliases") or [] if clean_school_term(alias))),
                "required_fact_groups": item.get("required_fact_groups") or [],
                "exclude_fact_keys": ["pigeonhole"],
                "confusable_with": [],
                "positive_examples": [f"{school_display_name(grade, point_name)}需要题面出现对应结构证据"],
                "near_miss_examples": [f"只出现“{point_name}”相近文字但没有题面结构证据"],
                "negative_examples": ["宽泛章节名、来源标签或没有结构证据的题目"],
                "source_refs": list(item.get("source_refs") or ["curated:school_topic"]),
            }
        )
    return nodes


def school_source_ref(entry: Dict[str, Any], source_file: str) -> str:
    grade_hint = clean_school_term(entry.get("grade_hint") or entry.get("grade") or "")
    category = clean_school_term(entry.get("category") or "")
    title = clean_school_term(entry.get("title") or entry.get("knowledge_point") or "")
    source = clean_school_term(entry.get("source") or entry.get("source_label") or "")
    return f"school_reference:{source_file}:{source}:{grade_hint}:{category}:{title}"


def school_node_from_entry(entry: Dict[str, Any], source_file: str) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    point_name = clean_school_term(entry.get("title") or entry.get("knowledge_point"))
    category = clean_school_term(entry.get("category") or "")
    if not point_name or point_name in SCHOOL_GENERIC_TERMS or len(point_name) <= 1:
        return None, {"term": point_name or category, "reason": "generic_or_empty_school_term", "source_file": source_file}

    grade = normalize_school_grade(entry.get("grade_hint") or entry.get("grade"))
    level = school_level_for_grade(grade)
    if not grade or not level:
        return None, {"term": point_name, "reason": "missing_supported_school_grade", "source_file": source_file}

    aliases = school_aliases(entry, point_name)
    required_groups = school_fact_groups(point_name, aliases, category)
    if not required_groups:
        return None, {"term": point_name, "reason": "missing_structural_rule", "source_file": source_file}

    grade_label = GRADE_LABELS.get(grade, "年级未确认")
    node = {
        "knowledge_point_id": school_node_id(grade, point_name, category),
        "name": point_name,
        "domain": school_domain_for_text(" ".join([point_name, category, *aliases])),
        "level": level,
        "quality_status": "approved",
        "knowledge_track": "school",
        "knowledge_track_label": "校内",
        "knowledge_grade": grade,
        "knowledge_grade_label": grade_label,
        "knowledge_semester": normalize_school_semester(entry.get("grade_hint") or entry.get("semester")),
        "knowledge_display_name": school_display_name(grade, point_name),
        "aliases": aliases,
        "required_fact_groups": required_groups,
        "exclude_fact_keys": ["pigeonhole"] if any(term in point_name for term in ("平均", "除法", "分配")) else [],
        "confusable_with": [],
        "positive_examples": [f"{school_display_name(grade, point_name)}需要题面出现对应结构证据"],
        "near_miss_examples": [f"只出现“{point_name}”相近文字但没有题面结构证据"],
        "negative_examples": ["宽泛章节名、来源标签或没有结构证据的题目"],
        "source_refs": [school_source_ref(entry, source_file)],
    }
    return node, None


def geometry_entry_to_school_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    grade = clean_school_term(entry.get("grade") or "")
    return {
        "source": "dim2_geometry_knowledge_base",
        "category": clean_school_term(entry.get("category") or ""),
        "title": clean_school_term(entry.get("knowledge_point") or ""),
        "track": clean_school_term(entry.get("source_label") or ""),
        "grade_hint": grade + clean_school_term(entry.get("semester") or ""),
        "note": clean_school_term(entry.get("confidence") or ""),
        "keywords": [
            clean_school_term(entry.get("knowledge_point") or ""),
            clean_school_term(entry.get("category") or ""),
            *[clean_school_term(item) for item in entry.get("aliases") or []],
        ],
    }


def build_school_nodes(reference_dir: Path, existing_nodes: Sequence[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    existing_ids = {str(node.get("knowledge_point_id") or "") for node in existing_nodes}
    existing_signatures = {
        (
            str(node.get("knowledge_track") or ""),
            str(node.get("knowledge_grade") or ""),
            clean_school_term(node.get("name") or ""),
        )
        for node in existing_nodes
    }
    entries: List[tuple[Dict[str, Any], str]] = []
    reference_data = load_json(reference_dir / "reference_standard_data.json")
    for entry in as_entries(reference_data):
        if str(entry.get("track") or "").strip() == SCHOOL_TRACK:
            entries.append((entry, "reference_standard_data.json"))

    if DIM2_GEOMETRY_KB.exists():
        for entry in as_entries(load_json(DIM2_GEOMETRY_KB)):
            if str(entry.get("source_label") or "").strip() == SCHOOL_TRACK:
                entries.append((geometry_entry_to_school_entry(entry), "dim2_geometry_knowledge_base.json"))

    nodes: List[Dict[str, Any]] = []
    review: List[Dict[str, Any]] = []
    seen_ids = set(existing_ids)
    seen_signatures = set(existing_signatures)
    for node in curated_school_topic_nodes():
        signature = (
            node["knowledge_track"],
            node["knowledge_grade"],
            clean_school_term(node["name"]),
        )
        if node["knowledge_point_id"] in seen_ids or signature in seen_signatures:
            continue
        seen_ids.add(node["knowledge_point_id"])
        seen_signatures.add(signature)
        nodes.append(node)

    for entry, source_file in entries:
        node, skipped = school_node_from_entry(entry, source_file)
        if skipped:
            review.append(skipped)
            continue
        assert node is not None
        signature = (
            node["knowledge_track"],
            node["knowledge_grade"],
            clean_school_term(node["name"]),
        )
        if node["knowledge_point_id"] in seen_ids or signature in seen_signatures:
            continue
        seen_ids.add(node["knowledge_point_id"])
        seen_signatures.add(signature)
        nodes.append(node)
    return nodes, review


def normalize_gaosi_topic(value: Any) -> str:
    return clean_school_term(value)


def gaosi_topic_base(topic: str) -> str:
    text = normalize_gaosi_topic(topic)
    text = re.sub(r"(问题)?[一二三四五六]$", "", text)
    text = re.sub(r"(综合|计算)[一二三四五六]$", r"\1", text)
    return text.strip(" -_/、，,。；;:") or topic


def gaosi_node_id(grade: str, topic: str) -> str:
    digest = hashlib.sha1(f"gaosi|{grade}|{topic}".encode("utf-8")).hexdigest()[:12]
    return f"{GAOSI_NODE_PREFIX}.{grade}.{digest}"


def gaosi_display_name(grade: str, topic: str) -> str:
    return f"奥数{GRADE_LABELS.get(grade, '年级未确认')}：{topic}"


def gaosi_level_for_topic(grade: str, topic: str) -> str:
    if any(fragment in topic for fragment in GAOSI_HIGH_LEVEL_TOPIC_FRAGMENTS):
        return "L5"
    if grade in {"3", "4"}:
        return "L3"
    if grade in {"5", "6"}:
        return "L4"
    return ""


def gaosi_aliases(entries: Sequence[Dict[str, Any]], topic: str) -> List[str]:
    aliases: List[str] = [topic, gaosi_topic_base(topic)]
    for entry in entries:
        for key in ("lecture_title", "topic_category", "category", "title"):
            value = normalize_gaosi_topic(entry.get(key))
            if value and value not in GAOSI_BROAD_TOPICS:
                aliases.append(value)

    base = gaosi_topic_base(topic)
    if base and base != topic:
        aliases.append(base)
    aliases.extend(gaosi_split_aliases(topic))
    aliases = [item for item in aliases if item and item not in GAOSI_BROAD_TOPICS and len(item) > 1]
    return list(dict.fromkeys(aliases))[:20]


def gaosi_split_aliases(topic: str) -> List[str]:
    text = normalize_gaosi_topic(topic)
    aliases: List[str] = []
    for part in re.split(r"[与和、/]+", text):
        part = gaosi_topic_base(part)
        if len(part) <= 1 or part in GAOSI_BROAD_TOPICS:
            continue
        aliases.append(part)
        aliases.append(re.sub(r"(问题|初步|扩展)$", "", part))
    if "牛吃草" in text:
        aliases.extend(["牛吃草", "牛吃草问题", "钟表问题"])
    if "鸡兔同笼" in text:
        aliases.extend(["鸡兔同笼", "头脚问题"])
    if "加法原理" in text or "乘法原理" in text:
        aliases.extend(["加法原理", "乘法原理", "分类计数", "分步计数"])
    if "格点" in text and "割补" in text:
        aliases.extend(["格点", "割补", "格点割补"])
    if "抽屉" in text:
        aliases.extend(["抽屉原理", "最不利原则"])
    if "浓度" in text:
        aliases.extend(["浓度问题", "经济问题"])
    if "数字谜" in text:
        aliases.extend(["数字谜", "数字谜问题"])
    if "竖式" in text:
        aliases.extend(["竖式", "竖式问题"])
    return list(dict.fromkeys(alias for alias in aliases if alias and alias != text))


def _gaosi_topic_has(topic: str, *fragments: str) -> bool:
    return any(fragment in topic for fragment in fragments)


def gaosi_fact_groups(topic: str, aliases: Sequence[str], examples: Sequence[str]) -> List[List[str]]:
    text = " ".join([topic, *aliases])

    if _gaosi_topic_has(text, "计数综合"):
        return [["gaosi_counting_synthesis"]]
    if _gaosi_topic_has(text, "计算综合", "整数计算综合"):
        return [["gaosi_arithmetic_synthesis"]]
    if _gaosi_topic_has(text, "数论综合"):
        return [["gaosi_number_theory_synthesis"]]
    if _gaosi_topic_has(text, "几何综合"):
        return [["gaosi_geometry_synthesis"]]
    if _gaosi_topic_has(text, "应用题综合"):
        return [["gaosi_application_synthesis"]]

    if _gaosi_topic_has(text, "抽屉"):
        return [["pigeonhole"], ["guarantee_at_least"]]
    if _gaosi_topic_has(text, "鸡兔同笼"):
        return [["gaosi_chicken_rabbit"]]
    if _gaosi_topic_has(text, "牛吃草", "钟表"):
        return [["gaosi_grazing_clock"]]
    if _gaosi_topic_has(text, "工程"):
        return [["gaosi_work_rate"]]
    if _gaosi_topic_has(text, "行程"):
        return [["gaosi_travel"]]
    if _gaosi_topic_has(text, "浓度", "经济"):
        return [["gaosi_concentration_profit"]]
    if _gaosi_topic_has(text, "比例"):
        return [["gaosi_ratio"]]
    if _gaosi_topic_has(text, "和差倍", "和倍", "差倍"):
        return [["gaosi_word_relation"]]
    if _gaosi_topic_has(text, "盈亏"):
        return [["gaosi_surplus_deficit"]]
    if _gaosi_topic_has(text, "还原", "年龄"):
        return [["gaosi_reverse_age"]]
    if _gaosi_topic_has(text, "平均数"):
        return [["gaosi_average"]]
    if _gaosi_topic_has(text, "基本应用题", "应用题拓展"):
        return [["gaosi_basic_application"]]

    if _gaosi_topic_has(text, "加法原理", "乘法原理"):
        return [["gaosi_counting_principle"]]
    if _gaosi_topic_has(text, "排列组合"):
        return [["gaosi_permutation_combination"]]
    if _gaosi_topic_has(text, "包含", "排除"):
        return [["gaosi_inclusion_exclusion"]]
    if _gaosi_topic_has(text, "枚举"):
        return [["gaosi_enumeration"]]
    if _gaosi_topic_has(text, "几何计数"):
        return [["gaosi_geometric_counting"]]
    if _gaosi_topic_has(text, "概率"):
        return [["gaosi_probability"]]

    if _gaosi_topic_has(text, "数字谜", "数字问题", "算符与数字"):
        return [["gaosi_digit_puzzle"], ["gaosi_vertical_puzzle"]]
    if _gaosi_topic_has(text, "幻方", "数阵"):
        return [["gaosi_magic_square"]]
    if _gaosi_topic_has(text, "竖式", "横式"):
        return [["gaosi_vertical_puzzle"]]
    if _gaosi_topic_has(text, "余数"):
        return [["gaosi_remainder"]]
    if _gaosi_topic_has(text, "整除", "约数", "倍数", "质数", "合数"):
        return [["gaosi_divisibility"]]
    if _gaosi_topic_has(text, "不定方程", "方程解"):
        return [["gaosi_equation"]]
    if _gaosi_topic_has(text, "进位制", "取整符号"):
        return [["gaosi_number_theory"]]

    if _gaosi_topic_has(text, "格点") and _gaosi_topic_has(text, "割补"):
        return [["gaosi_lattice"], ["gaosi_cut_paste"]]
    if _gaosi_topic_has(text, "剪拼", "割补"):
        return [["gaosi_cut_paste"]]
    if _gaosi_topic_has(text, "圆", "扇形"):
        return [["gaosi_circle_sector"]]
    if _gaosi_topic_has(text, "立体"):
        return [["gaosi_solid_geometry"]]
    if _gaosi_topic_has(text, "直线形", "长度", "角度", "几何图形"):
        return [["gaosi_geometry_basic"]]

    if _gaosi_topic_has(text, "分数数列"):
        return [["gaosi_sequence"], ["gaosi_arithmetic"]]
    if _gaosi_topic_has(text, "周期", "规律", "数列", "数表", "等差"):
        return [["gaosi_sequence"]]
    if _gaosi_topic_has(text, "间隔", "阵列"):
        return [["gaosi_interval_array"]]

    if _gaosi_topic_has(text, "逻辑推理", "智巧"):
        return [["gaosi_logic"]]
    if _gaosi_topic_has(text, "统筹", "对策", "最值"):
        return [["gaosi_optimization"]]
    if _gaosi_topic_has(text, "构造", "论证"):
        return [["gaosi_construction"]]

    if _gaosi_topic_has(text, "分数", "循环小数", "四则运算", "多位数", "小数", "比较与估算"):
        return [["gaosi_arithmetic"]]
    return []


def _gaosi_topic_exclude_fact_keys(topic: str) -> List[str]:
    excludes: List[str] = []
    if "抽屉" in topic:
        excludes.append("school_average_division")
    if "排列组合" in topic:
        excludes.extend(["school_square_tiling_perimeter", "school_perimeter"])
    if "工程" in topic:
        excludes.extend(["school_average_division", "school_unit_division_context", "school_division"])
    return list(dict.fromkeys(excludes))


def gaosi_source_refs(grade: str, topic: str, entries: Sequence[Dict[str, Any]]) -> List[str]:
    refs: List[str] = []
    for entry in entries[:6]:
        section = str(entry.get("section_label") or entry.get("section_level") or "").strip()
        qno = str(entry.get("question_no") or "").strip()
        page = str(entry.get("page_no") or "").strip()
        refs.append(f"gaosi_question:{grade}年级:{topic}:{section}:p{page}:q{qno}")
    return refs or [f"gaosi_topic:{grade}年级:{topic}"]


def build_gaosi_nodes(reference_dir: Path, existing_nodes: Sequence[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    path = reference_dir / "reference_standard_gaosi_question_data.json"
    entries = as_entries(load_json(path))
    grouped: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    for entry in entries:
        grade = normalize_school_grade(entry.get("grade") or entry.get("grade_hint"))
        topic = normalize_gaosi_topic(entry.get("lecture_title") or entry.get("topic_category") or entry.get("title"))
        if not grade or not topic:
            continue
        grouped.setdefault((grade, topic), []).append(entry)

    existing_ids = {str(node.get("knowledge_point_id") or "") for node in existing_nodes}
    existing_signatures = {
        (
            str(node.get("knowledge_track") or ""),
            str(node.get("knowledge_grade") or ""),
            normalize_gaosi_topic(node.get("name") or ""),
        )
        for node in existing_nodes
    }
    nodes: List[Dict[str, Any]] = []
    review: List[Dict[str, Any]] = []
    for (grade, topic), topic_entries in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        if topic in GAOSI_BROAD_TOPICS:
            review.append({"term": topic, "reason": "generic_or_broad_gaosi_topic", "source_file": path.name})
            continue
        level = gaosi_level_for_topic(grade, topic)
        if not level:
            review.append({"term": topic, "reason": "missing_supported_gaosi_grade", "source_file": path.name})
            continue
        examples = [
            str(entry.get("question_text") or "").strip()
            for entry in topic_entries
            if str(entry.get("question_text") or "").strip()
        ][:8]
        aliases = gaosi_aliases(topic_entries, topic)
        required_groups = gaosi_fact_groups(topic, aliases, examples)
        if not required_groups:
            review.append({"term": topic, "reason": "missing_gaosi_structural_rule", "source_file": path.name})
            continue
        node_id = gaosi_node_id(grade, topic)
        signature = ("olympiad", grade, topic)
        if node_id in existing_ids or signature in existing_signatures:
            continue
        existing_ids.add(node_id)
        existing_signatures.add(signature)
        nodes.append(
            {
                "knowledge_point_id": node_id,
                "name": topic,
                "domain": gaosi_domain_for_text(" ".join([topic, *aliases])),
                "level": level,
                "quality_status": "approved",
                "knowledge_track": "olympiad",
                "knowledge_track_label": "奥数",
                "knowledge_grade": grade,
                "knowledge_grade_label": GRADE_LABELS.get(grade, "年级未确认"),
                "knowledge_semester": "unknown",
                "knowledge_display_name": gaosi_display_name(grade, topic),
                "aliases": aliases,
                "required_fact_groups": required_groups,
                "exclude_fact_keys": _gaosi_topic_exclude_fact_keys(topic),
                "confusable_with": [],
                "positive_examples": examples[:3] or [f"{gaosi_display_name(grade, topic)}需要题面出现对应结构证据"],
                "near_miss_examples": [f"只出现“{topic}”相近文字但没有对应高思专题结构"],
                "negative_examples": ["宽泛分类标签、校内基础题或缺少结构证据的题目"],
                "source_refs": gaosi_source_refs(grade, topic, topic_entries),
            }
        )
    return nodes, review


def review_reason(term: str, approved_names: set[str], approved_aliases: set[str]) -> str:
    if term in approved_names or term in approved_aliases:
        return "already_covered_by_approved_graph"
    if term in GENERIC_TERMS or len(term) <= 2:
        return "generic_or_broad_label"
    if any(fragment in term for fragment in ("综合", "问题", "专题")):
        return "needs_structure_split_before_approval"
    return "needs_manual_structure_rules"


def build_report(
    graph: Dim5KnowledgeGraph,
    reference_dir: Path,
    *,
    generated_school_count: int = 0,
    generated_gaosi_count: int = 0,
    school_review_queue: Sequence[Dict[str, Any]] = (),
    gaosi_review_queue: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    validation_errors = graph.validate()
    approved_nodes = list(graph.approved_nodes)
    source_summaries: Dict[str, Any] = {}
    candidate_counter: Counter[str] = Counter()
    for file_name in REFERENCE_FILES:
        path = reference_dir / file_name
        payload = load_json(path)
        entries = as_entries(payload)
        source_summaries[file_name] = {
            "entries": len(entries),
            "unique_category": len({str(item.get("category") or "").strip() for item in entries if item.get("category")}),
            "unique_title": len({str(item.get("title") or "").strip() for item in entries if item.get("title")}),
            "unique_topic_category": len(
                {str(item.get("topic_category") or "").strip() for item in entries if item.get("topic_category")}
            ),
        }
        candidate_counter.update(collect_candidate_terms(entries))

    approved_names = {node.name for node in approved_nodes}
    approved_aliases = {alias for node in approved_nodes for alias in node.aliases}
    reference_review_queue = [
        {
            "term": term,
            "frequency": count,
            "reason": review_reason(term, approved_names, approved_aliases),
        }
        for term, count in candidate_counter.most_common()
        if review_reason(term, approved_names, approved_aliases) != "already_covered_by_approved_graph"
    ]
    review_queue = [
        *(
            {
                "term": str(item.get("term") or ""),
                "frequency": 1,
                "reason": str(item.get("reason") or "school_node_review"),
                "source_file": str(item.get("source_file") or ""),
            }
            for item in school_review_queue
        ),
        *(
            {
                "term": str(item.get("term") or ""),
                "frequency": 1,
                "reason": str(item.get("reason") or "gaosi_node_review"),
                "source_file": str(item.get("source_file") or ""),
            }
            for item in gaosi_review_queue
        ),
        *reference_review_queue,
    ]

    return {
        "graph_version": graph.version,
        "approved_node_count": len(approved_nodes),
        "generated_school_node_count": generated_school_count,
        "generated_gaosi_node_count": generated_gaosi_count,
        "validation_errors": validation_errors,
        "source_summaries": source_summaries,
        "review_queue_count": len(review_queue),
        "review_queue": review_queue[:SCHOOL_REVIEW_LIMIT],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", type=Path, default=DIM5_GRAPH_PATH)
    parser.add_argument(
        "--reference-dir",
        type=Path,
        default=ROOT / "app" / "services" / "parser",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data" / "dim5_knowledge_graph",
    )
    args = parser.parse_args()

    base_payload = load_json(args.graph)
    base_nodes = [
        node
        for node in base_payload.get("nodes") or []
        if isinstance(node, dict)
        and not str(node.get("knowledge_point_id") or "").startswith(f"{SCHOOL_NODE_PREFIX}.")
        and not str(node.get("knowledge_point_id") or "").startswith(f"{GAOSI_NODE_PREFIX}.")
    ]
    school_nodes, school_review_queue = build_school_nodes(args.reference_dir, base_nodes)
    gaosi_nodes, gaosi_review_queue = build_gaosi_nodes(args.reference_dir, [*base_nodes, *school_nodes])
    payload = {
        "version": str(base_payload.get("version") or "dim5_knowledge_graph_v1"),
        "nodes": [*base_nodes, *school_nodes, *gaosi_nodes],
    }
    args.graph.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    graph = Dim5KnowledgeGraph.load(args.graph)
    report = build_report(
        graph,
        args.reference_dir,
        generated_school_count=len(school_nodes),
        generated_gaosi_count=len(gaosi_nodes),
        school_review_queue=school_review_queue,
        gaosi_review_queue=gaosi_review_queue,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "dim5_knowledge_graph.approved.json").write_text(
        args.graph.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (args.output_dir / "dim5_knowledge_graph.build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.output_dir / "dim5_knowledge_graph.review_queue.json").write_text(
        json.dumps(report["review_queue"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"approved={report['approved_node_count']} school_generated={report['generated_school_node_count']} "
        f"gaosi_generated={report['generated_gaosi_node_count']} "
        f"review_queue={report['review_queue_count']} "
        f"errors={len(report['validation_errors'])}"
    )
    return 1 if report["validation_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
