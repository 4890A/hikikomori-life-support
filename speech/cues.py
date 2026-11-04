"""Text side of the speech pipeline: emoji parsing, segmentation and expression cue timing.

No audio or ML dependencies, so the timing rules can be unit tested on their own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Irodori's emoji (see Irodori-TTS/irodori_tts/gradio_emoji_palette.py) plus common extras, mapped
# to emotion names defined in web/src/anim/emotions.ts. Emoji that only change the voice (echo,
# phone filter, speed, pause, mouth noises...) have no facial equivalent and stay unmapped.
EMOJI_EMOTIONS: dict[str, str] = {
    "😊": "happy", "🤭": "happy", "😌": "happy", "🎵": "happy",
    "😄": "happy", "😃": "happy", "😁": "happy", "🙂": "happy", "☺️": "happy", "😋": "happy",
    "😆": "excited", "💪": "excited", "💥": "excited", "🤩": "excited", "🎉": "excited",
    "🫣": "embarrassed", "😅": "embarrassed", "😳": "flushed",
    "🥺": "flushed", "🥵": "flushed", "🌬️": "flushed",
    "😏": "smug", "😎": "smug", "🙄": "smug",
    "😠": "pout", "😒": "pout", "😡": "pout", "😤": "pout",
    "😭": "sad", "😢": "sad", "😔": "sad",
    "😲": "surprised", "😮": "surprised", "😱": "surprised", "😯": "surprised",
    "😰": "worried", "😨": "worried", "😟": "worried", "😖": "worried", "🙏": "worried", "😥": "worried",
    "😮‍💨": "sigh",
    "😪": "sleepy", "🥱": "sleepy", "😴": "sleepy",
    "🫶": "love", "🥰": "love", "😍": "love", "❤️": "love",
    "🤔": "thinking",
    "🥴": "dizzy", "😵‍💫": "dizzy", "😵": "dizzy",
}

# Emotions whose arm pose is part of the expression. An arm transition takes over a second, so
# it only plays when the cue lasts long enough to be seen. (Smug's foxtail never fits speech.)
ARM_EMOTIONS = frozenset({"thinking", "embarrassed", "love"})
MIN_ARM_SECONDS = 1.6

SENTENCE_END = frozenset("。．.!！?？\n\r")
CLAUSE_BREAK = frozenset("、，,")
PUNCTUATION = SENTENCE_END | CLAUSE_BREAK | frozenset("…‥・「」『』（）()【】[]\"'”“’‘ 　\t~〜ー―—-")

MAX_SEGMENT_CHARS = 60
MIN_TAIL_CHARS = 12
TAIL_MERGE_CHARS = 75

_EMOJI = re.compile(
    "(?:[\U0001F000-\U0001FAFF☀-➿⬀-⯿⏩-⏺⌀-⏿]"
    "(?:[\U0001F3FB-\U0001F3FF]|️)?"
    "(?:‍[\U0001F000-\U0001FAFF☀-➿⬀-⯿](?:️)?)*)"
)


@dataclass
class Fragment:
    """Speakable text between emoji/punctuation. Times are filled in by alignment."""

    text: str
    phones: list[str] = field(default_factory=list)
    start: float = 0.0
    end: float = 0.0


@dataclass
class Emoji:
    char: str

    @property
    def emotion(self) -> str | None:
        return EMOJI_EMOTIONS.get(self.char) or EMOJI_EMOTIONS.get(self.char.replace("️", ""))


@dataclass
class Punct:
    char: str

    @property
    def ends_sentence(self) -> bool:
        return any(c in SENTENCE_END for c in self.char)


Item = Fragment | Emoji | Punct


@dataclass
class Cue:
    start: float
    end: float
    emotion: str
    emoji: str
    kind: str  # "trailing" (colors the clause before it) or "leading" (starts here)

    def as_dict(self) -> dict:
        return {
            "start": round(float(self.start), 3),
            "end": round(float(self.end), 3),
            "emotion": self.emotion,
            "emoji": self.emoji,
            "kind": self.kind,
            "arms": bool(self.emotion in ARM_EMOTIONS and self.end - self.start >= MIN_ARM_SECONDS),
        }


def parse_items(text: str) -> list[Item]:
    """Splits text into speakable fragments, emoji and punctuation, in order."""
    items: list[Item] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            items.append(Fragment("".join(buffer)))
            buffer.clear()

    pos = 0
    while pos < len(text):
        match = _EMOJI.match(text, pos)
        if match:
            flush()
            items.append(Emoji(match.group(0)))
            pos = match.end()
            continue
        char = text[pos]
        # "ー" is a long vowel inside words, only punctuation when it stands alone.
        is_long_vowel = char in "ー〜~" and bool(buffer)
        if char in PUNCTUATION and not is_long_vowel:
            flush()
            items.append(Punct(char))
        else:
            buffer.append(char)
        pos += 1
    flush()
    return items


def _spoken_length(text: str) -> int:
    return sum(1 for item in parse_items(text) if isinstance(item, Fragment) for _ in item.text)


def _split_at(text: str, boundaries: frozenset[str]) -> list[str]:
    """Splits after boundary chars, keeping following emoji and punctuation with what precedes."""
    parts: list[str] = []
    start = pos = 0
    while pos < len(text):
        match = _EMOJI.match(text, pos)
        if match:
            pos = match.end()
            continue
        is_boundary = text[pos] in boundaries
        pos += 1
        if not is_boundary:
            continue
        while pos < len(text):
            match = _EMOJI.match(text, pos)
            if match:
                pos = match.end()
            elif text[pos] in PUNCTUATION and text[pos] not in "ー〜~「『（(【[":
                pos += 1
            else:
                break
        parts.append(text[start:pos])
        start = pos
    if start < len(text):
        parts.append(text[start:])
    return [p for p in parts if p.strip()]


def split_segments(text: str) -> list[str]:
    """Groups text into segments for separate synthesis.

    Whole-text synthesis sounds best, but the server caps one synthesis at 30 seconds, and very
    short inputs get an overestimated duration filled with silence and hallucinated sounds. So:
    split only at sentence ends (commas only for over-long sentences) and avoid short segments.
    """
    sentences: list[str] = []
    for sentence in _split_at(text.strip(), SENTENCE_END):
        if _spoken_length(sentence) > MAX_SEGMENT_CHARS:
            sentences.extend(_split_at(sentence, CLAUSE_BREAK))
        else:
            sentences.append(sentence)

    segments: list[str] = []
    for sentence in sentences:
        if segments and _spoken_length(segments[-1] + sentence) <= MAX_SEGMENT_CHARS:
            segments[-1] += sentence
        else:
            segments.append(sentence)
    if len(segments) > 1 and _spoken_length(segments[-1]) < MIN_TAIL_CHARS:
        if _spoken_length(segments[-2] + segments[-1]) <= TAIL_MERGE_CHARS:
            segments[-2:] = [segments[-2] + segments[-1]]
    return [s.strip() for s in segments if s.strip()]


# Short sentences are merged with the next one: see split_segments on very short inputs.
MIN_STREAM_SEGMENT_CHARS = 8
# A runaway or repeating LLM reply stops being spoken past this length.
MAX_SPOKEN_CHARS = 80
SUMMARY_MAX_CHARS = 40
SUMMARY_LABEL_TEXT = "状況"
_SUMMARY_LABEL = re.compile(r"^[^\]\n]*?\]\]\s*")
_SPEAKABLE = re.compile(r"[0-9!?.,~\-()\"'\u3000-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uFF00-\uFFEF]")


def clean_spoken(text: str) -> str:
    """Keeps only what TTS can say: drops broken emoji joiners, other scripts and whitespace."""
    kept: list[str] = []
    pos = 0
    while pos < len(text):
        match = _EMOJI.match(text, pos)
        if match:
            kept.append(match.group(0))
            pos = match.end()
            continue
        if _SPEAKABLE.fullmatch(text[pos]) and text[pos] != "\u3000":
            kept.append(text[pos])
        pos += 1
    return "".join(kept)


def _split_trailing_emoji(text: str) -> tuple[str, str]:
    """Separates a run of emoji at the very end of text from what comes before it."""
    end = len(text)
    start = end
    for match in reversed(list(_EMOJI.finditer(text))):
        if match.end() != start:
            break
        start = match.start()
    return text[:start], text[start:end]


class StreamSegmenter:
    """Cuts streamed text into segments as soon as each sentence and its trailing emoji are complete."""

    def __init__(self) -> None:
        self._buffer = ""
        self._pending = ""

    def feed(self, delta: str) -> list[str]:
        self._buffer += delta
        parts = _split_at(self._buffer, SENTENCE_END)
        if len(parts) < 2:
            return []
        self._buffer = parts[-1]
        segments: list[str] = []
        for sentence in parts[:-1]:
            self._pending += sentence
            if _spoken_length(self._pending) >= MIN_STREAM_SEGMENT_CHARS:
                # More text follows, so an emoji after the punctuation opens that text ("…！🤭次は").
                body, opener = _split_trailing_emoji(self._pending)
                segments.extend(split_segments(body))
                self._pending = opener
        return segments

    def flush(self) -> list[str]:
        rest = self._pending + self._buffer
        self._pending = self._buffer = ""
        return split_segments(rest) if rest.strip() else []


@dataclass
class ReplyEvents:
    emoji: Emoji | None = None
    segments: list[str] = field(default_factory=list)


class ReplyParser:
    """Turns raw LLM deltas into the expression to show and the clean segments to synthesize.

    Everything from "[[" on is the game summary and is never spoken. Replies stop early when a
    sentence repeats or the length cap is reached, because cheap models sometimes loop.
    """

    def __init__(self) -> None:
        self._segmenter = StreamSegmenter()
        self._spoken_raw = ""
        self._summary_raw: str | None = None
        self._held = ""
        self._emoji_checked = False
        self._seen: set[str] = set()
        self._spoken_chars = 0
        self.finished = False

    def feed(self, delta: str) -> ReplyEvents:
        if self.finished:
            return ReplyEvents()
        return self._events(self._split_summary(delta), final=False)

    def finish(self) -> ReplyEvents:
        if self.finished:
            return ReplyEvents()
        events = self._events(self._held, final=True)
        self._held = ""
        self.finished = True
        return events

    @property
    def summary(self) -> str | None:
        if self._summary_raw is None:
            return None
        raw = self._summary_raw.strip()
        lines = [line.strip() for line in _SUMMARY_LABEL.sub("", raw).splitlines() if line.strip()]
        if not lines:
            # Some models write the summary itself inside the brackets: [[リーチがかかってる]]
            label = raw.replace("]]", "").strip()
            if not label or label == SUMMARY_LABEL_TEXT:
                return None
            lines = [label]
        # A looping reply continues with its next emoji, and only the first summary counts.
        match = _EMOJI.search(lines[0])
        first = lines[0][: match.start()] if match else lines[0]
        return first.replace("]]", "").strip()[:SUMMARY_MAX_CHARS] or None

    def _split_summary(self, delta: str) -> str:
        if self._summary_raw is not None:
            self._summary_raw += delta
            return ""
        text = self._held + delta
        self._held = ""
        start = text.find("[[")
        if start >= 0:
            self._summary_raw = text[start + 2 :]
            return text[:start]
        if text.endswith("["):
            self._held = "["
            return text[:-1]
        return text

    def _events(self, spoken: str, final: bool) -> ReplyEvents:
        events = ReplyEvents()
        self._spoken_raw += spoken
        if not self._emoji_checked:
            events.emoji = self._leading_emoji(final)
        raw_segments = self._segmenter.feed(spoken)
        # Once the summary starts, nothing more will be spoken, so don't wait for it to finish.
        if final or self._summary_raw is not None:
            raw_segments += self._segmenter.flush()
        for segment in raw_segments:
            cleaned = clean_spoken(segment)
            length = _spoken_length(cleaned)
            if length == 0:
                continue
            if cleaned in self._seen or self._spoken_chars >= MAX_SPOKEN_CHARS:
                self.finished = True
                break
            self._seen.add(cleaned)
            self._spoken_chars += length
            events.segments.append(cleaned)
        return events

    def _leading_emoji(self, final: bool) -> Emoji | None:
        text = self._spoken_raw.lstrip()
        if not text:
            return None
        match = _EMOJI.match(text)
        # An emoji at the very end of the buffer may still be extended by the next delta (😮 + ‍💨).
        if match and match.end() == len(text) and not final:
            return None
        self._emoji_checked = True
        if not match:
            return None
        emoji = Emoji(match.group(0))
        return emoji if emoji.emotion is not None else None

def _first_onset(spans: list[tuple[float, float]], after: float, before: float) -> float | None:
    """Start of the first voiced span beginning inside (after, before)."""
    for start, _ in spans:
        if after < start < before:
            return start
    return None


def _neighbor(items: list[Item], index: int, step: int) -> Item | None:
    """Nearest non-emoji item in a direction, so adjacent emoji are classified alike."""
    i = index + step
    while 0 <= i < len(items):
        if not isinstance(items[i], Emoji):
            return items[i]
        i += step
    return None


def _follows_opening_emoji(items: list[Item], index: int) -> bool:
    """True when an earlier expression emoji in this sentence opened the text before this one.

    That text already has its expression ("😟あらら、お疲れさま😮‍💨大変だね"), so this emoji starts
    the next part instead of overwriting it.
    """
    for i in range(index - 1, -1, -1):
        other = items[i]
        if isinstance(other, Punct) and other.ends_sentence:
            return False
        if isinstance(other, Emoji) and other.emotion is not None:
            return not isinstance(_neighbor(items, i, -1), Fragment) and isinstance(_neighbor(items, i, 1), Fragment)
    return False


def build_cues(items: list[Item], spans: list[tuple[float, float]], duration: float) -> list[Cue]:
    """Turns aligned items into expression cues.

    An emoji directly after text colors that text ("楽しかったよ😊"): its cue runs from the start of
    the sentence (or the previous expression) until speech resumes. An emoji after punctuation
    and before text ("…😮‍💨まぁ") starts something new: its cue begins at the sound the model
    performs in the gap (a sigh, a laugh), or at the next speech, and runs to the sentence end.
    So does an emoji after text that an earlier emoji already opened.
    """
    frags = [i for i, item in enumerate(items) if isinstance(item, Fragment) and item.phones]
    cues: list[Cue] = []

    for index, item in enumerate(items):
        if not isinstance(item, Emoji) or item.emotion is None:
            continue
        before = [i for i in frags if i < index]
        after = [i for i in frags if i > index]
        prev_item = _neighbor(items, index, -1)
        next_item = _neighbor(items, index, 1)

        if not frags:
            cues.append(Cue(0.0, duration, item.emotion, item.char, "leading"))
        elif (not isinstance(prev_item, Fragment) and isinstance(next_item, Fragment)) or (
            after and _follows_opening_emoji(items, index)
        ):
            first = items[after[0]]
            gap_start = items[before[-1]].end if before else 0.0
            start = _first_onset(spans, gap_start, first.start)
            last = after[0]
            for i in range(after[0] + 1, len(items)):
                other = items[i]
                if isinstance(other, Punct) and other.ends_sentence:
                    break
                if isinstance(other, Emoji) and other.emotion is not None:
                    break
                if isinstance(other, Fragment) and other.phones:
                    last = i
            cues.append(Cue(start if start is not None else first.start, min(duration, items[last].end + 0.5),
                            item.emotion, item.char, "leading"))
        elif before:
            anchor = before[-1]
            first = anchor
            for i in range(anchor - 1, -1, -1):
                other = items[i]
                if isinstance(other, Punct) and other.ends_sentence:
                    break
                if isinstance(other, Emoji) and other.emotion is not None:
                    break
                if isinstance(other, Fragment) and other.phones:
                    first = i
            previous = [i for i in frags if i < first]
            gap_start = items[previous[-1]].end if previous else 0.0
            onset = _first_onset(spans, gap_start, items[first].start)
            start = onset if onset is not None else items[first].start
            end = items[anchor].end + 1.2
            if after:
                end = min(end, items[after[0]].start)
            cues.append(Cue(start, min(duration, end), item.emotion, item.char, "trailing"))
        else:
            # Emoji at the very start with no directly following text ("😊、はい").
            first = items[after[0]]
            cues.append(Cue(0.0, first.end, item.emotion, item.char, "leading"))

    return _resolve_overlaps(cues)


def _resolve_overlaps(cues: list[Cue]) -> list[Cue]:
    """Later cues win. Too-short leftovers are dropped; neighbors with one emotion are joined."""
    cues = sorted(cues, key=lambda c: c.start)
    for earlier, later in zip(cues, cues[1:]):
        earlier.end = min(earlier.end, later.start)
    merged: list[Cue] = []
    for cue in cues:
        if cue.end - cue.start < 0.15:
            continue
        if merged and merged[-1].emotion == cue.emotion and cue.start - merged[-1].end < 0.3:
            merged[-1].end = cue.end
        else:
            merged.append(cue)
    return merged
