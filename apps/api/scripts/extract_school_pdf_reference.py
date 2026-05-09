from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.parser.reference_standard import (  # noqa: E402
    ReferenceEntry,
    SCHOOL_PDF_DATA_FILE_NAME,
    _compact_terms,
    _normalize_match_text,
)
from scripts.extract_gaosi_pdf_reference import (  # noqa: E402
    _build_ocr_engine,
    _ocr_page,
    _resolve_model_dir,
)


SHEET_NAME = "人教版PDF目录"
DEFAULT_TEXTBOOK_DIR = Path(
    "C:/Users/admin/Desktop/\u8bd5\u5377\u5206\u6790project/\u53c2\u8003\u6559\u6750/\u6821\u5185"
)
DEFAULT_OUTPUT_PATH = (
    ROOT / "app" / "services" / "parser" / SCHOOL_PDF_DATA_FILE_NAME
)
DEFAULT_AUDIT_PATH = ROOT / "data" / "school_pdf_reference_audit.csv"


@dataclass(frozen=True)
class UnitSpec:
    unit_no: str
    title: str
    page: int | None = None
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class BookSpec:
    file_name: str
    grade: int
    semester: str
    units: tuple[UnitSpec, ...]

    @property
    def canonical_name(self) -> str:
        return f"人教版{self.grade}年级数学{self.semester}册"


@dataclass(frozen=True)
class MatchedUnit:
    book: BookSpec
    unit: UnitSpec
    toc_page: int | None
    matched_alias: str
    source_text: str


