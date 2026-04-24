"""
Mock OCR Provider

用于开发和测试环境，模拟 OCR 解析结果
"""

import os
import random
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.services.ocr.base import (
    BaseOCRProvider,
    DimensionCode,
    ParseAudit,
    ParseStatus,
    ParsedPaper,
    ParsedQuestion,
    QuestionBlock,
    QuestionType,
    SubItemCandidate,
    SubQuestion,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class MockOCRProvider(BaseOCRProvider):
    """
    Mock OCR Provider

    用于开发和测试环境，模拟 OCR 识别和解析结果
    无需真实 OCR 服务即可进行开发调试
    """

    # 模拟题目内容库
    SAMPLE_QUESTIONS = [
        {
            "type": QuestionType.FILL_BLANK,
            "content": "3/4 + 2/5 = ______",
            "score": 4.0,
            "applicable_dims": [DimensionCode.COMPUTATION],
        },
        {
            "type": QuestionType.SINGLE_CHOICE,
            "content": "下列哪个数是质数？\nA. 1  B. 9  C. 13  D. 15",
            "score": 3.0,
            "applicable_dims": [DimensionCode.CONCEPT],
        },
        {
            "type": QuestionType.FILL_BLANK,
            "content": "找规律填空: 2, 6, 12, 20, ______, 42",
            "score": 5.0,
            "applicable_dims": [DimensionCode.LOGIC],
        },
        {
            "type": QuestionType.CALCULATION,
            "content": "一个长方形的长是12厘米，宽是8厘米，求它的面积。",
            "score": 6.0,
            "applicable_dims": [DimensionCode.SPATIAL],
        },
        {
            "type": QuestionType.APPLICATION,
            "content": "小明有36颗糖，分给4个小朋友，每人分得多少颗？",
            "score": 5.0,
            "applicable_dims": [DimensionCode.APPLICATION],
        },
        {
            "type": QuestionType.OPEN_ENDED,
            "content": "用不同的方法计算 25 × 12，至少写出两种方法。",
            "score": 8.0,
            "applicable_dims": [DimensionCode.INNOVATION],
        },
        {
            "type": QuestionType.SOLUTION,
            "content": "一本书有120页，小明第一天看了1/4，第二天看了1/3，还剩多少页没看？",
            "score": 8.0,
            "applicable_dims": [DimensionCode.COMPUTATION, DimensionCode.APPLICATION],
        },
        {
            "type": QuestionType.COMPREHENSIVE,
            "content": """根据下图回答问题（图略）：
(1) 图中有几个三角形？
(2) 它们的面积分别是多少？
(3) 最大的三角形面积是最小三角形面积的几倍？""",
            "score": 12.0,
            "applicable_dims": [DimensionCode.SPATIAL, DimensionCode.LOGIC],
        },
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.confidence_range = config.get("confidence_range", (0.85, 0.98)) if config else (0.85, 0.98)
        self.parse_delay = config.get("parse_delay", 2.0) if config else 2.0  # 模拟解析延迟（秒）

    async def parse(self, file_path: str, **kwargs) -> ParsedPaper:
        """
        模拟解析试卷文件

        Args:
            file_path: 文件路径
            **kwargs:
                - paper_name: 试卷名称
                - paper_id: 试卷ID
                - page_count: 页数

        Returns:
            ParsedPaper: 解析后的试卷数据
        """
        import asyncio

        # 模拟解析延迟
        await asyncio.sleep(self.parse_delay)

        # 获取参数
        paper_name = kwargs.get("paper_name", "2024年小学五年级数学分班考试")
        paper_id = kwargs.get("paper_id", str(uuid.uuid4()))
        page_count = kwargs.get("page_count", random.randint(4, 8))

        # 确定文件类型
        file_type = "pdf" if file_path.lower().endswith(".pdf") else "image"

        # 随机生成题目数量（8-15题）
        num_questions = random.randint(8, 15)

        # 生成题目
        questions = []
        total_score = 0.0

        for i in range(num_questions):
            # 随机选择题目模板
            template = random.choice(self.SAMPLE_QUESTIONS)

            # 创建题目
            question = ParsedQuestion(
                question_no=str(i + 1),
                question_type=template["type"],
                raw_text=template["content"],
                question_label_raw=f"{i + 1}.",
                score=template["score"],
                is_optional=random.random() < 0.1,  # 10% 概率是选做题
                include_in_main_score=True,
                parse_confidence=random.uniform(*self.confidence_range),
                applicable_dims=template["applicable_dims"],
                page_no=min(page_count, max(1, i // 3 + 1)),
                image_block_url=None,
                block_bbox={"left": 24, "top": 40 + i * 20, "width": 640, "height": 120},
                question_block=QuestionBlock(
                    page_no=min(page_count, max(1, i // 3 + 1)),
                    bbox={"left": 24, "top": 40 + i * 20, "width": 640, "height": 120},
                    line_count=max(2, template["content"].count("\n") + 1),
                    text_density=0.65,
                ),
                parse_warnings=[],
                parse_audit=ParseAudit(
                    anchor_confidence=0.92,
                    score_confidence=0.90,
                    block_completeness=0.88,
                    image_required_hint=template["type"] in {QuestionType.COMPREHENSIVE, QuestionType.SOLUTION, QuestionType.APPLICATION},
                    image_strategy="text_only",
                    score_source="mock",
                    score_reason="Mock provider 直接提供分值。",
                    line_count=max(2, template["content"].count("\n") + 1),
                ),
                ocr_text_version="mock-v3.0",
                sub_questions=[],
                sub_item_candidates=[],
            )

            # 有30%概率添加子题目
            if random.random() < 0.3:
                num_sub = random.randint(2, 3)
                for j in range(num_sub):
                    sub_no = chr(97 + j)  # a, b, c, ...
                    sub = SubQuestion(
                        question_no=sub_no,
                        raw_text=f"({j+1}) 子题目 {sub_no}",
                        score=template["score"] / num_sub,
                        is_optional=False,
                    )
                    question.sub_questions.append(sub)
                    question.sub_item_candidates.append(
                        SubItemCandidate(
                            candidate_no=sub_no,
                            raw_text=sub.raw_text,
                            confidence=0.85,
                            reason="Mock provider 生成的小问候选。",
                            bbox={
                                "left": 48,
                                "top": 52 + i * 20 + j * 18,
                                "width": 600,
                                "height": 24,
                            },
                        )
                    )

            questions.append(question)
            total_score += template["score"]

        # 计算解析置信度
        avg_confidence = sum(q.parse_confidence for q in questions) / len(questions)

        # 确定解析状态
        parse_status = self.determine_parse_status(avg_confidence)

        # 创建试卷对象
        paper = ParsedPaper(
            paper_name=paper_name,
            total_question_count=num_questions,
            total_score=total_score,
            page_count=page_count,
            parse_status=parse_status,
            parse_confidence=avg_confidence,
            need_manual_review=self.needs_manual_review(parse_status),
            questions=questions,
            file_type=file_type,
            source_file_url=file_path,
        )

        logger.info(f"Mock OCR解析完成: {paper_id}, 题目数: {num_questions}, 总分: {total_score}")
        return paper

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            "status": "healthy",
            "provider": "MockOCRProvider",
            "message": "Mock OCR provider is ready (for development only)",
            "version": "1.0.0",
            "capabilities": {
                "supports_pdf": True,
                "supports_images": True,
                "max_file_size": "50MB",
                "max_pdf_pages": 30,
            },
        }
