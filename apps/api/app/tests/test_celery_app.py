import importlib

from app.tasks.celery_app import PAPER_ANALYSIS_TASK_NAME, app, celery, get_celery_app
from app.tasks.paper_analysis import paper_analysis_task


def test_celery_module_exposes_standard_singleton_names():
    module = importlib.import_module("app.tasks.celery_app")

    assert hasattr(module, "celery")
    assert hasattr(module, "app")
    assert hasattr(module, "get_celery_app")
    assert module.celery is celery
    assert module.app is app


def test_celery_singleton_matches_factory():
    assert celery is app
    assert celery is get_celery_app()
    assert celery.main == "math_report"


def test_paper_analysis_task_is_bound_to_shared_celery_app():
    assert paper_analysis_task.app is celery
    assert paper_analysis_task.name == PAPER_ANALYSIS_TASK_NAME


def test_queue_preflight_skips_redis_when_task_always_eager(monkeypatch):
    module = importlib.import_module("app.tasks.celery_app")

    def fail_if_pinged(*args, **kwargs):
        raise AssertionError("Redis should not be pinged in eager mode")

    monkeypatch.setattr(module.settings, "CELERY_TASK_ALWAYS_EAGER", True)
    monkeypatch.setattr(module, "_ping_redis", fail_if_pinged)

    status = module.get_queue_preflight_status()

    assert status["queue_ready"] is True
    assert "queue preflight skipped" in status["message"]


def test_enqueue_uses_local_thread_when_task_always_eager(monkeypatch):
    module = importlib.import_module("app.tasks.celery_app")
    created_thread = {}

    class FakeThread:
        def __init__(self, *, target, kwargs, name, daemon):
            created_thread.update(
                {
                    "target": target,
                    "kwargs": kwargs,
                    "name": name,
                    "daemon": daemon,
                    "started": False,
                }
            )

        def start(self):
            created_thread["started"] = True

    def fail_if_celery_loaded():
        raise AssertionError("Celery should not be loaded in eager local mode")

    monkeypatch.setattr(module.settings, "CELERY_TASK_ALWAYS_EAGER", True)
    monkeypatch.setattr(module, "get_celery_app", fail_if_celery_loaded)
    monkeypatch.setattr(module.threading, "Thread", FakeThread)
    monkeypatch.setattr(module.uuid, "uuid4", lambda: "fixed-id")

    task_id = module.enqueue_paper_analysis_task(paper_id="paper-1", file_path="paper.pdf")

    assert task_id == "local-eager-fixed-id"
    assert created_thread["target"] is module._run_local_eager_paper_analysis
    assert created_thread["kwargs"] == {
        "paper_id": "paper-1",
        "file_path": "paper.pdf",
        "task_id": "local-eager-fixed-id",
    }
    assert created_thread["name"] == "paper-analysis-paper-1"
    assert created_thread["daemon"] is True
    assert created_thread["started"] is True


def test_enqueue_uses_celery_send_task_when_not_eager(monkeypatch):
    module = importlib.import_module("app.tasks.celery_app")
    sent = {}

    class FakeResult:
        id = "celery-task-1"

    class FakeCelery:
        def send_task(self, name, kwargs):
            sent["name"] = name
            sent["kwargs"] = kwargs
            return FakeResult()

    monkeypatch.setattr(module.settings, "CELERY_TASK_ALWAYS_EAGER", False)
    monkeypatch.setattr(module, "get_celery_app", lambda: FakeCelery())

    task_id = module.enqueue_paper_analysis_task(paper_id="paper-1", file_path="paper.pdf")

    assert task_id == "celery-task-1"
    assert sent == {
        "name": module.PAPER_ANALYSIS_TASK_NAME,
        "kwargs": {"paper_id": "paper-1", "file_path": "paper.pdf"},
    }
