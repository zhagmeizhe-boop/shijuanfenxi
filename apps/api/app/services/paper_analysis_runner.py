from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, List, Optional

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
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
from app.services.ocr.factory import OCRProviderFactory
from app.services.parser import create_ai_parser
from app.services.report.report_service import ReportService
from app.services.scoring.dim1_applicability import evaluate_dim1_applicability
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
    return OCRProviderFactory.create_provider(
        provider_name=settings.OCR_PROVIDER,
        config={
            "app_id": settings.BAIDU_OCR_APP_ID,
            "api_key": settings.BAIDU_OCR_API_KEY,
            "secret_key": settings.BAIDU_OCR_SECRET_KEY,
            "poppler_path": settings.POPPLER_PATH,
        }
        if settings.OCR_PROVIDER == "baidu"
        else {},
    )


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


def _dimension_declared_or_inferred(dim_code: str, features, feature_dict: dict) -> bool:
    declared = set(getattr(features, "applicable_dimensions", []) or [])
    if dim_code in declared:
        return True

    if dim_code == "dim1":
        return bool(
            feature_dict.get("has_core_threshold") in (1, True)
            or feature_dict.get("computation_role") == "core"
            or (
                feature_dict.get("band")
                and feature_dict.get("sublevel")
                and feature_dict.get("computation_role") != "supporting"
            )
        )
    if dim_code == "dim2":
        return bool(
            feature_dict.get("has_core_spatial_dependency") in (1, True)
            or feature_dict.get("spatial_role") == "core"
            or (
                feature_dict.get("band")
                and feature_dict.get("sublevel")
                and feature_dict.get("spatial_role") != "supporting"
            )
        )
    if dim_code == "dim3":
        return bool(feature_dict.get("info_source_type") and feature_dict.get("relation_complexity"))
    if dim_code == "dim4":
        return bool(feature_dict.get("prototype_distance"))
    if dim_code == "dim5":
        return bool(feature_dict.get("band") and feature_dict.get("sublevel"))
    if dim_code == "dim6":
        return bool(feature_dict.get("key_step_count"))
    return False


def _collect_dimension_warnings(question, features, feature_dict: dict) -> List[str]:
    warnings: List[str] = []
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

    deduped: List[str] = []
    seen = set()
    for item in warnings:
        normalized = str(item).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


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

    if source_parts:
        reason_parts.append(f"依据来源：{' / '.join(source_parts)}。")

    if getattr(features, "analysis_facts", None):
        fact_bits = _list_strings(features.analysis_facts.get("core_knowledge_points", []))[:3]
        if fact_bits:
            reason_parts.append(f"核心事实：{'、'.join(fact_bits)}。")

    return " ".join(part.strip() for part in reason_parts if part.strip())


def _serialize_question_tag_payload(question, features) -> str:
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
    }
    return json.dumps(payload, ensure_ascii=False)


def _highest_grade_hint(features) -> Optional[str]:
    dim5_feature = features.get_feature("dim5") if hasattr(features, "get_feature") else {}
    grade_clues = _list_strings(dim5_feature.get("grade_clues", []))
    if grade_clues:
        return grade_clues[0][:20]
    band = str(dim5_feature.get("band", "")).strip()
    return band[:20] if band else None


def _describe_exception(stage: str, exc: Exception) -> str:
    stage_label = STAGE_LABELS.get(stage, stage)
    exc_type = exc.__class__.__name__
    exc_text = str(exc).strip() or exc_type
    return f"{stage_label}失败（{exc_type}）：{exc_text}"


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

        await db.commit()


async def mark_stale_analysis_tasks(stale_minutes: int | None = None) -> int:
    stale_minutes = stale_minutes or settings.TASK_STALE_MINUTES
    cutoff = datetime.utcnow() - timedelta(minutes=stale_minutes)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Paper).where(
                Paper.parse_status.in_([ModelParseStatus.PENDING, ModelParseStatus.PARSING]),
                Paper.updated_at < cutoff,
            )
        )
        stale_papers = result.scalars().all()
        if not stale_papers:
            return 0

        for paper in stale_papers:
            paper.parse_status = ModelParseStatus.PARSE_FAILED
            paper.last_stage = paper.last_stage or "parsing"
            paper.error_message = "任务中断或 worker 退出，请重新上传"

        await db.commit()
        return len(stale_papers)


