import asyncio
import json

import httpx
import pytest

import llm
from cues import EMOJI_EMOTIONS, clean_spoken


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


def test_every_request_sorts_providers_by_latency():
    _, requests, _ = run(lambda model: httpx.Response(500, text="down") if model == "main" else stream(text("はい")))
    assert all(r["provider"] == {"sort": "latency"} for r in requests)


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


def test_prompt_lists_every_expression_emoji_except_those_left_out():
    for emoji in EMOJI_EMOTIONS:
        assert (emoji in llm.SYSTEM_PROMPT) == (emoji not in llm.LEFT_OUT_OF_PROMPT)


def test_prompt_gives_every_expression_a_name():
    assert set(EMOJI_EMOTIONS.values()) <= set(llm.EMOTION_NAMES)


def test_voice_meanings_describe_only_mapped_emoji():
    assert set(llm.VOICE_MEANINGS) <= set(EMOJI_EMOTIONS)


def test_voice_only_emoji_have_no_expression():
    assert not set(llm.VOICE_ONLY_EMOJI) & set(EMOJI_EMOTIONS)


def test_prompt_is_not_about_one_kind_of_content():
    for word in ("麻雀", "牌", "プレイヤー"):
        assert word not in llm.SYSTEM_PROMPT + llm.SCREEN_RULE + llm.speech_message("x", "y")


def test_prompt_emoji_survive_parsing_whole():
    for emoji in [*EMOJI_EMOTIONS, *llm.VOICE_ONLY_EMOJI]:
        assert clean_spoken(f"{emoji}テスト") == f"{emoji}テスト"