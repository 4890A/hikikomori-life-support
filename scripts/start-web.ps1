# Serves the built web app on :5179. For development with live reload, use npm run dev in web/ instead.
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) 'web')
npm run preview
