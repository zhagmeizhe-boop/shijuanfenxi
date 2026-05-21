from copy import deepcopy
import json
from pathlib import Path

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


def _match_many(text: str, question_type: str = "application", max_candidates: int = 40):
    matcher = Dim5KnowledgeGraphMatcher()
    return matcher.match(question_text=text, question_type=question_type, max_candidates=max_candidates)


def _confirmed_candidate_names(result: dict) -> set[str]:
    return {
        candidate["knowledge_point_name"]
        for candidate in result["candidate_knowledge_points"]
        if candidate["candidate_status"] == "confirmed_candidate"
    }


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


def test_dim5_graph_merges_2024_gaosi_knowledge_tree_subtopics():
    graph = Dim5KnowledgeGraph.load()
    tree_path = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "parser"
        / "gaosi_knowledge_tree_2024.json"
    )
    entries = json.loads(tree_path.read_text(encoding="utf-8"))
    title_aliases = {
        "几何图形认识": "几何图形的认知",
        "抽屉原理一": "抽屉原理",
        "计算综合": "计算综合二",
    }
    gaosi_nodes = {
        (node.knowledge_grade, node.name): node
        for node in graph.approved_nodes
        if node.knowledge_track == "olympiad" and node.knowledge_point_id.startswith("dim5.gaosi.")
    }

    assert len(entries) == 94
    assert sum(len(entry.get("subtopics") or []) for entry in entries) == 405
    for entry in entries:
        title = title_aliases.get(entry["title"], entry["title"])
        node = gaosi_nodes.get((entry["grade"], title))
        assert node is not None, (entry["grade"], entry["title"])
        assert entry["source_ref"] in node.source_refs

    alias_checks = [
        ("3", "基本应用题", "归一问题"),
        ("5", "行程问题五", "柳卡图"),
        ("4", "抽屉原理", "最不利原则"),
        ("3", "智巧趣题二", "一笔画"),
        ("6", "构造论证二", "棋盘染色"),
    ]
    for grade, title, alias in alias_checks:
        assert alias in gaosi_nodes[(grade, title)].aliases


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


def test_dim5_graph_confirms_gaosi_knowledge_tree_subtopic_terms():
    basic = _match("三年级基本应用题中的归一问题。")
    travel = _match("行程问题五中的柳卡图解行程问题。")
    pigeonhole = _match("抽屉原理一的最不利原则。")
    puzzle = _match("智巧趣题二的一笔画问题。")
    construction = _match("构造论证二中的棋盘染色方法。")

    assert basic["confidence_status"] == "confirmed"
    assert basic["knowledge_display_name"] == "奥数三年级：基本应用题"

    assert travel["confidence_status"] == "confirmed"
    assert travel["knowledge_display_name"] == "奥数五年级：行程问题五"

    assert pigeonhole["confidence_status"] == "confirmed"
    assert pigeonhole["knowledge_display_name"] == "奥数四年级：抽屉原理"

    assert puzzle["confidence_status"] == "confirmed"
    assert puzzle["knowledge_display_name"] == "奥数三年级：智巧趣题二"

    assert construction["confidence_status"] == "confirmed"
    assert construction["knowledge_display_name"] == "奥数六年级：构造论证二"


def test_dim5_graph_does_not_confirm_generic_gaosi_tree_subtopic_labels():
    for text in ("综合问题", "基础题型", "基本公式"):
        result = _match(text)
        assert result["confidence_status"] != "confirmed"


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


