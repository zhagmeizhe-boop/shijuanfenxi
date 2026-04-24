"""
维度3：信息提取与转化评分引擎

评估应用题从场景信息到数学模型的转化难度
"""

from typing import Any, Dict, Optional

from app.services.scoring.base import BaseDimensionScorer, DimensionScore


class Dim3InformationScorer(BaseDimensionScorer):
    """
    维度3：信息提取与转化评分器

    评估应用题从场景信息到数学模型的转化难度
    """

    DIMENSION_CODE = "dim3"
    DIMENSION_NAME = "信息提取与转化"

    def __init__(self):
        # 维度3使用固定规则，不需要配置文件
        super().__init__(config=None)

    def _get_default_config(self):
        """获取默认配置（固定规则）"""
        return {
            "max_score": 10.0,
            "score_granularity": 0.5,
        }

    def score(self, features: Dict[str, Any]) -> DimensionScore:
        """
        计算维度3评分

        Args:
            features: 题目特征
                - info_source_type: 信息源类型 (text_only/image_text/table/multi_source)
                - info_count: 信息量 (few/medium/many)
                - has_noise_info: 是否有干扰信息 (0/1)
                - condition_scattered: 条件是否分散 (0/1)
                - need_modeling: 是否需要建模 (0/1)
                - relation_complexity: 关系复杂度 (low/medium/high)

        Returns:
            DimensionScore: 评分结果
        """
        # 检查是否为非适用题
        if features.get("not_applicable", False):
            return DimensionScore(
                dimension_code=self.dimension_code,
                score=0.0,
                level=0,
                level_label="N/A",
                evidence="该题目不适用此维度",
                applicable=False,
            )

        # 检查强制覆盖规则
        override = self._check_override_rules(features)
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

        # 计算等级
        level, level_label = self.calculate_level(final_score)

        # 生成证据
        evidence = self._generate_evidence(
            features, base_score, adjustments, final_score, level_label
        )

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

    def _check_override_rules(self, features: Dict[str, Any]) -> Optional[DimensionScore]:
        """检查强制覆盖规则"""
        # 强制1档规则
        if (
            features.get("info_source_type") == "text_only"
            and features.get("info_count") == "few"
            and features.get("has_noise_info") == 0
            and features.get("condition_scattered") == 0
            and features.get("need_modeling") == 0
            and features.get("relation_complexity") == "low"
        ):
            return DimensionScore(
                dimension_code=self.dimension_code,
                score=self.LEVEL_SCORE_MIDPOINTS[1],
                level=1,
                level_label="简单",
                evidence="【强制规则】强制1档：满足所有最简单信息处理条件（纯文字、信息量少、无干扰、条件集中、无需建模、关系复杂度低）",
                applicable=True,
            )

        # 强制5档规则
        if (
            features.get("info_source_type") == "multi_source"
            and features.get("info_count") == "many"
            and features.get("need_modeling") == 1
            and features.get("relation_complexity") == "high"
            and (features.get("has_noise_info") == 1 or features.get("condition_scattered") == 1)
        ):
            return DimensionScore(
                dimension_code=self.dimension_code,
                score=self.LEVEL_SCORE_MIDPOINTS[5],
                level=5,
                level_label="困难",
                evidence="【强制规则】强制5档：满足最复杂信息处理条件（多源混合、信息量大、需要建模、关系复杂度高，且存在干扰信息或条件分散）",
                applicable=True,
            )

        return None

    def _get_base_score(self, features: Dict[str, Any]) -> float:
        """获取基础分"""
        complexity = features.get("relation_complexity", "low")
        return {"low": 1.5, "medium": 4.5, "high": 6.5}.get(complexity, 1.5)

    def _calculate_adjustments(self, features: Dict[str, Any]) -> Dict[str, float]:
        """计算修正分"""
        adjustments = {}

        # 信息源类型
        source_type = features.get("info_source_type", "text_only")
        adjustments["info_source_type"] = {
            "text_only": 0.0, "image_text": 0.5, "table": 0.5, "multi_source": 1.0
        }.get(source_type, 0.0)

        # 信息量
        info_count = features.get("info_count", "few")
        adjustments["info_count"] = {"few": 0.0, "medium": 0.5, "many": 1.0}.get(info_count, 0.0)

        # 干扰信息
        if features.get("has_noise_info") == 1:
            adjustments["has_noise_info"] = 0.5

        # 条件分散
        if features.get("condition_scattered") == 1:
            adjustments["condition_scattered"] = 0.5

        # 需要建模
        if features.get("need_modeling") == 1:
            adjustments["need_modeling"] = 1.0

        return adjustments

    def _generate_evidence(
        self, features: Dict[str, Any], base_score: float,
        adjustments: Dict[str, float], final_score: float, level_label: str
    ) -> str:
        """生成评分证据（教师可读的中文叙述）"""
        info_source_type = features.get("info_source_type", "text_only")
        info_count = features.get("info_count", "few")
        has_noise_info = features.get("has_noise_info", 0)
        condition_scattered = features.get("condition_scattered", 0)
        need_modeling = features.get("need_modeling", 0)
        relation_complexity = features.get("relation_complexity", "low")

        source_desc = {
            "text_only": "纯文字", "image_text": "图文混排",
            "table": "含表格", "multi_source": "多种来源混合"
        }.get(info_source_type, info_source_type)

        count_desc = {
            "few": "较少（≤3条）", "medium": "中等（4-6条）", "many": "较多（>6条）"
        }.get(info_count, info_count)

        complexity_desc = {
            "low": "较简单", "medium": "中等", "high": "较复杂"
        }.get(relation_complexity, relation_complexity)

        extra = []
        if has_noise_info == 1:
            extra.append("含干扰信息")
        if condition_scattered == 1:
            extra.append("条件分散")
        if need_modeling == 1:
            extra.append("需建立数学模型")
        extra_str = "，" + "、".join(extra) if extra else ""

        adj_total = sum(v for v in adjustments.values() if v > 0)
        adj_str = f"，修正分+{adj_total:.1f}" if adj_total > 0 else ""

        return (
            f"本题信息来源为{source_desc}，有效信息{count_desc}，数量关系{complexity_desc}{extra_str}。"
            f"基础分{base_score}{adj_str}，综合评分{final_score}分，难度等级：{level_label}"
        )

    def _create_score_result(
        self, score: float, level: int, evidence: str, details: Dict = None
    ) -> DimensionScore:
        """创建评分结果"""
        level_labels = {1: "简单", 2: "较简单", 3: "中等", 4: "较难", 5: "困难"}

        return DimensionScore(
            dimension_code=self.dimension_code,
            score=score,
            level=level,
            level_label=level_labels.get(level, "未知"),
            evidence=evidence,
            applicable=True,
            details=details or {},
        )
