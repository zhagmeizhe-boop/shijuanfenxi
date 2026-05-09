from app.services.report.report_service import ReportService
from app.services.report.pdf_generator import PDFExportService


def test_report_service_hides_user_visible_report_warnings():
    warnings = [
        "第 1 页题号 1 缺少明确分值。",
        "第 2 页题号 3 未识别到明确分值。",
        "第 3 页题号 4 分值格式无法解析。",
        "第 1 页题号 2 重复，需检查。",
        "第 2 页题号 8 题干为空。",
    ]

    sanitized = ReportService._sanitize_report_warnings(warnings)

    assert sanitized == []


def test_report_payload_does_not_expose_structure_warnings():
    service = ReportService()

    report = service._build_report_payload(
        paper_id="paper-warning-hidden",
        paper_title="结构化提示测试卷",
        dimension_details=[],
        report_warnings=["第 1 页题号 2 重复，需检查。"],
    )

    assert report["report_warnings"] == []


def test_pdf_export_does_not_render_report_warning_banner():
    html = PDFExportService()._build_report_warning_html(
        ["第 1 页题号 2 重复，需检查。"]
    )

    assert html == ""


def _build_pdf_report_payload(dimension_details):
    return {
        "report_id": "pdf-radar-test",
        "paper_id": "pdf-radar-test",
        "paper_title": "雷达图测试卷",
        "generated_at": "2026-05-09T00:00:00",
        "dimensions": {
            "computation": 70.0,
            "concept": 0.0,
            "logic": 0.0,
            "spatial": 0.0,
            "application": 0.0,
            "innovation": 0.0,
        },
        "dimension_details": dimension_details,
        "report_warnings": [],
        "difficulty_position": {
            "level": 3,
            "label": "拔高卷",
            "overall_score": 7.0,
            "target_students": "适合测试。",
            "description": "用于测试 PDF 雷达图。",
        },
    }


def test_pdf_export_radar_renders_static_svg_for_not_covered_dimensions():
    html = PDFExportService()._generate_html(
        _build_pdf_report_payload(
            [
                {
                    "code": "dim1",
                    "name": "数学运算",
                    "score": 7.0,
                    "level": 4,
                    "level_label": "较难",
                    "score_status": "scored",
                    "evidence": "计算负担较高。",
                },
                {
                    "code": "dim2",
                    "name": "几何直观与空间想象",
                    "score": 0.0,
                    "level": 0,
                    "level_label": "未覆盖",
                    "score_status": "not_covered",
                    "evidence": "未覆盖。",
                },
            ]
        )
    )

    assert '<svg class="report-radar-svg"' in html
    assert 'data-testid="radar-data-area"' in html
    assert 'data-testid="radar-data-line"' in html
    assert 'stroke="#294766" stroke-width="3"' in html
    assert "NaN" not in html
    assert "None" not in html
    assert "null" not in html
    assert "echarts.min.js" not in html
    assert "chartReady" not in html
    assert "value: chartValues" not in html


def test_pdf_export_radar_shows_empty_state_when_all_dimensions_not_covered():
    dimension_details = [
        {
            "code": code,
            "name": name,
            "score": 0.0,
            "level": 0,
            "level_label": "未覆盖",
            "score_status": "not_covered",
            "evidence": "未覆盖。",
        }
        for code, name in [
            ("dim1", "数学运算"),
            ("dim2", "几何直观与空间想象"),
            ("dim3", "信息提取与转化"),
            ("dim4", "实践创新"),
            ("dim5", "知识广度"),
            ("dim6", "逻辑链条"),
        ]
    ]

    html = PDFExportService()._generate_html(_build_pdf_report_payload(dimension_details))

    assert 'id="radar-chart" class="is-empty"><span>暂无可绘制维度</span>' in html
    assert 'data-testid="radar-svg"' not in html
    assert 'data-testid="radar-data-line"' not in html
    assert "echarts.min.js" not in html
    assert "chartReady" not in html
