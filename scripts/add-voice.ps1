# Makes a voice from a WAV recording and switches her to it. A clear clip of 10-60 s works well.
#   .\scripts\add-voice.ps1 my-clip.wav
#   .\scripts\add-voice.ps1 my-clip.wav -Name calm
param(
    [Parameter(Mandatory)][string]$Clip,
    [string]$Name
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

if (-not (Test-Path $Clip)) { throw "$Clip not found." }
if (-not (Test-Path $SpeechExe)) { throw 'Setup is not finished. Run .\setup.ps1 first.' }
if (-not $Name) {
    $Name = ([IO.Path]::GetFileNameWithoutExtension($Clip) -replace '[^A-Za-z0-9_-]+', '-').Trim('-')
    if (-not $Name -or $Name -eq 'none') { $Name = 'my-voice' }
}
if ($Name -notmatch '^[A-Za-z0-9_-]+$' -or $Name -eq 'none') { throw "Use only letters, numbers, - and _ in the voice name, and not 'none'." }

Write-Host 'Only use a voice you have the right to use. Irodori-TTS forbids cloning someone without their consent.' -ForegroundColor Yellow
New-Item -ItemType Directory -Force $VoicesDir | Out-Null
$settings = Get-CompanionSettings
& $SpeechExe voice $settings.model $Clip (Join-Path $VoicesDir "$Name.voice.gguf")
if ($LASTEXITCODE -ne 0) { throw 'Could not make a voice from that file. It needs to be a WAV of at most 120 s.' }
$settings.voice = $Name
Save-CompanionSettings $settings
Write-Host "Her voice is now '$Name'. If she's running, restart her to use it."
