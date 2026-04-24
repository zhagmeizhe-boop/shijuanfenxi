"""
AI 题目解析服务。

当前实现重点：
- 先抽 facts，再解析六维 judgement
- dim1 / dim2 / dim5 通过本地参考体系做规则校正
- 多模态失败、JSON 截断、关键字段缺失时显式转入低置信复核路径
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.services.llm.moonshot_client import MoonshotClient
from app.services.ocr.base import ParsedPaper, ParsedQuestion, QuestionType
from app.services.parser.prompts import (
    QUESTION_ANALYSIS_SYSTEM_PROMPT,
    QUESTION_ANALYSIS_USER_PROMPT_TEMPLATE,
)
from app.services.parser.reference_standard import get_reference_standard

logger = logging.getLogger(__name__)


VISUAL_SIGNAL_PATTERN = re.compile(
    r"(?:如图|下图|下表|统计图|折线图|柱状图|扇形图|表格|三角形|长方形|正方形|圆|圆柱|圆锥|展开图|截面)"
)
DIMENSION_FEATURE_KEYS = {
    "dim1": "dim1_computation",
    "dim2": "dim2_spatial",
    "dim3": "dim3_information",
    "dim4": "dim4_innovation",
    "dim5": "dim5_knowledge",
    "dim6": "dim6_logic",
}


@dataclass
class QuestionFeatures:
    """题目的六维特征数据。"""

    question_id: str
    question_no: str
    question_summary: str
    analysis_facts: Dict[str, Any] = field(default_factory=dict)
    applicable_dimensions: List[str] = field(default_factory=list)

    dim1_computation: Dict[str, Any] = field(default_factory=dict)
    dim2_spatial: Dict[str, Any] = field(default_factory=dict)
    dim3_information: Dict[str, Any] = field(default_factory=dict)
    dim4_innovation: Dict[str, Any] = field(default_factory=dict)
    dim5_knowledge: Dict[str, Any] = field(default_factory=dict)
    dim6_logic: Dict[str, Any] = field(default_factory=dict)

    confidence: float = 0.0
    reasoning: str = ""
    warnings: List[str] = field(default_factory=list)
    need_manual_review: bool = False
    visual_mode: str = "text_only"
    used_image: bool = False
    image_fallback: bool = False
    calibration_audits: Dict[str, Any] = field(default_factory=dict)

    def get_feature(self, dim_code: str) -> Dict[str, Any]:
        feature_map = {
            "dim1": self.dim1_computation,
            "dim2": self.dim2_spatial,
            "dim3": self.dim3_information,
            "dim4": self.dim4_innovation,
            "dim5": self.dim5_knowledge,
            "dim6": self.dim6_logic,
        }
        return feature_map.get(dim_code, {})


class AIParser:
    """调用 LLM 进行题级六维分析。"""

    def __init__(self, llm_client: Optional[MoonshotClient] = None):
        self.llm = llm_client or self._create_default_client()
        self.reference_standard = get_reference_standard()
        logger.info("AIParser 初始化完成")

    def _create_default_client(self) -> MoonshotClient:
        return MoonshotClient(
            model="kimi-k2.5",
            temperature=0.3,
            max_tokens=2800,
        )

    @staticmethod
    def _normalize_feature_dict(value: Any) -> Dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _normalize_analysis_facts(value: Any) -> Dict[str, Any]:
        if not isinstance(value, dict):
            return {}

        facts = {
            "core_task": str(value.get("core_task", "")).strip(),
            "core_knowledge_points": [],
            "core_methods": [],
            "visual_elements": [],
            "fact_basis": str(value.get("fact_basis", "")).strip(),
            "image_used": 1 if value.get("image_used") in (1, True) else 0,
            "has_sub_items": 1 if value.get("has_sub_items") in (1, True) else 0,
        }

        for key in ("core_knowledge_points", "core_methods", "visual_elements"):
            raw = value.get(key, [])
            if isinstance(raw, list):
                facts[key] = [str(item).strip() for item in raw if str(item).strip()]
        return facts

    @staticmethod
    def _feature_confidence(feature: Dict[str, Any]) -> float:
        try:
            return float(feature.get("applicability_confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _infer_applicable_dimensions(
        cls,
        features: Dict[str, Dict[str, Any]],
        analysis_facts: Dict[str, Any],
    ) -> List[str]:
        inferred: List[str] = []

        dim1 = features["dim1_computation"]
        if (
            dim1.get("has_core_threshold") == 1
            or dim1.get("computation_role") == "core"
            or (
                dim1.get("band")
                and dim1.get("sublevel")
                and dim1.get("computation_role") != "supporting"
                and cls._feature_confidence(dim1) >= 0.5
            )
        ):
            inferred.append("dim1")

        dim2 = features["dim2_spatial"]
        if (
            dim2.get("has_core_spatial_dependency") == 1
            or dim2.get("spatial_role") == "core"
            or (
                dim2.get("band")
                and dim2.get("sublevel")
                and dim2.get("spatial_role") != "supporting"
                and cls._feature_confidence(dim2) >= 0.5
            )
        ):
            inferred.append("dim2")

        dim3 = features["dim3_information"]
        if dim3.get("info_source_type") and dim3.get("relation_complexity"):
            inferred.append("dim3")

        dim4 = features["dim4_innovation"]
        if dim4.get("prototype_distance"):
            inferred.append("dim4")

        dim5 = features["dim5_knowledge"]
        if dim5.get("band") and dim5.get("sublevel"):
            inferred.append("dim5")
        elif analysis_facts.get("core_knowledge_points"):
            inferred.append("dim5")

        dim6 = features["dim6_logic"]
        if dim6.get("key_step_count"):
            inferred.append("dim6")

        return inferred

    @staticmethod
    def _load_image_as_data_url(image_path: str) -> Optional[str]:
        try:
            path = Path(image_path)
            if not path.exists() or not path.is_file():
                return None

            mime_type, _ = mimetypes.guess_type(path.name)
            mime_type = mime_type or "image/jpeg"
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"data:{mime_type};base64,{encoded}"
        except Exception as exc:
            logger.warning("读取题块图片失败 %s: %s", image_path, exc)
            return None

    def _should_attach_image(self, question: ParsedQuestion) -> bool:
        if not question.image_block_url:
            return False
        audit = question.parse_audit
        if audit:
            if audit.image_required_hint or getattr(audit, "image_attach_recommended", False):
                return True
            if getattr(audit, "visual_category", "") in {
                "table_chart",
                "geometry_visual",
                "geometry_context",
                "spatial_3d",
                "explicit_visual",
                "multi_part_layout",
            }:
                return True
        if question.sub_item_candidates:
            return True
        return bool(VISUAL_SIGNAL_PATTERN.search(question.raw_text or ""))

    @staticmethod
    def _format_sub_item_candidates(question: ParsedQuestion) -> str:
        if not question.sub_item_candidates:
            return "无"
        return "；".join(
            f"{candidate.candidate_no}:{candidate.raw_text[:36]}"
            for candidate in question.sub_item_candidates[:4]
        )

    @staticmethod
    def _format_parse_audit(question: ParsedQuestion) -> str:
        if not question.parse_audit:
            return "无"
        audit = question.parse_audit
        notes = [
            f"anchor={audit.anchor_confidence:.2f}",
            f"score={audit.score_confidence:.2f}",
            f"block={audit.block_completeness:.2f}",
            f"image={audit.image_strategy}",
        ]
        if getattr(audit, "visual_category", ""):
            notes.append(f"visual={audit.visual_category}")
        if getattr(audit, "formula_strategy", ""):
            notes.append(f"formula={audit.formula_strategy}")
        if audit.cross_page_merged:
            notes.append("cross_page=1")
        if audit.warning_codes:
            notes.append(f"codes={'/'.join(audit.warning_codes[:4])}")
        return "，".join(notes)

    def _build_prompt(self, question: ParsedQuestion) -> Tuple[List[Dict[str, Any]], bool]:
        prompt_text = QUESTION_ANALYSIS_USER_PROMPT_TEMPLATE.format(
            question_no=question.question_no,
            page_no=question.page_no,
            question_type=getattr(question.question_type, "value", question.question_type),
            has_image="是" if self._should_attach_image(question) else "否",
            ocr_warnings="；".join(question.parse_warnings) if question.parse_warnings else "无",
            sub_item_candidates=self._format_sub_item_candidates(question),
            parse_audit_summary=self._format_parse_audit(question),
            question_text=question.raw_text,
        )

        if self._should_attach_image(question):
            image_data_url = self._load_image_as_data_url(question.image_block_url or "")
            if image_data_url:
                return (
                    [
                        {"role": "system", "content": QUESTION_ANALYSIS_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt_text},
                                {"type": "image_url", "image_url": {"url": image_data_url}},
                            ],
                        },
                    ],
                    True,
                )

        return (
            [
                {"role": "system", "content": QUESTION_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt_text},
            ],
            False,
        )

    @staticmethod
    def _extract_json_body(response: str) -> str:
        json_str = response
        if "```json" in response:
            json_str = response.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in response:
            json_str = response.split("```", 1)[1].split("```", 1)[0]
        return json_str.strip()

    def _repair_truncated_json(self, payload: str) -> str:
        in_string = False
        escape_next = False
        stack: List[str] = []
        last_safe_pos = 0

        for index, char in enumerate(payload):
            if escape_next:
                escape_next = False
                continue
            if char == "\\" and in_string:
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue

            if char in ("{", "["):
                stack.append(char)
            elif char in ("}", "]"):
                if stack:
                    stack.pop()
                    if not stack:
                        last_safe_pos = index + 1
            elif char == "," and len(stack) == 1:
                last_safe_pos = index

        if not stack:
            return payload

        truncated = payload[:last_safe_pos].rstrip().rstrip(",")
        closing = "".join("}" if token == "{" else "]" for token in reversed(stack))
        repaired = truncated + closing
        logger.warning(
            "LLM JSON 响应疑似截断：原始长度=%s 修复后长度=%s",
            len(payload),
            len(repaired),
        )
        return repaired

    @staticmethod
    def _has_required_structure(data: Dict[str, Any]) -> bool:
        if not isinstance(data, dict):
            return False
        if not isinstance(data.get("features"), dict):
            return False
        if not isinstance(data.get("question_summary", ""), str):
            return False
        return True

    def _build_failed_features(
        self,
        question: ParsedQuestion,
        *,
        reason: str,
        warning: Optional[str] = None,
    ) -> QuestionFeatures:
        warnings = [warning] if warning else []
        return QuestionFeatures(
            question_id="",
            question_no=question.question_no,
            question_summary="解析失败",
            confidence=0.0,
            reasoning=reason,
            warnings=warnings,
            need_manual_review=True,
            visual_mode="failed",
        )

    def _validate_dimension_features(
        self,
        normalized_features: Dict[str, Dict[str, Any]],
        analysis_facts: Dict[str, Any],
    ) -> List[str]:
        warnings: List[str] = []

        dim1 = normalized_features["dim1_computation"]
        if dim1.get("band") and not dim1.get("evidence_summary"):
            warnings.append("dim1 缺少证据摘要，当前结果需人工复核。")
        if dim1.get("band") and dim1.get("computation_role") == "supporting":
            warnings.append("dim1 标记为 supporting 但给出了 band，后端将谨慎处理适用性。")

        dim2 = normalized_features["dim2_spatial"]
        if dim2.get("band") and dim2.get("spatial_role") == "supporting":
            warnings.append("dim2 标记为 supporting 但给出了 band，建议人工复核。")

        dim5 = normalized_features["dim5_knowledge"]
        if dim5.get("band") and not (dim5.get("knowledge_tags") or analysis_facts.get("core_knowledge_points")):
            warnings.append("dim5 缺少稳定知识点依据，当前结果需人工复核。")

        return warnings

    def _parse_response(self, response: str, question: ParsedQuestion) -> QuestionFeatures:
        warnings: List[str] = []
        repaired = False

        try:
            payload = self._extract_json_body(response)
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                payload = self._repair_truncated_json(payload)
                data = json.loads(payload)
                repaired = True

            if not self._has_required_structure(data):
                return self._build_failed_features(
                    question,
                    reason="LLM 响应缺少关键字段，无法可靠解析。",
                    warning="LLM 响应结构不完整，已转入人工复核路径。",
                )

            feature_map = data.get("features", {})
            normalized_features = {
                "dim1_computation": self._normalize_feature_dict(feature_map.get("dim1_computation")),
                "dim2_spatial": self._normalize_feature_dict(feature_map.get("dim2_spatial")),
                "dim3_information": self._normalize_feature_dict(feature_map.get("dim3_information")),
                "dim4_innovation": self._normalize_feature_dict(feature_map.get("dim4_innovation")),
                "dim5_knowledge": self._normalize_feature_dict(feature_map.get("dim5_knowledge")),
                "dim6_logic": self._normalize_feature_dict(feature_map.get("dim6_logic")),
            }
            analysis_facts = self._normalize_analysis_facts(data.get("analysis_facts"))

            if repaired:
                warnings.append("LLM 响应疑似被截断，本题已自动转入低置信复核路径。")
            if not analysis_facts:
                warnings.append("LLM 未返回稳定 facts，当前结果需人工复核。")

            applicable_dimensions = data.get("applicable_dimensions", [])
            if not isinstance(applicable_dimensions, list):
                applicable_dimensions = []
                warnings.append("LLM 未返回合法的适用维度列表，已按事实和特征字段推断。")

            question_summary = str(data.get("question_summary", "")).strip() or question.raw_text[:80]

            calibration_audits: Dict[str, Any] = {}
            for dim_code, feature_key in (("dim1", "dim1_computation"), ("dim2", "dim2_spatial"), ("dim5", "dim5_knowledge")):
                normalized_features[feature_key] = self.reference_standard.calibrate_feature(
                    dim_code,
                    normalized_features[feature_key],
                    question_text=question.raw_text,
                    question_summary=question_summary,
                    analysis_facts=analysis_facts,
                )
                calibration_audits[dim_code] = normalized_features[feature_key].get("calibration", {})

            warnings.extend(self._validate_dimension_features(normalized_features, analysis_facts))

            inferred_dimensions = self._infer_applicable_dimensions(normalized_features, analysis_facts)
            applicable_dimensions = sorted(
                {
                    str(item).strip()
                    for item in applicable_dimensions
                    if str(item).strip() in DIMENSION_FEATURE_KEYS
                }
                | set(inferred_dimensions)
            )
            if not applicable_dimensions:
                warnings.append("LLM 未稳定识别到适用维度，当前结果需人工复核。")

            per_dim_warnings: List[str] = []
            need_manual_review = repaired or not analysis_facts
            for feature_key, feature in normalized_features.items():
                warning = str(feature.get("warning", "")).strip()
                if warning:
                    per_dim_warnings.append(f"{feature_key}: {warning}")
                if feature.get("need_manual_review") in (1, True):
                    need_manual_review = True
            warnings.extend(per_dim_warnings)

            return QuestionFeatures(
                question_id="",
                question_no=question.question_no,
                question_summary=question_summary,
                analysis_facts=analysis_facts,
                applicable_dimensions=applicable_dimensions,
                dim1_computation=normalized_features["dim1_computation"],
                dim2_spatial=normalized_features["dim2_spatial"],
                dim3_information=normalized_features["dim3_information"],
                dim4_innovation=normalized_features["dim4_innovation"],
                dim5_knowledge=normalized_features["dim5_knowledge"],
                dim6_logic=normalized_features["dim6_logic"],
                confidence=float(data.get("confidence", 0.0) or 0.0),
                reasoning=str(data.get("reasoning", "") or "").strip(),
                warnings=warnings,
                need_manual_review=need_manual_review or bool(question.parse_warnings),
                calibration_audits=calibration_audits,
            )
        except json.JSONDecodeError as exc:
            logger.error("JSON 解析失败 question=%s response_head=%s", question.question_no, response[:200])
            return self._build_failed_features(question, reason=f"JSON 解析错误: {exc}")
        except Exception as exc:
            logger.error("LLM 响应解析失败 question=%s: %s", question.question_no, exc)
            return self._build_failed_features(question, reason=f"响应解析异常: {exc}")

    async def parse_question(self, question: ParsedQuestion) -> QuestionFeatures:
        logger.info("开始解析题号 %s", question.question_no)
        messages, used_image = self._build_prompt(question)

        try:
            image_fallback = False
            try:
                response = await self.llm.chat(messages)
            except Exception:
                if not used_image:
                    raise
                image_fallback = True
                logger.warning("题号 %s 多模态调用失败，回退到纯文本分析。", question.question_no)
                messages = [
                    {"role": "system", "content": QUESTION_ANALYSIS_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": QUESTION_ANALYSIS_USER_PROMPT_TEMPLATE.format(
                            question_no=question.question_no,
                            page_no=question.page_no,
                            question_type=getattr(question.question_type, "value", question.question_type),
                            has_image="否",
                            ocr_warnings="；".join(question.parse_warnings) if question.parse_warnings else "无",
                            sub_item_candidates=self._format_sub_item_candidates(question),
                            parse_audit_summary=self._format_parse_audit(question),
                            question_text=question.raw_text,
                        ),
                    },
                ]
                response = await self.llm.chat(messages)

            features = self._parse_response(response, question)
            features.used_image = used_image and not image_fallback
            features.image_fallback = image_fallback
            features.visual_mode = "multimodal" if features.used_image else ("text_fallback" if image_fallback else "text_only")

            if image_fallback:
                features.warnings.append("多模态分析失败，当前题目按纯文本回退判断。")
                features.need_manual_review = True

            logger.info(
                "题号 %s 解析完成 confidence=%.2f manual_review=%s",
                question.question_no,
                features.confidence,
                features.need_manual_review,
            )
            return features
        except Exception as exc:
            logger.error("题号 %s 解析失败: %s", question.question_no, exc)
            return self._build_failed_features(question, reason=f"LLM 调用失败: {exc}")

    async def parse_paper(
        self,
        parsed_paper: ParsedPaper,
        concurrency: int = 5,
    ) -> List[QuestionFeatures]:
        questions = parsed_paper.questions
        logger.info("开始批量解析试卷，共 %s 题，最大并发 %s", len(questions), concurrency)

        semaphore = asyncio.Semaphore(concurrency)

        async def parse_with_semaphore(question: ParsedQuestion) -> QuestionFeatures:
            async with semaphore:
                return await self.parse_question(question)

        features_list = await asyncio.gather(*(parse_with_semaphore(question) for question in questions))
        success_count = sum(1 for item in features_list if item.question_summary != "解析失败")
        logger.info("试卷解析完成，成功 %s/%s 题", success_count, len(questions))
        return list(features_list)


def create_ai_parser(
    api_key: Optional[str] = None,
    model: str = "claude-sonnet-4-5",
    base_url: str = "https://one-api.aixuexi.com/v1",
) -> AIParser:
    client = MoonshotClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        temperature=0.3,
        max_tokens=2800,
    )
    return AIParser(llm_client=client)
