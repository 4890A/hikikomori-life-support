# Real-time screen companion: plan

## Goal

DeepSeek-chan watches whatever is on your screen and listens to you, then answers out loud with matching Irodori emotion and Live2D expression, as close to instantly as possible.

The repo already has the output half: TTS, emoji-driven voice and face cues, lip sync and synced playback. It has no LLM, speech recognition or screen capture yet.

**Decisions so far**

- You speak Japanese and it replies in Japanese.
- It reacts to the moment for anything on screen: games, video, work or websites. It started out tuned for mahjong, and that was removed after your first play test.
- Replies use 2-3 emoji from a guide in the prompt, built from `EMOJI_EMOTIONS` and Irodori's palette, so the face and voice can change within a line.
- Vision runs online through OpenRouter.
- Speech recognition tries Japanese Parakeet first.

## Your to-do list

These need you, and nothing is blocked on them until Step 2:

- [x] Create an OpenRouter account, add a little credit and create an API key.
- [x] Save the key as the `OPENROUTER_API_KEY` Windows user environment variable. To set it again, run this in your own terminal, then open a new one. Don't put it in the repo or send it to the browser.

  ```powershell
  [Environment]::SetEnvironmentVariable('OPENROUTER_API_KEY', (Read-Host 'OpenRouter key' -MaskInput), 'User')
  ```
- [ ] Have the mahjong client open during the TTS benchmark if you want to measure GPU contention with the game.
- [ ] Use headphones for the first voice tests, or her own voice can trigger the interruption.

## Status

- [x] Step 1: Benchmark TTS: `v4-Small`, 20 steps, sway, saved voice, chosen by ear; the game-load rerun is still open
- [x] Step 2: Benchmark vision models: `deepseek/deepseek-v4.1-flash`, with `z-ai/glm-5.3-flash` as fallback (results in Step 2)
- [x] Step 3: Streaming pipeline in the bridge: `POST /companion/turn` works; first audio is slower than the Step 1 numbers suggested (results in Step 3)
- [x] Step 4: Browser side: works with a test video; a real shared window still needs your try
- [ ] Step 5: Your voice
- [ ] Step 6: Polish, only if the numbers justify it

## Will RunPod make it fast enough?

**No, not needed so far. `v4.1-Small-MF` was rejected by ear because it sounds messed up. You picked `v4-Small` at 20 steps with independent guidance by ear, now the bridge default. It takes 0.74 s (p90), slightly over the 0.7 s gate, which isn't worth renting a GPU for. Recheck with the game open.**

The chosen 20-step settings, measured on a warmed-up server with 10 repeats per line:

| Guidance | Medium line total p50 | Medium line total p90 | Long line total p90 |
|---|---|---|---|
| Independent (the bridge default) | About 0.59 s | 0.743 s | 0.842 s |
| Alternating (slower, and you heard no reason to keep it) | About 0.77 s | 0.860 s | 0.912 s |

- **These numbers are optimistic:** they repeat the same lines, and new audio lengths add about 0.7 s (see Step 3).
- **Warm-up:** the first requests after a server starts are much slower: 3.34 s on the bridge's first request. The bridge now warms up in the background at startup.
- **Earlier numbers:** the table below includes some first runs on a fresh server, including 40 steps with independent guidance, so its p90 figures may be inflated. Prefer the table above when comparing 20-step settings.

`v4-Small` with the saved voice (5 repeats per line, so p90 is noisy):

| Steps, schedule, guidance | Medium line total p90 | Long line total p90 | Gate (under 0.7 s) |
|---|---|---|---|
| 40, linear, independent | 1.576 s | 1.760 s | Miss |
| 40, linear, alternating | 1.720 s | 1.539 s | Miss |
| 20, sway, alternating | 0.823 s | 1.042 s | Miss |
| 16, sway, independent | 0.557 s | 0.785 s | Pass |
| 12, sway, independent | 0.477 s | 0.646 s | Pass |
| 8, sway, independent | 0.366 s | 0.540 s | Pass |

Alternating guidance gave no speedup at 40 steps (p50 1.19 s vs 0.89 s on medium lines), so it isn't worth using. Alignment scores stayed about the same at every step count, which says little about how it sounds.

The earlier comparison, including the rejected model:

Measured on 2026-11-02 on the RTX 4070, without the mahjong client running. Each line ran 8 times after a warm-up request. Times are synthesis plus lip alignment for a line of about 20 characters:

