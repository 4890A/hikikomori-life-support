# Starts the Irodori-TTS server from the local Hugging Face cache with your voice as the default.
# Pass -Model to pick another downloaded checkpoint, e.g. -Model Irodori-TTS-v4.1-Small-MF.
# These environment variables override Irodori-TTS-Server/.env for this process only, so the .env
# file (which may point at another checkpoint) is left alone.
param([string]$Model = 'Irodori-TTS-v4-Small')
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$hub = if ($env:HF_HUB_CACHE) { $env:HF_HUB_CACHE } else { Join-Path $env:USERPROFILE '.cache\huggingface\hub' }
$snapshots = Join-Path $hub "models--Aratako--$Model\snapshots"
$snapshot = Get-ChildItem $snapshots -Directory -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $snapshot) { throw "$Model not found in $snapshots. Download it with: hf download Aratako/$Model" }

$env:IRODORI_CHECKPOINT = Join-Path $snapshot.FullName 'model.safetensors'
$env:IRODORI_DEFAULT_VOICE = 'my-voice'
$env:IRODORI_PRELOAD = 'true'
$env:HF_HUB_OFFLINE = '1'

Set-Location (Join-Path $root 'Irodori-TTS-Server')
uv run --no-sync python -m irodori_openai_tts --host 127.0.0.1 --port 8088
