"""Structured knowledge graph matcher for dimension 5.

The graph is intentionally stricter than the legacy Dim5 grounding path:
only approved graph nodes with satisfied structure evidence may become a
confirmed final knowledge point.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from app.services.scoring.dim5_canonical import (
    DIM5_KNOWLEDGE_DOMAINS,
    normalize_dim5_knowledge_level,
)


DIM5_GRAPH_VERSION = "dim5_knowledge_graph_v1"
DIM5_GRAPH_PATH = Path(__file__).with_name("dim5_knowledge_graph.json")
DIM5_CONFIDENCE_STATUSES = {
    "confirmed",
    "broad_category_only",
    "ambiguous",
    "review_required",
}
DIM5_KNOWLEDGE_TRACK_LABELS = {
    "school": "校内",
    "olympiad": "奥数",
    "junior": "初中前置",
    "unknown": "未确认",
}
DIM5_GRADE_LABELS = {
    "1": "一年级",
    "2": "二年级",
    "3": "三年级",
    "4": "四年级",
    "5": "五年级",
    "6": "六年级",
    "7": "七年级",
    "unknown": "年级未确认",
}
DIM5_SEMESTER_VALUES = {"上册", "下册", "unknown"}
GAOSI_NODE_ID_PREFIX = "dim5.gaosi."
STRONG_OLYMPIAD_FACT_KEYS = {
    "fraction_series",
    "telescoping_pattern",
    "circle_circumference_context",
    "circumference_increment",
    "radius_increment_goal",
    "pigeonhole",
    "guarantee_at_least",
    "gaosi_enumeration",
    "gaosi_counting_principle",
    "gaosi_permutation_combination",
    "gaosi_inclusion_exclusion",
    "gaosi_geometric_counting",
    "gaosi_work_rate",
    "gaosi_grazing_clock",
    "gaosi_travel",
    "gaosi_concentration_profit",
    "gaosi_ratio",
    "gaosi_chicken_rabbit",
    "gaosi_lattice",
    "gaosi_cut_paste",
    "gaosi_vertical_puzzle",
    "gaosi_digit_puzzle",
    "palindrome_number_counting",
    "gaosi_place_value_principle",
    "variable_speed_round_trip",
    "travel_equation_same_distance",
    "reverse_surplus_payment_process",
    "swallowtail_area_model",
    "graph_relation_network_counting",
    "statistics_chart_context",
    "statistics_percent_conversion",
    "fraction_application",
    "proportion_application",
    "two_type_cost_total",
    "square_difference_odd",
    "digit_swap_multiple",
    "repeated_digit_number",
    "integer_solution_factorization",
    "fold_cut_unfold",
    "geometry_transform_puzzle",
    "overlap_area",
    "area_ratio_relation",
    "tangram_area",
    "zhao_shuang_diagram",
    "reuleaux_triangle",
    "cylinder_surface_volume",
    "periodic_grid",
    "state_recurrence",
    "line_plane_recurrence",
    "transport_optimization",
    "gaosi_counting_synthesis",
    "gaosi_arithmetic_synthesis",
    "gaosi_number_theory_synthesis",
    "gaosi_geometry_synthesis",
    "gaosi_application_synthesis",
    "defined_operation_rule",
    "defined_operation_symbol",
    "defined_operation_target",
    "consecutive_product_definition",
    "work_progress_ratio",
    "area_decomposition",
    "condition_enumeration",
    "integer_split",
    "rotation_area_transform",
    "overall_area_method",
    "binary_search_strategy",
    "information_search_strategy",
    "butterfly_area_model",
    "perimeter_scale_relation",
    "division_quotient_digit_zero",
    "folded_perimeter_change",
    "polygon_perimeter",
    "rectangle_tiling_min_perimeter",
    "fraction_whole_part_relation",
    "cylinder_surface_volume_composite",
}
GENERIC_CONFIRMATION_FACT_KEYS = {
    "school_comparison",
    "school_division",
    "school_area",
    "geometry_area",
    "geometry_triangle",
    "gaosi_arithmetic",
    "gaosi_circle_sector",
    "number_theory_factor_multiple",
    "integer_constraint",
    "digit_property",
    "school_multiplicative_relation",
}
SPECIFIC_CONFIRMATION_FACT_KEYS = {
    "condition_enumeration",
    "integer_split",
    "rotation_area_transform",
    "binary_search_strategy",
    "information_search_strategy",
    "butterfly_area_model",
    "perimeter_scale_relation",
    "division_quotient_digit_zero",
    "folded_perimeter_change",
    "polygon_perimeter",
    "rectangle_tiling_min_perimeter",
    "fraction_whole_part_relation",
    "cylinder_surface_volume_composite",
    "triangle_angle_classification",
    "cylinder_cone_volume_height_ratio",
    "composite_area_split_relation",
    "cylinder_cone_volume_ratio",
    "number_table_position_pattern",
    "rectangle_area_fraction_percent_change",
}
GENERIC_ALIAS_TERMS = {
    "等于",
    "填上",
    "每个",
    "那么",
    "求最大",
    "整数",
    "数字",
    "计算",
    "求面积",
    "面积计算",
    "/",
    "面积",
    "圆",
    "三角形",
    "倍数",
}
DIM5_LOCALIZATION_ENGLISH_TEMPLATE_MARKERS = (
    "Extract observable",
    "Do not confirm",
    "Each extracted structure",
    "clockwise/counterclockwise",
    "Clockwise/counterclockwise",
    "For grazing",
    "Do not treat",
    "ordinary arithmetic expressions",
    "probability for ordinary counting",
    "ratio application from a colon",
)
DIM5_STRUCTURE_GLOSSARY: Dict[str, str] = {
    "rotation_direction": "顺时针、逆时针等旋转方向词，只说明几何或运动方向",
    "geometry_rotation": "图形绕点或绕中心旋转、转动、旋转后位置变化",
    "geometry_circle": "圆、半圆、扇形、半径、直径、圆心角、弧等圆形几何结构",
    "gaosi_circle_sector": "奥数圆与扇形专题结构，包括扇形面积、弧长、圆心角和割补关系",
    "sector_area": "扇形面积、圆心角与面积比例的计算结构",
    "arc_length_goal": "题目目标是求弧长、圆周长的一部分或弧相关长度",
    "area_goal": "题目目标是求面积、阴影面积或面积关系",
    "geometry_area": "几何面积计算、面积关系、阴影面积或割补面积",
    "school_area": "校内面积知识，如面积单位、面积公式、图形面积",
    "area_decomposition": "通过割补、拼接、分解或组合图形求面积",
    "overall_area_method": "整体法、整体转化、整体割补等面积整体处理方法",
    "rotation_area_transform": "通过图形旋转形成的扇形或割补关系求阴影面积",
    "area_relation_model": "等高、共边、蝴蝶、燕尾、面积比等面积关系模型",
    "butterfly_area_model": "四边形对角线、交点、三角形面积与比例共同构成的蝴蝶面积模型",
    "geometry_triangle": "三角形、三角形边角关系或三角形面积结构",
    "triangle_angle_classification": "根据三角形角度、角度比或角度和判断锐角、直角、钝角或等腰三角形",
    "statistics_chart_context": "统计图、统计表、扇形统计图、条形统计图、折线统计图等读图场景",
    "school_statistics": "校内统计知识，如统计表、平均数、条形/折线/扇形统计图",
    "statistics_percent_conversion": "统计图中百分比、占比、人数或圆心角之间的换算",
    "clock_face": "真实钟面、表盘或时钟刻度结构",
    "clock_hands_relation": "时针、分针之间的追及、重合、夹角或位置关系",
    "time_angle_goal": "题目目标是求时刻、经过时间、钟表夹角或特殊位置",
    "resource_growth": "草量、人流、水量等资源随时间增长或流入",
    "resource_consumption": "牛吃草、检票、抽水等资源被消耗或流出",
    "resource_time_or_initial": "出现原有量、每天、几天、吃完、时间或初始量条件",
    "growth_consumption": "同一问题中同时存在增长和消耗过程",
    "gaosi_grazing_clock": "高思牛吃草或钟表专题结构，需要满足对应完整模型条件",
    "work_rate_task": "工程、合作、单独完成、工作效率、总工程量等工程问题结构",
    "work_efficiency_relation": "工作效率、完成时间、合作效率之间的数量关系",
    "work_progress_ratio": "已完成量、未完成量、剩余工程量之间的比例变化",
    "defined_operation_rule": "题目规定或定义一种新的运算规则",
    "defined_operation_symbol": "题目中出现 ※、△、☆、□ 等自定义运算符号",
    "defined_operation_target": "要求代入或反求新定义运算中的未知量",
    "consecutive_product_definition": "新定义运算被定义为连续整数乘积或类似通项规则",
    "motion_task": "行程、相遇、追及、流水、同向/相向运动等行程问题结构",
    "speed_distance_time": "速度、路程、时间三量关系",
    "profit_discount": "利润、折扣、打折、加价、进价、售价、标价等经济问题结构",
    "price_profit_relation": "价格、成本、售价、利润、利润率之间的数量关系",
    "ratio_relation": "比、比例、按比例分配、几比几等数量关系",
    "whole_part_relation": "整体与部分、总量与分量之间的关系",
    "proportion_application": "比例应用题、比例分配或正反比例应用结构",
    "percent_calculation": "百分数、百分比、占比、折扣或增长率计算",
    "part_whole_count": "部分数量与整体数量之间的计数或比例关系",
    "concentration_task": "浓度、盐水、溶液、含盐率、加水或混合变化问题",
    "mixture_change": "混合、稀释、加入、倒出等浓度变化过程",
    "number_theory_factor_multiple": "因数、倍数、约数、公倍数、公因数等数论结构",
    "gaosi_divisibility": "整除、约数、倍数、质数、合数、因数等奥数数论结构",
    "divisibility_rule": "利用末位、数字和、拆分、倍数特征判断整除",
    "integer_constraint": "整数、自然数、正整数或整除条件限制",
    "digit_property": "数位、个位、十位、百位、数字和或数位交换性质",
    "gaosi_probability": "概率、随机事件、等可能结果、古典概型等概率结构",
    "school_probability": "校内可能性知识，如一定、可能、不可能、随机摸取",
    "counting_target": "题目目标是数方案数、选法数、情况数或总数",
    "counting_choice": "选择、安排、组合、排列、方案等计数选择结构",
    "sequence_pattern": "周期、循环、数列、图形排列、按规律变化等结构",
    "period_position": "用周期或余数定位第 n 项、某一天、某个位置",
    "gaosi_sequence": "高思规律、数列、数表、周期或找规律专题结构",
    "number_table_position_pattern": "数表、表格或多列排列中的周期/余数定位行列位置",
    "fraction_series": "长链分数、分式数列或分数求和结构",
    "telescoping_pattern": "裂项相消、首尾抵消、长链消去等求和结构",
    "school_average_division": "平均分、每份一样多、按人数或组数平均分配",
    "gaosi_average": "平均数、总数除以份数、平均量反推或基准数法",
    "school_division": "除法、被除数、除数、商、余数或平均分计算",
    "division_quotient_digit_zero": "除数是一位数时根据商的位数、中间0或末尾0反推被除数数字",
    "school_mixed_operation": "四则混合运算、运算顺序或脱式计算",
    "calculation_numeric_expression": "明确的数值算式、计算式或运算表达式",
    "multiplicative_sum": "乘法分配律中的乘积和、括号和或同因数结构",
    "equivalent_factor": "提取公因数、凑整或等价变形因子",
    "decimal_fraction_calculation": "小数、分数或小数分数混合计算",
    "pigeonhole": "抽屉原理、最不利情况、保证至少相同",
    "guarantee_at_least": "至少保证、无论怎样都至少出现的结论目标",
    "gaosi_enumeration": "枚举、分类列举、逐情况讨论",
    "condition_enumeration": "在多个条件限制下逐项枚举或排除可能情况",
    "integer_split": "把总数拆成若干个互不相同或满足条件的正整数",
    "gaosi_counting_principle": "加法原理、乘法原理、分类分步计数",
    "gaosi_permutation_combination": "排列、组合、排队、选取或安排",
    "solid_geometry": "立体图形、长方体、正方体、圆柱、圆锥等空间几何",
    "school_volume": "体积、容积、立方单位或立体图形体积公式",
    "cylinder_surface_volume": "圆柱侧面展开、圆柱表面积或体积守恒结构",
    "cylinder_surface_volume_composite": "圆柱表面积、侧面积、体积或容积同时参与的综合题",
    "cylinder_cone_volume_height_ratio": "圆柱和圆锥在等底面积等条件下，由体积比反求高的比",
    "cylinder_cone_volume_ratio": "圆柱和圆锥在同高、半径比或底面积比条件下求体积比",
    "school_cube_net": "正方体展开图、折叠成正方体、相对面或相邻面判断",
    "perimeter_scale_relation": "边长按倍数扩大或缩小时周长同步按倍数变化",
    "folded_perimeter_change": "正方形或长方形对折后周长减少或继续变化",
    "polygon_perimeter": "五边形、阶梯形、多边形或边长相加求周长",
    "rectangle_tiling_min_perimeter": "多个小正方形拼成长方形时通过贴合边使外周长或装饰条最少",
    "fraction_whole_part_relation": "分数应用题中整体总量与两个部分之间的倍比关系",
    "fold_cut_unfold": "折叠、剪纸、剪开后展开或折后图形判断",
    "geometry_transform_puzzle": "图形平移、旋转、拼图或变换拼合约束",
    "overlap_area": "重叠部分、公共部分、覆盖面积或容斥面积",
    "swallowtail_area_model": "燕尾模型、风筝与燕尾面积关系",
    "area_ratio_relation": "面积比、共边等高、面积转化关系",
    "composite_area_split_relation": "长方形、平行四边形等图形分割后，利用阴影面积和宽/边比例求整体面积",
    "rectangle_area_fraction_percent_change": "长方形长和宽按分数比例增减后，求面积变为原来的百分之几",
    "state_recurrence": "状态递推、传数游戏、倒推或状态转移",
    "reverse_process": "倒推还原、从结果反推原始数量",
    "surplus_deficit": "盈亏、多出、不够、剩下等盈亏结构",
    "binary_search_strategy": "通过一次操作把候选范围分成两段并逐步缩小范围",
    "information_search_strategy": "通过测试结果、反馈信息或排查结果确定唯一目标",
}
DIM5_STRUCTURE_KEY_ALIASES: Dict[str, str] = {
    "旋转方向": "rotation_direction",
    "顺时针": "rotation_direction",
    "逆时针": "rotation_direction",
    "几何旋转": "geometry_rotation",
    "图形旋转": "geometry_rotation",
    "圆形几何": "geometry_circle",
    "圆形结构": "geometry_circle",
    "圆与扇形": "geometry_circle",
    "面积目标": "area_goal",
    "求面积": "area_goal",
    "阴影面积": "area_goal",
    "统计图场景": "statistics_chart_context",
    "扇形统计图": "statistics_chart_context",
    "统计图": "statistics_chart_context",
    "统计百分比换算": "statistics_percent_conversion",
    "钟面": "clock_face",
    "表盘": "clock_face",
    "钟表夹角": "time_angle_goal",
    "时针分针关系": "clock_hands_relation",
    "时针与分针": "clock_hands_relation",
    "资源增长": "resource_growth",
    "草量增长": "resource_growth",
    "资源消耗": "resource_consumption",
    "吃完": "resource_consumption",
    "时间原有量": "resource_time_or_initial",
    "原有量时间": "resource_time_or_initial",
    "利润折扣": "profit_discount",
    "价格利润关系": "price_profit_relation",
    "比例关系": "ratio_relation",
    "整体部分关系": "whole_part_relation",
    "整除规则": "divisibility_rule",
    "因数倍数": "number_theory_factor_multiple",
    "概率": "gaosi_probability",
    "找规律": "gaosi_sequence",
    "周期规律": "sequence_pattern",
    "定义新运算": "defined_operation_rule",
    "新定义运算": "defined_operation_rule",
    "自定义运算": "defined_operation_rule",
    "新运算符号": "defined_operation_symbol",
    "定义运算目标": "defined_operation_target",
    "连续乘积定义": "consecutive_product_definition",
    "工程进度比例": "work_progress_ratio",
    "完成量比例": "work_progress_ratio",
    "面积分解": "area_decomposition",
    "图形割补": "area_decomposition",
    "整体法求面积": "overall_area_method",
    "旋转割补面积": "rotation_area_transform",
    "条件枚举": "condition_enumeration",
    "整数拆分": "integer_split",
    "二分策略": "binary_search_strategy",
    "信息查找": "information_search_strategy",
    "蝴蝶模型": "butterfly_area_model",
    "周长倍数关系": "perimeter_scale_relation",
    "商末尾0判断": "division_quotient_digit_zero",
    "折叠周长变化": "folded_perimeter_change",
    "多边形周长": "polygon_perimeter",
    "拼接周长最小": "rectangle_tiling_min_perimeter",
    "分数整体部分关系": "fraction_whole_part_relation",
    "圆柱表面积体积综合": "cylinder_surface_volume_composite",
    "三角形按角分类": "triangle_angle_classification",
    "三角形类型判断": "triangle_angle_classification",
    "圆柱圆锥体积高关系": "cylinder_cone_volume_height_ratio",
    "圆柱圆锥体积比": "cylinder_cone_volume_ratio",
    "数表位置规律": "number_table_position_pattern",
    "长方形面积变化": "rectangle_area_fraction_percent_change",
    "组合图形分割面积": "composite_area_split_relation",
}


@dataclass(frozen=True)
class Dim5GraphNode:
    knowledge_point_id: str
    name: str
    domain: str
    level: str
    aliases: tuple[str, ...]
    required_fact_groups: tuple[tuple[str, ...], ...]
    exclude_fact_keys: tuple[str, ...]
    confusable_with: tuple[str, ...]
    positive_examples: tuple[str, ...]
    near_miss_examples: tuple[str, ...]
    negative_examples: tuple[str, ...]
    source_refs: tuple[str, ...]
    quality_status: str = "review"
    knowledge_track: str = "unknown"
    knowledge_track_label: str = "未确认"
    knowledge_grade: str = "unknown"
    knowledge_grade_label: str = "年级未确认"
    knowledge_semester: str = "unknown"
    knowledge_display_name: str = ""
    required_structures: tuple[tuple[str, ...], ...] = ()
    supporting_structures: tuple[str, ...] = ()
    exclude_structures: tuple[str, ...] = ()
    fact_extraction_hints: tuple[str, ...] = ()
    negative_hints: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Dim5GraphNode":
        level = normalize_dim5_knowledge_level(raw.get("level"))
        name = str(raw.get("name") or "").strip()
        required_fact_groups = tuple(
            tuple(_string_list(group)) for group in raw.get("required_fact_groups") or []
        )
        exclude_fact_keys = tuple(_string_list(raw.get("exclude_fact_keys")))
        required_structures = tuple(
            tuple(_string_list(group)) for group in raw.get("required_structures") or []
        )
        supporting_structures = tuple(_string_list(raw.get("supporting_structures")))
        exclude_structures = tuple(_string_list(raw.get("exclude_structures")))
        track = _normalize_knowledge_track(raw.get("knowledge_track"))
        if track == "unknown":
            track = _infer_knowledge_track(name=name, level=level, source_refs=raw.get("source_refs"))
        grade = _normalize_knowledge_grade(raw.get("knowledge_grade") or raw.get("grade"))
        semester = _normalize_knowledge_semester(
            raw.get("knowledge_semester") or raw.get("semester")
        )
        track_label = str(
            raw.get("knowledge_track_label") or DIM5_KNOWLEDGE_TRACK_LABELS.get(track, "未确认")
        ).strip()
        grade_label = str(
            raw.get("knowledge_grade_label") or DIM5_GRADE_LABELS.get(grade, "年级未确认")
        ).strip()
        display_name = str(raw.get("knowledge_display_name") or "").strip()
        if not display_name:
            display_name = _build_knowledge_display_name(track_label, grade_label, name)
        else:
            display_name = _normalize_knowledge_display_name(
                display_name,
                track_label=track_label,
                grade_label=grade_label,
                name=name,
            )
        return cls(
            knowledge_point_id=str(raw.get("knowledge_point_id") or "").strip(),
            name=name,
            domain=str(raw.get("domain") or "").strip(),
            level=level,
            aliases=tuple(_string_list(raw.get("aliases"))),
            required_fact_groups=required_fact_groups,
            exclude_fact_keys=exclude_fact_keys,
            confusable_with=tuple(_string_list(raw.get("confusable_with"))),
            positive_examples=tuple(_string_list(raw.get("positive_examples"))),
            near_miss_examples=tuple(_string_list(raw.get("near_miss_examples"))),
            negative_examples=tuple(_string_list(raw.get("negative_examples"))),
            source_refs=tuple(_string_list(raw.get("source_refs"))),
            quality_status=str(raw.get("quality_status") or "review").strip(),
            knowledge_track=track,
            knowledge_track_label=track_label,
            knowledge_grade=grade,
            knowledge_grade_label=grade_label,
            knowledge_semester=semester,
            knowledge_display_name=display_name,
            required_structures=required_structures,
            supporting_structures=supporting_structures,
            exclude_structures=exclude_structures,
            fact_extraction_hints=tuple(_string_list(raw.get("fact_extraction_hints"))),
            negative_hints=tuple(_string_list(raw.get("negative_hints"))),
        )

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.knowledge_point_id:
            errors.append("missing knowledge_point_id")
        if not self.name:
            errors.append("missing name")
        if self.domain not in DIM5_KNOWLEDGE_DOMAINS:
            errors.append(f"invalid domain: {self.domain}")
        if not self.level:
            errors.append("missing or invalid level")
        if not self.required_fact_groups:
            errors.append("missing required_fact_groups")
        if not self.required_structures:
            errors.append("missing required_structures")
        if not self.source_refs:
            errors.append("missing source_refs")
        if not self.fact_extraction_hints:
            errors.append("missing fact_extraction_hints")
        if not self.negative_hints:
            errors.append("missing negative_hints")
        if self.quality_status == "approved" and (
            not self.positive_examples or not self.negative_examples
        ):
            errors.append("approved node must include positive and negative examples")
        if self.quality_status == "approved" and self.knowledge_track not in DIM5_KNOWLEDGE_TRACK_LABELS:
            errors.append(f"invalid knowledge_track: {self.knowledge_track}")
        if self.quality_status == "approved" and not self.knowledge_display_name:
            errors.append("approved node must include knowledge_display_name")
        if (
            self.quality_status == "approved"
            and self.knowledge_track == "school"
            and self.knowledge_point_id.startswith("dim5.school.")
            and self.knowledge_grade == "unknown"
        ):
            errors.append("approved school node must include knowledge_grade")
        return errors


@dataclass(frozen=True)
class Dim5KnowledgeGraph:
    version: str
    nodes: tuple[Dim5GraphNode, ...]

    @classmethod
    def load(cls, path: Path = DIM5_GRAPH_PATH) -> "Dim5KnowledgeGraph":
        payload = json.loads(path.read_text(encoding="utf-8"))
        nodes = tuple(Dim5GraphNode.from_dict(item) for item in payload.get("nodes") or [])
        graph = cls(version=str(payload.get("version") or DIM5_GRAPH_VERSION), nodes=nodes)
        errors = graph.validate()
        if errors:
            raise ValueError("Invalid Dim5 knowledge graph: " + "; ".join(errors[:12]))
        return graph

    @property
    def approved_nodes(self) -> tuple[Dim5GraphNode, ...]:
        return tuple(node for node in self.nodes if node.quality_status == "approved")

    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.version != DIM5_GRAPH_VERSION:
            errors.append(f"unexpected graph version: {self.version}")
        seen: set[str] = set()
        for node in self.nodes:
            if node.knowledge_point_id in seen:
                errors.append(f"duplicate knowledge_point_id: {node.knowledge_point_id}")
            seen.add(node.knowledge_point_id)
            errors.extend(f"{node.knowledge_point_id}: {error}" for error in node.validate())
        return errors


@dataclass(frozen=True)
class StructureFact:
    fact_key: str
    fact_type: str
    evidence: str
    source: str = "question_text"

    def as_dict(self) -> Dict[str, str]:
        return {
            "fact_key": self.fact_key,
            "fact_type": self.fact_type,
            "evidence": self.evidence,
            "source": self.source,
        }


@dataclass
class Dim5GraphCandidate:
    node: Dim5GraphNode
    candidate_status: str
    score: float
    matched_fact_keys: List[str] = field(default_factory=list)
    matched_aliases: List[str] = field(default_factory=list)
    missing_required_fact_groups: List[List[str]] = field(default_factory=list)
    blocked_by_fact_keys: List[str] = field(default_factory=list)
    missing_evidence_fact_keys: List[str] = field(default_factory=list)
    matched_evidence: List[str] = field(default_factory=list)
    matched_supporting_fact_keys: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.node.knowledge_point_id,
            "knowledge_point_id": self.node.knowledge_point_id,
            "knowledge_point_name": self.node.name,
            "knowledge_domain": self.node.domain,
            "knowledge_level": self.node.level,
            "knowledge_track": self.node.knowledge_track,
            "knowledge_track_label": self.node.knowledge_track_label,
            "knowledge_grade": self.node.knowledge_grade,
            "knowledge_grade_label": self.node.knowledge_grade_label,
            "knowledge_semester": self.node.knowledge_semester,
            "knowledge_display_name": self.node.knowledge_display_name,
            "candidate_status": self.candidate_status,
            "score": round(float(self.score), 3),
            "matched_fact_keys": self.matched_fact_keys,
            "matched_required_structures": self.matched_fact_keys,
            "matched_supporting_structures": self.matched_supporting_fact_keys,
            "matched_exclude_structures": self.blocked_by_fact_keys,
            "matched_aliases": self.matched_aliases,
            "missing_required_fact_groups": self.missing_required_fact_groups,
            "blocked_by_fact_keys": self.blocked_by_fact_keys,
            "missing_evidence_fact_keys": self.missing_evidence_fact_keys,
            "matched_evidence": self.matched_evidence[:6],
            "evidence": self.matched_evidence[:6],
            "candidate_score": round(float(self.score), 3),
            "confusable_with": list(self.node.confusable_with),
            "source_refs": list(self.node.source_refs),
            "required_structures": [list(group) for group in self.node.required_structures],
            "supporting_structures": list(self.node.supporting_structures),
            "exclude_structures": list(self.node.exclude_structures),
            "fact_extraction_hints": list(self.node.fact_extraction_hints),
            "negative_hints": list(self.node.negative_hints),
        }


class Dim5StructureExtractor:
    """Extract Dim5-only structure facts from the original question text."""

    _MATH_EXPRESSION_RE = re.compile(
        r"\d+(?:\.\d+)?\s*(?:[+\-*/×÷]|\\times|脳)\s*\d+(?:\.\d+)?"
    )
    _FRACTION_CHAIN_RE = re.compile(
        r"\d+\s*/\s*\(?\s*\d+\s*(?:[×*x脳]\s*\d+)?\s*\)?.*?(?:\+|\.{3}|…)"
    )

    def extract(self, question_text: str, *, question_type: str = "") -> List[Dict[str, str]]:
        text = _normalize_text(question_text)
        question_type = str(question_type or "").strip().lower()
        facts: Dict[str, StructureFact] = {}

        def add(key: str, fact_type: str, evidence: str) -> None:
            evidence = str(evidence or "").strip()
            if evidence and key not in facts:
                facts[key] = StructureFact(key, fact_type, evidence[:80])

        def add_terms(key: str, fact_type: str, terms: Sequence[str]) -> bool:
            evidence = _first_term(text, terms)
            if evidence:
                add(key, fact_type, evidence)
                return True
            return False

        math_match = self._MATH_EXPRESSION_RE.search(text)
        if math_match or question_type == "calculation":
            if math_match:
                add("calculation_numeric_expression", "expression", math_match.group(0))
            elif re.search(r"\d", text):
                add("calculation_numeric_expression", "expression", text[:40])

        if _has_multiplicative_sum(text):
            add("multiplicative_sum", "operation_structure", _expression_excerpt(text))
        if _has_equivalent_factor(text):
            add("equivalent_factor", "operation_structure", _expression_excerpt(text))
        if add_terms("decimal_fraction_calculation", "number_form", ("小数", "分数", "四则", "混合运算")):
            pass
        elif "calculation_numeric_expression" in facts and re.search(r"\d+\.\d+|\d+/\d+", text):
            add("decimal_fraction_calculation", "number_form", _expression_excerpt(text))

        if add_terms("percent_calculation", "ratio_percent", ("百分比", "占比", "百分数", "百分之", "%")):
            pass
        if add_terms("part_whole_count", "quantity_relation", ("占", "总字数", "总数", "全诗", "出现次数")):
            pass
        fraction_whole_part_evidence = _fraction_whole_part_relation_evidence(text)
        if fraction_whole_part_evidence:
            add("school_fraction", "school_number_form", fraction_whole_part_evidence)
            add("fraction_application", "quantity_relation", fraction_whole_part_evidence)
            add("whole_part_relation", "quantity_relation", fraction_whole_part_evidence)
            add("fraction_whole_part_relation", "quantity_relation", fraction_whole_part_evidence)

        defined_operation_evidence = _defined_operation_rule_evidence(text)
        if defined_operation_evidence:
            add("defined_operation_rule", "operation_structure", defined_operation_evidence)
            symbol_evidence = _defined_operation_symbol_evidence(text)
            if symbol_evidence:
                add("defined_operation_symbol", "operation_structure", symbol_evidence)
            target_evidence = _defined_operation_target_evidence(text)
            if target_evidence:
                add("defined_operation_target", "operation_goal", target_evidence)
            consecutive_product_evidence = _consecutive_product_definition_evidence(text)
            if consecutive_product_evidence:
                add("consecutive_product_definition", "operation_structure", consecutive_product_evidence)

        division_evidence = _school_division_evidence(text)
        if division_evidence:
            add("school_division", "school_operation", division_evidence)
        unit_division_evidence = _school_unit_division_context_evidence(text)
        if unit_division_evidence:
            add("school_unit_division_context", "school_quantity_relation", unit_division_evidence)
        if division_evidence and add_terms(
            "school_one_digit_divisor",
            "school_operation",
            ("除数是一位数", "除以一位数", "一位数除", "一位数的除法"),
        ):
            pass
        if division_evidence and add_terms(
            "school_quotient_digit",
            "school_operation",
            ("商的位数", "商是几位数", "商是两位数", "商是三位数", "商中间", "商末尾"),
        ):
            pass
        quotient_zero_evidence = _division_quotient_digit_zero_evidence(text)
        if quotient_zero_evidence:
            add("school_division", "school_operation", quotient_zero_evidence)
            add("school_one_digit_divisor", "school_operation", quotient_zero_evidence)
            add("school_quotient_digit", "school_operation", quotient_zero_evidence)
            add("division_quotient_digit_zero", "school_operation", quotient_zero_evidence)
        if division_evidence and add_terms(
            "school_division_estimation",
            "school_operation",
            ("除法估算", "估算", "大约", "约等于", "近似", "整十", "整百", "整千"),
        ):
            pass
        if division_evidence and add_terms(
            "school_vertical_division",
            "school_operation",
            ("竖式", "笔算", "验算"),
        ):
            pass
        if (division_evidence or unit_division_evidence) and add_terms(
            "school_division_representation",
            "school_operation",
            ("计算方法", "点阵图", "算盘图", "数的分解", "分解计算", "多种方法"),
        ):
            pass
        if add_terms(
            "school_average_division",
            "school_quantity_relation",
            ("平均分", "平均", "每份", "每组", "每人", "每行"),
        ):
            pass
        if add_terms("school_zero_operation", "school_operation", ("0的运算", "0 的运算", "有关0", "中间有0", "末尾有0")):
            pass
        if add_terms("school_mixed_operation", "school_operation", ("混合运算", "四则运算", "运算顺序", "脱式", "递等式")):
            pass
        if add_terms("school_parentheses_order", "school_operation", ("括号", "小括号", "中括号", "先算")):
            pass
        point_24_evidence = _school_24_point_evidence(text)
        if point_24_evidence:
            add("school_mixed_operation", "school_operation", point_24_evidence)
            add("school_parentheses_order", "school_operation", point_24_evidence)
            add("school_24_point_mixed_operation", "school_operation", point_24_evidence)
        if add_terms("school_operation_law", "school_operation", ("结合律", "交换律", "分配律", "运算定律", "简便运算")):
            pass
        if add_terms("school_addition_subtraction", "school_operation", ("加法", "减法", "加、减", "加减", "+", "-")):
            pass
        if not _has_counting_principle_context(text) and add_terms("school_multiplication", "school_operation", ("乘法", "乘以", "乘", "×", "*")):
            pass
        if add_terms("school_fraction", "school_number_form", ("分数", "几分之", "真分数", "假分数", "带分数", "通分", "约分")):
            pass
        fraction_application_evidence = _fraction_application_evidence(text)
        if fraction_application_evidence:
            add("school_fraction", "school_number_form", fraction_application_evidence)
            add("fraction_application", "quantity_relation", fraction_application_evidence)
        reciprocal_evidence = _school_reciprocal_concept_evidence(text)
        if reciprocal_evidence:
            add("school_reciprocal_concept", "school_number_form", reciprocal_evidence)
        if add_terms("school_decimal", "school_number_form", ("小数", "小数点", "十分位", "百分位")):
            pass
        if add_terms("school_equation", "school_operation", ("方程", "未知数", "解方程", "x", "X")):
            pass
        symbol_equation_evidence = _school_symbol_equation_substitution_evidence(text)
        if symbol_equation_evidence:
            add("school_equation", "school_operation", symbol_equation_evidence)
            add("school_symbol_equation_substitution", "school_operation", symbol_equation_evidence)
        if add_terms("school_comparison", "school_operation", ("比较大小", "填上", ">", "<", "大于", "小于", "等于")):
            pass
        if add_terms(
            "school_multiplicative_relation",
            "school_quantity_relation",
            ("倍数关系", "几倍", "倍", "扩大到", "缩小到", "倍增", "每分钟通知", "每分钟每人", "通知一人", "通知所有人"),
        ):
            pass
        perimeter_scale_evidence = _perimeter_scale_relation_evidence(text)
        if perimeter_scale_evidence:
            add("school_multiplicative_relation", "school_quantity_relation", perimeter_scale_evidence)
            add("school_perimeter", "school_geometry", perimeter_scale_evidence)
            add("school_rectangle_square", "school_geometry", perimeter_scale_evidence)
            add("perimeter_scale_relation", "school_geometry", perimeter_scale_evidence)
        if add_terms("school_translation", "school_geometry", ("平移", "平移后", "火箭升空", "电梯", "升降", "直线运动")):
            pass
        if add_terms("rotation_direction", "geometry_motion", ("顺时针", "逆时针")):
            pass
        if add_terms("school_rotation", "school_geometry", ("旋转", "旋转后", "荡秋千", "风车", "转动", "钟摆", "车轮", "开关门")):
            pass
        if "rotation_direction" in facts or "school_rotation" in facts:
            rotation_fact = facts.get("rotation_direction") or facts.get("school_rotation")
            add("geometry_rotation", "geometry_motion", rotation_fact.evidence if rotation_fact else "rotation")
        if "school_translation" in facts or "school_rotation" in facts or add_terms(
            "school_geometry_motion",
            "school_geometry",
            ("运动现象", "图形的运动", "物体运动", "火箭升空", "荡秋千", "风车", "电梯", "转动"),
        ):
            add("school_geometry_motion", "school_geometry", _first_term(text, ("运动现象", "图形的运动", "火箭升空", "荡秋千", "平移", "旋转")) or text[:40])
        if add_terms("school_axisymmetry", "school_geometry", ("轴对称", "对称轴", "对称图形", "补全轴对称")):
            pass
        if add_terms("school_perimeter", "school_geometry", ("周长", "围一圈", "边长之和")):
            pass
        if "school_perimeter" in facts and add_terms(
            "school_rectangle_square",
            "school_geometry",
            ("长方形", "正方形", "长和宽", "边长"),
        ):
            pass
        square_tiling_perimeter = _school_square_tiling_perimeter_evidence(text)
        if square_tiling_perimeter:
            add("school_perimeter", "school_geometry", square_tiling_perimeter)
            add("school_rectangle_square", "school_geometry", square_tiling_perimeter)
            add("school_square_tiling_perimeter", "school_geometry", square_tiling_perimeter)
        rectangle_tiling_min_evidence = _rectangle_tiling_min_perimeter_evidence(text)
        if rectangle_tiling_min_evidence:
            add("school_perimeter", "school_geometry", rectangle_tiling_min_evidence)
            add("school_rectangle_square", "school_geometry", rectangle_tiling_min_evidence)
            add("school_square_tiling_perimeter", "school_geometry", rectangle_tiling_min_evidence)
            add("rectangle_tiling_min_perimeter", "school_geometry", rectangle_tiling_min_evidence)
        rectangle_property = _school_rectangle_property_evidence(text)
        if rectangle_property:
            add("school_rectangle_property", "school_geometry", rectangle_property)
        if "school_perimeter" in facts and add_terms(
            "school_irregular_perimeter",
            "school_geometry",
            ("不规则图形", "平移法", "多边形", "组合图形"),
        ):
            pass
        folded_perimeter_evidence = _folded_perimeter_change_evidence(text)
        if folded_perimeter_evidence:
            add("school_perimeter", "school_geometry", folded_perimeter_evidence)
            add("school_rectangle_square", "school_geometry", folded_perimeter_evidence)
            add("folded_perimeter_change", "school_geometry", folded_perimeter_evidence)
        polygon_perimeter_evidence = _polygon_perimeter_evidence(text)
        if polygon_perimeter_evidence:
            add("school_perimeter", "school_geometry", polygon_perimeter_evidence)
            add("school_irregular_perimeter", "school_geometry", polygon_perimeter_evidence)
            add("polygon_perimeter", "school_geometry", polygon_perimeter_evidence)
        if add_terms("school_area", "school_geometry", ("面积", "平方厘米", "平方米", "平方分米", "底", "高")):
            pass
        if add_terms("school_volume", "school_geometry", ("体积", "容积", "立方厘米", "立方米", "长方体", "正方体", "圆柱", "圆锥")):
            pass
        composite_area_split_evidence = _composite_area_split_relation_evidence(text)
        if composite_area_split_evidence:
            add("school_area", "school_geometry", composite_area_split_evidence)
            add("geometry_area", "geometry", composite_area_split_evidence)
            add("area_goal", "goal", composite_area_split_evidence)
            add("area_decomposition", "geometry_structure", composite_area_split_evidence)
            add("composite_area_split_relation", "geometry_structure", composite_area_split_evidence)
        rectangle_area_change_evidence = _rectangle_area_fraction_percent_change_evidence(text)
        if rectangle_area_change_evidence:
            add("school_area", "school_geometry", rectangle_area_change_evidence)
            add("geometry_area", "geometry", rectangle_area_change_evidence)
            add("school_rectangle_square", "school_geometry", rectangle_area_change_evidence)
            add("school_fraction", "school_number_form", rectangle_area_change_evidence)
            add("percent_calculation", "ratio_percent", rectangle_area_change_evidence)
            add("rectangle_area_fraction_percent_change", "geometry_structure", rectangle_area_change_evidence)
        cube_net_evidence = _school_cube_net_evidence(text)
        if cube_net_evidence:
            add("solid_geometry", "geometry", cube_net_evidence)
            add("school_cube_net", "school_geometry", cube_net_evidence)
        if add_terms("school_statistics", "school_statistics", ("统计图", "统计表", "平均数", "条形统计图", "折线统计图", "扇形统计图")):
            pass
        statistics_chart_evidence = _statistics_chart_context_evidence(text)
        if statistics_chart_evidence:
            add("school_statistics", "school_statistics", statistics_chart_evidence)
            add("statistics_chart_context", "school_statistics", statistics_chart_evidence)
        statistics_percent_evidence = _statistics_percent_conversion_evidence(text)
        if statistics_percent_evidence:
            add("school_statistics", "school_statistics", statistics_percent_evidence)
            add("statistics_chart_context", "school_statistics", statistics_percent_evidence)
            add("statistics_percent_conversion", "quantity_relation", statistics_percent_evidence)
        if add_terms("school_probability", "school_statistics", ("可能性", "一定", "不可能", "随机")):
            pass

        if add_terms("number_theory_factor_multiple", "number_theory", ("因数", "倍数", "质数", "合数", "约数", "整除")):
            pass
        prime_factorization_evidence = _school_prime_factorization_evidence(text)
        if prime_factorization_evidence:
            add("number_theory_factor_multiple", "number_theory", prime_factorization_evidence)
            add("school_prime_factorization", "number_theory", prime_factorization_evidence)
        if "number_theory_factor_multiple" in facts and add_terms(
            "integer_constraint",
            "number_theory",
            ("整数", "自然数", "两位数", "三位数", "个因数", "余数"),
        ):
            pass

        if add_terms("digit_property", "number_theory", ("数字和", "数位", "各个数位", "删去", "非零的数字")):
            pass
        place_value_evidence = _gaosi_place_value_principle_evidence(text)
        if place_value_evidence:
            add("digit_property", "number_theory", place_value_evidence)
            add("gaosi_place_value_principle", "olympiad_number_theory", place_value_evidence)
        palindrome_evidence = _palindrome_number_counting_evidence(text)
        if palindrome_evidence:
            add("digit_property", "number_theory", palindrome_evidence)
            add("counting_target", "counting_goal", palindrome_evidence)
            add("palindrome_number_counting", "counting_structure", palindrome_evidence)
        if add_terms("divisibility_rule", "number_theory", ("9的倍数", "3的倍数", "整除", "数字之和", "余数")):
            pass

        work_rate_evidence = _work_rate_task_evidence(text)
        if work_rate_evidence:
            add("work_rate_task", "application_structure", work_rate_evidence)
        if work_rate_evidence and add_terms("work_efficiency_relation", "quantity_relation", ("效率", "单独", "合作", "共同完成", "每天完成", "轮流")):
            pass
        work_progress_evidence = _work_progress_ratio_evidence(text)
        if work_progress_evidence:
            add("work_rate_task", "application_structure", work_rate_evidence or work_progress_evidence)
            add("work_efficiency_relation", "quantity_relation", work_progress_evidence)
            add("work_progress_ratio", "quantity_relation", work_progress_evidence)

        growth = add_terms("resource_growth", "process_change", ("生长", "增长", "增加", "流入", "新增", "排队", "长草", "每天都长"))
        consumption = add_terms("resource_consumption", "process_change", ("吃", "消耗", "流出", "抽干", "吃完", "检票"))
        resource_time_or_initial = add_terms("resource_time_or_initial", "quantity_relation", ("原有", "原有草量", "每天", "天", "时间", "吃完"))
        if (growth and consumption) or add_terms("growth_consumption", "application_structure", ("牛吃草", "原有草量")):
            add("growth_consumption", "application_structure", _first_term(text, ("牛吃草", "原有", "增长", "生长", "消耗", "检票")) or text[:40])
        if (
            "growth_consumption" in facts
            and growth
            and consumption
            and resource_time_or_initial
            and any(term in text for term in ("牛", "草", "原有草量", "长草"))
        ):
            add("gaosi_grazing_clock", "olympiad_application", _first_term(text, ("牛吃草", "原有草量", "长草", "草")) or "增长消耗")

        if add_terms("motion_task", "application_structure", ("行程", "相遇", "追及", "速度", "路程", "同向", "相向", "流水")):
            pass
        if add_terms("speed_distance_time", "quantity_relation", ("每小时", "千米", "米/秒", "速度", "路程", "时间", "小时后")):
            pass
        variable_round_trip_evidence = _variable_speed_round_trip_evidence(text)
        if variable_round_trip_evidence:
            add("motion_task", "application_structure", variable_round_trip_evidence)
            add("speed_distance_time", "quantity_relation", variable_round_trip_evidence)
            add("variable_speed_round_trip", "application_structure", variable_round_trip_evidence)
        travel_equation_evidence = _travel_equation_same_distance_evidence(text)
        if travel_equation_evidence:
            add("motion_task", "application_structure", travel_equation_evidence)
            add("speed_distance_time", "quantity_relation", travel_equation_evidence)
            add("gaosi_travel", "olympiad_application", travel_equation_evidence)
            add("travel_equation_same_distance", "application_structure", travel_equation_evidence)

        if add_terms("concentration_task", "application_structure", ("浓度", "盐水", "溶液", "含盐", "酒精")):
            pass
        if add_terms("mixture_change", "process_change", ("加水", "蒸发", "混合", "倒入", "倒出", "稀释")):
            pass

        if add_terms("profit_discount", "application_structure", ("利润", "折扣", "进价", "售价", "标价", "获利", "加价", "打折")):
            pass
        if add_terms(
            "price_profit_relation",
            "quantity_relation",
            ("成本", "进价", "售价", "利润率", "获利", "亏损", "满减", "优惠", "原价", "现价", "水价", "起步价", "空驶费"),
        ):
            pass
        full_reduction_evidence = _full_reduction_discount_evidence(text)
        if full_reduction_evidence:
            add("price_profit_relation", "quantity_relation", full_reduction_evidence)

        if re.search(r"\d+\s*[:：]\s*\d+", text) or add_terms("ratio_relation", "quantity_relation", ("之比", "比是", "比例")):
            add("ratio_relation", "quantity_relation", _first_term(text, ("之比", "比是", "比例", ":")) or "ratio")
        proportion_application_evidence = _proportion_application_evidence(text)
        if proportion_application_evidence:
            add("ratio_relation", "quantity_relation", proportion_application_evidence)
            add("proportion_application", "quantity_relation", proportion_application_evidence)
        triangle_angle_evidence = _triangle_angle_classification_evidence(text)
        if triangle_angle_evidence:
            add("geometry_triangle", "geometry", triangle_angle_evidence)
            add("triangle_angle_classification", "school_geometry", triangle_angle_evidence)
            add("ratio_relation", "quantity_relation", triangle_angle_evidence)
        cylinder_cone_height_ratio_evidence = _cylinder_cone_volume_height_ratio_evidence(text)
        if cylinder_cone_height_ratio_evidence:
            add("school_volume", "school_geometry", cylinder_cone_height_ratio_evidence)
            add("solid_geometry", "geometry", cylinder_cone_height_ratio_evidence)
            add("ratio_relation", "quantity_relation", cylinder_cone_height_ratio_evidence)
            add("cylinder_cone_volume_height_ratio", "geometry_structure", cylinder_cone_height_ratio_evidence)
        cylinder_cone_volume_ratio_evidence = _cylinder_cone_volume_ratio_evidence(text)
        if cylinder_cone_volume_ratio_evidence:
            add("school_volume", "school_geometry", cylinder_cone_volume_ratio_evidence)
            add("solid_geometry", "geometry", cylinder_cone_volume_ratio_evidence)
            add("ratio_relation", "quantity_relation", cylinder_cone_volume_ratio_evidence)
            add("cylinder_cone_volume_ratio", "geometry_structure", cylinder_cone_volume_ratio_evidence)
        if add_terms("whole_part_relation", "quantity_relation", ("总量", "总数", "之和", "其余", "整体", "全部")):
            pass

        if add_terms("sequence_pattern", "pattern_sequence", ("周期", "循环", "规律", "数列", "数表", "按规律", "星期", "日历", "休息日")):
            pass
        if add_terms("period_position", "pattern_sequence", ("第n", "第 n", "第几", "位置", "余数")):
            pass
        number_table_evidence = _number_table_position_pattern_evidence(text)
        if number_table_evidence:
            add("sequence_pattern", "pattern_sequence", number_table_evidence)
            add("period_position", "pattern_sequence", number_table_evidence)
            add("gaosi_sequence", "olympiad_pattern", number_table_evidence)
            add("number_table_position_pattern", "pattern_sequence", number_table_evidence)
        square_difference_evidence = _square_difference_odd_evidence(text)
        if square_difference_evidence:
            add("sequence_pattern", "pattern_sequence", square_difference_evidence)
            add("gaosi_number_theory", "olympiad_number_theory", square_difference_evidence)
            add("square_difference_odd", "number_theory", square_difference_evidence)
        periodic_grid_evidence = _periodic_grid_evidence(text)
        if periodic_grid_evidence:
            add("sequence_pattern", "pattern_sequence", periodic_grid_evidence)
            add("period_position", "pattern_sequence", periodic_grid_evidence)
            add("periodic_grid", "pattern_sequence", periodic_grid_evidence)
        state_recurrence_evidence = _state_recurrence_evidence(text)
        if state_recurrence_evidence:
            add("sequence_pattern", "pattern_sequence", state_recurrence_evidence)
            add("reverse_process", "process_change", state_recurrence_evidence)
            add("state_recurrence", "pattern_sequence", state_recurrence_evidence)
        line_plane_evidence = _line_plane_recurrence_evidence(text)
        if line_plane_evidence:
            add("sequence_pattern", "pattern_sequence", line_plane_evidence)
            add("line_plane_recurrence", "pattern_sequence", line_plane_evidence)

        half_recurrence_evidence = _half_recurrence_process_evidence(text)
        if half_recurrence_evidence:
            add("half_recurrence", "process_change", half_recurrence_evidence)
        if add_terms("half_recurrence", "process_change", ("一半", "二分之一", "1/2", "失去", "减少为原来的")):
            pass
        reverse_process_evidence = _reverse_process_evidence(text)
        if reverse_process_evidence:
            add("reverse_process", "process_change", reverse_process_evidence)
        if add_terms("reverse_process", "process_change", ("倒推", "还原", "原来", "一开始", "开始", "最后", "末端", "已知末端")):
            pass
        surplus_deficit_evidence = _surplus_deficit_evidence(text)
        if surplus_deficit_evidence:
            add("surplus_deficit", "quantity_relation", surplus_deficit_evidence)
        reverse_payment_evidence = _reverse_surplus_payment_process_evidence(text)
        if reverse_payment_evidence:
            add("reverse_process", "process_change", reverse_payment_evidence)
            add("surplus_deficit", "quantity_relation", reverse_payment_evidence)
            add("reverse_surplus_payment_process", "process_change", reverse_payment_evidence)

        fraction_match = self._FRACTION_CHAIN_RE.search(text)
        if fraction_match or add_terms("fraction_series", "operation_structure", ("裂项", "长链", "分式求和")):
            add("fraction_series", "operation_structure", fraction_match.group(0)[:80] if fraction_match else "裂项")
        if "fraction_series" in facts and ("..." in text or "…" in text or add_terms("telescoping_pattern", "operation_structure", ("裂项", "相消", "消去", "首尾"))):
            add("telescoping_pattern", "operation_structure", _first_term(text, ("...", "…", "裂项", "相消", "消去")) or "fraction chain")

        pigeonhole_evidence = _pigeonhole_evidence(text)
        if pigeonhole_evidence:
            add("pigeonhole", "counting_structure", pigeonhole_evidence)
        guarantee_evidence = _guarantee_at_least_evidence(text)
        if guarantee_evidence:
            add("guarantee_at_least", "counting_goal", guarantee_evidence)
        if add_terms("counting_choice", "counting_structure", ("排列", "组合", "选择", "选", "方案", "种菜", "分类", "可选", "凑单", "下单")):
            pass
        if add_terms("counting_target", "counting_goal", ("多少种", "几种", "方案数", "共有多少", "一共有多少")):
            pass

        if add_terms("gaosi_enumeration", "olympiad_counting", ("枚举", "列举")):
            pass
        condition_split_evidence = _condition_enumeration_integer_split_evidence(text)
        if condition_split_evidence:
            add("integer_constraint", "number_theory", condition_split_evidence)
            add("gaosi_enumeration", "olympiad_counting", condition_split_evidence)
            add("condition_enumeration", "logic_strategy", condition_split_evidence)
            add("integer_split", "number_theory", condition_split_evidence)
        if add_terms("gaosi_counting_principle", "olympiad_counting", ("加法原理", "乘法原理", "分类", "分步")):
            pass
        permutation_evidence = _gaosi_permutation_combination_evidence(text)
        if "school_square_tiling_perimeter" not in facts and permutation_evidence:
            add("gaosi_permutation_combination", "olympiad_counting", permutation_evidence)
        if add_terms("gaosi_inclusion_exclusion", "olympiad_counting", ("包含", "排除", "重复", "重叠", "至少一个", "容斥")):
            pass
        if add_terms("gaosi_geometric_counting", "olympiad_counting", ("几何计数", "图中有多少", "三角形个数", "正方形个数", "长方形个数")):
            pass

        chicken_rabbit_evidence = _chicken_rabbit_evidence(text)
        if chicken_rabbit_evidence:
            add("two_type_objects", "quantity_relation", chicken_rabbit_evidence)
            add("total_and_parts", "quantity_relation", chicken_rabbit_evidence)
            add("gaosi_chicken_rabbit", "olympiad_application", chicken_rabbit_evidence)
        two_type_cost_evidence = _two_type_cost_total_evidence(text)
        if two_type_cost_evidence:
            add("two_type_objects", "quantity_relation", two_type_cost_evidence)
            add("total_and_parts", "quantity_relation", two_type_cost_evidence)
            add("two_type_cost_total", "quantity_relation", two_type_cost_evidence)
            add("gaosi_chicken_rabbit", "olympiad_application", two_type_cost_evidence)
        if add_terms("gaosi_word_relation", "olympiad_application", ("和差倍", "和倍", "差倍", "倍分", "几倍", "相差")):
            pass
        if add_terms("gaosi_basic_application", "olympiad_application", ("基本应用题", "应用题拓展", "归一问题", "等量代换", "乘除数量关系")):
            pass
        if surplus_deficit_evidence:
            add("gaosi_surplus_deficit", "olympiad_application", surplus_deficit_evidence)
        if add_terms("gaosi_reverse_age", "olympiad_application", ("还原", "倒推", "年龄", "岁")):
            pass
        if add_terms("gaosi_average", "olympiad_application", ("平均数",)):
            pass
        if work_rate_evidence:
            add("gaosi_work_rate", "olympiad_application", work_rate_evidence)
        clock_evidence = _clock_problem_evidence(text)
        if clock_evidence:
            add("gaosi_grazing_clock", "olympiad_application", clock_evidence)
            add("clock_face", "clock_structure", clock_evidence)
            if "时针" in text and "分针" in text:
                add("clock_hands_relation", "clock_structure", clock_evidence)
            if re.search(r"\d+\s*(?:点|时)\s*(?:\d+\s*分)?", text) or any(term in text for term in ("夹角", "重合", "垂直", "成直线")):
                add("time_angle_goal", "clock_structure", clock_evidence)
        if add_terms("gaosi_travel", "olympiad_application", ("行程", "速度", "路程", "相遇", "追及", "流水", "柳卡图", "柳卡图解行程", "环形路线", "间隔发车", "多人相遇", "接送", "接力")):
            pass
        if add_terms("gaosi_concentration_profit", "olympiad_application", ("浓度", "盐水", "溶液", "利润", "折扣", "进价", "售价", "经济")):
            pass
        if add_terms("gaosi_ratio", "olympiad_application", ("比例", "正比例", "反比例", "之比", "比是")):
            pass

        if add_terms("gaosi_arithmetic_synthesis", "olympiad_operation", ("计算综合", "整数计算综合")):
            pass
        if add_terms("gaosi_counting_synthesis", "olympiad_counting", ("计数综合",)):
            pass
        if add_terms("gaosi_number_theory_synthesis", "olympiad_number_theory", ("数论综合",)):
            pass
        if add_terms("gaosi_geometry_synthesis", "olympiad_geometry", ("几何综合",)):
            pass
        if add_terms("gaosi_application_synthesis", "olympiad_application", ("应用题综合",)):
            pass

        vertical_puzzle_evidence = _vertical_puzzle_evidence(text)
        digit_puzzle_evidence = _digit_puzzle_evidence(text)
        if add_terms("gaosi_arithmetic", "olympiad_operation", ("四则", "简便", "运算", "估算", "循环小数", "分数计算", "小数计算")):
            pass
        if vertical_puzzle_evidence:
            add("gaosi_vertical_puzzle", "olympiad_operation", vertical_puzzle_evidence)
        if digit_puzzle_evidence:
            add("gaosi_digit_puzzle", "olympiad_operation", digit_puzzle_evidence)
        digit_swap_evidence = _digit_swap_multiple_evidence(text)
        if digit_swap_evidence:
            add("digit_property", "number_theory", digit_swap_evidence)
            add("gaosi_digit_puzzle", "olympiad_operation", digit_swap_evidence)
            add("gaosi_place_value_principle", "olympiad_number_theory", digit_swap_evidence)
            add("digit_swap_multiple", "number_theory", digit_swap_evidence)
        repeated_digit_evidence = _repeated_digit_number_evidence(text)
        if repeated_digit_evidence:
            add("digit_property", "number_theory", repeated_digit_evidence)
            add("gaosi_digit_puzzle", "olympiad_operation", repeated_digit_evidence)
            add("repeated_digit_number", "number_theory", repeated_digit_evidence)
        if add_terms("gaosi_number_theory", "olympiad_number_theory", ("数论", "整除", "余数", "约数", "倍数", "质数", "合数", "同余", "不定方程")):
            pass
        if add_terms("gaosi_remainder", "olympiad_number_theory", ("余数", "同余")):
            pass
        remainder_evidence = _remainder_congruence_evidence(text)
        if remainder_evidence:
            add("gaosi_number_theory", "olympiad_number_theory", remainder_evidence)
            add("gaosi_remainder", "olympiad_number_theory", remainder_evidence)
            add("period_position", "pattern_sequence", remainder_evidence)
        if add_terms("gaosi_divisibility", "olympiad_number_theory", ("整除", "约数", "倍数", "质数", "合数", "因数")):
            pass
        if add_terms("gaosi_equation", "olympiad_number_theory", ("方程", "未知数", "不定方程")):
            pass
        integer_solution_evidence = _integer_solution_factorization_evidence(text)
        if integer_solution_evidence:
            add("integer_constraint", "number_theory", integer_solution_evidence)
            add("gaosi_number_theory", "olympiad_number_theory", integer_solution_evidence)
            add("gaosi_divisibility", "olympiad_number_theory", integer_solution_evidence)
            add("integer_solution_factorization", "number_theory", integer_solution_evidence)

        if add_terms("geometry_area", "geometry", ("面积", "阴影", "S阴", "三角形面积")):
            pass
        if add_terms("geometry_measurement_goal", "geometry", ("求面积", "求体积", "求周长", "面积是", "体积是")):
            pass
        if "geometry_area" in facts or "school_area" in facts or "geometry_measurement_goal" in facts:
            area_fact = facts.get("geometry_area") or facts.get("school_area") or facts.get("geometry_measurement_goal")
            add("area_goal", "goal", area_fact.evidence if area_fact else "area")
        if add_terms("area_relation_model", "geometry_structure", ("面积比", "等高", "共边", "蝴蝶模型", "燕尾模型", "割补", "沙漏")):
            pass
        cut_paste_area_evidence = _cut_paste_area_decomposition_evidence(text)
        if cut_paste_area_evidence:
            add("geometry_area", "geometry", cut_paste_area_evidence)
            add("area_goal", "goal", cut_paste_area_evidence)
            add("area_decomposition", "geometry_structure", cut_paste_area_evidence)
            add("gaosi_cut_paste", "olympiad_geometry", cut_paste_area_evidence)
            if any(term in text for term in ("圆", "扇形", "圆弧", "π", "半径", "直径")):
                add("gaosi_circle_sector", "olympiad_geometry", cut_paste_area_evidence)
                add("geometry_circle", "geometry", cut_paste_area_evidence)
        rotation_area_evidence = _rotation_area_transform_evidence(text)
        if rotation_area_evidence:
            add("geometry_area", "geometry", rotation_area_evidence)
            add("area_goal", "goal", rotation_area_evidence)
            add("area_decomposition", "geometry_structure", rotation_area_evidence)
            add("overall_area_method", "geometry_structure", rotation_area_evidence)
            add("rotation_area_transform", "geometry_structure", rotation_area_evidence)
            add("gaosi_cut_paste", "olympiad_geometry", rotation_area_evidence)
            add("gaosi_circle_sector", "olympiad_geometry", rotation_area_evidence)
            add("geometry_circle", "geometry", rotation_area_evidence)
        pythagorean_area_evidence = _pythagorean_area_relation_evidence(text)
        if pythagorean_area_evidence:
            add("geometry_area", "geometry", pythagorean_area_evidence)
            add("geometry_triangle", "geometry", pythagorean_area_evidence)
            add("area_relation_model", "geometry_structure", pythagorean_area_evidence)
        area_ratio_evidence = _area_ratio_relation_evidence(text)
        if area_ratio_evidence:
            add("geometry_area", "geometry", area_ratio_evidence)
            add("area_relation_model", "geometry_structure", area_ratio_evidence)
            add("area_ratio_relation", "geometry_structure", area_ratio_evidence)
        butterfly_area_evidence = _butterfly_area_model_evidence(text)
        if butterfly_area_evidence:
            add("geometry_area", "geometry", butterfly_area_evidence)
            add("geometry_triangle", "geometry", butterfly_area_evidence)
            add("area_relation_model", "geometry_structure", butterfly_area_evidence)
            add("area_ratio_relation", "geometry_structure", butterfly_area_evidence)
            add("butterfly_area_model", "geometry_structure", butterfly_area_evidence)
        swallowtail_evidence = _swallowtail_area_model_evidence(text)
        if swallowtail_evidence:
            add("geometry_area", "geometry", swallowtail_evidence)
            add("geometry_triangle", "geometry", swallowtail_evidence)
            add("area_relation_model", "geometry_structure", swallowtail_evidence)
            add("swallowtail_area_model", "geometry_structure", swallowtail_evidence)
        overlap_area_evidence = _overlap_area_evidence(text)
        if overlap_area_evidence:
            add("geometry_area", "geometry", overlap_area_evidence)
            add("area_relation_model", "geometry_structure", overlap_area_evidence)
            add("overlap_area", "geometry_structure", overlap_area_evidence)
        tangram_evidence = _tangram_area_evidence(text)
        if tangram_evidence:
            add("geometry_area", "geometry", tangram_evidence)
            add("area_relation_model", "geometry_structure", tangram_evidence)
            add("gaosi_cut_paste", "olympiad_geometry", tangram_evidence)
            add("tangram_area", "geometry_structure", tangram_evidence)
        zhao_shuang_evidence = _zhao_shuang_diagram_evidence(text)
        if zhao_shuang_evidence:
            add("geometry_area", "geometry", zhao_shuang_evidence)
            add("area_relation_model", "geometry_structure", zhao_shuang_evidence)
            add("zhao_shuang_diagram", "geometry_structure", zhao_shuang_evidence)
        if add_terms("basic_formula", "geometry_structure", ("公式", "直接代入", "长方形面积", "正方形面积", "圆柱", "圆锥", "体积公式")):
            pass
        if add_terms("geometry_triangle", "geometry", ("三角形", "△", " triangle ")):
            pass
        if add_terms("midline_or_midpoint", "geometry_structure", ("中点", "中位线")):
            pass
        segment_equal_midpoint_evidence = _segment_equal_midpoint_evidence(text)
        if segment_equal_midpoint_evidence:
            add("midline_or_midpoint", "geometry_structure", segment_equal_midpoint_evidence)
        equilateral_perimeter_evidence = _equilateral_triangle_perimeter_transform_evidence(text)
        if equilateral_perimeter_evidence:
            add("school_perimeter", "school_geometry", equilateral_perimeter_evidence)
            add("geometry_triangle", "geometry", equilateral_perimeter_evidence)
            add("midline_or_midpoint", "geometry_structure", equilateral_perimeter_evidence)
            add("equilateral_triangle_perimeter_transform", "geometry_structure", equilateral_perimeter_evidence)
        if add_terms("folding", "geometry_structure", ("翻折", "折叠", "对称", "沿")):
            pass
        fold_cut_evidence = _fold_cut_unfold_evidence(text)
        if fold_cut_evidence:
            add("folding", "geometry_structure", fold_cut_evidence)
            add("fold_cut_unfold", "geometry_structure", fold_cut_evidence)
        geometry_transform_evidence = _geometry_transform_puzzle_evidence(text)
        if geometry_transform_evidence:
            add("school_geometry_motion", "school_geometry", geometry_transform_evidence)
            add("geometry_transform_puzzle", "geometry_structure", geometry_transform_evidence)
        if add_terms("solid_geometry", "geometry", ("正方体", "立方体", "长方体", "立体", "积木", "棱")):
            pass
        if add_terms("view_projection", "geometry_structure", ("三视图", "左视图", "主视图", "俯视图", "从前面", "从左面", "观察", "投影", "截面", "切面")):
            pass
        if add_terms("extremum_goal", "goal", ("最少", "最多", "最大", "最小", "至少", "至多", "最短")):
            pass
        if add_terms("gaosi_geometry_basic", "olympiad_geometry", ("几何图形", "长度", "角度", "直线形", "图形认知")):
            pass
        if add_terms("gaosi_cut_paste", "olympiad_geometry", ("剪拼", "割补", "等积")):
            pass
        if add_terms("gaosi_lattice", "olympiad_geometry", ("格点", "方格", "网格", "点阵")):
            pass
        if add_terms("gaosi_circle_sector", "olympiad_geometry", ("扇形", "圆心角", "半径", "直径", "圆")):
            pass
        if "gaosi_circle_sector" in facts:
            circle_fact = facts.get("gaosi_circle_sector")
            add("geometry_circle", "geometry", circle_fact.evidence if circle_fact else "circle")
        reuleaux_evidence = _reuleaux_triangle_evidence(text)
        if reuleaux_evidence:
            add("geometry_area", "geometry", reuleaux_evidence)
            add("gaosi_circle_sector", "olympiad_geometry", reuleaux_evidence)
            add("reuleaux_triangle", "geometry_structure", reuleaux_evidence)
        circle_context = _first_term(text, ("圆周长", "圆的周长", "赤道", "圆环", "铁丝"))
        if circle_context and any(term in text for term in ("周长", "围在", "围成", "铁丝", "赤道")):
            add("circle_circumference_context", "geometry_structure", circle_context)
        if "circle_circumference_context" in facts and re.search(
            r"(?:长度|周长)\s*(?:增加|加长)|增加\s*\d+(?:\.\d+)?\s*(?:米|厘米|千米)",
            text,
        ):
            add(
                "circumference_increment",
                "process_change",
                _first_term(text, ("长度增加", "周长增加", "增加", "加长")) or "circumference increment",
            )
        if "circle_circumference_context" in facts and add_terms(
            "radius_increment_goal",
            "geometry_goal",
            ("圆环的宽", "圆环宽", "半径增加", "半径增量", "宽是"),
        ):
            pass
        if add_terms("gaosi_solid_geometry", "olympiad_geometry", ("立体", "正方体", "长方体", "圆柱", "圆锥", "表面积", "体积")):
            pass
        cylinder_evidence = _cylinder_surface_volume_evidence(text)
        if cylinder_evidence:
            add("solid_geometry", "geometry", cylinder_evidence)
            add("school_volume", "school_geometry", cylinder_evidence)
            add("gaosi_solid_geometry", "olympiad_geometry", cylinder_evidence)
            add("cylinder_surface_volume", "geometry_structure", cylinder_evidence)
        cylinder_composite_evidence = _cylinder_surface_volume_composite_evidence(text)
        if cylinder_composite_evidence:
            add("solid_geometry", "geometry", cylinder_composite_evidence)
            add("school_area", "school_geometry", cylinder_composite_evidence)
            add("school_volume", "school_geometry", cylinder_composite_evidence)
            add("cylinder_surface_volume", "geometry_structure", cylinder_composite_evidence)
            add("cylinder_surface_volume_composite", "geometry_structure", cylinder_composite_evidence)

        if add_terms("gaosi_sequence", "olympiad_pattern", ("周期", "规律", "数列", "数表", "等差", "找规律")):
            pass
        if add_terms("gaosi_interval_array", "olympiad_pattern", ("间隔", "阵列", "植树", "队列")):
            pass
        if add_terms("gaosi_magic_square", "olympiad_pattern", ("幻方", "数阵", "数阵图")):
            pass
        if add_terms("gaosi_logic", "olympiad_logic", ("逻辑", "推理", "真假", "真话", "假话", "条件", "名次", "排名", "一笔画", "火柴棒", "过河", "天平称重", "皇后", "棋盘控制", "握手", "下棋", "循环赛", "空瓶换水", "移动火柴棒")):
            pass
        binary_search_evidence = _binary_search_strategy_evidence(text)
        if binary_search_evidence:
            add("gaosi_logic", "olympiad_logic", binary_search_evidence)
            add("binary_search_strategy", "logic_strategy", binary_search_evidence)
            add("information_search_strategy", "logic_strategy", binary_search_evidence)
        if add_terms("gaosi_optimization", "olympiad_logic", ("统筹", "对策", "最值", "最多", "最少", "最大", "最小", "最优")):
            pass
        transport_evidence = _transport_optimization_evidence(text)
        if transport_evidence:
            add("gaosi_optimization", "olympiad_logic", transport_evidence)
            add("transport_optimization", "logic_strategy", transport_evidence)
        if add_terms("gaosi_construction", "olympiad_logic", ("构造", "论证", "证明", "存在", "任意", "棋盘染色", "构造抽屉", "数字论证", "图形论证")):
            pass
        if add_terms("gaosi_probability", "olympiad_counting", ("概率", "可能性", "随机")):
            pass

        graph_relation_evidence = _graph_relation_network_counting_evidence(text)
        if graph_relation_evidence:
            add("counting_target", "counting_goal", graph_relation_evidence)
            add("graph_relation_network_counting", "counting_structure", graph_relation_evidence)

        if add_terms("game_rule", "logic_strategy", ("游戏", "规则", "玩家", "轮流", "棋子", "移动", "无法移动")):
            pass
        winning_strategy_evidence = _winning_strategy_evidence(text)
        if winning_strategy_evidence:
            add("winning_strategy", "logic_strategy", winning_strategy_evidence)

        if len(text) < 8:
            add("risk_short_question_text", "risk", text or "empty question")

        return [fact.as_dict() for fact in facts.values()]


class Dim5FactProfileExtractor:
    """LLM-first Dim5 structure fact extractor.

    The extractor deliberately returns structure facts only. It never returns a
    final knowledge point. The rule extractor is allowed only as a marked
    fallback so downstream code can avoid treating it as the normal path.
    """

    def __init__(
        self,
        llm_client: Any,
        *,
        fallback_extractor: Dim5StructureExtractor | None = None,
        response_format: Dict[str, str] | None = None,
    ) -> None:
        self.llm = llm_client
        self.fallback_extractor = fallback_extractor or Dim5StructureExtractor()
        self.response_format = response_format or {"type": "json_object"}

    async def extract(
        self,
        *,
        question_id: str,
        raw_text: str,
        question_type: str = "",
        image_refs: Sequence[str] | None = None,
        ocr_warnings: Sequence[str] | None = None,
    ) -> Dict[str, Any]:
        messages = self._build_messages(
            question_id=question_id,
            raw_text=raw_text,
            question_type=question_type,
            image_refs=image_refs or [],
            ocr_warnings=ocr_warnings or [],
        )
        try:
            response = await self.llm.chat(messages, response_format=self.response_format)
            payload = _load_dim5_fact_profile_json(response)
            profile = _normalize_dim5_fact_profile(
                payload,
                question_text=raw_text,
                extraction_source="llm_dim5_fact_profile",
            )
            if not profile.get("structures"):
                raise ValueError("llm_dim5_fact_profile_empty_structures")
            return profile
        except Exception as exc:
            return self._fallback_profile(
                raw_text=raw_text,
                question_type=question_type,
                reason=str(exc)[:240],
            )

    def _fallback_profile(
        self,
        *,
        raw_text: str,
        question_type: str = "",
        reason: str = "",
    ) -> Dict[str, Any]:
        facts = self.fallback_extractor.extract(raw_text, question_type=question_type)
        profile = _build_dim5_fact_profile(facts, question_text=raw_text)
        profile["extraction_source"] = "rule_fallback"
        profile["need_manual_review"] = 1
        warnings = list(profile.get("warnings") or [])
        warning = "dim5_llm_fact_profile_failed_rule_fallback"
        if reason:
            warning = f"{warning}:{reason}"
        warnings.append(warning)
        profile["warnings"] = _unique(warnings)
        return profile

    @staticmethod
    def _build_messages(
        *,
        question_id: str,
        raw_text: str,
        question_type: str,
        image_refs: Sequence[str],
        ocr_warnings: Sequence[str],
    ) -> List[Dict[str, str]]:
        input_payload = {
            "question_id": str(question_id or ""),
            "raw_text": str(raw_text or ""),
            "question_type": str(question_type or ""),
            "image_refs": [str(item) for item in image_refs if str(item or "").strip()],
            "ocr_warnings": [str(item) for item in ocr_warnings if str(item or "").strip()],
        }
        user_prompt = (
            "请只抽取维度5使用的“题目结构事实”，不要输出最终知识点、等级、分数或候选。"
            "structures 字段只能使用英文结构 key；如果你想写中文标签，必须先转换成下面给出的英文 key。"
            "每个结构都必须在 evidence 中给出题干原文证据，或描述图片证据。"
            "重要结构 key 中文释义如下：\n"
            + dim5_structure_glossary_prompt(limit=90)
            + "\n关键边界：如果题干只有“顺时针/逆时针”，只能输出 rotation_direction；"
            "除非真实出现钟面、时针、分针、时刻或夹角关系，否则不得输出 clock_face 或 clock_hands_relation。"
            "如果是扇形统计图、百分比读图或统计表，优先输出 statistics_chart_context，不能只当成几何圆。"
            "返回 JSON，形状必须严格为："
            '{"structures":[],"objects":[],"methods":[],"evidence":[{"fact_key":"","text":"","source":"question_text"}],'
            '"visual_dependency":"none|helpful|required","warnings":[]}. '
            "输入 JSON：\n"
            + json.dumps(input_payload, ensure_ascii=False)
        )
        return [
            {
                "role": "system",
                "content": (
                    "你是严格的数学试题结构事实抽取器，只服务维度5。"
                    "你只抽取可观察结构，不裁决最终知识点。"
                ),
            },
            {"role": "user", "content": user_prompt},
        ]


@dataclass(frozen=True)
class Dim5Decision:
    selected: Dim5GraphCandidate | None
    confidence_status: str
    failure_reason: str
    rejected_reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        if not self.selected:
            return {
                "decision_status": "review_required"
                if self.confidence_status in {"review_required", "ambiguous", "broad_category_only"}
                else self.confidence_status,
                "is_applicable": False,
                "knowledge_point_id": "",
                "knowledge_point_name": "",
                "knowledge_domain": "",
                "knowledge_level": "",
                "confidence": 0.0,
                "evidence": [],
                "supporting_knowledge_points": [],
                "rejected_candidates": [],
                "need_manual_review": True,
                "reason": self.failure_reason,
            }
        node = self.selected.node
        return {
            "decision_status": "confirmed",
            "is_applicable": True,
            "knowledge_point_id": node.knowledge_point_id,
            "knowledge_point_name": node.name,
            "knowledge_domain": node.domain,
            "knowledge_level": node.level,
            "confidence": round(min(0.96, 0.72 + self.selected.score * 0.18), 3),
            "evidence": self.selected.matched_evidence[:6],
            "supporting_knowledge_points": [
                item
                for item in (node.name, *node.aliases[:4])
                if str(item or "").strip()
            ],
            "rejected_candidates": [],
            "need_manual_review": False,
        }


class Dim5DecisionEngine:
    """Final deterministic decision layer for Dim5 graph candidates."""

    def decide(self, candidates: Sequence[Dim5GraphCandidate]) -> Dim5Decision:
        confirmed = [item for item in candidates if item.candidate_status == "confirmed_candidate"]
        if not confirmed:
            if any(item.candidate_status == "weak_candidate" for item in candidates):
                return Dim5Decision(
                    selected=None,
                    confidence_status="broad_category_only",
                    failure_reason="weak_structure_evidence_only",
                )
            return Dim5Decision(
                selected=None,
                confidence_status="review_required",
                failure_reason="no_confirmed_candidate",
            )

        confirmed.sort(
            key=lambda item: (
                item.score,
                _is_generated_gaosi_topic_id(item.node.knowledge_point_id),
                len(item.node.required_structures),
                len(item.matched_supporting_fact_keys),
                bool(item.matched_aliases),
            ),
            reverse=True,
        )
        if len(confirmed) == 1:
            return Dim5Decision(selected=confirmed[0], confidence_status="confirmed", failure_reason="")

        score_gap = confirmed[0].score - confirmed[1].score
        same_family = _same_knowledge_family(confirmed[0].node, confirmed[1].node)
        same_domain = confirmed[0].node.domain == confirmed[1].node.domain
        if same_family:
            return Dim5Decision(selected=_more_specific_candidate(confirmed[0], confirmed[1]), confidence_status="confirmed", failure_reason="")
        if score_gap >= 0.03:
            return Dim5Decision(selected=confirmed[0], confidence_status="confirmed", failure_reason="")
        if score_gap > 0 and confirmed[0].matched_aliases:
            return Dim5Decision(selected=confirmed[0], confidence_status="confirmed", failure_reason="")
        if same_domain and score_gap > 0 and (
            len(confirmed[0].matched_fact_keys) > len(confirmed[1].matched_fact_keys)
            or confirmed[0].matched_aliases
        ):
            return Dim5Decision(selected=confirmed[0], confidence_status="confirmed", failure_reason="")
        return Dim5Decision(
            selected=None,
            confidence_status="ambiguous",
            failure_reason="ambiguous_confirmed_candidates",
        )


class Dim5KnowledgeGraphMatcher:
    def __init__(
        self,
        graph: Dim5KnowledgeGraph | None = None,
        extractor: Dim5StructureExtractor | None = None,
    ) -> None:
        self.graph = graph or Dim5KnowledgeGraph.load()
        self.extractor = extractor or Dim5StructureExtractor()

    def match(
        self,
        *,
        question_text: str,
        question_type: str = "",
        analysis_facts: Dict[str, Any] | None = None,
        dim5_feature: Dict[str, Any] | None = None,
        max_candidates: int = 8,
    ) -> Dict[str, Any]:
        supplied_profile = (
            (dim5_feature or {}).get("dim5_fact_profile")
            if isinstance(dim5_feature, dict)
            else None
        )
        if isinstance(supplied_profile, dict) and _string_list(supplied_profile.get("structures")):
            fact_profile = _normalize_dim5_fact_profile(
                supplied_profile,
                question_text=question_text,
                extraction_source=str(supplied_profile.get("extraction_source") or "llm_dim5_fact_profile"),
            )
            facts = _facts_from_dim5_fact_profile(fact_profile)
        else:
            facts = self.extractor.extract(question_text, question_type=question_type)
            fact_profile = _build_dim5_fact_profile(facts, question_text=question_text)
        fact_by_key = {str(fact.get("fact_key") or ""): fact for fact in facts}
        fact_keys = {key for key in fact_by_key if key}
        text_for_aliases = _normalize_text(question_text)

        candidates = [
            candidate
            for candidate in (
                self._match_node(node, fact_keys=fact_keys, fact_by_key=fact_by_key, text=text_for_aliases)
                for node in self.graph.approved_nodes
            )
            if candidate is not None
        ]
        candidates.sort(
            key=lambda item: (
                item.candidate_status == "confirmed_candidate",
                item.score,
                _is_generated_gaosi_topic_id(item.node.knowledge_point_id),
                len(item.node.required_structures),
                bool(item.matched_aliases),
            ),
            reverse=True,
        )
        candidates = candidates[: max(max_candidates, 0)]
        admission_results = _admission_results(candidates)
        decision = Dim5DecisionEngine().decide(candidates)
        selected = decision.selected
        confidence_status = decision.confidence_status
        failure_reason = decision.failure_reason
        candidate_dicts = [candidate.as_dict() for candidate in candidates]
        rejected = [
            _rejected_candidate_dict(candidate, selected)
            for candidate in candidates
            if not selected or candidate.node.knowledge_point_id != selected.node.knowledge_point_id
        ]
        decision_payload = decision.as_dict()
        decision_payload["rejected_candidates"] = rejected
        if fact_profile.get("need_manual_review") in (1, "1", True):
            decision_payload["need_manual_review"] = True
        result: Dict[str, Any] = {
            "version": "dim5_graph_matcher_v1",
            "graph_version": self.graph.version,
            "dim5_fact_profile": fact_profile,
            "dim5_structure_facts": facts,
            "graph_candidates": candidate_dicts,
            "admission_results": admission_results,
            "dim5_decision": decision_payload,
            "candidate_knowledge_points": candidate_dicts,
            "rejected_candidates": rejected,
            "confidence_status": confidence_status,
            "failure_reason": failure_reason,
            "selected_candidate_id": selected.node.knowledge_point_id if selected else "no_match",
            "knowledge_point_id": "",
            "knowledge_point_name": "",
            "knowledge_domain": "",
            "knowledge_level": "",
            "knowledge_track": "unknown",
            "knowledge_track_label": "未确认",
            "knowledge_grade": "unknown",
            "knowledge_grade_label": "年级未确认",
            "knowledge_semester": "unknown",
            "knowledge_display_name": "",
            "confidence": 0.0,
            "evidence": "",
            "need_manual_review": 1 if fact_profile.get("need_manual_review") in (1, "1", True) else 0,
        }
        if selected:
            result.update(
                {
                    "knowledge_point_id": selected.node.knowledge_point_id,
                    "knowledge_point_name": selected.node.name,
                    "knowledge_domain": selected.node.domain,
                    "knowledge_level": selected.node.level,
                    "knowledge_track": selected.node.knowledge_track,
                    "knowledge_track_label": selected.node.knowledge_track_label,
                    "knowledge_grade": selected.node.knowledge_grade,
                    "knowledge_grade_label": selected.node.knowledge_grade_label,
                    "knowledge_semester": selected.node.knowledge_semester,
                    "knowledge_display_name": selected.node.knowledge_display_name,
                    "confidence": round(min(0.96, 0.72 + selected.score * 0.18), 3),
                    "evidence": "；".join(selected.matched_evidence[:4]),
                }
            )
        return result

    def _match_node(
        self,
        node: Dim5GraphNode,
        *,
        fact_keys: set[str],
        fact_by_key: Dict[str, Dict[str, str]],
        text: str,
    ) -> Dim5GraphCandidate | None:
        matched_groups: List[tuple[str, ...]] = []
        matched_fact_keys: List[str] = []
        missing_groups: List[List[str]] = []
        if not node.required_structures:
            return None
        for group in node.required_structures:
            matched = [key for key in group if key in fact_keys]
            if matched:
                matched_groups.append(group)
                matched_fact_keys.extend(matched)
            else:
                missing_groups.append(list(group))

        matched_aliases = _alias_hits(text, (node.name, *node.aliases))
        matched_supporting = [key for key in node.supporting_structures if key in fact_keys]
        blocked_by = [key for key in node.exclude_structures if key in fact_keys]
        blocked_by.extend(_implicit_blocked_fact_keys(node, fact_keys))
        blocked_by = _unique(blocked_by)
        has_positive_signal = bool(matched_groups or matched_supporting or matched_aliases)
        if not has_positive_signal:
            return None

        matched_fact_keys = _unique(matched_fact_keys)
        missing_evidence = _unique(
            key
            for key in [*matched_fact_keys, *matched_supporting]
            if not str(fact_by_key.get(key, {}).get("evidence") or "").strip()
        )
        matched_evidence = _unique(
            str(fact_by_key.get(key, {}).get("evidence") or key)
            for key in [*matched_fact_keys, *matched_supporting]
            if str(fact_by_key.get(key, {}).get("evidence") or "").strip()
        )
        group_ratio = len(matched_groups) / max(len(node.required_structures), 1)
        alias_bonus = min(len(matched_aliases) * 0.06, 0.18)
        alias_specificity_bonus = min(sum(len(alias) for alias in matched_aliases) * 0.004, 0.08)
        specificity_bonus = min(len(node.required_structures) * 0.015, 0.08)
        structural_exact_bonus = (
            0.14
            if "school_square_tiling_perimeter" in matched_fact_keys
            and any("school_square_tiling_perimeter" in group for group in node.required_structures)
            else 0.0
        )
        all_matched_signal_keys = [*matched_fact_keys, *matched_supporting]
        topic_specific_bonus = (
            min(
                sum(
                    1
                    for key in (
                        "triangle_angle_classification",
                        "cylinder_cone_volume_height_ratio",
                        "composite_area_split_relation",
                        "cylinder_cone_volume_ratio",
                        "number_table_position_pattern",
                        "rectangle_area_fraction_percent_change",
                    )
                    if key in all_matched_signal_keys
                )
                * 0.08,
                0.16,
            )
        )
        curated_school_topic_bonus = 0.04 if _is_curated_school_topic_id(node.knowledge_point_id) else 0.0
        generated_gaosi_bonus = (
            0.14
            if _is_generated_gaosi_topic_id(node.knowledge_point_id)
            and _has_strong_olympiad_signal(all_matched_signal_keys)
            else 0.04
            if _is_generated_gaosi_topic_id(node.knowledge_point_id) and matched_aliases
            else 0.0
        )
        gaosi_signal_bonus = 0.08 if generated_gaosi_bonus and _has_strong_olympiad_signal(all_matched_signal_keys) else 0.0
        circle_area_bonus = (
            0.09
            if "gaosi_circle_sector" in matched_fact_keys
            and {"geometry_area", "school_area"} & set(fact_keys)
            and "cylinder_surface_volume" not in fact_keys
            and "school_volume" not in fact_keys
            else 0.0
        )
        specific_structure_bonus = min(
            sum(1 for key in matched_fact_keys if key in SPECIFIC_CONFIRMATION_FACT_KEYS) * 0.12,
            0.3,
        )
        supporting_bonus = min(len(matched_supporting) * 0.025, 0.08)
        school_gaosi_penalty = -0.16 if node.knowledge_track == "school" and _has_strong_olympiad_signal(fact_keys) else 0.0
        score = max(
            0.0,
            group_ratio
            + alias_bonus
            + alias_specificity_bonus
            + specificity_bonus
            + structural_exact_bonus
            + topic_specific_bonus
            + curated_school_topic_bonus
            + generated_gaosi_bonus
            + gaosi_signal_bonus
            + circle_area_bonus
            + specific_structure_bonus
            + supporting_bonus
            + school_gaosi_penalty,
        )

        if blocked_by:
            status = "blocked_candidate"
            score = min(score, 0.48)
        elif missing_evidence:
            status = "weak_candidate"
            score = min(score, 0.72)
        elif not missing_groups and not _only_generic_confirmation_signal(matched_fact_keys, matched_aliases):
            status = "confirmed_candidate"
            score = max(score, 0.86)
        else:
            status = "weak_candidate"
            score = min(score, 0.72)

        return Dim5GraphCandidate(
            node=node,
            candidate_status=status,
            score=score,
            matched_fact_keys=matched_fact_keys,
            matched_aliases=matched_aliases,
            missing_required_fact_groups=missing_groups,
            blocked_by_fact_keys=blocked_by,
            missing_evidence_fact_keys=missing_evidence,
            matched_evidence=matched_evidence,
            matched_supporting_fact_keys=_unique(matched_supporting),
        )


@lru_cache(maxsize=1)
def get_dim5_knowledge_graph() -> Dim5KnowledgeGraph:
    return Dim5KnowledgeGraph.load()


@lru_cache(maxsize=1)
def get_dim5_knowledge_graph_matcher() -> Dim5KnowledgeGraphMatcher:
    return Dim5KnowledgeGraphMatcher(get_dim5_knowledge_graph())


def _normalize_knowledge_track(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"school", "校内"}:
        return "school"
    if text in {"olympiad", "gaosi", "competition", "奥数", "高思", "竞赛"}:
        return "olympiad"
    if text in {"junior", "初中", "初中前置", "junior_bridge"}:
        return "junior"
    return "unknown"


def _infer_knowledge_track(*, name: str, level: str, source_refs: Any) -> str:
    text = " ".join([str(name or ""), " ".join(_string_list(source_refs))])
    if any(term in text for term in ("初中", "七年级", "七上")):
        return "junior"
    if any(term in text for term in ("高思", "奥数", "竞赛", "抽屉", "博弈", "牛吃草", "鸡兔同笼", "裂项")):
        return "olympiad"
    if level in {"L3", "L4", "L5"}:
        return "olympiad"
    if level in {"L1", "L2"}:
        return "school"
    return "unknown"


def _normalize_knowledge_grade(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    for digit in ("1", "2", "3", "4", "5", "6", "7"):
        if digit in text:
            return digit
    chinese_values = {
        "一": "1",
        "二": "2",
        "三": "3",
        "四": "4",
        "五": "5",
        "六": "6",
        "七": "7",
    }
    for key, digit in chinese_values.items():
        if key in text:
            return digit
    return "unknown"


def _normalize_knowledge_semester(value: Any) -> str:
    text = str(value or "").strip()
    if "上" in text:
        return "上册"
    if "下" in text:
        return "下册"
    return text if text in DIM5_SEMESTER_VALUES else "unknown"


def _build_knowledge_display_name(track_label: str, grade_label: str, name: str) -> str:
    name = str(name or "").strip()
    track_label = str(track_label or "未确认").strip()
    grade_label = str(grade_label or "年级未确认").strip()
    if not name:
        return ""
    if track_label == "未确认":
        return f"未确认：{name}"
    if grade_label and grade_label != "年级未确认":
        return f"{track_label}{grade_label}：{name}"
    if track_label in {"校内", "奥数", "初中前置"}:
        return f"{track_label}知识：{name}"
    return f"{track_label}：{name}"


def _normalize_knowledge_display_name(
    display_name: str,
    *,
    track_label: str,
    grade_label: str,
    name: str,
) -> str:
    text = str(display_name or "").strip()
    if "年级未确认" not in text:
        return text
    return _build_knowledge_display_name(track_label, grade_label, name)


def _normalize_text(value: Any) -> str:
    text = str(value or "").strip()
    return text.replace("：", ":").replace("（", "(").replace("）", ")")


def _string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _default_fact_extraction_hints(
    name: str,
    required_structures: Sequence[Sequence[str]],
    aliases: Any,
) -> List[str]:
    required_groups = _normalize_structure_groups(required_structures)
    aliases_text = "、".join(_string_list(aliases)[:6])
    group_text = _format_structure_groups_for_hints(required_groups)
    hint = f"识别题目是否满足「{name}」的结构证据。"
    if group_text:
        hint += f"必须命中这些结构组：{group_text}。"
    if aliases_text:
        hint += f"别名线索只作为辅助，不可单独准入：{aliases_text}。"
    hint += "每个结构标签都要能回溯到题干原文或图片证据。"
    return [hint]


def _default_negative_hints(name: str, negative_examples: Any, near_miss_examples: Any) -> List[str]:
    examples = _string_list(negative_examples)[:2] + _string_list(near_miss_examples)[:2]
    hints = [f"不要只凭关键词、章节名、别名或来源标签确认「{name}」；必须满足 required_structures 的结构证据。"]
    if examples:
        hints.append(f"这些近似但不成立的场景不能判为「{name}」：" + "；".join(examples))
    else:
        hints.append(f"只有泛关键词或无法回溯到题干/图片的证据时，不确认「{name}」。")
    return hints


def localize_dim5_graph_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a graph payload whose explicit rule fields are Chinese-readable."""

    localized = dict(payload or {})
    localized["nodes"] = [
        localize_dim5_graph_node_rules(node)
        for node in localized.get("nodes") or []
        if isinstance(node, dict)
    ]
    return localized


