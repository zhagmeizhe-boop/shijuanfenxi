from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.parser.reference_standard import (  # noqa: E402
    BAND_LABELS,
    GAOSI_PDF_DATA_FILE_NAME,
    GAOSI_QUESTION_DATA_FILE_NAME,
    GAOSI_QUESTION_SOURCE,
    GAOSI_SECTION_SUBLEVELS,
    ReferenceEntry,
    _compact_terms,
)
from scripts.extract_gaosi_pdf_reference import (  # noqa: E402
    PdfSpec,
    _build_ocr_engine,
    _default_specs,
    _ocr_page,
    _resolve_model_dir,
)


SHEET_NAME = "高思导引PDF题目"
DEFAULT_OUTPUT_PATH = (
    ROOT / "app" / "services" / "parser" / GAOSI_QUESTION_DATA_FILE_NAME
)
DEFAULT_AUDIT_PATH = ROOT / "data" / "gaosi_question_reference_audit.csv"
DEFAULT_SUMMARY_PATH = ROOT / "data" / "gaosi_topic_progression_summary.json"
DEFAULT_SUMMARY_AUDIT_PATH = ROOT / "data" / "gaosi_topic_progression_summary.csv"
SECTION_LEVELS = {
    "兴趣篇": "interest",
    "拓展篇": "extension",
    "超越篇": "challenge",
}
SECTION_LABELS = tuple(SECTION_LEVELS)
DIAGRAM_SIGNALS = ("如图", "图中", "下图", "右图", "左图", "图形", "图1", "图2")
ANSWER_SECTION_SIGNALS = ("参考答案", "答案与解析")
BOOK_FOOTER_PATTERN = re.compile(r"\s*高思学校竞赛数学导引\S{0,20}年级\s*$")
LECTURE_TITLE_NOISE = {
    "",
    "）",
    ")",
    "。",
    ".",
    "·",
    "目录",
    "兴趣篇",
    "拓展篇",
    "超越篇",
}
SECTION_PROFILE = {
    "interest": "同专题入门题，通常对应基础模板或直接变式。",
    "extension": "同专题拓展题，通常引入结构识别、条件重组或多步变式。",
    "challenge": "同专题超越题，通常需要更强的全局组织、构造、分类或综合迁移。",
}
DOMAIN_KEYWORDS = (
    ("calculation", ("计算", "四则", "分数", "小数", "比较大小", "简便", "裂项", "繁分式")),
    ("application", ("应用题", "工程", "牛吃草", "行程", "相遇", "追及", "比例", "百分", "利润", "浓度")),
    ("geometry", ("几何", "图形", "面积", "体积", "割补", "角", "三角形", "长方形", "圆")),
    ("number_theory", ("整除", "质数", "合数", "因数", "倍数", "余数", "同余")),
    ("counting", ("枚举", "计数", "排列", "组合", "加乘原理", "抽屉")),
    ("pattern", ("规律", "数列", "周期", "递推")),
    ("logic", ("推理", "还原", "倒推", "策略", "构造")),
)
STRUCTURE_SIGNALS = (
    ("grouping", ("凑整", "分组", "配对")),
    ("common_factor", ("公因数", "提取", "乘法分配律")),
    ("telescoping", ("裂项", "相消")),
    ("recursive_or_sequence", ("递推", "数列", "第n", "第 N", "通项")),
    ("defined_operation", ("定义", "新运算", "规定")),
    ("case_analysis", ("分类", "情况", "几种", "方案")),
    ("reverse_process", ("倒推", "还原", "反向")),
    ("growth_consumption", ("牛吃草", "匀速生长", "每天来的", "检票", "排队")),
    ("work_rate", ("工程", "效率", "工作量", "合作", "换班")),
    ("travel_chain", ("相遇", "追及", "速度", "路程", "往返")),
    ("geometry_transform", ("割补", "平移", "旋转", "等积", "辅助线")),
)
QUALITY_LOW_CONFIDENCE = 0.65


