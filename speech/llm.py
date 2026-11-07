"""OpenRouter client for the companion's replies. The prompts are in prompts.py."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("speech-bridge")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Picked in the docs/companion-plan.md benchmarks. Fallback is tried if the first model fails.
MODEL = os.environ.get("COMPANION_MODEL", "deepseek/deepseek-v4.1-flash")
FALLBACK_MODEL = os.environ.get("COMPANION_FALLBACK_MODEL", "z-ai/glm-5.3-flash")
# Thinking delays the first word, and DeepSeek returned no text at all on minimal reasoning.
REASONING_OFF = {"enabled": False}
# These reject disabled reasoning, so they get the least they accept.
REASONING_REQUIRED = {
    "z-ai/glm-5.3-flash": {"effort": "minimal", "exclude": True},
    "openai/gpt-5-nano": {"effort": "minimal", "exclude": True},
}
# Providers tried in order, then any other, until provider_check.py measures a better order. Their speed
# swings over the day: on 2026-11-03 the default routing sent DeepSeek to providers taking 7-13 s for a
# first word, then 0.7 s an hour later.
PROVIDER_ORDER = {
    "deepseek/deepseek-v4.1-flash": ["wafer", "inference-net", "digitalocean"],
    "z-ai/glm-5.3-flash": ["inference-net", "wafer", "modal"],
}
# A reply with no first word by now moves to the next model. The last model gets as long as it needs.
FIRST_TOKEN_SECONDS = 1.5
MAX_TOKENS = 150
# Memory updates write JSON summaries, which are longer than a spoken line.
BACKGROUND_MAX_TOKENS = 1000
TEMPERATURE = 0.8
LLM_TIMEOUT = httpx.Timeout(30.0)

class LLMError(Exception):
    pass


@dataclass
class StreamInfo:
    """Filled in while streaming, for logs and latency traces."""

    model: str | None = None
    provider: str | None = None
    usage: dict = field(default_factory=dict)


_measured_order: dict[str, list[str]] = {}


def set_provider_order(model: str, order: list[str]) -> None:
    _measured_order[model] = order


def provider_preferences(model: str) -> dict:
    order = _measured_order.get(model) or PROVIDER_ORDER.get(model)
    return {"order": order, "allow_fallbacks": True} if order else {"sort": "latency"}


def request_body(model: str, messages: list[dict], max_tokens: int = MAX_TOKENS) -> dict:
    return {
        "model": model,
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": TEMPERATURE,
        "provider": provider_preferences(model),
        "reasoning": REASONING_REQUIRED.get(model, REASONING_OFF),
        "messages": messages,
    }


async def stream_model(
    client: httpx.AsyncClient, key: str, model: str, messages: list[dict], info: StreamInfo, max_tokens: int = MAX_TOKENS
) -> AsyncIterator[str]:
    try:
        async with client.stream(
            "POST", OPENROUTER_URL, json=request_body(model, messages, max_tokens), headers={"Authorization": f"Bearer {key}"}, timeout=LLM_TIMEOUT
        ) as response:
            if response.status_code != 200:
                detail = (await response.aread()).decode("utf-8", "replace")[:300]
                raise LLMError(f"OpenRouter returned {response.status_code} for {model}: {detail}")
            async for line in response.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                chunk = json.loads(line[6:])
                if "error" in chunk:
                    raise LLMError(f"OpenRouter stream error from {model}: {str(chunk['error'])[:300]}")
                info.model = chunk.get("model", info.model)
                info.provider = chunk.get("provider", info.provider)
                info.usage = chunk.get("usage") or info.usage
                choices = chunk.get("choices") or [{}]
                delta = (choices[0].get("delta") or {}).get("content")
                if delta:
                    yield delta
    except httpx.HTTPError as exc:
        raise LLMError(f"OpenRouter request to {model} failed: {type(exc).__name__}: {exc}") from exc


async def stream_reply(
    client: httpx.AsyncClient,
    messages: list[dict],
    info: StreamInfo,
    first_token_seconds: float | None = FIRST_TOKEN_SECONDS,
    max_tokens: int = MAX_TOKENS,
) -> AsyncIterator[str]:
    """Yields reply text as it arrives, moving to the fallback model if the first gives no text in time.

    Done here rather than with OpenRouter's models list because the two models need different
    reasoning settings, and one request can only carry one. Raises LLMError if both fail, or if a
    reply fails partway, since the part already spoken can't be replaced.
    """
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LLMError("OPENROUTER_API_KEY is not set")
    models = (MODEL, FALLBACK_MODEL)
    failure = LLMError("no model configured")
    for position, model in enumerate(models):
        stream = stream_model(client, key, model, messages, info, max_tokens)
        is_last = position == len(models) - 1
        wrote = False
        try:
            # The fallback is the last resort, so a slow answer beats none.
            first = await asyncio.wait_for(stream.__anext__(), None if is_last else first_token_seconds)
            wrote = True
            yield first
            async for delta in stream:
                yield delta
            return
        except StopAsyncIteration:
            failure = LLMError(f"{model} returned no text")
        except asyncio.TimeoutError:
            failure = LLMError(f"{model} gave no first word within {first_token_seconds} s")
        except LLMError as exc:
            if wrote:
                raise
            failure = exc
        finally:
            await stream.aclose()
        logger.warning("%s", failure)
    raise failure

async def complete(client: httpx.AsyncClient, messages: list[dict], max_tokens: int = BACKGROUND_MAX_TOKENS) -> str:
    """The whole text of one reply, for background work where nobody is waiting on the first word."""
    info = StreamInfo()
    return "".join([delta async for delta in stream_reply(client, messages, info, first_token_seconds=None, max_tokens=max_tokens)])
