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
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET


NAMESPACE = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

DATA_FILE_NAME = "reference_standard_data.json"
WEAK_MATCH_TERMS = {
    "dim1": {"计算"},
    "dim2": {"几何"},
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
    r"(?:组合计数|容斥|数论|最值|构造|抽屉|染色|同余|质因数|竞赛|奥数|计数)"
)


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

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["keywords"] = list(self.keywords)
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "ReferenceEntry":
        return cls(
            source=str(payload.get("source", "")),
            sheet_name=str(payload.get("sheet_name", "")),
            category=str(payload.get("category", "")),
            title=str(payload.get("title", "")),
            track=str(payload.get("track", "")),
            grade_hint=str(payload.get("grade_hint", "")),
            note=str(payload.get("note", "")),
            keywords=tuple(str(item) for item in payload.get("keywords", []) if str(item).strip()),
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

    if normalized_track in {"超越篇", "超越", "普奥", "经典奥数", "竞赛备考"}:
        return BAND_LABELS[5]

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
        "dim2": {"几何"},
        "dim5": set(),
    }

    def __init__(self, workbook_path: Optional[Path] = None, data_path: Optional[Path] = None):
        self.data_path = data_path or Path(__file__).with_name(DATA_FILE_NAME)
        self.workbook_path = workbook_path or self._find_reference_workbook()
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

    def _load_entries(self) -> List[ReferenceEntry]:
        if self.data_path.exists():
            with self.data_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
            return [ReferenceEntry.from_dict(item) for item in payload]

        workbook_zip, workbook, rel_map, shared_strings = self._read_workbook_xml()
        try:
            entries: List[ReferenceEntry] = []
            entries.extend(self._parse_as_tree(workbook_zip, workbook, rel_map, shared_strings))
            entries.extend(self._parse_guide(workbook_zip, workbook, rel_map, shared_strings))
            entries.extend(self._parse_school(workbook_zip, workbook, rel_map, shared_strings))
            entries.extend(self._parse_classic(workbook_zip, workbook, rel_map, shared_strings))
            entries.extend(self._parse_competition(workbook_zip, workbook, rel_map, shared_strings))
            return entries
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

        scored_entries: List[Tuple[int, ReferenceEntry, List[str]]] = []
        for entry in self.entries:
            if not self._entry_matches_dimension(entry, filters):
                continue

            matched_terms = [term for term in entry.keywords if len(term) >= 2 and term in combined_text]
            if not matched_terms:
                continue

            score = sum(len(term) for term in matched_terms)
            title_key = _normalize_match_text(entry.title)
            if title_key and title_key in combined_text:
                score += max(4, len(title_key))
            if entry.track == "校内":
                score += 6
            elif entry.track in {"兴趣篇", "拓展篇", "高思导引"}:
                score += 2
            elif entry.track in {"经典奥数", "竞赛备考", "超越篇"}:
                score += 4 if olympiad_heavy else -3
            scored_entries.append((score, entry, matched_terms))

        if not scored_entries:
            return result

        scored_entries.sort(key=lambda item: item[0], reverse=True)
        top_entries = scored_entries[:5]
        result.matched_entries = [item[1] for item in top_entries]
        result.matched_terms = sorted({term for _, _, terms in top_entries for term in terms})
        result.strong_terms, result.weak_terms = self._split_match_terms(
            dim_code,
            result.matched_terms,
        )

        band_votes = [_track_to_band(entry.track, entry.grade_hint) for _, entry, _ in top_entries[:3]]
        band_votes = [vote for vote in band_votes if vote]
        if not band_votes:
            return result

        top_band = band_votes[0]
        stable = band_votes.count(top_band) >= 2 or len(set(band_votes)) == 1
        if not stable and len(top_entries) >= 2:
            stable = top_entries[0][0] >= top_entries[1][0] * 1.25

        exact_matches = [
            (entry, matched_terms)
            for _, entry, matched_terms in scored_entries
            if _normalize_match_text(entry.title) and _normalize_match_text(entry.title) in combined_text
        ]
        exact_band_votes = [_track_to_band(entry.track, entry.grade_hint) for entry, _ in exact_matches]
        exact_band_votes = [vote for vote in exact_band_votes if vote]
        exact_title_hit = bool(exact_band_votes)
        exact_title_override = any(
            _normalize_match_text(entry.title)
            and _normalize_match_text(entry.title) not in WEAK_MATCH_TERMS.get(dim_code, set())
            for entry, _ in exact_matches
        )
        exact_title_stable = len(set(exact_band_votes)) == 1 if exact_band_votes else False

        if exact_title_override and not olympiad_heavy:
            top_band = min(exact_band_votes, key=lambda band: BAND_ORDER[band])
            stable = exact_title_stable
        elif len(set(band_votes)) > 1 and not olympiad_heavy:
            top_band = min(band_votes, key=lambda band: BAND_ORDER[band])
            stable = False

        result.rule_band = top_band
        result.stable = stable
        if False and not stable:
            result.warning = "参考体系匹配到的档位不够稳定，建议人工复核。"
            result.needs_manual_review = True
        specific_strong_hit = any(
            len(term) >= SPECIFIC_TERM_MIN_LENGTH for term in result.strong_terms
        )
        result.can_override_model = exact_title_override or (
            stable and (len(result.strong_terms) >= 2 or specific_strong_hit)
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

        if calibration.rule_band and model_band in BAND_ORDER:
            calibration.band_gap = abs(BAND_ORDER[calibration.rule_band] - BAND_ORDER[model_band])
            if calibration.band_gap == 0:
                calibration.final_band = model_band
                calibration.band_source = (
                    "model_confirmed" if calibration.can_override_model else "model_with_audit"
                )
            elif calibration.can_override_model and calibration.band_gap == 1:
                calibrated["band"] = calibration.rule_band
                calibration.final_band = calibration.rule_band
                calibration.band_source = "rule_corrected"
            elif calibration.can_override_model:
                calibrated["band"] = calibration.rule_band
                calibrated["warning"] = f"模型主判档位与参考体系相差 {calibration.band_gap} 档，已按参考体系纠偏并标记复核。"
                calibrated["need_manual_review"] = True
                calibration.final_band = calibration.rule_band
                calibration.band_source = "rule_corrected_with_review"
                calibration.needs_manual_review = True
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
