import asyncio
import json

import httpx
import pytest

import llm


def stream(*chunks: dict) -> httpx.Response:
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks] + ["data: [DONE]\n\n"]
    return httpx.Response(200, text="".join(lines))


def text(content: str) -> dict:
    return {"choices": [{"delta": {"content": content}}]}


def run(handler) -> tuple[list[str], list[dict], BaseException | None]:
    """Streams one reply against a fake OpenRouter. Returns the text, the requests and any error."""
    requests: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        return handler(body["model"])

    async def collect() -> tuple[list[str], BaseException | None]:
        deltas: list[str] = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
            try:
                async for delta in llm.stream_reply(client, [], llm.StreamInfo()):
                    deltas.append(delta)
            except llm.LLMError as exc:
                return deltas, exc
        return deltas, None

    deltas, error = asyncio.run(collect())
    return deltas, requests, error


@pytest.fixture(autouse=True)
def models(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(llm, "MODEL", "main")
    monkeypatch.setattr(llm, "FALLBACK_MODEL", "z-ai/glm-5.3-flash")


def test_uses_only_the_main_model_when_it_works():
    deltas, requests, error = run(lambda model: stream(text("おっ"), text("、いいね")))
    assert deltas == ["おっ", "、いいね"]
    assert [r["model"] for r in requests] == ["main"]
    assert error is None


def test_each_model_gets_its_own_reasoning_setting():
    _, requests, _ = run(lambda model: httpx.Response(500, text="down") if model == "main" else stream(text("はい")))
    assert requests[0]["reasoning"] == {"enabled": False}
    assert requests[1]["reasoning"] == {"effort": "minimal", "exclude": True}


def test_known_models_prefer_proven_providers_but_can_use_others():
    _, requests, _ = run(lambda model: httpx.Response(500, text="down") if model == "main" else stream(text("はい")))
    assert requests[1]["provider"] == {"order": llm.PROVIDER_ORDER["z-ai/glm-5.3-flash"], "allow_fallbacks": True}


def test_other_models_sort_providers_by_latency():
    _, requests, _ = run(lambda model: httpx.Response(500, text="down") if model == "main" else stream(text("はい")))
    assert requests[0]["provider"] == {"sort": "latency"}


def test_falls_back_when_the_main_model_is_refused():
    deltas, _, error = run(lambda model: httpx.Response(429, text="busy") if model == "main" else stream(text("はい")))
    assert deltas == ["はい"]
    assert error is None


def test_falls_back_when_the_main_model_returns_no_text():
    deltas, requests, error = run(lambda model: stream({"choices": [{"delta": {"content": ""}}]}) if model == "main" else stream(text("はい")))
    assert deltas == ["はい"]
    assert len(requests) == 2
    assert error is None


def test_falls_back_on_a_stream_error_before_any_text():
    deltas, _, error = run(lambda model: stream({"error": {"code": 429}}) if model == "main" else stream(text("はい")))
    assert deltas == ["はい"]
    assert error is None


def test_does_not_restart_a_reply_that_fails_partway():
    deltas, requests, error = run(lambda model: stream(text("おっ"), {"error": {"code": 500}}))
    assert deltas == ["おっ"]
    assert len(requests) == 1
    assert isinstance(error, llm.LLMError)


def test_reports_when_both_models_fail():
    deltas, requests, error = run(lambda model: httpx.Response(500, text="down"))
    assert deltas == []
    assert len(requests) == 2
    assert isinstance(error, llm.LLMError)


def run_async(handler, seconds=llm.FIRST_TOKEN_SECONDS, complete=False):
    """Like run, with a handler that can wait, and a chosen limit on the first word."""
    requests: list[str] = []

    async def record(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        requests.append(model)
        return await handler(model)

    async def collect():
        async with httpx.AsyncClient(transport=httpx.MockTransport(record)) as client:
            if complete:
                return await llm.complete(client, [])
            return [delta async for delta in llm.stream_reply(client, [], llm.StreamInfo(), seconds)]

    return asyncio.run(collect()), requests


def test_stalled_main_model_moves_to_the_fallback():
    async def handler(model):
        if model == "main":
            await asyncio.sleep(5)
        return stream(text("はい"))

    deltas, requests = run_async(handler, seconds=0.05)
    assert deltas == ["はい"]
    assert requests == ["main", "z-ai/glm-5.3-flash"]


def test_the_last_model_may_take_as_long_as_it_needs():
    async def handler(model):
        if model == "main":
            return httpx.Response(500, text="down")
        await asyncio.sleep(0.2)
        return stream(text("はい"))

    deltas, _ = run_async(handler, seconds=0.05)
    assert deltas == ["はい"]


def test_fast_main_model_is_not_cut_off():
    async def handler(model):
        return stream(text("はい"))

    deltas, requests = run_async(handler, seconds=1.0)
    assert deltas == ["はい"]
    assert requests == ["main"]


def test_background_work_has_no_first_word_limit(monkeypatch):
    monkeypatch.setattr(llm, "FIRST_TOKEN_SECONDS", 0.01)

    async def handler(model):
        await asyncio.sleep(0.1)
        return stream(text("はい"))

    text_out, requests = run_async(handler, complete=True)
    assert text_out == "はい"
    assert requests == ["main"]
