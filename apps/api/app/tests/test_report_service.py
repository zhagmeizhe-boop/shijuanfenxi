from app.services.report.report_service import ReportService
from app.services.report.pdf_generator import PDFExportService
from app.services.scoring.paper_aggregator import QuestionDimensionScore


def test_report_service_hides_user_visible_report_warnings():
    warnings = [
        "第 1 页题号 1 缺少明确分值。",
        "第 2 页题号 3 未识别到明确分值。",
        "第 3 页题号 4 分值格式无法解析。",
        "第 1 页题号 2 重复，需检查。",
        "第 2 页题号 8 题干为空。",
    ]

    sanitized = ReportService._sanitize_report_warnings(warnings)

    assert sanitized == []


def test_report_payload_does_not_expose_structure_warnings():
    service = ReportService()

    report = service._build_report_payload(
        paper_id="paper-warning-hidden",
        paper_title="结构化提示测试卷",
        dimension_details=[],
        report_warnings=["第 1 页题号 2 重复，需检查。"],
    )

    assert report["report_warnings"] == []


def test_question_short_label_normalizes_common_display_forms():
    cases = {
        "（18）": "18",
        "(19)": "19",
        "1.": "1",
        "18、": "18",
        "三-15": "15",
        "二-2": "2",
        "10a": "10a",
        "12-1": "12-1",
    }

    for raw_label, expected in cases.items():
        assert ReportService._normalize_question_short_label(raw_label) == expected


def test_report_payload_builds_parent_summary_and_question_distribution():
    service = ReportService()
    dimension_details = [
        {
            "code": "dim1",
            "name": "数学运算",
            "score": 5.0,
            "level": 3,
            "level_label": "中等",
            "score_status": "scored",
            "evidence": "",
        },
        {
            "code": "dim3",
            "name": "场景理解复杂度",
            "score": 8.5,
            "level": 5,
            "level_label": "困难",
            "score_status": "scored",
            "evidence": "",
        },
        {
            "code": "dim6",
            "name": "逻辑链条",
            "score": 8.0,
            "level": 4,
            "level_label": "较难",
            "score_status": "scored",
            "evidence": "",
        },
    ]
    question_scores = [
        QuestionDimensionScore(
            question_id="q1",
            question_no="1",
            question_display_label="一-1",
            score=5.0,
            dim_scores={"dim1": 3.0},
            applicable_dims=["dim1"],
        ),
        QuestionDimensionScore(
            question_id="q2",
            question_no="2",
            question_display_label="一-2",
            score=5.0,
            dim_scores={"dim1": 4.0, "dim3": 6.0},
            applicable_dims=["dim1", "dim3"],
        ),
        QuestionDimensionScore(
            question_id="q3",
            question_no="3",
            question_display_label="二-3",
            score=5.0,
            dim_scores={"dim3": 7.0, "dim6": 9.0},
            applicable_dims=["dim3", "dim6"],
        ),
        QuestionDimensionScore(
            question_id="q4",
            question_no="4",
            score=5.0,
            dim_scores={},
            applicable_dims=[],
        ),
    ]

    report = service._build_report_payload(
        paper_id="paper-parent-summary",
        paper_title="家长速读测试卷",
        dimension_details=dimension_details,
        question_scores=question_scores,
    )

    position = report["difficulty_position"]
    assert position["position_summary"] == "奥数杯赛竞赛难度试卷，难度很高，适合挑战高难题和竞赛题。"
    assert position["target_students"] == "适合成绩优秀、准备挑战竞赛或高强度选拔的学生。"
    assert position["parent_summary"][0] == "这张试卷难度很高，这是奥数杯赛竞赛难度的试卷，适合看孩子能不能挑战高难题和竞赛题。"
    assert "较难题约占 33.3%" in position["parent_summary"][1]
    assert "主要卡点在读懂题意和连续推理" in position["parent_summary"][1]
    assert "孩子要先读懂题意，并把步骤完整推下去" in position["parent_summary"][1]
    assert "知识跨度" not in position["parent_summary"][1]

    distribution = position["question_distribution"]
    assert distribution["basis"] == "question_count"
    assert distribution["classified_count"] == 3
    assert distribution["unclassified_count"] == 1
    buckets = {bucket["key"]: bucket for bucket in distribution["buckets"]}
    assert buckets["basic"]["percentage"] == 33.3
    assert buckets["basic"]["questions"][0]["question_display_label"] == "一-1"
    assert buckets["basic"]["questions"][0]["question_short_label"] == "1"
    assert buckets["medium"]["questions"][0]["question_display_label"] == "一-2"
    assert buckets["medium"]["questions"][0]["question_short_label"] == "2"
    assert buckets["hard"]["questions"][0]["question_display_label"] == "二-3"
    assert buckets["hard"]["questions"][0]["question_short_label"] == "3"


