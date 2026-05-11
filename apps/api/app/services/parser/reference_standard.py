"""
人教版 / 高思导引参考体系解析与规则校正。

优先读取 repo 内的 JSON 资源；若资源缺失，再回退解析 Excel。
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET


NAMESPACE = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

DATA_FILE_NAME = "reference_standard_data.json"
GAOSI_PDF_DATA_FILE_NAME = "reference_standard_gaosi_pdf_data.json"
GAOSI_QUESTION_DATA_FILE_NAME = "reference_standard_gaosi_question_data.json"
SCHOOL_PDF_DATA_FILE_NAME = "reference_standard_school_pdf_data.json"
EXTRA_DATA_FILE_NAMES = (
    GAOSI_PDF_DATA_FILE_NAME,
    GAOSI_QUESTION_DATA_FILE_NAME,
    SCHOOL_PDF_DATA_FILE_NAME,
)
GAOSI_QUESTION_SOURCE = "gaosi_question_pdf"
GAOSI_TOPIC_SOURCES = {"gaosi_pdf", "guide"}
GAOSI_SECTION_SUBLEVELS = {
    "interest": "low",
    "extension": "mid",
    "challenge": "high",
    "兴趣篇": "low",
    "拓展篇": "mid",
    "超越篇": "high",
}
GAOSI_SECTION_LABELS = {"兴趣篇", "拓展篇", "超越篇"}
GAOSI_SECTION_LEVEL_LABELS = {
    "interest": "兴趣篇",
    "extension": "拓展篇",
    "challenge": "超越篇",
}
WEAK_MATCH_TERMS = {
    "dim1": {"计算"},
}
SPECIFIC_TERM_MIN_LENGTH = 4
BAND_LABELS = {
    1: "4年级及以前校内课本难度",
    2: "5、6年级校内课本难度",
    3: "4年级及以前高思导引拓展篇及以下难度",
    4: "5、6年级及以前高思导引拓展篇及以下难度 或 七年级及以上校内课本难度",
    5: "高思导引超越篇难度",
}
BAND_ORDER = {label: index for index, label in BAND_LABELS.items()}
OLYMPIAD_SIGNAL_PATTERN = re.compile(
    r"(?:组合计数|容斥|数论|最值|构造|抽屉|染色|同余|质因数|竞赛|奥数|计数|博弈|对称策略|必胜|必败|不变量|奇偶)"
)
DIM4_LEVEL_TO_NUM = {f"L{index}": index for index in range(1, 6)}
DIM4_NUM_TO_LEVEL = {value: key for key, value in DIM4_LEVEL_TO_NUM.items()}
DIM4_REFERENCE_MIN_MATCH_STRENGTH = 2
DIM4_PROFILE_MIN_CONFIDENCE = 0.65
GAOSI_QUESTION_HIGH_SIMILARITY_STRENGTH = 2
GAOSI_QUESTION_EXACT_STRENGTH = 3
GAOSI_QUESTION_TEXT_EXCERPT_LENGTH = 140
DIM5_QUESTION_UNSAFE_FLAGS = {"low_ocr_confidence", "short_question_text"}
DIM5_QUESTION_REVIEW_FLAGS = {"has_diagram", "cross_page_question", "diagram_partial_match"}
DIM5_TOPIC_TERM_MAX_LENGTH = 30
DIM5_GENERIC_TOPIC_TERMS = {
    "位置",
    "找规律",
    "整数",
    "根据",
    "应用题",
    "计算",
    "问题",
    "数学",
    "基础",
    "综合",
}
DIM5_DIRECT_FORMULA_BLOCK_SIGNALS = (
    "直接公式",
    "普通公式",
    "公式代入",
    "直接代入",
    "圆柱圆锥体积比",
    "圆柱和圆锥体积",
    "圆柱与圆锥体积",
    "圆柱体积",
    "圆锥体积",
    "长方形面积",
    "百分数直接应用",
)
DIM5_TOPIC_STRUCTURE_GROUPS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "grazing": {
        "topics": ("牛吃草", "牛吃草问题", "草生长", "增长消耗", "排队检票"),
        "signals": ("生长", "增长", "流进", "增加", "抽干", "水泵", "吃完", "消耗", "每天", "每分钟", "原有"),
    },
    "work_rate": {
        "topics": ("工程问题", "工程", "合作工程", "工作效率", "效率"),
        "signals": ("效率", "合作", "共同", "单独", "完成", "工作量", "工程", "天完成", "小时完成"),
    },
    "travel": {
        "topics": ("行程", "相遇", "追及", "流水行船", "速度"),
        "signals": ("相遇", "追及", "速度变化", "变速", "流水", "相向", "同向", "返回", "同时出发", "同时", "出发"),
    },
    "concentration": {
        "topics": ("浓度", "浓度问题", "溶液", "混合", "盐水"),
        "signals": ("浓度", "溶液", "盐水", "含盐", "加水", "蒸发", "混合", "百分之"),
    },
    "combinatorics": {
        "topics": ("组合计数", "排列组合", "枚举", "计数", "容斥", "选法"),
        "signals": ("选", "选法", "组成", "排列", "分类", "枚举", "情况", "共有", "多少种", "容斥"),
    },
    "number_theory": {
        "topics": ("数论", "整除", "余数", "同余", "质因数", "因数", "倍数", "奇偶"),
        "signals": ("整除", "余数", "同余", "质因数", "因数", "倍数", "奇数", "偶数", "约数"),
    },
    "sequence": {
        "topics": ("数列", "周期数列", "周期", "递推", "数表"),
        "signals": ("数列", "周期", "第", "项", "排列", "余数", "递推", "循环", "第几行", "第几列"),
    },
    "defined_operation": {
        "topics": ("定义新运算", "新运算", "规定运算"),
        "signals": ("定义", "规定", "新运算", "运算符号", "表示"),
    },
    "pigeonhole": {
        "topics": ("抽屉", "抽屉原理"),
        "signals": ("至少", "保证", "放入", "分成", "必有"),
    },
    "game": {
        "topics": ("博弈", "必胜", "必败", "对称策略"),
        "signals": ("甲乙", "轮流", "取", "胜", "败", "策略", "对称", "必胜", "必败"),
    },
    "advanced_geometry": {
        "topics": ("几何割补", "组合图形", "面积关系", "蝴蝶模型", "鸟头", "沙漏", "立体几何"),
        "signals": ("阴影", "面积", "如图", "辅助线", "割补", "重叠", "正方形", "三角形", "圆", "图形", "体积"),
    },
}


@dataclass(frozen=True)
class ReferenceEntry:
    source: str
    sheet_name: str
    category: str
    title: str
    track: str
    grade_hint: str = ""
    note: str = ""
    keywords: Tuple[str, ...] = ()
    grade: str = ""
    book_name: str = ""
    lecture_no: str = ""
    lecture_title: str = ""
    topic_category: str = ""
    section_level: str = ""
    section_label: str = ""
    page_no: str = ""
    question_no: str = ""
    star_level: str = ""
    question_text: str = ""
    has_diagram: bool = False
    ocr_confidence: float = 0.0
    source_pdf: str = ""
    dimension_profiles: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["keywords"] = list(self.keywords)
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "ReferenceEntry":
        try:
            ocr_confidence = float(payload.get("ocr_confidence") or 0.0)
        except (TypeError, ValueError):
            ocr_confidence = 0.0
        raw_profiles = payload.get("dimension_profiles")
        dimension_profiles = dict(raw_profiles) if isinstance(raw_profiles, dict) else {}
        return cls(
            source=str(payload.get("source", "")),
            sheet_name=str(payload.get("sheet_name", "")),
            category=str(payload.get("category", "")),
            title=str(payload.get("title", "")),
            track=str(payload.get("track", "")),
            grade_hint=str(payload.get("grade_hint", "")),
            note=str(payload.get("note", "")),
            keywords=tuple(str(item) for item in payload.get("keywords", []) if str(item).strip()),
            grade=str(payload.get("grade", "")),
            book_name=str(payload.get("book_name", "")),
            lecture_no=str(payload.get("lecture_no", "")),
            lecture_title=str(payload.get("lecture_title", "")),
            topic_category=str(payload.get("topic_category", "")),
            section_level=str(payload.get("section_level", "")),
            section_label=str(payload.get("section_label", "")),
            page_no=str(payload.get("page_no", "")),
            question_no=str(payload.get("question_no", "")),
            star_level=str(payload.get("star_level", "")),
            question_text=str(payload.get("question_text", "")),
            has_diagram=bool(payload.get("has_diagram", False)),
            ocr_confidence=ocr_confidence,
            source_pdf=str(payload.get("source_pdf", "")),
            dimension_profiles=dimension_profiles,
        )


@dataclass
class CalibrationResult:
    matched_entries: List[ReferenceEntry] = field(default_factory=list)
    matched_terms: List[str] = field(default_factory=list)
    strong_terms: List[str] = field(default_factory=list)
    weak_terms: List[str] = field(default_factory=list)
    rule_band: Optional[str] = None
    model_band: str = ""
    final_band: str = ""
    band_source: str = ""
    band_gap: Optional[int] = None
    warning: str = ""
    needs_manual_review: bool = False
    stable: bool = False
    can_override_model: bool = False
    exact_title_hit: bool = False
    exact_title_stable: bool = False
    question_level_match: bool = False
    question_level_match_quality: str = ""
    question_level_match_strength: int = 0
    question_level_match_type: str = ""
    reference_sublevel: str = ""
    topic_match_terms: List[str] = field(default_factory=list)
    structure_match_terms: List[str] = field(default_factory=list)
    match_scope: str = ""
    match_action: str = ""

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["matched_entries"] = [entry.to_dict() for entry in self.matched_entries]
        return payload


def _normalize_text(value: object) -> str:
    text = str(value or "").strip()
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text


def _normalize_match_text(value: object) -> str:
    text = _normalize_text(value)
    text = re.sub(r"[【】\[\]（）()《》<>“”\"'‘’·•,，。；;：:、/\\|]+", "", text)
    return text.lower()


def _compact_terms(*values: object) -> Tuple[str, ...]:
    terms: List[str] = []
    seen: set[str] = set()

    for value in values:
        normalized = _normalize_text(value)
        if not normalized:
            continue

        candidates = [normalized]
        candidates.extend(
            part
            for part in re.split(r"[【】\[\]（）()《》<>“”\"'‘’·•,，。；;：:、/\\|]+", normalized)
            if part
        )

        for candidate in candidates:
            compact = _normalize_match_text(candidate)
            if len(compact) < 2 or compact in seen:
                continue
            seen.add(compact)
            terms.append(compact)

    return tuple(terms)


def _column_index(cell_ref: str) -> int:
    letters = "".join(char for char in cell_ref if char.isalpha())
    value = 0
    for char in letters:
        value = value * 26 + ord(char.upper()) - 64
    return value


def _parse_grade_hint(value: str) -> Optional[int]:
    text = _normalize_text(value)
    if not text:
        return None

    arabic = re.search(r"(\d+)\s*年级", text)
    if arabic:
        return int(arabic.group(1))

    chinese_map = {
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
    chinese = re.search(r"([一二三四五六七八九])年级", text)
    if chinese:
        return chinese_map[chinese.group(1)]

    if "一、二年级" in text or "一二年级" in text:
        return 2
    if "三、四年级" in text or "三四年级" in text:
        return 4
    if "五、六年级" in text or "五六年级" in text:
        return 6
    if "初中" in text:
        return 7
    if "一阶" in text or "二阶" in text:
        return 4
    if "三阶" in text or "四阶" in text:
        return 6
    if "五阶" in text or "六阶" in text:
        return 7
    return None


def _guess_track_from_text(*values: object) -> str:
    combined = _normalize_text(" ".join(str(value or "") for value in values))
    if not combined:
        return ""
    if "超越" in combined:
        return "超越篇"
    if "拓展" in combined:
        return "拓展篇"
    if "兴趣" in combined:
        return "兴趣篇"
    if "竞赛" in combined:
        return "竞赛备考"
    if "经典奥数" in combined or "奥数" in combined:
        return "经典奥数"
    if "导引" in combined or "高思" in combined:
        return "高思导引"
    return ""


def _track_to_band(track: str, grade_hint: str) -> Optional[str]:
    normalized_track = _normalize_text(track)
    grade = _parse_grade_hint(grade_hint)

    if normalized_track == "校内":
        if grade is None or grade <= 4:
            return BAND_LABELS[1]
        if grade <= 6:
            return BAND_LABELS[2]
        return BAND_LABELS[4]

    if normalized_track in {"兴趣篇", "拓展篇", "浅奥", "导引", "高思导引", "拓展"}:
        if grade is None or grade <= 4:
            return BAND_LABELS[3]
        return BAND_LABELS[4]

    if normalized_track in {"超越篇", "超越"}:
        return BAND_LABELS[5]

    if normalized_track in {"普奥", "经典奥数", "竞赛备考", "奥数", "压轴", "压轴题"}:
        if grade is None or grade <= 4:
            return BAND_LABELS[3]
        return BAND_LABELS[4]

    return None


class WorkbookReferenceStandard:
    SHEET_NAMES = {
        "as_tree": "AS体系知识树",
        "guide": "高思导引章节序",
        "school": "校内（人教）-旧",
        "classic": "各年级经典奥数知识",
        "competition": "竞赛备考章节序（2025）",
    }

    DIM_CATEGORY_FILTERS = {
        "dim1": {"计算"},
        "dim5": set(),
    }

    def __init__(
        self,
        workbook_path: Optional[Path] = None,
        data_path: Optional[Path] = None,
        extra_data_paths: Optional[Sequence[Path]] = None,
    ):
        self.data_path = data_path or Path(__file__).with_name(DATA_FILE_NAME)
        if extra_data_paths is not None:
            self.extra_data_paths = list(extra_data_paths)
        elif data_path is None:
            self.extra_data_paths = [Path(__file__).with_name(file_name) for file_name in EXTRA_DATA_FILE_NAMES]
        else:
            self.extra_data_paths = []
        self.workbook_path = workbook_path
        self.entries = self._load_entries()

    @staticmethod
    def _find_reference_workbook() -> Path:
        repo_root = Path(__file__).resolve().parents[5]
        preferred = sorted(repo_root.glob("*.xlsx"))
        for candidate in preferred:
            if "大纲" in candidate.name or "章节" in candidate.name:
                return candidate
        if preferred:
            return preferred[0]
        raise FileNotFoundError("未找到六维评价所需的参考 Excel 工作簿。")

    @staticmethod
    def _load_json_entries(path: Path) -> List[ReferenceEntry]:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        if not isinstance(payload, list):
            return []
        return [
            ReferenceEntry.from_dict(item)
            for item in payload
            if isinstance(item, dict)
        ]

    @staticmethod
    def _dedupe_entries(entries: Iterable[ReferenceEntry]) -> List[ReferenceEntry]:
        deduped: List[ReferenceEntry] = []
        seen: set[tuple[str, str, str, str, str, str, str]] = set()
        for entry in entries:
            key = (
                _normalize_text(entry.source),
                _normalize_text(entry.title),
                _normalize_text(entry.track),
                _normalize_text(entry.grade_hint),
                _normalize_text(entry.lecture_no),
                _normalize_text(entry.question_no),
                _normalize_text(entry.question_text)[:80],
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(entry)
        return deduped

    def _load_extra_json_entries(self) -> List[ReferenceEntry]:
        entries: List[ReferenceEntry] = []
        for path in self.extra_data_paths:
            if not path.exists():
                continue
            entries.extend(self._load_json_entries(path))
        return entries

    def _load_entries(self) -> List[ReferenceEntry]:
        if self.data_path.exists():
            entries = self._load_json_entries(self.data_path)
            entries.extend(self._load_extra_json_entries())
            return self._dedupe_entries(entries)

        if self.workbook_path is None:
            self.workbook_path = self._find_reference_workbook()

        workbook_zip, workbook, rel_map, shared_strings = self._read_workbook_xml()
        try:
            entries: List[ReferenceEntry] = []
            entries.extend(self._parse_as_tree(workbook_zip, workbook, rel_map, shared_strings))
            entries.extend(self._parse_guide(workbook_zip, workbook, rel_map, shared_strings))
            entries.extend(self._parse_school(workbook_zip, workbook, rel_map, shared_strings))
            entries.extend(self._parse_classic(workbook_zip, workbook, rel_map, shared_strings))
            entries.extend(self._parse_competition(workbook_zip, workbook, rel_map, shared_strings))
            entries.extend(self._load_extra_json_entries())
            return self._dedupe_entries(entries)
        finally:
            workbook_zip.close()

    def export_json_resource(self, destination: Optional[Path] = None) -> Path:
        output_path = destination or self.data_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as file:
            json.dump([entry.to_dict() for entry in self.entries], file, ensure_ascii=False, indent=2)
        return output_path

    def _read_workbook_xml(self) -> Tuple[zipfile.ZipFile, ET.Element, Dict[str, str], List[str]]:
        workbook_zip = zipfile.ZipFile(self.workbook_path)
        workbook = ET.fromstring(workbook_zip.read("xl/workbook.xml"))
        rels = ET.fromstring(workbook_zip.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

        shared_strings: List[str] = []
        if "xl/sharedStrings.xml" in workbook_zip.namelist():
            sst_root = ET.fromstring(workbook_zip.read("xl/sharedStrings.xml"))
            for item in sst_root.findall("m:si", NAMESPACE):
                shared_strings.append("".join(text.text or "" for text in item.iterfind(".//m:t", NAMESPACE)))

        return workbook_zip, workbook, rel_map, shared_strings

    @staticmethod
    def _cell_value(cell: ET.Element, shared_strings: Sequence[str]) -> str:
        cell_type = cell.attrib.get("t")
        value = cell.find("m:v", NAMESPACE)
        if value is None:
            inline = cell.find("m:is", NAMESPACE)
            if inline is not None:
                return "".join(text.text or "" for text in inline.iterfind(".//m:t", NAMESPACE))
            return ""
        raw = value.text or ""
        if cell_type == "s" and raw.isdigit():
            return shared_strings[int(raw)]
        return raw

    def _sheet_rows(
        self,
        workbook_zip: zipfile.ZipFile,
        workbook: ET.Element,
        rel_map: Dict[str, str],
        shared_strings: Sequence[str],
        sheet_name: str,
    ) -> List[Dict[int, str]]:
        sheet_xml: Optional[bytes] = None
        for sheet in workbook.find("m:sheets", NAMESPACE):
            if sheet.attrib.get("name") != sheet_name:
                continue
            rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            sheet_xml = workbook_zip.read(f"xl/{rel_map[rid]}")
            break
        if sheet_xml is None:
            return []

        root = ET.fromstring(sheet_xml)
        rows: List[Dict[int, str]] = []
        for row in root.findall(".//m:sheetData/m:row", NAMESPACE):
            row_map: Dict[int, str] = {}
            for cell in row.findall("m:c", NAMESPACE):
                row_map[_column_index(cell.attrib["r"])] = self._cell_value(cell, shared_strings)
            rows.append(row_map)
        return rows

    def _parse_as_tree(
        self,
        workbook_zip: zipfile.ZipFile,
        workbook: ET.Element,
        rel_map: Dict[str, str],
        shared_strings: Sequence[str],
    ) -> List[ReferenceEntry]:
        rows = self._sheet_rows(workbook_zip, workbook, rel_map, shared_strings, self.SHEET_NAMES["as_tree"])
        if len(rows) < 3:
            return []

        header_row = rows[0]
        track_row = rows[1]
        group_starts = [
            column
            for column, value in header_row.items()
            if _normalize_text(value) == "推荐年级" and _normalize_text(header_row.get(column + 1, ""))
        ]

        entries: List[ReferenceEntry] = []
        for group_start in group_starts:
            category = _normalize_text(header_row.get(group_start + 1, ""))
            track_map = {
                group_start + 1: _normalize_text(track_row.get(group_start + 1, "")),
                group_start + 2: _normalize_text(track_row.get(group_start + 2, "")),
                group_start + 3: _normalize_text(track_row.get(group_start + 3, "")),
            }
            current_stage = ""

            for row in rows[2:]:
                if _normalize_text(row.get(group_start, "")):
                    current_stage = _normalize_text(row[group_start])
                for column, track in track_map.items():
                    title = _normalize_text(row.get(column, ""))
                    if not title or not track:
                        continue
                    entries.append(
                        ReferenceEntry(
                            source="as_tree",
                            sheet_name=self.SHEET_NAMES["as_tree"],
                            category=category,
                            title=title,
                            track=track,
                            grade_hint=current_stage,
                            keywords=_compact_terms(category, title, current_stage, track),
                        )
                    )
        return entries

    def _parse_guide(
        self,
        workbook_zip: zipfile.ZipFile,
        workbook: ET.Element,
        rel_map: Dict[str, str],
        shared_strings: Sequence[str],
    ) -> List[ReferenceEntry]:
        rows = self._sheet_rows(workbook_zip, workbook, rel_map, shared_strings, self.SHEET_NAMES["guide"])
        entries: List[ReferenceEntry] = []
        current_grade = ""
        current_module = ""
        current_section = ""
        current_lecture = ""

        for row in rows[1:]:
            current_grade = _normalize_text(row.get(1, "")) or current_grade
            current_lecture = _normalize_text(row.get(2, "")) or current_lecture
            current_module = _normalize_text(row.get(3, "")) or current_module
            current_section = _normalize_text(row.get(5, "")) or current_section
            knowledge_unit = _normalize_text(row.get(6, ""))
            title = knowledge_unit or current_section or current_lecture
            if not title:
                continue

            track = _guess_track_from_text(current_module, current_section, current_lecture, title) or "高思导引"
            entries.append(
                ReferenceEntry(
                    source="guide",
                    sheet_name=self.SHEET_NAMES["guide"],
                    category=current_module,
                    title=title,
                    track=track,
                    grade_hint=current_grade,
                    note=current_lecture,
                    keywords=_compact_terms(current_module, title, current_grade, current_section, current_lecture, track),
                )
            )
        return entries

    def _parse_school(
        self,
        workbook_zip: zipfile.ZipFile,
        workbook: ET.Element,
        rel_map: Dict[str, str],
        shared_strings: Sequence[str],
    ) -> List[ReferenceEntry]:
        rows = self._sheet_rows(workbook_zip, workbook, rel_map, shared_strings, self.SHEET_NAMES["school"])
        entries: List[ReferenceEntry] = []
        current_term = ""
        current_chapter = ""
        current_section = ""

        for row in rows[1:]:
            current_term = _normalize_text(row.get(1, "")) or current_term
            current_chapter = _normalize_text(row.get(2, "")) or current_chapter
            current_section = _normalize_text(row.get(3, "")) or current_section
            unit = _normalize_text(row.get(5, ""))
            difficulty = _normalize_text(row.get(6, ""))
            title = unit or current_section or current_chapter
            if not title:
                continue
            entries.append(
                ReferenceEntry(
                    source="school",
                    sheet_name=self.SHEET_NAMES["school"],
                    category=current_chapter,
                    title=title,
                    track="校内",
                    grade_hint=current_term,
                    note=difficulty,
                    keywords=_compact_terms(current_chapter, current_section, title, current_term, difficulty, "校内"),
                )
            )
        return entries

    def _parse_classic(
        self,
        workbook_zip: zipfile.ZipFile,
        workbook: ET.Element,
        rel_map: Dict[str, str],
        shared_strings: Sequence[str],
    ) -> List[ReferenceEntry]:
        rows = self._sheet_rows(workbook_zip, workbook, rel_map, shared_strings, self.SHEET_NAMES["classic"])
        entries: List[ReferenceEntry] = []
        current_grade = ""

        for row in rows[1:]:
            current_grade = _normalize_text(row.get(1, "")) or current_grade
            title = _normalize_text(row.get(2, ""))
            category = _normalize_text(row.get(3, ""))
            note = _normalize_text(row.get(5, ""))
            if not title:
                continue
            entries.append(
                ReferenceEntry(
                    source="classic",
                    sheet_name=self.SHEET_NAMES["classic"],
                    category=category,
                    title=title,
                    track="经典奥数",
                    grade_hint=current_grade,
                    note=note,
                    keywords=_compact_terms(category, title, current_grade, note, "经典奥数"),
                )
            )
        return entries

    def _parse_competition(
        self,
        workbook_zip: zipfile.ZipFile,
        workbook: ET.Element,
        rel_map: Dict[str, str],
        shared_strings: Sequence[str],
    ) -> List[ReferenceEntry]:
        rows = self._sheet_rows(workbook_zip, workbook, rel_map, shared_strings, self.SHEET_NAMES["competition"])
        if len(rows) < 4:
            return []

        grade_row = rows[0]
        header_row = rows[2]
        group_starts = [
            column
            for column, value in header_row.items()
            if _normalize_text(value) == "模块" and _normalize_text(header_row.get(column + 1, "")) == "章"
        ]

        entries: List[ReferenceEntry] = []
        for group_start in group_starts:
            grade_hint = _normalize_text(grade_row.get(group_start, ""))
            current_module = ""
            current_chapter = ""
            current_section = ""

            for row in rows[3:]:
                current_module = _normalize_text(row.get(group_start, "")) or current_module
                current_chapter = _normalize_text(row.get(group_start + 1, "")) or current_chapter
                current_section = _normalize_text(row.get(group_start + 2, "")) or current_section
                knowledge_unit = _normalize_text(row.get(group_start + 3, ""))
                title = knowledge_unit or current_section or current_chapter
                if not title:
                    continue
                entries.append(
                    ReferenceEntry(
                        source="competition",
                        sheet_name=self.SHEET_NAMES["competition"],
                        category=current_module,
                        title=title,
                        track="竞赛备考",
                        grade_hint=grade_hint,
                        note=current_chapter,
                        keywords=_compact_terms(current_module, current_chapter, current_section, title, grade_hint, "竞赛备考"),
                    )
                )
        return entries

    def _entry_matches_dimension(self, entry: ReferenceEntry, filters: set[str]) -> bool:
        if not filters:
            return True
        haystacks = {
            _normalize_match_text(entry.category),
            _normalize_match_text(entry.title),
            _normalize_match_text(entry.note),
        }
        return any(_normalize_match_text(filter_value) in haystack for haystack in haystacks for filter_value in filters if haystack)

    @staticmethod
    def _has_olympiad_signal(text: str) -> bool:
        return bool(OLYMPIAD_SIGNAL_PATTERN.search(text))

    @staticmethod
    def _split_match_terms(dim_code: str, terms: Sequence[str]) -> Tuple[List[str], List[str]]:
        weak_terms = WEAK_MATCH_TERMS.get(dim_code, set())
        strong: List[str] = []
        weak: List[str] = []

        for term in terms:
            if term in weak_terms:
                weak.append(term)
            else:
                strong.append(term)

        return sorted(dict.fromkeys(strong)), sorted(dict.fromkeys(weak))

    @staticmethod
    def _merge_warning(existing: str, incoming: str) -> str:
        existing = _normalize_text(existing)
        incoming = _normalize_text(incoming)
        if not incoming:
            return existing
        if not existing:
            return incoming
        if incoming in existing:
            return existing
        return f"{existing} {incoming}"

    @staticmethod
    def _dim5_has_specific_anchor(feature: Dict[str, object]) -> bool:
        for key in ("core_knowledge_units", "knowledge_tags"):
            for item in feature.get(key, []) or []:
                if len(_normalize_match_text(item)) >= SPECIFIC_TERM_MIN_LENGTH:
                    return True
        return False

    @staticmethod
    def _dim5_profile(entry: ReferenceEntry) -> Dict[str, object]:
        profiles = entry.dimension_profiles if isinstance(entry.dimension_profiles, dict) else {}
        profile = profiles.get("dim5", {})
        return dict(profile) if isinstance(profile, dict) else {}

    @classmethod
    def _dim5_entry_quality_flags(cls, entry: ReferenceEntry, strength: int = 0) -> set[str]:
        flags: set[str] = set()
        structure = cls._structure_profile(entry)
        for flag in structure.get("quality_flags", []) or []:
            normalized = str(flag or "").strip()
            if normalized:
                flags.add(normalized)
        dim5_profile = cls._dim5_profile(entry)
        for flag in dim5_profile.get("quality_flags", []) or []:
            normalized = str(flag or "").strip()
            if normalized:
                flags.add(normalized)
        if entry.ocr_confidence and entry.ocr_confidence < 0.65:
            flags.add("low_ocr_confidence")
        if entry.has_diagram:
            flags.add("has_diagram")
            if 0 < strength < GAOSI_QUESTION_EXACT_STRENGTH:
                flags.add("diagram_partial_match")
        if len(_normalize_match_text(entry.question_text or entry.title)) < 12:
            flags.add("short_question_text")
        if strength >= GAOSI_QUESTION_EXACT_STRENGTH:
            flags.discard("has_diagram")
            flags.discard("diagram_partial_match")
        return flags

    @classmethod
    def _dim5_entry_has_specific_anchor(
        cls,
        entry: ReferenceEntry,
        matched_terms: Sequence[str] = (),
    ) -> bool:
        profile = cls._dim5_profile(entry)
        for key in ("knowledge_anchor_terms", "core_knowledge_units", "knowledge_tags"):
            for item in profile.get(key, []) or []:
                if len(_normalize_match_text(item)) >= SPECIFIC_TERM_MIN_LENGTH:
                    return True
        for value in (entry.lecture_title, entry.topic_category, entry.title):
            normalized = _normalize_match_text(value)
            if len(normalized) >= SPECIFIC_TERM_MIN_LENGTH:
                return True
        return any(len(_normalize_match_text(term)) >= SPECIFIC_TERM_MIN_LENGTH for term in matched_terms)

    @classmethod
    def _dim5_entry_match_safety_level(cls, entry: ReferenceEntry, strength: int = 0) -> str:
        profile = cls._dim5_profile(entry)
        explicit = str(profile.get("match_safety_level") or "").strip().lower()
        if explicit in {"auto", "review", "unsafe"}:
            return explicit
        flags = cls._dim5_entry_quality_flags(entry, strength)
        if flags & DIM5_QUESTION_UNSAFE_FLAGS:
            return "unsafe"
        if flags & DIM5_QUESTION_REVIEW_FLAGS:
            return "review"
        return "auto"

    @staticmethod
    def _is_gaosi_question_entry(entry: ReferenceEntry) -> bool:
        return _normalize_text(entry.source) == GAOSI_QUESTION_SOURCE

    @staticmethod
    def _is_dim5_gaosi_topic_entry(dim_code: str, entry: ReferenceEntry) -> bool:
        if dim_code != "dim5":
            return False
        source = _normalize_text(entry.source)
        if source not in GAOSI_TOPIC_SOURCES:
            return False
        return not _normalize_text(entry.question_text)

    @staticmethod
    def _is_gaosi_challenge_entry(entry: ReferenceEntry) -> bool:
        section_level = _normalize_text(entry.section_level).lower()
        section_label = _normalize_text(entry.section_label)
        track = _normalize_text(entry.track)
        return section_level == "challenge" or section_label == "超越篇" or track == "超越篇"

    @staticmethod
    def _gaosi_question_quality_allows_dim5_beyond(quality: str) -> bool:
        normalized = {
            part.strip()
            for part in str(quality or "").split(",")
            if part.strip()
        }
        return not normalized or normalized == {"ok"}

    @classmethod
    def _dim5_band_for_entry(cls, entry: ReferenceEntry) -> Optional[str]:
        profile_band = _normalize_text(cls._dim5_profile(entry).get("dim5_reference_band", ""))
        if profile_band in BAND_ORDER:
            return profile_band
        section_level, section_label = cls._gaosi_section_level_and_label(entry)
        if section_level == "challenge" or section_label == "超越篇":
            return BAND_LABELS[5]
        if section_level in {"interest", "extension"} or section_label in {"兴趣篇", "拓展篇"}:
            grade_text = _normalize_text(entry.grade_hint or entry.grade or cls._gaosi_grade_text(entry))
            grade = int(grade_text) if grade_text.isdigit() else _parse_grade_hint(grade_text)
            return BAND_LABELS[3] if grade is None or grade <= 4 else BAND_LABELS[4]
        return _track_to_band(entry.track, entry.grade_hint)

    @staticmethod
    def _dim5_school_entry_has_specific_anchor(
        entry: ReferenceEntry,
        matched_terms: Sequence[str],
        combined_text: str,
    ) -> bool:
        title_key = _normalize_match_text(entry.title)
        if title_key and len(title_key) >= SPECIFIC_TERM_MIN_LENGTH and title_key in combined_text:
            return True
        return any(len(_normalize_match_text(term)) >= SPECIFIC_TERM_MIN_LENGTH for term in matched_terms)

    @classmethod
    def _dim5_has_strong_beyond_signal(
        cls,
        feature: Dict[str, object],
        combined_text: str,
    ) -> bool:
        if feature.get("competition_signal") == "strong":
            return True
        if feature.get("knowledge_integration") == "cross_domain_bridge":
            return True
        if feature.get("novel_definition_dependency") == "strong":
            return True
        return cls._has_olympiad_signal(combined_text)

    @classmethod
    def _dim5_direct_formula_blocked(cls, feature: Dict[str, object], combined_text: str) -> bool:
        if any(signal in combined_text for signal in DIM5_DIRECT_FORMULA_BLOCK_SIGNALS):
            return True
        if "圆柱" in combined_text and "圆锥" in combined_text and "体积比" in combined_text:
            return True
        if "直接" in combined_text and any(term in combined_text for term in ("公式", "百分数", "面积", "体积")):
            return True

        fact_text = _normalize_match_text(
            " ".join(
                str(part or "")
                for part in (
                    feature.get("evidence_summary", ""),
                    " ".join(str(item) for item in feature.get("evidence_tags", []) or []),
                    " ".join(str(item) for item in feature.get("knowledge_tags", []) or []),
                    " ".join(str(item) for item in feature.get("core_knowledge_units", []) or []),
                )
            )
        )
        return any(signal in fact_text for signal in DIM5_DIRECT_FORMULA_BLOCK_SIGNALS)

    @staticmethod
    def _dim5_is_generic_topic_term(term: str) -> bool:
        normalized = _normalize_match_text(term)
        return len(normalized) < 2 or normalized in DIM5_GENERIC_TOPIC_TERMS

    @staticmethod
    def _dim5_is_group_topic_term(term: str) -> bool:
        normalized = _normalize_match_text(term)
        return any(
            normalized == _normalize_match_text(topic)
            for group in DIM5_TOPIC_STRUCTURE_GROUPS.values()
            for topic in group["topics"]
        )

    @classmethod
    def _dim5_canonical_topic_term(
        cls,
        term: str,
        *,
        feature_topic_terms: Sequence[str] = (),
    ) -> str:
        normalized = _normalize_match_text(term)
        if not normalized or cls._dim5_is_generic_topic_term(normalized):
            return ""

        group_hits: List[str] = []
        for group in DIM5_TOPIC_STRUCTURE_GROUPS.values():
            for topic in group["topics"]:
                normalized_topic = _normalize_match_text(topic)
                if (
                    normalized_topic
                    and not cls._dim5_is_generic_topic_term(normalized_topic)
                    and normalized_topic in normalized
                ):
                    group_hits.append(normalized_topic)
        if group_hits:
            feature_related_hits = [
                hit
                for hit in group_hits
                if any(
                    feature_term
                    and len(feature_term) >= 2
                    and (
                        hit == feature_term
                        or hit in feature_term
                        or feature_term in hit
                    )
                    for feature_term in feature_topic_terms
                )
            ]
            if feature_related_hits:
                return max(feature_related_hits, key=len)
            return max(group_hits, key=len)

        feature_hits = [
            feature_term
            for feature_term in feature_topic_terms
            if (
                feature_term
                and len(feature_term) <= DIM5_TOPIC_TERM_MAX_LENGTH
                and not cls._dim5_is_generic_topic_term(feature_term)
                and (
                    feature_term in normalized
                    or normalized in feature_term
                )
            )
        ]
        if feature_hits:
            return max(feature_hits, key=len)

        if len(normalized) <= DIM5_TOPIC_TERM_MAX_LENGTH:
            return normalized
        return ""

    @classmethod
    def _dim5_feature_topic_terms(
        cls,
        feature: Dict[str, object],
        *,
        question_summary: str,
        analysis_facts: Dict[str, object],
    ) -> List[str]:
        terms: List[str] = []
        values: List[object] = [question_summary]
        for key in (
            "knowledge_tags",
            "core_knowledge_units",
            "supporting_knowledge_units",
            "method_tags",
            "canonical_knowledge_point",
            "canonical_alias_hits",
            "canonical_structure_hits",
        ):
            raw_value = feature.get(key, []) or []
            if isinstance(raw_value, list):
                values.extend(raw_value)
            else:
                values.append(raw_value)
        for key in ("core_knowledge_points", "core_methods"):
            values.extend(analysis_facts.get(key, []) or [])
        values.append(analysis_facts.get("core_task", ""))

        for value in values:
            for term in _compact_terms(value):
                if cls._dim5_is_generic_topic_term(term):
                    continue
                if term not in terms:
                    terms.append(term)
        combined = _normalize_match_text(" ".join(str(value or "") for value in values))
        for group in DIM5_TOPIC_STRUCTURE_GROUPS.values():
            for topic in group["topics"]:
                normalized_topic = _normalize_match_text(topic)
                if (
                    normalized_topic
                    and normalized_topic in combined
                    and not cls._dim5_is_generic_topic_term(normalized_topic)
                    and normalized_topic not in terms
                ):
                    terms.append(normalized_topic)
        return terms

    @classmethod
    def _dim5_entry_topic_terms(cls, entry: ReferenceEntry) -> List[str]:
        values: List[object] = [
            entry.title,
            entry.lecture_title,
            entry.topic_category,
            entry.category,
        ]
        values.extend(entry.keywords)
        dim5_profile = cls._dim5_profile(entry)
        for key in ("knowledge_anchor_terms", "core_knowledge_units", "knowledge_tags"):
            values.extend(dim5_profile.get(key, []) or [])

        terms: List[str] = []
        for value in values:
            for term in _compact_terms(value):
                if cls._dim5_is_generic_topic_term(term):
                    continue
                if term not in terms:
                    terms.append(term)
        return terms

    @classmethod
    def _dim5_topic_match_terms(
        cls,
        entry: ReferenceEntry,
        *,
        feature_topic_terms: Sequence[str],
        combined_text: str,
    ) -> List[str]:
        matched: List[str] = []
        entry_terms = cls._dim5_entry_topic_terms(entry)
        feature_terms = list(feature_topic_terms)

        def add_match(term: str) -> None:
            canonical = cls._dim5_canonical_topic_term(
                term,
                feature_topic_terms=feature_terms,
            )
            feature_related = any(
                feature_term
                and len(feature_term) >= 2
                and (
                    canonical == feature_term
                    or canonical in feature_term
                    or feature_term in canonical
                )
                for feature_term in feature_terms
            )
            is_group_topic = cls._dim5_is_group_topic_term(canonical)
            if canonical:
                if not is_group_topic and not feature_related:
                    return
                if is_group_topic and len(canonical) < SPECIFIC_TERM_MIN_LENGTH and not feature_related:
                    return
            if canonical and canonical not in matched:
                matched.append(canonical)

        for entry_term in entry_terms:
            if entry_term in combined_text:
                add_match(entry_term)
                continue
            for feature_term in feature_terms:
                if (
                    entry_term == feature_term
                    or (
                        len(entry_term) >= 2
                        and entry_term in feature_term
                    )
                    or (
                        len(feature_term) >= 2
                        and feature_term in entry_term
                    )
                ):
                    add_match(entry_term)
                    break

        return sorted(dict.fromkeys(matched))

    @classmethod
    def _dim5_structure_match_terms(
        cls,
        *,
        topic_terms: Sequence[str],
        entry: ReferenceEntry,
        combined_text: str,
    ) -> List[str]:
        entry_terms = cls._dim5_entry_topic_terms(entry)
        all_topic_terms = list(dict.fromkeys([*topic_terms, *entry_terms]))
        matched_signals: List[str] = []

        for group in DIM5_TOPIC_STRUCTURE_GROUPS.values():
            topic_hit = any(
                topic in term or term in topic
                for topic in group["topics"]
                for term in all_topic_terms
                if len(term) >= 2
            )
            if not topic_hit:
                continue
            for signal in group["signals"]:
                normalized_signal = _normalize_match_text(signal)
                if normalized_signal and normalized_signal in combined_text:
                    matched_signals.append(signal)

        return list(dict.fromkeys(matched_signals))

    @classmethod
    def _dim5_topic_structure_band_for_entry(cls, entry: ReferenceEntry) -> Optional[str]:
        reference_band = cls._dim5_band_for_entry(entry)
        if reference_band not in BAND_ORDER:
            return None
        if reference_band in {BAND_LABELS[1], BAND_LABELS[2]}:
            return None

        grade_text = _normalize_text(entry.grade or entry.grade_hint or cls._gaosi_grade_text(entry))
        grade = int(grade_text) if grade_text.isdigit() else _parse_grade_hint(grade_text)
        if reference_band == BAND_LABELS[5]:
            return BAND_LABELS[3] if grade is not None and grade <= 4 else BAND_LABELS[4]
        if grade is not None and grade <= 4:
            return BAND_LABELS[3]
        return BAND_LABELS[4] if reference_band == BAND_LABELS[4] else reference_band

    def _dim5_topic_structure_match_candidates(
        self,
        feature: Dict[str, object],
        *,
        question_summary: str,
        analysis_facts: Dict[str, object],
        combined_text: str,
        limit: int = 5,
    ) -> List[Tuple[int, ReferenceEntry, List[str], List[str], str]]:
        feature_topic_terms = self._dim5_feature_topic_terms(
            feature,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
        )
        if not feature_topic_terms:
            return []

        candidates: List[Tuple[int, ReferenceEntry, List[str], List[str], str]] = []
        for entry in self.entries:
            target_band = self._dim5_topic_structure_band_for_entry(entry)
            if not target_band:
                continue
            if self._is_gaosi_question_entry(entry) and self._dim5_entry_match_safety_level(entry) != "auto":
                continue

            topic_terms = self._dim5_topic_match_terms(
                entry,
                feature_topic_terms=feature_topic_terms,
                combined_text=combined_text,
            )
            if not topic_terms:
                continue

            structure_terms = self._dim5_structure_match_terms(
                topic_terms=topic_terms,
                entry=entry,
                combined_text=combined_text,
            )
            if not structure_terms:
                continue

            score = sum(len(term) for term in topic_terms) + sum(len(term) for term in structure_terms)
            title_key = _normalize_match_text(entry.title)
            if title_key and title_key in topic_terms:
                score += max(4, len(title_key))
            if self._is_gaosi_question_entry(entry):
                score += 4
            if entry.track in {"经典奥数", "竞赛备考", "普奥", "奥数"}:
                score += 3
            if self._is_gaosi_challenge_entry(entry):
                score += 1
            candidates.append((score, entry, topic_terms, structure_terms, target_band))

        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[: max(limit, 0)]

    def dim5_topic_structure_candidates(
        self,
        feature: Dict[str, object],
        *,
        question_text: str,
        question_summary: str,
        analysis_facts: Optional[Dict[str, object]] = None,
        limit: int = 5,
    ) -> List[Dict[str, object]]:
        analysis_facts = analysis_facts or {}
        combined_text = self._build_question_match_text(
            feature,
            question_text=question_text,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
        )
        if not combined_text or self._dim5_direct_formula_blocked(feature, combined_text):
            return []

        candidates = self._dim5_topic_structure_match_candidates(
            feature,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
            combined_text=combined_text,
            limit=limit,
        )
        return [
            {
                "source": entry.source,
                "book_name": entry.book_name,
                "grade": entry.grade,
                "grade_hint": entry.grade_hint,
                "lecture_no": entry.lecture_no,
                "lecture_title": entry.lecture_title,
                "topic_category": entry.topic_category,
                "section_level": entry.section_level,
                "section_label": entry.section_label,
                "track": entry.track,
                "title": entry.title,
                "question_no": entry.question_no,
                "page_no": entry.page_no,
                "topic_match_terms": list(topic_terms),
                "structure_match_terms": list(structure_terms),
                "dim5_reference_band": self._dim5_band_for_entry(entry),
                "dim5_topic_structure_band": target_band,
                "match_scope": "topic_structure",
                "match_action": "raise_band",
            }
            for _, entry, topic_terms, structure_terms, target_band in candidates
        ]

    @classmethod
    def _dim5_beyond_question_override_match(
        cls,
        question_level_entries: Sequence[Tuple[int, ReferenceEntry, List[str], int]],
        *,
        feature: Dict[str, object],
        combined_text: str,
    ) -> Optional[Tuple[ReferenceEntry, List[str], int, str, str]]:
        challenge_matches: List[Tuple[ReferenceEntry, List[str], int, str]] = []
        for _, entry, matched_terms, strength in question_level_entries:
            if not cls._is_gaosi_challenge_entry(entry):
                continue
            quality = cls._gaosi_question_match_quality(entry, strength)
            if not cls._gaosi_question_quality_allows_dim5_beyond(quality):
                continue
            challenge_matches.append((entry, matched_terms, strength, quality))

            if strength >= GAOSI_QUESTION_HIGH_SIMILARITY_STRENGTH:
                warning = ""
                if quality != "ok":
                    warning = "题目级高思超越篇参考含图形依赖，按偏召回策略进入超越篇，需人工复核。"
                return entry, matched_terms, strength, quality, warning

        top_challenge_matches = challenge_matches[:5]
        if (
            len(top_challenge_matches) >= 2
            and top_challenge_matches[0][2] == 1
            and cls._dim5_has_strong_beyond_signal(feature, combined_text)
        ):
            entry, matched_terms, strength, quality = top_challenge_matches[0]
            return (
                entry,
                matched_terms,
                strength,
                quality,
                "多个超越篇题目级候选与强竞赛/跨域信号同时出现，按偏召回策略进入超越篇，需人工复核。",
            )

        return None

    @staticmethod
    def _char_ngrams(text: str, size: int) -> set[str]:
        if len(text) < size:
            return {text} if text else set()
        return {text[index : index + size] for index in range(len(text) - size + 1)}

    @classmethod
    def _gaosi_question_match_strength(cls, entry: ReferenceEntry, combined_text: str) -> int:
        """0=no match, 1=partial audit, 2=high similarity, 3=exact/near-exact."""
        reference_text = _normalize_match_text(entry.question_text or entry.title)
        if len(reference_text) < 8:
            return 0

        if reference_text in combined_text:
            return 3

        size = 3 if len(reference_text) >= 18 else 2
        reference_grams = cls._char_ngrams(reference_text, size)
        combined_grams = cls._char_ngrams(combined_text, size)
        if not reference_grams or not combined_grams:
            return 0

        overlap = len(reference_grams & combined_grams)
        ratio = overlap / max(len(reference_grams), 1)
        if ratio >= 0.60 and overlap >= 8:
            return 2
        if ratio >= 0.35 and overlap >= 6:
            return 1
        return 0

    @staticmethod
    def _gaosi_question_match_quality(entry: ReferenceEntry, strength: int) -> str:
        quality_flags = sorted(WorkbookReferenceStandard._dim5_entry_quality_flags(entry, strength))
        return ",".join(quality_flags) if quality_flags else "ok"

    @staticmethod
    def _gaosi_question_match_type(strength: int) -> str:
        if strength >= GAOSI_QUESTION_EXACT_STRENGTH:
            return "exact/near_exact"
        if strength >= GAOSI_QUESTION_HIGH_SIMILARITY_STRENGTH:
            return "high_similarity"
        if strength > 0:
            return "partial/audit_only"
        return "none"

    @classmethod
    def _gaosi_question_auto_correction_allowed(
        cls,
        entry: ReferenceEntry,
        *,
        strength: int,
        quality: str,
        matched_terms: Sequence[str] = (),
    ) -> bool:
        if strength < GAOSI_QUESTION_HIGH_SIMILARITY_STRENGTH:
            return False
        safety_level = cls._dim5_entry_match_safety_level(entry, strength)
        if safety_level != "auto":
            return False
        if quality != "ok":
            return False
        if strength < GAOSI_QUESTION_EXACT_STRENGTH and not cls._dim5_entry_has_specific_anchor(
            entry,
            matched_terms,
        ):
            return False
        return True

    @classmethod
    def _select_dim5_question_override_matches(
        cls,
        matches: Sequence[Tuple[ReferenceEntry, List[str], int]],
    ) -> List[Tuple[ReferenceEntry, List[str], int]]:
        if not matches:
            return []

        exact_matches = [
            item for item in matches if item[2] >= GAOSI_QUESTION_EXACT_STRENGTH
        ]
        if exact_matches:
            top_entry, top_terms, top_strength = exact_matches[0]
            top_band = cls._dim5_band_for_entry(top_entry)
            competing_bands = {
                cls._dim5_band_for_entry(entry)
                for entry, _, _ in exact_matches[:3]
                if cls._dim5_band_for_entry(entry)
            }
            if len(competing_bands) > 1:
                return []
            same_band_exact = [
                item for item in exact_matches if cls._dim5_band_for_entry(item[0]) == top_band
            ]
            return same_band_exact[:3] if top_band else [(top_entry, top_terms, top_strength)]

        high_similarity = [
            item for item in matches if item[2] >= GAOSI_QUESTION_HIGH_SIMILARITY_STRENGTH
        ]
        if not high_similarity:
            return []

        top_band = cls._dim5_band_for_entry(high_similarity[0][0])
        if not top_band:
            return []
        competing_bands = {
            cls._dim5_band_for_entry(entry)
            for entry, _, _ in high_similarity[:3]
            if cls._dim5_band_for_entry(entry)
        }
        if len(competing_bands) > 1:
            return []
        return high_similarity[:3]

    @staticmethod
    def _gaosi_reference_sublevel(entry: ReferenceEntry) -> str:
        profile_sublevel = _normalize_text(
            WorkbookReferenceStandard._dim5_profile(entry).get("dim5_reference_sublevel", "")
        ).lower()
        if profile_sublevel in {"low", "mid", "high"}:
            return profile_sublevel
        label = (
            _normalize_text(entry.section_level)
            or _normalize_text(entry.section_label)
            or _normalize_text(entry.track)
        )
        return GAOSI_SECTION_SUBLEVELS.get(label, "")

    @staticmethod
    def _gaosi_section_level_and_label(entry: ReferenceEntry) -> Tuple[str, str]:
        raw_level = _normalize_text(entry.section_level)
        raw_label = _normalize_text(entry.section_label) or _normalize_text(entry.track)
        if raw_level in GAOSI_SECTION_LEVEL_LABELS:
            return raw_level, GAOSI_SECTION_LEVEL_LABELS[raw_level]
        if raw_label in GAOSI_SECTION_LABELS:
            reverse = {label: level for level, label in GAOSI_SECTION_LEVEL_LABELS.items()}
            return reverse[raw_label], raw_label
        return "", ""

    @staticmethod
    def _gaosi_grade_text(entry: ReferenceEntry) -> str:
        grade = _normalize_text(entry.grade)
        if grade:
            return grade
        grade_no = _parse_grade_hint(entry.grade_hint)
        return str(grade_no) if grade_no is not None else _normalize_text(entry.grade_hint)

    @classmethod
    def _apply_dim5_gaosi_audit_fields(
        cls,
        feature: Dict[str, object],
        calibration: CalibrationResult,
    ) -> None:
        if not calibration.can_override_model or not calibration.matched_entries:
            return

        question_entry = next(
            (entry for entry in calibration.matched_entries if cls._is_gaosi_question_entry(entry)),
            None,
        )
        entry = question_entry or calibration.matched_entries[0]
        source = "question_bank" if question_entry is not None else "knowledge_base"

        grade = cls._gaosi_grade_text(entry)
        section_level, section_label = cls._gaosi_section_level_and_label(entry)
        if calibration.match_scope == "topic_structure" and section_level == "challenge":
            section_level = ""
            section_label = ""
        if grade:
            feature["gaosi_grade"] = grade
        if section_level:
            feature["gaosi_section_level"] = section_level
        if section_label:
            feature["gaosi_section_label"] = section_label
        feature["gaosi_classification_source"] = source

    @staticmethod
    def _safe_float(value: object, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _dim4_profile(entry: ReferenceEntry) -> Dict[str, object]:
        profiles = entry.dimension_profiles if isinstance(entry.dimension_profiles, dict) else {}
        profile = profiles.get("dim4", {})
        return dict(profile) if isinstance(profile, dict) else {}

    @staticmethod
    def _structure_profile(entry: ReferenceEntry) -> Dict[str, object]:
        profiles = entry.dimension_profiles if isinstance(entry.dimension_profiles, dict) else {}
        profile = profiles.get("structure", {})
        return dict(profile) if isinstance(profile, dict) else {}

    @staticmethod
    def _dim4_level_code(value: object) -> str:
        text = str(value or "").strip().upper()
        if text in DIM4_LEVEL_TO_NUM:
            return text
        if text in {"1", "2", "3", "4", "5"}:
            return f"L{text}"
        match = re.search(r"\bL?([1-5])\b", text)
        if match:
            return f"L{match.group(1)}"
        return ""

    @classmethod
    def _dim4_profile_level(cls, profile: Dict[str, object]) -> Tuple[str, int]:
        level_code = cls._dim4_level_code(
            profile.get("reference_level")
            or profile.get("dim4_level")
            or profile.get("level")
        )
        return level_code, DIM4_LEVEL_TO_NUM.get(level_code, 0)

    @staticmethod
    def _profile_auto_calibration_allowed(profile: Dict[str, object]) -> bool:
        raw_value = profile.get("auto_calibration_allowed", True)
        if isinstance(raw_value, str):
            return raw_value.strip().lower() not in {"0", "false", "no", "否"}
        return raw_value is not False

    def _build_question_match_text(
        self,
        feature: Dict[str, object],
        *,
        question_text: str,
        question_summary: str,
        analysis_facts: Optional[Dict[str, object]] = None,
    ) -> str:
        analysis_facts = analysis_facts or {}
        direct_fact_parts = [
            question_summary,
            question_text,
            feature.get("evidence_summary", ""),
            " ".join(str(item) for item in feature.get("knowledge_tags", []) if item),
            " ".join(str(item) for item in feature.get("core_knowledge_units", []) if item),
            " ".join(str(item) for item in feature.get("supporting_knowledge_units", []) if item),
            " ".join(str(item) for item in feature.get("method_tags", []) if item),
            " ".join(str(item) for item in feature.get("evidence_tags", []) if item),
            " ".join(str(item) for item in analysis_facts.get("core_knowledge_points", []) if item),
            " ".join(str(item) for item in analysis_facts.get("core_methods", []) if item),
            " ".join(str(item) for item in analysis_facts.get("visual_elements", []) if item),
            analysis_facts.get("core_task", ""),
        ]
        return _normalize_match_text(" ".join(str(part) for part in direct_fact_parts if part))

    def _gaosi_question_profile_matches(
        self,
        feature: Dict[str, object],
        *,
        question_text: str,
        question_summary: str,
        analysis_facts: Optional[Dict[str, object]] = None,
        profile_key: str = "dim4",
    ) -> List[Tuple[int, ReferenceEntry, int, str, Dict[str, object], List[str]]]:
        combined_text = self._build_question_match_text(
            feature,
            question_text=question_text,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
        )
        if not combined_text:
            return []

        matches: List[Tuple[int, ReferenceEntry, int, str, Dict[str, object], List[str]]] = []
        for entry in self.entries:
            if not self._is_gaosi_question_entry(entry):
                continue
            profiles = entry.dimension_profiles if isinstance(entry.dimension_profiles, dict) else {}
            profile = profiles.get(profile_key, {})
            if not isinstance(profile, dict) or not profile:
                continue
            strength = self._gaosi_question_match_strength(entry, combined_text)
            if strength <= 0:
                continue
            matched_terms = [term for term in entry.keywords if len(term) >= 2 and term in combined_text]
            title_key = _normalize_match_text(entry.title)
            score = strength * 25 + sum(len(term) for term in matched_terms)
            if title_key and title_key in combined_text:
                score += max(4, len(title_key))
            quality = self._gaosi_question_match_quality(entry, strength)
            if profile_key == "dim4":
                quality_flags = {
                    part.strip()
                    for part in str(quality or "").split(",")
                    if part.strip()
                }
                if (
                    quality_flags <= {"has_diagram", "diagram_partial_match"}
                    and "diagram_partial_match" in quality_flags
                ):
                    quality = "diagram_partial_match"
            matches.append((score, entry, strength, quality, dict(profile), matched_terms))

        matches.sort(key=lambda item: item[0], reverse=True)
        return matches

    def gaosi_question_candidates(
        self,
        feature: Dict[str, object],
        *,
        question_text: str,
        question_summary: str,
        analysis_facts: Optional[Dict[str, object]] = None,
        limit: int = 5,
    ) -> List[Dict[str, object]]:
        combined_text = self._build_question_match_text(
            feature,
            question_text=question_text,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
        )
        if not combined_text:
            return []

        candidates: List[Tuple[int, Dict[str, object]]] = []
        for entry in self.entries:
            if not self._is_gaosi_question_entry(entry):
                continue
            strength = self._gaosi_question_match_strength(entry, combined_text)
            if strength <= 0:
                continue

            matched_terms = [term for term in entry.keywords if len(term) >= 2 and term in combined_text]
            title_key = _normalize_match_text(entry.title)
            score = strength * 25 + sum(len(term) for term in matched_terms)
            if title_key and title_key in combined_text:
                score += max(4, len(title_key))
            quality = self._gaosi_question_match_quality(entry, strength)
            dim4_profile = self._dim4_profile(entry)
            dim5_profile = self._dim5_profile(entry)
            profile_confidence = self._safe_float(
                dim4_profile.get("profile_confidence") or dim4_profile.get("confidence"),
                0.0,
            )
            auto_correction_allowed = self._gaosi_question_auto_correction_allowed(
                entry,
                strength=strength,
                quality=quality,
                matched_terms=matched_terms,
            )
            auto_dim4_calibration_allowed = (
                auto_correction_allowed
                and profile_confidence >= DIM4_PROFILE_MIN_CONFIDENCE
                and self._profile_auto_calibration_allowed(dim4_profile)
            )
            candidates.append(
                (
                    score,
                    {
                        "source": entry.source,
                        "book_name": entry.book_name,
                        "grade": entry.grade,
                        "grade_hint": entry.grade_hint,
                        "lecture_no": entry.lecture_no,
                        "lecture_title": entry.lecture_title,
                        "topic_category": entry.topic_category,
                        "section_level": entry.section_level,
                        "section_label": entry.section_label,
                        "track": entry.track,
                        "question_no": entry.question_no,
                        "page_no": entry.page_no,
                        "star_level": entry.star_level,
                        "question_text_excerpt": _normalize_text(entry.question_text)[
                            :GAOSI_QUESTION_TEXT_EXCERPT_LENGTH
                        ],
                        "similarity_strength": strength,
                        "similarity_type": self._gaosi_question_match_type(strength),
                        "match_quality": quality,
                        "matched_terms": list(matched_terms),
                        "ocr_confidence": entry.ocr_confidence,
                        "has_diagram": entry.has_diagram,
                        "auto_correction_allowed": auto_correction_allowed,
                        "auto_dim4_calibration_allowed": auto_dim4_calibration_allowed,
                        "dim5_reference_band": self._dim5_band_for_entry(entry),
                        "dim5_reference_sublevel": self._gaosi_reference_sublevel(entry),
                        "dim5_match_safety_level": self._dim5_entry_match_safety_level(entry, strength),
                        "knowledge_anchor_terms": list(
                            dim5_profile.get("knowledge_anchor_terms", []) or []
                        ),
                        "structure_profile": self._structure_profile(entry),
                        "dim4_profile": dim4_profile,
                        "dim5_profile": dim5_profile,
                    },
                )
            )

        candidates.sort(key=lambda item: item[0], reverse=True)
        return [candidate for _, candidate in candidates[: max(limit, 0)]]

    @staticmethod
    def _reference_match_payload(
        entry: ReferenceEntry,
        *,
        strength: int,
        quality: str,
        matched_terms: Sequence[str],
        profile: Dict[str, object],
    ) -> Dict[str, object]:
        reference_level, _ = WorkbookReferenceStandard._dim4_profile_level(profile)
        return {
            "book_name": entry.book_name,
            "grade": entry.grade,
            "lecture_no": entry.lecture_no,
            "lecture_title": entry.lecture_title,
            "section_level": entry.section_level,
            "section_label": entry.section_label,
            "question_no": entry.question_no,
            "page_no": entry.page_no,
            "star_level": entry.star_level,
            "source_pdf": entry.source_pdf,
            "similarity_strength": strength,
            "similarity_type": WorkbookReferenceStandard._gaosi_question_match_type(strength),
            "match_quality": quality,
            "matched_terms": list(matched_terms),
            "reference_level": reference_level,
            "profile_confidence": WorkbookReferenceStandard._safe_float(
                profile.get("profile_confidence") or profile.get("confidence"),
                0.0,
            ),
            "ocr_confidence": entry.ocr_confidence,
            "has_diagram": entry.has_diagram,
            "question_text_excerpt": _normalize_text(entry.question_text)[:GAOSI_QUESTION_TEXT_EXCERPT_LENGTH],
            "structure_profile": WorkbookReferenceStandard._structure_profile(entry),
        }

    @staticmethod
    def _merge_feature_warning(feature: Dict[str, object], warning: str) -> None:
        merged = WorkbookReferenceStandard._merge_warning(str(feature.get("warning", "")), warning)
        if merged:
            feature["warning"] = merged

    @staticmethod
    def _dim4_current_status_and_level(
        feature: Dict[str, object],
        *,
        question_text: str,
    ) -> Tuple[str, int]:
        try:
            from app.services.scoring.dim4_applicability import evaluate_dim4_applicability
            from app.services.scoring.dim4_innovation import Dim4InnovationScorer

            status_payload = evaluate_dim4_applicability(
                question_text,
                feature,
                llm_confidence=WorkbookReferenceStandard._safe_float(
                    feature.get("applicability_confidence"),
                    0.0,
                ),
            )
            status = str(status_payload.get("status", "")).strip() or "not_applicable"
            if status != "applicable":
                return status, 0

            score = Dim4InnovationScorer().score(feature)
            if not score.applicable:
                return "not_applicable", 0
            return status, int(score.level or 0)
        except Exception:
            return "review", 0

    @classmethod
    def _allow_non_adjacent_override(
        cls,
        dim_code: str,
        feature: Dict[str, object],
        calibration: CalibrationResult,
    ) -> bool:
        if calibration.band_gap in (None, 0, 1):
            return True
        if dim_code != "dim5":
            return calibration.can_override_model
        return calibration.exact_title_hit

    def match_dimension(
        self,
        dim_code: str,
        feature: Dict[str, object],
        *,
        question_text: str,
        question_summary: str,
        analysis_facts: Optional[Dict[str, object]] = None,
    ) -> CalibrationResult:
        result = CalibrationResult()
        filters = self.DIM_CATEGORY_FILTERS.get(dim_code, set())
        analysis_facts = analysis_facts or {}

        direct_fact_parts = [
            question_summary,
            question_text,
            feature.get("evidence_summary", ""),
            " ".join(str(item) for item in feature.get("knowledge_tags", []) if item),
            " ".join(str(item) for item in feature.get("core_knowledge_units", []) if item),
            " ".join(str(item) for item in feature.get("supporting_knowledge_units", []) if item),
            " ".join(str(item) for item in feature.get("method_tags", []) if item),
            " ".join(str(item) for item in feature.get("evidence_tags", []) if item),
            " ".join(str(item) for item in analysis_facts.get("core_knowledge_points", []) if item),
            " ".join(str(item) for item in analysis_facts.get("core_methods", []) if item),
            " ".join(str(item) for item in analysis_facts.get("visual_elements", []) if item),
            analysis_facts.get("core_task", ""),
        ]
        combined_text = _normalize_match_text(" ".join(str(part) for part in direct_fact_parts if part))
        if not combined_text:
            return result
        olympiad_heavy = self._has_olympiad_signal(combined_text)
        direct_formula_blocked = (
            dim_code == "dim5" and self._dim5_direct_formula_blocked(feature, combined_text)
        )
        if direct_formula_blocked:
            result.match_scope = "direct_formula_guard"
            result.match_action = "blocked_by_direct_formula"
        topic_structure_candidates = (
            []
            if dim_code != "dim5" or direct_formula_blocked
            else self._dim5_topic_structure_match_candidates(
                feature,
                question_summary=question_summary,
                analysis_facts=analysis_facts,
                combined_text=combined_text,
                limit=5,
            )
        )

        scored_entries: List[Tuple[int, ReferenceEntry, List[str], int]] = []
        for entry in self.entries:
            if not self._entry_matches_dimension(entry, filters):
                continue

            matched_terms = [term for term in entry.keywords if len(term) >= 2 and term in combined_text]
            question_match_strength = 0
            if self._is_gaosi_question_entry(entry):
                question_match_strength = self._gaosi_question_match_strength(entry, combined_text)
                if question_match_strength <= 0:
                    continue

            if not matched_terms and question_match_strength <= 0:
                continue

            if (
                dim_code == "dim5"
                and olympiad_heavy
                and entry.track == "校内"
                and not self._dim5_school_entry_has_specific_anchor(entry, matched_terms, combined_text)
            ):
                continue

            score = sum(len(term) for term in matched_terms)
            title_key = _normalize_match_text(entry.title)
            if title_key and title_key in combined_text:
                score += max(4, len(title_key))
            if question_match_strength:
                score += question_match_strength * 25
            if entry.track == "校内":
                score += 6
            elif entry.track in {"兴趣篇", "拓展篇", "高思导引"}:
                score += 2
            elif entry.track == "超越篇":
                score += 4 if olympiad_heavy else -3
            elif entry.track in {"经典奥数", "竞赛备考", "普奥", "奥数"}:
                score += 2 if olympiad_heavy else -1
            if self._is_dim5_gaosi_topic_entry(dim_code, entry):
                score -= 4
            scored_entries.append((score, entry, matched_terms, question_match_strength))

        if not scored_entries:
            if topic_structure_candidates:
                _, entry, topic_terms, structure_terms, target_band = topic_structure_candidates[0]
                result.matched_entries = [entry]
                result.matched_terms = list(topic_terms)
                result.strong_terms = list(topic_terms)
                result.rule_band = target_band
                result.stable = True
                result.can_override_model = True
                result.topic_match_terms = list(topic_terms)
                result.structure_match_terms = list(structure_terms)
                result.match_scope = "topic_structure"
                result.match_action = "raise_band"
                if self._is_gaosi_challenge_entry(entry):
                    result.warning = self._merge_warning(
                        result.warning,
                        "仅达到专题+结构命中，未达到题目级超越篇相似；按高思拓展档纠偏并建议复核。",
                    )
                    result.needs_manual_review = True
                return result
            return result

        scored_entries.sort(key=lambda item: item[0], reverse=True)
        top_entries = scored_entries[:5]
        result.matched_entries = [item[1] for item in top_entries]
        result.matched_terms = sorted({term for _, _, terms, _ in top_entries for term in terms})
        result.strong_terms, result.weak_terms = self._split_match_terms(
            dim_code,
            result.matched_terms,
        )

        question_level_entries = [
            item for item in scored_entries if item[3] > 0 and self._is_gaosi_question_entry(item[1])
        ]
        if question_level_entries:
            best_question_entry = question_level_entries[0][1]
            best_question_strength = question_level_entries[0][3]
            best_question_quality = self._gaosi_question_match_quality(
                best_question_entry,
                best_question_strength,
            )
            result.question_level_match = True
            result.question_level_match_quality = best_question_quality
            result.question_level_match_strength = best_question_strength
            result.question_level_match_type = self._gaosi_question_match_type(best_question_strength)
            result.reference_sublevel = self._gaosi_reference_sublevel(best_question_entry)

        vote_entries = question_level_entries[:3] if question_level_entries else top_entries[:3]
        band_votes = [self._dim5_band_for_entry(entry) for _, entry, _, _ in vote_entries]
        band_votes = [vote for vote in band_votes if vote]
        if not band_votes:
            return result

        top_band = band_votes[0]
        stable = band_votes.count(top_band) >= 2 or len(set(band_votes)) == 1
        if not stable and len(top_entries) >= 2:
            stable = top_entries[0][0] >= top_entries[1][0] * 1.25

        exact_matches = [
            (entry, matched_terms, question_match_strength)
            for _, entry, matched_terms, question_match_strength in scored_entries
            if _normalize_match_text(entry.title) and _normalize_match_text(entry.title) in combined_text
            and not self._is_dim5_gaosi_topic_entry(dim_code, entry)
            and not self._is_gaosi_question_entry(entry)
        ]
        exact_question_matches = [
            (entry, matched_terms, question_match_strength)
            for _, entry, matched_terms, question_match_strength in scored_entries
            if question_match_strength >= 2 and self._is_gaosi_question_entry(entry)
        ]
        high_quality_question_matches = [
            (entry, matched_terms, question_match_strength)
            for entry, matched_terms, question_match_strength in exact_question_matches
            if self._gaosi_question_auto_correction_allowed(
                entry,
                strength=question_match_strength,
                quality=self._gaosi_question_match_quality(entry, question_match_strength),
                matched_terms=matched_terms,
            )
        ]
        override_question_matches = (
            self._select_dim5_question_override_matches(high_quality_question_matches)
            if dim_code == "dim5"
            else high_quality_question_matches
        )
        dim5_beyond_question_match = None
        if dim_code == "dim5" and question_level_entries:
            dim5_beyond_question_match = self._dim5_beyond_question_override_match(
                question_level_entries[:5],
                feature=feature,
                combined_text=combined_text,
            )
            if dim5_beyond_question_match:
                beyond_entry, beyond_terms, beyond_strength, beyond_quality, beyond_warning = (
                    dim5_beyond_question_match
                )
                high_quality_question_matches = [
                    (beyond_entry, beyond_terms, beyond_strength),
                    *[
                        item
                        for item in high_quality_question_matches
                        if item[0] != beyond_entry
                    ],
                ]
                override_question_matches = self._select_dim5_question_override_matches(
                    high_quality_question_matches
                )
                result.question_level_match = True
                result.question_level_match_quality = beyond_quality
                result.question_level_match_strength = beyond_strength
                result.question_level_match_type = self._gaosi_question_match_type(beyond_strength)
                result.reference_sublevel = self._gaosi_reference_sublevel(beyond_entry)
                result.matched_entries = [
                    beyond_entry,
                    *[entry for entry in result.matched_entries if entry != beyond_entry],
                ][:5]
                if beyond_warning:
                    result.warning = self._merge_warning(result.warning, beyond_warning)
                    result.needs_manual_review = True
        exact_band_votes = [
            self._dim5_band_for_entry(entry)
            for entry, _, _ in (override_question_matches or exact_matches)
        ]
        exact_band_votes = [vote for vote in exact_band_votes if vote]
        exact_title_hit = bool(exact_band_votes)
        exact_title_stable = len(set(exact_band_votes)) == 1 if exact_band_votes else False
        exact_title_override = exact_title_stable and any(
            _normalize_match_text(entry.title)
            and _normalize_match_text(entry.title) not in WEAK_MATCH_TERMS.get(dim_code, set())
            and (
                dim_code != "dim5"
                or len(_normalize_match_text(entry.title)) >= SPECIFIC_TERM_MIN_LENGTH
            )
            for entry, _, _ in exact_matches
        )
        question_level_override = (
            bool(override_question_matches)
            and bool(exact_band_votes)
        )
        question_level_conflict = (
            bool(high_quality_question_matches) and not override_question_matches and dim_code == "dim5"
        )
        if question_level_conflict:
            result.warning = self._merge_warning(
                result.warning,
                "题目级高思候选存在篇章/档位冲突或安全画像不足，保留为审计线索，不直接纠偏模型档位。",
            )
        result.exact_title_hit = exact_title_hit
        result.exact_title_stable = True if question_level_override else exact_title_stable

        if question_level_override:
            top_band = exact_band_votes[0]
            stable = True
        elif exact_title_override and not olympiad_heavy:
            top_band = min(exact_band_votes, key=lambda band: BAND_ORDER[band])
            stable = exact_title_stable
        elif len(set(band_votes)) > 1 and not olympiad_heavy:
            top_band = min(band_votes, key=lambda band: BAND_ORDER[band])
            stable = False

        topic_structure_match = topic_structure_candidates[0] if topic_structure_candidates else None
        if topic_structure_match and not question_level_override:
            _, topic_entry, topic_terms, structure_terms, topic_band = topic_structure_match
            if (
                BAND_ORDER.get(topic_band, 0) > BAND_ORDER.get(top_band, 0)
                or (
                    self._is_gaosi_challenge_entry(topic_entry)
                    and BAND_ORDER.get(top_band, 0) > BAND_ORDER.get(topic_band, 0)
                )
            ):
                top_band = topic_band
                stable = True
            result.matched_entries = [
                topic_entry,
                *[entry for entry in result.matched_entries if entry != topic_entry],
            ][:5]
            result.matched_terms = sorted(
                dict.fromkeys([*result.matched_terms, *topic_terms])
            )
            result.strong_terms = sorted(dict.fromkeys([*result.strong_terms, *topic_terms]))
            result.topic_match_terms = list(topic_terms)
            result.structure_match_terms = list(structure_terms)
            result.match_scope = "topic_structure"
            result.match_action = "raise_band"
            if self._is_gaosi_challenge_entry(topic_entry):
                result.warning = self._merge_warning(
                    result.warning,
                    "仅达到专题+结构命中，未达到题目级超越篇相似；按高思拓展档纠偏并建议复核。",
                )
                result.needs_manual_review = True

        result.rule_band = top_band
        result.stable = stable
        if False and not stable:
            result.warning = "参考体系匹配到的档位不够稳定，建议人工复核。"
            result.needs_manual_review = True
        specific_strong_hit = any(
            len(term) >= SPECIFIC_TERM_MIN_LENGTH for term in result.strong_terms
        )
        dim5_specific_anchor = dim_code != "dim5" or self._dim5_has_specific_anchor(feature)
        result.can_override_model = question_level_override or exact_title_override or (
            stable and dim5_specific_anchor and (len(result.strong_terms) >= 2 or specific_strong_hit)
        )
        topic_structure_override = bool(topic_structure_match and not question_level_conflict)
        if topic_structure_override:
            result.can_override_model = True
        if result.question_level_match and not question_level_override:
            result.can_override_model = False
            result.warning = self._merge_warning(
                result.warning,
                "题目级高思参考只达到部分相似，保留为审计线索，不直接纠偏模型档位。",
            )
            if topic_structure_override:
                result.can_override_model = True
        if dim_code == "dim5":
            has_topic_only_gaosi = any(
                self._is_dim5_gaosi_topic_entry(dim_code, entry)
                for _, entry, _, _ in scored_entries
            )
            has_non_gaosi_override_source = any(
                not self._is_dim5_gaosi_topic_entry(dim_code, entry)
                for _, entry, _, _ in scored_entries
            )
            if (
                has_topic_only_gaosi
                and not topic_structure_override
                and not result.question_level_match
                and not has_non_gaosi_override_source
            ):
                result.can_override_model = False
                result.warning = self._merge_warning(
                    result.warning,
                    "高思导引仅命中专题/目录，保留为审计线索，不直接判为拓展篇或超越篇。",
                )

        if direct_formula_blocked and result.rule_band not in {BAND_LABELS[1], BAND_LABELS[2]}:
            result.can_override_model = False
            result.match_scope = "direct_formula_guard"
            result.match_action = "blocked_by_direct_formula"
            result.warning = self._merge_warning(
                result.warning,
                "直接公式类题目不因本地库专题或竞赛来源抬高知识广度档位。",
            )

        if result.weak_terms and not result.strong_terms:
            result.warning = self._merge_warning(
                result.warning,
                "参考体系仅命中泛化术语，保留为审计线索，不直接纠偏模型档位。",
            )
        elif result.rule_band and result.strong_terms and not result.can_override_model:
            result.warning = self._merge_warning(
                result.warning,
                "参考体系命中条目但证据不足，保留模型主判。",
            )

        if result.question_level_match and result.question_level_match_quality != "ok":
            result.warning = self._merge_warning(
                result.warning,
                "题目级高思参考命中，但参考题 OCR 置信度或图形依赖不足，当前仅作复核线索。",
            )
            result.needs_manual_review = True
            dim5_beyond_quality_override = (
                dim_code == "dim5"
                and dim5_beyond_question_match is not None
                and self._gaosi_question_quality_allows_dim5_beyond(result.question_level_match_quality)
            )
            if not dim5_beyond_quality_override:
                result.can_override_model = False

        if exact_title_override and not exact_title_stable:
            result.warning = self._merge_warning(
                result.warning,
                "参考体系精确命中多个层级条目，已采用更保守档位，建议人工复核。",
            )
            result.needs_manual_review = True
        elif result.rule_band and not stable and result.strong_terms:
            result.warning = self._merge_warning(
                result.warning,
                "参考体系匹配到的档位不够稳定，建议人工复核。",
            )
            result.needs_manual_review = True
        return result

    def calibrate_dim4_feature(
        self,
        feature: Dict[str, object],
        *,
        question_text: str,
        question_summary: str,
        analysis_facts: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        """Use question-level GaoSi strategy profiles to calibrate dim4 by at most one level."""
        if not isinstance(feature, dict):
            return {}

        calibrated = dict(feature)
        matches = self._gaosi_question_profile_matches(
            calibrated,
            question_text=question_text,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
            profile_key="dim4",
        )
        if not matches:
            return calibrated

        _, entry, strength, quality, profile, matched_terms = matches[0]
        reference_level_code, reference_level = self._dim4_profile_level(profile)
        reference_payload = self._reference_match_payload(
            entry,
            strength=strength,
            quality=quality,
            matched_terms=matched_terms,
            profile=profile,
        )
        profile_confidence = self._safe_float(
            profile.get("profile_confidence") or profile.get("confidence"),
            0.0,
        )

        calibration: Dict[str, object] = {
            "dimension": "dim4",
            "question_level_match": True,
            "reference_match": reference_payload,
            "reference_level": reference_level_code,
            "profile_confidence": profile_confidence,
            "action": "audit_only",
            "calibration_source": "gaosi_question_dim4_profile",
        }

        if strength < DIM4_REFERENCE_MIN_MATCH_STRENGTH:
            calibration["action"] = "audit_only_partial_match"
            calibration["warning"] = "题目级高思参考只达到部分相似，dim4 不做策略画像校准。"
            calibrated["calibration"] = calibration
            return calibrated

        if not reference_level_code:
            calibration["action"] = "audit_only_missing_reference_level"
            calibration["warning"] = "相似高思参考题缺少 dim4 参考档位，当前仅作审计线索。"
            calibrated["calibration"] = calibration
            return calibrated

        unreliable_reasons: List[str] = []
        quality_flags = {
            part.strip()
            for part in str(quality or "").split(",")
            if part.strip()
        }
        diagram_partial_match = "diagram_partial_match" in quality_flags
        if profile_confidence < DIM4_PROFILE_MIN_CONFIDENCE:
            unreliable_reasons.append("profile_low_confidence")
        if entry.ocr_confidence and entry.ocr_confidence < 0.65:
            unreliable_reasons.append("low_ocr_confidence")
        if entry.has_diagram and not diagram_partial_match:
            unreliable_reasons.append("diagram_reference")
        if quality != "ok" and not (quality_flags <= {"diagram_partial_match"}):
            unreliable_reasons.append(quality)
        if not self._profile_auto_calibration_allowed(profile):
            unreliable_reasons.append("profile_disallows_auto_calibration")

        if unreliable_reasons:
            calibration["action"] = "audit_only_unreliable_reference"
            calibration["unreliable_reasons"] = list(dict.fromkeys(unreliable_reasons))
            calibration["warning"] = "相似高思参考题画像置信度、OCR 或图形依赖不足，dim4 不做自动校准。"
            calibrated["calibration"] = calibration
            return calibrated

        current_status, current_level = self._dim4_current_status_and_level(
            calibrated,
            question_text=question_text,
        )
        current_level_code = DIM4_NUM_TO_LEVEL.get(current_level, "")
        calibration["model_status"] = current_status
        calibration["model_level"] = current_level_code

        if current_level:
            level_gap = reference_level - current_level
            calibration["level_gap"] = abs(level_gap)
        else:
            level_gap = 0
            calibration["level_gap"] = None

        if current_level and level_gap < 0:
            calibration["action"] = "audit_only_reference_lower"
            calibration["warning"] = (
                "相似高思参考题 dim4 画像低于当前模型判定，按防虚高策略仅保留审计线索，不下调当前等级。"
            )
            calibrated["calibration"] = calibration
            return calibrated

        if current_level and level_gap == 0:
            calibration["action"] = "reference_confirmed"
        else:
            calibrated["reference_calibrated_level"] = reference_level_code
            calibration["action"] = (
                "calibrated_to_reference_with_review"
                if diagram_partial_match
                else "calibrated_to_reference"
            )
        calibration["final_level"] = reference_level_code

        final_level = str(calibration.get("final_level") or reference_level_code or "").strip()
        if final_level:
            calibrated["knowledge_point"] = (
                entry.lecture_title
                or entry.title
                or entry.topic_category
                or calibrated.get("knowledge_point", "")
            )
            calibrated["topic_level"] = final_level
            calibrated["level_source"] = "question_bank"
            calibrated["anchor_evidence"] = (
                f"题目级高思参考命中 {entry.section_label or entry.track or '参考题'}，"
                f"参考 dim4 等级为 {reference_level_code}。"
            )
            calibrated["reference_matches"] = [reference_payload]
            calibrated["fallback_used"] = False
            if diagram_partial_match:
                calibration["warning"] = self._merge_warning(
                    str(calibration.get("warning") or ""),
                    "题目级高思参考含图形部分匹配，dim4 自动评分结果需要谨慎解读。",
                )
                calibrated["warning"] = self._merge_warning(
                    str(calibrated.get("warning") or ""),
                    str(calibration["warning"]),
                )

        calibrated["calibration"] = calibration
        return calibrated

    def calibrate_feature(
        self,
        dim_code: str,
        feature: Dict[str, object],
        *,
        question_text: str,
        question_summary: str,
        analysis_facts: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        if not isinstance(feature, dict):
            return {}

        calibrated = dict(feature)
        calibration = self.match_dimension(
            dim_code,
            feature,
            question_text=question_text,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
        )

        model_band = _normalize_text(feature.get("band", ""))
        calibration.model_band = model_band

        if (
            dim_code == "dim5"
            and calibration.rule_band
            and calibration.question_level_match
            and calibration.can_override_model
        ):
            if model_band in BAND_ORDER:
                calibration.band_gap = abs(BAND_ORDER[calibration.rule_band] - BAND_ORDER[model_band])
            calibrated["band"] = calibration.rule_band
            calibration.final_band = calibration.rule_band
            calibration.band_source = "question_bank"
        elif (
            dim_code == "dim5"
            and calibration.rule_band
            and calibration.match_scope == "topic_structure"
            and calibration.can_override_model
        ):
            if model_band in BAND_ORDER:
                calibration.band_gap = abs(BAND_ORDER[calibration.rule_band] - BAND_ORDER[model_band])
                should_raise = BAND_ORDER[calibration.rule_band] > BAND_ORDER[model_band]
            else:
                calibration.band_gap = None
                should_raise = True

            if should_raise:
                calibrated["band"] = calibration.rule_band
                calibrated["band_source"] = "topic_structure_match"
                calibration.final_band = calibration.rule_band
                calibration.band_source = "topic_structure_match"
                topic_text = "、".join(calibration.topic_match_terms[:3])
                structure_text = "、".join(calibration.structure_match_terms[:4])
                evidence_note = (
                    f"本地库命中专题：{topic_text}；结构信号：{structure_text}。"
                    if topic_text and structure_text
                    else ""
                )
                if evidence_note:
                    calibrated["evidence_summary"] = self._merge_warning(
                        str(calibrated.get("evidence_summary", "")),
                        evidence_note,
                    )
            else:
                calibration.final_band = model_band
                calibration.band_source = "model_confirmed"
                calibration.match_action = "confirm_model"
        elif calibration.rule_band and model_band in BAND_ORDER:
            calibration.band_gap = abs(BAND_ORDER[calibration.rule_band] - BAND_ORDER[model_band])
            if calibration.band_gap == 0:
                calibration.final_band = model_band
                calibration.band_source = (
                    "model_confirmed"
                    if calibration.can_override_model
                    else (
                        "audit_only"
                        if dim_code == "dim5" and calibration.question_level_match
                        else "model_with_audit"
                    )
                )
            elif calibration.can_override_model and calibration.band_gap == 1:
                calibrated["band"] = calibration.rule_band
                calibration.final_band = calibration.rule_band
                calibration.band_source = "rule_corrected"
            elif calibration.can_override_model and self._allow_non_adjacent_override(
                dim_code,
                feature,
                calibration,
            ):
                calibrated["band"] = calibration.rule_band
                calibrated["warning"] = f"模型主判档位与参考体系相差 {calibration.band_gap} 档，已按参考体系纠偏并标记复核。"
                calibrated["need_manual_review"] = True
                calibration.final_band = calibration.rule_band
                calibration.band_source = "rule_corrected_with_review"
                calibration.needs_manual_review = True
            elif calibration.can_override_model:
                calibration.final_band = model_band
                calibration.band_source = "audit_only"
                calibration.warning = self._merge_warning(
                    calibration.warning,
                    f"参考体系与模型档位相差 {calibration.band_gap} 档，当前仅保留审计线索，不直接跨档纠偏。",
                )
            else:
                calibration.final_band = model_band
                calibration.band_source = "audit_only"
        elif calibration.rule_band:
            if calibration.can_override_model:
                calibrated["band"] = calibration.rule_band
                calibration.final_band = calibration.rule_band
                calibration.band_source = "rule_fallback"
            else:
                calibration.final_band = model_band
                calibration.band_source = "audit_only"
        else:
            calibration.final_band = model_band
            calibration.band_source = "model_only" if model_band else ""

        if not calibration.match_action:
            if calibration.band_source == "audit_only":
                calibration.match_action = "audit_only"
            elif calibration.final_band and model_band and calibration.final_band != model_band:
                calibration.match_action = "raise_band"
            elif calibration.final_band and model_band and calibration.final_band == model_band:
                calibration.match_action = "confirm_model"

        if (
            dim_code == "dim5"
            and calibration.reference_sublevel
            and calibration.can_override_model
        ):
            calibrated["sublevel"] = calibration.reference_sublevel
            calibrated["reference_sublevel_source"] = "gaosi_question_level"

        if dim_code == "dim5":
            self._apply_dim5_gaosi_audit_fields(calibrated, calibration)
            if calibration.band_source == "question_bank":
                calibrated["band_source"] = "question_bank"

        if calibration.warning:
            calibrated["warning"] = self._merge_warning(
                calibrated.get("warning", ""),
                calibration.warning,
            )

        if calibration.needs_manual_review:
            calibrated["need_manual_review"] = True

        calibrated["calibration"] = calibration.to_dict()
        return calibrated


@lru_cache(maxsize=1)
def get_reference_standard() -> WorkbookReferenceStandard:
    return WorkbookReferenceStandard()
