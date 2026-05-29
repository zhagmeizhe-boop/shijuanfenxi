from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.api.v1.endpoints.admin as admin_module
from app.api.v1.endpoints.admin import (
    ADMIN_CANCELLED_MESSAGE,
    ADMIN_CANCELLED_STAGE,
    _require_admin_token,
    classify_failure,
    stage_display,
)
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models import ParseStatus


client = TestClient(app)


class _SummaryResult:
    def __init__(self, rows=None):
        self._rows = rows or [
            (ParseStatus.PENDING.value, 1),
            (ParseStatus.PARSING.value, 1),
            (ParseStatus.PARSE_SUCCESS.value, 2),
            (ParseStatus.PARSE_FAILED.value, 1),
        ]

    def all(self):
        return self._rows


class _CountResult:
    def scalar_one(self):
        return 1


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ListResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _FakeDb:
    def __init__(self, rows, summary_rows=None):
        self._results = [_SummaryResult(summary_rows), _CountResult(), _ListResult(rows)]

    async def execute(self, _statement):
        return self._results.pop(0)


class _CancelDb:
    def __init__(self, paper):
        self.paper = paper
        self.commits = 0

    async def get(self, _model, paper_id):
        if paper_id == self.paper.paper_id:
            return self.paper
        return None

    async def commit(self):
        self.commits += 1

    async def refresh(self, _paper):
        return None


