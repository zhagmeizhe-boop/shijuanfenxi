from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.services.ocr.base import ParsedQuestion, QuestionType
from app.services.parser.ai_parser import AIParser
from app.services.parser.dim5_knowledge_graph import (
    DIM5_GRAPH_PATH,
    Dim5KnowledgeGraph,
    Dim5FactProfileExtractor,
    Dim5KnowledgeGraphMatcher,
    build_dim5_rule_localization_report,
    normalize_dim5_structure_key,
)
from app.services.scoring.dim5_knowledge import Dim5KnowledgeScorer


EXPECTED_DIM5_GRAPH_NODE_COUNT = 988


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
        assert node.required_structures
        assert node.fact_extraction_hints
        assert node.negative_hints
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


def test_dim5_graph_rules_are_chinese_localized_without_changing_structure_keys():
    payload = json.loads(DIM5_GRAPH_PATH.read_text(encoding="utf-8"))
    report = build_dim5_rule_localization_report(payload)

    assert report["node_count"] == EXPECTED_DIM5_GRAPH_NODE_COUNT
    assert report["required_structures_coverage"] == EXPECTED_DIM5_GRAPH_NODE_COUNT
    assert report["fact_extraction_hints_coverage"] == EXPECTED_DIM5_GRAPH_NODE_COUNT
    assert report["negative_hints_coverage"] == EXPECTED_DIM5_GRAPH_NODE_COUNT
    assert report["chinese_rule_coverage"] == EXPECTED_DIM5_GRAPH_NODE_COUNT
    assert report["english_template_residue_count"] == 0
    assert report["low_quality_rule_count"] == 0

    for node in payload["nodes"]:
        for group in node["required_structures"]:
            for key in group:
                assert key == key.lower()
                assert key.replace("_", "").isalnum()


def test_dim5_high_risk_rules_have_chinese_boundaries():
    payload = json.loads(DIM5_GRAPH_PATH.read_text(encoding="utf-8"))
    by_name = {node["name"]: node for node in payload["nodes"]}

    circle_text = " ".join(by_name["圆与扇形"]["fact_extraction_hints"] + by_name["圆与扇形"]["negative_hints"])
    clock_text = " ".join(
        by_name["牛吃草问题与钟表问题"]["fact_extraction_hints"]
        + by_name["牛吃草问题与钟表问题"]["negative_hints"]
    )
    grazing_text = " ".join(by_name["牛吃草模型"]["fact_extraction_hints"] + by_name["牛吃草模型"]["negative_hints"])
    pie_text = " ".join(by_name["扇形统计图"]["fact_extraction_hints"] + by_name["扇形统计图"]["negative_hints"])

    assert "扇形统计图" in circle_text and "不确认" in circle_text
    assert "顺时针/逆时针" in clock_text and "不能单独触发" in clock_text
    assert "增长 + 消耗 + 时间/原有量" in grazing_text
    assert "statistics_chart_context" in pie_text and "统计图" in pie_text


def test_dim5_fact_profile_prompt_is_chinese_with_stable_english_keys():
    messages = Dim5FactProfileExtractor._build_messages(
        question_id="1",
        raw_text="如图，半圆绕B点顺时针旋转30°，求阴影部分面积。",
        question_type="application",
        image_refs=[],
        ocr_warnings=[],
    )
    prompt = messages[1]["content"]

    assert "只能使用英文结构 key" in prompt
    assert "geometry_circle: 圆" in prompt
    assert "area_goal: 题目目标是求面积" in prompt
    assert "顺时针/逆时针" in prompt
    assert "不得输出 clock_face" in prompt
    assert "Extract ONLY" not in prompt
    assert normalize_dim5_structure_key("旋转方向") == "rotation_direction"
    assert normalize_dim5_structure_key("圆形几何") == "geometry_circle"
    assert normalize_dim5_structure_key("面积目标") == "area_goal"


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


