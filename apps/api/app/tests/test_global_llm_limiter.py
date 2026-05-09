import pytest
from contextlib import asynccontextmanager

from app.services.llm import moonshot_client
from app.services.llm import claude_client
from app.services.llm import global_limiter
from app.services.llm.claude_client import ClaudeClient
from app.services.llm.moonshot_client import MoonshotClient


class FakeAsyncRedis:
    def __init__(self, eval_results):
        self.eval_results = list(eval_results)
        self.eval_calls = []
        self.zrem_calls = []
        self.closed = False

    async def eval(self, *args):
        self.eval_calls.append(args)
        return self.eval_results.pop(0)

    async def zrem(self, *args):
        self.zrem_calls.append(args)

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_acquire_llm_slot_returns_unmanaged_when_disabled():
    slot = await global_limiter.acquire_llm_slot(limit=0)

    assert slot.managed is False


@pytest.mark.asyncio
async def test_acquire_and_release_llm_slot_with_redis(monkeypatch):
    fake = FakeAsyncRedis(eval_results=[1])
    monkeypatch.setattr(global_limiter, "_create_async_redis_client", lambda _url: fake)
    monkeypatch.setattr(global_limiter.uuid, "uuid4", lambda: "slot-token")

    slot = await global_limiter.acquire_llm_slot(limit=3, redis_url="redis://example/0")

    assert slot.managed is True
    assert slot.token == "slot-token"
    assert fake.eval_calls

    await global_limiter.release_llm_slot(slot)

    assert fake.zrem_calls == [(global_limiter.LLM_SLOT_KEY, "slot-token")]
    assert fake.closed is True


@pytest.mark.asyncio
async def test_vision_llm_request_slot_acquires_pool_then_global(monkeypatch):
    fake = FakeAsyncRedis(eval_results=[1, 1])
    monkeypatch.setattr(global_limiter, "_create_async_redis_client", lambda _url: fake)
    monkeypatch.setattr(global_limiter.uuid, "uuid4", lambda: "slot-token")
    monkeypatch.setattr(global_limiter.settings, "GLOBAL_LLM_CONCURRENCY", 8)
    monkeypatch.setattr(global_limiter.settings, "GLOBAL_VISION_LLM_CONCURRENCY", 3)

    async with global_limiter.llm_request_slot(pool="vision"):
        assert [call[2] for call in fake.eval_calls] == [
            global_limiter.VISION_LLM_SLOT_KEY,
            global_limiter.GLOBAL_LLM_SLOT_KEY,
        ]

    assert fake.zrem_calls == [
        (global_limiter.GLOBAL_LLM_SLOT_KEY, "slot-token"),
        (global_limiter.VISION_LLM_SLOT_KEY, "slot-token"),
    ]


@pytest.mark.asyncio
async def test_question_llm_request_slot_acquires_pool_then_global(monkeypatch):
    fake = FakeAsyncRedis(eval_results=[1, 1])
    monkeypatch.setattr(global_limiter, "_create_async_redis_client", lambda _url: fake)
    monkeypatch.setattr(global_limiter.uuid, "uuid4", lambda: "slot-token")
    monkeypatch.setattr(global_limiter.settings, "GLOBAL_LLM_CONCURRENCY", 8)
    monkeypatch.setattr(global_limiter.settings, "GLOBAL_QUESTION_LLM_CONCURRENCY", 5)

    async with global_limiter.llm_request_slot(pool="question"):
        assert [call[2] for call in fake.eval_calls] == [
            global_limiter.QUESTION_LLM_SLOT_KEY,
            global_limiter.GLOBAL_LLM_SLOT_KEY,
        ]

    assert fake.zrem_calls == [
        (global_limiter.GLOBAL_LLM_SLOT_KEY, "slot-token"),
        (global_limiter.QUESTION_LLM_SLOT_KEY, "slot-token"),
    ]


@pytest.mark.asyncio
async def test_pool_full_does_not_acquire_global_slot(monkeypatch):
    fake = FakeAsyncRedis(eval_results=[0])
    monkeypatch.setattr(global_limiter, "_create_async_redis_client", lambda _url: fake)
    monkeypatch.setattr(global_limiter.settings, "GLOBAL_LLM_CONCURRENCY", 8)
    monkeypatch.setattr(global_limiter.settings, "GLOBAL_VISION_LLM_CONCURRENCY", 3)
    monkeypatch.setattr(global_limiter.settings, "GLOBAL_LLM_ACQUIRE_TIMEOUT_SECONDS", 0)

    with pytest.raises(global_limiter.GlobalLLMConcurrencyTimeout):
        async with global_limiter.llm_request_slot(pool="vision"):
            pass

    assert [call[2] for call in fake.eval_calls] == [global_limiter.VISION_LLM_SLOT_KEY]
    assert fake.zrem_calls == []
    assert fake.closed is True


