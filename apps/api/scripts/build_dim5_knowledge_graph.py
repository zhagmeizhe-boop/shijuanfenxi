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
    build_dim5_rule_localization_report,
    localize_dim5_graph_payload,
)


REFERENCE_FILES = (
    "reference_standard_data.json",
    "reference_standard_gaosi_question_data.json",
    "reference_standard_gaosi_pdf_data.json",
    "reference_standard_school_pdf_data.json",
)
GAOSI_KNOWLEDGE_TREE_FILE = "gaosi_knowledge_tree_2024.json"

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
RETIRED_BASE_NODE_IDS = {
    "dim5.pattern_sequence.number_table_position",
    "dim5.pattern_sequence.staircase_recurrence_xsc",
}
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
    ("division_quotient_digit_zero", ("商是三位数", "商的最高位", "商末尾有0", "商末尾有 0", "□里最小填", "□里最大填")),
    ("school_one_digit_divisor", ("除数是一位数", "除以一位数", "一位数除")),
    ("school_division", ("除法", "除数", "被除数", "商", "余数", "除以", "平均分")),
    ("school_zero_operation", ("0的运算", "有关0", "中间有0", "末尾有0")),
    ("school_mixed_operation", ("混合运算", "四则运算", "运算顺序", "脱式", "递等式")),
    ("school_parentheses_order", ("括号", "小括号", "中括号", "先算")),
    ("school_24_point_mixed_operation", ("24点", "结果等于24", "结果为24")),
    ("school_operation_law", ("结合律", "交换律", "分配律", "运算定律", "简便运算")),
    ("school_addition_subtraction", ("加法", "减法", "加减", "加、减")),
    ("school_multiplication", ("乘法", "乘以", "多位数乘", "两位数乘")),
    ("school_fraction", ("分数", "几分之", "真分数", "假分数", "带分数", "通分", "约分")),
    ("school_reciprocal_concept", ("倒数", "互为倒数", "乘积为1")),
    ("school_decimal", ("小数", "小数点", "十分位", "百分位")),
    ("school_equation", ("方程", "未知数", "解方程")),
    ("school_symbol_equation_substitution", ("代表一个数", "各代表", "等量代换", "代入消元", "△", "□")),
    ("school_division_representation", ("计算方法", "点阵图", "算盘图", "数的分解", "分解计算", "多种方法")),
    ("school_comparison", ("比较大小", "填上", "大于", "小于", "等于")),
    ("school_multiplicative_relation", ("倍数关系", "几倍", "扩大到", "缩小到")),
    ("perimeter_scale_relation", ("周长扩大", "边长扩大", "周长缩小", "边长缩小", "周长倍数")),
    ("school_translation", ("平移", "火箭升空", "电梯", "升降", "直线运动")),
    ("school_rotation", ("旋转", "荡秋千", "风车", "转动", "钟摆", "车轮", "开关门")),
    ("school_geometry_motion", ("运动现象", "图形的运动", "物体运动", "平移", "旋转", "火箭升空", "荡秋千")),
    ("school_axisymmetry", ("轴对称", "对称轴", "对称图形")),
    ("school_irregular_perimeter", ("不规则图形", "平移法", "多边形", "组合图形")),
    ("folded_perimeter_change", ("对折", "折叠后的周长", "周长减少", "再对折")),
    ("polygon_perimeter", ("五边形", "阶梯形", "多边形周长", "边长分别")),
    ("rectangle_tiling_min_perimeter", ("贴在一起", "做成长方形", "四周贴装饰条", "装饰条最少")),
    ("school_rectangle_square", ("长方形", "正方形", "长和宽", "边长")),
    ("school_perimeter", ("周长", "围一圈", "边长之和")),
    ("school_square_tiling_perimeter", ("小正方形", "拼成", "拼接", "共边", "周长最小", "周长最大")),
    ("school_rectangle_property", ("围成一个长方形", "围成长方形", "表示点", "点的位置", "长方形的性质")),
    ("triangle_angle_classification", ("三角形三个角", "度数的比", "角的比", "锐角三角形", "直角三角形", "钝角三角形")),
    ("school_cube_net", ("正方体展开图", "正方体的展开图", "展开图", "折叠", "对面", "相邻面")),
    ("school_area", ("面积", "平方厘米", "平方米", "平方分米")),
    ("school_volume", ("体积", "容积", "立方厘米", "立方米", "长方体", "正方体", "圆柱", "圆锥")),
    ("cylinder_cone_volume_height_ratio", ("底面积相等", "体积比", "高的比", "圆柱和圆锥高的比")),
    ("cylinder_cone_volume_ratio", ("高相同", "底面半径之比", "圆柱与圆锥", "体积比")),
    ("composite_area_split_relation", ("长方形被", "分成两个长方形", "宽的比", "阴影三角形面积", "原长方形面积")),
    ("rectangle_area_fraction_percent_change", ("长增加", "宽减少", "面积是原来的", "分数和百分数的综合应用")),
    ("signed_number_context", ("正负数", "记作", "基准数", "平均体重")),
    ("triangle_side_validity", ("围成三角形", "组成三角形", "三边关系", "小棒")),
    ("number_fraction_percent_comparison", ("小数、分数、百分数", "比较大小", "从小到大", "最大的数")),
    ("percent_rate_application", ("百分率", "出勤率", "合格率", "出油率")),
    ("school_ratio_context_choice", ("情境中的比", "比的意义", "可以用比表示")),
    ("graphic_sequence_pattern", ("图形规律", "小棒", "纽扣", "棋子按照一定规律")),
    ("submerged_volume_water_rise", ("浸没", "水面上升", "水未溢出", "容积")),
    ("parallel_line_area_comparison", ("平行线之间", "平行四边形梯形三角形面积")),
    ("repeated_percent_change", ("两次价格调整", "下降幅度", "连续增减")),
    ("fraction_unit_one_relation", ("单位1", "比一个数多", "比一个数少", "分率")),
    ("rotation_solid_volume", ("旋转体体积", "旋转一周", "以直线为轴")),
    ("parallel_triangle_area_relation", ("平行四边形和三角形", "等底等高")),
    ("probability_fair_game", ("游戏公平性", "摸球游戏", "摸后放回")),
    ("fraction_ratio_distribution", ("分数乘法", "按比分配", "余下按照")),
    ("cylinder_surface_area_practical", ("底面和四周", "抹水泥", "圆柱形水池")),
    ("divisibility_digit_construction", ("2、3、5的倍数", "选出三个数字", "写出三位数")),
    ("fraction_remaining_after_cuts", ("第一次剪去", "第二次剪去", "还剩下")),
    ("cylinder_cone_composite_volume", ("圆柱和圆锥组成", "组合图形的体积")),
    ("circle_cut_rectangle_area", ("圆平均分成", "拼成近似长方形")),
    ("school_fraction_equation_ratio", ("解方程", "解比例", "比例的基本性质")),
    ("school_circle_circumference_area_ring", ("圆的周长", "圆的面积", "环形面积")),
    ("school_composite_perimeter_area", ("组合图形周长面积", "图形计算", "涂色部分")),
    ("fan_chart_application", ("扇形统计图", "统计图和统计表")),
    ("cylinder_surface_volume_composite", ("圆柱表面积与体积", "表面积与体积综合", "装饰部分", "酒水高度")),
    ("school_statistics", ("统计图", "统计表", "平均数", "条形统计图", "折线统计图", "扇形统计图")),
    ("statistics_chart_context", ("统计图", "统计表", "条形统计图", "折线统计图", "扇形统计图", "圆心角")),
    ("statistics_percent_conversion", ("百分比", "百分数", "占比", "圆心角", "人数换算")),
    ("school_probability", ("可能性", "一定", "不可能", "随机")),
    ("school_prime_factorization", ("分解质因数", "质因数分解", "质因数")),
    ("fraction_application", ("分数应用题", "几分之", "还剩", "总数")),
    ("fraction_whole_part_relation", ("整体与部分", "其中", "分数应用题", "不经常", "经常")),
    ("proportion_application", ("比例分配", "按比例", "之比", "比是")),
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
    ("defined_operation_rule", ("定义新运算", "新定义运算", "规定一种运算", "一种运算")),
    ("defined_operation_symbol", ("※", "△", "☆", "◇", "新运算符号")),
    ("defined_operation_target", ("应填", "求出", "代入", "反求")),
    ("consecutive_product_definition", ("连续三数乘积", "连续整数乘积")),
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
    ("gaosi_reverse_age", ("还原", "倒推", "年龄", "岁")),
    ("gaosi_average", ("平均数", "平均")),
    ("gaosi_work_rate", ("工程", "合作", "单独", "共同完成", "工作效率", "总工程量", "剩余工程")),
    ("work_progress_ratio", ("已完成", "未完成", "剩余工程", "完成量比例")),
    ("gaosi_grazing_clock", ("牛吃草", "钟表", "时针", "分针", "草")),
    ("gaosi_travel", ("行程", "速度", "路程", "相遇", "追及", "流水")),
    ("gaosi_concentration_profit", ("浓度", "盐水", "溶液", "经济", "利润", "折扣", "进价", "售价")),
    ("gaosi_ratio", ("比例", "正比例", "反比例", "之比", "比是")),
    ("gaosi_geometry_basic", ("几何图形", "长度", "角度", "直线形", "图形认知")),
    ("gaosi_cut_paste", ("剪拼", "割补", "格点", "面积", "等积", "蝴蝶", "燕尾")),
    ("area_decomposition", ("图形割补", "面积分解", "组合图形", "阴影部分")),
    ("overall_area_method", ("整体法", "整体转化", "整体割补")),
    ("rotation_area_transform", ("旋转割补", "旋转求阴影面积", "旋转阴影面积")),
    ("butterfly_area_model", ("蝴蝶模型", "对角线相交", "面积比例")),
    ("gaosi_lattice", ("格点", "方格", "网格", "点阵")),
    ("gaosi_circle_sector", ("圆", "扇形", "半径", "直径", "圆心角")),
    ("gaosi_solid_geometry", ("立体", "正方体", "长方体", "圆柱", "圆锥", "表面积", "体积")),
    ("gaosi_sequence", ("周期", "规律", "数列", "数表", "等差", "找规律")),
    ("number_table_position_pattern", ("数表", "下表规律", "排成5列", "第几行", "第几列")),
    ("equal_area_sandglass", ("沙漏", "两个正方形", "大小正方形")),
    ("work_split_collaboration", ("来回帮忙", "中途帮助", "两个仓库", "分段合作")),
    ("staircase_recurrence", ("爬楼梯", "台阶走法", "一级或两级", "1级、2级、3级")),
    ("new_operation_conditional", ("条件判断型", "如果", "奇数", "偶数")),
    ("travel_inverse_speed_time", ("速度和时间成反比", "速度比", "返回速度")),
    ("trapezoid_auxiliary_area", ("梯形模型", "三等分点", "辅助线")),
    ("geometric_series_area_sum", ("等比数列求和", "后一个", "图形n的面积")),
    ("tree_diagram_queue_counting", ("树形图排队", "不能放在第一", "不同的放法")),
    ("cuboid_coloring", ("长方体染色", "刷漆", "未刷漆")),
    ("downstream_upstream_current", ("顺水", "逆水", "水速", "漂流")),
    ("partial_submerged_water_rise", ("不完全浸没", "竖直放入", "水面会上升")),
    ("slicing_volume_method", ("切片法", "挖空", "剩下部分的体积")),
    ("floor_function_operation", ("整数部分", "取整", "不大于")),
    ("cross_concentration_mix", ("十字交叉", "纯酒精含量", "混合后")),
    ("hidden_distance_meeting", ("隐藏路程差", "一半还多", "相遇")),
    ("round_robin_counting", ("循环赛", "单循环比赛", "比赛场次")),
    ("railway_ticket_counting", ("车票计数", "新增车站", "往返车票")),
    ("magic_square_relation", ("三阶幻方", "幻方", "数阵")),
    ("list_ratio_analysis", ("列表分析", "三个班", "男女生人数比")),
    ("vertical_multiplication_digit_analysis", ("乘法竖式", "位数分析", "数字被盖住")),
    ("remainder_system_conditions", ("多个余数条件", "被7除余", "被8除余")),
    ("complex_circle_overlap_area", ("复杂重叠", "两两相切", "圆和半圆")),
    ("gaosi_interval_array", ("间隔", "阵列", "植树", "队列")),
    ("gaosi_magic_square", ("幻方", "数阵", "数阵图")),
    ("gaosi_logic", ("逻辑", "推理", "真假", "条件", "智巧")),
    ("condition_enumeration", ("条件枚举", "分类枚举", "都不一样", "仅有一个")),
    ("integer_split", ("整数拆分", "正整数拆分", "每个至少", "每国至少")),
    ("binary_search_strategy", ("二分", "二分策略", "折半查找", "阀门排查")),
    ("information_search_strategy", ("信息查找", "排查", "测试反馈", "确定目标")),
    ("gaosi_optimization", ("统筹", "对策", "最值", "最多", "最少", "最大", "最小", "最优")),
    ("gaosi_construction", ("构造", "论证", "证明", "存在", "任意")),
    ("gaosi_probability", ("概率", "可能性", "随机")),
    ("two_type_cost_total", ("总价", "总费用", "停车费", "每辆", "每件", "两类对象")),
    ("square_difference_odd", ("连续奇数", "平方差", "平方数差")),
    ("digit_swap_multiple", ("数位交换", "交换数字", "交换数位", "成倍数")),
    ("repeated_digit_number", ("重复数字", "各位数字相同")),
    ("integer_solution_factorization", ("整数解", "约数枚举", "因数分解", "不定方程")),
    ("fold_cut_unfold", ("折叠展开", "剪纸", "剪开", "展开后")),
    ("geometry_transform_puzzle", ("俄罗斯方块", "平移旋转", "旋转平移", "图形变换")),
    ("overlap_area", ("重叠面积", "重叠部分", "公共部分")),
    ("area_ratio_relation", ("面积比", "面积之比", "等高", "共边")),
    ("tangram_area", ("七巧板", "七巧板面积")),
    ("zhao_shuang_diagram", ("赵爽弦图", "弦图")),
    ("reuleaux_triangle", ("勒洛三角形", "弓形")),
    ("cylinder_surface_volume", ("圆柱侧面展开", "圆柱", "表面积", "体积")),
    ("periodic_grid", ("周期格子", "周期", "方格", "数表")),
    ("state_recurrence", ("传数游戏", "状态转移", "递推", "还原问题")),
    ("line_plane_recurrence", ("直线分平面", "分成最多")),
    ("transport_optimization", ("运输费用", "运费", "费用最小", "运输最优")),
)
GAOSI_KNOWLEDGE_TREE_TITLE_ALIASES = {
    "几何图形认识": "几何图形的认知",
    "抽屉原理一": "抽屉原理",
    "计算综合": "计算综合二",
}
GAOSI_TREE_GENERIC_SUBTOPICS = {
    "综合问题",
    "综合题",
    "基础题型",
    "基础应用题",
    "基本公式",
    "公式应用",
    "基本公式应用",
    "其它计数",
    "综合",
    "基础",
    "基本",
    "公式",
    "展开图",
    "综合题型",
    "数字",
    "计算",
    "面积",
    "求面积",
    "面积计算",
    "圆",
    "三角形",
    "倍数",
}
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
        "knowledge_point_id": "dim5.school.3.perimeter_scale_relation",
        "name": "长方形和正方形周长 / 周长倍数关系",
        "domain": "geometry_spatial",
        "level": "L1",
        "grade": "3",
        "semester": "上册",
        "aliases": ["周长倍数关系", "边长扩大周长扩大", "长方形和正方形周长", "周长"],
        "required_fact_groups": [["school_perimeter"], ["school_rectangle_square"], ["perimeter_scale_relation"]],
        "source_refs": ["curated:midterm_grade3:q4:perimeter_scale_relation"],
    },
    {
        "knowledge_point_id": "dim5.school.3.folded_perimeter_change",
        "name": "长方形和正方形周长 / 折叠后的周长变化",
        "domain": "geometry_spatial",
        "level": "L1",
        "grade": "3",
        "semester": "上册",
        "aliases": ["折叠后的周长变化", "对折周长变化", "周长减少", "长方形和正方形周长", "周长"],
        "required_fact_groups": [["school_perimeter"], ["school_rectangle_square"], ["folded_perimeter_change"]],
        "source_refs": ["curated:midterm_grade3:q10:folded_perimeter_change"],
    },
    {
        "knowledge_point_id": "dim5.school.3.polygon_irregular_perimeter",
        "name": "多边形周长计算 / 不规则图形周长",
        "domain": "geometry_spatial",
        "level": "L1",
        "grade": "3",
        "semester": "上册",
        "aliases": ["多边形周长", "阶梯形周长", "五边形周长", "不规则图形周长", "周长"],
        "required_fact_groups": [["school_perimeter"], ["polygon_perimeter"]],
        "source_refs": ["curated:midterm_grade3:q20:polygon_irregular_perimeter"],
    },
    {
        "knowledge_point_id": "dim5.school.3.rectangle_tiling_min_perimeter",
        "name": "长方形和正方形周长 / 拼接图形周长最小化",
        "domain": "geometry_spatial",
        "level": "L1",
        "grade": "3",
        "semester": "上册",
        "aliases": ["拼接图形周长最小化", "装饰条最少", "正方形拼成长方形", "周长最小", "长方形和正方形周长"],
        "required_fact_groups": [["school_perimeter"], ["school_rectangle_square"], ["school_square_tiling_perimeter"], ["rectangle_tiling_min_perimeter"]],
        "source_refs": ["curated:midterm_grade3:q25:rectangle_tiling_min_perimeter"],
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
        "knowledge_point_id": "dim5.school.3.one_digit_division_quotient_digit_zero",
        "name": "除数是一位数的竖式计算 / 商的位数与末尾0判断",
        "domain": "number_operation",
        "level": "L1",
        "grade": "3",
        "semester": "下册",
        "aliases": ["商的位数与末尾0判断", "商是三位数", "商末尾有0", "除数是一位数的竖式计算"],
        "required_fact_groups": [["school_division"], ["school_quotient_digit"], ["division_quotient_digit_zero"]],
        "source_refs": ["curated:midterm_grade3:q5:quotient_digit_zero"],
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
    {
        "knowledge_point_id": "dim5.school.6.0db25e6f601c",
        "name": "倒数",
        "domain": "number_operation",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["倒数的认识", "互为倒数", "乘积为1", "一个数的倒数"],
        "required_fact_groups": [["school_reciprocal_concept"]],
        "source_refs": ["school_reference:reference_standard_data.json:六年级上册:倒数"],
    },
    {
        "knowledge_point_id": "dim5.school.6.fraction_whole_part_relation",
        "name": "分数应用题 / 整体与部分关系",
        "domain": "quantity_application",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["分数应用题", "整体与部分关系", "分数整体部分关系", "已知总量求部分"],
        "required_fact_groups": [["fraction_application"], ["fraction_whole_part_relation"]],
        "source_refs": ["curated:wmo_2026:q1:fraction_whole_part_relation"],
    },
    {
        "knowledge_point_id": "dim5.school.6.cylinder_surface_volume_composite",
        "name": "圆柱表面积与体积综合",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "6",
        "semester": "下册",
        "aliases": ["圆柱表面积与体积综合", "圆柱表面积", "圆柱体积", "圆柱容积"],
        "required_fact_groups": [["cylinder_surface_volume"], ["cylinder_surface_volume_composite"]],
        "source_refs": ["curated:wmo_2026:q17:cylinder_surface_volume_composite"],
    },
    {
        "knowledge_point_id": "dim5.school.4.triangle_angle_classification",
        "name": "三角形的分类 / 按角判断三角形",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "4",
        "semester": "下册",
        "aliases": ["三角形分类", "按角判断三角形", "锐角三角形", "直角三角形", "钝角三角形", "等腰三角形"],
        "required_fact_groups": [["geometry_triangle"], ["triangle_angle_classification"]],
        "source_refs": ["curated:guangzhou_liuzhong_426c:q11:triangle_angle_classification"],
    },
    {
        "knowledge_point_id": "dim5.school.6.cylinder_cone_volume_height_ratio",
        "name": "圆柱圆锥 / 等底面积下体积与高的关系",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "6",
        "semester": "下册",
        "aliases": ["圆柱圆锥体积高关系", "等底面积体积高关系", "圆柱和圆锥高的比", "底面积相等体积比"],
        "required_fact_groups": [["school_volume"], ["cylinder_cone_volume_height_ratio"]],
        "source_refs": ["curated:guangzhou_liuzhong_426c:q17:cylinder_cone_volume_height_ratio"],
    },
    {
        "knowledge_point_id": "dim5.school.5.composite_area_split_shadow",
        "name": "组合图形的面积 / 分割与阴影面积",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "5",
        "semester": "上册",
        "aliases": ["组合图形面积", "分割与阴影面积", "长方形分割面积", "阴影三角形面积", "原长方形面积"],
        "required_fact_groups": [["school_area"], ["composite_area_split_relation"]],
        "source_refs": ["curated:guangzhou_liuzhong_426c:q25:composite_area_split_relation"],
    },
    {
        "knowledge_point_id": "dim5.school.6.cylinder_cone_volume_ratio",
        "name": "圆柱与圆锥的体积比问题",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "6",
        "semester": "下册",
        "aliases": ["圆柱圆锥体积比", "圆柱与圆锥体积比", "同高圆柱圆锥体积比", "底面半径之比"],
        "required_fact_groups": [["school_volume"], ["cylinder_cone_volume_ratio"]],
        "source_refs": ["curated:guangda_fuzhong_autumn:q1_5:cylinder_cone_volume_ratio"],
    },
    {
        "knowledge_point_id": "dim5.school.6.rectangle_area_fraction_percent_change",
        "name": "分数百分数综合应用 / 长方形面积变化",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["长方形面积变化", "分数百分数综合应用", "长宽增减面积变化", "面积是原来的百分之几"],
        "required_fact_groups": [["school_area"], ["rectangle_area_fraction_percent_change"]],
        "source_refs": ["curated:guangda_fuzhong_autumn:q1_7:rectangle_area_fraction_percent_change"],
    },
    {
        "knowledge_point_id": "dim5.school.5.dc1d0c416fbb",
        "name": "正方体展开图",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "5",
        "semester": "下册",
        "aliases": ["正方体的展开图", "立体图形展开图", "折叠成正方体", "不是正方体展开图", "正方形的展开图"],
        "required_fact_groups": [["school_cube_net"]],
        "source_refs": ["school_reference:reference_standard_data.json:五年级下册:长方体和正方体:正方体展开图"],
    },
    {
        "knowledge_point_id": "dim5.school.4.36e8a8c30422",
        "name": "24点游戏与四则混合运算",
        "domain": "number_operation",
        "level": "L2",
        "grade": "4",
        "semester": "下册",
        "aliases": ["24点游戏", "结果等于24", "结果为24", "四则混合运算", "括号"],
        "required_fact_groups": [["school_24_point_mixed_operation"]],
        "source_refs": ["school_reference:reference_standard_data.json:四年级下册:四则运算:24点游戏"],
    },
    {
        "knowledge_point_id": "dim5.school.5.symbol_equation_substitution",
        "name": "等量代换与简易方程",
        "domain": "number_operation",
        "level": "L2",
        "grade": "5",
        "semester": "上册",
        "aliases": ["等量代换", "简易方程", "代入消元", "符号代表数", "△和□代表数"],
        "required_fact_groups": [["school_symbol_equation_substitution"]],
        "source_refs": ["school_reference:reference_standard_data.json:五年级上册:简易方程:等量关系"],
    },
    {
        "knowledge_point_id": "dim5.school.5.prime_factorization",
        "name": "质因数分解",
        "domain": "number_theory",
        "level": "L2",
        "grade": "5",
        "semester": "下册",
        "aliases": ["分解质因数", "质因数", "短除法", "所有质因数"],
        "required_fact_groups": [["school_prime_factorization"]],
        "source_refs": ["school_reference:reference_standard_data.json:五年级下册:因数与倍数:质因数分解"],
    },
    {
        "knowledge_point_id": "dim5.school.6.signed_number_context",
        "name": "负数的认识 / 用正负数表示生活中的量",
        "domain": "number_operation",
        "level": "L2",
        "grade": "6",
        "semester": "下册",
        "aliases": ["正负数表示生活中的量", "基准数非0", "记作正负数", "平均值作基准"],
        "required_fact_groups": [["signed_number_context"]],
        "source_refs": ["curated:xsc_school:q1:signed_number_context"],
    },
    {
        "knowledge_point_id": "dim5.school.4.triangle_side_validity",
        "name": "三角形三边关系 / 判断能否组成三角形",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "4",
        "semester": "下册",
        "aliases": ["三角形三边关系", "判断组成三角形的三条线长度", "小棒围三角形"],
        "required_fact_groups": [["triangle_side_validity"]],
        "source_refs": ["curated:xsc_school:q2:triangle_side_validity"],
    },
    {
        "knowledge_point_id": "dim5.school.6.number_fraction_percent_comparison",
        "name": "小数、分数、百分数的比较大小",
        "domain": "number_operation",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["分小百比较大小", "小数百分数比较大小", "从小到大排列", "最大的数"],
        "required_fact_groups": [["number_fraction_percent_comparison"]],
        "source_refs": ["curated:xsc_school:q3:number_fraction_percent_comparison", "curated:xsc_placement:q6:number_fraction_percent_comparison"],
    },
    {
        "knowledge_point_id": "dim5.school.6.percent_rate_application",
        "name": "百分数应用 / 常见百分率",
        "domain": "quantity_application",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["常见百分率", "百分率实际应用", "出勤率", "合格率", "出油率"],
        "required_fact_groups": [["percent_rate_application"]],
        "source_refs": ["curated:xsc_school:q4:percent_rate_application"],
    },
    {
        "knowledge_point_id": "dim5.school.6.ratio_context_choice",
        "name": "比的意义与实际情境",
        "domain": "quantity_application",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["情境中的比", "与比相关的综合题", "比的意义", "用比表示"],
        "required_fact_groups": [["school_ratio_context_choice"]],
        "source_refs": ["curated:xsc_school:q5:ratio_context_choice"],
    },
    {
        "knowledge_point_id": "dim5.school.5.graphic_sequence_letter_pattern",
        "name": "用字母表示数 / 图形规律",
        "domain": "pattern_sequence",
        "level": "L2",
        "grade": "5",
        "semester": "上册",
        "aliases": ["用字母表示图形规律", "小棒纽扣图形规律", "棋子图形规律", "图形规律"],
        "required_fact_groups": [["graphic_sequence_pattern"]],
        "source_refs": ["curated:xsc_school:q6:graphic_sequence_pattern", "curated:xsc_placement:q5:graphic_sequence_pattern"],
    },
    {
        "knowledge_point_id": "dim5.school.6.submerged_water_rise",
        "name": "长正方体体积与容积 / 浸没水面上升",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "6",
        "semester": "下册",
        "aliases": ["浸没水面上升", "物体完全浸没无水溢出", "水面上升高度", "体积容积说理"],
        "required_fact_groups": [["submerged_volume_water_rise"]],
        "source_refs": ["curated:xsc_school:q7:submerged_volume_water_rise", "curated:xsc_thinking:q5:submerged_volume_water_rise", "curated:xsc_school:q23:solid_volume_reasoning"],
    },
    {
        "knowledge_point_id": "dim5.school.6.repeated_percent_change",
        "name": "百分数应用 / 连续增减变化",
        "domain": "quantity_application",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["连续百分数变化", "两次价格调整", "下降幅度比较", "增减变化幅度"],
        "required_fact_groups": [["repeated_percent_change"]],
        "source_refs": ["curated:xsc_school:q8:repeated_percent_change"],
    },
    {
        "knowledge_point_id": "dim5.school.6.fraction_unit_one_relation",
        "name": "分数应用题 / 单位1判断",
        "domain": "quantity_application",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["单位1判断", "已知比一个数多的分率", "已知比一个数少的分率", "求单位1"],
        "required_fact_groups": [["fraction_unit_one_relation"]],
        "source_refs": ["curated:xsc_school:q9:fraction_unit_one_relation"],
    },
    {
        "knowledge_point_id": "dim5.school.6.rotation_solid_volume",
        "name": "旋转体体积 / 面积比与体积比",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "6",
        "semester": "下册",
        "aliases": ["复杂图形的旋转体体积", "正方形旋转体体积比", "以直线为轴旋转一周"],
        "required_fact_groups": [["rotation_solid_volume"]],
        "source_refs": ["curated:xsc_school:q10:rotation_solid_volume"],
    },
    {
        "knowledge_point_id": "dim5.school.5.parallel_triangle_area_relation",
        "name": "平行四边形和三角形面积关系",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "5",
        "semester": "上册",
        "aliases": ["等底等高三角形面积", "三角形和平行四边形的关系", "平行四边形面积"],
        "required_fact_groups": [["parallel_triangle_area_relation"]],
        "source_refs": ["curated:xsc_school:q11:parallel_triangle_area_relation"],
    },
    {
        "knowledge_point_id": "dim5.school.5.probability_fair_game",
        "name": "可能性 / 游戏规则公平性",
        "domain": "statistics_probability",
        "level": "L2",
        "grade": "5",
        "semester": "上册",
        "aliases": ["游戏规则的公平性判断", "摸球游戏公平性", "可能性公平"],
        "required_fact_groups": [["probability_fair_game"]],
        "source_refs": ["curated:xsc_school:q12:probability_fair_game"],
    },
    {
        "knowledge_point_id": "dim5.school.6.fraction_ratio_distribution",
        "name": "分数乘法与按比分配综合",
        "domain": "quantity_application",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["分数乘法后按比分配", "求出和后再按比分配", "余下按照比例分配"],
        "required_fact_groups": [["fraction_ratio_distribution"]],
        "source_refs": ["curated:xsc_school:q13:fraction_ratio_distribution"],
    },
    {
        "knowledge_point_id": "dim5.school.6.cylinder_surface_area_practical",
        "name": "圆柱表面积 / 实际涂抹面积",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "6",
        "semester": "下册",
        "aliases": ["圆柱实际表面积", "底面和四周抹水泥", "确定计算哪些面的面积"],
        "required_fact_groups": [["cylinder_surface_area_practical"]],
        "source_refs": ["curated:xsc_school:q14:cylinder_surface_area_practical"],
    },
    {
        "knowledge_point_id": "dim5.school.5.divisibility_digit_construction",
        "name": "2、3、5倍数特征 / 组数",
        "domain": "number_theory",
        "level": "L2",
        "grade": "5",
        "semester": "下册",
        "aliases": ["2、3、5的倍数特征", "组成符合条件的三位数", "有因数3", "有因数5"],
        "required_fact_groups": [["divisibility_digit_construction"]],
        "source_refs": ["curated:xsc_school:q15:divisibility_digit_construction"],
    },
    {
        "knowledge_point_id": "dim5.school.6.fraction_remaining_after_cuts",
        "name": "分数乘法应用 / 连续求剩余",
        "domain": "quantity_application",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["分数乘法综合题", "连续剪去求剩余", "第一次剪去第二次剪去"],
        "required_fact_groups": [["fraction_remaining_after_cuts"]],
        "source_refs": ["curated:xsc_school:q16:fraction_remaining_after_cuts"],
    },
    {
        "knowledge_point_id": "dim5.school.6.cylinder_cone_composite_volume",
        "name": "圆柱圆锥 / 组合图形体积",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "6",
        "semester": "下册",
        "aliases": ["圆柱圆锥组合体积", "组合图形的体积计算", "圆锥和圆柱组成"],
        "required_fact_groups": [["cylinder_cone_composite_volume"]],
        "source_refs": ["curated:xsc_school:q17:cylinder_cone_composite_volume"],
    },
    {
        "knowledge_point_id": "dim5.school.6.circle_cut_rectangle_area",
        "name": "圆的周长和面积 / 圆拼成长方形",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["圆拼成长方形", "已知近似长方形求圆面积", "圆平均分成若干份"],
        "required_fact_groups": [["circle_cut_rectangle_area"]],
        "source_refs": ["curated:xsc_school:q18:circle_cut_rectangle_area"],
    },
    {
        "knowledge_point_id": "dim5.school.6.fraction_equation_ratio",
        "name": "方程与解比例 / 分小百方程",
        "domain": "number_operation",
        "level": "L2",
        "grade": "6",
        "semester": "下册",
        "aliases": ["多步计算的分数方程", "依据比例的基本性质解比例", "解稍复杂方程", "解方程"],
        "required_fact_groups": [["school_fraction_equation_ratio"]],
        "source_refs": ["curated:xsc_school:q21:school_fraction_equation_ratio"],
    },
    {
        "knowledge_point_id": "dim5.school.6.circle_circumference_area_ring",
        "name": "圆的周长、面积与环形面积",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["圆周长面积环形面积", "圆形喷泉池", "防护栏", "小路面积"],
        "required_fact_groups": [["school_circle_circumference_area_ring"]],
        "source_refs": ["curated:xsc_school:q22:school_circle_circumference_area_ring"],
    },
    {
        "knowledge_point_id": "dim5.school.5.composite_perimeter_area",
        "name": "组合图形的周长和面积",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "5",
        "semester": "上册",
        "aliases": ["组合图形周长面积", "不规则图形周长面积", "涂色部分周长和面积", "分割法求组合图形面积"],
        "required_fact_groups": [["school_composite_perimeter_area"]],
        "source_refs": ["curated:xsc_school:q24:school_composite_perimeter_area"],
    },
    {
        "knowledge_point_id": "dim5.school.5.parallel_line_area_comparison",
        "name": "平行线间图形面积比较",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "5",
        "semester": "上册",
        "aliases": ["夹在两条平行线之间的面积比较", "平行四边形三角形梯形面积比较", "等底等高面积比较"],
        "required_fact_groups": [["parallel_line_area_comparison"]],
        "source_refs": ["curated:xsc_placement:q1:parallel_line_area_comparison"],
    },
    {
        "knowledge_point_id": "dim5.school.6.fan_chart_application",
        "name": "扇形统计图应用",
        "domain": "statistics_probability",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["运用扇形统计图解决问题", "统计图和统计表", "百分比人数换算"],
        "required_fact_groups": [["fan_chart_application"]],
        "source_refs": ["curated:xsc_school:q25:fan_chart_application"],
    },
    {
        "knowledge_point_id": "dim5.school.6.cone_package_surface",
        "name": "圆锥体积与长方体包装表面积",
        "domain": "geometry_spatial",
        "level": "L2",
        "grade": "6",
        "semester": "下册",
        "aliases": ["圆柱与圆锥综合题基础", "圆锥玩具体积", "长方体纸盒包装", "纸板面积"],
        "required_fact_groups": [["school_cone_package_surface"]],
        "source_refs": ["curated:xsc_placement:q24:school_cone_package_surface"],
    },
    {
        "knowledge_point_id": "dim5.school.6.fraction_mixed_calculation",
        "name": "分数四则混合运算",
        "domain": "number_operation",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["分数四则混合运算", "分小百混合运算", "脱式计算", "含百分数四则混合运算"],
        "required_fact_groups": [["school_fraction_mixed_calculation"]],
        "source_refs": ["curated:xsc_calculation:fraction_mixed_calculation"],
    },
    {
        "knowledge_point_id": "dim5.school.6.clever_factor_calculation",
        "name": "简便计算 / 提公因数巧算",
        "domain": "number_operation",
        "level": "L2",
        "grade": "6",
        "semester": "上册",
        "aliases": ["提公因数巧算", "整体约分", "分拆构造公因数", "能简算"],
        "required_fact_groups": [["school_clever_factor_calculation"]],
        "source_refs": ["curated:xsc_calculation:clever_factor_calculation"],
    },
)