def localize_dim5_graph_node_rules(raw: Dict[str, Any]) -> Dict[str, Any]:
    node = dict(raw or {})
    name = str(node.get("name") or "").strip()
    required = _normalize_structure_groups(
        node.get("required_structures") or node.get("required_fact_groups") or []
    )
    supporting = _unique(_string_list(node.get("supporting_structures")))
    legacy_excludes = _string_list(node.get("exclude_fact_keys"))
    excludes = _unique(legacy_excludes or _string_list(node.get("exclude_structures")))
    confusable = _unique(_string_list(node.get("confusable_with")))

    additions = _high_risk_localized_rule_additions(node)
    excludes = _unique([*excludes, *additions.get("exclude_structures", [])])
    confusable = _unique([*confusable, *additions.get("confusable_with", [])])
    supporting = _unique([*supporting, *additions.get("supporting_structures", [])])
    supporting = _prune_unscoped_supporting_structures(name, supporting, excludes, required)

    node["required_structures"] = [list(group) for group in required]
    node["supporting_structures"] = supporting
    node["exclude_structures"] = excludes
    node["confusable_with"] = confusable
    node["fact_extraction_hints"] = _unique(
        [
            *_default_fact_extraction_hints(name, required, node.get("aliases")),
            *additions.get("fact_extraction_hints", []),
        ]
    )
    node["negative_hints"] = _unique(
        [
            *_localized_exclude_hints(name, excludes),
            *_default_negative_hints(name, node.get("negative_examples"), node.get("near_miss_examples")),
            *additions.get("negative_hints", []),
        ]
    )
    return node