def test_dim5_graph_confirms_placement_exam_5_unconfirmed_cases():
    q1 = _match("5的倒数是（）。A. 5 B. 2 C. 0.5 D. 0.2", question_type="choice")
    q3 = _match("下面四个图形中，不是正方体的展开图的是（）。", question_type="comprehensive")
    q10 = _match(
        "像2、33、101这样的数，正着读、反着读完全一样，我们把这样的数叫做回文数。"
        "那么在1-2015这2015个数中，回文数共有多少个。",
        question_type="choice",
    )
    q13 = _match(
        "已知△、□各代表一个数，△+□=24，△=□+□+□-2，所以△是多少，□是多少。",
        question_type="application",
    )
    q15 = _match(
        "把42420分解质因数，则所有质因数的和等于多少。",
        question_type="application",
    )
    q18 = _match(
        "24点游戏：用2、3、4、5四个数字和加、减、乘、除、乘方五种运算符号或括号连接，"
        "组成一个算式，使运算结果等于24。",
        question_type="application",
    )
    q20 = _match(
        "从甲地到乙地的公路，有上坡路30km，下坡路42km和平路20km。汽车上坡每小时20千米，"
        "下坡每小时35千米，从甲地开往乙地需3.5小时，那么从乙地开到甲地需多少小时。",
        question_type="application",
    )
    q23 = _match(
        "毕达哥拉斯让两个青年学习，每人每天奖励1枚银币。学习一阵后钱袋空空如也，"
        "两位青年要求继续学习，非但不要奖金，反而每人每天交纳3枚银币作为学费。"
        "当交费学习的时间还不到有奖学习时间的四分之一时，两位青年每人获得的奖励银币还剩5枚。"
        "毕达哥拉斯的钱袋里最初有多少枚银币？",
        question_type="application",
    )

    assert q1["confidence_status"] == "confirmed"
    assert q1["knowledge_display_name"] == "校内六年级：倒数"
    assert q1["knowledge_level"] == "L2"

    assert q3["confidence_status"] == "confirmed"
    assert q3["knowledge_display_name"] == "校内五年级：正方体展开图"
    assert q3["knowledge_level"] == "L2"

    assert q10["confidence_status"] == "confirmed"
    assert q10["knowledge_display_name"] == "奥数知识：回文数的分类计数"
    assert q10["knowledge_level"] == "L3"
    assert q10["knowledge_point_name"] != "数字谜综合一"

    assert q13["confidence_status"] == "confirmed"
    assert q13["knowledge_display_name"] == "校内五年级：等量代换与简易方程"
    assert q13["knowledge_level"] == "L2"

    assert q15["confidence_status"] == "confirmed"
    assert q15["knowledge_display_name"] == "校内五年级：质因数分解"
    assert q15["knowledge_level"] == "L2"

    assert q18["confidence_status"] == "confirmed"
    assert q18["knowledge_display_name"] == "校内四年级：24点游戏与四则混合运算"
    assert q18["knowledge_level"] == "L2"

    assert q20["confidence_status"] == "confirmed"
    assert q20["knowledge_display_name"] == "奥数知识：变速往返行程问题"
    assert q20["knowledge_level"] == "L4"
    assert q20["knowledge_point_name"] != "行程问题"

    assert q23["confidence_status"] == "confirmed"
    assert q23["knowledge_display_name"] == "奥数四年级：还原与盈亏问题"
    assert q23["knowledge_level"] == "L3"


def test_dim5_graph_corrects_placement_exam_6_cases():
    q18 = _match(
        "一个三位数的个位数字是1，它的百位数字和十位数字之和为12，交换它的百位数字和十位数字后，变小了360。那么，这个数是多少。",
        question_type="application",
    )
    q20 = _match(
        "如图，ABC，ADE，EFG均为正三角形，D、G分别为线段AC、AE的中点，线段AB长为8。则多边形ABCDEFG的周长为多少。",
        question_type="application",
    )
    q23 = _match(
        "如图，在边长为6厘米的正方形ABCD中，以AB为底边作腰长为5厘米的等腰三角形PAB，则三角形PBD的面积等于多少平方厘米。",
        question_type="application",
    )
    q24 = _match(
        "一只蚂蚁从A处爬到B处，如果它的速度每分钟增加1米，可提前5分钟到达。如果它的速度每分钟再增加2米，则又可提前5分钟到达。那么A处到B处之间的路程是多少米。",
        question_type="application",
    )
    q27 = _match(
        "如图，每个点表示一个同学，互相认识的同学直接就连一条边。小明准备办一个生日宴会，并准备邀请他认识的同学，以及这些同学认识的同学参加，则共邀请了多少个同学参加。",
        question_type="application",
    )

    assert q18["confidence_status"] == "confirmed"
    assert q18["knowledge_display_name"] == "奥数五年级：位值原理"
    assert q18["knowledge_level"] == "L4"
    assert all(
        not (
            candidate["knowledge_point_name"] == "数字性质中9的倍数判定"
            and candidate["candidate_status"] == "confirmed_candidate"
        )
        for candidate in q18["candidate_knowledge_points"]
    )

    assert q20["confidence_status"] == "confirmed"
    assert q20["knowledge_point_name"] == "等边三角形周长转化"
    assert all(
        not (
            candidate["knowledge_point_name"] == "多边形内角和计算"
            and candidate["candidate_status"] == "confirmed_candidate"
        )
        for candidate in q20["candidate_knowledge_points"]
    )

    assert q23["confidence_status"] == "confirmed"
    assert q23["knowledge_display_name"] == "奥数五年级：燕尾模型"
    assert all(
        not (
            candidate["knowledge_point_name"] in {"三角形面积", "面积比模型", "基础几何公式应用"}
            and candidate["candidate_status"] == "confirmed_candidate"
        )
        for candidate in q23["candidate_knowledge_points"]
    )

    assert q24["confidence_status"] == "confirmed"
    assert q24["knowledge_display_name"] == "奥数知识：行程方程应用"
    assert q24["knowledge_point_name"] != "变速往返行程问题"
    assert all(
        not (
            "行程问题" in candidate["knowledge_point_name"]
            and candidate["candidate_status"] == "confirmed_candidate"
        )
        for candidate in q24["candidate_knowledge_points"]
    )

    assert q27["confidence_status"] == "confirmed"
    assert q27["knowledge_display_name"] == "奥数知识：图论基础与关系网络计数"
    assert q27["knowledge_point_name"] != "整数除法"