async def execute_paper_analysis(paper_id: str, file_path: str) -> None:
    report_service = ReportService()
    ocr_provider = _get_ocr_provider()
    current_stage = "ocr_parse"

    await _update_paper_state(
        paper_id,
        parse_status=ModelParseStatus.PARSING,
        last_stage=current_stage,
        error_message=None,
    )

    try:
        async with AsyncSessionLocal() as db:
            paper = await db.get(Paper, paper_id)
            paper_name = paper.paper_name if paper else f"试卷_{paper_id}"

        parsed_paper = await ocr_provider.parse(
            file_path=file_path,
            paper_name=paper_name,
            paper_id=paper_id,
        )

        await _update_paper_state(
            paper_id,
            parse_confidence=parsed_paper.parse_confidence,
            page_count=parsed_paper.page_count,
            total_question_count=len(parsed_paper.questions),
            total_score=sum(question.score for question in parsed_paper.questions),
        )

        current_stage = "question_persist"
        await _update_paper_state(paper_id, last_stage=current_stage)

        question_records: List[tuple[str, Any]] = []
        async with AsyncSessionLocal() as db:
            for question in parsed_paper.questions:
                question_id = str(uuid.uuid4())
                db.add(
                    Question(
                        question_id=question_id,
                        paper_id=paper_id,
                        page_no=question.page_no,
                        question_no=question.question_no,
                        question_label_raw=getattr(question, "question_label_raw", "") or None,
                        section_index_raw=getattr(question, "section_index_raw", "") or None,
                        question_type=ModelQuestionType(getattr(question.question_type, "value", question.question_type)),
                        raw_text=question.raw_text,
                        image_block_url=question.image_block_url,
                        score=question.score,
                        is_optional=question.is_optional,
                        include_in_main_score=question.include_in_main_score,
                        parse_confidence=question.parse_confidence,
                        applicable_dims=[getattr(item, "value", item) for item in question.applicable_dims],
                        ocr_text_version=question.ocr_text_version,
                    )
                )
                question_records.append((question_id, question))
            await db.commit()

        current_stage = "llm_parse"
        await _update_paper_state(paper_id, last_stage=current_stage)

        api_key = settings.ANTHROPIC_API_KEY or settings.MOONSHOT_API_KEY
        ai_parser = create_ai_parser(
            api_key=api_key,
            model=settings.CLAUDE_MODEL,
            base_url=settings.LLM_BASE_URL,
        )
        question_features = await ai_parser.parse_paper(parsed_paper)
        if len(question_features) != len(question_records):
            raise RuntimeError(
                f"LLM 结果数量不匹配：题目 {len(question_records)}，特征 {len(question_features)}"
            )

        current_stage = "report_build"
        await _update_paper_state(paper_id, last_stage=current_stage)

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
                question_dim_rows: List[QuestionDimScore] = []

                for dim_code, scorer in report_service.scorers.items():
                    feature_dict = features.get_feature(dim_code) if hasattr(features, "get_feature") else {}

                    if dim_code == "dim1":
                        allowed, reason = evaluate_dim1_applicability(
                            question.question_type,
                            question.raw_text,
                            feature_dict,
                            getattr(features, "applicable_dimensions", []),
                        )
                        if not allowed:
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
                        reason = ""

                    dim_result = scorer.score(feature_dict or {})
                    warning_messages = _collect_dimension_warnings(question, features, feature_dict)
                    if warning_messages:
                        dim_warnings[dim_code] = warning_messages
                        manual_review_needed = True

                    dim_reason = _build_dimension_reason(dim_code, dim_result, feature_dict, features) or reason
                    if not dim_result.applicable:
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
                    dim_reasons[dim_code] = dim_reason or reason
                    dim_confidences[dim_code] = _dimension_confidence(feature_dict, features)
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
                        evidence_text=_serialize_question_tag_payload(question, features),
                        tag_confidence=getattr(features, "confidence", 0.0) or 0.0,
                    )
                )
                for row in question_dim_rows:
                    db.add(row)

                qds_list.append(
                    QuestionDimensionScore(
                        question_id=question_id,
                        question_no=question.question_no,
                        question_label_raw=getattr(question, "question_label_raw", "") or question.question_no,
                        section_index_raw=getattr(question, "section_index_raw", "") or None,
                        question_display_label=_build_question_display_label(
                            question.question_no,
                            getattr(question, "question_label_raw", "") or question.question_no,
                            getattr(question, "section_index_raw", "") or None,
                        ),
                        score=question.score,
                        dim_scores=dim_scores,
                        applicable_dims=applicable_dims,
                        page_no=question.page_no,
                        question_summary=features.question_summary or _summarize_question(question.raw_text),
                        dim_reasons=dim_reasons,
                        dim_warnings=dim_warnings,
                        dim_confidences=dim_confidences,
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
        await _update_paper_state(paper_id, last_stage=current_stage)

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
        await _update_paper_state(
            paper_id,
            parse_status=ModelParseStatus.PARSE_FAILED,
            last_stage=current_stage,
            error_message=error_message,
        )
        logger.error("处理试卷分析任务失败 paper=%s stage=%s: %s", paper_id, current_stage, exc, exc_info=True)
        raise


def run_paper_analysis_sync(paper_id: str, file_path: str) -> None:
    asyncio.run(execute_paper_analysis(paper_id=paper_id, file_path=file_path))
