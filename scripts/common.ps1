# Shared by the setup and start scripts. Works in Windows PowerShell 5.1, the default on Windows.

$script:Root = Split-Path -Parent $PSScriptRoot
$script:SettingsPath = Join-Path $script:Root 'settings.json'
$script:SpeechExe = Join-Path $script:Root 'speech-cpp\app\speech.exe'
$script:VoicesDir = Join-Path $script:Root 'voices'
$script:ModelFile = Join-Path $script:Root 'web\public\model\deepseek\deepseek.model3.json'
$script:ModelUrl = 'https://vgen.co/KAMIYA/product/deepseek-chan-deepseek-free-live2d-model-layered-psd-psd/1c55a71a-2747-4616-819d-2dc0a934089d'

function Get-CompanionSettings {
    $settings = [ordered]@{ model = 'irodori-tts-mf'; steps = 6; durationScale = 1; voice = '' }
    if (Test-Path $script:SettingsPath) {
        $saved = Get-Content $script:SettingsPath -Raw | ConvertFrom-Json
        foreach ($name in @($settings.Keys)) {
            if ($null -ne $saved.$name) { $settings[$name] = $saved.$name }
        }
    }
    return $settings
}

function Save-CompanionSettings($settings) {
    [IO.File]::WriteAllText($script:SettingsPath, ($settings | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
}

function Get-OpenRouterKey {
    if ($env:OPENROUTER_API_KEY) { return $env:OPENROUTER_API_KEY }
    return [Environment]::GetEnvironmentVariable('OPENROUTER_API_KEY', 'User')
}

function Find-ModelZip {
    $downloads = Join-Path $env:USERPROFILE 'Downloads'
    foreach ($folder in @($script:Root, $downloads)) {
        if (Test-Path $folder) {
            $zip = Get-ChildItem $folder -Filter 'DeepSeek-chan*.zip' -File -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($zip) { return $zip.FullName }
        }
    }
    return $null
}

function Test-VoiceReady {
    $voice = (Get-CompanionSettings).voice
    return [bool]$voice -and (Test-Path (Join-Path $script:VoicesDir "$voice.voice.gguf"))
}

function Find-VoiceClip {
    if (-not (Test-Path $script:VoicesDir)) { return $null }
    $clip = Get-ChildItem $script:VoicesDir -Filter '*.wav' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($clip) { return $clip.FullName }
    return $null
}

function Test-GpuAvailable {
    if (-not (Test-Path $script:SpeechExe)) { return $false }
    $devices = & $script:SpeechExe devices 2>&1 | Out-String
    return $devices -match '(?m)^\S+\s+(gpu|igpu)\s'
}
