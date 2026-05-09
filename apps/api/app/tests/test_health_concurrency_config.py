from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


client = TestClient(app)


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
    assert data["vision_llm_concurrency"] == settings.VISION_LLM_CONCURRENCY
    assert data["question_llm_concurrency"] == settings.QUESTION_LLM_CONCURRENCY
    assert data["global_llm_concurrency"] == settings.GLOBAL_LLM_CONCURRENCY
    assert data["global_vision_llm_concurrency"] == settings.GLOBAL_VISION_LLM_CONCURRENCY
    assert data["global_question_llm_concurrency"] == settings.GLOBAL_QUESTION_LLM_CONCURRENCY
