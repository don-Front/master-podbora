# Production-сборка в каталог master-podbora/dist (REACT_APP_* из .env.production).
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$env:BUILD_PATH = '../../dist'
$env:NODE_ENV = 'production'
npm run build

Write-Host "OK: dist -> $(Resolve-Path '..\..\dist')"
