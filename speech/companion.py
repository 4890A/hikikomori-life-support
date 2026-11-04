"""One companion turn: a streaming LLM reply, spoken sentence by sentence as it arrives.

POST /companion/turn streams newline-delimited JSON:
  {"type":"expression", ...}  the face to show now, from the reply's first emoji, before any audio
  {"type":"segment", ...}     same as /speak, except "count" is null because the total isn't known yet
  {"type":"trace", ...}       latency of each stage in seconds
  {"type":"done"} or {"type":"error", "message":...}

Disconnecting cancels the turn. A segment already at the TTS server still finishes there, and the
next turn waits for it because the server synthesizes one request at a time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import AsyncIterator
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from cues import ReplyEvents, ReplyParser
from llm import SYSTEM_PROMPT, LLMError, StreamInfo, screen_message, speech_message, stream_reply
from synthesis import DEFAULT_VOICE, TTS_TIMEOUT, TTSError, synthesize_segment

logger = logging.getLogger("speech-bridge")
router = APIRouter(prefix="/companion")

# Text only: old frames would cost money on every turn and slow the model down.
HISTORY_MESSAGES = 16
SCREEN_TURN_NOTE = "（画面を見て反応して）"

history: deque[dict] = deque(maxlen=HISTORY_MESSAGES)
latest_summary: str | None = None


class TurnRequest(BaseModel):
    kind: Literal["speech", "screen"]
    text: str | None = None
    image: str | None = None  # Data URL of a JPEG frame.
    voice: str = DEFAULT_VOICE


def line(message: dict) -> str:
    return json.dumps(message, ensure_ascii=False) + "\n"


def build_messages(request: TurnRequest) -> list[dict]:
    if request.kind == "screen":
        content: str | list[dict] = screen_message(request.image or "")
    else:
        content = speech_message(request.text or "", latest_summary)
    return [{"role": "system", "content": SYSTEM_PROMPT}, *history, {"role": "user", "content": content}]


async def turn_lines(request: TurnRequest) -> AsyncIterator[str]:
    global latest_summary
    started = time.perf_counter()
    since = lambda: round(time.perf_counter() - started, 3)  # noqa: E731
    trace: dict = {"type": "trace", "kind": request.kind}
    out: asyncio.Queue[str | None] = asyncio.Queue()
    to_speak: asyncio.Queue[str | None] = asyncio.Queue()
    parser = ReplyParser()
    info = StreamInfo()
    spoken: list[str] = []

    def apply(events: ReplyEvents) -> None:
        if events.emoji is not None:
            trace.setdefault("expression", since())
            out.put_nowait(line({"type": "expression", "emotion": events.emoji.emotion, "emoji": events.emoji.char}))
        for segment in events.segments:
            trace.setdefault("first_sentence", since())
            to_speak.put_nowait(segment)

    async def read_llm(client: httpx.AsyncClient) -> None:
        try:
            async for delta in stream_reply(client, build_messages(request), info):
                trace.setdefault("first_token", since())
                apply(parser.feed(delta))
                if parser.finished:
                    break
            apply(parser.finish())
        finally:
            to_speak.put_nowait(None)

    async def speak(client: httpx.AsyncClient) -> None:
        index = 0
        while (text := await to_speak.get()) is not None:
            segment = await synthesize_segment(client, text, request.voice)
            trace.setdefault("first_audio_ready", since())
            spoken.append(text)
            out.put_nowait(line({"type": "segment", "index": index, "count": None, **segment}))
            index += 1

    async def run() -> None:
        try:
            async with httpx.AsyncClient(timeout=TTS_TIMEOUT) as client:
                tasks = [asyncio.create_task(read_llm(client)), asyncio.create_task(speak(client))]
                try:
                    await asyncio.gather(*tasks)
                finally:
                    # After one fails, gather leaves the other running.
                    for task in tasks:
                        task.cancel()
            trace["total"] = since()
            trace["model"] = info.model
            trace["provider"] = info.provider
            trace["cost"] = info.usage.get("cost")
            logger.info("companion turn %s, spoken %s, summary %s", trace, spoken, parser.summary)
            out.put_nowait(line(trace))
            out.put_nowait(line({"type": "done"}))
        except (LLMError, TTSError) as exc:
            out.put_nowait(line({"type": "error", "message": str(exc)}))
        except Exception as exc:
            logger.exception("companion turn failed")
            out.put_nowait(line({"type": "error", "message": f"{type(exc).__name__}: {exc}"}))
        finally:
            out.put_nowait(None)

    task = asyncio.create_task(run())
    try:
        while (message := await out.get()) is not None:
            yield message
    finally:
        task.cancel()
        # Even a cancelled turn keeps what was actually said, so the next reply can follow on.
        if spoken:
            user_text = request.text if request.kind == "speech" else SCREEN_TURN_NOTE
            history.append({"role": "user", "content": user_text})
            history.append({"role": "assistant", "content": "".join(spoken)})
        latest_summary = parser.summary or latest_summary


@router.post("/turn")
async def turn(request: TurnRequest) -> StreamingResponse:
    if request.kind == "speech" and not (request.text and request.text.strip()):
        raise HTTPException(status_code=400, detail="a speech turn needs text")
    if request.kind == "screen" and not (request.image and request.image.startswith("data:image/")):
        raise HTTPException(status_code=400, detail="a screen turn needs an image data URL")
    return StreamingResponse(turn_lines(request), media_type="application/x-ndjson")
