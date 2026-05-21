from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Awaitable, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.core.config import settings
from app.core.database import AsyncSessionLocal, close_db
from app.services.concurrency.analysis_slots import cleanup_stale_analysis_slots
from app.models import (
    DimensionCode as ModelDimensionCode,
    Paper,
    PaperDimScore,
    ParseStatus as ModelParseStatus,
    Question,
    QuestionDimScore,
    QuestionTag,
    QuestionType as ModelQuestionType,
    ReportSnapshot,
)
from app.services.ocr.field_safety import (
    MAX_QUESTION_NO_LENGTH,
    MAX_SECTION_INDEX_RAW_LENGTH,
    clamp_storage_text,
    normalize_section_index_raw,
)
from app.services.ocr.factory import create_ocr_provider
from app.services.parser import create_ai_parser
from app.services.report.report_service import ReportService
from app.services.scoring.dim1_applicability import (
    DIM1_STATUS_APPLICABLE,
    DIM1_STATUS_NEEDS_SECOND_REVIEW,
    DIM1_STATUS_NOT_APPLICABLE,
    DIM1_STATUS_REVIEW,
    evaluate_dim1_applicability,
)
from app.services.scoring.dim2_applicability import (
    DIM2_STATUS_APPLICABLE,
    build_dim2_text_geometry_fallback_facts,
    build_dim2_visual_fallback_facts,
    evaluate_dim2_applicability,
)
from app.services.scoring.dim3_applicability import (
    DIM3_STATUS_APPLICABLE,
    DIM3_STATUS_NEEDS_SECOND_REVIEW,
    DIM3_STATUS_NOT_APPLICABLE,
    enrich_dim3_text_length_facts,
    evaluate_dim3_applicability,
)
from app.services.scoring.dim4_applicability import (
    DIM4_STATUS_APPLICABLE,
    DIM4_STATUS_NEEDS_SECOND_REVIEW,
    DIM4_STATUS_NOT_APPLICABLE,
    evaluate_dim4_applicability,
)
from app.services.scoring.dim6_applicability import (
    DIM6_STATUS_APPLICABLE,
    DIM6_STATUS_NEEDS_SECOND_REVIEW,
    DIM6_STATUS_NOT_APPLICABLE,
    DIM6_STATUS_REVIEW,
    evaluate_dim6_applicability,
)
from app.services.scoring.dim_second_review import (
    SECOND_REVIEW_STATUS_APPLICABLE,
    SECOND_REVIEW_STATUS_FAILED_EXCLUDED,
    SECOND_REVIEW_STATUS_NOT_APPLICABLE,
    build_second_review_dimension_score,
    build_second_review_exclusion_details,
    normalize_second_review_payload,
)
from app.services.scoring.paper_aggregator import QuestionDimensionScore

logger = logging.getLogger(__name__)

STAGE_LABELS = {
    "upload_saved": "文件保存",
    "ocr_parse": "OCR 解析",
    "question_persist": "题目入库",
    "llm_parse": "LLM 分析",
    "report_build": "报告生成",
    "snapshot_save": "报告快照保存",
}

_UNSET = object()


def _get_ocr_provider():
    return create_ocr_provider()


def _summarize_question(text: str, max_length: int = 52) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[:max_length].rstrip()}..."


def _build_question_display_label(
    question_no: str,
    question_label_raw: str | None = None,
    section_index_raw: str | None = None,
) -> str:
    normalized_section = str(section_index_raw or "").strip()
    normalized_question_no = str(question_no or "").strip()
    if normalized_section and normalized_question_no:
        return f"{normalized_section}-{normalized_question_no}"

    normalized_raw_label = str(question_label_raw or "").strip()
    if normalized_raw_label:
        return normalized_raw_label

    return normalized_question_no


def _safe_question_no_for_storage(value: Any, *, fallback: str, context: str) -> str:
    normalized = clamp_storage_text(
        value,
        MAX_QUESTION_NO_LENGTH,
        field_name="question_no",
        logger=logger,
        context=context,
    )
    if normalized:
        return normalized
    return fallback[:MAX_QUESTION_NO_LENGTH]


def _safe_optional_storage_text(value: Any, *, max_length: int, field_name: str, context: str) -> str | None:
    normalized = clamp_storage_text(
        value,
        max_length,
        field_name=field_name,
        logger=logger,
        context=context,
    )
    return normalized or None


def _safe_section_index_for_storage(value: Any, *, context: str) -> str | None:
    normalized = normalize_section_index_raw(value)
    return _safe_optional_storage_text(
        normalized,
        max_length=MAX_SECTION_INDEX_RAW_LENGTH,
        field_name="section_index_raw",
        context=context,
    )


def _dimension_declared_or_inferred(dim_code: str, features, feature_dict: dict) -> bool:
    declared = set(getattr(features, "applicable_dimensions", []) or [])
    if dim_code in declared:
        return True

    if dim_code == "dim1":
        return feature_dict.get("calc_role") == "core"
    if dim_code == "dim2":
        return feature_dict.get("spatial_role") == "core"
    if dim_code == "dim4":
        return feature_dict.get("strategy_role") == "core"
    if dim_code == "dim5":
        return bool(
            (feature_dict.get("band") and feature_dict.get("sublevel"))
            or feature_dict.get("knowledge_level")
            or _dim5_has_graph_review_signal(feature_dict)
        )
    if dim_code == "dim6":
        return feature_dict.get("reasoning_role") == "core"
    return False


def _dim5_has_graph_review_signal(feature_dict: dict) -> bool:
    if not isinstance(feature_dict, dict):
        return False
    if str(feature_dict.get("dim5_excluded_reason") or "").strip() == "retry_failed":
        return False
    candidates = feature_dict.get("candidate_knowledge_points")
    if isinstance(candidates, list) and candidates:
        return True
    facts = feature_dict.get("dim5_structure_facts")
    if not isinstance(facts, list):
        return False
    clear_fact_keys = {
        "statistics_chart_context",
        "statistics_percent_conversion",
        "fraction_application",
        "proportion_application",
        "work_rate_task",
        "motion_task",
        "profit_discount",
        "price_profit_relation",
        "two_type_cost_total",
        "gaosi_chicken_rabbit",
        "gaosi_travel",
        "gaosi_work_rate",
        "gaosi_concentration_profit",
        "gaosi_number_theory",
        "gaosi_digit_puzzle",
        "square_difference_odd",
        "digit_swap_multiple",
        "integer_solution_factorization",
        "pigeonhole",
        "guarantee_at_least",
        "fold_cut_unfold",
        "geometry_transform_puzzle",
        "school_cube_net",
        "area_relation_model",
        "overlap_area",
        "cylinder_surface_volume",
        "periodic_grid",
        "state_recurrence",
        "line_plane_recurrence",
        "transport_optimization",
        "gaosi_probability",
    }
    return any(
        str(item.get("fact_key") or "") in clear_fact_keys
        for item in facts
        if isinstance(item, dict)
    )


_TRUE_PARSE_DAMAGE_MARKERS = ("残缺", "缺损", "截断", "识别失败", "公式增强识别失败")
_NON_DIMENSION_WARNING_MARKERS = ("score_missing", "分值", "裁切", "图片")
_DIMENSION_SCOPED_WARNING_CODES = {"dim2", "dim3", "dim4", "dim6"}


