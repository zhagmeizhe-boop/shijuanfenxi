"""Knowledge-library grounded candidate selection for dimension 5.

This module deliberately stays outside the main six-dimension prompt.  It
builds a small candidate set from the original question text first, uses local
structure slots as strong evidence, and only uses neutral analysis facts as a
downweighted supplement.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence

from app.services.parser.reference_standard import GAOSI_QUESTION_SOURCE, ReferenceEntry
from app.services.scoring.dim5_canonical import classify_dim5_knowledge_scope


DIM5_GROUNDING_VERSION = "dim5_grounding_v1"
GROUNDING_USE_CONFIDENCE_THRESHOLD = 0.55
GROUNDING_HIGH_CONFIDENCE_THRESHOLD = 0.70


def _clean_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = text.replace("×", "*").replace("÷", "/").replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", "", text)


def _readable_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _unique(items: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        text = _readable_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _contains_any(text: str, terms: Sequence[str]) -> List[str]:
    normalized = _clean_text(text)
    hits: List[str] = []
    for term in terms:
        clean = _clean_text(term)
        if clean and clean in normalized:
            hits.append(term)
    return _unique(hits)


def _has_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _evidence_core(text: str) -> str:
    clean = _clean_text(text)
    return re.sub(r"[\s()\[\]{}（）【】《》,，.。:：;；、_+\-*/=<>%!?？！]", "", clean)


def _is_weak_evidence_term(term: Any) -> bool:
    clean = _clean_text(term)
    if not clean:
        return True
    core = _evidence_core(clean)
    if not core:
        return True
    generic_terms = {_clean_text(item) for item in GENERIC_WEAK_EVIDENCE_TERMS}
    if core in generic_terms:
        return True
    if len(core) <= 1 and not _has_chinese(core):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?", core):
        return True
    if re.fullmatch(r"\d+/\d+", clean) or re.fullmatch(r"\d+(?:\.\d+)?/\d+(?:\.\d+)?", clean):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?%?", clean):
        return True
    if re.fullmatch(r"[a-d][.、)]?", clean):
        return True
    if re.fullmatch(r"[a-z]{1,4}\d?", core):
        return True
    if not _has_chinese(core) and re.fullmatch(r"[a-z0-9]+", core):
        return True
    if re.search(r"\d", core) and _has_chinese(core):
        if not any(_clean_text(item) in core for item in SEMANTIC_SHORT_EVIDENCE_TERMS):
            return True
    if _has_chinese(core) and len(core) <= 3:
        if not any(
            _clean_text(item) in core or core in _clean_text(item)
            for item in SEMANTIC_SHORT_EVIDENCE_TERMS
        ):
            return True
    if not _has_chinese(core) and len(core) <= 4:
        return True
    return False


def _match_terms_by_quality(text: str, terms: Sequence[str]) -> tuple[List[str], List[str]]:
    normalized = _clean_text(text)
    strong_hits: List[str] = []
    weak_hits: List[str] = []
    for term in terms:
        clean = _clean_text(term)
        if not clean or clean not in normalized:
            continue
        if _is_weak_evidence_term(term):
            weak_hits.append(term)
        else:
            strong_hits.append(term)
    return _unique(strong_hits), _unique(weak_hits)


def _level_rank(level: str) -> int:
    text = str(level or "").strip().upper()
    return int(text[1]) if len(text) == 2 and text.startswith("L") and text[1].isdigit() else 0


def _parse_grade(*values: Any) -> str:
    chinese = {
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
    for value in values:
        text = str(value or "")
        digit = re.search(r"[1-9]", text)
        if digit:
            return digit.group(0)
        for char, grade in chinese.items():
            if char in text:
                return grade
    return ""


def _grade_label(grade: str) -> str:
    labels = {
        "1": "一年级",
        "2": "二年级",
        "3": "三年级",
        "4": "四年级",
        "5": "五年级",
        "6": "六年级",
        "7": "七年级",
    }
    return labels.get(str(grade or "").strip(), "")


def _source_family(source: str) -> str:
    source = str(source or "").strip()
    if source in {"school", "school_pdf"}:
        return "school"
    if source in {"guide", "gaosi_pdf", GAOSI_QUESTION_SOURCE}:
        return "gaosi"
    if source in {"classic", "competition"}:
        return "olympiad"
    if source == "local_structure_rules":
        return "local_rules"
    return source or "unknown"


def _source_label(
    *,
    source_family: str,
    grade: str = "",
    chapter_title: str = "",
    source_label: str = "",
    has_strong_source_evidence: bool = False,
) -> str:
    if source_label:
        return source_label
    grade_text = _grade_label(grade)
    if source_family == "school":
        if has_strong_source_evidence and grade_text:
            return f"{grade_text}校内"
        return "校内知识"
    if source_family == "gaosi":
        if has_strong_source_evidence and grade_text:
            return f"{grade_text}奥数"
        return "奥数知识"
    if source_family == "local_rules":
        return chapter_title or ""
    return ""


def _entry_terms(entry: ReferenceEntry) -> List[str]:
    values: List[Any] = [
        entry.title,
        entry.lecture_title,
        entry.topic_category,
        entry.category,
        entry.track,
        entry.note,
    ]
    values.extend(entry.keywords)
    profile = entry.dimension_profiles.get("dim5", {}) if isinstance(entry.dimension_profiles, dict) else {}
    if isinstance(profile, dict):
        for key in ("knowledge_anchor_terms", "core_knowledge_units", "knowledge_tags"):
            raw = profile.get(key, [])
            if isinstance(raw, list):
                values.extend(raw)
    terms = []
    for value in values:
        text = _readable_text(value)
        if len(_clean_text(text)) >= 2:
            terms.append(text)
    return _unique(terms)


def _is_formula_like(question_text: str) -> bool:
    text = _clean_text(question_text)
    if not re.search(r"\d", text):
        return False
    if not re.search(r"[+\-*/=]", text):
        return False
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    return len(chinese_chars) <= 8 or len(chinese_chars) <= max(12, len(text) // 5)


def _has_fraction(text: str) -> bool:
    normalized = _clean_text(text)
    return bool(re.search(r"\d+/\d+", normalized)) or "分数" in normalized


def _has_decimal(text: str) -> bool:
    return bool(re.search(r"\d+\.\d+", _clean_text(text))) or "小数" in _clean_text(text)


def _has_common_factor_pattern(text: str) -> bool:
    normalized = _clean_text(text)
    if "*" not in normalized or not any(op in normalized for op in ("+", "-")):
        return False
    number_tokens = re.findall(r"\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?", normalized)
    repeated_numbers = {
        token
        for token in number_tokens
        if len(token) >= 2 and number_tokens.count(token) >= 2
    }
    if repeated_numbers:
        return True
    decimal_families: Dict[str, int] = {}
    for token in number_tokens:
        compact = token.replace(".", "").lstrip("0")
        if len(compact) >= 2:
            decimal_families[compact] = decimal_families.get(compact, 0) + 1
    return any(count >= 2 for count in decimal_families.values())


NUMBER_THEORY_TERMS = (
    "因数",
    "倍数",
    "质数",
    "合数",
    "质因数",
    "最大公因数",
    "最小公倍数",
    "公因数",
    "公倍数",
    "整除",
    "余数",
    "约数",
    "奇数",
    "偶数",
    "同余",
)


PATTERN_SEQUENCE_TERMS = (
    "规律",
    "周期",
    "循环",
    "数列",
    "第n项",
    "第n",
    "第几项",
    "第几",
    "相邻项",
    "递推",
    "重复节",
)

WORK_RATE_TERMS = (
    "工程",
    "工作量",
    "效率",
    "合作",
    "单独",
    "共同完成",
    "完成",
    "中途",
)

PROFIT_DISCOUNT_TERMS = (
    "利润",
    "获利",
    "盈利",
    "亏损",
    "折扣",
    "打折",
    "进价",
    "售价",
    "销售价",
    "标价",
    "成本",
    "加价",
)

GEOMETRY_AREA_TERMS = (
    "如图",
    "图形",
    "三角形",
    "△",
    "四边形",
    "面积",
    "中点",
    "中位线",
    "翻折",
    "折叠",
    "对称",
    "连接",
    "边",
)

HALF_RECURRENCE_TERMS = (
    "失去其质量的一半",
    "失去一半",
    "一半",
    "每小时",
    "八小时后",
    "倒推",
    "逆推",
    "递推",
    "指数变化",
    "倍半",
)

TELESCOPING_SUM_TERMS = (
    "裂项",
    "裂项相消",
    "分数裂项",
    "求和",
    "数列求和",
    "...",
    "…",
)

SOLID_VIEW_TERMS = (
    "三视图",
    "视图",
    "左视图",
    "前视图",
    "从左面观察",
    "从前面",
    "从左面",
    "看到的图形",
    "透明正方体",
    "正方体",
    "立体图形",
    "投影",
    "棱",
    "顶点",
)

DIGIT_DIVISIBILITY_TERMS = (
    "四位数",
    "数位",
    "各个数位",
    "数字之和",
    "数位和",
    "删去",
    "被删去",
    "非零数字",
    "9的倍数",
    "整除性质",
)

PIGEONHOLE_TERMS = (
    "抽屉",
    "抽屉原理",
    "最不利",
    "至少有",
    "完全相同",
    "品种完全相同",
    "每人可选",
    "每种",
    "最多只能",
    "整数拆分",
    "组合枚举",
)

GAME_STRATEGY_TERMS = (
    "博弈",
    "棋子",
    "玩家",
    "获胜",
    "制胜策略",
    "必胜",
    "无法移动",
    "输掉游戏",
    "移动棋子",
    "不能跳过",
    "对称策略",
    "状态镜像",
)

RATIO_WHOLE_TERMS = (
    "销售量",
    "之和的比",
    "销售总量",
    "整体与部分",
    "整体",
    "部分",
    "总量",
    "比例转化",
    "方程思想",
)

SPATIAL_EXTREMUM_TERMS = (
    "透明积木",
    "绿色积木",
    "不透明",
    "从前面",
    "从左面",
    "最少",
    "最多",
    "极值",
    "空间极值",
    "27个",
)

GENERIC_WEAK_EVIDENCE_TERMS = (
    "问题",
    "应用题",
    "基础",
    "综合",
    "一般",
    "常规",
    "根据",
    "数学",
    "知识",
    "模型",
    "方法",
    "关系",
    "数量关系",
    "等量关系",
    "方程",
    "列方程",
    "解方程",
    "计算",
    "分析",
    "题目",
    "如图",
    "图形",
    "连接",
    "边",
    "每小时",
    "最后",
    "剩下",
    "正好",
    "选择",
    "选",
    "分类",
)

SEMANTIC_SHORT_EVIDENCE_TERMS = (
    *NUMBER_THEORY_TERMS,
    *PATTERN_SEQUENCE_TERMS,
    *WORK_RATE_TERMS,
    *PROFIT_DISCOUNT_TERMS,
    *GEOMETRY_AREA_TERMS,
    *HALF_RECURRENCE_TERMS,
    *TELESCOPING_SUM_TERMS,
    *SOLID_VIEW_TERMS,
    *DIGIT_DIVISIBILITY_TERMS,
    *PIGEONHOLE_TERMS,
    *GAME_STRATEGY_TERMS,
    *RATIO_WHOLE_TERMS,
    *SPATIAL_EXTREMUM_TERMS,
    "百分数",
    "百分比",
    "比例",
    "浓度",
    "行程",
    "速度",
    "路程",
    "时间",
    "相遇",
    "追及",
    "溶液",
    "盐水",
    "还原",
    "盈亏",
    "鸡兔同笼",
    "组合",
    "排列",
    "计数",
    "容斥",
    "简便计算",
    "乘法分配律",
    "小数",
    "分数",
    "混合运算",
    "运算律",
)


@dataclass(frozen=True)
class KnowledgeCard:
    candidate_id: str
    knowledge_point: str
    domain: str
    source_family: str
    source: str
    chapter_title: str
    keywords: tuple[str, ...]
    recommended_level: str
    source_label: str = ""
    necessary_structures: tuple[str, ...] = ()
    excluded_contexts: tuple[str, ...] = ()
    confusing_with: tuple[str, ...] = ()


@dataclass
class GroundingCandidate:
    candidate_id: str
    canonical_knowledge_point: str
    knowledge_domain: str
    source: str
    source_family: str
    source_label: str
    grade_hint: str
    chapter_title: str
    matched_terms: List[str] = field(default_factory=list)
    matched_evidence: List[str] = field(default_factory=list)
    match_sources: set[str] = field(default_factory=set)
    recommended_level: str = "L2"
    score: float = 0.0
    risk_flags: List[str] = field(default_factory=list)
    necessary_structures: List[str] = field(default_factory=list)
    excluded_contexts: List[str] = field(default_factory=list)
    confusing_with: List[str] = field(default_factory=list)

    def merge(self, other: "GroundingCandidate") -> None:
        self.matched_terms = _unique([*self.matched_terms, *other.matched_terms])
        self.matched_evidence = _unique([*self.matched_evidence, *other.matched_evidence])
        self.match_sources.update(other.match_sources)
        self.score += other.score
        self.risk_flags = _unique([*self.risk_flags, *other.risk_flags])
        self.necessary_structures = _unique([*self.necessary_structures, *other.necessary_structures])
        self.excluded_contexts = _unique([*self.excluded_contexts, *other.excluded_contexts])
        self.confusing_with = _unique([*self.confusing_with, *other.confusing_with])
        if _level_rank(other.recommended_level) > _level_rank(self.recommended_level):
            self.recommended_level = other.recommended_level
        if not self.source_label and other.source_label:
            self.source_label = other.source_label

    @property
    def match_source(self) -> str:
        primary_sources = self.match_sources & {"question_text", "structure"}
        if primary_sources and "analysis_facts" in self.match_sources:
            return "both"
        if primary_sources == {"question_text", "structure"}:
            return "question_text+structure"
        if "structure" in primary_sources:
            return "structure"
        if "question_text" in primary_sources:
            return "question_text"
        if "analysis_facts" in self.match_sources:
            return "analysis_facts_only"
        return "unknown"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "canonical_knowledge_point": self.canonical_knowledge_point,
            "knowledge_domain": self.knowledge_domain,
            "source": self.source,
            "source_family": self.source_family,
            "source_label": self.source_label,
            "grade_hint": self.grade_hint,
            "chapter_title": self.chapter_title,
            "matched_terms": self.matched_terms,
            "matched_evidence": self.matched_evidence,
            "match_source": self.match_source,
            "recommended_level": self.recommended_level,
            "score": round(float(self.score), 3),
            "risk_flags": self.risk_flags,
            "necessary_structures": self.necessary_structures,
            "excluded_contexts": self.excluded_contexts,
            "confusing_with": self.confusing_with,
        }


LOCAL_KNOWLEDGE_CARDS: tuple[KnowledgeCard, ...] = (
    KnowledgeCard(
        candidate_id="local:calculation:distributive_law",
        knowledge_point="乘法分配律与简便计算",
        domain="number_operation",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="校内数与运算",
        keywords=("乘法分配律", "简便计算", "提取公因数", "凑整", "小数缩放", "运算律"),
        recommended_level="L2",
        source_label="校内数与运算",
        necessary_structures=("乘除与加减混合", "共同因数或小数缩放"),
        excluded_contexts=("整数整除约束", "质数合数判定"),
        confusing_with=("因数倍数与质合数",),
    ),
    KnowledgeCard(
        candidate_id="local:calculation:mixed_decimal_fraction",
        knowledge_point="小数分数混合运算",
        domain="number_operation",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="校内数与运算",
        keywords=("小数", "分数", "混合运算", "四则混合运算", "乘除", "加减"),
        recommended_level="L2",
        source_label="校内数与运算",
        necessary_structures=("小数或分数运算",),
        excluded_contexts=("整数整除约束", "质数合数判定"),
    ),
    KnowledgeCard(
        candidate_id="local:number_theory:factor_multiple_prime",
        knowledge_point="因数倍数与质合数",
        domain="number_theory",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="校内数论基础",
        keywords=NUMBER_THEORY_TERMS,
        recommended_level="L2",
        source_label="校内数论基础",
        necessary_structures=("整数约束", "整除/因倍质合证据"),
        excluded_contexts=("纯计算式", "小数分数混合运算"),
        confusing_with=("乘法分配律与简便计算",),
    ),
)


STRUCTURE_SLOTS: tuple[KnowledgeCard, ...] = (
    KnowledgeCard(
        candidate_id="slot:travel",
        knowledge_point="行程问题",
        domain="quantity_application",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="行程结构",
        keywords=("行程", "相遇", "追及", "速度", "路程", "时间", "同向", "相向", "流水"),
        recommended_level="L3",
        necessary_structures=("速度/路程/时间",),
    ),
    KnowledgeCard(
        candidate_id="slot:work_rate",
        knowledge_point="工程效率问题",
        domain="quantity_application",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="工程效率结构",
        keywords=("工程", "效率", "合作", "单独", "共同完成", "工作量", "轮流"),
        recommended_level="L3",
        necessary_structures=("总量", "单位时间效率"),
    ),
    KnowledgeCard(
        candidate_id="slot:grazing",
        knowledge_point="牛吃草模型",
        domain="quantity_application",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="增长消耗结构",
        keywords=("牛吃草", "原有", "生长", "增长", "增加", "流入", "消耗", "流出", "吃完", "抽干", "每天"),
        recommended_level="L4",
        necessary_structures=("原有量", "增长/流入", "消耗/流出"),
    ),
    KnowledgeCard(
        candidate_id="slot:concentration",
        knowledge_point="浓度问题",
        domain="quantity_application",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="浓度混合结构",
        keywords=("浓度", "溶液", "盐水", "含盐", "加水", "蒸发", "混合", "百分比"),
        recommended_level="L3",
        necessary_structures=("溶质", "溶液或浓度变化"),
    ),
    KnowledgeCard(
        candidate_id="slot:profit_discount",
        knowledge_point="利润折扣问题",
        domain="quantity_application",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="经济利润结构",
        keywords=("利润", "获利", "折扣", "成本", "售价", "销售价", "进价", "标价", "打折", "盈利", "亏损", "加价"),
        recommended_level="L3",
        necessary_structures=("成本/售价", "利润或折扣"),
    ),
    KnowledgeCard(
        candidate_id="slot:ratio_percent",
        knowledge_point="比例百分数应用",
        domain="quantity_application",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="比例百分数结构",
        keywords=("比例", "比", "百分数", "百分比", "占", "率", "增加了", "减少了"),
        recommended_level="L2",
        necessary_structures=("基准量", "比例或百分率"),
    ),
    KnowledgeCard(
        candidate_id="slot:reverse_surplus",
        knowledge_point="还原与盈亏问题",
        domain="quantity_application",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="还原盈亏结构",
        keywords=("还原", "倒推", "原来", "最后", "剩下", "盈亏", "不够", "正好"),
        recommended_level="L3",
        necessary_structures=("过程变化", "反向还原或盈亏比较"),
    ),
    KnowledgeCard(
        candidate_id="slot:chicken_rabbit",
        knowledge_point="鸡兔同笼",
        domain="quantity_application",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="鸡兔同笼结构",
        keywords=("鸡兔同笼", "头", "脚", "只", "腿", "共有"),
        recommended_level="L3",
        necessary_structures=("两类对象", "总数与脚数"),
    ),
    KnowledgeCard(
        candidate_id="slot:combinatorics",
        knowledge_point="组合计数",
        domain="counting_combinatorics",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="组合计数结构",
        keywords=("排列", "组合", "选法", "方案", "多少种", "分类", "不重不漏", "容斥"),
        recommended_level="L4",
        necessary_structures=("分类或选择", "计数目标"),
    ),
    KnowledgeCard(
        candidate_id="slot:period_sequence",
        knowledge_point="周期规律",
        domain="pattern_sequence",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="周期规律结构",
        keywords=("周期", "循环", "规律", "第n", "第几", "余数", "排列"),
        recommended_level="L3",
        necessary_structures=("重复节", "位置或余数"),
    ),
    KnowledgeCard(
        candidate_id="slot:geometry_midline_folding_area",
        knowledge_point="三角形中位线与翻折面积",
        domain="geometry_spatial",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="几何面积关系",
        keywords=("三角形", "△", "中点", "中位线", "翻折", "折叠", "对称", "面积", "连接", "边"),
        recommended_level="L3",
        necessary_structures=("三角形结构", "中点或中位线", "翻折或面积关系"),
        excluded_contexts=("整数整除约束", "数列规律"),
        confusing_with=("高阶数论综合", "简单规律与数列"),
    ),
    KnowledgeCard(
        candidate_id="slot:wmo_half_recurrence",
        knowledge_point="倍半递推与倒推还原",
        domain="pattern_sequence",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="倍半递推结构",
        keywords=HALF_RECURRENCE_TERMS,
        recommended_level="L3",
        necessary_structures=("连续倍半变化", "终值倒推"),
        excluded_contexts=("速度路程时间",),
        confusing_with=("行程问题", "小数分数混合运算"),
    ),
    KnowledgeCard(
        candidate_id="slot:wmo_fraction_telescoping",
        knowledge_point="分数裂项求和",
        domain="number_operation",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="分数裂项结构",
        keywords=TELESCOPING_SUM_TERMS,
        recommended_level="L4",
        necessary_structures=("分式长链", "裂项相消或求和"),
        excluded_contexts=("普通小数分数混合运算",),
        confusing_with=("小数分数混合运算", "乘法分配律与简便计算"),
    ),
    KnowledgeCard(
        candidate_id="slot:wmo_solid_view_projection",
        knowledge_point="三视图与立体图形",
        domain="geometry_spatial",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="三视图投影结构",
        keywords=SOLID_VIEW_TERMS,
        recommended_level="L4",
        necessary_structures=("立体对象", "观察方向或投影"),
        excluded_contexts=("普通图形公式",),
        confusing_with=("高年级校内图形公式",),
    ),
    KnowledgeCard(
        candidate_id="slot:wmo_digit_divisibility",
        knowledge_point="数字性质与9的倍数判定",
        domain="number_theory",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="数字整除性质",
        keywords=DIGIT_DIVISIBILITY_TERMS,
        recommended_level="L3",
        necessary_structures=("数位或数字和", "删去数字或整除性质"),
        excluded_contexts=("还原盈亏过程",),
        confusing_with=("还原与盈亏问题",),
    ),
    KnowledgeCard(
        candidate_id="slot:wmo_pigeonhole_enumeration",
        knowledge_point="抽屉原理与组合枚举",
        domain="counting_combinatorics",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="抽屉与整数拆分结构",
        keywords=PIGEONHOLE_TERMS,
        recommended_level="L4",
        necessary_structures=("分类盒子", "至少保证"),
        excluded_contexts=("还原盈亏过程",),
        confusing_with=("还原与盈亏问题", "简单枚举与分类"),
    ),
    KnowledgeCard(
        candidate_id="slot:wmo_game_winning_strategy",
        knowledge_point="博弈策略与必胜策略",
        domain="logic_strategy_construction",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="博弈必胜结构",
        keywords=GAME_STRATEGY_TERMS,
        recommended_level="L5",
        necessary_structures=("游戏规则", "胜负目标", "移动或应对"),
        excluded_contexts=("还原盈亏过程",),
        confusing_with=("还原与盈亏问题",),
    ),
    KnowledgeCard(
        candidate_id="slot:wmo_ratio_whole_relation",
        knowledge_point="比例整体关系",
        domain="quantity_application",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="比例整体转化结构",
        keywords=RATIO_WHOLE_TERMS,
        recommended_level="L3",
        necessary_structures=("部分与其余部分之比", "统一总量"),
        excluded_contexts=("普通数与代数泛化",),
        confusing_with=("高年级校内数与代数",),
    ),
    KnowledgeCard(
        candidate_id="slot:wmo_spatial_extremum",
        knowledge_point="三视图空间极值构造",
        domain="geometry_spatial",
        source_family="local_rules",
        source="local_structure_rules",
        chapter_title="三视图空间极值结构",
        keywords=SPATIAL_EXTREMUM_TERMS,
        recommended_level="L4",
        necessary_structures=("三视图约束", "最少最多构造"),
        excluded_contexts=("普通组合计数", "典型应用题入门模型"),
        confusing_with=("组合计数", "典型应用题入门模型"),
    ),
)


STRUCTURE_REQUIRED_GROUPS: Dict[str, tuple[tuple[str, ...], ...]] = {
    "slot:grazing": (
        ("原有", "一开始", "草量", "水池"),
        ("生长", "增长", "增加", "流入", "新长"),
        ("消耗", "流出", "吃完", "抽干", "排出"),
    ),
    "slot:travel": (("速度", "每小时", "路程", "相遇", "追及", "相向", "同向"),),
    "slot:work_rate": (("效率", "合作", "单独", "共同完成", "工作量", "完成"),),
    "slot:concentration": (("浓度", "溶液", "盐水", "含盐", "混合"),),
    "slot:profit_discount": (("利润", "获利", "折扣", "成本", "售价", "销售价", "进价", "标价", "盈利", "亏损", "加价"),),
    "slot:ratio_percent": (("比例", "百分数", "百分比", "占", "%", "率"),),
    "slot:reverse_surplus": (("还原", "倒推", "原来", "最后", "剩下", "盈亏", "不够", "正好"),),
    "slot:chicken_rabbit": (("鸡兔同笼", "头", "脚", "腿"),),
    "slot:combinatorics": (("排列", "组合", "选法", "方案", "多少种", "分类", "容斥"),),
    "slot:period_sequence": (("周期", "循环", "规律", "第n", "第几", "余数"),),
    "slot:geometry_midline_folding_area": (
        ("三角形", "△"),
        ("中点", "中位线"),
        ("翻折", "折叠", "对称", "面积"),
    ),
    "slot:wmo_half_recurrence": (
        ("失去其质量的一半", "失去一半", "一半"),
        ("每小时", "小时后", "八小时后"),
    ),
    "slot:wmo_fraction_telescoping": (
        ("/", "分数", "3/"),
        ("...", "…", "求和", "裂项"),
        ("×", "*"),
    ),
    "slot:wmo_solid_view_projection": (
        ("正方体", "透明正方体", "立体图形"),
        ("从左面", "从前面", "观察", "看到的图形", "视图", "投影"),
    ),
    "slot:wmo_digit_divisibility": (
        ("四位数", "数位", "数字之和", "数位和"),
        ("删去", "被删去", "剩下的数字", "非零数字"),
    ),
    "slot:wmo_pigeonhole_enumeration": (
        ("至少有", "完全相同", "保证"),
        ("每人可选", "每种", "品种", "组合枚举", "整数拆分"),
    ),
    "slot:wmo_game_winning_strategy": (
        ("棋子", "玩家", "游戏"),
        ("获胜", "制胜策略", "无法移动", "输掉游戏", "必胜"),
        ("移动", "不能跳过", "规则"),
    ),
    "slot:wmo_ratio_whole_relation": (
        ("销售量", "销售总量"),
        ("之和的比", "与", "比是"),
        ("总量", "整体", "四个月"),
    ),
    "slot:wmo_spatial_extremum": (
        ("立体图形", "透明积木", "积木"),
        ("从前面", "从左面", "看到的图形", "视图"),
        ("最少", "最多", "极值"),
    ),
}


def _question_structure_flags(question_text: str) -> set[str]:
    flags: set[str] = set()
    normalized = _clean_text(question_text)
    if not normalized:
        return flags

    if _is_formula_like(question_text):
        flags.add("calculation")
    if _has_decimal(question_text) or _has_fraction(question_text) or _has_common_factor_pattern(question_text):
        flags.add("number_operation")
    if _contains_any(question_text, NUMBER_THEORY_TERMS):
        flags.add("number_theory")
    if _contains_any(question_text, PATTERN_SEQUENCE_TERMS):
        flags.add("pattern_sequence")

    travel_core_hits = _contains_any(
        question_text,
        ("行程", "相遇", "追及", "速度", "路程", "同向", "相向", "流水", "出发"),
    )
    if travel_core_hits:
        flags.add("travel")

    work_hits = _contains_any(question_text, WORK_RATE_TERMS)
    if len(work_hits) >= 2 or ("工程" in normalized and any(term in normalized for term in ("完成", "合作", "单独", "效率"))):
        flags.add("work_rate")

    profit_hits = _contains_any(question_text, PROFIT_DISCOUNT_TERMS)
    if len(profit_hits) >= 2 or any(term in normalized for term in ("进价", "售价", "销售价", "获利", "加价")):
        flags.add("profit_discount")

    geometry_hits = _contains_any(question_text, GEOMETRY_AREA_TERMS)
    has_shape = any(term in normalized for term in ("三角形", "△", "四边形", "图形", "如图"))
    has_relation = any(term in normalized for term in ("中点", "中位线", "翻折", "折叠", "对称", "面积"))
    if has_shape and has_relation and len(geometry_hits) >= 2:
        flags.add("geometry_area")

    if any(term in normalized for term in ("失去其质量的一半", "失去一半")) or (
        "一半" in normalized and any(term in normalized for term in ("每小时", "小时后"))
    ):
        flags.add("half_recurrence")
        flags.add("pattern_sequence")

    if (
        ("/" in normalized or "分数" in normalized)
        and ("..." in normalized or "…" in normalized or "裂项" in normalized)
        and ("*" in normalized or "×" in normalized or "求和" in normalized)
    ):
        flags.add("telescoping_sum")
        flags.add("number_operation")

    if any(term in normalized for term in ("正方体", "立体图形", "积木")) and any(
        term in normalized for term in ("从左面", "从前面", "观察", "看到", "视图")
    ):
        flags.add("solid_view")

    if any(term in normalized for term in ("四位数", "数位", "数字之和")) and any(
        term in normalized for term in ("删去", "被删去", "非零数字")
    ):
        flags.add("digit_divisibility")
        flags.add("number_theory")

    if any(term in normalized for term in ("至少有", "完全相同", "保证")) and any(
        term in normalized for term in ("每人可选", "每种", "品种", "菜")
    ):
        flags.add("pigeonhole")

    if any(term in normalized for term in ("制胜策略", "获胜", "无法移动", "输掉游戏", "必胜")) and any(
        term in normalized for term in ("棋子", "玩家", "移动", "规则")
    ):
        flags.add("game_strategy")

    if "销售量" in normalized and any(term in normalized for term in ("之和的比", "比是")) and any(
        term in normalized for term in ("销售总量", "总量", "四个月")
    ):
        flags.add("ratio_whole")

    if "solid_view" in flags and any(term in normalized for term in ("最少", "最多", "最大", "最小")):
        flags.add("spatial_extremum")

    return flags


def _candidate_signature(candidate: GroundingCandidate) -> str:
    return _clean_text(
        " ".join(
            [
                candidate.canonical_knowledge_point,
                candidate.knowledge_domain,
                candidate.chapter_title,
                *candidate.matched_terms,
            ]
        )
    )


def _candidate_is_pattern_sequence(candidate: GroundingCandidate) -> bool:
    signature = _candidate_signature(candidate)
    return candidate.knowledge_domain == "pattern_sequence" or any(
        term in signature for term in ("规律", "数列", "周期", "找规律")
    )


def _candidate_is_number_theory(candidate: GroundingCandidate) -> bool:
    signature = _clean_text(
        " ".join(
            [
                candidate.canonical_knowledge_point,
                candidate.knowledge_domain,
                candidate.chapter_title,
            ]
        )
    )
    number_theory_identity_terms = (
        "因数倍数",
        "质合数",
        "质数",
        "合数",
        "质因数",
        "最大公因数",
        "最小公倍数",
        "整除",
        "余数",
        "约数",
        "同余",
    )
    return candidate.knowledge_domain == "number_theory" or any(
        _clean_text(term) in signature for term in number_theory_identity_terms
    )


def _candidate_is_geometry(candidate: GroundingCandidate) -> bool:
    signature = _candidate_signature(candidate)
    return candidate.knowledge_domain == "geometry_spatial" or any(
        term in signature for term in ("几何", "图形", "三角形", "面积", "翻折", "中位线")
    )


def _candidate_is_travel(candidate: GroundingCandidate) -> bool:
    signature = _candidate_signature(candidate)
    return "行程" in signature or any(term in signature for term in ("相遇", "追及", "速度路程"))


def _candidate_is_reverse_surplus(candidate: GroundingCandidate) -> bool:
    signature = _candidate_signature(candidate)
    return any(term in signature for term in ("还原与盈亏", "还原问题", "盈亏问题", "还原盈亏"))


def _candidate_is_generic_calculation(candidate: GroundingCandidate) -> bool:
    signature = _candidate_signature(candidate)
    if candidate.canonical_knowledge_point in {"分数裂项求和", "裂项与长链消去"}:
        return False
    return candidate.knowledge_domain == "number_operation" and any(
        term in signature for term in ("小数分数混合运算", "乘法分配律", "数与运算", "基础四则")
    )


def _candidate_is_generic_geometry_formula(candidate: GroundingCandidate) -> bool:
    signature = _candidate_signature(candidate)
    if any(term in signature for term in ("三视图", "立体图形", "空间极值", "正方体投影")):
        return False
    return any(term in signature for term in ("图形公式", "几何图形知识", "基础平面图形公式"))


def _candidate_is_generic_application(candidate: GroundingCandidate) -> bool:
    signature = _candidate_signature(candidate)
    return any(term in signature for term in ("典型应用题入门模型", "常规数量关系应用", "数量关系应用"))


def _candidate_is_generic_combinatorics(candidate: GroundingCandidate) -> bool:
    signature = _candidate_signature(candidate)
    return candidate.knowledge_domain == "counting_combinatorics" and not any(
        term in signature for term in ("抽屉", "空间", "三视图")
    )


def _add_risk(candidate: GroundingCandidate, risk: str, *, score_multiplier: float = 1.0) -> None:
    if risk not in candidate.risk_flags:
        candidate.risk_flags.append(risk)
        candidate.score *= score_multiplier


def _apply_question_structure_gates(
    candidate: GroundingCandidate,
    *,
    question_flags: set[str],
) -> None:
    has_conflicting_strong_structure = bool(
        question_flags
        & {
            "calculation",
            "work_rate",
            "profit_discount",
            "geometry_area",
            "half_recurrence",
            "telescoping_sum",
            "solid_view",
            "digit_divisibility",
            "pigeonhole",
            "game_strategy",
            "ratio_whole",
            "spatial_extremum",
        }
    )

    if _candidate_is_pattern_sequence(candidate) and "pattern_sequence" not in question_flags:
        if has_conflicting_strong_structure:
            _add_risk(candidate, "conflicting_question_structure", score_multiplier=0.25)
        else:
            _add_risk(candidate, "missing_necessary_structure", score_multiplier=0.55)

    if _candidate_is_number_theory(candidate) and "number_theory" not in question_flags:
        if has_conflicting_strong_structure:
            _add_risk(candidate, "blocked_number_theory_without_terms", score_multiplier=0.30)
        else:
            _add_risk(candidate, "missing_necessary_structure", score_multiplier=0.55)

    if "geometry_area" in question_flags and not _candidate_is_geometry(candidate):
        if _candidate_is_number_theory(candidate) or _candidate_is_pattern_sequence(candidate):
            _add_risk(candidate, "conflicting_question_structure", score_multiplier=0.25)

    if "calculation" in question_flags and _candidate_is_pattern_sequence(candidate):
        _add_risk(candidate, "conflicting_question_structure", score_multiplier=0.25)

    if "half_recurrence" in question_flags:
        if _candidate_is_travel(candidate):
            _add_risk(candidate, "conflicting_question_structure", score_multiplier=0.20)
        if _candidate_is_generic_calculation(candidate):
            _add_risk(candidate, "generic_calculation_over_specific_structure", score_multiplier=0.45)

    if "telescoping_sum" in question_flags and _candidate_is_generic_calculation(candidate):
        _add_risk(candidate, "generic_calculation_over_specific_structure", score_multiplier=0.40)

    if question_flags & {"digit_divisibility", "pigeonhole", "game_strategy"}:
        if _candidate_is_reverse_surplus(candidate):
            _add_risk(candidate, "conflicting_question_structure", score_multiplier=0.20)

    if "spatial_extremum" in question_flags:
        if (
            _candidate_is_generic_combinatorics(candidate)
            or _candidate_is_generic_application(candidate)
            or _candidate_is_generic_geometry_formula(candidate)
        ):
            _add_risk(candidate, "conflicting_question_structure", score_multiplier=0.20)
    elif "solid_view" in question_flags and _candidate_is_generic_geometry_formula(candidate):
        _add_risk(candidate, "generic_geometry_over_spatial_view", score_multiplier=0.45)

    if "ratio_whole" in question_flags and _candidate_is_generic_calculation(candidate):
        _add_risk(candidate, "generic_calculation_over_specific_structure", score_multiplier=0.45)


class Dim5KnowledgeGroundingService:
    """Build and select dim5 knowledge candidates grounded in local references."""

    def __init__(self, reference_standard: Any):
        self.reference_standard = reference_standard

    def ground(
        self,
        *,
        question_text: str,
        question_type: str = "",
        analysis_facts: Dict[str, Any] | None = None,
        max_candidates: int = 8,
    ) -> Dict[str, Any]:
        analysis_facts = analysis_facts or {}
        question_candidates = self._question_text_candidates(
            question_text=question_text,
            question_type=question_type,
        )
        structure_candidates = self._structure_candidates(question_text=question_text)
        analysis_candidates = self._analysis_fact_candidates(analysis_facts=analysis_facts)
        candidates = self._merge_candidates(
            [*question_candidates, *structure_candidates, *analysis_candidates],
            question_text=question_text,
        )
        candidates.sort(key=self._candidate_sort_key, reverse=True)
        candidates = candidates[: max(0, max_candidates)]
        selection = self._select_candidate(candidates)

        return {
            "version": DIM5_GROUNDING_VERSION,
            "query": {
                "question_type": question_type,
                "text_excerpt": str(question_text or "")[:180],
                "analysis_fact_keys": [
                    key
                    for key in ("core_task", "core_knowledge_points", "core_methods")
                    if analysis_facts.get(key)
                ],
            },
            "candidates": [candidate.as_dict() for candidate in candidates],
            **selection,
        }

    def _entries(self) -> Sequence[ReferenceEntry]:
        entries = getattr(self.reference_standard, "entries", [])
        return entries if isinstance(entries, list) else []

    def _question_text_candidates(self, *, question_text: str, question_type: str) -> List[GroundingCandidate]:
        candidates: List[GroundingCandidate] = []
        candidates.extend(self._local_card_candidates(question_text, source="question_text"))
        candidates.extend(self._reference_candidates(question_text, source="question_text"))

        if _is_formula_like(question_text):
            formula_evidence = ["纯计算式"]
            if _has_decimal(question_text):
                formula_evidence.append("小数运算")
            if _has_fraction(question_text):
                formula_evidence.append("分数运算")
            if _has_common_factor_pattern(question_text):
                formula_evidence.extend(["乘法分配律结构", "共同因数或小数缩放"])
                candidates.append(
                    self._candidate_from_card(
                        LOCAL_KNOWLEDGE_CARDS[0],
                        matched_terms=["乘法分配律", "简便计算"],
                        matched_evidence=formula_evidence,
                        match_source="question_text",
                        score=72.0,
                    )
                )
            if _has_decimal(question_text) or _has_fraction(question_text):
                candidates.append(
                    self._candidate_from_card(
                        LOCAL_KNOWLEDGE_CARDS[1],
                        matched_terms=["小数分数混合运算"],
                        matched_evidence=formula_evidence,
                        match_source="question_text",
                        score=48.0,
                    )
                )
        return candidates

    def _structure_candidates(self, *, question_text: str) -> List[GroundingCandidate]:
        candidates: List[GroundingCandidate] = []
        normalized_text = _clean_text(question_text)
        for card in STRUCTURE_SLOTS:
            required_groups = STRUCTURE_REQUIRED_GROUPS.get(card.candidate_id, ())
            group_hits: List[str] = []
            missing_required = False
            for group_terms in required_groups:
                hits = [term for term in group_terms if _clean_text(term) in normalized_text]
                if not hits:
                    missing_required = True
                    break
                group_hits.extend(hits[:2])
            keyword_hits = _contains_any(question_text, card.keywords)
            if missing_required and len(keyword_hits) < 2:
                continue
            score = 58.0 + len(group_hits) * 8 + len(keyword_hits) * 3
            candidates.append(
                self._candidate_from_card(
                    card,
                    matched_terms=_unique([*keyword_hits, *group_hits]),
                    matched_evidence=_unique([*group_hits, *keyword_hits])[:8],
                    match_source="structure",
                    score=score,
                )
            )
        return candidates

    def _analysis_fact_candidates(self, *, analysis_facts: Dict[str, Any]) -> List[GroundingCandidate]:
        parts: List[str] = [str(analysis_facts.get("core_task") or "")]
        for key in ("core_knowledge_points", "core_methods"):
            raw = analysis_facts.get(key, [])
            if isinstance(raw, list):
                parts.extend(str(item) for item in raw if str(item).strip())
        text = " ".join(parts)
        if not _clean_text(text):
            return []
        candidates = self._local_card_candidates(text, source="analysis_facts")
        candidates.extend(self._reference_candidates(text, source="analysis_facts", limit=8))
        for candidate in candidates:
            candidate.score *= 0.55
            candidate.risk_flags = _unique([*candidate.risk_flags, "analysis_facts_only"])
        return candidates

    def _local_card_candidates(self, text: str, *, source: str) -> List[GroundingCandidate]:
        candidates: List[GroundingCandidate] = []
        is_formula = _is_formula_like(text)
        for card in LOCAL_KNOWLEDGE_CARDS:
            matched = _contains_any(text, card.keywords)
            if not matched:
                continue
            score = 36.0 + sum(len(_clean_text(term)) for term in matched)
            risk_flags: List[str] = []
            if card.knowledge_point == "因数倍数与质合数" and is_formula:
                risk_flags.append("blocked_number_theory_in_calculation")
                score *= 0.35
            elif card.knowledge_point == "因数倍数与质合数" and source == "question_text" and len(matched) >= 2:
                score += 12.0
            if source == "analysis_facts":
                risk_flags.append("analysis_facts_only")
            candidates.append(
                self._candidate_from_card(
                    card,
                    matched_terms=matched[:8],
                    matched_evidence=matched[:8],
                    match_source=source,
                    score=score,
                    risk_flags=risk_flags,
                )
            )
        return candidates

    def _reference_candidates(
        self,
        text: str,
        *,
        source: str,
        limit: int = 12,
    ) -> List[GroundingCandidate]:
        normalized_text = _clean_text(text)
        candidates: List[GroundingCandidate] = []
        for entry in self._entries():
            terms = _entry_terms(entry)
            strong_matched, weak_matched = _match_terms_by_quality(normalized_text, terms)
            if not strong_matched and not weak_matched:
                continue
            if strong_matched:
                matched = strong_matched[:8]
                score = 28.0 + sum(len(_clean_text(term)) for term in matched)
                risk_flags: List[str] = []
            else:
                matched = weak_matched[:8]
                score = min(34.0, 24.0 + len(matched) * 2.0)
                risk_flags = ["weak_evidence", "weak_reference_match"]
            candidate = self._candidate_from_entry(
                entry,
                matched_terms=matched,
                matched_evidence=matched,
                match_source=source,
                score=score,
                risk_flags=risk_flags,
            )
            if source == "analysis_facts":
                candidate.risk_flags.append("analysis_facts_only")
            candidates.append(candidate)

        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[: max(0, limit)]

    def _candidate_from_card(
        self,
        card: KnowledgeCard,
        *,
        matched_terms: Sequence[str],
        matched_evidence: Sequence[str],
        match_source: str,
        score: float,
        risk_flags: Sequence[str] = (),
    ) -> GroundingCandidate:
        return GroundingCandidate(
            candidate_id=card.candidate_id,
            canonical_knowledge_point=card.knowledge_point,
            knowledge_domain=card.domain,
            source=card.source,
            source_family=card.source_family,
            source_label=card.source_label or _source_label(
                source_family=card.source_family,
                chapter_title=card.chapter_title,
            ),
            grade_hint="",
            chapter_title=card.chapter_title,
            matched_terms=list(matched_terms),
            matched_evidence=list(matched_evidence),
            match_sources={match_source},
            recommended_level=card.recommended_level,
            score=float(score),
            risk_flags=_unique(risk_flags),
            necessary_structures=list(card.necessary_structures),
            excluded_contexts=list(card.excluded_contexts),
            confusing_with=list(card.confusing_with),
        )

    def _candidate_from_entry(
        self,
        entry: ReferenceEntry,
        *,
        matched_terms: Sequence[str],
        matched_evidence: Sequence[str],
        match_source: str,
        score: float,
        risk_flags: Sequence[str] = (),
    ) -> GroundingCandidate:
        title = entry.title or entry.lecture_title or entry.topic_category or entry.category
        canonical = classify_dim5_knowledge_scope(
            {"knowledge_tags": [title, *matched_terms]},
            analysis_facts={"core_knowledge_points": [title, *matched_terms]},
        )
        point = str(canonical.get("canonical_knowledge_point") or title or "").strip()
        domain = str(canonical.get("canonical_knowledge_domain") or "school_general").strip()
        level = str(canonical.get("knowledge_level") or "L2").strip()
        source_family = _source_family(entry.source)
        grade = _parse_grade(entry.grade, entry.grade_hint, entry.book_name, entry.note)
        strong_term_count = sum(1 for term in matched_terms if not _is_weak_evidence_term(term))
        strong_source = match_source == "question_text" and strong_term_count >= 2
        if entry.source == GAOSI_QUESTION_SOURCE and match_source == "question_text" and strong_term_count:
            strong_source = True
        return GroundingCandidate(
            candidate_id="kb:"
            + ":".join(
                _clean_text(part)[:32]
                for part in (
                    entry.source,
                    title,
                    entry.grade or entry.grade_hint,
                    entry.lecture_no,
                    entry.question_no,
                )
                if str(part or "").strip()
            ),
            canonical_knowledge_point=point,
            knowledge_domain=domain,
            source=entry.source,
            source_family=source_family,
            source_label=_source_label(
                source_family=source_family,
                grade=grade,
                chapter_title=title,
                has_strong_source_evidence=strong_source,
            ),
            grade_hint=entry.grade or entry.grade_hint,
            chapter_title=title,
            matched_terms=list(matched_terms),
            matched_evidence=list(matched_evidence),
            match_sources={match_source},
            recommended_level=level,
            score=float(score),
            risk_flags=_unique(risk_flags),
        )

    def _merge_candidates(
        self,
        candidates: Sequence[GroundingCandidate],
        *,
        question_text: str,
    ) -> List[GroundingCandidate]:
        merged: Dict[str, GroundingCandidate] = {}
        is_formula = _is_formula_like(question_text)
        question_has_number_theory = bool(_contains_any(question_text, NUMBER_THEORY_TERMS))
        question_flags = _question_structure_flags(question_text)
        for candidate in candidates:
            key = f"{candidate.canonical_knowledge_point}|{candidate.knowledge_domain}"
            if is_formula and candidate.knowledge_domain == "number_theory" and not question_has_number_theory:
                candidate.risk_flags = _unique(
                    [*candidate.risk_flags, "blocked_number_theory_in_calculation"]
                )
                candidate.score *= 0.35
            _apply_question_structure_gates(candidate, question_flags=question_flags)
            if key in merged:
                merged[key].merge(candidate)
            else:
                merged[key] = candidate

        for candidate in merged.values():
            if candidate.match_source != "analysis_facts_only":
                candidate.risk_flags = [
                    flag for flag in candidate.risk_flags if flag != "analysis_facts_only"
                ]
            if "structure" in candidate.match_sources and not (
                {"conflicting_question_structure", "missing_necessary_structure"}
                & set(candidate.risk_flags)
            ):
                candidate.risk_flags = [
                    flag
                    for flag in candidate.risk_flags
                    if flag not in {"weak_evidence", "weak_reference_match", "weak_question_text_match"}
                ]
            if candidate.match_source == "analysis_facts_only" and "analysis_facts_only" not in candidate.risk_flags:
                candidate.risk_flags.append("analysis_facts_only")
            if candidate.match_source in {"question_text", "structure"} and candidate.score < 38:
                candidate.risk_flags.append("weak_question_text_match")
        return list(merged.values())

    @staticmethod
    def _candidate_sort_key(candidate: GroundingCandidate) -> tuple[int, int, float]:
        if "structure" in candidate.match_sources:
            source_rank = 5
        else:
            source_rank = {
                "both": 4,
                "question_text": 3,
                "analysis_facts_only": 1,
            }.get(candidate.match_source, 0)
        risk_rank = 0 if _blocking_risks(candidate.risk_flags) else 1
        return (risk_rank, source_rank, candidate.score)

    def _select_candidate(self, candidates: Sequence[GroundingCandidate]) -> Dict[str, Any]:
        if not candidates:
            return self._no_match("no_candidate", [])

        selected: GroundingCandidate | None = None
        for candidate in candidates:
            if _blocking_risks(candidate.risk_flags):
                continue
            if candidate.match_source == "analysis_facts_only":
                continue
            if candidate.score < 42:
                continue
            selected = candidate
            break

        if selected is None:
            top = candidates[0]
            return self._low_confidence(top, candidates)

        confidence = min(0.95, max(0.58, 0.46 + selected.score / 100.0))
        if selected.match_source in {"both", "question_text+structure"}:
            confidence = min(0.97, confidence + 0.06)
        rejected = self._rejected_candidates(candidates, selected.candidate_id)
        return {
            "selection_status": "selected",
            "selected_candidate_id": selected.candidate_id,
            "grounded_canonical_knowledge_point": selected.canonical_knowledge_point,
            "grounded_knowledge_domain": selected.knowledge_domain,
            "grounded_knowledge_source_text": selected.source_label
            if confidence >= GROUNDING_HIGH_CONFIDENCE_THRESHOLD
            else "",
            "grounded_knowledge_level": selected.recommended_level,
            "grounded_confidence": round(confidence, 3),
            "grounded_match_source": selected.match_source,
            "grounded_evidence": self._selection_evidence(selected),
            "grounded_risk_flags": selected.risk_flags,
            "grounded_rejected_candidates": rejected,
            "grounded_selector": "local_grounding_selector",
        }

    def _low_confidence(
        self,
        top: GroundingCandidate,
        candidates: Sequence[GroundingCandidate],
    ) -> Dict[str, Any]:
        confidence = 0.44 if top.match_source == "analysis_facts_only" else 0.52
        if _blocking_risks(top.risk_flags):
            confidence = min(confidence, 0.44)
        return {
            "selection_status": "low_confidence",
            "selected_candidate_id": top.candidate_id,
            "grounded_canonical_knowledge_point": top.canonical_knowledge_point,
            "grounded_knowledge_domain": top.knowledge_domain,
            "grounded_knowledge_source_text": "",
            "grounded_knowledge_level": top.recommended_level,
            "grounded_confidence": confidence,
            "grounded_match_source": top.match_source,
            "grounded_evidence": self._selection_evidence(top),
            "grounded_risk_flags": _unique([*top.risk_flags, "low_confidence_grounding"]),
            "grounded_rejected_candidates": self._rejected_candidates(candidates, top.candidate_id),
            "grounded_selector": "local_grounding_selector",
        }

    @staticmethod
    def _no_match(reason: str, candidates: Sequence[GroundingCandidate]) -> Dict[str, Any]:
        return {
            "selection_status": "no_match",
            "selected_candidate_id": "no_match",
            "grounded_canonical_knowledge_point": "",
            "grounded_knowledge_domain": "",
            "grounded_knowledge_source_text": "",
            "grounded_knowledge_level": "",
            "grounded_confidence": 0.0,
            "grounded_match_source": "",
            "grounded_evidence": reason,
            "grounded_risk_flags": ["no_grounded_match"],
            "grounded_rejected_candidates": [
                {
                    "candidate_id": candidate.candidate_id,
                    "knowledge_point": candidate.canonical_knowledge_point,
                    "reason": "not_selected",
                }
                for candidate in candidates[:4]
            ],
            "grounded_selector": "local_grounding_selector",
        }

    @staticmethod
    def _rejected_candidates(
        candidates: Sequence[GroundingCandidate],
        selected_id: str,
    ) -> List[Dict[str, str]]:
        rejected: List[Dict[str, str]] = []
        for candidate in candidates:
            if candidate.candidate_id == selected_id:
                continue
            reason = "evidence_weaker_than_selected"
            if "analysis_facts_only" in candidate.risk_flags:
                reason = "analysis_facts_only_without_question_evidence"
            if "blocked_number_theory_in_calculation" in candidate.risk_flags:
                reason = "pure_calculation_without_number_theory_evidence"
            if "weak_evidence" in candidate.risk_flags or "weak_reference_match" in candidate.risk_flags:
                reason = "weak_ocr_or_option_fragment_evidence"
            if "conflicting_question_structure" in candidate.risk_flags:
                reason = "conflicts_with_question_structure"
            if "missing_necessary_structure" in candidate.risk_flags:
                reason = "missing_required_knowledge_structure"
            if "generic_calculation_over_specific_structure" in candidate.risk_flags:
                reason = "generic_calculation_weaker_than_specific_structure"
            if "generic_geometry_over_spatial_view" in candidate.risk_flags:
                reason = "generic_geometry_formula_weaker_than_spatial_view"
            rejected.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "knowledge_point": candidate.canonical_knowledge_point,
                    "reason": reason,
                }
            )
            if len(rejected) >= 5:
                break
        return rejected

    @staticmethod
    def _selection_evidence(candidate: GroundingCandidate) -> str:
        evidence = "、".join(candidate.matched_evidence[:4]) or "题面知识信号"
        if candidate.canonical_knowledge_point == "乘法分配律与简便计算":
            return "题面是纯计算，出现乘法与加减组合，并存在共同因数或小数缩放，优先归入乘法分配律与简便计算。"
        if candidate.canonical_knowledge_point == "三角形中位线与翻折面积":
            return "题面出现三角形、中点、翻折和面积关系，优先归入几何面积关系。"
        if candidate.canonical_knowledge_point == "倍半递推与倒推还原":
            return "题面出现连续按一半变化并给出末端状态，核心是倍半递推和倒推还原。"
        if candidate.canonical_knowledge_point == "分数裂项求和":
            return "题面是分式长链求和，出现连续分母结构和省略号，核心是裂项相消。"
        if candidate.canonical_knowledge_point == "三视图与立体图形":
            return "题面出现立体对象和观察方向，核心是三视图投影与空间想象。"
        if candidate.canonical_knowledge_point == "数字性质与9的倍数判定":
            return "题面围绕数位、数字和与删去数字，核心是数字性质和整除判定。"
        if candidate.canonical_knowledge_point == "抽屉原理与组合枚举":
            return "题面要求至少出现相同选择，核心是先枚举分类盒子，再用抽屉原理保证。"
        if candidate.canonical_knowledge_point == "博弈策略与必胜策略":
            return "题面给出棋子移动规则和获胜目标，核心是博弈必胜策略。"
        if candidate.canonical_knowledge_point == "比例整体关系":
            return "题面多次比较部分与其余部分之和，核心是比例整体转化。"
        if candidate.canonical_knowledge_point == "三视图空间极值构造":
            return "题面在三视图约束下同时求最少和最多，核心是空间极值构造。"
        if candidate.match_source == "analysis_facts_only":
            return f"仅在 analysis_facts 中出现 {evidence}，缺少题面直接证据。"
        return f"题面证据命中 {evidence}，匹配 {candidate.canonical_knowledge_point}。"


def _blocking_risks(risk_flags: Sequence[str]) -> bool:
    return bool(
        {
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
        }
        & {str(flag) for flag in risk_flags}
    )
