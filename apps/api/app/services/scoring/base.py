"""
六维评分引擎 - 基础模块

提供评分引擎的基类和通用工具
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import json


class ScoreLevel(Enum):
    """得分等级"""
    LEVEL_1 = 1  # 0-2.0 简单
    LEVEL_2 = 2  # 2.5-4.0 较简单
    LEVEL_3 = 3  # 4.5-6.0 中等
    LEVEL_4 = 4  # 6.5-8.0 较难
    LEVEL_5 = 5  # 8.5-10.0 困难


@dataclass
class DimensionScore:
    """维度评分结果"""
    dimension_code: str
    score: float
    level: int
    level_label: str
    evidence: str
    applicable: bool = True
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension_code": self.dimension_code,
            "score": self.score,
            "level": self.level,
            "level_label": self.level_label,
            "evidence": self.evidence,
            "applicable": self.applicable,
            "details": self.details,
        }


class BaseDimensionScorer:
    """维度评分器基类"""

    DIMENSION_CODE: str = ""
    DIMENSION_NAME: str = ""
    CONFIG_PATH: str = ""

    # 各等级的代表分值（用于 override 规则中指定"至少N档"时取分）
    LEVEL_SCORE_MIDPOINTS: Dict[int, float] = {1: 1.0, 2: 3.0, 3: 5.0, 4: 7.0, 5: 9.0}

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or self._load_default_config()

    @property
    def dimension_code(self) -> str:
        """返回维度代码（兼容子类中 self.dimension_code 的用法）"""
        return self.DIMENSION_CODE

    def _load_default_config(self) -> Dict:
        """加载默认配置"""
        if self.CONFIG_PATH and os.path.exists(self.CONFIG_PATH):
            with open(self.CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return list(data.values())[0] if data else {}
        return {}

    def score(self, features: Dict[str, Any]) -> DimensionScore:
        """
        评分入口

        Args:
            features: 题目特征

        Returns:
            DimensionScore: 评分结果
        """
        if features.get("not_applicable", False):
            return DimensionScore(
                dimension_code=self.DIMENSION_CODE,
                score=0.0,
                level=0,
                level_label="N/A",
                evidence="该题目不适用此维度",
                applicable=False,
            )

        # 执行评分逻辑
        return self._calculate_score(features)

    def _calculate_score(self, features: Dict[str, Any]) -> DimensionScore:
        """
        计算分数（子类需要实现）
        """
        raise NotImplementedError("子类必须实现 _calculate_score 方法")

    def calculate_level(self, score: float) -> Tuple[int, str]:
        """计算等级"""
        levels = [
            (2.0, 1, "简单"),
            (4.0, 2, "较简单"),
            (6.0, 3, "中等"),
            (8.0, 4, "较难"),
            (10.0, 5, "困难"),
        ]
        for max_score, level, label in levels:
            if score <= max_score:
                return level, label
        return 5, "困难"

    def round_score(self, score: float) -> float:
        """按 0.5 粒度取整"""
        return round(score * 2) / 2


import os
