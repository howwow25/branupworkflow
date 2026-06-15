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

git reset --hard origin/main
if ($LASTEXITCODE -ne 0) { throw 'git reset failed' }

Write-Host '[2/4] Test DB 확인...' -ForegroundColor Cyan
if (-not (Test-Path "$ScriptDir\data\db")) {
    New-Item -ItemType Directory -Path "$ScriptDir\data\db" -Force | Out-Null
}

Write-Host '[3/4] Building dashboard HTML...' -ForegroundColor Cyan
python dashboard_html.py
if ($LASTEXITCODE -ne 0) { throw 'dashboard_html.py failed' }

Write-Host '[4/4] Restarting TEST API server (port 8801)...' -ForegroundColor Cyan
# 기존 8801 포트 프로세스 종료
$proc = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'api_server' }
if ($proc) {
    # 여러 python 프로세스 중 8801 포트 사용 중인 것만 확인
    $killed = $false
    foreach ($p in $proc) {
        $conns = netstat -ano | Select-String "8801" | Select-String $p.Id
        if ($conns) {
            Stop-Process -Id $p.Id -Force
            Write-Host "  Killed old TEST API server (PID: $($p.Id))"
            $killed = $true
        }
    }
}

# TEST API 서버 시작 (포트 8801)
$apiScript = Join-Path $ScriptDir "api_server.py"
Start-Process python -ArgumentList $apiScript -WindowStyle Hidden
Write-Host '  TEST API server started on port 8801'

Write-Host ''
Write-Host 'Update complete!' -ForegroundColor Green
Write-Host "  대시보드: toffer.co.kr/branup/test/index.html"
Write-Host "  API:      toffer.co.kr/branup/test/api (→ localhost:8801)"
Write-Host "  프로덕션: toffer.co.kr/branup/branup-watcher (port 8800) - 영향 없음"
Write-Host ''
Write-Host '⚠️ Apache 설정 필요:' -ForegroundColor Yellow
Write-Host '  ProxyPass /branup/test/api http://localhost:8801/api'
Write-Host '  ProxyPassReverse /branup/test/api http://localhost:8801/api'
