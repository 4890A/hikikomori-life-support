"""One-segment speech synthesis: Irodori-TTS audio plus lip track and expression cues."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import time

import httpx
import soundfile as sf

from analysis import TRACK_FPS, PhonemeModel, analyze
from cues import Emoji, Fragment, build_cues, parse_items
from tts_request import DEFAULT_VOICE, request_body

logger = logging.getLogger("speech-bridge")
TTS_URL = os.environ.get("IRODORI_TTS_URL", "http://127.0.0.1:8088")
# The server caps a single synthesis at this length; hitting it means speech was probably cut off.
SYNTHESIS_CAP_SECONDS = 30.0
# Silence kept around speech when trimming the model's leading and trailing padding.
TRIM_BEFORE_SECONDS = 0.08
TRIM_AFTER_SECONDS = 0.2
# The first requests after a server starts are several times slower, in a variety of lengths.
WARM_UP_LINES = (
    "😲えっ、リーチ！",
    "😆やった、ツモだ！今の手はすごく良かったよ！",
    "😊今の局はすごくいい流れだったね。最初は危ないかなと思ったけど、最後にしっかりあがれて本当によかったよ。",
)
WARM_UP_ROUNDS = 3
WARM_UP_RETRY_SECONDS = 3.0
TTS_TIMEOUT = httpx.Timeout(360.0)

model: PhonemeModel | None = None
warmed_up = False


class TTSError(Exception):
    pass


def get_model() -> PhonemeModel:
    global model
    if model is None:
        model = PhonemeModel()
    return model


def process_segment(wav_bytes: bytes, text: str) -> dict:
    """Blocking part: analysis, trimming and cue timing for one synthesized segment."""
    audio, sample_rate = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    items = parse_items(text)
    result = analyze(get_model(), audio, sample_rate, items)

    full_duration = len(audio) / sample_rate
    start = max(0.0, result.speech_start - TRIM_BEFORE_SECONDS)
    end = min(full_duration, result.speech_end + TRIM_AFTER_SECONDS)
    for item in items:
        if isinstance(item, Fragment):
            item.start = max(0.0, item.start - start)
            item.end = max(0.0, item.end - start)
    spans = [(a - start, b - start) for a, b in result.spans]
    duration = end - start
    cues = build_cues(items, spans, duration)

    first, last = int(start * TRACK_FPS), int(end * TRACK_FPS)
    buffer = io.BytesIO()
    sf.write(buffer, audio[int(start * sample_rate) : int(end * sample_rate)], sample_rate, format="WAV", subtype="PCM_16")

    if full_duration >= SYNTHESIS_CAP_SECONDS - 0.5:
        logger.warning("segment reached the synthesis cap and may be cut off: %s", text)
    return {
        "text": text,
        "audio_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "duration": round(duration, 3),
        "fps": TRACK_FPS,
        "open": result.open[first:last],
        "vowel": result.vowel[first:last],
        "cues": [cue.as_dict() for cue in cues],
        "ignored_emoji": [i.char for i in items if isinstance(i, Emoji) and i.emotion is None],
        "fragments": [
            {"text": i.text, "start": round(i.start, 3), "end": round(i.end, 3)}
            for i in items
            if isinstance(i, Fragment) and i.phones
        ],
        "alignment_score": round(result.alignment_score, 3),
    }


async def synthesize_segment(
    client: httpx.AsyncClient,
    text: str,
    voice: str = DEFAULT_VOICE,
    seed: int | None = None,
    speed: float | None = None,
    caption: str | None = None,
) -> dict:
    if not voice:
        raise TTSError("No voice is set. Put a WAV recording in the voices folder, then run start.ps1.")
    body = request_body(text, voice, seed, speed, caption)
    started = time.perf_counter()
    try:
        response = await client.post(f"{TTS_URL}/v1/audio/speech", json=body)
    except httpx.HTTPError as exc:
        raise TTSError(f"TTS server unreachable at {TTS_URL}: {exc}") from exc
    if response.status_code != 200:
        raise TTSError(f"TTS error {response.status_code}: {response.text[:300]}")
    synthesized = time.perf_counter()
    segment = await asyncio.to_thread(process_segment, response.content, text)
    logger.info(
        "segment %.2fs audio, synth %.2fs, analysis %.2fs, alignment %.2f, cues %s",
        segment["duration"],
        synthesized - started,
        time.perf_counter() - synthesized,
        segment["alignment_score"],
        [(c["emoji"], c["emotion"], c["start"], c["end"]) for c in segment["cues"]],
    )
    return segment


async def warm_up() -> None:
    """Runs in the background from startup, so the first real line isn't the slow one."""
    global warmed_up
    async with httpx.AsyncClient(timeout=TTS_TIMEOUT) as client:
        while True:
            try:
                await client.get(f"{TTS_URL}/health")
                break
            except httpx.HTTPError:
                await asyncio.sleep(WARM_UP_RETRY_SECONDS)
        started = time.perf_counter()
        for _ in range(WARM_UP_ROUNDS):
            for line in WARM_UP_LINES:
                try:
                    await synthesize_segment(client, line)
                except TTSError as exc:
                    logger.warning("warm-up stopped: %s", exc)
                    return
    warmed_up = True
    logger.info("warm-up finished in %.1fs", time.perf_counter() - started)