def test_dim5_graph_regresses_wmo_report_four_exposed_cases():
    defined_operation = _match(
        '我们规定一种运算"※"：※2=1×2×3，※3=2×3×4，※4=3×4×5，'
        '如果 1/(※7) - 1/(※8) = ※88 ×□，那么□中应填（  ）。',
        question_type="single_choice",
    )
    reverse = _match(
        "一块冰，每小时失去其质量的一半，八小时后其质量为 9/64 千克，"
        "那么这块冰一开始的质量是（  ）千克。",
        question_type="single_choice",
    )
    work_progress = _match(
        "一件工程做了若干天之后，已完成的部分是未完成部分的 1/7，"
        "再做4天之后，发现已完成的部分是未完成部分的 1/6，"
        "那么这件工程总共需（  ）天才能完成。",
        question_type="single_choice",
    )
    circle_cut_paste = _match(
        "下图正方形的边长为20厘米，图中阴影部分的面积是（  ）平方厘米。"
        "（π取3.14）[几何图形：正方形内含四个扇形，中间形成阴影区域]",
        question_type="single_choice",
    )

    assert defined_operation["confidence_status"] == "confirmed"
    assert defined_operation["knowledge_point_name"] == "定义新运算"
    assert {"defined_operation_rule", "defined_operation_target"} <= set(
        defined_operation["dim5_fact_profile"]["structures"]
    )
    assert not (
        _confirmed_candidate_names(defined_operation)
        & {"妙用加减号", "等式加减法", "小数分数混合运算"}
    )

    assert reverse["confidence_status"] == "confirmed"
    assert reverse["knowledge_point_name"] == "倍半递推与倒推还原"
    assert {"half_recurrence", "reverse_process"} <= set(reverse["dim5_fact_profile"]["structures"])
    assert "小数分数混合运算" not in _confirmed_candidate_names(reverse)

    assert work_progress["confidence_status"] == "confirmed"
    assert work_progress["knowledge_point_name"] == "工程问题"
    assert {"work_rate_task", "work_progress_ratio"} <= set(work_progress["dim5_fact_profile"]["structures"])
    assert "小数分数混合运算" not in _confirmed_candidate_names(work_progress)

    assert circle_cut_paste["confidence_status"] == "confirmed"
    assert circle_cut_paste["knowledge_point_name"] == "圆与扇形"
    assert {"geometry_circle", "gaosi_circle_sector", "area_goal"} <= set(
        circle_cut_paste["dim5_fact_profile"]["structures"]
    )
    assert {"area_decomposition", "gaosi_cut_paste"} & set(
        circle_cut_paste["dim5_fact_profile"]["structures"]
    )


def test_dim5_graph_regresses_confirmed_plan_wmo_targets():
    cases = [
        (
            "韩国、泰国、俄罗斯和新加坡共派了 15 名代表参加第三届"
            '"一带一路"国际合作高峰论坛。各国派出的代表人数都不一样'
            "（每国至少派 1 名）。泰国和新加坡共派出 6 名代表，"
            "俄罗斯和新加坡共派出 7 名代表。仅有一个国家派出了 4 名代表。",
            "奥数三年级：条件枚举 / 整数拆分",
        ),
        (
            "如图，将三角形 ABD 绕 B 点顺时针旋转 90°，得到三角形 CBE。"
            "已知 AB=10 厘米，BE=4 厘米，则图中阴影部分的面积是（  ）平方厘米。"
            "（π 取 3.14）",
            "奥数五年级：整体法求面积 / 旋转割补求阴影面积",
        ),
        (
            "同一条街上的 16 户人家中，有一户的管道漏水。维修工人将关闭部分人家的阀门。"
            "如果他们关闭 8 号和 9 号之间的阀门，而水表显示有水仍在使用，就知道漏水的地方"
            "在 1 号和 8 号之间；若水表未显示有水在使用，则 9 号和 16 号之间漏水。"
            "至少需要关闭几个阀门才能确定漏水的地方？",
            "奥数六年级：二分策略 / 信息查找 / 最优排查",
        ),
        (
            "经统计，某校六年级学生的家长中有 280 人使用微信和老师联系，其中不经常使用微信的是"
            "经常使用微信的 2/3，则不经常使用微信的有（  ）人。",
            "校内六年级：分数应用题 / 整体与部分关系",
        ),
        (
            "如图，四边形 ABCD 的对角线 AC 与 BD 相交于 O，边 BC 上有一点 E，BE：EC=7：5。"
            "三角形 ABO 的面积为 36，三角形 ADO 的面积为 18，三角形 CDO 的面积为 24。"
            "则三角形 AED 的面积是（  ）。",
            "奥数五年级：蝴蝶模型 / 面积比例",
        ),
        (
            "思思采摘了一些葡萄，放入一个圆柱形木桶里酿葡萄酒。桶的底面外直径是 48cm，"
            "内直径是 40cm，外高是 50cm，内高是 40cm。（π取3）给木桶的盖子和侧面进行装饰，"
            "装饰部分的面积是多少平方厘米？酒水的高度是木桶内高度的4/5，求酒水体积。",
            "校内六年级：圆柱表面积与体积综合",
        ),
    ]

    for text, expected_display in cases:
        result = _match(text)
        assert result["confidence_status"] == "confirmed"
        assert result["knowledge_display_name"] == expected_display


