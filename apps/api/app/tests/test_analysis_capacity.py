from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import papers


@pytest.mark.asyncio
async def test_enforce_analysis_queue_capacity_allows_when_below_limit(monkeypatch):
    monkeypatch.setattr(papers.settings, "MAX_QUEUED_ANALYSIS_TASKS", 3)

    async def fake_queued_count(_db):
        return 2

    monkeypatch.setattr(papers, "_queued_analysis_task_count", fake_queued_count)

    await papers._enforce_analysis_queue_capacity(object())


@pytest.mark.asyncio
async def test_enforce_analysis_queue_capacity_rejects_when_limit_reached(monkeypatch):
    monkeypatch.setattr(papers.settings, "MAX_QUEUED_ANALYSIS_TASKS", 3)

    async def fake_queued_count(_db):
        return 3

    monkeypatch.setattr(papers, "_queued_analysis_task_count", fake_queued_count)

    with pytest.raises(HTTPException) as exc_info:
        await papers._enforce_analysis_queue_capacity(object())

    assert exc_info.value.status_code == 429
    assert "3/3" in exc_info.value.detail


@pytest.mark.asyncio
async def test_enforce_analysis_queue_capacity_disabled_with_non_positive_limit(monkeypatch):
    monkeypatch.setattr(papers.settings, "MAX_QUEUED_ANALYSIS_TASKS", 0)

    async def fail_if_called(_db):
        raise AssertionError("capacity check should be skipped")

    monkeypatch.setattr(papers, "_queued_analysis_task_count", fail_if_called)

    await papers._enforce_analysis_queue_capacity(object())


@pytest.mark.asyncio
async def test_running_limit_does_not_reject_upload_when_queue_has_room(monkeypatch):
    monkeypatch.setattr(papers.settings, "MAX_RUNNING_ANALYSIS_TASKS", 3)
    monkeypatch.setattr(papers.settings, "MAX_QUEUED_ANALYSIS_TASKS", 10)

    async def fake_queued_count(_db):
        return 3

    monkeypatch.setattr(papers, "_queued_analysis_task_count", fake_queued_count)

    await papers._enforce_analysis_queue_capacity(object())


@pytest.mark.asyncio
async def test_waiting_status_poll_triggers_slot_cleanup(monkeypatch):
    calls = []

    async def fake_mark_stale(stale_minutes):
        calls.append(stale_minutes)

    monkeypatch.setattr(papers.settings, "TASK_STALE_MINUTES", 60)
    monkeypatch.setattr(papers, "mark_stale_analysis_tasks", fake_mark_stale)

    await papers._cleanup_analysis_slots_for_waiting_status(
        SimpleNamespace(
            paper_id="paper-1",
            parse_status=papers.ModelParseStatus.PENDING,
            last_stage="queued_waiting_for_analysis_slot",
        )
    )

    assert calls == [60]


@pytest.mark.asyncio
async def test_non_waiting_status_poll_skips_slot_cleanup(monkeypatch):
    async def fail_if_called(_stale_minutes):
        raise AssertionError("cleanup should not run")

    monkeypatch.setattr(papers, "mark_stale_analysis_tasks", fail_if_called)

    await papers._cleanup_analysis_slots_for_waiting_status(
        SimpleNamespace(
            paper_id="paper-1",
            parse_status=papers.ModelParseStatus.PENDING,
            last_stage="queued",
        )
    )
