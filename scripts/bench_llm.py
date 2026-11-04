"""Compares cheap OpenRouter models for the companion: latency, cost and whether replies follow the rules.

Speech turns are text only. Screen turns run once per image in .scratch/mahjong/ and are skipped
when there are no images. Run through scripts/bench-llm.ps1. Results go to .scratch/bench-llm/.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import statistics
import time
from pathlib import Path

import httpx
from PIL import Image

from cues import EMOJI_EMOTIONS, SENTENCE_END, _EMOJI, _spoken_length
from llm import MAX_REPLY_CHARS, MIN_REPLY_CHARS, SCREEN_RULE, SUMMARY_MARKER, SYSTEM_PROMPT, request_body

ROOT = Path(__file__).resolve().parent.parent
URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODELS = [
    "deepseek/deepseek-v4.1-flash",
    "qwen/qwen3.7-flash",
    "z-ai/glm-5.3-flash",
    "openai/gpt-5-nano",
    "google/gemini-2.5-flash-lite",
]
RATE_LIMIT_RETRY_SECONDS = 1.0
IMAGE_WIDTH = 768
TURNS_PER_HOUR = 300  # One comment every 12 seconds.

SPEECH_TURNS = [
    "やばい、親にリーチかけられた。どうしよう？",
    "よっしゃ、やっとあがれた！",
    "今の切り方、下手だったかな？",
    "もう三連続でラスなんだけど、つらい。",
]
SPEECH_CONTEXT = "直前の画面の状況: 南三局、プレイヤーは二着。\nプレイヤーの発言: "


def load_image(path: Path) -> str:
    """Encodes a screenshot the way the browser will send it: about 768 px wide, JPEG."""
    image = Image.open(path).convert("RGB")
    if image.width > IMAGE_WIDTH:
        image = image.resize((IMAGE_WIDTH, round(image.height * IMAGE_WIDTH / image.width)))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def build_turns(image_dir: Path) -> list[dict]:
    turns = [{"kind": "speech", "name": f"speech{i}", "content": SPEECH_CONTEXT + text} for i, text in enumerate(SPEECH_TURNS)]
    if image_dir.is_dir():
        for path in sorted(p for p in image_dir.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}):
            content = [{"type": "text", "text": SCREEN_RULE}, {"type": "image_url", "image_url": {"url": load_image(path)}}]
            turns.append({"kind": "screen", "name": path.stem, "content": content})
    return turns


def check_reply(text: str) -> dict:
    """Checks only the spoken part: what the summary marker leaves out never reaches TTS."""
    spoken = text.split(SUMMARY_MARKER)[0].strip()
    match = _EMOJI.match(spoken)
    emoji = match.group(0) if match else None
    length = _spoken_length(spoken)
    return {
        "spoken": spoken,
        "starts_with_allowed_emoji": emoji is not None and (emoji in EMOJI_EMOTIONS or emoji.replace("️", "") in EMOJI_EMOTIONS),
        "length": length,
        "length_ok": MIN_REPLY_CHARS <= length <= MAX_REPLY_CHARS,
        "no_latin": not any(c.isascii() and c.isalpha() for c in spoken),
        "has_summary": SUMMARY_MARKER in text,
    }


def run_turn(client: httpx.Client, key: str, model: str, turn: dict) -> dict:
    # The same request the bridge sends, so the benchmark tests what actually runs.
    body = request_body(model, [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": turn["content"]}])
    started = time.perf_counter()
    first_token = first_sentence = None
    text = ""
    usage: dict = {}
    served_by = None
    with client.stream("POST", URL, json=body, headers={"Authorization": f"Bearer {key}"}) as response:
        if response.status_code != 200:
            return {"error": f"HTTP {response.status_code}: {response.read().decode('utf-8', 'replace')[:300]}"}
        for line in response.iter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            chunk = json.loads(line[6:])
            if "error" in chunk:
                return {"error": str(chunk["error"])[:300]}
            served_by = chunk.get("provider", served_by)
            usage = chunk.get("usage") or usage
            choices = chunk.get("choices") or [{}]
            delta = (choices[0].get("delta") or {}).get("content") or ""
            if not delta:
                continue
            now = time.perf_counter() - started
            first_token = first_token if first_token is not None else now
            text += delta
            if first_sentence is None and any(c in SENTENCE_END for c in text):
                first_sentence = now
    total = time.perf_counter() - started
    if first_token is None:
        return {"error": "stream had no content"}
    details = usage.get("completion_tokens_details") or {}
    return {
        "first_token": first_token,
        "first_sentence": first_sentence if first_sentence is not None else total,
        "total": total,
        "text": text,
        "cost": usage.get("cost"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "provider": served_by,
        **check_reply(text),
    }


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def summarize(runs: list[dict]) -> dict | None:
    good = [r for r in runs if "error" not in r]
    if not good:
        return None
    costs = [r["cost"] for r in good if r["cost"] is not None]
    rate = lambda key: sum(bool(r[key]) for r in good) / len(good)  # noqa: E731
    return {
        "runs": len(good),
        "errors": len(runs) - len(good),
        "first_token_p50": percentile([r["first_token"] for r in good], 0.5),
        "first_token_p90": percentile([r["first_token"] for r in good], 0.9),
        "first_sentence_p50": percentile([r["first_sentence"] for r in good], 0.5),
        "first_sentence_p90": percentile([r["first_sentence"] for r in good], 0.9),
        "emoji_ok": rate("starts_with_allowed_emoji"),
        "length_ok": rate("length_ok"),
        "no_latin": rate("no_latin"),
        "summary_ok": rate("has_summary"),
        "mean_cost": statistics.fmean(costs) if costs else None,
        "reasoning_tokens_max": max((r["reasoning_tokens"] or 0) for r in good),
        "providers": sorted({r["provider"] for r in good if r["provider"]}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--images", type=Path, default=ROOT / ".scratch" / "mahjong")
    args = parser.parse_args()

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is not set")

    turns = build_turns(args.images)
    runs: dict[str, dict[str, list[dict]]] = {m: {"speech": [], "screen": []} for m in args.models}
    with httpx.Client(timeout=httpx.Timeout(60.0)) as client:
        # Round-robin, so a slow moment on the network doesn't land on one model only.
        for _ in range(args.repeats):
            for turn in turns:
                for model in args.models:
                    try:
                        result = run_turn(client, key, model, turn)
                        rate_limited = result.get("error", "").startswith("HTTP 429")
                        if rate_limited:
                            time.sleep(RATE_LIMIT_RETRY_SECONDS)
                            result = run_turn(client, key, model, turn)
                        result["rate_limited"] = rate_limited
                    except httpx.HTTPError as exc:
                        result = {"error": f"{type(exc).__name__}: {exc}"}
                    runs[model][turn["kind"]].append({"turn": turn["name"], **result})

    output = ROOT / ".scratch" / "bench-llm"
    output.mkdir(parents=True, exist_ok=True)
    summary = {m: {kind: summarize(r) for kind, r in by_kind.items()} for m, by_kind in runs.items()}
    (output / "results.json").write_text(json.dumps({"summary": summary, "runs": runs}, indent=2, ensure_ascii=False), encoding="utf-8")

    total_cost = sum(r.get("cost") or 0 for by_kind in runs.values() for rs in by_kind.values() for r in rs)
    for kind in ("speech", "screen"):
        print(f"\n{kind} turns")
        print(f"{'model':34}{'token p50':>10}{'token p90':>10}{'sent p50':>10}{'sent p90':>10}{'emoji':>7}{'len':>6}{'JP':>6}{'sum':>6}{'$/hr':>8}{'err':>5}")
        for model in args.models:
            s = summary[model][kind]
            if s is None:
                errors = [r["error"] for r in runs[model][kind] if "error" in r]
                print(f"{model:34}{'no results' if not errors else 'all failed: ' + errors[0][:90]}")
                continue
            hourly = f"{s['mean_cost'] * TURNS_PER_HOUR:.3f}" if s["mean_cost"] is not None else "?"
            print(
                f"{model:34}{s['first_token_p50']:>9.2f}s{s['first_token_p90']:>9.2f}s{s['first_sentence_p50']:>9.2f}s{s['first_sentence_p90']:>9.2f}s"
                f"{s['emoji_ok']:>7.0%}{s['length_ok']:>6.0%}{s['no_latin']:>6.0%}{s['summary_ok']:>6.0%}{hourly:>8}{s['errors']:>5}"
            )

    print("\nsample replies")
    for model in args.models:
        print(f"-- {model}")
        for r in [r for rs in runs[model].values() for r in rs if "error" not in r][:4]:
            print(f"   {r['first_token']:.2f}s {r['text'].strip()!r}")
    print("\nrate limited (retried once):", {m: sum(bool(r.get("rate_limited")) for rs in by_kind.values() for r in rs) for m, by_kind in runs.items()})
    print(f"\nbenchmark cost: ${total_cost:.4f}. Full results: {output / 'results.json'}")


if __name__ == "__main__":
    main()