def test_dim5_graph_regresses_grade3_midterm_confirmed_scope():
    cases = [
        (
            "正方形边长扩大为原来的 3 倍，周长扩大为原来的______倍。",
            "校内三年级：长方形和正方形周长 / 周长倍数关系",
        ),
        (
            "□46÷5，要使商是三位数，□里最小填______；要使84□÷4 的商末尾有 0，□里最大填______。",
            "校内三年级：除数是一位数的竖式计算 / 商的位数与末尾0判断",
        ),
        (
            "将一张正方形纸上下对折，周长比原正方形的周长减少8厘米，原正方形的周长是_____厘米。"
            "如果再对折1次，得到的新图形周长是_____厘米。",
            "校内三年级：长方形和正方形周长 / 折叠后的周长变化",
        ),
        (
            "计算下面图形的周长。（单位：厘米）（1）五边形，边长分别为5、5、5、5、5"
            "（2）阶梯形，尺寸标注为3、12、3、12",
            "校内三年级：多边形周长计算 / 不规则图形周长",
        ),
        (
            "把 24 张边长为 2 分米的正方形卡片贴在一起，做成长方形展示板，要在展示板四周贴装饰条。"
            "怎样设计能让贴的装饰条最少？",
            "校内三年级：长方形和正方形周长 / 拼接图形周长最小化",
        ),
    ]

    for text, expected_display in cases:
        result = _match(text)
        assert result["confidence_status"] == "confirmed"
        assert result["knowledge_display_name"] == expected_display


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


def test_dim5_new_chain_outputs_decision_artifacts_for_circle_rotation_area():
    result = _match_many(
        "如图，直径AB = 6的半圆，绕B点顺时针旋转30°，则图中阴影部分的面积是多少？",
        max_candidates=12,
    )

    assert result["confidence_status"] == "confirmed"
    assert result["selected_candidate_id"] == "dim5.gaosi.5.268236d5c977"
    assert result["knowledge_point_name"] == "圆与扇形"
    assert result["knowledge_level"] == "L4"
    assert result["dim5_decision"]["decision_status"] == "confirmed"
    assert result["dim5_decision"]["knowledge_point_id"] == result["selected_candidate_id"]
    assert result["dim5_fact_profile"]["structures"]
    assert "rotation_direction" in result["dim5_fact_profile"]["structures"]
    assert "gaosi_grazing_clock" not in result["dim5_fact_profile"]["structures"]
    assert result["graph_candidates"]
    assert result["admission_results"]
    assert all(
        not (
            candidate["knowledge_point_id"] == "dim5.gaosi.5.3d2bd8254119"
            and candidate["candidate_status"] == "confirmed_candidate"
        )
        for candidate in result["graph_candidates"]
    )


def test_dim5_grazing_requires_growth_consumption_and_time_structure():
    bare = _match("牛吃草")
    full = _match(
        "一片草地原有草量，每天匀速生长，若8头牛12天吃完，10头牛8天吃完，问几头牛6天吃完？"
    )

    assert bare["confidence_status"] != "confirmed"
    assert bare["dim5_decision"]["decision_status"] == "review_required"
    assert "gaosi_grazing_clock" not in bare["dim5_fact_profile"]["structures"]

    assert full["confidence_status"] == "confirmed"
    assert full["selected_candidate_id"] == "dim5.gaosi.5.3d2bd8254119"
    assert {"resource_growth", "resource_consumption", "resource_time_or_initial", "gaosi_grazing_clock"} <= set(
        full["dim5_fact_profile"]["structures"]
    )


