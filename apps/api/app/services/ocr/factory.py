"""
OCR provider factory and runtime preflight helpers.
"""

from __future__ import annotations

import logging
import importlib
from typing import Any, Dict, Optional, Type, TypedDict

from app.core.config import settings
from app.services.ocr.base import BaseOCRProvider

logger = logging.getLogger(__name__)


class OCRPreflightStatus(TypedDict):
    ocr_ready: bool
    provider: str
    message: str


class OCRProviderFactory:
    """Factory for OCR providers."""

    _providers: Dict[str, Type[BaseOCRProvider] | str] = {
        "mock": "app.services.ocr.mock_provider.MockOCRProvider",
        "vision_llm": "app.services.ocr.vision_llm_provider.VisionLLMProvider",
        "paddleocr": "app.services.ocr.paddleocr_provider.PaddleOCRProvider",
        "baidu": "app.services.ocr.baidu_provider.BaiduOCRProvider",
    }
    _instances: Dict[str, BaseOCRProvider] = {}

    @classmethod
    def _resolve_provider_class(cls, provider_name: str) -> Type[BaseOCRProvider]:
        provider_spec = cls._providers[provider_name]
        if isinstance(provider_spec, str):
            module_name, class_name = provider_spec.rsplit(".", 1)
            module = importlib.import_module(module_name)
            provider_class = getattr(module, class_name)
            cls._providers[provider_name] = provider_class
            return provider_class
        return provider_spec

    @classmethod
    def register_provider(cls, name: str, provider_class: Type[BaseOCRProvider]) -> None:
        cls._providers[name] = provider_class
        logger.info("Registered OCR provider: %s", name)

    @classmethod
    def create_provider(
        cls,
        provider_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
    ) -> BaseOCRProvider:
        provider_name = provider_name or settings.OCR_PROVIDER
        cache_key = f"{provider_name}_{hash(str(config))}"

        if use_cache and cache_key in cls._instances:
            logger.debug("Using cached OCR provider: %s", provider_name)
            return cls._instances[cache_key]

        if provider_name not in cls._providers:
            available = ", ".join(sorted(cls._providers.keys()))
            raise ValueError(f"Unknown OCR provider: {provider_name}. Available providers: {available}")

        provider_class = cls._resolve_provider_class(provider_name)
        instance = provider_class(config)
        if use_cache:
            cls._instances[cache_key] = instance

        logger.info("Created OCR provider: %s", provider_name)
        return instance

    @classmethod
    def get_available_providers(cls) -> Dict[str, str]:
        return {
            "mock": "Mock OCR provider (tests or explicit local debugging only)",
            "vision_llm": "Vision LLM provider (default; no OCR engine)",
            "paddleocr": "Legacy PaddleOCR local provider",
            "baidu": "Legacy Baidu OCR API provider",
        }

    @classmethod
    def clear_cache(cls) -> None:
        cls._instances.clear()
        logger.info("Cleared OCR provider cache")


def get_ocr_provider_config(provider_name: Optional[str] = None) -> Dict[str, Any]:
    provider_name = provider_name or settings.OCR_PROVIDER

    if provider_name == "baidu":
        return {
            "app_id": settings.BAIDU_OCR_APP_ID,
            "api_key": settings.BAIDU_OCR_API_KEY,
            "secret_key": settings.BAIDU_OCR_SECRET_KEY,
            "poppler_path": settings.POPPLER_PATH,
        }

    if provider_name == "paddleocr":
        return {
            "lang": settings.PADDLE_OCR_LANG,
            "use_angle_cls": settings.PADDLE_OCR_USE_ANGLE_CLS,
            "use_gpu": settings.PADDLE_OCR_USE_GPU,
            "model_dir": settings.PADDLE_OCR_MODEL_DIR,
            "poppler_path": settings.POPPLER_PATH,
        }

    if provider_name == "vision_llm":
        return {
            "api_key": settings.ANTHROPIC_API_KEY or settings.MOONSHOT_API_KEY,
            "base_url": settings.LLM_BASE_URL,
            "model": settings.VISION_LLM_MODEL or settings.CLAUDE_MODEL,
            "concurrency": settings.VISION_LLM_CONCURRENCY,
            "page_timeout": settings.VISION_LLM_PAGE_TIMEOUT,
            "render_dpi": settings.VISION_LLM_RENDER_DPI,
            "max_tokens": settings.VISION_LLM_MAX_TOKENS,
        }

    return {}


def create_ocr_provider(provider_name: Optional[str] = None, *, use_cache: bool = True) -> BaseOCRProvider:
    selected_provider = provider_name or settings.OCR_PROVIDER
    return OCRProviderFactory.create_provider(
        provider_name=selected_provider,
        config=get_ocr_provider_config(selected_provider),
        use_cache=use_cache,
    )


async def get_ocr_preflight_status(provider_name: Optional[str] = None) -> OCRPreflightStatus:
    selected_provider = provider_name or settings.OCR_PROVIDER

    try:
        provider = create_ocr_provider(selected_provider)
    except Exception as exc:
        logger.warning("OCR provider creation failed provider=%s detail=%s", selected_provider, exc)
        return {
            "ocr_ready": False,
            "provider": selected_provider,
            "message": f"OCR provider 初始化失败: {exc}",
        }

    try:
        health = await provider.health_check()
    except Exception as exc:
        logger.warning("OCR preflight failed provider=%s detail=%s", selected_provider, exc, exc_info=True)
        return {
            "ocr_ready": False,
            "provider": selected_provider,
            "message": f"OCR preflight 失败: {exc}",
        }

    status = str(health.get("status", "")).lower() == "healthy"
    message = str(health.get("message") or "").strip() or "OCR preflight completed"
    return {
        "ocr_ready": status,
        "provider": selected_provider,
        "message": message,
    }


def get_ocr_provider(
    provider_name: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> BaseOCRProvider:
    return OCRProviderFactory.create_provider(provider_name, config)