def build_dim5_rule_localization_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    nodes = [node for node in (payload.get("nodes") or []) if isinstance(node, dict)]
    english_nodes: List[Dict[str, str]] = []
    low_quality_nodes: List[Dict[str, str]] = []
    chinese_hint_count = 0
    for node in nodes:
        hints = _string_list(node.get("fact_extraction_hints"))
        negative_hints = _string_list(node.get("negative_hints"))
        text = " ".join([*hints, *negative_hints])
        if _contains_chinese(text) and hints and negative_hints:
            chinese_hint_count += 1
        markers = [marker for marker in DIM5_LOCALIZATION_ENGLISH_TEMPLATE_MARKERS if marker in text]
        if markers:
            english_nodes.append(
                {
                    "knowledge_point_id": str(node.get("knowledge_point_id") or ""),
                    "name": str(node.get("name") or ""),
                    "markers": " | ".join(markers[:4]),
                }
            )
        if not node.get("required_structures") or not hints or not negative_hints or not _contains_chinese(text):
            low_quality_nodes.append(
                {
                    "knowledge_point_id": str(node.get("knowledge_point_id") or ""),
                    "name": str(node.get("name") or ""),
                    "reason": "missing_required_structures_or_chinese_hints",
                }
            )
    high_risk = [
        _high_risk_rule_summary(node)
        for node in nodes
        if _is_high_risk_rule_node(node)
    ]
    return {
        "node_count": len(nodes),
        "required_structures_coverage": sum(1 for node in nodes if node.get("required_structures")),
        "fact_extraction_hints_coverage": sum(1 for node in nodes if node.get("fact_extraction_hints")),
        "negative_hints_coverage": sum(1 for node in nodes if node.get("negative_hints")),
        "chinese_rule_coverage": chinese_hint_count,
        "english_template_residue_count": len(english_nodes),
        "english_template_nodes": english_nodes[:50],
        "low_quality_rule_count": len(low_quality_nodes),
        "low_quality_rule_nodes": low_quality_nodes[:50],
        "high_risk_rule_summary": high_risk,
    }