def test_dim5_graph_distinguishes_geometry_formula_and_area_model():
    formula = _match("直接代入长方形面积公式求面积。")
    area_model = _match("图中需要利用蝴蝶模型和面积比关系求阴影面积。")

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


def test_dim5_graph_replays_batch_exam_7_11_14_corrections():
    statistics = _match("如图，条形统计图和扇形统计图表示人数，已知圆心角和百分比，求人数。")
    parking = _match("停车场有中型汽车和小型汽车共30辆，停车费共324元，中型每辆12元，小型每辆8元，问各有多少辆。")
    profit = _match("某商品按进价加价20%出售，后来打折仍获利，求进价和售价关系。")
    work = _match("一项工程，甲单独做20天完成，乙单独做30天完成，甲乙合作若干天完成。")
    transport = _match("几辆车运输货物，每车费用不同，怎样安排使运输费用最小。")

    assert statistics["confidence_status"] == "confirmed"
    assert statistics["knowledge_point_name"] == "统计图综合"
    assert all(
        not (
            candidate["knowledge_point_name"] == "圆与扇形"
            and candidate["candidate_status"] == "confirmed_candidate"
        )
        for candidate in statistics["candidate_knowledge_points"]
    )

    assert parking["confidence_status"] == "confirmed"
    assert parking["knowledge_point_name"] in {"两类对象总量总价问题", "鸡兔同笼问题一", "鸡兔同笼问题二", "鸡兔同笼"}
    assert all(
        not (
            candidate["knowledge_point_name"] == "整数除法"
            and candidate["candidate_status"] == "confirmed_candidate"
        )
        for candidate in parking["candidate_knowledge_points"]
    )

    assert profit["confidence_status"] == "confirmed"
    assert profit["knowledge_point_name"] == "利润折扣问题"
    assert all("简单规律" not in candidate["knowledge_point_name"] for candidate in profit["candidate_knowledge_points"])

    assert work["confidence_status"] == "confirmed"
    assert work["knowledge_point_name"] == "工程问题"

    assert transport["confidence_status"] == "confirmed"
    assert transport["knowledge_point_name"] == "运输费用统筹优化"
    assert all(
        not (
            candidate["knowledge_point_name"] == "排列组合"
            and candidate["candidate_status"] == "confirmed_candidate"
        )
        for candidate in transport["candidate_knowledge_points"]
    )


def test_dim5_graph_replays_batch_exam_12_13_ocr_risk_cases():
    digit_swap = _match("一个六位数交换某两位数字后，变成原数的3倍，求这个数。")
    fold_cut = _match("把纸片对折后剪开，展开后得到的图形是哪一个。")
    overlap = _match("两个正方形重叠在一起，已知重叠部分面积，求图形总面积。")
    cylinder = _match("把圆柱的侧面展开后重新围成圆柱，求最大底面积和体积关系。")
    line_plane = _match("平面上用n条直线最多可以把平面分成多少部分？")
    periodic = _match("方格中的数按规律周期重复，求第2024个格子的数。")
    probability = _match("从盒子中随机摸球后放回，求两次都摸到红球的概率。")

    assert digit_swap["confidence_status"] == "confirmed"
    assert digit_swap["knowledge_point_name"] == "数位交换成倍数数字谜"
    assert digit_swap["knowledge_point_name"] != "位值原理"

    assert fold_cut["confidence_status"] == "confirmed"
    assert fold_cut["knowledge_point_name"] == "折叠展开与剪纸问题"

    assert overlap["confidence_status"] == "confirmed"
    assert overlap["knowledge_point_name"] == "重叠面积与容斥面积"

    assert cylinder["confidence_status"] == "confirmed"
    assert cylinder["knowledge_point_name"] == "圆柱侧面展开与体积守恒"

    assert line_plane["confidence_status"] == "confirmed"
    assert line_plane["knowledge_point_name"] == "直线分平面递推"

    assert periodic["confidence_status"] == "confirmed"
    assert any(
        candidate["knowledge_point_name"] == "周期格子与数表规律"
        and candidate["candidate_status"] == "confirmed_candidate"
        for candidate in periodic["candidate_knowledge_points"]
    )

    assert probability["confidence_status"] == "confirmed"
    assert probability["knowledge_point_name"] == "概率初步"