| Setup | p90 | Gate (under 0.7 s) | Peak VRAM, whole GPU |
|---|---|---|---|
| `v4-Small`, 40 steps, wav voice | 1.964 s | Miss | 10.9 GB |
| `v4.1-Small-MF`, 4 steps, wav voice | 1.146 s | Miss | 11.1 GB |
| `v4.1-Small-MF`, 4 steps, saved latent | **0.324 s** | **Pass** | 6.3 GB |

Results by line length with the saved latent:

| Line | Total p90 | Realtime factor | Audio length |
|---|---|---|---|
| Short | 0.287 s | 0.11 | 2.19 s |
| Medium | 0.324 s | 0.06 | 4.50 s |
| Long | 0.475 s | 0.03 | 10.28 s |

- **What actually fixed it:** the original estimate blamed the 40 sampling steps, but the server was also re-encoding the voice clip on every request, at about 470 ms. Sampling itself takes about 100 ms at 4 steps. `scripts/encode_voice.py` saves the encoded voice once, and the server loads it as the voice `my-voice-latent`.
- **Same sound:** same-seed audio from the wav voice and the saved latent is identical (correlation 1.0000 on all 16 clips).
- **Still open, quality:** short lines score only about 0.27 on alignment on every setup, and about 1.2 s gets trimmed off each one, so they may have the padding problem described in Step 1.
- **Published accuracy:** the kana error rate on JSUT is 3.78% for `v4.1-Small-MF` and 3.43% for 40-step `v4.1-Small`. Voice similarity on JVS is 0.743, against 0.752 for 40-step `v4-Small`.
- **Still open, game load:** rerun with the mahjong client open.

If RunPod ever becomes necessary:

- **What RunPod costs:** a faster GPU only speeds up the compute. The network round trip gets added to every segment, and you pay by the hour.
- **When RunPod is worth it:** only if Step 1 misses its target and the same benchmark on a rented GPU beats local after network time. In that case, use a Pod started for each session, not serverless, so the first reaction doesn't risk a cold start.
- **RunPod price:** an RTX 4090 is listed at about $0.34 to $0.89/hr depending on tier. Sources disagree and prices changed recently, so check the live rate card.
- **RunPod changes needed:** `IRODORI_TTS_URL` already lets the bridge point elsewhere, but the bridge sends no auth header. Add that before exposing the server. The Pod also needs the voice file.

## How it will feel fast

Generating the whole reply will always take a moment, so the design hides that wait:

1. **Local reaction, right away:** she looks attentive as soon as you start talking, and thinks when you stop.
2. **Face, from the LLM's first token:** replies start with an emoji, so her expression changes before any audio exists.
3. **Voice, from the first finished sentence:** each sentence goes to TTS as soon as it's complete, without waiting for the full reply.
4. **Optional filler sounds:** pre-generated clips like 「おっ」 or 「えー」 cover the gap (Step 6).

Emoji already drive both Irodori's delivery and the face through `EMOJI_EMOTIONS` in `speech/cues.py`, so one token controls both and no separate emotion system is needed.

## Architecture

```
Browser (web/)                                Speech bridge (:8089)
 screen capture -> change detector --frame-->  POST /companion/turn
 mic -> voice activity detection  --audio-->     speech recognition (local)
 director: decides when to speak                 OpenRouter, streaming
 SpeechPlayer <--NDJSON expression/segment---    sentence splitter -> Irodori (:8088)
                                                 -> lip alignment
```

The browser captures and decides, and the bridge holds the API key and runs the pipeline. A plain POST with an NDJSON response reuses the existing stream reader and its abort handling, so no WebSocket is needed.

**Latency targets to verify (not measurements)**

| Step | Target |
|---|---|
| End-of-speech detection | 300-500 ms |
| Speech recognition | 100-300 ms |
| LLM first token, which also sets the face | 300-800 ms |
| First complete sentence | 200-400 ms more |
| TTS plus lip alignment | Under 700 ms (Step 1 gate); the chosen setting measures 743 ms |

Overall goal: the face changes under 1 s after a screen event or after you stop talking, and first audio arrives in about 2 s (median).

## Steps

### 1. Benchmark TTS (decides the RunPod question)

Results are in the RunPod section above. To reproduce them:

