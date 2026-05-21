"""Batch diagnostics for Dim5 knowledge graph coverage.

The script is intentionally read-only. It can replay questions from stored
reports or from OCR/text exports, then clusters Dim5 graph failures by
knowledge family instead of listing papers one by one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.parser.dim5_knowledge_graph import (  # noqa: E402
    GENERIC_CONFIRMATION_FACT_KEYS,
    STRONG_OLYMPIAD_FACT_KEYS,
    Dim5KnowledgeGraphMatcher,
)


KNOWLEDGE_FAMILY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("统计图", ("statistics_chart_context", "statistics_percent_conversion", "school_statistics")),
    ("应用题-工程行程经济", ("work_rate_task", "motion_task", "gaosi_travel", "profit_discount", "price_profit_relation")),
    ("应用题-方程总量关系", ("fraction_application", "proportion_application", "two_type_cost_total", "gaosi_chicken_rabbit")),
    ("几何-折叠变换与展开", ("fold_cut_unfold", "geometry_transform_puzzle", "school_cube_net")),
    ("几何-面积模型", ("area_relation_model", "area_ratio_relation", "overlap_area", "tangram_area", "zhao_shuang_diagram")),
    ("几何-圆柱圆弧", ("cylinder_surface_volume", "reuleaux_triangle", "gaosi_circle_sector")),
    ("数论与数字谜", ("gaosi_number_theory", "gaosi_digit_puzzle", "square_difference_odd", "digit_swap_multiple", "integer_solution_factorization")),
    ("构造抽屉概率", ("pigeonhole", "guarantee_at_least", "gaosi_construction", "gaosi_probability")),
    ("递推周期规律", ("gaosi_sequence", "periodic_grid", "state_recurrence", "line_plane_recurrence")),
    ("统筹优化", ("transport_optimization", "gaosi_optimization")),
)


@dataclass
class DiagnosticQuestion:
    source: str
    question_id: str
    paper_name: str
    question_no: str
    question_type: str
    text: str
    stored_applicable_dims: list[str]
    stored_dim5_applicable: bool | None
    stored_dim5_evidence: str
    stored_dim5_details: dict[str, Any]


def _list_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _decode_json_maybe(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _evidence_dim5_details(tag: Any | None) -> dict[str, Any]:
    payload = _decode_json_maybe(getattr(tag, "evidence_text", "") if tag else "")
    if not isinstance(payload, dict):
        return {}
    dim_details = payload.get("dim_details") or payload.get("dimension_details") or {}
    if isinstance(dim_details, dict):
        dim5 = dim_details.get("dim5") or dim_details.get("dim5_knowledge") or {}
        return dim5 if isinstance(dim5, dict) else {}
    return {}


def _question_sort_key(question: DiagnosticQuestion) -> tuple[int, str]:
    match = re.search(r"\d+", str(question.question_no or ""))
    return (int(match.group(0)) if match else 10_000, question.question_no)


async def _load_db_questions(args: argparse.Namespace) -> list[DiagnosticQuestion]:
    if not args.paper_id and not args.paper_name:
        return []
    try:
        from sqlalchemy import or_, select

        from app.core.database import AsyncSessionLocal
        from app.models import DimensionCode, Paper, Question, QuestionDimScore, QuestionTag
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Database diagnostics require the API Python environment with SQLAlchemy installed. "
            "Use --input for OCR/text replay, or run this script inside the API environment."
        ) from exc

    filters = []
    if args.paper_id:
        filters.append(Paper.paper_id.in_(args.paper_id))
    if args.paper_name:
        name_filters = [Paper.paper_name.ilike(f"%{name}%") for name in args.paper_name]
        filters.append(or_(*name_filters))
    if not filters:
        return []

    stmt = (
        select(Paper, Question, QuestionTag, QuestionDimScore)
        .join(Question, Question.paper_id == Paper.paper_id)
        .outerjoin(QuestionTag, QuestionTag.question_id == Question.question_id)
        .outerjoin(
            QuestionDimScore,
            (QuestionDimScore.question_id == Question.question_id)
            & (QuestionDimScore.dim_code == DimensionCode.APPLICATION),
        )
        .where(*filters)
        .order_by(Paper.paper_name, Question.page_no, Question.question_no)
    )
    if args.limit:
        stmt = stmt.limit(args.limit)

    rows: list[DiagnosticQuestion] = []
    async with AsyncSessionLocal() as db:
        result = await db.execute(stmt)
        for paper, question, tag, dim5_row in result.all():
            details = _evidence_dim5_details(tag)
            rows.append(
                DiagnosticQuestion(
                    source="database",
                    question_id=str(question.question_id),
                    paper_name=str(paper.paper_name),
                    question_no=str(question.question_no),
                    question_type=str(getattr(question.question_type, "value", question.question_type) or ""),
                    text=str(question.raw_text or ""),
                    stored_applicable_dims=_list_strings(question.applicable_dims),
                    stored_dim5_applicable=bool(dim5_row.is_applicable) if dim5_row else None,
                    stored_dim5_evidence=str(getattr(dim5_row, "score_evidence", "") or "") if dim5_row else "",
                    stored_dim5_details=details,
                )
            )
    return rows


def _load_text_questions(paths: Iterable[str]) -> list[DiagnosticQuestion]:
    questions: list[DiagnosticQuestion] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            raise FileNotFoundError(path)
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            items = payload if isinstance(payload, list) else payload.get("questions", [])
            for idx, item in enumerate(items, 1):
                if not isinstance(item, dict):
                    continue
                questions.append(
                    DiagnosticQuestion(
                        source=str(path),
                        question_id=str(item.get("question_id") or f"{path.stem}:{idx}"),
                        paper_name=str(item.get("paper_name") or path.stem),
                        question_no=str(item.get("question_no") or idx),
                        question_type=str(item.get("question_type") or "application"),
                        text=str(item.get("raw_text") or item.get("text") or ""),
                        stored_applicable_dims=_list_strings(item.get("applicable_dims")),
                        stored_dim5_applicable=None,
                        stored_dim5_evidence="",
                        stored_dim5_details={},
                    )
                )
            continue
        text = _read_text_or_pdf(path)
        for idx, block in enumerate(_split_question_blocks(text), 1):
            question_no = _guess_question_no(block, idx)
            questions.append(
                DiagnosticQuestion(
                    source=str(path),
                    question_id=f"{path.stem}:{question_no}",
                    paper_name=path.stem,
                    question_no=question_no,
                    question_type="application",
                    text=block,
                    stored_applicable_dims=[],
                    stored_dim5_applicable=None,
                    stored_dim5_evidence="",
                    stored_dim5_details={},
                )
            )
    return questions


def _read_text_or_pdf(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="ignore")
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return ""
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _split_question_blocks(text: str) -> list[str]:
    normalized = "\n".join(line.strip() for line in str(text or "").splitlines())
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    if not normalized:
        return []
    blocks = re.split(r"\n(?=\s*(?:\d+|[一二三四五六七八九十]+)[\.、．）)]\s*)", normalized)
    return [block.strip() for block in blocks if len(block.strip()) >= 8]


def _guess_question_no(block: str, fallback: int) -> str:
    match = re.match(r"\s*((?:\d+|[一二三四五六七八九十]+))", block)
    return match.group(1) if match else str(fallback)


def _fact_keys(match_result: dict[str, Any]) -> set[str]:
    return {
        str(item.get("fact_key") or "")
        for item in match_result.get("dim5_structure_facts") or []
        if isinstance(item, dict) and str(item.get("fact_key") or "")
    }


def _family_for_fact_keys(keys: set[str], match_result: dict[str, Any]) -> str:
    for family, family_keys in KNOWLEDGE_FAMILY_RULES:
        if any(key in keys for key in family_keys):
            return family
    selected = str(match_result.get("knowledge_point_name") or "").strip()
    if selected:
        return selected
    candidates = match_result.get("candidate_knowledge_points") or []
    if candidates and isinstance(candidates[0], dict):
        return str(candidates[0].get("knowledge_point_name") or "未分类")
    return "未分类"


def _confirmed_candidates(match_result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in match_result.get("candidate_knowledge_points") or []
        if isinstance(item, dict) and item.get("candidate_status") == "confirmed_candidate"
    ]


def _has_clear_graph_signal(match_result: dict[str, Any]) -> bool:
    keys = _fact_keys(match_result)
    if not keys:
        return False
    if any(key in STRONG_OLYMPIAD_FACT_KEYS for key in keys):
        return True
    return bool(match_result.get("candidate_knowledge_points"))


def _selected_candidate(match_result: dict[str, Any]) -> dict[str, Any]:
    selected_id = str(match_result.get("selected_candidate_id") or "")
    for candidate in match_result.get("candidate_knowledge_points") or []:
        if isinstance(candidate, dict) and candidate.get("knowledge_point_id") == selected_id:
            return candidate
    return {}


def _has_generic_misfire(match_result: dict[str, Any]) -> bool:
    if match_result.get("confidence_status") != "confirmed":
        return False
    selected = _selected_candidate(match_result)
    matched_keys = set(_list_strings(selected.get("matched_fact_keys")))
    if not matched_keys:
        return False
    return matched_keys <= GENERIC_CONFIRMATION_FACT_KEYS


def _has_confirmed_conflict(match_result: dict[str, Any]) -> bool:
    confirmed = _confirmed_candidates(match_result)
    if len(confirmed) < 2:
        return False
    if match_result.get("confidence_status") == "ambiguous":
        return True
    top_scores = sorted((float(item.get("score") or 0.0) for item in confirmed), reverse=True)
    return len(top_scores) > 1 and top_scores[0] - top_scores[1] < 0.03


def _has_olympiad_demoted_to_school(match_result: dict[str, Any]) -> bool:
    if match_result.get("confidence_status") != "confirmed":
        return False
    if match_result.get("knowledge_track") != "school":
        return False
    return any(key in STRONG_OLYMPIAD_FACT_KEYS for key in _fact_keys(match_result))


def diagnose_questions(questions: list[DiagnosticQuestion]) -> dict[str, Any]:
    matcher = Dim5KnowledgeGraphMatcher()
    clusters: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    rows: list[dict[str, Any]] = []
    for question in sorted(questions, key=_question_sort_key):
        match_result = matcher.match(
            question_text=question.text,
            question_type=question.question_type,
            dim5_feature=question.stored_dim5_details,
        )
        keys = _fact_keys(match_result)
        family = _family_for_fact_keys(keys, match_result)
        categories: list[str] = []
        entered_dim5 = question.stored_dim5_applicable is True or "dim5" in question.stored_applicable_dims
        if not entered_dim5 and _has_clear_graph_signal(match_result):
            categories.append("未进入Dim5但应进入")
        if match_result.get("confidence_status") != "confirmed" and _has_clear_graph_signal(match_result):
            categories.append("图谱未确认具体知识点")
        if _has_generic_misfire(match_result):
            categories.append("命中泛触发词导致误判")
        if _has_confirmed_conflict(match_result):
            categories.append("多个confirmed候选冲突")
        if _has_olympiad_demoted_to_school(match_result):
            categories.append("奥数专题被判成低年级校内基础")
        if not categories:
            continue
        row = {
            "source": question.source,
            "paper_name": question.paper_name,
            "question_no": question.question_no,
            "question_id": question.question_id,
            "family": family,
            "categories": categories,
            "stored_dim5_applicable": question.stored_dim5_applicable,
            "stored_applicable_dims": question.stored_applicable_dims,
            "graph_confidence_status": match_result.get("confidence_status"),
            "graph_failure_reason": match_result.get("failure_reason"),
            "selected": match_result.get("knowledge_display_name") or match_result.get("knowledge_point_name"),
            "fact_keys": sorted(keys),
            "top_candidates": [
                {
                    "name": item.get("knowledge_display_name") or item.get("knowledge_point_name"),
                    "status": item.get("candidate_status"),
                    "score": item.get("score"),
                    "facts": item.get("matched_fact_keys"),
                    "aliases": item.get("matched_aliases"),
                    "blocked_by": item.get("blocked_by_fact_keys"),
                }
                for item in (match_result.get("candidate_knowledge_points") or [])[:5]
                if isinstance(item, dict)
            ],
            "text_excerpt": question.text[:160],
        }
        rows.append(row)
        for category in categories:
            clusters[category][family].append(row)
    return {
        "question_count": len(questions),
        "issue_count": len(rows),
        "clusters": clusters,
        "issues": rows,
    }


def _to_plain_json(payload: Any) -> Any:
    if isinstance(payload, defaultdict):
        return {key: _to_plain_json(value) for key, value in payload.items()}
    if isinstance(payload, dict):
        return {key: _to_plain_json(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_to_plain_json(item) for item in payload]
    return payload


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Dim5 批量诊断",
        "",
        f"- 扫描题数：{payload['question_count']}",
        f"- 问题题数：{payload['issue_count']}",
    ]
    clusters = payload.get("clusters") or {}
    for category, by_family in clusters.items():
        lines.extend(["", f"## {category}"])
        for family, items in by_family.items():
            lines.append(f"- {family}：{len(items)}题")
            for item in items[:8]:
                selected = item.get("selected") or "未确认"
                lines.append(
                    f"  - {item['paper_name']} #{item['question_no']}：{selected}；facts={','.join(item['fact_keys'][:6])}"
                )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose Dim5 graph coverage in batch.")
    parser.add_argument("--paper-id", action="append", help="Paper id to load from database.")
    parser.add_argument("--paper-name", action="append", help="Paper name substring to load from database.")
    parser.add_argument("--input", action="append", default=[], help="OCR/text/JSON/PDF file with question text.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max DB rows.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", help="Write diagnostics to a file instead of stdout.")
    return parser.parse_args()


async def amain() -> int:
    args = parse_args()
    questions = []
    questions.extend(await _load_db_questions(args))
    questions.extend(_load_text_questions(args.input))
    payload = _to_plain_json(diagnose_questions(questions))
    rendered = render_markdown(payload) if args.format == "markdown" else json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)
    return 0


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
