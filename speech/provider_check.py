"""Picks each LLM's provider from OpenRouter's reported speed, at startup and on request.

Provider speed swings through the day, so a fixed order can go badly stale. This is one quick lookup
of OpenRouter's last 30 minutes of first-token latency and throughput. Those figures cover all its
users and all kinds of request, so they're a guide to which provider is healthy now, not a promise of
what a request with an image from this machine will take. The first word time of each real reply is
reported separately, in the turn's trace.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

import llm

logger = logging.getLogger("speech-bridge")

ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{model}/endpoints"
LOOKUP_TIMEOUT = httpx.Timeout(5.0)
MIN_UPTIME_LAST_5M = 90
ORDER_LENGTH = 5
# How much the slow end counts. A provider with a great median and a bad p90 stalls too often to trust.
P90_WEIGHT = 0.25
# Roughly a short first sentence, which is what she's waiting on before TTS can start.
FIRST_SENTENCE_TOKENS = 15
# Scores closer than this count as a tie, which goes to the cheaper provider.
TIE_MS = 100

status: dict = {"checking": False, "checked_at": None, "models": {}, "error": None}


def score(endpoint: dict) -> float | None:
    """Estimated milliseconds to a first sentence, or None if the provider has no recent figures."""
    latency = endpoint.get("latency_last_30m") or {}
    throughput = endpoint.get("throughput_last_30m") or {}
    p50, p90, tokens_per_second = latency.get("p50"), latency.get("p90"), throughput.get("p50")
    if p50 is None or p90 is None or not tokens_per_second:
        return None
    return p50 + P90_WEIGHT * max(0.0, p90 - p50) + 1000 * FIRST_SENTENCE_TOKENS / tokens_per_second


def rank(endpoints: list[dict]) -> list[dict]:
    """Healthy providers with recent figures: near ties by price, then the rest by score."""
    rows: list[dict] = []
    for endpoint in endpoints:
        value = score(endpoint)
        uptime = endpoint.get("uptime_last_5m")
        healthy = endpoint.get("status", 0) >= 0 and (uptime is None or uptime >= MIN_UPTIME_LAST_5M)
        if value is None or not healthy or not endpoint.get("tag"):
            continue
        rows.append(
            {
                "provider": endpoint["tag"],
                "name": endpoint.get("provider_name"),
                "score_ms": round(value),
                "p50_ms": round(endpoint["latency_last_30m"]["p50"]),
                "p90_ms": round(endpoint["latency_last_30m"]["p90"]),
                "tokens_per_second": round(endpoint["throughput_last_30m"]["p50"]),
                "price": round(float(endpoint["pricing"]["prompt"]) * 1e6, 3),
            }
        )
    if not rows:
        return []
    best = min(row["score_ms"] for row in rows)
    return sorted(rows, key=lambda row: (row["score_ms"] > best + TIE_MS, row["price"] if row["score_ms"] <= best + TIE_MS else row["score_ms"]))


async def _check_model(client: httpx.AsyncClient, key: str, model: str) -> None:
    response = await client.get(ENDPOINTS_URL.format(model=model), headers={"Authorization": f"Bearer {key}"}, timeout=LOOKUP_TIMEOUT)
    response.raise_for_status()
    ranked = rank(response.json()["data"]["endpoints"])
    status["models"][model] = ranked[:ORDER_LENGTH]
    if ranked:
        llm.set_provider_order(model, [row["provider"] for row in ranked[:ORDER_LENGTH]])
    logger.info("providers for %s: %s", model, [(r["provider"], r["score_ms"], r["price"]) for r in ranked[:ORDER_LENGTH]])


async def check_providers() -> dict:
    """Updates routing from OpenRouter's figures. A failure keeps the order already in use."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        status["error"] = "OPENROUTER_API_KEY is not set"
        logger.warning("provider check skipped: %s", status["error"])
        return status
    status["checking"] = True
    status["error"] = None
    try:
        async with httpx.AsyncClient() as client:
            await asyncio.gather(*(_check_model(client, key, model) for model in (llm.MODEL, llm.FALLBACK_MODEL)))
        status["checked_at"] = time.time()
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("provider check failed, keeping the current order: %s", status["error"])
    finally:
        status["checking"] = False
    return status
