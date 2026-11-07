"""What she remembers across sessions, saved to companion-data/memory.json.

- facts: about you. From what you say, or written by you in the panel, which she never changes.
- her: things she has said about herself, nicknames and running jokes, so she stays consistent.
- episodes: one summary per past session, from its log in companion-data/sessions/.
- today: a running summary of the current session.

What happened moment to moment is in the timeline (timeline.py). The model updates facts, today and
episodes in the background (see companion.py), so memory never delays a reply.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger("speech-bridge")

MAX_FACTS = 40
MAX_FACT_CHARS = 80
MAX_HER = 15
MAX_EPISODES = 100
MAX_TODAY_CHARS = 200
# What you say is read for facts after this many lines.
FACTS_AFTER_HEARD = 3
# Where a fact came from: you wrote it in the panel, you said it, or she guessed it.
YOU, SAID, GUESS = "you", "said", "guess"
GUESS_MARK = "（たぶん）"


@dataclass
class Memory:
    facts: list[dict] = field(default_factory=list)  # {"text", "source", "added"}
    her: list[str] = field(default_factory=list)
    episodes: list[dict] = field(default_factory=list)  # {"log", "start", "end", "title", "summary", "highlights", "apps"}
    today: str = ""
    today_log: str | None = None
    last_seen: float = 0.0
    unread_words: list[str] = field(default_factory=list)  # Your lines not yet read for facts.


def _fact(text: str, source: str) -> dict:
    return {"text": text.strip()[:MAX_FACT_CHARS], "source": source, "added": time.time()}


def migrate(data: dict, saved_at: float) -> dict:
    """Memory from before sessions and episodes: facts were plain text and one summary covered everything."""
    facts = [f if isinstance(f, dict) else _fact(str(f), SAID) for f in data.get("facts", []) if f]
    episodes = list(data.get("episodes", []))
    if data.get("summary") and not episodes:
        episodes.append(
            {"log": "before-sessions", "start": saved_at, "end": saved_at, "title": "前の記録", "summary": data["summary"], "highlights": [], "apps": []}
        )
    return {**data, "facts": facts, "episodes": episodes}


class MemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.memory = self._load()

    def _load(self) -> Memory:
        if not self.path.exists():
            return Memory()
        try:
            data = migrate(json.loads(self.path.read_text(encoding="utf-8")), self.path.stat().st_mtime)
            return Memory(**{key: data[key] for key in Memory.__dataclass_fields__ if key in data})
        except (OSError, ValueError, TypeError) as exc:
            # Keep the unreadable file for recovery rather than overwriting it on the next save.
            logger.warning("memory file unreadable, starting empty: %s", exc)
            self.path.replace(self.path.with_suffix(".unreadable.json"))
            return Memory()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self.memory), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    # Facts about you

    def note_words(self, text: str) -> None:
        self.memory.unread_words.append(text)
        self.memory.last_seen = time.time()
        self.save()

    def needs_facts(self) -> bool:
        return len(self.memory.unread_words) >= FACTS_AFTER_HEARD

    def apply_facts(self, texts: list, read: int) -> None:
        """Replaces the facts she learned, keeping yours as they are. Drops only the lines that were read."""
        yours = [f for f in self.memory.facts if f["source"] == YOU]
        before = {f["text"]: f for f in self.memory.facts}
        known = {f["text"] for f in yours}
        learned = []
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                continue
            guess = text.strip().startswith(GUESS_MARK)
            fact = _fact(text.strip().removeprefix(GUESS_MARK), GUESS if guess else SAID)
            if fact["text"] in known:
                continue
            # A fact she already had keeps the date she learned it.
            fact["added"] = before.get(fact["text"], fact)["added"]
            learned.append(fact)
            known.add(fact["text"])
        self.memory.facts = (yours + learned)[:MAX_FACTS]
        self.memory.unread_words = self.memory.unread_words[read:]
        self.save()

    def add_fact(self, text: str) -> None:
        self.memory.facts.append(_fact(text, YOU))
        self.memory.facts = self.memory.facts[-MAX_FACTS:]
        self.save()

    def edit_fact(self, index: int, text: str) -> bool:
        """Your edit makes the fact yours, so she won't change it."""
        if not 0 <= index < len(self.memory.facts):
            return False
        self.memory.facts[index] = _fact(text, YOU)
        self.save()
        return True

    def forget_fact(self, index: int) -> bool:
        return self._forget(self.memory.facts, index)

    # Her own bits, episodes and today

    def add_her(self, bits: list) -> None:
        merged = [*self.memory.her, *(b.strip() for b in bits if isinstance(b, str) and b.strip())]
        self.memory.her = list(dict.fromkeys(merged))[-MAX_HER:]
        self.save()

    def forget_her(self, index: int) -> bool:
        return self._forget(self.memory.her, index)

    def has_episode(self, log: str) -> bool:
        return any(e.get("log") == log for e in self.memory.episodes)

    def add_episode(self, episode: dict) -> None:
        self.memory.episodes = [*self.memory.episodes, episode][-MAX_EPISODES:]
        self.memory.episodes.sort(key=lambda e: e.get("start", 0))
        if episode.get("log") == self.memory.today_log:
            self.memory.today, self.memory.today_log = "", None
        self.save()

    def forget_episode(self, index: int) -> bool:
        return self._forget(self.memory.episodes, index)

    def set_today(self, log: str | None, text: str) -> None:
        self.memory.today, self.memory.today_log = text.strip()[:MAX_TODAY_CHARS], log
        self.save()

    def seen_now(self) -> None:
        self.memory.last_seen = time.time()

    def clear(self) -> None:
        self.memory = Memory()
        self.save()

    def _forget(self, items: list, index: int) -> bool:
        if not 0 <= index < len(items):
            return False
        del items[index]
        self.save()
        return True


class PendingTurns:
    """Replies still being prepared or spoken. Only what was actually heard gets remembered.

    She prepares lines she may never say, so a turn is saved by commit(), with the sentences that
    played. A line that was thrown away just ages out of here.
    """

    LIMIT = 8

    def __init__(self) -> None:
        self._turns: OrderedDict[str, dict] = OrderedDict()

    def start(self, **details) -> str:
        """details: anything to keep with the turn until it's committed, such as its act."""
        turn_id = uuid.uuid4().hex
        self._turns[turn_id] = {"written": {}, **details}
        while len(self._turns) > self.LIMIT:
            self._turns.popitem(last=False)
        return turn_id

    def add_written(self, turn_id: str, text: str, seconds: float) -> None:
        """A sentence that was synthesized, and how long it lasts."""
        if turn_id in self._turns:
            self._turns[turn_id]["written"][text] = seconds

    def commit(self, turn_id: str) -> dict | None:
        """Takes a turn once. None if it's unknown, which includes a turn committed already."""
        return self._turns.pop(turn_id, None)


def parse_json(text: str) -> dict | None:
    """Reads a model's JSON object, tolerating code fences. None if it isn't usable."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
