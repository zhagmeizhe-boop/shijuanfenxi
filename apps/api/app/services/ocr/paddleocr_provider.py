from __future__ import annotations

import base64
import importlib
import io
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image

from app.services.ocr.baidu_provider import BaiduOCRProvider
from app.services.ocr.base import BaseOCRProvider

logger = logging.getLogger(__name__)


class PaddleOCRProvider(BaiduOCRProvider):
    """Local PaddleOCR-backed provider that reuses the structured parsing pipeline."""

    PROVIDER_NAME = "PaddleOCRProvider"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        BaseOCRProvider.__init__(self, config)
        self.poppler_path = self.config.get("poppler_path")
        self.lang = str(self.config.get("lang") or "ch")
        self.use_angle_cls = bool(self.config.get("use_angle_cls", True))
        self.use_gpu = bool(self.config.get("use_gpu", False))
        self.model_dir = self.config.get("model_dir")
        self._ocr_engine: Any = None
        self._paddleocr_version = "unknown"

    def _load_paddleocr_class(self):
        try:
            module = importlib.import_module("paddleocr")
        except ModuleNotFoundError as exc:
            raise RuntimeError("PaddleOCR 未安装，请先安装 paddleocr") from exc

        self._paddleocr_version = getattr(module, "__version__", "unknown")
        return module.PaddleOCR

    def _resolve_model_home(self) -> Path:
        if self.model_dir:
            base_dir = Path(self.model_dir)
        else:
            if os.name == "nt":
                base_dir = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "math-report" / "paddleocr"
            else:
                base_dir = Path(__file__).resolve().parents[3] / "data" / "paddleocr"
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir

    def _prepare_runtime_env(self) -> Path:
        base_dir = self._resolve_model_home()
        os.environ.setdefault("PADDLE_HOME", str(base_dir))
        os.environ.setdefault("PADDLEOCR_HOME", str(base_dir))
        return base_dir

    def _resolve_model_dirs(self) -> Dict[str, str]:
        base_dir = self._prepare_runtime_env()
        child_map = {
            "det_model_dir": base_dir / "det",
            "rec_model_dir": base_dir / "rec",
            "cls_model_dir": base_dir / "cls",
        }
        for path in child_map.values():
            path.mkdir(parents=True, exist_ok=True)
        return {key: str(path) for key, path in child_map.items()}

    def _ensure_poppler_ready(self) -> None:
        executable_name = "pdftoppm.exe" if os.name == "nt" else "pdftoppm"

        if self.poppler_path:
            candidate = Path(self.poppler_path) / executable_name
            if candidate.exists():
                return
            raise RuntimeError(f"Poppler 不可用，未找到 {candidate}")

        if shutil.which("pdftoppm") or shutil.which("pdftoppm.exe"):
            return

        raise RuntimeError("Poppler 不可用，未找到 pdftoppm 可执行文件")

    def _get_engine(self):
        if self._ocr_engine is not None:
            return self._ocr_engine

        paddleocr_cls = self._load_paddleocr_class()
        engine_kwargs: Dict[str, Any] = {
            "use_angle_cls": self.use_angle_cls,
            "lang": self.lang,
            "use_gpu": self.use_gpu,
            "show_log": False,
        }
        engine_kwargs.update(self._resolve_model_dirs())

        self._ocr_engine = paddleocr_cls(**engine_kwargs)
        logger.info(
            "PaddleOCR engine initialized lang=%s use_angle_cls=%s use_gpu=%s",
            self.lang,
            self.use_angle_cls,
            self.use_gpu,
        )
        return self._ocr_engine

    @staticmethod
    def _format_runtime_error(exc: Exception) -> str:
        message = str(exc).strip()
        lowered = message.lower()

        if "拒绝访问" in message or "access is denied" in lowered:
            return f"PaddleOCR 模型目录不可写: {message}"
        if "max retries exceeded" in lowered or "failed to establish a new connection" in lowered:
            return "PaddleOCR 模型未就绪，且当前环境无法联网下载模型"
        if "pdftoppm" in lowered or "poppler" in lowered:
            return message
        return message or exc.__class__.__name__

    @staticmethod
    def _decode_base64_image(image_base64: str):
        try:
            import numpy as np
        except ModuleNotFoundError as exc:
            raise RuntimeError("PaddleOCR 缺少 numpy 运行时依赖") from exc

        binary = base64.b64decode(image_base64)
        with Image.open(io.BytesIO(binary)) as image:
            rgb_image = image.convert("RGB")
            return np.asarray(rgb_image)

    @staticmethod
    def _extract_page_entries(raw_result: Any) -> Sequence[Any]:
        if not isinstance(raw_result, list):
            return []

        if (
            len(raw_result) == 1
            and isinstance(raw_result[0], list)
            and raw_result[0]
            and isinstance(raw_result[0][0], (list, tuple))
            and len(raw_result[0][0]) >= 2
        ):
            return raw_result[0]

        return raw_result

    async def _recognize_text(self, image_base64: str) -> Dict[str, Any]:
        image_array = self._decode_base64_image(image_base64)
        engine = self._get_engine()
        raw_result = engine.ocr(image_array, cls=self.use_angle_cls)
        page_entries = self._extract_page_entries(raw_result)

        words_result: List[Dict[str, Any]] = []
        confidences: List[float] = []

        for entry in page_entries:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue

            box, recognition = entry[0], entry[1]
            if not box or not recognition:
                continue

            text = str(recognition[0] if len(recognition) > 0 else "").strip()
            if not text:
                continue

            try:
                confidence = float(recognition[1]) if len(recognition) > 1 else 0.0
            except (TypeError, ValueError):
                confidence = 0.0

            try:
                xs = [int(point[0]) for point in box]
                ys = [int(point[1]) for point in box]
            except (TypeError, ValueError, IndexError):
                continue

            words_result.append(
                {
                    "words": text,
                    "location": {
                        "left": min(xs),
                        "top": min(ys),
                        "width": max(max(xs) - min(xs), 1),
                        "height": max(max(ys) - min(ys), 1),
                    },
                    "probability": {"average": confidence},
                }
            )
            confidences.append(confidence)

        average_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return {
            "direction": 0,
            "words_result": words_result,
            "words_result_num": len(words_result),
            "probability": {"average": average_confidence},
        }

    async def _recognize_formula(self, image_base64: str) -> Dict[str, Any]:
        del image_base64
        return {
            "words_result": [],
            "probability": {"average": 0.0},
        }

    def _score_orientation_result(self, ocr_result: Dict[str, Any]) -> float:
        lines = self._extract_ocr_lines(ocr_result)
        if not lines:
            return -10_000.0

        page_width, page_height = self._page_metrics(lines)
        zone_left = min((line.left for line in lines), default=0)
        anchors = self._detect_question_anchors(
            lines,
            zone_left,
            allow_parenthesized=False,
        )
        heading_count = sum(1 for line in lines if self._extract_section_index_raw(line.text))
        readable_line_count = sum(1 for line in lines if len(str(line.text or "").strip()) >= 3)
        average_confidence = float(ocr_result.get("probability", {}).get("average", 0.0) or 0.0)
        portrait_bonus = 6.0 if page_height >= page_width else 0.0
        landscape_penalty = 8.0 if page_width > page_height * 1.2 else 0.0
        return (
            len(anchors) * 12.0
            + heading_count * 16.0
            + min(readable_line_count, 30) * 0.4
            + average_confidence * 5.0
            + portrait_bonus
            - landscape_penalty
        )

    async def _normalize_page_orientation(
        self,
        image_path: str,
        *,
        page_no: int,
    ) -> Tuple[str, Dict[str, Any], int]:
        source_path = Path(image_path)
        normalized_dir = source_path.parent / "ocr_normalized"
        normalized_dir.mkdir(parents=True, exist_ok=True)

        best_path = image_path
        best_result: Optional[Dict[str, Any]] = None
        best_rotation = 0
        best_score = float("-inf")
        cleanup_candidates: List[str] = []

        with Image.open(image_path) as image:
            for rotation in (0, 90, 270, 180):
                candidate_path = image_path
                if rotation != 0:
                    candidate_path = str(
                        normalized_dir / f"{source_path.stem}_p{page_no}_rot{rotation}.jpg"
                    )
                    rotated = image.rotate(rotation, expand=True, fillcolor="white")
                    rotated.save(candidate_path, format="JPEG", quality=95)
                    cleanup_candidates.append(candidate_path)

                result = await self._recognize_text(self._image_to_base64(candidate_path))
                score = self._score_orientation_result(result)
                logger.info(
                    "PaddleOCR orientation probe page=%s rotation=%s score=%.2f",
                    page_no,
                    rotation,
                    score,
                )
                if score > best_score:
                    best_score = score
                    best_path = candidate_path
                    best_result = result
                    best_rotation = rotation

        for candidate_path in cleanup_candidates:
            if candidate_path == best_path:
                continue
            try:
                os.remove(candidate_path)
            except OSError:
                pass

        if best_result is None:
            best_result = await self._recognize_text(self._image_to_base64(image_path))
            best_path = image_path
            best_rotation = 0

        if best_rotation:
            logger.info(
                "PaddleOCR page orientation normalized page=%s rotation=%s",
                page_no,
                best_rotation,
            )

        return best_path, best_result, best_rotation

    async def parse(self, file_path: str, **kwargs):
        logger.info("Using OCR provider: paddleocr")
        return await super().parse(file_path, **kwargs)

    async def health_check(self) -> Dict[str, Any]:
        try:
            self._ensure_poppler_ready()
            self._get_engine()
            return {
                "status": "healthy",
                "provider": self.PROVIDER_NAME,
                "message": "PaddleOCR 本地 OCR 已就绪",
                "version": self._paddleocr_version,
                "capabilities": {
                    "supports_pdf": True,
                    "supports_images": True,
                    "supports_formula": False,
                    "structured_question_blocks": True,
                    "sub_item_candidates": True,
                },
            }
        except Exception as exc:
            message = self._format_runtime_error(exc)
            logger.error("PaddleOCR health check failed: %s", exc)
            return {
                "status": "unhealthy",
                "provider": self.PROVIDER_NAME,
                "message": message,
                "version": self._paddleocr_version,
            }
