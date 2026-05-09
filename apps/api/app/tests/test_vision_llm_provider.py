import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw

from app.services.ocr.base import IMAGE_MANIFEST_KIND, ParseStatus, QuestionType
from app.services.ocr.vision_llm_provider import PageImage, VisionLLMProvider


class FakeVisionClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, messages, response_format=None):
        self.calls.append({"messages": messages, "response_format": response_format})
        if not self.responses:
            raise AssertionError("Unexpected Vision LLM call")
        return self.responses.pop(0)


def _make_provider(fake_client: FakeVisionClient) -> VisionLLMProvider:
    return VisionLLMProvider(
        {
            "llm_client": fake_client,
            "api_key": "existing-key",
            "base_url": "https://llm.example/v1",
            "model": "vision-model",
            "concurrency": 1,
            "page_timeout": 10,
            "render_dpi": 120,
        }
    )


def _make_image(tmp_path: Path) -> Path:
    image_path = tmp_path / "paper.jpg"
    Image.new("RGB", (900, 1200), "white").save(image_path, format="JPEG")
    return image_path


def _make_named_image(tmp_path: Path, name: str) -> Path:
    image_path = tmp_path / name
    Image.new("RGB", (900, 1200), "white").save(image_path, format="JPEG")
    return image_path


def test_vision_llm_provider_converts_page_json_to_parsed_paper(tmp_path):
    image_path = _make_image(tmp_path)
    response = {
        "page_no": 1,
        "page_width": 900,
        "page_height": 1200,
        "declared_question_count": 2,
        "questions": [
            {
                "question_no": "1",
                "question_label_raw": "1.",
                "question_type": "fill_blank",
                "raw_text": "计算：3/4 + 2/5 = ____",
                "score": 4,
                "bbox": {"left": 40, "top": 80, "width": 700, "height": 160},
                "visual_dependency": "none",
                "confidence": 0.93,
            },
            {
                "question_no": "2",
                "question_label_raw": "2.",
                "question_type": "comprehensive",
                "raw_text": "观察图形，求阴影面积。",
                "score": 6,
                "bbox": {"left": 42, "top": 260, "width": 720, "height": 260},
                "visual_dependency": "required",
                "visual_category": "geometry_visual",
                "confidence": 0.9,
            },
        ],
    }
    fake_client = FakeVisionClient([json.dumps(response, ensure_ascii=False)])
    provider = _make_provider(fake_client)

    parsed = asyncio.run(provider.parse(str(image_path), paper_name="测试卷"))

    assert parsed.paper_name == "测试卷"
    assert parsed.page_count == 1
    assert parsed.total_question_count == 2
    assert parsed.total_score == 10
    assert parsed.parse_status in {ParseStatus.PARSE_SUCCESS, ParseStatus.PARSE_RISK}
    assert parsed.questions[0].question_no == "1"
    assert parsed.questions[0].question_type == QuestionType.FILL_BLANK
    assert parsed.questions[0].image_block_url is not None
    assert Path(parsed.questions[0].image_block_url).exists()
    assert parsed.questions[1].parse_audit.image_required_hint is True
    assert fake_client.calls[0]["response_format"] == {"type": "json_object"}


def test_vision_llm_provider_normalizes_long_section_and_question_no(tmp_path):
    image_path = _make_image(tmp_path)
    response = {
        "page_no": 1,
        "questions": [
            {
                "question_no": "alpha_beta_gamma_delta_extra_long_identifier",
                "question_label_raw": "alpha_beta_gamma_delta_extra_long_identifier",
                "section_index_raw": "二、计算题，能简便的要简便计算（每题5分，共30分）",
                "question_type": "calculation",
                "raw_text": "计算：18 - 26 ÷ 5",
                "score": 5,
                "visual_dependency": "none",
                "confidence": 0.9,
            }
        ],
    }
    fake_client = FakeVisionClient([json.dumps(response, ensure_ascii=False)])
    provider = _make_provider(fake_client)

    parsed = asyncio.run(provider.parse(str(image_path), paper_name="长字段试卷"))

    question = parsed.questions[0]
    assert question.section_index_raw == "二"
    assert len(question.question_no) <= 20
    assert question.question_no == "alpha_beta_gamma_del"
    assert any("题号字段超过存储长度" in item for item in question.parse_warnings)