def test_parent_summary_changes_with_top_dimension_scores():
    summary = ReportService._build_parent_summary(
        3,
        [
            {"code": "dim1", "score": 7.5, "level": 4, "score_status": "scored"},
            {"code": "dim2", "score": 7.0, "level": 4, "score_status": "scored"},
            {"code": "dim3", "score": 4.0, "level": 2, "score_status": "scored"},
        ],
        {
            "buckets": [
                {"key": "basic", "percentage": 40.0},
                {"key": "medium", "percentage": 35.0},
                {"key": "hard", "percentage": 25.0},
            ]
        },
    )

    assert summary[0] == "这张试卷有一定难度，这是校内期中期末考试难度的试卷，题目有一定变化，适合检验孩子能否稳定拿到中高分。"
    assert "较难题约占 25.0%" in summary[1]
    assert "主要卡点在计算准确率和看图找关系" in summary[1]
    assert "孩子要少算错，并看懂图形关系" in summary[1]


def test_parent_summary_uses_low_pressure_wording_when_all_dimensions_below_six():
    summary = ReportService._build_parent_summary(
        2,
        [
            {"code": "dim1", "score": 5.5, "level": 3, "score_status": "scored"},
            {"code": "dim3", "score": 5.0, "level": 3, "score_status": "scored"},
            {"code": "dim6", "score": 4.5, "level": 2, "score_status": "scored"},
        ],
        {"buckets": [{"key": "hard", "percentage": 8.3}]},
    )

    assert summary[0] == "这张试卷难度适中，这是课内核心提升型试卷，主要看孩子能不能把学过的知识稳定用出来。"
    assert "较难题约占 8.3%" in summary[1]
    assert "整体没有特别突出的卡点" in summary[1]
    assert "重点看孩子能不能稳定完成基础题和中等题" in summary[1]


def test_parent_summary_uses_distribution_fallback_when_missing_hard_bucket():
    summary = ReportService._build_parent_summary(
        1,
        [{"code": "dim6", "score": 8.2, "level": 5, "score_status": "scored"}],
        {"buckets": [{"key": "basic", "percentage": 100.0}]},
    )

    assert summary[0] == "这张试卷整体比较基础，这是课内基础巩固型试卷，主要看孩子基础概念和常规计算是否过关。"
    assert "暂时没有足够的题目难度结构数据" in summary[1]
    assert "主要卡点在连续推理" in summary[1]


def test_existing_parent_summary_snapshot_is_not_rewritten():
    report_json = {
        "dimension_details": [
            {"code": "dim3", "score": 9.0, "level": 5, "score_status": "scored"}
        ],
        "difficulty_position": {
            "level": 4,
            "parent_summary": ["旧第一句", "旧第二句"],
        },
    }

    ReportService._ensure_difficulty_position_extensions(report_json, question_scores=[])

    assert report_json["difficulty_position"]["parent_summary"] == ["旧第一句", "旧第二句"]
    assert isinstance(report_json["difficulty_position"]["question_distribution"], dict)


def test_pdf_export_does_not_render_report_warning_banner():
    html = PDFExportService()._build_report_warning_html(
        ["第 1 页题号 2 重复，需检查。"]
    )

    assert html == ""


def _build_pdf_report_payload(dimension_details):
    return {
        "report_id": "pdf-radar-test",
        "paper_id": "pdf-radar-test",
        "paper_title": "雷达图测试卷",
        "generated_at": "2026-05-09T00:00:00",
        "dimensions": {
            "computation": 70.0,
            "concept": 0.0,
            "logic": 0.0,
            "spatial": 0.0,
            "application": 0.0,
            "innovation": 0.0,
        },
        "dimension_details": dimension_details,
        "report_warnings": [],
        "difficulty_position": {
            "level": 3,
            "label": "拔高卷",
            "overall_score": 7.0,
            "target_students": "适合测试。",
            "description": "用于测试 PDF 雷达图。",
        },
    }


