"""Measures Irodori-TTS plus lip alignment latency against a running TTS server.

Run scripts/start-tts.ps1 first, then scripts/bench-tts.ps1 -Label <name>. Results and audio for
listening go to .scratch/bench/<label>/. The first request for each line only warms the server up
and is left out of the statistics.
"""

from __future__ import annotations

import argparse
import io
import json
import statistics
import subprocess
import time
from pathlib import Path

import httpx
import soundfile as sf

from synthesis import DEFAULT_VOICE, process_segment

ROOT = Path(__file__).resolve().parent.parent
GATE_SECONDS = 0.7
GATE_BUCKET = "medium"

LINES: dict[str, list[str]] = {
    "short": ["😲えっ、リーチ！", "おっ、来たね😊", "😏ふふん、どう？"],
    "medium": [
        "😲えっ、もうリーチなの？ちょっと早すぎない？",
        "😆やった、ツモだ！今の手はすごく良かったよ！",
        "🤔うーん、その牌を切るのは少し怖いかも。",
    ],
    "long": [
        "😊今の局はすごくいい流れだったね。最初は危ないかなと思ったけど、最後にしっかりあがれて本当によかったよ。",
        "😰ちょっと待って、親のリーチがかかってるのに、その牌を切っちゃうの？さすがに危ないと思うんだけど、大丈夫かな。",
    ],
}


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile; with few samples, p90 is close to the slowest run."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def vram_used_mib() -> int | None:
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return int(output.splitlines()[0].strip())


def parse_option(option: str) -> tuple[str, object]:
    """Parses KEY=VALUE from --set, keeping VALUE as a string unless it is valid JSON."""
    key, separator, value = option.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {option!r}")
    try:
        return key, json.loads(value)
    except json.JSONDecodeError:
        return key, value


def synthesize(client: httpx.Client, url: str, voice: str, text: str, seed: int, options: dict) -> dict:
    body = {
        "model": "irodori-tts",
        "input": text,
        "voice": voice,
        "response_format": "wav",
        "irodori": {**options, "chunking_enabled": False, "seed": seed},
    }
    started = time.perf_counter()
    response = client.post(f"{url}/v1/audio/speech", json=body)
    synth_seconds = time.perf_counter() - started
    response.raise_for_status()

    started = time.perf_counter()
    segment = process_segment(response.content, text)
    analysis_seconds = time.perf_counter() - started

    raw, sample_rate = sf.read(io.BytesIO(response.content), dtype="float32")
    return {
        "wav": response.content,
        "synth": synth_seconds,
        "analysis": analysis_seconds,
        "total": synth_seconds + analysis_seconds,
        "audio": segment["duration"],
        "raw_audio": len(raw) / sample_rate,
        "alignment": segment["alignment_score"],
        "to_decode": float(response.headers.get("X-Irodori-Total-To-Decode", "nan")),
        "messages": response.headers.get("X-Irodori-Messages", ""),
    }


def summarize(runs: list[dict]) -> dict:
    audio = sum(run["audio"] for run in runs)
    return {
        "runs": len(runs),
        "synth_p50": percentile([r["synth"] for r in runs], 0.5),
        "synth_p90": percentile([r["synth"] for r in runs], 0.9),
        "analysis_p50": percentile([r["analysis"] for r in runs], 0.5),
        "analysis_p90": percentile([r["analysis"] for r in runs], 0.9),
        "total_p50": percentile([r["total"] for r in runs], 0.5),
        "total_p90": percentile([r["total"] for r in runs], 0.9),
        "realtime_factor": sum(r["synth"] for r in runs) / audio if audio else None,
        "audio_mean": statistics.fmean(r["audio"] for r in runs),
        "raw_audio_mean": statistics.fmean(r["raw_audio"] for r in runs),
        "alignment_mean": statistics.fmean(r["alignment"] for r in runs),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="Output folder name, e.g. v4-small")
    parser.add_argument("--url", default="http://127.0.0.1:8088")
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--repeats", type=int, default=8)
    parser.add_argument("--set", dest="options", type=parse_option, action="append", default=[],
                        metavar="KEY=VALUE", help="Irodori request option, e.g. num_steps=12")
    args = parser.parse_args()
    options = dict(args.options)

    output = ROOT / ".scratch" / "bench" / args.label
    output.mkdir(parents=True, exist_ok=True)

    results: dict = {
        "label": args.label, "url": args.url, "voice": args.voice, "options": options,
        "repeats": args.repeats, "buckets": {},
    }
    with httpx.Client(timeout=httpx.Timeout(360.0)) as client:
        health = client.get(f"{args.url}/health").json()
        results["checkpoint"] = health.get("runtime", {}).get("checkpoint")
        results["vram_before_mib"] = vram_used_mib()

        for bucket, lines in LINES.items():
            runs: list[dict] = []
            cold: list[float] = []
            for line_index, text in enumerate(lines):
                cold.append(synthesize(client, args.url, args.voice, text, 0, options)["total"])
                for repeat in range(args.repeats):
                    run = synthesize(client, args.url, args.voice, text, repeat + 1, options)
                    if repeat < 2:
                        (output / f"{bucket}{line_index}_seed{repeat + 1}.wav").write_bytes(run["wav"])
                    results.setdefault("sample_messages", run["messages"])
                    del run["wav"], run["messages"]
                    runs.append(run)
            results["buckets"][bucket] = {**summarize(runs), "first_request_total": cold}
            print(f"{bucket} done", flush=True)
        results["vram_after_mib"] = vram_used_mib()

    gate = results["buckets"][GATE_BUCKET]["total_p90"]
    results["gate"] = {"bucket": GATE_BUCKET, "limit_seconds": GATE_SECONDS, "total_p90": gate, "passed": gate < GATE_SECONDS}
    (output / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\ncheckpoint: {results['checkpoint']}")
    print(f"VRAM: {results['vram_before_mib']} -> {results['vram_after_mib']} MiB")
    print(f"{'bucket':8}{'synth p50':>11}{'synth p90':>11}{'align p50':>11}{'total p90':>11}{'RTF':>7}{'audio':>8}{'raw':>8}")
    for bucket, s in results["buckets"].items():
        print(
            f"{bucket:8}{s['synth_p50']:>10.3f}s{s['synth_p90']:>10.3f}s{s['analysis_p50']:>10.3f}s"
            f"{s['total_p90']:>10.3f}s{s['realtime_factor']:>7.2f}{s['audio_mean']:>7.2f}s{s['raw_audio_mean']:>7.2f}s"
        )
    verdict = "PASS" if gate < GATE_SECONDS else "MISS"
    print(f"gate ({GATE_BUCKET} total p90 < {GATE_SECONDS}s): {gate:.3f}s {verdict}")
    print(f"audio and results: {output}")


if __name__ == "__main__":
    main()