@pytest.mark.asyncio
async def test_global_full_releases_previously_acquired_pool_slot(monkeypatch):
    fake = FakeAsyncRedis(eval_results=[1, 0])
    monkeypatch.setattr(global_limiter, "_create_async_redis_client", lambda _url: fake)
    monkeypatch.setattr(global_limiter.uuid, "uuid4", lambda: "slot-token")
    monkeypatch.setattr(global_limiter.settings, "GLOBAL_LLM_CONCURRENCY", 8)
    monkeypatch.setattr(global_limiter.settings, "GLOBAL_QUESTION_LLM_CONCURRENCY", 5)
    monkeypatch.setattr(global_limiter.settings, "GLOBAL_LLM_ACQUIRE_TIMEOUT_SECONDS", 0)

    with pytest.raises(global_limiter.GlobalLLMConcurrencyTimeout):
        async with global_limiter.llm_request_slot(pool="question"):
            pass

    assert [call[2] for call in fake.eval_calls] == [
        global_limiter.QUESTION_LLM_SLOT_KEY,
        global_limiter.GLOBAL_LLM_SLOT_KEY,
    ]
    assert fake.zrem_calls == [(global_limiter.QUESTION_LLM_SLOT_KEY, "slot-token")]
    assert fake.closed is True


@pytest.mark.asyncio
async def test_moonshot_client_wraps_http_post_in_global_limiter(monkeypatch):
    events = []

    @asynccontextmanager
    async def fake_slot():
        events.append("enter")
        yield
        events.append("exit")

    async def fake_post(_payload):
        events.append("post")
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(moonshot_client, "llm_request_slot", fake_slot)
    client = MoonshotClient(api_key="key", model="model", base_url="https://example.com/v1")
    monkeypatch.setattr(client, "_post_chat_completion_unlimited", fake_post)

    content = await client.chat([{"role": "user", "content": "hello"}])

    assert content == "ok"
    assert events == ["enter", "post", "exit"]


@pytest.mark.asyncio
async def test_moonshot_client_uses_configured_llm_pool(monkeypatch):
    events = []

    @asynccontextmanager
    async def fake_slot(pool=None):
        events.append(("enter", pool))
        yield
        events.append(("exit", pool))

    async def fake_post(_payload):
        events.append(("post", None))
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(moonshot_client, "llm_request_slot", fake_slot)
    client = MoonshotClient(
        api_key="key",
        model="model",
        base_url="https://example.com/v1",
        llm_pool="question",
    )
    monkeypatch.setattr(client, "_post_chat_completion_unlimited", fake_post)

    content = await client.chat([{"role": "user", "content": "hello"}])

    assert content == "ok"
    assert events == [("enter", "question"), ("post", None), ("exit", "question")]


@pytest.mark.asyncio
async def test_claude_client_wraps_http_post_in_global_limiter(monkeypatch):
    events = []

    @asynccontextmanager
    async def fake_slot():
        events.append("enter")
        yield
        events.append("exit")

    class FakeResponse:
        def raise_for_status(self):
            events.append("raise_for_status")

        def json(self):
            return {
                "content": [{"text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            events.append("post")
            return FakeResponse()

    monkeypatch.setattr(claude_client, "llm_request_slot", fake_slot)
    monkeypatch.setattr(claude_client.httpx, "AsyncClient", FakeAsyncClient)
    client = ClaudeClient(api_key="key", model="claude-sonnet-4-5")

    content = await client.chat([{"role": "user", "content": "hello"}])

    assert content == "ok"
    assert events == ["enter", "post", "raise_for_status", "exit"]


@pytest.mark.asyncio
async def test_acquire_llm_slot_times_out_when_limit_stays_full(monkeypatch):
    fake = FakeAsyncRedis(eval_results=[0, 0, 0])
    monkeypatch.setattr(global_limiter, "_create_async_redis_client", lambda _url: fake)

    with pytest.raises(global_limiter.GlobalLLMConcurrencyTimeout):
        await global_limiter.acquire_llm_slot(
            limit=3,
            timeout_seconds=0,
            retry_interval_seconds=0.01,
            redis_url="redis://example/0",
        )

    assert fake.closed is True
