"""Vision-LLM based paper structure parser.

This provider replaces the OCR engine stage with a multimodal LLM stage while
keeping the existing ParsedPaper/ParsedQuestion contract for downstream scoring.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageOps

from app.services.llm.moonshot_client import MoonshotClient
from app.services.ocr.base import (
    BaseOCRProvider,
    DimensionCode,
    ParseAudit,
    ParseStatus,
    ParsedPaper,
    ParsedQuestion,
    QuestionBlock,
    QuestionCountAudit,
    QuestionType,
)
from app.services.ocr.field_safety import (
    MAX_QUESTION_NO_LENGTH,
    clamp_storage_text,
    normalize_section_index_raw,
    question_no_would_be_truncated,
)

logger = logging.getLogger(__name__)

VISION_JSON_RESPONSE_FORMAT = {"type": "json_object"}
VISION_OCR_TEXT_VERSION = "vision-llm-v1"
VISION_RESPONSE_HEAD_LIMIT = 360

VISION_PAGE_SYSTEM_PROMPT = """你是小学数学试卷页面的视觉结构化解析器。
你的任务是从页面图片中识别题目结构，不做难度评分，不生成报告。
必须只返回一个 JSON 对象，不能输出 Markdown、解释或额外文本。
输出必须以 { 开头，以 } 结尾，并且必须能被标准 JSON 解析器直接解析。
题目统计粒度按顶层题号，不要把 (1)(2) 小问拆成独立顶层题。
如果题目跨页延续，请用 is_continuation=true 标记，并保留同一 question_no。
如果分值、题号或题干不确定，用 null、空字符串和 warnings 表达，不要解释，不要编造。"""

VISION_PAGE_USER_PROMPT = """请解析这张小学数学试卷页面图片，返回严格 JSON：
{
  "page_no": {page_no},
  "page_width": {width},
  "page_height": {height},
  "declared_question_count": null,
  "warnings": [],
  "questions": [
    {
      "question_no": "1",
      "question_label_raw": "1.",
      "section_index_raw": "",
      "question_type": "application",
      "raw_text": "完整题干文本，包含小问文本和必要公式",
      "score": null,
      "bbox": {"left": 0, "top": 0, "width": 100, "height": 100},
      "is_continuation": false,
      "visual_dependency": "none",
      "visual_category": "none",
      "confidence": 0.85,
      "warnings": []
    }
  ]
}

