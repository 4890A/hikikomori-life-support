# Benchmarks cheap OpenRouter models. Screen turns use the images in .scratch\mahjong, if any.
#   .\scripts\bench-llm.ps1
#   .\scripts\bench-llm.ps1 -Repeats 5
param([int]$Repeats = 3)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
# A terminal opened before the key was saved doesn't have it yet.
if (-not $env:OPENROUTER_API_KEY) { $env:OPENROUTER_API_KEY = [Environment]::GetEnvironmentVariable('OPENROUTER_API_KEY', 'User') }
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = Join-Path $root 'speech'
uv run --project (Join-Path $root 'Irodori-TTS-Server') --no-sync python (Join-Path $root 'scripts\bench_llm.py') --repeats $Repeats