def _dedupe_warnings(warnings: List[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for item in warnings:
        normalized = str(item).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _is_true_parse_damage_warning(item: Any) -> bool:
    text = str(item or "").strip()
    if not text:
        return False
    if any(marker in text for marker in _NON_DIMENSION_WARNING_MARKERS):
        return False
    return any(marker in text for marker in _TRUE_PARSE_DAMAGE_MARKERS)


def _dimension_scoped_feature_warnings(features, dim_code: str) -> List[str]:
    prefix = f"{dim_code} "
    return [
        str(item).strip()
        for item in (getattr(features, "warnings", []) or [])
        if str(item).strip().startswith(prefix)
    ]


def _collect_applicability_parse_warnings(question) -> List[str]:
    return [
        str(item).strip()
        for item in (getattr(question, "parse_warnings", []) or [])
        if _is_true_parse_damage_warning(item)
    ]


def _collect_dimension_warnings(
    question,
    features,
    feature_dict: dict,
    dim_code: str | None = None,
) -> List[str]:
    warnings: List[str] = []
    if dim_code in {"dim1", "dim3", "dim4", "dim6"} and feature_dict.get("second_review_status") == "applicable":
        return []
    if dim_code == "dim2":
        if feature_dict.get("fallback_source") != "visual_geometry":
            warnings.extend(
                item
                for item in (getattr(features, "warnings", []) or [])
                if str(item).strip().startswith("dim2 ")
            )
        feature_warning = str(feature_dict.get("warning", "")).strip()
        if feature_warning:
            warnings.append(feature_warning)
        if getattr(features, "image_fallback", False):
            warnings.append("多模态分析失败，当前题目按纯文本回退判断。")

        return _dedupe_warnings(warnings)

    if dim_code in _DIMENSION_SCOPED_WARNING_CODES:
        warnings.extend(_dimension_scoped_feature_warnings(features, dim_code))
        feature_warning = str(feature_dict.get("warning", "")).strip()
        if feature_warning:
            warnings.append(feature_warning)
        if (
            getattr(features, "image_fallback", False)
            and str(feature_dict.get("image_dependency", "")).strip() == "required"
        ):
            warnings.append("多模态分析失败，当前题目按纯文本回退判断。")
        return _dedupe_warnings(warnings)

    warnings.extend(getattr(question, "parse_warnings", []) or [])
    warnings.extend(getattr(features, "warnings", []) or [])

    feature_warning = str(feature_dict.get("warning", "")).strip()
    if feature_warning:
        warnings.append(feature_warning)

    calibration = feature_dict.get("calibration", {})
    band_gap_value = 0.0
    if isinstance(calibration, dict):
        raw_band_gap = calibration.get("band_gap")
        try:
            band_gap_value = float(raw_band_gap) if raw_band_gap is not None else 0.0
        except (TypeError, ValueError):
            band_gap_value = 0.0

    if isinstance(calibration, dict) and band_gap_value >= 2:
        warnings.append("模型主判与参考体系差距较大，当前维度已按参考体系纠偏。")
    if getattr(features, "image_fallback", False):
        warnings.append("多模态分析失败，当前题目按纯文本回退判断。")

    return _dedupe_warnings(warnings)


def _list_strings(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dimension_confidence(feature_dict: dict, features) -> float:
    raw_confidence = feature_dict.get("applicability_confidence", getattr(features, "confidence", 0.0))
    try:
        return float(raw_confidence or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _dim1_feature_with_knowledge_context(feature_dict: dict, features) -> dict:
    enriched = dict(feature_dict) if isinstance(feature_dict, dict) else {}

    analysis_facts = getattr(features, "analysis_facts", {}) or {}
    if isinstance(analysis_facts, dict):
        enriched["analysis_facts"] = analysis_facts

    dim5_feature = (
        features.get_feature("dim5")
        if hasattr(features, "get_feature")
        else getattr(features, "dim5_knowledge", {})
    )
    if isinstance(dim5_feature, dict):
        enriched["dim5_knowledge"] = dim5_feature

    return enriched


def _build_dimension_reason(dim_code: str, dim_result, feature_dict: dict, features) -> str:
    reason_parts: List[str] = []
    if dim_result.evidence:
        reason_parts.append(dim_result.evidence)

    source_parts: List[str] = []
    if getattr(features, "used_image", False) and dim_code in {"dim2", "dim3"}:
        source_parts.append("图片")
    elif getattr(features, "image_fallback", False) and dim_code in {"dim2", "dim3"}:
        source_parts.append("纯文本回退")
    else:
        source_parts.append("文本")

    calibration = feature_dict.get("calibration", {})
    if isinstance(calibration, dict) and calibration.get("band_source"):
        source_parts.append(f"规则:{calibration.get('band_source')}")
    elif isinstance(calibration, dict) and calibration.get("action"):
        source_parts.append(f"参考校准:{calibration.get('action')}")

    if source_parts:
        reason_parts.append(f"依据来源：{' / '.join(source_parts)}。")

    if getattr(features, "analysis_facts", None):
        fact_bits = _list_strings(features.analysis_facts.get("core_knowledge_points", []))[:3]
        if fact_bits:
            reason_parts.append(f"核心事实：{'、'.join(fact_bits)}。")

    return " ".join(part.strip() for part in reason_parts if part.strip())


def _serialize_question_tag_payload(question, features, dimension_statuses: Optional[dict[str, Any]] = None) -> str:
    payload = {
        "question_no": question.question_no,
        "question_label_raw": getattr(question, "question_label_raw", "") or "",
        "section_index_raw": getattr(question, "section_index_raw", "") or "",
        "question_display_label": _build_question_display_label(
            question.question_no,
            getattr(question, "question_label_raw", "") or "",
            getattr(question, "section_index_raw", "") or "",
        ),
        "page_no": question.page_no,
        "question_type": getattr(question.question_type, "value", question.question_type),
        "ocr_text_version": question.ocr_text_version,
        "parse_warnings": getattr(question, "parse_warnings", []) or [],
        "parse_audit": question.parse_audit.to_dict() if getattr(question, "parse_audit", None) else None,
        "question_block": question.question_block.to_dict() if getattr(question, "question_block", None) else None,
        "sub_item_candidates": [candidate.to_dict() for candidate in getattr(question, "sub_item_candidates", [])],
        "analysis_facts": getattr(features, "analysis_facts", {}),
        "reasoning": getattr(features, "reasoning", ""),
        "warnings": getattr(features, "warnings", []),
        "need_manual_review": getattr(features, "need_manual_review", False),
        "used_image": getattr(features, "used_image", False),
        "image_fallback": getattr(features, "image_fallback", False),
        "visual_mode": getattr(features, "visual_mode", ""),
        "calibration_audits": getattr(features, "calibration_audits", {}),
        "dimension_statuses": dimension_statuses or {},
    }
    return json.dumps(payload, ensure_ascii=False)


def _second_review_exclusion_reason(dim_code: str, normalized_review: dict[str, Any]) -> str:
    if dim_code == "dim1":
        if normalized_review.get("status") == SECOND_REVIEW_STATUS_NOT_APPLICABLE:
            return (
                str(normalized_review.get("exclude_reason") or "").strip()
                or "二次复评确认该题没有稳定的核心计算执行负担，未计入该维度。"
            )
        return (
            str(normalized_review.get("exclude_reason") or "").strip()
            or "该题因题面信息不足或判定不稳定，未计入数学运算评分。"
        )
    if dim_code == "dim6":
        if normalized_review.get("status") == SECOND_REVIEW_STATUS_NOT_APPLICABLE:
            return (
                str(normalized_review.get("exclude_reason") or "").strip()
                or "二次复评确认该题没有稳定的逻辑链条负担，未计入该维度。"
            )
        return (
            str(normalized_review.get("exclude_reason") or "").strip()
            or "该题因题面信息不足或判定不稳定，未计入逻辑链条评分。"
        )
    dimension_name = "场景理解复杂度" if dim_code == "dim3" else "建模解题复杂度"
    if normalized_review.get("status") == SECOND_REVIEW_STATUS_NOT_APPLICABLE:
        return (
            str(normalized_review.get("exclude_reason") or "").strip()
            or f"二次复评确认该题没有稳定的{dimension_name}负担，未计入该维度。"
        )
    return (
        str(normalized_review.get("exclude_reason") or "").strip()
        or f"该题因图文信息不足或判定不稳定，未计入{dimension_name}评分。"
    )


def _highest_grade_hint(features) -> Optional[str]:
    dim5_feature = features.get_feature("dim5") if hasattr(features, "get_feature") else {}
    grade_clues = _list_strings(dim5_feature.get("grade_clues", []))
    if grade_clues:
        return grade_clues[0][:20]
    band = str(dim5_feature.get("band", "")).strip()
    return band[:20] if band else None


def _describe_exception(stage: str, exc: Exception) -> str:
    stage_label = STAGE_LABELS.get(stage, stage)
    exc_text = str(exc).strip()
    if stage == "question_persist" and (
        isinstance(exc, DBAPIError)
        or "StringDataRightTruncationError" in exc_text
        or "value too long for type character varying" in exc_text
    ):
        return "题目信息保存失败：识别出的题号或栏目标题过长，请重新上传或联系管理员。"

    exc_type = exc.__class__.__name__
    exc_text = exc_text or exc_type
    return f"{stage_label}失败（{exc_type}）：{exc_text}"


def _is_failed_question_features(features: Any) -> bool:
    return bool(getattr(features, "parse_failed", False))


async def _update_paper_state(
    paper_id: str,
    *,
    parse_status: Any = _UNSET,
    last_stage: Any = _UNSET,
    error_message: Any = _UNSET,
    parse_confidence: Any = _UNSET,
    need_manual_review: Any = _UNSET,
    page_count: Any = _UNSET,
    total_question_count: Any = _UNSET,
    total_score: Any = _UNSET,
    progress_current: Any = _UNSET,
    progress_total: Any = _UNSET,
    progress_message: Any = _UNSET,
) -> None:
    async with AsyncSessionLocal() as db:
        paper = await db.get(Paper, paper_id)
        if not paper:
            return

        if parse_status is not _UNSET:
            paper.parse_status = parse_status
        if last_stage is not _UNSET:
            paper.last_stage = last_stage
        if error_message is not _UNSET:
            paper.error_message = error_message
        if parse_confidence is not _UNSET:
            paper.parse_confidence = parse_confidence
        if need_manual_review is not _UNSET:
            paper.need_manual_review = need_manual_review
        if page_count is not _UNSET:
            paper.page_count = page_count
        if total_question_count is not _UNSET:
            paper.total_question_count = total_question_count
        if total_score is not _UNSET:
            paper.total_score = total_score
        if progress_current is not _UNSET:
            paper.progress_current = progress_current
        if progress_total is not _UNSET:
            paper.progress_total = progress_total
        if progress_message is not _UNSET:
            paper.progress_message = progress_message

        await db.commit()


async def mark_stale_analysis_tasks(stale_minutes: int | None = None) -> int:
    stale_minutes = stale_minutes or settings.TASK_STALE_MINUTES
    cutoff = datetime.utcnow() - timedelta(minutes=stale_minutes)
    stale_count = 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Paper).where(
                Paper.parse_status == ModelParseStatus.PARSING,
                Paper.updated_at < cutoff,
            )
        )
        stale_papers = result.scalars().all()

        for paper in stale_papers:
            paper.parse_status = ModelParseStatus.PARSE_FAILED
            paper.last_stage = paper.last_stage or "parsing"
            paper.error_message = "任务中断或 worker 退出，请重新上传"

        stale_count = len(stale_papers)
        if stale_papers:
            await db.commit()

        active_result = await db.execute(
            select(Paper.paper_id).where(Paper.parse_status == ModelParseStatus.PARSING)
        )
        active_paper_ids = [str(row[0]) for row in active_result.all() if row[0]]

    try:
        cleanup_stale_analysis_slots(active_paper_ids)
    except Exception:
        logger.warning("Failed to cleanup stale analysis slots", exc_info=True)

    return stale_count


async def mark_paper_waiting_for_analysis_slot(paper_id: str) -> None:
    await _update_paper_state(
        paper_id,
        parse_status=ModelParseStatus.PENDING,
        last_stage="queued_waiting_for_analysis_slot",
        error_message=None,
        progress_current=None,
        progress_total=None,
        progress_message="正在排队等待分析 worker 空闲槽位",
    )


def mark_paper_waiting_for_analysis_slot_sync(paper_id: str) -> None:
    _run_in_isolated_event_loop(mark_paper_waiting_for_analysis_slot(paper_id))


async def _run_with_db_cleanup(awaitable: Awaitable[None]) -> None:
    try:
        await awaitable
    finally:
        try:
            await close_db()
        except Exception:
            logger.warning("Failed to close async database pool before closing task event loop", exc_info=True)


def _run_in_isolated_event_loop(awaitable: Awaitable[None]) -> None:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run_with_db_cleanup(awaitable))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                logger.warning("Failed to shutdown async generators for task event loop", exc_info=True)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


async def execute_paper_analysis(paper_id: str, file_path: str) -> None:
    report_service = ReportService()
    ocr_provider = _get_ocr_provider()
    logger.info("Executing paper analysis with OCR provider=%s paper=%s", settings.OCR_PROVIDER, paper_id)
    current_stage = "ocr_parse"

    try:
        await _update_paper_state(
            paper_id,
            parse_status=ModelParseStatus.PARSING,
            last_stage=current_stage,
            error_message=None,
            progress_current=None,
            progress_total=None,
            progress_message=None,
        )

        async with AsyncSessionLocal() as db:
            paper = await db.get(Paper, paper_id)
            paper_name = paper.paper_name if paper else f"试卷_{paper_id}"

        async def _persist_ocr_progress(progress: dict[str, Any]) -> None:
            page_no = str(progress.get("page_no", "")).strip() or "?"
            completed = int(progress.get("completed", 0) or 0)
            total = int(progress.get("total", 0) or 0)
            success = bool(progress.get("success", False))
            status_suffix = "" if success else "\uff08\u5931\u8d25\uff09"
            logger.info(
                "Vision OCR progress paper=%s completed=%s/%s page=%s success=%s",
                paper_id,
                completed,
                total,
                page_no,
                success,
            )
            await _update_paper_state(
                paper_id,
                progress_current=completed,
                progress_total=total,
                progress_message="\u6700\u8fd1\u5b8c\u6210\u7b2c %s \u9875%s" % (page_no, status_suffix),
            )

        parsed_paper = await ocr_provider.parse(
            file_path=file_path,
            paper_name=paper_name,
            paper_id=paper_id,
            progress_callback=_persist_ocr_progress,
        )

        await _update_paper_state(
            paper_id,
            parse_confidence=parsed_paper.parse_confidence,
            page_count=parsed_paper.page_count,
            total_question_count=len(parsed_paper.questions),
            total_score=sum(question.score for question in parsed_paper.questions),
        )

        current_stage = "question_persist"
        logger.info("Entering stage=%s paper=%s total_questions=%s", current_stage, paper_id, len(parsed_paper.questions))
        await _update_paper_state(paper_id, last_stage=current_stage)

        question_records: List[tuple[str, Any]] = []
        async with AsyncSessionLocal() as db:
            for question in parsed_paper.questions:
                question_id = str(uuid.uuid4())
                field_context = f"paper={paper_id} question_id={question_id}"
                stored_question_no = _safe_question_no_for_storage(
                    getattr(question, "question_no", ""),
                    fallback=question_id,
                    context=field_context,
                )
                stored_question_label_raw = _safe_optional_storage_text(
                    getattr(question, "question_label_raw", ""),
                    max_length=50,
                    field_name="question_label_raw",
                    context=field_context,
                )
                stored_section_index_raw = _safe_section_index_for_storage(
                    getattr(question, "section_index_raw", ""),
                    context=field_context,
                )
                stored_ocr_text_version = _safe_optional_storage_text(
                    getattr(question, "ocr_text_version", ""),
                    max_length=20,
                    field_name="ocr_text_version",
                    context=field_context,
                ) or "v1.0"
                db.add(
                    Question(
                        question_id=question_id,
                        paper_id=paper_id,
                        page_no=question.page_no,
                        question_no=stored_question_no,
                        question_label_raw=stored_question_label_raw,
                        section_index_raw=stored_section_index_raw,
                        question_type=ModelQuestionType(getattr(question.question_type, "value", question.question_type)),
                        raw_text=question.raw_text,
                        image_block_url=question.image_block_url,
                        score=question.score,
                        is_optional=question.is_optional,
                        include_in_main_score=question.include_in_main_score,
                        parse_confidence=question.parse_confidence,
                        applicable_dims=[getattr(item, "value", item) for item in question.applicable_dims],
                        ocr_text_version=stored_ocr_text_version,
                    )
                )
                question_records.append((question_id, question))
            await db.commit()

        current_stage = "llm_parse"
        logger.info("Entering stage=%s paper=%s total_questions=%s", current_stage, paper_id, len(parsed_paper.questions))
        await _update_paper_state(
            paper_id,
            last_stage=current_stage,
            progress_current=0,
            progress_total=len(parsed_paper.questions),
            progress_message="LLM 分析已启动",
        )

        api_key = settings.ANTHROPIC_API_KEY or settings.MOONSHOT_API_KEY
        ai_parser = create_ai_parser(
            api_key=api_key,
            model=settings.CLAUDE_MODEL,
            base_url=settings.LLM_BASE_URL,
            max_tokens=settings.QUESTION_LLM_MAX_TOKENS,
            timeout=settings.QUESTION_LLM_REQUEST_TIMEOUT_SECONDS,
            llm_pool="question",
        )
        async def _persist_llm_progress(progress: dict[str, Any]) -> None:
            question_no = str(progress.get("question_no", "")).strip() or "?"
            completed = int(progress.get("completed", 0) or 0)
            total = int(progress.get("total", 0) or 0)
            success = bool(progress.get("success", False))
            status_suffix = "" if success else "\uff08\u5931\u8d25\uff0c\u5df2\u7ee7\u7eed\uff09"
            progress_message = "\u6700\u8fd1\u5b8c\u6210\u7b2c %s \u9898%s" % (question_no, status_suffix)
            logger.info(
                "LLM progress paper=%s completed=%s/%s question=%s success=%s",
                paper_id,
                completed,
                total,
                question_no,
                success,
            )
            await _update_paper_state(
                paper_id,
                progress_current=completed,
                progress_total=total,
                progress_message=progress_message,
            )

        question_features = await ai_parser.parse_paper(
            parsed_paper,
            concurrency=max(1, int(settings.QUESTION_LLM_CONCURRENCY or 1)),
            progress_callback=_persist_llm_progress,
            question_timeout_seconds=settings.QUESTION_LLM_TIMEOUT_SECONDS,
            question_max_attempts=settings.QUESTION_LLM_MAX_ATTEMPTS,
            retry_base_seconds=settings.QUESTION_LLM_RETRY_BASE_SECONDS,
        )
        if len(question_features) != len(question_records):
            raise RuntimeError(
                f"LLM 结果数量不匹配：题目 {len(question_records)}，特征 {len(question_features)}"
            )

        if question_features and all(_is_failed_question_features(features) for features in question_features):
            logger.error("All questions failed during llm_parse paper=%s total=%s", paper_id, len(question_features))
            await _update_paper_state(
                paper_id,
                parse_status=ModelParseStatus.PARSE_FAILED,
                last_stage=current_stage,
                error_message="LLM 阶段全部失败",
                progress_current=None,
                progress_total=None,
                progress_message=None,
            )
            return

        current_stage = "report_build"
        logger.info("Entering stage=%s paper=%s", current_stage, paper_id)
        await _update_paper_state(
            paper_id,
            last_stage=current_stage,
            progress_current=None,
            progress_total=None,
            progress_message=None,
        )

        qds_list: List[QuestionDimensionScore] = []
        paper_report_warnings = list(getattr(parsed_paper, "report_warnings", []) or [])
        manual_review_needed = parsed_paper.need_manual_review or bool(paper_report_warnings)

        async with AsyncSessionLocal() as db:
            paper = await db.get(Paper, paper_id)

            for (question_id, question), features in zip(question_records, question_features):
                dim_scores = {}
                applicable_dims = []
                dim_reasons = {}
                dim_warnings = {}
                dim_confidences = {}
                dim_statuses = {}
                dim_details = {}
                question_dim_rows: List[QuestionDimScore] = []
                dimension_status_payload: dict[str, Any] = {}

                for dim_code, scorer in report_service.scorers.items():
                    feature_dict = features.get_feature(dim_code) if hasattr(features, "get_feature") else {}
                    reason = ""
                    dim_result_override = None

                    if dim_code == "dim1":
                        feature_dict = _dim1_feature_with_knowledge_context(feature_dict, features)
                        setattr(features, "dim1_computation", feature_dict)
                        dim1_status = evaluate_dim1_applicability(
                            question.question_type,
                            question.raw_text,
                            feature_dict,
                            llm_confidence=getattr(features, "confidence", 0.0) or 0.0,
                            parse_warnings=[
                                *list(getattr(question, "parse_warnings", []) or []),
                                *list(getattr(features, "warnings", []) or []),
                            ],
                        )
                        dim_status = dim1_status["status"]
                        reason = dim1_status["reason"]
                        dim_statuses[dim_code] = dim_status
                        if dim1_status["warnings"]:
                            dim_warnings[dim_code] = list(
                                dict.fromkeys(str(item).strip() for item in dim1_status["warnings"] if str(item).strip())
                            )
                        dimension_status_payload[dim_code] = {
                            "status": dim_status,
                            "reason": reason,
                            "warnings": dim_warnings.get(dim_code, []),
                            "normalized_facts": feature_dict,
                        }
                        if dim_status in {DIM1_STATUS_NEEDS_SECOND_REVIEW, DIM1_STATUS_REVIEW}:
                            second_review_raw = await ai_parser.review_dim3_dim4_applicability(
                                question,
                                dim_code=dim_code,
                                analysis_facts=getattr(features, "analysis_facts", {}) or {},
                                initial_feature=feature_dict,
                                initial_status=dim1_status,
                            )
                            normalized_review = normalize_second_review_payload(dim_code, second_review_raw)
                            dimension_status_payload[dim_code]["initial_status"] = dim1_status
                            dimension_status_payload[dim_code]["second_review"] = normalized_review
                            if normalized_review["status"] == SECOND_REVIEW_STATUS_APPLICABLE:
                                dim_result_override = build_second_review_dimension_score(
                                    dim_code,
                                    second_review_raw,
                                    initial_feature=feature_dict,
                                    initial_status=dim1_status,
                                )
                                feature_dict = dict(dim_result_override.details or {})
                                setattr(features, "dim1_computation", feature_dict)
                                dim_status = DIM1_STATUS_APPLICABLE
                                reason = dim_result_override.evidence
                                dim_statuses[dim_code] = dim_status
                                dim_warnings.pop(dim_code, None)
                                dimension_status_payload[dim_code].update(
                                    {
                                        "status": dim_status,
                                        "reason": reason,
                                        "warnings": [],
                                        "normalized_facts": feature_dict,
                                        "score_details": dim_result_override.details,
                                    }
                                )
                            else:
                                final_status = (
                                    DIM1_STATUS_NOT_APPLICABLE
                                    if normalized_review["status"] == SECOND_REVIEW_STATUS_NOT_APPLICABLE
                                    else SECOND_REVIEW_STATUS_FAILED_EXCLUDED
                                )
                                reason = _second_review_exclusion_reason(dim_code, normalized_review)
                                exclusion_details = build_second_review_exclusion_details(
                                    dim_code,
                                    second_review_raw,
                                    initial_feature=feature_dict,
                                    initial_status=dim1_status,
                                )
                                dim_statuses[dim_code] = final_status
                                dim_warnings.pop(dim_code, None)
                                dim_reasons[dim_code] = reason
                                dim_confidences[dim_code] = float(normalized_review.get("confidence", 0.0) or 0.0)
                                dim_details[dim_code] = exclusion_details
                                dimension_status_payload[dim_code].update(
                                    {
                                        "status": final_status,
                                        "reason": reason,
                                        "warnings": [],
                                        "normalized_facts": exclusion_details,
                                        "score_details": exclusion_details,
                                    }
                                )
                                question_dim_rows.append(
                                    QuestionDimScore(
                                        question_id=question_id,
                                        dim_code=ModelDimensionCode(dim_code),
                                        dim_score=0.0,
                                        is_applicable=False,
                                        score_evidence=reason,
                                        rule_version="v3.0-accuracy",
                                        confidence=float(normalized_review.get("confidence", 0.0) or 0.0),
                                    )
                                )
                                continue
                        if dim_status != DIM1_STATUS_APPLICABLE:
                            dim_reasons[dim_code] = reason
                            dim_confidences[dim_code] = _dimension_confidence(feature_dict, features)
                            if isinstance(feature_dict, dict):
                                dim_details[dim_code] = feature_dict
                            question_dim_rows.append(
                                QuestionDimScore(
                                    question_id=question_id,
                                    dim_code=ModelDimensionCode(dim_code),
                                    dim_score=0.0,
                                    is_applicable=False,
                                    score_evidence=reason,
                                    rule_version="v3.0-accuracy",
                                    confidence=getattr(features, "confidence", 0.0) or 0.0,
                                )
                            )
                            continue
                    elif dim_code == "dim2":
                        dim2_fallback = build_dim2_text_geometry_fallback_facts(question.raw_text, feature_dict)
                        if not dim2_fallback:
                            dim2_fallback = build_dim2_visual_fallback_facts(
                                question.raw_text,
                                feature_dict,
                                parse_audit=getattr(question, "parse_audit", None),
                                has_image=bool(getattr(question, "image_block_url", None)),
                                used_image=getattr(features, "used_image", False),
                                image_fallback=getattr(features, "image_fallback", False),
                            )
                        if dim2_fallback:
                            feature_dict = dim2_fallback
                            setattr(features, "dim2_spatial", feature_dict)
                        dim2_status = evaluate_dim2_applicability(
                            question.raw_text,
                            feature_dict,
                            llm_confidence=getattr(features, "confidence", 0.0) or 0.0,
                            parse_audit=getattr(question, "parse_audit", None),
                            used_image=getattr(features, "used_image", False),
                            image_fallback=getattr(features, "image_fallback", False),
                            parse_warnings=list(getattr(question, "parse_warnings", []) or []),
                        )
                        dim_status = dim2_status["status"]
                        reason = dim2_status["reason"]
                        dim_statuses[dim_code] = dim_status
                        if dim2_status["warnings"]:
                            dim_warnings[dim_code] = list(
                                dict.fromkeys(str(item).strip() for item in dim2_status["warnings"] if str(item).strip())
                            )
                            manual_review_needed = True
                        dimension_status_payload[dim_code] = {
                            "status": dim_status,
                            "reason": reason,
                            "warnings": dim_warnings.get(dim_code, []),
                            "normalized_facts": feature_dict,
                        }
                        if dim_status != DIM2_STATUS_APPLICABLE:
                            dim_reasons[dim_code] = reason
                            dim_confidences[dim_code] = _dimension_confidence(feature_dict, features)
                            if isinstance(feature_dict, dict):
                                dim_details[dim_code] = feature_dict
                            question_dim_rows.append(
                                QuestionDimScore(
                                    question_id=question_id,
                                    dim_code=ModelDimensionCode(dim_code),
                                    dim_score=0.0,
                                    is_applicable=False,
                                    score_evidence=reason,
                                    rule_version="v3.0-accuracy",
                                    confidence=getattr(features, "confidence", 0.0) or 0.0,
                                )
                            )
                            continue
                    elif dim_code == "dim3":
                        feature_dict = enrich_dim3_text_length_facts(question.raw_text, feature_dict)
                        setattr(features, "dim3_information", feature_dict)
                        dim3_status = evaluate_dim3_applicability(
                            question.raw_text,
                            feature_dict,
                            llm_confidence=getattr(features, "confidence", 0.0) or 0.0,
                            parse_audit=getattr(question, "parse_audit", None),
                            used_image=getattr(features, "used_image", False),
                            image_fallback=getattr(features, "image_fallback", False),
                            parse_warnings=_collect_applicability_parse_warnings(question),
                        )
                        dim_status = dim3_status["status"]
                        reason = dim3_status["reason"]
                        dim_statuses[dim_code] = dim_status
                        if dim3_status["warnings"]:
                            dim_warnings[dim_code] = list(
                                dict.fromkeys(str(item).strip() for item in dim3_status["warnings"] if str(item).strip())
                            )
                        dimension_status_payload[dim_code] = {
                            "status": dim_status,
                            "reason": reason,
                            "warnings": dim_warnings.get(dim_code, []),
                            "normalized_facts": feature_dict,
                        }
                        if dim_status == DIM3_STATUS_NEEDS_SECOND_REVIEW:
                            second_review_raw = await ai_parser.review_dim3_dim4_applicability(
                                question,
                                dim_code=dim_code,
                                analysis_facts=getattr(features, "analysis_facts", {}) or {},
                                initial_feature=feature_dict,
                                initial_status=dim3_status,
                            )
                            normalized_review = normalize_second_review_payload(dim_code, second_review_raw)
                            dimension_status_payload[dim_code]["initial_status"] = dim3_status
                            dimension_status_payload[dim_code]["second_review"] = normalized_review
                            if normalized_review["status"] == SECOND_REVIEW_STATUS_APPLICABLE:
                                dim_result_override = build_second_review_dimension_score(
                                    dim_code,
                                    second_review_raw,
                                    initial_feature=feature_dict,
                                    initial_status=dim3_status,
                                )
                                feature_dict = dict(dim_result_override.details or {})
                                setattr(features, "dim3_information", feature_dict)
                                dim_status = DIM3_STATUS_APPLICABLE
                                reason = dim_result_override.evidence
                                dim_statuses[dim_code] = dim_status
                                dim_warnings.pop(dim_code, None)
                                dimension_status_payload[dim_code].update(
                                    {
                                        "status": dim_status,
                                        "reason": reason,
                                        "warnings": [],
                                        "normalized_facts": feature_dict,
                                        "score_details": dim_result_override.details,
                                    }
                                )
                            else:
                                final_status = (
                                    DIM3_STATUS_NOT_APPLICABLE
                                    if normalized_review["status"] == SECOND_REVIEW_STATUS_NOT_APPLICABLE
                                    else SECOND_REVIEW_STATUS_FAILED_EXCLUDED
                                )
                                reason = _second_review_exclusion_reason(dim_code, normalized_review)
                                exclusion_details = build_second_review_exclusion_details(
                                    dim_code,
                                    second_review_raw,
                                    initial_feature=feature_dict,
                                    initial_status=dim3_status,
                                )
                                dim_statuses[dim_code] = final_status
                                dim_warnings.pop(dim_code, None)
                                dim_reasons[dim_code] = reason
                                dim_confidences[dim_code] = float(normalized_review.get("confidence", 0.0) or 0.0)
                                dim_details[dim_code] = exclusion_details
                                dimension_status_payload[dim_code].update(
                                    {
                                        "status": final_status,
                                        "reason": reason,
                                        "warnings": [],
                                        "normalized_facts": exclusion_details,
                                        "score_details": exclusion_details,
                                    }
                                )
                                question_dim_rows.append(
                                    QuestionDimScore(
                                        question_id=question_id,
                                        dim_code=ModelDimensionCode(dim_code),
                                        dim_score=0.0,
                                        is_applicable=False,
                                        score_evidence=reason,
                                        rule_version="v3.0-accuracy",
                                        confidence=float(normalized_review.get("confidence", 0.0) or 0.0),
                                    )
                                )
                                continue
                        if dim_status != DIM3_STATUS_APPLICABLE:
                            dim_reasons[dim_code] = reason
                            dim_confidences[dim_code] = _dimension_confidence(feature_dict, features)
                            if isinstance(feature_dict, dict):
                                dim_details[dim_code] = feature_dict
                            question_dim_rows.append(
                                QuestionDimScore(
                                    question_id=question_id,
                                    dim_code=ModelDimensionCode(dim_code),
                                    dim_score=0.0,
                                    is_applicable=False,
                                    score_evidence=reason,
                                    rule_version="v3.0-accuracy",
                                    confidence=getattr(features, "confidence", 0.0) or 0.0,
                                )
                            )
                            continue
                    elif dim_code == "dim4":
                        dim4_status = evaluate_dim4_applicability(
                            question.raw_text,
                            feature_dict,
                            llm_confidence=getattr(features, "confidence", 0.0) or 0.0,
                            parse_audit=getattr(question, "parse_audit", None),
                            used_image=getattr(features, "used_image", False),
                            image_fallback=getattr(features, "image_fallback", False),
                            parse_warnings=_collect_applicability_parse_warnings(question),
                        )
                        dim_status = dim4_status["status"]
                        reason = dim4_status["reason"]
                        dim_statuses[dim_code] = dim_status
                        if dim4_status["warnings"]:
                            dim_warnings[dim_code] = list(
                                dict.fromkeys(str(item).strip() for item in dim4_status["warnings"] if str(item).strip())
                            )
                        dimension_status_payload[dim_code] = {
                            "status": dim_status,
                            "reason": reason,
                            "warnings": dim_warnings.get(dim_code, []),
                            "normalized_facts": feature_dict,
                        }
                        if dim_status == DIM4_STATUS_NEEDS_SECOND_REVIEW:
                            second_review_raw = await ai_parser.review_dim3_dim4_applicability(
                                question,
                                dim_code=dim_code,
                                analysis_facts=getattr(features, "analysis_facts", {}) or {},
                                initial_feature=feature_dict,
                                initial_status=dim4_status,
                            )
                            normalized_review = normalize_second_review_payload(dim_code, second_review_raw)
                            dimension_status_payload[dim_code]["initial_status"] = dim4_status
                            dimension_status_payload[dim_code]["second_review"] = normalized_review
                            if normalized_review["status"] == SECOND_REVIEW_STATUS_APPLICABLE:
                                dim_result_override = build_second_review_dimension_score(
                                    dim_code,
                                    second_review_raw,
                                    initial_feature=feature_dict,
                                    initial_status=dim4_status,
                                )
                                feature_dict = dict(dim_result_override.details or {})
                                setattr(features, "dim4_innovation", feature_dict)
                                dim_status = DIM4_STATUS_APPLICABLE
                                reason = dim_result_override.evidence
                                dim_statuses[dim_code] = dim_status
                                dim_warnings.pop(dim_code, None)
                                dimension_status_payload[dim_code].update(
                                    {
                                        "status": dim_status,
                                        "reason": reason,
                                        "warnings": [],
                                        "normalized_facts": feature_dict,
                                        "score_details": dim_result_override.details,
                                    }
                                )
                            else:
                                final_status = (
                                    DIM4_STATUS_NOT_APPLICABLE
                                    if normalized_review["status"] == SECOND_REVIEW_STATUS_NOT_APPLICABLE
                                    else SECOND_REVIEW_STATUS_FAILED_EXCLUDED
                                )
                                reason = _second_review_exclusion_reason(dim_code, normalized_review)
                                exclusion_details = build_second_review_exclusion_details(
                                    dim_code,
                                    second_review_raw,
                                    initial_feature=feature_dict,
                                    initial_status=dim4_status,
                                )
                                dim_statuses[dim_code] = final_status
                                dim_warnings.pop(dim_code, None)
                                dim_reasons[dim_code] = reason
                                dim_confidences[dim_code] = float(normalized_review.get("confidence", 0.0) or 0.0)
                                dim_details[dim_code] = exclusion_details
                                dimension_status_payload[dim_code].update(
                                    {
                                        "status": final_status,
                                        "reason": reason,
                                        "warnings": [],
                                        "normalized_facts": exclusion_details,
                                        "score_details": exclusion_details,
                                    }
                                )
                                question_dim_rows.append(
                                    QuestionDimScore(
                                        question_id=question_id,
                                        dim_code=ModelDimensionCode(dim_code),
                                        dim_score=0.0,
                                        is_applicable=False,
                                        score_evidence=reason,
                                        rule_version="v3.0-accuracy",
                                        confidence=float(normalized_review.get("confidence", 0.0) or 0.0),
                                    )
                                )
                                continue
                        if dim_status != DIM4_STATUS_APPLICABLE:
                            dim_reasons[dim_code] = reason
                            dim_confidences[dim_code] = _dimension_confidence(feature_dict, features)
                            if isinstance(feature_dict, dict):
                                dim_details[dim_code] = feature_dict
                            question_dim_rows.append(
                                QuestionDimScore(
                                    question_id=question_id,
                                    dim_code=ModelDimensionCode(dim_code),
                                    dim_score=0.0,
                                    is_applicable=False,
                                    score_evidence=reason,
                                    rule_version="v3.0-accuracy",
                                    confidence=getattr(features, "confidence", 0.0) or 0.0,
                                )
                            )
                            continue
                    elif dim_code == "dim6":
                        dim6_status = evaluate_dim6_applicability(
                            question.raw_text,
                            feature_dict,
                            llm_confidence=getattr(features, "confidence", 0.0) or 0.0,
                            parse_audit=getattr(question, "parse_audit", None),
                            parse_warnings=_collect_applicability_parse_warnings(question),
                        )
                        dim_status = dim6_status["status"]
                        reason = dim6_status["reason"]
                        dim_statuses[dim_code] = dim_status
                        if dim6_status["warnings"]:
                            dim_warnings[dim_code] = list(
                                dict.fromkeys(str(item).strip() for item in dim6_status["warnings"] if str(item).strip())
                            )
                        dimension_status_payload[dim_code] = {
                            "status": dim_status,
                            "reason": reason,
                            "warnings": dim_warnings.get(dim_code, []),
                            "normalized_facts": feature_dict,
                        }
                        if dim_status in {DIM6_STATUS_NEEDS_SECOND_REVIEW, DIM6_STATUS_REVIEW}:
                            second_review_raw = await ai_parser.review_dim3_dim4_applicability(
                                question,
                                dim_code=dim_code,
                                analysis_facts=getattr(features, "analysis_facts", {}) or {},
                                initial_feature=feature_dict,
                                initial_status=dim6_status,
                            )
                            normalized_review = normalize_second_review_payload(dim_code, second_review_raw)
                            dimension_status_payload[dim_code]["initial_status"] = dim6_status
                            dimension_status_payload[dim_code]["second_review"] = normalized_review
                            if normalized_review["status"] == SECOND_REVIEW_STATUS_APPLICABLE:
                                dim_result_override = build_second_review_dimension_score(
                                    dim_code,
                                    second_review_raw,
                                    initial_feature=feature_dict,
                                    initial_status=dim6_status,
                                )
                                feature_dict = dict(dim_result_override.details or {})
                                setattr(features, "dim6_logic", feature_dict)
                                dim_status = DIM6_STATUS_APPLICABLE
                                reason = dim_result_override.evidence
                                dim_statuses[dim_code] = dim_status
                                dim_warnings.pop(dim_code, None)
                                dimension_status_payload[dim_code].update(
                                    {
                                        "status": dim_status,
                                        "reason": reason,
                                        "warnings": [],
                                        "normalized_facts": feature_dict,
                                        "score_details": dim_result_override.details,
                                    }
                                )
                            else:
                                final_status = (
                                    DIM6_STATUS_NOT_APPLICABLE
                                    if normalized_review["status"] == SECOND_REVIEW_STATUS_NOT_APPLICABLE
                                    else SECOND_REVIEW_STATUS_FAILED_EXCLUDED
                                )
                                reason = _second_review_exclusion_reason(dim_code, normalized_review)
                                exclusion_details = build_second_review_exclusion_details(
                                    dim_code,
                                    second_review_raw,
                                    initial_feature=feature_dict,
                                    initial_status=dim6_status,
                                )
                                dim_statuses[dim_code] = final_status
                                dim_warnings.pop(dim_code, None)
                                dim_reasons[dim_code] = reason
                                dim_confidences[dim_code] = float(normalized_review.get("confidence", 0.0) or 0.0)
                                dim_details[dim_code] = exclusion_details
                                dimension_status_payload[dim_code].update(
                                    {
                                        "status": final_status,
                                        "reason": reason,
                                        "warnings": [],
                                        "normalized_facts": exclusion_details,
                                        "score_details": exclusion_details,
                                    }
                                )
                                question_dim_rows.append(
                                    QuestionDimScore(
                                        question_id=question_id,
                                        dim_code=ModelDimensionCode(dim_code),
                                        dim_score=0.0,
                                        is_applicable=False,
                                        score_evidence=reason,
                                        rule_version="v3.0-accuracy",
                                        confidence=float(normalized_review.get("confidence", 0.0) or 0.0),
                                    )
                                )
                                continue
                        if dim_status != DIM6_STATUS_APPLICABLE:
                            dim_reasons[dim_code] = reason
                            dim_confidences[dim_code] = _dimension_confidence(feature_dict, features)
                            if isinstance(feature_dict, dict):
                                dim_details[dim_code] = feature_dict
                            question_dim_rows.append(
                                QuestionDimScore(
                                    question_id=question_id,
                                    dim_code=ModelDimensionCode(dim_code),
                                    dim_score=0.0,
                                    is_applicable=False,
                                    score_evidence=reason,
                                    rule_version="v3.0-accuracy",
                                    confidence=getattr(features, "confidence", 0.0) or 0.0,
                                )
                            )
                            continue
                    else:
                        if not _dimension_declared_or_inferred(dim_code, features, feature_dict):
                            dim_statuses[dim_code] = "not_applicable"
                            dim_reasons[dim_code] = "未满足该维度适用条件。"
                            dim_confidences[dim_code] = _dimension_confidence(feature_dict, features)
                            if isinstance(feature_dict, dict):
                                dim_details[dim_code] = feature_dict
                            question_dim_rows.append(
                                QuestionDimScore(
                                    question_id=question_id,
                                    dim_code=ModelDimensionCode(dim_code),
                                    dim_score=0.0,
                                    is_applicable=False,
                                    score_evidence="未满足该维度适用条件。",
                                    rule_version="v3.0-accuracy",
                                    confidence=getattr(features, "confidence", 0.0) or 0.0,
                                )
                            )
                            continue
                        dim_statuses[dim_code] = "applicable"

                    dim_result = dim_result_override or scorer.score(feature_dict or {})
                    warning_messages = list(
                        dict.fromkeys(
                            [
                                *dim_warnings.get(dim_code, []),
                                *_collect_dimension_warnings(
                                    question,
                                    features,
                                    feature_dict,
                                    dim_code=dim_code,
                                ),
                            ]
                        )
                    )
                    if warning_messages:
                        dim_warnings[dim_code] = warning_messages
                        if dim_code != "dim4":
                            manual_review_needed = True

                    dim_reason = _build_dimension_reason(dim_code, dim_result, feature_dict, features) or reason
                    if not dim_result.applicable:
                        dim_statuses[dim_code] = "not_applicable"
                        dim_reasons[dim_code] = dim_reason or reason
                        dim_confidences[dim_code] = _dimension_confidence(feature_dict, features)
                        dim_details[dim_code] = dim_result.details or feature_dict
                        if dim_code in dimension_status_payload:
                            dimension_status_payload[dim_code]["status"] = "not_applicable"
                            dimension_status_payload[dim_code]["reason"] = dim_reason or reason
                            dimension_status_payload[dim_code]["warnings"] = dim_warnings.get(dim_code, [])
                        question_dim_rows.append(
                            QuestionDimScore(
                                question_id=question_id,
                                dim_code=ModelDimensionCode(dim_code),
                                dim_score=0.0,
                                is_applicable=False,
                                score_evidence=dim_reason or reason or "该题不适用此维度。",
                                rule_version="v3.0-accuracy",
                                confidence=getattr(features, "confidence", 0.0) or 0.0,
                            )
                        )
                        continue

                    dim_scores[dim_code] = dim_result.score
                    applicable_dims.append(dim_code)
                    dim_statuses[dim_code] = "applicable"
                    dim_reasons[dim_code] = dim_reason or reason
                    dim_confidences[dim_code] = _dimension_confidence(feature_dict, features)
                    dim_details[dim_code] = dim_result.details
                    if dim_code not in dimension_status_payload:
                        dimension_status_payload[dim_code] = {
                            "status": "applicable",
                            "reason": dim_reason or reason,
                            "warnings": dim_warnings.get(dim_code, []),
                            "normalized_facts": feature_dict,
                        }
                    else:
                        dimension_status_payload[dim_code]["status"] = "applicable"
                        dimension_status_payload[dim_code]["reason"] = dim_reason or reason
                        dimension_status_payload[dim_code]["warnings"] = dim_warnings.get(dim_code, [])
                    dimension_status_payload[dim_code]["score_details"] = dim_result.details
                    question_dim_rows.append(
                        QuestionDimScore(
                            question_id=question_id,
                            dim_code=ModelDimensionCode(dim_code),
                            dim_score=dim_result.score,
                            is_applicable=True,
                            score_evidence=dim_reason or reason or dim_result.evidence,
                            rule_version="v3.0-accuracy",
                            confidence=getattr(features, "confidence", 0.0) or 0.0,
                        )
                    )

                if getattr(features, "need_manual_review", False):
                    manual_review_needed = True

                knowledge_tags = (
                    _list_strings(features.get_feature("dim5").get("knowledge_tags", []))
                    if hasattr(features, "get_feature")
                    else []
                )
                aux_tags = []
                if getattr(features, "analysis_facts", None):
                    aux_tags.extend(_list_strings(features.analysis_facts.get("core_methods", [])))
                    aux_tags.extend(_list_strings(features.analysis_facts.get("visual_elements", [])))
                aux_tags.extend(
                    _list_strings(features.get_feature("dim1").get("evidence_tags", []))
                    if hasattr(features, "get_feature")
                    else []
                )
                aux_tags = list(dict.fromkeys(aux_tags))[:12]

                db.add(
                    QuestionTag(
                        question_id=question_id,
                        knowledge_points_main=knowledge_tags[:12],
                        knowledge_points_aux=aux_tags,
                        highest_grade_level=_highest_grade_hint(features),
                        evidence_text=_serialize_question_tag_payload(
                            question,
                            features,
                            dimension_statuses=dimension_status_payload,
                        ),
                        tag_confidence=getattr(features, "confidence", 0.0) or 0.0,
                    )
                )
                for row in question_dim_rows:
                    db.add(row)

                field_context = f"paper={paper_id} question_id={question_id}"
                stored_question_no = _safe_question_no_for_storage(
                    getattr(question, "question_no", ""),
                    fallback=question_id,
                    context=field_context,
                )
                stored_question_label_raw = _safe_optional_storage_text(
                    getattr(question, "question_label_raw", "") or stored_question_no,
                    max_length=50,
                    field_name="question_label_raw",
                    context=field_context,
                ) or stored_question_no
                stored_section_index_raw = _safe_section_index_for_storage(
                    getattr(question, "section_index_raw", ""),
                    context=field_context,
                )

                qds_list.append(
                    QuestionDimensionScore(
                        question_id=question_id,
                        question_no=stored_question_no,
                        question_label_raw=stored_question_label_raw,
                        section_index_raw=stored_section_index_raw,
                        question_display_label=_build_question_display_label(
                            stored_question_no,
                            stored_question_label_raw,
                            stored_section_index_raw,
                        ),
                        score=question.score,
                        dim_scores=dim_scores,
                        applicable_dims=applicable_dims,
                        page_no=question.page_no,
                        question_summary=features.question_summary or _summarize_question(question.raw_text),
                        dim_reasons=dim_reasons,
                        dim_warnings=dim_warnings,
                        dim_confidences=dim_confidences,
                        dim_statuses=dim_statuses,
                        dim_details=dim_details,
                    )
                )

            report = await report_service.generate_report_from_paper(
                paper_id=paper_id,
                question_scores=qds_list,
                paper_title=paper.paper_name if paper else parsed_paper.paper_name,
                report_warnings=paper_report_warnings,
            )

            db.add(
                PaperDimScore(
                    paper_id=paper_id,
                    dim1_score=report["dimension_details"][0]["score"],
                    dim2_score=report["dimension_details"][1]["score"],
                    dim3_score=report["dimension_details"][2]["score"],
                    dim4_score=report["dimension_details"][3]["score"],
                    dim5_score=report["dimension_details"][4]["score"],
                    dim6_score=report["dimension_details"][5]["score"],
                    overall_score=report["difficulty_position"]["overall_score"],
                    valid_dim_count=sum(1 for detail in report["dimension_details"] if detail["level"] > 0),
                    has_sample_warning=any(detail["warning"] for detail in report["dimension_details"]),
                )
            )

            if paper:
                paper.page_count = parsed_paper.page_count
                paper.total_question_count = len(parsed_paper.questions)
                paper.total_score = sum(question.score for question in parsed_paper.questions)
                paper.parse_confidence = parsed_paper.parse_confidence
                paper.need_manual_review = manual_review_needed
                paper.error_message = None

            await db.commit()

        current_stage = "snapshot_save"
        await _update_paper_state(
            paper_id,
            last_stage=current_stage,
            progress_current=None,
            progress_total=None,
            progress_message=None,
        )

        async with AsyncSessionLocal() as db:
            db.add(
                ReportSnapshot(
                    report_id=report["report_id"],
                    paper_id=paper_id,
                    report_json=report,
                )
            )
            paper = await db.get(Paper, paper_id)
            if paper:
                paper.parse_status = ModelParseStatus.PARSE_SUCCESS
                paper.last_stage = current_stage
                paper.error_message = None
                paper.page_count = parsed_paper.page_count
                paper.total_question_count = len(parsed_paper.questions)
                paper.total_score = sum(question.score for question in parsed_paper.questions)
                paper.parse_confidence = parsed_paper.parse_confidence
                paper.need_manual_review = manual_review_needed
            await db.commit()

        logger.info("试卷分析完成 paper=%s", paper_id)
    except Exception as exc:
        error_message = _describe_exception(current_stage, exc)
        try:
            await _update_paper_state(
                paper_id,
                parse_status=ModelParseStatus.PARSE_FAILED,
                last_stage=current_stage,
                error_message=error_message,
                progress_current=None,
                progress_total=None,
                progress_message=None,
            )
        except Exception:
            logger.error("Failed to persist parse_failed state paper=%s stage=%s", paper_id, current_stage, exc_info=True)
        logger.error("处理试卷分析任务失败 paper=%s stage=%s: %s", paper_id, current_stage, exc, exc_info=True)
        raise


def run_paper_analysis_sync(paper_id: str, file_path: str) -> None:
    _run_in_isolated_event_loop(execute_paper_analysis(paper_id=paper_id, file_path=file_path))
