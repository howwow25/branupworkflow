# branup update script
# git pull -> dashboard rebuild -> api server restart
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host 'Pulling latest from GitHub...' -ForegroundColor Cyan
git fetch origin
if ($LASTEXITCODE -ne 0) { throw 'git fetch failed' }

git reset --hard origin/main
if ($LASTEXITCODE -ne 0) { throw 'git reset failed' }

Write-Host 'Building dashboard HTML...' -ForegroundColor Cyan
python dashboard_html.py
if ($LASTEXITCODE -ne 0) { throw 'dashboard_html.py failed' }

Write-Host 'Restarting API server...' -ForegroundColor Cyan
$proc = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'api_server' }
if ($proc) {
    Stop-Process -Id $proc.Id -Force
    Write-Host '  Killed old API server (PID:' $proc.Id ')'
}

Start-Process python -ArgumentList 'api_server.py' -WindowStyle Hidden
Write-Host '  New API server started'

Write-Host 'Update complete! Ctrl+Shift+R to refresh dashboard' -ForegroundColor Green