```powershell
.\scripts\start-tts.ps1
# In a second terminal, once the server is up:
$env:HF_HUB_OFFLINE = '1'
uv run --project Irodori-TTS-Server --no-sync python scripts\encode_voice.py
.\scripts\bench-tts.ps1 -Label s12 -Voice my-voice-latent -Repeats 5 -Set num_steps=12,t_schedule_mode=sway
```

- `scripts/bench_tts.py` records warm p50/p90 synthesis time, realtime factor, alignment time and VRAM, and saves clips to `.scratch/bench/<label>/`.
- **Gate:** p90 of synthesis plus alignment under 700 ms for a line of about 20 characters.
- **Settings live in:** `DEFAULT_VOICE` and `SYNTHESIS_OPTIONS` in `speech/server.py`.
- If a later run with the game misses the gate, try `compile_model` and `bf16` for the codec, then run the same script on a rented Pod.
- **Listen to the short lines.** The code warns that very short inputs get an overestimated duration, filled with silence and invented sounds (`speech/cues.py`, `split_segments`). Reactions are short, so this is the biggest quality risk. If it happens, try `duration_scale`, or have the LLM write slightly longer lines.

### 2. Benchmark cheap vision models

**Current pick: `deepseek/deepseek-v4.1-flash`, with `z-ai/glm-5.3-flash` as fallback.** A later comparison on 2026-11-02 measured first sentence, which is when TTS can start (median / p90 seconds):

| Turn | DeepSeek V4.1 Flash | GLM 5.3 Flash | Gemini 2.5 Flash-Lite |
|---|---|---|---|
| Screen, mahjong frames | 0.43 / 0.59 | 0.81 / 0.93 | 0.73 / 1.13 |
| Screen, other games | 0.50 / 0.82 | 0.72 / 0.92 | 0.69 / 0.86 |
| Speech | 0.37 / 0.44 | 0.76 / 0.99 | 0.45 / 0.50 |

- **DeepSeek needs reasoning turned off.** On `{"effort": "minimal"}` it returned no text on 8 of 9 live turns. GLM rejects turning it off, so each model gets its own setting (`REASONING_REQUIRED` in `speech/llm.py`).
- **The bridge does the fallback itself,** because one OpenRouter request can only carry one reasoning setting. It moves on if a model fails or returns no text before speaking. Checked live with a main model that can't take images: GLM took over.
- **Live through the bridge, without a browser:** first audio ready in 0.80-1.90 s on 5 speech turns, and 1.03-1.88 s on 3 screen turns. TTS timing still varies with audio length.
- Only one provider, Wafer, served DeepSeek in these runs.

The original comparison, which picked GLM, follows. Run with `.\scripts\bench-llm.ps1`. Measured on 2026-11-02 with `provider: {sort: "latency"}`: 12 speech turns and 15 screen turns per model, using 5 frames from a public Mahjong Soul video.

| Model | Speech: first token p50 / p90 | Screen: first token p50 / p90 | Screen: first sentence p50 / p90 | Cost per hour, screen turns | Quality on screen turns |
|---|---|---|---|---|---|
| `z-ai/glm-5.3-flash` | 0.26 / 0.62 s | 0.49 / 0.73 s | 0.85 / 1.35 s | $0.021 | Most specific; some wrong details; output glitches |
| `google/gemini-2.5-flash-lite` | 0.39 / 0.50 s | 0.61 / 0.92 s | 0.75 / 1.00 s | $0.008 | Vague, invents riichi, summary format unreliable (60%) |
| `qwen/qwen3.7-flash` | 0.65 / 0.96 s | 1.30 / 2.28 s | 1.35 / 2.61 s | $0.009 | Slow, leaks Chinese and English |
| `openai/gpt-5-nano` | 0.94 / 2.18 s | 2.17 / 3.69 s | 2.31 / 3.90 s | $0.018 | Too slow, too long |

Cost assumes one comment every 12 s.

- **GLM needs cleanup before TTS (Step 3):** replies included a corrupted emoji (`😮‍ฟ`) and one reply repeated in full. It also said South 4 on frames showing East 4, so comments can be wrong about the game. Only one provider (InferenceNet) served it.
- **Reasoning:** GLM and `gpt-5-nano` reject disabled reasoning, so they use `{"effort": "minimal", "exclude": true}`. GLM spent up to 22 reasoning tokens.
- **Fallback:** Gemini Flash-Lite, the most consistent on timing and the cheapest here, but it was rate limited 2 times out of 27 and retried once.
- **Sample limits:** this is a small sample from one video in the Silver room, and it has no clear riichi frame. Recheck on your own game.
- **Vision stays online and never waits on a second model:**
  - **Screen turns:** one vision model gets the frame and writes the spoken reply in a single streaming call, so there's only one network wait. It also returns a one-line summary of the game after the spoken reply. The summary isn't sent to TTS.
  - **Speech turns:** send text only, plus the latest summary, so answering you never waits on image processing. The benchmark also tests sending a fresh frame on these turns, in case replies need it and the delay is small.