def test_vision_llm_provider_parses_ordered_image_manifest(tmp_path):
    page_1_path = _make_named_image(tmp_path, "scan-02.jpg")
    page_2_path = _make_named_image(tmp_path, "scan-01.jpg")
    manifest_path = tmp_path / "input_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "kind": IMAGE_MANIFEST_KIND,
                "version": 1,
                "pages": [
                    {
                        "page_no": 1,
                        "path": str(page_1_path),
                        "original_filename": "scan-02.jpg",
                        "content_type": "image/jpeg",
                        "size": page_1_path.stat().st_size,
                    },
                    {
                        "page_no": 2,
                        "path": str(page_2_path),
                        "original_filename": "scan-01.jpg",
                        "content_type": "image/jpeg",
                        "size": page_2_path.stat().st_size,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    fake_client = FakeVisionClient(
        [
            json.dumps(
                {
                    "page_no": 1,
                    "questions": [
                        {
                            "question_no": "1",
                            "question_type": "application",
                            "raw_text": "第一页题目",
                            "score": 4,
                            "bbox": {"left": 20, "top": 20, "width": 300, "height": 120},
                            "confidence": 0.9,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "page_no": 2,
                    "questions": [
                        {
                            "question_no": "2",
                            "question_type": "application",
                            "raw_text": "第二页题目",
                            "score": 5,
                            "bbox": {"left": 20, "top": 20, "width": 300, "height": 120},
                            "confidence": 0.91,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        ]
    )
    provider = _make_provider(fake_client)

    parsed = asyncio.run(provider.parse(str(manifest_path), paper_name="多图试卷"))

    assert parsed.file_type == "images"
    assert parsed.page_count == 2
    assert [question.page_no for question in parsed.questions] == [1, 2]
    assert [question.question_no for question in parsed.questions] == ["1", "2"]


def test_vision_llm_provider_accepts_markdown_fenced_json(tmp_path):
    image_path = _make_image(tmp_path)
    response = """```json
{
  "page_no": 1,
  "questions": [
    {
      "question_no": "1",
      "question_type": "application",
      "raw_text": "一辆车每小时行 60 千米，2 小时行多少千米？",
      "score": 4,
      "bbox": {"left": 40, "top": 80, "width": 700, "height": 180},
      "confidence": 0.9
    }
  ]
}
```"""
    fake_client = FakeVisionClient([response])
    provider = _make_provider(fake_client)

    parsed = asyncio.run(provider.parse(str(image_path), paper_name="围栏 JSON 测试卷"))

    assert parsed.total_question_count == 1
    assert parsed.questions[0].question_no == "1"


def test_vision_llm_provider_repairs_trailing_commas_and_inner_quotes(tmp_path):
    provider = _make_provider(FakeVisionClient([]))
    page_image = PageImage(page_no=1, path=str(tmp_path / "page.jpg"), width=900, height=1200)
    response = """{
  "page_no": 1,
  "questions": [
    {
      "question_no": "2",
      "question_type": "application",
      "raw_text": "统计古诗中"春"字出现次数。",
      "score": 3,
      "bbox": null,
      "confidence": 0.81,
    },
  ],
}"""

    payload = asyncio.run(provider._load_page_json(response, page_image))

    assert payload["questions"][0]["question_no"] == "2"
    assert payload["questions"][0]["raw_text"] == '统计古诗中"春"字出现次数。'


def test_vision_llm_provider_repairs_truncated_json_locally(tmp_path):
    provider = _make_provider(FakeVisionClient([]))
    page_image = PageImage(page_no=1, path=str(tmp_path / "page.jpg"), width=900, height=1200)
    response = (
        '{"page_no": 1, "questions": ['
        '{"question_no": "5", "question_type": "application", "raw_text": "应用题", '
        '"score": 2, "bbox": null, "confidence": 0.8}]'
    )

    payload = asyncio.run(provider._load_page_json(response, page_image))

    assert payload["questions"][0]["question_no"] == "5"
    assert payload["questions"][0]["raw_text"] == "应用题"


def test_vision_llm_provider_marks_duplicate_missing_score_and_bbox_fallback(tmp_path):
    image_path = _make_image(tmp_path)
    response = {
        "page_no": 1,
        "declared_question_count": 2,
        "questions": [
            {
                "question_no": "1",
                "question_type": "solution",
                "raw_text": "第一题。",
                "score": 5,
                "bbox": {"left": 20, "top": 20, "width": 400, "height": 120},
                "confidence": 0.88,
            },
            {
                "question_no": "1",
                "question_type": "comprehensive",
                "raw_text": "重复题号且需要图形。",
                "score": None,
                "bbox": None,
                "visual_dependency": "required",
                "confidence": 0.52,
            },
        ],
    }
    fake_client = FakeVisionClient([json.dumps(response, ensure_ascii=False)])
    provider = _make_provider(fake_client)

    parsed = asyncio.run(provider.parse(str(image_path), paper_name="测试卷"))

    assert parsed.need_manual_review is True
    assert parsed.questions[1].question_no == "1-dup2"
    assert parsed.questions[1].score == 0
    assert parsed.questions[1].image_block_url.endswith("vision_pages\\page_1.jpg") or parsed.questions[
        1
    ].image_block_url.endswith("vision_pages/page_1.jpg")
    assert parsed.questions[1].parse_audit.score_source == "missing"
    assert any("分值" in warning for warning in parsed.questions[1].parse_warnings)
    assert any("重复" in warning for warning in parsed.report_warnings)
    assert not any(
        "缺少明确分值" in warning
        or "未识别到明确分值" in warning
        or "分值格式无法解析" in warning
        for warning in parsed.report_warnings
    )


def test_vision_llm_provider_keeps_missing_scores_out_of_report_warnings(tmp_path):
    image_path = _make_image(tmp_path)
    response = {
        "page_no": 1,
        "questions": [
            {
                "question_no": "1",
                "question_type": "application",
                "raw_text": "第一题。",
                "score": None,
                "bbox": {"left": 20, "top": 20, "width": 400, "height": 120},
                "confidence": 0.98,
            },
            {
                "question_no": "2",
                "question_type": "application",
                "raw_text": "第二题。",
                "score": None,
                "bbox": {"left": 20, "top": 180, "width": 400, "height": 120},
                "confidence": 0.98,
            },
        ],
    }
    fake_client = FakeVisionClient([json.dumps(response, ensure_ascii=False)])
    provider = _make_provider(fake_client)

    parsed = asyncio.run(provider.parse(str(image_path), paper_name="缺分值测试卷"))

    assert parsed.need_manual_review is False
    assert parsed.report_warnings == []
    assert [question.parse_audit.score_source for question in parsed.questions] == ["missing", "missing"]
    assert all(any("分值" in warning for warning in question.parse_warnings) for question in parsed.questions)


def test_vision_llm_duplicate_question_crops_use_unique_final_numbers(tmp_path):
    image_path = _make_image(tmp_path)
    response = {
        "page_no": 1,
        "questions": [
            {
                "question_no": "1",
                "question_type": "solution",
                "raw_text": "第一道题。",
                "score": 4,
                "bbox": {"left": 20, "top": 20, "width": 300, "height": 120},
                "confidence": 0.91,
            },
            {
                "question_no": "1",
                "question_type": "solution",
                "raw_text": "同页重复题号。",
                "score": 5,
                "bbox": {"left": 20, "top": 180, "width": 300, "height": 120},
                "confidence": 0.89,
            },
        ],
    }
    fake_client = FakeVisionClient([json.dumps(response, ensure_ascii=False)])
    provider = _make_provider(fake_client)

    parsed = asyncio.run(provider.parse(str(image_path), paper_name="重复题号测试卷"))

    first_image = Path(parsed.questions[0].image_block_url)
    second_image = Path(parsed.questions[1].image_block_url)
    assert parsed.questions[1].question_no == "1-dup2"
    assert first_image.name == "page_1_q_1.jpg"
    assert second_image.name == "page_1_q_1-dup2.jpg"
    assert first_image != second_image
    assert first_image.exists()
    assert second_image.exists()


def test_vision_llm_provider_merges_cross_page_continuation(tmp_path):
    page_1_path = _make_named_image(tmp_path, "page_1.jpg")
    page_2_path = _make_named_image(tmp_path, "page_2.jpg")
    provider = _make_provider(FakeVisionClient([]))

    questions, audits, warnings = provider._build_structured_result(
        [
            PageImage(page_no=1, path=str(page_1_path), width=900, height=1200),
            PageImage(page_no=2, path=str(page_2_path), width=900, height=1200),
        ],
        [
            {
                "page_no": 1,
                "questions": [
                    {
                        "question_no": "4",
                        "question_type": "application",
                        "raw_text": "第 4 题前半部分。",
                        "score": 8,
                        "bbox": {"left": 40, "top": 80, "width": 700, "height": 220},
                        "confidence": 0.88,
                    }
                ],
            },
            {
                "page_no": 2,
                "questions": [
                    {
                        "question_no": "4",
                        "question_type": "application",
                        "raw_text": "第 4 题后半部分。",
                        "score": None,
                        "bbox": {"left": 40, "top": 40, "width": 700, "height": 180},
                        "is_continuation": True,
                        "confidence": 0.73,
                    }
                ],
            },
        ],
    )

    assert len(questions) == 1
    assert len(audits) == 2
    assert "续第 2 页" in questions[0].raw_text
    assert questions[0].parse_audit.cross_page_merged is True
    assert any("跨页延续" in warning for warning in warnings)


def test_vision_llm_provider_merges_cross_page_subquestion_continuation(tmp_path):
    page_1_path = _make_named_image(tmp_path, "page_1.jpg")
    page_2_path = _make_named_image(tmp_path, "page_2.jpg")
    provider = _make_provider(FakeVisionClient([]))

    questions, audits, warnings = provider._build_structured_result(
        [
            PageImage(page_no=1, path=str(page_1_path), width=900, height=1200),
            PageImage(page_no=2, path=str(page_2_path), width=900, height=1200),
        ],
        [
            {
                "page_no": 1,
                "questions": [
                    {
                        "question_no": "29",
                        "question_label_raw": "29.",
                        "question_type": "calculation",
                        "raw_text": "29. 列式计算。（1）第一小问。",
                        "score": 6,
                        "bbox": {"left": 40, "top": 760, "width": 700, "height": 160},
                        "confidence": 0.9,
                    }
                ],
            },
            {
                "page_no": 2,
                "questions": [
                    {
                        "question_no": "2",
                        "question_label_raw": "(2)",
                        "question_type": "calculation",
                        "raw_text": "(2) 一个数的 2 倍比 54 的 1/6 少 3，求这个数。",
                        "score": None,
                        "bbox": {"left": 40, "top": 30, "width": 700, "height": 90},
                        "is_continuation": True,
                        "confidence": 0.84,
                    },
                    {
                        "question_no": "30",
                        "question_label_raw": "30.",
                        "question_type": "application",
                        "raw_text": "30. 求阴影面积。",
                        "score": 4,
                        "bbox": {"left": 40, "top": 260, "width": 700, "height": 220},
                        "confidence": 0.89,
                    },
                ],
            },
        ],
    )

    assert [question.question_no for question in questions] == ["29", "30"]
    assert "续第 2 页" in questions[0].raw_text
    assert "(2) 一个数" in questions[0].raw_text
    assert audits[1].detected_count == 1
    assert audits[1].anchor_numbers == ["30"]
    assert not any("已按独立题处理" in warning for warning in warnings)
    assert not any("题号 2 被" in warning for warning in warnings)
    assert not any("缺失" in warning for warning in warnings)


def test_vision_llm_provider_keeps_new_question_when_continuation_number_differs(tmp_path):
    page_1_path = _make_named_image(tmp_path, "page_1.jpg")
    page_2_path = _make_named_image(tmp_path, "page_2.jpg")
    provider = _make_provider(FakeVisionClient([]))

    questions, audits, warnings = provider._build_structured_result(
        [
            PageImage(page_no=1, path=str(page_1_path), width=900, height=1200),
            PageImage(page_no=2, path=str(page_2_path), width=900, height=1200),
        ],
        [
            {
                "page_no": 1,
                "questions": [
                    {
                        "question_no": "18",
                        "question_type": "calculation",
                        "raw_text": "第 18 题计算。",
                        "score": 4,
                        "bbox": {"left": 40, "top": 80, "width": 700, "height": 180},
                        "confidence": 0.91,
                    }
                ],
            },
            {
                "page_no": 2,
                "questions": [
                    {
                        "question_no": "19",
                        "question_type": "application",
                        "raw_text": "第 19 题应用题。",
                        "score": None,
                        "bbox": {"left": 40, "top": 80, "width": 700, "height": 180},
                        "is_continuation": True,
                        "confidence": 0.88,
                    }
                ],
            },
        ],
    )

    assert [question.question_no for question in questions] == ["18", "19"]
    assert len(audits) == 2
    assert questions[0].parse_audit.cross_page_merged is False
    assert questions[1].parse_audit.cross_page_merged is False
    assert any("已按独立题处理" in warning for warning in questions[1].parse_warnings)
    assert any("已按独立题处理" in warning for warning in warnings)


def test_vision_llm_provider_keeps_declared_count_mismatch_out_of_report_warnings(tmp_path):
    image_path = _make_image(tmp_path)
    response = {
        "page_no": 1,
        "declared_question_count": 10,
        "questions": [
            {
                "question_no": str(number),
                "question_label_raw": f"{number}.",
                "question_type": "single_choice",
                "raw_text": f"第 {number} 题。",
                "score": 2,
                "bbox": {"left": 20, "top": 20 + number * 80, "width": 400, "height": 60},
                "confidence": 0.96,
            }
            for number in range(1, 6)
        ],
    }
    fake_client = FakeVisionClient([json.dumps(response, ensure_ascii=False)])
    provider = _make_provider(fake_client)

    parsed = asyncio.run(provider.parse(str(image_path), paper_name="声明题数测试卷"))

    assert parsed.total_question_count == 5
    assert parsed.question_count_audits[0].declared_count == 10
    assert parsed.question_count_audits[0].detected_count == 5
    assert not any("声明题数" in warning for warning in parsed.report_warnings)


def test_vision_llm_provider_reports_global_missing_question_numbers(tmp_path):
    image_path = _make_image(tmp_path)
    response = {
        "page_no": 1,
        "questions": [
            {
                "question_no": str(number),
                "question_label_raw": f"{number}.",
                "question_type": "application",
                "raw_text": f"第 {number} 题。",
                "score": 4,
                "bbox": {"left": 20, "top": 20 + index * 100, "width": 400, "height": 80},
                "confidence": 0.95,
            }
            for index, number in enumerate([1, 2, 4])
        ],
    }
    fake_client = FakeVisionClient([json.dumps(response, ensure_ascii=False)])
    provider = _make_provider(fake_client)

    parsed = asyncio.run(provider.parse(str(image_path), paper_name="跳号测试卷"))

    assert any("整卷题号可能不连续" in warning and "3" in warning for warning in parsed.report_warnings)
    assert not any("第 1 页题号可能不连续" in warning for warning in parsed.report_warnings)


def test_vision_llm_provider_auto_orients_sideways_page():
    provider = _make_provider(FakeVisionClient([]))
    upright = Image.new("RGB", (1000, 700), "white")
    draw = ImageDraw.Draw(upright)
    for y in range(80, 620, 42):
        draw.line((80, y, 900, y), fill="black", width=4)
        draw.line((80, y + 12, 740, y + 12), fill="black", width=3)
    sideways = upright.rotate(270, expand=True)

    oriented = provider._auto_orient_page_image(sideways, page_no=1)

    assert oriented.width > oriented.height


def test_vision_llm_provider_trims_large_page_whitespace():
    provider = _make_provider(FakeVisionClient([]))
    image = Image.new("RGB", (1000, 1000), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((420, 430, 620, 560), outline="black", width=6)

    trimmed = provider._trim_page_whitespace(image, page_no=1)

    assert trimmed.width < 300
    assert trimmed.height < 250


def test_vision_llm_provider_flags_missing_number_and_low_confidence(tmp_path):
    image_path = _make_image(tmp_path)
    response = {
        "page_no": 1,
        "questions": [
            {
                "question_no": "",
                "question_type": "comprehensive",
                "raw_text": "观察统计图，回答问题。",
                "score": None,
                "bbox": None,
                "visual_dependency": "required",
                "confidence": 0.42,
            }
        ],
    }
    fake_client = FakeVisionClient([json.dumps(response, ensure_ascii=False)])
    provider = _make_provider(fake_client)

    parsed = asyncio.run(provider.parse(str(image_path), paper_name="低置信度测试卷"))

    assert parsed.need_manual_review is True
    assert parsed.questions[0].question_no == "p1q1"
    assert parsed.questions[0].image_block_url is not None
    assert Path(parsed.questions[0].image_block_url).name == "page_1.jpg"
    assert any("缺少题号" in warning for warning in parsed.report_warnings)
    assert parsed.parse_status in {
        ParseStatus.NEED_MANUAL_REVIEW,
        ParseStatus.NEED_REUPLOAD,
    }


def test_vision_llm_provider_repairs_invalid_json_with_same_client(tmp_path):
    image_path = _make_image(tmp_path)
    repaired_response = {
        "page_no": 1,
        "questions": [
            {
                "question_no": "3",
                "question_type": "application",
                "raw_text": "小明买了 3 支笔，每支 2 元，一共多少元？",
                "score": 3,
                "bbox": [30, 40, 500, 180],
                "confidence": 0.86,
            }
        ],
    }
    fake_client = FakeVisionClient(
        [
            '{"page_no": 1, "questions": [',
            json.dumps(repaired_response, ensure_ascii=False),
        ]
    )
    provider = _make_provider(fake_client)

    parsed = asyncio.run(provider.parse(str(image_path), paper_name="修复测试卷"))

    assert parsed.total_question_count == 1
    assert parsed.questions[0].question_no == "3"
    assert len(fake_client.calls) == 2


def test_vision_llm_provider_reports_page_when_repair_still_invalid(tmp_path):
    image_path = _make_image(tmp_path)
    fake_client = FakeVisionClient(["这不是 JSON", "仍然不是 JSON"])
    provider = _make_provider(fake_client)

    with pytest.raises(ValueError) as exc_info:
        asyncio.run(provider.parse(str(image_path), paper_name="失败测试卷"))

    message = str(exc_info.value)
    assert "第 1 页 Vision LLM 返回内容不是有效 JSON" in message
    assert "已重试 1 次" in message
    assert len(fake_client.calls) == 2


def test_vision_llm_provider_passes_configured_max_tokens_to_client():
    provider = VisionLLMProvider(
        {
            "api_key": "existing-key",
            "base_url": "https://llm.example/v1",
            "model": "vision-model",
            "max_tokens": 12000,
        }
    )

    with patch("app.services.ocr.vision_llm_provider.MoonshotClient") as client_class:
        provider._get_llm_client()

    assert client_class.call_args.kwargs["max_tokens"] == 12000
    assert client_class.call_args.kwargs["llm_pool"] == "vision"


def test_vision_llm_health_uses_existing_key_config():
    provider = VisionLLMProvider(
        {
            "api_key": "existing-key",
            "base_url": "https://llm.example/v1",
            "model": "vision-model",
        }
    )

    status = asyncio.run(provider.health_check())

    assert status["status"] == "healthy"
    assert status["provider"] == "VisionLLMProvider"
    assert status["capabilities"]["ocr_engine"] is False
