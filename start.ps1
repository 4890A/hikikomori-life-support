# Starts the voice engine, the speech bridge and the web app, then opens her page. Ctrl+C stops them.
param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'scripts\common.ps1')
Set-Location $Root

if (-not (Test-Path $SpeechExe) -or -not (Test-Path $ModelFile) -or -not (Test-Path (Join-Path $Root '.venv'))) {
    throw 'Setup is not finished. Run: powershell -ExecutionPolicy Bypass -File .\setup.ps1'
}
if (-not (Test-VoiceReady)) {
    $clip = Find-VoiceClip
    if (-not $clip) { throw "She needs a voice. Put a WAV recording in $VoicesDir, then run this again." }
    & (Join-Path $Root 'scripts\add-voice.ps1') $clip
}
foreach ($port in 8088, 8089, 5179) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Close whatever is using it, which may be an earlier run of this script."
    }
}

Push-Location (Join-Path $Root 'web')
try {
    npm run build | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'The web app failed to build.' }
} finally {
    Pop-Location
}

$logs = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$shell = (Get-Process -Id $PID).Path
function Start-CompanionService($name, $file) {
    Start-Process $shell -PassThru -WindowStyle Hidden `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $Root "scripts\$file")) `
        -RedirectStandardOutput (Join-Path $logs "$name.log") -RedirectStandardError (Join-Path $logs "$name.err.log")
}

$services = @{}
try {
    $services.voice = Start-CompanionService 'voice' 'start-tts.ps1'
    $services.bridge = Start-CompanionService 'bridge' 'start-speech.ps1'
    $services.web = Start-CompanionService 'web' 'start-web.ps1'

    Write-Host 'Starting up...'
    $url = 'http://localhost:5179'
    $deadline = (Get-Date).AddMinutes(3)
    $ready = $false
    while (-not $ready) {
        if ((Get-Date) -gt $deadline) { throw "She didn't start in time. Check the files in $logs, or run .\doctor.ps1." }
        foreach ($name in @($services.Keys)) {
            if ($services[$name].HasExited) { throw "The $name service stopped. See $logs\$name.err.log" }
        }
        try {
            $health = Invoke-RestMethod "$url/speech/health" -TimeoutSec 2
            $ready = [bool]$health.warmed_up
        } catch { }
        if (-not $ready) { Start-Sleep -Seconds 1 }
    }

    Write-Host "She's ready: $url" -ForegroundColor Green
    if (-not (Get-OpenRouterKey)) {
        Write-Warning 'No OpenRouter key, so she can only speak what you type in the Voice panel. Run setup to add one.'
    }
    Write-Host 'Press Ctrl+C to stop.'
    if (-not $NoBrowser) { Start-Process $url }
    while ($true) {
        foreach ($name in @($services.Keys)) {
            if ($services[$name].HasExited) { throw "The $name service stopped. See $logs\$name.err.log" }
        }
        Start-Sleep -Seconds 1
    }
} finally {
    foreach ($service in $services.Values) {
        if ($service -and -not $service.HasExited) { & taskkill /PID $service.Id /T /F 2>&1 | Out-Null }
    }
    Write-Host 'Stopped.'
}
