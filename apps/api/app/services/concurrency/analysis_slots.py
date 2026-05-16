from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Optional

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


@dataclass(frozen=True)
class AnalysisSlotSnapshot:
    token: str
    paper_id: str
    expires_at: float


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


def _slot_ttl_seconds(ttl_seconds: Optional[int] = None) -> int:
    configured_ttl = settings.ANALYSIS_SLOT_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    return max(60, int(configured_ttl))


def _slot_token_paper_id(token: str) -> str:
    return str(token or "").split(":", 1)[0]


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

    ttl = _slot_ttl_seconds(ttl_seconds)
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


def list_analysis_slots(*, redis_url: Optional[str] = None) -> list[AnalysisSlotSnapshot]:
    client = _create_redis_client(redis_url or settings.REDIS_URL)
    try:
        raw_slots = client.zrange(ANALYSIS_SLOT_KEY, 0, -1, withscores=True)
    except Exception as exc:
        raise AnalysisSlotBackendError(f"Failed to list analysis slots: {exc}") from exc
    finally:
        client.close()

    slots: list[AnalysisSlotSnapshot] = []
    for raw_token, raw_score in raw_slots or []:
        token = str(raw_token or "")
        if not token:
            continue
        try:
            expires_at = float(raw_score)
        except (TypeError, ValueError):
            expires_at = 0.0
        slots.append(
            AnalysisSlotSnapshot(
                token=token,
                paper_id=_slot_token_paper_id(token),
                expires_at=expires_at,
            )
        )
    return slots


def release_analysis_slot_token(token: str, *, redis_url: Optional[str] = None) -> int:
    normalized_token = str(token or "").strip()
    if not normalized_token:
        return 0

    client = _create_redis_client(redis_url or settings.REDIS_URL)
    try:
        removed = int(client.zrem(ANALYSIS_SLOT_KEY, normalized_token) or 0)
        if removed:
            logger.info("Analysis running slot token released token=%s", normalized_token)
        return removed
    except Exception as exc:
        raise AnalysisSlotBackendError(f"Failed to release analysis slot token: {exc}") from exc
    finally:
        client.close()


def refresh_analysis_slot(slot: Optional[AnalysisSlot], *, ttl_seconds: Optional[int] = None) -> bool:
    if not slot or not slot.managed or not slot.client or not slot.token:
        return False

    ttl = _slot_ttl_seconds(ttl_seconds)
    expires_at = time.time() + ttl
    try:
        existing_score = slot.client.zscore(ANALYSIS_SLOT_KEY, slot.token)
        if existing_score is None:
            logger.warning("Analysis running slot disappeared before refresh paper=%s", slot.paper_id)
            return False
        slot.client.zadd(ANALYSIS_SLOT_KEY, {slot.token: expires_at}, xx=True)
        slot.client.expire(ANALYSIS_SLOT_KEY, ttl)
    except Exception as exc:
        logger.warning("Failed to refresh analysis slot paper=%s: %s", slot.paper_id, exc)
        return False

    logger.debug("Analysis running slot refreshed paper=%s ttl=%s", slot.paper_id, ttl)
    return True


def cleanup_stale_analysis_slots(
    active_paper_ids: Iterable[str],
    *,
    redis_url: Optional[str] = None,
) -> int:
    active_ids = {str(paper_id).strip() for paper_id in active_paper_ids if str(paper_id).strip()}
    now = time.time()
    removed_count = 0

    for slot in list_analysis_slots(redis_url=redis_url):
        should_remove = slot.expires_at <= now or not slot.paper_id or slot.paper_id not in active_ids
        if not should_remove:
            continue
        try:
            removed_count += release_analysis_slot_token(slot.token, redis_url=redis_url)
        except AnalysisSlotBackendError:
            logger.warning("Failed to cleanup stale analysis slot token=%s", slot.token, exc_info=True)

    if removed_count:
        logger.warning("Cleaned up %s stale analysis running slots", removed_count)
    return removed_count


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
