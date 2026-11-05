"""Audio side of the speech pipeline: phoneme recognition, forced alignment and lip-sync tracks."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
import pyopenjtalk
import torch
from huggingface_hub import snapshot_download
from transformers import HubertForCTC

from cues import Fragment, Item
from model_source import PHONEME_MODEL, PHONEME_REVISION

SAMPLE_RATE = 16000
TRACK_FPS = 50
MODEL_HOP = 320  # samples per model frame
WINDOW_JOIN_SECONDS = 0.25
WINDOW_PAD_SECONDS = 0.15
WINDOW_MAX_SECONDS = 8.0
# The mouth should move slightly before the sound it makes.
LIP_LEAD_SECONDS = 0.04

VOWELS = "aiueo"
_VOWEL_OF = {"a": "a", "i": "i", "u": "u", "e": "e", "o": "o", "I": "i", "U": "u"}
_OPENNESS = {"a": 1.0, "o": 0.8, "e": 0.7, "i": 0.5, "u": 0.45}
# How far each consonant lets the mouth open, relative to its loudness.
_LIPS_CLOSED = {"m", "my", "b", "by", "p", "py"}
_PHONE_OPENNESS = {"cl": 0.15, "N": 0.3}
_DEFAULT_CONSONANT_OPENNESS = 0.55
# Sound with no recognized phoneme (a laugh, a sigh) opens the mouth moderately.
_NONVERBAL_OPENNESS = 0.6


def _recognition_windows(spans: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    """Voiced stretches joined across short pauses, padded, and capped in length."""
    windows: list[list[float]] = []
    for start, end in spans:
        if windows and start - windows[-1][1] < WINDOW_JOIN_SECONDS:
            windows[-1][1] = end
        else:
            windows.append([start, end])
    out: list[tuple[float, float]] = []
    for start, end in windows:
        position = max(0.0, start - WINDOW_PAD_SECONDS)
        stop = min(duration, end + WINDOW_PAD_SECONDS)
        while stop - position > WINDOW_MAX_SECONDS:
            out.append((position, position + WINDOW_MAX_SECONDS))
            position += WINDOW_MAX_SECONDS
        out.append((position, stop))
    return out


@dataclass
class Analysis:
    audio: np.ndarray
    spans: list[tuple[float, float]]
    open: list[float]
    vowel: str
    speech_start: float
    speech_end: float
    alignment_score: float


class PhonemeModel:
    def __init__(self) -> None:
        path = Path(snapshot_download(PHONEME_MODEL, revision=PHONEME_REVISION))
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = HubertForCTC.from_pretrained(path).to(self.device).eval()
        vocab: dict[str, int] = json.loads((path / "vocab.json").read_text(encoding="utf-8"))
        self.vocab = vocab
        self.labels = {index: label for label, index in vocab.items()}
        self.gap_ids = [vocab[k] for k in ("PAD", "pau", "sil")]

    @torch.no_grad()
    def log_probs(self, audio_16k: np.ndarray, spans: list[tuple[float, float]]) -> np.ndarray:
        """Frame log-probabilities, recognizing each voiced stretch separately.

        Given a whole clip with long pauses the model goes deaf to earlier speech, labelling
        seconds of clear words as blank, while the same audio on its own is recognized fine.
        Everything outside the voiced stretches is treated as blank.
        """
        frames = len(audio_16k) // MODEL_HOP + 1
        out = np.full((frames, len(self.labels)), -20.0, dtype=np.float32)
        out[:, self.vocab["PAD"]] = 0.0
        for start, end in _recognition_windows(spans, len(audio_16k) / SAMPLE_RATE):
            first = int(start * SAMPLE_RATE)
            clip = torch.from_numpy(audio_16k[first : int(end * SAMPLE_RATE)]).to(self.device)[None]
            if clip.shape[1] < MODEL_HOP * 4:
                continue
            log_probs = torch.log_softmax(self.model(clip).logits[0], dim=-1).cpu().numpy()
            offset = first // MODEL_HOP
            count = min(len(log_probs), frames - offset)
            out[offset : offset + count] = log_probs[:count]
        return out

    def target_id(self, phone: str) -> int | None:
        return self.vocab.get(phone)


def fragment_phones(text: str) -> list[str]:
    """Phonemes for a fragment. Unreadable text (Latin words, symbols) simply yields none."""
    normalized = unicodedata.normalize("NFKC", text)
    if not re.search(r"\w", normalized):
        return []
    return [p for p in pyopenjtalk.g2p(normalized).split() if p not in ("pau", "sil")]


def align(log_probs: np.ndarray, targets: list[int], gap_ids: list[int]) -> tuple[np.ndarray, np.ndarray, float]:
    """CTC-style Viterbi alignment. Returns start and end frames per phoneme, and a mean score.

    States alternate gap, phone, gap, phone... Gaps absorb silence and non-speech sounds, so laughs
    and sighs between words don't pull neighbouring phonemes toward them.
    """
    frames, _ = log_probs.shape
    count = len(targets)
    states = 2 * count + 1
    gap = np.logaddexp.reduce(log_probs[:, gap_ids], axis=1)
    emissions = np.empty((frames, states))
    emissions[:, 0::2] = gap[:, None]
    emissions[:, 1::2] = log_probs[:, targets]

    score = np.full(states, -np.inf)
    score[0] = emissions[0, 0]
    score[1] = emissions[0, 1]
    back = np.zeros((frames, states), dtype=np.int8)
    for t in range(1, frames):
        stay = score
        step = np.concatenate(([-np.inf], score[:-1]))
        skip = np.concatenate(([-np.inf, -np.inf], score[:-2]))
        skip[0::2] = -np.inf  # only a phone can follow a phone directly
        stacked = np.stack([stay, step, skip])
        choice = stacked.argmax(axis=0)
        back[t] = choice
        score = stacked[choice, np.arange(states)] + emissions[t]

    state = states - 1 if score[states - 1] >= score[states - 2] else states - 2
    starts = np.zeros(count, dtype=int)
    ends = np.zeros(count, dtype=int)
    total = 0.0
    seen = 0
    for t in range(frames - 1, -1, -1):
        if state % 2 == 1:
            phone = state // 2
            if ends[phone] == 0:  # walking backward, so the first visit is the phone's last frame
                ends[phone] = t + 1
            starts[phone] = t
            total += log_probs[t, targets[phone]]
            seen += 1
        state -= int(back[t, state])
    return starts, ends, float(np.exp(total / max(seen, 1)))


def voiced_spans(audio_16k: np.ndarray, hop: int) -> list[tuple[float, float]]:
    rms = librosa.feature.rms(y=audio_16k, frame_length=hop * 2, hop_length=hop)[0]
    threshold = max(np.percentile(rms, 95) * 0.06, 1e-4)
    active = rms > threshold
    spans: list[tuple[float, float]] = []
    start = None
    for i, on in enumerate(active):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if i - start >= 3:
                spans.append((start * hop / SAMPLE_RATE, i * hop / SAMPLE_RATE))
            start = None
    if start is not None:
        spans.append((start * hop / SAMPLE_RATE, len(active) * hop / SAMPLE_RATE))
    # Bridge tiny dropouts inside a sound.
    merged: list[tuple[float, float]] = []
    for span in spans:
        if merged and span[0] - merged[-1][1] < 0.1:
            merged[-1] = (merged[-1][0], span[1])
        else:
            merged.append(span)
    return merged


def lip_track(
    audio_16k: np.ndarray, log_probs: np.ndarray, labels: dict[int, str], aligned: dict[int, str]
) -> tuple[list[float], str]:
    """Per-frame mouth openness and vowel: loudness drives openness, phonemes the shape.

    Phonemes are what the model heard, falling back to the phoneme the text aligned to at that frame
    (`aligned`, by model frame) where it heard nothing, such as speech under a voice effect.
    """
    hop = SAMPLE_RATE // TRACK_FPS
    frames = int(np.ceil(len(audio_16k) / hop))
    rms = librosa.feature.rms(y=audio_16k, frame_length=hop * 2, hop_length=hop)[0][:frames]
    rms = np.pad(rms, (0, frames - len(rms)))
    loud = np.clip(rms / max(np.percentile(rms, 97), 1e-4), 0, 1) ** 0.6
    loud[rms < max(np.percentile(rms, 97) * 0.05, 1e-4)] = 0

    ids = log_probs.argmax(axis=-1)
    per_track_frame = len(ids) / max(frames, 1)
    openness = np.full(frames, _NONVERBAL_OPENNESS)
    vowels = ["-"] * frames
    phone = None
    last_seen = -1000
    phone_start = 0
    pad = 0
    vowel = "-"
    for f in range(frames):
        frame = min(int(f * per_track_frame), len(ids) - 1)
        k = int(ids[frame])
        label = labels[k] if k != pad else None
        if label is None or label in ("pau", "sil"):
            label = aligned.get(frame)
        if label is not None:
            if label != phone or f - last_seen > 1:
                phone_start = f
            phone = label
            last_seen = f
            if label in _VOWEL_OF:
                vowel = _VOWEL_OF[label]
        # Vowels ring on between the model's sparse labels; after ~0.3s it is no longer speech.
        if phone is None or f - last_seen > TRACK_FPS * 0.3:
            vowels[f] = "a" if loud[f] > 0 else "-"
            continue
        if phone in _VOWEL_OF:
            openness[f] = _OPENNESS[_VOWEL_OF[phone]]
        elif phone in _LIPS_CLOSED:
            # Lips press shut briefly, then release into whatever follows.
            openness[f] = 0.08 if f - phone_start < 4 else _DEFAULT_CONSONANT_OPENNESS
        else:
            openness[f] = _PHONE_OPENNESS.get(phone, _DEFAULT_CONSONANT_OPENNESS)
        vowels[f] = vowel

    track = np.round(np.clip(loud * openness, 0, 1), 3)
    shift = int(LIP_LEAD_SECONDS * TRACK_FPS)
    track = np.concatenate((track[shift:], np.zeros(shift)))
    vowels = vowels[shift:] + ["-"] * shift
    return track.tolist(), "".join(vowels)


def analyze(model: PhonemeModel, audio: np.ndarray, sample_rate: int, items: list[Item]) -> Analysis:
    """Aligns items to the audio (filling in fragment times) and builds the lip-sync track."""
    audio_16k = librosa.resample(audio, orig_sr=sample_rate, target_sr=SAMPLE_RATE)
    spans = voiced_spans(audio_16k, SAMPLE_RATE // TRACK_FPS)
    log_probs = model.log_probs(audio_16k, spans)
    frame_seconds = MODEL_HOP / SAMPLE_RATE

    fragments = [item for item in items if isinstance(item, Fragment)]
    targets: list[int] = []
    owners: list[Fragment] = []
    for fragment in fragments:
        fragment.phones = [p for p in fragment_phones(fragment.text) if model.target_id(p) is not None]
        for phone in fragment.phones:
            targets.append(model.target_id(phone))
            owners.append(fragment)

    score = 0.0
    aligned: dict[int, str] = {}
    if targets:
        starts, ends, score = align(log_probs, targets, model.gap_ids)
        for i, fragment in enumerate(owners):
            start, end = float(starts[i] * frame_seconds), float(ends[i] * frame_seconds)
            if i == 0 or owners[i - 1] is not fragment:
                fragment.start = start
            fragment.end = end
            for frame in range(starts[i], ends[i]):
                aligned[frame] = model.labels[targets[i]]

    open_track, vowel_track = lip_track(audio_16k, log_probs, model.labels, aligned)
    return Analysis(
        audio=audio,
        spans=spans,
        open=open_track,
        vowel=vowel_track,
        speech_start=spans[0][0] if spans else 0.0,
        speech_end=spans[-1][1] if spans else len(audio) / sample_rate,
        alignment_score=score,
    )
