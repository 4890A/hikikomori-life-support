# Starts speech.cpp on :8088 with the model in settings.json, on the first GPU (Vulkan), or the CPU
# without one. The speech bridge sets the steps per request. If you pass -Model, give
# start-speech.ps1 the same one.
param([string]$Model)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

if (-not (Test-Path $SpeechExe)) { throw 'speech.cpp is not set up. Run: .\scripts\setup-speech-cpp.ps1' }
$settings = Get-CompanionSettings
if (-not $Model) { $Model = $settings.model }

$arguments = @('serve', $Model, '--device', 'auto', '--port', '8088')
if (Test-Path $VoicesDir) {
    foreach ($voice in Get-ChildItem $VoicesDir -Filter '*.voice.gguf' -File) {
        $arguments += @('--add-voice', "$($voice.Name -replace '\.voice\.gguf$', '')=$($voice.FullName)")
    }
}
& $SpeechExe @arguments
