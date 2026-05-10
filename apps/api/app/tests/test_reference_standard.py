import json
from pathlib import Path

from app.services.parser.reference_standard import (
    BAND_LABELS,
    DATA_FILE_NAME,
    GAOSI_QUESTION_DATA_FILE_NAME,
    GAOSI_QUESTION_SOURCE,
    GAOSI_PDF_DATA_FILE_NAME,
    ReferenceEntry,
    SCHOOL_PDF_DATA_FILE_NAME,
    WorkbookReferenceStandard,
    get_reference_standard,
)


def _build_standard(entries: list[ReferenceEntry]) -> WorkbookReferenceStandard:
    standard = WorkbookReferenceStandard.__new__(WorkbookReferenceStandard)
    standard.data_path = Path(DATA_FILE_NAME)
    standard.workbook_path = None
    standard.entries = entries
    return standard


def _dim4_profile(level: str = "L4", confidence: float = 0.9, auto_allowed: bool = True) -> dict:
    return {
        "strategy_role": "core",
        "template_fit": "non_routine",
        "breakthrough_type": "constructive",
        "strategy_shift_count": "2",
        "construction_requirement": "custom_construction",
        "exploration_space": "branched",
        "representation_reframe": "structural",
        "transfer_distance": "far",
        "path_openness": "multiple_paths",
        "dead_end_risk": "medium",
        "global_strategy_required": 1,
        "image_dependency": "none",
        "reference_level": level,
        "profile_confidence": confidence,
        "auto_calibration_allowed": auto_allowed,
        "evidence_summary": "参考题需要策略换路与构造。",
        "profile_warning": "",
    }


def _gaosi_dim4_entry(
    question_text: str,
    *,
    level: str = "L4",
    ocr_confidence: float = 0.92,
    has_diagram: bool = False,
) -> ReferenceEntry:
    return ReferenceEntry(
        source=GAOSI_QUESTION_SOURCE,
        sheet_name="高思导引PDF题目",
        category="应用题",
        title="策略构造题",
        track="拓展篇",
        grade_hint="六年级",
        keywords=("策略构造题", "拓展篇"),
        grade="6",
        book_name="竞赛数学导引 六年级",
        lecture_no="12",
        lecture_title="策略构造题",
        section_level="extension",
        section_label="拓展篇",
        page_no="120",
        question_no="5",
        question_text=question_text,
        has_diagram=has_diagram,
        ocr_confidence=ocr_confidence,
        source_pdf="gaosi.pdf",
        dimension_profiles={"dim4": _dim4_profile(level=level)},
    )


def _dim4_l3_feature() -> dict:
    return {
        "strategy_role": "core",
        "template_fit": "reframed",
        "breakthrough_type": "strategy_shift",
        "strategy_shift_count": "1",
        "construction_requirement": "none",
        "exploration_space": "bounded",
        "representation_reframe": "structural",
        "transfer_distance": "medium",
        "path_openness": "single",
        "dead_end_risk": "medium",
        "global_strategy_required": 0,
        "image_dependency": "none",
        "evidence_summary": "需要一次换路并重组策略。",
        "applicability_confidence": 0.91,
    }


def _dim4_l2_feature() -> dict:
    return {
        "strategy_role": "core",
        "template_fit": "adapted",
        "breakthrough_type": "none",
        "strategy_shift_count": "0",
        "construction_requirement": "simple_setup",
        "exploration_space": "bounded",
        "representation_reframe": "minor",
        "transfer_distance": "near",
        "path_openness": "single",
        "dead_end_risk": "medium",
        "global_strategy_required": 0,
        "image_dependency": "none",
        "evidence_summary": "需要轻度变式和简单设置。",
        "applicability_confidence": 0.9,
    }


def _dim4_l4_feature() -> dict:
    return {
        "strategy_role": "core",
        "template_fit": "non_routine",
        "breakthrough_type": "constructive",
        "strategy_shift_count": "2",
        "construction_requirement": "custom_construction",
        "exploration_space": "branched",
        "representation_reframe": "structural",
        "transfer_distance": "far",
        "path_openness": "multiple_paths",
        "dead_end_risk": "medium",
        "global_strategy_required": 1,
        "image_dependency": "none",
        "evidence_summary": "需要构造对象并探索多条路径。",
        "applicability_confidence": 0.9,
    }


def _dim4_direct_not_applicable_feature() -> dict:
    return {
        "strategy_role": "core",
        "template_fit": "direct",
        "breakthrough_type": "none",
        "strategy_shift_count": "0",
        "construction_requirement": "none",
        "exploration_space": "none",
        "representation_reframe": "none",
        "transfer_distance": "near",
        "path_openness": "single",
        "dead_end_risk": "low",
        "global_strategy_required": 0,
        "image_dependency": "none",
        "evidence_summary": "直接套用常规模板。",
        "applicability_confidence": 0.9,
    }