def test_admin_token_required(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret")

    with pytest.raises(HTTPException) as exc_info:
        _require_admin_token(None)

    assert exc_info.value.status_code == 401


def test_admin_token_wrong(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret")

    with pytest.raises(HTTPException) as exc_info:
        _require_admin_token("wrong")

    assert exc_info.value.status_code == 403


def test_admin_token_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "")

    with pytest.raises(HTTPException) as exc_info:
        _require_admin_token("secret")

    assert exc_info.value.status_code == 503


def test_classify_known_failure_solutions():
    network = classify_failure("ocr_parse", "All connection attempts failed")
    assert network.reason == "LLM 网关网络不可达"
    assert "白名单" in network.solution

    permission = classify_failure("ocr_parse", "PermissionError: [Errno 13] Permission denied: '/app/uploads/x'")
    assert permission.reason == "服务器上传/报告目录没有写入权限"
    assert "chown" in permission.solution

    llm = classify_failure("llm_parse", "LLM 阶段全部失败")
    assert llm.reason == "题目 LLM 分析失败"
    assert "降低题目分析并发" in llm.solution


def test_classify_unknown_failure_solution():
    guide = classify_failure("unknown_stage", "something unexpected")

    assert guide.reason == "未知异常"
    assert "paper_id" in guide.solution


def test_classify_admin_cancelled_failure_solution():
    guide = classify_failure(ADMIN_CANCELLED_STAGE, ADMIN_CANCELLED_MESSAGE)

    assert guide.reason == ADMIN_CANCELLED_MESSAGE
    assert "重新上传" in guide.solution


def test_waiting_for_analysis_slot_stage_display():
    assert stage_display("queued_waiting_for_analysis_slot", ParseStatus.PENDING) == "已有试卷在分析，正在排队等待"
    assert stage_display("queued", ParseStatus.PENDING, has_active_analysis=True) == "已有试卷在分析，正在排队等待"
    assert stage_display("queued", ParseStatus.PENDING, has_active_analysis=False) == "已进入队列，等待 worker 接手"


def test_admin_papers_endpoint_returns_failed_items(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret")
    now = datetime(2026, 5, 28, 10, 0, 0)
    row = SimpleNamespace(
        paper_id="paper-1",
        paper_name="三年级期中试卷.pdf",
        parse_status=ParseStatus.PARSE_FAILED,
        last_stage="ocr_parse",
        error_message="All connection attempts failed",
        total_question_count=0,
        created_at=now,
        updated_at=now,
    )

    async def override_db():
        return _FakeDb([row])

    app.dependency_overrides[get_db] = override_db
    try:
        response = client.get("/api/v1/admin/papers", headers={"X-Admin-Token": "secret"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == {"total": 5, "parsing": 2, "success": 2, "failed": 1}
    assert data["total"] == 1
    assert data["items"][0]["paper_id"] == "paper-1"
    assert data["items"][0]["stage_display"] == "OCR/试卷题目提取"
    assert data["items"][0]["failure_reason_display"] == "LLM 网关网络不可达"
    assert "白名单" in data["items"][0]["failure_solution_display"]


def test_admin_papers_endpoint_shows_queued_waiting_when_active_analysis_exists(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret")
    now = datetime(2026, 5, 28, 10, 0, 0)
    row = SimpleNamespace(
        paper_id="paper-queued",
        paper_name="排队试卷.pdf",
        parse_status=ParseStatus.PENDING,
        last_stage="queued",
        error_message=None,
        cancel_requested=False,
        cancel_requested_at=None,
        total_question_count=0,
        created_at=now,
        updated_at=now,
    )

    async def override_db():
        return _FakeDb([row], summary_rows=[(ParseStatus.PENDING.value, 1), (ParseStatus.PARSING.value, 1)])

    app.dependency_overrides[get_db] = override_db
    try:
        response = client.get("/api/v1/admin/papers?status=parsing", headers={"X-Admin-Token": "secret"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    data = response.json()
    assert data["items"][0]["stage_display"] == "已有试卷在分析，正在排队等待"


def test_admin_papers_endpoint_shows_waiting_for_worker_when_no_active_analysis(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret")
    now = datetime(2026, 5, 28, 10, 0, 0)
    row = SimpleNamespace(
        paper_id="paper-queued",
        paper_name="排队试卷.pdf",
        parse_status=ParseStatus.PENDING,
        last_stage="queued",
        error_message=None,
        cancel_requested=False,
        cancel_requested_at=None,
        total_question_count=0,
        created_at=now,
        updated_at=now,
    )

    async def override_db():
        return _FakeDb([row], summary_rows=[(ParseStatus.PENDING.value, 1)])

    app.dependency_overrides[get_db] = override_db
    try:
        response = client.get("/api/v1/admin/papers?status=parsing", headers={"X-Admin-Token": "secret"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    data = response.json()
    assert data["items"][0]["stage_display"] == "已进入队列，等待 worker 接手"


def test_cancel_pending_paper_marks_failed_and_revokes(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret")
    revoked = {}

    class FakeControl:
        def revoke(self, task_id, terminate=False):
            revoked["task_id"] = task_id
            revoked["terminate"] = terminate

    class FakeCelery:
        control = FakeControl()

    monkeypatch.setattr(admin_module, "get_celery_app", lambda: FakeCelery())

    paper = SimpleNamespace(
        paper_id="paper-pending",
        parse_status=ParseStatus.PENDING,
        last_stage="queued",
        error_message=None,
        analysis_task_id="task-1",
        cancel_requested=False,
        cancel_requested_at=None,
        progress_current=1,
        progress_total=2,
        progress_message="queued",
    )
    fake_db = _CancelDb(paper)

    async def override_db():
        return fake_db

    app.dependency_overrides[get_db] = override_db
    try:
        response = client.post("/api/v1/admin/papers/paper-pending/cancel", headers={"X-Admin-Token": "secret"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json()["parse_status"] == "parse_failed"
    assert paper.parse_status == ParseStatus.PARSE_FAILED
    assert paper.last_stage == ADMIN_CANCELLED_STAGE
    assert paper.error_message == ADMIN_CANCELLED_MESSAGE
    assert paper.progress_current is None
    assert paper.progress_total is None
    assert paper.progress_message is None
    assert paper.cancel_requested is True
    assert paper.cancel_requested_at is not None
    assert revoked == {"task_id": "task-1", "terminate": False}
    assert fake_db.commits == 1


def test_cancel_endpoint_requires_admin_token(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret")

    response = client.post("/api/v1/admin/papers/paper-1/cancel")

    assert response.status_code == 401


def test_cancel_endpoint_rejects_wrong_admin_token(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret")

    response = client.post("/api/v1/admin/papers/paper-1/cancel", headers={"X-Admin-Token": "wrong"})

    assert response.status_code == 403


def test_cancel_parsing_paper_requests_safe_stop(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret")
    monkeypatch.setattr(admin_module, "get_celery_app", lambda: SimpleNamespace(control=SimpleNamespace(revoke=lambda *_args, **_kwargs: None)))

    paper = SimpleNamespace(
        paper_id="paper-parsing",
        parse_status=ParseStatus.PARSING,
        last_stage="ocr_parse",
        error_message=None,
        analysis_task_id="task-2",
        cancel_requested=False,
        cancel_requested_at=None,
        progress_current=1,
        progress_total=4,
        progress_message="running",
    )
    fake_db = _CancelDb(paper)

    async def override_db():
        return fake_db

    app.dependency_overrides[get_db] = override_db
    try:
        response = client.post("/api/v1/admin/papers/paper-parsing/cancel", headers={"X-Admin-Token": "secret"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json()["parse_status"] == "parsing"
    assert paper.parse_status == ParseStatus.PARSING
    assert paper.cancel_requested is True
    assert paper.cancel_requested_at is not None
    assert "等待当前阶段安全退出" in paper.progress_message


def test_cancel_finished_paper_returns_conflict(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret")
    paper = SimpleNamespace(
        paper_id="paper-success",
        parse_status=ParseStatus.PARSE_SUCCESS,
    )

    async def override_db():
        return _CancelDb(paper)

    app.dependency_overrides[get_db] = override_db
    try:
        response = client.post("/api/v1/admin/papers/paper-success/cancel", headers={"X-Admin-Token": "secret"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 409
