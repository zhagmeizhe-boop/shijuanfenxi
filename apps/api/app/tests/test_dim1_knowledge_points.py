import json
import re
from pathlib import Path

import pytest


DATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "services"
    / "parser"
    / "dim1_knowledge_points.json"
)

LEVEL_TO_GRADE = {
    "L1": 1,
    "L2": 1,
    "L3": 2,
    "L4": 2,
    "L5": 3,
    "L6": 3,
    "L7": 4,
    "L8": 4,
    "L9": 5,
    "L10": 5,
    "L11": 6,
    "L12": 6,
}

REQUIRED_KEYS = {
    "id",
    "source",
    "display_name",
    "track",
    "grade",
    "level_code",
    "branch",
    "knowledge_point",
    "parent_topic",
    "source_file",
    "source_location",
}

TARGET_GAOSI_BRANCHES = {"计算"}


@pytest.fixture(scope="module")
def entries() -> list[dict]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def test_dim1_knowledge_points_resource_shape(entries):
    assert DATA_PATH.exists()
    assert len(entries) > 150
    assert {entry["source"] for entry in entries} == {
        "school_excel",
        "gaosi_knowledge_tree_pdf",
    }

    ids = [entry["id"] for entry in entries]
    assert len(ids) == len(set(ids))
    assert all(REQUIRED_KEYS == set(entry) for entry in entries)


def test_school_entries_use_only_requested_sheet_and_fixed_grade_mapping(entries):
    school_entries = [entry for entry in entries if entry["source"] == "school_excel"]

    assert school_entries
    assert {entry["level_code"] for entry in school_entries} == set(LEVEL_TO_GRADE)
    for entry in school_entries:
        assert entry["track"] == "校内"
        assert entry["branch"] == "校内计算"
        assert entry["parent_topic"] == ""
        assert entry["source_file"] == "新-【小数】计算分级表.xlsx"
        assert "Excel sheet=分级表-7月1日更新;" in entry["source_location"]
        assert entry["grade"] == LEVEL_TO_GRADE[entry["level_code"]]


def test_display_names_follow_dim1_contract(entries):
    for entry in entries:
        knowledge_point = entry["knowledge_point"]
        grade = entry["grade"]
        if entry["source"] == "school_excel":
            assert re.fullmatch(r"校内-[1-6]年级-.+", entry["display_name"])
            assert entry["display_name"] == f"校内-{grade}年级-{knowledge_point}"
        else:
            assert re.fullmatch(r"高思导引-[3-6]年级-.+", entry["display_name"])
            assert entry["display_name"] == f"高思导引-{grade}年级-{knowledge_point}"


def test_gaosi_entries_are_limited_to_target_pdf_branches(entries):
    gaosi_entries = [
        entry for entry in entries if entry["source"] == "gaosi_knowledge_tree_pdf"
    ]

    assert gaosi_entries
    assert {entry["branch"] for entry in gaosi_entries} == TARGET_GAOSI_BRANCHES
    for entry in gaosi_entries:
        assert entry["track"] == "高思导引"
        assert entry["level_code"] == ""
        assert entry["source_file"] == "2024知识树.pdf"
        assert f"branch={entry['branch']}" in entry["source_location"]
        assert f"grade={entry['grade']}" in entry["source_location"]


def test_no_empty_duplicates_or_structural_labels(entries):
    display_names = [entry["display_name"] for entry in entries]
    invalid_points = {
        "知识树",
        "校内计算",
        "数字谜",
        "数论",
        "计算",
        "数",
        "字",
        "谜",
        "论",
    }

    assert len(display_names) == len(set(display_names))
    for entry in entries:
        knowledge_point = entry["knowledge_point"]
        assert knowledge_point
        assert knowledge_point.strip() == knowledge_point
        assert knowledge_point not in invalid_points
        assert not re.fullmatch(r"第\d+讲-\d+", knowledge_point)
        assert not re.fullmatch(r"[1-6]年级", knowledge_point)


def test_expected_anchor_entries_are_present(entries):
    by_display_name = {entry["display_name"]: entry for entry in entries}

    for display_name in {
        "校内-5年级-小数乘法计算",
        "校内-6年级-解比例",
        "高思导引-3年级-四则运算一",
        "高思导引-5年级-分数与循环小数",
        "高思导引-6年级-计算综合",
    }:
        assert display_name in by_display_name

    subtopic = by_display_name["高思导引-3年级-简单凑整法"]
    assert subtopic["branch"] == "计算"
    assert subtopic["parent_topic"] == "四则运算一"
