"""
报告服务

处理报告数据的获取和生成
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import logging
from sqlalchemy import select

logger = logging.getLogger(__name__)
from app.services.scoring.dim1_computation import Dim1ComputationScorer
from app.services.scoring.dim2_spatial import Dim2SpatialScorer
from app.services.scoring.dim3_information import Dim3InformationScorer
from app.services.scoring.dim4_innovation import Dim4InnovationScorer
from app.services.scoring.dim5_knowledge import Dim5KnowledgeScorer
from app.services.scoring.dim6_logic import Dim6LogicScorer
from app.services.scoring.paper_aggregator import PaperAggregator, QuestionDimensionScore


class ReportService:
    """报告服务"""

    def __init__(self):
        self.aggregator = PaperAggregator()
        self.scorers = {
            "dim1": Dim1ComputationScorer(),
            "dim2": Dim2SpatialScorer(),
            "dim3": Dim3InformationScorer(),
            "dim4": Dim4InnovationScorer(),
            "dim5": Dim5KnowledgeScorer(),
            "dim6": Dim6LogicScorer(),
        }

    @staticmethod
    def _build_question_display_label(
        question_no: str,
        question_label_raw: Optional[str] = None,
        section_index_raw: Optional[str] = None,
    ) -> str:
        normalized_section = str(section_index_raw or "").strip()
        normalized_question_no = str(question_no or "").strip()
        if normalized_section and normalized_question_no:
            return f"{normalized_section}-{normalized_question_no}"

        normalized_raw_label = str(question_label_raw or "").strip()
        if normalized_raw_label:
            return normalized_raw_label

        return normalized_question_no

    @staticmethod
    def _dimension_scores_from_db(dim_scores) -> Dict[str, float]:
        return {
            "dim1": dim_scores.dim1_score,
            "dim2": dim_scores.dim2_score,
            "dim3": dim_scores.dim3_score,
            "dim4": dim_scores.dim4_score,
            "dim5": dim_scores.dim5_score,
            "dim6": dim_scores.dim6_score,
        }

    @staticmethod
    def _safe_json_loads(raw: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(raw or "")
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _parse_warning_messages(audit_payload: Dict[str, Any]) -> List[str]:
        warnings: List[str] = []
        for item in audit_payload.get("parse_warnings", []) or []:
            text = str(item).strip()
            if text:
                warnings.append(text)
        for item in audit_payload.get("warnings", []) or []:
            text = str(item).strip()
            if text:
                warnings.append(text)
        if audit_payload.get("image_fallback"):
            warnings.append("多模态分析失败，当前题目按纯文本回退判断。")
        return list(dict.fromkeys(warnings))

    @staticmethod
    def _build_counted_reason(score_evidence: str, audit_payload: Dict[str, Any]) -> str:
        source_parts: List[str] = []
        if audit_payload.get("used_image"):
            source_parts.append("图片")
        elif audit_payload.get("image_fallback"):
            source_parts.append("纯文本回退")
        else:
            source_parts.append("文本")

        calibration_audits = audit_payload.get("calibration_audits", {})
        if isinstance(calibration_audits, dict):
            candidates = []
            for dim_code, payload in calibration_audits.items():
                if isinstance(payload, dict) and payload.get("band_source"):
                    candidates.append(f"{dim_code}:{payload.get('band_source')}")
            if candidates:
                source_parts.append("规则:" + " / ".join(candidates[:2]))

        reason = (score_evidence or "").strip()
        source_text = f"依据来源：{' / '.join(source_parts)}。"
        if reason:
            return f"{reason} {source_text}".strip()
        return source_text

    def _build_question_scores_from_rows(
        self,
        questions,
        tag_map: Dict[str, Any],
        dim_score_rows,
    ) -> List[QuestionDimensionScore]:
        grouped_dim_rows: Dict[str, List[Any]] = {}
        for row in dim_score_rows:
            grouped_dim_rows.setdefault(row.question_id, []).append(row)

        question_scores: List[QuestionDimensionScore] = []
        for question in questions:
            qid = question.question_id
            audit_payload = self._safe_json_loads(getattr(tag_map.get(qid), "evidence_text", ""))
            rows = grouped_dim_rows.get(qid, [])

            dim_scores: Dict[str, float] = {}
            applicable_dims: List[str] = []
            dim_reasons: Dict[str, str] = {}
            dim_warnings: Dict[str, List[str]] = {}
            dim_confidences: Dict[str, float] = {}
            audit_warnings = self._parse_warning_messages(audit_payload)

            for row in rows:
                dim_code = getattr(row.dim_code, "value", row.dim_code)
                if row.is_applicable:
                    dim_scores[dim_code] = row.dim_score
                    applicable_dims.append(dim_code)
                    dim_reasons[dim_code] = self._build_counted_reason(row.score_evidence or "", audit_payload)
                    try:
                        dim_confidences[dim_code] = float(row.confidence or 0.0)
                    except (TypeError, ValueError):
                        dim_confidences[dim_code] = 0.0
                if audit_warnings:
                    dim_warnings[dim_code] = audit_warnings

            question_scores.append(
                QuestionDimensionScore(
                    question_id=qid,
                    question_no=question.question_no,
                    question_label_raw=(
                        getattr(question, "question_label_raw", None)
                        or audit_payload.get("question_label_raw")
                        or question.question_no
                    ),
                    section_index_raw=(
                        getattr(question, "section_index_raw", None)
                        or audit_payload.get("section_index_raw")
                    ),
                    question_display_label=(
                        audit_payload.get("question_display_label")
                        or self._build_question_display_label(
                            question.question_no,
                            getattr(question, "question_label_raw", None)
                            or audit_payload.get("question_label_raw"),
                            getattr(question, "section_index_raw", None)
                            or audit_payload.get("section_index_raw"),
                        )
                    ),
                    score=question.score,
                    dim_scores=dim_scores,
                    applicable_dims=applicable_dims,
                    page_no=question.page_no,
                    question_summary=(audit_payload.get("analysis_facts", {}) or {}).get("core_task", "") or question.raw_text[:80],
                    dim_reasons=dim_reasons,
                    dim_warnings=dim_warnings,
                    dim_confidences=dim_confidences,
                )
            )

        return question_scores

    def _build_dimension_details_from_aggregated(self, aggregated: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {
                "code": dim_code,
                "name": summary.dimension_name,
                "score": round(summary.paper_score, 1),
                "level": summary.level,
                "level_label": summary.level_label,
                "evidence": summary.evidence,
                "warning": bool(summary.warning_messages or summary.sample_warning),
                "counted_questions": summary.counted_questions,
            }
            for dim_code, summary in aggregated.items()
        ]

    def _build_report_payload(
        self,
        *,
        paper_id: str,
        paper_title: str,
        dimension_details: List[Dict[str, Any]],
        generated_at: Optional[str] = None,
        report_warnings: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        valid_dimension_details = [detail for detail in dimension_details if detail["level"] > 0]
        overall_score = (
            sum(detail["score"] for detail in valid_dimension_details) / len(valid_dimension_details)
            if valid_dimension_details
            else 0.0
        )
        difficulty_level = self._calculate_difficulty_level(overall_score)
        detail_by_code = {detail["code"]: detail for detail in dimension_details}

        return {
            "report_id": paper_id,
            "paper_id": paper_id,
            "paper_title": paper_title,
            "generated_at": generated_at or datetime.now().isoformat(),
            "dimensions": {
                "computation": round(detail_by_code.get("dim1", {}).get("score", 0.0) * 10, 1),
                "concept": round(detail_by_code.get("dim2", {}).get("score", 0.0) * 10, 1),
                "logic": round(detail_by_code.get("dim3", {}).get("score", 0.0) * 10, 1),
                "spatial": round(detail_by_code.get("dim4", {}).get("score", 0.0) * 10, 1),
                "application": round(detail_by_code.get("dim5", {}).get("score", 0.0) * 10, 1),
                "innovation": round(detail_by_code.get("dim6", {}).get("score", 0.0) * 10, 1),
            },
            "dimension_details": dimension_details,
            "report_warnings": list(report_warnings or []),
            "difficulty_position": {
                "level": difficulty_level,
                "label": self._get_difficulty_label(difficulty_level),
                "overall_score": round(overall_score, 1),
                "target_students": self._get_target_students(difficulty_level),
                "description": self._get_difficulty_description(difficulty_level),
                "dimension_distribution": [
                    {"code": "dim1", "name": "数学运算", "percentage": 17, "color": "#3B82F6"},
                    {"code": "dim2", "name": "几何直观", "percentage": 16, "color": "#8B5CF6"},
                    {"code": "dim3", "name": "信息提取", "percentage": 17, "color": "#EC4899"},
                    {"code": "dim4", "name": "实践创新", "percentage": 17, "color": "#10B981"},
                    {"code": "dim5", "name": "知识广度", "percentage": 16, "color": "#F59E0B"},
                    {"code": "dim6", "name": "逻辑链条", "percentage": 17, "color": "#EF4444"},
                ],
            },
            "benchmark_comparisons": [],
            "knowledge_points": [],
            "representative_questions": [],
            "overall_summary": (
                f"本试卷综合难度为{self._get_difficulty_label(difficulty_level)}，"
                f"综合评分{round(overall_score, 1)}分。"
            ),
            "recommendations": [
                "根据各维度得分情况，有针对性地进行复习和训练",
                "重点关注得分较低的维度，加强相关知识点的学习",
                "适当练习高难度题目，提升综合解题能力",
            ],
        }

    @staticmethod
    def _score_to_dimension_level(score: float) -> tuple[int, str]:
        if score <= 0:
            return 0, "N/A"
        if score <= 2.0:
            return 1, "简单"
        if score <= 4.0:
            return 2, "较简单"
        if score <= 6.0:
            return 3, "中等"
        if score <= 8.0:
            return 4, "较难"
        return 5, "困难"

    async def get_report_data(self, paper_id: str) -> Optional[Dict[str, Any]]:
        """
        从数据库读取真实报告数据

        Args:
            paper_id: 试卷ID（前端上传后导航使用的 ID）

        Returns:
            Dict: 报告数据，格式与前端 FullReportData 匹配；未找到时返回 None
        """
        from app.core.database import AsyncSessionLocal
        from app.models import Paper, PaperDimScore, Question, QuestionDimScore, QuestionTag, ReportSnapshot

        async with AsyncSessionLocal() as db:
            paper = await db.get(Paper, paper_id)
            if not paper:
                return None

            try:
                snapshot_result = await db.execute(
                    select(ReportSnapshot)
                    .where(ReportSnapshot.paper_id == paper_id)
                    .order_by(ReportSnapshot.created_at.desc())
                )
                latest_snapshot = snapshot_result.scalars().first()
            except Exception as exc:
                latest_snapshot = None
                logger.warning("读取报告快照失败 paper=%s: %s", paper_id, exc, exc_info=True)

            if latest_snapshot and isinstance(latest_snapshot.report_json, dict):
                report_json = dict(latest_snapshot.report_json)
                report_json.setdefault("report_id", latest_snapshot.report_id)
                report_json.setdefault("paper_id", paper_id)
                report_json["paper_title"] = paper.paper_name
                report_json.setdefault("generated_at", latest_snapshot.created_at.isoformat())
                report_json.setdefault("benchmark_comparisons", [])
                report_json.setdefault("knowledge_points", [])
                report_json.setdefault("representative_questions", [])
                report_json.setdefault("report_warnings", [])
                for detail in report_json.get("dimension_details", []):
                    detail.setdefault("counted_questions", [])
                    detail["warning"] = bool(detail.get("warning"))
                return report_json

            dim_scores = await db.get(PaperDimScore, paper_id)
            if not dim_scores:
                # 试卷存在但评分尚未完成
                return None
            question_result = await db.execute(
                select(Question)
                .where(Question.paper_id == paper_id)
                .order_by(Question.page_no.asc(), Question.question_no.asc())
            )
            questions = question_result.scalars().all()

            tag_result = await db.execute(
                select(QuestionTag)
                .join(Question, Question.question_id == QuestionTag.question_id)
                .where(Question.paper_id == paper_id)
            )
            tag_map = {row.question_id: row for row in tag_result.scalars().all()}

            dim_row_result = await db.execute(
                select(QuestionDimScore)
                .join(Question, Question.question_id == QuestionDimScore.question_id)
                .where(Question.paper_id == paper_id)
            )
            dim_score_rows = dim_row_result.scalars().all()

        if questions and dim_score_rows:
            rebuilt_question_scores = self._build_question_scores_from_rows(
                questions,
                tag_map,
                dim_score_rows,
            )
            aggregated = self.aggregator.aggregate_all_dimensions(rebuilt_question_scores)
            dimension_details = self._build_dimension_details_from_aggregated(aggregated)
            return self._build_report_payload(
                paper_id=paper_id,
                paper_title=paper.paper_name,
                dimension_details=dimension_details,
                report_warnings=[],
            )

        scores = self._dimension_scores_from_db(dim_scores)
        dimension_details = []
        for dim_code, summary_score in scores.items():
            level, level_label = self._score_to_dimension_level(summary_score)
            dimension_details.append(
                {
                    "code": dim_code,
                    "name": self.aggregator.DIMENSION_NAMES[dim_code],
                    "score": round(summary_score, 1),
                    "level": level,
                    "level_label": level_label,
                    "evidence": "",
                    "warning": False,
                    "counted_questions": [],
                }
            )
        return self._build_report_payload(
            paper_id=paper_id,
            paper_title=paper.paper_name,
            dimension_details=dimension_details,
            report_warnings=[],
        )

    def _generate_mock_report(self, report_id: str) -> Dict[str, Any]:
        """生成Mock报告数据"""
        return {
            "report_id": report_id,
            "paper_id": "paper-001",
            "paper_title": "2024年春季六年级数学分班考试卷",
            "generated_at": datetime.now().isoformat(),

            "dimensions": {
                "computation": 75,
                "concept": 82,
                "logic": 68,
                "spatial": 70,
                "application": 65,
                "innovation": 58,
            },

            "dimension_details": [
                {
                    "code": "dim1",
                    "name": "计算熟练度",
                    "score": 7.5,
                    "level": 4,
                    "level_label": "较难",
                    "evidence": "数值类型为带分数/小数混合，运算层数为3-4层，无变形难度，特殊运算包含分数小数互化，易错程度为中等。基础分7.0，因分数小数互化+0.5。",
                },
                {
                    "code": "dim2",
                    "name": "概念清晰度",
                    "score": 6.0,
                    "level": 3,
                    "level_label": "中等",
                    "evidence": "图形熟悉度为标准图形，需要添加1条辅助线，图形变换包含单一变换，空间重构程度为中等。非强制规则判定。",
                },
                {
                    "code": "dim3",
                    "name": "逻辑推理力",
                    "score": 8.0,
                    "level": 4,
                    "level_label": "较难",
                    "evidence": "信息来源类型为图文混合，信息数量为中等，不含噪音信息，条件分散，需要数学建模，关系复杂度为高。强制规则触发：条件分散+建模需求+高复杂度。",
                },
                {
                    "code": "dim4",
                    "name": "空间想象力",
                    "score": 7.0,
                    "level": 4,
                    "level_label": "较难",
                    "evidence": "非教材原型，存在情境伪装，需要策略选择。创新程度为中等，基础分5.0，情境伪装+0.5，策略选择+1.0，开放性质+0.5。",
                },
                {
                    "code": "dim5",
                    "name": "应用实践力",
                    "score": 5.5,
                    "level": 3,
                    "level_label": "中等",
                    "evidence": "最高知识点学段：六年级上册，基础分4.5；去重知识点数：5个，修正分+0.5；因知识点数量达到4-6个，判定为中等水平。",
                    "warning": True,
                },
                {
                    "code": "dim6",
                    "name": "创新思维力",
                    "score": 8.5,
                    "level": 5,
                    "level_label": "困难",
                    "evidence": "关键步骤数4-5，基础分7.0；存在隐藏关系+0.5，需要反向推理+0.5，需要验证+0.5；因存在分支讨论，最低分限制为6.5。最终得分8.5。",
                },
            ],

            "difficulty_position": {
                "level": 4,
                "label": "拔高卷",
                "overall_score": 7.1,
                "target_students": "适合基础扎实、希望进一步拔高的学生。本卷强调思维方法的灵活运用，适合准备参加择校考试或希望进入重点班的学生。",
                "description": "面向思维突破阶段，突出方法创新",
                "dimension_distribution": [
                    {"code": "dim1", "name": "计算", "percentage": 18, "color": "#3B82F6"},
                    {"code": "dim2", "name": "概念", "percentage": 16, "color": "#8B5CF6"},
                    {"code": "dim3", "name": "逻辑", "percentage": 20, "color": "#EC4899"},
                    {"code": "dim4", "name": "空间", "percentage": 14, "color": "#10B981"},
                    {"code": "dim5", "name": "应用", "percentage": 16, "color": "#F59E0B"},
                    {"code": "dim6", "name": "创新", "percentage": 16, "color": "#EF4444"},
                ],
            },

            "benchmark_comparisons": [
                {"name": "区平均分", "score": 6.2, "comparison": "higher", "difference": 0.9},
                {"name": "市重点班", "score": 7.5, "comparison": "lower", "difference": 0.4},
                {"name": "省实验班", "score": 8.1, "comparison": "lower", "difference": 1.0},
            ],

            "knowledge_points": [
                {"id": "kp1", "name": "分数运算", "level": "六年级上册", "count": 5, "related_questions": ["Q1", "Q2", "Q5"]},
                {"id": "kp2", "name": "比和比例", "level": "六年级上册", "count": 3, "related_questions": ["Q3", "Q7"]},
                {"id": "kp3", "name": "圆的认识", "level": "六年级上册", "count": 4, "related_questions": ["Q4", "Q6", "Q8"]},
                {"id": "kp4", "name": "百分数应用", "level": "六年级下册", "count": 2, "related_questions": ["Q9"]},
                {"id": "kp5", "name": "圆柱圆锥", "level": "六年级下册", "count": 3, "related_questions": ["Q10", "Q11"]},
            ],

            "representative_questions": [
                {
                    "id": "Q1",
                    "question_no": "第1题",
                    "content": "计算：\\frac{3}{4} + \\frac{2}{5} - \\frac{1}{2}",
                    "dimension_code": "dim1",
                    "dimension_name": "计算熟练度",
                    "score": 7.5,
                    "level": 4,
                    "evidence": "分数运算，需要通分，复杂度中等",
                },
                {
                    "id": "Q3",
                    "question_no": "第3题",
                    "content": "甲、乙两数的比是3:5，它们的和是48，求这两个数。",
                    "dimension_code": "dim3",
                    "dimension_name": "逻辑推理力",
                    "score": 8.0,
                    "level": 4,
                    "evidence": "需要理解比例关系并建立方程求解",
                },
            ],

            "overall_summary": "本试卷整体难度较高，以拔高为主，注重考查学生的综合应用能力和创新思维。计算部分以分数运算为主，概念部分涉及几何与代数，逻辑部分强调推理建模。",
            "recommendations": [
                "建议学生重点复习分数运算和比例应用",
                "加强逻辑推理和建模能力的训练",
                "适当拓展几何辅助线的添加技巧",
                "关注实际应用题的解题策略",
            ],
        }

    async def generate_report_from_paper(
        self,
        paper_id: str,
        question_scores: List[Dict[str, Any]],
        paper_title: Optional[str] = None,
        dim5_override=None,
        report_warnings: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        从试卷和题目分数生成完整报告

        Args:
            paper_id: 试卷ID
            question_scores: 题目分数列表（六个维度均按题级评分后统一聚合）
            paper_title: 试卷标题
            dim5_override: 兼容旧调用的 dim5 覆盖结果；当前主链路不再依赖

        Returns:
            Dict: 完整报告数据
        """
        from app.services.scoring.paper_aggregator import PaperDimensionSummary

        # 汇总各维度分数
        aggregated = self.aggregator.aggregate_all_dimensions(question_scores)

        # 用试卷级 dim5 覆盖聚合结果
        if dim5_override is not None:
            aggregated["dim5"] = PaperDimensionSummary(
                dimension_code="dim5",
                dimension_name="知识点广度",
                paper_score=dim5_override.score,
                level=dim5_override.level,
                level_label=dim5_override.level_label,
                total_question_score=0.0,
                question_count=0,
                sample_warning=False,
                evidence=dim5_override.evidence,
                warning_messages=[],
                counted_questions=[],
            )

        dimension_details = self._build_dimension_details_from_aggregated(aggregated)
        report = self._build_report_payload(
            paper_id=paper_id,
            paper_title=paper_title or f"试卷 {paper_id}",
            dimension_details=dimension_details,
            generated_at=datetime.now().isoformat(),
            report_warnings=report_warnings or [],
        )
        report["report_id"] = f"rpt-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        return report

    def _calculate_difficulty_level(self, overall_score: float) -> int:
        """计算难度等级"""
        if overall_score <= 2.0:
            return 1
        elif overall_score <= 4.0:
            return 2
        elif overall_score <= 6.0:
            return 3
        elif overall_score <= 8.0:
            return 4
        else:
            return 5

    def _get_difficulty_label(self, level: int) -> str:
        """获取难度标签"""
        labels = {
            1: "基础卷",
            2: "常规卷",
            3: "提升卷",
            4: "拔高卷",
            5: "选拔卷",
        }
        return labels.get(level, "未知")

    def _get_target_students(self, level: int) -> str:
        """获取目标学生描述"""
        descriptions = {
            1: "适合基础薄弱、需要巩固基本概念的学生。",
            2: "适合基础一般、希望稳步提升的学生。",
            3: "适合基础较好、希望挑战自我的学生。",
            4: "适合基础扎实、希望进一步拔高的学生。",
            5: "适合成绩优秀、准备参加竞赛选拔的学生。",
        }
        return descriptions.get(level, "")

    def _get_difficulty_description(self, level: int) -> str:
        """获取难度描述"""
        descriptions = {
            1: "侧重基础知识的掌握和基本技能的训练",
            2: "注重知识点的全面覆盖和基本应用能力",
            3: "强调知识的灵活运用和综合解题能力",
            4: "突出思维方法的创新和复杂问题解决",
            5: "挑战高难度思维和极限解题技巧",
        }
        return descriptions.get(level, "")
