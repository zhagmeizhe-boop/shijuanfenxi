from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.parser.reference_standard import BAND_LABELS, get_reference_standard  # noqa: E402


def _load_cases(path: Path | None, question_text: str, question_summary: str) -> list[dict[str, Any]]:
    if path is None:
        return [{"question_text": question_text, "question_summary": question_summary}]

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise ValueError("input must be a JSON object or array")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose dim5 GaoSi question-bank matches for one or more questions.",
    )
    parser.add_argument("--question-text", default="", help="Question text for a single diagnosis.")
    parser.add_argument("--question-summary", default="", help="Optional summary for a single diagnosis.")
    parser.add_argument("--input", type=Path, default=None, help="JSON object/array with question_text fields.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--model-band-index", type=int, default=2, choices=range(1, 6))
    parser.add_argument("--model-sublevel", default="mid", choices=("low", "mid", "high"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = _load_cases(args.input, args.question_text, args.question_summary)
    standard = get_reference_standard()

    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        question_text = str(case.get("question_text") or case.get("text") or "").strip()
        question_summary = str(case.get("question_summary") or case.get("summary") or "").strip()
        if not question_text:
            continue

        feature = {
            "band": BAND_LABELS[args.model_band_index],
            "sublevel": args.model_sublevel,
            "evidence_summary": question_summary,
            "knowledge_tags": case.get("knowledge_tags", []),
            "core_knowledge_units": case.get("core_knowledge_units", []),
        }
        analysis_facts = {
            "core_task": case.get("core_task", ""),
            "core_knowledge_points": case.get("core_knowledge_points", []),
            "core_methods": case.get("core_methods", []),
            "visual_elements": case.get("visual_elements", []),
        }
        question_level_candidates = standard.gaosi_question_candidates(
            feature,
            question_text=question_text,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
            limit=args.limit,
        )
        topic_structure_candidates = (
            standard.dim5_topic_structure_candidates(
                feature,
                question_text=question_text,
                question_summary=question_summary,
                analysis_facts=analysis_facts,
                limit=args.limit,
            )
            if hasattr(standard, "dim5_topic_structure_candidates")
            else []
        )
        calibrated = standard.calibrate_feature(
            "dim5",
            feature,
            question_text=question_text,
            question_summary=question_summary,
            analysis_facts=analysis_facts,
        )
        results.append(
            {
                "index": index,
                "question_summary": question_summary,
                "final_band": calibrated.get("band", ""),
                "final_sublevel": calibrated.get("sublevel", ""),
                "band_source": calibrated.get("band_source")
                or calibrated.get("calibration", {}).get("band_source", ""),
                "final_action": calibrated.get("calibration", {}).get("match_action", ""),
                "match_scope": calibrated.get("calibration", {}).get("match_scope", ""),
                "need_manual_review": bool(calibrated.get("need_manual_review")),
                "calibration": calibrated.get("calibration", {}),
                "question_level_candidates": question_level_candidates,
                "topic_structure_candidates": topic_structure_candidates,
            }
        )

    output = json.dumps(results, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