def dim5_structure_glossary_prompt(limit: int = 80) -> str:
    items = list(DIM5_STRUCTURE_GLOSSARY.items())[: max(limit, 0)]
    return "\n".join(f"- {key}: {description}" for key, description in items)


def normalize_dim5_structure_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text in DIM5_STRUCTURE_KEY_ALIASES:
        return DIM5_STRUCTURE_KEY_ALIASES[text]
    lowered = text.strip().lower()
    if lowered in DIM5_STRUCTURE_KEY_ALIASES:
        return DIM5_STRUCTURE_KEY_ALIASES[lowered]
    if re.fullmatch(r"[a-z][a-z0-9_]*", lowered):
        return lowered
    compact = re.sub(r"[\s:：，,。；;（）()【】\\[\\]\"'`]+", "", text)
    return DIM5_STRUCTURE_KEY_ALIASES.get(compact, "")


def _normalize_structure_groups(value: Any) -> List[List[str]]:
    groups: List[List[str]] = []
    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, (list, tuple, set)):
                group = _unique(normalize_dim5_structure_key(key) for key in item)
            else:
                group = _unique([normalize_dim5_structure_key(item)])
            group = [key for key in group if key]
            if group:
                groups.append(group)
    return groups


def _format_structure_groups_for_hints(groups: Sequence[Sequence[str]]) -> str:
    parts: List[str] = []
    for index, group in enumerate(groups[:6], start=1):
        labels = " / ".join(_structure_key_with_description(key) for key in group[:5])
        if labels:
            parts.append(f"第{index}组 {labels}")
    return "；".join(parts)


