"""Everything that happened, in order: what she saw, what you said, and what she said.

Prompts show her the recent part, memory is built from it, and each session is written to
companion-data/sessions/<start>.jsonl for the tuning report. Text only: no images or audio.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger("speech-bridge")

# Kinds shown to the model. "turn" (timings and cost) and "declined" are for the report only.
SEEN, HEARD, SAID, DECLINED, TURN, SESSION = "seen", "heard", "said", "declined", "turn", "session"
RECENT_SECONDS = 360
RECENT_LIMIT = 30
# A gap this long starts a new session.
SESSION_GAP_SECONDS = 15 * 60


@dataclass
class Event:
    kind: str
    text: str = ""
    t: float = field(default_factory=time.time)
    extra: dict = field(default_factory=dict)


# Two notes this alike describe the same thing.
SAME_NOTE = 0.6


def similarity(a: str, b: str) -> float:
    """Shared character pairs, which works for Japanese without word splitting. 1 means the same."""
    pairs = lambda text: {text[i : i + 2] for i in range(len(text) - 1)}  # noqa: E731
    x, y = pairs(a), pairs(b)
    return len(x & y) / len(x | y) if x and y else float(a == b)


def ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 3:
        return "たった今"
    if seconds < 60:
        return f"{seconds}秒前"
    if seconds < 3600:
        return f"{seconds // 60}分前"
    return f"{seconds // 3600}時間前"


def render_event(event: Event, now: float) -> str | None:
    when = ago(now - event.t)
    if event.kind == SEEN:
        return f"- {when} 見た: {event.text}"
    if event.kind == HEARD:
        return f"- {when} きみ: 「{event.text}」"
    if event.kind == SAID:
        cut = "（途中で止めた）" if event.extra.get("cut") else ""
        return f"- {when} あなた: 「{event.text}」{cut}"
    return None


def read_log(path: Path) -> list[Event]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            data = json.loads(line)
            events.append(Event(data["kind"], data.get("text", ""), data["t"], data.get("extra") or {}))
        except (ValueError, KeyError, TypeError):
            continue  # A line cut short when the bridge stopped.
    return events


class Timeline:
    def __init__(self, folder: Path | None) -> None:
        self.folder = folder
        self.events: list[Event] = []
        self.session_start = 0.0
        self.path: Path | None = None
        # Called with a session's log once it's over, to make it into a memory.
        self.on_session_end: Callable[[Path], None] | None = None

    def new_session(self) -> None:
        """Starts a fresh session now, even if the last one was recent."""
        self.end_session()
        self._ensure_session(time.time())

    def end_session(self) -> None:
        if self.events and self.path is not None and self.on_session_end:
            self.on_session_end(self.path)
        self.events = []

    def _ensure_session(self, now: float) -> None:
        if self.events and now - self.events[-1].t < SESSION_GAP_SECONDS:
            return
        self.end_session()
        self.session_start = now
        if self.folder is not None:
            stamp = time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime(now))
            self.path = self.folder / f"{stamp}.jsonl"
            count = 2
            while self.path.exists():  # Two sessions within a second, as in tests and replays.
                self.path = self.folder / f"{stamp}-{count}.jsonl"
                count += 1
        self._append(Event(SESSION, "start", now))

    def add(self, kind: str, text: str = "", **extra) -> Event:
        now = time.time()
        self._ensure_session(now)
        event = Event(kind, text, now, extra)
        self._append(event)
        return event

    def _append(self, event: Event) -> None:
        self.events.append(event)
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("could not write the session log: %s", exc)

    def recent(self, now: float | None = None, seconds: float = RECENT_SECONDS, limit: int = RECENT_LIMIT) -> list[Event]:
        now = time.time() if now is None else now
        shown = [e for e in self.events if e.kind in (SEEN, HEARD, SAID) and now - e.t <= seconds]
        return shown[-limit:]

    def render(self, now: float | None = None) -> str:
        """The recent events, with a note repeating the one before it shown once, at its latest time."""
        now = time.time() if now is None else now
        shown: list[Event] = []
        for event in self.recent(now):
            last_seen = next((e for e in reversed(shown) if e.kind == SEEN), None)
            if event.kind == SEEN and shown and shown[-1].kind == SEEN and last_seen and similarity(event.text, last_seen.text) >= SAME_NOTE:
                shown[-1] = event
                continue
            shown.append(event)
        return "\n".join(line for e in shown if (line := render_event(e, now)))

    def last_seen(self, within: float, now: float | None = None) -> Event | None:
        now = time.time() if now is None else now
        return next((e for e in reversed(self.events) if e.kind == SEEN and now - e.t <= within), None)

    def said(self, limit: int = 3) -> list[Event]:
        return [e for e in self.events if e.kind == SAID][-limit:]

    def minutes_together(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        return int((now - self.session_start) // 60) if self.events else 0
