"""
OCR Provider 工厂

用于管理和创建不同的 OCR Provider 实例
"""

from typing import Dict, Type, Optional, Any
import logging

from app.services.ocr.base import BaseOCRProvider
from app.services.ocr.mock_provider import MockOCRProvider
from app.services.ocr.baidu_provider import BaiduOCRProvider
from app.core.config import settings

logger = logging.getLogger(__name__)


class OCRProviderFactory:
    """
    OCR Provider 工厂

    用于创建和管理 OCR Provider 实例
    """

    # 注册的 provider 类
    _providers: Dict[str, Type[BaseOCRProvider]] = {
        "mock": MockOCRProvider,
        "baidu": BaiduOCRProvider,
    }

    # 缓存的 provider 实例
    _instances: Dict[str, BaseOCRProvider] = {}

    @classmethod
    def register_provider(cls, name: str, provider_class: Type[BaseOCRProvider]) -> None:
        """
        注册新的 OCR Provider

        Args:
            name: Provider 名称
            provider_class: Provider 类
        """
        cls._providers[name] = provider_class
        logger.info(f"Registered OCR provider: {name}")

    @classmethod
    def create_provider(
        cls,
        provider_name: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
    ) -> BaseOCRProvider:
        """
        创建 OCR Provider 实例

        Args:
            provider_name: Provider 名称，如果为 None 则使用配置中的默认 provider
            config: Provider 配置
            use_cache: 是否使用缓存

        Returns:
            BaseOCRProvider: Provider 实例

        Raises:
            ValueError: 如果 provider 名称无效
        """
        # 确定 provider 名称
        if provider_name is None:
            provider_name = settings.OCR_PROVIDER

        # 检查缓存
        cache_key = f"{provider_name}_{hash(str(config))}"
        if use_cache and cache_key in cls._instances:
            logger.debug(f"Using cached OCR provider: {provider_name}")
            return cls._instances[cache_key]

        # 创建新的实例
        if provider_name not in cls._providers:
            available = ", ".join(cls._providers.keys())
            raise ValueError(
                f"Unknown OCR provider: {provider_name}. "
                f"Available providers: {available}"
            )

        provider_class = cls._providers[provider_name]
        instance = provider_class(config)

        # 缓存实例
        if use_cache:
            cls._instances[cache_key] = instance

        logger.info(f"Created OCR provider: {provider_name}")
        return instance

    @classmethod
    def get_available_providers(cls) -> Dict[str, str]:
        """
        获取可用的 provider 列表

        Returns:
            Dict[str, str]: provider 名称和描述的映射
        """
        return {
            "mock": "Mock OCR Provider (for development and testing)",
            "baidu": "Baidu OCR API (production ready, 50000 free calls/day)",
        }

    @classmethod
    def clear_cache(cls) -> None:
        """清除缓存的 provider 实例"""
        cls._instances.clear()
        logger.info("Cleared OCR provider cache")


# 便捷的创建函数
def get_ocr_provider(
    provider_name: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> BaseOCRProvider:
    """
    获取 OCR Provider 实例的便捷函数

    Args:
        provider_name: Provider 名称
        config: Provider 配置

    Returns:
        BaseOCRProvider: Provider 实例
    """
    return OCRProviderFactory.create_provider(provider_name, config)
