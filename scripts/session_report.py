"""How a companion session went, from its log in companion-data/sessions/, for tuning.

    uv run --no-sync python scripts/session_report.py              the latest session
    uv run --no-sync python scripts/session_report.py FILE --transcript
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

SESSIONS = Path(__file__).resolve().parent.parent / "companion-data" / "sessions"
_EMOJI_START = re.compile(r"^[\U0001F000-\U0001FAFF☀-➿‍️]+")


def bigrams(text: str) -> set[str]:
    text = re.sub(r"[\W_]+", "", text)
    return {text[i : i + 2] for i in range(len(text) - 1)}


def similar(a: str, b: str) -> float:
    x, y = bigrams(a), bigrams(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def median(values: list[float]) -> str:
    return f"{statistics.median(values):.2f}" if values else "-"


def report(path: Path, transcript: bool) -> None:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(events) < 2:
        print(f"{path.name}: nothing happened")
        return
    span = max(events[-1]["t"] - events[0]["t"], 1e-9)
    minutes = max(span / 60, 1e-9)
    said = [e for e in events if e["kind"] == "said"]
    turns = [e for e in events if e["kind"] == "turn"]
    talk = sum(e["extra"].get("seconds", 0) for e in said)
    gaps = []
    for before, after in zip(said, said[1:]):
        gaps.append(after["t"] - after["extra"].get("seconds", 0) - before["t"])
    openings = [m.group(0) if (m := _EMOJI_START.match(e["text"])) else "" for e in said]
    repeats = sum(1 for a, b in zip(said, said[1:]) if similar(a["text"], b["text"]) > 0.5)
    same_opening = sum(1 for a, b in zip(openings, openings[1:]) if a and a == b)
    cost = sum(t["extra"].get("cost") or 0 for t in turns)
    by_source: dict[str, list[float]] = {}
    for t in turns:
        if "first_audio_ready" in t["extra"]:
            by_source.setdefault(t["extra"].get("source", "?"), []).append(t["extra"]["first_audio_ready"])

    print(f"{path.name}: {minutes:.1f} min")
    print(f"  her talk time      {100 * talk / span:.0f}% ({talk:.0f} s)")
    print(f"  lines              {len(said)} ({len(said) / minutes:.1f} a minute), {sum(1 for e in said if e['extra'].get('cut'))} cut short")
    print(f"  gap between lines  median {median(gaps)} s, shortest {min(gaps):.1f} s" if gaps else "  gap between lines  -")
    print(f"  acts               {dict(Counter(e['extra'].get('act') or '?' for e in said).most_common())}")
    print(f"  stayed quiet       {sum(1 for e in events if e['kind'] == 'declined')} times ({sum(1 for e in events if e['kind'] == 'declined') / minutes:.1f} a minute)")
    print(f"  your words         {sum(1 for e in events if e['kind'] == 'heard')}")
    print(f"  repeats            {repeats} similar lines back to back, {same_opening} same opening emoji back to back")
    print(f"  first audio        " + ", ".join(f"{k} {median(v)} s (n={len(v)})" for k, v in by_source.items()))
    print(f"  cost               ${cost:.4f} (${cost / minutes * 60:.3f} an hour)")
    if transcript:
        start = events[0]["t"]
        for e in events:
            if e["kind"] in ("seen", "heard", "said", "declined"):
                extra = e["extra"]
                note = f" [{extra.get('act')}]" if e["kind"] == "said" else f" [{extra.get('interest')}]" if e["kind"] in ("seen", "declined") else ""
                print(f"  {e['t'] - start:7.1f}s {e['kind']:8} {e['text']}{note}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", nargs="?", type=Path)
    parser.add_argument("--transcript", action="store_true", help="also list what she saw, heard and said")
    args = parser.parse_args()
    path = args.file or max(SESSIONS.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, default=None)
    if path is None:
        raise SystemExit(f"no sessions in {SESSIONS}")
    report(path, args.transcript)


if __name__ == "__main__":
    main()
