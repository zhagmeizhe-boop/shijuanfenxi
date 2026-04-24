"""
维度6：逻辑链条长度评分引擎

评估题目解题过程中的逻辑复杂度
"""

from typing import Any, Dict

from app.services.scoring.base import BaseDimensionScorer, DimensionScore


class Dim6LogicScorer(BaseDimensionScorer):
    """
    维度6：逻辑链条长度评分器

    评估题目解题过程中的逻辑复杂度。
    """

    DIMENSION_CODE = "dim6"
    DIMENSION_NAME = "逻辑链条长度"

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
        计算维度6评分

        Args:
            features: 题目特征
                - key_step_count: 关键步骤数 (1/2/3/4-5/6+)
                - has_hidden_relation: 是否有隐藏关系 (0/1)
                - need_reverse_reasoning: 是否需要反向推理 (0/1)
                - has_branch: 是否有分支 (0/1)
                - need_case_discussion: 是否需要分类讨论 (0/1)
                - need_validation: 是否需要验证 (0/1)

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

        # 提取特征
        key_step_count = features.get("key_step_count", "1")
        has_hidden_relation = features.get("has_hidden_relation", 0)
        need_reverse_reasoning = features.get("need_reverse_reasoning", 0)
        has_branch = features.get("has_branch", 0)
        need_case_discussion = features.get("need_case_discussion", 0)
        need_validation = features.get("need_validation", 0)

        # 计算基础分
        base_scores = {
            "1": 1.5,
            "2": 3.0,
            "3": 5.0,
            "4-5": 7.0,
            "6+": 8.5,
        }
        base_score = base_scores.get(key_step_count, 1.5)

        # 计算修正分
        adjustments = 0.0
        adjustment_details = []

        if has_hidden_relation == 1:
            adjustments += 0.5
            adjustment_details.append("隐藏关系+0.5")

        if need_reverse_reasoning == 1:
            adjustments += 0.5
            adjustment_details.append("反向推理+0.5")

        if need_validation == 1:
            adjustments += 0.5
            adjustment_details.append("验证要求+0.5")

        # 计算最终分数（先加修正分）
        final_score = base_score + adjustments

        # 应用最低分限制
        min_score = 0.0
        if has_branch == 1 or need_case_discussion == 1:
            min_score = self.LEVEL_SCORE_MIDPOINTS[4]
            if final_score < min_score:
                final_score = min_score
                adjustment_details.append(f"分支/分类讨论要求最低{min_score}分")

        # 封顶
        final_score = min(final_score, 10.0)

        # 按 0.5 粒度取整
        final_score = self.round_score(final_score)

        # 计算等级
        level, level_label = self.calculate_level(final_score)

        # 生成证据（教师可读的中文叙述）
        step_desc = {
            "1": "1个", "2": "2个", "3": "3个", "4-5": "4-5个", "6+": "6个以上"
        }.get(key_step_count, key_step_count)

        extra = []
        if has_hidden_relation == 1:
            extra.append("含隐藏关系需挖掘")
        if need_reverse_reasoning == 1:
            extra.append("需逆向推理")
        if need_validation == 1:
            extra.append("需验证答案")
        if has_branch == 1:
            extra.append("存在解题分支")
        if need_case_discussion == 1:
            extra.append("需分类讨论")
        extra_str = "，" + "、".join(extra) if extra else ""

        floor_str = f"（因存在分支或分类讨论，最低分限制为{min_score}分）" if min_score > 0 and (has_branch == 1 or need_case_discussion == 1) else ""

        evidence = (
            f"本题需要{step_desc}关键推理步骤{extra_str}。"
            f"基础分{base_score}，修正分+{adjustments:.1f}{floor_str}，"
            f"综合评分{final_score}分，难度等级：{level_label}"
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
                "adjustment_details": adjustment_details,
                "min_score_applied": min_score if (has_branch == 1 or need_case_discussion == 1) else None,
                "features": features,
            },
        )
