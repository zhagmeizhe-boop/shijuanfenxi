from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.main import app


client = TestClient(app)


def test_settings_defaults_use_single_task_fast_profile():
    defaults = Settings.model_fields

    assert defaults["MAX_RUNNING_ANALYSIS_TASKS"].default == 1
    assert defaults["MAX_ACTIVE_ANALYSIS_TASKS"].default == 1
    assert defaults["MAX_QUEUED_ANALYSIS_TASKS"].default == 3
    assert defaults["VISION_LLM_CONCURRENCY"].default == 4
    assert defaults["QUESTION_LLM_CONCURRENCY"].default == 10
    assert defaults["GLOBAL_LLM_CONCURRENCY"].default == 14
    assert defaults["GLOBAL_VISION_LLM_CONCURRENCY"].default == 4
    assert defaults["GLOBAL_QUESTION_LLM_CONCURRENCY"].default == 10
    assert defaults["VISION_LLM_PAGE_TIMEOUT"].default == 150.0
    assert defaults["VISION_LLM_MAX_ATTEMPTS"].default == 3
    assert defaults["QUESTION_LLM_TIMEOUT_SECONDS"].default == 180.0
    assert defaults["QUESTION_LLM_REQUEST_TIMEOUT_SECONDS"].default == 90.0
    assert defaults["QUESTION_LLM_MAX_ATTEMPTS"].default == 2


def test_health_exposes_llm_pool_and_capacity_config():
    with (
        patch(
            "app.main.get_database_preflight_status",
            new=AsyncMock(
                return_value={
                    "database_ready": True,
                    "database_kind": "postgresql",
                    "message": "ready",
                }
            ),
        ),
        patch(
            "app.main.get_queue_preflight_status",
            return_value={
                "queue_ready": True,
                "message": "ready",
            },
        ),
        patch(
            "app.main.get_ocr_preflight_status",
            new=AsyncMock(
                return_value={
                    "ocr_ready": True,
                    "provider": "vision_llm",
                    "message": "ready",
                }
            ),
        ),
    ):
        response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app_workers"] == settings.APP_WORKERS
    assert data["db_pool_size"] == settings.DB_POOL_SIZE
    assert data["db_max_overflow"] == settings.DB_MAX_OVERFLOW
    assert data["analysis_running_limit"] == settings.MAX_RUNNING_ANALYSIS_TASKS
    assert data["analysis_queue_limit"] == settings.MAX_QUEUED_ANALYSIS_TASKS
    assert data["vision_llm_concurrency"] == settings.VISION_LLM_CONCURRENCY
    assert data["vision_llm_page_timeout"] == settings.VISION_LLM_PAGE_TIMEOUT
    assert data["vision_llm_max_attempts"] == settings.VISION_LLM_MAX_ATTEMPTS
    assert data["question_llm_concurrency"] == settings.QUESTION_LLM_CONCURRENCY
    assert data["question_llm_timeout_seconds"] == settings.QUESTION_LLM_TIMEOUT_SECONDS
    assert data["question_llm_request_timeout_seconds"] == settings.QUESTION_LLM_REQUEST_TIMEOUT_SECONDS
    assert data["question_llm_max_attempts"] == settings.QUESTION_LLM_MAX_ATTEMPTS
    assert data["global_llm_concurrency"] == settings.GLOBAL_LLM_CONCURRENCY
    assert data["global_vision_llm_concurrency"] == settings.GLOBAL_VISION_LLM_CONCURRENCY
    assert data["global_question_llm_concurrency"] == settings.GLOBAL_QUESTION_LLM_CONCURRENCY
