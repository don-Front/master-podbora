# Быстрая проверка React/Django и сборки dist.
param(
    [string]$HostIp = '193.105.37.142',
    [string]$LanIp = '192.168.5.53'
)

$checks = @(
    @{ Label = 'Django /health/ (localhost)'; Url = 'http://127.0.0.1:10112/health/' },
    @{ Label = 'React UI (localhost)'; Url = 'http://127.0.0.1:10111/' },
    @{ Label = "Django /health/ (LAN $LanIp)"; Url = "http://${LanIp}:10112/health/" },
    @{ Label = "React UI (LAN $LanIp)"; Url = "http://${LanIp}:10111/" },
    @{ Label = "Django /health/ (external $HostIp)"; Url = "http://${HostIp}:10112/health/" },
    @{ Label = "React UI (external $HostIp)"; Url = "http://${HostIp}:10111/" }
)

Write-Host "=== HTTP checks ==="
foreach ($c in $checks) {
    try {
        $r = Invoke-WebRequest -Uri $c.Url -TimeoutSec 8 -UseBasicParsing
        Write-Host ("[OK]   {0} -> {1}" -f $c.Label, $r.StatusCode)
    } catch {
        Write-Host ("[FAIL] {0}" -f $c.Label)
    }
}

$distJs = Get-ChildItem "$PSScriptRoot\dist\static\js\main.*.js" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($distJs -and (Select-String -Path $distJs.FullName -Pattern "${HostIp}:10112" -Quiet)) {
    Write-Host "[OK]   dist bundle contains API http://${HostIp}:10112/api"
} else {
    Write-Host "[FAIL] dist bundle: API URL not found"
}

if (Test-Path "$PSScriptRoot\dist\widget.js") {
    if (Select-String -Path "$PSScriptRoot\dist\widget.js" -Pattern "${HostIp}:10111" -Quiet) {
        Write-Host "[OK]   dist/widget.js -> http://${HostIp}:10111"
    }
}

Write-Host ""
Write-Host "External test (mobile data): http://${HostIp}:10111 and http://${HostIp}:10112/health/"
