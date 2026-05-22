"""Localize Dim5 graph rule descriptions without changing structure keys.

The online matcher uses English structure keys such as ``geometry_circle``.
This script rewrites only human/LLM-facing rule descriptions so Chinese
questions are grounded against Chinese-readable hints and negative rules.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.parser.dim5_knowledge_graph import (  # noqa: E402
    DIM5_GRAPH_PATH,
    build_dim5_rule_localization_report,
    localize_dim5_graph_payload,
)


DEFAULT_OUTPUT_DIR = ROOT / "data" / "dim5_knowledge_graph"
DEFAULT_DRAFT_PATH = DEFAULT_OUTPUT_DIR / "dim5_knowledge_graph_rules_draft.json"
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "dim5_knowledge_graph_rules_report.json"
EXPECTED_MIN_NODE_COUNT = 913


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chinese-localize Dim5 graph rule hints and audit coverage.",
    )
    parser.add_argument("--graph", type=Path, default=DIM5_GRAPH_PATH)
    parser.add_argument("--draft", type=Path, default=DEFAULT_DRAFT_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write files; return non-zero if localization acceptance fails.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = _load_json(args.graph)
    localized = localize_dim5_graph_payload(payload)
    report = build_dim5_rule_localization_report(localized)

    if not args.check:
        args.graph.write_text(
            json.dumps(localized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        args.draft.parent.mkdir(parents=True, exist_ok=True)
        args.draft.write_text(
            json.dumps(localized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    print(
        "node_count={node_count} required={required_structures_coverage} "
        "hints={fact_extraction_hints_coverage} negative={negative_hints_coverage} "
        "chinese={chinese_rule_coverage} english_residue={english_template_residue_count} "
        "low_quality={low_quality_rule_count}".format(**report)
    )
    failed = (
        report["node_count"] < EXPECTED_MIN_NODE_COUNT
        or report["required_structures_coverage"] != report["node_count"]
        or report["fact_extraction_hints_coverage"] != report["node_count"]
        or report["negative_hints_coverage"] != report["node_count"]
        or report["chinese_rule_coverage"] != report["node_count"]
        or report["english_template_residue_count"] != 0
        or report["low_quality_rule_count"] != 0
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
