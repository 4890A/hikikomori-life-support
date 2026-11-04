# Benchmarks the running TTS server plus lip alignment. Uses the same Python environment as the
# speech bridge, so the alignment model loads and runs as it does in production.
#   .\scripts\start-tts.ps1
#   .\scripts\bench-tts.ps1 -Label v4-small-12 -Voice my-voice-latent -Set num_steps=12,t_schedule_mode=sway
param(
    [Parameter(Mandatory)][string]$Label,
    [int]$Repeats = 8,
    [string]$Url = 'http://127.0.0.1:8088',
    [string]$Voice = 'my-voice',
    [string[]]$Set = @()
)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$env:HF_HUB_OFFLINE = '1'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = Join-Path $root 'speech'
$options = @($Set | ForEach-Object { '--set', $_ })
uv run --project (Join-Path $root 'Irodori-TTS-Server') --no-sync --with pyopenjtalk-plus python (Join-Path $root 'scripts\bench_tts.py') --label $Label --repeats $Repeats --url $Url --voice $Voice @options