def test_dim5_graph_contains_exam_1_10_curated_topic_nodes():
    graph = Dim5KnowledgeGraph.load()
    nodes = {node.knowledge_point_id: node for node in graph.approved_nodes}
    expected_ids = {
        "dim5.geometry_spatial.cube_section_cut",
        "dim5.geometry_spatial.cube_net_opposite_faces",
        "dim5.geometry_spatial.unit_cube_surface_area",
        "dim5.geometry_spatial.cylinder_roll_unfold_length",
        "dim5.pattern_sequence.calendar_week_cycle",
        "dim5.pattern_sequence.work_rest_cycle",
        "dim5.pattern_sequence.staircase_recurrence",
        "dim5.pattern_sequence.doubling_notification",
        "dim5.pattern_sequence.square_number_sequence_position",
        "dim5.pattern_sequence.equation_pattern_generalization",
        "dim5.logic_strategy.handshake_round_robin",
        "dim5.logic_strategy.truth_rank_logic",
        "dim5.logic_strategy.balance_scale_search",
        "dim5.logic_strategy.chessboard_queen_control",
        "dim5.quantity_application.full_reduction_optimization",
        "dim5.quantity_application.tiered_piecewise_pricing",
        "dim5.quantity_application.taxi_piecewise_fare",
        "dim5.geometry_spatial.midpoint_equal_area",
        "dim5.geometry_spatial.inscribed_square_circle_area",
        "dim5.geometry_spatial.curvilinear_arch_area",
        "dim5.geometry_spatial.pythagorean_area_relation",
        "dim5.geometry_spatial.circle_rectangle_overlap_area",
        "dim5.number_theory.congruence_remainder_system",
        "dim5.number_theory.place_value_digit_equation",
        "dim5.number_theory.vertical_arithmetic_puzzle",
    }

    assert expected_ids <= nodes.keys()
    for node_id in expected_ids:
        node = nodes[node_id]
        assert node.aliases
        assert node.positive_examples
        assert node.negative_examples
        assert node.source_refs


