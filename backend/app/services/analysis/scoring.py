from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
from dataclasses import dataclass, field
import math
import logging

logger = logging.getLogger(__name__)


class Dimension(Enum):
    """六维能力维度"""
    COMPUTATION = "computation"
    CONCEPT = "concept"
    LOGIC = "logic"
    SPATIAL = "spatial"
    APPLICATION = "application"
    INNOVATION = "innovation"


@dataclass
class DimensionScore:
    """维度得分详情"""
    dimension: Dimension
    score: float  # 0-100
    confidence: float  # 置信度 0-1
    question_count: int  # 该维度涉及的题目数量
    weight: float  # 权重
    breakdown: Dict[str, Any] = field(default_factory=dict)  # 细分指标


@dataclass
class SixDimensionResult:
    """六维评分结果"""
    computation: DimensionScore
    concept: DimensionScore
    logic: DimensionScore
    spatial: DimensionScore
    application: DimensionScore
    innovation: DimensionScore
    overall_score: float
    confidence: float
    analysis_summary: str

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "dimensions": {
                "computation": self.computation.score,
                "concept": self.concept.score,
                "logic": self.logic.score,
                "spatial": self.spatial.score,
                "application": self.application.score,
                "innovation": self.innovation.score,
            },
            "overall_score": self.overall_score,
            "confidence": self.confidence,
            "summary": self.analysis_summary,
        }


@dataclass
class QuestionDimensionMapping:
    """题目到维度的映射"""
    question_id: str
    dimension_weights: Dict[Dimension, float]  # 各维度权重，总和为1
    difficulty: float  # 1-5
    score: float  # 题目分值


