# Запуск React (10111) и Django/Daphne (10112) без Docker, доступ с 0.0.0.0.
# Использование: powershell -ExecutionPolicy Bypass -File start_external_network.ps1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

Write-Host '[master-podbora] React  -> http://0.0.0.0:10111  (внешний: http://193.105.37.142:10111)'
Write-Host '[master-podbora] Django -> http://0.0.0.0:10112  (health: /health/)'

$backendScript = Join-Path $Root 'back\chatbot\run_daphne.ps1'
$distDir = Join-Path $Root 'dist'

Start-Process powershell -ArgumentList @(
    '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', $backendScript
) -WorkingDirectory (Join-Path $Root 'back\chatbot')

Start-Sleep -Seconds 2

# Production dist (PUBLIC_URL=/podbor-chat). Не npm start — иначе белый экран за прокси.
Start-Process powershell -ArgumentList @(
    '-NoExit', '-ExecutionPolicy', 'Bypass', '-Command',
    "Set-Location '$distDir'; npx --yes serve . -l tcp://0.0.0.0:10111"
) -WorkingDirectory $distDir

Write-Host '[master-podbora] Оба процесса запущены в отдельных окнах PowerShell.'