def test_reference_standard_prefers_json_resource():
    standard = get_reference_standard()

    assert standard.data_path.name == DATA_FILE_NAME
    assert standard.data_path.exists()
    assert len(standard.entries) > 1000


def test_reference_standard_json_resource_does_not_require_workbook(tmp_path, monkeypatch):
    data_path = tmp_path / DATA_FILE_NAME
    data_path.write_text(
        json.dumps(
            [
                ReferenceEntry(
                    source="school",
                    sheet_name="test",
                    category="计算",
                    title="整数四则应用",
                    track="校内",
                    grade_hint="四年级",
                    keywords=("整数四则应用",),
                ).to_dict()
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def _unexpected_lookup():
        raise AssertionError("JSON resource should bypass workbook lookup")

    monkeypatch.setattr(
        WorkbookReferenceStandard,
        "_find_reference_workbook",
        staticmethod(_unexpected_lookup),
    )

    standard = WorkbookReferenceStandard(data_path=data_path)

    assert len(standard.entries) == 1
    assert standard.entries[0].title == "整数四则应用"
    assert standard.workbook_path is None


def test_reference_standard_merges_extra_json_files_and_dedupes(tmp_path, monkeypatch):
    data_path = tmp_path / DATA_FILE_NAME
    gaosi_path = tmp_path / GAOSI_PDF_DATA_FILE_NAME
    gaosi_question_path = tmp_path / GAOSI_QUESTION_DATA_FILE_NAME
    school_path = tmp_path / SCHOOL_PDF_DATA_FILE_NAME
    duplicate = ReferenceEntry(
        source="gaosi_pdf",
        sheet_name="高思导引PDF目录",
        category="应用题",
        title="牛吃草问题",
        track="高思导引",
        grade_hint="五年级",
        keywords=("牛吃草问题",),
    )
    data_path.write_text(
        json.dumps([duplicate.to_dict()], ensure_ascii=False),
        encoding="utf-8",
    )
    gaosi_path.write_text(
        json.dumps(
            [
                duplicate.to_dict(),
                ReferenceEntry(
                    source="gaosi_pdf",
                    sheet_name="高思导引PDF目录",
                    category="几何问题",
                    title="立体几何",
                    track="高思导引",
                    grade_hint="六年级",
                    keywords=("立体几何",),
                ).to_dict(),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    school_path.write_text(
        json.dumps(
            [
                ReferenceEntry(
                    source="school_pdf",
                    sheet_name="人教版PDF目录",
                    category="人教版五年级数学上册",
                    title="小数乘法",
                    track="校内",
                    grade_hint="5年级上册",
                    keywords=("小数乘法", "5年级上册", "校内"),
                ).to_dict(),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    gaosi_question_path.write_text(
        json.dumps(
            [
                ReferenceEntry(
                    source=GAOSI_QUESTION_SOURCE,
                    sheet_name="高思导引PDF题目",
                    category="应用题",
                    title="牛吃草问题",
                    track="拓展篇",
                    grade_hint="五年级",
                    keywords=("牛吃草问题", "拓展篇"),
                    grade="5",
                    lecture_no="8",
                    lecture_title="牛吃草问题",
                    section_level="extension",
                    section_label="拓展篇",
                    page_no="88",
                    question_no="3",
                    question_text="牧场上有一片草地，每天都匀速生长，若8头牛12天吃完，10头牛8天吃完，问几头牛6天吃完？",
                    ocr_confidence=0.91,
                    source_pdf="gaosi.pdf",
                ).to_dict(),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def _unexpected_lookup():
        raise AssertionError("JSON resources should bypass workbook lookup")

    monkeypatch.setattr(
        WorkbookReferenceStandard,
        "_find_reference_workbook",
        staticmethod(_unexpected_lookup),
    )

    standard = WorkbookReferenceStandard(
        data_path=data_path,
        extra_data_paths=[gaosi_path, gaosi_question_path, school_path],
    )

    assert len(standard.entries) == 4
    assert [entry.title for entry in standard.entries] == ["牛吃草问题", "立体几何", "牛吃草问题", "小数乘法"]


def test_reference_standard_calibrates_dim5_feature():
    standard = get_reference_standard()
    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[1],
            "sublevel": "mid",
            "evidence_summary": "只涉及长方形面积。",
            "knowledge_tags": ["长方形面积"],
            "method_tags": ["面积公式"],
        },
        question_text="一个长方形长 12 厘米，宽 8 厘米，求它的面积。",
        question_summary="长方形面积基础题",
        analysis_facts={
            "core_task": "利用长方形面积公式求面积",
            "core_knowledge_points": ["长方形面积"],
            "core_methods": ["公式代入"],
            "visual_elements": ["长方形"],
        },
    )

    assert feature["band"] == BAND_LABELS[1]


def test_gaosi_pdf_grade_3_4_maps_to_low_grade_guide_band():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="gaosi_pdf",
                sheet_name="高思导引PDF目录",
                category="计算问题",
                title="找规律填数",
                track="高思导引",
                grade_hint="三年级",
                keywords=("找规律填数", "三年级", "高思导引"),
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[1],
            "sublevel": "mid",
            "evidence_summary": "模型主判偏向校内。",
            "core_knowledge_units": ["找规律填数"],
            "knowledge_tags": ["找规律填数"],
        },
        question_text="按规律填数，这是找规律填数问题。",
        question_summary="找规律填数",
        analysis_facts={"core_knowledge_points": ["找规律填数"]},
    )

    assert feature["band"] == BAND_LABELS[1]
    assert feature["calibration"]["band_source"] == "audit_only"


def test_gaosi_pdf_grade_5_6_maps_to_high_grade_guide_band():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="gaosi_pdf",
                sheet_name="高思导引PDF目录",
                category="应用题",
                title="牛吃草问题",
                track="高思导引",
                grade_hint="五年级",
                keywords=("牛吃草问题", "五年级", "高思导引"),
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[2],
            "sublevel": "mid",
            "evidence_summary": "模型主判偏向校内高年级。",
            "core_knowledge_units": ["牛吃草问题"],
            "knowledge_tags": ["牛吃草问题"],
        },
        question_text="典型牛吃草问题，涉及消耗增长模型。",
        question_summary="牛吃草问题",
        analysis_facts={"core_knowledge_points": ["牛吃草问题"]},
    )

    assert feature["band"] == BAND_LABELS[2]
    assert feature["calibration"]["band_source"] == "audit_only"


def test_school_pdf_grade_1_4_maps_to_lower_school_band():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="school_pdf",
                sheet_name="人教版PDF目录",
                category="人教版四年级数学上册",
                title="平行四边形和梯形",
                track="校内",
                grade_hint="4年级上册",
                keywords=("平行四边形和梯形", "四年级", "校内"),
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[2],
            "sublevel": "mid",
            "evidence_summary": "模型主判偏向高年级校内。",
            "core_knowledge_units": ["平行四边形和梯形"],
            "knowledge_tags": ["平行四边形和梯形"],
        },
        question_text="这是一道平行四边形和梯形的基础性质题。",
        question_summary="平行四边形和梯形",
        analysis_facts={"core_knowledge_points": ["平行四边形和梯形"]},
    )

    assert feature["band"] == BAND_LABELS[1]


def test_school_pdf_grade_5_6_maps_to_upper_school_band():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="school_pdf",
                sheet_name="人教版PDF目录",
                category="人教版六年级数学下册",
                title="圆柱与圆锥",
                track="校内",
                grade_hint="6年级下册",
                keywords=("圆柱与圆锥", "六年级", "校内"),
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[1],
            "sublevel": "mid",
            "evidence_summary": "模型主判偏向低年级校内。",
            "core_knowledge_units": ["圆柱与圆锥"],
            "knowledge_tags": ["圆柱与圆锥"],
        },
        question_text="求圆柱与圆锥体积关系。",
        question_summary="圆柱与圆锥",
        analysis_facts={"core_knowledge_points": ["圆柱与圆锥"]},
    )

    assert feature["band"] == BAND_LABELS[2]


def test_dim5_short_generic_school_title_does_not_override_model_band():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="school_pdf",
                sheet_name="人教版PDF目录",
                category="人教版一年级数学上册",
                title="位置",
                track="校内",
                grade_hint="1年级上册",
                keywords=("位置", "一年级", "校内"),
            ),
            ReferenceEntry(
                source="school_pdf",
                sheet_name="人教版PDF目录",
                category="人教版五年级数学上册",
                title="位置",
                track="校内",
                grade_hint="5年级上册",
                keywords=("位置", "五年级", "校内"),
            ),
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[2],
            "sublevel": "mid",
            "evidence_summary": "只给出位置这个泛化标题。",
            "core_knowledge_units": ["位置"],
            "knowledge_tags": ["位置"],
        },
        question_text="根据位置关系回答问题。",
        question_summary="位置",
        analysis_facts={"core_knowledge_points": ["位置"]},
    )

    assert feature["band"] == BAND_LABELS[2]
    assert feature["calibration"]["band_source"] in {"audit_only", "model_only"}


