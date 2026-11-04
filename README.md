# DeepSeek-chan animated mascot

A browser mascot built on the free **DeepSeek-chan** Live2D model: idle motion, natural
blinking, mouse-following gaze, talking (text-to-speech, mic or audio-file lip-sync) and a
set of emotions (happy, excited, embarrassed, flushed, thinking, surprised, sad, love, smug,
dizzy, pout).

![demo frames](docs/demo_strip.png) — full clip: [`docs/demo.mp4`](docs/demo.mp4)

> **Credits** — Illustration & PSD: Kamiya Ryoko (神宫凉子) · Live2D rigging: 霓虹猫_NeonNeko ·
> distributed free by Kamiya Ryoko ([VGen](https://vgen.co/KAMIYA), X @kamiya_ryoko).
> The model files are **not** in this repo (redistribution is prohibited by its terms);
> the setup step extracts them from your downloaded zip. This project only adds animation code.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Node 20+. Put the model zip
(`DeepSeek-chan … PSD.zip`) in the repo root, then:

```powershell
uv run live2dselfrigging         # copies the model out of the zip into web/public/model (ASCII names)
cd web
npm install
npm run dev                      # http://localhost:5179
```

## Speech with emotions (Irodori-TTS)

Type Japanese text with [Irodori emoji](Irodori-TTS/irodori_tts/gradio_emoji_palette.py) in the
**Voice** panel. She says it in the cloned voice, her lips follow the actual audio, and each emoji
triggers its expression at the matching moment. Run these alongside `npm run dev`:

```powershell
.\scripts\start-tts.ps1      # Irodori-TTS server on :8088: v4 Small, your voice (overrides .env for this process only)
.\scripts\start-speech.ps1   # speech bridge on :8089 (lip-sync and expression timing)
```

The bridge uses a precomputed voice file, which saves about 470 ms per request. Create it once with:

```powershell
$env:HF_HUB_OFFLINE = '1'; uv run --project Irodori-TTS-Server --no-sync python scripts\encode_voice.py
```

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
dropdown sets how often. It needs `OPENROUTER_API_KEY`, and shared frames go to OpenRouter, so share only that window. See `docs/companion-plan.md`.

Tests: `$env:PYTHONPATH="speech"; uv run --project Irodori-TTS-Server --no-sync --with pytest python -m pytest speech/test_cues.py`

## Controls

- **Voice**: Irodori-TTS speech with timed expressions (see above); click an emoji to insert it.
- **Emotion buttons** or number keys `1`–`0`.
- **Talk**: *Speak* uses the browser's TTS voice with matching mouth movement; *Lip-flap only*
  animates without sound; *Mic lip-sync* follows your microphone; or pick an audio file.
- **Click** her head for a pat (happy) or the top of her face for a startle; clicking her body
  makes her embarrassed. Reactions return to the previous emotion on their own.
- **6 7** gesture button or key `G` (clip: [`docs/six_seven.mp4`](docs/six_seven.mp4)).
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