def test_dim5_graph_replays_exam_1_10_topic_reinforcement_cases():
    cases = [
        ("一个正方体一刀切掉一块，判断露出的截面形状是几边形。", "dim5.geometry_spatial.cube_section_cut"),
        ("根据正方体展开图判断写有文字的六个面中哪些是相对面？", "dim5.geometry_spatial.cube_net_opposite_faces"),
        ("若干个棱长是1厘米的小正方体拼成一个立体图形，求露在外面的总表面积。", "dim5.geometry_spatial.unit_cube_surface_area"),
        ("一卷圆柱形彩纸，底面直径、高和纸张厚度已知，将纸卷完全展开后长度是多少？", "dim5.geometry_spatial.cylinder_roll_unfold_length"),
        ("今年5月1日是星期五，经过100天是星期几？", "dim5.pattern_sequence.calendar_week_cycle"),
        ("爸爸工作4天休息1天，妈妈工作2天休息1天，求共同休息日。", "dim5.pattern_sequence.work_rest_cycle"),
        ("每次只能上一级或两级台阶，爬到第10级台阶有多少种走法？", "dim5.pattern_sequence.staircase_recurrence"),
        ("老师打电话通知队员，每分钟每人可以通知一人，求最短几分钟通知所有人。", "dim5.pattern_sequence.doubling_notification"),
        ("完全平方数和非平方数按规律排列，求第99个数。", "dim5.pattern_sequence.square_number_sequence_position"),
        ("观察等式1+3=2^2，1+3+5=3^2的规律，写出第n个等式和公式。", "dim5.pattern_sequence.equation_pattern_generalization"),
        ("6人下棋每两人下一局，已知若干人已下局数，求某人下了几局。", "dim5.logic_strategy.handshake_round_robin"),
        ("甲乙丙取得前三名，每人说一句关于名次的话，其中只有一句真话，推理排名。", "dim5.logic_strategy.truth_rank_logic"),
        ("12瓶盐水中有1瓶较重，用天平称重，至少称几次能保证找出？", "dim5.logic_strategy.balance_scale_search"),
        ("国际象棋皇后控制行列斜线，怎样放置使棋盘每个方格被控制？", "dim5.logic_strategy.chessboard_queen_control"),
        ("三件商品可选，满30元减12元，如何凑单使总费用最低？", "dim5.quantity_application.full_reduction_optimization"),
        ("阶梯水价按分档水量计费，累计用水18立方米，求水费。", "dim5.quantity_application.tiered_piecewise_pricing"),
        ("出租车起步价10元，超过3公里每公里加价，还有空驶费，比较费用。", "dim5.quantity_application.taxi_piecewise_fare"),
        ("在三角形ABC中，AM=BM，CN=AN，求阴影部分面积占三角形的几分之几。", "dim5.geometry_spatial.midpoint_equal_area"),
        ("圆中取最大正方形，已知半径，求阴影面积。", "dim5.geometry_spatial.inscribed_square_circle_area"),
        ("四分之一圆弧围成曲边图形，求弓形面积。", "dim5.geometry_spatial.curvilinear_arch_area"),
        ("直角三角形三边上分别作正方形，利用三个正方形面积关系求面积。", "dim5.geometry_spatial.pythagorean_area_relation"),
        ("扇形和长方形重叠，求公共部分面积和阴影面积。", "dim5.geometry_spatial.circle_rectangle_overlap_area"),
        ("一个整数被7除余2，被5除余3，求最小的这个数。", "dim5.number_theory.congruence_remainder_system"),
        ("若abc表示一个三位数，交换数位后满足等式，求这个三位数。", "dim5.number_theory.place_value_digit_equation"),
        ("残缺的乘法竖式中，在方框填入不是2的数字，使乘法竖式成立。", "dim5.number_theory.vertical_arithmetic_puzzle"),
    ]

    for text, expected_id in cases:
        result = _match_many(text)
        assert result["confidence_status"] == "confirmed", text
        assert result["selected_candidate_id"] == expected_id, text

    balance = _match_many("12瓶盐水中有1瓶较重，用天平称重，至少称几次能保证找出？")
    unit_cube = _match_many("若干个棱长是1厘米的小正方体拼成一个立体图形，求露在外面的总表面积。")
    roll = _match_many("一卷圆柱形彩纸，底面直径、高和纸张厚度已知，将纸卷完全展开后长度是多少？")
    date = _match_many("今年5月1日是星期五，经过100天是星期几？")

    assert all("浓度" not in name for name in _confirmed_candidate_names(balance))
    assert "排列组合" not in _confirmed_candidate_names(unit_cube)
    assert "长度与角度的计算" not in _confirmed_candidate_names(roll)
    assert "还原问题与年龄问题" not in _confirmed_candidate_names(date)


def test_dim5_graph_generic_triggers_do_not_confirm_by_themselves():
    for text in ("填上等于", "综合问题", "基础题型", "基本公式", "求面积", "一个圆", "三角形", "数字", "计算"):
        result = _match(text)
        assert result["confidence_status"] != "confirmed", text


def test_dim5_graph_review_signal_keeps_unconfirmed_dim5_in_applicability_flow():
    assert AIParser._dim5_has_graph_review_signal(
        {
            "band": "",
            "sublevel": "",
            "dim5_structure_facts": [{"fact_key": "transport_optimization"}],
            "candidate_knowledge_points": [],
        }
    )
    assert AIParser._dim5_has_graph_review_signal(
        {
            "band": "",
            "sublevel": "",
            "dim5_structure_facts": [],
            "candidate_knowledge_points": [{"knowledge_point_name": "统计图综合"}],
        }
    )
    assert not AIParser._dim5_has_graph_review_signal(
        {
            "dim5_excluded_reason": "retry_failed",
            "dim5_structure_facts": [{"fact_key": "transport_optimization"}],
        }
    )


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
