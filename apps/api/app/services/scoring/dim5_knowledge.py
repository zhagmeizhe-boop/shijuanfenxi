"""
维度5：知识点广度评分引擎

按题目所属五档及档内层级直接映射分数。
"""

from typing import Any, Dict

from app.services.scoring.base import BaseDimensionScorer, DimensionScore
from app.services.scoring.banded_dimension import score_banded_dimension


class Dim5KnowledgeScorer(BaseDimensionScorer):
    """
    维度5：知识点广度评分器

    只看解出题目必须跨过的最高核心知识门槛。
    """

    DIMENSION_CODE = "dim5"
    DIMENSION_NAME = "知识点广度"

    def __init__(self):
        super().__init__(config=None)

    def _get_default_config(self):
        return {
            "max_score": 10.0,
            "score_granularity": 0.5,
        }

    def _calculate_score(self, features: Dict[str, Any]) -> DimensionScore:
        return score_banded_dimension(
            self,
            features,
            tag_keys=("evidence_tags", "knowledge_tags"),
            invalid_evidence="LLM 未返回合法的知识点广度档位或档内层级，无法计算此维度分数。",
        )
