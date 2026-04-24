from pathlib import Path

from app.services.parser.reference_standard import (
    BAND_LABELS,
    DATA_FILE_NAME,
    ReferenceEntry,
    WorkbookReferenceStandard,
    get_reference_standard,
)


def _build_standard(entries: list[ReferenceEntry]) -> WorkbookReferenceStandard:
    standard = WorkbookReferenceStandard.__new__(WorkbookReferenceStandard)
    standard.data_path = Path(DATA_FILE_NAME)
    standard.workbook_path = None
    standard.entries = entries
    return standard


def test_reference_standard_prefers_json_resource():
    standard = get_reference_standard()

    assert standard.data_path.name == DATA_FILE_NAME
    assert standard.data_path.exists()
    assert len(standard.entries) > 1000


def test_reference_standard_calibrates_school_geometry():
    standard = get_reference_standard()
    feature = standard.calibrate_feature(
        "dim2",
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


def test_dim1_weak_generic_match_does_not_override_model_band():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="school",
                sheet_name="test",
                category="计算",
                title="计算",
                track="校内",
                grade_hint="四年级",
                keywords=("计算",),
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim1",
        {
            "band": BAND_LABELS[4],
            "sublevel": "mid",
            "evidence_summary": "需要较复杂的计算组织。",
        },
        question_text="这道题需要较复杂计算，但参考体系只命中泛词。",
        question_summary="复杂计算题",
        analysis_facts={"core_task": "复杂计算"},
    )

    calibration = feature["calibration"]

    assert feature["band"] == BAND_LABELS[4]
    assert calibration["can_override_model"] is False
    assert calibration["band_source"] == "audit_only"
    assert "泛化术语" in feature["warning"]


def test_dim2_weak_generic_match_does_not_override_model_band():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="school",
                sheet_name="test",
                category="几何",
                title="几何",
                track="校内",
                grade_hint="四年级",
                keywords=("几何",),
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim2",
        {
            "band": BAND_LABELS[4],
            "sublevel": "mid",
            "evidence_summary": "需要复杂空间关系判断。",
        },
        question_text="这道题需要复杂几何关系判断，但参考体系只命中泛词。",
        question_summary="空间关系题",
        analysis_facts={"core_task": "空间关系判断"},
    )

    calibration = feature["calibration"]

    assert feature["band"] == BAND_LABELS[4]
    assert calibration["can_override_model"] is False
    assert calibration["band_source"] == "audit_only"
    assert "泛化术语" in feature["warning"]


def test_dim1_specific_exact_title_can_override_model_band():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="school",
                sheet_name="test",
                category="计算",
                title="小数四则混合运算",
                track="校内",
                grade_hint="五年级",
                keywords=("小数四则混合运算", "小数", "四则", "混合运算"),
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim1",
        {
            "band": BAND_LABELS[1],
            "sublevel": "mid",
            "evidence_summary": "模型主判偏低。",
        },
        question_text="计算：小数四则混合运算。",
        question_summary="小数四则混合运算",
        analysis_facts={"core_task": "小数四则混合运算"},
    )

    calibration = feature["calibration"]

    assert feature["band"] == BAND_LABELS[2]
    assert calibration["can_override_model"] is True
    assert calibration["band_source"] == "rule_corrected"


def test_dim2_specific_exact_title_can_override_model_band():
    standard = _build_standard(
        [
            ReferenceEntry(
                source="guide",
                sheet_name="test",
                category="几何",
                title="正方体涂色",
                track="拓展篇",
                grade_hint="五年级",
                keywords=("正方体涂色", "正方体", "涂色"),
            )
        ]
    )

    feature = standard.calibrate_feature(
        "dim2",
        {
            "band": BAND_LABELS[2],
            "sublevel": "mid",
            "evidence_summary": "模型主判偏低。",
        },
        question_text="如图，求正方体涂色后露出的面数。",
        question_summary="正方体涂色",
        analysis_facts={"core_task": "正方体涂色模型"},
    )

    calibration = feature["calibration"]

    assert feature["band"] == BAND_LABELS[4]
    assert calibration["can_override_model"] is True
    assert calibration["band_source"] == "rule_corrected_with_review"
    assert feature["need_manual_review"] is True
