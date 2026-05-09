from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List

import fitz
import numpy as np
from PIL import Image
from paddleocr import PaddleOCR

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.parser.reference_standard import (  # noqa: E402
    GAOSI_PDF_DATA_FILE_NAME,
    ReferenceEntry,
    _compact_terms,
)


SHEET_NAME = "高思导引PDF目录"
DEFAULT_TEXTBOOK_DIR = Path(
    "C:/Users/admin/Desktop/\u8bd5\u5377\u5206\u6790project/\u53c2\u8003\u6559\u6750"
)
DEFAULT_OUTPUT_PATH = (
    ROOT / "app" / "services" / "parser" / GAOSI_PDF_DATA_FILE_NAME
)
DEFAULT_AUDIT_PATH = ROOT / "data" / "gaosi_pdf_reference_audit.csv"
TRACK_HIGH = "超越篇"
TRACK_GUIDE = "高思导引"
HIGH_TRACK_SIGNALS = ("超越", "竞赛备考", "压轴")
NOISE_TOKENS = {
    "目",
    "目录",
    "参考答案",
    "高思学校竞赛数学导引",
}


@dataclass(frozen=True)
class PdfSpec:
    path: Path
    grade: int
    canonical_name: str


@dataclass
class OcrLine:
    text: str
    confidence: float
    left: float
    top: float


@dataclass
class TocEntry:
    book_name: str
    grade: int
    page_index: int
    lecture_no: str
    title: str
    category: str
    related_lecture: str
    source_text: str


def _default_specs() -> List[PdfSpec]:
    def textbook_path(file_name: str) -> Path:
        direct = DEFAULT_TEXTBOOK_DIR / file_name
        if direct.exists():
            return direct
        olympiad = DEFAULT_TEXTBOOK_DIR / "奥数" / file_name
        if olympiad.exists():
            return olympiad
        matches = sorted(DEFAULT_TEXTBOOK_DIR.rglob(file_name))
        return matches[0] if matches else direct

    return [
        PdfSpec(
            textbook_path("竟赛数学导引 三年级.pdf"),
            3,
            "竞赛数学导引 三年级",
        ),
        PdfSpec(
            textbook_path("竟赛数学导引 四年级.pdf"),
            4,
            "竞赛数学导引 四年级",
        ),
        PdfSpec(
            textbook_path("竞赛数学导引 五年级.pdf"),
            5,
            "竞赛数学导引 五年级",
        ),
        PdfSpec(
            textbook_path("竞赛数学导引 六年级.pdf"),
            6,
            "竞赛数学导引 六年级",
        ),
    ]


def _resolve_model_dir(value: str | None) -> Path:
    if value:
        return Path(value)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "math-report" / "paddleocr"
    return ROOT / "data" / "paddleocr"


def _build_ocr_engine(model_dir: Path) -> PaddleOCR:
    os.environ.setdefault("PADDLE_HOME", str(model_dir))
    os.environ.setdefault("PADDLEOCR_HOME", str(model_dir))
    return PaddleOCR(
        use_angle_cls=True,
        lang="ch",
        use_gpu=False,
        show_log=False,
        det_model_dir=str(model_dir / "det"),
        rec_model_dir=str(model_dir / "rec"),
        cls_model_dir=str(model_dir / "cls"),
    )


def _render_page(page: fitz.Page, zoom: float) -> np.ndarray:
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
    return np.asarray(image)


def _extract_page_entries(raw_result: Any) -> Iterable[Any]:
    if not isinstance(raw_result, list):
        return []
    if (
        len(raw_result) == 1
        and isinstance(raw_result[0], list)
        and raw_result[0]
        and isinstance(raw_result[0][0], (list, tuple))
    ):
        return raw_result[0]
    return raw_result


def _ocr_page(ocr: PaddleOCR, page: fitz.Page, zoom: float) -> List[OcrLine]:
    raw_result = ocr.ocr(_render_page(page, zoom), cls=True)
    lines: List[OcrLine] = []
    for entry in _extract_page_entries(raw_result):
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        box, recognition = entry[0], entry[1]
        if not box or not recognition:
            continue
        text = str(recognition[0]).strip()
        if not text:
            continue
        try:
            confidence = float(recognition[1])
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.45:
            continue
        try:
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
        except (TypeError, ValueError, IndexError):
            xs = [0.0]
            ys = [0.0]
        lines.append(
            OcrLine(
                text=text,
                confidence=confidence,
                left=min(xs),
                top=min(ys),
            )
        )
    return _sort_reading_order(lines)


