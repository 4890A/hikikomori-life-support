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
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from acts import BEAT, COMMENT, GREETING, MOMENT, REPLY, Act, choose_act
from character import DATA_DIR, CharacterCard, load_card, reset_card, save_card
from cues import _EMOJI, EMOJI_EMOTIONS, LookParser, ReplyEvents, ReplyParser
from llm import FALLBACK_MODEL, MODEL, LLMError, StreamInfo, complete, stream_reply
from memory_store import MAX_FACT_CHARS, MemoryStore, PendingTurns, parse_json
from prompts import FEELING_LABEL, build_system_prompt, context_block, look_message, note_message, reply_message
import provider_check
from recall import episode_from, episode_messages, facts_messages, memory_text, today_messages, transcript, when_was, worth_remembering
from synthesis import TTS_TIMEOUT, TTSError, synthesize_segment
from timeline import DECLINED, HEARD, SAID, SAME_NOTE, SEEN, TURN, Timeline, read_log, similarity
from tts_request import DEFAULT_VOICE, MIN_SEGMENT_CHARS

logger = logging.getLogger("speech-bridge")
router = APIRouter(prefix="/companion")

SESSIONS_DIR = DATA_DIR / "sessions"
card: CharacterCard = load_card()
store = MemoryStore(DATA_DIR / "memory.json")
timeline = Timeline(SESSIONS_DIR)
pending_turns = PendingTurns()

# Why the browser wants a screen line, and so what kind of line it is.
SOURCE_OF_REASON = {"big change": MOMENT, "some change": COMMENT, "check-in": COMMENT, "idle": BEAT, "greeting": GREETING}
# The interest (0-3) a look needs before she says anything: a big change needs little, a lull none.
INTEREST_NEEDED = {MOMENT: 1, COMMENT: 1, BEAT: 0, GREETING: 0}
# How often the summary of today is brought up to date: whichever comes first.
TODAY_EVERY_SECONDS = 240
TODAY_EVERY_EVENTS = 20
# At startup, sessions that ended without becoming memories are wrapped up, at most this many.
WRAP_UP_AT_START = 3
# Her last question still counts as open for this long.
QUESTION_OPEN_SECONDS = 60
# Events older than this give her something to call back to.
CALLBACK_AFTER_SECONDS = 60
# A comment repeating what she noted this recently is declined.
STALE_WITHIN_SECONDS = 45
# A big change this soon after her last reaction is treated as an ordinary comment.
MOMENT_SPACING_SECONDS = 12
# A note is three short lines, and is never spoken.
NOTE_MAX_TOKENS = 70
NOTE_NEVER_SPEAKS = 99


class TurnRequest(BaseModel):
    kind: Literal["speech", "screen"]
    text: str | None = None
    image: str | None = None  # Data URL of a JPEG frame. With speech, the screen as you spoke.
    voice: str = DEFAULT_VOICE
    now_saying: str | None = None  # What she's still saying, if this line will follow it.
    reason: str | None = None  # Why the browser asked for a screen line: see SOURCE_OF_REASON.


class CommitRequest(BaseModel):
    turn_id: str
    spoken: list[str]


def line(message: dict) -> str:
    return json.dumps(message, ensure_ascii=False) + "\n"


def _ends_with_question(text: str) -> bool:
    return any(mark in text[-6:] for mark in ("？", "?"))


def pick_act(source: str) -> Act:
    said = timeline.said(limit=6)
    now = time.time()
    asked_last = bool(said) and _ends_with_question(said[-1].text) and now - said[-1].t < QUESTION_OPEN_SECONDS
    callbacks = [e.t for e in said if e.extra.get("act") == "callback"]
    old = [e for e in timeline.recent(now) if now - e.t >= CALLBACK_AFTER_SECONDS]
    return choose_act(
        source,
        [e.extra.get("act", "") for e in said],
        asked_last=asked_last,
        seconds_since_callback=now - callbacks[-1] if callbacks else float("inf"),
        has_history=bool(old),
    )


def build_messages(request: TurnRequest, act: Act, threshold: int, source: str) -> list[dict]:
    recent_lines = [e.text for e in timeline.said()]
    notes = []
    said = timeline.said(limit=1)
    if request.kind == "screen" and said and _ends_with_question(said[-1].text) and time.time() - said[-1].t < QUESTION_OPEN_SECONDS:
        notes.append("あなたのさっきの質問に、きみはまだ答えていない。同じ質問はしない")
    rendered = timeline.render()
    # Older memories come up when they share words with what's happening now.
    remembered = memory_text(store.memory, f"{rendered[-400:]} {request.text or ''}", greeting=source == GREETING)
    context = context_block(rendered, timeline.minutes_together(), notes=notes, memory=remembered)
    if request.kind == "screen":
        content: str | list[dict] = look_message(card, request.image or "", context, act, threshold, recent_lines, request.now_saying)
    else:
        content = reply_message(request.text or "", context, act, recent_lines, request.now_saying, request.image)
    return [{"role": "system", "content": build_system_prompt(card)}, {"role": "user", "content": content}]


