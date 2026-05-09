"""Build a dim5-auditable GaoSi question bank from existing extracted entries.

This is intentionally separate from the OCR extractor. Full OCR over the four
scanned books is slow on a local CPU, while the repository already has a
question-level bank. This script keeps the formal bank untouched and writes a
temporary enriched copy plus audit CSV for review.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.parser.reference_standard import (  # noqa: E402
    GAOSI_QUESTION_DATA_FILE_NAME,
    GAOSI_QUESTION_SOURCE,
    ReferenceEntry,
    _compact_terms,
)
from scripts.extract_gaosi_question_reference import (  # noqa: E402
    QuestionDraft,
    SECTION_LEVELS,
    _build_dim4_profile_skeleton,
    _build_dim5_profile,
    _build_structure_profile,
    _clean_line,
    _entry_topic_category,
    _load_lecture_lookup,
    write_outputs,
)


DEFAULT_INPUT_PATH = ROOT / "app" / "services" / "parser" / GAOSI_QUESTION_DATA_FILE_NAME
DEFAULT_OUTPUT_PATH = ROOT / "data" / "tmp_gaosi_question_reference_dim5.json"
DEFAULT_AUDIT_PATH = ROOT / "data" / "tmp_gaosi_question_reference_dim5_audit.csv"
DEFAULT_SUMMARY_PATH = ROOT / "data" / "tmp_gaosi_topic_progression_dim5.json"
DEFAULT_SUMMARY_AUDIT_PATH = ROOT / "data" / "tmp_gaosi_topic_progression_dim5.csv"


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return default


def _parse_pages(value: object) -> List[int]:
    pages: List[int] = []
    for part in re.split(r"[,，/、\s]+", str(value or "")):
        page = _safe_int(part)
        if page > 0 and page not in pages:
            pages.append(page)
    return pages


def _section_label(entry: ReferenceEntry) -> str:
    if entry.section_label in SECTION_LEVELS:
        return entry.section_label
    for label, level in SECTION_LEVELS.items():
        if entry.section_level == level:
            return label
    if entry.track in SECTION_LEVELS:
        return entry.track
    return next(iter(SECTION_LEVELS))


def _with_dim5_profile(
    entry: ReferenceEntry,
    lecture_lookup: Dict[tuple[int, str], Dict[str, str]],
) -> ReferenceEntry:
    if entry.source != GAOSI_QUESTION_SOURCE:
        return entry

    grade = _safe_int(entry.grade or entry.grade_hint)
    if grade <= 0:
        grade = 6
    lecture_no = str(entry.lecture_no or "").strip()
    lecture_title = _clean_line(entry.lecture_title or entry.title or entry.category)
    topic_category = entry.topic_category or _entry_topic_category(
        grade,
        lecture_no,
        lecture_title,
        lecture_lookup,
    )
    question_text = _clean_line(entry.question_text)
    section_label = _section_label(entry)
    pages = _parse_pages(entry.page_no)
    page_no = pages[0] if pages else _safe_int(entry.page_no, 0)

    draft = QuestionDraft(
        book_name=entry.book_name,
        grade=grade,
        lecture_no=lecture_no,
        lecture_title=lecture_title,
        section_label=section_label,
        page_no=page_no,
        question_no=entry.question_no,
        star_level=entry.star_level,
        source_pdf=entry.source_pdf,
        lines=[question_text],
        confidences=[entry.ocr_confidence or 0.0],
        pages=pages or ([page_no] if page_no else []),
    )
    structure_profile = _build_structure_profile(
        draft,
        topic_category=topic_category,
        question_text=question_text,
    )
    profiles = dict(entry.dimension_profiles) if isinstance(entry.dimension_profiles, dict) else {}
    profiles["structure"] = structure_profile
    profiles.setdefault("dim4", _build_dim4_profile_skeleton(structure_profile))
    profiles["dim5"] = _build_dim5_profile(
        grade=grade,
        lecture_title=lecture_title,
        topic_category=topic_category,
        structure_profile=structure_profile,
    )

    payload = entry.to_dict()
    payload.update(
        {
            "category": topic_category or entry.category,
            "title": lecture_title or entry.title,
            "track": section_label,
            "grade": str(grade),
            "grade_hint": entry.grade_hint or f"{grade}年级",
            "lecture_title": lecture_title,
            "topic_category": topic_category,
            "section_level": SECTION_LEVELS.get(section_label, entry.section_level),
            "section_label": section_label,
            "has_diagram": bool(entry.has_diagram or structure_profile.get("has_diagram")),
            "dimension_profiles": profiles,
            "keywords": _compact_terms(
                lecture_title,
                topic_category,
                section_label,
                entry.grade_hint or f"{grade}年级",
                question_text[:120],
            ),
        }
    )
    return ReferenceEntry.from_dict(payload)


def load_entries(path: Path) -> List[ReferenceEntry]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a list in {path}")
    return [ReferenceEntry.from_dict(item) for item in payload if isinstance(item, dict)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich existing GaoSi question entries with dim5 audit profiles.",
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--summary-audit", type=Path, default=DEFAULT_SUMMARY_AUDIT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    lecture_lookup = _load_lecture_lookup()
    entries = [_with_dim5_profile(entry, lecture_lookup) for entry in load_entries(args.input)]
    write_outputs(
        entries,
        output_path=args.output,
        audit_path=args.audit,
        summary_path=args.summary,
        summary_audit_path=args.summary_audit,
    )
    print(f"wrote {len(entries)} entries to {args.output}")
    print(f"wrote audit to {args.audit}")


if __name__ == "__main__":
    main()
