"""
维度4：实践与创新评分引擎

评估题目相对课本原型的变化程度（变化难度），
核心驱动字段为 prototype_distance（原题变化程度）。
"""

from typing import Any, Dict, Optional

from app.services.scoring.base import BaseDimensionScorer, DimensionScore


class Dim4InnovationScorer(BaseDimensionScorer):
    """
    维度4：实践与创新评分器

    以"变化难度"为核心，评估题目相对课本原型的变化程度。
    """

    DIMENSION_CODE = "dim4"
    DIMENSION_NAME = "实践与创新"

    def __init__(self):
        super().__init__(config=None)

    def _get_default_config(self):
        """获取默认配置"""
        return {
            "max_score": 10.0,
            "score_granularity": 0.5,
        }

    def score(self, features: Dict[str, Any]) -> DimensionScore:
        """
        计算维度4评分

        Args:
            features: 题目特征
                - prototype_distance: 原题变化程度
                    original / surface / structural / deep
                - disguise_level: 情境伪装程度 (none/light/heavy)
                - is_reverse: 是否逆向提问 (0/1)
                - is_open_ended: 是否开放题 (0/1)
                - decode_difficulty: 题意解码难度 (low/medium/high)

        Returns:
            DimensionScore: 评分结果
        """
        # 先检查 Force-5（开放+深度变形）
        override = self._check_force5(features)
        if override:
            return override

        # 再检查 Force-1（课本原题，完全无包装）
        override = self._check_force1(features)
        if override:
            return override

        # 计算基础分
        base_score = self._get_base_score(features)

        # 计算修正分
        adjustments = self._calculate_adjustments(features)
        total_adjustment = sum(adjustments.values())

        # 计算最终分数
        raw_score = base_score + total_adjustment
        final_score = min(raw_score, 10.0)
        final_score = self.round_score(final_score)

        # Force-4：结构变形+深度伪装，最低 L4
        override = self._check_force4(features, final_score)
        if override:
            return override

        # 计算等级
        level, level_label = self.calculate_level(final_score)

        # 生成证据
        evidence = self._generate_evidence(features, base_score, adjustments, final_score, level_label)

        return DimensionScore(
            dimension_code=self.dimension_code,
            score=final_score,
            level=level,
            level_label=level_label,
            evidence=evidence,
            applicable=True,
            details={
                "base_score": base_score,
                "adjustments": adjustments,
                "features": features,
            },
        )

    def _check_force5(self, features: Dict[str, Any]) -> Optional[DimensionScore]:
        """Force-5：深度变形且为开放题 → 最低 9.0"""
        if (
            features.get("prototype_distance") == "deep"
            and features.get("is_open_ended") == 1
        ):
            return DimensionScore(
                dimension_code=self.dimension_code,
                score=self.LEVEL_SCORE_MIDPOINTS[5],
                level=5,
                level_label="困难",
                evidence="【强制规则】强制5档：深度变形且为开放题，变化难度最高",
                applicable=True,
            )
        return None

    def _check_force1(self, features: Dict[str, Any]) -> Optional[DimensionScore]:
        """Force-1：课本原题，无伪装，非逆向，非开放 → 固定 1.0"""
        if (
            features.get("prototype_distance") == "original"
            and features.get("disguise_level", "none") == "none"
            and features.get("is_reverse", 0) == 0
            and features.get("is_open_ended", 0) == 0
        ):
            return DimensionScore(
                dimension_code=self.dimension_code,
                score=self.LEVEL_SCORE_MIDPOINTS[1],
                level=1,
                level_label="简单",
                evidence="【强制规则】强制1档：课本原题，无情境伪装，非逆向，非开放题",
                applicable=True,
            )
        return None

    def _check_force4(self, features: Dict[str, Any], current_score: float) -> Optional[DimensionScore]:
        """Force-4：结构/深度变形且深度伪装 → 最低 L4 分值"""
        min_l4 = self.LEVEL_SCORE_MIDPOINTS[4]
        if (
            features.get("prototype_distance") in ["structural", "deep"]
            and features.get("disguise_level") == "heavy"
            and current_score < min_l4
        ):
            _, level_label = self.calculate_level(min_l4)
            return DimensionScore(
                dimension_code=self.dimension_code,
                score=min_l4,
                level=4,
                level_label=level_label,
                evidence="【强制规则】强制4档：结构或深度变形且情境深度伪装，至少判定为4档",
                applicable=True,
            )
        return None

    def _get_base_score(self, features: Dict[str, Any]) -> float:
        """获取基础分（以 prototype_distance 为主驱动）"""
        prototype_distance = features.get("prototype_distance", "surface")
        return {
            "original": 1.0,
            "surface": 3.0,
            "structural": 6.0,
            "deep": 8.5,
        }.get(prototype_distance, 3.0)

    def _calculate_adjustments(self, features: Dict[str, Any]) -> Dict[str, float]:
        """计算修正分"""
        adjustments = {}

        disguise_level = features.get("disguise_level", "none")
        if disguise_level == "light":
            adjustments["disguise_level"] = 0.5
        elif disguise_level == "heavy":
            adjustments["disguise_level"] = 1.5

        if features.get("is_reverse", 0) == 1:
            adjustments["is_reverse"] = 0.5

        decode_difficulty = features.get("decode_difficulty", "low")
        if decode_difficulty == "medium":
            adjustments["decode_difficulty"] = 0.5
        elif decode_difficulty == "high":
            adjustments["decode_difficulty"] = 1.0

        if features.get("is_open_ended", 0) == 1:
            adjustments["is_open_ended"] = 0.5

        return adjustments

    def _generate_evidence(
        self, features: Dict[str, Any], base_score: float,
        adjustments: Dict[str, float], final_score: float, level_label: str
    ) -> str:
        """生成评分证据（教师可读的中文叙述）"""
        prototype_distance = features.get("prototype_distance", "surface")
        disguise_level = features.get("disguise_level", "none")
        is_reverse = features.get("is_reverse", 0)
        is_open_ended = features.get("is_open_ended", 0)
        decode_difficulty = features.get("decode_difficulty", "low")

        distance_desc = {
            "original": "课本原题（无变化）",
            "surface": "表面变形（换数字或情境，解题结构不变）",
            "structural": "结构变形（变换题型或问法，需重组解题路径）",
            "deep": "深度变形（多步重组或创新组合，与原型差异显著）",
        }.get(prototype_distance, prototype_distance)

        disguise_desc = {
            "none": "无情境伪装",
            "light": "轻度情境包装",
            "heavy": "深度情境伪装（知识点不易识别）",
        }.get(disguise_level, disguise_level)

        decode_desc = {
            "low": "题意直接明了",
            "medium": "题意需要一定转化",
            "high": "题意隐晦，需多次转化",
        }.get(decode_difficulty, decode_difficulty)

        extra = []
        if is_reverse == 1:
            extra.append("逆向提问")
        if is_open_ended == 1:
            extra.append("开放题")
        extra_str = "，" + "、".join(extra) if extra else ""

        adj_total = sum(v for v in adjustments.values() if v > 0)
        adj_str = f"，修正分+{adj_total:.1f}" if adj_total > 0 else ""

        return (
            f"本题为{distance_desc}，{disguise_desc}，{decode_desc}{extra_str}。"
            f"基础分{base_score}{adj_str}，综合评分{final_score}分，难度等级：{level_label}"
        )
