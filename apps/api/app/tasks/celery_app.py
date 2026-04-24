from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import TypedDict
from urllib.parse import urlsplit

from app.core.config import settings

PAPER_ANALYSIS_TASK_NAME = "paper_analysis.execute"
QUEUE_CHECK_TIMEOUT_SECONDS = 1.5

logger = logging.getLogger(__name__)


class QueuePreflightStatus(TypedDict):
    queue_ready: bool
    message: str
    broker_kind: str
    backend_kind: str
    broker_url: str
    backend_url: str


def _load_celery():
    try:
        from celery import Celery
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "未安装 Celery/Redis 运行依赖，请在 apps/api 环境安装 celery 和 redis。"
        ) from exc
    return Celery


def _load_redis():
    try:
        import redis
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "未安装 Redis 运行依赖，请在 apps/api 环境安装 redis。"
        ) from exc
    return redis


def _service_kind(url: str) -> str:
    scheme = urlsplit(url).scheme.lower()
    if "+" in scheme:
        scheme = scheme.split("+", 1)[1]
    return scheme or "unknown"


def _sanitize_service_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme:
        return url

    host = parsed.hostname or "unknown-host"
    netloc = host
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"

    path = parsed.path or ""
    if parsed.username:
        netloc = f"{parsed.username}:***@{netloc}"

    return f"{parsed.scheme}://{netloc}{path}"


def _describe_redis_connection_issue(exc: Exception) -> str:
    message = str(exc).strip()
    lowered = message.lower()

    if isinstance(exc, TimeoutError) or "timeout" in lowered or "timed out" in lowered:
        return "Redis 连接超时"
    if any(token in lowered for token in ("actively refused", "connection refused", "error 10061", "winerror 10061")):
        return "Redis 未启动或端口不可达"
    if any(token in lowered for token in ("connection closed", "connection lost", "connection reset", "broken pipe")):
        return "Redis 连接中断"

    return message or exc.__class__.__name__


def _ping_redis(url: str, *, label: str, timeout_seconds: float) -> tuple[bool, str]:
    redis = _load_redis()
    safe_url = _sanitize_service_url(url)
    client = redis.Redis.from_url(
        url,
        socket_connect_timeout=timeout_seconds,
        socket_timeout=timeout_seconds,
        health_check_interval=0,
    )

    try:
        client.ping()
    except redis.exceptions.AuthenticationError:
        return False, f"{label} Redis 认证失败（{safe_url}）"
    except redis.exceptions.TimeoutError as exc:
        return False, f"{label} {_describe_redis_connection_issue(exc)}（{safe_url}）"
    except redis.exceptions.ConnectionError as exc:
        return False, f"{label} {_describe_redis_connection_issue(exc)}（{safe_url}）"
    except OSError as exc:
        return False, f"{label} {_describe_redis_connection_issue(exc)}（{safe_url}）"

    return True, f"{label} 可用（{safe_url}）"


def get_queue_preflight_status(*, timeout_seconds: float = QUEUE_CHECK_TIMEOUT_SECONDS) -> QueuePreflightStatus:
    broker_url = settings.CELERY_BROKER_URL
    backend_url = settings.CELERY_RESULT_BACKEND
    broker_kind = _service_kind(broker_url)
    backend_kind = _service_kind(backend_url)
    broker_display = _sanitize_service_url(broker_url)
    backend_display = _sanitize_service_url(backend_url)

    if broker_kind != "redis":
        return {
            "queue_ready": False,
            "message": f"队列 broker 不是 Redis：{broker_display}",
            "broker_kind": broker_kind,
            "backend_kind": backend_kind,
            "broker_url": broker_display,
            "backend_url": backend_display,
        }

    if backend_kind != "redis":
        return {
            "queue_ready": False,
            "message": f"结果后端不是 Redis：{backend_display}",
            "broker_kind": broker_kind,
            "backend_kind": backend_kind,
            "broker_url": broker_display,
            "backend_url": backend_display,
        }

    checks: list[tuple[str, str]] = [("broker", broker_url)]
    if backend_url != broker_url:
        checks.append(("result backend", backend_url))

    for label, target_url in checks:
        try:
            ready, message = _ping_redis(
                target_url,
                label=label,
                timeout_seconds=timeout_seconds,
            )
        except RuntimeError as exc:
            message = str(exc)
            ready = False

        if not ready:
            logger.warning(
                "Queue preflight failed label=%s broker=%s backend=%s detail=%s",
                label,
                broker_display,
                backend_display,
                message,
            )
            return {
                "queue_ready": False,
                "message": message,
                "broker_kind": broker_kind,
                "backend_kind": backend_kind,
                "broker_url": broker_display,
                "backend_url": backend_display,
            }

    return {
        "queue_ready": True,
        "message": f"队列可用（broker={broker_display}，backend={backend_display}）",
        "broker_kind": broker_kind,
        "backend_kind": backend_kind,
        "broker_url": broker_display,
        "backend_url": backend_display,
    }


def describe_queue_dispatch_error(exc: Exception) -> str:
    exc_type = exc.__class__.__name__
    lowered = str(exc).lower()
    broker_display = _sanitize_service_url(settings.CELERY_BROKER_URL)

    if any(token in lowered for token in ("actively refused", "connection refused", "error 10061", "winerror 10061")):
        return f"Redis 未启动或端口不可达（{broker_display}）"
    if "timeout" in lowered or "timed out" in lowered:
        return f"Redis 连接超时（{broker_display}）"
    if any(token in lowered for token in ("connection closed", "connection lost", "connection reset", "broken pipe")):
        return f"Redis 连接中断（{broker_display}）"

    exc_text = str(exc).strip() or exc_type
    return f"{exc_type}：{exc_text}"


@lru_cache()
def get_celery_app():
    Celery = _load_celery()
    celery_app = Celery(
        "math_report",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
        include=["app.tasks.paper_analysis"],
    )
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="Asia/Shanghai",
        enable_utc=False,
        task_track_started=True,
        worker_prefetch_multiplier=1,
        task_acks_late=False,
        broker_connection_retry_on_startup=True,
        task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
        task_eager_propagates=True,
    )

    if os.name == "nt":
        celery_app.conf.worker_pool = "solo"
        celery_app.conf.worker_concurrency = 1

    return celery_app


def enqueue_paper_analysis_task(*, paper_id: str, file_path: str) -> str:
    celery_app = get_celery_app()

    if settings.CELERY_TASK_ALWAYS_EAGER:
        from app.tasks.paper_analysis import paper_analysis_task

        result = paper_analysis_task.delay(paper_id=paper_id, file_path=file_path)
    else:
        result = celery_app.send_task(
            PAPER_ANALYSIS_TASK_NAME,
            kwargs={"paper_id": paper_id, "file_path": file_path},
        )

    return str(result.id)