def test_pdf_export_renders_parent_summary_and_question_distribution():
    payload = _build_pdf_report_payload([])
    payload["difficulty_position"]["parent_summary"] = [
        "这张试卷难度偏高，这是小升初分班考难度的试卷，题目更绕、步骤更多，会明显考验孩子做难题的稳定性。",
        "从题目结构看，较难题约占 33.3%。主要卡点在读懂题意和连续推理：孩子要先读懂题意，并把步骤完整推下去。",
    ]
    payload["difficulty_position"]["question_distribution"] = {
        "basis": "question_count",
        "classification": "average_applicable_dimension_score",
        "total_count": 3,
        "classified_count": 3,
        "unclassified_count": 0,
        "buckets": [
            {
                "key": "basic",
                "label": "基础题",
                "description": "主要检查基本概念、直接计算和常规方法。",
                "count": 1,
                "percentage": 33.3,
                "questions": [{"question_display_label": "（18）", "question_no": "18"}],
            },
            {
                "key": "medium",
                "label": "中等题",
                "description": "需要一定转化、综合运用或稳定的解题步骤。",
                "count": 1,
                "percentage": 33.3,
                "questions": [{"question_display_label": "三-15", "question_no": "15"}],
            },
            {
                "key": "hard",
                "label": "较难题",
                "description": "更容易拉开差距。",
                "count": 1,
                "percentage": 33.3,
                "questions": [{"question_display_label": "1.", "question_no": "1"}],
            },
        ],
    }

    html = PDFExportService()._generate_html(payload)

    assert "家长速读" in html
    assert "主要卡点在读懂题意和连续推理" in html
    assert "较难题约占 33.3%" in html
    assert "试卷难度综合分" in html
    assert "试卷定位" in html
    assert "校内期中期末考试难度试卷" in html
    assert "题目难度结构" in html
    assert "基础题" in html
    assert "中等题" in html
    assert "较难题" in html
    assert "33.3%" in html
    assert "（18）" not in html
    assert "三-15" not in html
    assert "18" in html
    assert "15" in html


def test_pdf_export_parent_summary_fallback_is_parent_friendly():
    html = PDFExportService()._build_parent_summary_html(
        {},
        "拔高卷",
        "",
        "校内期中期末考试难度试卷，题目有一定变化，适合检验孩子能否稳定拿到中高分。",
    )

    assert "这张试卷整体定位为拔高卷" in html
    assert "校内期中期末考试难度试卷" in html
    assert "重点关注计算准确率、看图找关系、读懂题意、整理条件、知识混合使用和连续推理" in html
    assert "六维评价明细" not in html


def test_pdf_export_radar_renders_static_svg_for_not_covered_dimensions():
    html = PDFExportService()._generate_html(
        _build_pdf_report_payload(
            [
                {
                    "code": "dim1",
                    "name": "数学运算",
                    "score": 7.0,
                    "level": 4,
                    "level_label": "较难",
                    "score_status": "scored",
                    "evidence": "计算负担较高。",
                },
                {
                    "code": "dim2",
                    "name": "几何直观与空间想象",
                    "score": 0.0,
                    "level": 0,
                    "level_label": "未覆盖",
                    "score_status": "not_covered",
                    "evidence": "未覆盖。",
                },
            ]
        )
    )

    assert '<svg class="report-radar-svg"' in html
    assert 'data-testid="radar-data-area"' in html
    assert 'data-testid="radar-data-line"' in html
    assert 'stroke="#294766" stroke-width="3"' in html
    assert "NaN" not in html
    assert "None" not in html
    assert "null" not in html
    assert "echarts.min.js" not in html
    assert "chartReady" not in html
    assert "value: chartValues" not in html


