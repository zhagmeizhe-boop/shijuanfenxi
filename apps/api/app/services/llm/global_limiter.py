from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

LLMPoolName = Literal["vision", "question"]

GLOBAL_LLM_SLOT_KEY = "math-analysis:llm:global-slots"
VISION_LLM_SLOT_KEY = "math-analysis:llm:vision-slots"
QUESTION_LLM_SLOT_KEY = "math-analysis:llm:question-slots"

# Backward-compatible alias for older tests/imports.
LLM_SLOT_KEY = GLOBAL_LLM_SLOT_KEY

_ACQUIRE_SLOT_SCRIPT = """
redis.call("ZREMRANGEBYSCORE", KEYS[1], "-inf", ARGV[1])
local limit = tonumber(ARGV[2])
local count = redis.call("ZCARD", KEYS[1])
if count >= limit then
    return 0
end
redis.call("ZADD", KEYS[1], ARGV[3], ARGV[4])
redis.call("EXPIRE", KEYS[1], ARGV[5])
return 1
"""


class GlobalLLMConcurrencyTimeout(TimeoutError):
    """Raised when an LLM request waits too long for a global slot."""


class GlobalLLMConcurrencyBackendError(RuntimeError):
    """Raised when Redis cannot be used for global LLM coordination."""


@dataclass(frozen=True)
class LLMSlot:
    token: str
    managed: bool
    key: str = GLOBAL_LLM_SLOT_KEY
    client: Optional[Any] = None


def _load_async_redis():
    try:
        import redis.asyncio as redis_async
    except ModuleNotFoundError as exc:
        raise GlobalLLMConcurrencyBackendError("Redis dependency is not installed") from exc
    return redis_async


def _create_async_redis_client(redis_url: str):
    redis_async = _load_async_redis()
    return redis_async.Redis.from_url(
        redis_url,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
        health_check_interval=0,
        decode_responses=True,
    )


def _pool_slot_key(pool: LLMPoolName) -> str:
    if pool == "vision":
        return VISION_LLM_SLOT_KEY
    if pool == "question":
        return QUESTION_LLM_SLOT_KEY
    raise ValueError(f"Unsupported LLM pool: {pool}")


def _pool_limit(pool: LLMPoolName) -> int:
    if pool == "vision":
        return max(0, int(settings.GLOBAL_VISION_LLM_CONCURRENCY or 0))
    if pool == "question":
        return max(0, int(settings.GLOBAL_QUESTION_LLM_CONCURRENCY or 0))
    raise ValueError(f"Unsupported LLM pool: {pool}")


async def _close_async_client(client: Any) -> None:
    close = getattr(client, "aclose", None) or getattr(client, "close", None)
    if close is None:
        return

    result = close()
    if inspect.isawaitable(result):
        await result


async def acquire_llm_slot(
    *,
    limit: Optional[int] = None,
    slot_key: str = GLOBAL_LLM_SLOT_KEY,
    timeout_seconds: Optional[float] = None,
    retry_interval_seconds: Optional[float] = None,
    ttl_seconds: Optional[int] = None,
    redis_url: Optional[str] = None,
) -> LLMSlot:
    slot_limit = max(0, int(settings.GLOBAL_LLM_CONCURRENCY if limit is None else limit))
    if slot_limit <= 0:
        return LLMSlot(token="", managed=False, key=slot_key)

    configured_timeout = settings.GLOBAL_LLM_ACQUIRE_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    configured_retry_interval = (
        settings.GLOBAL_LLM_RETRY_INTERVAL_SECONDS
        if retry_interval_seconds is None
        else retry_interval_seconds
    )
    configured_ttl = settings.GLOBAL_LLM_SLOT_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    timeout = max(0.0, float(configured_timeout))
    retry_interval = max(0.05, float(configured_retry_interval))
    ttl = max(30, int(configured_ttl))
    token = str(uuid.uuid4())
    client = _create_async_redis_client(redis_url or settings.REDIS_URL)
    deadline = asyncio.get_running_loop().time() + timeout

    try:
        while True:
            now = time.time()
            acquired = bool(
                int(
                    await client.eval(
                        _ACQUIRE_SLOT_SCRIPT,
                        1,
                        slot_key,
                        now,
                        slot_limit,
                        now + ttl,
                        token,
                        ttl,
                    )
                )
            )
            if acquired:
                return LLMSlot(token=token, managed=True, key=slot_key, client=client)

            if asyncio.get_running_loop().time() >= deadline:
                raise GlobalLLMConcurrencyTimeout(
                    f"Timed out waiting for LLM slot key={slot_key} limit={slot_limit}"
                )
            await asyncio.sleep(retry_interval)
    except Exception:
        await _close_async_client(client)
        raise


async def release_llm_slot(slot: LLMSlot) -> None:
    if not slot.managed or not slot.client:
        return

    try:
        await slot.client.zrem(slot.key, slot.token)
    except Exception as exc:
        logger.warning("Failed to release LLM slot key=%s: %s", slot.key, exc)
    finally:
        await _close_async_client(slot.client)


@asynccontextmanager
async def llm_request_slot(pool: Optional[LLMPoolName] = None) -> AsyncIterator[None]:
    slots: list[LLMSlot] = []
    try:
        if pool is not None:
            slots.append(
                await acquire_llm_slot(
                    limit=_pool_limit(pool),
                    slot_key=_pool_slot_key(pool),
                )
            )

        slots.append(await acquire_llm_slot(slot_key=GLOBAL_LLM_SLOT_KEY))
        yield
    except Exception:
        raise
    finally:
        for slot in reversed(slots):
            await release_llm_slot(slot)
