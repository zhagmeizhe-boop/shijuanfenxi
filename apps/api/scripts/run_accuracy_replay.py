from __future__ import annotations

import asyncio
import argparse
import json
import sys
from pathlib import Path


def _load_cases(case_path: Path) -> list[dict]:
    with case_path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _normalize_question_type(raw_value, question_type_enum):
    if isinstance(raw_value, question_type_enum):
        return raw_value
    if hasattr(raw_value, "value"):
        raw_value = raw_value.value
    raw_text = str(raw_value or "").strip().lower()
    for item in question_type_enum:
        if item.value == raw_text:
            return item
    return question_type_enum.SOLUTION


def _resolve_case_file_path(repo_root: Path, case_path: Path, raw_value: str) -> Path:
    candidate = Path(raw_value)
    if candidate.is_absolute():
        return candidate

    repo_candidate = (repo_root / candidate).resolve()
    if repo_candidate.exists():
        return repo_candidate

    workspace_candidate = (repo_root.parent / candidate).resolve()
    if workspace_candidate.exists():
        return workspace_candidate

    return (case_path.parent / candidate).resolve()


async def _run_paper_count_case(provider, pdf_path: Path):
    parsed_paper = await provider.parse(
        str(pdf_path),
        paper_name=pdf_path.stem,
        paper_id=f"replay-{pdf_path.stem}",
    )

    section_counts: dict[str, int] = {}
    for audit in getattr(parsed_paper, "question_count_audits", []) or []:
        key = str(getattr(audit, "section_index_raw", "") or getattr(audit, "zone_key", "")).strip()
        if not key:
            continue
        section_counts[key] = section_counts.get(key, 0) + int(getattr(audit, "detected_count", 0) or 0)

    return parsed_paper, section_counts


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str((repo_root / "apps" / "api").resolve()))

    from app.core.config import settings
    from app.services.ocr.factory import create_ocr_provider

    parser = argparse.ArgumentParser(description="Run offline accuracy replay checks.")
    parser.add_argument(
        "--cases",
        default=str(repo_root / "apps" / "api" / "data" / "accuracy_replay_cases.json"),
        help="Path to replay cases JSON.",
    )
    parser.add_argument(
        "--case-type",
        action="append",
        dest="case_types",
        help="Only run specified case types, e.g. --case-type paper_count.",
    )
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on mismatch.")
    args = parser.parse_args()

    case_path = Path(args.cases)
    cases = _load_cases(case_path)

    question_type_enum = None
    ocr_provider = None
    reference_standard = None
    dim1_applicability_evaluator = None

    def _get_question_type_enum():
        nonlocal question_type_enum
        if question_type_enum is None:
            from app.services.ocr.base import QuestionType

            question_type_enum = QuestionType
        return question_type_enum

    def _get_ocr_provider():
        nonlocal ocr_provider
        if ocr_provider is None:
            ocr_provider = create_ocr_provider(settings.OCR_PROVIDER, use_cache=False)
        return ocr_provider

    def _get_reference_standard():
        nonlocal reference_standard
        if reference_standard is None:
            from app.services.parser.reference_standard import get_reference_standard

            reference_standard = get_reference_standard()
        return reference_standard

    def _get_dim1_applicability_evaluator():
        nonlocal dim1_applicability_evaluator
        if dim1_applicability_evaluator is None:
            from app.services.scoring.dim1_applicability import evaluate_dim1_applicability

            dim1_applicability_evaluator = evaluate_dim1_applicability
        return dim1_applicability_evaluator

    total_checks = 0
    passed_checks = 0
    failures: list[str] = []

    case_type_filters = {str(item).strip().lower() for item in (args.case_types or []) if str(item).strip()}

    for case in cases:
        case_type = str(case.get("case_type", "dimension")).strip().lower()
        if case_type_filters and case_type not in case_type_filters:
            continue
        if case_type == "paper_count":
            pdf_path = _resolve_case_file_path(repo_root, case_path, str(case["pdf_path"]))
            if not pdf_path.exists():
                failures.append(f"[{case['name']}] pdf not found: {pdf_path}")
                total_checks += 1
                continue

            parsed_paper, section_counts = asyncio.run(_run_paper_count_case(_get_ocr_provider(), pdf_path))

            total_checks += 1
            expected_total = int(case["expected_total_question_count"])
            if parsed_paper.total_question_count == expected_total:
                passed_checks += 1
            else:
                failures.append(
                    f"[{case['name']}] expected total_question_count={expected_total}, got {parsed_paper.total_question_count}"
                )

            for section_case in case.get("expected_sections", []):
                total_checks += 1
                section_key = str(section_case.get("section_index_raw", "")).strip()
                expected_count = int(section_case.get("count", 0))
                actual_count = int(section_counts.get(section_key, 0))
                if actual_count == expected_count:
                    passed_checks += 1
                else:
                    failures.append(
                        f"[{case['name']}] expected section {section_key} count={expected_count}, got {actual_count}"
                    )

            if "expected_warning" in case:
                total_checks += 1
                actual_warning = bool(getattr(parsed_paper, "report_warnings", []))
                if actual_warning == bool(case["expected_warning"]):
                    passed_checks += 1
                else:
                    failures.append(
                        f"[{case['name']}] expected warning={case['expected_warning']}, got {actual_warning}"
                    )
            continue

        if case_type == "ocr":
            question_type = _normalize_question_type(case.get("question_type", ""), _get_question_type_enum())
            question_text = case.get("question_text", "")
            line_count = int(case.get("line_count", 1) or 1)
            sub_item_candidates = []
            if case.get("sub_item_count"):
                from app.services.ocr.base import SubItemCandidate

                sub_item_candidates = [
                    SubItemCandidate(candidate_no=str(index + 1), raw_text="")
                    for index in range(int(case["sub_item_count"]))
                ]

            if "expected_formula_attempt" in case:
                total_checks += 1
                actual = _get_ocr_provider()._should_try_formula_enhancement(
                    question_text,
                    question_type,
                    line_count,
                )
                if actual == bool(case["expected_formula_attempt"]):
                    passed_checks += 1
                else:
                    failures.append(
                        f"[{case['name']}] expected formula_attempt={case['expected_formula_attempt']}, got {actual}"
                    )

            if any(
                key in case
                for key in ("expected_visual_category", "expected_image_required", "expected_image_attach")
            ):
                visual = _get_ocr_provider()._classify_visual_need(
                    question_text,
                    question_type,
                    sub_item_candidates,
                )
                if "expected_visual_category" in case:
                    total_checks += 1
                    if visual.get("category") == case["expected_visual_category"]:
                        passed_checks += 1
                    else:
                        failures.append(
                            f"[{case['name']}] expected visual_category={case['expected_visual_category']}, got {visual.get('category')}"
                        )
                if "expected_image_required" in case:
                    total_checks += 1
                    if bool(visual.get("required")) == bool(case["expected_image_required"]):
                        passed_checks += 1
                    else:
                        failures.append(
                            f"[{case['name']}] expected image_required={case['expected_image_required']}, got {visual.get('required')}"
                        )
                if "expected_image_attach" in case:
                    total_checks += 1
                    if bool(visual.get("attach_recommended")) == bool(case["expected_image_attach"]):
                        passed_checks += 1
                    else:
                        failures.append(
                            f"[{case['name']}] expected image_attach={case['expected_image_attach']}, got {visual.get('attach_recommended')}"
                        )
            continue

        dim_code = case["dim_code"]
        feature = dict(case.get("feature", {}))
        calibrated = _get_reference_standard().calibrate_feature(
            dim_code,
            feature,
            question_text=case["question_text"],
            question_summary=case.get("question_summary", ""),
            analysis_facts=case.get("analysis_facts", {}),
        )

        expected_band = case.get("expected_band")
        if expected_band:
            total_checks += 1
            if calibrated.get("band") == expected_band:
                passed_checks += 1
            else:
                failures.append(
                    f"[{case['name']}] expected band={expected_band}, got {calibrated.get('band')}"
                )

        if dim_code == "dim1" and "expected_applicable" in case:
            total_checks += 1
            applicable, reason = _get_dim1_applicability_evaluator()(
                case.get("question_type", ""),
                case["question_text"],
                calibrated,
                ["dim1"],
            )
            if applicable == bool(case["expected_applicable"]):
                passed_checks += 1
            else:
                failures.append(
                    f"[{case['name']}] expected applicable={case['expected_applicable']}, got {applicable} ({reason})"
                )

    print(f"replay checks: {passed_checks}/{total_checks} passed")
    if failures:
        print("failures:")
        for item in failures:
            print(f"- {item}")
    else:
        print("all checks passed")

    return 1 if failures and args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
