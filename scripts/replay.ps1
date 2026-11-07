# Plays a video to her as if it were a shared window, then prints how the session went. Start her
# first with .\start.ps1. What she says goes into her memory, unless you started her with the
# COMPANION_DATA_DIR environment variable pointing somewhere else.
#   .\scripts\replay.ps1 -Video .scratch\mahjong-video\clip.mp4 -Minutes 3
#   .\scripts\replay.ps1 -Video clip.mp4 -Say '20=what is this?', '70=I think I am winning'
# -Say takes seconds=words; Japanese works too.
param(
    [Parameter(Mandatory)][string]$Video,
    [double]$Minutes = 3,
    [ValidateSet('quiet', 'normal', 'chatty')][string]$Chattiness = 'normal',
    [string[]]$Say = @()
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'common.ps1')

if (-not (Test-Path $Video)) { throw "$Video not found." }
try { $null = Invoke-RestMethod 'http://localhost:5179/speech/health' -TimeoutSec 3 } catch { throw 'She is not running. Start her with .\start.ps1 first.' }
$chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe", "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe", "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { throw 'Chrome is needed for the replay.' }

$profileDir = Join-Path $env:TEMP 'companion-replay-profile'
$nodeArgs = @((Join-Path $PSScriptRoot 'replay.mjs'), '--chrome', $chrome, '--profile', $profileDir, '--video', (Resolve-Path $Video).Path, '--minutes', $Minutes, '--chattiness', $Chattiness)
foreach ($line in $Say) { $nodeArgs += @('--say', $line) }
try {
    node @nodeArgs
} finally {
    foreach ($p in (Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object { $_.CommandLine -match 'companion-replay-profile' })) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
$data = if ($env:COMPANION_DATA_DIR) { $env:COMPANION_DATA_DIR } else { Join-Path $Root 'companion-data' }
$latest = Get-ChildItem (Join-Path $data 'sessions') -Filter '*.jsonl' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
uv run --no-sync python (Join-Path $Root 'scripts\session_report.py') $latest.FullName --transcript
