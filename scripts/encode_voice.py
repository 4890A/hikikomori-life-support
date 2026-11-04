"""Precomputes a voice's reference latent, so the TTS server doesn't re-encode the wav per request.

Re-encoding takes about 470 ms on an RTX 4070, far longer than sampling with the MeanFlow model.
The server picks the .pt file up as a new voice id. The settings match how the runtime encodes a
wav reference by default. Assumes the clip fits the checkpoint's reference limit: the server trims
a longer wav before normalizing it, so normalization would differ for such a clip.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from irodori_tts.codec import DACVAECodec
from irodori_tts.inference_runtime import _load_audio

ROOT = Path(__file__).resolve().parent.parent
VOICES = ROOT / "Irodori-TTS-Server" / "voices"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", default="my-voice", help="Wav name in Irodori-TTS-Server/voices")
    args = parser.parse_args()

    source = VOICES / f"{args.voice}.wav"
    target = VOICES / f"{args.voice}-latent.pt"
    device = "cuda" if torch.cuda.is_available() else "cpu"
    codec = DACVAECodec.load(device=device, dtype=torch.float32)

    wav, sample_rate = _load_audio(source)
    latent = codec.encode_waveform(
        wav.unsqueeze(0),
        sample_rate=int(sample_rate),
        normalize_db=-16.0,
        ensure_max=True,
    ).cpu()
    torch.save(latent, target)
    print(f"{source.name}: {wav.shape[1] / sample_rate:.1f}s -> {target.name}, latent shape {tuple(latent.shape)}")


if __name__ == "__main__":
    main()
