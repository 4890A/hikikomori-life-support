"""Keyframed motions authored for this project, written out as Cubism motion3.json files.

These only use parameters the DeepSeek-chan rig already has; they add no new art or
deformers. Run ``uv run make-motions`` to regenerate ``web/public/motions/``.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "web" / "public" / "motions"
FPS = 30.0

# A keyframe is (time, value) or (time, value, "step") to jump instead of easing in.
Key = tuple


def curve(param: str, keys: list[Key]) -> dict:
    """Builds a motion3 curve with ease-in-out beziers (flat handles) between keyframes."""
    t0, v0 = keys[0][:2]
    segments: list[float] = [t0, v0]
    for key in keys[1:]:
        t1, v1 = key[:2]
        if len(key) > 2 and key[2] == "step":
            segments += [2, t1, v1]
        else:
            third = (t1 - t0) / 3
            segments += [1, t0 + third, v0, t1 - third, v1, t1, v1]
        t0, v0 = t1, v1
    return {"Target": "Parameter", "Id": param, "Segments": [round(x, 4) for x in segments]}


def motion(duration: float, curves: list[dict], loop: bool = False) -> dict:
    segment_count = point_count = 0
    for c in curves:
        s = c["Segments"]
        point_count += 1
        i = 2
        while i < len(s):
            kind = s[i]
            n = 3 if kind == 1 else 1
            segment_count += 1
            point_count += n
            i += 1 + 2 * n
    return {
        "Version": 3,
        "Meta": {
            "Duration": duration,
            "Fps": FPS,
            "Loop": loop,
            "AreBeziersRestricted": True,
            "CurveCount": len(curves),
            "TotalSegmentCount": segment_count,
            "TotalPointCount": point_count,
            "UserDataCount": 0,
            "TotalUserDataSize": 0,
        },
        "Curves": curves,
    }


class SixSevenTiming:
    switch = 0.1  # swap to the posed arms while the forearms are still at rest
    start = 0.45  # first beat
    half = 0.3  # time between beats (one hand up, then the other)
    beats = 6  # 3 full up/down cycles
    stop = start + half * beats
    rest_at = stop + 0.4
    end = rest_at + 0.1


def _arm_curves(fore: str, wrist: str, upper: str, perspective: str, levels: dict, upper_value: float,
                perspective_value: float, up_on_even: bool) -> list[dict]:
    """Forearm/wrist bounce between `levels["up"]` and `levels["down"]`, one keyframe per beat."""
    T = SixSevenTiming
    fk: list[Key] = [(0, 0), (T.switch, 0)]
    wk: list[Key] = [(0, 0), (T.switch, 0)]
    for b in range(T.beats + 1):
        f, w = levels["up" if (b % 2 == 0) == up_on_even else "down"]
        fk.append((T.start + b * T.half, f))
        wk.append((T.start + b * T.half, w))
    fk += [(T.rest_at, 0), (T.end, 0)]
    wk += [(T.rest_at, 0), (T.end, 0)]
    curves = [curve(fore, fk), curve(wrist, wk)]
    for param, value in ((upper, upper_value), (perspective, perspective_value)):
        curves.append(curve(param, [(0, 0), (T.switch, 0), (T.start, value), (T.stop, value), (T.rest_at, 0), (T.end, 0)]))
    return curves


def _switch(param: str) -> dict:
    """Stepped on/off for a posed-arm toggle while the forearm is at rest."""
    T = SixSevenTiming
    return curve(param, [(0, 0), (T.switch, 1, "step"), (T.rest_at + 0.05, 1), (T.end, 0, "step")])


# The open "hand on chest" arm (Movement2) at waist-to-chest height: upper arm lowered so the
# forearm stays level, wrist turned so the fingers point outward and the palm faces up.
OPEN_HAND_LEVELS = {"up": (0.42, -0.5), "down": (0.24, -0.45)}
# Keep the upper arm near the rigger's own value (0.034): the elbow then stays tucked at her
# side under the sleeve. Negative values swing the elbow onto her stomach, detaching the arm.
OPEN_HAND_UPPER = 0.034


def six_seven() -> dict:
    """The "6 7" meme gesture: both palms up in front, hands alternately rising and falling
    like a seesaw at medium height, 3 cycles. Says "six… se-ven" on the first two beats.

    The rig only has an open posed hand on her left (Movement2). Her right posed hands either
    point (Movement3) or hold a foxtail (Movement1). This file keeps the pointing arm as a
    fallback so it works on its own (e.g. in VTube Studio); the web app hides it and draws the
    left open hand mirrored instead, driven by ``six_seven.mirror.motion3.json``.
    """
    T = SixSevenTiming
    curves = _arm_curves("Param60", "Param61", "Param62", "Param59", OPEN_HAND_LEVELS, OPEN_HAND_UPPER, 0.476, up_on_even=True)
    # Fallback right arm: the finger arm at the same height (wrist >= 0 keeps the finger relaxed).
    curves += _arm_curves("Param41", "Param42", "Param36", "Param39", {"up": (0.4, 0.0), "down": (0.25, 0.1)},
                          0.1, 0.322, up_on_even=False)
    curves += [_switch("Movement2"), _switch("Movement3"), _switch("Param40")]
    curves.append(curve("Param43", [(0, 0), (T.switch, 1, "step"), (T.end, 0, "step")]))
    curves.append(curve("Movement1", [(0, 0), (T.end, 0)]))  # no foxtail
    start, half, beats, stop, rest_at, end = T.start, T.half, T.beats, T.stop, T.rest_at, T.end

    # Head tilts toward the raised hand and bobs on every beat; shoulders sway along.
    tilt: list[Key] = [(0, 0), (start - 0.1, 0)]
    bob: list[Key] = [(0, 0), (start - 0.15, 0)]
    for b in range(beats + 1):
        t = start + b * half
        tilt.append((t, 5 if b % 2 == 0 else -5))
        bob.append((t - half / 2, 2) if b else (t - 0.05, 1))
        bob.append((t, -3))
    tilt += [(rest_at, 0), (end, 0)]
    bob += [(rest_at, 0), (end, 0)]
    curves += [curve("AngleZ", tilt), curve("PositionY", bob)]
    curves.append(curve("PositionZ", [(k[0], -0.8 * k[1]) for k in tilt]))

    # Cheeky smirk, raised brows, slightly lidded eyes.
    face = {"ParamMouthForm": 0.5, "EyeSmile": 0.35, "ParamBrowLY": 0.35, "ParamBrowRY": 0.35}
    for param, value in face.items():
        curves.append(curve(param, [(0, 0), (start - 0.15, value), (stop, value), (end, 0)]))
    for param in ("ParamEyeLOpen", "ParamEyeROpen"):
        curves.append(curve(param, [(0, 1), (start - 0.15, 0.85), (stop, 0.85), (end, 1)]))

    # "six" on beat 0, "se-ven" on beat 1.
    s, v = start, start + half
    curves.append(curve("ParamMouthOpenY", [
        (0, 0), (s - 0.08, 0), (s, 0.45), (s + 0.12, 0.08), (v - 0.04, 0), (v + 0.03, 0.55),
        (v + 0.12, 0.2), (v + 0.2, 0.4), (v + 0.32, 0), (end, 0),
    ]))
    curves.append(curve("ParamI", [(0, 0), (s - 0.05, 1), (s + 0.12, 1), (v - 0.05, 0), (end, 0)]))
    curves.append(curve("ParamE", [(0, 0), (v - 0.05, 0), (v + 0.03, 1), (v + 0.3, 1), (v + 0.4, 0), (end, 0)]))

    return motion(round(end, 3), curves)


def six_seven_mirror() -> dict:
    """Her right hand for the web app: the left open-hand arm in opposite phase, rendered by a
    horizontally mirrored second model instance that only draws that arm."""
    T = SixSevenTiming
    curves = _arm_curves("Param60", "Param61", "Param62", "Param59", OPEN_HAND_LEVELS, OPEN_HAND_UPPER, 0.476, up_on_even=False)
    curves.append(_switch("Movement2"))
    return motion(round(T.end, 3), curves)


MOTIONS = {"six_seven": six_seven, "six_seven.mirror": six_seven_mirror}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, build in MOTIONS.items():
        path = OUT_DIR / f"{name}.motion3.json"
        path.write_text(json.dumps(build(), indent=1), encoding="utf-8")
        print(f"wrote {path}")
