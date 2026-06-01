#!/usr/bin/env python3
"""
브랜업 대시보드용 간단한 REST API 서버
표준 라이브러리만 사용. http.server 기반.

엔드포인트:
  GET  /api/tasks/<id>        → task 상세 JSON
  PATCH /api/tasks/<id>       → task 필드 업데이트 (JSON body)
  DELETE /api/tasks/<id>      → task 삭제
  POST /api/tasks/<id>/complete → task 완료 처리
"""
import json
import os
import sys
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

DATA_DIR = os.environ.get("BRANUP_DATA_DIR",
    str(Path(__file__).parent.parent / "data"))

sys.path.insert(0, str(Path(__file__).parent))
from db import get_conn, get_task_by_id, update_task, now_iso


PORT = int(os.environ.get("BRANUP_API_PORT", "8800"))


class APIHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _parse_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _extract_task_id(self):
        parsed = urlparse(self.path)
        # /api/tasks/<id> or /api/tasks/<id>/complete
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "tasks":
            task_id = parts[2]
            return task_id, parts[3] if len(parts) > 3 else None
        return None, None

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        task_id, _ = self._extract_task_id()
        if not task_id:
            self._send_json({"error": "not found"}, 404)
            return

        task = get_task_by_id(task_id)
        if not task:
            self._send_json({"error": "task not found"}, 404)
            return

        self._send_json(task)

    def do_PATCH(self):
        task_id, _ = self._extract_task_id()
        if not task_id:
            self._send_json({"error": "not found"}, 404)
            return

        task = get_task_by_id(task_id)
        if not task:
            self._send_json({"error": "task not found"}, 404)
            return

        body = self._parse_body()
        allowed = {"title", "assignee", "due_at", "summary"}
        updates = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            self._send_json({"error": "no valid fields"}, 400)
            return

        update_task(task_id, **updates)

        # refresh
        task = get_task_by_id(task_id)
        self._send_json(task)

    def do_DELETE(self):
        task_id, _ = self._extract_task_id()
        if not task_id:
            self._send_json({"error": "not found"}, 404)
            return

        task = get_task_by_id(task_id)
        if not task:
            self._send_json({"error": "task not found"}, 404)
            return

        conn = get_conn()
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()
        self._send_json({"deleted": True, "id": task_id})

    def do_POST(self):
        task_id, action = self._extract_task_id()
        if not task_id or action != "complete":
            self._send_json({"error": "not found"}, 404)
            return

        task = get_task_by_id(task_id)
        if not task:
            self._send_json({"error": "task not found"}, 404)
            return

        ts = now_iso()
        update_task(task_id, status="완료", closed_at=ts)

        task = get_task_by_id(task_id)
        self._send_json(task)

    def log_message(self, format, *args):
        """조용한 로그"""
        pass


def main():
    server = HTTPServer(("127.0.0.1", PORT), APIHandler)
    print(f"🔌 브랜업 API 서버 시작: http://127.0.0.1:{PORT}")
    print(f"   종료: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 서버 종료")
        server.server_close()


if __name__ == "__main__":
    main()