def test_dim5_ambiguous_school_title_does_not_override_model_band():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="school_pdf",
                sheet_name="人教版PDF目录",
                category="人教版二年级数学上册",
                title="数学广角",
                track="校内",
                grade_hint="2年级上册",
                keywords=("数学广角", "二年级", "校内"),
            ),
            ReferenceEntry(
                source="school_pdf",
                sheet_name="人教版PDF目录",
                category="人教版五年级数学下册",
                title="数学广角",
                track="校内",
                grade_hint="5年级下册",
                keywords=("数学广角", "五年级", "校内"),
            ),
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[2],
            "sublevel": "mid",
            "evidence_summary": "只给出数学广角泛化标题，没有具体子主题。",
            "core_knowledge_units": ["数学广角"],
            "knowledge_tags": ["数学广角"],
        },
        question_text="一道数学广角题。",
        question_summary="数学广角",
        analysis_facts={"core_knowledge_points": ["数学广角"]},
    )

    assert feature["band"] == BAND_LABELS[2]
    assert feature["calibration"]["band_source"] in {"audit_only", "model_only"}


def test_gaosi_pdf_overtaking_signal_maps_to_top_band():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="gaosi_pdf",
                sheet_name="高思导引PDF目录",
                category="计数问题",
                title="压轴计数",
                track="超越篇",
                grade_hint="六年级",
                keywords=("压轴计数", "超越篇", "六年级"),
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[4],
            "sublevel": "mid",
            "evidence_summary": "模型主判为高年级拓展。",
            "core_knowledge_units": ["压轴计数"],
            "knowledge_tags": ["压轴计数"],
        },
        question_text="压轴计数题，需要使用超越篇计数方法。",
        question_summary="压轴计数",
        analysis_facts={"core_knowledge_points": ["压轴计数"]},
    )

    assert feature["band"] == BAND_LABELS[4]
    assert feature["calibration"]["band_source"] == "audit_only"


