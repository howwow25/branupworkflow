# branup TEST 인스턴스 업데이트 스크립트
# 용도: toffer.co.kr/branup/test (마일스톤#2 테스트)
# 기존 toffer.co.kr/branup/branup-watcher 와 독립 실행

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# ⚠️ TEST 인스턴스 전용 환경변수
$env:BRANUP_DATA_DIR = "$ScriptDir\data"
$env:BRANUP_API_PORT = "8801"
$env:BRANUP_API_BASE = "/branup/test/api"

Write-Host '[1/4] Git pull...' -ForegroundColor Cyan
git fetch origin
if ($LASTEXITCODE -ne 0) { throw 'git fetch failed' }

git reset --hard origin/delay-process-1
if ($LASTEXITCODE -ne 0) { throw 'git reset failed' }

Write-Host '[2/4] Test DB 확인...' -ForegroundColor Cyan
if (-not (Test-Path "$ScriptDir\data\db")) {
    New-Item -ItemType Directory -Path "$ScriptDir\data\db" -Force | Out-Null
}

Write-Host '[3/4] Building dashboard HTML...' -ForegroundColor Cyan
python dashboard_html.py
if ($LASTEXITCODE -ne 0) { throw 'dashboard_html.py failed' }

Write-Host '[4/4] Restarting TEST API server (port 8801)...' -ForegroundColor Cyan
# 포트 8801을 점유한 기존 프로세스를 PID 기준으로 확실히 종료
# (CommandLine 은 Windows에서 비어있을 수 있어 신뢰 불가 → 포트 소유 PID 직접 조회)
$conns = Get-NetTCPConnection -LocalPort 8801 -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $pids) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host "  Killed old TEST API server (PID: $procId)"
        } catch {
            Write-Host "  Failed to kill PID $procId : $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    Start-Sleep -Seconds 1
} else {
    Write-Host '  No existing server on port 8801'
}

# TEST API 서버 시작 (포트 8801)
$apiScript = Join-Path $ScriptDir "api_server.py"
Start-Process python -ArgumentList $apiScript -WindowStyle Hidden
Start-Sleep -Seconds 2
# 기동 확인 — 포트 바인딩 여부로 실제 기동 확인
$check = Get-NetTCPConnection -LocalPort 8801 -State Listen -ErrorAction SilentlyContinue
if ($check) {
    Write-Host '  TEST API server started on port 8801' -ForegroundColor Green
} else {
    Write-Host '  WARNING: TEST API server NOT listening on 8801 - check api-server errors' -ForegroundColor Red
}

Write-Host ''
Write-Host 'Update complete!' -ForegroundColor Green
Write-Host "  대시보드: toffer.co.kr/branup/test/index.html"
Write-Host "  API:      toffer.co.kr/branup/test/api (→ localhost:8801)"
Write-Host "  프로덕션: toffer.co.kr/branup/branup-watcher (port 8800) - 영향 없음"
Write-Host ''
Write-Host '⚠️ Apache 설정 필요 (httpd.conf):' -ForegroundColor Yellow
Write-Host '  ProxyPass /branup/test http://localhost:8801/'
Write-Host '  ProxyPassReverse /branup/test http://localhost:8801/'
Write-Host ''
Write-Host '  접속: http://toffer.co.kr/branup/test/'
