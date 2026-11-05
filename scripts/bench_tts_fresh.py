"""Compares TTS engines on lines they haven't seen, which is what real replies look like.

Unlike bench_tts.py this never repeats a line, because PyTorch sampling is much slower on audio
lengths it hasn't just used. Works against the OpenAI-style route of Irodori-TTS-Server
(--engine pytorch) or speech.cpp (--engine cpp). Clips go to .scratch/bench-fresh/<label>/.
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

ROOT = Path(__file__).resolve().parent.parent
WARM_UP = [
    "😊こんにちは、今日もよろしくね。",
    "🤔ちょっと待って、それはどういう意味なのかな？",
    "😆やったね！すごく上手になってきたと思うよ、この調子でいこう。",
    "😲えっ、本当に？",
    "🤭ふふっ、そういうところが面白いんだよね。",
    "😮‍💨はあ、今日は長い一日だったな。",
]
LINES = [
    "😲わあ、すごい景色だね！",
    "🤔その選択、ちょっと意外かも。",
    "😆やった、うまくいったじゃん！",
    "😏ほらね、言ったとおりでしょ？",
    "😟それ、本当に大丈夫なの？",
    "🤭なんか変な動きしてて笑っちゃった。",
    "😊のんびりしてていい感じだね。",
    "😮‍💨まぁ、そういう日もあるよね。",
    "😳えっ、そんなことまでできるの？",
    "😎これはもう勝ったも同然じゃない？",
    "🥺もう少しだけ一緒に見てていい？",
    "😠ちょっと、今のはずるいでしょ！",
    "😲画面がいきなり真っ赤になったからびっくりしたよ。",
    "🤔うーん、次はどっちに進むのがいいんだろうね。",
    "😆すごいすごい、さっきより全然うまくなってるよ！",
    "😌ゆっくり進めばいいと思うし、焦らなくても大丈夫だよ。",
    "😏そんなに急いじゃって、何か隠してるんじゃないの？",
    "😟なんだか敵が増えてきたみたいだけど、回復しなくていいの？",
    "🤭さっきからずっと同じ場所をぐるぐる回ってるの、気づいてる？",
    "😊この音楽いいね、なんだか懐かしい気持ちになっちゃうな。",
    "😲そこに隠し通路があったなんて、全然気がつかなかったよ！",
    "😮‍💨はあ、ここまで来るのに本当に時間がかかったけど、やっと終わりが見えてきたね。",
    "😆今の見た？タイミングばっちりだったし、もう一回やってほしいくらいかっこよかったよ！",
    "🤔その装備も悪くないけど、次の場所ではもう少し守りを固めたほうがいいかもしれないね。",
]


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def vram_used_mib() -> int | None:
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return int(output.splitlines()[0].strip())


def request_body(engine: str, voice: str, text: str, steps: int, seed: int, guidance: str, sway: bool, meanflow: bool) -> dict:
    if engine == "pytorch":
        return {
            "model": "irodori-tts",
            "input": text,
            "voice": voice,
            "response_format": "wav",
            "irodori": {
                "chunking_enabled": False,
                "seed": seed,
                "num_steps": steps,
                **({"t_schedule_mode": "sway", "sway_coeff": -1.0} if sway else {"t_schedule_mode": "linear"}),
                "cfg_guidance_mode": guidance,
            },
        }
    return {
        "input": text,
        "voice": voice,
        "response_format": "wav",
        "seed": seed,
        "steps": steps,
        **({} if meanflow else {"sway_coeff": -1.0 if sway else 0.0, "cfg_guidance_mode": guidance}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["pytorch", "cpp"], required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8088")
    parser.add_argument("--voice", required=True)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--guidance", default="independent")
    parser.add_argument("--linear", action="store_true", help="Use the default linear schedule instead of sway")
    parser.add_argument("--meanflow", action="store_true", help="Leave out the settings speech.cpp's MF model refuses")
    args = parser.parse_args()

    output = ROOT / ".scratch" / "bench-fresh" / args.label
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    with httpx.Client(timeout=httpx.Timeout(360.0)) as client:
        def speak(text: str, seed: int) -> tuple[float, bytes]:
            started = time.perf_counter()
            response = client.post(f"{args.url}/v1/audio/speech", json=request_body(args.engine, args.voice, text, args.steps, seed, args.guidance, not args.linear, args.meanflow))
            elapsed = time.perf_counter() - started
            if response.status_code != 200:
                raise SystemExit(f"{response.status_code}: {response.text[:400]}")
            return elapsed, response.content

        warm = [speak(text, i)[0] for i, text in enumerate(WARM_UP)]
        vram = vram_used_mib()
        for index, text in enumerate(LINES):
            seconds, wav = speak(text, 100 + index)
            (output / f"line{index:02d}.wav").write_bytes(wav)
            audio, rate = sf.read(io.BytesIO(wav), dtype="float32")
            rows.append({"text": text, "seconds": seconds, "audio": len(audio) / rate, "rate": rate})

    times = [row["seconds"] for row in rows]
    audio = sum(row["audio"] for row in rows)
    summary = {
        "label": args.label,
        "steps": args.steps,
        "guidance": args.guidance,
        "median": statistics.median(times),
        "p90": percentile(times, 0.9),
        "max": max(times),
        "min": min(times),
        "slow_over_1s": sum(t > 1.0 for t in times),
        "realtime_factor": sum(times) / audio,
        "warm_up": [round(t, 2) for t in warm],
        "vram_mib": vram,
        "sample_rate": rows[0]["rate"],
    }
    (output / "results.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"{args.label:26} median {summary['median']:.3f}s  p90 {summary['p90']:.3f}s  min {summary['min']:.3f}s  max {summary['max']:.3f}s  "
        f"over 1s {summary['slow_over_1s']}/{len(times)}  RTF {summary['realtime_factor']:.3f}  VRAM {vram} MiB  warm-up {summary['warm_up']}"
    )


if __name__ == "__main__":
    main()