BOOK_SPECS: tuple[BookSpec, ...] = (
    BookSpec(
        "人教版一年级数学上册电子课本.pdf",
        1,
        "上",
        (
            UnitSpec("1", "准备课", 2),
            UnitSpec("2", "位置", 9),
            UnitSpec("3", "1~5的认识和加减法", 14, ("1~5的认识", "和加减法")),
            UnitSpec("4", "认识图形（一）", 34),
            UnitSpec("5", "6~10的认识和加减法", 39, ("6~10的认识", "和加减法")),
            UnitSpec("6", "11~20各数的认识", 73, ("11~20各数的认识",)),
            UnitSpec("活动", "数学乐园", 82),
            UnitSpec("7", "认识钟表", 84),
            UnitSpec("8", "20以内的进位加法", 88),
            UnitSpec("9", "总复习", 104),
        ),
    ),
    BookSpec(
        "人教版一年级数学下册电子课本.pdf",
        1,
        "下",
        (
            UnitSpec("1", "认识图形（二）", 2),
            UnitSpec("2", "20以内的退位减法", 8),
            UnitSpec("3", "分类与整理", 27),
            UnitSpec("4", "100以内数的认识", 33, ("100以内数的",)),
            UnitSpec("活动", "摆一摆，想一想", 51, ("摆一摆想一想",)),
            UnitSpec("5", "认识人民币", 52),
            UnitSpec("6", "100以内的加法和减法（一）", 61, ("100以内的加法", "和减法（一）")),
            UnitSpec("7", "找规律", 85),
            UnitSpec("8", "总复习", 92),
        ),
    ),
    BookSpec(
        "人教版二年级数学上册电子课本.pdf",
        2,
        "上",
        (
            UnitSpec("1", "长度单位", 2),
            UnitSpec("2", "100以内的加法和减法（二）", 11, ("100以内的加法", "和减法（二）")),
            UnitSpec("3", "角的初步认识", 38),
            UnitSpec("4", "表内乘法（一）", 46),
            UnitSpec("5", "观察物体（一）", 68),
            UnitSpec("6", "表内乘法（二）", 72),
            UnitSpec("活动", "量一量，比一比", 88, ("量一量比一比",)),
            UnitSpec("7", "认识时间", 90),
            UnitSpec("8", "数学广角", 97),
            UnitSpec("9", "总复习", 100),
        ),
    ),
    BookSpec(
        "人教版二年级数学下册电子课本.pdf",
        2,
        "下",
        (
            UnitSpec("1", "数据收集整理", 2),
            UnitSpec("2", "表内除法（一）", 7),
            UnitSpec("3", "图形的运动（一）", 28),
            UnitSpec("4", "表内除法（二）", 38),
            UnitSpec("5", "混合运算", 47),
            UnitSpec("6", "有余数的除法", 59),
            UnitSpec("活动", "小小设计师", 72),
            UnitSpec("7", "万以内数的认识", 74),
            UnitSpec("8", "克和千克", 100),
            UnitSpec("9", "数学广角-推理", 109, ("数学广角推理", "推理")),
            UnitSpec("10", "总复习", 113),
        ),
    ),
    BookSpec(
        "人教版三年级数学上册电子课本.pdf",
        3,
        "上",
        (
            UnitSpec("1", "时、分、秒", 2, ("时分秒",)),
            UnitSpec("2", "万以内的加法和减法（一）", 11, ("万以内的加法", "和减法（一）")),
            UnitSpec("3", "测量", 21),
            UnitSpec("4", "万以内的加法和减法（二）", 36, ("万以内的加法", "和减法（二）")),
            UnitSpec("5", "倍的认识", 50),
            UnitSpec("6", "多位数乘一位数", 56),
            UnitSpec("活动", "数字编码", 77),
            UnitSpec("7", "长方形和正方形", 79),
            UnitSpec("8", "分数的初步认识", 89),
            UnitSpec("9", "数学广角-集合", 104, ("数学广角集合", "集合")),
            UnitSpec("10", "总复习", 108),
        ),
    ),
    BookSpec(
        "人教版三年级数学下册电子课本.pdf",
        3,
        "下",
        (
            UnitSpec("1", "位置与方向（一）", 2),
            UnitSpec("2", "除数是一位数的除法", 11, ("除数是一位数", "的除法")),
            UnitSpec("3", "统计", 36),
            UnitSpec("4", "两位数乘两位数", 41),
            UnitSpec("5", "面积", 60),
            UnitSpec("6", "年、月、日", 76, ("年月日",)),
            UnitSpec("活动", "制作活动日历", 90),
            UnitSpec("7", "小数的初步认识", 91),
            UnitSpec("8", "数学广角", 101),
            UnitSpec("活动", "我们的校园", 106),
            UnitSpec("9", "总复习", 108),
        ),
    ),
    BookSpec(
        "人教版四年级数学上册电子课本.pdf",
        4,
        "上",
        (
            UnitSpec("1", "大数的认识", 2),
            UnitSpec("活动", "1亿有多大", 33),
            UnitSpec("2", "公顷和平方千米", 34),
            UnitSpec("3", "角的度量", 38),
            UnitSpec("4", "三位数乘两位数", 47),
            UnitSpec("5", "平行四边形和梯形", 56),
            UnitSpec("6", "除数是两位数的除法", 71, ("除数是两位数", "的除法")),
            UnitSpec("7", "条形统计图", 94),
            UnitSpec("8", "数学广角-优化", 104, ("数学广角优化", "优化")),
            UnitSpec("9", "总复习", 109),
        ),
    ),
    BookSpec(
        "人教版四年级数学下册电子课本.pdf",
        4,
        "下",
        (
            UnitSpec("1", "四则运算", 2),
            UnitSpec("2", "观察物体（二）", 13),
            UnitSpec("3", "运算定律", 17),
            UnitSpec("4", "小数的意义和性质", 33),
            UnitSpec("5", "三角形", 60),
            UnitSpec("6", "小数的加法和减法", 72),
            UnitSpec("7", "图形的运动（二）", 83),
            UnitSpec("8", "统计", 91),
            UnitSpec("活动", "营养午餐", 102),
            UnitSpec("9", "数学广角", 104),
            UnitSpec("10", "总复习", 109),
        ),
    ),
    BookSpec(
        "人教版五年级数学上册电子课本.pdf",
        5,
        "上",
        (
            UnitSpec("1", "小数乘法", 2),
            UnitSpec("2", "位置", 19),
            UnitSpec("3", "小数除法", 24),
            UnitSpec("4", "可能性", 44),
            UnitSpec("活动", "掷一掷", 50),
            UnitSpec("5", "简易方程", 52),
            UnitSpec("6", "多边形的面积", 86),
            UnitSpec("7", "数学广角-植树问题", 106, ("数学广角植树问题", "植树问题")),
            UnitSpec("8", "总复习", 112),
        ),
    ),
    BookSpec(
        "人教版五年级数学下册电子课本.pdf",
        5,
        "下",
        (
            UnitSpec("1", "观察物体（三）", 2),
            UnitSpec("2", "因数与倍数", 5),
            UnitSpec("3", "长方体和正方体", 18),
            UnitSpec("活动", "探索图形", 44),
            UnitSpec("4", "分数的意义和性质", 45),
            UnitSpec("5", "图形的运动（三）", 83),
            UnitSpec("6", "分数的加法和减法", 89),
            UnitSpec("活动", "打电话", 103),
            UnitSpec("7", "统计", 105),
            UnitSpec("8", "数学广角", 112),
            UnitSpec("9", "总复习", 116),
        ),
    ),
    BookSpec(
        "人教版六年级数学上册电子课本.pdf",
        6,
        "上",
        (
            UnitSpec("1", "分数乘法", 2),
            UnitSpec("2", "位置与方向（二）", 19),
            UnitSpec("3", "分数除法", 28),
            UnitSpec("4", "比", 48),
            UnitSpec("5", "圆", 57),
            UnitSpec("活动", "确定起跑线", 80),
            UnitSpec("6", "百分数（一）", 82, ("百分数",)),
            UnitSpec("7", "扇形统计图", 96),
            UnitSpec("活动", "节约用水", 105),
            UnitSpec("8", "数学广角-数与形", 107, ("数学广角数与形", "数与形")),
            UnitSpec("9", "总复习", 112),
        ),
    ),
    BookSpec(
        "人教版六年级数学下册电子课本.pdf",
        6,
        "下",
        (
            UnitSpec("1", "负数", 2),
            UnitSpec("2", "百分数（二）", 8),
            UnitSpec("活动", "生活与百分数", 16),
            UnitSpec("3", "圆柱与圆锥", 17),
            UnitSpec("4", "比例", 40),
            UnitSpec("活动", "自行车里的数学", 67),
            UnitSpec("5", "数学广角", 68),
            UnitSpec("6", "整理和复习", 72),
            UnitSpec("6.1", "数与代数", 72),
            UnitSpec("6.2", "图形与几何", 86, ("图形与儿何",)),
            UnitSpec("6.3", "统计与概率", 96),
            UnitSpec("6.4", "数学思考", 100),
            UnitSpec("6.5", "综合与实践", 105),
        ),
    ),
)


