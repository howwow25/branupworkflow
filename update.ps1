# branup 운영(branup-watcher) 업데이트 스크립트
# git pull -> dashboard rebuild -> api server restart -> 검증
# 대시보드: http://toffer.co.kr/branup/branup-watcher/
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# ── 환경변수 ────────────────────────────────────────────────
# BRANUP_DATA_DIR 은 의도적으로 건드리지 않는다.
# 이 머신에 이미 시스템/사용자 환경변수로 잡혀 있고, 여기서 덮어쓰면
# 운영 DB 경로가 바뀌어 업무가 전부 사라진 것처럼 보인다.
if (-not $env:BRANUP_API_PORT) { $env:BRANUP_API_PORT = '8800' }
if (-not $env:BRANUP_API_BASE) { $env:BRANUP_API_BASE = '/branup/branup-watcher/api' }
$Port = [int]$env:BRANUP_API_PORT

Write-Host '[0/4] 적용되는 설정' -ForegroundColor Cyan
Write-Host "  BRANUP_DATA_DIR = $(if ($env:BRANUP_DATA_DIR) { $env:BRANUP_DATA_DIR } else { '(미설정 → 기본값: <스크립트 상위>\data)' })"
Write-Host "  BRANUP_API_PORT = $env:BRANUP_API_PORT"
Write-Host "  BRANUP_API_BASE = $env:BRANUP_API_BASE"

Write-Host '[1/4] Pulling latest from GitHub...' -ForegroundColor Cyan
git fetch origin
if ($LASTEXITCODE -ne 0) { throw 'git fetch failed' }

git reset --hard origin/main
if ($LASTEXITCODE -ne 0) { throw 'git reset failed' }
Write-Host "  now at: $(git log --oneline -1)"

Write-Host '[2/4] Building dashboard HTML...' -ForegroundColor Cyan
python dashboard_html.py
if ($LASTEXITCODE -ne 0) { throw 'dashboard_html.py failed' }

Write-Host "[3/4] Restarting API server (port $Port)..." -ForegroundColor Cyan
# 포트를 점유한 기존 프로세스를 PID 기준으로 확실히 종료
# (CommandLine 은 Windows에서 비어있을 수 있어 신뢰 불가 → 포트 소유 PID 직접 조회)
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($conns) {
    $procIds = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $procIds) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host "  Killed old API server (PID: $procId)"
        } catch {
            Write-Host "  Failed to kill PID $procId : $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    Start-Sleep -Seconds 1
} else {
    Write-Host "  No existing server on port $Port"
}

# ⚠️ Start-Process 는 Set-Location 을 따라가지 않는다.
# 상대경로('api_server.py')로 띄우면 엉뚱한 작업 디렉터리에서 파일을 못 찾아
# 새 서버가 조용히 안 뜨고, 옛 프로세스만 남는다 → 절대경로 + -WorkingDirectory 필수.
$apiScript = Join-Path $ScriptDir 'api_server.py'
if (-not (Test-Path $apiScript)) { throw "api_server.py not found: $apiScript" }
Start-Process python -ArgumentList $apiScript -WorkingDirectory $ScriptDir -WindowStyle Hidden
Start-Sleep -Seconds 2

$check = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $check) {
    throw "API server NOT listening on $Port - 기동 실패. 다음으로 원인 확인: python `"$apiScript`""
}
Write-Host "  New API server started (port $Port)" -ForegroundColor Green

Write-Host '[4/4] 배포 검증...' -ForegroundColor Cyan
# 살아있는 서버가 정말 최신 코드인지 확인한다.
# 존재하지 않는 업무 ID로 드랍존을 호출 → 데이터는 바뀌지 않고 라우팅 유무만 판별된다.
#   {"error":"task not found"} = 최신 코드 (엔드포인트 있음)
#   {"error":"not found"}      = 옛 코드   (엔드포인트 없음 = 재시작 실패)
# 404 응답이므로 Invoke-WebRequest 는 예외를 던진다. 본문을 꺼내 판별한다.
# (PowerShell 5.1 / 7 모두에서 동작하도록 두 경로를 모두 처리)
$probeUri = "http://127.0.0.1:$Port/api/tasks/__deploy_probe__/dropzone"
try {
    $body = (Invoke-WebRequest -Method POST -Uri $probeUri -TimeoutSec 5 -UseBasicParsing).Content
} catch {
    $body = $_.ErrorDetails.Message
    if (-not $body) {
        try {
            $stream = $_.Exception.Response.GetResponseStream()
            $body = (New-Object System.IO.StreamReader($stream)).ReadToEnd()
        } catch {
            $body = "(probe failed: $($_.Exception.Message))"
        }
    }
}

if ($body -match 'task not found') {
    Write-Host '  OK: 최신 코드가 서비스 중입니다.' -ForegroundColor Green
} else {
    Write-Host "  WARNING: 살아있는 서버가 옛 코드입니다. 응답: $body" -ForegroundColor Red
    Write-Host '  → 포트를 점유한 프로세스가 이 폴더의 api_server.py 가 아닐 수 있습니다:' -ForegroundColor Red
    Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
            Get-CimInstance Win32_Process -Filter "ProcessId=$_" |
                Select-Object ProcessId, CreationDate, CommandLine | Format-List
        }
}

Write-Host ''
Write-Host 'Update complete! Ctrl+Shift+R to refresh dashboard' -ForegroundColor Green
Write-Host '  대시보드: http://toffer.co.kr/branup/branup-watcher/'