def _structure_key_with_description(key: str) -> str:
    description = structure_key_chinese_description(key)
    return f"{key}（{description}）"


def structure_key_chinese_description(key: str) -> str:
    text = str(key or "").strip()
    if text in DIM5_STRUCTURE_GLOSSARY:
        return DIM5_STRUCTURE_GLOSSARY[text]
    if text.startswith("school_"):
        return "校内知识结构，需要题面出现对应的概念、计算目标或应用场景"
    if text.startswith("gaosi_"):
        return "高思奥数专题结构，需要题面出现对应专题模型而不只是章节名"
    if "geometry" in text or "circle" in text or "area" in text:
        return "几何图形、面积、长度或空间关系相关结构"
    if "count" in text or "combination" in text or "permutation" in text:
        return "计数、选择、排列组合或方案数相关结构"
    if "ratio" in text or "percent" in text or "proportion" in text:
        return "比例、百分数、整体与部分之间的数量关系"
    if "sequence" in text or "period" in text or "pattern" in text:
        return "周期、数列、图形或等式规律结构"
    if "digit" in text or "number" in text or "divisibility" in text:
        return "数位、整数、整除、因数倍数或数论性质"
    if "travel" in text or "motion" in text or "speed" in text:
        return "行程、速度、路程、时间或运动过程结构"
    return "程序内部结构标签，需要从题干或图片中找到可回溯证据"


def _localized_exclude_hints(name: str, excludes: Sequence[str]) -> List[str]:
    if not excludes:
        return []
    return [
        f"如果题目命中这些排除结构，则不确认或降级「{name}」："
        + "；".join(_structure_key_with_description(key) for key in excludes[:8])
    ]


def _high_risk_localized_rule_additions(node: Dict[str, Any]) -> Dict[str, List[str]]:
    name = str(node.get("name") or "")
    additions: Dict[str, List[str]] = {
        "supporting_structures": [],
        "exclude_structures": [],
        "confusable_with": [],
        "fact_extraction_hints": [],
        "negative_hints": [],
    }

    def add(field: str, *values: str) -> None:
        additions[field].extend(value for value in values if value)

    if name == "小数分数混合运算":
        add(
            "exclude_structures",
            "defined_operation_rule",
            "defined_operation_symbol",
            "defined_operation_target",
            "half_recurrence",
            "reverse_process",
            "work_rate_task",
            "work_progress_ratio",
        )
        add("confusable_with", "定义新运算", "倍半递推与倒推还原", "工程问题")
        add(
            "negative_hints",
            "如果题目先定义一种新运算、要求倒推初始量，或出现工程完成量/未完成量比例变化，不确认「小数分数混合运算」；分数只作为数量关系，不是主知识点。",
        )
    if "定义新运算" in name:
        add(
            "supporting_structures",
            "defined_operation_rule",
            "defined_operation_symbol",
            "defined_operation_target",
            "consecutive_product_definition",
        )
        add("exclude_structures", "work_rate_task", "statistics_chart_context")
        add("confusable_with", "小数分数混合运算", "分数裂项求和", "普通四则计算")
        add(
            "fact_extraction_hints",
            "定义新运算准入必须识别 defined_operation_rule（题目规定或定义新的运算规则），并优先识别 defined_operation_symbol（如 ※、△、☆ 等符号）与 defined_operation_target（代入或反求目标）。",
        )
        add(
            "negative_hints",
            "只有普通加减乘除、分数小数算式或填空符号，而没有题面给出的新运算定义规则时，不确认「定义新运算」。",
        )
    if name in {"工程效率问题", "工程问题"} or name.endswith("工程问题"):
        add("supporting_structures", "work_rate_task", "work_efficiency_relation", "work_progress_ratio", "gaosi_work_rate")
        add("exclude_structures", "motion_task", "growth_consumption")
        add("confusable_with", "小数分数混合运算", "牛吃草模型", "行程问题")
        add(
            "fact_extraction_hints",
            "工程问题准入必须识别 work_rate_task（工程、总工程量、完成任务语境），并识别 work_efficiency_relation 或 work_progress_ratio（完成量、未完成量、剩余工程量随时间变化的比例关系）。",
        )
        add(
            "negative_hints",
            "只有分数或除法算式，但没有工程/任务完成语境和完成进度关系时，不确认「工程问题」。",
        )
    if "圆与扇形" in name:
        add("supporting_structures", "geometry_circle", "area_goal", "geometry_rotation", "rotation_direction", "area_decomposition", "gaosi_cut_paste")
        add("exclude_structures", "statistics_chart_context", "school_statistics", "statistics_percent_conversion", "school_volume", "cylinder_surface_volume")
        add("confusable_with", "扇形统计图", "统计图综合", "钟表问题", "圆柱表面积/体积")
        add(
            "fact_extraction_hints",
            "圆与扇形准入时，应识别 geometry_circle（圆、半圆、扇形、半径、直径、圆心角、弧）以及 area_goal 或 arc_length_goal（求面积、阴影面积、弧长或周长关系）。",
            "如果出现顺时针/逆时针，只能作为 rotation_direction 或 geometry_rotation 的证据，不能作为钟表结构。",
        )
        add(
            "negative_hints",
            "如果题目是扇形统计图、百分比统计、读图换算或圆柱体积/表面积，不确认「圆与扇形」。",
            "只有“圆”“扇形”词语但没有几何面积、弧长、半径直径或圆心角目标时，不自动确认。",
        )
    if "牛吃草" in name:
        add("supporting_structures", "resource_growth", "resource_consumption", "resource_time_or_initial", "growth_consumption")
        add("exclude_structures", "geometry_rotation", "statistics_chart_context")
        if "钟表" not in name:
            add("exclude_structures", "clock_face", "clock_hands_relation")
        add("confusable_with", "工程效率问题", "钟表问题", "比例应用")
        add(
            "fact_extraction_hints",
            "牛吃草准入必须同时识别 resource_growth（增长/生长/流入）、resource_consumption（消耗/吃完/流出）和 resource_time_or_initial（时间/每天/原有量）。",
        )
        add(
            "negative_hints",
            "只有“牛吃草”标题或单独出现牛、草、吃等词，不确认牛吃草；必须有增长 + 消耗 + 时间/原有量三类结构。",
        )
    if "钟表" in name:
        add("supporting_structures", "clock_face", "clock_hands_relation", "time_angle_goal")
        add("exclude_structures", "geometry_rotation", "statistics_chart_context")
        add("confusable_with", "圆与扇形", "几何旋转")
        add(
            "fact_extraction_hints",
            "钟表准入必须识别 clock_face（钟面/表盘）、clock_hands_relation（时针分针关系）和 time_angle_goal（时刻、夹角、重合、垂直等目标）。",
        )
        add(
            "negative_hints",
            "只有“顺时针/逆时针”不能单独触发钟表问题；几何旋转题中的方向词只属于 rotation_direction。",
        )
    if "扇形统计图" in name or "统计图综合" in name:
        add("supporting_structures", "statistics_chart_context", "statistics_percent_conversion", "school_statistics")
        add("confusable_with", "圆与扇形", "平均数")
        add(
            "fact_extraction_hints",
            "扇形统计图/统计图综合准入必须命中 statistics_chart_context（统计图或统计表读图场景），并优先识别百分比、人数、圆心角或占比换算。",
        )
        add(
            "negative_hints",
            "如果题目目标是几何阴影面积、弧长或圆与扇形公式计算，而不是统计图读图，不确认统计图知识点。",
        )
    if "平均" in name:
        add("supporting_structures", "gaosi_average", "school_average_division", "part_whole_count")
        add("confusable_with", "平均分应用", "统计图综合")
        add("negative_hints", "只有“每份”“每人”等除法词而没有平均量、总数与份数关系时，不确认平均数。")
    if "利润" in name or "折扣" in name:
        add("supporting_structures", "profit_discount", "price_profit_relation", "percent_calculation")
        add("exclude_structures", "concentration_task", "statistics_chart_context")
        add("confusable_with", "浓度问题", "百分数意义与计算", "比例应用")
        add("negative_hints", "只有百分号或比例词但没有进价、售价、标价、利润、折扣等商业关系时，不确认利润折扣。")
    if "比例" in name or "比" == name:
        add("supporting_structures", "ratio_relation", "whole_part_relation", "proportion_application")
        add("exclude_structures", "profit_discount", "concentration_task")
        add("confusable_with", "百分数意义与计算", "利润折扣问题", "浓度问题")
        add("negative_hints", "只有冒号、百分号或“比”字但没有两个或多个数量之间的比例关系时，不确认比例应用。")
    if "整除" in name or "因数" in name or "倍数" in name or "约数" in name:
        add("supporting_structures", "gaosi_divisibility", "number_theory_factor_multiple", "divisibility_rule", "integer_constraint")
        add("exclude_structures", "decimal_fraction_calculation")
        add("confusable_with", "数字谜", "普通四则计算")
        add("negative_hints", "普通算式计算或小数分数计算中没有整数限制、整除条件、因数倍数条件时，不确认整除/因数倍数。")
    if "概率" in name or "可能性" in name:
        add("supporting_structures", "gaosi_probability", "school_probability", "counting_target")
        add("exclude_structures", "statistics_chart_context")
        add("confusable_with", "统计图综合", "排列组合")
        add("negative_hints", "只有普通计数或方案数问题但没有随机事件、等可能结果、摸取/抽取等概率结构时，不确认概率。")
    if "规律" in name or "周期" in name or "数列" in name or "数表" in name:
        add("supporting_structures", "sequence_pattern", "period_position", "gaosi_sequence")
        if "数表" in name:
            add("supporting_structures", "number_table_position_pattern")
        add("confusable_with", "分数裂项求和", "整除余数问题")
        add("negative_hints", "只有普通计算或单次求值，没有重复周期、位置定位、第 n 项或递推关系时，不确认找规律。")
    return additions


def _prune_unscoped_supporting_structures(
    name: str,
    supporting: Sequence[str],
    excludes: Sequence[str],
    required_structures: Sequence[Sequence[str]],
) -> List[str]:
    excluded = set(excludes)
    required = {key for group in required_structures for key in group}
    broad_scoring_keys = {
        "sequence_pattern",
        "period_position",
        "gaosi_sequence",
        "school_statistics",
        "statistics_chart_context",
        "statistics_percent_conversion",
        "gaosi_average",
        "school_average_division",
        "part_whole_count",
    }
    scoped_groups = [
        (
            ("整除", "因数", "倍数", "约数", "质数", "合数", "数论"),
            {"gaosi_divisibility", "number_theory_factor_multiple", "divisibility_rule", "integer_constraint"},
        ),
        (
            ("利润", "折扣", "经济", "售价", "进价"),
            {"profit_discount", "price_profit_relation"},
        ),
        (
            ("比例", "比", "整体关系"),
            {"ratio_relation", "whole_part_relation", "proportion_application"},
        ),
        (
            ("概率", "可能性"),
            {"gaosi_probability", "school_probability"},
        ),
        (
            ("规律", "周期", "数列", "递推"),
            {"sequence_pattern", "period_position", "gaosi_sequence"},
        ),
    ]
    result: List[str] = []
    for key in supporting:
        if key in excluded or key in required:
            continue
        if key in broad_scoring_keys and any(term in name for term in ("规律", "周期", "数列", "统计图", "平均")):
            continue
        if any(key in scoped_keys and not any(term in name for term in terms) for terms, scoped_keys in scoped_groups):
            continue
        result.append(key)
    return _unique(result)


