# Companion v2: one shared timeline, real turn-taking, memory she uses, and voice input

## Context

She doesn't feel natural yet: she talks too much, her lines all feel alike, she seems to forget things, and there's no room for you. Her saved memory (`companion-data/memory.json`) and the earlier measurements show why.

| Problem | Evidence | Cause |
|---|---|---|
| Hardly any pauses | 59% talk time and about 6 lines a minute at Normal; pauses of about 3.4 s | The wait after a line is only 0.4-3 s. Her next line is prepared during the current one. Nothing ever decides "nothing worth saying" |
| Every line is the same kind | The prompt asks for a one-line reaction (一言反応) of 15-40 characters every time | No questions, follow-ups, opinions or callbacks, so you're given nothing to answer |
| No sense of memory | History is 8 copies of `（画面を見て反応して）` ("react to the screen") plus her own lines. **0 facts** after a whole session. The summary is generic | The model never sees what was on screen when she spoke. Facts come only from typed words. Nothing makes her bring up the past |
| Wrong details | "Three tiles on the panda's head", the wrong round | She writes straight from the image with no looking step, and old frames aren't kept |
| One slot for "next line" | Your words just replace whatever's queued | No priorities, no staleness, no listening state, no waiting for your answer |

**Your choices:** always listening with a push-to-talk switch, about a third of the time talking at Normal, looking before speaking (about +0.3 s and roughly twice the API cost), and aizuchi after you speak.

**Goal:** she reacts to real moments, then pauses. She asks you things and waits for an answer, and brings up earlier moments and past sessions. Voice works hands-free, and talking to her never derails her watching the screen. The aim is the feel of watching with a friend, not running commentary.

## The system at a glance

```
Browser                                              Bridge (:8089)
 ScreenWatcher --change--> FLOOR MANAGER --look/reply/beat--> /companion/turn ---> TIMELINE ----> session log (.jsonl)
 Mic (speech.cpp realtime) -> floor events   (who may speak, when;   (acts, prompts,    |  seen / heard / said      |
 PTT key (bridge SSE)    -> floor events      intent queue, pacing)    look-first)      v                           v
 SpeechPlayer <------------- segments, observations, "declined" -------  MEMORY: today, episodes, facts about you, her bits
```

All four parts read and write one **timeline** of what happened, so prompts, memory and tuning all see the same story.

## 1. The timeline (bridge, new `speech/timeline.py`)

- **Events, with times:** `seen` (her note on the screen, plus how interesting it was), `heard` (your words, including short "うん"s, with language and whether typed or spoken), `said` (only the sentences that played, with a cut-off marked 「（途中で止めた）」 "(stopped partway)"), `declined` (she looked and chose silence), and `session` start and end.
- **Replaces the fake user/assistant pairs** in `memory.history`. The prompt gets the last ~6 minutes, up to 30 events, as one log with relative times: `- 40秒前 見た: 相手がリーチ` ("40 s ago, seen: the opponent called riichi").
- **Written to `companion-data/sessions/<start>.jsonl`**, along with timings and the floor manager's decisions and reasons. This feeds memory and the tuning report, and helps with debugging. It holds text only: no images, no audio.
- **`PendingTurns` → commit** keeps working as now. Only heard sentences become `said` events.

## 2. Turn-taking: floor manager, intents and pacing (browser, `floor.ts` replaces `pacing.ts`)

A pure `decide(state, now)` function with Vitest tests, like `nextAction()` today.

**Floor states:**
- **quiet** and **she's talking**, as now.
- **you're talking:** from VAD speech start until the end of your speech, plus 0.8 s.
- **waiting for you:** 6 s after a line ending in ？, extended while you speak.

**Intents** replace the single "upcoming" slot. Only one unprompted line is generated at a time, and a reply to you cancels it.

| Intent | From | Priority | Goes stale after |
|---|---|---|---|
| reply | Your words, typed or spoken | 100 | 20 s |
| moment | A big screen change (≥12%) | 80 | 3 s |
| comment | Screen interest building up | 50 | 8 s |
| beat | Greeting, idle chat, callback, follow-up | 20 | 30 s |

**Rules:**
1. **You come first.** If you talk for 0.6 s or more while she's speaking, and it isn't just a backchannel like 「うん」「へえ」 or "yeah", she stops:
   - If her current sentence ends within 0.5 s, she finishes it. Otherwise her voice fades over 0.15 s.
   - While you talk she doesn't start new lines.
   - A short 「うん」 from you never interrupts her. It's just logged as `heard`.
