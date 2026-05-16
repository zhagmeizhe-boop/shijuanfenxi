import asyncio
from types import SimpleNamespace

import pytest

import app.services.paper_analysis_runner as paper_analysis_runner
from app.models import ParseStatus, Question
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


def test_paper_analysis_task_starts_and_stops_heartbeat(monkeypatch):
    slot = object()
    calls = []

    class FakeHeartbeat:
        def __init__(self, acquired_slot):
            calls.append(("heartbeat_init", acquired_slot))

        def start(self):
            calls.append(("heartbeat_start", None))

        def stop(self):
            calls.append(("heartbeat_stop", None))

    monkeypatch.setattr(task_module, "try_acquire_analysis_slot", lambda **_kwargs: slot)
    monkeypatch.setattr(task_module, "AnalysisSlotHeartbeat", FakeHeartbeat)
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
        ("heartbeat_init", slot),
        ("heartbeat_start", None),
        ("run", {"paper_id": "paper-1", "file_path": "paper.pdf"}),
        ("heartbeat_stop", None),
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


def test_mark_stale_analysis_tasks_marks_stale_and_cleans_slots(monkeypatch):
    stale_paper = SimpleNamespace(
        paper_id="stale-paper",
        parse_status=ParseStatus.PARSING,
        last_stage=None,
        error_message=None,
    )
    captured = {}

    class FakeResult:
        def __init__(self, *, scalars=None, rows=None):
            self._scalars = scalars or []
            self._rows = rows or []

        def scalars(self):
            return self

        def all(self):
            return self._scalars or self._rows

    class FakeSession:
        def __init__(self):
            self.results = [
                FakeResult(scalars=[stale_paper]),
                FakeResult(rows=[("active-paper",)]),
            ]
            self.commits = 0

        async def __aenter__(self):
            captured["session"] = self
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, _query):
            return self.results.pop(0)

        async def commit(self):
            self.commits += 1

    monkeypatch.setattr(paper_analysis_runner, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(
        paper_analysis_runner,
        "cleanup_stale_analysis_slots",
        lambda active_ids: captured.setdefault("active_ids", list(active_ids)),
    )

    stale_count = asyncio.run(paper_analysis_runner.mark_stale_analysis_tasks(60))

    assert stale_count == 1
    assert stale_paper.parse_status == ParseStatus.PARSE_FAILED
    assert stale_paper.last_stage == "parsing"
    assert stale_paper.error_message
    assert captured["session"].commits == 1
    assert captured["active_ids"] == ["active-paper"]


def test_question_persist_truncation_error_is_user_friendly():
    message = paper_analysis_runner._describe_exception(
        "question_persist",
        Exception("value too long for type character varying(20) [SQL: INSERT INTO question ...]"),
    )

    assert "题目信息保存失败" in message
    assert "SQL" not in message
    assert "character varying" not in message
