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
# 포트 8800을 점유한 기존 프로세스를 PID 기준으로 확실히 종료
# (CommandLine 은 Windows에서 비어있을 수 있어 신뢰 불가 → 포트 소유 PID 직접 조회)
$conns = Get-NetTCPConnection -LocalPort 8800 -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $pids) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host "  Killed old API server (PID: $procId)"
        } catch {
            Write-Host "  Failed to kill PID $procId : $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    Start-Sleep -Seconds 1
} else {
    Write-Host '  No existing server on port 8800'
}

Start-Process python -ArgumentList 'api_server.py' -WindowStyle Hidden
Start-Sleep -Seconds 2
# 기동 확인 — 포트 바인딩 여부로 실제 기동 확인
$check = Get-NetTCPConnection -LocalPort 8800 -State Listen -ErrorAction SilentlyContinue
if ($check) {
    Write-Host '  New API server started (port 8800)' -ForegroundColor Green
} else {
    Write-Host '  WARNING: API server NOT listening on 8800 - check api-server errors' -ForegroundColor Red
}

Write-Host 'Update complete! Ctrl+Shift+R to refresh dashboard' -ForegroundColor Green
