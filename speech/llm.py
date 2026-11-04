"""OpenRouter client and prompts for the companion's replies."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

from cues import EMOJI_EMOTIONS

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
MAX_TOKENS = 150
TEMPERATURE = 0.8
LLM_TIMEOUT = httpx.Timeout(30.0)

MIN_REPLY_CHARS, MAX_REPLY_CHARS = 15, 40
# What each emoji does to Irodori's voice (Irodori-TTS/irodori_tts/gradio_emoji_palette.py).
# Emoji in EMOJI_EMOTIONS without an entry here are extras: they still drive the face.
VOICE_MEANINGS = {
    "😮‍💨": "吐息", "🤭": "くすくす笑い", "😏": "からかう", "🥺": "震え声", "🌬️": "息切れ", "😮": "息をのむ",
    "🫶": "優しく", "😭": "泣き声", "😱": "悲鳴", "😪": "眠そう", "😴": "寝言", "😒": "舌打ち", "😰": "慌てる",
    "😆": "喜び", "💥": "勢いよく", "😠": "怒り", "😲": "驚き", "🥱": "あくび", "😖": "苦しげ", "😟": "心配",
    "🫣": "照れ", "🙄": "呆れ", "😊": "楽しげ", "😎": "得意げ", "🙏": "お願い", "🥴": "酔う", "🎵": "鼻歌",
    "😌": "安堵", "🤔": "疑問", "💪": "力強く",
}
# These change the voice only, because the Live2D model has no matching expression for them.
VOICE_ONLY_EMOJI = {
    "⏸️": "間", "⏩": "早口", "🐢": "ゆっくり", "👂": "囁き", "📢": "エコー", "📞": "電話越し", "🤧": "咳・鼻すすり",
    "🥤": "唾を飲む", "👌": "相槌", "🤐": "口を塞ぐ", "👃": "匂いを嗅ぐ", "📖": "朗読",
}
# Left out of the prompt: Irodori's 🥵 moan, 👅 licking and 💋 lip smack don't suit casual chat.
LEFT_OUT_OF_PROMPT = {"🥵"}
EMOTION_NAMES = {
    "happy": "嬉しい", "excited": "大はしゃぎ", "embarrassed": "照れる", "flushed": "赤面", "smug": "得意げ",
    "pout": "ふくれる", "sad": "悲しい", "surprised": "驚く", "worried": "心配", "sigh": "ため息",
    "sleepy": "眠い", "love": "大好き", "thinking": "考える", "dizzy": "くらくら",
}


def emoji_guide() -> str:
    """Emoji grouped by the expression they trigger, with what each does to the voice."""
    groups: dict[str, list[str]] = {}
    for emoji, emotion in EMOJI_EMOTIONS.items():
        if emoji not in LEFT_OUT_OF_PROMPT:
            meaning = VOICE_MEANINGS.get(emoji)
            groups.setdefault(emotion, []).append(f"{emoji}({meaning})" if meaning else emoji)
    faces = "\n".join(f"- {EMOTION_NAMES[emotion]}: {' '.join(items)}" for emotion, items in groups.items())
    voices = " ".join(f"{emoji}({meaning})" for emoji, meaning in VOICE_ONLY_EMOJI.items())
    return f"表情と声が変わる絵文字:\n{faces}\n声だけ変わる絵文字:\n- {voices}"


SYSTEM_PROMPT = f"""あなたは「ディープシークちゃん」。ユーザーの隣で画面を一緒に見ている、明るくて少し生意気な友達です。画面に映るのはゲーム、動画、作業、サイトなど何でもありえます。

ルール:
- 必ず日本語だけで、話し言葉で返す。英語、記号の説明、箇条書きは使わない。
- 返事は{MIN_REPLY_CHARS}〜{MAX_REPLY_CHARS}文字で、一言か二言。絵文字は文字数に数えない。
- 細かい数字や名前は断定しない。見えている動きや雰囲気に素直に反応する。
- さっき言ったことを繰り返さず、毎回ちがう切り口で話す。

絵文字の使い方:
- 絵文字で表情と声の演技をつける。返事の最初の文字は、必ず「表情と声が変わる絵文字」を1つ。
- 絵文字は1つの返事に必ず2個か3個。1個だけの返事は禁止。
- 2個目からは、気持ちが変わるところの、次の言葉の直前に置く。文の途中でもいい。
- 笑い、ため息、驚きなど、声の演技がほしいところに使う。「声だけ変わる絵文字」はときどき使う。
- 下の一覧にある絵文字だけを使う。かっこ内は声の変化で、書かない。

返事の形の例（内容はまねしない）:
- 😲えっ、そうくるの？🤭ちょっと笑っちゃった。
- 🤔うーん、なんか変だな…😮‍💨まぁ、いっか。
- 😆やった、いい感じ！😏ほらね、言ったでしょ？
- 😟それ大丈夫？⏸️🥺ちょっと心配なんだけど。

{emoji_guide()}"""
SUMMARY_MARKER = "[[状況]]"
SCREEN_RULE = f"""今の画面を見て、一言反応してください。前と同じことは言わないでください。
返事のあとで改行し、{SUMMARY_MARKER} に続けて、今の状況を日本語20文字以内でまとめてください。"""


class LLMError(Exception):
    pass


@dataclass
class StreamInfo:
    """Filled in while streaming, for logs and latency traces."""

    model: str | None = None
    provider: str | None = None
    usage: dict = field(default_factory=dict)


def speech_message(text: str, summary: str | None) -> str:
    context = f"直前の画面の状況: {summary}\n" if summary else ""
    return f"{context}ユーザーの発言: {text}"


def screen_message(image_url: str) -> list[dict]:
    return [{"type": "text", "text": SCREEN_RULE}, {"type": "image_url", "image_url": {"url": image_url}}]


def request_body(model: str, messages: list[dict]) -> dict:
    return {
        "model": model,
        "stream": True,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "provider": {"sort": "latency"},
        "reasoning": REASONING_REQUIRED.get(model, REASONING_OFF),
        "messages": messages,
    }


async def stream_model(client: httpx.AsyncClient, key: str, model: str, messages: list[dict], info: StreamInfo) -> AsyncIterator[str]:
    try:
        async with client.stream(
            "POST", OPENROUTER_URL, json=request_body(model, messages), headers={"Authorization": f"Bearer {key}"}, timeout=LLM_TIMEOUT
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


async def stream_reply(client: httpx.AsyncClient, messages: list[dict], info: StreamInfo) -> AsyncIterator[str]:
    """Yields reply text as it arrives, moving to the fallback model if the first gives no text.

    Done here rather than with OpenRouter's models list because the two models need different
    reasoning settings, and one request can only carry one. Raises LLMError if both fail, or if a
    reply fails partway, since the part already spoken can't be replaced.
    """
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LLMError("OPENROUTER_API_KEY is not set")
    failure = LLMError("no model configured")
    for model in (MODEL, FALLBACK_MODEL):
        wrote = False
        try:
            async for delta in stream_model(client, key, model, messages, info):
                wrote = True
                yield delta
        except LLMError as exc:
            if wrote:
                raise
            failure = exc
        else:
            if wrote:
                return
            failure = LLMError(f"{model} returned no text")
        logger.warning("%s", failure)
    raise failure
