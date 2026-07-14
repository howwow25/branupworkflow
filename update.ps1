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
$apiScript = Join-Path $ScriptDir 'api_server.py'
if (-not (Test-Path $apiScript)) { throw "api_server.py not found: $apiScript" }

# ⚠️ 포트 기준 종료만으로는 부족하다.
# 윈도우의 SO_REUSEADDR 은 이미 LISTEN 중인 포트를 가로채는 것까지 허용해서
# api_server 프로세스가 같은 포트에 여러 개 공존할 수 있고, Get-NetTCPConnection 에는
# 그중 '승자' 하나만 보인다. 승자만 죽이면 뒤에 숨어 있던 옛 프로세스가 되살아나
# 새 코드를 배포해도 옛 API 가 응답한다 (실제로 2주 묵은 프로세스가 그렇게 살아남았다).
# → 포트 소유자 + api_server.py 를 실행 중인 파이썬 프로세스를 '모두' 찾아 종료한다.
$targets = @()
$targets += Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess

# 이 인스턴스의 api_server.py 프로세스 (테스트 인스턴스는 자기 폴더 절대경로로 뜨므로 제외됨)
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
        $cmd = $_.CommandLine
        $cmd -and $cmd -match 'api_server\.py' -and
        ($cmd -match [regex]::Escape($apiScript) -or $cmd -notmatch '[\\/][^\\/"]*api_server\.py')
    } | ForEach-Object { $targets += $_.ProcessId }

$targets = $targets | Sort-Object -Unique
if ($targets) {
    foreach ($procId in $targets) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host "  Killed old API server (PID: $procId)"
        } catch {
            Write-Host "  Failed to kill PID $procId : $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
    Start-Sleep -Seconds 1
} else {
    Write-Host "  No existing API server process found"
}

# 포트가 실제로 비었는지 확인 (안 비었으면 못 죽인 프로세스가 있다는 뜻)
$still = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($still) {
    $stillPids = ($still | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
    throw "포트 $Port 가 여전히 점유 중입니다 (PID: $stillPids). 관리자 권한으로 재실행하거나 해당 프로세스를 직접 종료하세요."
}

# ⚠️ Start-Process 는 Set-Location 을 따라가지 않는다.
# 상대경로('api_server.py')로 띄우면 엉뚱한 작업 디렉터리에서 파일을 못 찾아
# 새 서버가 조용히 안 뜨고, 옛 프로세스만 남는다 → 절대경로 + -WorkingDirectory 필수.
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