def test_pdf_export_radar_shows_empty_state_when_all_dimensions_not_covered():
    dimension_details = [
        {
            "code": code,
            "name": name,
            "score": 0.0,
            "level": 0,
            "level_label": "未覆盖",
            "score_status": "not_covered",
            "evidence": "未覆盖。",
        }
        for code, name in [
            ("dim1", "数学运算"),
            ("dim2", "几何直观与空间想象"),
            ("dim3", "场景理解复杂度"),
            ("dim4", "建模解题复杂度"),
            ("dim5", "知识广度"),
            ("dim6", "逻辑链条"),
        ]
    ]

    html = PDFExportService()._generate_html(_build_pdf_report_payload(dimension_details))

    assert 'id="radar-chart" class="is-empty"><span>暂无可绘制维度</span>' in html
    assert 'data-testid="radar-svg"' not in html
    assert 'data-testid="radar-data-line"' not in html
    assert "echarts.min.js" not in html
    assert "chartReady" not in html


def test_pdf_export_dim1_evidence_explains_score_not_question_counts():
    html = PDFExportService()._generate_html(
        _build_pdf_report_payload(
            [
                {
                    "code": "dim1",
                    "name": "数学运算",
                    "score": 8.6,
                    "level": 4,
                    "level_label": "较难",
                    "score_status": "scored",
                    "evidence": "旧概览。",
                    "score_breakdown": {
                        "pure_calculation": {"question_count": 2},
                        "embedded_calculation": {"question_count": 4},
                    },
                }
            ]
        )
    )

    assert "计算维度，综合得分 8.6 分" in html
    assert "说明本卷计算难度较高" in html
    assert "共 6 道题计入数学运算评分" not in html
    assert "纯计算题和" not in html


def test_pdf_export_dim3_evidence_explains_scenario_comprehension_score():
    html = PDFExportService()._generate_html(
        _build_pdf_report_payload(
            [
                {
                    "code": "dim3",
                    "name": "场景理解复杂度",
                    "score": 8.6,
                    "level": 4,
                    "level_label": "较难",
                    "score_status": "scored",
                    "evidence": "共 4 道相关题目；题级平均维度分 8.6 分，判定为拔高。",
                }
            ]
        )
    )

    assert "场景理解复杂度维度，综合得分 8.6 分" in html
    assert "学生读题理解题意上设置了明显难度" in html
    assert "场景相对复杂" in html
    assert "按题目等级加权" not in html
    assert "高等级题" not in html
    assert "共 4 道相关题目" not in html
    assert "题级平均维度分" not in html


def test_pdf_export_dim6_evidence_explains_logic_chain_evaluation_point():
    html = PDFExportService()._generate_html(
        _build_pdf_report_payload(
            [
                {
                    "code": "dim6",
                    "name": "逻辑链条",
                    "score": 8.6,
                    "level": 4,
                    "level_label": "较难",
                    "score_status": "scored",
                    "evidence": "共 4 道相关题目；题级平均维度分 8.6 分，判定为拔高。",
                }
            ]
        )
    )

    assert "逻辑推理综合得分 8.6 分" in html
    assert "这张试卷不少题解题链条较长" in html
    assert "连续推进 3-4 步" in html
    assert "逻辑链条维度，综合得分" not in html
    assert "逻辑链条长度" not in html
    assert "共 4 道相关题目" not in html
    assert "题级平均维度分" not in html


def test_pdf_export_dim5_evidence_explains_knowledge_breadth_score():
    html = PDFExportService()._generate_html(
        _build_pdf_report_payload(
            [
                {
                    "code": "dim5",
                    "name": "知识广度",
                    "score": 8.6,
                    "level": 4,
                    "level_label": "较难",
                    "score_status": "scored",
                    "evidence": "按知识范围等级权重计算，权重得分 8.6 分。",
                }
            ]
        )
    )

    assert "知识广度综合得分 8.6 分" in html
    assert "说明本卷知识广度较高" in html
    assert "五六年级奥数典型方法或七年级基础前置知识" in html
    assert "按知识范围等级权重计算" not in html


