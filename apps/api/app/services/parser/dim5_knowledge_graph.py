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

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Dim5GraphNode":
        level = normalize_dim5_knowledge_level(raw.get("level"))
        name = str(raw.get("name") or "").strip()
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
            required_fact_groups=tuple(
                tuple(_string_list(group)) for group in raw.get("required_fact_groups") or []
            ),
            exclude_fact_keys=tuple(_string_list(raw.get("exclude_fact_keys"))),
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
        if not self.source_refs:
            errors.append("missing source_refs")
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
    matched_evidence: List[str] = field(default_factory=list)

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
            "matched_aliases": self.matched_aliases,
            "missing_required_fact_groups": self.missing_required_fact_groups,
            "blocked_by_fact_keys": self.blocked_by_fact_keys,
            "matched_evidence": self.matched_evidence[:6],
            "confusable_with": list(self.node.confusable_with),
            "source_refs": list(self.node.source_refs),
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
        if add_terms("school_translation", "school_geometry", ("平移", "平移后", "火箭升空", "电梯", "升降", "直线运动")):
            pass
        if add_terms("school_rotation", "school_geometry", ("旋转", "旋转后", "荡秋千", "风车", "转动", "钟摆", "车轮", "开关门")):
            pass
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
        rectangle_property = _school_rectangle_property_evidence(text)
        if rectangle_property:
            add("school_rectangle_property", "school_geometry", rectangle_property)
        if "school_perimeter" in facts and add_terms(
            "school_irregular_perimeter",
            "school_geometry",
            ("不规则图形", "平移法", "多边形", "组合图形"),
        ):
            pass
        if add_terms("school_area", "school_geometry", ("面积", "平方厘米", "平方米", "平方分米", "底", "高")):
            pass
        if add_terms("school_volume", "school_geometry", ("体积", "容积", "立方厘米", "立方米", "长方体", "正方体", "圆柱", "圆锥")):
            pass
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
        if add_terms("work_efficiency_relation", "quantity_relation", ("效率", "单独", "合作", "共同完成", "每天完成", "轮流")):
            pass

        growth = add_terms("resource_growth", "process_change", ("生长", "增长", "增加", "流入", "新增", "排队", "长草", "每天都长"))
        consumption = add_terms("resource_consumption", "process_change", ("吃", "消耗", "流出", "抽干", "吃完", "检票"))
        if (growth and consumption) or add_terms("growth_consumption", "application_structure", ("牛吃草", "原有草量")):
            add("growth_consumption", "application_structure", _first_term(text, ("牛吃草", "原有", "增长", "生长", "消耗", "检票")) or text[:40])
        if "growth_consumption" in facts and any(term in text for term in ("牛", "草", "原有草量", "长草")):
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
        if add_terms("whole_part_relation", "quantity_relation", ("总量", "总数", "之和", "其余", "整体", "全部")):
            pass

        if add_terms("sequence_pattern", "pattern_sequence", ("周期", "循环", "规律", "数列", "数表", "按规律", "星期", "日历", "休息日")):
            pass
        if add_terms("period_position", "pattern_sequence", ("第n", "第 n", "第几", "位置", "余数")):
            pass
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

        if add_terms("half_recurrence", "process_change", ("一半", "半", "失去", "减少为原来的")):
            pass
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
        if add_terms("gaosi_counting_principle", "olympiad_counting", ("加法原理", "乘法原理", "分类", "分步")):
            pass
        if "school_square_tiling_perimeter" not in facts and add_terms("gaosi_permutation_combination", "olympiad_counting", ("排列", "组合", "安排", "排队")):
            pass
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
        if add_terms("gaosi_grazing_clock", "olympiad_application", ("牛吃草", "钟表", "时针", "分针", "长草")):
            pass
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
        if add_terms("area_relation_model", "geometry_structure", ("面积比", "等高", "共边", "蝴蝶模型", "燕尾模型", "割补", "沙漏")):
            pass
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

        if add_terms("gaosi_sequence", "olympiad_pattern", ("周期", "规律", "数列", "数表", "等差", "找规律")):
            pass
        if add_terms("gaosi_interval_array", "olympiad_pattern", ("间隔", "阵列", "植树", "队列")):
            pass
        if add_terms("gaosi_magic_square", "olympiad_pattern", ("幻方", "数阵", "数阵图")):
            pass
        if add_terms("gaosi_logic", "olympiad_logic", ("逻辑", "推理", "真假", "真话", "假话", "条件", "名次", "排名", "一笔画", "火柴棒", "过河", "天平称重", "皇后", "棋盘控制", "握手", "下棋", "循环赛", "空瓶换水", "移动火柴棒")):
            pass
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
        facts = self.extractor.extract(question_text, question_type=question_type)
        fact_by_key = {str(fact.get("fact_key") or ""): fact for fact in facts}
        fact_keys = {key for key in fact_by_key if key}
        combined_text = _combined_text(question_text, analysis_facts or {}, dim5_feature or {})

        candidates = [
            candidate
            for candidate in (
                self._match_node(node, fact_keys=fact_keys, fact_by_key=fact_by_key, text=combined_text)
                for node in self.graph.approved_nodes
            )
            if candidate is not None
        ]
        candidates.sort(
            key=lambda item: (
                item.candidate_status == "confirmed_candidate",
                item.score,
                _is_generated_gaosi_topic_id(item.node.knowledge_point_id),
                len(item.node.required_fact_groups),
                bool(item.matched_aliases),
            ),
            reverse=True,
        )
        candidates = candidates[: max(max_candidates, 0)]
        confirmed = [item for item in candidates if item.candidate_status == "confirmed_candidate"]
        selected: Dim5GraphCandidate | None = None
        confidence_status = "review_required"
        failure_reason = "no_confirmed_candidate"

        if confirmed:
            confirmed.sort(
                key=lambda item: (
                    item.score,
                    _is_generated_gaosi_topic_id(item.node.knowledge_point_id),
                    len(item.node.required_fact_groups),
                    bool(item.matched_aliases),
                ),
                reverse=True,
            )
            score_gap = confirmed[0].score - confirmed[1].score if len(confirmed) > 1 else 1.0
            same_family = len(confirmed) > 1 and _same_knowledge_family(confirmed[0].node, confirmed[1].node)
            if len(confirmed) == 1 or score_gap >= 0.03 or same_family or (score_gap > 0 and confirmed[0].matched_aliases):
                selected = confirmed[0]
                confidence_status = "confirmed"
                failure_reason = ""
            else:
                confidence_status = "ambiguous"
                failure_reason = "ambiguous_confirmed_candidates"
        elif any(item.candidate_status == "weak_candidate" for item in candidates):
            confidence_status = "broad_category_only"
            failure_reason = "weak_structure_evidence_only"

        candidate_dicts = [candidate.as_dict() for candidate in candidates]
        rejected = [
            candidate.as_dict()
            for candidate in candidates
            if not selected or candidate.node.knowledge_point_id != selected.node.knowledge_point_id
        ]
        result: Dict[str, Any] = {
            "version": "dim5_graph_matcher_v1",
            "graph_version": self.graph.version,
            "dim5_structure_facts": facts,
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
        for group in node.required_fact_groups:
            matched = [key for key in group if key in fact_keys]
            if matched:
                matched_groups.append(group)
                matched_fact_keys.extend(matched)
            else:
                missing_groups.append(list(group))

        matched_aliases = _alias_hits(text, (node.name, *node.aliases))
        blocked_by = [key for key in node.exclude_fact_keys if key in fact_keys]
        blocked_by.extend(_implicit_blocked_fact_keys(node, fact_keys))
        blocked_by = _unique(blocked_by)
        has_positive_signal = bool(matched_groups or matched_aliases)
        if not has_positive_signal:
            return None

        matched_fact_keys = _unique(matched_fact_keys)
        matched_evidence = _unique(
            str(fact_by_key.get(key, {}).get("evidence") or key)
            for key in matched_fact_keys
        )
        group_ratio = len(matched_groups) / max(len(node.required_fact_groups), 1)
        alias_bonus = min(len(matched_aliases) * 0.06, 0.18)
        alias_specificity_bonus = min(sum(len(alias) for alias in matched_aliases) * 0.004, 0.08)
        specificity_bonus = min(len(node.required_fact_groups) * 0.015, 0.08)
        structural_exact_bonus = (
            0.14
            if "school_square_tiling_perimeter" in matched_fact_keys
            and any("school_square_tiling_perimeter" in group for group in node.required_fact_groups)
            else 0.0
        )
        curated_school_topic_bonus = 0.04 if _is_curated_school_topic_id(node.knowledge_point_id) else 0.0
        generated_gaosi_bonus = (
            0.14
            if _is_generated_gaosi_topic_id(node.knowledge_point_id)
            and _has_strong_olympiad_signal(matched_fact_keys)
            else 0.04
            if _is_generated_gaosi_topic_id(node.knowledge_point_id) and matched_aliases
            else 0.0
        )
        gaosi_signal_bonus = 0.08 if generated_gaosi_bonus and _has_strong_olympiad_signal(matched_fact_keys) else 0.0
        school_gaosi_penalty = -0.16 if node.knowledge_track == "school" and _has_strong_olympiad_signal(fact_keys) else 0.0
        score = max(
            0.0,
            group_ratio
            + alias_bonus
            + alias_specificity_bonus
            + specificity_bonus
            + structural_exact_bonus
            + curated_school_topic_bonus
            + generated_gaosi_bonus
            + gaosi_signal_bonus
            + school_gaosi_penalty,
        )

        if blocked_by:
            status = "blocked_candidate"
            score = min(score, 0.48)
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
            matched_evidence=matched_evidence,
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


def _fraction_application_evidence(text: str) -> str:
    if not any(term in text for term in ("分数", "几分之", "通分", "约分")) and not re.search(r"\d+\s*/\s*\d+", text):
        return ""
    if any(term in text for term in ("总数", "总量", "一共", "还剩", "剩下", "分给", "人数", "已知", "求")):
        return _first_term(text, ("几分之", "分数", "还剩", "总数", "总量")) or "分数应用题"
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
    if "周长" not in text:
        return ""
    if not any(term in text for term in ("小正方形", "正方形")):
        return ""
    if not any(term in text for term in ("拼成", "拼接", "共边", "周长最小", "周长最大", "周长最少")):
        return ""
    return _first_term(text, ("周长最小", "周长最大", "小正方形", "拼成", "共边")) or "正方形拼图周长"


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
    return _first_term(
        text,
        (
            "工程",
            "单独",
            "合作",
            "合做",
            "共同完成",
            "工作效率",
            "总工程量",
            "剩余工程",
        ),
    )


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
