from app.services.concurrency import analysis_slots


class FakeRedis:
    def __init__(self, eval_result):
        self.eval_result = eval_result
        self.eval_calls = []
        self.zrem_calls = []
        self.closed = False

    def eval(self, *args):
        self.eval_calls.append(args)
        return self.eval_result

    def zrem(self, *args):
        self.zrem_calls.append(args)

    def close(self):
        self.closed = True


def test_try_acquire_analysis_slot_returns_slot_when_redis_allows(monkeypatch):
    fake = FakeRedis(eval_result=1)
    monkeypatch.setattr(analysis_slots, "_create_redis_client", lambda _url: fake)

    slot = analysis_slots.try_acquire_analysis_slot(
        paper_id="paper-1",
        task_id="task-1",
        limit=3,
        redis_url="redis://example/0",
    )

    assert slot is not None
    assert slot.managed is True
    assert slot.paper_id == "paper-1"
    assert "paper-1:task-1" == slot.token
    assert fake.eval_calls

    analysis_slots.release_analysis_slot(slot)

    assert fake.zrem_calls == [(analysis_slots.ANALYSIS_SLOT_KEY, "paper-1:task-1")]
    assert fake.closed is True


def test_try_acquire_analysis_slot_returns_none_when_limit_reached(monkeypatch):
    fake = FakeRedis(eval_result=0)
    monkeypatch.setattr(analysis_slots, "_create_redis_client", lambda _url: fake)

    slot = analysis_slots.try_acquire_analysis_slot(
        paper_id="paper-1",
        task_id="task-1",
        limit=3,
        redis_url="redis://example/0",
    )

    assert slot is None
    assert fake.closed is True


def test_try_acquire_analysis_slot_can_be_disabled():
    slot = analysis_slots.try_acquire_analysis_slot(paper_id="paper-1", limit=0)

    assert slot is not None
    assert slot.managed is False
