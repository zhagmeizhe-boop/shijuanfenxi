"""
OpenAI-compatible LLM client.
Supports internal gateway deployments and other chat/completions compatible APIs.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from app.services.llm.global_limiter import llm_request_slot

logger = logging.getLogger(__name__)


class MoonshotClient:
    """
    OpenAI-compatible LLM client.
    The historical class name is kept for compatibility with existing call sites.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-5",
        base_url: str = "https://one-api.aixuexi.com/v1",
        temperature: float = 0.3,
        max_tokens: int = 4000,
        timeout: float = 60.0,
        llm_pool: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("MOONSHOT_API_KEY")
        if not self.api_key:
            raise ValueError("LLM API Key 未配置")

        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.llm_pool = llm_pool

        logger.info("LLM client initialized model=%s base_url=%s pool=%s", model, self.base_url, self.llm_pool or "global")

    @staticmethod
    def _normalize_response_format(response_format: Optional[Any]) -> Optional[Dict[str, Any]]:
        if response_format is None:
            return None
        if isinstance(response_format, str):
            return {"type": response_format}
        if isinstance(response_format, dict):
            return dict(response_format)
        raise TypeError("response_format must be None, str, or dict")

    @staticmethod
    def _is_response_format_unsupported(error: httpx.HTTPStatusError) -> bool:
        status_code = error.response.status_code
        if status_code not in {400, 404, 415, 422}:
            return False

        body = error.response.text.lower()
        response_format_tokens = (
            "response_format",
            "json_object",
            "json schema",
            "json_schema",
        )
        unsupported_tokens = (
            "unsupported",
            "not support",
            "not supported",
            "unknown",
            "invalid",
            "unrecognized",
        )
        return any(token in body for token in response_format_tokens) and any(
            token in body for token in unsupported_tokens
        )

    async def _post_chat_completion_unlimited(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def _post_chat_completion(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        slot_context = llm_request_slot(pool=self.llm_pool) if self.llm_pool else llm_request_slot()
        async with slot_context:
            return await self._post_chat_completion_unlimited(payload)

    @staticmethod
    def _extract_content(data: Dict[str, Any]) -> str:
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("LLM response missing choices")

        message = choices[0].get("message") or {}
        content = message.get("content", "")

        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts: List[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(str(item.get("text", "")))
            return "".join(text_parts)
        return str(content)

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Any] = None,
    ) -> str:
        """
        Send a chat/completions request.
        If the gateway does not support response_format, retry once without it.
        """
        normalized_response_format = self._normalize_response_format(response_format)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        if normalized_response_format:
            payload["response_format"] = normalized_response_format

        try:
            data = await self._post_chat_completion(payload)
        except httpx.TimeoutException:
            logger.error("LLM API timeout model=%s", self.model)
            raise
        except httpx.HTTPStatusError as exc:
            if normalized_response_format and self._is_response_format_unsupported(exc):
                logger.warning(
                    "Structured output unsupported, retrying without response_format model=%s status=%s",
                    self.model,
                    exc.response.status_code,
                )
                fallback_payload = dict(payload)
                fallback_payload.pop("response_format", None)
                data = await self._post_chat_completion(fallback_payload)
            else:
                logger.error("LLM API HTTP error status=%s body=%s", exc.response.status_code, exc.response.text)
                raise
        except Exception as exc:
            logger.error("LLM API request failed: %s", exc)
            raise

        usage = data.get("usage") or {}
        logger.info(
            "LLM API request succeeded model=%s prompt_tokens=%s completion_tokens=%s",
            self.model,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
        )
        return self._extract_content(data)
