# Full deploy master-podbora (192.168.5.53 -> 193.105.37.142 -> master-turbo-podbor.ru)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

function Log($msg) { Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $msg" }

Log "1/5 Firewall: open TCP 10111 and 10112"
foreach ($port in @(10111, 10112)) {
    $ruleName = "master-podbora-$port"
    try {
        if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -ErrorAction Stop | Out-Null
            Log "Firewall rule created: $ruleName"
        }
    } catch {
        Write-Warning "Firewall rule $ruleName skipped (need admin): $_"
    }
}

Log "2/5 Docker compose build + up (fallback without Docker)"
Push-Location $Root
$dockerOk = $false
try {
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        docker-compose up --build -d 2>&1 | Write-Host
        if ($LASTEXITCODE -eq 0) { $dockerOk = $true }
    } else {
        docker compose up --build -d 2>&1 | Write-Host
        if ($LASTEXITCODE -eq 0) { $dockerOk = $true }
    }
} catch {
    Write-Warning "Docker unavailable: $_"
} finally {
    Pop-Location
}

if (-not $dockerOk) {
    Log "Docker unavailable - restart without Docker (Daphne + serve)"
    foreach ($port in @(10111, 10112)) {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn -and $conn.OwningProcess) {
            Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
            Log "Stopped PID $($conn.OwningProcess) on port $port"
        }
    }
    Start-Sleep -Seconds 2

    $backendScript = Join-Path $Root 'back\chatbot\run_daphne.ps1'
    $backendDir = Join-Path $Root 'back\chatbot'
    Start-Process -FilePath 'powershell.exe' -ArgumentList @(
        '-ExecutionPolicy', 'Bypass', '-NoProfile', '-Command',
        "Set-Location '$backendDir'; & '$backendScript'"
    ) -WorkingDirectory $backendDir -WindowStyle Hidden

    Start-Sleep -Seconds 5
}

Log "2b/5 Django migrations"
$backendDir = Join-Path $Root 'back\chatbot'
Push-Location $backendDir
try {
    py -3 manage.py migrate --noinput
    if ($LASTEXITCODE -ne 0) {
        Write-Error 'Django migrate failed'
    }
} finally {
    Pop-Location
}

Log "3/5 Wait for Django health"
$ok = $false
for ($i = 1; $i -le 45; $i++) {
    try {
        $code = (curl.exe -sS -m 5 -o NUL -w '%{http_code}' http://127.0.0.1:10112/health/).Trim()
        if ($code -eq '200') { $ok = $true; break }
    } catch {}
    Start-Sleep -Seconds 2
}
if (-not $ok) {
    Write-Error 'Django healthcheck failed on http://127.0.0.1:10112/health/'
}

Log "4/5 Build dist for /podbor-chat"
$front = Join-Path $Root 'front\chatbot'
Push-Location $front
try {
    $env:BUILD_PATH = Join-Path $Root 'dist'
    Get-Content '.env.production.proxy' | ForEach-Object {
        if ($_ -match '^([^#=]+)=(.*)$') {
            Set-Item -Path "env:$($matches[1].Trim())" -Value $matches[2].Trim()
        }
    }
    npm run build
    Copy-Item -Force (Join-Path $Root 'front\chatbot\public\widget.js') (Join-Path $Root 'dist\widget.js')
} finally {
    Pop-Location
}

if (-not $dockerOk) {
    $distDir = Join-Path $Root 'dist'
    Start-Process powershell -ArgumentList @(
        '-NoExit', '-ExecutionPolicy', 'Bypass', '-Command',
        "Set-Location '$distDir'; npx --yes serve . -l tcp://0.0.0.0:10111"
    ) -WorkingDirectory $distDir -WindowStyle Minimized
    Start-Sleep -Seconds 2
}

Log "5/5 Nginx proxy on gateway and master VPS"
try { py (Join-Path $Root 'deploy\deploy_gateway_nginx.py') } catch { Write-Warning "Gateway nginx: $_" }
try { py (Join-Path $Root 'deploy\setup_master_vps_nginx.py') } catch { Write-Warning "Master VPS nginx: $_" }

Log "Local verification"
curl.exe -sS -m 8 -w "`nreact:%{http_code}`n" http://127.0.0.1:10111/ -o NUL
curl.exe -sS -m 8 -w "health:%{http_code}`n" http://127.0.0.1:10112/health/ -o NUL
curl.exe -sS -m 8 -w "api:%{http_code}`n" "http://127.0.0.1:10112/api/hints/?state=start" -o NUL

Log "External verification"
curl.exe -sS -m 12 -w "master-chat:%{http_code}`n" http://master-turbo-podbor.ru/podbor-chat/ -o NUL
curl.exe -sS -m 12 -w "master-api:%{http_code}`n" "http://master-turbo-podbor.ru/podbor-api/api/hints/?state=start" -o NUL
curl.exe -sS -m 12 -w "master-fastapi:%{http_code}`n" "http://master-turbo-podbor.ru/api/search-equipment" -o NUL

Log "Done. URLs:"
Write-Host '  UI:  http://master-turbo-podbor.ru/podbor-chat/'
Write-Host '  API: http://master-turbo-podbor.ru/podbor-api/api/'
Write-Host '  FastAPI: http://master-turbo-podbor.ru/api/'
Write-Host '  LAN: http://192.168.5.53:10111 and http://192.168.5.53:10112'
