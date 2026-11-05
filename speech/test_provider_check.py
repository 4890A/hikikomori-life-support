import asyncio

import httpx
import pytest

import llm
import provider_check
from provider_check import rank, score


def endpoint(tag, p50=300, p90=500, tps=150, price="0.0000001", uptime=100, status=0):
    return {
        "tag": tag,
        "provider_name": tag.split("/")[0],
        "latency_last_30m": {"p50": p50, "p90": p90},
        "throughput_last_30m": {"p50": tps},
        "pricing": {"prompt": price},
        "uptime_last_5m": uptime,
        "status": status,
    }


def order(endpoints):
    return [row["provider"] for row in rank(endpoints)]


def test_score_counts_median_slow_end_and_streaming():
    assert score(endpoint("a", p50=300, p90=700, tps=150)) == 300 + 100 + 100


@pytest.mark.parametrize("missing", ["latency_last_30m", "throughput_last_30m"])
def test_no_recent_figures_gives_no_score(missing):
    assert score({**endpoint("a"), missing: None}) is None


def test_a_big_gap_beats_a_low_price():
    assert order([endpoint("cheap", p50=900, p90=900, price="0.00000001"), endpoint("fast", p50=200, p90=200, price="0.0000005")])[0] == "fast"


def test_a_bad_slow_end_outweighs_a_slightly_better_median():
    # The real case that prompted this: the best median, but 10% of requests over a second.
    stally = endpoint("stally", p50=255, p90=1800, tps=215, price="0.0000003")
    steady = endpoint("steady", p50=330, p90=670, tps=178, price="0.0000003")
    assert order([stally, steady])[0] == "steady"


def test_near_ties_go_to_the_cheaper_provider():
    assert order([endpoint("pricey", p50=300, price="0.00000045"), endpoint("cheap", p50=350, price="0.00000004")])[0] == "cheap"


def test_providers_outside_the_tie_stay_in_score_order():
    ranked = order(
        [
            endpoint("best", p50=200, p90=200),
            endpoint("slowest", p50=2000, p90=2000),
            endpoint("middle", p50=900, p90=900),
        ]
    )
    assert ranked == ["best", "middle", "slowest"]


def test_unhealthy_providers_are_left_out():
    ranked = order([endpoint("down", p50=100, uptime=50), endpoint("errored", p50=100, status=-1), endpoint("fine", p50=400)])
    assert ranked == ["fine"]


def test_unknown_recent_uptime_is_allowed():
    assert order([endpoint("new", uptime=None)]) == ["new"]


def test_no_usable_providers_gives_an_empty_ranking():
    assert rank([{**endpoint("a"), "latency_last_30m": None}]) == []


def test_routing_uses_a_measured_order_and_can_still_fall_back():
    model = "test/provider-model"
    assert llm.provider_preferences(model) == {"sort": "latency"}
    llm.set_provider_order(model, ["b", "a"])
    assert llm.provider_preferences(model) == {"order": ["b", "a"], "allow_fallbacks": True}


@pytest.fixture
def lookup(monkeypatch):
    """A fake OpenRouter. Set `respond` to change what it answers. Restores everything it changes."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    monkeypatch.setattr(llm, "MODEL", "test/main")
    monkeypatch.setattr(llm, "FALLBACK_MODEL", "test/other")
    monkeypatch.setattr(llm, "_measured_order", {})
    monkeypatch.setattr(provider_check, "status", {"checking": False, "checked_at": None, "models": {}, "error": None})
    state = {"requests": [], "respond": lambda: httpx.Response(200, json={"data": {"endpoints": [endpoint("wafer/us")]}})}
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return state["respond"]()

    monkeypatch.setattr(provider_check.httpx, "AsyncClient", lambda: real_client(transport=httpx.MockTransport(handler)))
    return state


def test_check_routes_each_model_and_reports_it(lookup):
    status = asyncio.run(provider_check.check_providers())
    assert llm.provider_preferences("test/main")["order"] == ["wafer/us"]
    assert llm.provider_preferences("test/other")["order"] == ["wafer/us"]
    assert status["models"]["test/main"][0]["p50_ms"] == 300
    assert status["checked_at"] is not None and status["checking"] is False and status["error"] is None


def test_check_is_one_authorized_lookup_per_model_with_no_generation(lookup):
    asyncio.run(provider_check.check_providers())
    assert len(lookup["requests"]) == 2
    for request in lookup["requests"]:
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer secret"


def test_failed_lookup_keeps_the_current_order(lookup):
    llm.set_provider_order("test/main", ["kept"])
    lookup["respond"] = lambda: httpx.Response(503, text="down")
    status = asyncio.run(provider_check.check_providers())
    assert llm.provider_preferences("test/main")["order"] == ["kept"]
    assert status["error"] is not None and status["checking"] is False and status["checked_at"] is None


def test_no_usable_figures_keeps_the_current_order(lookup):
    llm.set_provider_order("test/main", ["kept"])
    lookup["respond"] = lambda: httpx.Response(200, json={"data": {"endpoints": [{**endpoint("a"), "latency_last_30m": None}]}})
    asyncio.run(provider_check.check_providers())
    assert llm.provider_preferences("test/main")["order"] == ["kept"]


def test_check_is_skipped_without_a_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(provider_check, "status", {"checking": False, "checked_at": None, "models": {}, "error": None})
    assert asyncio.run(provider_check.check_providers())["error"] == "OPENROUTER_API_KEY is not set"
