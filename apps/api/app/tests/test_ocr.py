import pytest
import pytest_asyncio
from httpx import AsyncClient
from datetime import datetime
from unittest.mock import AsyncMock, patch

from app.main import app
from app.services.ocr.mock_provider import MockOCRProvider
from app.services.ocr.base import (
    ParsedPaper, ParsedQuestion, SubQuestion,
    ParseStatus, QuestionType, DimensionCode
)


# ==================== Fixtures ====================

@pytest_asyncio.fixture
async def async_client():
    """创建异步 HTTP 客户端"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_ocr_provider():
    """创建 Mock OCR Provider"""
    return MockOCRProvider()


@pytest.fixture
def sample_parsed_question():
    """创建示例解析题目"""
    return ParsedQuestion(
        question_no="1",
        question_type=QuestionType.FILL_BLANK,
        raw_text="3/4 + 2/5 = ______",
        score=4.0,
        is_optional=False,
        include_in_main_score=True,
        parse_confidence=0.95,
        applicable_dims=[DimensionCode.COMPUTATION],
        ocr_text_version="v1.0",
        sub_questions=[],
    )


@pytest.fixture
def sample_parsed_paper():
    """创建示例解析试卷"""
    return ParsedPaper(
        paper_name="2024年小学五年级数学分班考试",
        total_question_count=10,
        total_score=100.0,
        page_count=6,
        parse_status=ParseStatus.PARSE_SUCCESS,
        parse_confidence=0.92,
        need_manual_review=False,
        questions=[],  # 简化，不添加题目
        file_type="pdf",
        source_file_url="/tmp/mock_paper.pdf",
    )


# ==================== Test Cases ====================

class TestMockOCRProvider:
    """测试 Mock OCR Provider"""

    @pytest.mark.asyncio
    async def test_parse_returns_parsed_paper(self, mock_ocr_provider):
        """测试 parse 方法返回 ParsedPaper 对象"""
        result = await mock_ocr_provider.parse(
            file_path="/tmp/test.pdf",
            paper_name="测试试卷",
        )

        assert isinstance(result, ParsedPaper)
        assert result.paper_name == "测试试卷"
        assert result.total_question_count > 0
        assert result.total_score > 0
        assert result.parse_status == ParseStatus.PARSE_SUCCESS

    @pytest.mark.asyncio
    async def test_parse_generates_questions(self, mock_ocr_provider):
        """测试 parse 方法生成题目"""
        result = await mock_ocr_provider.parse(
            file_path="/tmp/test.pdf",
        )

        assert len(result.questions) > 0

        # 检查每个题目都有必要的字段
        for question in result.questions:
            assert question.question_no
            assert question.question_label_raw
            assert question.question_type
            assert question.raw_text
            assert question.score >= 0
            assert question.parse_confidence >= 0

    @pytest.mark.asyncio
    async def test_parse_with_sub_questions(self, mock_ocr_provider):
        """测试解析带子题目的试卷"""
        # 多次调用以触发子题目生成（30%概率）
        results_with_sub = []
        for _ in range(10):
            result = await mock_ocr_provider.parse(file_path="/tmp/test.pdf")
            has_sub = any(len(q.sub_questions) > 0 for q in result.questions)
            if has_sub:
                results_with_sub.append(result)

        # 至少有一个结果包含子题目
        assert len(results_with_sub) > 0

    @pytest.mark.asyncio
    async def test_health_check(self, mock_ocr_provider):
        """测试健康检查"""
        result = await mock_ocr_provider.health_check()

        assert result["status"] == "healthy"
        assert result["provider"] == "MockOCRProvider"
        assert "capabilities" in result

    def test_validate_upload_valid_file(self, mock_ocr_provider):
        """测试验证有效的上传文件"""
        result = mock_ocr_provider.validate_upload(
            file_path="test.pdf",
            file_size=1024 * 1024,  # 1MB
            file_extension=".pdf",
            is_pdf=True,
        )

        assert result.is_valid is True
        assert result.error_message is None

    def test_validate_upload_oversized_file(self, mock_ocr_provider):
        """测试验证过大的文件"""
        result = mock_ocr_provider.validate_upload(
            file_path="test.pdf",
            file_size=100 * 1024 * 1024,  # 100MB
            file_extension=".pdf",
            is_pdf=True,
        )

        assert result.is_valid is False
        assert "超过限制" in result.error_message

    def test_validate_upload_invalid_extension(self, mock_ocr_provider):
        """测试验证不支持的文件类型"""
        result = mock_ocr_provider.validate_upload(
            file_path="test.txt",
            file_size=1024,
            file_extension=".txt",
            is_pdf=False,
        )

        assert result.is_valid is False
        assert "不支持" in result.error_message


class TestPapersAPI:
    """测试试卷 API"""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, async_client):
        """测试健康检查端点"""
        with patch(
            "app.main.get_ocr_preflight_status",
            new=AsyncMock(return_value={"ocr_ready": True, "provider": "paddleocr", "message": "ready"}),
        ):
            response = await async_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["ocr_provider"] == "paddleocr"
        assert data["ocr_ready"] is True

    @pytest.mark.asyncio
    async def test_root_endpoint(self, async_client):
        """测试根路径端点"""
        response = await async_client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data

    @pytest.mark.asyncio
    async def test_get_paper_status(self, async_client):
        """测试获取试卷状态"""
        paper_id = "test-paper-123"
        response = await async_client.get(f"/api/v1/papers/{paper_id}/status")

        assert response.status_code == 200
        data = response.json()
        assert data["paper_id"] == paper_id
        assert "parse_status" in data

    @pytest.mark.asyncio
    async def test_get_paper_result(self, async_client):
        """测试获取试卷解析结果"""
        paper_id = "test-paper-456"
        response = await async_client.get(f"/api/v1/papers/{paper_id}/result")

        assert response.status_code == 200
        data = response.json()
        assert data["paper_id"] == paper_id
        assert "questions" in data
        assert len(data["questions"]) > 0