def _is_high_risk_rule_node(node: Dict[str, Any]) -> bool:
    text = str(node.get("name") or "")
    return any(
        term in text
        for term in (
            "圆与扇形",
            "牛吃草",
            "钟表",
            "扇形统计图",
            "统计图综合",
            "平均",
            "利润",
            "折扣",
            "比例",
            "整除",
            "因数",
            "倍数",
            "概率",
            "规律",
            "定义新运算",
            "工程问题",
            "工程效率",
            "倒推还原",
            "小数分数混合运算",
        )
    )


def _high_risk_rule_summary(node: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "knowledge_point_id": str(node.get("knowledge_point_id") or ""),
        "name": str(node.get("name") or ""),
        "required_structures": node.get("required_structures") or [],
        "supporting_structures": node.get("supporting_structures") or [],
        "exclude_structures": node.get("exclude_structures") or [],
        "confusable_with": node.get("confusable_with") or [],
        "fact_extraction_hints": _string_list(node.get("fact_extraction_hints"))[:3],
        "negative_hints": _string_list(node.get("negative_hints"))[:4],
    }


def _contains_chinese(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(value or "")))


def _first_term(text: str, terms: Sequence[str]) -> str:
    for term in terms:
        term = str(term or "").strip()
        if term and term in text:
            return term
    return ""


def _has_counting_principle_context(text: str) -> bool:
    return bool(_first_term(text, ("加法原理", "乘法原理", "分类计数", "分步计数")))


def _statistics_chart_context_evidence(text: str) -> str:
    direct = _first_term(text, ("条形统计图", "扇形统计图", "折线统计图", "统计图", "统计表"))
    if direct:
        return direct
    if any(term in text for term in ("圆心角", "百分比", "占比")) and any(
        term in text for term in ("人数", "人", "数据", "统计")
    ):
        return _first_term(text, ("圆心角", "百分比", "占比")) or "统计图数据换算"
    return ""


def _statistics_percent_conversion_evidence(text: str) -> str:
    if not any(term in text for term in ("统计图", "条形统计图", "扇形统计图", "统计表", "圆心角")):
        return ""
    if any(term in text for term in ("百分比", "百分数", "占比", "%", "圆心角", "人数")):
        return _first_term(text, ("百分比", "百分数", "占比", "%", "圆心角", "人数")) or "统计图百分比换算"
    return ""


def _clock_problem_evidence(text: str) -> str:
    direct_topic = _first_term(text, ("钟表问题", "钟面", "钟表", "时钟", "钟"))
    has_both_hands = "时针" in text and "分针" in text
    has_time_expression = bool(re.search(r"\d+\s*(?:点|时)\s*(?:\d+\s*分)?", text))
    has_clock_relation = any(term in text for term in ("夹角", "重合", "成直线", "垂直", "追及", "相遇", "快慢"))
    if direct_topic and (has_both_hands or has_time_expression or has_clock_relation or direct_topic in {"钟表问题", "钟面", "钟表"}):
        return direct_topic
    if has_both_hands and (has_time_expression or has_clock_relation):
        return _first_term(text, ("时针", "分针", "夹角", "重合")) or "时针分针关系"
    return ""


def _fraction_application_evidence(text: str) -> str:
    if not any(term in text for term in ("分数", "几分之", "通分", "约分")) and not re.search(r"\d+\s*/\s*\d+", text):
        return ""
    if any(term in text for term in ("总数", "总量", "一共", "还剩", "剩下", "分给", "人数", "已知", "求")):
        return _first_term(text, ("几分之", "分数", "还剩", "总数", "总量")) or "分数应用题"
    return ""


def _fraction_whole_part_relation_evidence(text: str) -> str:
    has_fraction = bool(re.search(r"\d+\s*/\s*\d+", text)) or any(term in text for term in ("几分之", "分数"))
    has_total = any(term in text for term in ("总数", "总量", "一共", "共有", "有")) and re.search(r"\d+\s*(?:人|个|只|本|元|米|厘米|千克)?", text)
    has_part_relation = any(term in text for term in ("其中", "不经常", "经常", "部分", "整体", "总共")) and (
        "是" in text or "占" in text
    )
    if has_fraction and has_total and has_part_relation:
        return _first_term(text, ("其中", "不经常", "经常", "总数", "总量", "2/3")) or "分数整体部分关系"
    return ""


def _proportion_application_evidence(text: str) -> str:
    direct = _first_term(text, ("比例分配", "按比例", "正比例", "反比例"))
    if direct:
        return direct
    has_ratio = bool(re.search(r"\d+\s*[:：]\s*\d+", text)) or any(term in text for term in ("之比", "比是", "比例"))
    if has_ratio and any(term in text for term in ("总量", "总数", "分配", "人数", "销量", "路程", "速度", "面积")):
        return _first_term(text, ("之比", "比是", "比例", "总量", "分配")) or "比例应用题"
    return ""


def _school_reciprocal_concept_evidence(text: str) -> str:
    direct = _first_term(text, ("倒数", "互为倒数", "乘积为1"))
    if not direct:
        return ""
    if re.search(r"(?:的倒数|互为倒数|倒数是|乘积为\s*1)", text):
        return direct
    return direct if len(text) <= 80 else ""


def _school_24_point_evidence(text: str) -> str:
    if not any(term in text for term in ("24点", "结果等于24", "结果为24", "=24")):
        return ""
    has_digits = len(re.findall(r"\d+", text)) >= 4
    has_operations = any(term in text for term in ("加", "减", "乘", "除", "乘方", "括号", "+", "-", "×", "÷", "*", "/"))
    if has_digits and has_operations:
        return _first_term(text, ("24点", "结果等于24", "结果为24", "=24")) or "24点游戏"
    return ""


def _school_cube_net_evidence(text: str) -> str:
    if "展开图" not in text:
        return ""
    direct = _first_term(text, ("正方体展开图", "正方体的展开图", "长方体展开图", "长方体的展开图"))
    if direct:
        return direct
    if any(term in text for term in ("折叠", "对面", "相邻面", "不是")) and any(
        term in text for term in ("正方体", "长方体", "立体图形", "正方形")
    ):
        return _first_term(text, ("展开图", "折叠", "不是")) or "正方体展开图"
    return ""


def _school_symbol_equation_substitution_evidence(text: str) -> str:
    has_symbol_unknown = any(term in text for term in ("△", "□", "○", "☆", "▲", "■"))
    has_represents_number = any(term in text for term in ("代表一个数", "各代表", "代表数", "表示一个数"))
    has_equation = "=" in text and any(term in text for term in ("+", "-", "＋", "－"))
    if has_symbol_unknown and (has_represents_number or has_equation):
        return _first_term(text, ("代表一个数", "各代表", "=", "△", "□")) or "符号等量代换"
    return ""


def _school_prime_factorization_evidence(text: str) -> str:
    direct = _first_term(text, ("分解质因数", "质因数分解"))
    if direct:
        return direct
    if "质因数" in text and any(term in text for term in ("和", "个数", "最大", "最小", "所有")):
        return "质因数"
    return ""


def _palindrome_number_counting_evidence(text: str) -> str:
    if not any(term in text for term in ("回文数", "正着读、反着读", "正着读", "反着读")):
        return ""
    has_count_goal = any(term in text for term in ("共有", "多少", "个数", "几个", "统计"))
    has_range_or_digit = bool(re.search(r"\d+\s*[-~至到]\s*\d+", text)) or any(
        term in text for term in ("数位", "一位数", "两位数", "三位数", "四位数")
    )
    if has_count_goal and has_range_or_digit:
        return _first_term(text, ("回文数", "正着读、反着读", "正着读", "反着读")) or "回文数计数"
    return ""


def _gaosi_place_value_principle_evidence(text: str) -> str:
    direct = _first_term(text, ("位值原理", "数位交换", "交换数位"))
    if direct:
        return direct
    if re.search(r"[a-zA-Z]{2,4}", text) and any(term in text for term in ("表示", "三位数", "两位数", "组成")):
        return _first_term(text, ("三位数", "两位数", "组成", "表示")) or "位值制数字谜"
    has_place_digits = any(term in text for term in ("个位", "十位", "百位", "千位", "数位"))
    has_multi_digit = any(term in text for term in ("两位数", "三位数", "四位数", "多位数")) or bool(
        re.search(r"[个十百千]位数字", text)
    )
    has_place_change = any(term in text for term in ("交换", "调换", "变大", "变小", "相差", "差了"))
    if has_place_digits and has_multi_digit and has_place_change:
        return _first_term(text, ("三位数", "百位", "十位", "个位", "交换")) or "数位交换"
    return ""


def _full_reduction_discount_evidence(text: str) -> str:
    if re.search(r"满\s*\d+(?:\.\d+)?\s*元?\s*减\s*\d+(?:\.\d+)?", text):
        return _first_term(text, ("满", "减", "凑单", "下单", "优惠")) or "满减优惠"
    if "凑单" in text and any(term in text for term in ("优惠", "满减", "总费用", "最省", "最低")):
        return _first_term(text, ("凑单", "优惠", "满减", "总费用")) or "凑单优惠"
    return ""


def _remainder_congruence_evidence(text: str) -> str:
    if re.search(r"被\s*\d+\s*除\s*余\s*\d+", text) or re.search(r"除以\s*\d+\s*余\s*\d+", text):
        return _first_term(text, ("同余", "余数", "除余")) or "被除余数条件"
    if re.search(r"余\s*\d+", text) and any(term in text for term in ("被", "除", "最小", "满足条件")):
        return _first_term(text, ("同余", "余数", "余")) or "余数条件"
    return ""


def _segment_equal_midpoint_evidence(text: str) -> str:
    if not any(term in text for term in ("三角形", "△")):
        return ""
    if not any(term in text for term in ("面积", "阴影", "等底", "等高")):
        return ""
    if re.search(r"[A-Z]{1,2}\s*=\s*[A-Z]{1,2}", text):
        return _first_term(text, ("中点", "中线", "等底等高", "面积")) or "线段相等面积关系"
    return ""


def _pythagorean_area_relation_evidence(text: str) -> str:
    if "直角三角形" not in text:
        return ""
    if "正方形" not in text or "面积" not in text:
        return ""
    if any(term in text for term in ("三边", "斜边", "勾股")):
        return _first_term(text, ("勾股", "三边", "斜边", "正方形面积")) or "勾股面积关系"
    return ""


def _square_difference_odd_evidence(text: str) -> str:
    has_square = any(term in text for term in ("平方差", "平方数差", "平方"))
    has_odd_or_continuous = any(term in text for term in ("连续奇数", "连续", "奇数"))
    has_number_theory_goal = any(term in text for term in ("整除", "倍数", "余数", "整数", "定义"))
    if has_square and has_odd_or_continuous and has_number_theory_goal:
        return _first_term(text, ("连续奇数", "平方差", "平方数差", "整除")) or "连续奇数平方差"
    return ""


def _periodic_grid_evidence(text: str) -> str:
    if not any(term in text for term in ("周期", "循环", "重复", "按规律")):
        return ""
    if any(term in text for term in ("格子", "方格", "数表", "表格", "位置", "第")):
        return _first_term(text, ("周期", "循环", "格子", "方格", "数表")) or "周期格子"
    return ""


def _state_recurrence_evidence(text: str) -> str:
    direct = _first_term(text, ("传数游戏", "状态转移", "递推", "还原问题", "爬楼梯", "一级或两级台阶", "台阶走法"))
    if direct:
        return direct
    if any(term in text for term in ("每次", "轮流", "传给", "操作后", "最后")) and any(
        term in text for term in ("原来", "倒推", "还原", "第n次", "第 n 次")
    ):
        return _first_term(text, ("每次", "最后", "原来", "倒推")) or "状态转移还原"
    return ""


def _line_plane_recurrence_evidence(text: str) -> str:
    if any(term in text for term in ("直线分平面", "直线把平面", "分成最多")):
        return _first_term(text, ("直线分平面", "直线", "平面")) or "直线分平面"
    if re.search(r"直线.{0,12}平面.{0,8}分成", text) or re.search(r"直线.{0,12}分成.{0,8}部分", text):
        return _first_term(text, ("直线", "平面", "部分")) or "直线分平面"
    return ""


def _variable_speed_round_trip_evidence(text: str) -> str:
    has_segment_speed = any(term in text for term in ("上坡", "下坡", "平路", "顺水", "逆水", "去程", "返程"))
    has_round_trip = (
        any(term in text for term in ("往返", "返回", "返程"))
        or bool(
            re.search(r"甲地.{0,4}乙地", text)
            and re.search(r"乙地.{0,4}甲地", text)
        )
    )
    has_speed_distance = any(term in text for term in ("每小时", "千米", "速度", "行驶", "小时"))
    if has_segment_speed and has_round_trip and has_speed_distance:
        return _first_term(text, ("上坡", "下坡", "平路", "往返", "从乙地到甲地")) or "变速往返行程"
    return ""


def _travel_equation_same_distance_evidence(text: str) -> str:
    has_motion = any(term in text for term in ("速度", "路程", "从A", "到B", "A处到B处", "爬到"))
    has_same_distance = any(term in text for term in ("A处到B处", "从A处爬到B处", "从 A 处爬到 B 处", "路程"))
    has_speed_change = bool(re.search(r"速度.{0,8}(?:增加|提高|加快)", text)) or "速度每分钟增加" in text
    has_time_gain = any(term in text for term in ("提前", "早到", "少用", "提前到达"))
    if has_motion and has_same_distance and has_speed_change and has_time_gain:
        return _first_term(text, ("速度每分钟增加", "提前", "路程", "A处到B处")) or "速度增加提前到达"
    return ""


def _reverse_surplus_payment_process_evidence(text: str) -> str:
    has_payment_change = any(term in text for term in ("奖励", "奖金", "交纳", "交费", "学费", "银币", "钱袋"))
    has_process_switch = any(term in text for term in ("不要奖金", "反而", "继续学习", "又学", "学习了一阵"))
    has_remainder_or_start = any(term in text for term in ("剩", "还剩", "最初", "一开始", "原有", "空空如也"))
    has_ratio = any(term in text for term in ("四分之一", "几分之一", "一半", "时间"))
    if has_payment_change and has_process_switch and has_remainder_or_start:
        return _first_term(text, ("奖励", "交纳", "还剩", "最初", "四分之一")) or "收支变化倒推"
    if has_payment_change and has_remainder_or_start and has_ratio:
        return _first_term(text, ("奖励", "交纳", "还剩", "最初", "四分之一")) or "收支变化倒推"
    return ""


def _school_unit_division_context_evidence(text: str) -> str:
    if any(term in text for term in ("阀门", "漏水", "水表")) and any(term in text for term in ("关闭", "确定", "查明")):
        return ""
    direct = _first_term(
        text,
        (
            "平均分",
            "每层",
            "每组",
            "每个小组",
            "每个",
            "每人",
            "每份",
            "每袋",
            "每盒",
            "每箱",
            "一层高",
            "摞",
        ),
    )
    if direct:
        return direct
    patterns = (
        r"\d+\s*层高.{0,12}一层高",
        r"一层高.{0,12}\d+\s*层",
        r"摞\s*\d+\s*层",
        r"完成\s*\d+\s*个.{0,16}耗时",
        r"耗时.{0,16}完成\s*\d+\s*个",
        r"按照这样的制作效率",
    )
    if _work_rate_task_evidence(text):
        patterns = patterns[:3]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return ""


def _school_square_tiling_perimeter_evidence(text: str) -> str:
    if not any(term in text for term in ("周长", "四周", "装饰条", "边框", "围")):
        return ""
    if not any(term in text for term in ("小正方形", "正方形")):
        return ""
    if not any(term in text for term in ("拼成", "拼接", "贴在一起", "共边", "周长最小", "周长最大", "周长最少", "装饰条最少")):
        return ""
    return _first_term(text, ("周长最小", "周长最大", "装饰条最少", "小正方形", "拼成", "贴在一起", "共边")) or "正方形拼图周长"


def _perimeter_scale_relation_evidence(text: str) -> str:
    has_perimeter = "周长" in text
    has_square_or_rectangle = any(term in text for term in ("正方形", "长方形", "边长"))
    has_scale = any(term in text for term in ("扩大为原来的", "缩小为原来的", "扩大到", "缩小到", "倍"))
    if has_perimeter and has_square_or_rectangle and has_scale:
        return _first_term(text, ("边长扩大", "边长缩小", "周长扩大", "周长缩小", "扩大为原来的")) or "周长倍数关系"
    return ""


def _division_quotient_digit_zero_evidence(text: str) -> str:
    has_division = "÷" in text or "除" in text
    has_digit_judgment = any(term in text for term in ("商是三位数", "商是两位数", "商的最高位", "商末尾有 0", "商末尾有0", "商中间有0"))
    has_unknown_digit = any(term in text for term in ("□", "◇", "里最小填", "里最大填"))
    if has_division and has_digit_judgment and has_unknown_digit:
        return _first_term(text, ("商是三位数", "商的最高位", "商末尾有 0", "商末尾有0", "□")) or "商的位数与末尾0判断"
    return ""


def _folded_perimeter_change_evidence(text: str) -> str:
    has_perimeter = "周长" in text
    has_fold = any(term in text for term in ("对折", "折叠", "上下对折", "再对折"))
    has_rectangle_square = any(term in text for term in ("正方形", "长方形"))
    has_change = any(term in text for term in ("减少", "增加", "变化", "得到的新图形"))
    if has_perimeter and has_fold and has_rectangle_square and has_change:
        return _first_term(text, ("对折", "再对折", "周长减少", "新图形周长")) or "折叠后的周长变化"
    return ""


def _polygon_perimeter_evidence(text: str) -> str:
    if any(term in text for term in ("正三角形", "等边三角形", "中点")):
        return ""
    has_perimeter = "周长" in text
    has_polygon = any(term in text for term in ("五边形", "阶梯形", "多边形", "不规则图形", "边长分别", "尺寸标注"))
    if has_perimeter and has_polygon:
        return _first_term(text, ("五边形", "阶梯形", "多边形", "边长分别", "周长")) or "多边形周长"
    return ""


def _rectangle_tiling_min_perimeter_evidence(text: str) -> str:
    has_tiles = any(term in text for term in ("小正方形", "正方形", "卡片")) and any(term in text for term in ("拼成", "贴在一起", "做成长方形"))
    has_outer_boundary = any(term in text for term in ("四周", "装饰条", "边框"))
    has_min_goal = any(term in text for term in ("最少", "最小", "尽量少", "贴的装饰条最少"))
    if has_tiles and has_outer_boundary and has_min_goal:
        return _first_term(text, ("贴在一起", "做成长方形", "四周", "装饰条", "最少")) or "拼接图形周长最小化"
    return ""


def _equilateral_triangle_perimeter_transform_evidence(text: str) -> str:
    has_equilateral = any(term in text for term in ("正三角形", "等边三角形"))
    has_perimeter_goal = "周长" in text
    has_length_transfer = any(term in text for term in ("中点", "边长", "线段", "多边形", "周长"))
    if has_equilateral and has_perimeter_goal and has_length_transfer:
        return _first_term(text, ("正三角形", "等边三角形", "中点", "周长")) or "等边三角形周长转化"
    return ""


def _swallowtail_area_model_evidence(text: str) -> str:
    direct = _first_term(text, ("燕尾模型", "风筝与燕尾"))
    if direct:
        return direct
    has_area_goal = any(term in text for term in ("面积", "平方厘米", "平方分米", "平方米"))
    has_square_context = "正方形" in text and re.search(r"ABCD", text)
    has_triangle_context = "三角形" in text and any(term in text for term in ("PAB", "PBD", "等腰三角形", "以AB为底边"))
    has_model_vertices = "PBD" in text and ("PAB" in text or "AB为底边" in text)
    if has_area_goal and has_square_context and has_triangle_context and has_model_vertices:
        return _first_term(text, ("PBD", "PAB", "正方形", "等腰三角形")) or "燕尾面积结构"
    return ""


def _area_ratio_relation_evidence(text: str) -> str:
    direct = _first_term(text, ("面积比", "面积之比", "等高", "共边", "同底", "同高"))
    if direct:
        return direct
    if "面积" in text and any(term in text for term in ("中点", "中位线", "比例", "之比", "倍")) and any(
        term in text for term in ("三角形", "四边形", "正方形", "长方形")
    ):
        return _first_term(text, ("面积", "中点", "中位线", "比例")) or "面积比例关系"
    return ""


def _butterfly_area_model_evidence(text: str) -> str:
    has_quadrilateral_diagonal = any(term in text for term in ("四边形", "梯形")) and any(
        term in text for term in ("对角线", "相交于", "交于 O", "交于O")
    )
    has_triangle_areas = "三角形" in text and "面积" in text and len(re.findall(r"面积(?:为|是)?\s*\d+", text)) >= 2
    has_ratio = bool(re.search(r"[A-Z]{1,2}\s*[:：]\s*[A-Z]{1,2}\s*=\s*\d+\s*[:：]\s*\d+", text)) or any(
        term in text for term in ("面积比", "之比", "BE：EC", "BE:EC")
    )
    if has_quadrilateral_diagonal and has_triangle_areas and has_ratio:
        return _first_term(text, ("对角线", "相交于 O", "BE：EC", "面积为")) or "蝴蝶模型面积比例"
    return ""