class ScoringEngine:
    """
    六维评分引擎

    负责将试卷题目映射到六个能力维度并进行量化评分。
    """

    # 维度配置
    DIMENSION_CONFIG = {
        Dimension.COMPUTATION: {
            "name": "计算熟练度",
            "description": "口算、笔算、估算等计算能力",
            "keywords": ["计算", "口算", "笔算", "估算", "简便运算", "四则运算"],
            "typical_questions": ["口算题", "竖式计算", "脱式计算", "简便计算"],
        },
        Dimension.CONCEPT: {
            "name": "概念清晰度",
            "description": "数学概念、定义、符号的理解",
            "keywords": ["概念", "定义", "性质", "公式", "定理", "法则", "意义"],
            "typical_questions": ["填空题", "判断题", "概念辨析", "选择题"],
        },
        Dimension.LOGIC: {
            "name": "逻辑推理力",
            "description": "数学推理、证明、归纳能力",
            "keywords": ["推理", "证明", "归纳", "演绎", "逻辑", "规律", "结论"],
            "typical_questions": ["找规律", "证明题", "逻辑推理题", "归纳题"],
        },
        Dimension.SPATIAL: {
            "name": "空间想象力",
            "description": "几何、图形、空间关系理解",
            "keywords": ["图形", "几何", "面积", "体积", "周长", "展开图", "视图"],
            "typical_questions": ["几何题", "图形题", "展开图", "空间想象"],
        },
        Dimension.APPLICATION: {
            "name": "应用实践力",
            "description": "实际问题建模与解决能力",
            "keywords": ["应用题", "实际问题", "解决问题", "生活", "情境", "建模"],
            "typical_questions": ["应用题", "实际问题", "综合题", "解决问题"],
        },
        Dimension.INNOVATION: {
            "name": "创新思维力",
            "description": "开放题、拓展题的创造性解答",
            "keywords": ["创新", "开放题", "拓展", "探究", "创造性", "一题多解", "挑战"],
            "typical_questions": ["开放题", "探究题", "拓展题", "挑战题"],
        },
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def calculate_dimensions(
        self,
        question_mappings: List[QuestionDimensionMapping],
    ) -> SixDimensionResult:
        """
        计算六维评分

        Args:
            question_mappings: 题目到维度的映射列表

        Returns:
            SixDimensionResult: 六维评分结果
        """
        # 初始化各维度得分统计
        dimension_stats = {dim: {"total_weighted_score": 0.0, "total_weight": 0.0, "count": 0}
                           for dim in Dimension}

        # 计算每个维度的加权得分
        for mapping in question_mappings:
            for dimension, weight in mapping.dimension_weights.items():
                if weight > 0:
                    # 考虑题目难度和得分
                    normalized_score = mapping.score * (1 + (mapping.difficulty - 3) * 0.1)
                    weighted_score = normalized_score * weight

                    dimension_stats[dimension]["total_weighted_score"] += weighted_score
                    dimension_stats[dimension]["total_weight"] += weight
                    dimension_stats[dimension]["count"] += 1

        # 计算最终维度得分
        dimension_scores = {}
        for dimension in Dimension:
            stats = dimension_stats[dimension]
            if stats["total_weight"] > 0:
                raw_score = stats["total_weighted_score"] / stats["total_weight"]
                # 归一化到 0-100
                normalized_score = min(max(raw_score * 10, 0), 100)
            else:
                normalized_score = 50  # 默认中等得分

            confidence = min(stats["count"] / 5, 1.0) if stats["count"] > 0 else 0.3

            dimension_scores[dimension] = DimensionScore(
                dimension=dimension,
                score=round(normalized_score, 1),
                confidence=round(confidence, 2),
                question_count=stats["count"],
                weight=round(stats["total_weight"], 2),
                breakdown={
                    "total_weighted_score": round(stats["total_weighted_score"], 2),
                    "average_question_score": round(stats["total_weighted_score"] / max(stats["count"], 1), 2),
                }
            )

        # 计算整体得分和置信度
        overall_score = sum(ds.score for ds in dimension_scores.values()) / 6
        overall_confidence = sum(ds.confidence for ds in dimension_scores.values()) / 6

        # 生成分析摘要
        analysis_summary = self._generate_analysis_summary(dimension_scores, overall_score)

        return SixDimensionResult(
            computation=dimension_scores[Dimension.COMPUTATION],
            concept=dimension_scores[Dimension.CONCEPT],
            logic=dimension_scores[Dimension.LOGIC],
            spatial=dimension_scores[Dimension.SPATIAL],
            application=dimension_scores[Dimension.APPLICATION],
            innovation=dimension_scores[Dimension.INNOVATION],
            overall_score=round(overall_score, 1),
            confidence=round(overall_confidence, 2),
            analysis_summary=analysis_summary,
        )

    def _generate_analysis_summary(
        self,
        dimension_scores: Dict[Dimension, DimensionScore],
        overall_score: float
    ) -> str:
        """生成分析摘要"""
        # 找出最强和最弱维度
        sorted_dims = sorted(
            dimension_scores.items(),
            key=lambda x: x[1].score,
            reverse=True
        )

        strongest = sorted_dims[0]
        weakest = sorted_dims[-1]

        # 生成摘要
        level_desc = "优秀" if overall_score >= 80 else "良好" if overall_score >= 70 else "中等" if overall_score >= 60 else "待提升"

        summary = (
            f"该试卷整体难度评级为【{level_desc}】。"
            f"学生在【{self.DIMENSION_CONFIG[strongest[0]]['name']}】方面表现最为突出，"
            f"得分{strongest[1].score}分；"
            f"而在【{self.DIMENSION_CONFIG[weakest[0]]['name']}】方面相对薄弱，"
            f"得分{weakest[1].score}分，建议针对性加强训练。"
        )

        return summary

    def auto_map_question(
        self,
        question_content: str,
        question_type: str,
    ) -> Dict[Dimension, float]:
        """
        自动将题目映射到维度

        Args:
            question_content: 题目内容
            question_type: 题目类型

        Returns:
            Dict[Dimension, float]: 各维度权重
        """
        content_lower = question_content.lower()
        weights = {dim: 0.0 for dim in Dimension}

        # 基于关键词匹配
        for dimension, config in self.DIMENSION_CONFIG.items():
            for keyword in config["keywords"]:
                if keyword in content_lower:
                    weights[dimension] += 0.2

        # 基于题型匹配
        type_dimension_mapping = {
            "计算": Dimension.COMPUTATION,
            "口算": Dimension.COMPUTATION,
            "竖式": Dimension.COMPUTATION,
            "概念": Dimension.CONCEPT,
            "填空": Dimension.CONCEPT,
            "判断": Dimension.CONCEPT,
            "推理": Dimension.LOGIC,
            "证明": Dimension.LOGIC,
            "找规律": Dimension.LOGIC,
            "几何": Dimension.SPATIAL,
            "图形": Dimension.SPATIAL,
            "面积": Dimension.SPATIAL,
            "应用题": Dimension.APPLICATION,
            "解决问题": Dimension.APPLICATION,
            "开放题": Dimension.INNOVATION,
            "拓展": Dimension.INNOVATION,
            "探究": Dimension.INNOVATION,
        }

        for type_keyword, dimension in type_dimension_mapping.items():
            if type_keyword in question_type or type_keyword in content_lower:
                weights[dimension] += 0.3

        # 归一化
        total_weight = sum(weights.values())
        if total_weight > 0:
            weights = {k: v / total_weight for k, v in weights.items()}
        else:
            # 默认均匀分布
            weights = {dim: 1.0 / len(Dimension) for dim in Dimension}

        return weights