def test_pdf_export_dim4_evidence_explains_modeling_solution_score():
    html = PDFExportService()._generate_html(
        _build_pdf_report_payload(
            [
                {
                    "code": "dim4",
                    "name": "建模解题复杂度",
                    "score": 8.2,
                    "level": 4,
                    "level_label": "较难",
                    "score_status": "scored",
                    "evidence": "共 15 道题纳入建模解题复杂度评分；按建模解题等级权重计算；权重得分 8.2 分。",
                }
            ]
        )
    )

    assert "综合得分为 8.2 分" in html
    assert "在解题思路上有较明显难度" in html
    assert "先把条件之间的关系理清楚" in html
    assert "建模解题复杂度综合得分" not in html
    assert "按题目等级加权" not in html
    assert "列表" not in html
    assert "画图" not in html
    assert "比例" not in html
    assert "方程" not in html
    assert "表格" not in html
    assert "共 15 道题纳入建模解题复杂度评分" not in html
    assert "按建模解题等级权重计算" not in html
    assert "权重得分" not in html


def test_pdf_export_dim5_counted_question_uses_structured_sentence():
    html = PDFExportService()._generate_html(
        _build_pdf_report_payload(
            [
                {
                    "code": "dim5",
                    "name": "知识广度",
                    "score": 8.0,
                    "level": 4,
                    "level_label": "较难",
                    "score_status": "scored",
                    "evidence": "旧概览。",
                    "counted_questions": [
                        {
                            "question_no": "8",
                            "question_display_label": "8",
                            "summary": "面积比模型",
                            "score": 8.0,
                            "level_code": "L4",
                            "difficulty_label": "较难（8.0）",
                            "knowledge_source_text": "五六年级奥数",
                            "knowledge_point_text": "面积比模型",
                            "score_reason": "难点在于要识别等高、共边或割补关系，并把图形面积关系转化为比例关系。",
                            "reason": "旧文案：奥数面积比，因此计为较难。",
                        }
                    ],
                }
            ]
        )
    )

    assert (
        "较难（8.0）：本题属于五六年级奥数的面积比模型；"
        "难点在于要识别等高、共边或割补关系，并把图形面积关系转化为比例关系。"
    ) in html
    assert "命中" not in html
    assert "因此计为" not in html


def test_pdf_export_dim4_counted_question_uses_structured_sentence():
    html = PDFExportService()._generate_html(
        _build_pdf_report_payload(
            [
                {
                    "code": "dim4",
                    "name": "建模解题复杂度",
                    "score": 9.5,
                    "level": 5,
                    "level_label": "困难",
                    "score_status": "scored",
                    "evidence": "旧概览。",
                    "counted_questions": [
                        {
                            "question_no": "15",
                            "question_display_label": "15",
                            "summary": "数论约束",
                            "score": 9.5,
                            "level_code": "L5",
                            "difficulty_label": "困难（9.5）",
                            "knowledge_point_text": "数论约束",
                            "practice_level_text": "综合构造建模",
                            "score_reason": "难点在于要把整除、余数和范围条件一起回查，逐步排除不满足条件的数。",
                            "reason": "高思题目级参考画像已校准到 L5。",
                        }
                    ],
                }
            ]
        )
    )

    assert (
        "困难（9.5）：本题是数论约束中的综合构造建模；"
        "难点在于要把整除、余数和范围条件一起回查，逐步排除不满足条件的数。"
    ) in html
    assert "校准" not in html
    assert "参考画像" not in html


def test_pdf_export_dim4_counted_question_filters_english_score_reason():
    html = PDFExportService()._generate_html(
        _build_pdf_report_payload(
            [
                {
                    "code": "dim4",
                    "name": "建模解题复杂度",
                    "score": 8.0,
                    "level": 4,
                    "level_label": "较难",
                    "score_status": "scored",
                    "evidence": "旧概览。",
                    "counted_questions": [
                        {
                            "question_no": "20",
                            "question_display_label": "20",
                            "summary": "反射路径",
                            "score": 8.0,
                            "level_code": "L4",
                            "difficulty_label": "较难（8.0）",
                            "knowledge_point_text": "反射路径",
                            "practice_level_text": "多关系建模",
                            "score_reason": (
                                "This problem requires understanding the 90-degree reflection rule, "
                                "then applying coordinate management through multiple reflections."
                            ),
                            "reason": "旧文案。",
                        }
                    ],
                }
            ]
        )
    )

    assert (
        "较难（8.0）：本题是反射路径中的多关系建模；"
        "难点在于不能直接套模板，需要构造中间量、分类回查或重组关系。"
    ) in html
    assert "This problem" not in html
    assert "requires understanding" not in html
