from app.services.ocr.baidu_provider import BaiduOCRProvider, OCRLine
from app.services.ocr.base import QuestionCountAudit, QuestionType, SubItemCandidate
from app.services.ocr.layout_types import QuestionAnchor


def _provider() -> BaiduOCRProvider:
    return BaiduOCRProvider(config={})


def test_extract_question_label_preserves_plain_numeric_prefix():
    provider = _provider()

    assert provider._extract_question_label("4. 计算下面各题") == ("4", "4.")


def test_extract_question_label_preserves_parenthesized_prefix():
    provider = _provider()

    assert provider._extract_question_label("（4）计算下面各题") == ("4", "（4）")


def test_extract_question_label_supports_chinese_numeral_prefix():
    provider = _provider()

    assert provider._extract_question_label("四、计算下面各题") == ("4", "四、")


def test_extract_question_label_rejects_formula_prefix():
    provider = _provider()

    assert provider._extract_question_label("20.18-26÷5") is None


def test_extract_question_label_rejects_decimal_value():
    provider = _provider()

    assert provider._extract_question_label("1.4") is None


def test_extract_question_label_rejects_ellipsis_continuation():
    provider = _provider()
    line = OCRLine(
        text="20...将所有数如此排列，2018在第",
        left=980,
        top=120,
        width=320,
        height=24,
    )

    assert provider._extract_question_label(line.text) is None
    assert provider._is_zone_seed_line(line) is False


def test_extract_section_index_raw_from_heading():
    provider = _provider()

    assert provider._extract_section_index_raw("二、解答题") == "二"


def test_extract_section_index_raw_ignores_regular_question_text():
    provider = _provider()

    assert provider._extract_section_index_raw("四、求阴影部分面积") is None


def test_formula_enhancement_is_attempted_for_formula_fill_blank():
    provider = _provider()

    assert (
        provider._should_try_formula_enhancement(
            "计算：3/4 + 1/6 = ____",
            QuestionType.FILL_BLANK,
            1,
        )
        is True
    )


def test_formula_enhancement_is_skipped_for_plain_application():
    provider = _provider()

    assert (
        provider._should_try_formula_enhancement(
            "一辆汽车3小时行了180千米，平均每小时行多少千米？",
            QuestionType.APPLICATION,
            2,
        )
        is False
    )


def test_visual_need_marks_table_chart_as_required():
    provider = _provider()

    visual = provider._classify_visual_need(
        "根据下表完成统计图，并回答问题。",
        QuestionType.COMPREHENSIVE,
        [],
    )

    assert visual["category"] == "table_chart"
    assert visual["required"] is True
    assert visual["attach_recommended"] is True


def test_visual_need_marks_geometry_context_as_attach_only():
    provider = _provider()

    visual = provider._classify_visual_need(
        "一个圆柱的侧面积是62.8平方厘米，求它的高。",
        QuestionType.APPLICATION,
        [],
    )

    assert visual["category"] == "geometry_context"
    assert visual["required"] is False
    assert visual["attach_recommended"] is True


def test_visual_need_marks_multi_part_layout_as_attach_only():
    provider = _provider()

    visual = provider._classify_visual_need(
        "观察下面图形并回答问题。",
        QuestionType.SOLUTION,
        [SubItemCandidate(candidate_no="1", raw_text=""), SubItemCandidate(candidate_no="2", raw_text="")],
    )

    assert visual["category"] == "multi_part_layout"
    assert visual["required"] is False
    assert visual["attach_recommended"] is True


def test_direction_to_rotation_degrees_matches_baidu_direction_mapping():
    provider = _provider()

    assert provider._direction_to_rotation_degrees(0) == 0
    assert provider._direction_to_rotation_degrees(1) == 270
    assert provider._direction_to_rotation_degrees(2) == 180
    assert provider._direction_to_rotation_degrees(3) == 90


