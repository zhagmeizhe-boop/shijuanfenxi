from copy import deepcopy

from app.services.ocr.base import ParsedQuestion, QuestionType
from app.services.parser.ai_parser import AIParser
from app.services.parser.dim5_knowledge_graph import (
    Dim5KnowledgeGraph,
    Dim5KnowledgeGraphMatcher,
)
from app.services.scoring.dim5_knowledge import Dim5KnowledgeScorer


def _match(text: str, question_type: str = "application"):
    matcher = Dim5KnowledgeGraphMatcher()
    return matcher.match(question_text=text, question_type=question_type)


def test_dim5_graph_schema_only_approves_structured_nodes():
    graph = Dim5KnowledgeGraph.load()

    assert graph.validate() == []
    assert graph.approved_nodes
    school_nodes = [
        node
        for node in graph.approved_nodes
        if node.knowledge_track == "school" and node.knowledge_point_id.startswith("dim5.school.")
    ]
    gaosi_nodes = [
        node
        for node in graph.approved_nodes
        if node.knowledge_track == "olympiad" and node.knowledge_point_id.startswith("dim5.gaosi.")
    ]
    assert school_nodes
    assert len(gaosi_nodes) >= 90
    generic_terms = {"计算问题", "计数问题", "几何问题", "组合问题", "综合应用", "数论综合"}
    for node in graph.approved_nodes:
        assert node.name not in generic_terms
        assert node.required_fact_groups
        assert node.level
        assert node.source_refs
        assert node.positive_examples
        assert node.negative_examples
        assert node.knowledge_display_name
    for node in school_nodes:
        assert node.knowledge_track_label == "校内"
        assert node.knowledge_grade in {"1", "2", "3", "4", "5", "6"}
        assert node.knowledge_grade_label.endswith("年级")
        assert node.knowledge_display_name.startswith(f"校内{node.knowledge_grade_label}：")
    for node in gaosi_nodes:
        assert node.knowledge_track_label == "奥数"
        assert node.knowledge_grade in {"3", "4", "5", "6"}
        assert node.knowledge_display_name.startswith(f"奥数{node.knowledge_grade_label}：")


def test_dim5_graph_distinguishes_work_rate_and_grazing():
    work = _match("某工程由甲单独做20天完成，由乙单独做30天完成，甲乙合作若干天后完成。")
    grazing = _match("一片草地原有草量，每天均匀生长，若干头牛每天吃草，最后吃完。")

    assert work["confidence_status"] == "confirmed"
    assert work["knowledge_point_name"] == "工程问题"
    assert work["knowledge_display_name"] == "奥数五年级：工程问题"
    assert work["knowledge_level"] == "L4"
    assert grazing["confidence_status"] == "confirmed"
    assert grazing["knowledge_point_name"] == "牛吃草问题与钟表问题"
    assert grazing["knowledge_display_name"] == "奥数五年级：牛吃草问题与钟表问题"
    assert grazing["knowledge_level"] == "L4"


def test_dim5_graph_distinguishes_profit_concentration_and_ratio():
    concentration = _match("一杯盐水浓度为10%，加入清水后混合，求新的浓度。")
    profit = _match("商品在进价基础上加价30%出售并获利，已知售价求进价。")
    ratio = _match("一月销量与其余三个月销量之和的比是1:4，已知四月销量，求总量。")

    assert concentration["knowledge_point_name"] == "浓度问题与经济问题"
    assert profit["knowledge_point_name"] == "利润折扣问题"
    assert ratio["knowledge_point_name"] == "比例解应用题"


def test_dim5_graph_distinguishes_counting_and_pigeonhole():
    pigeonhole = _match("56人选择9种菜，金额正好相同，购买品种完全相同的至少有几人？")
    counting = _match("从5种颜色中选择2种给图形涂色，一共有多少种方案？")

    assert pigeonhole["confidence_status"] == "ambiguous"
    assert pigeonhole["failure_reason"] == "ambiguous_confirmed_candidates"
    assert any(
        candidate["knowledge_display_name"] == "奥数四年级：抽屉原理"
        for candidate in pigeonhole["candidate_knowledge_points"]
    )
    assert counting["confidence_status"] == "confirmed"
    assert counting["knowledge_point_name"] == "组合计数"


