from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

ANALYSIS_SLOT_KEY = "math-analysis:analysis:running-slots"

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


class AnalysisSlotBackendError(RuntimeError):
    """Raised when Redis cannot be used for analysis slot coordination."""


@dataclass(frozen=True)
class AnalysisSlot:
    token: str
    paper_id: str
    managed: bool
    client: Optional[Any] = None


def get_analysis_running_limit() -> int:
    configured = settings.MAX_RUNNING_ANALYSIS_TASKS
    if configured is None:
        configured = settings.MAX_ACTIVE_ANALYSIS_TASKS
    return max(0, int(configured or 0))


def _load_redis():
    try:
        import redis
    except ModuleNotFoundError as exc:
        raise AnalysisSlotBackendError("Redis dependency is not installed") from exc
    return redis


def _create_redis_client(redis_url: str):
    redis = _load_redis()
    return redis.Redis.from_url(
        redis_url,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
        health_check_interval=0,
        decode_responses=True,
    )


def try_acquire_analysis_slot(
    *,
    paper_id: str,
    task_id: Optional[str] = None,
    limit: Optional[int] = None,
    ttl_seconds: Optional[int] = None,
    redis_url: Optional[str] = None,
) -> Optional[AnalysisSlot]:
    slot_limit = get_analysis_running_limit() if limit is None else max(0, int(limit))
    if slot_limit <= 0:
        return AnalysisSlot(token="", paper_id=paper_id, managed=False)

    configured_ttl = settings.ANALYSIS_SLOT_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    ttl = max(60, int(configured_ttl))
    token = f"{paper_id}:{task_id or uuid.uuid4()}"
    now = time.time()
    expires_at = now + ttl
    client = _create_redis_client(redis_url or settings.REDIS_URL)

    try:
        acquired = bool(
            int(
                client.eval(
                    _ACQUIRE_SLOT_SCRIPT,
                    1,
                    ANALYSIS_SLOT_KEY,
                    now,
                    slot_limit,
                    expires_at,
                    token,
                    ttl,
                )
            )
        )
    except Exception as exc:
        try:
            client.close()
        finally:
            raise AnalysisSlotBackendError(f"Failed to acquire analysis slot: {exc}") from exc

    if not acquired:
        client.close()
        logger.info(
            "Analysis running slot unavailable paper=%s limit=%s retry_later=true",
            paper_id,
            slot_limit,
        )
        return None

    logger.info("Analysis running slot acquired paper=%s limit=%s", paper_id, slot_limit)
    return AnalysisSlot(token=token, paper_id=paper_id, managed=True, client=client)


def release_analysis_slot(slot: Optional[AnalysisSlot]) -> None:
    if not slot or not slot.managed or not slot.client:
        return

    try:
        slot.client.zrem(ANALYSIS_SLOT_KEY, slot.token)
        logger.info("Analysis running slot released paper=%s", slot.paper_id)
    except Exception as exc:
        logger.warning("Failed to release analysis slot paper=%s: %s", slot.paper_id, exc)
    finally:
        slot.client.close()
