# Installs a pinned speech.cpp release into speech-cpp/ without touching PATH, checks its checksum, and
# fetches the Irodori model. Safe to run again: a finished install is skipped.
param([string]$Version = '0.10.1', [string]$Model)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'common.ps1')

$dir = Join-Path $Root 'speech-cpp'
$installed = if (Test-Path $SpeechExe) { (& $SpeechExe --version 2>&1 | Out-String) } else { '' }
if ($installed -match "speech\.cpp $([regex]::Escape($Version))\b") {
    Write-Host "speech.cpp $Version is already installed."
} else {
    New-Item -ItemType Directory -Force $dir | Out-Null
    $archive = "speech-$Version-windows-x64-vulkan.zip"
    $base = "https://github.com/nyosegawa/speech.cpp/releases/download/v$Version"
    Invoke-WebRequest "$base/$archive" -OutFile (Join-Path $dir $archive)
    Invoke-WebRequest "$base/SHA256SUMS" -OutFile (Join-Path $dir 'SHA256SUMS')

    $line = Select-String -Path (Join-Path $dir 'SHA256SUMS') -SimpleMatch $archive
    if (-not $line) { throw "$archive is not listed in SHA256SUMS." }
    $expected = ($line.Line -split '\s+')[0]
    $actual = (Get-FileHash (Join-Path $dir $archive) -Algorithm SHA256).Hash
    if ($expected -ne $actual) { throw "Checksum mismatch for ${archive}: expected $expected, got $actual." }

    Expand-Archive -Force (Join-Path $dir $archive) (Join-Path $dir 'app')
    Remove-Item (Join-Path $dir $archive)
}

if (-not $Model) { $Model = (Get-CompanionSettings).model }
& $SpeechExe pull $Model
if ($LASTEXITCODE -ne 0) { throw "Could not download $Model." }
