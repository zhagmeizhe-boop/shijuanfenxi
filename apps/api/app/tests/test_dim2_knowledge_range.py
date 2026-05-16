from app.services.scoring.dim2_knowledge_range import match_dim2_knowledge_range
from app.services.scoring.dim2_spatial import Dim2SpatialScorer
from app.services.scoring.paper_aggregator import PaperAggregator, QuestionDimensionScore


def _knowledge_features(core_points: list[str]) -> dict:
    return {"analysis_facts": {"core_knowledge_points": core_points}}


def _dim2_features(core_points: list[str], **overrides) -> dict:
    features = {
        "task_form": "explicit_visual",
        "spatial_role": "core",
        "figure_complexity": "composite_2d",
        "relation_hops": "2",
        "hidden_relation_count": "1",
        "visual_operation_count": "1",
        "structural_visual_method": "decomposition",
        "measurement_dependency": "inferred",
        "global_view_required": 0,
        "image_dependency": "helpful",
        "geometry_model_types": [],
        "geometry_model_count": "0",
        "model_recognition_role": "none",
        "area_relation_chain": "none",
        "model_combination_complexity": "none",
        "evidence_summary": "需要读取图形面积关系。",
        "analysis_facts": {"core_knowledge_points": core_points},
    }
    features.update(overrides)
    return features


def _counted_dim2_reason(question_no: str, core_points: list[str]) -> str:
    score = Dim2SpatialScorer().score(_dim2_features(core_points))
    question = QuestionDimensionScore(
        question_id=f"q-{question_no}",
        question_no=question_no,
        question_label_raw=f"({question_no})",
        score=6.0,
        dim_scores={"dim2": score.score},
        applicable_dims=["dim2"],
        question_summary="、".join(core_points),
        dim_reasons={"dim2": score.evidence},
        dim_details={"dim2": score.details},
    )
    summary = PaperAggregator().aggregate([question], "dim2")
    return str(summary.counted_questions[0]["reason"])


def test_rectangle_area_does_not_match_circle_ring_area():
    match = match_dim2_knowledge_range(
        _knowledge_features(["长方形周长", "长方形面积", "图形分割性质"])
    )

    assert match.status == "matched"
    assert "利用整体法计算圆（环）形面积" not in match.matched_knowledge_points
    assert "长方形面积的复杂应用" in match.matched_knowledge_points


def test_square_composite_area_does_not_match_circle_ring_area():
    match = match_dim2_knowledge_range(
        _knowledge_features(["正方形面积公式", "组合图形面积计算", "面积差"])
    )

    assert match.status == "matched"
    assert "利用整体法计算圆（环）形面积" not in match.matched_knowledge_points
    assert "一般的组合图形面积计算" in match.matched_knowledge_points


def test_area_conservation_does_not_match_circle_ring_area():
    match = match_dim2_knowledge_range(
        _knowledge_features(["面积守恒", "正方形面积", "长方形面积"])
    )

    assert match.status == "matched"
    assert "利用整体法计算圆（环）形面积" not in match.matched_knowledge_points
    assert "长方形面积的复杂应用" in match.matched_knowledge_points


def test_real_ring_area_still_matches_circle_sector_knowledge():
    ring_match = match_dim2_knowledge_range(_knowledge_features(["环形面积"]))
    method_match = match_dim2_knowledge_range(
        _knowledge_features(["利用整体法计算圆（环）形面积"])
    )

    assert ring_match.knowledge_range_label == "校内六年级"
    assert "环形面积" in ring_match.matched_knowledge_points
    assert method_match.knowledge_range_label == "校内六年级"
    assert "利用整体法计算圆（环）形面积" in method_match.matched_knowledge_points


def test_counted_question_reasons_do_not_show_circle_area_for_rectangular_cases():
    reasons = [
        _counted_dim2_reason("11", ["长方形周长", "长方形面积", "图形分割性质"]),
        _counted_dim2_reason("22", ["正方形面积公式", "组合图形面积计算", "面积差"]),
        _counted_dim2_reason("8", ["面积守恒", "正方形面积", "长方形面积"]),
    ]

    for reason in reasons:
        assert "利用整体法计算圆（环）形面积" not in reason
        assert "圆（环）形面积" not in reason
