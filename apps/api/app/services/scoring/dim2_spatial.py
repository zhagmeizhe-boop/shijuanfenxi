"""
维度2：几何直观与空间想象评分引擎

按题目所属五档及档内层级直接映射分数。
"""

from typing import Any, Dict

from app.services.scoring.base import BaseDimensionScorer, DimensionScore
from app.services.scoring.banded_dimension import score_banded_dimension


class Dim2SpatialScorer(BaseDimensionScorer):
    """
    维度2：几何直观与空间想象评分器

    只看解出题目必须跨过的最高核心几何/空间门槛。
    """

    DIMENSION_CODE = "dim2"
    DIMENSION_NAME = "几何直观与空间想象"

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
            invalid_evidence="LLM 未返回合法的几何直观与空间想象档位或档内层级，无法计算此维度分数。",
        )
