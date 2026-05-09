"""
Anthropic Claude 客户端

用于调用 Claude claude-sonnet-4-6 进行题目特征提取
"""

import os
import logging
from typing import List, Optional

import httpx

from app.services.llm.global_limiter import llm_request_slot

logger = logging.getLogger(__name__)


class ClaudeClient:
    """
    Anthropic Claude API 客户端

    使用 Anthropic 原生 /v1/messages 接口
    """

    BASE_URL = "https://api.anthropic.com/v1/messages"
    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-6",
        temperature: float = 0.3,
        max_tokens: int = 2000,
        timeout: float = 60.0,
        llm_pool: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("Anthropic API Key 未配置，请设置环境变量 ANTHROPIC_API_KEY")

        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.llm_pool = llm_pool

        logger.info("ClaudeClient initialized model=%s pool=%s", model, self.llm_pool or "global")

    async def chat(
        self,
        messages: List[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        发送对话请求

        Args:
            messages: OpenAI 格式的消息列表，支持 system/user/assistant 角色
            temperature: 温度（可选，覆盖默认值）
            max_tokens: 最大 token 数（可选，覆盖默认值）

        Returns:
            str: 模型回复的文本内容
        """
        # 将 OpenAI 格式的 messages 转换为 Anthropic 格式
        # Anthropic 要求 system 消息单独传，user/assistant 消息放在 messages 列表
        system_content = None
        anthropic_messages = []

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                system_content = content
            else:
                anthropic_messages.append({"role": role, "content": content})

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        payload = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature or self.temperature,
            "messages": anthropic_messages,
        }

        if system_content:
            payload["system"] = system_content

        try:
            slot_context = llm_request_slot(pool=self.llm_pool) if self.llm_pool else llm_request_slot()
            async with slot_context:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(self.BASE_URL, headers=headers, json=payload)
                    response.raise_for_status()

                    data = response.json()
                    content = data["content"][0]["text"]

                    # 记录 token 消耗
                    usage = data.get("usage", {})
                    logger.info(
                        f"Claude API 调用成功，输入: {usage.get('input_tokens', 0)}, "
                        f"输出: {usage.get('output_tokens', 0)}"
                    )

                    return content

        except httpx.TimeoutException:
            logger.error("Claude API 调用超时")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"Claude API HTTP 错误: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Claude API 调用异常: {e}")
            raise
