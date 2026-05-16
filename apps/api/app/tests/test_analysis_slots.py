from app.services.concurrency import analysis_slots


class FakeRedis:
    def __init__(self, eval_result=1, slots=None):
        self.eval_result = eval_result
        self.slots = dict(slots or {})
        self.eval_calls = []
        self.zadd_calls = []
        self.zrem_calls = []
        self.expire_calls = []
        self.closed = False

    def eval(self, *args):
        self.eval_calls.append(args)
        return self.eval_result

    def zrange(self, *_args, **_kwargs):
        return list(self.slots.items())

    def zscore(self, _key, token):
        return self.slots.get(token)

    def zadd(self, _key, mapping, **kwargs):
        self.zadd_calls.append((mapping, kwargs))
        added = 0
        for token, score in mapping.items():
            if kwargs.get("xx") and token not in self.slots:
                continue
            if token not in self.slots:
                added += 1
            self.slots[token] = score
        return added

    def expire(self, *args):
        self.expire_calls.append(args)
        return True

    def zrem(self, *args):
        self.zrem_calls.append(args)
        token = args[-1]
        removed = 1 if token in self.slots else 0
        self.slots.pop(token, None)
        return removed

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


def test_list_analysis_slots_parses_tokens(monkeypatch):
    fake = FakeRedis(
        slots={
            "paper-1:task-1": 123.0,
            "paper-2:task-2": "456.5",
        }
    )
    monkeypatch.setattr(analysis_slots, "_create_redis_client", lambda _url: fake)

    slots = analysis_slots.list_analysis_slots(redis_url="redis://example/0")

    assert [slot.paper_id for slot in slots] == ["paper-1", "paper-2"]
    assert [slot.expires_at for slot in slots] == [123.0, 456.5]
    assert fake.closed is True


def test_cleanup_stale_analysis_slots_releases_inactive_and_expired_tokens(monkeypatch):
    fake = FakeRedis(
        slots={
            "active-paper:task-1": 9999999999.0,
            "missing-paper:task-2": 9999999999.0,
            "expired-paper:task-3": 1.0,
        }
    )
    monkeypatch.setattr(analysis_slots, "_create_redis_client", lambda _url: fake)

    removed = analysis_slots.cleanup_stale_analysis_slots(
        {"active-paper", "expired-paper"},
        redis_url="redis://example/0",
    )

    assert removed == 2
    assert "active-paper:task-1" in fake.slots
    assert "missing-paper:task-2" not in fake.slots
    assert "expired-paper:task-3" not in fake.slots


def test_refresh_analysis_slot_updates_score_and_key_ttl(monkeypatch):
    fake = FakeRedis(slots={"paper-1:task-1": 123.0})
    monkeypatch.setattr(analysis_slots.time, "time", lambda: 1000.0)
    slot = analysis_slots.AnalysisSlot(
        token="paper-1:task-1",
        paper_id="paper-1",
        managed=True,
        client=fake,
    )

    refreshed = analysis_slots.refresh_analysis_slot(slot, ttl_seconds=120)

    assert refreshed is True
    assert fake.slots["paper-1:task-1"] == 1120.0
    assert fake.zadd_calls == [({"paper-1:task-1": 1120.0}, {"xx": True})]
    assert fake.expire_calls == [(analysis_slots.ANALYSIS_SLOT_KEY, 120)]


def test_refresh_analysis_slot_returns_false_when_token_missing():
    fake = FakeRedis(slots={})
    slot = analysis_slots.AnalysisSlot(
        token="paper-1:task-1",
        paper_id="paper-1",
        managed=True,
        client=fake,
    )

    assert analysis_slots.refresh_analysis_slot(slot, ttl_seconds=120) is False
    assert fake.zadd_calls == []
