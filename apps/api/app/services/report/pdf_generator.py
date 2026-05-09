"""
PDF export service.

Render the report with Playwright and return either raw PDF bytes or an
optionally persisted file path.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

from app.core.config import settings

logger = logging.getLogger(__name__)

DIM_META = [
    {
        "code": "dim1",
        "field": "computation",
        "name": "数学运算",
        "chart_name": "数学运算",
        "color": "#295d8a",
    },
    {
        "code": "dim2",
        "field": "concept",
        "name": "几何直观与空间想象",
        "chart_name": "几何直观\n与空间想象",
        "color": "#3d7a85",
    },
    {
        "code": "dim3",
        "field": "logic",
        "name": "信息提取与转化",
        "chart_name": "信息提取\n与转化",
        "color": "#6f7d48",
    },
    {
        "code": "dim4",
        "field": "spatial",
        "name": "实践创新",
        "chart_name": "实践创新",
        "color": "#8a6842",
    },
    {
        "code": "dim5",
        "field": "application",
        "name": "知识广度",
        "chart_name": "知识广度",
        "color": "#8b5754",
    },
    {
        "code": "dim6",
        "field": "innovation",
        "name": "逻辑链条长度",
        "chart_name": "逻辑链条\n长度",
        "color": "#5f567c",
    },
]

for _meta in DIM_META:
    if _meta.get("code") == "dim6":
        _meta["name"] = "逻辑链条"
        _meta["chart_name"] = "逻辑链条"

DIFFICULTY_META = {
    1: {
        "label": "基础卷",
        "color": "#3f7a57",
        "surface": "#f1f7f2",
        "border": "#c9ddce",
        "description": "整体更强调基础概念与常规运算，适合夯实基本能力。",
        "target_students": "适合基础薄弱、需要巩固基本概念的学生。",
    },
    2: {
        "label": "提升卷",
        "color": "#356a7c",
        "surface": "#eef5f8",
        "border": "#c7d9e0",
        "description": "注重知识覆盖、基本应用和稳定解题能力，适合从课内掌握走向稳步提升。",
        "target_students": "适合基础一般、希望从课内掌握走向稳定提升的学生。",
    },
    3: {
        "label": "拔高卷",
        "color": "#8a6b2d",
        "surface": "#fbf6ea",
        "border": "#e6d9b4",
        "description": "强调综合运用、方法迁移和拔高训练，适合基础较好的学生。",
        "target_students": "适合基础较好、需要强化综合运用和拔高训练的学生。",
    },
    4: {
        "label": "选拔卷",
        "color": "#8b5a3c",
        "surface": "#fbf2ee",
        "border": "#e6cfc1",
        "description": "面向选拔区分场景，重视复杂问题解决、策略迁移与稳定性。",
        "target_students": "适合基础扎实、需要面向选拔场景提升综合稳定性的学生。",
    },
    5: {
        "label": "竞赛卷",
        "color": "#6b557f",
        "surface": "#f4f0f8",
        "border": "#d9d0e6",
        "description": "整体强度高，突出竞赛型思维、跨模块综合和高难度解题技巧。",
        "target_students": "适合成绩优秀、准备挑战竞赛或高强度选拔的学生。",
    },
}


class PDFExportService:
    """Service responsible for PDF generation."""

    def __init__(self) -> None:
        report_dir = settings.REPORT_OUTPUT_DIR
        if os.path.isabs(report_dir):
            self.output_dir = Path(report_dir)
        else:
            api_root = Path(__file__).resolve().parents[3]
            rel = report_dir.replace("\\", "/").lstrip("./")
            self.output_dir = api_root / rel
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate_report_pdf(
        self,
        report_data: dict,
        output_path: Optional[str] = None,
    ) -> str:
        """Generate a PDF file on disk and return the path."""
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(self.output_dir / f"report_{timestamp}.pdf")

        pdf_bytes = await self.generate_report_pdf_bytes(report_data)
        Path(output_path).write_bytes(pdf_bytes)

        logger.info("PDF report saved to %s", output_path)
        return output_path

    async def generate_report_pdf_bytes(self, report_data: dict) -> bytes:
        """Generate a PDF report and return the raw bytes."""
        report_id = str(report_data.get("report_id") or report_data.get("paper_id") or "unknown")
        loop = asyncio.get_running_loop()
        policy = asyncio.get_event_loop_policy()
        logger.info("PDF export started report=%s", report_id)
        logger.info(
            "PDF export context report=%s loop=%s policy=%s is_windows=%s",
            report_id,
            type(loop).__name__,
            type(policy).__name__,
            sys.platform == "win32",
        )

        logger.info("PDF export stage=build_html report=%s", report_id)
        html_content = self._generate_html(report_data)

        logger.info("PDF export stage=launch_browser report=%s", report_id)
        pdf_bytes = await asyncio.to_thread(self._render_pdf_bytes_sync, html_content, report_id)

        logger.info("PDF export stage=pdf_ready report=%s bytes=%s", report_id, len(pdf_bytes))
        return pdf_bytes

    def _render_pdf_bytes_sync(self, html_content: str, report_id: str) -> bytes:
        try:
            with sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch()
                except Exception as exc:
                    raise RuntimeError(self._build_render_error_message("launch_browser", exc)) from exc
                try:
                    page = browser.new_page()
                    try:
                        page.set_content(html_content, wait_until="domcontentloaded")
                    except Exception as exc:
                        raise RuntimeError(self._build_render_error_message("render_html", exc)) from exc

                    try:
                        return page.pdf(
                            format="A4",
                            print_background=True,
                            margin={
                                "top": "10mm",
                                "right": "10mm",
                                "bottom": "12mm",
                                "left": "10mm",
                            },
                        )
                    except Exception as exc:
                        raise RuntimeError(self._build_render_error_message("render_pdf", exc)) from exc
                finally:
                    browser.close()
        except Exception as exc:
            logger.exception("PDF export renderer failed report=%s", report_id)
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(self._build_render_error_message("render_pdf", exc)) from exc

    @staticmethod
    def _build_render_error_message(stage: str, exc: Exception) -> str:
        stage_label = {
            "launch_browser": "Chromium 启动",
            "render_html": "HTML 渲染",
            "render_pdf": "PDF 生成",
        }.get(stage, "PDF 渲染")

        exc_type = exc.__class__.__name__
        exc_text = str(exc).strip()
        combined_text = exc_text or exc_type
        lowered = combined_text.lower()

        if "executable doesn't exist" in lowered or "playwright install" in lowered:
            combined_text = "未检测到 Playwright Chromium 浏览器，请先执行 playwright install chromium。"
        elif exc_type == "NotImplementedError" or "create_subprocess_exec" in lowered:
            combined_text = "当前运行环境不支持启动浏览器子进程。Windows 开发环境请使用线程内同步渲染。"
        elif "browser" in lowered and "closed" in lowered:
            combined_text = "浏览器进程在导出过程中提前退出。"

        return f"{stage_label}失败（{exc_type}）：{combined_text}"

    def _format_generated_at(self, value: Optional[str]) -> str:
        if not value:
            return datetime.now().strftime("%Y-%m-%d %H:%M")

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return value

    @staticmethod
    def _format_score(value: object, digits: int = 1) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        return f"{numeric:.{digits}f}"

    @staticmethod
    def _safe_float(value: object, fallback: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _clamp_radar_value(value: object) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(numeric):
            return 0.0
        return max(0.0, min(100.0, numeric))

    @staticmethod
    def _radar_svg_point(index: int, radius: float, total: int = 6) -> tuple[float, float]:
        center_x = 180.0
        center_y = 168.0
        angle = -math.pi / 2 + (index * 2 * math.pi) / total
        return (
            center_x + math.cos(angle) * radius,
            center_y + math.sin(angle) * radius,
        )

    @staticmethod
    def _format_svg_point(point: tuple[float, float]) -> str:
        return f"{point[0]:.2f},{point[1]:.2f}"

    def _build_radar_label_html(self, meta: dict, index: int) -> str:
        label_x, label_y = self._radar_svg_point(index, 142.0, len(DIM_META))
        if label_x < 168:
            text_anchor = "end"
        elif label_x > 192:
            text_anchor = "start"
        else:
            text_anchor = "middle"

        lines = str(meta.get("chart_name") or meta.get("name") or "").splitlines() or [
            str(meta.get("name") or "")
        ]
        first_line_dy = 0 if len(lines) == 1 else -0.45 * (len(lines) - 1)
        tspan_html = "".join(
            f'<tspan x="{label_x:.2f}" dy="{first_line_dy:.2f}em">{escape(line)}</tspan>'
            if line_index == 0
            else f'<tspan x="{label_x:.2f}" dy="1.15em">{escape(line)}</tspan>'
            for line_index, line in enumerate(lines)
        )
        return (
            f'<text x="{label_x:.2f}" y="{label_y:.2f}" text-anchor="{text_anchor}" '
            'dominant-baseline="middle" fill="#43525d" font-size="12" font-weight="600">'
            f"{tspan_html}</text>"
        )

    def _build_radar_svg_html(self, chart_values: list[object]) -> str:
        total = len(DIM_META)
        values = [self._clamp_radar_value(value) for value in chart_values[:total]]
        if len(values) < total:
            values.extend([0.0] * (total - len(values)))

        grid_html_parts: list[str] = []
        for index, level in enumerate([0.25, 0.5, 0.75, 1.0]):
            points = " ".join(
                self._format_svg_point(self._radar_svg_point(dim_index, 108.0 * level, total))
                for dim_index in range(total)
            )
            fill = "rgba(238, 242, 246, 0.72)" if index % 2 == 0 else "rgba(248, 250, 252, 0.28)"
            grid_html_parts.append(
                f'<polygon points="{points}" fill="{fill}" stroke="#d6dde3" '
                'stroke-width="1" vector-effect="non-scaling-stroke" />'
            )

        axis_html_parts: list[str] = []
        for index, meta in enumerate(DIM_META):
            outer_x, outer_y = self._radar_svg_point(index, 108.0, total)
            axis_html_parts.append(
                f'<line x1="180.00" y1="168.00" x2="{outer_x:.2f}" y2="{outer_y:.2f}" '
                'stroke="#d6dde3" stroke-width="1" vector-effect="non-scaling-stroke" />'
            )
            axis_html_parts.append(self._build_radar_label_html(meta, index))

        data_points = [
            self._radar_svg_point(index, 108.0 * (value / 100.0), total)
            for index, value in enumerate(values)
        ]
        data_points_text = " ".join(self._format_svg_point(point) for point in data_points)
        closed_line_points = f"{data_points_text} {self._format_svg_point(data_points[0])}"
        marker_html = "".join(
            f'<circle data-testid="radar-data-point" cx="{point[0]:.2f}" cy="{point[1]:.2f}" '
            'r="4" fill="#294766" stroke="#ffffff" stroke-width="2" '
            'vector-effect="non-scaling-stroke" />'
            for point in data_points
        )

        return f"""
        <svg class="report-radar-svg" data-testid="radar-svg" viewBox="0 0 360 340" role="img" aria-label="六维评价雷达图">
          <title>六维评价雷达图</title>
          {"".join(grid_html_parts)}
          {"".join(axis_html_parts)}
          <polygon data-testid="radar-data-area" points="{data_points_text}" fill="rgba(41, 71, 102, 0.16)" stroke="none" />
          <polyline data-testid="radar-data-line" points="{closed_line_points}" fill="none" stroke="#294766" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" />
          {marker_html}
        </svg>
        """

    @staticmethod
    def _truncate_text(text: object, max_length: int = 56) -> str:
        normalized = " ".join(str(text or "").split()).strip()
        if not normalized:
            return "暂无评分依据说明。"
        if len(normalized) <= max_length:
            return normalized
        return f"{normalized[:max_length].rstrip()}…"

    @staticmethod
    def _format_counted_question_analysis(text: object) -> str:
        normalized = " ".join(str(text or "").split()).strip()
        for marker in ("依据标签：", "核心事实：", "依据来源："):
            normalized = normalized.split(marker, 1)[0].strip()
        normalized = normalized.rstrip(" 。；;，,")

        match = re.match(r"^(L[1-5])\s+[^：:]{1,40}[：:]\s*(.+)$", normalized)
        if match:
            normalized = f"{match.group(1)}：{match.group(2).strip()}"
        return normalized.rstrip(" 。；;，,")

    def _build_report_warning_html(self, warnings: list[object]) -> str:
        del warnings
        return ""

    def _build_counted_questions_html(self, detail: dict) -> str:
        counted_questions = detail.get("counted_questions", [])
        if not isinstance(counted_questions, list) or not counted_questions:
            return ""

        rendered_items = []
        for entry in counted_questions[:3]:
            question_label = escape(
                str(
                    entry.get("question_display_label")
                    or entry.get("question_label_raw")
                    or entry.get("question_no")
                    or ""
                )
            )
            reason_text = self._format_counted_question_analysis(
                entry.get("full_reason")
                or entry.get("reason")
                or entry.get("summary")
                or ""
            )
            reason = escape(reason_text)
            rendered_items.append(
                f"""
                <li>
                  <strong>{question_label}</strong>
                  <span>{reason}</span>
                </li>
                """
            )

        return (
            '<div class="report-dimension-card__questions">'
            '<span class="report-dimension-card__label">计入题目</span>'
            f'<ul class="report-counted-question-list">{"".join(rendered_items)}</ul>'
            "</div>"
        )

        items = []
        for entry in counted_questions[:3]:
            question_label = escape(
                str(entry.get("question_label_raw") or entry.get("question_no") or "")
            )
            question_label = (
                f"第 {escape(str(page_no))} 页 / 第 {question_no} 题"
                if page_no
                else f"第 {question_no} 题"
            )
            question_no = (
                f"{escape(str(page_no))} 页 / 第 {raw_question_no}"
                if page_no
                else raw_question_no
            )
            reason = escape(self._truncate_text(entry.get("reason") or entry.get("summary"), 58))
            items.append(
                f"""
                <li>
                  <strong>第 {question_no} 题</strong>
                  <span>{reason}</span>
                </li>
                """
            )
        return (
            '<div class="report-dimension-card__questions">'
            '<span class="report-dimension-card__label">计入题目</span>'
            f'<ul class="report-counted-question-list">{"".join(items)}</ul>'
            "</div>"
        )

    def _build_dimension_cards_html(self, details_by_code: dict[str, dict]) -> str:
        cards_html: list[str] = []
        for dim_meta in DIM_META:
            detail = details_by_code.get(dim_meta["code"], {})
            if detail.get("score_status") == "not_covered":
                detail["warning"] = False
            score = self._safe_float(detail.get("score"))
            is_not_covered = detail.get("score_status") == "not_covered" or int(detail.get("level") or 0) <= 0
            score_html = f'<strong style="color:{dim_meta["color"]}">未覆盖</strong>' if is_not_covered else (
                f'<strong style="color:{dim_meta["color"]}">{self._format_score(score)}</strong><span>/ 10</span>'
            )
            meter_width = 0 if is_not_covered else max(0, min(score * 10, 100))
            evidence_label = "覆盖状态" if is_not_covered else "评分依据摘要"
            level_label = escape(str(detail.get("level_label") or "未评级"))
            evidence = escape(self._truncate_text(detail.get("evidence")))
            warning_html = (
                '<span class="report-inline-tag report-status-tag">评分提示</span>'
                if detail.get("warning")
                else ""
            )
            counted_questions_html = self._build_counted_questions_html(detail)

            cards_html.append(
                f"""
                <article class="report-dimension-card" style="border-top-color:{dim_meta['color']}">
                  <div class="report-dimension-card__header">
                    <div class="report-dimension-card__title">
                      <h3>{escape(dim_meta['name'])}</h3>
                      <p>{escape(dim_meta['code'].upper())}</p>
                    </div>
                    <div class="report-dimension-card__badges">
                      <span class="report-level-pill" style="color:{dim_meta['color']};background:{dim_meta['color']}14;border-color:{dim_meta['color']}33">
                        {level_label}
                      </span>
                      {warning_html}
                    </div>
                  </div>
                  <div class="report-dimension-card__score">
                    {score_html}
                  </div>
                  <div class="report-dimension-card__meter">
                    <div style="width:{meter_width:.0f}%;background:{dim_meta['color']}"></div>
                  </div>
                  <div class="report-dimension-card__evidence">
                    <span class="report-dimension-card__label">评分依据摘要</span>
                    <p>{evidence}</p>
                  </div>
                  {counted_questions_html}
                </article>
                """
            )

        rows_html: list[str] = []
        for index in range(0, len(cards_html), 2):
            row_cards = "".join(cards_html[index : index + 2])
            rows_html.append(f'<div class="report-dimension-row">{row_cards}</div>')

        return "".join(rows_html)

    def _build_scale_html(self, difficulty_level: int) -> str:
        blocks: list[str] = []
        for level, meta in DIFFICULTY_META.items():
            active_class = " is-active" if level == difficulty_level else ""
            dot_color = meta["color"] if level == difficulty_level else "rgba(191, 199, 207, 0.9)"
            blocks.append(
                f"""
                <div class="report-difficulty-scale__item{active_class}">
                  <div class="report-difficulty-scale__dot" style="background:{dot_color}"></div>
                  <strong>{escape(meta['label'])}</strong>
                  <span>Level {level}</span>
                </div>
                """
            )
        return "".join(blocks)

    def _generate_html(self, report_data: dict) -> str:
        dimensions = report_data.get("dimensions", {})
        details = report_data.get("dimension_details", [])
        report_warnings = report_data.get("report_warnings", [])
        details_by_code = {item.get("code", ""): item for item in details}
        position = report_data.get("difficulty_position", {})

        raw_difficulty_level = position.get("level")
        difficulty_level = int(self._safe_float(raw_difficulty_level, 0))
        difficulty_meta = DIFFICULTY_META.get(difficulty_level, DIFFICULTY_META[3])
        has_known_difficulty_level = difficulty_level in DIFFICULTY_META
        difficulty_label_value = (
            difficulty_meta["label"]
            if has_known_difficulty_level
            else position.get("label") or difficulty_meta["label"]
        )
        difficulty_label = escape(str(difficulty_label_value))
        difficulty_description_value = (
            difficulty_meta["description"]
            if has_known_difficulty_level
            else position.get("description") or difficulty_meta["description"]
        )
        difficulty_description = escape(
            str(difficulty_description_value)
        )
        target_students_value = (
            difficulty_meta["target_students"]
            if has_known_difficulty_level
            else position.get("target_students") or "未提供"
        )
        target_students = escape(str(target_students_value))
        overall_score = self._format_score(position.get("overall_score"))

        paper_title = escape(str(report_data.get("paper_title") or "未提供"))

        radar_display_values_raw = []
        radar_chart_values_raw = []
        for meta in DIM_META:
            detail = details_by_code.get(meta["code"], {})
            is_not_covered = (
                detail.get("score_status") == "not_covered"
                or int(detail.get("level") or 0) <= 0
            )
            if is_not_covered:
                radar_display_values_raw.append(None)
                radar_chart_values_raw.append(0)
            else:
                value = self._safe_float(dimensions.get(meta["field"], 0))
                radar_display_values_raw.append(value)
                radar_chart_values_raw.append(value)

        radar_has_drawable_values = any(value is not None for value in radar_display_values_raw)
        radar_empty_class = ' class="is-empty"' if not radar_has_drawable_values else ""
        radar_chart_html = (
            self._build_radar_svg_html(radar_chart_values_raw)
            if radar_has_drawable_values
            else "<span>暂无可绘制维度</span>"
        )
        warning_banner_html = self._build_report_warning_html(report_warnings)

        def radar_metric_text(meta: dict) -> str:
            detail = details_by_code.get(meta["code"], {})
            if detail.get("score_status") == "not_covered" or int(detail.get("level") or 0) <= 0:
                return "未覆盖"
            return f"{self._format_score(dimensions.get(meta['field'], 0), 0)} / 100"

        radar_metrics_html = "".join(
            f"""
            <div class="report-radar-metric">
              <strong>{escape(meta['name'])}</strong>
              <span>{radar_metric_text(meta)}</span>
            </div>
            """
            for meta in DIM_META
        )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>六维评价分析报告</title>
  <style>
    @page {{
      size: A4;
      margin: 12mm 10mm 12mm;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #f4f6f8;
      color: #1f2933;
      font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    .report-shell {{ padding: 8px 6px 0; }}
    .report-header, .report-section, .report-difficulty-card, .report-radar-card {{
      background: #fffdfb;
      border: 1px solid #cfd6dc;
      border-radius: 14px;
    }}
    .report-header {{ padding: 18px 20px; margin-bottom: 12px; }}
    .report-header__top {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: flex-start;
      padding-bottom: 14px;
      border-bottom: 1px solid #d8dde2;
    }}
    .report-eyebrow, .report-section__eyebrow, .report-card-eyebrow {{
      display: inline-block;
      margin-bottom: 6px;
      color: #294766;
      font-size: 10px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }}
    h1, h2, h3 {{
      font-family: "Noto Serif SC", "Source Han Serif SC", "Songti SC", "STSong", serif;
      font-weight: 700;
    }}
    h1 {{ font-size: 26px; line-height: 1.18; }}
    .report-header__paper {{
      margin-top: 8px;
      max-width: 520px;
      color: #5d6a72;
      font-size: 14px;
      line-height: 1.55;
    }}
    .report-overview-strip, .report-dimension-list, .report-radar-metrics {{
      display: grid;
      gap: 10px;
    }}
    .report-overview-strip {{ grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 12px; }}
    .report-overview-item, .report-radar-metric,
    .report-target-block, .report-score-panel {{
      background: #ffffff;
      border: 1px solid #d5dbe0;
      border-radius: 12px;
    }}
    .report-overview-item {{ padding: 12px 14px; min-height: 68px; }}
    .report-overview-item span, .report-score-panel__label, .report-card-note,
    .report-target-block span, .report-dimension-card__label {{
      display: block;
      color: #8a9399;
      font-size: 10px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }}
    .report-overview-item strong {{
      display: block;
      margin-top: 6px;
      color: #1f2933;
      font-size: 15px;
      line-height: 1.45;
      font-weight: 600;
    }}
    .report-overview-item strong {{ font-size: 17px; }}
    .report-core-grid {{
      display: block;
      margin-bottom: 12px;
    }}
    .report-core-grid > article + article {{ margin-top: 12px; }}
    .report-difficulty-card, .report-radar-card {{
      padding: 18px;
      break-inside: avoid;
      page-break-inside: avoid;
    }}
    .report-card-heading {{
      margin-bottom: 14px;
      break-after: avoid-page;
      page-break-after: avoid;
    }}
    .report-card-heading h3 {{ font-size: 22px; line-height: 1.18; }}
    .report-card-heading p {{ margin-top: 8px; color: #5d6a72; font-size: 12px; line-height: 1.65; }}
    .report-difficulty-card__top {{
      display: grid;
      grid-template-columns: 148px 1fr;
      gap: 14px;
      margin-bottom: 14px;
    }}
    .report-score-panel {{ padding: 14px; background: {difficulty_meta['surface']}; border-color: {difficulty_meta['border']}; break-inside: avoid; page-break-inside: avoid; }}
    .report-score-panel__value {{ display: flex; align-items: baseline; gap: 8px; margin-top: 10px; }}
    .report-score-panel__value strong, .report-dimension-card__score strong {{
      font-family: "Noto Serif SC", "Source Han Serif SC", "Songti SC", "STSong", serif;
      line-height: 1;
      font-weight: 700;
    }}
    .report-score-panel__value strong {{ font-size: 34px; color: {difficulty_meta['color']}; }}
    .report-score-panel__value small, .report-dimension-card__score span {{ color: #5d6a72; font-size: 13px; }}
    .report-level-pill, .report-inline-tag {{
      display: inline-flex;
      align-items: center;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid transparent;
      font-size: 10px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      white-space: nowrap;
    }}
    .report-inline-tag {{ color: #6d7277; background: #f3f4f5; border-color: #d8dde2; }}
    .report-target-block {{ margin-top: 10px; padding: 12px 14px; break-inside: avoid; page-break-inside: avoid; }}
    .report-target-block p {{ margin-top: 8px; color: #1f2933; font-size: 12px; line-height: 1.65; }}
    .report-difficulty-scale {{
      display: flex;
      gap: 8px;
      padding: 10px 12px;
      margin-bottom: 12px;
      background: #ffffff;
      border: 1px solid #d5dbe0;
      border-radius: 12px;
      break-inside: avoid;
      page-break-inside: avoid;
    }}
    .report-difficulty-scale__item {{ flex: 1; min-width: 0; text-align: center; }}
    .report-difficulty-scale__dot {{ width: 10px; height: 10px; margin: 0 auto 8px; border-radius: 999px; }}
    .report-difficulty-scale__item strong {{ display: block; color: #5d6a72; font-size: 11px; font-weight: 600; }}
    .report-difficulty-scale__item span, .report-radar-metric span {{ color: #8a9399; font-size: 10px; }}
    .report-difficulty-scale__item.is-active strong {{ color: #1f2933; }}
    .report-dimension-card__meter {{
      overflow: hidden;
      background: #dde3e7;
      border-radius: 999px;
    }}
    .report-dimension-card__meter div {{ height: 100%; border-radius: 999px; }}
    .report-radar-card__body {{
      display: grid;
      gap: 14px;
    }}
    #radar-chart {{
      width: 100%;
      height: 220px;
      overflow: visible;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
      break-inside: avoid;
      page-break-inside: avoid;
    }}
    .report-radar-svg {{
      display: block;
      width: 100%;
      height: 100%;
      overflow: visible;
    }}
    .report-radar-svg text {{
      font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif;
    }}
    #radar-chart.is-empty {{
      display: flex;
      align-items: center;
      justify-content: center;
      color: #8a9399;
      font-size: 12px;
      background: #f8fafc;
      border: 1px dashed #cfd6dc;
      border-radius: 12px;
    }}
    .report-radar-metrics {{ grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }}
    .report-radar-metric {{ padding: 10px 12px; break-inside: avoid; page-break-inside: avoid; }}
    .report-radar-metric strong {{
      display: block;
      margin-bottom: 4px;
      color: #1f2933;
      font-size: 12px;
      line-height: 1.35;
      font-weight: 600;
    }}
    .report-section {{
      padding: 18px 20px;
      margin-bottom: 12px;
    }}
    .report-section__header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 14px;
      padding-bottom: 10px;
      border-bottom: 1px solid #d8dde2;
      break-after: avoid-page;
      page-break-after: avoid;
    }}
    .report-section__header h2 {{ font-size: 21px; line-height: 1.2; }}
    .report-section__header p {{ max-width: 280px; color: #5d6a72; font-size: 12px; line-height: 1.6; }}
    .report-dimension-list {{ gap: 12px; }}
    .report-dimension-row {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      break-inside: avoid;
      page-break-inside: avoid;
    }}
    .report-dimension-card {{
      padding: 14px 14px 16px;
      border-top-width: 4px;
      break-inside: avoid;
      page-break-inside: avoid;
    }}
    .report-dimension-card__header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 10px;
    }}
    .report-dimension-card__title h3 {{ font-size: 15px; line-height: 1.35; font-weight: 600; }}
    .report-dimension-card__title p {{
      margin-top: 6px;
      color: #8a9399;
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .report-dimension-card__score {{ display: flex; align-items: baseline; gap: 8px; margin: 12px 0 10px; }}
    .report-dimension-card__score strong {{ font-size: 30px; }}
    .report-dimension-card__meter {{ height: 6px; margin-bottom: 12px; }}
    .report-dimension-card__evidence {{ padding-top: 10px; border-top: 1px solid #dfe4e8; }}
    .report-dimension-card__evidence p {{ margin-top: 6px; color: #5d6a72; font-size: 12px; line-height: 1.6; }}
    .report-dimension-card__questions {{ margin-top: 12px; padding-top: 10px; border-top: 1px dashed #dfe4e8; }}
    .report-counted-question-list {{ display: grid; gap: 8px; list-style: none; margin-top: 8px; }}
    .report-counted-question-list li {{
      padding: 9px 10px;
      background: #ffffff;
      border: 1px solid #d7dde2;
      border-radius: 10px;
      break-inside: avoid;
      page-break-inside: avoid;
    }}
    .report-counted-question-list strong {{
      display: block;
      color: #1f2933;
      font-size: 11px;
      line-height: 1.4;
      font-weight: 600;
    }}
    .report-counted-question-list span {{
      display: block;
      margin-top: 4px;
      color: #5d6a72;
      font-size: 11px;
      line-height: 1.55;
    }}
    .report-footer {{ padding-top: 0; margin-top: 8px; text-align: center; color: #8a9399; font-size: 10px; }}
    @media print {{
      .report-shell {{ padding: 0; }}
      .report-section,
      .report-header,
      .report-difficulty-card,
      .report-radar-card {{
        box-shadow: none;
      }}
      .report-radar-card,
      #radar-chart {{
        break-inside: avoid;
        page-break-inside: avoid;
      }}
      #radar-chart {{
        min-height: 220px;
      }}
    }}
  </style>
</head>
<body>
  <div class="report-shell">
    {warning_banner_html}
    <header class="report-header">
      <div class="report-header__top">
        <div>
          <span class="report-eyebrow">专业教研版报告</span>
          <h1>六维评价分析报告</h1>
          <p class="report-header__paper">{paper_title}</p>
        </div>
      </div>
      <div class="report-overview-strip">
        <div class="report-overview-item"><span>整卷等级</span><strong>{difficulty_label}</strong></div>
        <div class="report-overview-item"><span>综合分</span><strong>{overall_score} / 10</strong></div>
        <div class="report-overview-item"><span>目标学生</span><strong>{target_students}</strong></div>
      </div>
    </header>

    <main>
      <section class="report-core-grid">
        <article class="report-difficulty-card">
          <div class="report-card-heading">
            <span class="report-card-eyebrow">核心结论</span>
            <h3>难度定位</h3>
            <p>{difficulty_description}</p>
          </div>

          <div class="report-difficulty-card__top">
            <div class="report-score-panel">
              <span class="report-score-panel__label">综合分</span>
              <div class="report-score-panel__value">
                <strong>{overall_score}</strong>
                <small>/ 10</small>
              </div>
              <span class="report-level-pill" style="align-self:flex-start;color:{difficulty_meta['color']};background:{difficulty_meta['color']}14;border-color:{difficulty_meta['color']}33">{difficulty_label}</span>
            </div>

            <div>
              <span class="report-card-note">结论摘要</span>
              <p style="margin-top:10px;color:#5d6a72;font-size:13px;line-height:1.8">{difficulty_description}</p>
              <div class="report-target-block">
                <span>目标学生</span>
                <p>{target_students}</p>
              </div>
            </div>
          </div>

          <div class="report-difficulty-scale">{self._build_scale_html(difficulty_level)}</div>
        </article>

        <article class="report-radar-card">
          <div class="report-card-heading">
            <span class="report-card-eyebrow">六维结构</span>
            <h3>六维分布</h3>
            <p>从整卷视角查看六个评价维度的相对强弱，作为难度定位与能力结构判断的辅助依据。</p>
          </div>

          <div class="report-radar-card__body">
            <div id="radar-chart"{radar_empty_class}>{radar_chart_html}</div>
            <div class="report-radar-metrics">{radar_metrics_html}</div>
          </div>
        </article>
      </section>

      <section class="report-section">
        <div class="report-section__header">
          <div>
            <span class="report-section__eyebrow">六维评分</span>
            <h2>六维评价明细</h2>
          </div>
          <p>统一呈现维度名称、得分、等级与评分依据摘要，减少冗余噪音，突出可读性。</p>
        </div>
        <div class="report-dimension-list">{self._build_dimension_cards_html(details_by_code)}</div>
      </section>

    </main>

    <footer class="report-footer">本报告仅调整呈现方式，不涉及六维算法口径与后端接口变更。</footer>
  </div>

</body>
</html>"""
