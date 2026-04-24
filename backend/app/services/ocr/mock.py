from typing import List, Dict, Any, Optional
import logging
import random
import asyncio

from app.services.ocr.base import OCRProvider, OCROutput

logger = logging.getLogger(__name__)


class MockOCRProvider(OCRProvider):
    """
    Mock OCR Provider

    用于开发和测试环境，模拟 OCR 识别结果
    无需真实 OCR 服务即可进行开发调试
    """

    # 模拟识别文本库
    SAMPLE_TEXTS = [
        "1. 计算：3/4 + 2/5 = ?",
        "2. 找出下列数字的规律：2, 6, 12, 20, __",
        "3. 一个长方形的长是12厘米，宽是8厘米，求它的面积。",
        "4. 小明有36颗糖，分给4个小朋友，每人分得多少颗？",
        "5. 化简：2/8 = ?",
        "6. 计算：125 × 8 = ?",
        "7. 一个正方形的周长是24厘米，求它的边长。",
        "8. 3/5 + 1/4 = ?",
        "9. 25的3倍是多少？",
        "10. 一本书有120页，小明第一天看了1/4，第二天看了1/3，还剩多少页没看？",
    ]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.delay_range = config.get("delay_range", (0.5, 2.0)) if config else (0.5, 2.0)
        self.confidence_range = config.get("confidence_range", (0.85, 0.99)) if config else (0.85, 0.99)
        self.error_rate = config.get("error_rate", 0.0) if config else 0.0

    async def recognize(
        self,
        file_path: str,
        **kwargs
    ) -> List[OCROutput]:
        """
        模拟识别文件

        根据文件类型自动选择对应的模拟方法
        """
        # 模拟处理延迟
        delay = random.uniform(*self.delay_range)
        await asyncio.sleep(delay)

        # 模拟错误
        if random.random() < self.error_rate:
            raise Exception("Mock OCR recognition failed")

        # 根据文件扩展名选择处理方法
        if file_path.lower().endswith('.pdf'):
            return await self.recognize_pdf(file_path, **kwargs)
        else:
            return await self.recognize_image(file_path, **kwargs)

    async def recognize_pdf(
        self,
        file_path: str,
        **kwargs
    ) -> List[OCROutput]:
        """模拟识别 PDF 文件"""
        num_pages = kwargs.get('num_pages', random.randint(1, 3))
        results = []

        for page in range(1, num_pages + 1):
            # 每页随机生成 3-8 个文本块
            num_blocks = random.randint(3, 8)
            for block_idx in range(num_blocks):
                text = random.choice(self.SAMPLE_TEXTS)
                confidence = random.uniform(*self.confidence_range)

                # 模拟边界框
                bbox = {
                    "x": random.randint(50, 200),
                    "y": random.randint(100 + block_idx * 50, 150 + block_idx * 50),
                    "width": random.randint(300, 500),
                    "height": random.randint(30, 50),
                }

                results.append(OCROutput(
                    text=text,
                    confidence=confidence,
                    bbox=bbox,
                    page=page,
                    block_type="text",
                ))

        return results

    async def recognize_image(
        self,
        file_path: str,
        **kwargs
    ) -> List[OCROutput]:
        """模拟识别图片文件"""
        num_blocks = kwargs.get('num_blocks', random.randint(5, 15))
        results = []

        for i in range(num_blocks):
            text = random.choice(self.SAMPLE_TEXTS)
            confidence = random.uniform(*self.confidence_range)

            # 模拟边界框
            bbox = {
                "x": random.randint(30, 100),
                "y": random.randint(50 + i * 40, 80 + i * 40),
                "width": random.randint(400, 600),
                "height": random.randint(25, 45),
            }

            results.append(OCROutput(
                text=text,
                confidence=confidence,
                bbox=bbox,
                page=1,
                block_type="text",
            ))

        return results

    async def health_check(self) -> dict:
        """健康检查"""
        return {
            "status": "healthy",
            "provider": "MockOCRProvider",
            "message": "Mock OCR provider is ready (for development only)",
            "config": {
                "delay_range": self.delay_range,
                "confidence_range": self.confidence_range,
                "error_rate": self.error_rate,
            },
        }