def test_gaosi_question_interest_entry_calibrates_to_low_sublevel():
    question_text = "甲乙两人同时从相距1200米的两地相向而行，甲每分钟走70米，乙每分钟走50米，几分钟后相遇？"
    standard = _build_standard(
        [
            ReferenceEntry(
                source=GAOSI_QUESTION_SOURCE,
                sheet_name="高思导引PDF题目",
                category="行程问题",
                title="行程问题",
                track="兴趣篇",
                grade_hint="五年级",
                keywords=("行程问题", "兴趣篇"),
                section_level="interest",
                section_label="兴趣篇",
                question_text=question_text,
                ocr_confidence=0.92,
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[2],
            "sublevel": "mid",
            "evidence_summary": "模型主判偏低。",
        },
        question_text=question_text,
        question_summary="相遇问题",
        analysis_facts={"core_task": "行程相遇"},
    )

    calibration = feature["calibration"]

    assert feature["band"] == BAND_LABELS[4]
    assert feature["sublevel"] == "low"
    assert calibration["can_override_model"] is True
    assert calibration["question_level_match"] is True


def test_gaosi_question_extension_entry_calibrates_to_mid_sublevel():
    question_text = "牧场上有一片草地，每天都匀速生长，若8头牛12天吃完，10头牛8天吃完，问几头牛6天吃完？"
    standard = _build_standard(
        [
            ReferenceEntry(
                source=GAOSI_QUESTION_SOURCE,
                sheet_name="高思导引PDF题目",
                category="应用题",
                title="牛吃草问题",
                track="拓展篇",
                grade_hint="五年级",
                keywords=("牛吃草问题", "拓展篇"),
                section_level="extension",
                section_label="拓展篇",
                question_text=question_text,
                ocr_confidence=0.93,
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[2],
            "sublevel": "low",
            "evidence_summary": "模型主判偏低。",
        },
        question_text=question_text,
        question_summary="牛吃草问题",
        analysis_facts={"core_task": "牛吃草模型"},
    )

    calibration = feature["calibration"]

    assert feature["band"] == BAND_LABELS[4]
    assert feature["sublevel"] == "mid"
    assert calibration["can_override_model"] is True
    assert calibration["band_source"] == "question_bank"
    assert feature["band_source"] == "question_bank"
    assert "need_manual_review" not in feature


def test_gaosi_question_high_similarity_with_specific_anchor_can_calibrate_dim5():
    reference_text = "牧场上有一片草地，每天都匀速生长，若8头牛12天吃完，10头牛8天吃完，问几头牛6天吃完？"
    question_text = "牧场有一片草地，每天都匀速生长，若8头牛12天吃完，10头牛8天吃完，问多少头牛6天吃完？"
    standard = _build_standard(
        [
            ReferenceEntry(
                source=GAOSI_QUESTION_SOURCE,
                sheet_name="高思导引PDF题目",
                category="应用题",
                title="牛吃草问题",
                track="拓展篇",
                grade_hint="五年级",
                keywords=("牛吃草问题", "草地匀速生长", "拓展篇"),
                section_level="extension",
                section_label="拓展篇",
                question_text=reference_text,
                ocr_confidence=0.93,
                dimension_profiles={
                    "dim5": {
                        "knowledge_anchor_terms": ["牛吃草问题", "草地匀速生长"],
                        "dim5_reference_band": BAND_LABELS[4],
                        "dim5_reference_sublevel": "mid",
                        "match_safety_level": "auto",
                    }
                },
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[2],
            "sublevel": "low",
            "evidence_summary": "模型主判偏低。",
            "knowledge_tags": ["牛吃草问题"],
            "core_knowledge_units": ["牛吃草问题"],
        },
        question_text=question_text,
        question_summary="牛吃草问题",
        analysis_facts={"core_task": "牛吃草模型", "core_knowledge_points": ["牛吃草问题"]},
    )

    calibration = feature["calibration"]

    assert feature["band"] == BAND_LABELS[4]
    assert feature["sublevel"] == "mid"
    assert calibration["question_level_match"] is True
    assert calibration["question_level_match_type"] == "high_similarity"
    assert calibration["band_source"] == "question_bank"


def test_gaosi_question_extension_star_does_not_raise_sublevel_to_high():
    question_text = "牧场上有一片草地，每天都匀速生长，若8头牛12天吃完，10头牛8天吃完，问几头牛6天吃完？"
    standard = _build_standard(
        [
            ReferenceEntry(
                source=GAOSI_QUESTION_SOURCE,
                sheet_name="高思导引PDF题目",
                category="应用题",
                title="牛吃草问题",
                track="拓展篇",
                grade_hint="五年级",
                keywords=("牛吃草问题", "拓展篇"),
                section_level="extension",
                section_label="拓展篇",
                question_text=question_text,
                star_level="★★",
                ocr_confidence=0.93,
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[2],
            "sublevel": "low",
            "evidence_summary": "模型主判偏低。",
        },
        question_text=question_text,
        question_summary="牛吃草问题",
        analysis_facts={"core_task": "牛吃草模型"},
    )

    assert feature["sublevel"] == "mid"
    assert feature["reference_sublevel_source"] == "gaosi_question_level"


def test_gaosi_question_challenge_entry_calibrates_to_beyond_band():
    question_text = "有一列按规则变化的数列，第1项为2，以后每项都由前两项和一个周期参数共同决定，求第2026项除以7的余数。"
    standard = _build_standard(
        [
            ReferenceEntry(
                source=GAOSI_QUESTION_SOURCE,
                sheet_name="高思导引PDF题目",
                category="数列问题",
                title="周期数列",
                track="超越篇",
                grade_hint="六年级",
                keywords=("周期数列", "超越篇"),
                section_level="challenge",
                section_label="超越篇",
                question_text=question_text,
                ocr_confidence=0.90,
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[4],
            "sublevel": "mid",
            "evidence_summary": "模型主判为高年级拓展。",
            "knowledge_tags": ["周期数列"],
            "core_knowledge_units": ["周期数列"],
        },
        question_text=question_text,
        question_summary="周期数列",
        analysis_facts={"core_knowledge_points": ["周期数列"]},
    )

    assert feature["band"] == BAND_LABELS[5]
    assert feature["sublevel"] == "high"
    assert feature["gaosi_grade"] == "6"
    assert feature["gaosi_section_level"] == "challenge"
    assert feature["gaosi_section_label"] == "超越篇"
    assert feature["gaosi_classification_source"] == "question_bank"
    assert feature["calibration"]["question_level_match"] is True


def test_dim5_diagram_partial_gaosi_question_match_is_review_only():
    reference_text = (
        "如图，在长方形ABCD中连接对角线AC，并在边上取点E、F，"
        "根据图中面积关系求阴影部分面积。"
    )
    question_text = "在长方形ABCD中连接对角线AC，并在边上取点E，求阴影部分面积。"
    standard = _build_standard(
        [
            ReferenceEntry(
                source=GAOSI_QUESTION_SOURCE,
                sheet_name="高思导引PDF题目",
                category="几何问题",
                title="面积关系",
                track="超越篇",
                grade_hint="六年级",
                keywords=("面积关系", "超越篇"),
                grade="6",
                section_level="challenge",
                section_label="超越篇",
                question_text=reference_text,
                has_diagram=True,
                ocr_confidence=0.94,
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[4],
            "sublevel": "mid",
            "knowledge_tags": ["面积关系"],
            "core_knowledge_units": ["面积关系"],
        },
        question_text=question_text,
        question_summary="面积关系",
        analysis_facts={"core_task": "根据面积关系求阴影面积"},
    )

    assert feature["band"] == BAND_LABELS[4]
    assert feature["calibration"]["question_level_match"] is True
    assert feature["calibration"]["can_override_model"] is False
    assert feature["need_manual_review"] is True
    assert "diagram_partial_match" in feature["calibration"]["question_level_match_quality"]


def test_dim5_conflicting_high_similarity_question_matches_keep_model_band():
    reference_text = (
        "一列数按照前两项和周期参数共同决定，求第2026项除以7的余数。"
    )
    question_text = "一列数按照前两项和周期参数决定，求第2026项除以7的余数。"
    standard = _build_standard(
        [
            ReferenceEntry(
                source=GAOSI_QUESTION_SOURCE,
                sheet_name="高思导引PDF题目",
                category="数列问题",
                title="周期数列",
                track="兴趣篇",
                grade_hint="六年级",
                keywords=("周期数列", "兴趣篇"),
                grade="6",
                section_level="interest",
                section_label="兴趣篇",
                question_text=reference_text,
                ocr_confidence=0.94,
            ),
            ReferenceEntry(
                source=GAOSI_QUESTION_SOURCE,
                sheet_name="高思导引PDF题目",
                category="数列问题",
                title="周期数列",
                track="超越篇",
                grade_hint="六年级",
                keywords=("周期数列", "超越篇"),
                grade="6",
                section_level="challenge",
                section_label="超越篇",
                question_text=reference_text,
                ocr_confidence=0.94,
            ),
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[4],
            "sublevel": "mid",
            "knowledge_tags": ["周期数列"],
            "core_knowledge_units": ["周期数列"],
        },
        question_text=question_text,
        question_summary="周期数列",
        analysis_facts={"core_task": "周期数列求余数"},
    )

    assert feature["band"] == BAND_LABELS[4]
    assert feature["calibration"]["can_override_model"] is False
    assert feature["calibration"]["band_source"] == "audit_only"
    assert "候选存在篇章/档位冲突" in feature["warning"]


def test_gaosi_question_candidates_include_dim5_safety_profile():
    question_text = "甲乙两人同时从相距200米的两地相向而行，几分钟后相遇？"
    standard = _build_standard(
        [
            ReferenceEntry(
                source=GAOSI_QUESTION_SOURCE,
                sheet_name="高思导引PDF题目",
                category="行程问题",
                title="相遇问题",
                track="兴趣篇",
                grade_hint="五年级",
                keywords=("相遇问题", "兴趣篇"),
                grade="5",
                section_level="interest",
                section_label="兴趣篇",
                question_text=question_text,
                ocr_confidence=0.94,
                dimension_profiles={
                    "dim5": {
                        "knowledge_anchor_terms": ["相遇问题"],
                        "dim5_reference_band": BAND_LABELS[4],
                        "dim5_reference_sublevel": "low",
                        "match_safety_level": "auto",
                    }
                },
            )
        ]
    )

    candidates = standard.gaosi_question_candidates(
        {"knowledge_tags": ["相遇问题"]},
        question_text=question_text,
        question_summary="相遇问题",
        analysis_facts={"core_task": "行程相遇"},
    )

    assert candidates[0]["dim5_reference_band"] == BAND_LABELS[4]
    assert candidates[0]["dim5_reference_sublevel"] == "low"
    assert candidates[0]["dim5_match_safety_level"] == "auto"
    assert candidates[0]["knowledge_anchor_terms"] == ["相遇问题"]


def test_classic_olympiad_reference_maps_to_gaosi_band_not_beyond():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="classic",
                sheet_name="经典奥数",
                category="计数问题",
                title="组合计数",
                track="经典奥数",
                grade_hint="五年级",
                keywords=("组合计数", "经典奥数"),
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[2],
            "sublevel": "mid",
            "evidence_summary": "模型主判为校内高年级。",
            "knowledge_tags": ["组合计数"],
            "core_knowledge_units": ["组合计数"],
        },
        question_text="本题考查组合计数，需要按对象分类后计数。",
        question_summary="组合计数",
        analysis_facts={"core_knowledge_points": ["组合计数"]},
    )

    assert feature["band"] == BAND_LABELS[4]
    assert feature["band"] != BAND_LABELS[5]
    assert feature["gaosi_grade"] == "5"
    assert feature["gaosi_classification_source"] == "knowledge_base"


def test_competition_reference_maps_to_gaosi_band_not_beyond():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="competition",
                sheet_name="竞赛备考章节序",
                category="应用题",
                title="牛吃草问题",
                track="竞赛备考",
                grade_hint="六年级",
                keywords=("牛吃草问题", "竞赛备考"),
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[2],
            "sublevel": "mid",
            "evidence_summary": "模型主判为校内高年级。",
            "knowledge_tags": ["牛吃草问题"],
            "core_knowledge_units": ["牛吃草问题"],
        },
        question_text="典型牛吃草问题，草每天匀速生长，比较牛数与天数。",
        question_summary="牛吃草问题",
        analysis_facts={"core_knowledge_points": ["牛吃草问题"]},
    )

    assert feature["band"] == BAND_LABELS[4]
    assert feature["band"] != BAND_LABELS[5]
    assert feature["gaosi_grade"] == "6"
    assert feature["gaosi_classification_source"] == "knowledge_base"


def test_gaosi_question_low_confidence_match_is_audit_only():
    question_text = "牧场上有一片草地，每天都匀速生长，若8头牛12天吃完，10头牛8天吃完，问几头牛6天吃完？"
    standard = _build_standard(
        [
            ReferenceEntry(
                source=GAOSI_QUESTION_SOURCE,
                sheet_name="高思导引PDF题目",
                category="应用题",
                title="牛吃草问题",
                track="拓展篇",
                grade_hint="五年级",
                keywords=("牛吃草问题", "拓展篇"),
                section_level="extension",
                section_label="拓展篇",
                question_text=question_text,
                ocr_confidence=0.52,
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[2],
            "sublevel": "low",
            "evidence_summary": "模型主判偏低。",
        },
        question_text=question_text,
        question_summary="牛吃草问题",
        analysis_facts={"core_task": "牛吃草模型"},
    )

    assert feature["band"] == BAND_LABELS[2]
    assert feature["calibration"]["can_override_model"] is False
    assert feature["need_manual_review"] is True


def test_dim5_specific_exact_title_can_override_model_band():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="guide",
                sheet_name="test",
                category="应用",
                title="牛吃草问题",
                track="拓展篇",
                grade_hint="五年级",
                keywords=("牛吃草问题", "牛吃草", "消耗增长"),
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[2],
            "sublevel": "mid",
            "evidence_summary": "模型主判偏低。",
        },
        question_text="牧场上有一片草地，典型牛吃草问题。",
        question_summary="牛吃草问题",
        analysis_facts={"core_task": "牛吃草模型"},
    )

    calibration = feature["calibration"]

    assert feature["band"] == BAND_LABELS[2]
    assert calibration["can_override_model"] is False
    assert calibration["band_source"] == "audit_only"


def test_dim5_large_gap_without_strong_anchor_keeps_model_band():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="guide",
                sheet_name="test",
                category="应用",
                title="比例关系与方程条件综合",
                track="超越篇",
                grade_hint="六年级",
                keywords=("比例关系", "方程条件", "数量关系"),
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim5",
        {
            "band": BAND_LABELS[2],
            "sublevel": "mid",
            "evidence_summary": "模型主判偏向课内比例关系与方程条件整理。",
            "knowledge_tags": ["比例关系", "方程条件", "数量关系"],
            "core_knowledge_units": ["比例关系", "方程条件", "数量关系"],
        },
        question_text="根据比例关系与方程条件整理数量关系后求未知数。",
        question_summary="比例关系与方程条件求未知数",
        analysis_facts={"core_task": "根据比例关系与方程条件求未知数"},
    )

    calibration = feature["calibration"]

    assert feature["band"] == BAND_LABELS[2]
    assert calibration["final_band"] == BAND_LABELS[2]
    assert calibration["band_source"] in {"audit_only", "model_only"}
    assert calibration["band_source"] != "rule_corrected_with_review"