页码：{page_no}
图片尺寸：{width} x {height}
要求：
1. 只抽取卷面实际存在的题目，不要补题。
2. bbox 应覆盖整道顶层题，包括图形和小问。
3. 分值只在页面明确出现时填写；不确定时填 null 并加 warning。
4. 几何图、统计图、表格、复杂图文排版题要设置 visual_dependency 为 attach 或 required。
5. 如果本页没有可识别题目，questions 返回空数组。
6. 不要输出 ```json，不要输出任何 JSON 外文本。
"""


@dataclass
class PageImage:
    page_no: int
    path: str
    width: int
    height: int


class VisionLLMProvider(BaseOCRProvider):
    """Parse a paper into structured questions using a multimodal LLM."""

    PROVIDER_NAME = "VisionLLMProvider"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.model = str(self.config.get("model") or "").strip()
        self.base_url = str(self.config.get("base_url") or "").strip()
        self.api_key = self.config.get("api_key")
        self.concurrency = max(1, int(self.config.get("concurrency") or 2))
        self.page_timeout = float(self.config.get("page_timeout") or 90.0)
        self.max_attempts = max(
            1,
            int(self.config.get("max_attempts") or self.config.get("max_retries") or 3),
        )
        self.retry_base_seconds = max(0.0, float(self.config.get("retry_base_seconds") or 1.5))
        self.render_dpi = max(72, int(self.config.get("render_dpi") or 180))
        self.max_tokens = max(1000, int(self.config.get("max_tokens") or 12000))
        self.max_image_side = max(1000, int(self.config.get("max_image_side") or 2400))
        self._llm_client = self.config.get("llm_client")

    def _get_llm_client(self):
        if self._llm_client is not None:
            return self._llm_client
        if not self.api_key:
            raise ValueError("LLM API Key 未配置，请设置 ANTHROPIC_API_KEY 或 MOONSHOT_API_KEY")
        self._llm_client = MoonshotClient(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
            temperature=0.1,
            max_tokens=self.max_tokens,
            timeout=self.page_timeout,
            llm_pool="vision",
        )
        return self._llm_client

    async def health_check(self) -> Dict[str, Any]:
        try:
            import fitz  # noqa: F401
        except Exception as exc:
            return {
                "status": "unhealthy",
                "provider": self.PROVIDER_NAME,
                "message": f"PyMuPDF 不可用，无法渲染 PDF 页面：{exc}",
                "version": "1.0.0",
            }

        if not self.api_key:
            return {
                "status": "unhealthy",
                "provider": self.PROVIDER_NAME,
                "message": "LLM API Key 未配置，请设置 ANTHROPIC_API_KEY 或 MOONSHOT_API_KEY",
                "version": "1.0.0",
            }
        if not self.model:
            return {
                "status": "unhealthy",
                "provider": self.PROVIDER_NAME,
                "message": "视觉大模型未配置，请设置 VISION_LLM_MODEL 或 CLAUDE_MODEL",
                "version": "1.0.0",
            }
        if not self.base_url:
            return {
                "status": "unhealthy",
                "provider": self.PROVIDER_NAME,
                "message": "LLM_BASE_URL 未配置",
                "version": "1.0.0",
            }

        return {
            "status": "healthy",
            "provider": self.PROVIDER_NAME,
            "message": "Vision LLM 结构化识别配置已就绪",
            "version": "1.0.0",
            "capabilities": {
                "supports_pdf": True,
                "supports_images": True,
                "supports_formula": True,
                "structured_question_blocks": True,
                "sub_item_candidates": False,
                "ocr_engine": False,
                "model": self.model,
                "max_tokens": self.max_tokens,
            },
        }

    async def parse(self, file_path: str, **kwargs) -> ParsedPaper:
        paper_name = kwargs.get("paper_name", "数学试卷")
        paper_id = kwargs.get("paper_id", "unknown")
        logger.info("Vision LLM parsing started paper=%s file=%s", paper_id, file_path)

        page_images = self._render_input_to_page_images(file_path)
        if not page_images:
            raise RuntimeError("未能从上传文件生成页面图片")

        page_payloads = await self._parse_page_images(
            page_images,
            progress_callback=kwargs.get("progress_callback"),
        )
        questions, audits, report_warnings = self._build_structured_result(page_images, page_payloads)
        if not questions:
            raise RuntimeError("视觉大模型未识别到任何题目")

        total_score = sum(question.score for question in questions if question.include_in_main_score)
        avg_confidence = sum(question.parse_confidence for question in questions) / len(questions)
        penalty = min(0.35, len(report_warnings) * 0.025)
        parse_confidence = max(0.0, min(1.0, avg_confidence - penalty))
        parse_status = self.determine_parse_status(parse_confidence)
        need_manual_review = self.needs_manual_review(parse_status) or bool(report_warnings)

        file_type = "images" if self.is_image_manifest_path(file_path) else (
            "pdf" if str(file_path).lower().endswith(".pdf") else "image"
        )

        return ParsedPaper(
            paper_name=paper_name,
            total_question_count=len(questions),
            total_score=total_score,
            page_count=len(page_images),
            parse_status=parse_status,
            parse_confidence=parse_confidence,
            need_manual_review=need_manual_review,
            questions=questions,
            file_type=file_type,
            source_file_url=file_path,
            report_warnings=list(dict.fromkeys(report_warnings)),
            question_count_audits=audits,
        )

    def _render_input_to_page_images(self, file_path: str) -> List[PageImage]:
        if self.is_image_manifest_path(file_path):
            manifest_pages = self.load_image_manifest_pages(file_path)
            validation = self.validate_image_count(len(manifest_pages))
            if not validation.is_valid:
                raise ValueError(validation.error_message)
            return [
                self._prepare_image_page(page.path, page_no=page.page_no)
                for page in manifest_pages
            ]

        file_ext = Path(file_path).suffix.lower()
        if file_ext == ".pdf":
            return self._render_pdf_to_images(file_path)
        return [self._prepare_image_page(file_path, page_no=1)]

    def _render_pdf_to_images(self, pdf_path: str) -> List[PageImage]:
        try:
            import fitz
        except Exception as exc:
            raise RuntimeError("PyMuPDF 未安装，无法将 PDF 渲染为页面图片") from exc

        pdf = fitz.open(pdf_path)
        try:
            if pdf.page_count > self.upload_config.max_pdf_pages:
                raise ValueError(
                    f"PDF页数超过限制: {pdf.page_count}页 (最大: {self.upload_config.max_pdf_pages}页)"
                )

            output_dir = Path(pdf_path).resolve().parent / "vision_pages"
            output_dir.mkdir(parents=True, exist_ok=True)
            zoom = self.render_dpi / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            page_images: List[PageImage] = []

            for page_index in range(pdf.page_count):
                page_no = page_index + 1
                pixmap = pdf.load_page(page_index).get_pixmap(matrix=matrix, alpha=False)
                image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                output_path = output_dir / f"page_{page_no}.jpg"
                page_images.append(self._save_page_image(image, output_path, page_no=page_no))

            return page_images
        finally:
            pdf.close()

    def _prepare_image_page(self, image_path: str, *, page_no: int) -> PageImage:
        output_dir = Path(image_path).resolve().parent / "vision_pages"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"page_{page_no}.jpg"

        with Image.open(image_path) as image:
            normalized = ImageOps.exif_transpose(image).convert("RGB")
            return self._save_page_image(normalized, output_path, page_no=page_no)

    def _save_page_image(self, image: Image.Image, output_path: Path, *, page_no: int) -> PageImage:
        normalized = image.convert("RGB")
        normalized = self._trim_page_whitespace(normalized, page_no=page_no)
        normalized = self._auto_orient_page_image(normalized, page_no=page_no)
        normalized = self._trim_page_whitespace(normalized, page_no=page_no)
        if max(normalized.size) > self.max_image_side:
            normalized.thumbnail((self.max_image_side, self.max_image_side), Image.Resampling.LANCZOS)
        normalized.save(output_path, format="JPEG", quality=90, optimize=True)
        return PageImage(
            page_no=page_no,
            path=str(output_path),
            width=normalized.width,
            height=normalized.height,
        )

    def _trim_page_whitespace(self, image: Image.Image, *, page_no: int) -> Image.Image:
        grayscale = ImageOps.grayscale(image)
        mask = grayscale.point(lambda pixel: 0 if pixel > 245 else 255)
        bbox = mask.getbbox()
        if not bbox:
            return image

        width, height = image.size
        left, top, right, bottom = bbox
        margin_x = max(16, int(width * 0.015))
        margin_y = max(16, int(height * 0.015))
        left = max(0, left - margin_x)
        top = max(0, top - margin_y)
        right = min(width, right + margin_x)
        bottom = min(height, bottom + margin_y)

        cropped_width = right - left
        cropped_height = bottom - top
        if cropped_width <= 0 or cropped_height <= 0:
            return image
        if cropped_width * cropped_height >= width * height * 0.98:
            return image

        logger.info(
            "Vision page whitespace trimmed page=%s from=%sx%s to=%sx%s",
            page_no,
            width,
            height,
            cropped_width,
            cropped_height,
        )
        return image.crop((left, top, right, bottom))

    def _auto_orient_page_image(self, image: Image.Image, *, page_no: int) -> Image.Image:
        candidate_by_angle = {
            0: image,
            90: image.rotate(90, expand=True),
            270: image.rotate(270, expand=True),
        }
        score_by_angle = {
            angle: self._horizontal_text_score(candidate)
            for angle, candidate in candidate_by_angle.items()
        }
        original_score = score_by_angle[0]
        best_score = max(score_by_angle.values())
        if score_by_angle[90] >= best_score * 0.99:
            best_angle = 90
        elif score_by_angle[270] >= best_score * 0.99:
            best_angle = 270
        else:
            best_angle = max(score_by_angle, key=score_by_angle.get)
        best_image = candidate_by_angle[best_angle]

        if best_angle and best_score > max(original_score * 1.8, original_score + 1.0):
            logger.info(
                "Vision page auto-oriented page=%s angle=%s score=%.3f original_score=%.3f",
                page_no,
                best_angle,
                best_score,
                original_score,
            )
            return best_image
        return image

    @staticmethod
    def _horizontal_text_score(image: Image.Image) -> float:
        thumbnail = ImageOps.grayscale(image.copy())
        thumbnail.thumbnail((900, 900))
        width, height = thumbnail.size
        if width <= 0 or height <= 0:
            return 0.0

        pixels = thumbnail.load()
        row_counts = [0] * height
        col_counts = [0] * width
        for y in range(height):
            for x in range(width):
                if pixels[x, y] < 215:
                    row_counts[y] += 1
                    col_counts[x] += 1

        def dispersion(values: Sequence[int]) -> float:
            if not values:
                return 0.0
            mean = sum(values) / len(values)
            if mean <= 0:
                return 0.0
            variance = sum((value - mean) ** 2 for value in values) / len(values)
            return variance / mean

        column_score = dispersion(col_counts)
        if column_score <= 0:
            return 0.0
        return dispersion(row_counts) / column_score

    async def _parse_page_images(
        self,
        page_images: Sequence[PageImage],
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]] = None,
    ) -> List[Dict[str, Any]]:
        semaphore = asyncio.Semaphore(self.concurrency)
        progress_lock = asyncio.Lock()
        completed_count = 0
        total_pages = len(page_images)

        async def publish_progress(
            page_image: PageImage,
            *,
            success: bool,
            elapsed_seconds: float,
            error: str = "",
        ) -> None:
            nonlocal completed_count

            async with progress_lock:
                completed_count += 1
                payload = {
                    "completed": completed_count,
                    "total": total_pages,
                    "page_no": page_image.page_no,
                    "success": success,
                    "elapsed_seconds": elapsed_seconds,
                    "error": error[:240],
                }

            if not progress_callback:
                return

            try:
                maybe_result = progress_callback(payload)
                if asyncio.iscoroutine(maybe_result):
                    await maybe_result
            except Exception as exc:
                logger.warning(
                    "Failed to publish vision OCR progress page=%s: %s",
                    page_image.page_no,
                    exc,
                )

        async def parse_one(page_image: PageImage) -> Dict[str, Any] | Exception:
            started_at = asyncio.get_running_loop().time()
            async with semaphore:
                try:
                    payload = await self._parse_single_page(page_image)
                except Exception as exc:
                    elapsed = asyncio.get_running_loop().time() - started_at
                    await publish_progress(
                        page_image,
                        success=False,
                        elapsed_seconds=elapsed,
                        error=str(exc),
                    )
                    return exc

            elapsed = asyncio.get_running_loop().time() - started_at
            await publish_progress(page_image, success=True, elapsed_seconds=elapsed)
            return payload

        results = list(await asyncio.gather(*(parse_one(page_image) for page_image in page_images)))
        failures: List[str] = []
        page_payloads: List[Dict[str, Any]] = []
        for page_image, result in zip(page_images, results):
            if isinstance(result, Exception):
                failures.append(f"page={page_image.page_no}: {result}")
                continue
            page_payloads.append(result)

        if failures:
            raise RuntimeError("Vision LLM page parse failed after retries: " + "; ".join(failures))

        return page_payloads

    async def _parse_single_page(self, page_image: PageImage) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_attempts + 1):
            started_at = asyncio.get_running_loop().time()
            try:
                payload = await self._parse_single_page_once(page_image)
                logger.info(
                    "Vision LLM page parsed page=%s attempt=%s/%s elapsed=%.2fs",
                    page_image.page_no,
                    attempt,
                    self.max_attempts,
                    asyncio.get_running_loop().time() - started_at,
                )
                return payload
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                elapsed = asyncio.get_running_loop().time() - started_at
                logger.warning(
                    "Vision LLM page parse failed page=%s attempt=%s/%s elapsed=%.2fs error=%s",
                    page_image.page_no,
                    attempt,
                    self.max_attempts,
                    elapsed,
                    exc,
                )
                if attempt >= self.max_attempts:
                    break
                await asyncio.sleep(self.retry_base_seconds * (2 ** (attempt - 1)))

        raise RuntimeError(
            f"Vision LLM page parse failed page={page_image.page_no} attempts={self.max_attempts}: {last_error}"
        ) from last_error

    async def _parse_single_page_once(self, page_image: PageImage) -> Dict[str, Any]:
        messages = self._build_page_messages(page_image)
        client = self._get_llm_client()

        try:
            response = await asyncio.wait_for(
                client.chat(messages, response_format=VISION_JSON_RESPONSE_FORMAT),
                timeout=self.page_timeout,
            )
            return await self._load_page_json(response, page_image)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(f"Vision LLM 页面解析超时 page={page_image.page_no}") from exc

    def _build_page_messages(self, page_image: PageImage) -> List[Dict[str, Any]]:
        prompt_text = (
            VISION_PAGE_USER_PROMPT
            .replace("{page_no}", str(page_image.page_no))
            .replace("{width}", str(page_image.width))
            .replace("{height}", str(page_image.height))
        )
        return [
            {"role": "system", "content": VISION_PAGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": self._image_to_data_url(page_image.path)}},
                ],
            },
        ]

    @staticmethod
    def _image_to_data_url(image_path: str) -> str:
        mime_type, _ = mimetypes.guess_type(image_path)
        mime_type = mime_type or "image/jpeg"
        encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    async def _load_page_json(self, response: str, page_image: PageImage) -> Dict[str, Any]:
        try:
            payload = self._json_loads_with_local_repair(response)
        except ValueError as direct_error:
            logger.warning(
                "Vision LLM page JSON parse failed page=%s attempt=1 error=%s response_head=%s",
                page_image.page_no,
                direct_error,
                self._response_head(response),
            )
            try:
                payload = await self._repair_page_json_with_llm(response, page_image, str(direct_error))
            except Exception as repair_error:
                message = (
                    f"第 {page_image.page_no} 页 Vision LLM 返回内容不是有效 JSON，已重试 1 次："
                    f"{repair_error}"
                )
                logger.error(
                    "Vision LLM page JSON repair failed page=%s attempt=2 direct_error=%s repair_error=%s response_head=%s",
                    page_image.page_no,
                    direct_error,
                    repair_error,
                    self._response_head(response),
                )
                raise ValueError(message) from repair_error

        if "pages" in payload and isinstance(payload["pages"], list) and payload["pages"]:
            payload = payload["pages"][0]
        if not isinstance(payload, dict):
            raise ValueError(f"第 {page_image.page_no} 页 Vision LLM 返回内容不是 JSON 对象")

        payload.setdefault("page_no", page_image.page_no)
        payload.setdefault("page_width", page_image.width)
        payload.setdefault("page_height", page_image.height)
        payload.setdefault("questions", [])
        if not isinstance(payload.get("questions"), list):
            payload["questions"] = []
            payload.setdefault("warnings", [])
            payload["warnings"].append("模型返回的 questions 不是数组。")
        return payload

    def _json_loads_with_local_repair(self, response: str) -> Dict[str, Any]:
        payload = self._extract_json_body(response)
        candidates = self._local_json_candidates(payload)
        last_error: Optional[str] = None
        for candidate in candidates:
            try:
                loaded = json.loads(candidate)
            except json.JSONDecodeError as exc:
                last_error = str(exc)
                continue
            if isinstance(loaded, dict):
                return loaded
            last_error = f"解析结果不是 JSON 对象: {type(loaded).__name__}"
        raise ValueError(f"无法解析 Vision LLM JSON 响应：{last_error or '响应中没有可用 JSON 对象'}")

    @staticmethod
    def _extract_json_body(response: str) -> str:
        text = str(response or "").strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start : end + 1]
        if start >= 0:
            return text[start:]
        return text

    @staticmethod
    def _strip_trailing_commas(payload: str) -> str:
        return re.sub(r",(\s*[}\]])", r"\1", payload)

    def _local_json_candidates(self, payload: str) -> List[str]:
        candidates: List[str] = []
        for candidate in (
            payload.strip(),
            self._strip_trailing_commas(payload.strip()),
            self._repair_common_json_issues(payload),
            self._repair_common_json_issues(self._close_truncated_json(payload)),
        ):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        return candidates

    def _repair_common_json_issues(self, payload: str) -> str:
        repaired = payload.strip()
        repaired = self._strip_trailing_commas(repaired)
        repaired = self._insert_missing_commas(repaired)
        repaired = self._escape_unescaped_inner_quotes(repaired)
        repaired = self._insert_missing_commas(repaired)
        repaired = self._strip_trailing_commas(repaired)
        return repaired

    @staticmethod
    def _next_non_whitespace_char(payload: str, start_index: int) -> str:
        index = start_index
        while index < len(payload) and payload[index].isspace():
            index += 1
        return payload[index] if index < len(payload) else ""

    @classmethod
    def _string_is_object_key(cls, payload: str, quote_index: int) -> bool:
        index = quote_index + 1
        escape_next = False
        while index < len(payload):
            char = payload[index]
            if escape_next:
                escape_next = False
            elif char == "\\":
                escape_next = True
            elif char == '"':
                return cls._next_non_whitespace_char(payload, index + 1) == ":"
            index += 1
        return False

    @staticmethod
    def _is_json_value_start(char: str) -> bool:
        return char in {'"', "{", "[", "-"} or char.isdigit() or char in {"t", "f", "n"}

    @staticmethod
    def _is_json_value_end(char: str) -> bool:
        return char in {'"', "}", "]"} or char.isdigit() or char in {"e", "l"}

    def _should_insert_missing_comma(
        self,
        payload: str,
        index: int,
        previous_significant: str,
        stack: Sequence[str],
    ) -> bool:
        if not stack or not self._is_json_value_end(previous_significant):
            return False
        if previous_significant in {"", "{", "[", ":", ","}:
            return False

        char = payload[index]
        container = stack[-1]
        if container == "[":
            return self._is_json_value_start(char)
        if container == "{":
            return char == '"' and self._string_is_object_key(payload, index)
        return False

    def _insert_missing_commas(self, payload: str) -> str:
        """Repair common Vision LLM omissions such as `} "next_key"` or `} {`.

        This is intentionally a small JSON-state scanner instead of a broad
        regex, so punctuation inside question text is never treated as structure.
        """

        result: List[str] = []
        stack: List[str] = []
        in_string = False
        escape_next = False
        previous_significant = ""

        for index, char in enumerate(payload):
            if in_string:
                result.append(char)
                if escape_next:
                    escape_next = False
                elif char == "\\":
                    escape_next = True
                elif char == '"':
                    in_string = False
                    previous_significant = '"'
                continue

            if char.isspace():
                result.append(char)
                continue

            if self._should_insert_missing_comma(payload, index, previous_significant, stack):
                result.append(",")
                previous_significant = ","

            result.append(char)

            if char == '"':
                in_string = True
                escape_next = False
                continue
            if char in ("{", "["):
                stack.append(char)
            elif char in ("}", "]"):
                if stack:
                    expected = "{" if char == "}" else "["
                    if stack[-1] == expected:
                        stack.pop()
                    else:
                        stack.pop()
            previous_significant = char

        return "".join(result)

    def _escape_unescaped_inner_quotes(self, payload: str) -> str:
        result: List[str] = []
        in_string = False
        escape_next = False

        for index, char in enumerate(payload):
            if escape_next:
                result.append(char)
                escape_next = False
                continue

            if char == "\\" and in_string:
                result.append(char)
                escape_next = True
                continue

            if char == '"':
                if not in_string:
                    in_string = True
                    result.append(char)
                    continue

                next_char = self._next_non_whitespace_char(payload, index + 1)
                if next_char in {":", ",", "}", "]", ""}:
                    in_string = False
                    result.append(char)
                else:
                    result.append('\\"')
                continue

            result.append(char)

        return "".join(result)

    @staticmethod
    def _scan_json_state(payload: str) -> Tuple[List[str], bool, bool, int]:
        stack: List[str] = []
        in_string = False
        escape_next = False
        last_safe_boundary = 0

        for index, char in enumerate(payload):
            if escape_next:
                escape_next = False
                continue
            if char == "\\" and in_string:
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue

            if char in ("{", "["):
                stack.append(char)
            elif char in ("}", "]"):
                if stack:
                    stack.pop()
                    if not stack:
                        last_safe_boundary = index + 1
            elif char == "," and len(stack) == 1:
                last_safe_boundary = index

        return stack, in_string, escape_next, last_safe_boundary

    def _close_truncated_json(self, payload: str) -> str:
        text = payload.strip().rstrip(",")
        if text.endswith(("[", "{", ":")):
            return payload.strip()
        stack, in_string, escape_next, _ = self._scan_json_state(text)
        if not stack:
            return text
        if in_string:
            if escape_next:
                text = text[:-1]
            text += '"'
        closing = "".join("}" if token == "{" else "]" for token in reversed(stack))
        return text + closing

    @staticmethod
    def _response_head(response: str, limit: int = VISION_RESPONSE_HEAD_LIMIT) -> str:
        normalized = str(response or "").strip().replace("\r", "\\r").replace("\n", "\\n")
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit].rstrip()}..."

    async def _repair_page_json_with_llm(
        self,
        response: str,
        page_image: PageImage,
        error_message: str,
    ) -> Dict[str, Any]:
        repair_prompt = (
            "下面是一个视觉试卷解析 JSON，但格式无法解析。请只返回修复后的 JSON 对象，"
            "只修复 JSON 语法，不要改写题干，不要改变原始语义，不要新增不存在的题目。\n"
            "返回结构必须是页面级对象，字段包括 page_no、page_width、page_height、"
            "declared_question_count、warnings、questions；questions 必须是数组。\n"
            f"页码：{page_image.page_no}\n"
            f"错误：{error_message}\n"
            f"原始响应：\n{response}"
        )
        client = self._get_llm_client()
        repaired = await asyncio.wait_for(
            client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你只修复 JSON 语法，严格返回一个页面级 JSON 对象。"
                            "不要输出 Markdown，不要解释，不要新增题目。"
                        ),
                    },
                    {"role": "user", "content": repair_prompt},
                ],
                response_format=VISION_JSON_RESPONSE_FORMAT,
            ),
            timeout=self.page_timeout,
        )
        try:
            return self._json_loads_with_local_repair(repaired)
        except ValueError as exc:
            logger.warning(
                "Vision LLM repaired JSON parse failed page=%s error=%s repaired_head=%s",
                page_image.page_no,
                exc,
                self._response_head(repaired),
            )
            raise

    def _build_structured_result(
        self,
        page_images: Sequence[PageImage],
        page_payloads: Sequence[Dict[str, Any]],
    ) -> Tuple[List[ParsedQuestion], List[QuestionCountAudit], List[str]]:
        page_by_no = {page.page_no: page for page in page_images}
        questions: List[ParsedQuestion] = []
        audits: List[QuestionCountAudit] = []
        report_warnings: List[str] = []
        seen_keys: Dict[Tuple[str, str], int] = {}

        for page_payload in page_payloads:
            page_no = self._coerce_int(page_payload.get("page_no"), fallback=len(audits) + 1)
            page_image = page_by_no.get(page_no) or page_images[min(max(page_no - 1, 0), len(page_images) - 1)]
            page_questions = page_payload.get("questions", [])
            page_warnings = self._string_list(page_payload.get("warnings"))
            report_warnings.extend(f"第 {page_no} 页：{item}" for item in page_warnings)

            page_anchor_numbers: List[str] = []
            page_duplicate_numbers: List[str] = []
            detected_count = 0

            for index, raw_question in enumerate(page_questions, start=1):
                if not isinstance(raw_question, dict):
                    report_warnings.append(f"第 {page_no} 页第 {index} 个题目结构不是对象，已跳过。")
                    continue

                preview_no, preview_section = self._preview_question_identity(raw_question, page_image, index)
                key = (preview_section or "", preview_no)
                continuation = bool(raw_question.get("is_continuation") or raw_question.get("continuation"))

                final_question_no = preview_no
                duplicate_question_no: Optional[str] = None
                if not continuation:
                    if key in seen_keys:
                        seen_keys[key] += 1
                        duplicate_question_no = preview_no
                        final_question_no = f"{preview_no}-dup{seen_keys[key]}"
                        page_duplicate_numbers.append(preview_no)
                        report_warnings.append(f"第 {page_no} 页题号 {preview_no} 重复，需检查。")
                    else:
                        seen_keys[key] = 1

                question = self._build_question(
                    raw_question,
                    page_image,
                    index,
                    report_warnings,
                    question_no_override=final_question_no,
                )

                if continuation and questions and self._should_merge_continuation(raw_question, question, questions[-1]):
                    target_question_no = questions[-1].question_no
                    self._merge_continuation_question(questions[-1], question)
                    report_warnings.append(f"第 {page_no} 页题块已合并到题号 {target_question_no} 的跨页延续部分。")
                    continue

                if continuation and questions:
                    previous_no = questions[-1].question_no
                    question.parse_warnings.append(
                        f"模型标记为跨页延续，但题号 {question.question_no} 与上一题 {previous_no} 不一致，已按独立题处理。"
                    )
                    if question.parse_audit:
                        question.parse_audit.cross_page_merged = False
                        question.parse_audit.warning_codes = list(
                            dict.fromkeys([*question.parse_audit.warning_codes, "continuation_mismatch"])
                        )
                    report_warnings.append(
                        f"第 {page_no} 页题号 {question.question_no} 被标记为跨页延续，但上一题为 {previous_no}，已按独立题处理。"
                    )

                if duplicate_question_no:
                    question.parse_warnings.append(f"题号 {duplicate_question_no} 重复，已保留并标记。")
                    if question.parse_audit:
                        question.parse_audit.warning_codes.append("duplicate_question_no")

                detected_count += 1
                page_anchor_numbers.append(preview_no)
                questions.append(question)

            declared_count = self._coerce_optional_int(page_payload.get("declared_question_count"))
            missing_numbers: List[str] = []

            audits.append(
                QuestionCountAudit(
                    page_no=page_no,
                    zone_key=f"page_{page_no}",
                    section_index_raw="",
                    detected_count=detected_count,
                    declared_count=declared_count,
                    anchor_numbers=page_anchor_numbers,
                    missing_numbers=missing_numbers,
                    duplicate_numbers=page_duplicate_numbers,
                    secondary_pass_used=False,
                    mismatch_reason="; ".join(page_warnings),
                    layout_type="vision_llm",
                )
            )

        global_missing_numbers = self._find_missing_numbers([question.question_no for question in questions])
        if global_missing_numbers:
            report_warnings.append(f"整卷题号可能不连续，缺失：{', '.join(global_missing_numbers)}。")

        return questions, audits, list(dict.fromkeys(item for item in report_warnings if item))

    def _build_question(
        self,
        raw_question: Dict[str, Any],
        page_image: PageImage,
        index: int,
        report_warnings: List[str],
        question_no_override: Optional[str] = None,
    ) -> ParsedQuestion:
        raw_label = self._first_text(raw_question, "question_label_raw", "label", "raw_label")
        warnings = self._string_list(raw_question.get("warnings"))
        raw_question_no = self._first_text(raw_question, "question_no", "number", "no") or raw_label
        question_no = self._normalize_question_no(raw_question_no)
        if question_no_would_be_truncated(raw_question_no):
            warnings.append("题号字段超过存储长度，已截断为安全题号。")
        if not question_no:
            question_no = f"p{page_image.page_no}q{index}"
            warnings.append("模型未稳定识别题号，已生成临时题号。")
            report_warnings.append(f"第 {page_image.page_no} 页第 {index} 个题块缺少题号。")
        if question_no_override:
            question_no = question_no_override
        question_no = clamp_storage_text(
            question_no,
            MAX_QUESTION_NO_LENGTH,
            field_name="question_no",
            logger=logger,
            context=f"paper_page={page_image.page_no}",
        )

        raw_text = self._first_text(raw_question, "raw_text", "question_text", "content", "stem", "text")
        if not raw_text:
            raw_text = "（模型未能稳定识别题干）"
            warnings.append("题干文本为空。")
            report_warnings.append(f"第 {page_image.page_no} 页题号 {question_no} 题干为空。")

        score, score_warning = self._parse_score(raw_question.get("score"))
        if score_warning:
            warnings.append(score_warning)

        confidence = self._coerce_float(raw_question.get("confidence"), fallback=0.82)
        confidence = max(0.0, min(1.0, confidence))
        visual_dependency = str(raw_question.get("visual_dependency") or "none").strip().lower()
        image_required = visual_dependency in {"required", "true", "1", "yes"}
        image_attach = image_required or visual_dependency in {"attach", "recommended"}
        visual_category = str(raw_question.get("visual_category") or ("explicit_visual" if image_attach else "none")).strip()

        bbox = self._normalize_bbox(raw_question.get("bbox"), page_image)
        image_block_url = self._build_question_block_image(page_image, question_no, bbox)
        if not image_block_url and image_attach:
            image_block_url = page_image.path
            warnings.append("题目依赖图形但模型未返回稳定 bbox，已附整页图。")

        question_type = self._normalize_question_type(raw_question.get("question_type"), raw_text, image_attach)
        line_count = max(1, raw_text.count("\n") + 1)
        audit_warnings = list(dict.fromkeys(warnings))

        parse_audit = ParseAudit(
            anchor_confidence=confidence if question_no else 0.0,
            score_confidence=0.85 if not score_warning else 0.35,
            block_completeness=0.85 if bbox else 0.55,
            cross_page_merged=bool(raw_question.get("is_continuation") or raw_question.get("continuation")),
            image_cropped=bool(image_block_url),
            image_required_hint=image_required,
            image_attach_recommended=image_attach and not image_required,
            image_strategy="vision_llm_page",
            visual_category=visual_category,
            visual_reason=str(raw_question.get("visual_reason") or ""),
            score_source="vision_llm" if not score_warning else "missing",
            score_reason="视觉大模型从页面直接读取分值。" if not score_warning else "页面未识别到明确分值。",
            formula_enhanced=False,
            formula_strategy="vision_llm",
            line_count=line_count,
            warning_codes=self._warning_codes(audit_warnings),
            notes=[f"vision_model={self.model}"],
        )

        return ParsedQuestion(
            question_no=question_no,
            question_label_raw=raw_label,
            section_index_raw=normalize_section_index_raw(
                self._first_text(raw_question, "section_index_raw", "section", "section_no")
            ),
            question_type=question_type,
            raw_text=raw_text,
            score=score,
            is_optional=bool(raw_question.get("is_optional", False)),
            include_in_main_score=bool(raw_question.get("include_in_main_score", True)),
            parse_confidence=confidence,
            applicable_dims=self._normalize_applicable_dims(raw_question.get("applicable_dims")),
            page_no=page_image.page_no,
            image_block_url=image_block_url,
            block_bbox=bbox,
            question_block=QuestionBlock(
                page_no=page_image.page_no,
                bbox=bbox or {"left": 0, "top": 0, "width": page_image.width, "height": page_image.height},
                line_count=line_count,
                text_density=self._estimate_text_density(raw_text, bbox, page_image),
            ),
            parse_warnings=audit_warnings,
            parse_audit=parse_audit,
            ocr_text_version=VISION_OCR_TEXT_VERSION,
            sub_questions=[],
            sub_item_candidates=[],
        )

    def _preview_question_identity(
        self,
        raw_question: Dict[str, Any],
        page_image: PageImage,
        index: int,
    ) -> Tuple[str, str]:
        raw_label = self._first_text(raw_question, "question_label_raw", "label", "raw_label")
        question_no = self._normalize_question_no(
            self._first_text(raw_question, "question_no", "number", "no") or raw_label
        )
        if not question_no:
            question_no = f"p{page_image.page_no}q{index}"
        section = self._first_text(raw_question, "section_index_raw", "section", "section_no")
        return question_no, section

    def _should_merge_continuation(
        self,
        raw_question: Dict[str, Any],
        continuation: ParsedQuestion,
        previous: ParsedQuestion,
    ) -> bool:
        explicit_no = self._first_text(raw_question, "question_no", "number", "no", "question_label_raw", "label", "raw_label")
        if not explicit_no:
            return True

        if self._looks_like_sub_question_label(raw_question):
            return True

        continuation_no = self._normalize_question_no(explicit_no)
        previous_no = self._normalize_question_no(previous.question_no)
        return bool(continuation_no and continuation_no == previous_no)

    @staticmethod
    def _looks_like_sub_question_label(raw_question: Dict[str, Any]) -> bool:
        candidates = [
            raw_question.get("question_label_raw"),
            raw_question.get("label"),
            raw_question.get("raw_label"),
            raw_question.get("question_no"),
            raw_question.get("number"),
            raw_question.get("no"),
        ]
        raw_text = str(raw_question.get("raw_text") or "").strip()
        if raw_text:
            candidates.append(raw_text[:12])

        for value in candidates:
            text = str(value or "").strip()
            if not text:
                continue
            text = text.replace("（", "(").replace("）", ")")
            if re.match(r"^\(\s*\d{1,2}\s*\)$", text):
                return True
            if re.match(r"^\d{1,2}\s*\)$", text):
                return True
            if re.match(r"^\(\s*\d{1,2}\s*\)", text):
                return True
        return False

    @staticmethod
    def _merge_continuation_question(target: ParsedQuestion, continuation: ParsedQuestion) -> None:
        target.raw_text = f"{target.raw_text}\n[续第 {continuation.page_no} 页]\n{continuation.raw_text}".strip()
        target.parse_confidence = min(target.parse_confidence, continuation.parse_confidence)
        target.parse_warnings = list(
            dict.fromkeys([*target.parse_warnings, "跨页题干已由视觉大模型合并。", *continuation.parse_warnings])
        )
        if target.parse_audit:
            target.parse_audit.cross_page_merged = True
            target.parse_audit.warning_codes = list(
                dict.fromkeys([*target.parse_audit.warning_codes, "cross_page_merged"])
            )

    def _build_question_block_image(
        self,
        page_image: PageImage,
        question_no: str,
        bbox: Optional[Dict[str, int]],
    ) -> Optional[str]:
        if not bbox:
            return None
        try:
            source_path = Path(page_image.path)
            output_dir = source_path.parent.parent / "question_blocks"
            output_dir.mkdir(parents=True, exist_ok=True)
            safe_question_no = re.sub(r"[^0-9A-Za-z_-]+", "_", question_no).strip("_") or "unknown"
            output_path = output_dir / f"page_{page_image.page_no}_q_{safe_question_no}.jpg"

            with Image.open(page_image.path) as image:
                margin_x = max(24, int(image.width * 0.01))
                margin_y = max(24, int(image.height * 0.01))
                left = max(bbox["left"] - margin_x, 0)
                top = max(bbox["top"] - margin_y, 0)
                right = min(bbox["left"] + bbox["width"] + margin_x, image.width)
                bottom = min(bbox["top"] + bbox["height"] + margin_y, image.height)
                if right <= left or bottom <= top:
                    return None
                image.crop((left, top, right, bottom)).save(output_path, format="JPEG", quality=92)
            return str(output_path)
        except Exception as exc:
            logger.warning("Vision question block crop failed page=%s question=%s: %s", page_image.page_no, question_no, exc)
            return None

    @staticmethod
    def _first_text(payload: Dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _string_list(value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    @staticmethod
    def _normalize_question_no(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        text = text.replace("（", "(").replace("）", ")").strip()
        match = re.search(r"(\d{1,3})(?:\s*[.．、题)]|$)", text)
        if match:
            return match.group(1)
        return re.sub(r"\s+", "", text)[:20]

    def _normalize_question_type(self, value: Any, raw_text: str, image_attach: bool) -> QuestionType:
        normalized = str(value or "").strip().lower()
        for item in QuestionType:
            if item.value == normalized:
                return item
        if image_attach:
            return QuestionType.COMPREHENSIVE
        if "选择" in raw_text or re.search(r"\bA[.、]", raw_text):
            return QuestionType.SINGLE_CHOICE
        if "填空" in raw_text or "____" in raw_text or "______" in raw_text:
            return QuestionType.FILL_BLANK
        if "计算" in raw_text:
            return QuestionType.CALCULATION
        if any(token in raw_text for token in ("解答", "求", "证明")):
            return QuestionType.SOLUTION
        return QuestionType.APPLICATION

    @staticmethod
    def _parse_score(value: Any) -> Tuple[float, Optional[str]]:
        if value in (None, ""):
            return 0.0, "未识别到明确分值。"
        try:
            score = float(value)
        except (TypeError, ValueError):
            match = re.search(r"\d+(?:\.\d+)?", str(value))
            if not match:
                return 0.0, "分值格式无法解析。"
            score = float(match.group(0))
        if score < 0:
            return 0.0, "分值为负，已按 0 处理。"
        return score, None

    def _normalize_bbox(self, value: Any, page_image: PageImage) -> Optional[Dict[str, int]]:
        if value in (None, ""):
            return None
        if isinstance(value, (list, tuple)) and len(value) >= 4:
            left, top, third, fourth = [self._coerce_int(item, fallback=0) for item in value[:4]]
            width = third - left if third > left and fourth > top else third
            height = fourth - top if third > left and fourth > top else fourth
            candidate = {"left": left, "top": top, "width": width, "height": height}
        elif isinstance(value, dict):
            left = self._coerce_int(value.get("left", value.get("x", value.get("x1"))), fallback=0)
            top = self._coerce_int(value.get("top", value.get("y", value.get("y1"))), fallback=0)
            if "right" in value or "x2" in value:
                right = self._coerce_int(value.get("right", value.get("x2")), fallback=left)
                width = right - left
            else:
                width = self._coerce_int(value.get("width", value.get("w")), fallback=0)
            if "bottom" in value or "y2" in value:
                bottom = self._coerce_int(value.get("bottom", value.get("y2")), fallback=top)
                height = bottom - top
            else:
                height = self._coerce_int(value.get("height", value.get("h")), fallback=0)
            candidate = {"left": left, "top": top, "width": width, "height": height}
        else:
            return None

        left = max(0, min(candidate["left"], page_image.width - 1))
        top = max(0, min(candidate["top"], page_image.height - 1))
        width = max(1, min(candidate["width"], page_image.width - left))
        height = max(1, min(candidate["height"], page_image.height - top))
        if width < 8 or height < 8:
            return None
        return {"left": left, "top": top, "width": width, "height": height}

    @staticmethod
    def _normalize_applicable_dims(value: Any) -> List[DimensionCode]:
        if not isinstance(value, list):
            return []
        dims: List[DimensionCode] = []
        for item in value:
            try:
                dims.append(DimensionCode(str(getattr(item, "value", item))))
            except ValueError:
                continue
        return list(dict.fromkeys(dims))

    @staticmethod
    def _warning_codes(warnings: Sequence[str]) -> List[str]:
        codes: List[str] = []
        for warning in warnings:
            if "题号" in warning:
                codes.append("question_no_uncertain")
            elif "分值" in warning:
                codes.append("score_uncertain")
            elif "bbox" in warning or "整页图" in warning:
                codes.append("bbox_uncertain")
            elif warning:
                codes.append("vision_llm_warning")
        return list(dict.fromkeys(codes))

    @staticmethod
    def _estimate_text_density(raw_text: str, bbox: Optional[Dict[str, int]], page_image: PageImage) -> float:
        area = (bbox["width"] * bbox["height"]) if bbox else (page_image.width * page_image.height)
        if area <= 0:
            return 0.0
        return max(0.0, min(1.0, len(raw_text) / max(area / 1800.0, 1.0)))

    @staticmethod
    def _coerce_int(value: Any, *, fallback: int) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _coerce_optional_int(value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_float(value: Any, *, fallback: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _find_missing_numbers(question_numbers: Sequence[str]) -> List[str]:
        numeric_values = []
        for item in question_numbers:
            if str(item).isdigit():
                numeric_values.append(int(item))
        if len(numeric_values) < 2:
            return []
        numeric_values = sorted(set(numeric_values))
        expected = set(range(numeric_values[0], numeric_values[-1] + 1))
        return [str(item) for item in sorted(expected - set(numeric_values))]