def _sort_reading_order(lines: List[OcrLine], *, row_tolerance: float = 14.0) -> List[OcrLine]:
    rows: List[List[OcrLine]] = []
    for line in sorted(lines, key=lambda item: item.top):
        if not rows or abs(rows[-1][0].top - line.top) > row_tolerance:
            rows.append([line])
        else:
            rows[-1].append(line)

    ordered: List[OcrLine] = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda item: item.left))
    return ordered


def _normalize_token(text: str) -> str:
    text = str(text or "").strip()
    text = text.replace("．", ".").replace("·", "")
    text = re.sub(r"\s+", "", text)
    return text


def _is_noise_token(token: str) -> bool:
    token = _normalize_token(token)
    if not token:
        return True
    if token in NOISE_TOKENS:
        return True
    if token.startswith("高思学校竞赛数学导引"):
        return True
    if re.fullmatch(r"[.。·…\-_—:：+]+", token):
        return True
    if re.fullmatch(r"\d+\(?答?\d*\)?", token):
        return True
    if re.fullmatch(r"[（(]?答\d+[)）]?", token):
        return True
    return False


def _is_toc_page(tokens: List[str]) -> bool:
    lecture_count = sum(1 for token in tokens if re.search(r"第\s*\d+\s*讲", token))
    has_toc = any("目录" in token for token in tokens)
    has_answer = any("参考答案" in token for token in tokens)
    return has_toc or lecture_count >= 2 or (lecture_count >= 1 and has_answer)


def _extract_category(token: str) -> tuple[str, str]:
    normalized = _normalize_token(token).strip("()（）")
    match = re.search(r"(.+?问题)?第\s*(\d+)\s*讲", normalized)
    if not match:
        return "", ""
    return (match.group(1) or "").strip(), match.group(2)


def _toc_entries_from_tokens(
    *,
    spec: PdfSpec,
    page_index: int,
    tokens: List[str],
) -> List[TocEntry]:
    if not _is_toc_page(tokens):
        return []

    entries: List[TocEntry] = []
    i = 0
    while i < len(tokens):
        token = _normalize_token(tokens[i])
        match = re.match(r"第\s*(\d+)\s*讲(.*)", token)
        if not match:
            i += 1
            continue

        lecture_no = match.group(1)
        title = match.group(2).strip()
        category = ""
        related_lecture = ""
        consumed: List[str] = [tokens[i]]
        i += 1

        if not title:
            while i < len(tokens):
                candidate = _normalize_token(tokens[i])
                consumed.append(tokens[i])
                i += 1
                if _is_noise_token(candidate):
                    continue
                if re.match(r"第\s*\d+\s*讲", candidate):
                    i -= 1
                    consumed.pop()
                    break
                if "参考答案" in candidate:
                    break
                if "问题第" in candidate:
                    category, related_lecture = _extract_category(candidate)
                    continue
                title = candidate
                break

        while i < len(tokens):
            candidate = _normalize_token(tokens[i])
            if re.match(r"第\s*\d+\s*讲", candidate):
                break
            consumed.append(tokens[i])
            i += 1
            if "问题第" in candidate:
                category, related_lecture = _extract_category(candidate)
                continue
            if "参考答案" in candidate:
                break
            if not title and not _is_noise_token(candidate):
                title = candidate

        title = _clean_title(title)
        if title:
            entries.append(
                TocEntry(
                    book_name=spec.canonical_name,
                    grade=spec.grade,
                    page_index=page_index,
                    lecture_no=lecture_no,
                    title=title,
                    category=category,
                    related_lecture=related_lecture,
                    source_text=" | ".join(consumed),
                )
            )
    return entries


def _clean_title(value: str) -> str:
    value = _normalize_token(value)
    value = re.sub(r"[.。·…_—-]+$", "", value)
    value = re.sub(r"^\W+", "", value)
    value = re.sub(r"\W+$", "", value)
    return value


