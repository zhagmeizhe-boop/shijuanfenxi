from __future__ import annotations

import logging

from app.core.config import settings
from app.services.concurrency.analysis_slots import (
    AnalysisSlotBackendError,
    release_analysis_slot,
    try_acquire_analysis_slot,
)
from app.services.paper_analysis_runner import (
    mark_paper_waiting_for_analysis_slot_sync,
    run_paper_analysis_sync,
)
from app.tasks.celery_app import PAPER_ANALYSIS_TASK_NAME, celery

logger = logging.getLogger(__name__)


def _safe_mark_waiting_for_slot(paper_id: str) -> None:
    try:
        mark_paper_waiting_for_analysis_slot_sync(paper_id)
    except Exception:
        logger.warning("Failed to mark paper waiting for analysis slot paper=%s", paper_id, exc_info=True)


@celery.task(name=PAPER_ANALYSIS_TASK_NAME, bind=True, max_retries=None)
def paper_analysis_task(self, paper_id: str, file_path: str) -> None:
    slot = None
    try:
        slot = try_acquire_analysis_slot(
            paper_id=paper_id,
            task_id=getattr(getattr(self, "request", None), "id", None),
        )
    except AnalysisSlotBackendError as exc:
        logger.warning("Analysis slot backend unavailable paper=%s: %s", paper_id, exc)
        raise self.retry(exc=exc, countdown=max(1, int(settings.ANALYSIS_SLOT_RETRY_SECONDS or 30)))

    if slot is None:
        _safe_mark_waiting_for_slot(paper_id)
        raise self.retry(
            exc=RuntimeError("analysis running slot unavailable"),
            countdown=max(1, int(settings.ANALYSIS_SLOT_RETRY_SECONDS or 30)),
        )

    try:
        run_paper_analysis_sync(paper_id=paper_id, file_path=file_path)
    finally:
        release_analysis_slot(slot)