@dataclass
class QuestionDraft:
    book_name: str
    grade: int
    lecture_no: str
    lecture_title: str
    section_label: str
    page_no: int
    question_no: str
    star_level: str
    source_pdf: str
    lines: List[str] = field(default_factory=list)
    confidences: List[float] = field(default_factory=list)
    pages: List[int] = field(default_factory=list)

    def add_line(self, text: str, confidence: float, page_no: int) -> None:
        cleaned = _clean_line(text)
        if not cleaned:
            return
        self.lines.append(cleaned)
        self.confidences.append(confidence)
        if page_no not in self.pages:
            self.pages.append(page_no)

    @property
    def question_text(self) -> str:
        return _clean_question_text(" ".join(self.lines))

    @property
    def ocr_confidence(self) -> float:
        if not self.confidences:
            return 0.0
        return round(sum(self.confidences) / len(self.confidences), 4)

    @property
    def has_diagram(self) -> bool:
        return any(signal in self.question_text for signal in DIAGRAM_SIGNALS)

    @property
    def source_pages(self) -> List[int]:
        return self.pages or [self.page_no]


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip())


def _clean_line(text: str) -> str:
    text = str(text or "").strip()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text


def _clean_question_text(text: str) -> str:
    text = _clean_line(text)
    text = BOOK_FOOTER_PATTERN.sub("", text)
    text = re.sub(r"\s*高思学校竞赛数学导引\S*$", "", text)
    text = re.sub(r"^(?:[★☆*＊\s]*\d{1,3}[.．、)]\s*)+", "", text)
    return text.strip()


def _is_noise_line(text: str) -> bool:
    compact = _normalize_for_match(text)
    if not compact:
        return True
    if compact in {"高思学校竞赛数学导引", "竞赛数学导引", "目录"}:
        return True
    if compact.startswith("高思学校竞赛数学导引"):
        return True
    if re.fullmatch(r"\d{1,3}", compact):
        return True
    if re.fullmatch(r"[-—_·.。]+", compact):
        return True
    return False


