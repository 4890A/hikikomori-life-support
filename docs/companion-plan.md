# Real-time screen companion: plan

> This is the working log from building the companion, including paths and tools that have since changed. For setup, see the README.

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

### TTS engine: speech.cpp, `irodori-tts-mf` at 6 steps (current default)

You chose `irodori-tts-mf` at 6 steps. On the same 24 new lines it took 0.259 s median, 0.377 s p90 and 0.457 s at worst, with none over 1 s. In 16 live screen turns through the bridge, without a browser, TTS and lip alignment took 0.27 s median and first audio was ready in 1.06 s median, 1.48 s at worst. You listened to it at 6 steps and it sounds fine, unlike an earlier 4-step test of this model in Python. MF takes no sway or guidance settings, so the bridge leaves them out.

Earlier you chose speech.cpp's `irodori-tts` at 20 steps, measured below. `.\scripts\start-speech.ps1 -Steps N` changes the steps, `-Model` must match `start-tts.ps1 -Model`, and `-Engine pytorch` with `start-tts-python.ps1` goes back to Python. Each sentence now goes to TTS alone, because the server would otherwise add 0.9 s between sentences. The first live run gave first audio ready in 0.80-1.28 s on 7 of 8 turns, and 3.42 s on the first, a large screenshot after startup.

