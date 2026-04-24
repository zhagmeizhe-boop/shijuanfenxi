from __future__ import annotations

from app.services.paper_analysis_runner import run_paper_analysis_sync
from app.tasks.celery_app import PAPER_ANALYSIS_TASK_NAME, get_celery_app

celery_app = get_celery_app()


@celery_app.task(name=PAPER_ANALYSIS_TASK_NAME)
def paper_analysis_task(paper_id: str, file_path: str) -> None:
    run_paper_analysis_sync(paper_id=paper_id, file_path=file_path)
