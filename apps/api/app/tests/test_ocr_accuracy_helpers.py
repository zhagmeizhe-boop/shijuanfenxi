from app.services.ocr.baidu_provider import BaiduOCRProvider, OCRLine
from app.services.ocr.base import QuestionType, SubItemCandidate


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