Tested [speech.cpp](https://github.com/nyosegawa/speech.cpp) v0.10.1 on Vulkan, with its F16 `v4.1-Small` and the same voice, against PyTorch `v4-Small` with the saved voice. `scripts/bench_tts_fresh.py` sends 24 new lines of varied length, with sway and independent guidance, on the RTX 4070 without a game running. Times are for a complete WAV:

| Engine, steps | Median | p90 | Max | Over 1 s |
|---|---|---|---|---|
| speech.cpp, 20 | 0.613 s | 0.941 s | 1.012 s | 1 of 24 |
| speech.cpp, 16 | 0.502 s | 0.685 s | 0.872 s | 0 of 24 |
| speech.cpp, 12 | 0.411 s | 0.540 s | 0.695 s | 0 of 24 |
| speech.cpp, 8 | 0.324 s | 0.442 s | 0.550 s | 0 of 24 |
| PyTorch, 20 | 1.197 s | 1.424 s | 1.468 s | 15 of 24 |
| PyTorch, 16 | 0.465 s | 1.111 s | 1.243 s | 4 of 24 |
| PyTorch, 12 | 0.377 s | 0.465 s | 1.239 s | 1 of 24 |

- **At the default 40 steps (linear schedule):** speech.cpp took 0.951 s median, 1.482 s p90 and 8 of 24 over 1 s. PyTorch took 1.566 s, 1.747 s and 22 of 24. You said the lower-step speech.cpp clips don't sound as good as Python, so choosing between 40 steps on speech.cpp and PyTorch at 20 is waiting on a listening test.
- **PyTorch's 16 and 12 step numbers are flattering:** those runs repeated lines from earlier passes, so many audio lengths had already been seen. Only the 20-step row is close to a fair comparison, and even it followed one discarded warm pass.
- **Slow audio lengths:** speech.cpp doesn't show the 0.7 s penalty for new lengths, so this may replace the fixed-duration fix.
- **Trade-offs:** you found these clips don't sound as good as Python, and more steps may help. speech.cpp also doesn't apply Irodori's SilentCipher watermark.

### 4. Browser side

Done. Click **Start Companion** in the panel, then pick the game window. The text box sends typed speech turns until the mic exists (Step 5).

- `web/src/companion/screen.ts`: `ScreenWatcher` compares 64x36 grayscale frames twice a second and sends a JPEG about 768 px wide when needed.
- `web/src/companion/director.ts`: decides when she speaks. Your words interrupt her. Otherwise see the rhythm table below. `userSpeaking` is ready for the mic.
- `web/src/companion/clock.ts`: runs the director and screen checks from a Web Worker, because browsers can throttle page timers on hidden pages.
- `web/src/anim/speech.ts`: `playStream()` also handles `expression` and `trace` lines, and `active` now follows the audio clock, so it stays right when frames stop.
- `web/src/ui.ts`: the Companion section shows turns, cost, and face and audio timing.
- `web/src/companion/turnMonitor.ts`: a toggleable overlay with the exact frame she was sent, or your typed words, and live timers for each step: Model, Writing, TTS and Speaking. The TTS timer runs until playback starts, so it includes the trip back to the browser and decoding, not just synthesis.

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

**Video to speech, measured in the live page on 2026-11-03.** Real game frames on a test stream, timed from the picture changing to audio leaving the page, each after enough quiet to respond at once, so this is close to a best case. No game was running, and the speakers' own delay isn't included.

| Median (p90), seconds | Checking twice a second (20 changes) | Checking every frame (16 changes) |
|---|---|---|
| Change noticed | 0.80 (1.29) | 0.06 (0.08) |
| Face changes | 1.13 (1.73) | 0.44 (0.58) |
| First sound | 2.78 (3.62) | 1.85 (2.25) |
| TTS and lip alignment | 1.25 | 1.05 |

The watcher now checks about 30 times a second against the picture from 0.5 s earlier, the gap the thresholds were measured at, and sends the frame at once. A check took about 2 ms on the main thread. On the Mahjong Soul clip she still made 4.8 comments a minute. The trade-off is that a frame can catch an effect before it fills out.

TTS is the biggest remaining delay. The same engine took 0.65 s median with the page closed and 0.74 s with it open, rendering at 118 fps, on benchmark lines. In this replies test, 😲 opened 14 of 20 replies and 🥤 appeared in 11, so the emoji prompt needs another look.

**Not tested:**

- The browser's real window picker and a live game window. The picker can't be automated.
- Whether she keeps going when her window is really hidden. In the automated test the browser never reported the page as hidden (0 of 17 turns), even with another tab on top, so that test proves nothing. The Web Worker clock is in place, but frames from a real shared window may still stall while hidden. If so, try `ImageCapture.grabFrame()`.
- Sound: nobody has listened to this flow yet.

**Known issues:**

- One reply in about 12 screen turns stalled 4.35 s and had nothing speakable, so only her face changed. The bridge now logs raw replies to diagnose repeats.
- She often gets the round wrong, such as saying South on East frames.

### Character card and memory

Done. Measured on 2026-11-03: 16 real game-frame changes in the live page, picture change to audio leaving the page, in close to a best case, with no game running.

| Median (p90) | Change noticed | Face changes | First sound |
|---|---|---|---|
| Before the card and short openings | 0.06 s (0.08 s) | 0.44 s (0.58 s) | 1.85 s (2.25 s) |
| With them | 0.05 s (0.07 s) | 0.49 s (0.70 s) | **1.66 s (1.84 s)** |

- `characters/deepseek-chan.json`: the default card. Panel edits go to `companion-data/character.json`, and Reset deletes them.
- `speech/prompts.py`: adds the emoji rules and summary format the bridge depends on, so a card can't break them. Each message also lists her recent emoji to avoid. Across 16 screen replies she used 24 different emoji, and no opener more than twice.
- `speech/memory_store.py`: the last 16 messages word for word, a running summary, and up to 30 facts, saved in `companion-data/memory.json`. A background request updates them after 3 things you say or 8 exchanges, so it never delays a reply. Facts come only from what you say, never from her comments or the screen.
- `speech/llm.py`: providers changed through the day, with DeepSeek's first word taking 7-13 s at one point on default routing. A first word later than 1.5 s moves to the fallback.
- `speech/provider_check.py`: at startup, and from the panel's Check again button, looks up OpenRouter's reported latency and throughput from the last 30 minutes, then routes to the best-scoring provider. The score combines median, p90 and streaming speed, and near ties go to the cheaper one. These figures cover all of OpenRouter's users and request types, so they aren't a measurement from this machine or of image requests. The panel shows the choice and what actually answered each reply.

**Not tested:** how short openings sound; a real stall switching models live (unit tests only); memory across a long session, where the summary may lose detail.

### Watching and preparing while she speaks

Done. She keeps reading the screen while she talks and prepares her next line in the background, only changing course at a sentence end. Your typed messages fade her voice instead. `web/src/companion/pacing.ts` holds the rules as a pure function, with Vitest tests (`npm test` in `web/`). Only sentences that were heard get remembered, through `POST /companion/commit`.

Measured on 2026-11-04, with no game running and no side-by-side run of the old build:

| Test | Result |
|---|---|
| 16 picture changes at random moments while she talked, change to reaction heard | 4.43 s median, 6.67 s p90, 9.38 s worst. By the old rules I estimate about 9 s at the median |
| Line ready, from the frame being taken | 1.09 s median |
| Sentences overlapping or cut off, without typing | 0 of 21 |
| Typed message while she talked, to her reply starting | 0.71 s, one sentence faded |
| Screen changing every second for 40 s | 7 lines replaced, no overlaps, but she talked almost nonstop |
| Mahjong Soul clip for 90 s at Normal | 6 lines a minute, talking 59% of the time, pauses of about 3.4 s |

**What limits reaction time is how long sentences are.** The median sentence took 3.46 s at 3.5 characters a second, and only about 45% of a generated clip is sound. `.\scripts\start-speech.ps1 -DurationScale 0.7` shortens the median test line from 4.94 s to 3.46 s, and 0.5 to 2.46 s. The default stays at 1 until you've listened: clips are in `.scratch/bench-duration/`.

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