def _track_for_entry(entry: TocEntry) -> str:
    combined = f"{entry.title} {entry.category} {entry.source_text}"
    if any(signal in combined for signal in HIGH_TRACK_SIGNALS):
        return TRACK_HIGH
    return TRACK_GUIDE


def _grade_hint(grade: int) -> str:
    return f"{grade}年级"


def _to_reference_entry(entry: TocEntry) -> ReferenceEntry:
    grade_hint = _grade_hint(entry.grade)
    track = _track_for_entry(entry)
    note_parts = [
        entry.book_name,
        f"第{entry.lecture_no}讲",
        f"目录OCR页{entry.page_index}",
    ]
    if entry.related_lecture:
        note_parts.append(f"体系第{entry.related_lecture}讲")
    note = "；".join(note_parts)
    return ReferenceEntry(
        source="gaosi_pdf",
        sheet_name=SHEET_NAME,
        category=entry.category,
        title=entry.title,
        track=track,
        grade_hint=grade_hint,
        note=note,
        keywords=_compact_terms(
            entry.category,
            entry.title,
            grade_hint,
            track,
            f"第{entry.lecture_no}讲",
        ),
    )


def _dedupe_entries(entries: Iterable[TocEntry]) -> List[TocEntry]:
    deduped: List[TocEntry] = []
    seen: set[tuple[int, str, str]] = set()
    for entry in entries:
        key = (entry.grade, entry.lecture_no, entry.title)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def extract_entries(
    specs: Iterable[PdfSpec],
    *,
    max_pages: int,
    zoom: float,
    model_dir: Path,
) -> List[TocEntry]:
    ocr = _build_ocr_engine(model_dir)
    entries: List[TocEntry] = []
    for spec in specs:
        if not spec.path.exists():
            raise FileNotFoundError(spec.path)
        with fitz.open(str(spec.path)) as doc:
            page_limit = min(max_pages, doc.page_count)
            book_entries: List[TocEntry] = []
            found_toc = False
            for page_index in range(1, page_limit + 1):
                page = doc.load_page(page_index - 1)
                tokens = [line.text for line in _ocr_page(ocr, page, zoom)]
                page_entries = _toc_entries_from_tokens(
                    spec=spec,
                    page_index=page_index,
                    tokens=tokens,
                )
                if page_entries:
                    found_toc = True
                    book_entries.extend(page_entries)
                elif found_toc and len({entry.lecture_no for entry in book_entries}) >= 20:
                    break
                if len({entry.lecture_no for entry in book_entries}) >= 24:
                    break
            entries.extend(_dedupe_entries(book_entries))
    return _dedupe_entries(entries)


def write_outputs(
    entries: List[TocEntry],
    *,
    output_path: Path,
    audit_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    reference_entries = [_to_reference_entry(entry).to_dict() for entry in entries]
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
                "toc_page",
                "lecture_no",
                "title",
                "category",
                "related_lecture",
                "track",
                "source_text",
            ],
        )
        writer.writeheader()
        for entry in entries:
            writer.writerow(
                {
                    "book_name": entry.book_name,
                    "grade": entry.grade,
                    "toc_page": entry.page_index,
                    "lecture_no": entry.lecture_no,
                    "title": entry.title,
                    "category": entry.category,
                    "related_lecture": entry.related_lecture,
                    "track": _track_for_entry(entry),
                    "source_text": entry.source_text,
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract GaoSi guide TOC entries from scanned PDFs into reference-standard JSON.",
    )
    parser.add_argument("--max-pages", type=int, default=30)
    parser.add_argument("--zoom", type=float, default=1.5)
    parser.add_argument("--model-dir", default="")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_dir = _resolve_model_dir(args.model_dir)
    entries = extract_entries(
        _default_specs(),
        max_pages=args.max_pages,
        zoom=args.zoom,
        model_dir=model_dir,
    )
    write_outputs(entries, output_path=args.output, audit_path=args.audit)
    by_book: dict[str, int] = {}
    for entry in entries:
        by_book[entry.book_name] = by_book.get(entry.book_name, 0) + 1
    print(f"wrote {len(entries)} entries to {args.output}")
    for book_name, count in sorted(by_book.items()):
        print(f"{book_name}: {count}")
    print(f"audit: {args.audit}")


if __name__ == "__main__":
    main()
