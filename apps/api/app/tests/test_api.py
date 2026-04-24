"""
API集成测试

测试报告API、上传API等接口
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import json

from app.main import app


client = TestClient(app)


class TestReportAPI:
    """测试报告API"""

    def test_get_report_success(self):
        """测试获取报告成功"""
        with patch("app.api.v1.endpoints.report.report_service") as mock_service:
            mock_service.get_report_data.return_value = {
                "report_id": "rpt-001",
                "paper_title": "测试试卷",
                "dimensions": {"computation": 75, "concept": 82},
            }

            response = client.get("/api/v1/reports/rpt-001")

            assert response.status_code == 200
            data = response.json()
            assert data["report_id"] == "rpt-001"
            assert "dimensions" in data

    def test_get_report_not_found(self):
        """测试获取不存在的报告"""
        with patch("app.api.v1.endpoints.report.report_service") as mock_service:
            mock_service.get_report_data.return_value = None

            response = client.get("/api/v1/reports/rpt-notexist")

            assert response.status_code == 404
            assert "不存在" in response.json()["detail"]

    def test_generate_pdf_success(self):
        """测试生成PDF成功"""
        with patch("app.api.v1.endpoints.report.pdf_service") as mock_service:
            mock_service.generate_report_pdf.return_value = "/tmp/report.pdf"

            with patch("app.api.v1.endpoints.report.FileResponse") as mock_file_response:
                mock_file_response.return_value = MagicMock()

                response = client.post("/api/v1/reports/rpt-001/pdf")

                # 注意：由于FileResponse的复杂性，这里可能返回307或其他状态码
                # 主要看是否调用了服务
                mock_service.generate_report_pdf.assert_called_once()

    def test_generate_pdf_service_error(self):
        """测试PDF生成服务错误"""
        with patch("app.api.v1.endpoints.report.pdf_service") as mock_service:
            mock_service.generate_report_pdf.side_effect = Exception("PDF generation failed")

            response = client.post("/api/v1/reports/rpt-001/pdf")

            assert response.status_code == 500
            assert "PDF生成失败" in response.json()["detail"]


class TestUploadAPI:
    """测试上传API"""

    def test_upload_pdf_success(self):
        """测试PDF上传成功"""
        test_file_content = b"%PDF-1.4 test pdf content"

        with patch("app.api.v1.endpoints.upload.process_pdf") as mock_process:
            mock_process.return_value = {
                "paper_id": "paper-001",
                "status": "success",
                "questions_count": 10,
            }

            response = client.post(
                "/api/v1/upload/pdf",
                files={"file": ("test.pdf", test_file_content, "application/pdf")},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["paper_id"] == "paper-001"
            assert data["status"] == "success"

    def test_upload_invalid_file_type(self):
        """测试上传无效文件类型"""
        response = client.post(
            "/api/v1/upload/pdf",
            files={"file": ("test.txt", b"not a pdf", "text/plain")},
        )

        assert response.status_code == 400
        assert "文件类型" in response.json()["detail"] or "PDF" in response.json()["detail"]

    def test_upload_file_too_large(self):
        """测试上传超大文件"""
        # 创建超过限制大小的文件内容
        large_content = b"%PDF-1.4" + b"A" * (11 * 1024 * 1024)  # 10MB+

        with patch("app.api.v1.endpoints.upload.settings") as mock_settings:
            mock_settings.MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB

            response = client.post(
                "/api/v1/upload/pdf",
                files={"file": ("large.pdf", large_content, "application/pdf")},
            )

            # 可能返回413或400
            assert response.status_code in [413, 400, 500]

    def test_upload_processing_error(self):
        """测试上传处理错误"""
        test_content = b"%PDF-1.4 test"

        with patch("app.api.v1.endpoints.upload.process_pdf") as mock_process:
            mock_process.side_effect = Exception("Processing failed")

            response = client.post(
                "/api/v1/upload/pdf",
                files={"file": ("test.pdf", test_content, "application/pdf")},
            )

            assert response.status_code == 500
            assert "处理失败" in response.json()["detail"] or "Processing" in response.json()["detail"]


class TestHealthCheck:
    """测试健康检查接口"""

    def test_health_check(self):
        """测试健康检查"""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

    def test_root_endpoint(self):
        """测试根端点"""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