# Background memory work. Each job runs once at a time, and a failure just tries again next time.
_running: set[str] = set()
_tasks: set[asyncio.Task] = set()
_today = {"at": 0.0, "events": 0}


def run_later(job) -> None:
    try:
        task = asyncio.get_running_loop().create_task(job)
    except RuntimeError:
        job.close()  # No event loop, as in tests: memory work is skipped.
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def ask_model(job: str, messages: list[dict]) -> dict | None:
    if job in _running:
        return None
    _running.add(job)
    try:
        async with httpx.AsyncClient() as client:
            text = await complete(client, messages)
        data = parse_json(text)
        if data is None:
            logger.warning("%s: reply was not usable: %s", job, text[:200])
        return data
    except LLMError as exc:
        logger.warning("%s failed: %s", job, exc)
        return None
    finally:
        _running.discard(job)


async def update_facts() -> None:
    if not store.needs_facts():
        return
    words = list(store.memory.unread_words)
    data = await ask_model("facts", facts_messages(store.memory, words))
    if data and isinstance(data.get("facts"), list):
        store.apply_facts(data["facts"], read=len(words))
        logger.info("facts updated: %s", [f["text"] for f in store.memory.facts])


def maybe_update_today() -> None:
    shown = sum(1 for e in timeline.events if e.kind in (SEEN, HEARD, SAID))
    if time.time() - _today["at"] < TODAY_EVERY_SECONDS and shown - _today["events"] < TODAY_EVERY_EVENTS:
        return
    _today["at"], _today["events"] = time.time(), shown
    run_later(update_today())


async def update_today() -> None:
    text = transcript(timeline.events)
    if not text or not worth_remembering(timeline.events):
        return
    log = timeline.path.name if timeline.path else None
    data = await ask_model("today", today_messages(text))
    if data and isinstance(data.get("today"), str):
        store.set_today(log, data["today"])
        logger.info("today: %s", store.memory.today)


async def wrap_up(path: Path) -> None:
    """Turns a finished session's log into an episode she can remember."""
    if store.has_episode(path.name) or not path.exists():
        return
    events = read_log(path)
    if not worth_remembering(events):
        return
    data = await ask_model(f"episode {path.name}", episode_messages(transcript(events), events[0].t))
    episode = episode_from(data or {}, path.name, events[0].t, events[-1].t)
    if episode and not store.has_episode(path.name):
        store.add_episode(episode)
        store.add_her(episode["her"])
        logger.info("remembered session %s: %s", path.name, episode["title"])


async def wrap_up_old_sessions() -> None:
    """Sessions that ended while the bridge was stopped become memories now."""
    if not SESSIONS_DIR.exists():
        return
    logs = sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in [p for p in logs if p != timeline.path and not store.has_episode(p.name)][:WRAP_UP_AT_START]:
        await wrap_up(path)


timeline.on_session_end = lambda path: run_later(wrap_up(path))


