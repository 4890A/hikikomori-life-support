# Installs everything the companion needs. Safe to run again: finished steps are skipped.
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
param(
    [string]$ZipPath,          # The model zip, if it isn't in this folder or Downloads.
    [switch]$SkipKey,          # Don't ask for an OpenRouter key.
    [switch]$CpuOnly           # Use the small CPU build of torch, even with an NVIDIA GPU.
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'scripts\common.ps1')
Set-Location $Root

function Write-Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

function Install-Tool($command, $wingetId, $why) {
    if (Get-Command $command -ErrorAction SilentlyContinue) { return }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "$command is needed ($why) and winget isn't available. Install it, then run this again."
    }
    $answer = Read-Host "$command is needed ($why). Install it with winget? [Y/n]"
    if ($answer -match '^[nN]') { throw "$command is needed. Install it, then run this again." }
    winget install --id $wingetId --exact --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw "winget couldn't install $command." }
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:Path
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "$command was installed. Open a new terminal, then run this again."
    }
}

Write-Host 'This downloads about 3-8 GB, depending on your GPU. It can take a while the first time.'

Write-Step 'Checking your PC'
if (-not $IsWindows -and $PSVersionTable.PSVersion.Major -ge 6) { throw 'Setup currently supports Windows only.' }
$freeGb = [math]::Round((Get-PSDrive ($Root.Substring(0, 1))).Free / 1GB, 1)
Write-Host "Free disk space: $freeGb GB"
if ($freeGb -lt 10) { Write-Warning 'Less than 10 GB free, so setup may run out of space.' }
Install-Tool 'uv' 'astral-sh.uv' 'it installs Python and its packages'
Install-Tool 'node' 'OpenJS.NodeJS.LTS' 'it builds the web app'

Write-Step 'Installing Python packages'
$useCuda = (-not $CpuOnly) -and [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
$extra = if ($useCuda) { 'cu128' } else { 'cpu' }
Write-Host "Lip alignment will use: $(if ($useCuda) { 'your NVIDIA GPU' } else { 'the CPU, about 0.1 s slower per line' })"
uv sync --extra $extra
if ($LASTEXITCODE -ne 0) { throw 'uv sync failed.' }

Write-Step 'Installing the voice engine (speech.cpp)'
& (Join-Path $Root 'scripts\setup-speech-cpp.ps1')
if (-not (Test-GpuAvailable)) {
    Write-Warning 'No Vulkan GPU found, so speech will run on the CPU and be slow. Updating your graphics driver may help.'
}

Write-Step 'Downloading the lip alignment model'
$env:PYTHONPATH = Join-Path $Root 'speech'
uv run --no-sync python -c "from huggingface_hub import snapshot_download; from model_source import PHONEME_MODEL, PHONEME_REVISION; snapshot_download(PHONEME_MODEL, revision=PHONEME_REVISION)"
if ($LASTEXITCODE -ne 0) { throw 'Could not download the lip alignment model.' }

Write-Step 'Setting up the character model'
if (Test-Path $ModelFile) {
    Write-Host 'Already set up.'
} else {
    if (-not $ZipPath) { $ZipPath = Find-ModelZip }
    while (-not $ZipPath -or -not (Test-Path $ZipPath)) {
        Write-Host ''
        Write-Host "DeepSeek-chan's creators don't allow her files to be reposted, so she isn't included here." -ForegroundColor Yellow
        Write-Host 'She is a free download from their page. Download the zip, then come back here:'
        Write-Host "  $ModelUrl"
        Start-Process $ModelUrl
        Read-Host 'Press Enter once the zip is in your Downloads folder'
        $ZipPath = Find-ModelZip
    }
    Write-Host "Using $ZipPath"
    uv run --no-sync live2dselfrigging --zip $ZipPath
    if ($LASTEXITCODE -ne 0) { throw "Couldn't read the model from that zip. Download it again from: $ModelUrl" }
}

Write-Step 'Setting up her voice'
New-Item -ItemType Directory -Force $VoicesDir | Out-Null
if (Test-VoiceReady) {
    Write-Host "Already set up: $((Get-CompanionSettings).voice)"
} else {
    if (-not (Find-VoiceClip)) {
        Write-Host ''
        Write-Host 'She speaks in a voice cloned from a recording, and none is included here.' -ForegroundColor Yellow
        Write-Host 'Put a WAV file in the folder below. A clear clip of one person speaking for 10-60 s works well.'
        Write-Host 'It stays on your PC. Only use a voice you have the right to use: Irodori-TTS forbids cloning someone without their consent.'
        Write-Host "  $VoicesDir"
        Start-Process $VoicesDir
    }
    while (-not (Test-VoiceReady)) {
        $clip = Find-VoiceClip
        if (-not $clip) {
            Read-Host 'Press Enter once the WAV file is in that folder'
            if (-not (Find-VoiceClip)) { Write-Host "No .wav file found in $VoicesDir" -ForegroundColor Yellow }
            continue
        }
        Write-Host "Using $clip"
        try {
            & (Join-Path $Root 'scripts\add-voice.ps1') $clip
        } catch {
            Write-Warning "$_"
            Read-Host 'Replace that file with another WAV, then press Enter'
        }
    }
}

Write-Step 'Building the web app'
Push-Location (Join-Path $Root 'web')
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'The web app failed to build.' }
} finally {
    Pop-Location
}

Write-Step 'OpenRouter key (for her replies and for seeing your screen)'
if (Get-OpenRouterKey) {
    Write-Host 'Already set.'
} elseif ($SkipKey) {
    Write-Host 'Skipped.'
} else {
    Write-Host 'She needs a key from https://openrouter.ai/keys to write replies. It costs roughly 4 cents an hour.'
    Write-Host 'Frames from the window you share are sent to OpenRouter. Press Enter to skip for now.'
    $secure = Read-Host 'Paste your key (it stays hidden)' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
    if ($key) {
        [Environment]::SetEnvironmentVariable('OPENROUTER_API_KEY', $key, 'User')
        Write-Host 'Saved to your Windows user account.'
    } else {
        Write-Host 'Skipped. She can still speak what you type in the Voice panel. Run setup again to add a key.'
    }
}

Write-Step 'Testing her voice'
$settings = Get-CompanionSettings
$test = Join-Path $env:TEMP 'companion-voice-test.wav'
# Written as character codes because Windows PowerShell 5.1 misreads UTF-8 in scripts without a BOM.
$hello = -join @([char]0x3053, [char]0x3093, [char]0x306B, [char]0x3061, [char]0x306F, [char]0x3002)
$voiceFile = Join-Path $VoicesDir "$($settings.voice).voice.gguf"
& $SpeechExe tts $settings.model --add-voice "$($settings.voice)=$voiceFile" --voice $settings.voice --steps $settings.steps -o $test $hello
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $test) -or (Get-Item $test).Length -lt 1000) {
    throw 'The voice test failed. Run .\doctor.ps1 for details.'
}
Remove-Item $test

Write-Host "`nAll set. Start her with:  .\start.ps1" -ForegroundColor Green
