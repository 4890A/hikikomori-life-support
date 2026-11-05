# Starts the Irodori-TTS server from the local Hugging Face cache, with the voice in settings.json as
# the default. It expects that voice's wav in Irodori-TTS-Server/voices.
# Pass -Model to pick another downloaded checkpoint, e.g. -Model Irodori-TTS-v4.1-Small-MF.
# These environment variables override Irodori-TTS-Server/.env for this process only, so the .env
# file (which may point at another checkpoint) is left alone.
param([string]$Model = 'Irodori-TTS-v4-Small')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')
$voice = (Get-CompanionSettings).voice
if (-not $voice) { throw 'No voice is set in settings.json.' }

$root = Split-Path -Parent $PSScriptRoot
$hub = if ($env:HF_HUB_CACHE) { $env:HF_HUB_CACHE } else { Join-Path $env:USERPROFILE '.cache\huggingface\hub' }
$snapshots = Join-Path $hub "models--Aratako--$Model\snapshots"
$snapshot = Get-ChildItem $snapshots -Directory -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $snapshot) { throw "$Model not found in $snapshots. Download it with: hf download Aratako/$Model" }

$env:IRODORI_CHECKPOINT = Join-Path $snapshot.FullName 'model.safetensors'
$env:IRODORI_DEFAULT_VOICE = $voice
$env:IRODORI_PRELOAD = 'true'
$env:HF_HUB_OFFLINE = '1'

Set-Location (Join-Path $root 'Irodori-TTS-Server')
uv run --no-sync python -m irodori_openai_tts --host 127.0.0.1 --port 8088