CURATED_BASE_TOPICS: tuple[Dict[str, Any], ...] = (
    {
        "knowledge_point_id": "dim5.counting_combinatorics.condition_enumeration_integer_split",
        "name": "条件枚举 / 整数拆分",
        "domain": "counting_combinatorics",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "3",
        "knowledge_grade_label": "三年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数三年级：条件枚举 / 整数拆分",
        "aliases": ["条件枚举", "整数拆分", "分类枚举", "互不相同正整数"],
        "required_fact_groups": [["condition_enumeration"], ["integer_split"]],
        "exclude_fact_keys": ["work_rate_task"],
        "confusable_with": ["工程问题", "排列组合", "最值问题"],
        "positive_examples": ["若干国家代表总数固定、各国人数互不相同且满足部分和条件，枚举正整数拆分确定对象。"],
        "near_miss_examples": ["只出现国际合作、论坛等语境，没有工作效率或完成任务结构。"],
        "negative_examples": ["工程合作完成任务、普通排列组合计数或只有总数没有条件限制的应用题。"],
        "source_refs": ["curated:wmo_2026:q10:condition_enumeration_integer_split"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.rotation_area_transform",
        "name": "整体法求面积 / 旋转割补求阴影面积",
        "domain": "geometry_spatial",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数五年级：整体法求面积 / 旋转割补求阴影面积",
        "aliases": ["整体法求面积", "旋转割补", "旋转求阴影面积", "阴影面积"],
        "required_fact_groups": [["rotation_area_transform"], ["area_goal"]],
        "exclude_fact_keys": ["statistics_chart_context", "school_statistics", "cylinder_surface_volume"],
        "confusable_with": ["平移和旋转", "圆与扇形", "基础几何公式应用"],
        "positive_examples": ["图形绕点旋转形成可整体转化的阴影面积，并出现π或扇形面积关系。"],
        "near_miss_examples": ["只判断顺时针或逆时针方向，不求面积。"],
        "negative_examples": ["校内图形运动概念题、统计图读图题或圆柱表面积体积题。"],
        "source_refs": ["curated:wmo_2026:q12:rotation_area_transform"],
    },
    {
        "knowledge_point_id": "dim5.logic_strategy.binary_information_search",
        "name": "二分策略 / 信息查找 / 最优排查",
        "domain": "logic_strategy_construction",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "6",
        "knowledge_grade_label": "六年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数六年级：二分策略 / 信息查找 / 最优排查",
        "aliases": ["二分策略", "信息查找", "最优排查", "折半查找"],
        "required_fact_groups": [["binary_search_strategy"], ["information_search_strategy"]],
        "exclude_fact_keys": ["school_division", "school_unit_division_context"],
        "confusable_with": ["整数除法", "最值问题", "逻辑推理"],
        "positive_examples": ["通过关闭某个阀门观察反馈，把漏水位置候选范围分成两段，求至少几次确定目标。"],
        "near_miss_examples": ["只出现每个对象或编号，不需要利用反馈缩小范围。"],
        "negative_examples": ["普通平均分、整数除法或没有测试反馈的信息题。"],
        "source_refs": ["curated:wmo_2026:q13:binary_information_search"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.butterfly_area_ratio",
        "name": "蝴蝶模型 / 面积比例",
        "domain": "geometry_spatial",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数五年级：蝴蝶模型 / 面积比例",
        "aliases": ["蝴蝶模型", "面积比例", "对角线面积关系", "四边形面积比例"],
        "required_fact_groups": [["butterfly_area_model"], ["geometry_area"], ["area_ratio_relation"]],
        "exclude_fact_keys": ["basic_formula"],
        "confusable_with": ["面积比模型", "燕尾模型", "三角形面积"],
        "positive_examples": ["四边形对角线相交，给出多个三角形面积和边上比例，求另一三角形面积。"],
        "near_miss_examples": ["只用底乘高直接求一个三角形面积。"],
        "negative_examples": ["普通面积公式题或没有对角线交点与比例关系的图形题。"],
        "source_refs": ["curated:wmo_2026:q14:butterfly_area_ratio"],
    },
    {
        "knowledge_point_id": "dim5.number_operation.defined_operation",
        "name": "定义新运算",
        "domain": "number_operation",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：定义新运算",
        "aliases": ["定义新运算", "新定义运算", "规定一种运算", "自定义运算", "运算符号", "※运算"],
        "required_fact_groups": [["defined_operation_rule"], ["defined_operation_target", "defined_operation_symbol"]],
        "exclude_fact_keys": ["work_rate_task", "statistics_chart_context"],
        "confusable_with": ["小数分数混合运算", "分数裂项求和", "普通四则计算"],
        "positive_examples": ["题目先规定一种运算 ※，给出若干定义式，再要求代入或反求未知量。"],
        "near_miss_examples": ["只有普通加减乘除或填空符号，没有题面定义的新运算规则。"],
        "negative_examples": ["分数小数混合运算、普通方程填空、工程问题或统计图读图题。"],
        "source_refs": ["curated:wmo_2026_local_final:q1:defined_operation"],
    },
    {
        "knowledge_point_id": "dim5.number_operation.conditional_defined_operation",
        "name": "条件判断型新定义运算",
        "domain": "number_operation",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：条件判断型新定义运算",
        "aliases": ["条件判断型的普通规则新运算", "定义☆运算", "奇偶条件新运算", "如果则新定义运算"],
        "required_fact_groups": [["new_operation_conditional"]],
        "exclude_fact_keys": [],
        "confusable_with": ["等量代换与简易方程", "定义新运算"],
        "positive_examples": ["定义☆运算时按a+b是奇数或偶数给出不同公式，再代入求值。"],
        "near_miss_examples": ["只有△和□代表数的等量代换，没有新运算规则。"],
        "negative_examples": ["普通方程、等量代换或没有条件分支的新定义运算。"],
        "source_refs": ["curated:xsc_thinking:q7:new_operation_conditional"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.equal_area_sandglass",
        "name": "沙漏面积模型",
        "domain": "geometry_spatial",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数五年级：沙漏面积模型",
        "aliases": ["大小正方形间的沙漏", "沙漏面积", "两个正方形阴影面积"],
        "required_fact_groups": [["equal_area_sandglass"]],
        "exclude_fact_keys": ["basic_formula"],
        "confusable_with": ["基础几何公式应用", "面积比模型"],
        "positive_examples": ["大小两个正方形边长已知，图中形成沙漏状阴影，求阴影部分面积。"],
        "near_miss_examples": ["只直接求一个正方形面积。"],
        "negative_examples": ["普通正方形面积公式题或没有沙漏/阴影关系的图形题。"],
        "source_refs": ["curated:xsc_thinking:q2:equal_area_sandglass"],
    },
    {
        "knowledge_point_id": "dim5.quantity_application.work_split_collaboration",
        "name": "工程分段合作 / 来回帮忙",
        "domain": "quantity_application",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数五年级：工程分段合作 / 来回帮忙",
        "aliases": ["工作量相同的来回帮忙问题", "分段合作工程", "中途帮助", "两个仓库同时搬完"],
        "required_fact_groups": [["work_split_collaboration"]],
        "exclude_fact_keys": [],
        "confusable_with": ["工程问题"],
        "positive_examples": ["甲乙丙在两个仓库搬货，中途一人转去帮忙，最后两个仓库同时搬完。"],
        "near_miss_examples": ["甲乙单独做和合作完成的普通工程题。"],
        "negative_examples": ["没有分段、来回帮忙或同时完成条件的普通效率题。"],
        "source_refs": ["curated:xsc_thinking:q4:work_split_collaboration"],
    },
    {
        "knowledge_point_id": "dim5.quantity_application.travel_inverse_speed_time",
        "name": "行程反比 / 速度时间关系",
        "domain": "quantity_application",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "6",
        "knowledge_grade_label": "六年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数六年级：行程反比 / 速度时间关系",
        "aliases": ["速度和时间成反比解行程", "速度时间反比", "往返同路程速度比"],
        "required_fact_groups": [["travel_inverse_speed_time"]],
        "exclude_fact_keys": [],
        "confusable_with": ["比例解应用题", "普通行程问题"],
        "positive_examples": ["往返同一路程，返回速度与去时速度之比已知，结合总时间求距离。"],
        "near_miss_examples": ["只给两个量的普通比例关系，没有同一路程速度时间反比。"],
        "negative_examples": ["一般比例分配或没有速度时间路程结构的题。"],
        "source_refs": ["curated:xsc_thinking:q13:travel_inverse_speed_time", "curated:xsc_placement:q3:travel_inverse_speed_time"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.trapezoid_auxiliary_area",
        "name": "梯形辅助线面积模型",
        "domain": "geometry_spatial",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数五年级：梯形辅助线面积模型",
        "aliases": ["连辅助线后构造梯形模型", "三等分点阴影面积", "平行四边形辅助线面积"],
        "required_fact_groups": [["trapezoid_auxiliary_area"]],
        "exclude_fact_keys": ["basic_formula"],
        "confusable_with": ["平行四边形面积", "面积比模型"],
        "positive_examples": ["平行四边形面积已知，点在边上三等分，连辅助线构造梯形求阴影面积。"],
        "near_miss_examples": ["直接用平行四边形底高求面积。"],
        "negative_examples": ["没有辅助线或三等分点关系的普通面积题。"],
        "source_refs": ["curated:xsc_thinking:q14:trapezoid_auxiliary_area"],
    },
    {
        "knowledge_point_id": "dim5.pattern_sequence.geometric_series_area_sum",
        "name": "等比面积数列求和",
        "domain": "pattern_sequence",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "6",
        "knowledge_grade_label": "六年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数六年级：等比面积数列求和",
        "aliases": ["整数型等比数列求和", "等比面积数列", "图形n的面积", "后一个图形面积递推"],
        "required_fact_groups": [["geometric_series_area_sum"]],
        "exclude_fact_keys": ["pythagorean_area_relation"],
        "confusable_with": ["勾股面积关系", "简单规律与数列"],
        "positive_examples": ["一系列等腰直角三角形面积按斜边和直角边倍比递推，求第n个图形面积。"],
        "near_miss_examples": ["单个直角三角形或正方形上的勾股面积关系。"],
        "negative_examples": ["没有面积倍比递推的普通几何题。"],
        "source_refs": ["curated:xsc_thinking:q17:geometric_series_area_sum"],
    },
    {
        "knowledge_point_id": "dim5.counting_combinatorics.tree_diagram_queue_counting",
        "name": "树形图排队 / 位置限制计数",
        "domain": "counting_combinatorics",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "4",
        "knowledge_grade_label": "四年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数四年级：树形图排队 / 位置限制计数",
        "aliases": ["树形图排队问题", "错位排列放书", "不能放在第一层", "不同的放法"],
        "required_fact_groups": [["tree_diagram_queue_counting"]],
        "exclude_fact_keys": [],
        "confusable_with": ["排列组合"],
        "positive_examples": ["A、B、C、D四本书放书架，每本书都有不能放的位置，求不同放法。"],
        "near_miss_examples": ["没有位置限制的普通全排列。"],
        "negative_examples": ["只安排若干人排队但没有逐项位置约束的题。"],
        "source_refs": ["curated:xsc_placement:q9:tree_diagram_queue_counting"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.cuboid_coloring",
        "name": "长方体染色计数",
        "domain": "geometry_spatial",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数五年级：长方体染色计数",
        "aliases": ["长方体染色", "刷漆小立方体", "未刷漆的小立方体", "涂色方块数"],
        "required_fact_groups": [["cuboid_coloring"]],
        "exclude_fact_keys": ["school_cube_net"],
        "confusable_with": ["认识立体图形", "正方体展开图"],
        "positive_examples": ["由48个小立方体堆成长方体，表面刷漆后问六个面都未刷漆的小立方体个数。"],
        "near_miss_examples": ["只识别长方体、正方体形状。"],
        "negative_examples": ["普通立体图形认识或没有刷漆计数的体积题。"],
        "source_refs": ["curated:xsc_placement:q10:cuboid_coloring"],
    },
    {
        "knowledge_point_id": "dim5.quantity_application.downstream_upstream_current",
        "name": "流水行船 / 顺逆水速度",
        "domain": "quantity_application",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数五年级：流水行船 / 顺逆水速度",
        "aliases": ["根据顺速和逆速求船速和水速", "顺水航行", "逆水航行", "顺水漂流"],
        "required_fact_groups": [["downstream_upstream_current"]],
        "exclude_fact_keys": [],
        "confusable_with": ["普通行程问题"],
        "positive_examples": ["顺水航行3小时和逆水航行5小时航程相等，求顺水漂流1小时的航程。"],
        "near_miss_examples": ["没有水流速度的普通速度时间路程题。"],
        "negative_examples": ["工程、比例或没有顺逆水结构的行程题。"],
        "source_refs": ["curated:xsc_placement:q11:downstream_upstream_current"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.slicing_volume_method",
        "name": "切片法求体积",
        "domain": "geometry_spatial",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数五年级：切片法求体积",
        "aliases": ["切片法求体积", "挖空后剩下体积", "正方体切割成小正方体"],
        "required_fact_groups": [["slicing_volume_method"]],
        "exclude_fact_keys": ["school_cube_net"],
        "confusable_with": ["认识立体图形", "长方体染色计数"],
        "positive_examples": ["正方体切成1厘米小正方体后，从正面、上面、右面沿阴影区域挖空，求剩余体积。"],
        "near_miss_examples": ["只求正方体体积或表面积。"],
        "negative_examples": ["没有切片、挖空或分层统计的立体几何题。"],
        "source_refs": ["curated:xsc_placement:q14:slicing_volume_method"],
    },
    {
        "knowledge_point_id": "dim5.number_operation.floor_function_operation",
        "name": "取整函数计算",
        "domain": "number_operation",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "6",
        "knowledge_grade_label": "六年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数六年级：取整函数计算",
        "aliases": ["复杂取整取小", "整数部分", "不大于的整数", "取整符号"],
        "required_fact_groups": [["floor_function_operation"]],
        "exclude_fact_keys": ["school_comparison"],
        "confusable_with": ["普通四则计算"],
        "positive_examples": ["规定符号表示某数的整数部分或不大于某数的整数，再进行计算推理。"],
        "near_miss_examples": ["普通小数取近似数。"],
        "negative_examples": ["没有特殊取整定义的普通计算题。"],
        "source_refs": ["curated:xsc_placement:q15:floor_function_operation"],
    },
    {
        "knowledge_point_id": "dim5.quantity_application.cross_concentration_mix",
        "name": "十字交叉浓度问题",
        "domain": "quantity_application",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "6",
        "knowledge_grade_label": "六年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数六年级：十字交叉浓度问题",
        "aliases": ["十字交叉法反求混合前重量", "酒精浓度混合", "纯酒精含量", "多取15千克"],
        "required_fact_groups": [["cross_concentration_mix"]],
        "exclude_fact_keys": ["profit_discount"],
        "confusable_with": ["浓度问题与经济问题"],
        "positive_examples": ["72%和58%酒精混合成62%，再各多取15千克后为63.25%，反求第一次两种酒精重量。"],
        "near_miss_examples": ["只加水稀释求新浓度。"],
        "negative_examples": ["普通百分数应用或没有两次混合差量关系的浓度题。"],
        "source_refs": ["curated:xsc_placement:q26:cross_concentration_mix"],
    },
    {
        "knowledge_point_id": "dim5.quantity_application.hidden_distance_meeting",
        "name": "相遇问题 / 隐藏路程差",
        "domain": "quantity_application",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数五年级：相遇问题 / 隐藏路程差",
        "aliases": ["相遇过程中的隐藏路程差", "距离的一半还多", "同时出发相遇"],
        "required_fact_groups": [["hidden_distance_meeting"]],
        "exclude_fact_keys": [],
        "confusable_with": ["普通行程问题"],
        "positive_examples": ["两人同时从两村出发，相遇时一人走了全程一半还多0.75千米，求速度。"],
        "near_miss_examples": ["直接给两人速度和时间求路程。"],
        "negative_examples": ["没有相遇和隐藏路程差条件的行程题。"],
        "source_refs": ["curated:xsc_placement:q23:hidden_distance_meeting"],
    },
    {
        "knowledge_point_id": "dim5.counting_combinatorics.round_robin_counting",
        "name": "循环赛规律 / 比赛场次",
        "domain": "counting_combinatorics",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "4",
        "knowledge_grade_label": "四年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数四年级：循环赛规律 / 比赛场次",
        "aliases": ["循环赛规律", "单循环比赛", "比赛场次", "数线段方法"],
        "required_fact_groups": [["round_robin_counting"]],
        "exclude_fact_keys": [],
        "confusable_with": ["找规律", "握手问题与比赛轮次"],
        "positive_examples": ["n个队单循环比赛，每两个队之间比赛一场，用线段数推广比赛场次公式。"],
        "near_miss_examples": ["只问几个队比赛一次的直接加法。"],
        "negative_examples": ["普通数列找规律或没有两两配对比赛语义的题。"],
        "source_refs": ["curated:xsc_placement:q27:round_robin_counting"],
    },
    {
        "knowledge_point_id": "dim5.counting_combinatorics.railway_ticket_counting",
        "name": "车站车票计数",
        "domain": "counting_combinatorics",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "4",
        "knowledge_grade_label": "四年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数四年级：车站车票计数",
        "aliases": ["排列组合辨析", "新增车站车票", "往返车票不一样", "需要增加车票种数"],
        "required_fact_groups": [["railway_ticket_counting"]],
        "exclude_fact_keys": [],
        "confusable_with": ["排列组合"],
        "positive_examples": ["原有7个车站，新增3个车站，往返车票不一样，求需要增加多少种车票。"],
        "near_miss_examples": ["普通无向两两配对只数线段。"],
        "negative_examples": ["没有车站、车票或有向往返语义的普通排列题。"],
        "source_refs": ["curated:xsc_placement:q13:railway_ticket_counting"],
    },
    {
        "knowledge_point_id": "dim5.pattern_sequence.magic_square_relation",
        "name": "三阶幻方关系",
        "domain": "pattern_sequence",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "4",
        "knowledge_grade_label": "四年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数四年级：三阶幻方关系",
        "aliases": ["三阶幻方", "数阵填数", "b+c=2×a"],
        "required_fact_groups": [["magic_square_relation"]],
        "exclude_fact_keys": ["gaosi_permutation_combination"],
        "confusable_with": ["数阵图", "简单规律"],
        "positive_examples": ["根据三阶幻方行列对角线和相等，利用b+c=2×a关系补全数阵。"],
        "near_miss_examples": ["普通表格填数，没有幻方等和关系。"],
        "negative_examples": ["没有幻方或数阵结构的规律题。"],
        "source_refs": ["curated:xsc_placement:q22:magic_square_relation"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.partial_submerged_water_rise",
        "name": "不完全浸没水面上升",
        "domain": "geometry_spatial",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "6",
        "knowledge_grade_label": "六年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数六年级：不完全浸没水面上升",
        "aliases": ["不完全浸没水未溢出", "圆柱竖直放入水池", "水面会上升"],
        "required_fact_groups": [["partial_submerged_water_rise"]],
        "exclude_fact_keys": [],
        "confusable_with": ["长正方体体积与容积 / 浸没水面上升"],
        "positive_examples": ["圆柱形水池中已有水，将较高圆柱竖直放入，水面上升但物体可能不完全浸没。"],
        "near_miss_examples": ["物体完全浸没且只用排水体积直接求水面上升。"],
        "negative_examples": ["普通圆柱体积或没有水位变化的题。"],
        "source_refs": ["curated:xsc_thinking:q5:partial_submerged_water_rise"],
    },
    {
        "knowledge_point_id": "dim5.quantity_application.list_ratio_analysis",
        "name": "列表分析 / 多对象比例",
        "domain": "quantity_application",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "6",
        "knowledge_grade_label": "六年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数六年级：列表分析 / 多对象比例",
        "aliases": ["简单的列表分析", "三个班男女生人数比", "多对象比例整理"],
        "required_fact_groups": [["list_ratio_analysis"]],
        "exclude_fact_keys": [],
        "confusable_with": ["比例解应用题"],
        "positive_examples": ["甲乙丙三个班给出男女生总比、各班男女比和总人数比，列表整理求乙班男女比。"],
        "near_miss_examples": ["只有一个比例关系的普通比例应用题。"],
        "negative_examples": ["没有多个对象和多重比例条件的题。"],
        "source_refs": ["curated:xsc_thinking:q16:list_ratio_analysis"],
    },
    {
        "knowledge_point_id": "dim5.number_operation.vertical_multiplication_digit_analysis",
        "name": "乘法竖式位数分析",
        "domain": "number_operation",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数五年级：乘法竖式位数分析",
        "aliases": ["多位数乘多位数位数分析", "乘法竖式数字被盖住", "三角形盖住数字"],
        "required_fact_groups": [["vertical_multiplication_digit_analysis"]],
        "exclude_fact_keys": ["school_multiplication"],
        "confusable_with": ["乘法竖式及应用", "竖式数字谜"],
        "positive_examples": ["乘法竖式中部分数字被三角形盖住，利用位数和部分数字推断乘积。"],
        "near_miss_examples": ["直接进行多位数乘法竖式计算。"],
        "negative_examples": ["普通乘法运算或没有遮挡推理的竖式题。"],
        "source_refs": ["curated:xsc_thinking:q3:vertical_multiplication_digit_analysis"],
    },
    {
        "knowledge_point_id": "dim5.number_theory.remainder_system_conditions",
        "name": "多条件余数问题",
        "domain": "number_theory",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数五年级：多条件余数问题",
        "aliases": ["三个条件的逐级满足", "被7除余2", "被8除余3", "被9除余1", "同余与余数问题"],
        "required_fact_groups": [["remainder_system_conditions"]],
        "exclude_fact_keys": [],
        "confusable_with": ["余数", "进位制与取整符号"],
        "positive_examples": ["一个小于200的自然数，同时满足被7、8、9除后的多个余数条件。"],
        "near_miss_examples": ["只做一个除法求余数。"],
        "negative_examples": ["普通大小比较或没有多个余数条件的题。"],
        "source_refs": ["curated:xsc_placement:q12:remainder_system_conditions"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.complex_circle_overlap_area",
        "name": "复杂圆形重叠与割补面积",
        "domain": "geometry_spatial",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数五年级：复杂圆形重叠与割补面积",
        "aliases": ["复杂重叠整体面积", "割补法求复杂面积", "圆和半圆两两相切", "多块阴影面积"],
        "required_fact_groups": [["complex_circle_overlap_area"]],
        "exclude_fact_keys": ["statistics_chart_context"],
        "confusable_with": ["圆与扇形", "方圆重叠面积"],
        "positive_examples": ["多个圆和半圆两两相切，求多块阴影部分面积，需要整体或割补处理。"],
        "near_miss_examples": ["只求一个圆或扇形的直接面积。"],
        "negative_examples": ["统计图扇形或没有重叠/相切阴影结构的普通圆面积题。"],
        "source_refs": ["curated:xsc_placement:q21:complex_circle_overlap_area"],
    },
    {
        "knowledge_point_id": "dim5.counting_combinatorics.palindrome_counting",
        "name": "回文数的分类计数",
        "domain": "counting_combinatorics",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：回文数的分类计数",
        "aliases": ["回文数", "数位对称", "分类计数", "按位数分类"],
        "required_fact_groups": [["palindrome_number_counting"]],
        "exclude_fact_keys": ["gaosi_digit_puzzle", "gaosi_permutation_combination"],
        "confusable_with": ["数字谜", "组合计数"],
        "positive_examples": ["统计1到2015范围内正着读反着读一样的回文数个数。"],
        "near_miss_examples": ["只判断一个数是不是回文数，不需要分类计数。"],
        "negative_examples": ["普通数字谜、竖式填数或没有数位对称统计目标的题。"],
        "source_refs": ["curated:placement_exam_5:q10"],
    },
    {
        "knowledge_point_id": "dim5.quantity_application.variable_speed_round_trip",
        "name": "变速往返行程问题",
        "domain": "quantity_application",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：变速往返行程问题",
        "aliases": ["上坡下坡行程", "往返行程", "变速行程", "上坡", "下坡", "平路"],
        "required_fact_groups": [["variable_speed_round_trip"], ["motion_task"], ["speed_distance_time"]],
        "exclude_fact_keys": ["work_rate_task", "concentration_task"],
        "confusable_with": ["普通行程问题"],
        "positive_examples": ["去程有上坡、下坡和平路，返程上坡下坡角色互换，求返程时间。"],
        "near_miss_examples": ["只有单一路段速度、时间、路程关系的普通行程题。"],
        "negative_examples": ["工程效率题、浓度变化题或不涉及往返变速结构的应用题。"],
        "source_refs": ["curated:placement_exam_5:q20"],
    },
    {
        "knowledge_point_id": "dim5.quantity_application.reverse_surplus_payment_process",
        "name": "还原与盈亏问题",
        "domain": "quantity_application",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "4",
        "knowledge_grade_label": "四年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数四年级：还原与盈亏问题",
        "aliases": ["收支变化倒推", "奖励与收费", "钱袋变化", "还剩", "最初有多少"],
        "required_fact_groups": [["reverse_surplus_payment_process"]],
        "exclude_fact_keys": ["work_rate_task", "motion_task"],
        "confusable_with": ["普通方程应用", "年龄问题"],
        "positive_examples": ["先每天奖励银币，后来每天交费，已知还剩数量，倒推最初钱数。"],
        "near_miss_examples": ["只列一个普通方程，没有过程收支变化。"],
        "negative_examples": ["普通年龄差问题、单纯分数应用题或没有收支变化的方程题。"],
        "source_refs": ["curated:placement_exam_5:q23"],
    },
    {
        "knowledge_point_id": "dim5.number_theory.place_value_principle",
        "name": "位值原理",
        "domain": "number_theory",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数五年级：位值原理",
        "aliases": ["位值原理", "位值原理综合", "数位交换", "百位十位个位", "多位数表示"],
        "required_fact_groups": [["gaosi_place_value_principle"]],
        "exclude_fact_keys": ["digit_swap_multiple"],
        "confusable_with": ["数字性质中9的倍数判定", "数字谜"],
        "positive_examples": ["三位数交换百位和十位后变小，利用位值表示数值差。"],
        "near_miss_examples": ["只根据数字和判断3或9的倍数。"],
        "negative_examples": ["普通竖式填数、单纯整除判断或没有数位交换关系的题。"],
        "source_refs": ["reference_standard_data.json:高思导引:5年级:位值原理综合", "curated:placement_exam_6:q18"],
    },
    {
        "knowledge_point_id": "dim5.school.4.equilateral_triangle_perimeter_transform",
        "name": "等边三角形周长转化",
        "domain": "geometry_spatial",
        "level": "L2",
        "quality_status": "approved",
        "knowledge_track": "school",
        "knowledge_track_label": "校内",
        "knowledge_grade": "4",
        "knowledge_grade_label": "四年级",
        "knowledge_semester": "下册",
        "knowledge_display_name": "校内四年级：等边三角形周长转化",
        "aliases": ["正三角形周长转化", "等边三角形求周长或边长", "正三角形", "等边三角形", "中点边长转化"],
        "required_fact_groups": [["equilateral_triangle_perimeter_transform"], ["school_perimeter"], ["midline_or_midpoint"]],
        "exclude_fact_keys": ["geometry_area"],
        "confusable_with": ["多边形内角和计算", "等边三角形求周长或边长"],
        "positive_examples": ["多个正三角形共用边和中点关系，求组合多边形周长。"],
        "near_miss_examples": ["只问等边三角形单个边长乘3的直接计算。"],
        "negative_examples": ["求多边形内角和、角度或普通面积的题。"],
        "source_refs": ["school_reference:reference_standard_data.json:四年级下册:三角形:等边三角形求周长或边长", "curated:placement_exam_6:q20"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.swallowtail_area_model",
        "name": "燕尾模型",
        "domain": "geometry_spatial",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数五年级：燕尾模型",
        "aliases": ["燕尾模型", "风筝与燕尾", "燕尾面积模型", "面积比模型"],
        "required_fact_groups": [["swallowtail_area_model"], ["geometry_area"], ["area_relation_model"], ["geometry_triangle"]],
        "exclude_fact_keys": ["basic_formula"],
        "confusable_with": ["三角形面积", "面积比模型", "基础几何公式应用"],
        "positive_examples": ["正方形中构造等腰三角形，求由顶点连线形成的三角形面积。"],
        "near_miss_examples": ["直接用底乘高除以2计算的普通三角形面积。"],
        "negative_examples": ["没有共点、共边或面积关系转换的直接公式题。"],
        "source_refs": ["reference_standard_data.json:高思导引:5年级:燕尾模型", "curated:placement_exam_6:q23"],
    },
    {
        "knowledge_point_id": "dim5.quantity_application.travel_equation_application",
        "name": "行程方程应用",
        "domain": "quantity_application",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：行程方程应用",
        "aliases": ["行程方程应用", "速度增加提前到达", "同一路程行程方程", "速度时间路程方程"],
        "required_fact_groups": [["travel_equation_same_distance"], ["motion_task"], ["speed_distance_time"]],
        "exclude_fact_keys": ["variable_speed_round_trip", "work_rate_task"],
        "confusable_with": ["行程问题一", "变速往返行程问题"],
        "positive_examples": ["同一路程下速度增加会提前到达，利用速度、时间、路程关系列方程。"],
        "near_miss_examples": ["去程返程上坡下坡速度互换的变速往返行程。"],
        "negative_examples": ["工程效率题、浓度题或没有速度时间路程关系的应用题。"],
        "source_refs": ["curated:placement_exam_6:q24"],
    },
    {
        "knowledge_point_id": "dim5.counting_combinatorics.graph_relation_network_counting",
        "name": "图论基础与关系网络计数",
        "domain": "counting_combinatorics",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：图论基础与关系网络计数",
        "aliases": ["图论基础", "关系网络计数", "点边关系", "认识关系", "二层关系计数", "集合去重计数"],
        "required_fact_groups": [["graph_relation_network_counting"], ["counting_target"]],
        "exclude_fact_keys": [],
        "confusable_with": ["整数除法", "普通计数"],
        "positive_examples": ["用点和边表示同学认识关系，统计直接认识和间接认识的人并去重。"],
        "near_miss_examples": ["只数一共有多少个点或边，不涉及二层关系。"],
        "negative_examples": ["普通除法平均分或没有关系网络结构的计数题。"],
        "source_refs": ["curated:placement_exam_6:q27"],
    },
    {
        "knowledge_point_id": "dim5.school.6.statistics_chart_comprehensive",
        "name": "统计图综合",
        "domain": "statistics_probability",
        "level": "L2",
        "quality_status": "approved",
        "knowledge_track": "school",
        "knowledge_track_label": "校内",
        "knowledge_grade": "6",
        "knowledge_grade_label": "六年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "校内六年级：统计图综合",
        "aliases": ["统计图综合", "条形统计图", "扇形统计图", "百分比人数换算", "圆心角与比例"],
        "required_fact_groups": [["school_statistics"], ["statistics_chart_context"]],
        "exclude_fact_keys": ["geometry_area"],
        "confusable_with": ["圆与扇形", "平均数"],
        "positive_examples": ["条形统计图与扇形统计图同时给出人数、百分比或圆心角，要求换算总人数或局部人数。"],
        "near_miss_examples": ["只根据圆或扇形图形求几何面积，不涉及统计图数据。"],
        "negative_examples": ["普通圆与扇形面积、周长计算，或只出现平均数而没有统计图读图任务。"],
        "source_refs": ["curated:placement_exam_batch_7_11_14:statistics_chart"],
    },
    {
        "knowledge_point_id": "dim5.quantity_application.two_type_total_price",
        "name": "两类对象总量总价问题",
        "domain": "quantity_application",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：两类对象总量总价问题",
        "aliases": ["鸡兔同笼变式", "总量总价", "两类对象", "停车费问题", "方程组应用"],
        "required_fact_groups": [["two_type_cost_total"], ["gaosi_chicken_rabbit"]],
        "exclude_fact_keys": ["school_division"],
        "confusable_with": ["整数除法", "平均分应用", "普通单价数量总价"],
        "positive_examples": ["两类车辆共若干辆、总停车费已知、每类单价不同，求两类车辆数量。"],
        "near_miss_examples": ["已知单价和数量直接求总价的单步乘法或除法。"],
        "negative_examples": ["只有元/辆这类单位写法，没有两类对象和总量总价约束。"],
        "source_refs": ["curated:placement_exam_7:q19", "curated:placement_exam_batch_11_14:equation_applications"],
    },
    {
        "knowledge_point_id": "dim5.number_theory.square_difference_odd",
        "name": "连续奇数平方差与整除",
        "domain": "number_theory",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：连续奇数平方差与整除",
        "aliases": ["连续奇数平方差", "平方数差", "整除性判断", "新定义数论"],
        "required_fact_groups": [["square_difference_odd"]],
        "exclude_fact_keys": ["school_comparison"],
        "confusable_with": ["数的大小比较", "简单规律与数列"],
        "positive_examples": ["定义一种数，需要利用连续奇数平方差或平方数差的整除性质判断。"],
        "near_miss_examples": ["只比较两个数大小或只填不等号。"],
        "negative_examples": ["没有平方差、连续奇数或整除约束的普通数感题。"],
        "source_refs": ["curated:placement_exam_7:q3", "curated:placement_exam_batch_12_13:number_theory"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.fold_cut_unfold",
        "name": "折叠展开与剪纸问题",
        "domain": "geometry_spatial",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：折叠展开与剪纸问题",
        "aliases": ["折叠展开", "剪纸问题", "折后展开", "翻折剪开"],
        "required_fact_groups": [["fold_cut_unfold"]],
        "exclude_fact_keys": ["school_cube_net"],
        "confusable_with": ["正方体展开图", "轴对称图形"],
        "positive_examples": ["纸片折叠或对折后剪开，要求判断展开后的图形或痕迹。"],
        "near_miss_examples": ["只判断正方体六个面的相邻或相对关系。"],
        "negative_examples": ["没有折叠、剪开和展开过程的普通平面图形题。"],
        "source_refs": ["curated:placement_exam_7:q7", "curated:placement_exam_13:q5"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.transform_puzzle",
        "name": "旋转平移拼图问题",
        "domain": "geometry_spatial",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：旋转平移拼图问题",
        "aliases": ["旋转平移", "俄罗斯方块拼图", "图形变换拼图", "平移旋转"],
        "required_fact_groups": [["geometry_transform_puzzle"]],
        "exclude_fact_keys": [],
        "confusable_with": ["平移和旋转", "排列组合"],
        "positive_examples": ["通过旋转、平移或翻转俄罗斯方块形图形，判断能否拼成指定图形。"],
        "near_miss_examples": ["只识别生活中的平移或旋转现象。"],
        "negative_examples": ["没有实际图形拼合约束的普通变换识别题。"],
        "source_refs": ["curated:placement_exam_14:q1_2"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.overlap_area",
        "name": "重叠面积与容斥面积",
        "domain": "geometry_spatial",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：重叠面积与容斥面积",
        "aliases": ["重叠面积", "重叠部分", "公共部分", "容斥面积"],
        "required_fact_groups": [["overlap_area"], ["geometry_area"]],
        "exclude_fact_keys": [],
        "confusable_with": ["基础几何公式应用", "三角形面积"],
        "positive_examples": ["两个正方形或多个图形覆盖后，利用重叠部分和总面积关系求面积。"],
        "near_miss_examples": ["直接套用长方形或正方形面积公式。"],
        "negative_examples": ["没有重叠、覆盖或公共部分关系的面积题。"],
        "source_refs": ["curated:placement_exam_14:q10", "curated:placement_exam_13:q10"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.cylinder_surface_volume",
        "name": "圆柱侧面展开与体积守恒",
        "domain": "geometry_spatial",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：圆柱侧面展开与体积守恒",
        "aliases": ["圆柱侧面展开", "圆柱展开图", "圆柱体积守恒", "最大底面积"],
        "required_fact_groups": [["cylinder_surface_volume"]],
        "exclude_fact_keys": ["school_cube_net"],
        "confusable_with": ["认识圆柱的展开图", "圆柱的体积"],
        "positive_examples": ["圆柱侧面展开或重新围成圆柱，比较底面积、表面积或体积关系。"],
        "near_miss_examples": ["直接用圆柱体积公式求单个圆柱体积。"],
        "negative_examples": ["没有展开、围成或守恒关系的普通立体几何题。"],
        "source_refs": ["curated:placement_exam_14:q1_4"],
    },
    {
        "knowledge_point_id": "dim5.number_theory.digit_swap_multiple",
        "name": "数位交换成倍数数字谜",
        "domain": "number_theory",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：数位交换成倍数数字谜",
        "aliases": ["数位交换", "交换数字后成倍数", "位值制", "数字谜"],
        "required_fact_groups": [["digit_swap_multiple"]],
        "exclude_fact_keys": ["school_comparison"],
        "confusable_with": ["整数除法", "数字谜综合"],
        "positive_examples": ["六位数交换某两个数字后变成原数的若干倍，利用位值制列式求数。"],
        "near_miss_examples": ["只交换两位数后比较大小。"],
        "negative_examples": ["没有数位交换和倍数关系的普通数字题。"],
        "source_refs": ["curated:placement_exam_12:q16"],
    },
    {
        "knowledge_point_id": "dim5.pattern_sequence.periodic_grid",
        "name": "周期格子与数表规律",
        "domain": "pattern_sequence",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：周期格子与数表规律",
        "aliases": ["周期格子", "数表周期", "方格周期", "周期规律"],
        "required_fact_groups": [["periodic_grid"]],
        "exclude_fact_keys": [],
        "confusable_with": ["包含与排除", "简单规律与数列"],
        "positive_examples": ["方格或数表中的数字、颜色按周期重复，求指定位置的状态。"],
        "near_miss_examples": ["只做普通等差数列求项。"],
        "negative_examples": ["没有周期重复和位置索引的普通找规律题。"],
        "source_refs": ["curated:placement_exam_13:q20"],
    },
    {
        "knowledge_point_id": "dim5.pattern_sequence.state_recurrence",
        "name": "传数游戏与状态递推",
        "domain": "pattern_sequence",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：传数游戏与状态递推",
        "aliases": ["传数游戏", "状态转移", "递推还原", "状态递推"],
        "required_fact_groups": [["state_recurrence"]],
        "exclude_fact_keys": [],
        "confusable_with": ["还原问题", "周期规律"],
        "positive_examples": ["按规则多轮传数或变换状态，要求倒推初始状态或递推最终状态。"],
        "near_miss_examples": ["只有一次普通倒推，没有状态重复变换。"],
        "negative_examples": ["普通数列或没有状态变换规则的应用题。"],
        "source_refs": ["curated:placement_exam_13:q33"],
    },
    {
        "knowledge_point_id": "dim5.pattern_sequence.line_plane_recurrence",
        "name": "直线分平面递推",
        "domain": "pattern_sequence",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：直线分平面递推",
        "aliases": ["直线分平面", "直线最多", "平面分成多少部分", "分成最多部分", "递推规律"],
        "required_fact_groups": [["line_plane_recurrence"]],
        "exclude_fact_keys": [],
        "confusable_with": ["最值问题", "简单规律与数列"],
        "positive_examples": ["n条直线最多把平面分成多少部分，需要建立递推关系。"],
        "near_miss_examples": ["只比较最大最小数值但没有递推结构。"],
        "negative_examples": ["普通几何作图或没有直线分割平面的题。"],
        "source_refs": ["curated:placement_exam_13:q19"],
    },
    {
        "knowledge_point_id": "dim5.logic_strategy.transport_optimization",
        "name": "运输费用统筹优化",
        "domain": "logic_strategy_construction",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：运输费用统筹优化",
        "aliases": ["运输费用最小", "运输优化", "方案最优", "运费最小", "统筹优化"],
        "required_fact_groups": [["transport_optimization"]],
        "exclude_fact_keys": [],
        "confusable_with": ["排列组合", "统筹与对策"],
        "positive_examples": ["多种车辆或路线运输货物，比较费用并安排使总费用最小。"],
        "near_miss_examples": ["只问有几种安排方案，不涉及最小费用或最优目标。"],
        "negative_examples": ["普通排列组合、座位安排或没有费用目标的方案计数。"],
        "source_refs": ["curated:placement_exam_13:q34"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.cube_section_cut",
        "name": "正方体截面与立体切割",
        "domain": "geometry_spatial",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：正方体截面与立体切割",
        "aliases": ["正方体截面", "立体切割", "一刀切掉", "切面", "截面形状", "截面是几边形"],
        "required_fact_groups": [["solid_geometry"], ["view_projection"]],
        "exclude_fact_keys": ["school_cube_net"],
        "confusable_with": ["认识立体图形", "立体几何", "正方体展开图"],
        "positive_examples": ["一个正方体一刀切掉一块，判断露出的截面在一个平面上是什么边形。"],
        "near_miss_examples": ["只认识正方体、长方体等立体图形名称，不涉及切割截面。"],
        "negative_examples": ["正方体展开图相对面判断、普通立体图形认知或圆柱体积计算。"],
        "source_refs": ["curated:placement_exam_1:q9"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.cube_net_opposite_faces",
        "name": "正方体展开图相对面判断",
        "domain": "geometry_spatial",
        "level": "L2",
        "quality_status": "approved",
        "knowledge_track": "school",
        "knowledge_track_label": "校内",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "下册",
        "knowledge_display_name": "校内五年级：正方体展开图相对面判断",
        "aliases": ["正方体相对面", "展开图相对面", "相邻面判断", "折成正方体", "对面的字", "六个面", "哪些是相对面"],
        "required_fact_groups": [["school_cube_net"], ["solid_geometry"]],
        "exclude_fact_keys": ["fold_cut_unfold"],
        "confusable_with": ["认识立体图形", "折叠展开与剪纸问题"],
        "positive_examples": ["根据正方体展开图判断写有文字的六个面中哪些互为相对面。"],
        "near_miss_examples": ["只判断一个平面图形是不是轴对称图形。"],
        "negative_examples": ["纸片对折剪开后的展开图，或普通正方体体积、表面积计算。"],
        "source_refs": ["curated:placement_exam_6:q8", "curated:placement_exam_9:q21"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.unit_cube_surface_area",
        "name": "小正方体拼搭表面积",
        "domain": "geometry_spatial",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "school",
        "knowledge_track_label": "校内",
        "knowledge_grade": "5",
        "knowledge_grade_label": "五年级",
        "knowledge_semester": "下册",
        "knowledge_display_name": "校内五年级：小正方体拼搭表面积",
        "aliases": ["小正方体拼成", "小正方体拼搭", "露在外面", "外表面积", "总表面积", "积木表面积", "拼成立体图形的表面积"],
        "required_fact_groups": [["solid_geometry"], ["geometry_area"]],
        "exclude_fact_keys": ["cylinder_surface_volume", "gaosi_permutation_combination"],
        "confusable_with": ["排列组合", "立体几何", "圆柱切分后，求表面积"],
        "positive_examples": ["若干个棱长相同的小正方体拼成一个立体图形，求露在外面的总面积。"],
        "near_miss_examples": ["只数有多少个小正方体，不求外表面积。"],
        "negative_examples": ["普通排列组合、圆柱表面积计算或单个长方体表面积公式题。"],
        "source_refs": ["curated:placement_exam_3:q18", "curated:placement_exam_9:q8"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.cylinder_roll_unfold_length",
        "name": "圆柱卷纸侧面展开与层数",
        "domain": "geometry_spatial",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：圆柱卷纸侧面展开与层数",
        "aliases": ["卷纸展开长度", "圆柱彩纸展开", "圆柱形彩纸", "卷纸厚度", "纸张厚度", "纸卷展开", "纸卷完全展开", "展开后长度", "圆柱侧面展开长度"],
        "required_fact_groups": [["cylinder_surface_volume"], ["gaosi_solid_geometry"]],
        "exclude_fact_keys": ["school_cube_net"],
        "confusable_with": ["长度与角度的计算", "圆柱侧面展开与体积守恒"],
        "positive_examples": ["圆柱形彩纸有高度、底面直径和纸张厚度，求彩纸展开后的长度。"],
        "near_miss_examples": ["只根据圆柱底面周长求一圈侧面展开图长。"],
        "negative_examples": ["普通线段长度角度计算或没有卷纸层数、厚度关系的圆柱题。"],
        "source_refs": ["curated:placement_exam_9:q10"],
    },
    {
        "knowledge_point_id": "dim5.pattern_sequence.calendar_week_cycle",
        "name": "日历星期周期",
        "domain": "pattern_sequence",
        "level": "L2",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "3",
        "knowledge_grade_label": "三年级",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数三年级：日历星期周期",
        "aliases": ["星期几", "日历周期", "日期问题", "经过多少天是星期几", "年月日周期", "星期分布"],
        "required_fact_groups": [["sequence_pattern"]],
        "exclude_fact_keys": ["gaosi_reverse_age"],
        "confusable_with": ["还原问题与年龄问题", "周期问题"],
        "positive_examples": ["已知某年某月某日是星期五，求经过若干天后是星期几。"],
        "near_miss_examples": ["只问年龄变化或今年几岁，不涉及星期和日期循环。"],
        "negative_examples": ["年龄还原题、普通时间单位换算或没有7天循环的应用题。"],
        "source_refs": ["curated:placement_exam_2:q3", "curated:placement_exam_5:q24"],
    },
    {
        "knowledge_point_id": "dim5.pattern_sequence.work_rest_cycle",
        "name": "工作休息周期",
        "domain": "pattern_sequence",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：工作休息周期",
        "aliases": ["工作几天休息几天", "工作4天休息1天", "共同休息", "轮班周期", "休息日周期"],
        "required_fact_groups": [["sequence_pattern"]],
        "exclude_fact_keys": ["work_rate_task"],
        "confusable_with": ["工程问题", "日期周期"],
        "positive_examples": ["爸爸工作4天休息1天、妈妈工作2天休息1天，根据日历求共同休息日期。"],
        "near_miss_examples": ["工程合作中甲乙轮流工作求完成时间。"],
        "negative_examples": ["普通工程效率题或没有重复工作休息节奏的日期题。"],
        "source_refs": ["curated:placement_exam_4:q7"],
    },
    {
        "knowledge_point_id": "dim5.pattern_sequence.staircase_recurrence",
        "name": "爬楼梯递推",
        "domain": "pattern_sequence",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：爬楼梯递推",
        "aliases": ["爬楼梯", "一级或两级台阶", "跨一级或两级", "台阶走法", "斐波那契走法"],
        "required_fact_groups": [["state_recurrence"], ["counting_target"]],
        "exclude_fact_keys": ["school_division", "graph_relation_network_counting"],
        "confusable_with": ["普通组合计数", "排列组合"],
        "positive_examples": ["每次只能上一级或两级台阶，求到第5级或第10级台阶有多少种走法。"],
        "near_miss_examples": ["只问爬了几层楼或每层楼高度的普通乘除题。"],
        "negative_examples": ["普通排列组合或没有相邻状态递推关系的计数题。"],
        "source_refs": ["curated:placement_exam_2:q8"],
    },
    {
        "knowledge_point_id": "dim5.pattern_sequence.doubling_notification",
        "name": "电话通知倍增递推",
        "domain": "pattern_sequence",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：电话通知倍增递推",
        "aliases": ["电话通知", "倍增通知", "每分钟倍增", "每分钟通知一人", "通知所有人", "紧急通知", "通知所有队员"],
        "required_fact_groups": [["school_multiplicative_relation"], ["extremum_goal"]],
        "exclude_fact_keys": ["gaosi_divisibility", "gaosi_number_theory"],
        "confusable_with": ["统筹与对策", "整除", "最值问题"],
        "positive_examples": ["老师用打电话方式每分钟倍增通知队员，设计最短方案并求10分钟最多通知人数。"],
        "near_miss_examples": ["普通电话费用计费题。"],
        "negative_examples": ["单纯整除判断、普通最值问题或没有传播倍增过程的安排题。"],
        "source_refs": ["curated:placement_exam_9:q24"],
    },
    {
        "knowledge_point_id": "dim5.pattern_sequence.square_number_sequence_position",
        "name": "平方数序列定位",
        "domain": "pattern_sequence",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：平方数序列定位",
        "aliases": ["完全平方数列", "完全平方数", "非平方数列", "非平方数", "完全平方数和非平方数", "平方数定位", "第99个数", "平方数与非平方数"],
        "required_fact_groups": [["sequence_pattern"], ["period_position"]],
        "exclude_fact_keys": ["school_comparison"],
        "confusable_with": ["简单规律与数列", "周期规律"],
        "positive_examples": ["完全平方数和非平方数按规则混排，求数列中第99个数。"],
        "near_miss_examples": ["只判断一个数是不是完全平方数。"],
        "negative_examples": ["普通等差数列、周期排列或没有平方数定位目标的题。"],
        "source_refs": ["curated:placement_exam_3:q15"],
    },
    {
        "knowledge_point_id": "dim5.pattern_sequence.equation_pattern_generalization",
        "name": "等式规律与公式递推",
        "domain": "pattern_sequence",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：等式规律与公式递推",
        "aliases": ["观察等式", "第n个等式", "写出第n个算式", "等式规律", "公式递推"],
        "required_fact_groups": [["sequence_pattern"], ["calculation_numeric_expression"]],
        "exclude_fact_keys": ["school_division"],
        "confusable_with": ["四则混合运算", "简单规律与数列"],
        "positive_examples": ["观察一组含分数的等式，写出第6个等式和第n个等式并说明。"],
        "near_miss_examples": ["只计算一个给定算式的结果。"],
        "negative_examples": ["普通四则混合运算或没有归纳第n项的计算题。"],
        "source_refs": ["curated:placement_exam_8:q18"],
    },
    {
        "knowledge_point_id": "dim5.logic_strategy.handshake_round_robin",
        "name": "握手问题与比赛轮次",
        "domain": "counting_combinatorics",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：握手问题与比赛轮次",
        "aliases": ["握手问题", "每两人下一局", "循环赛", "比赛轮次", "已下局数", "度数关系"],
        "required_fact_groups": [["graph_relation_network_counting"], ["gaosi_logic"]],
        "exclude_fact_keys": ["school_addition_subtraction", "school_division"],
        "confusable_with": ["普通加减法", "图论基础与关系网络计数"],
        "positive_examples": ["六人下棋每两人下一局，已知若干人已下局数，求某人下了几局。"],
        "near_miss_examples": ["只按总人数平均分组，不涉及两两关系。"],
        "negative_examples": ["普通加减法应用题或没有两两配对关系的计数题。"],
        "source_refs": ["curated:placement_exam_2:q11", "curated:placement_exam_3:q10"],
    },
    {
        "knowledge_point_id": "dim5.logic_strategy.truth_rank_logic",
        "name": "真假话与名次推理",
        "domain": "logic_strategy_construction",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：真假话与名次推理",
        "aliases": ["真假话", "真话假话", "只有一句真话", "名次推理", "我不是第一", "得了前三名", "排名推理"],
        "required_fact_groups": [["gaosi_logic"]],
        "exclude_fact_keys": ["school_comparison"],
        "confusable_with": ["普通比较大小", "逻辑推理"],
        "positive_examples": ["三人取得前三名，每人说一句关于自己名次的话，根据真假关系推理名次。"],
        "near_miss_examples": ["只比较三个数的大小顺序。"],
        "negative_examples": ["普通名数比较或没有真假陈述约束的排序题。"],
        "source_refs": ["curated:placement_exam_3:q20"],
    },
    {
        "knowledge_point_id": "dim5.logic_strategy.balance_scale_search",
        "name": "天平称重找异常物",
        "domain": "logic_strategy_construction",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：天平称重找异常物",
        "aliases": ["天平称重", "较重的一瓶", "较轻的一瓶", "找出盐水", "保证找出", "异常瓶"],
        "required_fact_groups": [["gaosi_logic"], ["guarantee_at_least"], ["extremum_goal"]],
        "exclude_fact_keys": [],
        "confusable_with": ["浓度问题", "抽屉原理"],
        "positive_examples": ["若干瓶矿泉水中有一瓶盐水较重或较轻，问至少用天平称几次能保证找出。"],
        "near_miss_examples": ["盐水加水稀释后求浓度。"],
        "negative_examples": ["普通浓度变化题或没有天平称重过程的最不利原则题。"],
        "source_refs": ["curated:placement_exam_5:q21"],
    },
    {
        "knowledge_point_id": "dim5.logic_strategy.chessboard_queen_control",
        "name": "棋盘控制与皇后覆盖",
        "domain": "logic_strategy_construction",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：棋盘控制与皇后覆盖",
        "aliases": ["棋盘控制", "皇后覆盖", "国际象棋皇后", "控制行列斜线", "黑白棋盘"],
        "required_fact_groups": [["gaosi_logic"]],
        "exclude_fact_keys": ["school_volume"],
        "confusable_with": ["智巧趣题", "棋盘染色"],
        "positive_examples": ["在黑白棋盘上放置皇后，使每个小方格都被行、列或斜线控制。"],
        "near_miss_examples": ["只根据棋盘颜色做奇偶染色论证。"],
        "negative_examples": ["普通平面图形识别或没有棋盘控制规则的计数题。"],
        "source_refs": ["curated:placement_exam_6:q28"],
    },
    {
        "knowledge_point_id": "dim5.quantity_application.full_reduction_optimization",
        "name": "满减凑单与优惠拆单",
        "domain": "quantity_application",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "school",
        "knowledge_track_label": "校内",
        "knowledge_grade": "6",
        "knowledge_grade_label": "六年级",
        "knowledge_semester": "下册",
        "knowledge_display_name": "校内六年级：满减凑单与优惠拆单",
        "aliases": ["满减", "满30减12", "满30元减12", "满60减30", "优惠拆单", "凑单", "如何凑单", "总费用最低"],
        "required_fact_groups": [["counting_choice"], ["price_profit_relation"]],
        "exclude_fact_keys": [],
        "confusable_with": ["排列组合", "普通单价数量总价"],
        "positive_examples": ["多个菜品有满减优惠，选择下单方式使总费用最低。"],
        "near_miss_examples": ["只按单价乘数量直接求总价。"],
        "negative_examples": ["普通组合计数或没有价格优惠目标的选择题。"],
        "source_refs": ["curated:placement_exam_1:q8"],
    },
    {
        "knowledge_point_id": "dim5.quantity_application.tiered_piecewise_pricing",
        "name": "阶梯计费与分段收费",
        "domain": "quantity_application",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "school",
        "knowledge_track_label": "校内",
        "knowledge_grade": "6",
        "knowledge_grade_label": "六年级",
        "knowledge_semester": "下册",
        "knowledge_display_name": "校内六年级：阶梯计费与分段收费",
        "aliases": ["阶梯水价", "分档水量", "阶梯计费", "分段收费", "累计用水", "按档计费"],
        "required_fact_groups": [["price_profit_relation"], ["school_volume"]],
        "exclude_fact_keys": ["gaosi_solid_geometry"],
        "confusable_with": ["体积", "长方体与正方体", "圆柱圆锥"],
        "positive_examples": ["根据阶梯水价表和累计用水量，按不同档位计算应缴水费。"],
        "near_miss_examples": ["只根据长方体水池长宽高求容积。"],
        "negative_examples": ["普通体积单位换算或没有分段单价的立方米题。"],
        "source_refs": ["curated:placement_exam_5:q12"],
    },
    {
        "knowledge_point_id": "dim5.quantity_application.taxi_piecewise_fare",
        "name": "出租车分段计价",
        "domain": "quantity_application",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "school",
        "knowledge_track_label": "校内",
        "knowledge_grade": "6",
        "knowledge_grade_label": "六年级",
        "knowledge_semester": "下册",
        "knowledge_display_name": "校内六年级：出租车分段计价",
        "aliases": ["出租车计价", "起步价", "空驶费", "分段加价", "每公里加价", "中途换车"],
        "required_fact_groups": [["price_profit_relation"]],
        "exclude_fact_keys": ["school_volume"],
        "confusable_with": ["行程问题", "普通单价数量总价"],
        "positive_examples": ["出租车有起步价、超过若干公里后分段加价和空驶费，比较不同乘车方案费用。"],
        "near_miss_examples": ["只根据速度和时间求路程。"],
        "negative_examples": ["普通行程追及题或没有分段费用规则的价格题。"],
        "source_refs": ["curated:placement_exam_9:q23"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.midpoint_equal_area",
        "name": "中点面积与等底等高",
        "domain": "geometry_spatial",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：中点面积与等底等高",
        "aliases": ["中点面积", "等底等高", "中线平分面积", "三角形面积关系", "阴影部分面积", "AM=BM", "CN=AN"],
        "required_fact_groups": [["midline_or_midpoint"], ["geometry_area"]],
        "exclude_fact_keys": ["basic_formula"],
        "confusable_with": ["三角形面积", "面积比模型"],
        "positive_examples": ["三角形中给出中点和线段关系，利用等底等高或中线平分面积求阴影面积。"],
        "near_miss_examples": ["直接给底和高套三角形面积公式。"],
        "negative_examples": ["没有中点、中线或等底等高关系的基础面积题。"],
        "source_refs": ["curated:placement_exam_2:q6"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.inscribed_square_circle_area",
        "name": "圆内接正方形面积",
        "domain": "geometry_spatial",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：圆内接正方形面积",
        "aliases": ["圆内最大正方形", "圆内接正方形", "正方形在圆内", "圆中取最大正方形", "阴影面积"],
        "required_fact_groups": [["gaosi_circle_sector"], ["geometry_area"], ["extremum_goal"]],
        "exclude_fact_keys": ["statistics_chart_context"],
        "confusable_with": ["圆与扇形", "最值问题"],
        "positive_examples": ["圆中取最大正方形，已知圆半径或直径，求阴影面积。"],
        "near_miss_examples": ["普通扇形面积或圆心角统计图读数。"],
        "negative_examples": ["只计算普通圆面积、扇形面积或不含内接正方形的最值题。"],
        "source_refs": ["curated:placement_exam_3:q23"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.curvilinear_arch_area",
        "name": "曲边图形面积与弓形面积",
        "domain": "geometry_spatial",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：曲边图形面积与弓形面积",
        "aliases": ["弧形面积", "弓形面积", "曲边图形面积", "圆弧围成", "四分之一圆弧", "弧围成区域"],
        "required_fact_groups": [["gaosi_circle_sector"], ["geometry_area"]],
        "exclude_fact_keys": ["statistics_chart_context"],
        "confusable_with": ["圆与扇形", "基础几何公式应用"],
        "positive_examples": ["多个圆弧围成曲边区域，利用扇形和三角形面积关系求面积。"],
        "near_miss_examples": ["只根据圆心角和半径直接求单个扇形面积。"],
        "negative_examples": ["统计图中的扇形或没有曲边区域分解的圆面积题。"],
        "source_refs": ["curated:placement_exam_6:q16"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.pythagorean_area_relation",
        "name": "勾股面积关系",
        "domain": "geometry_spatial",
        "level": "L3",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：勾股面积关系",
        "aliases": ["勾股面积", "斜边上的正方形", "三个正方形面积", "直角三角形三边面积", "直角三角形三边上正方形", "三边上分别作正方形", "弦图面积"],
        "required_fact_groups": [["geometry_area"], ["geometry_triangle"], ["area_relation_model"]],
        "exclude_fact_keys": ["swallowtail_area_model"],
        "confusable_with": ["三角形面积", "赵爽弦图"],
        "positive_examples": ["三个正方形分别建在直角三角形三边上，利用面积关系求中间三角形面积。"],
        "near_miss_examples": ["直接用底乘高除以2求三角形面积。"],
        "negative_examples": ["普通三角形面积公式题或没有勾股面积关系的正方形面积题。"],
        "source_refs": ["curated:placement_exam_6:q19"],
    },
    {
        "knowledge_point_id": "dim5.geometry_spatial.circle_rectangle_overlap_area",
        "name": "方圆重叠面积",
        "domain": "geometry_spatial",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：方圆重叠面积",
        "aliases": ["扇形和长方形重叠", "方圆重叠", "圆与长方形重叠", "重叠阴影面积", "公共部分面积"],
        "required_fact_groups": [["overlap_area"], ["gaosi_circle_sector"], ["geometry_area"]],
        "exclude_fact_keys": ["statistics_chart_context"],
        "confusable_with": ["圆与扇形", "重叠面积与容斥面积"],
        "positive_examples": ["扇形和长方形重叠，已知长方形边长和圆的半径关系，求阴影面积。"],
        "near_miss_examples": ["两个正方形重叠求公共部分面积。"],
        "negative_examples": ["普通圆或扇形面积计算，或没有方圆重叠结构的面积题。"],
        "source_refs": ["curated:placement_exam_10:q9"],
    },
    {
        "knowledge_point_id": "dim5.number_theory.congruence_remainder_system",
        "name": "同余与余数问题",
        "domain": "number_theory",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：同余与余数问题",
        "aliases": ["同余问题", "余数问题", "被7除余2", "被5除余3", "被8除余3", "被9除余1", "除余", "中国剩余"],
        "required_fact_groups": [["gaosi_remainder"], ["period_position"]],
        "exclude_fact_keys": ["school_comparison"],
        "confusable_with": ["数的大小比较", "整除"],
        "positive_examples": ["小于200的自然数，被7除余2、被8除余3、被9除余1，求这个数。"],
        "near_miss_examples": ["只做一个除法算式求余数。"],
        "negative_examples": ["普通大小比较或没有多个除数余数条件的整除题。"],
        "source_refs": ["curated:placement_exam_4:q3"],
    },
    {
        "knowledge_point_id": "dim5.number_theory.place_value_digit_equation",
        "name": "位值制数字谜",
        "domain": "number_theory",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：位值制数字谜",
        "aliases": ["位值制数字谜", "abc表示三位数", "abc表示一个三位数", "全体两位数的和", "数位方程", "由数字组成的数"],
        "required_fact_groups": [["gaosi_place_value_principle"]],
        "exclude_fact_keys": ["school_comparison", "digit_swap_multiple", "divisibility_rule"],
        "confusable_with": ["位值原理", "整除"],
        "positive_examples": ["abc表示一个三位数，等于由a、b、c组成的全体两位数的和，求满足条件的三位数。"],
        "near_miss_examples": ["只交换两位数字后比较大小。"],
        "negative_examples": ["普通数字大小比较或没有位值表达式约束的数论题。"],
        "source_refs": ["curated:placement_exam_4:q8"],
    },
    {
        "knowledge_point_id": "dim5.number_theory.vertical_arithmetic_puzzle",
        "name": "竖式数字谜",
        "domain": "number_theory",
        "level": "L4",
        "quality_status": "approved",
        "knowledge_track": "olympiad",
        "knowledge_track_label": "奥数",
        "knowledge_grade": "unknown",
        "knowledge_grade_label": "年级未确认",
        "knowledge_semester": "unknown",
        "knowledge_display_name": "奥数知识：竖式数字谜",
        "aliases": ["竖式数字谜", "残缺乘法竖式", "方框填数字", "使算式成立", "不是2的数字"],
        "required_fact_groups": [["gaosi_vertical_puzzle"]],
        "exclude_fact_keys": ["school_vertical_division"],
        "confusable_with": ["有趣的乘法", "乘法竖式及应用"],
        "positive_examples": ["残缺的乘法竖式中，在方框填入不是2的数字，使乘法竖式成立。"],
        "near_miss_examples": ["普通乘法竖式计算，不需要推理未知数字。"],
        "negative_examples": ["没有未知数字约束的笔算乘法或普通数字谜。"],
        "source_refs": ["curated:placement_exam_2:q9"],
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
    text = re.sub(r"^\d+[、.．]\s*", "", text)
    text = re.sub(r"^\d+\s+", "", text)
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
        add_group("division_quotient_digit_zero")
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
    add_group("school_24_point_mixed_operation")
    add_group("school_operation_law")
    add_group("school_fraction")
    add_group("fraction_whole_part_relation")
    add_group("school_reciprocal_concept")
    add_group("school_decimal")
    add_group("school_equation")
    add_group("school_symbol_equation_substitution")
    add_group("school_comparison")
    add_group("school_division_representation")
    add_group("school_multiplicative_relation")
    add_group("perimeter_scale_relation")

    if "school_geometry_motion" in matched:
        add_group("school_geometry_motion")
        add_group("school_translation", "school_rotation")
    add_group("school_axisymmetry")
    if "school_perimeter" in matched:
        add_group("school_perimeter", "school_square_tiling_perimeter")
        add_group("school_rectangle_square", "school_square_tiling_perimeter")
        add_group("school_irregular_perimeter")
        add_group("perimeter_scale_relation")
        add_group("folded_perimeter_change")
        add_group("polygon_perimeter")
        add_group("rectangle_tiling_min_perimeter")
    add_group("school_rectangle_property")
    add_group("school_cube_net")
    add_group("school_area")
    add_group("school_volume")
    add_group("school_statistics")
    add_group("school_probability")
    add_group("school_prime_factorization")

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


def curated_base_topic_nodes(existing_nodes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    curated_by_id = {
        str(item.get("knowledge_point_id") or "").strip(): dict(item)
        for item in CURATED_BASE_TOPICS
        if str(item.get("knowledge_point_id") or "").strip()
    }
    seen_ids: set[str] = set()
    nodes: List[Dict[str, Any]] = []
    for node in existing_nodes:
        node_id = str(node.get("knowledge_point_id") or "").strip()
        if node_id in curated_by_id:
            nodes.append(_apply_exam_1_10_boundary_metadata(dict(curated_by_id[node_id])))
        else:
            nodes.append(_apply_exam_1_10_boundary_metadata(dict(node)))
        if node_id:
            seen_ids.add(node_id)
    for node_id, item in curated_by_id.items():
        if node_id not in seen_ids:
            nodes.append(_apply_exam_1_10_boundary_metadata(dict(item)))
    return nodes


def _append_unique_texts(value: Any, additions: Sequence[str]) -> List[str]:
    result = [str(item).strip() for item in value or [] if str(item).strip()]
    for item in additions:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def _apply_exam_1_10_boundary_metadata(node: Dict[str, Any]) -> Dict[str, Any]:
    name = str(node.get("name") or "")
    excludes: List[str] = [str(item).strip() for item in node.get("exclude_fact_keys") or [] if str(item).strip()]
    negative_examples: List[str] = [
        str(item).strip() for item in node.get("negative_examples") or [] if str(item).strip()
    ]
    confusable_with: List[str] = [str(item).strip() for item in node.get("confusable_with") or [] if str(item).strip()]

    def add_excludes(*keys: str) -> None:
        excludes.extend(key for key in keys if key)

    def add_negative(*examples: str) -> None:
        negative_examples.extend(example for example in examples if example)

    def add_confusable(*items: str) -> None:
        confusable_with.extend(item for item in items if item)

    if "浓度" in name:
        add_excludes("guarantee_at_least")
        add_negative("天平称重找异常盐水瓶属于称重策略，不属于浓度变化。")
        add_confusable("天平称重找异常物")
    if any(term in name for term in ("体积", "容积", "立体几何", "长方体与正方体", "圆柱圆锥")):
        add_excludes("price_profit_relation")
        add_negative("阶梯水价中的立方米是计费单位，不属于体积或立体几何。")
        add_confusable("阶梯计费与分段收费")
    if name == "排列组合":
        add_excludes("solid_geometry", "geometry_area")
        add_negative("小正方体拼搭表面积属于立体几何面积，不属于排列组合。")
        add_confusable("小正方体拼搭表面积")
    if "长度与角度" in name:
        add_excludes("cylinder_surface_volume")
        add_negative("圆柱卷纸展开长度属于圆柱侧面展开与层数关系，不属于普通长度与角度计算。")
        add_confusable("圆柱卷纸侧面展开与层数")
    if "还原问题" in name or "年龄问题" in name:
        add_excludes("sequence_pattern")
        add_negative("日期星期周期中的“今年/经过”不是年龄还原。")
        add_confusable("日历星期周期")
    if "圆与扇形" in name:
        add_excludes("statistics_chart_context")
        add_negative("统计图中的圆心角是读图比例信息，不属于几何圆与扇形面积。")
        add_negative("圆坐标读图不是普通圆与扇形面积计算。")
        add_confusable("统计图综合", "圆坐标读图")
    if name == "认识立体图形":
        add_excludes("school_cube_net")
        add_negative("正方体展开图相对面判断不应停留在认识立体图形。")
        add_confusable("正方体展开图相对面判断")

    node["exclude_fact_keys"] = list(dict.fromkeys(excludes))
    node["negative_examples"] = list(dict.fromkeys(negative_examples))
    node["confusable_with"] = list(dict.fromkeys(confusable_with))
    return node


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
    exclude_fact_keys: List[str] = []
    if any(term in point_name for term in ("平均", "除法", "分配")):
        exclude_fact_keys.append("pigeonhole")
    if any(term in point_name for term in ("体积", "容积", "长方体", "正方体", "圆柱", "圆锥")):
        exclude_fact_keys.append("price_profit_relation")
    if any(term in point_name for term in ("体积", "容积", "圆柱", "圆锥", "认识立体图形")):
        exclude_fact_keys.append("school_cube_net")
    if any(term in point_name for term in ("乘法", "竖式", "笔算")):
        exclude_fact_keys.append("gaosi_vertical_puzzle")

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
        "exclude_fact_keys": list(dict.fromkeys(exclude_fact_keys)),
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


def gaosi_aliases(
    entries: Sequence[Dict[str, Any]],
    topic: str,
    tree_entries: Sequence[Dict[str, Any]] = (),
) -> List[str]:
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
    aliases.extend(gaosi_tree_aliases(tree_entries))
    aliases = [item for item in aliases if item and item not in GAOSI_BROAD_TOPICS and len(item) > 1]
    return list(dict.fromkeys(aliases))[:40]


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


def gaosi_knowledge_tree_topic(entry: Dict[str, Any]) -> str:
    title = normalize_gaosi_topic(entry.get("title"))
    return GAOSI_KNOWLEDGE_TREE_TITLE_ALIASES.get(title, title)


def load_gaosi_knowledge_tree(reference_dir: Path) -> List[Dict[str, Any]]:
    path = reference_dir / GAOSI_KNOWLEDGE_TREE_FILE
    if not path.exists():
        return []
    return as_entries(load_json(path))


def gaosi_knowledge_tree_by_topic(reference_dir: Path) -> Dict[tuple[str, str], List[Dict[str, Any]]]:
    grouped: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    for entry in load_gaosi_knowledge_tree(reference_dir):
        grade = normalize_school_grade(entry.get("grade"))
        topic = gaosi_knowledge_tree_topic(entry)
        if grade and topic:
            grouped.setdefault((grade, topic), []).append(entry)
    return grouped


def gaosi_tree_aliases(entries: Sequence[Dict[str, Any]]) -> List[str]:
    aliases: List[str] = []
    for entry in entries:
        raw_title = normalize_gaosi_topic(entry.get("title"))
        canonical_title = gaosi_knowledge_tree_topic(entry)
        if raw_title and raw_title != canonical_title:
            aliases.append(raw_title)
        for subtopic in entry.get("subtopics") or []:
            aliases.extend(gaosi_tree_subtopic_aliases(subtopic))
    return list(dict.fromkeys(alias for alias in aliases if gaosi_tree_alias_allowed(alias)))


def gaosi_tree_subtopic_aliases(value: Any) -> List[str]:
    text = normalize_gaosi_topic(value)
    if not text:
        return []
    aliases: List[str] = [text]
    aliases.extend(part.strip() for part in re.split(r"[、/]|与", text) if part.strip())
    aliases.append(re.sub(r"(综合题[一二三四五六]?|综合题|应用题|问题[一二三四五六]?|计算)$", "", text))
    if "柳卡图" in text:
        aliases.append("柳卡图")
    if "一笔画" in text:
        aliases.append("一笔画")
    if "最不利原则" in text:
        aliases.append("最不利原则")
    if "棋盘染色" in text:
        aliases.append("棋盘染色")
    if "分解质因数" in text:
        aliases.append("分解质因数")
    for model in ("蝴蝶模型", "沙漏模型", "燕尾模型", "鸟头模型", "风筝模型"):
        if model in text:
            aliases.append(model)
    return [alias for alias in dict.fromkeys(aliases) if gaosi_tree_alias_allowed(alias)]


def gaosi_tree_alias_allowed(value: str) -> bool:
    text = normalize_gaosi_topic(value)
    if not text or len(text) <= 1:
        return False
    if text in GENERIC_TERMS or text in GAOSI_BROAD_TOPICS or text in GAOSI_TREE_GENERIC_SUBTOPICS:
        return False
    if re.fullmatch(r"[A-Za-z]", text):
        return False
    if text in {"公式计算", "基础计数方法"}:
        return False
    return True


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

    if _gaosi_topic_has(text, "连续奇数", "平方差", "平方数差"):
        return [["square_difference_odd"]]
    if _gaosi_topic_has(text, "数位交换", "交换数字", "交换数位"):
        return [["digit_swap_multiple"]]
    if _gaosi_topic_has(text, "重复数字", "各位数字相同"):
        return [["repeated_digit_number"]]
    if _gaosi_topic_has(text, "整数解", "约数枚举"):
        return [["integer_solution_factorization"]]
    if _gaosi_topic_has(text, "运输费用", "运费", "运输最优"):
        return [["transport_optimization"]]
    if _gaosi_topic_has(text, "条件枚举", "整数拆分"):
        return [["condition_enumeration"], ["integer_split"]]
    if _gaosi_topic_has(text, "二分策略", "信息查找", "最优排查"):
        return [["binary_search_strategy"], ["information_search_strategy"]]

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
    if _gaosi_topic_has(text, "折叠展开", "剪纸", "剪开"):
        return [["fold_cut_unfold"]]
    if _gaosi_topic_has(text, "俄罗斯方块", "图形变换", "平移旋转", "旋转平移"):
        return [["geometry_transform_puzzle"]]
    if _gaosi_topic_has(text, "重叠面积", "重叠部分", "公共部分"):
        return [["overlap_area"], ["geometry_area"]]
    if _gaosi_topic_has(text, "面积比", "面积之比", "等高", "共边"):
        return [["area_ratio_relation"], ["geometry_area"]]
    if _gaosi_topic_has(text, "七巧板"):
        return [["tangram_area"], ["geometry_area"]]
    if _gaosi_topic_has(text, "赵爽弦图", "弦图"):
        return [["zhao_shuang_diagram"], ["geometry_area"]]
    if _gaosi_topic_has(text, "勒洛三角形", "弓形"):
        return [["reuleaux_triangle"], ["gaosi_circle_sector"]]
    if _gaosi_topic_has(text, "圆柱侧面展开", "圆柱"):
        return [["cylinder_surface_volume"]]
    if _gaosi_topic_has(text, "剪拼", "割补"):
        return [["gaosi_cut_paste"]]
    if _gaosi_topic_has(text, "整体法求面积", "旋转割补"):
        return [["rotation_area_transform"], ["area_goal"]]
    if _gaosi_topic_has(text, "蝴蝶模型", "面积比例"):
        return [["butterfly_area_model"], ["geometry_area"], ["area_ratio_relation"]]
    if _gaosi_topic_has(text, "圆", "扇形"):
        return [["gaosi_circle_sector"]]
    if _gaosi_topic_has(text, "立体"):
        return [["gaosi_solid_geometry"]]
    if _gaosi_topic_has(text, "直线形", "长度", "角度", "几何图形"):
        return [["gaosi_geometry_basic"]]

    if _gaosi_topic_has(text, "分数数列"):
        return [["gaosi_sequence"], ["gaosi_arithmetic"]]
    if _gaosi_topic_has(text, "周期格子"):
        return [["periodic_grid"]]
    if _gaosi_topic_has(text, "传数游戏", "状态转移", "递推"):
        return [["state_recurrence"]]
    if _gaosi_topic_has(text, "直线分平面"):
        return [["line_plane_recurrence"]]
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
        excludes.extend(["school_square_tiling_perimeter", "school_perimeter", "solid_geometry", "geometry_area"])
    if "浓度" in topic:
        excludes.append("guarantee_at_least")
    if "立体几何" in topic:
        excludes.append("price_profit_relation")
    if "长度与角度" in topic:
        excludes.append("cylinder_surface_volume")
    if any(term in topic for term in ("几何图形的认知", "直线形计算")):
        excludes.append("cylinder_surface_volume")
    if "还原问题" in topic or "年龄问题" in topic:
        excludes.append("sequence_pattern")
    if "圆与扇形" in topic:
        excludes.append("statistics_chart_context")
    return list(dict.fromkeys(excludes))


def gaosi_source_refs(
    grade: str,
    topic: str,
    entries: Sequence[Dict[str, Any]],
    tree_entries: Sequence[Dict[str, Any]] = (),
) -> List[str]:
    refs: List[str] = []
    for entry in entries[:6]:
        section = str(entry.get("section_label") or entry.get("section_level") or "").strip()
        qno = str(entry.get("question_no") or "").strip()
        page = str(entry.get("page_no") or "").strip()
        refs.append(f"gaosi_question:{grade}年级:{topic}:{section}:p{page}:q{qno}")
    for entry in tree_entries:
        source_ref = str(entry.get("source_ref") or "").strip()
        if source_ref:
            refs.append(source_ref)
    return list(dict.fromkeys(refs)) or [f"gaosi_topic:{grade}年级:{topic}"]


def build_gaosi_nodes(reference_dir: Path, existing_nodes: Sequence[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    path = reference_dir / "reference_standard_gaosi_question_data.json"
    entries = as_entries(load_json(path))
    tree_by_topic = gaosi_knowledge_tree_by_topic(reference_dir)
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
        tree_entries = tree_by_topic.get((grade, topic), [])
        base_aliases = gaosi_aliases(topic_entries, topic)
        required_groups = gaosi_fact_groups(topic, base_aliases, examples)
        aliases = gaosi_aliases(topic_entries, topic, tree_entries)
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
                "source_refs": gaosi_source_refs(grade, topic, topic_entries, tree_entries),
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
        and str(node.get("knowledge_point_id") or "").strip() not in RETIRED_BASE_NODE_IDS
        and not str(node.get("knowledge_point_id") or "").startswith(f"{SCHOOL_NODE_PREFIX}.")
        and not str(node.get("knowledge_point_id") or "").startswith(f"{GAOSI_NODE_PREFIX}.")
    ]
    base_nodes = curated_base_topic_nodes(base_nodes)
    school_nodes, school_review_queue = build_school_nodes(args.reference_dir, base_nodes)
    gaosi_nodes, gaosi_review_queue = build_gaosi_nodes(args.reference_dir, [*base_nodes, *school_nodes])
    payload = {
        "version": str(base_payload.get("version") or "dim5_knowledge_graph_v1"),
        "nodes": [*base_nodes, *school_nodes, *gaosi_nodes],
    }
    payload = localize_dim5_graph_payload(payload)
    args.graph.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
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
        newline="\n",
    )
    (args.output_dir / "dim5_knowledge_graph.build_report.json").write_text(
        json.dumps(
            {**report, "rule_localization": build_dim5_rule_localization_report(payload)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (args.output_dir / "dim5_knowledge_graph.review_queue.json").write_text(
        json.dumps(report["review_queue"], ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
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