2. **She replies when you finish.** Waiting screen lines are dropped. If something big happened while you talked, it goes into the reply's context, so she can say 「あ、話してる間に勝ってる！」 ("Oh, you won while we were talking!"). Watching continues the whole time, so the flow isn't lost.
3. **After she asks a question, she waits for your answer** for 6 s. Only a big moment can break in, and only after 2 s. If you stay quiet, she drops the question and doesn't nag.
4. **She breathes between lines.** The gap is `base + 0.4 × the last line's length`, multiplied by a random 0.8-1.3. A big moment can shorten it, to no less than 0.6 s.
5. **A talk-share governor** tracks how much of the last 90 s she spent talking:
   - Under target, a moderate change can prompt a comment.
   - Over target, only big moments can.
   - Over 1.3 times the target, she only replies to you.
6. **No monologues.** After 2 unprompted lines in a row without you saying anything, the next gap doubles.
7. **She prepares ahead only when it pays off:** for big moments and replies. Comments start generating so they're ready as the gap ends, not straight after her line.

**Default settings, all adjustable in the panel:**

| Preset | Target talk time | Base gap | Idle chat when the screen is still | Pause after declining to speak |
|---|---|---|---|---|
| Quiet | 15% | 4 s | Every 2-4 min | 8 s |
| **Normal** | **33%** | **2.5 s** | Every 45-90 s | 5 s |
| Chatty | 45% | 1.2 s | Every 25-45 s | 3 s |

- **Unanswered idle questions:** after 2 with no answer from you, idle chat halves its rate until you speak.
- **Gaps within a line:** the pause between sentences follows punctuation, a little longer after ！ and ？. That's a small change in `speech.ts`.

## 3. Look first: observe, decide, then speak, in one streamed request

- **What she writes** for a screen turn, in this order:
  - `見たもの:` what she sees, in 20 characters or less, and only what's visible.
  - `気になる度: 0-3` how interesting it is.
  - `セリフ:` her line.

  The bridge streams only the line part to TTS. If the interest is below the governor's current bar, it **stops the request early**: no line, no TTS. It records `seen` plus `declined`.
- **Background notes:** when the screen changed but she isn't allowed to talk, at most every 10 s, she writes a note without a line. The timeline, and so her memory, keeps up with what happened while she was quiet.
- **Replies to you** carry the latest frame while you're sharing, so 「これ何？」 ("What's this?") works. If that adds more than 0.3 s before her first word, the frame is attached only when you say words like これ/それ/あれ/画面, "this" or "what's".
- **Parser:** `ReplyParser` in `speech/cues.py` already separates the spoken part from a summary marked `[[状況]]`. It moves to these labels instead, tolerating models that skip a label. A reply with no `セリフ` counts as declined.
- **The latency cost**, about 0.2-0.4 s, is measured in phase A. If big moments get too slow, they switch to line first, note second, which is today's order.

## 4. Prompts (`speech/prompts.py`, rewritten)

**System prompt**, which is stable so providers can cache it:
- **Her character card,** as now.
- **New: how to be a good watching buddy:**
  - Don't narrate everything. Pick up only changes and surprises.
  - Use a different kind of line each time.
  - If you speak, answer that first.
  - Don't assert numbers, tiles or names you can't see clearly.
  - Bring up things said before only now and then.
  - Staying quiet is fine.
  - You may speak English. She answers in Japanese, since her voice is Japanese-only, with English words in katakana.
- **Emoji rules,** as now, but short reactions may use just 1 emoji.

**Each turn's message**, which changes every time:
- **Now:** the time, and how long you've been together today.
- **Her memories:** facts about you, today so far, last time, and any matching memories.
- **The timeline.**
- **What's happening:** for example, waiting for your answer, or you just spoke.
- **This turn's job:** the act and the length, for example 「今回の役目: 質問で。10〜30文字」 ("This turn: ask a question, 10-30 characters").
- **The output format,** and the image when there is one.

**Acts,** picked by new `speech/acts.py` (pure, with tests) from the intent, recent acts, whether she's waiting for you, and what memory matches:

| Act | Used for | Length |
|---|---|---|
| リアクション Reaction | moment | 5-15 characters |
| 感想 Opinion / ツッコミ Teasing / 予想 Prediction | comment | 15-35 |
| 質問 Question | comment, beat | 10-30. Never while waiting for an answer. At most 1 in 3 lines |
| 返事 Reply | reply | 15-60, with a question back about 30% of the time |
| 思い出話 Callback | comment or beat when a memory matches | 20-50. At most one every 3 min |
| 雑談 Small talk, あいさつ Greeting, つなぎ Follow-up | beat | 15-50 |