async def turn_lines(request: TurnRequest) -> AsyncIterator[str]:
    started = time.perf_counter()
    since = lambda: round(time.perf_counter() - started, 3)  # noqa: E731
    is_speech = request.kind == "speech"
    source = REPLY if is_speech else SOURCE_OF_REASON.get(request.reason or "", COMMENT)
    # Videos change so much that every look would be a "big moment" and every line a reaction.
    # Soon after a reaction, a big change gets an ordinary comment, which she can also decline.
    said = timeline.said(limit=1)
    if source == MOMENT and said and said[-1].extra.get("act") == "reaction" and time.time() - said[-1].t < MOMENT_SPACING_SECONDS:
        source = COMMENT
    act = pick_act(source)
    threshold = 0 if is_speech else INTEREST_NEEDED[source]
    trace: dict = {"type": "trace", "kind": request.kind, "source": source, "act": act.key}
    out: asyncio.Queue[str | None] = asyncio.Queue()
    to_speak: asyncio.Queue[str | None] = asyncio.Queue()
    # A comment on what she just saw is a repeat. A big change or a lull may still be worth a line.
    previous = None if is_speech or source != COMMENT else timeline.last_seen(STALE_WITHIN_SECONDS, looks_only=True)
    is_stale = (lambda seen: similarity(seen, previous.text) >= SAME_NOTE) if previous else None
    parser: LookParser | ReplyParser = (
        ReplyParser(MIN_SEGMENT_CHARS) if is_speech else LookParser(threshold, MIN_SEGMENT_CHARS, is_stale=is_stale)
    )
    info = StreamInfo()
    spoken: list[str] = []
    if is_speech:
        timeline.add(HEARD, request.text or "", typed=True)
        store.note_words(request.text or "")
        run_later(update_facts())
        maybe_update_today()
    turn_id = pending_turns.start(act=act.key, source=source)
    out.put_nowait(line({"type": "turn", "turn_id": turn_id, "act": act.key}))
    looked = {"seen": False, "declined": False}

    def report_look() -> None:
        """What she saw goes on the timeline whether or not she speaks, so she remembers it."""
        if not isinstance(parser, LookParser):
            return
        if parser.observation and parser.decided and not looked["seen"]:
            looked["seen"] = True
            timeline.add(SEEN, parser.observation, interest=parser.interest)
            out.put_nowait(line({"type": "seen", "text": parser.observation, "interest": parser.interest}))
        if parser.declined and not looked["declined"]:
            looked["declined"] = True
            trace["declined"] = True
            timeline.add(DECLINED, parser.observation or "", interest=parser.interest, needed=threshold)
            out.put_nowait(line({"type": "declined", "interest": parser.interest}))

    def apply(events: ReplyEvents) -> None:
        report_look()
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
            raw: list[str] = []
            async for delta in stream_reply(client, build_messages(request, act, threshold, source), info):
                if "first_token" not in trace:
                    trace["first_token"] = since()
                    out.put_nowait(line({"type": "stage", "stage": "writing"}))
                raw.append(delta)
                apply(parser.feed(delta))
                if parser.finished:
                    break
            apply(parser.finish())
            report_look()
            logger.info("raw reply (%s): %s", act.key, "".join(raw).replace("\n", " | "))
        finally:
            to_speak.put_nowait(None)

    async def speak(client: httpx.AsyncClient) -> None:
        index = 0
        while (text := await to_speak.get()) is not None:
            segment = await synthesize_segment(client, text, request.voice)
            trace.setdefault("first_audio_ready", since())
            pending_turns.add_written(turn_id, text, segment["duration"])
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
            if isinstance(parser, LookParser):
                trace["interest"] = parser.interest
            logger.info("companion turn %s, spoken %s", trace, spoken)
            timeline.add(TURN, **{("turn_kind" if k == "kind" else k): v for k, v in trace.items() if k != "type"})
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


@router.post("/turn")
async def turn(request: TurnRequest) -> StreamingResponse:
    if request.kind == "speech" and not (request.text and request.text.strip()):
        raise HTTPException(status_code=400, detail="a speech turn needs text")
    if request.kind == "screen" and not (request.image and request.image.startswith("data:image/")):
        raise HTTPException(status_code=400, detail="a screen turn needs an image data URL")
    return StreamingResponse(turn_lines(request), media_type="application/x-ndjson")


class NoteRequest(BaseModel):
    image: str  # Data URL of a JPEG frame.


@router.post("/observe")
async def observe(request: NoteRequest) -> dict:
    """A quick look between lines, so she remembers what happened while she was quiet.

    Returns what she noted and how interesting it was, which the browser uses to decide whether
    it's worth a line. A note repeating her last one isn't kept.
    """
    if not request.image.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="a note needs an image data URL")
    context = context_block(timeline.render(), timeline.minutes_together())
    messages = [{"role": "system", "content": build_system_prompt(card)}, {"role": "user", "content": note_message(request.image, context)}]
    try:
        async with httpx.AsyncClient() as client:
            text = await complete(client, messages, max_tokens=NOTE_MAX_TOKENS)
    except LLMError as exc:
        logger.warning("note failed: %s", exc)
        return {"seen": None, "interest": None, "new": False}
    parser = LookParser(threshold=NOTE_NEVER_SPEAKS)
    parser.feed(text)
    parser.finish()
    if not parser.observation:
        return {"seen": None, "interest": None, "new": False, "emotion": None}
    last = timeline.last_seen(STALE_WITHIN_SECONDS)
    new = not (last and similarity(parser.observation, last.text) >= SAME_NOTE)
    if new:
        timeline.add(SEEN, parser.observation, interest=parser.interest, note=True)
        maybe_update_today()
    # Her face can react to what she noticed, even when she says nothing.
    feeling = re.search(rf"{FEELING_LABEL}\s*[:：]\s*(.*)", text)
    emoji = _EMOJI.search(feeling.group(1)) if feeling else None
    emotion = EMOJI_EMOTIONS.get(emoji.group(0)) if emoji else None
    return {"seen": parser.observation, "interest": parser.interest, "new": new, "emotion": emotion}


