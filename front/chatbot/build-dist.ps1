# Production-сборка в каталог master-podbora/dist (REACT_APP_* из .env.production).
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$env:BUILD_PATH = '../../dist'
$env:NODE_ENV = 'production'
Get-Content '.env.production.proxy' | ForEach-Object {
  if ($_ -match '^([^#=]+)=(.*)$') {
    Set-Item -Path "env:$($matches[1].Trim())" -Value $matches[2].Trim()
  }
}
npm run build
Copy-Item -Force (Join-Path $PSScriptRoot 'public\widget.js') (Join-Path (Resolve-Path '..\..\dist') 'widget.js')

$dist = Resolve-Path '..\..\dist'
$podborChat = Join-Path $dist 'podbor-chat'
if (Test-Path $podborChat) {
  Remove-Item $podborChat -Recurse -Force
}
New-Item -ItemType Directory -Path $podborChat -Force | Out-Null
Copy-Item (Join-Path $dist 'static') (Join-Path $podborChat 'static') -Recurse -Force
Copy-Item (Join-Path $dist 'index.html') $podborChat -Force
Copy-Item (Join-Path $dist 'widget.js') $podborChat -Force
Copy-Item (Join-Path $dist 'manifest.json') $podborChat -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $dist 'robots.txt') $podborChat -Force -ErrorAction SilentlyContinue

$competitorsSrc = Join-Path $dist 'competitors'
$competitorsDst = Join-Path $podborChat 'competitors'
if (Test-Path $competitorsSrc) {
  if (Test-Path $competitorsDst) {
    Remove-Item $competitorsDst -Recurse -Force
  }
  Copy-Item $competitorsSrc $competitorsDst -Recurse -Force
}

Write-Host "OK: dist -> $dist"