def test_dim5_graph_confirms_school_knowledge_with_display_name():
    result = _match(
        "把298看作300，估算298÷3大约是多少。",
        question_type="application",
    )

    assert result["confidence_status"] == "confirmed"
    assert result["knowledge_point_name"] == "除法估算"
    assert result["knowledge_track"] == "school"
    assert result["knowledge_grade"] == "3"
    assert result["knowledge_display_name"] == "校内三年级：除法估算"


def test_dim5_graph_does_not_treat_guarantee_rate_as_pigeonhole():
    result = _match(
        "某班种树84棵，平均分给6个小组，要求保证出苗率，问每组多少棵。",
        question_type="application",
    )

    assert result["confidence_status"] == "confirmed"
    assert result["knowledge_track"] == "school"
    assert result["knowledge_level"] == "L1"
    assert result["knowledge_point_name"] in {"平均分应用", "除数是一位数的除法中求平均问题"}
    assert result["knowledge_point_name"] != "抽屉原理与组合枚举"


def test_dim5_graph_corrects_grade3_midterm_school_cases():
    q8 = _match(
        "汉诺塔是一个源于印度古老传说的益智玩具。如图，每层的厚度相同，如果4层高52毫米，"
        "那么一层高多少毫米；如果摞8层，高度是多少毫米。",
        question_type="application",
    )
    q12 = _match(
        "下面不是36÷3的计算方法。A. 30÷3=10，6÷3=2，10+2=12；B. 三个点阵图；C. 算盘图示。",
        question_type="choice",
    )
    q14 = _match(
        "下面的点表示现点，哪一个能围成一个长方形。",
        question_type="choice",
    )
    q15 = _match(
        "用4个边长是1厘米的小正方形，拼成如下的图形，周长最小的是哪一个。"
        "A.4个正方形横排 B.3个正方形加1个 C.2x2正方形 D.T形排列",
        question_type="choice",
    )
    q23 = _match(
        "农场采购了576袋玉米种子，平均分成6个种植小组，每个小组负责一块玉米种植区的播种工作。"
        "每个种植小组能分到多少袋玉米种子？",
        question_type="application",
    )
    q26 = _match(
        "李明制作短视频效率稳定，此前完成6个同款科普短视频共耗时54分钟。按照这样的制作效率，"
        "完成12个需要多少分钟？总时长225分钟能制作多少个？",
        question_type="application",
    )

    assert q8["confidence_status"] == "confirmed"
    assert q8["knowledge_track"] == "school"
    assert q8["knowledge_level"] == "L1"

    assert q12["confidence_status"] == "confirmed"
    assert q12["knowledge_point_name"] == "除法的意义与计算方法"
    assert q12["knowledge_level"] == "L1"

    assert q14["confidence_status"] == "confirmed"
    assert q14["knowledge_point_name"] == "长方形的特征"
    assert q14["knowledge_level"] == "L1"

    assert q15["confidence_status"] == "confirmed"
    assert q15["knowledge_point_name"] == "长方形和正方形周长"
    assert q15["knowledge_display_name"] == "校内三年级：长方形和正方形周长"
    assert all(
        not (
            candidate["knowledge_point_name"] == "排列组合"
            and candidate["candidate_status"] == "confirmed_candidate"
        )
        for candidate in q15["candidate_knowledge_points"]
    )

    for result in (q23, q26):
        assert result["confidence_status"] == "confirmed"
        assert result["knowledge_track"] == "school"
        assert result["knowledge_level"] == "L1"
        assert result["knowledge_point_name"] != "工程问题"
        assert all(
            not (
                candidate["knowledge_point_name"] == "工程问题"
                and candidate["candidate_status"] == "confirmed_candidate"
            )
            for candidate in result["candidate_knowledge_points"]
        )


def test_dim5_graph_distinguishes_geometry_formula_and_area_model():
    formula = _match("直接代入长方形面积公式求面积。")
    area_model = _match("图中需要利用蝴蝶模型和燕尾模型求阴影面积。")

    assert formula["knowledge_point_name"] == "基础几何公式应用"
    assert area_model["knowledge_point_name"] == "面积比模型"