def test_detect_reading_zones_splits_dual_column_layout():
    provider = _provider()
    lines = [
        OCRLine(text="一、填空题", left=40, top=40, width=120, height=24),
        OCRLine(text="1. 计算下面各题", left=48, top=90, width=200, height=24),
        OCRLine(text="2. 数列找规律", left=48, top=150, width=200, height=24),
        OCRLine(text="四、应用题", left=680, top=40, width=120, height=24),
        OCRLine(text="1. 工程问题", left=692, top=92, width=220, height=24),
        OCRLine(text="2. 行程问题", left=692, top=154, width=220, height=24),
    ]

    zones = provider._detect_reading_zones(lines)

    assert len(zones) == 2
    assert zones[0].left < zones[1].left


def test_detect_question_anchors_ignores_figure_caption():
    provider = _provider()
    lines = [
        OCRLine(text="第1题图", left=40, top=20, width=80, height=20),
        OCRLine(text="1. 计算下面各题", left=42, top=70, width=180, height=24),
        OCRLine(text="2. 观察图形", left=42, top=120, width=180, height=24),
    ]

    anchors = provider._detect_question_anchors(lines, zone_left=40)

    assert [anchor.question_no for anchor in anchors] == ["1", "2"]


def test_build_zone_sections_keeps_section_local_numbering():
    provider = _provider()
    zone = provider._detect_reading_zones(
        [
            OCRLine(text="一、填空题", left=40, top=30, width=120, height=24),
            OCRLine(text="1. 第一题", left=48, top=70, width=180, height=24),
            OCRLine(text="2. 第二题", left=48, top=110, width=180, height=24),
            OCRLine(text="二、选择题", left=40, top=180, width=120, height=24),
            OCRLine(text="1. 第三题", left=48, top=220, width=180, height=24),
            OCRLine(text="2. 第四题", left=48, top=260, width=180, height=24),
        ]
    )[0]

    sections = provider._build_zone_sections(zone)

    assert [section.section_index_raw for section in sections] == ["一", "二"]
    assert [provider._detect_question_anchors(section.lines, section.left)[0].question_no for section in sections] == ["1", "1"]


def test_recover_missing_question_anchors_supports_weak_gap_anchor():
    provider = _provider()
    section_lines = [
        OCRLine(text="1. 第一题", left=40, top=40, width=120, height=24),
        OCRLine(text="2把3.57:2.8化成最简单整数比", left=40, top=96, width=220, height=24),
        OCRLine(text="3. 第三题", left=40, top=152, width=120, height=24),
    ]
    anchors = provider._detect_question_anchors(section_lines, zone_left=40)

    recovered = provider._recover_missing_question_anchors(section_lines, anchors, zone_left=40)

    assert [anchor.question_no for anchor in recovered] == ["1", "2", "3"]
    assert recovered[1].recovery_reason == "weak_gap_anchor"


def test_consume_leading_section_metadata_reads_neighboring_note_line():
    provider = _provider()
    lines = [
        OCRLine(text="（本大题共5小题，共25分）", left=40, top=40, width=180, height=24),
        OCRLine(text="22. 一缸水，用去二分之一和5桶，还剩30%", left=40, top=92, width=280, height=24),
    ]

    remaining_lines, declared_count = provider._consume_leading_section_metadata(lines, None)

    assert declared_count == 5
    assert [line.text for line in remaining_lines] == ["22. 一缸水，用去二分之一和5桶，还剩30%"]


