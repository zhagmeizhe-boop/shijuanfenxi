from scripts.extract_gaosi_question_reference import (
    QuestionDraft,
    _clean_question_text,
    _parse_question_start,
    _resolve_lecture_title,
    _to_reference_entry,
    build_topic_progression_summary,
)


def test_gaosi_question_extractor_uses_directory_title_fallback():
    lookup = {(3, "1"): {"title": "四则运算一", "category": "计算问题"}}

    title = _resolve_lecture_title(3, "1", "）", lookup)

    assert title == "四则运算一"


def test_gaosi_question_extractor_parses_star_after_question_number():
    question_no, star_level, rest = _parse_question_start("1 ★计算：28+72")

    assert question_no == "1"
    assert star_level == "★"
    assert rest == "计算：28+72"


def test_gaosi_question_extractor_strips_book_footer_from_question_text():
    text = _clean_question_text("计算：321-199。 高思学校竞赛数学导引·三年级")

    assert text == "计算：321-199。"


def test_gaosi_question_entry_contains_structure_profile_and_dim4_skeleton():
    draft = QuestionDraft(
        book_name="竞赛数学导引 三年级",
        grade=3,
        lecture_no="1",
        lecture_title="）",
        section_label="拓展篇",
        page_no=18,
        question_no="2",
        star_level="★★",
        source_pdf="gaosi.pdf",
    )
    draft.add_line("计算：51+49+62+38。", 0.95, 18)

    entry = _to_reference_entry(
        draft,
        lecture_lookup={(3, "1"): {"title": "四则运算一", "category": "计算问题"}},
    )

    assert entry is not None
    assert entry.lecture_title == "四则运算一"
    assert entry.category == "计算问题"
    structure = entry.dimension_profiles["structure"]
    assert structure["topic_domain"] == "calculation"
    assert structure["section_level"] == "extension"
    assert entry.dimension_profiles["dim4"]["profile_source"] == "local_structure_skeleton"
    assert entry.dimension_profiles["dim4"]["auto_calibration_allowed"] is False


def test_gaosi_topic_progression_summary_keeps_three_sections():
    entries = []
    for section_label in ("兴趣篇", "拓展篇", "超越篇"):
        draft = QuestionDraft(
            book_name="竞赛数学导引 五年级",
            grade=5,
            lecture_no="8",
            lecture_title="牛吃草问题",
            section_label=section_label,
            page_no=80,
            question_no="1",
            star_level="★",
            source_pdf="gaosi.pdf",
        )
        draft.add_line("牧场有草每天匀速生长，若干头牛若干天吃完。", 0.92, 80)
        entry = _to_reference_entry(draft)
        assert entry is not None
        entries.append(entry)

    summary = build_topic_progression_summary(entries)

    assert len(summary) == 1
    assert summary[0]["section_count"] == 3
    assert summary[0]["missing_sections"] == []
    assert [section["section_label"] for section in summary[0]["sections"]] == [
        "兴趣篇",
        "拓展篇",
        "超越篇",
    ]
