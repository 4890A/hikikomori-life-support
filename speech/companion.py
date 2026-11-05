"""One companion turn: a streaming LLM reply, spoken sentence by sentence as it arrives.

POST /companion/turn streams newline-delimited JSON:
  {"type":"turn", ...}        this reply's id, to commit it once it has been heard
  {"type":"stage", ...}       "writing" at the model's first word, "tts" when a sentence goes to TTS
  {"type":"expression", ...}  the face to show now, from the reply's first emoji, before any audio
  {"type":"segment", ...}     same as /speak, except "count" is null because the total isn't known yet
  {"type":"trace", ...}       latency of each stage in seconds
  {"type":"done"} or {"type":"error", "message":...}

She prepares lines she may never say, so nothing is remembered until POST /companion/commit lists the
sentences that played.

Disconnecting cancels the turn. A segment already at the TTS server still finishes there, and the
next turn waits for it because the server synthesizes one request at a time.

The character card and her memory can be read and edited through the other routes here. Memory is
updated in the background after a turn, so it never delays a reply.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from character import DATA_DIR, CharacterCard, load_card, reset_card, save_card
from cues import ReplyEvents, ReplyParser
from llm import FALLBACK_MODEL, MODEL, LLMError, StreamInfo, complete, stream_reply
from memory_store import MemoryStore, PendingTurns, parse_update, update_messages
from prompts import SCREEN_TURN_NOTE, build_system_prompt, screen_message, speech_message
import provider_check
from synthesis import TTS_TIMEOUT, TTSError, synthesize_segment
from tts_request import DEFAULT_VOICE, MIN_SEGMENT_CHARS

logger = logging.getLogger("speech-bridge")
router = APIRouter(prefix="/companion")

card: CharacterCard = load_card()
store = MemoryStore(DATA_DIR / "memory.json")
pending_turns = PendingTurns()
updating_memory = False


class TurnRequest(BaseModel):
    kind: Literal["speech", "screen"]
    text: str | None = None
    image: str | None = None  # Data URL of a JPEG frame.
    voice: str = DEFAULT_VOICE
    now_saying: str | None = None  # What she's still saying, if this line will follow it.


class CommitRequest(BaseModel):
    turn_id: str
    spoken: list[str]


def line(message: dict) -> str:
    return json.dumps(message, ensure_ascii=False) + "\n"


def build_messages(request: TurnRequest) -> list[dict]:
    memory = store.memory
    if request.kind == "screen":
        content: str | list[dict] = screen_message(card, request.image or "", memory.history, request.now_saying)
    else:
        content = speech_message(request.text or "", memory.screen_summary, memory.history, request.now_saying)
    return [{"role": "system", "content": build_system_prompt(card, memory)}, *memory.history, {"role": "user", "content": content}]


async def update_memory() -> None:
    """Folds recent exchanges into her summary and facts. A failure just tries again next time."""
    global updating_memory
    if updating_memory or not store.needs_update():
        return
    updating_memory = True
    pending = list(store.memory.unprocessed)
    try:
        async with httpx.AsyncClient() as client:
            text = await complete(client, update_messages(store.memory, pending))
        update = parse_update(text)
        if update is None:
            logger.warning("memory update was not usable: %s", text[:200])
            return
        store.apply_update(*update, processed=len(pending))
        logger.info("memory updated: %d facts, summary %s", len(store.memory.facts), store.memory.summary)
    except LLMError as exc:
        logger.warning("memory update failed: %s", exc)
    finally:
        updating_memory = False


async def turn_lines(request: TurnRequest) -> AsyncIterator[str]:
    started = time.perf_counter()
    since = lambda: round(time.perf_counter() - started, 3)  # noqa: E731
    trace: dict = {"type": "trace", "kind": request.kind}
    out: asyncio.Queue[str | None] = asyncio.Queue()
    to_speak: asyncio.Queue[str | None] = asyncio.Queue()
    parser = ReplyParser(MIN_SEGMENT_CHARS)
    info = StreamInfo()
    spoken: list[str] = []
    is_speech = request.kind == "speech"
    turn_id = pending_turns.start(request.text if is_speech else SCREEN_TURN_NOTE, is_speech)
    out.put_nowait(line({"type": "turn", "turn_id": turn_id}))

    def apply(events: ReplyEvents) -> None:
        if events.emoji is not None:
            trace.setdefault("expression", since())
            out.put_nowait(line({"type": "expression", "emotion": events.emoji.emotion, "emoji": events.emoji.char}))
        for segment in events.segments:
            if "first_sentence" not in trace:
                trace["first_sentence"] = since()
                out.put_nowait(line({"type": "stage", "stage": "tts"}))
            to_speak.put_nowait(segment)

    async def read_llm(client: httpx.AsyncClient) -> None:
        try:
            async for delta in stream_reply(client, build_messages(request), info):
                if "first_token" not in trace:
                    trace["first_token"] = since()
                    out.put_nowait(line({"type": "stage", "stage": "writing"}))
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
        pending_turns.set_summary(turn_id, parser.summary)


@router.post("/turn")
async def turn(request: TurnRequest) -> StreamingResponse:
    if request.kind == "speech" and not (request.text and request.text.strip()):
        raise HTTPException(status_code=400, detail="a speech turn needs text")
    if request.kind == "screen" and not (request.image and request.image.startswith("data:image/")):
        raise HTTPException(status_code=400, detail="a screen turn needs an image data URL")
    return StreamingResponse(turn_lines(request), media_type="application/x-ndjson")


@router.post("/commit")
async def commit_turn(request: CommitRequest) -> dict:
    """Remembers the sentences of a reply that were actually heard."""
    saved = pending_turns.commit(request.turn_id, request.spoken, store)
    if saved and request.spoken:
        asyncio.ensure_future(update_memory())
    return {"saved": saved}


@router.get("/providers")
async def get_providers() -> dict:
    return {**provider_check.status, "main_model": MODEL, "fallback_model": FALLBACK_MODEL}


@router.post("/providers/check")
async def recheck_providers() -> dict:
    await provider_check.check_providers()
    return await get_providers()


@router.get("/character")
async def get_character() -> CharacterCard:
    return card


@router.put("/character")
async def put_character(new_card: CharacterCard) -> CharacterCard:
    global card
    save_card(new_card)
    card = new_card
    return card


@router.delete("/character")
async def delete_character() -> CharacterCard:
    """Goes back to the default card."""
    global card
    card = reset_card()
    return card


@router.get("/prompt")
async def get_prompt() -> dict:
    """Exactly what the LLM is told right now, to check an edit."""
    return {"system": build_system_prompt(card, store.memory)}


@router.get("/memory")
async def get_memory() -> dict:
    memory = store.memory
    return {"facts": memory.facts, "summary": memory.summary, "messages": len(memory.history)}


@router.delete("/memory")
async def clear_memory() -> dict:
    store.clear()
    return await get_memory()


@router.delete("/memory/facts/{index}")
async def forget_fact(index: int) -> dict:
    if not store.forget_fact(index):
        raise HTTPException(status_code=404, detail="no such fact")
    return await get_memory()