def test_dim5_graph_confirms_game_strategy_only_with_winning_goal():
    result = _match("两名玩家轮流移动棋子，最后无法移动棋子的玩家输，问先手的制胜策略。")

    assert result["confidence_status"] == "confirmed"
    assert result["knowledge_point_name"] == "博弈策略与必胜策略"
    assert result["knowledge_level"] == "L5"


def test_dim5_graph_confirms_fraction_telescoping_over_basic_operations():
    result = _match(
        "计算：3/(2×7) + 3/(7×12) + 3/(12×17) + … + 3/(47×52) = （  ）。",
        question_type="calculation",
    )

    assert result["confidence_status"] == "confirmed"
    assert result["knowledge_point_name"] == "分数裂项求和"
    assert result["knowledge_display_name"] == "奥数知识：分数裂项求和"
    assert result["knowledge_level"] == "L4"
    assert result["selected_candidate_id"] == "dim5.number_operation.fraction_telescoping"


def test_dim5_graph_confirms_circle_circumference_radius_increment():
    result = _match(
        "把一根刚好围在圆上的铁丝长度增加1米，形成一个圆环，求圆环的宽是多少米。"
    )

    assert result["confidence_status"] == "confirmed"
    assert result["knowledge_point_name"] == "圆周长变化与半径增量"
    assert result["knowledge_display_name"] == "奥数知识：圆周长变化与半径增量"
    assert result["knowledge_level"] == "L3"
    assert result["selected_candidate_id"] == "dim5.geometry_spatial.circle_circumference_radius_increment"


def test_dim5_graph_returns_review_when_no_structure_is_confirmed():
    result = _match("题干缺失，只保留了题号。")

    assert result["confidence_status"] == "review_required"
    assert result["knowledge_point_name"] == ""
    assert result["knowledge_level"] == ""
    assert result["selected_candidate_id"] == "no_match"


def test_dim5_graph_parser_application_does_not_pollute_analysis_facts():
    parser = AIParser.__new__(AIParser)
    question = ParsedQuestion(
        question_no="3",
        question_type=QuestionType.CALCULATION,
        raw_text="统计古诗中“春”字出现次数占全诗总字数的百分比。",
        page_no=1,
    )
    analysis_facts = {
        "core_task": "统计指定文字出现次数并计算百分比",
        "core_knowledge_points": ["百分数的意义"],
        "core_methods": ["计数"],
    }
    before = deepcopy(analysis_facts)

    feature = parser._apply_dim5_graph_grounding(
        {},
        question=question,
        analysis_facts=analysis_facts,
    )

    assert analysis_facts == before
    assert feature["confidence_status"] == "confirmed"
    assert feature["knowledge_point_name"] == "百分数意义与计算"
    assert "dim5_structure_facts" in feature
    assert "dim5_structure_facts" not in analysis_facts


def test_dim5_scorer_does_not_fallback_when_graph_is_not_confirmed():
    result = Dim5KnowledgeScorer().score(
        {
            "confidence_status": "review_required",
            "failure_reason": "no_confirmed_candidate",
            "knowledge_tags": ["因数倍数与质合数"],
            "dim5_structure_facts": [],
            "candidate_knowledge_points": [],
        }
    )

    assert result.applicable is False
    assert result.score == 0.0
    assert result.details["dim5_excluded_reason"] == "dim5_graph_not_confirmed"


def test_dim5_scorer_accepts_confirmed_graph_result():
    result = Dim5KnowledgeScorer().score(
        {
            "confidence_status": "confirmed",
            "knowledge_point_id": "dim5.quantity_application.grazing",
            "knowledge_point_name": "牛吃草模型",
            "knowledge_domain": "quantity_application",
            "knowledge_level": "L4",
            "knowledge_track": "olympiad",
            "knowledge_track_label": "奥数",
            "knowledge_grade": "unknown",
            "knowledge_grade_label": "年级未确认",
            "knowledge_display_name": "奥数年级未确认：牛吃草模型",
            "graph_version": "dim5_knowledge_graph_v1",
        }
    )

    assert result.applicable is True
    assert result.score == 8.0
    assert result.details["canonical_knowledge_point"] == "牛吃草模型"
    assert result.details["confidence_status"] == "confirmed"
    assert result.details["knowledge_display_name"] == "奥数知识：牛吃草模型"
