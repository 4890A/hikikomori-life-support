# Checks everything the companion needs and says how to fix what's wrong. Changes nothing.
$ProgressPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'scripts\common.ps1')
Set-Location $Root
$problems = 0

function Show-Check($name, [bool]$ok, $detail, $fix) {
    if ($ok) {
        Write-Host "[ ok ] $name  $detail" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] $name  $detail" -ForegroundColor Red
        if ($fix) { Write-Host "       Fix: $fix" }
        $script:problems += 1
    }
}

$setup = 'powershell -ExecutionPolicy Bypass -File .\setup.ps1'
Show-Check 'uv' ([bool](Get-Command uv -ErrorAction SilentlyContinue)) '' $setup
Show-Check 'Node' ([bool](Get-Command node -ErrorAction SilentlyContinue)) '' $setup
Show-Check 'Python packages' (Test-Path (Join-Path $Root '.venv')) '' $setup
Show-Check 'speech.cpp' (Test-Path $SpeechExe) '' $setup
if (Test-Path $SpeechExe) {
    Show-Check 'Vulkan GPU' (Test-GpuAvailable) '' 'Update your graphics driver. Without a GPU, speech is slow.'
    if (Test-GpuAvailable) {
        & $SpeechExe devices 2>&1 | Where-Object { $_ -match '\bgpu\b' } | Select-Object -First 1 | ForEach-Object { Write-Host "       $_" }
    }
}
Show-Check 'Character model' (Test-Path $ModelFile) '' "Download the zip from $ModelUrl then run setup."
Show-Check 'Web app built' (Test-Path (Join-Path $Root 'web\dist\index.html')) '' $setup
$key = Get-OpenRouterKey
Show-Check 'OpenRouter key' ([bool]$key) '' "Run setup, or she can only speak what you type in the Voice panel."
if ($key) {
    try {
        $null = Invoke-RestMethod 'https://openrouter.ai/api/v1/key' -Headers @{ Authorization = "Bearer $key" } -TimeoutSec 10
        Show-Check 'OpenRouter key works' $true '' ''
    } catch {
        Show-Check 'OpenRouter key works' $false 'It was refused, or OpenRouter could not be reached.' 'Check your connection, or make a new key at https://openrouter.ai/keys and run setup.'
    }
}
$settings = Get-CompanionSettings
Write-Host "       Settings: model $($settings.model), $($settings.steps) steps, duration scale $($settings.durationScale), voice $($settings.voice)"
Show-Check 'Voice file' (Test-VoiceReady) $settings.voice "Put a WAV recording in $VoicesDir, then run setup."
foreach ($port in 8088, 8089, 5179) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        Write-Host "       Port $port is in use. That's fine if she's running."
    }
}
Write-Host ''
if ($problems -eq 0) { Write-Host 'Everything looks fine.' -ForegroundColor Green } else { Write-Host "$problems problem(s) found." -ForegroundColor Red }
exit $problems
