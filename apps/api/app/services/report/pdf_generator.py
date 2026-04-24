"""
PDF export service.

Render the report with Playwright and return either raw PDF bytes or an
optionally persisted file path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

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

DIFFICULTY_META = {
    1: {
        "label": "基础卷",
        "color": "#3f7a57",
        "surface": "#f1f7f2",
        "border": "#c9ddce",
        "description": "整体更强调基础概念与常规运算，适合夯实基本能力。",
    },
    2: {
        "label": "常规卷",
        "color": "#356a7c",
        "surface": "#eef5f8",
        "border": "#c7d9e0",
        "description": "覆盖课程常规要求，兼顾熟练度、理解度与基础应用。",
    },
    3: {
        "label": "提升卷",
        "color": "#8a6b2d",
        "surface": "#fbf6ea",
        "border": "#e6d9b4",
        "description": "强调综合运用能力，适合从熟练解题向稳定提分过渡。",
    },
    4: {
        "label": "拔高卷",
        "color": "#8b5a3c",
        "surface": "#fbf2ee",
        "border": "#e6cfc1",
        "description": "试题更重视方法迁移、思维跨度与综合判断能力。",
    },
    5: {
        "label": "选拔卷",
        "color": "#6b557f",
        "surface": "#f4f0f8",
        "border": "#d9d0e6",
        "description": "整体强度较高，适合区分高水平学生的思维品质与稳定性。",
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

                    self._wait_for_charts_sync(page, report_id)
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

    def _wait_for_charts_sync(self, page: Page, report_id: str) -> None:
        """Wait for the embedded radar chart to finish rendering."""
        try:
            page.wait_for_function("window.__chartReady === true", timeout=5000)
        except PlaywrightTimeoutError:
            logger.warning(
                "PDF export chart readiness timed out, falling back to fixed delay report=%s",
                report_id,
            )
            page.wait_for_timeout(1500)
        except Exception as exc:
            raise RuntimeError(self._build_render_error_message("wait_chart", exc)) from exc

    @staticmethod
    def _build_render_error_message(stage: str, exc: Exception) -> str:
        stage_label = {
            "launch_browser": "Chromium 启动",
            "render_html": "HTML 渲染",
            "wait_chart": "图表等待",
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
    def _truncate_text(text: object, max_length: int = 56) -> str:
        normalized = " ".join(str(text or "").split()).strip()
        if not normalized:
            return "暂无评分依据说明。"
        if len(normalized) <= max_length:
            return normalized
        return f"{normalized[:max_length].rstrip()}…"

    def _build_summary_html(self, summary: object) -> str:
        paragraphs = [item.strip() for item in str(summary or "").splitlines() if item.strip()]
        if not paragraphs:
            paragraphs = ["暂无总体评价。"]
        return "".join(f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs)

    def _build_advice_note(self, details: list[dict]) -> str:
        warning_count = sum(1 for item in details if item.get("warning"))
        if warning_count > 0:
            return (
                f"当前六维明细中有 {warning_count} 个维度带有复核提示，"
                "建议结合题号、题目摘要与计入理由做二次核对后再制定训练重点。"
            )
        return "建议先依据整卷等级与综合分确定训练强度，再按六维得分和计入题号安排分层巩固与专项提升。"

    def _build_report_warning_html(self, warnings: list[object]) -> str:
        normalized = [str(item).strip() for item in warnings if str(item).strip()]
        if not normalized:
            return ""

        items = "".join(f"<li>{escape(item)}</li>" for item in normalized)
        return (
            '<section class="report-warning-banner">'
            '<div class="report-warning-banner__header"><strong>OCR 识别提示</strong></div>'
            f'<ul class="report-warning-banner__list">{items}</ul>'
            "</section>"
        )

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
            reason = escape(
                self._truncate_text(entry.get("reason") or entry.get("summary"), 58)
            )
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
            score = self._safe_float(detail.get("score"))
            level_label = escape(str(detail.get("level_label") or "未评级"))
            evidence = escape(self._truncate_text(detail.get("evidence")))
            warning_html = (
                '<span class="report-inline-tag report-status-tag">复核提示</span>'
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
                    <strong style="color:{dim_meta['color']}">{self._format_score(score)}</strong>
                    <span>/ 10</span>
                  </div>
                  <div class="report-dimension-card__meter">
                    <div style="width:{max(0, min(score * 10, 100)):.0f}%;background:{dim_meta['color']}"></div>
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

    def _build_distribution_html(self, position: dict) -> str:
        distribution_by_code = {
            item.get("code", ""): item for item in position.get("dimension_distribution", [])
        }

        rows: list[str] = []
        for dim_meta in DIM_META:
            distribution = distribution_by_code.get(dim_meta["code"], {})
            percentage = int(self._safe_float(distribution.get("percentage")))
            color = escape(str(distribution.get("color") or dim_meta["color"]))
            rows.append(
                f"""
                <div class="report-difficulty-row">
                  <span class="report-difficulty-row__label">{escape(dim_meta['name'])}</span>
                  <div class="report-difficulty-row__bar">
                    <div class="report-difficulty-row__fill" style="width:{max(0, min(percentage, 100))}%;background:{color}"></div>
                  </div>
                  <span class="report-difficulty-row__value">{percentage}%</span>
                </div>
                """
            )
        return "".join(rows)

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

    def _build_recommendations_html(self, recommendations: list) -> str:
        if not recommendations:
            return """
            <li class="report-advice-item">
              <span class="report-advice-item__index">01</span>
              <p>暂无学习建议。</p>
            </li>
            """

        return "".join(
            f"""
            <li class="report-advice-item">
              <span class="report-advice-item__index">{str(index + 1).zfill(2)}</span>
              <p>{escape(str(item))}</p>
            </li>
            """
            for index, item in enumerate(recommendations)
        )

    def _generate_html(self, report_data: dict) -> str:
        dimensions = report_data.get("dimensions", {})
        details = report_data.get("dimension_details", [])
        report_warnings = report_data.get("report_warnings", [])
        details_by_code = {item.get("code", ""): item for item in details}
        position = report_data.get("difficulty_position", {})

        difficulty_level = int(self._safe_float(position.get("level"), 3))
        difficulty_meta = DIFFICULTY_META.get(difficulty_level, DIFFICULTY_META[3])
        difficulty_label = escape(str(position.get("label") or difficulty_meta["label"]))
        difficulty_description = escape(
            str(position.get("description") or difficulty_meta["description"])
        )
        target_students = escape(str(position.get("target_students") or "未提供"))
        overall_score = self._format_score(position.get("overall_score"))

        paper_title = escape(str(report_data.get("paper_title") or "未提供"))

        radar_values = json.dumps(
            [self._safe_float(dimensions.get(meta["field"], 0)) for meta in DIM_META],
            ensure_ascii=False,
        )
        radar_names = json.dumps([meta["name"] for meta in DIM_META], ensure_ascii=False)
        radar_indicators = json.dumps(
            [{"name": meta["chart_name"], "max": 100, "color": "#43525d"} for meta in DIM_META],
            ensure_ascii=False,
        )
        warning_banner_html = self._build_report_warning_html(report_warnings)
        radar_metrics_html = "".join(
            f"""
            <div class="report-radar-metric">
              <strong>{escape(meta['name'])}</strong>
              <span>{self._format_score(dimensions.get(meta['field'], 0), 0)} / 100</span>
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
  <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
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
    .report-warning-banner {{
      margin-bottom: 12px;
      padding: 12px 14px;
      background: linear-gradient(180deg, #fff7e4, #fffbf2);
      border: 1px solid #e0c27d;
      border-radius: 12px;
    }}
    .report-warning-banner__header {{
      color: #8f5d12;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
    }}
    .report-warning-banner__list {{
      margin: 8px 0 0 18px;
      color: #7a5a20;
      font-size: 11px;
      line-height: 1.6;
    }}
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
    .report-overview-item, .report-radar-metric, .report-advice-item,
    .report-advice-note, .report-prose-block, .report-target-block, .report-score-panel {{
      background: #ffffff;
      border: 1px solid #d5dbe0;
      border-radius: 12px;
    }}
    .report-overview-item {{ padding: 12px 14px; min-height: 68px; }}
    .report-overview-item span, .report-score-panel__label, .report-card-note,
    .report-target-block span, .report-prose-block__note, .report-dimension-card__label, .report-advice-note strong {{
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
    .report-difficulty-scale__item span, .report-difficulty-row__value, .report-radar-metric span {{ color: #8a9399; font-size: 10px; }}
    .report-difficulty-scale__item.is-active strong {{ color: #1f2933; }}
    .report-distribution-list {{ display: grid; gap: 8px; }}
    .report-difficulty-row {{
      display: grid;
      grid-template-columns: 140px 1fr 36px;
      gap: 8px;
      align-items: center;
    }}
    .report-difficulty-row__label {{ color: #5d6a72; font-size: 12px; line-height: 1.4; }}
    .report-difficulty-row__bar, .report-dimension-card__meter {{
      overflow: hidden;
      background: #dde3e7;
      border-radius: 999px;
    }}
    .report-difficulty-row__bar {{ height: 8px; }}
    .report-difficulty-row__fill, .report-dimension-card__meter div {{ height: 100%; border-radius: 999px; }}
    .report-radar-card__body {{
      display: grid;
      gap: 14px;
    }}
    #radar-chart {{ width: 100%; height: 220px; }}
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
    .report-prose-block {{ padding: 18px 20px; }}
    .report-prose-block p {{ color: #1f2933; font-size: 14px; line-height: 1.85; orphans: 3; widows: 3; }}
    .report-prose-block p + p {{ margin-top: 12px; }}
    .report-advice-note {{ padding: 12px 14px; break-inside: avoid; page-break-inside: avoid; }}
    .report-advice-note p {{ margin-top: 8px; color: #5d6a72; font-size: 12px; line-height: 1.65; }}
    .report-advice-list {{ display: grid; gap: 10px; list-style: none; margin-top: 12px; }}
    .report-advice-item {{
      display: grid;
      grid-template-columns: 52px 1fr;
      gap: 12px;
      padding: 12px 14px;
      break-inside: avoid;
      page-break-inside: avoid;
    }}
    .report-advice-item__index {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 38px;
      height: 38px;
      border-radius: 999px;
      border: 1px solid #d5dbe0;
      background: #ffffff;
      color: #8a9399;
      font-family: "Noto Serif SC", "Source Han Serif SC", "Songti SC", "STSong", serif;
      font-size: 16px;
      font-weight: 700;
    }}
    .report-advice-item p {{ color: #1f2933; font-size: 13px; line-height: 1.7; }}
    .report-footer {{ padding-top: 0; margin-top: 8px; text-align: center; color: #8a9399; font-size: 10px; }}
    @media print {{
      .report-shell {{ padding: 0; }}
      .report-section,
      .report-header,
      .report-difficulty-card,
      .report-radar-card {{
        box-shadow: none;
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
          <div class="report-distribution-list">{self._build_distribution_html(position)}</div>
        </article>

        <article class="report-radar-card">
          <div class="report-card-heading">
            <span class="report-card-eyebrow">六维结构</span>
            <h3>六维分布</h3>
            <p>从整卷视角查看六个评价维度的相对强弱，作为难度定位与后续训练建议的辅助依据。</p>
          </div>

          <div class="report-radar-card__body">
            <div id="radar-chart"></div>
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

      <section class="report-section">
        <div class="report-section__header">
          <div>
            <span class="report-section__eyebrow">总体评价</span>
            <h2>整卷结论</h2>
          </div>
          <p>以正文报告块呈现总体判断，弱化普通卡片感，增强正式报告语境下的阅读节奏。</p>
        </div>
        <article class="report-prose-block">
          <span class="report-prose-block__note">报告正文</span>
          {self._build_summary_html(report_data.get("overall_summary"))}
        </article>
      </section>

      <section class="report-section">
        <div class="report-section__header">
          <div>
            <span class="report-section__eyebrow">学习建议</span>
            <h2>后续训练建议</h2>
          </div>
          <p>采用编号建议列表，保留重点提示，但整体视觉层级低于核心结论与总体评价。</p>
        </div>

        <div class="report-advice-note">
          <strong>重点提示</strong>
          <p>{escape(self._build_advice_note(details))}</p>
        </div>

        <ol class="report-advice-list">{self._build_recommendations_html(report_data.get("recommendations", []))}</ol>
      </section>
    </main>

    <footer class="report-footer">本报告仅调整呈现方式，不涉及六维算法口径与后端接口变更。</footer>
  </div>

  <script>
    (function () {{
      var chart = echarts.init(document.getElementById('radar-chart'), null, {{ renderer: 'svg' }});
      chart.setOption({{
        tooltip: {{
          trigger: 'item',
          backgroundColor: 'rgba(255, 255, 255, 0.96)',
          borderColor: '#cfd6dc',
          textStyle: {{ color: '#1f2933' }},
          formatter: function () {{
            var rows = [];
            var names = {radar_names};
            var values = {radar_values};
            for (var i = 0; i < names.length; i += 1) {{
              rows.push(names[i] + ': ' + values[i].toFixed(0) + ' / 100');
            }}
            return rows.join('<br/>');
          }}
        }},
        radar: {{
          indicator: {radar_indicators},
          shape: 'polygon',
          splitNumber: 4,
          radius: '67%',
          center: ['50%', '48%'],
          axisName: {{ fontSize: 12, fontWeight: 600, padding: [0, 0, 8, 0] }},
          splitLine: {{ lineStyle: {{ color: '#d6dde3' }} }},
          splitArea: {{ show: true, areaStyle: {{ color: ['rgba(238, 242, 246, 0.72)', 'rgba(248, 250, 252, 0.28)'] }} }},
          axisLine: {{ lineStyle: {{ color: '#d6dde3' }} }}
        }},
        series: [{{
          name: '六维评价',
          type: 'radar',
          data: [{{
            value: {radar_values},
            name: '当前试卷',
            symbol: 'circle',
            symbolSize: 7,
            lineStyle: {{ width: 2.5, color: '#294766' }},
            areaStyle: {{ color: 'rgba(41, 71, 102, 0.16)' }},
            itemStyle: {{ color: '#294766', borderColor: '#ffffff', borderWidth: 2 }}
          }}]
        }}]
      }});
      window.__chartReady = true;
    }})();
  </script>
</body>
</html>"""
