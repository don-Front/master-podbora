# Production UI для виджета: http://0.0.0.0:10111 (прокси master-turbo-podbor.ru/podbor-chat/)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$dist = Join-Path $repoRoot 'dist'

if (-not (Test-Path (Join-Path $dist 'index.html'))) {
    Write-Host 'dist not found, building...'
    Set-Location $PSScriptRoot
    & (Join-Path $PSScriptRoot 'build-dist.ps1')
}

$listenerPid = (netstat -ano | Select-String ':10111\s+.*LISTENING' | ForEach-Object {
    ($_.Line -split '\s+')[-1]
} | Select-Object -First 1)

if ($listenerPid) {
    Write-Host "stop PID $listenerPid on :10111"
    taskkill /PID $listenerPid /F | Out-Null
    Start-Sleep -Seconds 1
}

Write-Host "start serve on :10111 from $dist"
Set-Location $dist
npx --yes serve -s . -l tcp://0.0.0.0:10111