def test_dim5_pie_chart_blocks_geometry_circle_sector_candidate():
    result = _match_many(
        "某校学生参加社团情况如扇形统计图，STEAM占30%，共有120人，求总人数。",
        max_candidates=16,
    )

    assert result["confidence_status"] == "confirmed"
    assert result["knowledge_domain"] == "statistics_probability"
    assert any(
        candidate["knowledge_point_id"] == "dim5.gaosi.5.268236d5c977"
        and candidate["candidate_status"] == "blocked_candidate"
        for candidate in result["graph_candidates"]
    )


def test_dim5_corrects_confirmed_report_specific_misclassifications():
    cases = [
        (
            "一个三角形三个角的度数的比是 3：2：4，这个三角形是（  ）。 A.锐角三角形 B.直角三角形 C.钝角三角形 D.等腰三角形",
            "校内四年级：三角形的分类 / 按角判断三角形",
            "triangle_angle_classification",
        ),
        (
            "一圆柱和一圆锥的底面积相等，圆柱和圆锥的体积比是 3：2，圆柱和圆锥高的比是（  ） A.1：2 B.2：1 C.1：3 D.2：3",
            "校内六年级：圆柱圆锥 / 等底面积下体积与高的关系",
            "cylinder_cone_volume_height_ratio",
        ),
        (
            "如图，一长方形被一条直线分成两个长方形，这两个长方形的宽的比为 1：3，若阴影三角形面积为 3 平方厘米，则原长方形面积为（  ）平方厘米。 A.4 B.6 C.8 D.10",
            "校内五年级：组合图形的面积 / 分割与阴影面积",
            "composite_area_split_relation",
        ),
        (
            "（圆柱和圆锥体的体积）高相同的圆柱与圆锥，底面半径之比为2:3，则它们的体积比是（）。",
            "校内六年级：圆柱与圆锥的体积比问题",
            "cylinder_cone_volume_ratio",
        ),
        (
            "（找规律）将正整数依次按下表规律排成5列，根据表中的排列规律，数2016应排在第（）行，第（）列。",
            "奥数四年级：数列与数表",
            "number_table_position_pattern",
        ),
        (
            "（分数和百分数的综合应用）一个长方形，若长增加1/4，宽减少1/5，那么新的长方形面积是原来的（）%",
            "校内六年级：分数百分数综合应用 / 长方形面积变化",
            "rectangle_area_fraction_percent_change",
        ),
    ]

    for text, expected_display, expected_structure in cases:
        result = _match_many(text, max_candidates=24)

        assert result["confidence_status"] == "confirmed", text
        assert result["knowledge_display_name"] == expected_display
        assert expected_structure in result["dim5_fact_profile"]["structures"]


def test_dim5_specific_guards_do_not_block_true_ratio_permutation_or_discount():
    ratio = _match_many("甲、乙两数的比是3：5，甲数是24，求乙数是多少。", max_candidates=16)
    permutation = _match_many("5名同学排队拍照，一共有多少种不同的排法？", max_candidates=16)
    discount = _match_many("一件衣服标价140元，打七折出售还赚了28元。这件衣服的成本是多少元？", max_candidates=16)

    assert ratio["confidence_status"] == "confirmed"
    assert "比例" in ratio["knowledge_display_name"] or "比例" in ratio["knowledge_point_name"]

    assert permutation["confidence_status"] == "confirmed"
    assert permutation["knowledge_display_name"] == "奥数四年级：排列组合"

    assert discount["confidence_status"] == "confirmed"
    assert {"profit_discount", "price_profit_relation"} <= set(discount["dim5_fact_profile"]["structures"])
    assert "rectangle_area_fraction_percent_change" not in discount["dim5_fact_profile"]["structures"]


