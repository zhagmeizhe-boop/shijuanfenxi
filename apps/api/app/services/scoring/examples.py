"""
六维评分引擎使用示例

演示如何使用维度1、维度2、维度3的评分引擎
"""

import json
from typing import Dict, Any

from app.services.scoring.dim1_computation import Dim1ComputationScorer
from app.services.scoring.dim2_spatial import Dim2SpatialScorer
from app.services.scoring.dim3_information import Dim3InformationScorer


def print_score_result(dim_name: str, result):
    """打印评分结果"""
    print(f"\n{'='*60}")
    print(f"【{dim_name}】")
    print(f"{'='*60}")
    print(f"维度代码: {result.dimension_code}")
    print(f"得分: {result.score}")
    print(f"等级: {result.level} ({result.level_label})")
    print(f"是否适用: {result.applicable}")
    print(f"证据: {result.evidence}")
    if result.details:
        print(f"详细信息:")
        print(json.dumps(result.details, ensure_ascii=False, indent=2))


def example_dim1():
    """示例1：维度1 - 数学运算"""
    print("\n" + "="*60)
    print("示例1：维度1 - 数学运算评分")
    print("="*60)

    scorer = Dim1ComputationScorer()

    # 示例1.1：最简单的计算题
    features_1 = {
        "number_type": "simple",
        "operation_layers": "1",
        "transformation_difficulty": "none",
        "special_ops": "none",
        "error_proneness": "low",
    }
    result_1 = scorer.score(features_1)
    print_score_result("维度1 - 最简单的计算题", result_1)

    # 示例1.2：中等复杂度
    features_2 = {
        "number_type": "mixed_basic",
        "operation_layers": "2-3",
        "transformation_difficulty": "one",
        "special_ops": "none",
        "error_proneness": "medium",
    }
    result_2 = scorer.score(features_2)
    print_score_result("维度1 - 中等复杂度", result_2)

    # 示例1.3：高复杂度
    features_3 = {
        "number_type": "multi_system",
        "operation_layers": "6+",
        "transformation_difficulty": "multiple",
        "special_ops": "multiple",
        "error_proneness": "high",
    }
    result_3 = scorer.score(features_3)
    print_score_result("维度1 - 高复杂度", result_3)


def example_dim2():
    """示例2：维度2 - 几何直观与空间想象"""
    print("\n" + "="*60)
    print("示例2：维度2 - 几何直观与空间想象评分")
    print("="*60)

    scorer = Dim2SpatialScorer()

    # 示例2.1：非几何题
    features_1 = {"is_geometry": 0}
    result_1 = scorer.score(features_1)
    print_score_result("维度2 - 非几何题", result_1)

    # 示例2.2：简单几何题
    features_2 = {
        "is_geometry": 1,
        "figure_familiarity": "regular",
        "need_auxiliary_line": "no",
        "transform_type": "none",
        "spatial_reconstruction_level": "low",
    }
    result_2 = scorer.score(features_2)
    print_score_result("维度2 - 简单几何题", result_2)

    # 示例2.3：复杂几何题
    features_3 = {
        "is_geometry": 1,
        "figure_familiarity": "non_standard",
        "need_auxiliary_line": "must",
        "transform_type": "combined",
        "spatial_reconstruction_level": "high",
    }
    result_3 = scorer.score(features_3)
    print_score_result("维度2 - 复杂几何题", result_3)


def example_dim3():
    """示例3：维度3 - 信息提取与转化"""
    print("\n" + "="*60)
    print("示例3：维度3 - 信息提取与转化评分")
    print("="*60)

    scorer = Dim3InformationScorer()

    # 示例3.1：最简单信息处理
    features_1 = {
        "info_source_type": "text_only",
        "info_count": "few",
        "has_noise_info": 0,
        "condition_scattered": 0,
        "need_modeling": 0,
        "relation_complexity": "low",
    }
    result_1 = scorer.score(features_1)
    print_score_result("维度3 - 最简单信息处理", result_1)

    # 示例3.2：中等复杂度
    features_2 = {
        "info_source_type": "image_text",
        "info_count": "medium",
        "has_noise_info": 0,
        "condition_scattered": 0,
        "need_modeling": 1,
        "relation_complexity": "medium",
    }
    result_2 = scorer.score(features_2)
    print_score_result("维度3 - 中等复杂度", result_2)

    # 示例3.3：最复杂信息处理
    features_3 = {
        "info_source_type": "multi_source",
        "info_count": "many",
        "has_noise_info": 1,
        "condition_scattered": 1,
        "need_modeling": 1,
        "relation_complexity": "high",
    }
    result_3 = scorer.score(features_3)
    print_score_result("维度3 - 最复杂信息处理", result_3)


def run_all_examples():
    """运行所有示例"""
    print("\n" + "="*60)
    print("六维评分引擎使用示例")
    print("="*60)

    example_dim1()
    example_dim2()
    example_dim3()

    print("\n" + "="*60)
    print("所有示例运行完成！")
    print("="*60)


if __name__ == "__main__":
    run_all_examples()
