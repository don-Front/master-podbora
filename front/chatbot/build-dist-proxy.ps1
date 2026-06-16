# Production dist для прокси https://turbo-podbor.ru/podbor-chat/ и /podbor-api/
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$envFile = Join-Path $PSScriptRoot '.env.production.proxy'
if (-not (Test-Path $envFile)) {
    throw "Missing $envFile"
}

Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -notmatch '^\s*([^=]+)=(.*)$') { return }
    $name = $matches[1].Trim()
    $value = $matches[2].Trim()
    Set-Item -Path "env:$name" -Value $value
}

$env:BUILD_PATH = '../../dist'
$env:NODE_ENV = 'production'
npm run build
Write-Host 'OK: dist built for https://turbo-podbor.ru/podbor-chat/'