def _chinese_number_to_int(text: str) -> int | None:
    text = _normalize_for_match(text)
    if not text:
        return None
    if text.isdigit():
        return int(text)
    digits = {
        "零": 0,
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = digits.get(left, 1 if left == "" else 0)
        ones = digits.get(right, 0) if right else 0
        value = tens * 10 + ones
        return value or None
    return digits.get(text)


def _normalize_lecture_no(value: object) -> str:
    number = _chinese_number_to_int(str(value or ""))
    return str(number) if number is not None else _normalize_for_match(value)


def _clean_title_candidate(value: object) -> str:
    title = _clean_line(str(value or ""))
    title = re.sub(r"^第\s*[一二三四五六七八九十百\d]+\s*讲", "", title).strip()
    title = re.sub(r"^[：:·.．。\s]+", "", title)
    title = re.sub(r"[.．。·•，,\s]+$", "", title)
    title = title.strip("()（）[]【】")
    compact = _normalize_for_match(title)
    if compact in LECTURE_TITLE_NOISE:
        return ""
    if re.fullmatch(r"[)）(（\W_]+", title):
        return ""
    if title.startswith("高思学校竞赛数学导引"):
        return ""
    return title


def _section_label(text: str) -> str:
    compact = _normalize_for_match(text)
    for label in SECTION_LABELS:
        if label in compact:
            return label
    return ""


def _is_answer_section(text: str) -> bool:
    compact = _normalize_for_match(text)
    return any(signal in compact for signal in ANSWER_SECTION_SIGNALS)


def _is_answer_page(lines: Sequence[Any]) -> bool:
    top_text = "".join(_clean_line(getattr(line, "text", "")) for line in list(lines)[:12])
    compact = _normalize_for_match(top_text)
    return any(signal in compact for signal in ANSWER_SECTION_SIGNALS)


def _parse_lecture(text: str) -> tuple[str, str]:
    compact = _clean_line(text)
    match = re.search(r"第\s*([一二三四五六七八九十百\d]+)\s*讲\s*(.*)", compact)
    if not match:
        return "", ""
    lecture_no = _normalize_lecture_no(match.group(1))
    lecture_title = _clean_title_candidate(match.group(2))
    return lecture_no, lecture_title


def _parse_question_start(text: str) -> tuple[str, str, str]:
    cleaned = _clean_line(text)
    match = re.match(
        r"^([★☆*＊\s]{0,8})(\d{1,3})(?:[.．、)]\s*|\s+(?=[★☆*＊]))([★☆*＊\s]{0,8})(.*)",
        cleaned,
    )
    if not match:
        return "", "", ""
    star_level = (match.group(1) + match.group(3)).strip().replace("*", "★").replace("＊", "★")
    question_no = match.group(2)
    rest = match.group(4).strip()
    return question_no, star_level, rest


def _load_lecture_lookup(path: Path | None = None) -> Dict[tuple[int, str], Dict[str, str]]:
    data_path = path or (ROOT / "app" / "services" / "parser" / GAOSI_PDF_DATA_FILE_NAME)
    if not data_path.exists():
        return {}
    try:
        payload = json.loads(data_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, list):
        return {}

    lookup: Dict[tuple[int, str], Dict[str, str]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        grade_match = re.search(r"(\d+)\s*年级", str(item.get("grade_hint", "")))
        lecture_match = re.search(r"第\s*([一二三四五六七八九十百\d]+)\s*讲", str(item.get("note", "")))
        if not grade_match or not lecture_match:
            continue
        grade = int(grade_match.group(1))
        lecture_no = _normalize_lecture_no(lecture_match.group(1))
        title = _clean_title_candidate(item.get("title", ""))
        if not title:
            continue
        lookup[(grade, lecture_no)] = {
            "title": title,
            "category": _clean_title_candidate(item.get("category", "")),
        }
    return lookup


def _resolve_lecture_title(
    grade: int,
    lecture_no: str,
    ocr_title: str,
    lookup: Dict[tuple[int, str], Dict[str, str]],
    current_title: str = "",
) -> str:
    lookup_title = lookup.get((grade, _normalize_lecture_no(lecture_no)), {}).get("title", "")
    if lookup_title:
        return lookup_title
    cleaned = _clean_title_candidate(ocr_title)
    if cleaned:
        return cleaned
    current = _clean_title_candidate(current_title)
    if current:
        return current
    return ""


def _entry_topic_category(
    grade: int,
    lecture_no: str,
    lecture_title: str,
    lookup: Dict[tuple[int, str], Dict[str, str]] | None = None,
) -> str:
    lookup = lookup or {}
    category = lookup.get((grade, _normalize_lecture_no(lecture_no)), {}).get("category", "")
    return category or lecture_title


def _count_non_space_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def _text_length_band(length: int) -> str:
    if length < 45:
        return "short"
    if length < 90:
        return "medium"
    if length < 120:
        return "long"
    return "very_long"


def _extract_structure_signals(text: str) -> List[str]:
    compact = _normalize_for_match(text)
    signals: List[str] = []
    for signal, keywords in STRUCTURE_SIGNALS:
        if any(keyword in compact for keyword in keywords):
            signals.append(signal)
    return signals


def _infer_topic_domain(lecture_title: str, question_text: str) -> str:
    compact = _normalize_for_match(f"{lecture_title} {question_text}")
    for domain, keywords in DOMAIN_KEYWORDS:
        if any(keyword in compact for keyword in keywords):
            return domain
    return "general"


def _quality_flags(draft: QuestionDraft, question_text: str) -> List[str]:
    flags: List[str] = []
    if draft.ocr_confidence < QUALITY_LOW_CONFIDENCE:
        flags.append("low_ocr_confidence")
    if draft.has_diagram:
        flags.append("has_diagram")
    if len(question_text) < 12:
        flags.append("short_question_text")
    if not _clean_title_candidate(draft.lecture_title):
        flags.append("missing_lecture_title")
    if len(draft.source_pages) > 1:
        flags.append("cross_page_question")
    return flags


def _build_structure_profile(
    draft: QuestionDraft,
    *,
    topic_category: str,
    question_text: str,
) -> Dict[str, Any]:
    length = _count_non_space_chars(question_text)
    section_level = SECTION_LEVELS[draft.section_label]
    return {
        "knowledge_point": draft.lecture_title or topic_category,
        "topic_category": topic_category,
        "topic_domain": _infer_topic_domain(draft.lecture_title or topic_category, question_text),
        "gaosi_grade": str(draft.grade),
        "section_level": section_level,
        "section_label": draft.section_label,
        "section_progression_role": SECTION_PROFILE.get(section_level, ""),
        "text_length_chars": length,
        "text_length_band": _text_length_band(length),
        "structure_signals": _extract_structure_signals(question_text),
        "star_count": draft.star_level.count("★"),
        "has_diagram": draft.has_diagram,
        "source_pages": draft.source_pages,
        "quality_flags": _quality_flags(draft, question_text),
        "profile_source": "local_ocr_structure",
    }


def _dim5_reference_band(grade: int, section_level: str) -> str:
    if section_level == "challenge":
        return BAND_LABELS[5]
    return BAND_LABELS[3] if grade <= 4 else BAND_LABELS[4]


def _dim5_reference_sublevel(section_level: str) -> str:
    return GAOSI_SECTION_SUBLEVELS.get(section_level, "")


def _knowledge_anchor_terms(
    *,
    lecture_title: str,
    topic_category: str,
    structure_profile: Dict[str, Any],
) -> List[str]:
    terms: List[str] = []
    for value in (
        lecture_title,
        topic_category,
        structure_profile.get("topic_domain", ""),
        *structure_profile.get("structure_signals", []),
    ):
        text = str(value or "").strip()
        if len(_normalize_for_match(text)) >= 3 and text not in terms:
            terms.append(text)
    return terms


def _dim5_match_safety_level(structure_profile: Dict[str, Any]) -> str:
    flags = {
        str(flag or "").strip()
        for flag in structure_profile.get("quality_flags", []) or []
        if str(flag or "").strip()
    }
    if flags & {"low_ocr_confidence", "short_question_text"}:
        return "unsafe"
    if flags & {"has_diagram", "cross_page_question"}:
        return "review"
    return "auto"


def _build_dim5_profile(
    *,
    grade: int,
    lecture_title: str,
    topic_category: str,
    structure_profile: Dict[str, Any],
) -> Dict[str, Any]:
    section_level = str(structure_profile.get("section_level") or "")
    return {
        "knowledge_anchor_terms": _knowledge_anchor_terms(
            lecture_title=lecture_title,
            topic_category=topic_category,
            structure_profile=structure_profile,
        ),
        "dim5_reference_band": _dim5_reference_band(grade, section_level),
        "dim5_reference_sublevel": _dim5_reference_sublevel(section_level),
        "match_safety_level": _dim5_match_safety_level(structure_profile),
        "quality_flags": list(structure_profile.get("quality_flags", []) or []),
        "profile_source": "local_ocr_dim5_safety_profile",
    }


def _build_dim4_profile_skeleton(structure_profile: Dict[str, Any]) -> Dict[str, Any]:
    section_level = str(structure_profile.get("section_level") or "")
    text_length_band = str(structure_profile.get("text_length_band") or "")
    signal_count = len(structure_profile.get("structure_signals") or [])
    star_count = int(structure_profile.get("star_count") or 0)
    if section_level == "challenge" and (signal_count >= 2 or text_length_band in {"long", "very_long"}):
        level = "L5" if signal_count >= 3 or star_count >= 2 else "L4"
    elif section_level == "challenge":
        level = "L4"
    elif section_level == "extension" and (signal_count >= 2 or text_length_band in {"long", "very_long"}):
        level = "L4"
    elif section_level == "extension":
        level = "L3"
    elif signal_count >= 2 or text_length_band == "very_long":
        level = "L3"
    elif signal_count == 1 or text_length_band == "long":
        level = "L2"
    else:
        level = "L1"

    return {
        "reference_level": level,
        "knowledge_point": structure_profile.get("knowledge_point", ""),
        "profile_confidence": 0.55,
        "auto_calibration_allowed": False,
        "profile_source": "local_structure_skeleton",
        "evidence_summary": "本地 OCR 结构画像给出的初始 dim4 档位，仅用于离线学习与后续 LLM 画像输入，不直接自动校准。",
        "profile_warning": "未经过 LLM 或人工确认，运行时只作为审计画像。",
    }


def _to_reference_entry(
    draft: QuestionDraft,
    *,
    lecture_lookup: Dict[tuple[int, str], Dict[str, str]] | None = None,
) -> ReferenceEntry | None:
    question_text = draft.question_text
    if len(question_text) < 6:
        return None

    grade_hint = f"{draft.grade}年级"
    section_level = SECTION_LEVELS[draft.section_label]
    lecture_lookup = lecture_lookup or {}
    lecture_title = _resolve_lecture_title(
        draft.grade,
        draft.lecture_no,
        draft.lecture_title,
        lecture_lookup,
    )
    topic_category = _entry_topic_category(draft.grade, draft.lecture_no, lecture_title, lecture_lookup)
    title = lecture_title or f"第{draft.lecture_no}讲"
    structure_profile = _build_structure_profile(
        QuestionDraft(
            book_name=draft.book_name,
            grade=draft.grade,
            lecture_no=draft.lecture_no,
            lecture_title=lecture_title,
            section_label=draft.section_label,
            page_no=draft.page_no,
            question_no=draft.question_no,
            star_level=draft.star_level,
            source_pdf=draft.source_pdf,
            lines=draft.lines,
            confidences=draft.confidences,
            pages=draft.pages,
        ),
        topic_category=topic_category,
        question_text=question_text,
    )
    note = (
        f"{draft.book_name} 第{draft.lecture_no}讲 {draft.section_label} "
        f"第{draft.question_no}题，PDF页 {','.join(str(page) for page in draft.source_pages)}"
    )
    return ReferenceEntry(
        source=GAOSI_QUESTION_SOURCE,
        sheet_name=SHEET_NAME,
        category=topic_category,
        title=title,
        track=draft.section_label,
        grade_hint=grade_hint,
        note=note,
        keywords=_compact_terms(
            lecture_title,
            topic_category,
            draft.section_label,
            grade_hint,
            question_text[:120],
        ),
        grade=str(draft.grade),
        book_name=draft.book_name,
        lecture_no=draft.lecture_no,
        lecture_title=lecture_title,
        topic_category=topic_category,
        section_level=section_level,
        section_label=draft.section_label,
        page_no=",".join(str(page) for page in draft.source_pages),
        question_no=draft.question_no,
        star_level=draft.star_level,
        question_text=question_text,
        has_diagram=draft.has_diagram,
        ocr_confidence=draft.ocr_confidence,
        source_pdf=draft.source_pdf,
        dimension_profiles={
            "structure": structure_profile,
            "dim4": _build_dim4_profile_skeleton(structure_profile),
            "dim5": _build_dim5_profile(
                grade=draft.grade,
                lecture_title=lecture_title,
                topic_category=topic_category,
                structure_profile=structure_profile,
            ),
        },
    )


def _flush_question(
    draft: QuestionDraft | None,
    entries: List[ReferenceEntry],
    *,
    lecture_lookup: Dict[tuple[int, str], Dict[str, str]] | None = None,
) -> None:
    if draft is None:
        return
    entry = _to_reference_entry(draft, lecture_lookup=lecture_lookup)
    if entry is not None:
        entries.append(entry)


def _dedupe_entries(entries: Iterable[ReferenceEntry]) -> List[ReferenceEntry]:
    deduped: List[ReferenceEntry] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for entry in entries:
        key = (
            entry.grade,
            entry.lecture_no,
            entry.section_label,
            entry.question_no,
            entry.question_text[:80],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _entry_structure(entry: ReferenceEntry) -> Dict[str, Any]:
    profiles = entry.dimension_profiles if isinstance(entry.dimension_profiles, dict) else {}
    structure = profiles.get("structure", {})
    return dict(structure) if isinstance(structure, dict) else {}


def _entry_dim5(entry: ReferenceEntry) -> Dict[str, Any]:
    profiles = entry.dimension_profiles if isinstance(entry.dimension_profiles, dict) else {}
    profile = profiles.get("dim5", {})
    return dict(profile) if isinstance(profile, dict) else {}


def _sample_text(text: str, max_chars: int = 90) -> str:
    text = _clean_line(text)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}..."


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return default


def build_topic_progression_summary(entries: Sequence[ReferenceEntry]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[str, str, str], List[ReferenceEntry]] = {}
    for entry in entries:
        key = (entry.grade, entry.lecture_no, entry.lecture_title or entry.title)
        grouped.setdefault(key, []).append(entry)

    summaries: List[Dict[str, Any]] = []
    section_order = {"interest": 0, "extension": 1, "challenge": 2}
    for (grade, lecture_no, lecture_title), group in sorted(
        grouped.items(),
        key=lambda item: (_safe_int(item[0][0]), _safe_int(item[0][1]), item[0][2]),
    ):
        section_summaries: List[Dict[str, Any]] = []
        all_signals: set[str] = set()
        topic_domain = ""
        for section_label, section_level in SECTION_LEVELS.items():
            section_entries = [entry for entry in group if entry.section_label == section_label]
            if not section_entries:
                continue
            lengths = [_count_non_space_chars(entry.question_text) for entry in section_entries]
            diagrams = sum(1 for entry in section_entries if entry.has_diagram)
            low_confidence = sum(1 for entry in section_entries if entry.ocr_confidence < QUALITY_LOW_CONFIDENCE)
            signals: set[str] = set()
            for entry in section_entries:
                structure = _entry_structure(entry)
                topic_domain = topic_domain or str(structure.get("topic_domain") or "")
                signals.update(str(signal) for signal in structure.get("structure_signals", []) or [])
            all_signals.update(signals)
            section_entries_sorted = sorted(section_entries, key=lambda entry: _safe_int(entry.question_no))
            section_summaries.append(
                {
                    "section_level": section_level,
                    "section_label": section_label,
                    "question_count": len(section_entries),
                    "question_numbers": [entry.question_no for entry in section_entries_sorted],
                    "average_text_length_chars": round(sum(lengths) / max(len(lengths), 1), 1),
                    "diagram_question_count": diagrams,
                    "low_confidence_question_count": low_confidence,
                    "structure_signals": sorted(signals),
                    "representative_questions": [
                        {
                            "question_no": entry.question_no,
                            "page_no": entry.page_no,
                            "star_level": entry.star_level,
                            "text": _sample_text(entry.question_text),
                        }
                        for entry in section_entries_sorted[:3]
                    ],
                    "progression_note": SECTION_PROFILE[section_level],
                }
            )

        section_summaries.sort(key=lambda item: section_order.get(str(item["section_level"]), 99))
        missing_sections = [
            label
            for label, level in SECTION_LEVELS.items()
            if not any(item["section_level"] == level for item in section_summaries)
        ]
        summaries.append(
            {
                "grade": grade,
                "lecture_no": lecture_no,
                "lecture_title": lecture_title,
                "topic_domain": topic_domain or "general",
                "question_count": len(group),
                "section_count": len(section_summaries),
                "missing_sections": missing_sections,
                "structure_signals": sorted(all_signals),
                "sections": section_summaries,
                "progression_summary": (
                    f"{lecture_title} 在高思导引中按兴趣篇、拓展篇、超越篇递进；"
                    "题目级 OCR 库已保留各篇章代表题、结构信号和质量标记，"
                    "dim5 可据此区分篇章层级，dim4 可在同专题内进行变式等级校准。"
                ),
            }
        )
    return summaries


def extract_question_entries(
    specs: Iterable[PdfSpec],
    *,
    max_pages: int | None,
    zoom: float,
    model_dir: Path,
    start_page: int = 1,
    lecture_lookup: Dict[tuple[int, str], Dict[str, str]] | None = None,
    progress_every: int = 0,
) -> List[ReferenceEntry]:
    ocr = _build_ocr_engine(model_dir)
    entries: List[ReferenceEntry] = []
    lecture_lookup = lecture_lookup or _load_lecture_lookup()

    for spec in specs:
        if not spec.path.exists():
            raise FileNotFoundError(spec.path)

        current_lecture_no = ""
        current_lecture_title = ""
        current_section = ""
        current_question: QuestionDraft | None = None

        with fitz.open(str(spec.path)) as doc:
            page_count = doc.page_count
            page_end = page_count if max_pages is None else min(page_count, max_pages)
            for page_no in range(max(start_page, 1), page_end + 1):
                if progress_every > 0 and (
                    page_no == max(start_page, 1)
                    or page_no == page_end
                    or (page_no - max(start_page, 1)) % progress_every == 0
                ):
                    print(
                        f"ocr progress: {spec.canonical_name} page {page_no}/{page_end}",
                        flush=True,
                    )
                page = doc.load_page(page_no - 1)
                lines = _ocr_page(ocr, page, zoom)
                if _is_answer_page(lines) and current_lecture_no:
                    _flush_question(current_question, entries, lecture_lookup=lecture_lookup)
                    current_question = None
                    break

                for line in lines:
                    text = _clean_line(line.text)
                    if _is_noise_line(text):
                        continue

                    lecture_no, lecture_title = _parse_lecture(text)
                    if lecture_no:
                        is_new_lecture = lecture_no != current_lecture_no
                        if is_new_lecture:
                            _flush_question(current_question, entries, lecture_lookup=lecture_lookup)
                            current_question = None
                        current_lecture_no = lecture_no
                        current_lecture_title = _resolve_lecture_title(
                            spec.grade,
                            current_lecture_no,
                            lecture_title,
                            lecture_lookup,
                            current_lecture_title,
                        )
                        if is_new_lecture:
                            current_section = ""
                        continue

                    section_label = _section_label(text)
                    if section_label:
                        _flush_question(current_question, entries, lecture_lookup=lecture_lookup)
                        current_question = None
                        current_section = section_label
                        continue

                    if not current_lecture_no or not current_section:
                        continue

                    question_no, star_level, rest = _parse_question_start(text)
                    if question_no:
                        _flush_question(current_question, entries)
                        current_question = QuestionDraft(
                            book_name=spec.canonical_name,
                            grade=spec.grade,
                            lecture_no=current_lecture_no,
                            lecture_title=current_lecture_title,
                            section_label=current_section,
                            page_no=page_no,
                            question_no=question_no,
                            star_level=star_level,
                            source_pdf=str(spec.path),
                        )
                        current_question.add_line(rest, line.confidence, page_no)
                        continue

                    if current_question is not None:
                        current_question.add_line(text, line.confidence, page_no)

        _flush_question(current_question, entries, lecture_lookup=lecture_lookup)

    return _dedupe_entries(entries)


def write_outputs(
    entries: List[ReferenceEntry],
    *,
    output_path: Path,
    audit_path: Path,
    summary_path: Path | None = None,
    summary_audit_path: Path | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([entry.to_dict() for entry in entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with audit_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "grade",
                "book_name",
                "lecture_no",
                "lecture_title",
                "section_label",
                "section_level",
                "page_no",
                "question_no",
                "star_level",
                "ocr_confidence",
                "has_diagram",
                "text_length_chars",
                "text_length_band",
                "topic_domain",
                "structure_signals",
                "quality_flags",
                "knowledge_anchor_terms",
                "dim5_reference_band",
                "dim5_reference_sublevel",
                "match_safety_level",
                "dim4_reference_level_skeleton",
                "dim4_auto_calibration_allowed",
                "question_text",
                "source_pdf",
            ],
        )
        writer.writeheader()
        for entry in entries:
            structure = _entry_structure(entry)
            dim4_profile = (
                entry.dimension_profiles.get("dim4", {})
                if isinstance(entry.dimension_profiles, dict)
                else {}
            )
            dim5_profile = _entry_dim5(entry)
            writer.writerow(
                {
                    "grade": entry.grade,
                    "book_name": entry.book_name,
                    "lecture_no": entry.lecture_no,
                    "lecture_title": entry.lecture_title,
                    "section_label": entry.section_label,
                    "section_level": entry.section_level,
                    "page_no": entry.page_no,
                    "question_no": entry.question_no,
                    "star_level": entry.star_level,
                    "ocr_confidence": entry.ocr_confidence,
                    "has_diagram": entry.has_diagram,
                    "text_length_chars": structure.get("text_length_chars", ""),
                    "text_length_band": structure.get("text_length_band", ""),
                    "topic_domain": structure.get("topic_domain", ""),
                    "structure_signals": "|".join(structure.get("structure_signals", []) or []),
                    "quality_flags": "|".join(structure.get("quality_flags", []) or []),
                    "knowledge_anchor_terms": "|".join(
                        dim5_profile.get("knowledge_anchor_terms", []) or []
                    ),
                    "dim5_reference_band": dim5_profile.get("dim5_reference_band", ""),
                    "dim5_reference_sublevel": dim5_profile.get("dim5_reference_sublevel", ""),
                    "match_safety_level": dim5_profile.get("match_safety_level", ""),
                    "dim4_reference_level_skeleton": dim4_profile.get("reference_level", ""),
                    "dim4_auto_calibration_allowed": dim4_profile.get("auto_calibration_allowed", ""),
                    "question_text": entry.question_text,
                    "source_pdf": entry.source_pdf,
                }
            )

    if summary_path:
        summaries = build_topic_progression_summary(entries)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")

        if summary_audit_path:
            summary_audit_path.parent.mkdir(parents=True, exist_ok=True)
            with summary_audit_path.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "grade",
                        "lecture_no",
                        "lecture_title",
                        "topic_domain",
                        "question_count",
                        "section_count",
                        "missing_sections",
                        "interest_count",
                        "extension_count",
                        "challenge_count",
                        "structure_signals",
                    ],
                )
                writer.writeheader()
                for item in summaries:
                    counts = {
                        section["section_level"]: section["question_count"]
                        for section in item.get("sections", [])
                    }
                    writer.writerow(
                        {
                            "grade": item["grade"],
                            "lecture_no": item["lecture_no"],
                            "lecture_title": item["lecture_title"],
                            "topic_domain": item["topic_domain"],
                            "question_count": item["question_count"],
                            "section_count": item["section_count"],
                            "missing_sections": "|".join(item["missing_sections"]),
                            "interest_count": counts.get("interest", 0),
                            "extension_count": counts.get("extension", 0),
                            "challenge_count": counts.get("challenge", 0),
                            "structure_signals": "|".join(item.get("structure_signals", []) or []),
                        }
                    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract question-level GaoSi guide entries from scanned PDFs.",
    )
    parser.add_argument("--max-pages", type=int, default=0, help="0 means all pages.")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--zoom", type=float, default=1.5)
    parser.add_argument("--model-dir", default="")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--summary-audit", type=Path, default=DEFAULT_SUMMARY_AUDIT_PATH)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Skip topic progression summary outputs.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_dir = _resolve_model_dir(args.model_dir)
    max_pages = args.max_pages if args.max_pages > 0 else None
    lecture_lookup = _load_lecture_lookup()
    entries = extract_question_entries(
        _default_specs(),
        max_pages=max_pages,
        zoom=args.zoom,
        model_dir=model_dir,
        start_page=args.start_page,
        lecture_lookup=lecture_lookup,
        progress_every=max(args.progress_every, 0),
    )
    write_outputs(
        entries,
        output_path=args.output,
        audit_path=args.audit,
        summary_path=None if args.no_summary else args.summary,
        summary_audit_path=None if args.no_summary else args.summary_audit,
    )
    by_book: dict[str, int] = {}
    by_section: dict[str, int] = {}
    lecture_sections: set[tuple[str, str, str]] = set()
    for entry in entries:
        by_book[entry.book_name] = by_book.get(entry.book_name, 0) + 1
        by_section[entry.section_label] = by_section.get(entry.section_label, 0) + 1
        lecture_sections.add((entry.grade, entry.lecture_no, entry.section_label))
    lecture_keys = {(entry.grade, entry.lecture_no) for entry in entries}
    complete_lectures = sum(
        1
        for grade, lecture_no in lecture_keys
        if all((grade, lecture_no, section_label) in lecture_sections for section_label in SECTION_LABELS)
    )
    print(f"wrote {len(entries)} question entries to {args.output}")
    for book_name, count in sorted(by_book.items()):
        print(f"{book_name}: {count}")
    for section_label, count in sorted(by_section.items()):
        print(f"{section_label}: {count}")
    print(f"lectures: {len(lecture_keys)} ({complete_lectures} with all three sections)")
    print(f"audit: {args.audit}")
    if not args.no_summary:
        print(f"summary: {args.summary}")
        print(f"summary audit: {args.summary_audit}")


if __name__ == "__main__":
    main()
