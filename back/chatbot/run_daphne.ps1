# Запуск Django через Daphne (ASGI). Запускать из проводника ПКМ → «Выполнить с PowerShell» или: powershell -File run_daphne.ps1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 -m daphne -b 127.0.0.1 -p 8000 chatbot.asgi:application
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python -m daphne -b 127.0.0.1 -p 8000 chatbot.asgi:application
} else {
    Write-Error 'Не найдены команды py или python в PATH.'
}