### 3. Streaming pipeline in the bridge

Done. What's there:

- `speech/companion.py`: `POST /companion/turn`. Takes `{"kind":"speech","text":...}` or `{"kind":"screen","image":<data URL>}` and streams `expression`, `segment`, `trace`, then `done` or `error`. Disconnecting cancels the turn. History is the last 8 exchanges as text only.
- `speech/llm.py`: prompts and the OpenRouter client. `COMPANION_MODEL` and `COMPANION_FALLBACK_MODEL` override the models.
- `speech/cues.py`: `ReplyParser`, `StreamSegmenter` and `clean_spoken`. They keep the summary out of speech, drop broken emoji and other scripts, and stop on repeated sentences or past 80 characters.
- `speech/synthesis.py`: one-segment synthesis, moved out of `server.py`, plus a background warm-up at startup. `/health` reports `warmed_up`.

Measured live with 8 full turns from a warmed-up bridge, with no browser, speech recognition or game running. This is a small sample:

| Turn | Face | First audio ready |
|---|---|---|
| Speech (5 turns) | 0.28-0.64 s | 1.16-2.34 s |
| Screen (3 turns) | 0.94-2.11 s | 2.46-3.62 s |

**Why first audio is slow: new audio lengths.** Sampling takes about 0.45 s or about 1.2 s, and it's the frame count that matters, not text length or content. Repeating a new frame count doesn't reliably make it fast. The Step 1 benchmark repeated the same lines, so its 0.59 s median understates real replies. Expect about 1.3 s of TTS on many new lines. The cause inside PyTorch or the model is still unknown.

**Fix to try next:** generate at a small fixed set of durations instead of the predicted one. Cycling 3-8 fixed durations kept the median at about 0.5 s, with 1 in 12 to 3 in 32 requests still slow. The risk is sound quality, because a duration longer than the speech can add silence or invented sounds, so this needs a listening test.

**Not verified:** the automatic switch to the Gemini fallback. An invalid model ID is rejected before fallback runs, so it wasn't exercised, though Gemini does accept the same request settings when used as the main model.

### 4. Browser side

Done. Click **Start Companion** in the panel, then pick the game window. The text box sends typed speech turns until the mic exists (Step 5).

- `web/src/companion/screen.ts`: `ScreenWatcher` compares 64x36 grayscale frames twice a second and sends a JPEG about 768 px wide when needed.
- `web/src/companion/director.ts`: decides when she speaks. Your words interrupt her. Otherwise see the rhythm table below. `userSpeaking` is ready for the mic.
- `web/src/companion/clock.ts`: runs the director and screen checks from a Web Worker, because browsers can throttle page timers on hidden pages.
- `web/src/anim/speech.ts`: `playStream()` also handles `expression` and `trace` lines, and `active` now follows the audio clock, so it stays right when frames stop.
- `web/src/ui.ts`: the Companion section shows turns, cost, and face and audio timing.

**Rhythm (after your first play test):** she was too quiet, so the mahjong thresholds were replaced. The delay is seconds of quiet after her last line, chosen by the biggest change seen since her last comment, with a random 0.85-1.25x on each wait. A pixel counts as changed past a difference of 24 out of 255.

| Chattiness | Big change (12%+) | Some change (2%+) | Any change (0.5%+) | Nothing changed |
|---|---|---|---|---|
| Quiet | 6 s | 15 s | 30 s | 90 s |
| Normal (default) | 3 s | 6 s | 12 s | 30 s |
| Chatty | 2 s | 3 s | 6 s | 20 s |

Measured with the Mahjong Soul clip on 2026-11-02: Normal made 4.7 comments a minute over 90 s, and 17 in 219 s in a later run. Chatty made only 5 a minute over 60 s, because generating and speaking each line takes most of the cycle. A paused video gave a comment about every 38 s. Quiet wasn't measured. At about $0.00016 a screen turn in the first play session, Normal should cost about 5 cents an hour.