- **Variety:** no act three times in a row.
- **Length rules move out of the card:** the card's 15-40 character and short-opening rules are removed from `characters/deepseek-chan.json`, and the act sets the length instead. A card you've already edited in `companion-data` keeps its own rules, so the panel will warn about them.

## 5. Memory she uses (`speech/memory_store.py` v2)

| Layer | What | Updated | In every prompt |
|---|---|---|---|
| Recent | The last ~6 min of timeline | Live | Yes |
| Today so far | 150-character summary of this session | Every 4 min or 20 events, in the background | Yes |
| Episodes | One per session: date, title, summary, 1-3 highlights, apps or games seen | At session end | The latest one, plus up to 2 that match the current screen or your words, by word overlap |
| Facts about you | Up to 40, each marked "you said it" or "guess" | Every 3 things you say. Guesses only from repeated patterns, like a game you play across 3 sessions | Up to 12 |
| Her bits | Nicknames she gave, promises, opinions, running jokes (up to 15) | At session end | Yes, so she stays consistent |

- **Greeting beat:** at session start it gets the time since you were last here and the last episode, for example 「おかえり！昨日の麻雀のリベンジ？」 ("Welcome back! Revenge for yesterday's mahjong?"). This is the clearest signal that she remembers.
- **When a session ends:** the Stop button, closing the page (`sendBeacon` to `/companion/session/end`), the bridge shutting down, or 15 min with no activity. An unfinished session is wrapped up the next time she starts, from its `.jsonl` log.
- **Migration:** the current summary becomes the first episode, facts carry over, and the placeholder history is dropped.
- **Panel:** shows episodes and facts, with forget and clear.
- **Clearing memory** also deletes the session logs.

## 6. Voice input

- **Engine:** the same speech.cpp server serves TTS, recognition and voice detection together:

  ```
  speech serve irodori-tts-mf qwen3-asr-0.6b silero-vad
  ```

  It offers OpenAI-style live transcription over a WebSocket at `/v1/realtime`, with built-in voice detection. That gives the start and end of your speech, the text as you say it, and the final text.
  - **The default model, `qwen3-asr-0.6b`,** handles Japanese and English.
  - **`reazonspeech-v2`** is Japanese only and may be more accurate. Both get benchmarked on your voice in phase D, and `settings.json` gains `asrModel`.
  - **`setup.ps1`** pulls the extra models, about 0.85 GB.
- **Browser** (new `web/src/companion/mic.ts`):
  - `getUserMedia` with echo cancellation, noise suppression and automatic gain.
  - An AudioWorklet converts to 16-bit PCM and streams it to `/asr`. That's a new WebSocket proxy in `web/vite.config.ts` to `ws://127.0.0.1:8088/v1/realtime`, so it's same-origin and needs no CORS flag.
  - The text so far shows in the panel, labelled 「聞いてる: …」 ("listening: …").
- **Push-to-talk switch:** the bridge's existing 60 Hz desktop stream (`speech/desktop.py`) adds the state of a key, read with `GetAsyncKeyState`, so it works while the game has focus.
  - In push-to-talk mode, audio is only sent while the key is held.
  - Releasing the key ends what you said.
- **Her own voice:** browser echo cancellation, plus a bridge check that drops text closely matching what she said in the last 4 s. Both sides are compared as kana readings through pyopenjtalk, which the bridge already has.
  - With speakers, game audio can still trigger it, which is what push-to-talk is for.
- **Aizuchi:** about 8 short clips, such as うん, うんうん, へえ, なるほど and あー, are made in her voice with lip tracks at startup and cached.
  - She plays one about 0.3 s after you finish speaking for 1.2 s or more, about half the time and never twice in a row, while the reply is generated.
- **One server or two:** if one server makes recognition wait behind TTS by more than 0.3 s, recognition moves to a second speech.cpp process on :8090.

## 7. Tuning tools, because tuning is the hard part

- **`scripts/session_report.py`** reads a session `.jsonl` and reports:
  - talk share, lines a minute and the spread of gaps
  - the mix of acts, how often she declined, and repeated lines (by character overlap)
  - reply delay, barge-ins, dropped echoes, and estimated cost per hour
- **`scripts/replay.ps1`** with Node over the Chrome DevTools protocol, the pattern from the gaze tests:
  - opens a throwaway Chrome and feeds a local video as the shared window
  - injects scripted lines of yours at set times, as typed or transcribed text
  - runs N minutes at given settings, then prints the report

  This means prompts and timings can be compared without playing yourself.
- **Panel:** a live talk-share meter, the current floor state, the next intent and why, and the act chosen. Sliders set the target talk time and base gap, saved in `localStorage`.