def test_dim4_question_profile_calibrates_adjacent_level():
    question_text = "把1到9填入九宫格，使每行每列的和满足给定条件，并说明构造方法。"
    standard = _build_standard([_gaosi_dim4_entry(question_text, level="L4")])

    feature = standard.calibrate_dim4_feature(
        _dim4_l3_feature(),
        question_text=question_text,
        question_summary="九宫格策略构造",
        analysis_facts={"core_task": "构造满足条件的九宫格"},
    )

    assert feature["reference_calibrated_level"] == "L4"
    assert feature["calibration"]["action"] == "calibrated_to_reference"
    assert feature["calibration"]["reference_match"]["question_no"] == "5"


def test_gaosi_question_candidates_include_structure_and_profile_quality():
    question_text = "把1到9填入九宫格，使每行每列的和满足给定条件，并说明构造方法。"
    entry = _gaosi_dim4_entry(question_text, level="L4")
    standard = _build_standard([entry])

    candidates = standard.gaosi_question_candidates(
        {"knowledge_tags": ["九宫格"]},
        question_text=question_text,
        question_summary="九宫格策略构造",
        analysis_facts={"core_task": "构造满足条件的九宫格"},
    )

    assert candidates[0]["similarity_type"] == "exact/near_exact"
    assert candidates[0]["auto_correction_allowed"] is True
    assert candidates[0]["auto_dim4_calibration_allowed"] is True
    assert candidates[0]["dim4_profile"]["reference_level"] == "L4"