def _overlap_area_evidence(text: str) -> str:
    if any(term in text for term in ("重叠面积", "重合面积", "重叠部分", "公共部分")):
        return _first_term(text, ("重叠面积", "重合面积", "重叠部分", "公共部分")) or "重叠面积"
    if "面积" in text and any(term in text for term in ("重叠", "覆盖", "交叠", "公共")):
        return _first_term(text, ("重叠", "覆盖", "公共")) or "重叠面积"
    return ""


def _tangram_area_evidence(text: str) -> str:
    if any(term in text for term in ("七巧板", "七巧板面积")):
        return _first_term(text, ("七巧板面积", "七巧板")) or "七巧板面积"
    return ""


def _zhao_shuang_diagram_evidence(text: str) -> str:
    if any(term in text for term in ("赵爽弦图", "弦图", "勾股弦图")):
        return _first_term(text, ("赵爽弦图", "弦图", "勾股弦图")) or "赵爽弦图"
    return ""


def _fold_cut_unfold_evidence(text: str) -> str:
    direct = _first_term(text, ("折叠展开", "剪纸", "剪开", "展开后", "折后展开"))
    if direct:
        return direct
    if any(term in text for term in ("折叠", "翻折", "对折")) and any(term in text for term in ("剪", "展开", "痕迹", "得到的图形")):
        return _first_term(text, ("折叠", "翻折", "剪", "展开")) or "折叠展开"
    return ""


def _geometry_transform_puzzle_evidence(text: str) -> str:
    direct = _first_term(text, ("俄罗斯方块", "平移旋转", "旋转平移", "图形变换"))
    if direct:
        return direct
    if any(term in text for term in ("平移", "旋转", "翻转")) and any(term in text for term in ("拼成", "拼图", "方块", "图形")):
        return _first_term(text, ("平移", "旋转", "翻转", "拼图")) or "几何变换拼图"
    return ""


def _reuleaux_triangle_evidence(text: str) -> str:
    if any(term in text for term in ("勒洛三角形", "弓形", "圆弧三角形")):
        return _first_term(text, ("勒洛三角形", "弓形", "圆弧三角形")) or "勒洛三角形"
    return ""


def _cylinder_surface_volume_evidence(text: str) -> str:
    if "圆柱" not in text:
        return ""
    if any(term in text for term in ("侧面展开", "展开图", "展开后", "卷纸", "彩纸", "纸卷", "厚度", "表面积", "体积", "底面积", "最大")):
        return _first_term(text, ("圆柱", "卷纸", "彩纸", "侧面展开", "展开后", "厚度", "表面积", "体积", "底面积")) or "圆柱侧面展开"
    return ""


def _cylinder_surface_volume_composite_evidence(text: str) -> str:
    if "圆柱" not in text:
        return ""
    if any(term in text for term in ("侧面展开", "重新围成", "最大底面积", "展开后")):
        return ""
    has_surface = any(term in text for term in ("表面积", "侧面", "盖子", "装饰部分", "面积"))
    has_volume = any(term in text for term in ("体积", "容积", "酒水", "高度", "内高", "外高"))
    has_dimensions = any(term in text for term in ("直径", "半径", "底面", "高", "π"))
    if has_surface and has_volume and has_dimensions:
        return _first_term(text, ("圆柱形", "装饰部分", "酒水", "体积", "直径")) or "圆柱表面积与体积综合"
    return ""


def _school_rectangle_property_evidence(text: str) -> str:
    if "长方形" not in text:
        return ""
    return _first_term(
        text,
        (
            "围成一个长方形",
            "围成长方形",
            "能围成",
            "表示点",
            "点的位置",
            "长方形的性质",
        ),
    )


def _work_rate_task_evidence(text: str) -> str:
    direct = _first_term(text, ("工程", "工作效率", "总工程量", "剩余工程", "共同完成", "每天完成"))
    if direct:
        return direct
    if any(term in text for term in ("单独", "合作", "合做", "效率")) and any(
        term in text for term in ("工程", "工作", "任务", "共同完成", "单独完成", "每天完成", "做了", "再做")
    ):
        return _first_term(text, ("单独", "合作", "合做", "效率")) or "工程效率关系"
    return ""


def _work_progress_ratio_evidence(text: str) -> str:
    has_work_context = any(term in text for term in ("工程", "工作", "任务", "总工程量"))
    has_progress_terms = "已完成" in text and any(term in text for term in ("未完成", "剩余", "剩下"))
    has_time_change = any(term in text for term in ("再做", "又做", "若干天", "总共需", "才能完成", "完成这件工程"))
    has_ratio = bool(re.search(r"\d+\s*/\s*\d+|\d+\s*:\s*\d+|之比|是.{0,8}的", text))
    if has_work_context and has_progress_terms and has_time_change and has_ratio:
        match = re.search(r"已完成.{0,40}(?:未完成|剩余|剩下).{0,40}(?:再做|又做|总共需|才能完成).{0,40}", text)
        return match.group(0) if match else _first_term(text, ("已完成", "未完成", "再做", "总共需")) or "工程进度比例"
    return ""


def _condition_enumeration_integer_split_evidence(text: str) -> str:
    has_total_split = bool(re.search(r"共(?:派了|有|分成)?\s*\d+", text)) or any(term in text for term in ("总共", "合计"))
    has_distinct_positive = any(term in text for term in ("都不一样", "互不相同", "各不相同")) and any(
        term in text for term in ("至少", "每国", "每人", "每组", "正整数")
    )
    has_pair_sum = bool(re.search(r".{0,8}和.{0,8}共(?:派出|有)?\s*\d+", text))
    has_unique_condition = any(term in text for term in ("仅有一个", "只有一个", "恰有一个"))
    if has_total_split and has_distinct_positive and (has_pair_sum or has_unique_condition):
        return _first_term(text, ("都不一样", "至少", "共派出", "仅有一个", "互不相同")) or "条件枚举整数拆分"
    return ""


def _rotation_area_transform_evidence(text: str) -> str:
    has_rotation = any(term in text for term in ("旋转", "顺时针", "逆时针", "绕"))
    has_area_goal = any(term in text for term in ("阴影", "面积", "平方厘米", "平方分米", "平方米"))
    explicit_circle_topic = any(term in text for term in ("半圆", "圆形", "圆弧", "扇形", "圆心角"))
    if explicit_circle_topic and not any(term in text for term in ("整体法", "整体", "割补", "转化")):
        return ""
    has_circle_signal = any(term in text for term in ("π", "圆", "扇形", "圆弧", "半径", "直径", "90°", "90 度"))
    if has_rotation and has_area_goal and has_circle_signal:
        return _first_term(text, ("阴影部分的面积", "旋转", "顺时针", "π", "90°")) or "旋转割补求阴影面积"
    return ""


def _binary_search_strategy_evidence(text: str) -> str:
    has_search_context = any(term in text for term in ("漏水", "阀门", "水表", "关闭部分", "排查", "查明"))
    has_feedback = any(term in text for term in ("显示有水", "未显示", "仍在使用", "就知道", "确定"))
    has_split = bool(re.search(r"\d+\s*号和\s*\d+\s*号之间", text)) or any(term in text for term in ("之间", "部分人家", "一户"))
    has_optimal_goal = any(term in text for term in ("至少需要", "最少", "才能确定", "确定漏水"))
    if has_search_context and has_feedback and has_split and has_optimal_goal:
        return _first_term(text, ("阀门", "水表显示", "未显示", "至少需要", "确定漏水")) or "二分排查策略"
    return ""


def _defined_operation_rule_evidence(text: str) -> str:
    if any(term in text for term in ("规定一种运算", "定义一种运算", "定义新运算", "新定义运算", "一种运算")):
        return _first_term(text, ("规定一种运算", "定义一种运算", "定义新运算", "新定义运算", "一种运算")) or "定义新运算"
    return ""


def _defined_operation_symbol_evidence(text: str) -> str:
    match = re.search(r"[※★☆△▲□○◎◇◆⊙#@]", text)
    return match.group(0) if match else ""


def _defined_operation_target_evidence(text: str) -> str:
    if not _defined_operation_symbol_evidence(text):
        return ""
    if any(term in text for term in ("应填", "□中", "求□", "求出", "等于多少")) or "□" in text:
        return _first_term(text, ("应填", "□中", "求□", "求出", "等于多少", "□")) or "新定义运算目标"
    return ""


def _consecutive_product_definition_evidence(text: str) -> str:
    direct = _first_term(text, ("连续三数乘积", "连续三个数的乘积", "连续整数乘积"))
    if direct:
        return direct
    match = re.search(r"[※★☆△▲□○◎◇◆⊙#@]\s*\d+\s*=\s*\d+\s*[×*xX]\s*\d+\s*[×*xX]\s*\d+", text)
    return match.group(0) if match else ""


def _half_recurrence_process_evidence(text: str) -> str:
    has_half = any(term in text for term in ("一半", "二分之一", "1/2", "半"))
    has_step = any(term in text for term in ("每小时", "每次", "每天", "每轮", "每过"))
    has_loss = any(term in text for term in ("失去", "减少", "剩下", "留下", "减去"))
    if has_half and has_step and has_loss:
        match = re.search(r"(?:每小时|每次|每天|每轮|每过).{0,18}(?:一半|二分之一|1/2|半)", text)
        return match.group(0) if match else _first_term(text, ("一半", "失去", "每小时")) or "倍半递推"
    return ""


def _reverse_process_evidence(text: str) -> str:
    if any(term in text for term in ("一开始", "原来", "最初", "开始")) and any(
        term in text for term in ("后", "之后", "最后", "末端", "剩下")
    ):
        return _first_term(text, ("一开始", "原来", "最初", "最后", "之后", "剩下")) or "倒推还原"
    return ""


def _cut_paste_area_decomposition_evidence(text: str) -> str:
    has_area_goal = any(term in text for term in ("阴影", "面积", "平方厘米", "平方米", "平方分米"))
    has_composite_shape = any(term in text for term in ("正方形", "长方形", "三角形", "扇形", "圆弧", "圆", "组合图形", "几何图形"))
    has_decomposition_signal = any(term in text for term in ("割补", "剪拼", "拼接", "分解", "组合", "内含", "形成"))
    if has_area_goal and has_composite_shape and has_decomposition_signal:
        return _first_term(text, ("阴影部分", "割补", "剪拼", "内含", "形成", "组合图形", "面积")) or "图形割补面积"
    return ""


def _triangle_angle_classification_evidence(text: str) -> str:
    has_triangle = "三角形" in text
    has_angle_ratio = (
        ("角" in text and any(term in text for term in ("度数的比", "角的比", "度数比")))
        or bool(re.search(r"角.{0,12}\d+\s*[:：]\s*\d+\s*[:：]\s*\d+", text))
    )
    has_classification_target = any(term in text for term in ("锐角三角形", "直角三角形", "钝角三角形", "等腰三角形", "是什么三角形"))
    if has_triangle and has_angle_ratio and has_classification_target:
        return _first_term(text, ("三角形三个角", "度数的比", "锐角三角形", "直角三角形", "钝角三角形")) or "三角形按角分类"
    return ""


def _cylinder_cone_volume_height_ratio_evidence(text: str) -> str:
    if not ("圆柱" in text and "圆锥" in text):
        return ""
    has_equal_base_area = any(term in text for term in ("底面积相等", "底面积相同", "等底面积", "底面积都相等"))
    has_volume_ratio = any(term in text for term in ("体积比", "体积之比", "体积的比"))
    has_height_ratio_goal = any(term in text for term in ("高的比", "高度比", "高之比"))
    if has_equal_base_area and has_volume_ratio and has_height_ratio_goal:
        return _first_term(text, ("底面积相等", "体积比", "高的比", "圆柱", "圆锥")) or "圆柱圆锥体积高关系"
    return ""


def _cylinder_cone_volume_ratio_evidence(text: str) -> str:
    if not ("圆柱" in text and "圆锥" in text):
        return ""
    has_same_height = any(term in text for term in ("高相同", "等高", "高度相同"))
    has_radius_ratio = any(term in text for term in ("底面半径之比", "半径之比", "底面半径的比", "半径比"))
    has_volume_ratio_goal = any(term in text for term in ("体积比", "体积之比", "体积的比"))
    if has_same_height and has_radius_ratio and has_volume_ratio_goal:
        return _first_term(text, ("高相同", "底面半径之比", "半径之比", "体积比")) or "圆柱圆锥体积比"
    return ""


def _composite_area_split_relation_evidence(text: str) -> str:
    has_area_goal = any(term in text for term in ("阴影三角形面积", "阴影部分面积", "原长方形面积", "面积为", "面积是"))
    has_split = any(term in text for term in ("长方形被", "分成两个长方形", "被一条直线分成", "分割"))
    has_ratio_relation = any(term in text for term in ("宽的比", "宽之比", "宽的比为", "宽的比是"))
    if "长方形" in text and has_area_goal and has_split and has_ratio_relation:
        return _first_term(text, ("长方形被", "分成两个长方形", "宽的比", "阴影三角形面积", "原长方形面积")) or "组合图形分割面积"
    return ""


def _rectangle_area_fraction_percent_change_evidence(text: str) -> str:
    if "长方形" not in text or "面积" not in text:
        return ""
    has_length_change = "长" in text and any(term in text for term in ("增加", "减少", "扩大", "缩小"))
    has_width_change = "宽" in text and any(term in text for term in ("增加", "减少", "扩大", "缩小"))
    has_fraction_change = bool(re.search(r"\d+\s*/\s*\d+", text)) or any(term in text for term in ("几分之", "分数"))
    asks_percent_of_original = any(term in text for term in ("原来的", "原来", "百分之", "%"))
    has_price_context = any(term in text for term in ("标价", "售价", "进价", "成本", "利润", "折扣", "打折", "优惠"))
    if has_length_change and has_width_change and has_fraction_change and asks_percent_of_original and not has_price_context:
        return _first_term(text, ("长增加", "长减少", "宽增加", "宽减少", "面积是原来的", "原来的")) or "长方形面积变化"
    return ""


def _number_table_position_pattern_evidence(text: str) -> str:
    has_table = any(term in text for term in ("数表", "表规律", "下表", "排成"))
    has_sequence = any(term in text for term in ("正整数", "依次", "规律", "排列规律", "按表规律"))
    has_position_goal = any(term in text for term in ("第几行", "第几列", "第（", "第()行", "行，第", "列"))
    has_column_count = bool(re.search(r"\d+\s*列", text))
    if has_table and has_sequence and has_position_goal and has_column_count:
        return _first_term(text, ("按下表规律", "排列规律", "排成", "第几行", "第几列", "数表")) or "数表位置规律"
    return ""


def _gaosi_permutation_combination_evidence(text: str) -> str:
    if _number_table_position_pattern_evidence(text):
        return ""
    if any(term in text for term in ("排列组合", "组合的巧算", "A和C", "分类与分步")):
        return _first_term(text, ("排列组合", "组合的巧算", "A和C", "分类与分步")) or "排列组合"
    if any(term in text for term in ("安排", "排队")) and any(
        term in text for term in ("几种", "多少种", "方案", "方法", "顺序")
    ):
        return _first_term(text, ("安排", "排队", "几种", "方案")) or "排列组合计数"
    if "排列" in text and not any(term in text for term in ("排列规律", "按规律排列", "排成")):
        return "排列"
    return ""


def _surplus_deficit_evidence(text: str) -> str:
    direct = _first_term(text, ("盈亏", "盈余", "亏欠"))
    if direct:
        return direct
    if not any(term in text for term in ("多出", "多了", "少了", "不够", "剩下")):
        return ""
    if not any(term in text for term in ("每人", "每组", "分给", "分配", "发给", "如果", "则")):
        return ""
    match = re.search(r"(?:多出|多了|少了|不够|剩下).{0,12}(?:多出|多了|少了|不够|剩下|正好)", text)
    return match.group(0) if match else ""


def _chicken_rabbit_evidence(text: str) -> str:
    direct = _first_term(text, ("鸡兔同笼", "头脚问题"))
    if direct:
        return direct
    if "鸡" in text and "兔" in text and any(term in text for term in ("头", "脚", "腿", "只")):
        return _first_term(text, ("鸡", "兔")) or "鸡兔"
    if "两类" in text and re.search(r"(?:头|只).{0,12}(?:脚|腿)|(?:脚|腿).{0,12}(?:头|只)", text):
        return "两类头腿关系"
    return ""


def _two_type_cost_total_evidence(text: str) -> str:
    has_two_types = bool(
        re.search(r"(\u4e2d\u578b|\u5c0f\u578b|\u5927\u578b|\u7532|\u4e59|A|B).{0,12}(\u5c0f\u578b|\u4e2d\u578b|\u5927\u578b|\u7532|\u4e59|A|B)", text)
    ) or any(term in text for term in ("两种", "两类", "两辆", "两种票", "两种商品"))
    has_total_count = any(term in text for term in ("共", "一共", "合计", "总共", "总数"))
    has_total_money = any(term in text for term in ("总价", "总费用", "停车费", "费用", "元"))
    has_unit_price = bool(re.search(r"\u6bcf.{0,4}(?:\u8f86|\u4ef6|\u5f20|\u4e2a|\u4eba).{0,8}\d+(?:\.\d+)?\s*\u5143", text)) or any(
        term in text for term in ("单价", "每辆", "每件", "每张")
    )
    if has_two_types and has_total_count and has_total_money and has_unit_price:
        return _first_term(text, ("停车费", "总价", "总费用", "每辆", "两种", "两类")) or "两类对象总量总价"
    return ""


def _vertical_puzzle_evidence(text: str) -> str:
    direct = _first_term(text, ("竖式问题", "横式问题", "复杂竖式", "数字谜", "算符与数字"))
    if direct:
        return direct
    has_layout = any(term in text for term in ("竖式", "横式", "□", "方框", "空格"))
    has_unknown_digit = any(term in text for term in ("填入", "填数", "填上", "不同数字", "不是", "使算式成立", "算符"))
    if has_layout and has_unknown_digit:
        return _first_term(text, ("竖式", "横式", "□", "方框", "空格")) or "竖式填数"
    return ""


def _digit_puzzle_evidence(text: str) -> str:
    direct = _first_term(text, ("数字谜", "数字问题", "算符与数字"))
    if direct:
        return direct
    if any(term in text for term in ("不同数字", "数位", "个位", "十位", "百位", "数字和")) and any(
        term in text for term in ("填入", "填数", "竖式", "横式", "算式成立")
    ):
        return _first_term(text, ("不同数字", "数位", "个位", "十位", "百位", "数字和")) or "数字填空"
    return ""


def _digit_swap_multiple_evidence(text: str) -> str:
    has_multi_digit = any(term in text for term in ("两位数", "三位数", "四位数", "五位数", "六位数", "多位数"))
    has_swap_or_move = any(term in text for term in ("交换", "调换", "移动", "放到", "删去", "添上"))
    has_multiple_relation = any(term in text for term in ("倍", "倍数", "变成", "等于原数", "是原来的"))
    if has_multi_digit and has_swap_or_move and has_multiple_relation:
        return _first_term(text, ("交换", "调换", "六位数", "倍数", "变成")) or "数位交换成倍数"
    return ""


def _repeated_digit_number_evidence(text: str) -> str:
    if any(term in text for term in ("重复数字", "各位数字相同", "形如", "循环数字")):
        return _first_term(text, ("重复数字", "各位数字相同", "形如", "循环数字")) or "重复数字"
    if re.search(r"(\d)\1{2,}", text) and any(term in text for term in ("数", "倍数", "整除", "乘积", "差")):
        return "重复数字"
    return ""


def _integer_solution_factorization_evidence(text: str) -> str:
    direct = _first_term(text, ("整数解", "正整数解", "约数枚举", "因数分解", "不定方程"))
    if direct:
        return direct
    if any(term in text for term in ("整数", "自然数")) and any(term in text for term in ("乘积", "积为", "约数", "因数", "枚举")):
        return _first_term(text, ("整数", "乘积", "约数", "因数")) or "整数解约数枚举"
    return ""


def _school_division_evidence(text: str) -> str:
    term = _first_term(
        text,
        (
            "除法",
            "除数",
            "被除数",
            "商",
            "余数",
            "平均分",
            "÷",
        ),
    )
    if term:
        return term
    match = re.search(r"\d+\s*(?:÷|/)\s*\d+", text)
    return match.group(0) if match else ""


def _graph_relation_network_counting_evidence(text: str) -> str:
    if any(term in text for term in ("握手", "每两人", "下一局", "下棋", "循环赛", "已下局数")) and any(
        term in text for term in ("多少", "几局", "几次", "人数", "男生")
    ):
        return _first_term(text, ("握手", "每两人", "下一局", "下棋", "循环赛", "已下局数")) or "握手比赛轮次"
    has_nodes = any(term in text for term in ("每个点表示", "点表示", "每个点", "点"))
    has_edges = any(term in text for term in ("连一条边", "直接就连一条边", "边"))
    has_relation = any(term in text for term in ("互相认识", "认识的同学", "同学认识的同学"))
    has_count_goal = any(term in text for term in ("邀请", "共邀请", "参加", "多少个同学"))
    if has_nodes and has_edges and has_relation and has_count_goal:
        return _first_term(text, ("互相认识", "连一条边", "邀请", "同学认识的同学")) or "关系网络计数"
    return ""