def test_choose_better_section_result_keeps_non_empty_primary_over_empty_secondary():
    provider = _provider()
    primary_lines = [OCRLine(text="22. 一缸水", left=40, top=40, width=120, height=24)]
    primary_anchors = [
        QuestionAnchor(
            line_index=0,
            question_no="22",
            question_label_raw="22.",
            line=primary_lines[0],
        )
    ]
    primary_audit = QuestionCountAudit(
        page_no=4,
        zone_key="z1",
        section_index_raw="五",
        detected_count=1,
        declared_count=5,
        anchor_numbers=["22"],
        secondary_pass_used=False,
        mismatch_reason="卷面声明 5 题，识别 1 题",
        layout_type="single_column",
    )
    secondary_audit = QuestionCountAudit(
        page_no=4,
        zone_key="z1",
        section_index_raw="五",
        detected_count=0,
        declared_count=5,
        anchor_numbers=[],
        secondary_pass_used=True,
        mismatch_reason="卷面声明 5 题，识别 0 题；section 存在正文但未识别到题号",
        layout_type="single_column",
    )

    chosen_lines, chosen_anchors, chosen_audit = provider._choose_better_section_result(
        primary_lines=primary_lines,
        primary_anchors=primary_anchors,
        primary_audit=primary_audit,
        secondary_result=(primary_lines, [], secondary_audit),
    )

    assert chosen_lines == primary_lines
    assert chosen_anchors == primary_anchors
    assert chosen_audit is primary_audit


def test_recover_sectionless_continuation_anchors_synthesizes_next_question():
    provider = _provider()
    section_lines = [
        OCRLine(text="某城市实行分段计费，收费标准如下：", left=48, top=40, width=280, height=24),
        OCRLine(text="用水量不超过10吨时，每吨水费为3.6元。", left=48, top=78, width=320, height=24),
        OCRLine(text="王大伯家上个月用水18吨，需缴水费多少元？", left=48, top=220, width=340, height=24),
    ]

    recovered = provider._recover_sectionless_continuation_anchors(
        section_lines,
        section_state={
            "entered": True,
            "declared_count": None,
            "last_question_no": 8,
            "detected_numbers": ["1", "3", "4", "5", "6", "7", "8"],
        },
    )

    assert [anchor.question_no for anchor in recovered] == ["9"]
    assert recovered[0].recovery_reason == "synthetic_continuation_anchor"


def test_recover_missing_question_anchors_can_synthesize_gap_question():
    provider = _provider()
    section_lines = [
        OCRLine(text="22. 一缸水，用去二分之一和5桶，还剩30%", left=40, top=40, width=280, height=24),
        OCRLine(text="一批水果分两次运完，第一次运了全部的40%", left=40, top=168, width=280, height=24),
        OCRLine(text="24. 一条围巾，如果卖100元，可赚25%", left=40, top=320, width=280, height=24),
    ]
    anchors = [
        QuestionAnchor(line_index=0, question_no="22", question_label_raw="22.", line=section_lines[0]),
        QuestionAnchor(line_index=2, question_no="24", question_label_raw="24.", line=section_lines[2]),
    ]

    recovered = provider._recover_missing_question_anchors(section_lines, anchors, zone_left=40)

    assert [anchor.question_no for anchor in recovered] == ["22", "23", "24"]
    assert recovered[1].recovery_reason == "synthetic_gap_anchor"


def test_select_best_anchor_sequence_prefers_continuous_low_start_sequence():
    provider = _provider()
    anchors = [
        QuestionAnchor(line_index=0, question_no="20", question_label_raw="20.", line=OCRLine(text="20.18-26÷5", left=320, top=575, width=256, height=46)),
        QuestionAnchor(line_index=1, question_no="2", question_label_raw="2.", line=OCRLine(text="2.", left=230, top=968, width=37, height=30)),
        QuestionAnchor(line_index=2, question_no="3", question_label_raw="3.", line=OCRLine(text="3. 应用题", left=210, top=1341, width=80, height=26)),
        QuestionAnchor(line_index=3, question_no="4", question_label_raw="4.", line=OCRLine(text="4. 工程题", left=229, top=1754, width=26, height=26)),
        QuestionAnchor(line_index=4, question_no="5", question_label_raw="5.", line=OCRLine(text="5. 数论题", left=233, top=2171, width=25, height=25)),
        QuestionAnchor(line_index=5, question_no="6", question_label_raw="6.", line=OCRLine(text="6. 组合题", left=222, top=2583, width=30, height=30)),
    ]

    selected = provider._select_best_anchor_sequence(anchors)

    assert [anchor.question_no for anchor in selected] == ["2", "3", "4", "5", "6"]


