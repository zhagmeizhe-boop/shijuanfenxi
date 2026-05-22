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
        "name": "计算难度",
        "chart_name": "计算\n难度",
        "color": "#295d8a",
    },
    {
        "code": "dim2",
        "field": "concept",
        "name": "几何难度",
        "chart_name": "几何\n难度",
        "color": "#3d7a85",
    },
    {
        "code": "dim3",
        "field": "logic",
        "name": "读题难度",
        "chart_name": "读题\n难度",
        "color": "#6f7d48",
    },
    {
        "code": "dim4",
        "field": "spatial",
        "name": "解题方法难度",
        "chart_name": "解题方法\n难度",
        "color": "#8a6842",
    },
    {
        "code": "dim5",
        "field": "application",
        "name": "知识门槛难度",
        "chart_name": "知识门槛\n难度",
        "color": "#8b5754",
    },
    {
        "code": "dim6",
        "field": "innovation",
        "name": "解题链路难度",
        "chart_name": "解题链路\n难度",
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
        "position_summary": "课内基础巩固型试卷，主要看孩子基础概念和常规计算是否过关。",
        "target_students": "适合基础薄弱、需要巩固基本概念的学生。",
    },
    2: {
        "label": "提升卷",
        "color": "#356a7c",
        "surface": "#eef5f8",
        "border": "#c7d9e0",
        "description": "注重知识覆盖、基本应用和稳定解题能力，适合从课内掌握走向稳步提升。",
        "position_summary": "课内核心提升型试卷，主要看孩子能不能把学过的知识稳定用出来。",
        "target_students": "适合基础一般、希望从课内掌握走向稳定提升的学生。",
    },
    3: {
        "label": "拔高卷",
        "color": "#8a6b2d",
        "surface": "#fbf6ea",
        "border": "#e6d9b4",
        "description": "强调综合运用、方法迁移和拔高训练，适合基础较好的学生。",
        "position_summary": "校内期中期末考试难度试卷，题目有一定变化，适合检验孩子能否稳定拿到中高分。",
        "target_students": "适合基础较好、需要强化综合运用和拔高训练的学生。",
    },
    4: {
        "label": "选拔卷",
        "color": "#8b5a3c",
        "surface": "#fbf2ee",
        "border": "#e6cfc1",
        "description": "面向选拔区分场景，重视复杂问题解决、策略迁移与稳定性。",
        "position_summary": "小升初分班考难度试卷，题目更绕、步骤更多，用来拉开学生差距。",
        "target_students": "适合基础扎实、需要面向选拔场景提升综合稳定性的学生。",
    },
    5: {
        "label": "竞赛卷",
        "color": "#6b557f",
        "surface": "#f4f0f8",
        "border": "#d9d0e6",
        "description": "整体强度高，突出竞赛型思维、跨模块综合和高难度解题技巧。",
        "position_summary": "奥数杯赛竞赛难度试卷，难度很高，适合挑战高难题和竞赛题。",
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

    @classmethod
    def _build_dim1_score_overview(cls, score: object) -> str:
        try:
            score_value = float(score or 0.0)
        except (TypeError, ValueError):
            score_value = 0.0

        if score_value >= 9:
            explanation = "说明本卷计算要求很高，包含较强的多步、结构化或拓展计算，对综合计算能力要求突出。"
        elif score_value >= 8:
            explanation = "说明本卷计算难度较高，计算题和应用题中的核心计算都会拉开学生差距。"
        elif score_value >= 6:
            explanation = "说明本卷有一定计算难度，除准确率外，也考查多步运算和常见转化。"
        elif score_value >= 4:
            explanation = "说明本卷计算难度整体偏常规，重点考查校内计算的熟练度和稳定性。"
        else:
            explanation = "说明本卷计算要求以基础运算为主，主要看基本规则掌握和计算准确率。"
        return f"计算难度，综合得分 {score_value:.1f} 分，{explanation}"

    @classmethod
    def _build_dim2_score_overview(cls, score: object) -> str:
        try:
            score_value = float(score or 0.0)
        except (TypeError, ValueError):
            score_value = 0.0

        if score_value >= 9:
            explanation = "说明本卷几何与空间要求很高，包含高强度空间重构、多视图或高阶几何模型。"
        elif score_value >= 8:
            explanation = "说明本卷几何难度较高，复合图形、隐含关系或空间转换会明显拉开差距。"
        elif score_value >= 6:
            explanation = "说明本卷有一定几何与空间难度，除基本公式外，也考查图形关系整理和模型识别。"
        elif score_value >= 4:
            explanation = "说明本卷以常规图形关系为主，重点考查读图准确性和单步空间转化。"
        else:
            explanation = "说明本卷主要覆盖基础识图和直接几何公式，重点看图形概念和基本关系是否掌握。"
        return f"几何难度，综合得分 {score_value:.1f} 分，{explanation}"

    @classmethod
    def _build_dim3_score_overview(cls, score: object) -> str:
        try:
            score_value = float(score or 0.0)
        except (TypeError, ValueError):
            score_value = 0.0

        if score_value >= 9:
            explanation = "说明这张试卷在学生读题理解题意上设置了较高难度，不少题目需要完整读懂多条规则、多阶段过程或复杂图文关系。"
        elif score_value >= 8:
            explanation = "说明这张试卷在学生读题理解题意上设置了明显难度，部分题目的场景相对复杂，学生需要先理清对象、阶段、规则或图文关系。"
        elif score_value >= 6:
            explanation = "说明这张试卷在学生读题理解题意上设置了一定难度，部分题目需要先读懂关键问法、比较标准或简单规则。"
        elif score_value >= 4:
            explanation = "说明这张试卷在学生读题和理解题意上有常规要求，部分题目需要分清对象、顺序或图文对应关系。"
        else:
            explanation = "说明这张试卷在学生读题和理解题意上的要求比较基础，大多数题目读完后能较快明白题目在说什么。"
        return f"读题难度，综合得分 {score_value:.1f} 分，{explanation}"

    @classmethod
    def _build_dim4_score_overview(cls, score: object) -> str:
        try:
            score_value = float(score or 0.0)
        except (TypeError, ValueError):
            score_value = 0.0

        if score_value >= 9:
            explanation = "说明本卷在解题思路上难度很高。孩子做核心题时，通常不能只按常规步骤推进，需要先找到关键突破口，再持续检查每一步是否和题目条件一致。"
        elif score_value >= 8:
            explanation = "说明本卷在解题思路上有较明显难度。孩子做这类题时，往往需要先把条件之间的关系理清楚，再选择合适的切入方式逐步推进。"
        elif score_value >= 6:
            explanation = "说明本卷在解题思路上有一定难度。部分题目不是读完就能直接下手，需要孩子先整理已知条件和目标之间的关系，再按较清晰的步骤推进。"
        elif score_value >= 4:
            explanation = "说明本卷在解题思路上的要求整体偏常规。多数题目读懂后可以沿常见思路完成，少量题需要先做简单整理再下手。"
        else:
            explanation = "说明本卷在解题思路上的要求比较基础。多数题目读懂题意后，可以直接找到主要关系并完成解答。"
        return f"解题方法难度，综合得分 {score_value:.1f} 分，{explanation}"

    @classmethod
    def _build_dim5_score_overview(cls, score: object) -> str:
        try:
            score_value = float(score or 0.0)
        except (TypeError, ValueError):
            score_value = 0.0

        if score_value >= 9:
            explanation = "说明本卷知识门槛很高，核心题多接近六年级奥数较难题、小升初压轴题或七年级核心前置知识。"
        elif score_value >= 8:
            explanation = "说明本卷知识门槛较高，较多题目需要五六年级奥数典型方法或七年级基础前置知识。"
        elif score_value >= 6:
            explanation = "说明本卷有一定知识拓展，除校内核心知识外，还覆盖校内综合或三四年级奥数入门模型。"
        elif score_value >= 4:
            explanation = "说明本卷主要落在四至六年级校内核心知识，常规两三步应用、比例、图形公式等是主要要求。"
        else:
            explanation = "说明本卷以一至三年级校内基础知识为主，主要考查基本概念、基础计算和直接应用。"
        return f"知识门槛难度，综合得分 {score_value:.1f} 分，{explanation}"

    @classmethod
    def _build_dim6_score_overview(cls, score: object) -> str:
        try:
            score_value = float(score or 0.0)
        except (TypeError, ValueError):
            score_value = 0.0

        if score_value >= 9:
            explanation = "这张试卷有少量解题链条很长的压轴题，通常要连续推进 5 步以上，并检查多个条件。"
        elif score_value >= 8:
            explanation = "这张试卷不少题解题链条较长，通常要连续推进 3-4 步，并穿插分类、倒推或回查。"
        elif score_value >= 6:
            explanation = "这张试卷部分题解题链条有一定长度，通常要把前后条件接起来推进 2-4 步。"
        elif score_value >= 4:
            explanation = "这张试卷整体解题链条偏短，少量题需要 1-2 步衔接。"
        else:
            explanation = "这张试卷多数题解题链条很短，通常读懂条件后一步判断即可。"

        return f"解题链路难度，综合得分 {score_value:.1f} 分，{explanation}"

    DIM1_DIFFICULTY_LABELS = {
        "L1": "简单（2.0）",
        "L2": "较易（4.0）",
        "L3": "中等（6.0）",
        "L4": "较难（8.0）",
        "L5": "困难（9.5）",
    }

    @classmethod
    def _level_code_from_score(cls, score: object) -> str:
        try:
            score_value = float(score or 0)
        except (TypeError, ValueError):
            score_value = 0.0
        if score_value >= 9:
            return "L5"
        if score_value >= 8:
            return "L4"
        if score_value >= 6:
            return "L3"
        if score_value >= 4:
            return "L2"
        return "L1"

    @classmethod
    def _counted_question_difficulty_label(
        cls,
        entry: dict | None = None,
        score: object = None,
        level_code: str = "",
    ) -> str:
        entry = entry or {}
        explicit = str(entry.get("difficulty_label") or "").strip()
        if explicit:
            return explicit
        normalized_level = str(entry.get("level_code") or level_code or "").strip().upper()
        if normalized_level in cls.DIM1_DIFFICULTY_LABELS:
            return cls.DIM1_DIFFICULTY_LABELS[normalized_level]
        inferred_level = cls._level_code_from_score(score if score is not None else entry.get("score"))
        return cls.DIM1_DIFFICULTY_LABELS[inferred_level]

    @classmethod
    def _breakdown_number(cls, breakdown: object, key: str) -> float | None:
        if not isinstance(breakdown, dict):
            return None
        value = breakdown.get(key)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric

    @classmethod
    def _nested_breakdown_number(cls, breakdown: object, group_key: str, value_key: str) -> float | None:
        if not isinstance(breakdown, dict):
            return None
        group = breakdown.get(group_key)
        return cls._breakdown_number(group, value_key)

    @classmethod
    def _format_dimension_evidence(cls, detail: dict) -> str:
        if detail.get("code") == "dim1":
            if detail.get("score_status") == "not_covered" or int(detail.get("level") or 0) <= 0:
                return str(detail.get("evidence") or "")
            return cls._build_dim1_score_overview(detail.get("score"))
        if detail.get("code") == "dim2":
            if detail.get("score_status") == "not_covered" or int(detail.get("level") or 0) <= 0:
                return str(detail.get("evidence") or "")
            return cls._build_dim2_score_overview(detail.get("score"))
        if detail.get("code") == "dim3":
            if detail.get("score_status") == "not_covered" or int(detail.get("level") or 0) <= 0:
                return str(detail.get("evidence") or "")
            return cls._build_dim3_score_overview(detail.get("score"))
        if detail.get("code") == "dim4":
            if detail.get("score_status") == "not_covered" or int(detail.get("level") or 0) <= 0:
                return str(detail.get("evidence") or "")
            return cls._build_dim4_score_overview(detail.get("score"))
        if detail.get("code") == "dim5":
            if detail.get("score_status") == "not_covered" or int(detail.get("level") or 0) <= 0:
                return str(detail.get("evidence") or "")
            return cls._build_dim5_score_overview(detail.get("score"))
        if detail.get("code") == "dim6":
            if detail.get("score_status") == "not_covered" or int(detail.get("level") or 0) <= 0:
                return str(detail.get("evidence") or "")
            return cls._build_dim6_score_overview(detail.get("score"))

        return str(detail.get("evidence") or "")

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

    @classmethod
    def _format_counted_question_analysis(
        cls,
        text: object,
        entry: dict | None = None,
    ) -> str:
        normalized = " ".join(str(text or "").split()).strip()
        for marker in ("依据标签：", "核心事实：", "依据来源："):
            normalized = normalized.split(marker, 1)[0].strip()
        normalized = normalized.rstrip(" 。；;，,")

        match = re.match(r"^(L[1-5])(?:\s+[^：:]{1,40})?[：:]\s*(.+)$", normalized)
        if match:
            normalized = (
                f"{cls._counted_question_difficulty_label(entry, level_code=match.group(1))}："
                f"{match.group(2).strip()}"
            )

        score_match = re.match(r"^(\d+(?:\.\d+)?)分[：:]\s*(.+)$", normalized)
        if score_match:
            normalized = (
                f"{cls._counted_question_difficulty_label(entry, score_match.group(1))}："
                f"{score_match.group(2).strip()}"
            )
        return normalized.rstrip(" 。；;，,")

    @staticmethod
    def _clean_dim4_display_text(value: object) -> str:
        return " ".join(str(value or "").split()).strip(" 。；;，,")

    @classmethod
    def _is_probably_english_display_text(cls, value: object) -> bool:
        text = cls._clean_dim4_display_text(value)
        if not text:
            return False

        english_words = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text)
        if not english_words:
            return False

        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", text))
        ascii_letter_count = len(re.findall(r"[A-Za-z]", text))
        stopwords = {
            "and",
            "are",
            "but",
            "either",
            "for",
            "from",
            "into",
            "requires",
            "that",
            "the",
            "then",
            "this",
            "through",
            "to",
            "with",
        }
        stopword_hits = sum(1 for word in english_words if word.lower() in stopwords)
        has_english_sentence = len(english_words) >= 4 or stopword_hits >= 2

        if cjk_count == 0:
            return has_english_sentence or ascii_letter_count >= 20

        return (
            ascii_letter_count >= 30
            and ascii_letter_count > max(12, cjk_count * 2.5)
            and stopword_hits >= 1
        )

    @classmethod
    def _dim4_fallback_score_reason(cls, entry: dict) -> str:
        level_code = str(entry.get("level_code") or "").strip().upper()
        if not level_code:
            level_code = cls._level_code_from_score(entry.get("score"))
        if level_code == "L5":
            return "难点在于要从全局构造或证明可行性，局部算对还不够"
        if level_code == "L4":
            return "难点在于不能直接套模板，需要构造中间量、分类回查或重组关系"
        if level_code == "L3":
            return "难点在于要完成一次策略转换或模型迁移，再沿新关系推进"
        if level_code == "L2":
            return "难点在于要在常规模板上做少量调整，分清变化后的条件"
        return "难点在于要识别基础模板，并按常规关系直接推进"

    @classmethod
    def _format_dim4_counted_question_analysis(cls, entry: dict, fallback_text: object) -> str:
        difficulty = cls._counted_question_difficulty_label(entry)
        point = cls._clean_dim4_display_text(entry.get("knowledge_point_text"))
        practice_level = cls._clean_dim4_display_text(entry.get("practice_level_text"))
        raw_reason = cls._clean_dim4_display_text(entry.get("score_reason"))
        reason = (
            raw_reason
            if raw_reason and not cls._is_probably_english_display_text(raw_reason)
            else cls._dim4_fallback_score_reason(entry)
        )

        if difficulty and reason and (point or practice_level):
            if point and practice_level:
                target = f"本题是{point}中的{practice_level}"
            elif point:
                target = f"本题是{point}的建模解题题"
            else:
                target = f"本题属于{practice_level}题"
            return f"{difficulty}：{target}；{reason}。"

        return cls._format_counted_question_analysis(fallback_text, entry)

    @staticmethod
    def _clean_dim5_display_text(value: object) -> str:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            return ""
        return (
            text.replace("竞赛数学导引", "奥数")
            .replace("高思导引", "奥数")
            .strip(" 。；;，,")
        )

    @classmethod
    def _format_dim5_counted_question_analysis(cls, entry: dict, fallback_text: object) -> str:
        difficulty = cls._counted_question_difficulty_label(entry)
        source = cls._clean_dim5_display_text(entry.get("knowledge_source_text"))
        point = cls._clean_dim5_display_text(entry.get("knowledge_point_text"))
        reason = cls._clean_dim5_display_text(entry.get("score_reason"))

        if difficulty and reason and (source or point):
            if source and point:
                target = f"本题属于{source}的{point}"
            elif source:
                target = f"本题属于{source}知识范围"
            else:
                target = f"本题主要考查{point}"
            return f"{difficulty}：{target}；{reason}。"

        fallback = cls._format_counted_question_analysis(fallback_text, entry)
        return cls._clean_dim5_display_text(fallback)

    @classmethod
    def _dim6_student_action_from_task(cls, task: str, evidence: str) -> str:
        if "周期" in task:
            return "找准循环节和目标位置，再把余数对应回具体状态"
        if "方案" in task:
            return "先列出可行方案，再按同一个标准比较，并检查限制条件是否都满足"
        if "情况" in task:
            return "把可能情况分完整，逐一代回条件检查，避免漏掉或重复"
        if "倒推" in task or "还原" in task:
            return "从结果往前还原每一步，再检查是否符合原条件"
        if "条件同时" in task:
            return "同时盯住多个条件，先缩小范围，再确认每个条件都成立"
        if "变化" in task or "阶段" in task:
            return "按阶段记录变化，把上一阶段的结果接到下一阶段条件中"
        if "中间结论" in task or "前一步" in evidence:
            return "把前一步得到的结果接到下一步条件里，连续推出中间结论"
        return "把已有条件一步步接起来，并在最后检查结论是否符合题意"

    @classmethod
    def _dim6_chain_description_from_entry(cls, entry: dict) -> str:
        chain_span = str(entry.get("chain_span") or "").strip()
        if chain_span == "1":
            return "很短，通常一步判断即可"
        if chain_span == "2":
            return "较短，大约需要连续推进 1-2 步"
        if chain_span == "3-4":
            return "较长，大约需要连续推进 3-4 步"
        if chain_span == "5+":
            return "很长，通常需要连续推进 5 步以上"

        level_code = str(entry.get("level_code") or "").strip().upper()
        if not level_code:
            level_code = cls._level_code_from_score(entry.get("score"))
        if level_code == "L5":
            return "很长，通常需要多步推进，并伴随分类、倒推、回查或多条件检查"
        if level_code == "L4":
            return "较长，通常需要多步推进，并伴随分类、倒推、回查或多条件检查"
        if level_code == "L3":
            return "有一定长度，通常需要把前后条件连续接起来"
        if level_code == "L2":
            return "较短，通常需要一两步衔接"
        return "很短，通常一步判断即可"

    @classmethod
    def _format_dim6_counted_question_analysis(cls, entry: dict, fallback_text: object) -> str:
        normalized = cls._format_counted_question_analysis(fallback_text, entry)
        if not normalized:
            return normalized
        if "这题的解题链条" in normalized and "学生需要" in normalized:
            return normalized
        current_style = re.match(r"^(.+?)：这题难在(.+?)；学生需要(.+)$", normalized)
        if current_style:
            difficulty, _task, action = current_style.groups()
            chain_description = cls._dim6_chain_description_from_entry(entry)
            return f"{difficulty}：这题的解题链条{chain_description}；学生需要{action.strip()}"

        old_style = re.match(r"^(.+?)：本题逻辑链条难在(.+?)；依据是(.+)$", normalized)
        if old_style:
            difficulty, task, evidence = old_style.groups()
            action = cls._dim6_student_action_from_task(task.strip(), evidence.strip())
            chain_description = cls._dim6_chain_description_from_entry(entry)
            return f"{difficulty}：这题的解题链条{chain_description}；学生需要{action}"
        return normalized

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
            raw_reason = entry.get("full_reason") or entry.get("reason") or entry.get("summary") or ""
            if detail.get("code") == "dim4":
                reason_text = self._format_dim4_counted_question_analysis(entry, raw_reason)
            elif detail.get("code") == "dim5":
                reason_text = self._format_dim5_counted_question_analysis(entry, raw_reason)
            elif detail.get("code") == "dim6":
                reason_text = self._format_dim6_counted_question_analysis(entry, raw_reason)
            else:
                reason_text = self._format_counted_question_analysis(raw_reason, entry)
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
            evidence_label = "覆盖状态" if is_not_covered else "得分概览"
            level_label = escape(str(detail.get("level_label") or "未评级"))
            evidence_max_length = 120 if detail.get("code") in {"dim3", "dim4"} else 56
            evidence = escape(
                self._truncate_text(
                    self._format_dimension_evidence(detail),
                    max_length=evidence_max_length,
                )
            )
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
                    <span class="report-dimension-card__label">{evidence_label}</span>
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

    def _build_parent_summary_html(
        self,
        position: dict,
        difficulty_label: str,
        difficulty_description: str,
        position_summary: str,
    ) -> str:
        del difficulty_description
        raw_summary = position.get("parent_summary") if isinstance(position, dict) else None
        if isinstance(raw_summary, list):
            summary_items = [str(item).strip() for item in raw_summary if str(item).strip()][:2]
        else:
            summary_items = []

        if len(summary_items) < 2:
            summary_items = [
                f"这张试卷整体定位为{difficulty_label}，{position_summary}",
                "具体卡点要结合各维度得分看，重点关注计算准确率、看图找关系、读懂题意、整理条件、知识混合使用和连续推理里分数偏高的部分。",
            ]

        paragraphs = "".join(
            f"<p>{escape(item)}</p>"
            for item in summary_items[:2]
        )
        return (
            '<span class="report-card-note">家长速读</span>'
            f'<div class="report-parent-summary">{paragraphs}</div>'
        )

    @staticmethod
    def _normalize_question_short_label(value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        text = text.replace("（", "(").replace("）", ")").strip()
        section_match = re.match(r"^[第\s]*[一二三四五六七八九十百千万零〇]+[部分卷题组]*[-－—]\s*(.+)$", text)
        if section_match:
            text = section_match.group(1).strip()

        bracket_match = re.match(r"^[\(（\[\【]\s*(.+?)\s*[\)）\]\】]$", text)
        if bracket_match:
            text = bracket_match.group(1).strip()

        question_match = re.match(r"^第\s*(.+?)\s*题$", text)
        if question_match:
            text = question_match.group(1).strip()

        return re.sub(r"[\s\.．、，,。:：]+$", "", text).strip()

    @classmethod
    def _question_distribution_label(cls, item: dict) -> str:
        return (
            str(item.get("question_short_label") or "").strip()
            or cls._normalize_question_short_label(item.get("question_display_label"))
            or cls._normalize_question_short_label(item.get("question_label_raw"))
            or cls._normalize_question_short_label(item.get("question_no"))
            or str(
                item.get("question_display_label")
                or item.get("question_label_raw")
                or item.get("question_no")
                or ""
            ).strip()
        )

    def _build_question_distribution_html(self, distribution: object) -> str:
        if not isinstance(distribution, dict):
            return """
            <div class="report-question-distribution">
              <div class="report-question-distribution__header">
                <div>
                  <span class="report-card-note">题目难度结构</span>
                  <h4>基础题 / 中等题 / 较难题</h4>
                </div>
              </div>
              <div class="report-question-distribution__empty">暂无题目难度结构数据。</div>
            </div>
            """

        raw_buckets = distribution.get("buckets", [])
        buckets = raw_buckets if isinstance(raw_buckets, list) else []
        order = {"basic": 0, "medium": 1, "hard": 2}

        bucket_html: list[str] = []
        for bucket in sorted(
            [item for item in buckets if isinstance(item, dict)],
            key=lambda item: order.get(str(item.get("key") or ""), 99),
        ):
            raw_questions = bucket.get("questions", [])
            questions = raw_questions if isinstance(raw_questions, list) else []
            question_labels = [
                self._question_distribution_label(item)
                for item in questions
                if isinstance(item, dict) and self._question_distribution_label(item)
            ]
            question_text = "、".join(question_labels) if question_labels else "暂无题目"
            percentage = self._safe_float(bucket.get("percentage"))
            count = int(self._safe_float(bucket.get("count"), 0))
            bucket_html.append(
                f"""
                <div class="report-question-bucket">
                  <div class="report-question-bucket__summary">
                    <span>{escape(str(bucket.get("label") or ""))}</span>
                    <strong>{percentage:.1f}%</strong>
                    <small>{count} 道</small>
                  </div>
                  <p>{escape(str(bucket.get("description") or "暂无说明。"))}</p>
                  <div class="report-question-bucket__questions">{escape(question_text)}</div>
                </div>
                """
            )

        unclassified_count = int(self._safe_float(distribution.get("unclassified_count"), 0))
        note_html = (
            f'<p class="report-question-distribution__note">另有 {unclassified_count} 道题缺少可用于分桶的维度分，未强行归类。</p>'
            if unclassified_count > 0
            else ""
        )
        classified_count = int(self._safe_float(distribution.get("classified_count"), 0))

        return f"""
        <div class="report-question-distribution">
          <div class="report-question-distribution__header">
            <div>
              <span class="report-card-note">题目难度结构</span>
              <h4>基础题 / 中等题 / 较难题</h4>
            </div>
            <span class="report-question-distribution__total">共 {classified_count} 道已归类题</span>
          </div>
          <div class="report-question-distribution__grid">{"".join(bucket_html)}</div>
          {note_html}
        </div>
        """

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
        position_summary_value = (
            difficulty_meta["position_summary"]
            if has_known_difficulty_level
            else position.get("position_summary")
            or position.get("description")
            or position.get("target_students")
            or "未提供"
        )
        position_summary = escape(str(position_summary_value))
        overall_score = self._format_score(position.get("overall_score"))
        parent_summary_html = self._build_parent_summary_html(
            position,
            str(difficulty_label_value),
            str(difficulty_description_value),
            str(position_summary_value),
        )
        question_distribution_html = self._build_question_distribution_html(
            position.get("question_distribution") if isinstance(position, dict) else None
        )

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
    .report-parent-summary {{ display: grid; gap: 7px; margin-top: 8px; }}
    .report-parent-summary p {{ color: #5d6a72; font-size: 12px; line-height: 1.72; }}
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
    .report-question-distribution {{ padding-top: 2px; break-inside: avoid; page-break-inside: avoid; }}
    .report-question-distribution__header {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 10px;
      margin-bottom: 10px;
    }}
    .report-question-distribution__header h4 {{ margin-top: 0; color: #1f2933; font-size: 13px; line-height: 1.4; font-weight: 600; }}
    .report-question-distribution__total {{ color: #8a9399; font-size: 10px; white-space: nowrap; }}
    .report-question-distribution__grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }}
    .report-question-bucket {{
      padding: 10px 10px 11px;
      background: #ffffff;
      border: 1px solid #d7dde2;
      border-radius: 10px;
      break-inside: avoid;
      page-break-inside: avoid;
    }}
    .report-question-bucket__summary {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 4px 8px;
      align-items: baseline;
    }}
    .report-question-bucket__summary span {{ color: #1f2933; font-size: 11px; font-weight: 600; line-height: 1.35; }}
    .report-question-bucket__summary strong {{ color: #294766; font-size: 18px; line-height: 1; font-family: "Noto Serif SC", "Source Han Serif SC", "Songti SC", "STSong", serif; }}
    .report-question-bucket__summary small {{ grid-column: 1 / -1; color: #8a9399; font-size: 10px; }}
    .report-question-bucket p {{ margin-top: 7px; color: #5d6a72; font-size: 10px; line-height: 1.55; }}
    .report-question-bucket__questions {{
      margin-top: 7px;
      padding-top: 7px;
      color: #1f2933;
      font-size: 10px;
      line-height: 1.55;
      border-top: 1px dashed #d7dde2;
      overflow-wrap: anywhere;
    }}
    .report-question-distribution__empty {{
      padding: 10px 12px;
      color: #8a9399;
      font-size: 11px;
      background: #ffffff;
      border: 1px dashed #d7dde2;
      border-radius: 10px;
    }}
    .report-question-distribution__note {{ margin-top: 8px; color: #8a9399; font-size: 10px; line-height: 1.55; }}
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
        <div class="report-overview-item"><span>试卷难度综合分</span><strong>{overall_score} / 10</strong></div>
        <div class="report-overview-item"><span>试卷定位</span><strong>{position_summary}</strong></div>
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
              <span class="report-score-panel__label">试卷难度综合分</span>
              <div class="report-score-panel__value">
                <strong>{overall_score}</strong>
                <small>/ 10</small>
              </div>
              <span class="report-level-pill" style="align-self:flex-start;color:{difficulty_meta['color']};background:{difficulty_meta['color']}14;border-color:{difficulty_meta['color']}33">{difficulty_label}</span>
            </div>

            <div>
              {parent_summary_html}
            </div>
          </div>

          <div class="report-difficulty-scale">{self._build_scale_html(difficulty_level)}</div>
          {question_distribution_html}
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
          <p>统一呈现维度名称、得分、等级与得分概览，减少冗余噪音，突出可读性。</p>
        </div>
        <div class="report-dimension-list">{self._build_dimension_cards_html(details_by_code)}</div>
      </section>

    </main>

    <footer class="report-footer">本报告按六维评价结果生成，题目难度结构基于每题实际适用维度的平均分统计。</footer>
  </div>

</body>
</html>"""
