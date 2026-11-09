# Live2D screen companion

A Live2D character who watches a window you share, talks about what's happening in Japanese, and answers what you type, with her voice, face and lips in sync. She runs on your own PC, apart from the LLM that writes her replies. It works on games, video, or whatever else is on screen.

> **Character credits:** DeepSeek-chan's illustration and PSD by Kamiya Ryoko (神宫凉子), Live2D rigging by 霓虹猫_NeonNeko, distributed free by [Kamiya Ryoko](https://vgen.co/KAMIYA). This project isn't affiliated with them or with DeepSeek. Her files aren't in this repository, as their terms don't allow reposting. [See who made what.](THIRD_PARTY.md)

## Setup

**You need:** Windows 10 or 11, a GPU with Vulkan support, about 10 GB of free disk space, and [Git](https://git-scm.com/download/win). An NVIDIA GPU makes lip sync a little faster. It's been tested on one PC with an RTX 4070, so other hardware is unproven: please report what you find.

**Get ready before you start:**

- **Her model:** download the free zip from [the creator's page](https://vgen.co/KAMIYA/product/deepseek-chan-deepseek-free-live2d-model-layered-psd-psd/1c55a71a-2747-4616-819d-2dc0a934089d) into your Downloads folder. You can also do this when setup asks.
- **A voice recording:** a WAV file of one person speaking clearly for 10-60 s. She speaks in a voice cloned from it. Only use a voice you have the right to use: Irodori-TTS forbids cloning someone without their consent.
- **An OpenRouter key (optional):** get one from [openrouter.ai/keys](https://openrouter.ai/keys) and add a few dollars of credit. She costs roughly 4 cents an hour while she's talking. Without a key, she can only speak what you type in the Voice panel.

Then open PowerShell and run:

```powershell
git clone https://github.com/4890A/hikikomori-life-support
cd hikikomori-life-support
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

The first run downloads 3-8 GB, depending on your GPU, so it can take a while. It's safe to stop and run again, as finished steps are skipped. Setup goes through these steps:

| Step | What happens | Needs you? |
|---|---|---|
| 1. Check your PC | Checks disk space, and offers to install `uv` (Python) and Node with `winget` if they're missing | Say yes to installing them |
| 2. Python packages | Installs PyTorch and the speech bridge's packages into `.venv`. NVIDIA PCs get the GPU build, others a smaller CPU build | |
| 3. Voice engine | Downloads [speech.cpp](https://github.com/nyosegawa/speech.cpp) into `speech-cpp/` and checks it, then the Irodori-TTS voice model (1.9 GB) | |
| 4. Lip-sync model | Downloads a phoneme model (0.35 GB) from Hugging Face | |
| 5. Her model | Finds the zip in this folder or your Downloads, and copies what she needs into `web/public/model/`. If it isn't there, setup opens the download page and waits | Download the zip |
| 6. Her voice | Opens the `voices` folder and waits for your WAV file, then makes her voice from it | Put your WAV file in `voices` and press Enter |
| 7. Web app | Installs and builds her page | |
| 8. OpenRouter key | Asks for your key, which stays hidden as you paste it and is saved to your Windows user account. Press Enter to skip | Paste your key |
| 9. Voice test | Speaks one line, so problems show up now | |

**Setup options:** `-ZipPath <file>` uses a model zip from somewhere else, `-SkipKey` skips the key question, and `-CpuOnly` uses the smaller CPU build of PyTorch even with an NVIDIA GPU.

### Starting and stopping her

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

This starts the voice engine, the speech bridge and her page, and opens http://localhost:5179 once she's ready, which takes a few seconds while her voice warms up. Press Ctrl+C in that window to stop everything. Add `-NoBrowser` to start her without opening the browser.

### If something goes wrong

Run `powershell -ExecutionPolicy Bypass -File .\doctor.ps1`. It checks each part, changes nothing, and suggests a fix for anything wrong. Each service writes a log in `logs/`. Common problems:

- **"Port ... is already in use":** she may still be running from before. Close that PowerShell window, or restart your PC.
- **"Setup is not finished":** run `setup.ps1` again. It picks up where it stopped.
- **The voice step keeps failing:** the file must be a real WAV, not an MP3 renamed to `.wav`, and at most 120 s long.
- **Speech is very slow:** `doctor.ps1` says whether it found a Vulkan GPU. Updating your graphics driver usually fixes it.

### Updating and uninstalling

To update, run `git pull`, then run `setup.ps1` again.

To uninstall, delete this folder, then remove what setup put elsewhere:

- **speech.cpp's model:** `%LOCALAPPDATA%\speech.cpp`.
- **The lip-sync model:** in `%USERPROFILE%\.cache\huggingface`.
- **uv's download cache:** several GB of Python packages. Run `uv cache clean` to clear it.
- **Your key:** run `[Environment]::SetEnvironmentVariable('OPENROUTER_API_KEY', $null, 'User')`.

`uv` and Node, if setup installed them, can be removed from Windows' installed apps.

## Using her

Open http://localhost:5179, click **Start Companion** and pick a window.

**Privacy:** frames from the window you share, and what she remembers about you, are sent to OpenRouter and its model providers. Share only the window you want her to see. Her memory, your character edits and a text log of each session (what she noted on screen, what you said and what she said, with no images or audio) stay in `companion-data/` on your PC, and you can delete them from the panel.

- **Her character:** the **Character** section edits her personality, speaking style and rules, and shows the full prompt. The default is `characters/deepseek-chan.json`.
- **Her memory:** she learns facts about you from what you say, remembers each session once you stop her, and greets you with what happened last time. The **Memory** section lists what she knows about you: click a fact to rewrite it, or add your own. Facts you wrote or edited are kept exactly as you wrote them. It also lists past sessions and things she said about herself, each of which you can forget.
- **How often she talks:** the Quiet, Normal and Chatty setting aims for her to be talking about 25%, 45% or 60% of the time. She pauses after each line, longer after a longer one, waits for your answer when she asks you something, and slows down after a few lines in a row with nothing from you. She glances at the screen every few seconds, even while talking, and remembers what she sees. In the pauses her face reacts to it, with the odd short sound like 「へえ」. When nothing on screen is worth a remark she stays quiet. The overlay shows how much she has been talking.
- **Where she looks:** she follows your mouse anywhere on the desktop, and looks at the window you share while she's reacting to it. If you share a whole screen or a tab she can't tell where it is, so pick a side under **Behaviour**. Drag her window around and she sways with it, hair and all. These positions stay on your PC.
- **Her voice:** to change it, run `.\scripts\add-voice.ps1 another-clip.wav`, using only a voice you have the right to use.
- **Other settings:** `settings.json`, which you can create next to this file, takes `steps`, `durationScale`, `voice` and `model`. A lower `durationScale`, such as 0.7, shortens her lines and helps her react sooner.

## How it fits together

| Port | Service | Does |
|---|---|---|
| 5179 | Web app (`web/`) | Her page, screen watching and when she speaks |
| 8089 | Speech bridge (`speech/`) | Replies from the LLM, lip sync, expressions and memory |
| 8088 | [speech.cpp](https://github.com/nyosegawa/speech.cpp) | Irodori-TTS voice on Vulkan |

For development, run `.\scripts\start-tts.ps1`, `.\scripts\start-speech.ps1` and `npm run dev` in `web/`.

**Tuning how she talks:** `scripts/session_report.py` sums up a session from its log: how much of the time she talked, the gaps, the kinds of line, how often she stayed quiet, repeats, delays and cost. `.\scripts\replay.ps1 -Video clip.mp4 -Minutes 3 -Say '20=what is this?'` plays a video to her as if it were a shared window, in a throwaway Chrome, with lines of yours at set times, then prints that report, so you can compare prompt and timing changes without playing. Start her first, ideally with `$env:COMPANION_DATA_DIR` set to a scratch folder so replays stay out of her memory. The design is in `docs/companion-v2-plan.md`.

**Before a release:** run the tests below, then run `setup.ps1` from a fresh clone and check that she speaks and reacts.

## Speech details
How the timing works (`speech/`):

1. **Segments** (`cues.py`): long text splits at sentence ends only. The bridge synthesizes each
   segment whole, because short inputs get an overestimated duration, filled with silence and
   hallucinated sounds, and the server caps one synthesis at 30 s.
2. **Alignment** (`analysis.py`): a phoneme recognizer
   (`prj-beatrice/japanese-hubert-base-phoneme-ctc-v4`) runs on the generated audio, one voiced
   stretch at a time. The text between emoji is converted to phonemes (`pyopenjtalk`) and
   force-aligned to the recognizer's output, which gives each emoji's position a real timestamp.
3. **Expressions** (`cues.py`): an emoji right after text colors that text (`楽しかったよ😊` runs from
   the sentence start until speech resumes). An emoji after punctuation and before text
   (`…😮‍💨まぁ`) starts at the sound performed in the gap, or at the next speech. Later cues cut off
   earlier ones. `EMOJI_EMOTIONS` holds the emoji-to-emotion map; voice-only emoji (📞 ⏸️ 🐢 …) just
   affect the voice.
4. **Lips** (`analysis.py`): loudness sets how open the mouth is and phonemes set its shape, with lips
   closing on m/b/p. The track is precomputed, so the mouth leads the sound by 40 ms.
5. **Playback** (`web/src/anim/speech.ts`): audio is scheduled on the Web Audio clock, and lips and
   cues follow that clock (compensating output latency). Faces fire 0.15 s early and arm poses
   0.45 s early, so they arrive on the words; arm poses are skipped for cues shorter than 1.6 s.

**Companion:** with both scripts and `npm run dev` running, click **Start Companion** and pick the
window to watch. She comments regularly, sooner when more is happening, and answers what you type. The
dropdown sets how often. It needs `OPENROUTER_API_KEY`, and shared frames go to OpenRouter, so share only that window.

**Character and memory:** the panel's Character section edits who she is, shows what she remembers about you, and
previews the full prompt. The default card is `characters/deepseek-chan.json`. Your edits and her memory are saved in
`companion-data/`, which isn't in Git, and her memory is sent to OpenRouter with each reply. The rules her face and voice
depend on are added by `speech/prompts.py`. See `docs/companion-plan.md`.

Tests: `uv run --no-sync pytest`, and `npm test` in `web/`.

## Controls

- **Voice**: Irodori-TTS speech with timed expressions (see above); click an emoji to insert it.
- **Emotion buttons** or number keys `1`–`0`.
- **Talk**: *Speak* uses the browser's TTS voice with matching mouth movement; *Lip-flap only*
  animates without sound; *Mic lip-sync* follows your microphone; or pick an audio file.
- **Click** her head for a pat (happy) or the top of her face for a startle; clicking her body
  makes her embarrassed. Reactions return to the previous emotion on their own.
- **6 7** gesture button or key `G`.
- Toggles for mouse following, idle motion, blinking, outfit (short skirt, glasses, monocle, fang)
  and view presets (full / upper body / face).

## What came with the model vs. what this project adds

**Already in the model zip** (by Kamiya Ryoko / 霓虹猫_NeonNeko):

- The artwork, the rig (`.moc3`, 509 parameters) and the physics (hair, ears, skirt, chest, tail, sleeves).
- Expression art switched by toggle parameters: `> <` eyes, blush, heart eyes, smug eyes, swirl
  eyes, tears, cold sweat, dark face, loading spinner, fang, glasses, monocle.
- 23 `.exp3.json` expression files — each just flips one of those toggles on/off.
- 8 `.motion3.json` motions:
  - `IDLE` — effects-only loop (eye twinkles, tear/sweat flow). **Used** as the base layer.
  - Finger up / down, hand on chest on / off, foxtail grass on / off — ~1 s arm transitions.
    **Used** for the thinking, embarrassed, love and smug arm poses.
  - `脱捕` — a 13 s "tracking lost" idle. Not used.
- A VTube Studio config, where blinking, gaze, talking and expressions come from webcam face tracking.

**Made in this project** (none of this existed in the zip):

| Animation | How |
| --- | --- |
| Idle (breathing, sway, wandering glances, random fidgets: head tilt, ear flick, hum, lean in) | Procedural code, `animator.ts` |
| Blinking (random timing, double blinks, per-emotion rate) | Procedural code, `blink.ts` |
| Looking around / following the mouse | Procedural code, `gaze.ts` |
| Talking: text lip-flap, TTS-synced speech, mic and audio-file lip-sync | Procedural code, `talk.ts` |
| Emotions: happy, excited, embarrassed, flushed, thinking, surprised, sad, love, smug, dizzy, pout | `emotions.ts` — each combines the rig's existing toggles/poses with chosen parameter values, timing, crossfades and its own motion (bounce, tremble, glances, …) |
| Click reactions (head pat, startle, poke) | Code, `main.ts` |
| **"6 7" gesture** | Keyframed motion files `web/public/motions/six_seven.motion3.json` (+ `six_seven.mirror.motion3.json`), generated by `src/live2dselfrigging/motions.py` (`uv run make-motions`), plus `mirrorArm.ts` in the web app. |

The "6 7" gesture: both palms up at waist-to-chest height, hands rising and falling alternately
like a seesaw for 3 cycles, head tilting with the beat, saying "six… se-ven".
The rig cannot be edited (only the compiled `.moc3` is distributed) and its only open posed hand
is on her left (the hand-on-chest arm). So:

- **In the web app**, her right hand is that same left arm drawn by a second, horizontally
  mirrored instance of the model that renders only that arm (`mirrorArm.ts`), driven by
  `six_seven.mirror.motion3.json`. Her own right posed arm is hidden meanwhile.
- **Elsewhere** (e.g. as a VTube Studio hotkey — untested), `six_seven.motion3.json` works on its
  own but falls back to the rig's right finger-up arm, so that hand points instead of showing a palm.
- The elbows stay tucked at her sides under the puffed sleeves (upper-arm `Param62` kept at the
  rigger's own value); swinging the upper arm inward detaches the forearm from the elbow.
  The forearms point out to the sides rather than toward the camera, since the rig's arms only
  rotate in the picture plane.

## How it works

Rendering uses PixiJS 7 + [`pixi-live2d-display-lipsyncpatch`](https://github.com/RaSan147/pixi-live2d-display)
(MIT) with the Live2D Cubism Core 5 (proprietary, free to use, loaded from Live2D's CDN).
The library's built-in focus/blink/breath are disabled; `web/src/anim/` drives the rig instead:

| File | Role |
| --- | --- |
| `animator.ts` | Composes all layers each frame, right before physics runs |
| `emotions.ts` | Emotion definitions: pose targets, procedural motion, gaze bias, blink rate, arm poses |
| `gaze.ts` | Pointer tracking with idle wandering; eyes lead, head follows on springs |
| `blink.ts` | Randomized blinks with occasional double blinks |
| `talk.ts` | Text → syllable track (vowel shapes), Web Speech TTS, mic/audio loudness analysis |
| `motion3.ts` | Small motion3.json player (rigger's arm transitions and FX loop, plus our own gestures) |

Rig notes worth knowing if you extend it:

- Head/body turn through **physics inputs** — `AngleX/Y/Z`, `PositionX/Y/Z`, `LeanInput` — not
  `ParamAngleX` directly (physics overwrites those and also drives hair, ears, skirt, chest).
- Expression overlays are toggle params `key1`–`key13` (`key5` = `> <` eyes, `key7` = blush,
  `key8` = loading spinner, `key4` = heart eyes, …). Arm poses are `Movement1–3`, played via the
  bundled transition motions. The ears are linked to the brows, so lowering brows droops them.
- Running two model instances requires reserving the Cubism Core heap up front
  (`Memory.initializeAmountOfMemory` in `live2d.ts`); otherwise loading the second one moves the
  heap and the first model silently freezes.
- The model needs 49 clipping-mask contexts and Cubism 4.2 multiply/screen colors; `live2d.ts`
  re-initializes the renderer with two mask textures at 2048px, and the lipsyncpatch fork is used
  because the original `pixi-live2d-display` lacks screen-color support (the nose renders black).
