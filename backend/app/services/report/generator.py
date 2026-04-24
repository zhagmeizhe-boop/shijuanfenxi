from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class PaperInfo:
    """试卷基础信息"""
    title: str
    grade: str
    subject: str
    total_score: int
    question_count: int
    estimated_time: int  # 预计完成时间（分钟）
    source: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass
class DifficultyLevel:
    """难度等级"""
    overall: str  # very_easy, easy, medium, hard, very_hard
    score: float  # 0-100
    description: str


@dataclass
class KnowledgePoint:
    """知识点"""
    name: str
    category: str
    count: int  # 题目数量
    difficulty_avg: float  # 平均难度


@dataclass
class RepresentativeQuestion:
    """各维度代表题"""
    id: str
    dimension: str
    content: str
    difficulty: float
    score: float


@dataclass
class ComparisonData:
    """对比数据"""
    averageScore: float
    currentScore: float
    percentile: float  # 百分位排名
    benchmark: str  # 参照系名称


@dataclass
class AnalysisReport:
    """完整分析报告"""
    id: str
    paper_info: PaperInfo
    dimensions: Dict[str, float]  # 六维得分
    difficulty: DifficultyLevel
    target_students: List[str]
    comparison: ComparisonData
    knowledge_points: List[KnowledgePoint]
    representative_questions: List[RepresentativeQuestion]
    generated_at: datetime
    version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "paper_info": {
                "title": self.paper_info.title,
                "grade": self.paper_info.grade,
                "subject": self.paper_info.subject,
                "total_score": self.paper_info.total_score,
                "question_count": self.paper_info.question_count,
                "estimated_time": self.paper_info.estimated_time,
                "source": self.paper_info.source,
                "created_at": self.paper_info.created_at.isoformat() if self.paper_info.created_at else None,
            },
            "dimensions": self.dimensions,
            "difficulty": {
                "overall": self.difficulty.overall,
                "score": self.difficulty.score,
                "description": self.difficulty.description,
            },
            "target_students": self.target_students,
            "comparison": {
                "averageScore": self.comparison.averageScore,
                "currentScore": self.comparison.currentScore,
                "percentile": self.comparison.percentile,
                "benchmark": self.comparison.benchmark,
            },
            "knowledge_points": [
                {
                    "name": kp.name,
                    "category": kp.category,
                    "count": kp.count,
                    "difficulty_avg": kp.difficulty_avg,
                }
                for kp in self.knowledge_points
            ],
            "representative_questions": [
                {
                    "id": rq.id,
                    "dimension": rq.dimension,
                    "content": rq.content,
                    "difficulty": rq.difficulty,
                    "score": rq.score,
                }
                for rq in self.representative_questions
            ],
            "generated_at": self.generated_at.isoformat(),
            "version": self.version,
        }


class ReportGenerator:
    """
    分析报告生成器

    将分析结果转换为标准格式的报告
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def generate_report(
        self,
        paper_info: PaperInfo,
        dimension_scores: Dict[str, float],
        difficulty: DifficultyLevel,
        knowledge_points: List[KnowledgePoint],
        comparison: ComparisonData,
        representative_questions: List[RepresentativeQuestion],
    ) -> AnalysisReport:
        """
        生成完整分析报告
        """
        report_id = f"RPT-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # 确定目标学生群体
        target_students = self._determine_target_students(
            difficulty, dimension_scores
        )

        report = AnalysisReport(
            id=report_id,
            paper_info=paper_info,
            dimensions=dimension_scores,
            difficulty=difficulty,
            target_students=target_students,
            comparison=comparison,
            knowledge_points=knowledge_points,
            representative_questions=representative_questions,
            generated_at=datetime.now(),
        )

        self.logger.info(f"Generated analysis report: {report_id}")
        return report

    def _determine_target_students(
        self,
        difficulty: DifficultyLevel,
        dimension_scores: Dict[str, float],
    ) -> List[str]:
        """
        根据分析结果确定适合的学生群体
        """
        target_students = []

        # 基于难度
        if difficulty.overall in ["very_easy", "easy"]:
            target_students.append("基础薄弱需巩固学生")
        elif difficulty.overall == "medium":
            target_students.append("成绩中等学生")
        else:
            target_students.append("成绩优异需拔高学生")

        # 基于维度分析
        avg_score = sum(dimension_scores.values()) / len(dimension_scores)
        if avg_score >= 80:
            target_students.append("学习能力较强的学生")
        elif avg_score >= 60:
            target_students.append("需要系统训练的学生")

        return target_students
