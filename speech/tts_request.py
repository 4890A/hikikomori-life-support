"""Which TTS engine the bridge uses, its settings, and the request each engine expects.

No audio or ML dependencies, so the settings can be unit tested on their own.
"""

from __future__ import annotations

import os

ENGINE_CPP = "cpp"  # speech.cpp with Irodori v4.1-Small-MF on Vulkan.
ENGINE_PYTORCH = "pytorch"  # Irodori-TTS-Server with v4-Small on CUDA.

ENGINE = os.environ.get("TTS_ENGINE", ENGINE_CPP)
# Must match the model given to scripts/start-tts.ps1.
MODEL = os.environ.get("TTS_MODEL", "irodori-tts-mf")
# Chosen in docs/companion-plan.md. MeanFlow defaults to 4 steps, and Irodori's other models to 40.
STEPS = int(os.environ.get("TTS_STEPS", "6"))
# Below 1 shortens each line. About half of a line at 1 is silence: see docs/companion-plan.md.
DURATION_SCALE = float(os.environ.get("TTS_DURATION_SCALE", "1"))
SWAY_COEFF = -1.0
GUIDANCE_MODE = "independent"

# A voice file made from the user's recording by scripts/add-voice.ps1. Empty until they add one.
DEFAULT_VOICE = os.environ.get("TTS_VOICE", "")

# The fewest characters a streamed segment holds before it goes to TTS. speech.cpp speaks each
# sentence of a request on its own with 0.9 s between them, so merging gains nothing and only
# delays the first audio. PyTorch speaks a request as a whole, and very short inputs do badly.
MIN_SEGMENT_CHARS = {ENGINE_CPP: 1, ENGINE_PYTORCH: 8}[ENGINE]


def uses_meanflow(model: str) -> bool:
    return "mf" in model.split(":")[0].split("-")


def request_body(
    text: str,
    voice: str,
    seed: int | None = None,
    speed: float | None = None,
    caption: str | None = None,
    engine: str = ENGINE,
    steps: int = STEPS,
    model: str = MODEL,
    duration_scale: float = DURATION_SCALE,
) -> dict:
    """The JSON for POST /v1/audio/speech."""
    if engine == ENGINE_CPP:
        body: dict = {"input": text, "voice": voice, "response_format": "wav", "steps": steps}
        # MeanFlow has guidance built in, and speech.cpp refuses these settings for it.
        if not uses_meanflow(model):
            body["sway_coeff"] = SWAY_COEFF
            body["cfg_guidance_mode"] = GUIDANCE_MODE
        if seed is not None:
            body["seed"] = seed
        if caption:
            body["instructions"] = caption
        if duration_scale != 1:
            body["duration_scale"] = duration_scale
    else:
        irodori: dict = {
            "chunking_enabled": False,
            "num_steps": steps,
            "t_schedule_mode": "sway",
            "sway_coeff": SWAY_COEFF,
            "cfg_guidance_mode": GUIDANCE_MODE,
        }
        if seed is not None:
            irodori["seed"] = seed
        if caption:
            irodori["caption"] = caption
        if duration_scale != 1:
            irodori["duration_scale"] = duration_scale
        body = {"model": "irodori-tts", "input": text, "voice": voice, "response_format": "wav", "irodori": irodori}
    if speed is not None:
        body["speed"] = speed
    return body
