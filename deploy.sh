#!/bin/bash
# 브랜업 API 서버 → toffer.co.kr 배포 스크립트
# 서버에서 실행: ./deploy.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export BRANUP_DATA_DIR="${BRANUP_DATA_DIR:-$SCRIPT_DIR/data}"

echo "📥 Git pull..."
cd "$SCRIPT_DIR"
git pull origin main

# API 서버 재시작
echo "🔌 API 서버 재시작..."
pkill -f "api_server.py" 2>/dev/null || true
sleep 1

mkdir -p "$BRANUP_DATA_DIR/db"

nohup python3 "$SCRIPT_DIR/api_server.py" \
    > "$BRANUP_DATA_DIR/api-server.log" 2>&1 &

echo "✅ API 서버 시작됨 (PID: $!)"

# 대시보드 HTML 재생성 (선택)
if python3 "$SCRIPT_DIR/dashboard_html.py" 2>/dev/null; then
    echo "📊 대시보드 HTML 갱신 완료"
fi

echo "🌐 API: $(hostname -I 2>/dev/null || echo 'localhost'):8800"
echo "   Nginx 프록시 설정 시 /api → 127.0.0.1:8800"
