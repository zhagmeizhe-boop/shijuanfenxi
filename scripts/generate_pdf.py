"""
本地PDF生成脚本

使用Playwright生成PDF报告
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright


async def generate_pdf(
    report_data: dict,
    output_path: str = None,
) -> str:
    """
    生成PDF报告

    Args:
        report_data: 报告数据
        output_path: 输出路径（可选）

    Returns:
        str: 生成的PDF文件路径
    """
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"./report_{timestamp}.pdf"

    # 生成HTML内容
    html_content = generate_html(report_data)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        # 设置页面内容
        await page.set_content(html_content)

        # 等待图表渲染完成
        await page.wait_for_selector("#radar-chart")
        await asyncio.sleep(2)  # 等待ECharts渲染

        # 生成PDF
        await page.pdf(
            path=output_path,
            format="A4",
            print_background=True,
            margin={
                "top": "20mm",
                "right": "15mm",
                "bottom": "20mm",
                "left": "15mm",
            },
        )

        await browser.close()

    print(f"✅ PDF报告已生成: {output_path}")
    return output_path


def generate_html(report_data: dict) -> str:
    """生成HTML内容"""
    dimensions = report_data.get("dimensions", {})
    details = report_data.get("dimension_details", [])

    html_template = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>六维分析报告</title>
        <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}

            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                line-height: 1.6;
                color: #1f2937;
                background: white;
            }}

            .report-header {{
                text-align: center;
                padding: 40px 20px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
            }}

            .report-header h1 {{
                font-size: 32px;
                margin-bottom: 12px;
            }}

            .paper-title {{
                font-size: 18px;
                opacity: 0.9;
            }}

            .section {{
                padding: 40px 20px;
                max-width: 900px;
                margin: 0 auto;
            }}

            .section-title {{
                font-size: 24px;
                font-weight: 600;
                margin-bottom: 24px;
                padding-bottom: 12px;
                border-bottom: 2px solid #e5e7eb;
            }}

            .radar-container {{
                width: 100%;
                height: 400px;
            }}

            .dimension-card {{
                background: #f9fafb;
                border-radius: 12px;
                padding: 24px;
                margin-bottom: 20px;
                border-left: 4px solid #3b82f6;
            }}

            .dimension-card h3 {{
                font-size: 18px;
                margin-bottom: 12px;
                color: #1f2937;
            }}

            .score-row {{
                display: flex;
                align-items: center;
                gap: 16px;
                margin-bottom: 12px;
            }}

            .score-value {{
                font-size: 32px;
                font-weight: 700;
                color: #3b82f6;
            }}

            .level-badge {{
                padding: 4px 12px;
                background: #dbeafe;
                color: #1e40af;
                border-radius: 20px;
                font-size: 14px;
                font-weight: 500;
            }}

            .evidence {{
                font-size: 14px;
                color: #6b7280;
                line-height: 1.6;
            }}

            .report-footer {{
                text-align: center;
                padding: 24px;
                background: #f3f4f6;
                color: #6b7280;
                font-size: 14px;
            }}
        </style>
    </head>
    <body>
        <header class="report-header">
            <h1>六维分析报告</h1>
            <p class="paper-title">{report_data.get('paper_title', '数学分班考试卷')}</p>
        </header>

        <section class="section">
            <h2 class="section-title">六维能力分析</h2>
            <div class="radar-container" id="radar-chart"></div>
        </section>

        <section class="section">
            <h2 class="section-title">各维度详细评分</h2>
            {''.join([f"""
            <div class="dimension-card">
                <h3>{d.get('name', '')}</h3>
                <div class="score-row">
                    <span class="score-value">{d.get('score', 0)}</span>
                    <span class="level-badge">{d.get('level_label', '')}</span>
                </div>
                <p class="evidence">{d.get('evidence', '')}</p>
            </div>
            """ for d in details])}
        </section>

        <footer class="report-footer">
            <p>© 2024 六维分析系统 | 本报告仅供参考</p>
        </footer>

        <script>
            // 初始化雷达图
            var chart = echarts.init(document.getElementById('radar-chart'));
            var option = {{
                radar: {{
                    indicator: [
                        {{ name: '计算熟练度', max: 100 }},
                        {{ name: '概念清晰度', max: 100 }},
                        {{ name: '逻辑推理力', max: 100 }},
                        {{ name: '空间想象力', max: 100 }},
                        {{ name: '应用实践力', max: 100 }},
                        {{ name: '创新思维力', max: 100 }}
                    ],
                    radius: '65%',
                    axisName: {{
                        color: '#374151',
                        fontSize: 12
                    }}
                }},
                series: [{{
                    type: 'radar',
                    data: [{{
                        value: [
                            {dimensions.get('computation', 0)},
                            {dimensions.get('concept', 0)},
                            {dimensions.get('logic', 0)},
                            {dimensions.get('spatial', 0)},
                            {dimensions.get('application', 0)},
                            {dimensions.get('innovation', 0)}
                        ],
                        name: '能力评估',
                        areaStyle: {{
                            color: 'rgba(59, 130, 246, 0.3)'
                        }},
                        lineStyle: {{
                            color: '#3b82f6',
                            width: 2
                        }},
                        itemStyle: {{
                            color: '#3b82f6'
                        }}
                    }}]
                }}]
            }};
            chart.setOption(option);
        </script>
    </body>
    </html>
    """

    return html_template


async def main():
    """测试PDF生成"""
    # Mock报告数据
    mock_report = {
        "report_id": "rpt-test-001",
        "paper_title": "2024年春季六年级数学分班考试卷",
        "dimensions": {
            "computation": 75,
            "concept": 82,
            "logic": 68,
            "spatial": 70,
            "application": 65,
            "innovation": 58,
        },
        "dimension_details": [
            {
                "code": "dim1",
                "name": "计算熟练度",
                "score": 7.5,
                "level": 4,
                "level_label": "较难",
                "evidence": "数值类型为带分数/小数混合，运算层数为3-4层。",
            },
            {
                "code": "dim2",
                "name": "概念清晰度",
                "score": 6.0,
                "level": 3,
                "level_label": "中等",
                "evidence": "图形熟悉度为标准图形，需要添加1条辅助线。",
            },
            {
                "code": "dim3",
                "name": "逻辑推理力",
                "score": 8.0,
                "level": 4,
                "level_label": "较难",
                "evidence": "信息来源类型为图文混合，条件分散。",
            },
        ],
    }

    output_path = await generate_pdf(mock_report, "./test_report.pdf")
    print(f"PDF已生成: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
