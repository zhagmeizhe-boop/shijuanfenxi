"""
OpenAI-compatible LLM 客户端

支持公司内网 API 网关及其他 OpenAI-compatible 接口
"""

import os
import json
import logging
from typing import Dict, Any, Optional
import httpx

logger = logging.getLogger(__name__)


class MoonshotClient:
    """
    OpenAI-compatible LLM 客户端
    支持公司内网网关（claude-sonnet-4-5 等）及 Moonshot 模型
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-5",
        base_url: str = "https://one-api.aixuexi.com/v1",
        temperature: float = 0.3,
        max_tokens: int = 4000,
        timeout: float = 60.0,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("MOONSHOT_API_KEY")
        if not self.api_key:
            raise ValueError("LLM API Key 未配置")

        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        logger.info(f"LLM Client 初始化完成，模型: {model}, base_url: {base_url}")

    async def chat(
        self,
        messages: list,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        发送对话请求
        """
        url = f"{self.base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()

                data = response.json()
                content = data["choices"][0]["message"]["content"]

                # 记录token消耗
                usage = data.get("usage", {})
                logger.info(
                    f"LLM API 调用成功，模型: {self.model}，"
                    f"输入: {usage.get('prompt_tokens', 0)}, "
                    f"输出: {usage.get('completion_tokens', 0)}"
                )

                return content

        except httpx.TimeoutException:
            logger.error(f"LLM API 调用超时（模型: {self.model}）")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"LLM API HTTP错误: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"LLM API 调用异常: {e}")
            raise
