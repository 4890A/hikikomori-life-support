# Starts the speech bridge on :8089 (lip-sync, expression timing and companion turns). It uses the
# settings in settings.json, and these options override them for one run.
#   .\scripts\start-speech.ps1 -Steps 8               more steps: slower
#   .\scripts\start-speech.ps1 -DurationScale 0.7     shorter lines, with less silence
#   .\scripts\start-speech.ps1 -Model irodori-tts -Steps 20   match start-tts.ps1 -Model irodori-tts
#   .\scripts\start-speech.ps1 -Engine pytorch -Steps 20      for start-tts-python.ps1
param(
    [int]$Steps,
    [double]$DurationScale,
    [string]$Model,
    [string]$Voice,
    [ValidateSet('cpp', 'pytorch')][string]$Engine = 'cpp'
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

$settings = Get-CompanionSettings
if (-not $Steps) { $Steps = $settings.steps }
if (-not $DurationScale) { $DurationScale = $settings.durationScale }
if (-not $Model) { $Model = $settings.model }
if (-not $Voice) { $Voice = $settings.voice }

if ($Engine -eq 'pytorch') {
    $latent = Join-Path $Root "Irodori-TTS-Server\voices\$Voice-latent.pt"
    if (-not (Test-Path $latent)) {
        throw "$latent is missing. Create it with: uv run --project Irodori-TTS-Server --no-sync python scripts\encode_voice.py --voice $Voice"
    }
    $Voice = "$Voice-latent"
}
# A terminal opened before the key was saved doesn't have it yet. Companion turns report it if unset.
$env:OPENROUTER_API_KEY = Get-OpenRouterKey
$env:TTS_ENGINE = $Engine
$env:TTS_STEPS = $Steps
$env:TTS_MODEL = $Model
$env:TTS_VOICE = $Voice
$env:TTS_DURATION_SCALE = $DurationScale
$env:HF_HUB_OFFLINE = '1'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = Join-Path $Root 'speech'
Set-Location $Root
uv run --no-sync python (Join-Path $Root 'speech\server.py')