# Short sounds she makes between lines, made once in her voice and cached.
AIZUCHI = ["🤔ふーん", "😊へえ", "😮おお", "🤭ふふ", "😌うんうん", "😲わっ", "🤔んー", "😆あはは", "😯ほう", "😏ほほう"]
_aizuchi: list[dict] = []
_aizuchi_lock = asyncio.Lock()


@router.get("/aizuchi")
async def aizuchi() -> dict:
    """The clips, with their lip tracks and faces, made on first use."""
    async with _aizuchi_lock:
        if not _aizuchi:
            async with httpx.AsyncClient(timeout=TTS_TIMEOUT) as client:
                for text in AIZUCHI:
                    try:
                        _aizuchi.append(await synthesize_segment(client, text))
                    except TTSError as exc:
                        logger.warning("aizuchi %s failed: %s", text, exc)
    return {"clips": _aizuchi}


@router.post("/commit")
async def commit_turn(request: CommitRequest) -> dict:
    """Remembers the sentences of a reply that were actually heard."""
    turn = pending_turns.commit(request.turn_id)
    if turn and request.spoken:
        written = turn["written"]
        timeline.add(
            SAID,
            "".join(request.spoken),
            act=turn.get("act"),
            source=turn.get("source"),
            seconds=round(sum(written.get(text, 0.0) for text in request.spoken), 2),
            cut=len(request.spoken) < len(written),
        )
        store.seen_now()
        maybe_update_today()
    return {"saved": turn is not None}


@router.post("/session/start")
async def start_session() -> dict:
    """Begins a new session log. The one before it becomes a memory in the background."""
    timeline.new_session()
    return {"log": timeline.path.name if timeline.path else None}


@router.post("/session/end")
async def end_session() -> dict:
    """She was stopped or the page closed: this session becomes a memory now."""
    timeline.end_session()
    return {"ended": True}


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
    """What the LLM is told: the fixed part, and the memories and recent events each turn adds."""
    rendered = timeline.render()
    remembered = memory_text(store.memory, rendered[-400:])
    return {"system": build_system_prompt(card), "turn": context_block(rendered, timeline.minutes_together(), memory=remembered)}


class FactText(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_FACT_CHARS)


@router.get("/memory")
async def get_memory() -> dict:
    memory = store.memory
    now = time.time()
    return {
        "facts": [{"text": f["text"], "source": f["source"]} for f in memory.facts],
        "her": memory.her,
        "episodes": [{"title": e["title"], "summary": e["summary"], "when": when_was(e["start"], now)} for e in memory.episodes],
        "today": memory.today,
    }


@router.delete("/memory")
async def clear_memory() -> dict:
    """Forgets everything, including the session logs she'd make memories from."""
    timeline.on_session_end = None
    timeline.end_session()
    timeline.on_session_end = lambda path: run_later(wrap_up(path))
    store.clear()
    for path in SESSIONS_DIR.glob("*.jsonl") if SESSIONS_DIR.exists() else []:
        path.unlink(missing_ok=True)
    return await get_memory()


@router.post("/memory/facts")
async def add_fact(fact: FactText) -> dict:
    store.add_fact(fact.text)
    return await get_memory()


@router.put("/memory/facts/{index}")
async def edit_fact(index: int, fact: FactText) -> dict:
    if not store.edit_fact(index, fact.text):
        raise HTTPException(status_code=404, detail="no such fact")
    return await get_memory()


@router.delete("/memory/facts/{index}")
async def forget_fact(index: int) -> dict:
    if not store.forget_fact(index):
        raise HTTPException(status_code=404, detail="no such fact")
    return await get_memory()


@router.delete("/memory/her/{index}")
async def forget_her(index: int) -> dict:
    if not store.forget_her(index):
        raise HTTPException(status_code=404, detail="no such memory")
    return await get_memory()


@router.delete("/memory/episodes/{index}")
async def forget_episode(index: int) -> dict:
    if not store.forget_episode(index):
        raise HTTPException(status_code=404, detail="no such memory")
    return await get_memory()