def test_dim4_local_skeleton_reference_is_candidate_not_auto_calibration():
    question_text = "把1到9填入九宫格，使每行每列的和满足给定条件，并说明构造方法。"
    entry = _gaosi_dim4_entry(question_text, level="L4")
    entry = ReferenceEntry(
        **{
            **entry.to_dict(),
            "dimension_profiles": {
                "structure": {"topic_domain": "logic"},
                "dim4": {
                    "reference_level": "L4",
                    "profile_confidence": 0.55,
                    "auto_calibration_allowed": False,
                    "profile_source": "local_structure_skeleton",
                },
            },
        }
    )
    standard = _build_standard([entry])

    feature = standard.calibrate_dim4_feature(
        _dim4_l3_feature(),
        question_text=question_text,
        question_summary="九宫格策略构造",
        analysis_facts={"core_task": "构造满足条件的九宫格"},
    )
    candidates = standard.gaosi_question_candidates(
        {},
        question_text=question_text,
        question_summary="九宫格策略构造",
        analysis_facts={"core_task": "构造满足条件的九宫格"},
    )

    assert "reference_calibrated_level" not in feature
    assert feature["calibration"]["action"] == "audit_only_unreliable_reference"
    assert candidates[0]["auto_correction_allowed"] is True
    assert candidates[0]["auto_dim4_calibration_allowed"] is False
    assert candidates[0]["structure_profile"]["topic_domain"] == "logic"