def _pigeonhole_evidence(text: str) -> str:
    direct = _first_term(text, ("抽屉", "抽屉原理", "最不利", "构造抽屉"))
    if direct:
        return direct
    patterns = (
        r"(?:至少|最少).{0,16}(?:保证|一定|必有|有).{0,20}(?:相同|同一|同色|同类|同天|同月|同年|完全相同)",
        r"(?:相同|同一|同色|同类|同天|同月|同年|完全相同).{0,16}(?:至少|最少).{0,8}(?:有|几|多少)",
        r"(?:至少|最少).{0,12}(?:取|摸|抽|选).{0,24}(?:保证|一定|必有).{0,20}(?:相同|同一|同色|同类)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return ""


def _guarantee_at_least_evidence(text: str) -> str:
    direct = _first_term(text, ("最不利原则", "最不利"))
    if direct:
        return direct
    patterns = (
        r"(?:至少|最少).{0,16}(?:保证|一定|必有|有|几|多少)",
        r"(?:保证|一定|必有).{0,16}(?:至少|最少)",
        r"(?:相同|同一|同色|同类|完全相同).{0,16}(?:至少|最少)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return ""


def _transport_optimization_evidence(text: str) -> str:
    has_transport = any(term in text for term in ("运输", "运货", "货物", "车辆", "卡车", "车"))
    has_cost_or_time = any(term in text for term in ("费用", "运费", "成本", "时间", "最短", "最少", "最小", "最优"))
    has_arrangement = any(term in text for term in ("安排", "方案", "怎样", "如何", "使", "最"))
    if has_transport and has_cost_or_time and has_arrangement:
        return _first_term(text, ("运输", "运费", "费用", "最小", "最优", "安排")) or "运输费用最优"
    return ""


def _winning_strategy_evidence(text: str) -> str:
    direct = _first_term(text, ("获胜", "必胜", "必败", "制胜策略", "博弈策略"))
    if direct:
        return direct
    if any(term in text for term in ("玩家", "先手", "后手", "轮流", "棋子", "游戏")) and any(
        term in text for term in ("输", "赢", "胜", "策略")
    ):
        return _first_term(text, ("输", "赢", "胜", "策略")) or "博弈策略"
    return ""


def _has_multiplicative_sum(text: str) -> bool:
    return bool(re.search(r"(?:[+]|(?<!\d)-).*(?:[*×÷/]|脳)|(?:[*×÷/]|脳).*(?:[+]|(?<!\d)-)", text))


def _has_equivalent_factor(text: str) -> bool:
    if _first_term(text, ("提取公因数", "乘法分配律", "小数缩放")):
        return True
    numbers = [item.replace(".", "").lstrip("0") for item in re.findall(r"\d+(?:\.\d+)?", text)]
    numbers = [item for item in numbers if len(item) >= 2]
    for idx, left in enumerate(numbers):
        for right in numbers[idx + 1 :]:
            if left == right or left in right or right in left:
                return True
    return False


def _expression_excerpt(text: str) -> str:
    match = re.search(r"[\d\.\s+\-*/×÷脳()（）]{6,}", text)
    return (match.group(0) if match else text[:80]).strip()


def _alias_hits(text: str, aliases: Iterable[str]) -> List[str]:
    return _unique(
        alias
        for alias in aliases
        if alias and alias not in GENERIC_ALIAS_TERMS and alias in text
    )


def _unique(items: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _build_dim5_fact_profile(facts: Sequence[Dict[str, str]], *, question_text: str = "") -> Dict[str, Any]:
    structures = _unique(str(fact.get("fact_key") or "") for fact in facts if isinstance(fact, dict))
    objects = _unique(str(fact.get("evidence") or "") for fact in facts if fact.get("fact_type") in {"geometry", "school_geometry", "school_statistics"})
    methods = _unique(str(fact.get("fact_key") or "") for fact in facts if str(fact.get("fact_type") or "").endswith("_structure") or fact.get("fact_type") in {"quantity_relation", "process_change"})
    evidence = [
        {
            "fact_key": str(fact.get("fact_key") or ""),
            "text": str(fact.get("evidence") or ""),
            "source": str(fact.get("source") or "question_text"),
        }
        for fact in facts
        if isinstance(fact, dict) and str(fact.get("fact_key") or "")
    ]
    visual_dependency = "required" if any(term in str(question_text or "") for term in ("如图", "图中", "阴影", "统计图")) else "helpful"
    warnings: List[str] = []
    if not structures:
        warnings.append("未抽取到稳定的维度5结构事实。")
    if visual_dependency == "required" and not any(item.get("source") == "image" for item in evidence):
        warnings.append("题目可能依赖图形，当前结构事实主要来自题干文本。")
    return {
        "structures": structures,
        "objects": objects[:12],
        "methods": methods[:12],
        "evidence": evidence,
        "visual_dependency": visual_dependency,
        "warnings": warnings,
        "extraction_source": "rule_fallback",
        "need_manual_review": 1,
    }


def _load_dim5_fact_profile_json(response: Any) -> Dict[str, Any]:
    if isinstance(response, dict):
        return response
    text = str(response or "").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("dim5_fact_profile_response_not_object")
    return payload


def _normalize_dim5_fact_profile(
    payload: Any,
    *,
    question_text: str = "",
    extraction_source: str = "",
) -> Dict[str, Any]:
    raw = payload.get("dim5_fact_profile") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        raw = payload if isinstance(payload, dict) else {}

    raw_structures = _string_list(raw.get("structures"))
    structures = _unique(normalize_dim5_structure_key(key) for key in raw_structures)
    unknown_structures = [
        key for key in raw_structures if key and not normalize_dim5_structure_key(key)
    ]
    objects = _unique(_string_list(raw.get("objects")))[:12]
    methods = _unique(_string_list(raw.get("methods")))[:12]
    evidence = _normalize_dim5_profile_evidence(raw.get("evidence"), structures)
    visual_dependency = str(raw.get("visual_dependency") or "").strip().lower()
    if visual_dependency not in {"none", "helpful", "required"}:
        visual_dependency = "required" if any(term in str(question_text or "") for term in ("如图", "图中", "阴影", "统计图")) else "helpful"
    warnings = _unique(_string_list(raw.get("warnings")))
    if unknown_structures:
        warnings.append("dim5_unknown_structure_keys:" + ",".join(unknown_structures[:8]))
    if not structures:
        warnings.append("dim5_fact_profile_empty_structures")
    missing_evidence = [
        key for key in structures if not any(item.get("fact_key") == key and item.get("text") for item in evidence)
    ]
    if missing_evidence:
        warnings.append("dim5_fact_profile_missing_traceable_evidence:" + ",".join(missing_evidence[:8]))
    return {
        "structures": structures,
        "objects": objects,
        "methods": methods,
        "evidence": evidence,
        "visual_dependency": visual_dependency,
        "warnings": warnings,
        "extraction_source": str(extraction_source or raw.get("extraction_source") or "").strip()
        or "llm_dim5_fact_profile",
        "need_manual_review": 1 if raw.get("need_manual_review") in (1, "1", True) or bool(missing_evidence) else 0,
    }


def _normalize_dim5_profile_evidence(value: Any, structures: Sequence[str]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                fact_key = str(
                    item.get("fact_key")
                    or item.get("structure")
                    or item.get("key")
                    or ""
                ).strip()
                fact_key = normalize_dim5_structure_key(fact_key)
                text = str(item.get("text") or item.get("evidence") or "").strip()
                source = str(item.get("source") or "question_text").strip() or "question_text"
            else:
                fact_key = ""
                text = str(item or "").strip()
                source = "question_text"
            if not fact_key and len(structures) == 1:
                fact_key = str(structures[0])
            if fact_key:
                items.append({"fact_key": fact_key, "text": text[:120], "source": source})
    existing = {item["fact_key"] for item in items}
    for key in structures:
        if key not in existing:
            items.append({"fact_key": key, "text": "", "source": "missing"})
    return items


def _facts_from_dim5_fact_profile(profile: Dict[str, Any]) -> List[Dict[str, str]]:
    structures = _string_list(profile.get("structures"))
    evidence_by_key: Dict[str, Dict[str, str]] = {}
    for item in profile.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        fact_key = str(item.get("fact_key") or "").strip()
        if not fact_key:
            continue
        evidence_by_key.setdefault(
            fact_key,
            {
                "evidence": str(item.get("text") or item.get("evidence") or "").strip(),
                "source": str(item.get("source") or "question_text").strip() or "question_text",
            },
        )
    facts: List[Dict[str, str]] = []
    for key in structures:
        evidence = evidence_by_key.get(key, {})
        facts.append(
            {
                "fact_key": key,
                "fact_type": "dim5_structure",
                "evidence": str(evidence.get("evidence") or "").strip(),
                "source": str(evidence.get("source") or "missing").strip(),
            }
        )
    return facts


def _admission_results(candidates: Sequence[Dim5GraphCandidate]) -> List[Dict[str, Any]]:
    has_cross_domain_conflict = _has_cross_domain_candidate_conflict(candidates)
    return [
        _admission_result(
            candidate,
            force_conflict=has_cross_domain_conflict
            and candidate.candidate_status == "confirmed_candidate",
        )
        for candidate in candidates
    ]


def _has_cross_domain_candidate_conflict(
    candidates: Sequence[Dim5GraphCandidate],
    *,
    close_score_threshold: float = 0.08,
) -> bool:
    confirmed = sorted(
        (candidate for candidate in candidates if candidate.candidate_status == "confirmed_candidate"),
        key=lambda candidate: candidate.score,
        reverse=True,
    )
    if len(confirmed) < 2:
        return False
    top = confirmed[0]
    for candidate in confirmed[1:]:
        if candidate.node.domain == top.node.domain:
            continue
        if top.score - candidate.score < close_score_threshold:
            return True
        return False
    return False


def _admission_result(candidate: Dim5GraphCandidate, *, force_conflict: bool = False) -> Dict[str, Any]:
    status_map = {
        "confirmed_candidate": "passed",
        "blocked_candidate": "blocked",
        "weak_candidate": "weak",
    }
    status = status_map.get(candidate.candidate_status, "weak")
    if force_conflict:
        status = "conflict"
    blocked_reasons = [
        f"命中排除结构：{key}" for key in candidate.blocked_by_fact_keys
    ]
    if candidate.missing_required_fact_groups:
        blocked_reasons.extend(
            "缺少必要结构：" + "/".join(group)
            for group in candidate.missing_required_fact_groups[:4]
        )
    if candidate.missing_evidence_fact_keys:
        blocked_reasons.append(
            "结构证据无法回溯：" + "、".join(candidate.missing_evidence_fact_keys[:6])
        )
    if candidate.candidate_status == "weak_candidate" and candidate.matched_aliases and not candidate.matched_fact_keys:
        blocked_reasons.append("只有别名或弱关键词命中，缺少结构事实。")
    if force_conflict:
        blocked_reasons.append("cross_domain_candidate_conflict")
    risk_flags = _admission_risk_flags(candidate)
    if force_conflict:
        risk_flags.append("cross_domain_candidate_conflict")
    return {
        "knowledge_point_id": candidate.node.knowledge_point_id,
        "knowledge_point_name": candidate.node.name,
        "admission_status": status,
        "passed_reasons": [
            f"满足结构：{key}" for key in candidate.matched_fact_keys
        ][:8],
        "blocked_reasons": blocked_reasons,
        "risk_flags": risk_flags,
    }


def _admission_risk_flags(candidate: Dim5GraphCandidate) -> List[str]:
    flags: List[str] = []
    if candidate.blocked_by_fact_keys:
        flags.append("blocked_by_exclude_structure")
    if candidate.missing_required_fact_groups:
        flags.append("missing_required_structure")
    if candidate.missing_evidence_fact_keys:
        flags.append("missing_traceable_evidence")
    if candidate.matched_aliases and not candidate.matched_fact_keys:
        flags.append("alias_only_match")
    if _only_generic_confirmation_signal(candidate.matched_fact_keys, candidate.matched_aliases):
        flags.append("generic_signal_only")
    return flags


def _rejected_candidate_dict(
    candidate: Dim5GraphCandidate,
    selected: Dim5GraphCandidate | None,
) -> Dict[str, Any]:
    payload = candidate.as_dict()
    reasons: List[str] = []
    if candidate.blocked_by_fact_keys:
        reasons.append("命中排除结构：" + "、".join(candidate.blocked_by_fact_keys))
    if candidate.missing_required_fact_groups:
        reasons.append(
            "缺少必要结构："
            + "；".join("/".join(group) for group in candidate.missing_required_fact_groups[:3])
        )
    if candidate.missing_evidence_fact_keys:
        reasons.append("结构证据无法回溯：" + "、".join(candidate.missing_evidence_fact_keys[:6]))
    if selected and candidate.candidate_status == "confirmed_candidate":
        reasons.append(f"证据弱于最终候选：{selected.node.name}")
    if not reasons:
        reasons.append("未通过最终裁决排序。")
    payload["reason"] = "；".join(reasons)
    return payload


def _more_specific_candidate(
    left: Dim5GraphCandidate,
    right: Dim5GraphCandidate,
) -> Dim5GraphCandidate:
    left_specificity = len(left.node.required_structures) + len(left.matched_fact_keys) + len(left.matched_supporting_fact_keys)
    right_specificity = len(right.node.required_structures) + len(right.matched_fact_keys) + len(right.matched_supporting_fact_keys)
    if left_specificity != right_specificity:
        return left if left_specificity > right_specificity else right
    return left if left.score >= right.score else right


def _is_curated_school_topic_id(value: str) -> bool:
    text = str(value or "")
    if not text.startswith("dim5.school."):
        return False
    return not re.match(r"^dim5\.school\.\d\.[0-9a-f]{12}$", text)


def _is_generated_gaosi_topic_id(value: str) -> bool:
    return str(value or "").startswith(GAOSI_NODE_ID_PREFIX)


def _has_strong_olympiad_signal(fact_keys: Iterable[str]) -> bool:
    return any(str(key or "") in STRONG_OLYMPIAD_FACT_KEYS for key in fact_keys)


def _only_generic_confirmation_signal(fact_keys: Iterable[str], aliases: Iterable[str]) -> bool:
    specific_fact = any(str(key or "") not in GENERIC_CONFIRMATION_FACT_KEYS for key in fact_keys)
    specific_alias = any(str(alias or "").strip() not in GENERIC_ALIAS_TERMS for alias in aliases)
    return not specific_fact and not specific_alias


def _implicit_blocked_fact_keys(node: Dim5GraphNode, fact_keys: set[str]) -> List[str]:
    blocked: List[str] = []
    node_name = node.name
    required_keys = {key for group in node.required_structures for key in group}
    generic_operation_keys = {
        "calculation_numeric_expression",
        "decimal_fraction_calculation",
        "school_addition_subtraction",
        "school_multiplication",
        "school_division",
        "school_mixed_operation",
        "school_fraction",
    }
    specific_operation_blockers: List[str] = []
    if "defined_operation_rule" in fact_keys and "defined_operation_rule" not in required_keys:
        specific_operation_blockers.append("defined_operation_rule")
    if {"half_recurrence", "reverse_process"} <= fact_keys and not {"half_recurrence", "reverse_process"} & required_keys:
        specific_operation_blockers.append("reverse_process")
    if {"work_rate_task", "work_progress_ratio"} <= fact_keys and not {"work_rate_task", "gaosi_work_rate", "work_progress_ratio"} & required_keys:
        specific_operation_blockers.append("work_rate_task")
    if specific_operation_blockers and required_keys & generic_operation_keys:
        blocked.extend(specific_operation_blockers)
    if "binary_search_strategy" in fact_keys and node.knowledge_track == "school":
        blocked.append("binary_search_strategy")
    if "division_quotient_digit_zero" in fact_keys and node_name in {"最值问题一", "最值问题二", "统筹与对策"}:
        blocked.append("division_quotient_digit_zero")
    if "rectangle_tiling_min_perimeter" in fact_keys and node_name in {"最值问题一", "最值问题二", "统筹与对策"}:
        blocked.append("rectangle_tiling_min_perimeter")
    if "rotation_area_transform" in fact_keys and node.knowledge_track == "school" and node_name in {
        "平移和旋转",
        "平移和旋转的应用",
        "旋转的含义及三要素",
        "图形旋转的特征",
    }:
        blocked.append("rotation_area_transform")
    if "rotation_area_transform" in fact_keys and node_name == "圆与扇形":
        blocked.append("rotation_area_transform")
    if "rotation_area_transform" in fact_keys and node_name in {"几何图形剪拼", "格点与割补"}:
        blocked.append("rotation_area_transform")
    if "condition_enumeration" in fact_keys and node_name in {"工程问题", "工程效率问题"}:
        blocked.append("condition_enumeration")
    if "condition_enumeration" in fact_keys and "integer_split" in fact_keys and node_name in {"枚举法一", "枚举法二"}:
        blocked.append("condition_enumeration")
    if (
        {"triangle_angle_classification", "cylinder_cone_volume_height_ratio", "cylinder_cone_volume_ratio", "composite_area_split_relation"}
        & fact_keys
        and node.knowledge_point_id.startswith(GAOSI_NODE_ID_PREFIX)
        and "比例" in node_name
    ):
        blocked.append("specific_geometry_ratio_structure")
    if "number_table_position_pattern" in fact_keys and node_name == "排列组合":
        blocked.append("number_table_position_pattern")
    if "number_table_position_pattern" in fact_keys and node.domain == "pattern_sequence" and node_name != "数列与数表":
        blocked.append("number_table_position_pattern")
    if "number_table_position_pattern" in fact_keys and node_name in {"找规律", "周期问题", "等差数列"}:
        blocked.append("number_table_position_pattern")
    if "composite_area_split_relation" in fact_keys and node_name in {"三角形面积", "三角形的面积计算公式", "三角形面积计算公式的逆用"}:
        blocked.append("composite_area_split_relation")
    if "rectangle_area_fraction_percent_change" in fact_keys and any(term in node_name for term in ("折扣", "商品", "优惠", "定价")):
        blocked.append("rectangle_area_fraction_percent_change")
    if (
        {"cylinder_cone_volume_height_ratio", "cylinder_cone_volume_ratio"} & fact_keys
        and "cylinder_cone" not in node.knowledge_point_id
        and any(term in node_name for term in ("侧面积", "表面积", "展开", "卷纸", "体积之差", "体积相等"))
    ):
        blocked.append("cylinder_cone_volume_ratio")
    if (
        "cylinder_surface_volume_composite" in fact_keys
        and node.knowledge_track == "olympiad"
        and any(term in node_name for term in ("圆柱", "立体几何"))
    ):
        blocked.append("cylinder_surface_volume_composite")
    if "gaosi_place_value_principle" in fact_keys and node.knowledge_point_id == "dim5.number_theory.digit_divisibility":
        blocked.append("gaosi_place_value_principle")
    if "digit_swap_multiple" in fact_keys and node.knowledge_point_id == "dim5.number_theory.place_value_principle":
        blocked.append("digit_swap_multiple")
    if ("periodic_grid" in fact_keys or "overlap_area" in fact_keys) and node_name == "包含与排除":
        blocked.append("periodic_or_overlap_specific")
    if "line_plane_recurrence" in fact_keys and node_name in {"最值问题一", "统筹与对策", "最值问题二"}:
        blocked.append("line_plane_recurrence")
    if "equilateral_triangle_perimeter_transform" in fact_keys and node_name == "多边形内角和计算":
        blocked.append("equilateral_triangle_perimeter_transform")
    if "swallowtail_area_model" in fact_keys and node_name in {"面积比模型", "基础几何公式应用", "三角形面积"}:
        blocked.append("swallowtail_area_model")
    if "overlap_area" in fact_keys and node_name == "圆与扇形":
        blocked.append("overlap_area")
    if "school_statistics" in fact_keys and (
        node_name == "圆与扇形"
        or (node.knowledge_point_id.startswith(GAOSI_NODE_ID_PREFIX) and "圆与扇形" in node_name)
    ):
        blocked.append("school_statistics")
    if "two_type_cost_total" in fact_keys and node_name in {"整数除法", "除数是一位数的竖式计算", "平均分应用"}:
        blocked.append("two_type_cost_total")
    if "transport_optimization" in fact_keys and node_name in {"排列组合", "统筹与对策"}:
        blocked.append("transport_optimization")
    if "travel_equation_same_distance" in fact_keys and (
        node_name == "行程问题"
        or (node.knowledge_point_id.startswith(GAOSI_NODE_ID_PREFIX) and "行程" in node_name)
    ):
        blocked.append("travel_equation_same_distance")
    if (
        "school_cube_net" in fact_keys
        and node.knowledge_point_id.startswith(GAOSI_NODE_ID_PREFIX)
        and "立体" in node_name
    ):
        blocked.append("school_cube_net")
    if "graph_relation_network_counting" in fact_keys and node_name in {"整数除法", "除数是一位数的竖式计算", "平均分应用"}:
        blocked.append("graph_relation_network_counting")
    return blocked


def _same_knowledge_family(left: Dim5GraphNode, right: Dim5GraphNode) -> bool:
    return _knowledge_family_key(left) == _knowledge_family_key(right)


def _knowledge_family_key(node: Dim5GraphNode) -> tuple[str, str, str, str]:
    return (
        node.knowledge_track,
        node.knowledge_grade,
        node.domain,
        _normalize_family_name(node.name),
    )


def _normalize_family_name(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"(问题)?[一二三四五六七八九十]+$", "", text)
    text = re.sub(r"(综合|计算)[一二三四五六七八九十]+$", r"\1", text)
    text = text.replace("问题", "")
    return text or str(value or "").strip()


def _combined_text(question_text: str, analysis_facts: Dict[str, Any], dim5_feature: Dict[str, Any]) -> str:
    parts: List[str] = [str(question_text or "")]
    for key in ("core_knowledge_points", "core_methods"):
        raw = analysis_facts.get(key)
        if isinstance(raw, list):
            parts.extend(str(item) for item in raw)
    for key in ("knowledge_tags", "core_knowledge_units", "supporting_knowledge_units"):
        raw = dim5_feature.get(key)
        if isinstance(raw, list):
            parts.extend(str(item) for item in raw)
    return " ".join(part for part in parts if str(part).strip())