def test_recover_leading_calculation_anchors_uses_clusters_not_raw_line_count():
    provider = _provider()
    section_lines = [
        OCRLine(text="姓名：", left=31, top=65, width=189, height=81),
        OCRLine(text="建议时长：90min", left=625, top=73, width=569, height=65),
        OCRLine(text="分班考模拟卷3", left=1000, top=332, width=486, height=73),
        OCRLine(text="20.18-26÷5", left=320, top=575, width=256, height=46),
        OCRLine(text="1.4", left=414, top=637, width=62, height=43),
        OCRLine(text="题目二正文", left=251, top=961, width=320, height=48),
        OCRLine(text="2.", left=230, top=968, width=26, height=30),
    ]
    anchors = [
        QuestionAnchor(line_index=6, question_no="2", question_label_raw="2.", line=section_lines[6]),
    ]

    updated_lines, recovered_anchors = provider._recover_leading_calculation_anchors(
        section_lines,
        anchors,
        "",
    )

    assert [anchor.question_no for anchor in recovered_anchors] == ["1", "2"]
    assert updated_lines[3].text.startswith("1. ")
    assert recovered_anchors[1].line_index == 5
    assert recovered_anchors[1].force_use_label is True


def test_recover_pre_anchor_content_lines_shifts_following_anchor_start():
    provider = _provider()
    section_lines = [
        OCRLine(text="3. 第三题", left=210, top=1341, width=80, height=26),
        OCRLine(text="第三题后半句", left=318, top=1414, width=723, height=51),
        OCRLine(text="一项工程甲独做6小时完成", left=310, top=1732, width=480, height=62),
        OCRLine(text="余下的由甲独做还要", left=820, top=1740, width=360, height=44),
        OCRLine(text="4.", left=229, top=1754, width=26, height=26),
        OCRLine(text="完成", left=310, top=1802, width=111, height=58),
    ]
    anchors = [
        QuestionAnchor(line_index=0, question_no="3", question_label_raw="3.", line=section_lines[0]),
        QuestionAnchor(line_index=4, question_no="4", question_label_raw="4.", line=section_lines[4]),
    ]

    recovered = provider._recover_pre_anchor_content_lines(section_lines, anchors)

    assert recovered[1].line_index == 2
    assert recovered[1].force_use_label is True


def test_detect_reading_zones_falls_back_to_all_lines_for_mixed_layout():
    provider = _provider()
    lines = [
        OCRLine(text="左栏题干第一行", left=40, top=60, width=220, height=24),
        OCRLine(text="左栏题干第二行", left=48, top=118, width=220, height=24),
        OCRLine(text="四、解答题", left=700, top=40, width=120, height=24),
        OCRLine(text="23. 工程问题", left=712, top=92, width=220, height=24),
        OCRLine(text="24. 行程问题", left=712, top=154, width=220, height=24),
    ]

    zones = provider._detect_reading_zones(lines)

    assert len(zones) == 2
    assert zones[0].left < zones[1].left


def test_build_zone_sections_preserves_headingless_prefix_before_first_heading():
    provider = _provider()
    zone = provider._detect_reading_zones(
        [
            OCRLine(text="1. 第一题", left=40, top=40, width=180, height=24),
            OCRLine(text="2. 第二题", left=40, top=92, width=180, height=24),
            OCRLine(text="二、选择题", left=40, top=180, width=120, height=24),
            OCRLine(text="1. 第三题", left=40, top=232, width=180, height=24),
        ]
    )[0]

    sections = provider._build_zone_sections(zone)

    assert [section.section_index_raw for section in sections] == ["一", "二"]
    assert sections[0].is_headingless_prefix is True