def test_dim4_question_profile_large_gap_calibrates_to_reference_up():
    question_text = "在若干张卡片中选择并重新排列，使每组乘积相等，求一种可行构造。"
    standard = _build_standard([_gaosi_dim4_entry(question_text, level="L4")])

    feature = standard.calibrate_dim4_feature(
        _dim4_l2_feature(),
        question_text=question_text,
        question_summary="卡片重排构造",
        analysis_facts={"core_task": "构造可行卡片分组"},
    )

    assert feature["reference_calibrated_level"] == "L4"
    assert "need_manual_review" not in feature
    assert feature["calibration"]["action"] == "calibrated_to_reference"
    assert feature["topic_level"] == "L4"
    assert feature["level_source"] == "question_bank"


def test_dim4_question_profile_large_gap_calibrates_to_reference_down():
    question_text = "按给出的两个规则试填数字，使等式成立。"
    standard = _build_standard([_gaosi_dim4_entry(question_text, level="L2")])

    feature = standard.calibrate_dim4_feature(
        _dim4_l4_feature(),
        question_text=question_text,
        question_summary="规则试填数字",
        analysis_facts={"core_task": "根据规则试填数字"},
    )

    assert "reference_calibrated_level" not in feature
    assert "need_manual_review" not in feature
    assert feature["calibration"]["action"] == "audit_only_reference_lower"
    assert feature["calibration"]["reference_level"] == "L2"
    assert feature["calibration"]["model_level"] == "L4"
    assert "topic_level" not in feature


