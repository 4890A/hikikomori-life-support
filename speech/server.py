"""Speech bridge: Irodori-TTS audio plus timed lip-sync and expression cues for the Live2D model.

POST /speak streams newline-delimited JSON, one line per segment as soon as it is ready, so playback
can start before long text has finished generating. POST /companion/turn does the same for a reply
written by the LLM (see companion.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import synthesis
from companion import router as companion_router
from cues import EMOJI_EMOTIONS, split_segments
from synthesis import DEFAULT_VOICE, TTS_TIMEOUT, TTS_URL, TTSError, get_model, synthesize_segment, warm_up

logger = logging.getLogger("speech-bridge")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    warming = asyncio.create_task(warm_up())
    yield
    warming.cancel()


app = FastAPI(title="Live2D speech bridge", lifespan=lifespan)
app.include_router(companion_router)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1)
    voice: str = DEFAULT_VOICE
    seed: int | None = None
    speed: float | None = None
    caption: str | None = None


async def speech_lines(request: SpeakRequest) -> AsyncIterator[str]:
    segments = split_segments(request.text)
    async with httpx.AsyncClient(timeout=TTS_TIMEOUT) as client:
        for index, text in enumerate(segments):
            try:
                segment = await synthesize_segment(client, text, request.voice, request.seed, request.speed, request.caption)
            except TTSError as exc:
                yield json.dumps({"type": "error", "message": str(exc)}) + "\n"
                return
            yield json.dumps({"type": "segment", "index": index, "count": len(segments), **segment}, ensure_ascii=False) + "\n"
    yield json.dumps({"type": "done"}) + "\n"


async def guarded_lines(request: SpeakRequest) -> AsyncIterator[str]:
    """Reports failures as a stream line; the response has already started, so no HTTP error."""
    try:
        async for line in speech_lines(request):
            yield line
    except Exception as exc:
        logger.exception("speech failed")
        yield json.dumps({"type": "error", "message": f"{type(exc).__name__}: {exc}"}) + "\n"


@app.post("/speak")
async def speak(request: SpeakRequest) -> StreamingResponse:
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="text is empty")
    return StreamingResponse(guarded_lines(request), media_type="application/x-ndjson")


@app.get("/emoji")
async def emoji() -> dict[str, str]:
    """Which emoji drive which expression, so the UI can offer them."""
    return EMOJI_EMOTIONS


@app.get("/health")
async def health() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            tts = (await client.get(f"{TTS_URL}/health")).json()
    except httpx.HTTPError as exc:
        return {"status": "tts_unreachable", "detail": str(exc)}
    return {
        "status": "ok",
        "checkpoint": tts.get("runtime", {}).get("checkpoint"),
        "tts_loaded": tts.get("runtime", {}).get("loaded"),
        "warmed_up": synthesis.warmed_up,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s:%(name)s:%(message)s")
    get_model()
    uvicorn.run(app, host="127.0.0.1", port=8089)
