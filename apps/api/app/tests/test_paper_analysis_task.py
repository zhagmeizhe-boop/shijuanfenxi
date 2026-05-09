import pytest

import app.services.paper_analysis_runner as paper_analysis_runner
from app.models import Question
from app.tasks import paper_analysis as task_module


def test_paper_analysis_task_runs_when_slot_is_acquired(monkeypatch):
    slot = object()
    calls = []

    monkeypatch.setattr(task_module, "try_acquire_analysis_slot", lambda **_kwargs: slot)
    monkeypatch.setattr(
        task_module,
        "run_paper_analysis_sync",
        lambda **kwargs: calls.append(("run", kwargs)),
    )
    monkeypatch.setattr(
        task_module,
        "release_analysis_slot",
        lambda acquired_slot: calls.append(("release", acquired_slot)),
    )

    task_module.paper_analysis_task.run("paper-1", "paper.pdf")

    assert calls == [
        ("run", {"paper_id": "paper-1", "file_path": "paper.pdf"}),
        ("release", slot),
    ]


def test_paper_analysis_task_retries_when_slot_unavailable(monkeypatch):
    class RetryRaised(Exception):
        pass

    captured = {}

    def fake_retry(*, exc, countdown):
        captured["exc"] = exc
        captured["countdown"] = countdown
        raise RetryRaised

    monkeypatch.setattr(task_module, "try_acquire_analysis_slot", lambda **_kwargs: None)
    monkeypatch.setattr(
        task_module,
        "_safe_mark_waiting_for_slot",
        lambda paper_id: captured.setdefault("marked_paper_id", paper_id),
    )
    monkeypatch.setattr(task_module.settings, "ANALYSIS_SLOT_RETRY_SECONDS", 7)
    monkeypatch.setattr(task_module.paper_analysis_task, "retry", fake_retry)

    with pytest.raises(RetryRaised):
        task_module.paper_analysis_task.run("paper-1", "paper.pdf")

    assert captured["marked_paper_id"] == "paper-1"
    assert captured["countdown"] == 7
    assert "analysis running slot unavailable" in str(captured["exc"])


def test_question_section_index_column_allows_long_headings():
    assert Question.__table__.c.section_index_raw.type.length == 100


def test_question_persist_truncation_error_is_user_friendly():
    message = paper_analysis_runner._describe_exception(
        "question_persist",
        Exception("value too long for type character varying(20) [SQL: INSERT INTO question ...]"),
    )

    assert "题目信息保存失败" in message
    assert "SQL" not in message
    assert "character varying" not in message