def _resolve_pdf_path(textbook_dir: Path, file_name: str) -> Path:
    direct = textbook_dir / file_name
    if direct.exists():
        return direct
    matches = sorted(textbook_dir.rglob(file_name))
    return matches[0] if matches else direct


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", _normalize_match_text(value))


def _source_excerpt(tokens: list[str], alias: str, window: int = 6) -> str:
    alias_key = _compact(alias)
    if not alias_key:
        return ""
    compact_tokens = [_compact(token) for token in tokens]
    for start in range(len(tokens)):
        combined = ""
        for end in range(start, min(len(tokens), start + window)):
            combined += compact_tokens[end]
            if alias_key and alias_key in combined:
                left = max(0, start - 2)
                right = min(len(tokens), end + 3)
                return " | ".join(tokens[left:right])
    return ""


def _match_unit(unit: UnitSpec, page_tokens: dict[int, list[str]]) -> tuple[int | None, str, str]:
    aliases = (unit.title, unit.title.replace("-", ""), *unit.aliases)
    for alias in aliases:
        alias_key = _compact(alias)
        if not alias_key:
            continue
        for page_no, tokens in page_tokens.items():
            page_text = _compact("".join(tokens))
            if alias_key in page_text:
                return page_no, alias, _source_excerpt(tokens, alias) or " | ".join(tokens[:20])
    return None, "", ""


def extract_entries(
    specs: Iterable[BookSpec],
    *,
    textbook_dir: Path,
    max_pages: int,
    zoom: float,
    model_dir: Path,
) -> List[MatchedUnit]:
    ocr = _build_ocr_engine(model_dir)
    matched: List[MatchedUnit] = []
    for spec in specs:
        path = _resolve_pdf_path(textbook_dir, spec.file_name)
        if not path.exists():
            raise FileNotFoundError(path)

        with fitz.open(str(path)) as doc:
            page_tokens: dict[int, list[str]] = {}
            page_limit = min(max_pages, doc.page_count)
            for page_index in range(1, page_limit + 1):
                lines = _ocr_page(ocr, doc.load_page(page_index - 1), zoom)
                tokens = [line.text for line in lines if line.text.strip()]
                if tokens:
                    page_tokens[page_index] = tokens

        for unit in spec.units:
            toc_page, alias, source_text = _match_unit(unit, page_tokens)
            matched.append(
                MatchedUnit(
                    book=spec,
                    unit=unit,
                    toc_page=toc_page,
                    matched_alias=alias,
                    source_text=source_text,
                )
            )
    return matched