def test_build_zone_sections_corrects_regressed_section_heading_across_pages():
    provider = _provider()
    zone = provider._detect_reading_zones(
        [
            OCRLine(text="一、应用题", left=40, top=40, width=120, height=24),
            OCRLine(text="1. 工程问题", left=40, top=92, width=180, height=24),
        ]
    )[0]

    sections = provider._build_zone_sections(zone, carried_section_index_raw="二")

    assert sections[0].section_index_raw == "三"


def test_extract_expected_question_numbers_uses_heading_range_and_figure_caption():
    provider = _provider()
    lines = [
        OCRLine(text="第24题图", left=700, top=420, width=100, height=24),
    ]

    expected_numbers = provider._extract_expected_question_numbers(
        "四、解答题（19-23小题每小题7分，24",
        lines,
    )

    assert expected_numbers == [19, 20, 21, 22, 23, 24]


def test_extract_expected_question_numbers_does_not_use_figure_caption_without_heading_range():
    provider = _provider()
    lines = [
        OCRLine(text="第5题图", left=700, top=420, width=100, height=24),
    ]

    expected_numbers = provider._extract_expected_question_numbers(
        "一、选择题(每小题3分,共30分)",
        lines,
    )

    assert expected_numbers == []


def test_detect_question_anchors_aligns_sparse_candidates_to_expected_numbers():
    provider = _provider()
    lines = [
        OCRLine(text="9. 统计图应用", left=40, top=40, width=220, height=24),
        OCRLine(text="22. 行程问题", left=40, top=240, width=220, height=24),
    ]

    anchors = provider._detect_question_anchors(
        lines,
        zone_left=40,
        expected_question_numbers=[19, 20, 21, 22, 23, 24],
    )

    assert [anchor.question_no for anchor in anchors] == ["19", "22"]


def test_recover_leading_calculation_anchors_can_use_generic_body_clusters():
    provider = _provider()
    section_lines = [
        OCRLine(text="姓名", left=30, top=40, width=80, height=24),
        OCRLine(text="满分100分", left=200, top=40, width=120, height=24),
        OCRLine(text="第一题题干", left=40, top=200, width=180, height=24),
        OCRLine(text="第二题题干", left=40, top=340, width=180, height=24),
        OCRLine(text="第三题题干", left=40, top=500, width=180, height=24),
        OCRLine(text="4. 第四题", left=40, top=680, width=180, height=24),
    ]
    anchors = [
        QuestionAnchor(
            line_index=5,
            question_no="4",
            question_label_raw="4.",
            line=section_lines[5],
        )
    ]

    updated_lines, recovered = provider._recover_leading_calculation_anchors(
        section_lines,
        anchors,
        "",
    )

    assert [anchor.question_no for anchor in recovered] == ["1", "2", "3", "4"]
    assert updated_lines[2].text.startswith("1. ")
    assert updated_lines[3].text.startswith("2. ")
    assert updated_lines[4].text.startswith("3. ")


def test_build_report_warnings_ignores_page_local_mismatch_when_section_closes():
    provider = _provider()
    audits = [
        QuestionCountAudit(
            page_no=1,
            zone_key="zone-1",
            section_index_raw="二",
            detected_count=2,
            declared_count=4,
            anchor_numbers=["1", "2"],
            secondary_pass_used=False,
            mismatch_reason="卷面声明 4 题，识别 2 题；同一 section 的跨页续接被跳过",
            layout_type="dual_column",
        ),
        QuestionCountAudit(
            page_no=2,
            zone_key="zone-1",
            section_index_raw="二",
            detected_count=2,
            declared_count=4,
            anchor_numbers=["3", "4"],
            secondary_pass_used=False,
            mismatch_reason="卷面声明 4 题，识别 2 题",
            layout_type="dual_column",
        ),
    ]

    warnings = provider._build_report_warnings(audits)

    assert warnings == []


