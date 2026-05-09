"""
百度 OCR Provider。

当前实现重点：
- 用页内题号锚点 + 版面块边界切分大题
- 对跨页续写做合并，不改变对外大题统计口径
- 内部识别大题内的小问候选块，仅用于后续分析提准
- 为每道题补齐题块图片、解析审计和更真实的置信度
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx
from pdf2image import convert_from_path
from PIL import Image

from app.services.ocr.base import (
    BaseOCRProvider,
    DimensionCode,
    ParseStatus,
    ParseAudit,
    ParsedPaper,
    ParsedQuestion,
    QuestionCountAudit,
    QuestionBlock,
    QuestionType,
    SubItemCandidate,
)
from app.services.ocr.layout_types import OCRLine, QuestionAnchor, ReadingZone, SectionBlock

logger = logging.getLogger(__name__)


class BaiduOCRProvider(BaseOCRProvider):
    """基于百度 OCR 的试卷解析器。"""

    OCR_API_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/accurate"
    FORMULA_API_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/formula"
    TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
    TOP_LEVEL_PLAIN_NO_PATTERN = re.compile(r"^\s*(\d{1,2})\s*(?:[.\uFF0E\u3001\u9898])(?!\d)")

    TOP_LEVEL_CHINESE_NO_PATTERN = re.compile(r"^\s*([一二三四五六七八九十]{1,3})\s*[、\.．题]")

    TOP_LEVEL_PLAIN_NO_PATTERN = re.compile(r"^\s*(\d{1,2})\s*[\.．、题]")
    TOP_LEVEL_PAREN_NO_PATTERN = re.compile(r"^\s*[（(](\d{1,2})[）)]")
    SECTION_HEADING_PATTERN = re.compile(r"^\s*([一二三四五六七八九十]{1,3})\s*[、\.．]\s*(.*)$")
    SECTION_HEADING_PAREN_PATTERN = re.compile(r"^\s*[（(]([一二三四五六七八九十]{1,3})[）)]\s*(.*)$")
    TOP_LEVEL_PLAIN_NO_PATTERN = re.compile(r"^\s*(\d{1,2})\s*(?:[.\uFF0E\u3001\u9898])(?!\d)")
    WEAK_TOP_LEVEL_NO_PATTERN = re.compile(r"^\s*(\d{1,2})(?=[\u4e00-\u9fff])")
    SECTION_HEADING_KEYWORDS = (
        "填空",
        "选择",
        "判断",
        "计算",
        "解答",
        "应用",
        "解决问题",
        "操作",
        "作图",
        "统计",
        "综合",
        "附加",
        "附加题",
    )
    SUB_ITEM_PATTERNS = (
        re.compile(r"^\s*[（(]([1-9]\d{0,1})[）)]"),
        re.compile(r"^\s*([1-9]\d{0,1})\s*[\.．、)]"),
        re.compile(r"^\s*([A-Za-z])\s*[\.．、)]"),
    )
    SCORE_PATTERNS = (
        re.compile(r"[（(\[]\s*(\d+(?:\.\d+)?)\s*分\s*[）)\]]"),
        re.compile(r"[:：]\s*(\d+(?:\.\d+)?)\s*分"),
        re.compile(r"(\d+(?:\.\d+)?)\s*分"),
    )
    CHOICE_OPTION_PATTERN = re.compile(
        r"(?:A[\.．、:：].*B[\.．、:：].*C[\.．、:：])|"
        r"(?:A、.*B、.*C、)|"
        r"(?:A\..*B\..*C\.)",
        re.S,
    )
    BLANK_PATTERN = re.compile(r"_{2,}|（\s*）|\(\s*\)|\[ \]|\[\s*\]|□|▢|▭")
    CALCULATION_SIGNAL_PATTERN = re.compile(
        r"(?:计算|直接写得数|得数|口算|列式计算|简便计算|脱式计算|竖式计算|验算)"
    )
    FORMULA_HEAVY_PATTERN = re.compile(
        r"(?:\d+\s*[+\-×xX÷*/]\s*\d+)|(?:\d+\s*[:：]\s*\d+)|(?:\d+\s*%\s*)"
    )
    APPLICATION_SIGNAL_PATTERN = re.compile(
        r"(?:应用题|解决问题|实际问题|商店|学校|小明|小红|平均|至少|最多|需要|一共|还剩|几小时|多少)"
    )
    COMPREHENSIVE_SIGNAL_PATTERN = re.compile(
        r"(?:根据下图|根据下表|统计图|完成下面|操作题|作图|阅读材料|观察下列)"
    )
    VISUAL_SIGNAL_PATTERN = re.compile(
        r"(?:如图|下图|下表|统计图|折线图|柱状图|扇形图|表格|三角形|长方形|正方形|圆|圆柱|圆锥|展开图|截面)"
    )

    TABLE_CHART_SIGNAL_PATTERN = re.compile(
        r"(?:下表|表格|统计表|统计图|折线图|柱状图|条形图|扇形图|坐标图|线段图)"
    )
    GEOMETRY_STRONG_SIGNAL_PATTERN = re.compile(
        r"(?:如图|图中|看图|阴影部分|展开图|截面|折叠|旋转|从某方向看|正视图|侧视图|俯视图)"
    )
    GEOMETRY_CONTEXT_PATTERN = re.compile(
        r"(?:三角形|长方形|正方形|平行四边形|梯形|圆|扇形|角|周长|面积|体积|长方体|正方体|圆柱|圆锥|立体图形|对称轴)"
    )
    SPATIAL_SIGNAL_PATTERN = re.compile(
        r"(?:展开图|截面|折叠|旋转|立体|正视图|侧视图|俯视图|从上面看|从侧面看)"
    )
    SHORT_GEOMETRY_IMAGE_PATTERN = re.compile(
        "(?:S\\s*\u9634|S\u9634\u5f71|\u9634\u5f71(?:\u90e8\u5206)?(?:\u9762\u79ef)?|"
        "\u5706\u5185\u6700\u5927\u6b63\u65b9\u5f62|\u5185\u63a5\u6b63\u65b9\u5f62|"
        "\u9732\u5728\u5916\u9762\u7684\u9762\u79ef|\u5982\u56fe.*\u6c42\u9762\u79ef|"
        "\u56fe\u4e2d.*\u6c42\u9762\u79ef|\u6c42\\s*S)"
    )
    SHORT_GEOMETRY_3D_PATTERN = re.compile(
        "(?:\u9732\u5728\u5916\u9762|\u5c0f\u6b63\u65b9\u4f53|\u6b63\u65b9\u4f53|"
        "\u957f\u65b9\u4f53|\u68f1\u957f|\u7acb\u4f53|\u8868\u9762\u79ef)"
    )
    FORMULA_TRIGGER_PATTERN = re.compile(
        r"(?:=|≈|×|÷|/|%|[+\-*]|列式|竖式|脱式|简便计算|\d+\s*/\s*\d+)"
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.app_id = config.get("app_id") if config else None
        self.api_key = config.get("api_key") if config else None
        self.secret_key = config.get("secret_key") if config else None
        self.poppler_path = config.get("poppler_path") if config else None
        self.access_token: Optional[str] = None
        self.token_expire_time: Optional[datetime] = None

        if not all([self.app_id, self.api_key, self.secret_key]):
            logger.warning("百度 OCR 配置不完整，请检查环境变量")

    async def _get_access_token(self) -> str:
        if self.access_token and self.token_expire_time and datetime.now() < self.token_expire_time:
            return self.access_token

        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.TOKEN_URL, data=params)
            response.raise_for_status()
            data = response.json()
            self.access_token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            self.token_expire_time = datetime.fromtimestamp(
                datetime.now().timestamp() + expires_in - 300
            )
            logger.info("百度 OCR Access Token 获取成功")
            return self.access_token

    async def _recognize_text(self, image_base64: str) -> Dict[str, Any]:
        access_token = await self._get_access_token()
        url = f"{self.OCR_API_URL}?access_token={access_token}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "image": image_base64,
            "recognize_granularity": "small",
            "detect_direction": "true",
            "vertexes_location": "true",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, data=data)
            response.raise_for_status()
            result = response.json()
            if "error_code" in result:
                logger.error("百度 OCR 识别错误: %s", result)
                raise RuntimeError(f"百度 OCR 错误: {result.get('error_msg')}")
            return result

    async def _recognize_formula(self, image_base64: str) -> Dict[str, Any]:
        access_token = await self._get_access_token()
        url = f"{self.FORMULA_API_URL}?access_token={access_token}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "image": image_base64,
            "disp_formula": "true",
            "detect_direction": "true",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, data=data)
            response.raise_for_status()
            result = response.json()
            if "error_code" in result:
                logger.error("Formula OCR request failed: %s", result)
                raise RuntimeError(f"Formula OCR error: {result.get('error_msg')}")
            return result

    def _pdf_to_images(self, pdf_path: str, dpi: int = 300) -> List[str]:
        temp_dir = os.path.join(os.path.dirname(pdf_path), "temp_images")
        os.makedirs(temp_dir, exist_ok=True)

        poppler_path = self.poppler_path or os.environ.get("POPPLER_PATH")
        images = convert_from_path(pdf_path, dpi=dpi, poppler_path=poppler_path)

        image_paths: List[str] = []
        for index, image in enumerate(images):
            image_path = os.path.join(temp_dir, f"page_{index + 1}.jpg")
            image.save(image_path, "JPEG", quality=95)
            image_paths.append(image_path)

        logger.info("PDF 转图片完成，共 %s 页", len(image_paths))
        return image_paths

    def _image_to_base64(self, image_path: str) -> str:
        with open(image_path, "rb") as file:
            return base64.b64encode(file.read()).decode("utf-8")

    @staticmethod
    def _direction_to_rotation_degrees(raw_direction: Any) -> int:
        try:
            direction = int(raw_direction)
        except (TypeError, ValueError):
            return 0

        return {
            0: 0,
            1: 270,
            2: 180,
            3: 90,
        }.get(direction, 0)

    async def _normalize_page_orientation(
        self,
        image_path: str,
        *,
        page_no: int,
    ) -> Tuple[str, Dict[str, Any], int]:
        initial_result = await self._recognize_text(self._image_to_base64(image_path))
        rotation_degrees = self._direction_to_rotation_degrees(initial_result.get("direction"))
        if rotation_degrees == 0:
            return image_path, initial_result, 0

        source_path = Path(image_path)
        normalized_dir = source_path.parent / "ocr_normalized"
        normalized_dir.mkdir(parents=True, exist_ok=True)
        normalized_path = normalized_dir / f"{source_path.stem}_rot{rotation_degrees}{source_path.suffix}"

        with Image.open(image_path) as image:
            rotated = image.rotate(rotation_degrees, expand=True, fillcolor="white")
            rotated.save(normalized_path, format="JPEG", quality=95)

        logger.info(
            "OCR page orientation normalized page=%s direction=%s rotation=%s",
            page_no,
            initial_result.get("direction"),
            rotation_degrees,
        )
        normalized_result = await self._recognize_text(self._image_to_base64(str(normalized_path)))
        return str(normalized_path), normalized_result, rotation_degrees

    @staticmethod
    def _page_metrics(lines: Sequence[OCRLine]) -> Tuple[int, int]:
        page_width = max((line.right for line in lines), default=0)
        page_height = max((line.bottom for line in lines), default=0)
        return page_width, page_height

    def _extract_ocr_lines(self, ocr_result: Dict[str, Any]) -> List[OCRLine]:
        words_result = ocr_result.get("words_result", [])
        if not words_result:
            return []

        lines: List[OCRLine] = []
        for item in words_result:
            text = str(item.get("words", "")).strip()
            if not text:
                continue

            location = item.get("location") or {}
            left = int(location.get("left", 0))
            top = int(location.get("top", 0))
            width = int(location.get("width", 0))
            height = int(location.get("height", 0))
            if width <= 0 or height <= 0:
                vertexes = item.get("vertexes_location") or []
                if vertexes:
                    xs = [int(point.get("x", 0)) for point in vertexes]
                    ys = [int(point.get("y", 0)) for point in vertexes]
                    if xs and ys:
                        left = min(xs)
                        top = min(ys)
                        width = max(xs) - left
                        height = max(ys) - top

            lines.append(
                OCRLine(
                    text=text,
                    left=left,
                    top=top,
                    width=max(width, 1),
                    height=max(height, 1),
                )
            )

        lines.sort(key=lambda item: (item.top, item.left))
        return self._filter_noise_lines(lines)

    def _filter_noise_lines(self, lines: Sequence[OCRLine]) -> List[OCRLine]:
        if not lines:
            return []

        page_height = max(line.bottom for line in lines)
        filtered: List[OCRLine] = []
        for line in lines:
            normalized = line.text.strip()
            if not normalized:
                continue

            compact = normalized.replace(" ", "")
            is_page_marker = re.fullmatch(r"(?:第?\d+页|共\d+页|\d+/\d+)", compact)
            if is_page_marker and (line.top <= page_height * 0.08 or line.bottom >= page_height * 0.92):
                continue

            filtered.append(line)

        return filtered

    @staticmethod
    def _normalize_chinese_question_no(value: str) -> Optional[str]:
        numerals = {
            "一": 1,
            "二": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        normalized = str(value or "").strip()
        if not normalized:
            return None
        if normalized == "十":
            return "10"
        if "十" not in normalized:
            return str(numerals[normalized]) if normalized in numerals else None
        if normalized.startswith("十"):
            tail = normalized[1:]
            return str(10 + numerals.get(tail, 0)) if tail in numerals else "10"
        if normalized.endswith("十"):
            head = normalized[:-1]
            return str(numerals[head] * 10) if head in numerals else None

        head, tail = normalized.split("十", 1)
        if head not in numerals or tail not in numerals:
            return None
        return str(numerals[head] * 10 + numerals[tail])

    def _extract_section_index_raw(self, text: str) -> Optional[str]:
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return None

        for pattern in (self.SECTION_HEADING_PATTERN, self.SECTION_HEADING_PAREN_PATTERN):
            match = pattern.match(normalized_text)
            if not match:
                continue

            section_index_raw = str(match.group(1) or "").strip()
            suffix = str(match.group(2) or "").strip()
            normalized_suffix = re.sub(r"\s+", "", suffix)

            if not normalized_suffix:
                return section_index_raw

            if any(keyword in normalized_suffix for keyword in self.SECTION_HEADING_KEYWORDS):
                return section_index_raw

            if (
                len(normalized_suffix) <= 4
                and not re.search(r"\d|[=+\-*/×÷]", normalized_suffix)
            ):
                return section_index_raw

        return None

    def _latest_section_index_from_lines(
        self,
        lines: Sequence[OCRLine],
        current_section_index_raw: str = "",
    ) -> str:
        section_index_raw = current_section_index_raw
        for line in lines:
            detected = self._extract_section_index_raw(line.text)
            if detected:
                section_index_raw = detected
        return section_index_raw

    def _section_index_to_number(self, section_index_raw: str) -> Optional[int]:
        normalized = self._normalize_chinese_question_no(str(section_index_raw or "").strip())
        if not normalized:
            return None
        try:
            return int(normalized)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _number_to_section_index_raw(section_no: int) -> Optional[str]:
        mapping = {
            1: "一",
            2: "二",
            3: "三",
            4: "四",
            5: "五",
            6: "六",
            7: "七",
            8: "八",
            9: "九",
            10: "十",
        }
        return mapping.get(int(section_no))

    def _infer_headingless_prefix_section_index(
        self,
        carried_section_index_raw: str,
        first_heading_index_raw: str,
    ) -> str:
        carried = str(carried_section_index_raw or "").strip()
        if carried:
            return carried

        first_heading_no = self._section_index_to_number(first_heading_index_raw)
        if first_heading_no is None or first_heading_no <= 1:
            return ""

        return self._number_to_section_index_raw(first_heading_no - 1) or ""

    def _is_valid_plain_question_label(self, question_no: str, remainder: str) -> bool:
        normalized_no = str(question_no or "").strip()
        normalized_remainder = str(remainder or "").lstrip()

        if not normalized_no or normalized_no == "0":
            return False
        if not normalized_remainder:
            return True
        if normalized_remainder.startswith(("..", "...", "\u2026", ".", "\uFF0E")):
            return False

        heading_like_prefixes = (
            "计算",
            "填空",
            "选择",
            "解答",
            "应用题",
            "解决问题",
        )
        if any(normalized_remainder.startswith(prefix) for prefix in heading_like_prefixes):
            if "每题" in normalized_remainder or "共" in normalized_remainder:
                return False

        instruction_like_prefixes = (
            "不得",
            "考试时间",
            "满分",
            "时间",
            "答案",
            "注意事项",
        )
        if any(normalized_remainder.startswith(prefix) for prefix in instruction_like_prefixes):
            return False

        if normalized_remainder[0].isdigit():
            digit_prefix = re.match(r"^\d+(?:\.\d+)?", normalized_remainder)
            tail = normalized_remainder[digit_prefix.end() :] if digit_prefix else normalized_remainder
            tail = tail.lstrip()
            probe = normalized_remainder[:24]
            has_formula_signal = bool(re.search(r"[+\-*/=xX()（）\[\]]", probe))
            if not tail:
                return False
            if tail.startswith(("..", "...", "\u2026", ".", "\uFF0E")):
                return False
            if tail[0] in "+-*/=\u00D7\u00F7xX:\uFF1A":
                return False
            if re.match(
                r"^\d+(?:\.\d+)?\s*(?:元|%|厘米|平方厘米|平方米|立方厘米|立方米|米|千克|吨|分钟|小时|克|m2?|cm2?)",
                probe,
            ) and not has_formula_signal:
                return False
            if re.match(r"^\d+\.\d+$", probe) and not has_formula_signal:
                return False

        return True

    def _is_valid_weak_question_label(self, question_no: str, remainder: str) -> bool:
        normalized_no = str(question_no or "").strip()
        normalized_remainder = str(remainder or "").lstrip()

        if not normalized_no or normalized_no == "0":
            return False
        if not normalized_remainder:
            return False
        if not re.match(r"^[\u4e00-\u9fff“”‘’《》]", normalized_remainder):
            return False
        if not self._is_valid_plain_question_label(question_no, normalized_remainder):
            return False
        return True

    def _extract_weak_question_label(
        self,
        text: str,
        *,
        expected_no: Optional[int] = None,
    ) -> Optional[Tuple[str, str]]:
        weak_match = self.WEAK_TOP_LEVEL_NO_PATTERN.match(text)
        if not weak_match:
            return None

        question_no = weak_match.group(1)
        if expected_no is not None:
            try:
                if int(question_no) != int(expected_no):
                    return None
            except (TypeError, ValueError):
                return None

        remainder = text[weak_match.end() :]
        if not self._is_valid_weak_question_label(question_no, remainder):
            return None
        return question_no, question_no

    def _extract_question_label(self, text: str) -> Optional[Tuple[str, str]]:
        if re.match(
            r"^\s*\d{1,2}\.\d+(?:元|%|厘米|平方厘米|平方米|立方厘米|立方米|米|千克|吨|分钟|小时|克|m2?|cm2?)",
            text,
        ):
            return None

        plain_match = re.match(r"^\s*(\d{1,2})\s*(?:[.\uFF0E\u3001\u9898])", text)
        if plain_match:
            question_no = plain_match.group(1)
            remainder = text[plain_match.end() :]
            if self._is_valid_plain_question_label(question_no, remainder):
                return question_no, plain_match.group(0).strip()

        paren_match = self.TOP_LEVEL_PAREN_NO_PATTERN.match(text)
        if paren_match:
            return paren_match.group(1), paren_match.group(0).strip()

        chinese_match = self.TOP_LEVEL_CHINESE_NO_PATTERN.match(text)
        if not chinese_match:
            return None

        normalized = self._normalize_chinese_question_no(chinese_match.group(1))
        if not normalized:
            return None
        return normalized, chinese_match.group(0).strip()

    def _extract_question_no(self, text: str) -> Optional[str]:
        extracted = self._extract_question_label(text)
        if not extracted:
            return None
        return extracted[0]

    def _is_zone_seed_line(self, line: OCRLine) -> bool:
        if self._extract_section_index_raw(line.text):
            return True
        if self._is_figure_caption(line.text):
            return False
        label = self._extract_question_label(line.text)
        if not label:
            return False
        return not bool(self.TOP_LEVEL_PAREN_NO_PATTERN.match(line.text))

    @staticmethod
    def _format_corrected_question_label(raw_label: str, corrected_no: int) -> str:
        compact = str(raw_label or "").strip()
        suffix = "."
        if compact:
            last_char = compact[-1]
            if not last_char.isdigit():
                suffix = last_char
        return f"{corrected_no}{suffix}"

    def _repair_anchor_sequence(self, anchors: Sequence[QuestionAnchor]) -> List[QuestionAnchor]:
        repaired: List[QuestionAnchor] = []
        for index, anchor in enumerate(anchors):
            try:
                current_no = int(str(anchor.question_no).strip())
            except (TypeError, ValueError):
                repaired.append(anchor)
                continue

            corrected_no = current_no
            if repaired:
                try:
                    previous_no = int(str(repaired[-1].question_no).strip())
                except (TypeError, ValueError):
                    previous_no = None

                next_no: Optional[int] = None
                if index + 1 < len(anchors):
                    try:
                        next_no = int(str(anchors[index + 1].question_no).strip())
                    except (TypeError, ValueError):
                        next_no = None

                if previous_no is not None and current_no < previous_no and current_no < 10 <= previous_no:
                    candidate = (previous_no // 10) * 10 + current_no
                    if candidate <= previous_no:
                        candidate += 10
                    if candidate - previous_no <= 2 and (
                        next_no is None or next_no <= current_no or candidate < next_no
                    ):
                        corrected_no = candidate
                    else:
                        continue
                elif previous_no is not None and current_no <= previous_no:
                    continue

            if corrected_no == current_no:
                repaired.append(anchor)
                continue

            repaired.append(
                QuestionAnchor(
                    line_index=anchor.line_index,
                    question_no=str(corrected_no),
                    question_label_raw=self._format_corrected_question_label(
                        anchor.question_label_raw,
                        corrected_no,
                    ),
                    line=anchor.line,
                )
            )

        return repaired

    @staticmethod
    def _anchor_sequence_start_bonus(question_no: int) -> int:
        if question_no <= 3:
            return 6
        if question_no <= 10:
            return 3
        return 0

    @staticmethod
    def _anchor_sequence_transition_score(previous_no: int, current_no: int) -> int:
        gap = current_no - previous_no
        if gap <= 0:
            return -10_000
        if gap == 1:
            return 8
        if gap == 2:
            return 6
        if gap == 3:
            return 3
        return max(-6, 3 - (gap - 3) * 3)

    def _select_best_anchor_sequence(
        self,
        anchors: Sequence[QuestionAnchor],
    ) -> List[QuestionAnchor]:
        if len(anchors) <= 1:
            return list(anchors)

        numeric_values: List[Optional[int]] = []
        for anchor in anchors:
            try:
                numeric_values.append(int(str(anchor.question_no).strip()))
            except (TypeError, ValueError):
                numeric_values.append(None)

        if sum(1 for value in numeric_values if value is not None) <= 1:
            return list(anchors)

        best_scores: List[int] = []
        previous_indices: List[Optional[int]] = []
        for index, current_no in enumerate(numeric_values):
            if current_no is None:
                best_scores.append(-10_000)
                previous_indices.append(None)
                continue

            score = 8 + self._anchor_sequence_start_bonus(current_no)
            previous_index: Optional[int] = None
            for candidate_index, previous_no in enumerate(numeric_values[:index]):
                if previous_no is None or previous_no >= current_no:
                    continue
                candidate_score = (
                    best_scores[candidate_index]
                    + self._anchor_sequence_transition_score(previous_no, current_no)
                )
                if candidate_score > score:
                    score = candidate_score
                    previous_index = candidate_index

            best_scores.append(score)
            previous_indices.append(previous_index)

        best_end_index = max(range(len(best_scores)), key=lambda item: best_scores[item])
        selected_indices: List[int] = []
        while best_end_index is not None and best_scores[best_end_index] > -10_000:
            selected_indices.append(best_end_index)
            best_end_index = previous_indices[best_end_index]

        if not selected_indices:
            return list(anchors)
        selected_indices.reverse()
        return [anchors[index] for index in selected_indices]

    @staticmethod
    def _score_anchor_candidate_group(
        candidates: Sequence[Tuple[int, OCRLine, Tuple[str, str]]],
    ) -> int:
        if not candidates:
            return -10_000

        numbers: List[int] = []
        for _, _, label in candidates:
            try:
                numbers.append(int(str(label[0]).strip()))
            except (TypeError, ValueError):
                continue

        if not numbers:
            return -10_000

        descending_breaks = sum(
            1 for index in range(1, len(numbers)) if numbers[index] <= numbers[index - 1]
        )
        large_forward_jumps = sum(
            1 for index in range(1, len(numbers)) if numbers[index] - numbers[index - 1] > 3
        )
        duplicate_penalty = len(numbers) - len(set(numbers))
        low_start_bonus = 2 if numbers[0] <= 3 else 0
        return (
            len(numbers) * 5
            - descending_breaks * 10
            - large_forward_jumps * 3
            - duplicate_penalty * 4
            + low_start_bonus
        )

    def _should_keep_sectionless_continuation(
        self,
        section_index_raw: str,
        anchors: Sequence[QuestionAnchor],
        page_questions: Sequence[ParsedQuestion],
        existing_questions: Sequence[ParsedQuestion],
        section_state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        normalized_section = str(section_index_raw or "").strip()
        if not normalized_section or not anchors:
            return False

        last_question_no: Optional[int] = None
        for question in reversed([*existing_questions, *page_questions]):
            if str(getattr(question, "section_index_raw", "") or "").strip() != normalized_section:
                continue
            try:
                last_question_no = int(str(getattr(question, "question_no", "") or "").strip())
                break
            except (TypeError, ValueError):
                continue

        try:
            first_anchor_no = int(str(anchors[0].question_no).strip())
        except (TypeError, ValueError):
            return False

        if last_question_no is not None:
            return last_question_no < first_anchor_no <= last_question_no + 2

        if not section_state:
            return False

        declared_count = section_state.get("declared_count")
        if not section_state.get("entered"):
            return False
        detected_numbers = []
        for value in section_state.get("detected_numbers", []) or []:
            try:
                detected_numbers.append(int(str(value).strip()))
            except (TypeError, ValueError, AttributeError):
                continue
        if detected_numbers:
            last_detected_no = max(detected_numbers)
            return last_detected_no < first_anchor_no <= last_detected_no + 2

        anchor_values: List[int] = []
        for anchor in anchors[:3]:
            try:
                anchor_values.append(int(str(anchor.question_no).strip()))
            except (TypeError, ValueError):
                continue
        if len(anchor_values) >= 2 and all(
            0 < anchor_values[index + 1] - anchor_values[index] <= 2
            for index in range(len(anchor_values) - 1)
        ):
            return True

        if declared_count is None:
            return True

        try:
            declared_total = int(declared_count)
        except (TypeError, ValueError):
            return True
        return 1 <= first_anchor_no <= declared_total

    def _detect_question_start_indices(self, lines: Sequence[OCRLine]) -> List[int]:
        if not lines:
            return []

        plain_candidates = [
            index
            for index, line in enumerate(lines)
            if (
                self.TOP_LEVEL_PLAIN_NO_PATTERN.match(line.text)
                or self.TOP_LEVEL_CHINESE_NO_PATTERN.match(line.text)
            )
            and not self._extract_section_index_raw(line.text)
        ]
        candidate_indices = plain_candidates or [
            index
            for index, line in enumerate(lines)
            if self.TOP_LEVEL_PAREN_NO_PATTERN.match(line.text)
        ]

        if not candidate_indices:
            return []

        page_width = max(line.right for line in lines)
        baseline_left = min(lines[index].left for index in candidate_indices)
        left_tolerance = max(48, int(page_width * 0.10))

        filtered = [
            index
            for index in candidate_indices
            if lines[index].left <= baseline_left + left_tolerance
        ]
        filtered = filtered or candidate_indices

        deduped: List[int] = []
        seen_question_nos: set[str] = set()
        for index in filtered:
            extracted = self._extract_question_label(lines[index].text)
            if not extracted:
                continue
            question_no, _ = extracted
            if question_no in seen_question_nos and deduped:
                previous = lines[deduped[-1]]
                current = lines[index]
                if abs(current.top - previous.top) <= max(current.height, previous.height) * 1.5:
                    continue
            deduped.append(index)
            seen_question_nos.add(question_no)
        return deduped

    def _bbox_from_lines(self, lines: Sequence[OCRLine]) -> Optional[Dict[str, int]]:
        if not lines:
            return None
        left = min(line.left for line in lines)
        top = min(line.top for line in lines)
        right = max(line.right for line in lines)
        bottom = max(line.bottom for line in lines)
        return {
            "left": left,
            "top": top,
            "width": right - left,
            "height": bottom - top,
        }

    def _merge_bbox(
        self,
        base_bbox: Optional[Dict[str, int]],
        extra_bbox: Optional[Dict[str, int]],
    ) -> Optional[Dict[str, int]]:
        if not base_bbox:
            return extra_bbox
        if not extra_bbox:
            return base_bbox

        left = min(base_bbox["left"], extra_bbox["left"])
        top = min(base_bbox["top"], extra_bbox["top"])
        right = max(base_bbox["left"] + base_bbox["width"], extra_bbox["left"] + extra_bbox["width"])
        bottom = max(base_bbox["top"] + base_bbox["height"], extra_bbox["top"] + extra_bbox["height"])
        return {
            "left": left,
            "top": top,
            "width": right - left,
            "height": bottom - top,
        }

    def _normalize_question_text(self, lines: Sequence[OCRLine]) -> str:
        chunks: List[str] = []
        for line in lines:
            text = re.sub(r"\s+", " ", line.text.strip())
            if not text:
                continue
            if chunks and text == chunks[-1]:
                continue
            chunks.append(text)
        return "\n".join(chunks).strip()

    def _extract_score_details(self, text: str) -> Tuple[float, bool, str, str, float]:
        matches: List[Tuple[float, str]] = []
        for index, pattern in enumerate(self.SCORE_PATTERNS):
            for match in pattern.finditer(text):
                try:
                    matches.append((float(match.group(1)), f"pattern_{index + 1}"))
                except ValueError:
                    continue

        unique_scores = {score for score, _ in matches}
        if len(unique_scores) == 1:
            score = next(iter(unique_scores))
            source = matches[0][1]
            return score, True, source, "题面中稳定提取到单一分值。", 0.95

        if len(unique_scores) > 1:
            return 0.0, False, "ambiguous", "题面出现多个候选分值，无法稳定判定。", 0.2

        if "分" not in text:
            return 0.0, False, "missing", "题面未出现明显分值标记。", 0.1

        return 0.0, False, "unreliable", "题面存在分值痕迹，但 OCR 提取不稳定。", 0.35

    def _normalize_formula_text(self, text: str) -> str:
        normalized = text
        normalized = re.sub(r"(?<=\d)\s*[xX]\s*(?=\d)", " × ", normalized)
        normalized = re.sub(r"(?<=\d)\s*[*]\s*(?=\d)", " × ", normalized)
        normalized = re.sub(r"(?<=\d)\s*[/]\s*(?=\d)", " ÷ ", normalized)
        return normalized

    @staticmethod
    def _normalized_text_compact(text: str) -> str:
        return re.sub(r"\s+", "", str(text or "")).lower()

    def _should_try_formula_enhancement(
        self,
        question_text: str,
        question_type: QuestionType,
        line_count: int,
    ) -> bool:
        normalized = " ".join(str(question_text or "").split())
        if not normalized:
            return False

        compact = self._normalized_text_compact(normalized)
        operator_hits = len(re.findall(r"[+\-×xX÷*/=≈%]", compact))
        digit_groups = len(re.findall(r"\d+(?:\.\d+)?", compact))

        if question_type == QuestionType.CALCULATION:
            return True
        if self._is_formula_like_fill_blank(normalized):
            return True
        if self.FORMULA_TRIGGER_PATTERN.search(normalized) and operator_hits >= 2 and digit_groups >= 3:
            return True
        return line_count <= 4 and operator_hits >= 3 and digit_groups >= 3

    def _extract_formula_texts(self, formula_result: Dict[str, Any]) -> List[str]:
        candidates: List[str] = []
        raw_candidates: List[Any] = []

        for key in ("formula_result", "words_result", "result"):
            value = formula_result.get(key)
            if isinstance(value, list):
                raw_candidates.extend(value)
            elif isinstance(value, dict):
                raw_candidates.append(value)

        if isinstance(formula_result.get("formula"), str):
            raw_candidates.append({"formula": formula_result.get("formula")})

        for item in raw_candidates:
            if isinstance(item, str):
                text = item
            elif isinstance(item, dict):
                text = (
                    item.get("words")
                    or item.get("formula")
                    or item.get("content")
                    or item.get("text")
                    or ""
                )
            else:
                text = ""

            normalized = self._normalize_formula_text(str(text).strip())
            if normalized and self.FORMULA_TRIGGER_PATTERN.search(normalized):
                candidates.append(normalized)

        deduped: List[str] = []
        seen = set()
        for item in candidates:
            compact = self._normalized_text_compact(item)
            if compact in seen:
                continue
            seen.add(compact)
            deduped.append(item)
        return deduped

    def _merge_formula_texts(self, question_text: str, formula_texts: Sequence[str]) -> str:
        if not formula_texts:
            return question_text

        base_compact = self._normalized_text_compact(question_text)
        additions: List[str] = []
        for item in formula_texts:
            compact = self._normalized_text_compact(item)
            if not compact or compact in base_compact:
                continue
            additions.append(item)

        if not additions:
            return question_text

        return f"{question_text.strip()}\n[FORMULA] {'; '.join(additions[:3])}".strip()

    async def _maybe_enhance_formula_text(
        self,
        question_text: str,
        question_type: QuestionType,
        line_count: int,
        image_block_url: Optional[str],
    ) -> Tuple[str, bool, str, List[str], List[str]]:
        if not image_block_url or not self._should_try_formula_enhancement(question_text, question_type, line_count):
            return question_text, False, "text_only", [], []

        try:
            image_base64 = self._image_to_base64(image_block_url)
            result = await self._recognize_formula(image_base64)
            formula_texts = self._extract_formula_texts(result)
            merged_text = self._merge_formula_texts(question_text, formula_texts)

            notes: List[str] = []
            if formula_texts:
                notes.append(f"formula_hits={len(formula_texts)}")
                notes.append(f"formula_sample={formula_texts[0][:48]}")

            return (
                merged_text,
                merged_text != question_text,
                "formula_api" if formula_texts else "formula_no_hit",
                notes,
                [],
            )
        except Exception as exc:
            logger.warning("公式增强失败: %s", exc)
            return (
                question_text,
                False,
                "formula_failed",
                [],
                [f"formula_failed:{type(exc).__name__}"],
            )

    def _is_formula_like_fill_blank(self, text: str) -> bool:
        compact = text.replace(" ", "")
        return bool(self.BLANK_PATTERN.search(compact) and self.FORMULA_HEAVY_PATTERN.search(compact))

    def _detect_question_type(self, text: str) -> QuestionType:
        normalized = " ".join((text or "").split())
        if not normalized:
            return QuestionType.SOLUTION

        if self.CHOICE_OPTION_PATTERN.search(normalized) or "选择正确答案" in normalized:
            return QuestionType.SINGLE_CHOICE
        if self.CALCULATION_SIGNAL_PATTERN.search(normalized):
            return QuestionType.CALCULATION
        if self._is_formula_like_fill_blank(normalized):
            return QuestionType.CALCULATION
        if self.BLANK_PATTERN.search(normalized):
            return QuestionType.FILL_BLANK
        if self.COMPREHENSIVE_SIGNAL_PATTERN.search(normalized):
            return QuestionType.COMPREHENSIVE
        if self.APPLICATION_SIGNAL_PATTERN.search(normalized) and len(normalized) >= 18:
            return QuestionType.APPLICATION
        if self.VISUAL_SIGNAL_PATTERN.search(normalized):
            return QuestionType.COMPREHENSIVE
        return QuestionType.SOLUTION

    def _line_text_density(self, lines: Sequence[OCRLine], bbox: Optional[Dict[str, int]]) -> float:
        if not lines or not bbox:
            return 0.0
        area = max(bbox["width"] * bbox["height"], 1)
        char_count = sum(len(re.sub(r"\s+", "", line.text)) for line in lines)
        return round(min(char_count * 1200 / area, 1.0), 3)

    def _extract_sub_item_label(self, text: str) -> Optional[str]:
        for pattern in self.SUB_ITEM_PATTERNS:
            match = pattern.match(text)
            if match:
                return next((group for group in match.groups() if group), None)
        return None

    def _detect_sub_item_candidates(self, lines: Sequence[OCRLine]) -> List[SubItemCandidate]:
        if len(lines) < 3:
            return []

        start_indices: List[int] = []
        for index, line in enumerate(lines[1:], start=1):
            label = self._extract_sub_item_label(line.text)
            if label:
                start_indices.append(index)

        if len(start_indices) < 2:
            return []

        candidates: List[SubItemCandidate] = []
        for offset, start_index in enumerate(start_indices):
            end_index = start_indices[offset + 1] if offset + 1 < len(start_indices) else len(lines)
            candidate_lines = lines[start_index:end_index]
            label = self._extract_sub_item_label(candidate_lines[0].text)
            if not label:
                continue

            bbox = self._bbox_from_lines(candidate_lines)
            candidates.append(
                SubItemCandidate(
                    candidate_no=str(label),
                    raw_text=self._normalize_question_text(candidate_lines),
                    confidence=0.82,
                    reason="在大题内部识别到稳定的小问起始标记。",
                    bbox=bbox,
                )
            )
        return candidates

    def _classify_visual_need(
        self,
        question_text: str,
        question_type: QuestionType,
        sub_item_candidates: Sequence[SubItemCandidate],
    ) -> Dict[str, Any]:
        normalized = " ".join(str(question_text or "").split())
        if not normalized:
            return {
                "required": False,
                "attach_recommended": False,
                "category": "none",
                "reason": "题面文本为空",
            }

        if self.SHORT_GEOMETRY_IMAGE_PATTERN.search(normalized):
            category = "spatial_3d" if self.SHORT_GEOMETRY_3D_PATTERN.search(normalized) else "geometry_visual"
            return {
                "required": True,
                "attach_recommended": True,
                "category": category,
                "reason": "短文本图形题需要结合题块图片判断",
            }

        if self.TABLE_CHART_SIGNAL_PATTERN.search(normalized):
            return {
                "required": True,
                "attach_recommended": True,
                "category": "table_chart",
                "reason": "题面包含表格或统计图关键词",
            }

        if self.GEOMETRY_STRONG_SIGNAL_PATTERN.search(normalized):
            category = "spatial_3d" if self.SPATIAL_SIGNAL_PATTERN.search(normalized) else "geometry_visual"
            return {
                "required": True,
                "attach_recommended": True,
                "category": category,
                "reason": "题面显式依赖图形或空间视图",
            }

        if self.GEOMETRY_CONTEXT_PATTERN.search(normalized):
            category = "spatial_3d" if self.SPATIAL_SIGNAL_PATTERN.search(normalized) else "geometry_context"
            required = question_type == QuestionType.COMPREHENSIVE and category == "spatial_3d"
            return {
                "required": required,
                "attach_recommended": True,
                "category": category,
                "reason": "题面涉及几何对象，附图有助于稳定判断",
            }

        if self.VISUAL_SIGNAL_PATTERN.search(normalized):
            return {
                "required": True,
                "attach_recommended": True,
                "category": "explicit_visual",
                "reason": "题面出现显式看图提示",
            }

        if sub_item_candidates and question_type in {
            QuestionType.COMPREHENSIVE,
            QuestionType.SOLUTION,
        }:
            return {
                "required": False,
                "attach_recommended": True,
                "category": "multi_part_layout",
                "reason": "题块中存在多个小问候选，附图有助于理解版面结构",
            }

        return {
            "required": False,
            "attach_recommended": False,
            "category": "none",
            "reason": "未识别到稳定的图像依赖信号",
        }

    def _build_question_block_image(
        self,
        image_path: str,
        page_no: int,
        question_no: str,
        bbox: Optional[Dict[str, int]],
    ) -> Optional[str]:
        if not bbox:
            return None

        try:
            source_path = Path(image_path)
            output_root = source_path.parent
            if output_root.name == "temp_images":
                output_root = output_root.parent
            question_dir = output_root / "question_blocks"
            question_dir.mkdir(parents=True, exist_ok=True)

            safe_question_no = re.sub(r"[^0-9A-Za-z_-]+", "_", question_no).strip("_") or "unknown"
            output_path = question_dir / f"page_{page_no}_q_{safe_question_no}.jpg"

            with Image.open(image_path) as image:
                margin_x = max(24, int(image.width * 0.01))
                margin_y = max(24, int(image.height * 0.01))
                left = max(bbox["left"] - margin_x, 0)
                top = max(bbox["top"] - margin_y, 0)
                right = min(bbox["left"] + bbox["width"] + margin_x, image.width)
                bottom = min(bbox["top"] + bbox["height"] + margin_y, image.height)
                if right <= left or bottom <= top:
                    return None

                cropped = image.crop((left, top, right, bottom))
                cropped.save(output_path, format="JPEG", quality=92)

            return str(output_path)
        except Exception as exc:
            logger.warning("题块图片裁切失败 page=%s question=%s: %s", page_no, question_no, exc)
            return None

    def _calculate_question_confidence(self, audit: ParseAudit) -> float:
        weighted = (
            audit.anchor_confidence * 0.35
            + audit.score_confidence * 0.20
            + audit.block_completeness * 0.30
            + (0.85 if audit.image_cropped or not audit.image_attach_recommended else 0.55) * 0.15
        )
        if audit.cross_page_merged:
            weighted -= 0.08
        if "score_ambiguous" in audit.warning_codes:
            weighted -= 0.10
        if "image_recommended_missing" in audit.warning_codes:
            weighted -= 0.05
        if "formula_api_failed" in audit.warning_codes:
            weighted -= 0.08
        if audit.formula_enhanced:
            weighted += 0.03
        return round(max(0.2, min(weighted, 0.99)), 3)

    def _append_lines_to_question(
        self,
        question: ParsedQuestion,
        lines: Sequence[OCRLine],
        *,
        page_no: int,
    ) -> None:
        continuation_text = self._normalize_question_text(lines)
        if not continuation_text:
            return

        if question.raw_text:
            question.raw_text = f"{question.raw_text}\n{continuation_text}".strip()
        else:
            question.raw_text = continuation_text

        extra_bbox = self._bbox_from_lines(lines)
        if page_no == question.page_no:
            question.block_bbox = self._merge_bbox(question.block_bbox, extra_bbox)

        if page_no != question.page_no:
            continuation_warning = f"第 {page_no} 页内容并入题号 {question.question_no}，该题存在跨页续写。"
            if continuation_warning not in question.parse_warnings:
                question.parse_warnings.append(continuation_warning)

        if question.parse_audit is None:
            question.parse_audit = ParseAudit()
        question.parse_audit.line_count += len(lines)
        if page_no == question.page_no:
            question.parse_audit.notes.append(f"merged_same_page_{page_no}")
            if "same_page_merge" not in question.parse_audit.warning_codes:
                question.parse_audit.warning_codes.append("same_page_merge")
        else:
            question.parse_audit.cross_page_merged = True
            question.parse_audit.notes.append(f"merged_page_{page_no}")
            if "cross_page_merge" not in question.parse_audit.warning_codes:
                question.parse_audit.warning_codes.append("cross_page_merge")
        question.parse_confidence = self._calculate_question_confidence(question.parse_audit)

    def _build_parse_audit(
        self,
        *,
        question_text: str,
        question_type: QuestionType,
        score_reliable: bool,
        score_source: str,
        score_reason: str,
        score_confidence: float,
        bbox: Optional[Dict[str, int]],
        line_count: int,
        image_block_url: Optional[str],
        formula_enhanced: bool,
        formula_strategy: str,
        formula_warning_codes: Sequence[str],
        visual_assessment: Dict[str, Any],
    ) -> ParseAudit:
        text_density = self._line_text_density([], bbox) if False else 0.0
        block_density = 0.0 if not bbox else 0.0
        # 使用 line_count + bbox 近似描述题块完整度，避免题块过小却被高置信接受。
        if bbox:
            area = max(bbox["width"] * bbox["height"], 1)
            char_count = len(re.sub(r"\s+", "", question_text))
            block_density = round(min(char_count * 1200 / area, 1.0), 3)
        anchor_confidence = 0.95
        block_completeness = min(0.98, 0.65 + min(line_count, 6) * 0.05 + block_density * 0.1)

        image_required = bool(visual_assessment.get("required"))
        image_attach_recommended = bool(visual_assessment.get("attach_recommended"))
        if image_block_url:
            image_strategy = "image_attached"
        elif image_required:
            image_strategy = "image_missing"
        elif image_attach_recommended:
            image_strategy = "image_recommended_missing"
        else:
            image_strategy = "text_only"
        audit = ParseAudit(
            anchor_confidence=anchor_confidence,
            score_confidence=score_confidence,
            block_completeness=round(block_completeness, 3),
            cross_page_merged=False,
            image_cropped=bool(image_block_url),
            image_required_hint=image_required,
            image_attach_recommended=image_attach_recommended,
            image_strategy=image_strategy,
            visual_category=str(visual_assessment.get("category", "none") or "none"),
            visual_reason=str(visual_assessment.get("reason", "") or ""),
            score_source=score_source,
            score_reason=score_reason,
            formula_enhanced=formula_enhanced,
            formula_strategy=formula_strategy,
            line_count=line_count,
        )

        if image_required and not image_block_url:
            audit.warning_codes.append("image_missing")
        elif image_attach_recommended and not image_block_url:
            audit.warning_codes.append("image_recommended_missing")
        if not score_reliable:
            warning_code = {
                "ambiguous": "score_ambiguous",
                "missing": "score_missing",
                "unreliable": "score_unreliable",
            }.get(score_source, "score_unreliable")
            audit.warning_codes.append(warning_code)
        for warning_code in formula_warning_codes:
            normalized = str(warning_code).strip()
            if normalized.startswith("formula_failed"):
                audit.warning_codes.append("formula_api_failed")
            elif normalized:
                audit.warning_codes.append(normalized)

        return audit

    @staticmethod
    def _is_figure_caption(text: str) -> bool:
        compact = re.sub(r"\s+", "", str(text or ""))
        return bool(
            re.match(r"^(?:第?\d+题图|图\d+|附图\d*|题图)$", compact)
            or compact.endswith("题图")
        )

    @staticmethod
    def _extract_declared_question_count(text: str) -> Optional[int]:
        normalized = str(text or "").strip()
        if not normalized:
            return None

        patterns = (
            r"(?:共|本大题共|本部分共|共有)\s*(\d{1,3})\s*(?:道|题|小题)",
            r"[（(]\s*(\d{1,3})\s*(?:道|题|小题)\s*[)）]",
        )
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    return None

        score_match = re.search(
            r"每小题\s*(\d+(?:\.\d+)?)\s*分[^共]*共\s*(\d+(?:\.\d+)?)\s*分",
            normalized,
        )
        if score_match:
            try:
                score_per_question = float(score_match.group(1))
                total_score = float(score_match.group(2))
            except (TypeError, ValueError):
                return None
            if score_per_question > 0:
                declared_count = total_score / score_per_question
                if declared_count.is_integer() and 1 <= declared_count <= 60:
                    return int(declared_count)
        return None

    @staticmethod
    def _extract_question_numbers_from_heading_text(text: str) -> List[int]:
        normalized = str(text or "").strip()
        if not normalized:
            return []

        numbers: List[int] = []
        for match in re.finditer(r"(\d{1,2})\s*(?:[-~～—－至])\s*(\d{1,2})(?:\s*(?:小题|题))?", normalized):
            try:
                start_no = int(match.group(1))
                end_no = int(match.group(2))
            except (TypeError, ValueError):
                continue
            if start_no <= 0 or end_no <= 0 or end_no < start_no or end_no - start_no > 20:
                continue
            numbers.extend(range(start_no, end_no + 1))

        for match in re.finditer(r"(?:^|[（(，,、及和])\s*(\d{1,2})\s*(?:小题|题)\b", normalized):
            try:
                value = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if value > 0:
                numbers.append(value)

        return sorted(dict.fromkeys(numbers))

    @staticmethod
    def _extract_question_numbers_from_figure_captions(lines: Sequence[OCRLine]) -> List[int]:
        numbers: List[int] = []
        for line in lines:
            compact = re.sub(r"\s+", "", str(line.text or ""))
            match = re.match(r"^第?(\d{1,2})题图$", compact)
            if not match:
                continue
            try:
                numbers.append(int(match.group(1)))
            except (TypeError, ValueError):
                continue
        return sorted(dict.fromkeys(numbers))

    def _extract_expected_question_numbers(
        self,
        heading_text: str,
        lines: Sequence[OCRLine],
    ) -> List[int]:
        heading_numbers = self._extract_question_numbers_from_heading_text(heading_text)
        if not heading_numbers:
            return []

        caption_numbers = self._extract_question_numbers_from_figure_captions(lines)
        if not caption_numbers:
            return heading_numbers

        return sorted(dict.fromkeys([*heading_numbers, *caption_numbers]))

    def _looks_like_section_heading_without_index(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", str(text or ""))
        if not normalized:
            return False
        if self._extract_section_index_raw(normalized):
            return False
        return any(keyword in normalized for keyword in self.SECTION_HEADING_KEYWORDS) and (
            "每小题" in normalized
            or "本大题" in normalized
            or "共" in normalized
        )

    def _infer_expected_question_numbers_from_declared_count(
        self,
        anchors: Sequence[QuestionAnchor],
        declared_count: Optional[int],
    ) -> List[int]:
        if declared_count is None or not anchors:
            return []

        try:
            declared_total = int(str(declared_count).strip())
        except (TypeError, ValueError, AttributeError):
            return []
        if declared_total <= 0:
            return []

        numeric_anchor_values: List[int] = []
        for anchor in anchors:
            try:
                numeric_anchor_values.append(int(str(anchor.question_no).strip()))
            except (TypeError, ValueError):
                continue
        if not numeric_anchor_values:
            return []

        min_anchor = min(numeric_anchor_values)
        max_anchor = max(numeric_anchor_values)
        if 1 <= min_anchor and max_anchor <= declared_total:
            return list(range(1, declared_total + 1))

        if max_anchor - min_anchor < declared_total:
            return list(range(min_anchor, min_anchor + declared_total))

        return []

    @staticmethod
    def _is_sub_item_like_line(text: str) -> bool:
        normalized = str(text or "").strip()
        if not normalized:
            return False
        return bool(
            re.match(r"^[（(][1-9]\d{0,1}[)）]", normalized)
            or re.match(r"^[A-Za-z][.．、)]", normalized)
        )

    def _is_viable_continuation_cluster(
        self,
        cluster: Sequence[Tuple[int, OCRLine]],
    ) -> bool:
        if not cluster:
            return False

        texts = [str(line.text or "").strip() for _, line in cluster if str(line.text or "").strip()]
        if not texts:
            return False

        compact_text = "".join(re.sub(r"\s+", "", text) for text in texts)
        chinese_hits = len(re.findall(r"[\u4e00-\u9fff]", compact_text))
        if len(compact_text) < 16 or chinese_hits < 6:
            return False

        first_text = texts[0]
        if self._is_sub_item_like_line(first_text) and chinese_hits < 12:
            return False

        if all(
            self._is_short_calculation_block_line(text)
            or self._is_preamble_noise_line(text)
            for text in texts
        ):
            return False

        return True

    @staticmethod
    def _extract_formula_prefixed_question_no(text: str) -> Optional[int]:
        normalized = str(text or "").strip()
        match = re.match(r"^(\d{1,2})\s*[.．、]\s*(?=[\d(（+\-])", normalized)
        if not match:
            return None
        if len(re.findall(r"[+\-=\u00D7\u00F7xX*/]", normalized)) < 1:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    def _recover_formula_prefixed_declared_anchors(
        self,
        section_lines: Sequence[OCRLine],
        anchors: Sequence[QuestionAnchor],
        declared_count: Optional[int],
    ) -> List[QuestionAnchor]:
        if anchors or declared_count is None:
            return list(anchors)

        try:
            declared_total = int(str(declared_count).strip())
        except (TypeError, ValueError, AttributeError):
            return list(anchors)
        if declared_total <= 0:
            return list(anchors)

        candidates: List[QuestionAnchor] = []
        for line_index, line in enumerate(section_lines):
            if self._extract_section_index_raw(line.text) or self._is_figure_caption(line.text):
                continue
            question_no = self._extract_formula_prefixed_question_no(line.text)
            if question_no is None:
                continue
            candidates.append(
                QuestionAnchor(
                    line_index=line_index,
                    question_no=str(question_no),
                    question_label_raw=f"{question_no}.",
                    line=line,
                    force_use_label=True,
                    recovery_reason="formula_declared_anchor",
                )
            )

        if not candidates:
            return list(anchors)

        candidates = self._select_best_anchor_sequence(candidates)
        numeric_values: List[int] = []
        for anchor in candidates:
            try:
                numeric_values.append(int(str(anchor.question_no).strip()))
            except (TypeError, ValueError):
                continue
        if not numeric_values:
            return list(anchors)

        if (
            len(candidates) >= 2
            and len(candidates) <= declared_total
            and all(
                0 < numeric_values[index + 1] - numeric_values[index] <= 2
                for index in range(len(numeric_values) - 1)
            )
        ):
            return list(candidates)

        if len(candidates) == declared_total:
            return list(candidates)

        return list(anchors)

    def _consume_leading_section_metadata(
        self,
        lines: Sequence[OCRLine],
        declared_count: Optional[int],
    ) -> Tuple[List[OCRLine], Optional[int]]:
        remaining_lines = list(lines)
        resolved_declared_count = declared_count
        consumed_count = 0

        for line in remaining_lines[:6]:
            text = str(line.text or "").strip()
            if not text:
                consumed_count += 1
                continue

            detected_count = self._extract_declared_question_count(text)
            if detected_count is not None:
                resolved_declared_count = detected_count
                consumed_count += 1
                continue

            if (
                re.match(r"^[（(].{0,40}[)）]$", text)
                or self._is_preamble_noise_line(text)
                or self._looks_like_section_heading_without_index(text)
            ):
                consumed_count += 1
                continue
            break

        if consumed_count:
            remaining_lines = remaining_lines[consumed_count:]
        return remaining_lines, resolved_declared_count

    @staticmethod
    def _split_line_clusters(
        indexed_lines: Sequence[Tuple[int, OCRLine]],
    ) -> List[List[Tuple[int, OCRLine]]]:
        if not indexed_lines:
            return []

        heights = sorted(max(line.height, 1) for _, line in indexed_lines)
        median_height = heights[len(heights) // 2]
        gap_threshold = max(96, int(median_height * 2.4))

        clusters: List[List[Tuple[int, OCRLine]]] = [[indexed_lines[0]]]
        for item in indexed_lines[1:]:
            previous_line = clusters[-1][-1][1]
            current_line = item[1]
            if current_line.top - previous_line.bottom >= gap_threshold:
                clusters.append([item])
            else:
                clusters[-1].append(item)

        return clusters

    @staticmethod
    def _section_state(
        section_contexts: Dict[str, Dict[str, Any]],
        section_index_raw: str,
    ) -> Dict[str, Any]:
        return section_contexts.setdefault(
            section_index_raw,
            {
                "entered": False,
                "declared_count": None,
                "last_question_no": None,
                "detected_numbers": [],
            },
        )

    def _build_seed_groups_from_lines(
        self,
        seed_lines: Sequence[OCRLine],
        page_width: int,
    ) -> List[Dict[str, Any]]:
        sorted_seeds = sorted(seed_lines, key=lambda item: (item.left, item.top))
        if len(sorted_seeds) < 2:
            return []

        gap_threshold = max(96, int(page_width * 0.10))
        seed_groups: List[Dict[str, Any]] = []
        for line in sorted_seeds:
            anchor_left = line.left
            if not seed_groups or anchor_left - seed_groups[-1]["max_left"] > gap_threshold:
                seed_groups.append({"positions": [anchor_left], "max_left": anchor_left})
            else:
                seed_groups[-1]["positions"].append(anchor_left)
                seed_groups[-1]["max_left"] = anchor_left

        if len(seed_groups) <= 1 and len(sorted_seeds) >= 4:
            sorted_lefts = sorted(line.left for line in seed_lines)
            gaps = [
                (sorted_lefts[index + 1] - sorted_lefts[index], index)
                for index in range(len(sorted_lefts) - 1)
            ]
            if gaps:
                largest_gap, gap_index = max(gaps, key=lambda item: item[0])
                if largest_gap >= max(140, int(page_width * 0.12)):
                    left_group = sorted_lefts[: gap_index + 1]
                    right_group = sorted_lefts[gap_index + 1 :]
                    if left_group and right_group:
                        seed_groups = [
                            {"positions": left_group, "max_left": max(left_group)},
                            {"positions": right_group, "max_left": max(right_group)},
                        ]

        if len(seed_groups) > 2:
            ordered_groups = sorted(
                seed_groups,
                key=lambda item: sum(item["positions"]) / max(len(item["positions"]), 1),
            )
            ordered_centers = [
                sum(group["positions"]) / max(len(group["positions"]), 1)
                for group in ordered_groups
            ]
            gaps = [
                (ordered_centers[index + 1] - ordered_centers[index], index)
                for index in range(len(ordered_centers) - 1)
            ]
            largest_gap, split_index = max(gaps, key=lambda item: item[0])
            if largest_gap >= max(100, int(page_width * 0.08)):
                left_positions = [
                    pos
                    for group in ordered_groups[: split_index + 1]
                    for pos in group["positions"]
                ]
                right_positions = [
                    pos
                    for group in ordered_groups[split_index + 1 :]
                    for pos in group["positions"]
                ]
                seed_groups = [
                    {"positions": left_positions, "max_left": max(left_positions)},
                    {"positions": right_positions, "max_left": max(right_positions)},
                ]

        return seed_groups

    def _detect_reading_zones(self, lines: Sequence[OCRLine]) -> List[ReadingZone]:
        if not lines:
            return []

        page_width, page_height = self._page_metrics(lines)
        seed_lines = [line for line in lines if self._is_zone_seed_line(line)]
        seed_groups = self._build_seed_groups_from_lines(seed_lines, page_width)
        fallback_groups = self._build_seed_groups_from_lines(lines, page_width)
        if len(seed_groups) <= 1 and len(fallback_groups) > 1:
            seed_groups = fallback_groups

        if len(seed_groups) <= 1:
            bbox = self._bbox_from_lines(lines) or {"left": 0, "top": 0, "width": 0, "height": 0}
            return [
                ReadingZone(
                    zone_key="zone-1",
                    lines=sorted(lines, key=lambda item: (item.top, item.left)),
                    left=bbox["left"],
                    top=bbox["top"],
                    right=bbox["left"] + bbox["width"],
                    bottom=bbox["top"] + bbox["height"],
                    layout_type="single_column",
                )
            ]

        baselines = [sum(group["positions"]) / len(group["positions"]) for group in seed_groups]
        if max(baselines) - min(baselines) < page_width * 0.18:
            bbox = self._bbox_from_lines(lines) or {"left": 0, "top": 0, "width": 0, "height": 0}
            return [
                ReadingZone(
                    zone_key="zone-1",
                    lines=sorted(lines, key=lambda item: (item.top, item.left)),
                    left=bbox["left"],
                    top=bbox["top"],
                    right=bbox["left"] + bbox["width"],
                    bottom=bbox["top"] + bbox["height"],
                    layout_type="single_column",
                )
            ]

        assignments: Dict[int, List[OCRLine]] = {index: [] for index in range(len(baselines))}
        for line in lines:
            nearest = min(range(len(baselines)), key=lambda idx: abs(line.left - baselines[idx]))
            assignments[nearest].append(line)

        layout_type = "dual_column" if len(baselines) == 2 else "multi_zone"
        zones: List[ReadingZone] = []
        for index, zone_lines in assignments.items():
            if not zone_lines:
                continue
            zone_lines = sorted(zone_lines, key=lambda item: (item.top, item.left))
            bbox = self._bbox_from_lines(zone_lines)
            if not bbox:
                continue
            zone = ReadingZone(
                zone_key=f"zone-{index + 1}",
                lines=zone_lines,
                left=bbox["left"],
                top=bbox["top"],
                right=bbox["left"] + bbox["width"],
                bottom=bbox["top"] + bbox["height"],
                layout_type=layout_type,
            )
            if self._is_margin_zone(zone, page_width, page_height):
                continue
            zones.append(zone)

        if not zones:
            bbox = self._bbox_from_lines(lines) or {"left": 0, "top": 0, "width": 0, "height": 0}
            return [
                ReadingZone(
                    zone_key="zone-1",
                    lines=sorted(lines, key=lambda item: (item.top, item.left)),
                    left=bbox["left"],
                    top=bbox["top"],
                    right=bbox["left"] + bbox["width"],
                    bottom=bbox["top"] + bbox["height"],
                    layout_type="single_column",
                )
            ]

        zones.sort(key=lambda zone: (zone.left, zone.top))
        if len(zones) == 1:
            zones[0].layout_type = "single_column"
        return zones

    @staticmethod
    def _is_margin_zone(zone: ReadingZone, page_width: int, page_height: int) -> bool:
        narrow = zone.width <= max(120, int(page_width * 0.13))
        short = zone.height <= max(240, int(page_height * 0.45))
        sparse = len(zone.lines) <= 4
        edge_zone = zone.left <= page_width * 0.05 or zone.right >= page_width * 0.95
        short_text = sum(len(re.sub(r"\s+", "", str(line.text or ""))) for line in zone.lines) <= 20
        return narrow and sparse and short and edge_zone and short_text

    def _build_zone_sections(
        self,
        zone: ReadingZone,
        carried_section_index_raw: str = "",
    ) -> List[SectionBlock]:
        lines = sorted(zone.lines, key=lambda item: (item.top, item.left))
        heading_indices = [
            index for index, line in enumerate(lines) if self._extract_section_index_raw(line.text)
        ]
        sections: List[SectionBlock] = []

        if not heading_indices:
            bbox = self._bbox_from_lines(lines)
            if bbox:
                sections.append(
                    SectionBlock(
                        zone_key=zone.zone_key,
                        section_index_raw=carried_section_index_raw,
                        heading_text="",
                        lines=lines,
                        left=bbox["left"],
                        top=bbox["top"],
                        right=bbox["left"] + bbox["width"],
                        bottom=bbox["top"] + bbox["height"],
                        declared_count=None,
                        layout_type=zone.layout_type,
                    )
                )
            return sections

        first_heading_index_raw = self._extract_section_index_raw(lines[heading_indices[0]].text) or ""
        if heading_indices[0] > 0:
            leading_lines = [line for line in lines[: heading_indices[0]] if line.text.strip()]
            leading_section_index_raw = self._infer_headingless_prefix_section_index(
                carried_section_index_raw,
                first_heading_index_raw,
            )
            bbox = self._bbox_from_lines(leading_lines)
            if bbox:
                sections.append(
                    SectionBlock(
                        zone_key=zone.zone_key,
                        section_index_raw=leading_section_index_raw,
                        heading_text="",
                        lines=leading_lines,
                        left=bbox["left"],
                        top=bbox["top"],
                        right=bbox["left"] + bbox["width"],
                        bottom=bbox["top"] + bbox["height"],
                        declared_count=None,
                        layout_type=zone.layout_type,
                        is_headingless_prefix=bool(leading_section_index_raw and not carried_section_index_raw),
                    )
                )

        current_section = carried_section_index_raw
        for offset, heading_index in enumerate(heading_indices):
            heading_line = lines[heading_index]
            detected_section = self._extract_section_index_raw(heading_line.text) or current_section
            previous_section_no = self._section_index_to_number(current_section)
            detected_section_no = self._section_index_to_number(detected_section)
            if (
                previous_section_no is not None
                and detected_section_no is not None
                and detected_section_no < previous_section_no
            ):
                current_section = (
                    self._number_to_section_index_raw(previous_section_no + 1)
                    or detected_section
                    or current_section
                )
            else:
                current_section = detected_section or current_section
            next_heading = heading_indices[offset + 1] if offset + 1 < len(heading_indices) else len(lines)
            content_lines = [
                line
                for line in lines[heading_index + 1 : next_heading]
                if not self._extract_section_index_raw(line.text)
            ]
            if not content_lines:
                continue

            bbox = self._bbox_from_lines([heading_line, *content_lines]) or self._bbox_from_lines(content_lines)
            if not bbox:
                continue

            sections.append(
                SectionBlock(
                    zone_key=zone.zone_key,
                    section_index_raw=current_section,
                    heading_text=heading_line.text,
                    lines=content_lines,
                    left=bbox["left"],
                    top=bbox["top"],
                    right=bbox["left"] + bbox["width"],
                    bottom=bbox["top"] + bbox["height"],
                    declared_count=self._extract_declared_question_count(heading_line.text),
                    layout_type=zone.layout_type,
                )
            )

        return sections

    def _is_formula_heavy_line(self, text: str) -> bool:
        normalized = " ".join(str(text or "").split())
        if not normalized:
            return False

        compact = normalized.replace(" ", "")
        if re.fullmatch(r"[\d.]{6,}", compact):
            return True

        digit_groups = len(re.findall(r"\d+(?:\.\d+)?", normalized))
        operator_hits = len(re.findall(r"[+\-脳xX梅*/=]", normalized))
        return digit_groups >= 2 and (operator_hits >= 1 or self.FORMULA_TRIGGER_PATTERN.search(normalized))

    @staticmethod
    def _coerce_question_number_list(values: Optional[Sequence[int]]) -> List[int]:
        if not values:
            return []

        normalized: List[int] = []
        for value in values:
            try:
                numeric = int(str(value).strip())
            except (TypeError, ValueError):
                continue
            if numeric <= 0 or numeric in normalized:
                continue
            normalized.append(numeric)
        return sorted(normalized)

    def _align_anchors_to_expected_numbers(
        self,
        anchors: Sequence[QuestionAnchor],
        expected_question_numbers: Optional[Sequence[int]],
    ) -> List[QuestionAnchor]:
        expected_values = self._coerce_question_number_list(expected_question_numbers)
        if not anchors or not expected_values:
            return list(anchors)

        aligned: List[QuestionAnchor] = []
        used_numbers: set[int] = set()
        last_expected: Optional[int] = None

        for anchor in anchors:
            try:
                current_no = int(str(anchor.question_no).strip())
            except (TypeError, ValueError):
                continue

            candidate_no: Optional[int] = None
            if current_no in expected_values and current_no not in used_numbers:
                candidate_no = current_no
            elif current_no < 10:
                suffix_matches = [
                    number
                    for number in expected_values
                    if number % 10 == current_no and number not in used_numbers
                ]
                if last_expected is not None:
                    suffix_matches = [number for number in suffix_matches if number > last_expected] or suffix_matches
                if len(suffix_matches) == 1:
                    candidate_no = suffix_matches[0]

            if candidate_no is None:
                continue
            if last_expected is not None and candidate_no <= last_expected:
                continue

            if candidate_no == current_no:
                normalized_anchor = anchor
            else:
                normalized_anchor = QuestionAnchor(
                    line_index=anchor.line_index,
                    question_no=str(candidate_no),
                    question_label_raw=self._format_corrected_question_label(
                        anchor.question_label_raw,
                        candidate_no,
                    ),
                    line=anchor.line,
                    force_use_label=anchor.force_use_label,
                    recovery_reason=anchor.recovery_reason,
                )

            aligned.append(normalized_anchor)
            used_numbers.add(candidate_no)
            last_expected = candidate_no

        return aligned

    def _detect_question_anchors(
        self,
        lines: Sequence[OCRLine],
        zone_left: int,
        *,
        expected_question_numbers: Optional[Sequence[int]] = None,
        allow_parenthesized: bool = True,
    ) -> List[QuestionAnchor]:
        if not lines:
            return []

        plain_candidates: List[Tuple[int, OCRLine, Tuple[str, str]]] = []
        paren_candidates: List[Tuple[int, OCRLine, Tuple[str, str]]] = []
        for index, line in enumerate(lines):
            if self._extract_section_index_raw(line.text) or self._is_figure_caption(line.text):
                continue
            label = self._extract_question_label(line.text)
            if not label:
                continue
            if self.TOP_LEVEL_PAREN_NO_PATTERN.match(line.text):
                if not allow_parenthesized:
                    continue
                paren_candidates.append((index, line, label))
            else:
                plain_candidates.append((index, line, label))

        candidates = plain_candidates or (paren_candidates if allow_parenthesized else [])

        if not candidates:
            return []

        local_right = max((line.right for line in lines), default=zone_left)
        local_width = max(local_right - zone_left, 1)
        baseline_left = min(line.left for _, line, _ in candidates)
        left_tolerance = max(42, int(local_width * 0.18))
        threshold = min(
            baseline_left + left_tolerance,
            zone_left + max(72, int(local_width * 0.24)),
        )

        formula_heavy_count = sum(1 for item in candidates if self._is_formula_heavy_line(item[1].text))
        if len(candidates) <= 2 and all(self._is_formula_heavy_line(item[1].text) for item in candidates):
            filtered = candidates
        elif len(candidates) <= 4 and formula_heavy_count >= max(2, len(candidates) - 1):
            filtered = candidates
        else:
            sorted_candidates = sorted(candidates, key=lambda item: (item[1].left, item[1].top))
            gap_threshold = max(72, int(local_width * 0.12))
            grouped_candidates: List[List[Tuple[int, OCRLine, Tuple[str, str]]]] = []
            for candidate in sorted_candidates:
                if (
                    not grouped_candidates
                    or candidate[1].left - grouped_candidates[-1][-1][1].left > gap_threshold
                ):
                    grouped_candidates.append([candidate])
                else:
                    grouped_candidates[-1].append(candidate)

            if len(grouped_candidates) > 1:
                options = list(grouped_candidates)
                if formula_heavy_count >= max(2, len(candidates) // 2):
                    options.append(candidates)
                best_group = max(options, key=self._score_anchor_candidate_group)
                filtered = sorted(best_group, key=lambda item: (item[1].top, item[1].left))
            else:
                filtered = [item for item in candidates if item[1].left <= threshold] or candidates

        if filtered and all(self._is_formula_heavy_line(item[1].text) for item in filtered):
            filtered = sorted(
                filtered,
                key=lambda item: (
                    int(str(item[2][0]).strip()) if str(item[2][0]).strip().isdigit() else 999,
                    item[1].top,
                    item[1].left,
                ),
            )
        else:
            filtered = sorted(filtered, key=lambda item: (item[1].top, item[1].left))

        anchors: List[QuestionAnchor] = []
        for index, line, label in filtered:
            question_no, question_label_raw = label
            if anchors:
                previous = anchors[-1]
                if (
                    previous.question_no == question_no
                    and abs(previous.line.top - line.top)
                    <= max(previous.line.height, line.height) * 1.5
                ):
                    continue

            anchors.append(
                QuestionAnchor(
                    line_index=index,
                    question_no=question_no,
                    question_label_raw=question_label_raw,
                    line=line,
                )
            )

        if expected_question_numbers:
            anchors = self._align_anchors_to_expected_numbers(anchors, expected_question_numbers)
        else:
            anchors = self._select_best_anchor_sequence(anchors)
        return self._repair_anchor_sequence(anchors)

    def _recover_gap_weak_anchors(
        self,
        section_lines: Sequence[OCRLine],
        anchors: Sequence[QuestionAnchor],
        zone_left: int,
    ) -> List[QuestionAnchor]:
        if len(anchors) < 2:
            return list(anchors)

        local_right = max((line.right for line in section_lines), default=zone_left)
        local_width = max(local_right - zone_left, 1)
        left_tolerance = max(72, int(local_width * 0.28))

        recovered: List[QuestionAnchor] = []
        for index, anchor in enumerate(anchors[:-1]):
            recovered.append(anchor)
            next_anchor = anchors[index + 1]
            try:
                current_no = int(str(anchor.question_no).strip())
                next_no = int(str(next_anchor.question_no).strip())
            except (TypeError, ValueError):
                continue

            if next_no - current_no <= 1:
                continue

            used_indices: set[int] = set()
            for expected_no in range(current_no + 1, next_no):
                candidate_line_index: Optional[int] = None
                candidate_line: Optional[OCRLine] = None

                for line_index in range(anchor.line_index + 1, next_anchor.line_index):
                    if line_index in used_indices:
                        continue
                    line = section_lines[line_index]
                    if line.left > zone_left + left_tolerance:
                        continue
                    if not self._extract_weak_question_label(line.text, expected_no=expected_no):
                        continue
                    candidate_line_index = line_index
                    candidate_line = line
                    break

                if candidate_line_index is None or candidate_line is None:
                    continue

                used_indices.add(candidate_line_index)
                recovered.append(
                    QuestionAnchor(
                        line_index=candidate_line_index,
                        question_no=str(expected_no),
                        question_label_raw=str(expected_no),
                        line=candidate_line,
                        force_use_label=True,
                        recovery_reason="weak_gap_anchor",
                    )
                )

        recovered.append(anchors[-1])
        recovered.sort(
            key=lambda item: (
                item.line_index,
                int(str(item.question_no).strip()) if str(item.question_no).strip().isdigit() else 999,
            )
        )
        return recovered

    def _recover_gap_synthetic_anchors(
        self,
        section_lines: Sequence[OCRLine],
        anchors: Sequence[QuestionAnchor],
    ) -> List[QuestionAnchor]:
        if len(anchors) < 2:
            return list(anchors)

        recovered: List[QuestionAnchor] = []
        for index, anchor in enumerate(anchors[:-1]):
            recovered.append(anchor)
            next_anchor = anchors[index + 1]
            try:
                current_no = int(str(anchor.question_no).strip())
                next_no = int(str(next_anchor.question_no).strip())
            except (TypeError, ValueError):
                continue

            missing_numbers = list(range(current_no + 1, next_no))
            if not missing_numbers:
                continue

            indexed_orphans = [
                (line_index, section_lines[line_index])
                for line_index in range(anchor.line_index + 1, next_anchor.line_index)
                if section_lines[line_index].text.strip()
                and not self._extract_section_index_raw(section_lines[line_index].text)
                and not self._is_figure_caption(section_lines[line_index].text)
            ]
            if not indexed_orphans:
                continue

            clusters = self._split_line_clusters(indexed_orphans)
            if not clusters:
                continue

            if len(clusters) >= len(missing_numbers):
                selected_clusters = clusters[: len(missing_numbers)]
            elif len(missing_numbers) == 1:
                selected_clusters = [max(clusters, key=lambda items: len(items))]
            else:
                selected_clusters = []

            for missing_no, cluster in zip(missing_numbers, selected_clusters):
                line_index, line = cluster[0]
                recovered.append(
                    QuestionAnchor(
                        line_index=line_index,
                        question_no=str(missing_no),
                        question_label_raw=str(missing_no),
                        line=line,
                        force_use_label=True,
                        recovery_reason="synthetic_gap_anchor",
                    )
                )

        recovered.append(anchors[-1])
        recovered.sort(
            key=lambda item: (
                item.line_index,
                int(str(item.question_no).strip()) if str(item.question_no).strip().isdigit() else 999,
            )
        )
        return recovered

    def _recover_expected_tail_anchors(
        self,
        section_lines: Sequence[OCRLine],
        anchors: Sequence[QuestionAnchor],
        expected_question_numbers: Optional[Sequence[int]],
    ) -> List[QuestionAnchor]:
        expected_values = self._coerce_question_number_list(expected_question_numbers)
        if not anchors or not expected_values:
            return list(anchors)

        try:
            last_anchor_no = int(str(anchors[-1].question_no).strip())
        except (TypeError, ValueError):
            return list(anchors)

        trailing_numbers = [number for number in expected_values if number > last_anchor_no]
        if not trailing_numbers:
            return list(anchors)

        indexed_orphans = [
            (line_index, section_lines[line_index])
            for line_index in range(anchors[-1].line_index + 1, len(section_lines))
            if section_lines[line_index].text.strip()
            and not self._extract_section_index_raw(section_lines[line_index].text)
            and not self._is_figure_caption(section_lines[line_index].text)
        ]
        if not indexed_orphans:
            return list(anchors)

        clusters = self._split_line_clusters(indexed_orphans)
        if not clusters:
            return list(anchors)
        if len(clusters) < len(trailing_numbers) and len(trailing_numbers) > 1:
            return list(anchors)

        selected_clusters = (
            clusters[: len(trailing_numbers)]
            if len(clusters) >= len(trailing_numbers)
            else [max(clusters, key=lambda items: len(items))]
        )

        recovered = list(anchors)
        for question_no, cluster in zip(trailing_numbers, selected_clusters):
            line_index, line = cluster[0]
            recovered.append(
                QuestionAnchor(
                    line_index=line_index,
                    question_no=str(question_no),
                    question_label_raw=str(question_no),
                    line=line,
                    force_use_label=True,
                    recovery_reason="synthetic_gap_anchor",
                )
            )

        recovered.sort(
            key=lambda item: (
                item.line_index,
                int(str(item.question_no).strip()) if str(item.question_no).strip().isdigit() else 999,
            )
        )
        return recovered

    def _recover_declared_count_tail_anchors(
        self,
        section_lines: Sequence[OCRLine],
        anchors: Sequence[QuestionAnchor],
        declared_count: Optional[int],
    ) -> List[QuestionAnchor]:
        if declared_count is None or not anchors:
            return list(anchors)

        try:
            declared_total = int(str(declared_count).strip())
        except (TypeError, ValueError, AttributeError):
            return list(anchors)
        if declared_total <= 0:
            return list(anchors)

        numeric_anchor_values: List[int] = []
        for anchor in anchors:
            try:
                numeric_anchor_values.append(int(str(anchor.question_no).strip()))
            except (TypeError, ValueError):
                continue
        if not numeric_anchor_values:
            return list(anchors)
        if max(numeric_anchor_values) > declared_total or min(numeric_anchor_values) < 1:
            return list(anchors)

        trailing_numbers = [
            number
            for number in range(max(numeric_anchor_values) + 1, declared_total + 1)
            if number not in numeric_anchor_values
        ]
        if not trailing_numbers:
            return list(anchors)

        indexed_orphans = [
            (line_index, section_lines[line_index])
            for line_index in range(anchors[-1].line_index + 1, len(section_lines))
            if section_lines[line_index].text.strip()
            and not self._extract_section_index_raw(section_lines[line_index].text)
            and not self._is_figure_caption(section_lines[line_index].text)
        ]
        if not indexed_orphans:
            return list(anchors)

        clusters = self._split_line_clusters(indexed_orphans)
        if not clusters:
            return list(anchors)
        if len(clusters) < len(trailing_numbers) and len(trailing_numbers) > 1:
            return list(anchors)

        selected_clusters = (
            clusters[: len(trailing_numbers)]
            if len(clusters) >= len(trailing_numbers)
            else [max(clusters, key=lambda items: len(items))]
        )

        recovered = list(anchors)
        for question_no, cluster in zip(trailing_numbers, selected_clusters):
            line_index, line = cluster[0]
            recovered.append(
                QuestionAnchor(
                    line_index=line_index,
                    question_no=str(question_no),
                    question_label_raw=str(question_no),
                    line=line,
                    force_use_label=True,
                    recovery_reason="synthetic_gap_anchor",
                )
            )

        recovered.sort(
            key=lambda item: (
                item.line_index,
                int(str(item.question_no).strip()) if str(item.question_no).strip().isdigit() else 999,
            )
        )
        return recovered

    def _recover_missing_question_anchors(
        self,
        section_lines: Sequence[OCRLine],
        anchors: Sequence[QuestionAnchor],
        zone_left: int,
        *,
        expected_question_numbers: Optional[Sequence[int]] = None,
        declared_count: Optional[int] = None,
    ) -> List[QuestionAnchor]:
        recovered = self._recover_formula_prefixed_declared_anchors(
            section_lines,
            anchors,
            declared_count,
        )
        inferred_expected_numbers = self._coerce_question_number_list(expected_question_numbers)
        if not inferred_expected_numbers:
            inferred_expected_numbers = self._infer_expected_question_numbers_from_declared_count(
                recovered,
                declared_count,
            )

        recovered = self._recover_gap_weak_anchors(section_lines, recovered, zone_left)
        recovered = self._recover_gap_synthetic_anchors(section_lines, recovered)
        recovered = self._recover_expected_tail_anchors(
            section_lines,
            recovered,
            inferred_expected_numbers,
        )
        recovered = self._recover_declared_count_tail_anchors(
            section_lines,
            recovered,
            declared_count,
        )
        return self._repair_anchor_sequence(recovered)

    def _recover_sectionless_continuation_anchors(
        self,
        section_lines: Sequence[OCRLine],
        *,
        section_state: Optional[Dict[str, Any]],
    ) -> List[QuestionAnchor]:
        if not section_state or not section_state.get("entered"):
            return []

        try:
            last_question_no = int(str(section_state.get("last_question_no")).strip())
        except (TypeError, ValueError, AttributeError):
            last_question_no = None

        declared_count = section_state.get("declared_count")
        try:
            declared_total = int(str(declared_count).strip()) if declared_count is not None else None
        except (TypeError, ValueError, AttributeError):
            declared_total = None

        detected_numbers: List[int] = []
        for number in section_state.get("detected_numbers", []) or []:
            try:
                detected_numbers.append(int(str(number).strip()))
            except (TypeError, ValueError, AttributeError):
                continue

        remaining_needed = None
        if declared_total is not None:
            remaining_needed = max(declared_total - len(set(detected_numbers)), 0)

        indexed_lines = [
            (line_index, line)
            for line_index, line in enumerate(section_lines)
            if line.text.strip()
            and not self._extract_section_index_raw(line.text)
            and not self._is_figure_caption(line.text)
        ]
        if not indexed_lines:
            return []

        clusters = self._split_line_clusters(indexed_lines)
        if not clusters:
            return []
        viable_clusters = [
            cluster
            for cluster in clusters
            if self._is_viable_continuation_cluster(cluster)
        ]
        if not viable_clusters:
            return []

        detected_set = set(detected_numbers)
        caption_numbers = self._extract_question_numbers_from_figure_captions(section_lines)
        suggested_numbers = [
            number
            for number in caption_numbers
            if (last_question_no is None or number > last_question_no)
            and number not in detected_set
        ]
        if suggested_numbers:
            target_no = suggested_numbers[0]
            line_index, line = viable_clusters[-1][0]
            return [
                QuestionAnchor(
                    line_index=line_index,
                    question_no=str(target_no),
                    question_label_raw=str(target_no),
                    line=line,
                    force_use_label=True,
                    recovery_reason="synthetic_continuation_anchor",
                )
            ]

        if remaining_needed is not None and remaining_needed <= 0:
            return []

        if remaining_needed is None:
            if last_question_no is None or len(viable_clusters) < 1:
                return []
            synthetic_count = 1
        else:
            synthetic_count = min(remaining_needed, len(viable_clusters))
            if synthetic_count <= 0:
                return []

        selected_clusters = viable_clusters[-synthetic_count:]
        if not selected_clusters:
            return []

        start_no = last_question_no + 1 if last_question_no is not None else 1
        anchors: List[QuestionAnchor] = []
        for offset, cluster in enumerate(selected_clusters):
            synthetic_no = start_no + offset
            if declared_total is not None and synthetic_no > declared_total:
                break
            line_index, line = cluster[0]
            anchors.append(
                QuestionAnchor(
                    line_index=line_index,
                    question_no=str(synthetic_no),
                    question_label_raw=str(synthetic_no),
                    line=line,
                    force_use_label=True,
                    recovery_reason="synthetic_continuation_anchor",
                )
            )

        return anchors

    def _trim_overlapping_continuation_anchors(
        self,
        anchors: Sequence[QuestionAnchor],
        *,
        section_state: Optional[Dict[str, Any]],
    ) -> List[QuestionAnchor]:
        if not anchors or not section_state:
            return list(anchors)

        detected_values: List[int] = []
        for value in section_state.get("detected_numbers", []) or []:
            try:
                detected_values.append(int(str(value).strip()))
            except (TypeError, ValueError, AttributeError):
                continue
        if not detected_values:
            return list(anchors)

        max_detected = max(detected_values)
        detected_set = set(detected_values)
        trimmed = list(anchors)
        while trimmed:
            try:
                current_no = int(str(trimmed[0].question_no).strip())
            except (TypeError, ValueError):
                break
            if current_no in detected_set or current_no <= max_detected:
                trimmed = trimmed[1:]
                continue
            break
        return trimmed

    def _recover_leading_calculation_anchors(
        self,
        section_lines: List[OCRLine],
        anchors: List[QuestionAnchor],
        section_heading_text: str,
    ) -> Tuple[List[OCRLine], List[QuestionAnchor]]:
        if not anchors:
            return section_lines, anchors

        try:
            first_anchor_no = int(str(anchors[0].question_no).strip())
        except (TypeError, ValueError):
            return section_lines, anchors

        missing_before = first_anchor_no - 1
        if missing_before <= 0 or anchors[0].line_index <= 0:
            return section_lines, anchors

        leading_candidates = [
            (index, line)
            for index, line in enumerate(section_lines[: anchors[0].line_index])
            if (
                line.text.strip()
                and not self._extract_question_label(line.text)
                and not self._extract_section_index_raw(line.text)
                and not self._is_figure_caption(line.text)
                and not self._is_preamble_noise_line(line.text)
                and self._is_short_calculation_block_line(line.text)
            )
        ]
        leading_clusters = self._split_line_clusters(leading_candidates) if leading_candidates else []
        if len(leading_clusters) != missing_before:
            generic_candidates = [
                (index, line)
                for index, line in enumerate(section_lines[: anchors[0].line_index])
                if (
                    line.text.strip()
                    and not self._extract_question_label(line.text)
                    and not self._extract_section_index_raw(line.text)
                    and not self._is_figure_caption(line.text)
                    and not self._is_preamble_noise_line(line.text)
                )
            ]
            if not generic_candidates:
                return section_lines, anchors
            leading_clusters = self._split_line_clusters(generic_candidates)
            if len(leading_clusters) != missing_before:
                return section_lines, anchors

        updated_lines = list(section_lines)
        synthetic_anchors: List[QuestionAnchor] = []
        start_no = first_anchor_no - missing_before
        for offset, cluster in enumerate(leading_clusters):
            line_index, line = cluster[0]
            synthetic_no = str(start_no + offset)
            synthetic_text = f"{synthetic_no}. {line.text}"
            synthetic_line = OCRLine(
                text=synthetic_text,
                left=line.left,
                top=line.top,
                width=line.width,
                height=line.height,
            )
            updated_lines[line_index] = synthetic_line
            synthetic_anchors.append(
                QuestionAnchor(
                    line_index=line_index,
                    question_no=synthetic_no,
                    question_label_raw=f"{synthetic_no}.",
                    line=synthetic_line,
                )
            )

        synthetic_tail_index = leading_clusters[-1][-1][0]
        if synthetic_anchors and synthetic_tail_index + 1 < anchors[0].line_index:
            pre_anchor_lines = [
                (index, line)
                for index, line in enumerate(section_lines[synthetic_tail_index + 1 : anchors[0].line_index], start=synthetic_tail_index + 1)
                if (
                    line.text.strip()
                    and not self._extract_question_label(line.text)
                    and not self._extract_section_index_raw(line.text)
                    and not self._is_figure_caption(line.text)
                )
            ]
            if pre_anchor_lines:
                last_pre_anchor_line = pre_anchor_lines[-1][1]
                if anchors[0].line.top - last_pre_anchor_line.bottom <= max(48, anchors[0].line.height * 2):
                    anchors = [
                        QuestionAnchor(
                            line_index=pre_anchor_lines[0][0],
                            question_no=anchors[0].question_no,
                            question_label_raw=anchors[0].question_label_raw,
                            line=anchors[0].line,
                            force_use_label=True,
                            recovery_reason="pre_anchor_merge",
                        ),
                        *anchors[1:],
                    ]

        return updated_lines, synthetic_anchors + anchors

    @staticmethod
    def _is_preamble_noise_line(text: str) -> bool:
        compact = re.sub(r"\s+", "", str(text or ""))
        if not compact:
            return True

        noise_keywords = (
            "姓名",
            "班级",
            "学校",
            "考号",
            "满分",
            "时间",
            "建议时长",
            "考试",
            "真卷",
            "模拟卷",
            "错题笔记",
            "答案",
            "填空题",
            "选择题",
            "计算题",
            "应用题",
            "解答题",
        )
        return any(keyword in compact for keyword in noise_keywords)

    @staticmethod
    def _is_short_calculation_block_line(text: str) -> bool:
        normalized = " ".join(str(text or "").split())
        if not normalized:
            return False

        compact = normalized.replace(" ", "")
        chinese_hits = len(re.findall(r"[\u4e00-\u9fff]", compact))
        digit_hits = len(re.findall(r"\d", compact))
        formula_operator_hits = len(re.findall(r"[+\-=\u00D7\u00F7xX*/]", compact))
        ratio_operator_hits = len(re.findall(r"[:\uFF1A]", compact))
        if digit_hits == 0:
            return False
        if re.fullmatch(r"[=＝]?\d+(?:\.\d+)?", compact):
            return True
        if formula_operator_hits >= 1 and chinese_hits <= 4:
            return True
        if ratio_operator_hits >= 1 and formula_operator_hits == 0 and chinese_hits <= 1:
            return True
        return False

    def _recover_pre_anchor_content_lines(
        self,
        section_lines: Sequence[OCRLine],
        anchors: Sequence[QuestionAnchor],
    ) -> List[QuestionAnchor]:
        if len(anchors) <= 1:
            return list(anchors)

        adjusted_anchors = list(anchors)
        for index in range(1, len(adjusted_anchors)):
            previous_anchor = adjusted_anchors[index - 1]
            current_anchor = adjusted_anchors[index]
            if current_anchor.line_index <= previous_anchor.line_index + 1:
                continue

            candidate_block: List[Tuple[int, OCRLine]] = []
            next_top = section_lines[current_anchor.line_index].top
            next_height = section_lines[current_anchor.line_index].height
            for line_index in range(current_anchor.line_index - 1, previous_anchor.line_index, -1):
                line = section_lines[line_index]
                if (
                    not line.text.strip()
                    or self._extract_question_label(line.text)
                    or self._extract_section_index_raw(line.text)
                    or self._is_figure_caption(line.text)
                ):
                    break
                gap = next_top - line.bottom
                gap_threshold = max(72, int(max(line.height, next_height) * 2.2))
                if gap > gap_threshold:
                    break
                candidate_block.append((line_index, line))
                next_top = line.top
                next_height = line.height

            if not candidate_block:
                continue

            candidate_block.reverse()
            previous_bottom = section_lines[previous_anchor.line_index].bottom
            separation_threshold = max(
                96,
                int(max(candidate_block[0][1].height, section_lines[previous_anchor.line_index].height) * 2.4),
            )
            if candidate_block[0][1].top - previous_bottom <= separation_threshold:
                continue

            adjusted_anchors[index] = QuestionAnchor(
                line_index=candidate_block[0][0],
                question_no=current_anchor.question_no,
                question_label_raw=current_anchor.question_label_raw,
                line=current_anchor.line,
                force_use_label=True,
                recovery_reason="pre_anchor_merge",
            )

        return adjusted_anchors

    @staticmethod
    def _find_missing_numbers(anchor_numbers: Sequence[str]) -> List[str]:
        numeric_values: List[int] = []
        for value in anchor_numbers:
            try:
                numeric_values.append(int(str(value).strip()))
            except (TypeError, ValueError):
                return []

        if len(numeric_values) < 2:
            return []

        start = min(numeric_values)
        end = max(numeric_values)
        present = set(numeric_values)
        return [str(number) for number in range(start, end + 1) if number not in present]

    def _section_has_unassigned_anchor(
        self,
        lines: Sequence[OCRLine],
        anchors: Sequence[QuestionAnchor],
        zone_left: int,
    ) -> bool:
        if len(lines) <= 1:
            return False

        anchor_indices = {anchor.line_index for anchor in anchors}
        local_right = max((line.right for line in lines), default=zone_left)
        local_width = max(local_right - zone_left, 1)
        tolerance = max(42, int(local_width * 0.2))

        for index, line in enumerate(lines):
            if index in anchor_indices:
                continue
            if self._extract_section_index_raw(line.text) or self._is_figure_caption(line.text):
                continue
            if self.TOP_LEVEL_PAREN_NO_PATTERN.match(line.text) and not self.TOP_LEVEL_PLAIN_NO_PATTERN.match(line.text):
                continue
            if self._extract_question_label(line.text) and line.left <= zone_left + tolerance:
                return True
        return False

    def _has_embedded_followup_anchor(
        self,
        lines: Sequence[OCRLine],
        zone_left: int,
    ) -> bool:
        if len(lines) <= 1:
            return False

        local_right = max((line.right for line in lines), default=zone_left)
        local_width = max(local_right - zone_left, 1)
        tolerance = max(42, int(local_width * 0.2))

        for line in lines[1:]:
            if self._extract_section_index_raw(line.text) or self._is_figure_caption(line.text):
                continue
            if self.TOP_LEVEL_PAREN_NO_PATTERN.match(line.text) and not self.TOP_LEVEL_PLAIN_NO_PATTERN.match(line.text):
                continue
            if self._extract_question_label(line.text) and line.left <= zone_left + tolerance:
                return True
        return False

    def _build_question_count_audit(
        self,
        *,
        page_no: int,
        zone_key: str,
        section_index_raw: str,
        anchors: Sequence[QuestionAnchor],
        declared_count: Optional[int],
        layout_type: str,
        secondary_pass_used: bool,
        has_embedded_anchor: bool = False,
        body_line_count: int = 0,
        continuation_skipped: bool = False,
    ) -> QuestionCountAudit:
        anchor_numbers = [anchor.question_no for anchor in anchors]
        duplicates = [
            number
            for number, count in Counter(anchor_numbers).items()
            if count > 1
        ]
        missing_numbers = self._find_missing_numbers(anchor_numbers)

        mismatch_reasons: List[str] = []
        if declared_count is not None and declared_count != len(anchor_numbers):
            mismatch_reasons.append(f"卷面声明 {declared_count} 题，识别 {len(anchor_numbers)} 题")
        if missing_numbers:
            mismatch_reasons.append(f"题号不连续，缺少 {'/'.join(missing_numbers[:8])}")
        if duplicates:
            mismatch_reasons.append(f"题号重复 {'/'.join(duplicates[:8])}")
        if body_line_count > 0 and not anchor_numbers:
            mismatch_reasons.append("section 存在正文但未识别到题号")
        if has_embedded_anchor and (missing_numbers or duplicates or declared_count is not None):
            mismatch_reasons.append("题块内混入疑似后续题号")
        if continuation_skipped:
            mismatch_reasons.append("同一 section 的跨页续接被跳过")

        return QuestionCountAudit(
            page_no=page_no,
            zone_key=zone_key,
            section_index_raw=section_index_raw,
            detected_count=len(anchor_numbers),
            declared_count=declared_count,
            anchor_numbers=anchor_numbers,
            missing_numbers=missing_numbers,
            duplicate_numbers=duplicates,
            secondary_pass_used=secondary_pass_used,
            mismatch_reason="；".join(mismatch_reasons),
            layout_type=layout_type,
        )

    @staticmethod
    def _audit_penalty(audit: QuestionCountAudit) -> int:
        penalty = 0
        if audit.declared_count is not None and audit.declared_count != audit.detected_count:
            penalty += abs(audit.declared_count - audit.detected_count) * 3
        penalty += len(audit.missing_numbers) * 3
        penalty += len(audit.duplicate_numbers) * 3
        if audit.detected_count == 0 and audit.mismatch_reason:
            penalty += 12
            if audit.declared_count is not None:
                penalty += 6
        if "section 存在正文但未识别到题号" in audit.mismatch_reason:
            penalty += 8
        if "同一 section 的跨页续接被跳过" in audit.mismatch_reason:
            penalty += 6
        if "题块内混入疑似后续题号" in audit.mismatch_reason:
            penalty += 4
        if audit.mismatch_reason and not (audit.missing_numbers or audit.duplicate_numbers):
            penalty += 2
        return penalty

    def _crop_region_image(
        self,
        image_path: str,
        bbox: Dict[str, int],
        suffix: str,
    ) -> Tuple[Optional[str], int, int]:
        try:
            source_path = Path(image_path)
            output_root = source_path.parent
            if output_root.name == "temp_images":
                output_root = output_root.parent
            crop_dir = output_root / "section_crops"
            crop_dir.mkdir(parents=True, exist_ok=True)

            safe_suffix = re.sub(r"[^0-9A-Za-z_-]+", "_", suffix).strip("_") or "section"
            output_path = crop_dir / f"{source_path.stem}_{safe_suffix}.jpg"

            with Image.open(image_path) as image:
                margin_x = max(24, int(image.width * 0.012))
                margin_y = max(24, int(image.height * 0.012))
                left = max(bbox["left"] - margin_x, 0)
                top = max(bbox["top"] - margin_y, 0)
                right = min(bbox["left"] + bbox["width"] + margin_x, image.width)
                bottom = min(bbox["top"] + bbox["height"] + margin_y, image.height)
                if right <= left or bottom <= top:
                    return None, 0, 0

                image.crop((left, top, right, bottom)).save(output_path, format="JPEG", quality=95)

            return str(output_path), left, top
        except Exception as exc:
            logger.warning("OCR section crop failed suffix=%s: %s", suffix, exc)
            return None, 0, 0

    async def _recover_formula_leading_anchors_from_crop(
        self,
        crop_path: str,
        adjusted_lines: List[OCRLine],
        anchors: List[QuestionAnchor],
    ) -> Tuple[List[OCRLine], List[QuestionAnchor]]:
        if not anchors:
            return adjusted_lines, anchors

        try:
            first_anchor_no = int(str(anchors[0].question_no).strip())
        except (TypeError, ValueError):
            return adjusted_lines, anchors

        missing_before = first_anchor_no - 1
        if missing_before <= 0:
            return adjusted_lines, anchors

        try:
            section_top = min((line.top for line in adjusted_lines), default=anchors[0].line.top)
            probe_bottom = max(
                int(anchors[0].line.top - section_top + anchors[0].line.height * 1.5),
                160,
            )
            formula_image_path = crop_path
            with Image.open(crop_path) as image:
                probe_bottom = min(probe_bottom, image.height)
                if 0 < probe_bottom < image.height:
                    probe_path = str(Path(crop_path).with_name(f"{Path(crop_path).stem}_formula_probe.jpg"))
                    image.crop((0, 0, image.width, probe_bottom)).save(probe_path, format="JPEG", quality=95)
                    formula_image_path = probe_path

            formula_result = await self._recognize_formula(self._image_to_base64(formula_image_path))
        except Exception as exc:
            logger.warning("OCR formula recovery failed crop=%s: %s", crop_path, exc)
            return adjusted_lines, anchors

        formula_texts = self._extract_formula_texts(formula_result)
        if not formula_texts:
            return adjusted_lines, anchors

        existing_numbers = {str(anchor.question_no).strip() for anchor in anchors}
        recovered_specs: List[Tuple[int, str]] = []
        for formula_text in formula_texts:
            if len(recovered_specs) >= missing_before:
                break
            match = re.match(r"^\s*(\d{1,2})\s*[.．]", formula_text)
            if not match:
                continue
            number = int(match.group(1))
            if number <= 0 or number >= first_anchor_no or str(number) in existing_numbers:
                continue
            recovered_specs.append((number, formula_text))
            existing_numbers.add(str(number))

        if not recovered_specs:
            missing_numbers = [
                number
                for number in range(1, first_anchor_no)
                if str(number) not in existing_numbers
            ]
            for index, formula_text in enumerate(formula_texts[: len(missing_numbers)]):
                number = missing_numbers[index]
                recovered_specs.append((number, f"{number}. {formula_text}"))
                existing_numbers.add(str(number))

        if not recovered_specs:
            return adjusted_lines, anchors

        reference_line = anchors[0].line
        base_left = min((line.left for line in adjusted_lines), default=reference_line.left)
        base_width = max(reference_line.width, 320)
        step_height = max(reference_line.height + 12, 36)

        synthetic_lines = list(adjusted_lines)
        for offset, (number, formula_text) in enumerate(sorted(recovered_specs, key=lambda item: item[0])):
            synthetic_text = (
                formula_text
                if re.match(r"^\s*(\d{1,2})\s*[.．]", formula_text)
                else f"{number}. {formula_text}"
            )
            synthetic_lines.append(
                OCRLine(
                    text=synthetic_text,
                    left=base_left,
                    top=max(reference_line.top - step_height * (len(recovered_specs) - offset), 0),
                    width=base_width,
                    height=reference_line.height,
                )
            )

        synthetic_lines.sort(key=lambda item: (item.top, item.left))
        return synthetic_lines, self._detect_question_anchors(synthetic_lines, base_left)

    async def _secondary_parse_section(
        self,
        section: SectionBlock,
        *,
        image_path: str,
        page_no: int,
    ) -> Optional[Tuple[List[OCRLine], List[QuestionAnchor], QuestionCountAudit]]:
        crop_path, offset_left, offset_top = self._crop_region_image(
            image_path,
            section.bbox,
            f"p{page_no}_{section.zone_key}_{section.section_index_raw or 'section'}",
        )
        if not crop_path:
            return None

        try:
            crop_result = await self._recognize_text(self._image_to_base64(crop_path))
            crop_lines = self._extract_ocr_lines(crop_result)
            adjusted_lines = [
                OCRLine(
                    text=line.text,
                    left=line.left + offset_left,
                    top=line.top + offset_top,
                    width=line.width,
                    height=line.height,
                )
                for line in crop_lines
            ]
            adjusted_lines = [
                line for line in adjusted_lines if not self._extract_section_index_raw(line.text)
            ]
            adjusted_lines, resolved_declared_count = self._consume_leading_section_metadata(
                adjusted_lines,
                section.declared_count,
            )
            expected_question_numbers = self._extract_expected_question_numbers(
                section.heading_text,
                adjusted_lines,
            )
            if resolved_declared_count is None and expected_question_numbers:
                resolved_declared_count = len(expected_question_numbers)
            section.declared_count = resolved_declared_count
            anchors = self._detect_question_anchors(
                adjusted_lines,
                section.left,
                expected_question_numbers=expected_question_numbers,
                allow_parenthesized=not bool(
                    section.section_index_raw
                    and not str(section.heading_text or "").strip()
                    and not section.is_headingless_prefix
                ),
            )
            adjusted_lines, anchors = await self._recover_formula_leading_anchors_from_crop(
                crop_path,
                adjusted_lines,
                anchors,
            )
            anchors = self._recover_missing_question_anchors(
                adjusted_lines,
                anchors,
                section.left,
                expected_question_numbers=expected_question_numbers,
                declared_count=resolved_declared_count,
            )
            audit = self._build_question_count_audit(
                page_no=page_no,
                zone_key=section.zone_key,
                section_index_raw=section.section_index_raw,
                anchors=anchors,
                declared_count=resolved_declared_count,
                layout_type=section.layout_type,
                secondary_pass_used=True,
                has_embedded_anchor=self._section_has_unassigned_anchor(adjusted_lines, anchors, section.left),
                body_line_count=len([line for line in adjusted_lines if line.text.strip()]),
            )
            return adjusted_lines, anchors, audit
        except Exception as exc:
            logger.warning(
                "OCR secondary pass failed page=%s zone=%s section=%s: %s",
                page_no,
                section.zone_key,
                section.section_index_raw,
                exc,
            )
            return None

    def _choose_better_section_result(
        self,
        *,
        primary_lines: List[OCRLine],
        primary_anchors: List[QuestionAnchor],
        primary_audit: QuestionCountAudit,
        secondary_result: Optional[Tuple[List[OCRLine], List[QuestionAnchor], QuestionCountAudit]],
    ) -> Tuple[List[OCRLine], List[QuestionAnchor], QuestionCountAudit]:
        if secondary_result is None:
            return primary_lines, primary_anchors, primary_audit

        secondary_lines, secondary_anchors, secondary_audit = secondary_result
        if primary_anchors and not secondary_anchors:
            primary_audit.secondary_pass_used = True
            return primary_lines, primary_anchors, primary_audit
        if secondary_anchors and not primary_anchors:
            return secondary_lines, secondary_anchors, secondary_audit

        primary_penalty = self._audit_penalty(primary_audit)
        secondary_penalty = self._audit_penalty(secondary_audit)

        if (
            secondary_penalty < primary_penalty
            or (
                secondary_penalty == primary_penalty
                and len(secondary_anchors) > len(primary_anchors)
            )
        ):
            return secondary_lines, secondary_anchors, secondary_audit

        primary_audit.secondary_pass_used = True
        return primary_lines, primary_anchors, primary_audit

    def _build_report_warnings(self, audits: Sequence[QuestionCountAudit]) -> List[str]:
        if not audits:
            return []

        problematic_messages: List[str] = []
        grouped_audits: Dict[str, List[QuestionCountAudit]] = {}
        direct_audits: List[QuestionCountAudit] = []

        for audit in audits:
            section_key = str(audit.section_index_raw or "").strip()
            if section_key:
                grouped_audits.setdefault(section_key, []).append(audit)
            else:
                direct_audits.append(audit)

        for audit in direct_audits:
            mismatch_reason = str(audit.mismatch_reason or "").strip()
            if not mismatch_reason:
                continue
            if (
                not audit.anchor_numbers
                and "section 存在正文但未识别到题号" in mismatch_reason
                and audit.layout_type in {"dual_column", "multi_zone"}
                and any(
                    other.page_no == audit.page_no and getattr(other, "anchor_numbers", [])
                    for other in audits
                )
            ):
                continue
            problematic_messages.append(f"第 {audit.page_no} 页：{mismatch_reason}")

        for section_key, items in grouped_audits.items():
            if len(items) == 1 and items[0].declared_count is None:
                mismatch_reason = str(items[0].mismatch_reason or "").strip()
                if mismatch_reason:
                    problematic_messages.append(f"第 {items[0].page_no} 页 {section_key} 部分：{mismatch_reason}")
                continue

            declared_count = next(
                (int(item.declared_count) for item in items if item.declared_count is not None),
                None,
            )
            anchor_numbers: List[str] = []
            for item in items:
                anchor_numbers.extend(str(number).strip() for number in item.anchor_numbers if str(number).strip())

            duplicates = [
                number
                for number, count in Counter(anchor_numbers).items()
                if count > 1
            ]
            missing_numbers = self._find_missing_numbers(anchor_numbers)

            mismatch_reasons: List[str] = []
            if declared_count is not None and declared_count != len(anchor_numbers):
                mismatch_reasons.append(f"卷面声明 {declared_count} 题，识别 {len(anchor_numbers)} 题")
            if missing_numbers:
                mismatch_reasons.append(f"题号不连续，缺少 {'/'.join(missing_numbers[:8])}")
            if duplicates:
                mismatch_reasons.append(f"题号重复 {'/'.join(duplicates[:8])}")

            if mismatch_reasons:
                has_empty_section = any(
                    "section 存在正文但未识别到题号" in str(item.mismatch_reason or "")
                    for item in items
                )
                skipped_continuation = any(
                    "同一 section 的跨页续接被跳过" in str(item.mismatch_reason or "")
                    for item in items
                )
                embedded_followup = any(
                    "题块内混入疑似后续题号" in str(item.mismatch_reason or "")
                    for item in items
                )
                if has_empty_section:
                    mismatch_reasons.append("section 存在正文但未识别到题号")
                if skipped_continuation:
                    mismatch_reasons.append("同一 section 的跨页续接被跳过")
                if embedded_followup:
                    mismatch_reasons.append("题块内混入疑似后续题号")

            if mismatch_reasons:
                problematic_messages.append(
                    f"{section_key} 部分：{'；'.join(dict.fromkeys(mismatch_reasons))}"
                )

        if not problematic_messages:
            return []

        warnings = ["OCR 题数与卷面声明或题号连续性不完全一致，当前报告需复核。"]
        for message in problematic_messages[:4]:
            warnings.append(message)
        return list(dict.fromkeys(warnings))

    @staticmethod
    def _is_decorative_sidebar_line(line: OCRLine) -> bool:
        text = str(line.text or "").strip()
        if not text:
            return True
        if line.height >= 160 and line.height >= int(line.width * 0.4):
            return True
        if line.width <= 160 and line.height >= 120:
            return True
        return False

    def _pick_best_question_for_orphan_lines(
        self,
        orphan_lines: Sequence[OCRLine],
        *,
        page_no: int,
        page_questions: Sequence[ParsedQuestion],
        existing_questions: Sequence[ParsedQuestion],
    ) -> Optional[ParsedQuestion]:
        orphan_bbox = self._bbox_from_lines(orphan_lines)
        if not orphan_bbox:
            return None

        candidates = [
            question
            for question in [*page_questions, *existing_questions]
            if int(getattr(question, "page_no", 0) or 0) == page_no and getattr(question, "block_bbox", None)
        ]
        if not candidates:
            return page_questions[-1] if page_questions else (existing_questions[-1] if existing_questions else None)

        orphan_top = orphan_bbox["top"]
        orphan_bottom = orphan_bbox["top"] + orphan_bbox["height"]
        orphan_center = (orphan_top + orphan_bottom) / 2

        def candidate_key(question: ParsedQuestion) -> Tuple[int, float]:
            bbox = dict(question.block_bbox or {})
            question_top = int(bbox.get("top", 0) or 0)
            question_bottom = question_top + int(bbox.get("height", 0) or 0)
            overlap = max(0, min(orphan_bottom, question_bottom) - max(orphan_top, question_top))
            question_center = (question_top + question_bottom) / 2
            return overlap, -abs(question_center - orphan_center)

        return max(candidates, key=candidate_key)

    def _append_orphan_section_lines(
        self,
        lines: Sequence[OCRLine],
        *,
        page_no: int,
        page_questions: Sequence[ParsedQuestion],
        existing_questions: Sequence[ParsedQuestion],
    ) -> bool:
        orphan_lines = [
            line
            for line in lines
            if line.text.strip() and not self._is_decorative_sidebar_line(line)
        ]
        if not orphan_lines:
            return False

        target_question = self._pick_best_question_for_orphan_lines(
            orphan_lines,
            page_no=page_no,
            page_questions=page_questions,
            existing_questions=existing_questions,
        )
        if target_question is None:
            return False

        self._append_lines_to_question(
            target_question,
            orphan_lines,
            page_no=page_no,
        )
        return True

    async def _build_question_from_lines(
        self,
        block_lines: Sequence[OCRLine],
        *,
        page_no: int,
        image_path: str,
        section_index_raw: str,
        zone_left: int,
        forced_question_no: Optional[str] = None,
        forced_question_label_raw: Optional[str] = None,
        force_use_label: bool = False,
        recovery_reason: str = "",
    ) -> Tuple[Optional[ParsedQuestion], bool]:
        if not block_lines:
            return None, False

        question_text = self._normalize_question_text(block_lines)
        if not question_text:
            return None, False

        question_label = self._extract_question_label(block_lines[0].text)
        if forced_question_no and (force_use_label or not question_label):
            question_label = (
                str(forced_question_no).strip(),
                str(forced_question_label_raw or forced_question_no).strip(),
            )
        if not question_label:
            return None, True

        question_no, question_label_raw = question_label
        if force_use_label and question_text:
            visible_prefix = question_label_raw if question_label_raw.endswith((".", "．", "、")) else f"{question_no}."
            if not question_text.startswith(visible_prefix):
                question_text = f"{visible_prefix} {question_text}".strip()
        bbox = self._bbox_from_lines(block_lines)
        line_count = len(block_lines)
        question_text = self._normalize_formula_text(question_text)
        sub_item_candidates = self._detect_sub_item_candidates(block_lines)
        initial_question_type = self._detect_question_type(question_text)
        image_block_url = self._build_question_block_image(image_path, page_no, question_no, bbox)
        (
            question_text,
            formula_enhanced,
            formula_strategy,
            formula_notes,
            formula_warning_codes,
        ) = await self._maybe_enhance_formula_text(
            question_text,
            initial_question_type,
            line_count,
            image_block_url,
        )
        question_type = self._detect_question_type(question_text)
        score, score_reliable, score_source, score_reason, score_confidence = self._extract_score_details(question_text)
        visual_assessment = self._classify_visual_need(question_text, question_type, sub_item_candidates)
        parse_audit = self._build_parse_audit(
            question_text=question_text,
            question_type=question_type,
            score_reliable=score_reliable,
            score_source=score_source,
            score_reason=score_reason,
            score_confidence=score_confidence,
            bbox=bbox,
            line_count=line_count,
            image_block_url=image_block_url,
            formula_enhanced=formula_enhanced,
            formula_strategy=formula_strategy,
            formula_warning_codes=formula_warning_codes,
            visual_assessment=visual_assessment,
        )
        parse_audit.notes.extend(formula_notes)

        review_required = False
        parse_warnings: List[str] = []
        if not score_reliable:
            parse_warnings.append(f"{score_reason} 当前分值保留为 0，建议人工复核。")
            review_required = True
        if parse_audit.image_required_hint and not image_block_url:
            parse_warnings.append("题块图片裁切失败或缺失，涉及图形/表格时建议人工复核。")
            review_required = True
        if parse_audit.image_attach_recommended and not image_block_url and not parse_audit.image_required_hint:
            parse_warnings.append("该题建议附带题块图片，但当前裁图缺失，后续将按纯文本分析。")
        if "formula_api_failed" in parse_audit.warning_codes:
            parse_warnings.append("该题疑似公式密集，但公式增强识别失败，当前仍按普通 OCR 文本解析。")
            review_required = True
        if sub_item_candidates:
            parse_audit.notes.append(f"sub_items={len(sub_item_candidates)}")

        if self._has_embedded_followup_anchor(block_lines, zone_left):
            parse_warnings.append("当前题块中混入疑似后续题号，OCR 切题结果需复核。")
            parse_audit.notes.append("embedded_followup_anchor")
            parse_audit.warning_codes.append("embedded_followup_anchor")
            review_required = True
        if recovery_reason == "weak_gap_anchor":
            parse_warnings.append("OCR 弱题号恢复：按连续题号补出题号。")
            parse_audit.notes.append("weak_gap_anchor")
            review_required = True
        elif recovery_reason == "synthetic_gap_anchor":
            parse_warnings.append("OCR 缺号恢复：按断号区间补出题号。")
            parse_audit.notes.append("synthetic_gap_anchor")
            review_required = True
        elif recovery_reason == "synthetic_continuation_anchor":
            parse_warnings.append("OCR 跨页缺号恢复：按 section 连续性补出题号。")
            parse_audit.notes.append("synthetic_continuation_anchor")
            review_required = True

        question_block = QuestionBlock(
            page_no=page_no,
            bbox=bbox or {"left": 0, "top": 0, "width": 0, "height": 0},
            line_count=line_count,
            text_density=self._line_text_density(block_lines, bbox),
        )
        parse_audit.block_completeness = max(parse_audit.block_completeness, question_block.text_density)

        question = ParsedQuestion(
            question_no=question_no,
            question_type=question_type,
            raw_text=question_text,
            question_label_raw=question_label_raw,
            section_index_raw=section_index_raw,
            score=score,
            is_optional=False,
            include_in_main_score=True,
            parse_confidence=0.0,
            applicable_dims=[],
            page_no=page_no,
            image_block_url=image_block_url,
            block_bbox=bbox,
            question_block=question_block,
            parse_warnings=parse_warnings,
            parse_audit=parse_audit,
            ocr_text_version="v4.0-layout-aware",
            sub_questions=[],
            sub_item_candidates=sub_item_candidates,
        )
        question.parse_confidence = self._calculate_question_confidence(parse_audit)
        if recovery_reason:
            question.parse_confidence = min(question.parse_confidence, 0.72 if "synthetic" in recovery_reason else 0.78)
        return question, review_required

    async def _parse_page_questions(
        self,
        ocr_result: Dict[str, Any],
        *,
        page_no: int,
        image_path: str,
        existing_questions: List[ParsedQuestion],
    ) -> Tuple[List[ParsedQuestion], bool]:
        lines = self._extract_ocr_lines(ocr_result)
        if not lines:
            logger.warning("OCR 结果为空 page=%s", page_no)
            return [], False

        start_indices = self._detect_question_start_indices(lines)
        review_required = False
        page_questions: List[ParsedQuestion] = []
        current_section_index_raw = (
            str(getattr(existing_questions[-1], "section_index_raw", "") or "")
            if existing_questions
            else ""
        )
        section_heading_indices = [
            index for index, line in enumerate(lines) if self._extract_section_index_raw(line.text)
        ]

        if not start_indices:
            current_section_index_raw = self._latest_section_index_from_lines(
                lines,
                current_section_index_raw,
            )
            continuation_lines = [
                line for line in lines if not self._extract_section_index_raw(line.text)
            ]
            if existing_questions:
                if continuation_lines:
                    self._append_lines_to_question(
                        existing_questions[-1],
                        continuation_lines,
                        page_no=page_no,
                    )
                return [], True

            logger.warning("第 %s 页未识别到大题号，且没有上一题可合并。", page_no)
            return [], True

        first_start = start_indices[0]
        if first_start > 0:
            leading_lines = lines[:first_start]
            current_section_index_raw = self._latest_section_index_from_lines(
                leading_lines,
                current_section_index_raw,
            )
            continuation_lines = [
                line for line in leading_lines if not self._extract_section_index_raw(line.text)
            ]
            if continuation_lines and existing_questions:
                self._append_lines_to_question(
                    existing_questions[-1],
                    continuation_lines,
                    page_no=page_no,
                )
            review_required = True

        scan_cursor = first_start

        for position, start_index in enumerate(start_indices):
            current_section_index_raw = self._latest_section_index_from_lines(
                lines[scan_cursor:start_index],
                current_section_index_raw,
            )
            next_start_index = start_indices[position + 1] if position + 1 < len(start_indices) else len(lines)
            section_breaks = [
                index
                for index in section_heading_indices
                if start_index < index < next_start_index
            ]
            end_index = section_breaks[0] if section_breaks else next_start_index
            block_lines = [
                line
                for line in lines[start_index:end_index]
                if not self._extract_section_index_raw(line.text)
            ]
            scan_cursor = end_index
            if not block_lines:
                continue
            question_text = self._normalize_question_text(block_lines)
            if not question_text:
                continue

            question_label = self._extract_question_label(block_lines[0].text)
            if not question_label:
                review_required = True
                continue
            question_no, question_label_raw = question_label
            section_index_raw = current_section_index_raw

            bbox = self._bbox_from_lines(block_lines)
            line_count = len(block_lines)
            question_text = self._normalize_formula_text(question_text)
            sub_item_candidates = self._detect_sub_item_candidates(block_lines)
            initial_question_type = self._detect_question_type(question_text)
            image_block_url = self._build_question_block_image(image_path, page_no, question_no, bbox)
            (
                question_text,
                formula_enhanced,
                formula_strategy,
                formula_notes,
                formula_warning_codes,
            ) = await self._maybe_enhance_formula_text(
                question_text,
                initial_question_type,
                line_count,
                image_block_url,
            )
            question_type = self._detect_question_type(question_text)
            score, score_reliable, score_source, score_reason, score_confidence = self._extract_score_details(question_text)
            visual_assessment = self._classify_visual_need(question_text, question_type, sub_item_candidates)
            parse_audit = self._build_parse_audit(
                question_text=question_text,
                question_type=question_type,
                score_reliable=score_reliable,
                score_source=score_source,
                score_reason=score_reason,
                score_confidence=score_confidence,
                bbox=bbox,
                line_count=line_count,
                image_block_url=image_block_url,
                formula_enhanced=formula_enhanced,
                formula_strategy=formula_strategy,
                formula_warning_codes=formula_warning_codes,
                visual_assessment=visual_assessment,
            )
            parse_audit.notes.extend(formula_notes)

            parse_warnings: List[str] = []
            if not score_reliable:
                parse_warnings.append(f"{score_reason} 当前分值保留为 0，建议人工复核。")
                review_required = True
            if parse_audit.image_required_hint and not image_block_url:
                parse_warnings.append("题块图片裁切失败或缺失，涉及图形/表格时建议人工复核。")
                review_required = True

            if parse_audit.image_attach_recommended and not image_block_url and not parse_audit.image_required_hint:
                parse_warnings.append("该题建议附带题块图片，但当前裁图缺失，后续将按纯文本分析。")
            if "formula_api_failed" in parse_audit.warning_codes:
                parse_warnings.append("该题疑似公式密集，但公式增强识别失败，当前仍按普通 OCR 文本解析。")
                review_required = True
            if sub_item_candidates:
                parse_audit.notes.append(f"sub_items={len(sub_item_candidates)}")

            question_block = QuestionBlock(
                page_no=page_no,
                bbox=bbox or {"left": 0, "top": 0, "width": 0, "height": 0},
                line_count=line_count,
                text_density=self._line_text_density(block_lines, bbox),
            )
            parse_audit.block_completeness = max(parse_audit.block_completeness, question_block.text_density)

            question = ParsedQuestion(
                question_no=question_no,
                question_type=question_type,
                raw_text=question_text,
                question_label_raw=question_label_raw,
                section_index_raw=section_index_raw,
                score=score,
                is_optional=False,
                include_in_main_score=True,
                parse_confidence=0.0,
                applicable_dims=[],
                page_no=page_no,
                image_block_url=image_block_url,
                block_bbox=bbox,
                question_block=question_block,
                parse_warnings=parse_warnings,
                parse_audit=parse_audit,
                ocr_text_version="v3.0-structured",
                sub_questions=[],
                sub_item_candidates=sub_item_candidates,
            )
            question.parse_confidence = self._calculate_question_confidence(parse_audit)
            page_questions.append(question)

        logger.info("第 %s 页解析出 %s 道大题", page_no, len(page_questions))
        return page_questions, review_required

    async def _parse_page_questions(
        self,
        ocr_result: Dict[str, Any],
        *,
        page_no: int,
        image_path: str,
        existing_questions: List[ParsedQuestion],
        section_contexts: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Tuple[List[ParsedQuestion], bool, List[QuestionCountAudit], List[str]]:
        lines = self._extract_ocr_lines(ocr_result)
        if not lines:
            logger.warning("OCR 缁撴灉涓虹┖ page=%s", page_no)
            return [], False, [], []

        zones = self._detect_reading_zones(lines)
        review_required = False
        page_questions: List[ParsedQuestion] = []
        page_count_audits: List[QuestionCountAudit] = []
        if section_contexts is None:
            section_contexts = {}
        current_section_index_raw = (
            str(getattr(existing_questions[-1], "section_index_raw", "") or "")
            if existing_questions
            else ""
        )

        for zone in zones:
            sections = self._build_zone_sections(zone, current_section_index_raw)
            if not sections:
                continue

            for section in sections:
                section_index_raw = section.section_index_raw or current_section_index_raw
                if section_index_raw:
                    current_section_index_raw = section_index_raw
                section_state = (
                    self._section_state(section_contexts, section_index_raw)
                    if section_index_raw
                    else None
                )
                if section_state and (str(section.heading_text or "").strip() or section.is_headingless_prefix):
                    section_state["entered"] = True

                section_lines = list(section.lines)
                section_lines, resolved_declared_count = self._consume_leading_section_metadata(
                    section_lines,
                    section.declared_count,
                )
                if section_state and resolved_declared_count is None:
                    section_declared_count = section_state.get("declared_count")
                    try:
                        resolved_declared_count = (
                            int(str(section_declared_count).strip())
                            if section_declared_count is not None
                            else None
                        )
                    except (TypeError, ValueError, AttributeError):
                        resolved_declared_count = None
                expected_question_numbers = self._extract_expected_question_numbers(
                    section.heading_text,
                    section_lines,
                )
                if resolved_declared_count is None and expected_question_numbers:
                    resolved_declared_count = len(expected_question_numbers)
                section.declared_count = resolved_declared_count
                if section_state and resolved_declared_count is not None:
                    section_state["declared_count"] = resolved_declared_count
                body_line_count = len([line for line in section_lines if line.text.strip()])
                anchors = self._detect_question_anchors(
                    section_lines,
                    section.left,
                    expected_question_numbers=expected_question_numbers,
                    allow_parenthesized=not bool(
                        section_index_raw
                        and not str(section.heading_text or "").strip()
                        and not section.is_headingless_prefix
                    ),
                )
                section_lines, anchors = self._recover_leading_calculation_anchors(
                    section_lines,
                    anchors,
                    section.heading_text,
                )
                anchors = self._recover_missing_question_anchors(
                    section_lines,
                    anchors,
                    section.left,
                    expected_question_numbers=expected_question_numbers,
                    declared_count=resolved_declared_count,
                )
                anchors = self._recover_pre_anchor_content_lines(section_lines, anchors)
                if not str(section.heading_text or "").strip() and not section_index_raw and anchors:
                    current_page_numbers: List[int] = []
                    for question in page_questions:
                        if int(getattr(question, "page_no", 0) or 0) != page_no:
                            continue
                        try:
                            current_page_numbers.append(int(str(getattr(question, "question_no", "")).strip()))
                        except (TypeError, ValueError):
                            continue
                    try:
                        first_anchor_no = int(str(anchors[0].question_no).strip())
                    except (TypeError, ValueError):
                        first_anchor_no = None
                    if (
                        current_page_numbers
                        and first_anchor_no is not None
                        and first_anchor_no <= max(current_page_numbers)
                    ):
                        anchors = []
                if (
                    not str(section.heading_text or "").strip()
                    and section_index_raw
                    and not section.is_headingless_prefix
                ):
                    anchors = self._trim_overlapping_continuation_anchors(
                        anchors,
                        section_state=section_state,
                    )
                    if not anchors:
                        anchors = self._recover_sectionless_continuation_anchors(
                            section_lines,
                            section_state=section_state,
                        )
                    keep_section = (
                        self._should_keep_sectionless_continuation(
                            section_index_raw,
                            anchors,
                            page_questions,
                            existing_questions,
                            section_state=section_state,
                        )
                        if anchors
                        else bool(section_state and section_state.get("entered") and body_line_count)
                    )
                    if not keep_section:
                        if section_state and section_state.get("declared_count") is not None:
                            try:
                                declared_total = int(str(section_state.get("declared_count")).strip())
                            except (TypeError, ValueError, AttributeError):
                                declared_total = None
                            detected_total = len(
                                {
                                    str(number).strip()
                                    for number in (section_state.get("detected_numbers", []) or [])
                                    if str(number).strip()
                                }
                            )
                            if declared_total is not None and detected_total >= declared_total:
                                continue
                        skipped_audit = self._build_question_count_audit(
                            page_no=page_no,
                            zone_key=section.zone_key,
                            section_index_raw=section_index_raw,
                            anchors=anchors,
                            declared_count=resolved_declared_count,
                            layout_type=section.layout_type,
                            secondary_pass_used=False,
                            has_embedded_anchor=self._section_has_unassigned_anchor(
                                section_lines,
                                anchors,
                                section.left,
                            ),
                            body_line_count=body_line_count,
                            continuation_skipped=True,
                        )
                        page_count_audits.append(skipped_audit)
                        if skipped_audit.mismatch_reason:
                            review_required = True
                        continue
                primary_audit = self._build_question_count_audit(
                    page_no=page_no,
                    zone_key=section.zone_key,
                    section_index_raw=section_index_raw,
                    anchors=anchors,
                    declared_count=resolved_declared_count,
                    layout_type=section.layout_type,
                    secondary_pass_used=False,
                    has_embedded_anchor=self._section_has_unassigned_anchor(section_lines, anchors, section.left),
                    body_line_count=body_line_count,
                )

                secondary_result = None
                if primary_audit.mismatch_reason:
                    secondary_result = await self._secondary_parse_section(
                        section,
                        image_path=image_path,
                        page_no=page_no,
                    )

                section_lines, anchors, final_audit = self._choose_better_section_result(
                    primary_lines=section_lines,
                    primary_anchors=anchors,
                    primary_audit=primary_audit,
                    secondary_result=secondary_result,
                )
                page_count_audits.append(final_audit)
                if final_audit.mismatch_reason:
                    review_required = True

                if not anchors:
                    if section_lines and (page_questions or existing_questions):
                        merged = self._append_orphan_section_lines(
                            section_lines,
                            page_no=page_no,
                            page_questions=page_questions,
                            existing_questions=existing_questions,
                        )
                        if not merged:
                            target_question = page_questions[-1] if page_questions else existing_questions[-1]
                            self._append_lines_to_question(
                                target_question,
                                section_lines,
                                page_no=page_no,
                            )
                            review_required = True
                    continue

                if anchors[0].line_index > 0 and (page_questions or existing_questions):
                    leading_lines = section_lines[: anchors[0].line_index]
                    if leading_lines:
                        target_question = page_questions[-1] if page_questions else existing_questions[-1]
                        self._append_lines_to_question(
                            target_question,
                            leading_lines,
                            page_no=page_no,
                        )
                        review_required = True

                formula_anchor_blocks = (
                    len(anchors) > 1
                    and any(
                        anchors[index].line_index > anchors[index + 1].line_index
                        for index in range(len(anchors) - 1)
                    )
                    and all(self._is_formula_heavy_line(anchor.line.text) for anchor in anchors)
                )

                for offset, anchor in enumerate(anchors):
                    if formula_anchor_blocks:
                        block_lines = [anchor.line]
                    else:
                        next_anchor_index = anchors[offset + 1].line_index if offset + 1 < len(anchors) else len(section_lines)
                        block_lines = section_lines[anchor.line_index : next_anchor_index]
                    if anchor.force_use_label and block_lines and block_lines[0] is not anchor.line:
                        block_lines = [
                            line
                            for line in block_lines
                            if line is block_lines[0] or line is not anchor.line
                        ]
                    question, question_review = await self._build_question_from_lines(
                        block_lines,
                        page_no=page_no,
                        image_path=image_path,
                        section_index_raw=section_index_raw,
                        zone_left=section.left,
                        forced_question_no=anchor.question_no,
                        forced_question_label_raw=anchor.question_label_raw,
                        force_use_label=anchor.force_use_label,
                        recovery_reason=anchor.recovery_reason,
                    )
                    review_required = review_required or question_review
                    if question is not None:
                        page_questions.append(question)

                if section_state:
                    section_state["entered"] = True
                    if final_audit.declared_count is not None:
                        section_state["declared_count"] = final_audit.declared_count
                    detected_numbers = [
                        str(number).strip()
                        for number in [*section_state.get("detected_numbers", []), *final_audit.anchor_numbers]
                        if str(number).strip()
                    ]
                    section_state["detected_numbers"] = list(dict.fromkeys(detected_numbers))
                    numeric_anchor_values: List[int] = []
                    for anchor in anchors:
                        try:
                            numeric_anchor_values.append(int(str(anchor.question_no).strip()))
                        except (TypeError, ValueError):
                            continue
                    if numeric_anchor_values:
                        section_state["last_question_no"] = max(numeric_anchor_values)

        page_warnings = self._build_report_warnings(page_count_audits)
        logger.info("OCR layout-aware parsing page=%s questions=%s zones=%s", page_no, len(page_questions), len(zones))
        return page_questions, review_required, page_count_audits, page_warnings

    async def parse(self, file_path: str, **kwargs) -> ParsedPaper:
        paper_name = kwargs.get("paper_name", "数学试卷")
        paper_id = kwargs.get("paper_id", "unknown")

        logger.info("开始解析试卷 %s, 文件: %s", paper_id, file_path)
        file_ext = os.path.splitext(file_path)[1].lower()
        if self.is_image_manifest_path(file_path):
            manifest_pages = self.load_image_manifest_pages(file_path)
            validation = self.validate_image_count(len(manifest_pages))
            if not validation.is_valid:
                raise ValueError(validation.error_message)
            file_ext = ".images"
            image_paths = [page.path for page in manifest_pages]
            page_inputs = [(page.page_no, page.path) for page in manifest_pages]
        elif file_ext == ".pdf":
            image_paths = self._pdf_to_images(file_path)
            page_inputs = [(page_index + 1, image_path) for page_index, image_path in enumerate(image_paths)]
        else:
            image_paths = [file_path]
            page_inputs = [(1, file_path)]

        all_questions: List[ParsedQuestion] = []
        all_count_audits: List[QuestionCountAudit] = []
        report_warnings: List[str] = []
        total_confidence = 0.0
        processed_pages = 0
        needs_manual_review = False
        cleanup_candidates: List[str] = []
        section_contexts: Dict[str, Dict[str, Any]] = {}

        for page_index, (page_no, image_path) in enumerate(page_inputs):
            logger.info("识别第 %s/%s 页", page_index + 1, len(page_inputs))
            try:
                normalized_image_path, ocr_result, rotation_applied = await self._normalize_page_orientation(
                    image_path,
                    page_no=page_no,
                )
                if normalized_image_path != image_path:
                    cleanup_candidates.append(normalized_image_path)

                page_questions, page_review, page_count_audits, page_warnings = await self._parse_page_questions(
                    ocr_result,
                    page_no=page_no,
                    image_path=normalized_image_path,
                    existing_questions=all_questions,
                    section_contexts=section_contexts,
                )
                all_questions.extend(page_questions)
                all_count_audits.extend(page_count_audits)
                page_confidence = (
                    sum(question.parse_confidence for question in page_questions) / len(page_questions)
                    if page_questions
                    else ocr_result.get("probability", {}).get("average", 0.75)
                )
                if rotation_applied:
                    page_confidence = min(0.99, page_confidence + 0.02)
                total_confidence += page_confidence
                processed_pages += 1
                needs_manual_review = (
                    needs_manual_review
                    or page_review
                    or any(audit.mismatch_reason for audit in page_count_audits)
                )
                await asyncio.sleep(0.2)
            except Exception as exc:
                logger.error("第 %s 页识别失败: %s", page_no, exc)
                needs_manual_review = True
                continue

        avg_confidence = total_confidence / processed_pages if processed_pages else 0.5
        report_warnings = self._build_report_warnings(all_count_audits)
        parse_status = self.determine_parse_status(avg_confidence)
        needs_manual_review = (
            needs_manual_review
            or self.needs_manual_review(parse_status)
            or any(question.parse_warnings for question in all_questions)
            or bool(report_warnings)
        )

        paper = ParsedPaper(
            paper_name=paper_name,
            total_question_count=len(all_questions),
            total_score=sum(question.score for question in all_questions),
            page_count=len(page_inputs),
            parse_status=parse_status,
            parse_confidence=avg_confidence,
            need_manual_review=needs_manual_review,
            questions=all_questions,
            file_type="pdf" if file_ext == ".pdf" else ("images" if file_ext == ".images" else "image"),
            source_file_url=file_path,
            report_warnings=list(dict.fromkeys(report_warnings)),
            question_count_audits=all_count_audits,
        )

        logger.info(
            "试卷解析完成 paper=%s question_count=%s confidence=%.2f need_manual_review=%s",
            paper_id,
            len(all_questions),
            avg_confidence,
            needs_manual_review,
        )

        self._cleanup_temp_files(image_paths + cleanup_candidates, file_ext)
        return paper

    def _cleanup_temp_files(self, image_paths: List[str], original_ext: str) -> None:
        if original_ext == ".pdf" and image_paths:
            temp_dir = os.path.dirname(image_paths[0])
            try:
                import shutil

                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.debug("清理临时文件: %s", temp_dir)
            except Exception as exc:
                logger.warning("清理临时文件失败: %s", exc)

    def _cleanup_temp_files(self, image_paths: List[str], original_ext: str) -> None:
        if original_ext == ".pdf" and image_paths:
            temp_dir = os.path.dirname(image_paths[0])
            try:
                import shutil

                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.debug("娓呯悊涓存椂鏂囦欢: %s", temp_dir)
            except Exception as exc:
                logger.warning("娓呯悊涓存椂鏂囦欢澶辫触: %s", exc)
            return

        for image_path in image_paths:
            path_obj = Path(image_path)
            if path_obj.parent.name not in {"ocr_normalized", "section_crops"}:
                continue
            try:
                path_obj.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("娓呯悊涓存椂鏂囦欢澶辫触: %s", exc)

    async def health_check(self) -> Dict[str, Any]:
        try:
            if not all([self.api_key, self.secret_key]):
                return {
                    "status": "unhealthy",
                    "provider": "BaiduOCRProvider",
                    "message": "配置不完整，缺少 API Key 或 Secret Key",
                    "version": "3.0.0",
                }

            await self._get_access_token()
            return {
                "status": "healthy",
                "provider": "BaiduOCRProvider",
                "message": "百度 OCR 服务正常",
                "version": "3.0.0",
                "capabilities": {
                    "supports_pdf": True,
                    "supports_images": True,
                    "supports_formula": True,
                    "max_file_size": "10MB",
                    "max_pdf_pages": 30,
                    "structured_question_blocks": True,
                    "sub_item_candidates": True,
                },
            }
        except Exception as exc:
            logger.error("健康检查失败: %s", exc)
            return {
                "status": "unhealthy",
                "provider": "BaiduOCRProvider",
                "message": str(exc),
                "version": "3.0.0",
            }
