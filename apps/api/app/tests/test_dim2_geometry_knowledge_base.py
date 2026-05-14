import json
import re
from pathlib import Path

import pytest


DATA_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "scoring"
    / "dim2_geometry_knowledge_base.json"
)

REQUIRED_KEYS = {
    "source_label",
    "grade",
    "semester",
    "knowledge_point",
    "display_name",
    "category",
    "aliases",
    "source_refs",
    "confidence",
}

VALID_SOURCES = {"校内", "高思导引"}
VALID_GRADES = {"一年级", "二年级", "三年级", "四年级", "五年级", "六年级"}
VALID_SEMESTERS = {"", "上册", "下册"}
VALID_CATEGORIES = {
    "shape_recognition",
    "position_direction",
    "measurement",
    "plane_geometry",
    "solid_geometry",
    "transformation",
    "area_model",
    "circle_sector",
    "length_angle",
}
VALID_CONFIDENCES = {"high", "medium", "low"}
FORBIDDEN_MAIN_TERMS = {
    "线段图法解决应用题",
    "统计图",
    "条形统计",
    "折线统计",
    "扇形统计",
    "用直线上的点表示正负数",
    "正、负数",
    "集合",
    "搭配",
    "排列",
    "沏茶",
    "鸡兔",
    "植树",
    "找次品",
    "鸽巢",
    "数与形",
    "几何计数",
}


@pytest.fixture(scope="module")
def entries() -> list[dict]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def test_dim2_geometry_knowledge_base_schema(entries):
    assert DATA_PATH.exists()
    assert len(entries) >= 120

    display_names = [entry["display_name"] for entry in entries]
    assert len(display_names) == len(set(display_names))

    for entry in entries:
        assert set(entry) == REQUIRED_KEYS
        assert entry["source_label"] in VALID_SOURCES
        assert entry["grade"] in VALID_GRADES
        assert entry["semester"] in VALID_SEMESTERS
        assert entry["knowledge_point"].strip() == entry["knowledge_point"]
        assert entry["knowledge_point"]
        assert entry["category"] in VALID_CATEGORIES
        assert entry["confidence"] in VALID_CONFIDENCES
        assert isinstance(entry["aliases"], list)
        assert isinstance(entry["source_refs"], list) and entry["source_refs"]
        for source_ref in entry["source_refs"]:
            assert source_ref["source_file"]
            assert source_ref["source_type"] in {"excel", "pdf_ocr", "pdf_text"}
            assert source_ref["raw_text"]


def test_display_names_follow_dim2_contract(entries):
    for entry in entries:
        source = entry["source_label"]
        grade = entry["grade"]
        point = entry["knowledge_point"]
        assert entry["display_name"] == f"{source}——{grade}——{point}知识点"
        if source == "校内":
            assert re.fullmatch(r"校内——[一二三四五六]年级——.+知识点", entry["display_name"])
            assert entry["semester"] in {"上册", "下册"}
        else:
            assert re.fullmatch(r"高思导引——[三四五六]年级——.+知识点", entry["display_name"])
            assert entry["semester"] == ""


def test_school_entries_cover_grades_and_use_declared_sources(entries):
    school_entries = [entry for entry in entries if entry["source_label"] == "校内"]
    assert {entry["grade"] for entry in school_entries} == VALID_GRADES

    grade12_entries = [entry for entry in school_entries if entry["grade"] in {"一年级", "二年级"}]
    assert grade12_entries
    assert {ref["source_type"] for entry in grade12_entries for ref in entry["source_refs"]} == {"pdf_ocr"}
    assert all("1-2年级合集" not in ref["source_file"] for entry in grade12_entries for ref in entry["source_refs"])

    upper_school_entries = [entry for entry in school_entries if entry["grade"] not in {"一年级", "二年级"}]
    assert upper_school_entries
    assert any(
        ref["source_file"] == "人教版教材知识点.xlsx"
        and ref.get("sheet") == "校内（人教）-旧"
        for entry in upper_school_entries
        for ref in entry["source_refs"]
    )


def test_gaosi_entries_are_limited_to_geometry_branch(entries):
    gaosi_entries = [entry for entry in entries if entry["source_label"] == "高思导引"]

    assert gaosi_entries
    assert {entry["grade"] for entry in gaosi_entries} == {"三年级", "四年级", "五年级", "六年级"}
    for entry in gaosi_entries:
        assert entry["semester"] == ""
        for source_ref in entry["source_refs"]:
            assert source_ref["source_file"] == "2024知识树.pdf"
            assert source_ref["source_type"] == "pdf_text"
            assert source_ref["branch"] == "几何"
            assert "lecture_no" in source_ref


def test_non_geometry_noise_is_not_used_as_main_knowledge_point(entries):
    for entry in entries:
        point = entry["knowledge_point"]
        assert not any(term in point for term in FORBIDDEN_MAIN_TERMS)
        assert not re.fullmatch(r"第\d+讲-\d+", point)
        assert not re.fullmatch(r"[一二三四五六]年级", point)
        assert point not in {"几何", "知识树", "综合问题", "基本公式", "差不变"}


def test_expected_anchor_entries_are_present(entries):
    display_names = {entry["display_name"] for entry in entries}

    expected = {
        "校内——二年级——观察物体（一）知识点",
        "校内——三年级——认识东、南、西、北知识点",
        "校内——五年级——平行四边形的面积计算公式知识点",
        "校内——六年级——圆的认识知识点",
        "校内——五年级——长方体和正方体的体积公式知识点",
        "校内——六年级——圆柱的认识知识点",
        "校内——六年级——圆锥的认识知识点",
        "高思导引——四年级——直线形计算一知识点",
        "高思导引——五年级——圆与扇形知识点",
        "高思导引——六年级——立体几何知识点",
        "高思导引——四年级——格点与割补知识点",
    }
    assert expected <= display_names
