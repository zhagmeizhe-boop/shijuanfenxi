import asyncio
import base64
import io
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from app.core.config import settings
from app.services.ocr.baidu_provider import BaiduOCRProvider
from app.services.ocr.factory import (
    OCRProviderFactory,
    create_ocr_provider,
    get_ocr_preflight_status,
    get_ocr_provider_config,
)
from app.services.ocr.mock_provider import MockOCRProvider
from app.services.ocr.paddleocr_provider import PaddleOCRProvider
from app.services.ocr.vision_llm_provider import VisionLLMProvider


@pytest.fixture(autouse=True)
def clear_ocr_provider_cache():
    OCRProviderFactory.clear_cache()
    yield
    OCRProviderFactory.clear_cache()


def test_factory_lists_vision_llm_provider():
    providers = OCRProviderFactory.get_available_providers()

    assert "vision_llm" in providers
    assert "paddleocr" in providers
    assert "mock" in providers
    assert "baidu" in providers


def test_create_ocr_provider_uses_vision_llm_by_default(monkeypatch):
    monkeypatch.setattr(settings, "OCR_PROVIDER", "vision_llm")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setattr(settings, "MOONSHOT_API_KEY", "moonshot-key")
    monkeypatch.setattr(settings, "LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setattr(settings, "CLAUDE_MODEL", "claude-vision")
    monkeypatch.setattr(settings, "VISION_LLM_MODEL", None)

    provider = create_ocr_provider()

    assert isinstance(provider, VisionLLMProvider)
    assert provider.api_key == "anthropic-key"
    assert provider.base_url == "https://llm.example/v1"
    assert provider.model == "claude-vision"


def test_create_ocr_provider_supports_mock_and_legacy_baidu(monkeypatch):
    monkeypatch.setattr(settings, "OCR_PROVIDER", "mock")
    assert isinstance(create_ocr_provider(), MockOCRProvider)

    OCRProviderFactory.clear_cache()
    monkeypatch.setattr(settings, "OCR_PROVIDER", "baidu")
    provider = create_ocr_provider()
    assert isinstance(provider, BaiduOCRProvider)


def test_get_ocr_provider_config_builds_vision_payload(monkeypatch):
    monkeypatch.setattr(settings, "OCR_PROVIDER", "vision_llm")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(settings, "MOONSHOT_API_KEY", "moonshot-key")
    monkeypatch.setattr(settings, "LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setattr(settings, "CLAUDE_MODEL", "claude-default")
    monkeypatch.setattr(settings, "VISION_LLM_MODEL", "vision-model")
    monkeypatch.setattr(settings, "VISION_LLM_CONCURRENCY", 3)
    monkeypatch.setattr(settings, "VISION_LLM_PAGE_TIMEOUT", 75.0)
    monkeypatch.setattr(settings, "VISION_LLM_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "VISION_LLM_RETRY_BASE_SECONDS", 0.25)
    monkeypatch.setattr(settings, "VISION_LLM_RENDER_DPI", 160)
    monkeypatch.setattr(settings, "VISION_LLM_MAX_TOKENS", 12000)

    config = get_ocr_provider_config()

    assert config["api_key"] == "moonshot-key"
    assert config["base_url"] == "https://llm.example/v1"
    assert config["model"] == "vision-model"
    assert config["concurrency"] == 3
    assert config["page_timeout"] == 75.0
    assert config["max_attempts"] == 2
    assert config["retry_base_seconds"] == 0.25
    assert config["render_dpi"] == 160
    assert config["max_tokens"] == 12000


def test_get_ocr_provider_config_builds_paddle_payload(monkeypatch):
    monkeypatch.setattr(settings, "OCR_PROVIDER", "paddleocr")
    monkeypatch.setattr(settings, "PADDLE_OCR_LANG", "ch")
    monkeypatch.setattr(settings, "PADDLE_OCR_USE_ANGLE_CLS", True)
    monkeypatch.setattr(settings, "PADDLE_OCR_USE_GPU", False)
    monkeypatch.setattr(settings, "PADDLE_OCR_MODEL_DIR", None)
    monkeypatch.setattr(settings, "POPPLER_PATH", "D:\\poppler\\bin")

    config = get_ocr_provider_config()

    assert config["lang"] == "ch"
    assert config["use_angle_cls"] is True
    assert config["use_gpu"] is False
    assert config["poppler_path"] == "D:\\poppler\\bin"


def test_ocr_preflight_uses_provider_health(monkeypatch):
    monkeypatch.setattr(settings, "OCR_PROVIDER", "vision_llm")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setattr(settings, "MOONSHOT_API_KEY", None)

    with patch.object(
        VisionLLMProvider,
        "health_check",
        new=AsyncMock(return_value={"status": "healthy", "provider": "VisionLLMProvider", "message": "ready"}),
    ):
        status = asyncio.run(get_ocr_preflight_status())

    assert status["ocr_ready"] is True
    assert status["provider"] == "vision_llm"
    assert status["message"] == "ready"


def test_ocr_preflight_reports_provider_init_failure(monkeypatch):
    monkeypatch.setattr(settings, "OCR_PROVIDER", "vision_llm")

    with patch(
        "app.services.ocr.factory.create_ocr_provider",
        side_effect=RuntimeError("Vision LLM 未就绪"),
    ):
        status = asyncio.run(get_ocr_preflight_status())

    assert status["ocr_ready"] is False
    assert status["provider"] == "vision_llm"
    assert "Vision LLM 未就绪" in status["message"]


def test_paddle_orientation_normalization_rotates_sideways_pages(tmp_path):
    image_path = tmp_path / "sideways.jpg"
    Image.new("RGB", (1200, 800), "white").save(image_path, format="JPEG")

    provider = PaddleOCRProvider(config={})

    async def fake_recognize(image_base64: str):
        with Image.open(io.BytesIO(base64.b64decode(image_base64))) as image:
            orientation = "portrait" if image.height > image.width else "landscape"
        return {
            "orientation": orientation,
            "words_result": [],
            "probability": {"average": 0.9},
        }

    provider._recognize_text = fake_recognize
    provider._score_orientation_result = lambda result: 10.0 if result["orientation"] == "portrait" else 1.0

    normalized_path, normalized_result, rotation = asyncio.run(
        provider._normalize_page_orientation(str(image_path), page_no=1)
    )

    assert rotation in (90, 270)
    assert normalized_path != str(image_path)
    assert normalized_result["orientation"] == "portrait"