## Build order (each phase works on its own)

| Phase | Delivers | Can be tested with |
|---|---|---|
| **A. Timeline + prompts** | timeline.py, session log, acts.py, look-first parser, prompt rewrite, card rules moved, session report | Typed chat and the replay tool on the mahjong clip |
| **B. Memory v2** | Today summary, episodes, facts, her bits, greeting, matching memories, migration, panel | Two sessions in a row; prompt preview |
| **C. Floor manager** | floor.ts (talk share, gaps, waiting for you, idle beats, background notes, cooldowns), director rewired, live meters and sliders | Replay at each preset; Vitest |
| **D. Voice** | ASR and VAD in speech.cpp, mic.ts, `/asr` proxy, push-to-talk key, barge-in, echo filter, aizuchi, ASR benchmark | Your mic, with headphones and with speakers |

## Files

- **Bridge:**
  - `speech/companion.py`: turn kinds `look`, `observe`, `reply` and `beat`, plus `POST /heard` and `/session/start`, `/session/end`.
  - `speech/prompts.py` (rewritten), `speech/cues.py` (the parser), `speech/memory_store.py` (v2), `speech/character.py`, `speech/desktop.py` (key state).
  - New: `speech/timeline.py`, `speech/acts.py`, `speech/echo.py`.
- **Web:**
  - New: `web/src/companion/floor.ts` and its test, replacing `pacing.ts`, and `web/src/companion/mic.ts`.
  - Changed: `director.ts`, `web/src/anim/speech.ts` (stopping at a sentence end, aizuchi clips, punctuation gaps), `ui.ts`, `turnMonitor.ts`, `web/vite.config.ts`.
- **Scripts:** `scripts/start-tts.ps1` (serve ASR and VAD), `setup.ps1` and `scripts/common.ps1` (`asrModel`), new `scripts/session_report.py` and `scripts/replay.ps1`.
- **Card and docs:**
  - `characters/deepseek-chan.json`: length rules move out.
  - `README.md`: voice input, push-to-talk, and privacy (mic audio goes only to local speech.cpp, and session logs hold text only).
  - `docs/companion-plan.md`: results.

**Reused as they are:**
- `ScreenWatcher` in `screen.ts`.
- `SpeechPlayer` in `speech.ts`: prepare, play, switch, fade, cancel and commit.
- The worker clock in `clock.ts`.
- Emoji cues and `StreamSegmenter` in `cues.py`.
- `synthesize_segment` in `synthesis.py`.
- `stream_reply` with its fallback, and `provider_check`.
- The desktop event stream in `desktop.py`.
- `turnMonitor`.

## Verification

**Unit tests:**
- `floor.decide()`: yielding to you, backchannels, waiting for an answer, the governor and the no-monologue limit.
- Picking acts.
- Rendering the timeline.
- Parsing the look-first output while it streams.
- Memory migration.
- Echo similarity.

**Replay on the mahjong clip for 5 min at Normal:**
- Talk share of 28-38%, against 59% today.
- Median gap between her lines of at least 4 s.
- No act in more than 40% of lines, and no opening repeated back to back.
- She declines at least once a minute in quiet stretches.
- Estimated cost per hour.

**Typed conversation:**
- She answers what you said, then waits 6 s after her question, with no screen comment in that time.
- She mentions something from earlier in the session.

**Memory:**
- After a session where you say 5 things about yourself, they appear as facts.
- After restarting the bridge, her greeting mentions the last session.
- The prompt preview shows what she remembers.

**Voice:**

| Target | Measure |
|---|---|
| Aizuchi | 0.5 s or less after you finish |
| Her reply's first audio | 2.0 s median or less after you finish |
| Stopping when you talk over her | 0.4 s or less |
| A short 「うん」 from you | Never stops her |
| Her own voice heard as you | 0 times with headphones; counted with speakers |
| Push-to-talk | Works while a game has focus |
| Recognition accuracy | About 20 of your phrases in Japanese and English, for both models |

**Latency regression:** screen big moment to first sound, against 1.66 s today. Target 2.0 s or less with look-first.

## Risks

- **Following the format:** a flash model may not stick to the look-first labels. The parser is tolerant and tested, and a missing line counts as declined.
- **Echo cancellation:** whether Chrome's echo cancellation on Windows removes the page's own audio needs checking. Game audio from speakers isn't cancelled, which is what push-to-talk is for.
- **GPU sharing:** speech.cpp may make recognition wait behind TTS, in which case recognition gets its own process.
- **Cost:** about twice today's cost is an estimate, and the report measures it.
