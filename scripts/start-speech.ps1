# Starts the speech bridge (lip-sync, expression timing and companion turns). Uses the TTS server's
# Python environment for torch/transformers and layers the Japanese phonemizer on top, without
# changing that environment.
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$latent = Join-Path $root 'Irodori-TTS-Server\voices\my-voice-latent.pt'
if (-not (Test-Path $latent)) {
    throw "$latent is missing. Create it with: uv run --project Irodori-TTS-Server --no-sync python scripts\encode_voice.py"
}
# A terminal opened before the key was saved doesn't have it yet. Companion turns report it if unset.
if (-not $env:OPENROUTER_API_KEY) { $env:OPENROUTER_API_KEY = [Environment]::GetEnvironmentVariable('OPENROUTER_API_KEY', 'User') }
$env:HF_HUB_OFFLINE = '1'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = Join-Path $root 'speech'
uv run --project (Join-Path $root 'Irodori-TTS-Server') --no-sync --with pyopenjtalk-plus python (Join-Path $root 'speech\server.py')