def test_build_report_warnings_skips_headingless_empty_zone_when_same_page_has_real_anchors():
    provider = _provider()
    audits = [
        QuestionCountAudit(
            page_no=1,
            zone_key="zone-1",
            section_index_raw="",
            detected_count=0,
            declared_count=None,
            anchor_numbers=[],
            secondary_pass_used=False,
            mismatch_reason="section 存在正文但未识别到题号",
            layout_type="dual_column",
        ),
        QuestionCountAudit(
            page_no=1,
            zone_key="zone-2",
            section_index_raw="",
            detected_count=3,
            declared_count=None,
            anchor_numbers=["1", "2", "3"],
            secondary_pass_used=False,
            mismatch_reason="",
            layout_type="dual_column",
        ),
    ]

    warnings = provider._build_report_warnings(audits)

    assert warnings == []


def test_should_keep_sectionless_continuation_when_previous_page_entered_section_without_anchors():
    provider = _provider()
    anchors = [
        QuestionAnchor(
            line_index=0,
            question_no="25",
            question_label_raw="25.",
            line=OCRLine(text="25. 第一题", left=700, top=80, width=180, height=24),
        ),
        QuestionAnchor(
            line_index=1,
            question_no="26",
            question_label_raw="26.",
            line=OCRLine(text="26. 第二题", left=700, top=180, width=180, height=24),
        ),
    ]

    keep_section = provider._should_keep_sectionless_continuation(
        "五",
        anchors,
        page_questions=[],
        existing_questions=[],
        section_state={
            "entered": True,
            "declared_count": 5,
            "last_question_no": None,
            "detected_numbers": [],
        },
    )

    assert keep_section is True


def test_extract_declared_question_count_can_use_score_ratio():
    provider = _provider()

    declared_count = provider._extract_declared_question_count("二、填空题(每小题3分,共18分)")

    assert declared_count == 6


def test_extract_expected_question_numbers_supports_truncated_heading_range():
    provider = _provider()

    expected_numbers = provider._extract_expected_question_numbers(
        "四、解答题（19~23",
        [OCRLine(text="第24题图", left=40, top=40, width=100, height=24)],
    )

    assert expected_numbers == [19, 20, 21, 22, 23, 24]


def test_recover_missing_question_anchors_can_use_declared_count_for_local_numbering_tail():
    provider = _provider()
    section_lines = [
        OCRLine(text="1. 第一题", left=40, top=40, width=180, height=24),
        OCRLine(text="2. 第二题", left=40, top=120, width=180, height=24),
        OCRLine(text="第三题题干", left=40, top=260, width=180, height=24),
        OCRLine(text="第四题题干", left=40, top=400, width=180, height=24),
    ]
    anchors = [
        QuestionAnchor(line_index=0, question_no="1", question_label_raw="1.", line=section_lines[0]),
        QuestionAnchor(line_index=1, question_no="2", question_label_raw="2.", line=section_lines[1]),
    ]

    recovered = provider._recover_missing_question_anchors(
        section_lines,
        anchors,
        zone_left=40,
        declared_count=4,
    )

    assert [anchor.question_no for anchor in recovered] == ["1", "2", "3", "4"]


def test_trim_overlapping_continuation_anchors_removes_duplicate_prefix():
    provider = _provider()
    anchors = [
        QuestionAnchor(
            line_index=0,
            question_no="11",
            question_label_raw="11.",
            line=OCRLine(text="11. 题目", left=40, top=40, width=180, height=24),
        ),
        QuestionAnchor(
            line_index=1,
            question_no="12",
            question_label_raw="12.",
            line=OCRLine(text="12. 题目", left=40, top=120, width=180, height=24),
        ),
        QuestionAnchor(
            line_index=2,
            question_no="13",
            question_label_raw="13.",
            line=OCRLine(text="13. 题目", left=40, top=200, width=180, height=24),
        ),
    ]

    trimmed = provider._trim_overlapping_continuation_anchors(
        anchors,
        section_state={
            "entered": True,
            "declared_count": 30,
            "last_question_no": 12,
            "detected_numbers": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"],
        },
    )

    assert [anchor.question_no for anchor in trimmed] == ["13"]
