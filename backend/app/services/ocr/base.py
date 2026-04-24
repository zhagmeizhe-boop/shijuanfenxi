from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging
import asyncio

logger = logging.getLogger(__name__)


class OCROutput:
    """OCR 识别结果"""
    def __init__(
        self,
        text: str,
        confidence: float,
        bbox: Optional[Dict[str, Any]] = None,
        page: int = 1,
        block_type: str = "text",
    ):
        self.text = text
        self.confidence = confidence
        self.bbox = bbox or {}
        self.page = page
        self.block_type = block_type  # text, image, table, formula

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "bbox": self.bbox,
            "page": self.page,
            "block_type": self.block_type,
        }


class OCRProvider(ABC):
    """
    OCR Provider 抽象基类

    所有 OCR 实现都需要继承此类，实现统一的接口
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    async def recognize(
        self,
        file_path: str,
        **kwargs
    ) -> List[OCROutput]:
        """
        识别文件中的文字

        Args:
            file_path: 文件路径
            **kwargs: 额外的识别参数

        Returns:
            List[OCROutput]: 识别结果列表
        """
        pass

    @abstractmethod
    async def recognize_pdf(
        self,
        file_path: str,
        **kwargs
    ) -> List[OCROutput]:
        """
        识别 PDF 文件

        Args:
            file_path: PDF 文件路径
            **kwargs: 额外的识别参数

        Returns:
            List[OCROutput]: 识别结果列表
        """
        pass

    @abstractmethod
    async def recognize_image(
        self,
        file_path: str,
        **kwargs
    ) -> List[OCROutput]:
        """
        识别图片文件

        Args:
            file_path: 图片文件路径
            **kwargs: 额外的识别参数

        Returns:
            List[OCROutput]: 识别结果列表
        """
        pass

    def validate_config(self) -> bool:
        """
        验证配置是否完整

        Returns:
            bool: 配置是否有效
        """
        return True

    async def health_check(self) -> Dict[str, Any]:
        """
        健康检查

        Returns:
            dict: 健康状态
        """
        return {
            "status": "unknown",
            "provider": self.__class__.__name__,
            "message": "Health check not implemented",
        }