**General prompt:** replies to 3 frames each from Minecraft, Mario Kart and Elden Ring, with no history, all fit the game shown. She can still state wrong details with confidence.

Tested in the real page with that clip standing in for a shared window (a small sample, with the game not running on this PC):

| Turn | Face | First audio scheduled |
|---|---|---|
| Screen, after the summary fix (4 turns with audio) | 0.49-0.93 s | 2.05-4.0 s, usually about 2.5 s |
| Typed speech | 0.44 s | 1.70 s |

Also checked: reacting unprompted to match-end screens, idle comments, a typed turn interrupting another, and Stop.

**Not tested:**

- The browser's real window picker and a live game window. The picker can't be automated.
- Whether she keeps going when her window is really hidden. In the automated test the browser never reported the page as hidden (0 of 17 turns), even with another tab on top, so that test proves nothing. The Web Worker clock is in place, but frames from a real shared window may still stall while hidden. If so, try `ImageCapture.grabFrame()`.
- Sound: nobody has listened to this flow yet.

**Known issues:**

- One reply in about 12 screen turns stalled 4.35 s and had nothing speakable, so only her face changed. The bridge now logs raw replies to diagnose repeats.
- She often gets the round wrong, such as saying South on East frames.

### 5. Your voice

- New `web/src/companion/mic.ts`: voice activity detection in the browser, planned with `@ricky0123/vad-web`. Talking over her calls `SpeechPlayer.stop()`.
- New `speech/stt.py`, benchmarked on your own voice in this order:
  1. `nvidia/parakeet-tdt_ctc-0.6b-ja`: 0.6B parameters, trained on ReazonSpeech v2.0 (35k+ hours of natural Japanese speech), with a published JSUT error rate of about 9.0 CER. It needs NeMo, which is a heavy install, or a community ONNX export such as `OpenVoiceOS/nvidia-parakeet-tdt_ctc-0.6b-ja-onnx`. Try ONNX first, and check its license and whether it works on Windows.
  2. `efwkjn/faster-whisper-ja-22M` and `faster-whisper-large-v3-turbo`: already downloaded, and used as the baseline.
- Keep whichever is fastest while accurate enough on mahjong terms like リーチ, ロン and ツモ. A published JSUT score says little about casual speech mid-game. No independent Japanese latency numbers turned up, so this has to be measured here.
- Update `scripts/start-speech.ps1` with the new dependency.
- Expect CUDA library issues on Windows with faster-whisper and possibly the ONNX runtime.

### 6. Polish, only if the numbers justify it

- Pre-generated filler clips with their lip tracks, played while the real line generates.
- If alignment is the slow part, send audio first and fall back to the loudness-based mouth (`web/src/anim/talk.ts`).

## Privacy

Selected frames go to OpenRouter and its model provider. **Share only the game window in the browser picker, not your whole screen,** so notifications and passwords stay out. Also check whether `provider.data_collection: "deny"` works with the chosen model.

## Verification

- **Unit tests:** run the existing test command in `README.md`, with new cases for split emoji, sentences across deltas and flush at end of stream.
- **Trace every turn:** log trigger, STT done, first token, first sentence, TTS done, alignment done and first audio. Report p50/p90 over at least 30 turns.
- **Live test:** play a real mahjong game for 15 minutes and check that:
  - the targets above hold
  - segments play with no gaps (realtime factor below 1)
  - interrupting her stops audio promptly, and the next turn isn't held up by the TTS request still running (concurrency is 1)
  - VRAM stays within 12 GB alongside the game
  - cost is about what Step 2 predicted

## Sources

- [Irodori-TTS v4.1-Small-MF model card](https://huggingface.co/Aratako/Irodori-TTS-v4.1-Small-MF)
- [Irodori-TTS README](https://github.com/Aratako/Irodori-TTS)
- [Parakeet Japanese model card](https://huggingface.co/nvidia/parakeet-tdt_ctc-0.6b-ja/blob/main/README.md)
- [OpenRouter provider routing](https://openrouter.ai/docs/guides/routing/provider-selection)
- [OpenRouter latency guide](https://openrouter.ai/docs/guides/best-practices/latency-and-performance)
- [RunPod pricing](https://www.runpod.io/gpu-cloud/pricing)
- [RunPod RTX 4090 tracker](https://computeprices.com/providers/runpod/gpus/rtx4090)
- [RunPod Secure Cloud price change](https://www.usagepricing.com/blueprint/activity/runpod-2026-09-20-secure-cloud-price-hike)
