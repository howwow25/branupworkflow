# 브랜업 업데이트 스크립트
# GitHub 최신 코드 반영 → 대시보드 재생성 → API 서버 재시작
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "📡 GitHub에서 최신 코드 가져오는 중..." -ForegroundColor Cyan
git fetch origin
if ($LASTEXITCODE -ne 0) { throw "git fetch 실패" }

git reset --hard origin/main
if ($LASTEXITCODE -ne 0) { throw "git reset 실패" }

Write-Host "📊 대시보드 HTML 생성 중..." -ForegroundColor Cyan
python dashboard_html.py
if ($LASTEXITCODE -ne 0) { throw "dashboard_html.py 실행 실패" }

Write-Host "🔄 API 서버 재시작 중..." -ForegroundColor Cyan
$proc = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "api_server" }
if ($proc) {
    Stop-Process -Id $proc.Id -Force
    Write-Host "  기존 API 서버 종료 (PID: $($proc.Id))"
}

Start-Process python -ArgumentList "api_server.py" -WindowStyle Hidden
Write-Host "  새 API 서버 시작됨"

Write-Host "✅ 업데이트 완료! 브라우저에서 Ctrl+Shift+R 새로고침" -ForegroundColor Green