def test_dim4_not_applicable_with_high_reference_profile_calibrates_to_reference():
    question_text = "把若干个数字填入方格，使横竖斜的和都相等。"
    standard = _build_standard([_gaosi_dim4_entry(question_text, level="L4")])

    feature = standard.calibrate_dim4_feature(
        _dim4_direct_not_applicable_feature(),
        question_text=question_text,
        question_summary="方格填数",
        analysis_facts={"core_task": "构造满足条件的方格"},
    )

    assert feature["reference_calibrated_level"] == "L4"
    assert feature["topic_level"] == "L4"
    assert feature["level_source"] == "question_bank"
    assert feature["calibration"]["action"] == "calibrated_to_reference"


def test_dim4_low_quality_reference_profile_is_audit_only():
    question_text = "把若干个数字填入方格，使横竖斜的和都相等。"
    standard = _build_standard([_gaosi_dim4_entry(question_text, level="L4", ocr_confidence=0.52)])

    feature = standard.calibrate_dim4_feature(
        _dim4_l3_feature(),
        question_text=question_text,
        question_summary="方格填数",
        analysis_facts={"core_task": "构造满足条件的方格"},
    )

    assert "reference_calibrated_level" not in feature
    assert feature["calibration"]["action"] == "audit_only_unreliable_reference"


def test_dim4_diagram_partial_reference_profile_calibrates_with_review():
    reference_text = "如图，把四个全等直角三角形和一个小正方形重新拼成一个大正方形，求一种可行拼法并说明理由。"
    question_text = "如图，把四个全等直角三角形和小正方形重新拼成一个大正方形，求可行拼法并说明理由。"
    standard = _build_standard([_gaosi_dim4_entry(reference_text, level="L4", has_diagram=True)])

    feature = standard.calibrate_dim4_feature(
        _dim4_l3_feature(),
        question_text=question_text,
        question_summary="图形拼法构造",
        analysis_facts={"core_task": "构造可行拼法"},
    )

    assert feature["reference_calibrated_level"] == "L4"
    assert feature["calibration"]["action"] == "calibrated_to_reference_with_review"
    assert feature["calibration"]["reference_match"]["match_quality"] == "diagram_partial_match"
    assert feature["need_manual_review"] is True
    assert "图形部分匹配" in feature["warning"]


def test_dim4_topic_only_gaosi_match_does_not_calibrate():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="gaosi_pdf",
                sheet_name="高思导引PDF目录",
                category="应用题",
                title="牛吃草问题",
                track="拓展篇",
                grade_hint="五年级",
                keywords=("牛吃草问题",),
                dimension_profiles={"dim4": _dim4_profile(level="L4")},
            )
        ]
    )

    feature = standard.calibrate_dim4_feature(
        _dim4_l3_feature(),
        question_text="典型牛吃草问题，需要整理增长与消耗关系。",
        question_summary="牛吃草问题",
        analysis_facts={"core_task": "牛吃草模型"},
    )

    assert "reference_calibrated_level" not in feature
    assert "calibration" not in feature