def test_dim5_graph_regresses_xsc_two_paper_diff_records():
    diff_path = Path(__file__).resolve().parents[4] / "outputs" / "dim5_diff_20260522" / "dim5_diff_data.json"
    if not diff_path.exists():
        pytest.skip("小升初维度5差异清单不在当前工作区")

    rows = json.loads(diff_path.read_text(encoding="utf-8"))["rows"]
    allowed_review = {
        ("学情诊断卷-思维", "9"),
        ("学情诊断卷-思维", "10"),
        ("学情诊断卷-思维", "11"),
        ("学情诊断卷-思维", "12"),
        ("分班考模拟卷", "17（1）"),
        ("分班考模拟卷", "17（2）"),
        ("分班考模拟卷", "18"),
        ("分班考模拟卷", "19"),
        ("分班考模拟卷", "20"),
    }
    expected_display_overrides = {
        ("学情诊断卷-校内", "1"): "校内六年级：负数的认识 / 用正负数表示生活中的量",
        ("学情诊断卷-校内", "2"): "校内四年级：三角形三边关系 / 判断能否组成三角形",
        ("学情诊断卷-校内", "7"): "校内六年级：长正方体体积与容积 / 浸没水面上升",
        ("学情诊断卷-校内", "10"): "校内六年级：旋转体体积 / 面积比与体积比",
        ("学情诊断卷-校内", "17"): "校内六年级：圆柱圆锥 / 组合图形体积",
        ("学情诊断卷-思维", "5"): "奥数六年级：不完全浸没水面上升",
        ("学情诊断卷-思维", "7"): "奥数知识：条件判断型新定义运算",
        ("学情诊断卷-思维", "13"): "奥数六年级：行程反比 / 速度时间关系",
        ("学情诊断卷-思维", "16"): "奥数六年级：列表分析 / 多对象比例",
        ("学情诊断卷-思维", "17"): "奥数六年级：等比面积数列求和",
        ("分班考模拟卷", "5"): "校内五年级：用字母表示数 / 图形规律",
        ("分班考模拟卷", "6"): "校内六年级：小数、分数、百分数的比较大小",
        ("分班考模拟卷", "10"): "奥数五年级：长方体染色计数",
        ("分班考模拟卷", "14"): "奥数五年级：切片法求体积",
        ("分班考模拟卷", "24"): "校内六年级：圆锥体积与长方体包装表面积",
        ("分班考模拟卷", "26"): "奥数六年级：十字交叉浓度问题",
        ("分班考模拟卷", "27"): "奥数四年级：循环赛规律 / 比赛场次",
    }

    matcher = Dim5KnowledgeGraphMatcher()
    confirmed = 0
    review_only = 0
    for row in rows:
        key = (row["source_paper"], row["question_label"])
        result = matcher.match(
            question_text=row["question_text"],
            question_type=row.get("question_type") or "",
            max_candidates=24,
        )
        if key in allowed_review:
            assert result["confidence_status"] == "review_required", key
            review_only += 1
            continue

        assert result["confidence_status"] == "confirmed", key
        assert result["knowledge_track_label"] == row["expected_track"], key
        if key in expected_display_overrides:
            assert result["knowledge_display_name"] == expected_display_overrides[key], key
        confirmed += 1

    assert confirmed == 62
    assert review_only == 9


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
    assert feature["dim5_decision"]["decision_status"] == "confirmed"
    assert feature["dim5_fact_profile"]["structures"]
    assert feature["graph_candidates"]
    assert feature["admission_results"]
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
            "dim5_fact_profile": {"structures": ["resource_growth", "resource_consumption"]},
            "graph_candidates": [{"knowledge_point_id": "dim5.quantity_application.grazing"}],
            "admission_results": [{"knowledge_point_id": "dim5.quantity_application.grazing", "admission_status": "passed"}],
            "dim5_decision": {
                "decision_status": "confirmed",
                "knowledge_point_id": "dim5.quantity_application.grazing",
                "knowledge_point_name": "牛吃草模型",
                "knowledge_domain": "quantity_application",
                "knowledge_level": "L4",
                "evidence": ["原有草量", "每天匀速生长", "吃完"],
            },
        }
    )

    assert result.applicable is True
    assert result.score == 8.0
    assert result.details["canonical_knowledge_point"] == "牛吃草模型"
    assert result.details["confidence_status"] == "confirmed"
    assert result.details["knowledge_display_name"] == "奥数知识：牛吃草模型"
    assert result.details["dim5_decision"]["decision_status"] == "confirmed"
    assert result.details["graph_candidates"]
    assert "原有草量" in result.details["level_evidence"]
