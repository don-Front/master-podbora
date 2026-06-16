# Открыть TCP 10111 (React) и 10112 (Django) в Windows Firewall.
# Запуск от имени администратора: ПКМ → «Выполнить с PowerShell» или:
#   Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass -File open_firewall_ports.ps1'
#Requires -RunAsAdministrator

$ErrorActionPreference = 'Stop'

$rules = @(
    @{ Name = 'master-podbora-react-10111'; Port = 10111 },
    @{ Name = 'master-podbora-django-10112'; Port = 10112 }
)

foreach ($r in $rules) {
    netsh advfirewall firewall delete rule name="$($r.Name)" 2>$null | Out-Null
    netsh advfirewall firewall add rule name="$($r.Name)" dir=in action=allow protocol=TCP localport=$($r.Port) profile=any enable=yes | Out-Null
    Write-Host "OK: $($r.Name) TCP $($r.Port)"
}

netsh advfirewall firewall show rule name="master-podbora-react-10111"
netsh advfirewall firewall show rule name="master-podbora-django-10112"