def _grade_hint(book: BookSpec) -> str:
    return f"{book.grade}年级{book.semester}册"


def _to_reference_entry(entry: MatchedUnit) -> ReferenceEntry:
    grade_hint = _grade_hint(entry.book)
    title_alias = entry.unit.title.replace("-", "")
    note_parts = [
        entry.book.canonical_name,
        f"第{entry.unit.unit_no}单元",
    ]
    if entry.unit.page is not None:
        note_parts.append(f"教材第{entry.unit.page}页")
    if entry.toc_page is not None:
        note_parts.append(f"目录OCR页{entry.toc_page}")
    else:
        note_parts.append("目录OCR未稳定命中，使用内置人教版目录基线")
    return ReferenceEntry(
        source="school_pdf",
        sheet_name=SHEET_NAME,
        category=entry.book.canonical_name,
        title=entry.unit.title,
        track="校内",
        grade_hint=grade_hint,
        note="；".join(note_parts),
        keywords=_compact_terms(
            entry.book.canonical_name,
            entry.unit.title,
            title_alias,
            *entry.unit.aliases,
            grade_hint,
            "校内",
            f"第{entry.unit.unit_no}单元",
        ),
    )


def _dedupe_entries(entries: Iterable[MatchedUnit]) -> List[MatchedUnit]:
    deduped: List[MatchedUnit] = []
    seen: set[tuple[int, str, str, str]] = set()
    for entry in entries:
        key = (entry.book.grade, entry.book.semester, entry.unit.unit_no, entry.unit.title)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def write_outputs(
    entries: List[MatchedUnit],
    *,
    output_path: Path,
    audit_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    reference_entries = [_to_reference_entry(entry).to_dict() for entry in _dedupe_entries(entries)]
    output_path.write_text(
        json.dumps(reference_entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with audit_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "book_name",
                "grade",
                "semester",
                "unit_no",
                "title",
                "textbook_page",
                "toc_ocr_page",
                "matched_alias",
                "matched_in_ocr",
                "source_text",
            ],
        )
        writer.writeheader()
        for entry in entries:
            writer.writerow(
                {
                    "book_name": entry.book.canonical_name,
                    "grade": entry.book.grade,
                    "semester": entry.book.semester,
                    "unit_no": entry.unit.unit_no,
                    "title": entry.unit.title,
                    "textbook_page": entry.unit.page or "",
                    "toc_ocr_page": entry.toc_page or "",
                    "matched_alias": entry.matched_alias,
                    "matched_in_ocr": bool(entry.toc_page),
                    "source_text": re.sub(r"\s+", " ", entry.source_text),
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract PEP school textbook TOC units from scanned PDFs into reference-standard JSON.",
    )
    parser.add_argument("--textbook-dir", type=Path, default=DEFAULT_TEXTBOOK_DIR)
    parser.add_argument("--max-pages", type=int, default=6)
    parser.add_argument("--zoom", type=float, default=1.35)
    parser.add_argument("--model-dir", default="")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_dir = _resolve_model_dir(args.model_dir)
    entries = extract_entries(
        BOOK_SPECS,
        textbook_dir=args.textbook_dir,
        max_pages=args.max_pages,
        zoom=args.zoom,
        model_dir=model_dir,
    )
    write_outputs(entries, output_path=args.output, audit_path=args.audit)

    by_book: dict[str, int] = {}
    matched_count = 0
    for entry in entries:
        by_book[entry.book.canonical_name] = by_book.get(entry.book.canonical_name, 0) + 1
        matched_count += int(entry.toc_page is not None)
    print(f"wrote {len(entries)} entries to {args.output}")
    print(f"ocr matched {matched_count}/{len(entries)} entries")
    for book_name, count in sorted(by_book.items()):
        print(f"{book_name}: {count}")
    print(f"audit: {args.audit}")


if __name__ == "__main__":
    main()
