#!/usr/bin/env python3
"""
브랜업 대시보드용 간단한 REST API 서버
표준 라이브러리만 사용. http.server 기반.

엔드포인트:
  GET   /api/tasks/<id>           → task 상세 JSON
  PATCH  /api/tasks/<id>          → task 필드 업데이트 (JSON body)
  DELETE /api/tasks/<id>          → task 삭제
  POST   /api/tasks/<id>/complete → task 완료 처리
  POST   /api/agent               → 자연어 에이전트 명령어 처리
"""
import json
import os
import sys
import re
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote, quote

DATA_DIR = os.environ.get("BRANUP_DATA_DIR",
    str(Path(__file__).parent.parent / "data"))

sys.path.insert(0, str(Path(__file__).parent))
from db import (get_conn, get_task_by_id, update_task, now_iso,
                get_active_tasks, get_completed_tasks,
                create_task, get_room_by_chat_id, upsert_room,
                get_task_by_display_num,
                get_projects, get_project_by_id, create_project,
                update_project, delete_project, get_tasks_by_project,
                add_file, get_files_by_task, get_files_by_project,
                get_file_by_id, get_file_path, delete_file,
                get_file_size_sum)


PORT = int(os.environ.get("BRANUP_API_PORT", "8800"))


def parse_text(text):
    """자연어 텍스트에서 제목/담당/마감/내용 추출"""
    title, assignee, due, priority, content = None, None, None, None, None

    # 내용 추출 (제일 먼저 — 줄바꿈 포함할 수 있으므로)
    m = re.search(r'내용\s*[:：]\s*(.+?)(?:\n(?:제목|담당|마감|우선|피드백)\s*[:：]|$)', text, re.IGNORECASE | re.DOTALL)
    if m:
        content = m.group(1).strip()

    # 제목 추출
    m = re.search(r'제목\s*[:：]\s*(.+?)(?:\n|담당|마감|우선|내용|$)', text, re.IGNORECASE)
    if m:
        title = m.group(1).strip()

    # 담당자 추출
    m = re.search(r'담당(?:자)?\s*[:：]\s*(.+?)(?:\n|마감|제목|우선|내용|$)', text, re.IGNORECASE)
    if m:
        assignee = m.group(1).strip()

    # 우선순위 추출
    m = re.search(r'우선(?:순위)?\s*[:：]\s*(긴급|높음|중간|낮음)', text, re.IGNORECASE)
    if m:
        priority = m.group(1)

    # 마감 추출 및 날짜 변환
    m = re.search(r'마감\s*[:：]\s*(.+?)(?:\n|제목|담당|내용|$)', text, re.IGNORECASE)
    if m:
        raw_due = m.group(1).strip()
        if re.match(r'\d{4}-\d{2}-\d{2}', raw_due):
            due = raw_due[:10]
        else:
            dm = re.search(r'(\d{1,2})[/.](\d{1,2})', raw_due)
            if dm:
                from datetime import datetime, timezone, timedelta
                month, day = int(dm.group(1)), int(dm.group(2))
                year = datetime.now(timezone(timedelta(hours=9))).year
                try:
                    due = f"{year}-{month:02d}-{day:02d}"
                except Exception:
                    due = None

    # 제목이 없으면 첫 줄 사용
    if not title:
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        for line in lines:
            if not re.match(r'(업무지시|담당|마감|제목)', line):
                title = line[:50]
                break
        if not title and lines:
            title = lines[0][:50]

    return title, assignee, due, priority, content


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

    def _refresh_dashboard(self):
        """DB 변경 후 대시보드 HTML 재생성 (dashboard_html.py가 index.html도 함께 생성)"""
        try:
            import subprocess
            scripts_dir = Path(__file__).parent
            subprocess.Popen(
                [sys.executable, str(scripts_dir / "dashboard_html.py")],
                env={**os.environ, "BRANUP_DATA_DIR": DATA_DIR,
                     "BRANUP_API_PORT": str(PORT),
                     "BRANUP_API_BASE": os.environ.get("BRANUP_API_BASE", "")},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def _parse_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _extract_task_id(self):
        parsed = urlparse(self.path)
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
        parsed = urlparse(self.path)
        path = parsed.path

        # 대시보드 HTML 서빙
        if path == "/" or path == "/dashboard.html" or path == "/index.html":
            dashboard_path = Path(DATA_DIR) / "dashboard.html"
            if dashboard_path.exists():
                html = dashboard_path.read_text(encoding="utf-8")
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self._cors_headers()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send_json({"error": "dashboard not found"}, 404)
            return

        # /api/projects → 프로젝트 목록
        if path == "/api/projects":
            projects = get_projects()
            self._send_json(projects)
            return

        # /api/projects/<id>/tasks → 프로젝트별 업무
        m = re.match(r'^/api/projects/([^/]+)/tasks$', path)
        if m:
            tasks = get_tasks_by_project(unquote(m.group(1)))
            self._send_json(tasks)
            return

        # /api/tasks/list → 전체 활성 업무
        if path == "/api/tasks/list":
            tasks = get_active_tasks()
            self._send_json(tasks)
            return

        # /api/tasks/completed → 전체 완료 업무
        if path == "/api/tasks/completed":
            tasks = get_completed_tasks()
            self._send_json(tasks)
            return

        # /api/weekly-report?assignee=강경철 → 주간리포트 요청
        if path == "/api/weekly-report":
            self._handle_weekly_report()
            return

        # /api/reports/<filename> → 리포트 md 파일 다운로드
        m = re.match(r'^/api/reports/([^/]+\.md)$', path)
        if m:
            filename = unquote(m.group(1))
            filepath = Path(DATA_DIR) / "reports" / filename
            if filepath.exists():
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(filepath.stat().st_size))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                with open(filepath, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self._send_json({"error": "파일을 찾을 수 없습니다"}, 404)
            return

        # /api/rooms/<chat_id> → room 조회
        m = re.match(r'^/api/rooms/([^/]+)$', path)
        if m:
            room = get_room_by_chat_id(unquote(m.group(1)))
            if room:
                self._send_json(room)
            else:
                self._send_json({"error": "not found"}, 404)
            return

        # /api/rooms/<room_id>/tasks → room별 업무
        m = re.match(r'^/api/rooms/([^/]+)/tasks$', path)
        if m:
            tasks = get_tasks_by_room(unquote(m.group(1)))
            self._send_json(tasks)
            return

        # /api/projects/<id> → 프로젝트 상세
        m = re.match(r'^/api/projects/([^/]+)$', path)
        if m:
            proj = get_project_by_id(unquote(m.group(1)))
            if proj:
                self._send_json(proj)
            else:
                self._send_json({"error": "project not found"}, 404)
            return

        # /api/tasks/<id>/files → 업무 파일 목록
        m = re.match(r'^/api/tasks/([^/]+)/files$', path)
        if m:
            task_id = unquote(m.group(1))
            task = get_task_by_id(task_id)
            if not task:
                self._send_json({"error": "task not found"}, 404)
                return
            files = get_files_by_task(task_id)
            self._send_json(files)
            return

        # /api/projects/<id>/files → 프로젝트 파일 목록
        m = re.match(r'^/api/projects/([^/]+)/files$', path)
        if m:
            project_id = unquote(m.group(1))
            proj = get_project_by_id(project_id)
            if not proj:
                self._send_json({"error": "project not found"}, 404)
                return
            files = get_files_by_project(project_id)
            self._send_json(files)
            return

        # /api/files/<id> → 파일 다운로드
        m = re.match(r'^/api/files/([^/]+)$', path)
        if m:
            file_id = unquote(m.group(1))
            file_rec = get_file_by_id(file_id)
            if not file_rec:
                self._send_json({"error": "file not found"}, 404)
                return
            filepath = get_file_path(file_rec)
            if not filepath.exists():
                self._send_json({"error": "file missing"}, 404)
                return
            content = filepath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", file_rec.get("mime_type", "application/octet-stream"))
            self.send_header("Content-Disposition",
                f"attachment; filename*=UTF-8''{quote(file_rec['original_name'], safe='')}")
            self._cors_headers()
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

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
        path = urlparse(self.path).path

        # /api/projects/<id> → 프로젝트 수정 (권한 체크 포함)
        m = re.match(r'^/api/projects/([^/]+)$', path)
        if m:
            self._handle_project_patch(unquote(m.group(1)))
            return

        task_id, _ = self._extract_task_id()
        if not task_id:
            self._send_json({"error": "not found"}, 404)
            return

        task = get_task_by_id(task_id)
        if not task:
            self._send_json({"error": "task not found"}, 404)
            return

        body = self._parse_body()
        allowed = {"title", "assignee", "due_at", "summary", "priority", "feedback", "related_tasks", "project_id"}
        updates = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            self._send_json({"error": "no valid fields"}, 400)
            return

        update_task(task_id, **updates)
        task = get_task_by_id(task_id)
        self._refresh_dashboard()
        self._send_json(task)

    def do_DELETE(self):
        parts = urlparse(self.path).path.strip("/").split("/")

        # /api/projects/<id> → 프로젝트 삭제
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "projects":
            self._handle_project_delete(parts[2])
            return

        # /api/tasks/<id>/related/<display_num> → 연관업무 삭제
        if len(parts) == 5 and parts[0] == "api" and parts[1] == "tasks" and parts[3] == "related":
            self._handle_remove_related(parts[2], parts[4])
            return

        # /api/files/<id> → 파일 삭제
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "files":
            self._handle_file_delete(parts[2])
            return

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
        self._refresh_dashboard()
        self._send_json({"deleted": True, "id": task_id})

    def do_POST(self):
        parts = urlparse(self.path).path.strip("/").split("/")

        # /api/agent → 에이전트 명령어
        if len(parts) >= 2 and parts[0] == "api" and parts[1] == "agent":
            self._handle_agent()
            return

        # /api/projects → 프로젝트 생성
        if len(parts) == 2 and parts[0] == "api" and parts[1] == "projects":
            self._handle_project_create()
            return

        # /api/projects/<id>/tasks → 프로젝트에 업무 추가
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "tasks":
            self._handle_project_task_create(parts[2])
            return

        # /api/tasks → 새 업무 생성
        if len(parts) == 2 and parts[0] == "api" and parts[1] == "tasks":
            self._handle_create()
            return

        # /api/rooms → room 생성/조회
        if len(parts) == 2 and parts[0] == "api" and parts[1] == "rooms":
            self._handle_rooms_create()
            return

        # /api/tasks/<id>/related → 연관업무 추가
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "tasks" and parts[3] == "related":
            self._handle_add_related(parts[2])
            return

        # /api/tasks/<id>/files → 업무 파일 업로드
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "tasks" and parts[3] == "files":
            self._handle_file_upload(task_id=unquote(parts[2]))
            return

        # /api/projects/<id>/files → 프로젝트 파일 업로드
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "files":
            self._handle_file_upload(project_id=unquote(parts[2]))
            return

        # /api/tasks/<id>/complete
        task_id, action = self._extract_task_id()
        if not task_id or action != "complete":
            # /api/tasks/<id>/uncomplete 시도
            if task_id and action == "uncomplete":
                self._handle_uncomplete(task_id)
                return
            self._send_json({"error": "not found"}, 404)
            return

        task = get_task_by_id(task_id)
        if not task:
            self._send_json({"error": "task not found"}, 404)
            return

        ts = now_iso()
        update_task(task_id, status="완료", closed_at=ts)
        task = get_task_by_id(task_id)
        self._refresh_dashboard()
        self._send_json(task)

    # ── 파일 업로드/삭제 핸들러 ──────────────────────────

    def _parse_multipart(self):
        """multipart/form-data 파싱 → {filename: (data, content_type)}"""
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            return {}
        import cgi, io
        # boundary 추출
        boundary = None
        for part in content_type.split(";"):
            part = part.strip()
            if part.startswith("boundary="):
                boundary = part[9:]
        if not boundary:
            return {}
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        # multipart 파싱
        result = {}
        raw = b"--" + boundary.encode() + b"\r\n" + body + b"\r\n--" + boundary.encode() + b"--"
        # 간단한 수동 파싱 (cgi.FieldStorage는 wsgi 전용이므로)
        parts = body.split(b"--" + boundary.encode())
        for part in parts:
            if b"Content-Disposition" not in part:
                continue
            headers_end = part.find(b"\r\n\r\n")
            if headers_end == -1:
                continue
            headers_raw = part[:headers_end].decode("utf-8", errors="replace")
            data = part[headers_end + 4:]
            if data.endswith(b"\r\n"):
                data = data[:-2]
            # filename 추출
            filename = None
            for line in headers_raw.split("\r\n"):
                if "filename=" in line:
                    import re
                    m = re.search(r'filename="([^"]*)"', line)
                    if m:
                        filename = m.group(1)
            if filename and data:
                result[filename] = data
        return result

    def _handle_file_upload(self, task_id=None, project_id=None):
        """POST /api/tasks/<id>/files 또는 /api/projects/<id>/files"""
        LIMITS = {
            "file": 20 * 1024 * 1024,      # 20MB per file
            "task": 50 * 1024 * 1024,      # 50MB per task
            "project": 200 * 1024 * 1024,  # 200MB per project
        }

        # 소유자 확인
        if task_id:
            owner = get_task_by_id(task_id)
            if not owner:
                self._send_json({"error": "task not found"}, 404)
                return
            current_total = get_file_size_sum(task_id=task_id)
            max_total = LIMITS["task"]
        elif project_id:
            owner = get_project_by_id(project_id)
            if not owner:
                self._send_json({"error": "project not found"}, 404)
                return
            current_total = get_file_size_sum(project_id=project_id)
            max_total = LIMITS["project"]
        else:
            self._send_json({"error": "task_id or project_id required"}, 400)
            return

        files = self._parse_multipart()
        if not files:
            self._send_json({"error": "no files uploaded"}, 400)
            return

        uploaded = []
        errors = []
        for filename, data in files.items():
            size = len(data)
            # 개별 파일 크기 제한
            if size > LIMITS["file"]:
                errors.append(f"{filename}: {size/1024/1024:.1f}MB (20MB 제한 초과)")
                continue
            # 총량 제한 체크
            if current_total + size > max_total:
                limit_mb = max_total / 1024 / 1024
                errors.append(f"{filename}: 총량 {limit_mb:.0f}MB 제한 초과")
                continue
            # MIME 추정
            ext = Path(filename).suffix.lower()
            mime_map = {
                ".pdf": "application/pdf",
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ".xls": "application/vnd.ms-excel",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".doc": "application/msword",
                ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                ".ppt": "application/vnd.ms-powerpoint",
                ".zip": "application/zip", ".hwp": "application/haansofthwp",
            }
            mime = mime_map.get(ext, "application/octet-stream")
            rec = add_file(task_id=task_id, project_id=project_id,
                          original_name=filename, file_data=data, mime_type=mime)
            current_total += size
            uploaded.append(rec)

        self._send_json({"uploaded": uploaded, "errors": errors})

    def _handle_file_delete(self, file_id):
        """DELETE /api/files/<id>"""
        rec = get_file_by_id(unquote(file_id))
        if not rec:
            self._send_json({"error": "file not found"}, 404)
            return
        delete_file(unquote(file_id))
        self._send_json({"deleted": True, "file_id": file_id,
                         "original_name": rec["original_name"]})

    # ── 주간리포트 요청 처리 ──────────────────────────

    def _handle_weekly_report(self):
        """GET /api/weekly-report?assignee=강경철&week_start=2026-06-15&week_end=2026-06-21 → Hermes에 분석 요청 (비동기)"""
        from urllib.parse import parse_qs

        API_BASE = os.environ.get("BRANUP_API_BASE", "")
        report = None

        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        assignee = qs.get("assignee", [None])[0]
        week_start_str = qs.get("week_start", [None])[0]
        week_end_str = qs.get("week_end", [None])[0]

        if not assignee:
            self._send_json({"error": "assignee 파라미터가 필요합니다"}, 400)
            return

        # ── 기준 주 범위 결정 (파라미터 없으면 이번주) ──
        from datetime import datetime, timezone, timedelta
        KST = timezone(timedelta(hours=9))
        today = datetime.now(KST).date()

        if week_start_str and week_end_str:
            try:
                monday = datetime.strptime(week_start_str, "%Y-%m-%d").date()
                sunday = datetime.strptime(week_end_str, "%Y-%m-%d").date()
            except ValueError:
                self._send_json({"error": "날짜 형식이 올바르지 않습니다 (YYYY-MM-DD)"}, 400)
                return
        else:
            monday = today - timedelta(days=today.weekday())
            sunday = monday + timedelta(days=6)

        # ── 해당 직원의 모든 업무 조회 (진행중+완료) ──
        conn = get_conn()
        rows = conn.execute(
            """SELECT display_num, title, status, summary, due_at, assignee,
                      priority, created_at, closed_at, project_id, feedback, related_tasks
               FROM tasks
               WHERE assignee LIKE ?
                 AND status NOT IN ('보류')
               ORDER BY due_at ASC""",
            (f"%{assignee}%",)
        ).fetchall()

        tasks = []
        for r in rows:
            t = dict(r)
            due = t.get("due_at", "")
            closed = t.get("closed_at", "")
            try:
                if due:
                    d = datetime.strptime(due[:10], "%Y-%m-%d").date()
                    if monday <= d <= sunday:
                        t["_in_week"] = True
                    else:
                        t["_in_week"] = False
                elif closed:
                    d = datetime.strptime(closed[:10], "%Y-%m-%d").date()
                    if monday <= d <= sunday:
                        t["_in_week"] = True
                    else:
                        t["_in_week"] = False
                else:
                    t["_in_week"] = False
            except Exception:
                t["_in_week"] = False
            tasks.append(t)

        # ── JSON 페이로드 구성 ──
        payload = {
            "assignee": assignee,
            "week_start": monday.isoformat(),
            "week_end": sunday.isoformat(),
            "total": len(tasks),
            "tasks": tasks
        }

        # ── Hermes로 리포트 전송 (로컬에서 weekly_report.py 실행 후 결과만 전송) ──
        import subprocess
        import tempfile
        from datetime import datetime as dt_now

        log_dir = Path(DATA_DIR) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "telethon_weekly.log"

        # ── 그룹챗 ID (브랜업 그룹) ──
        group_chat_id = os.environ.get("BRANUP_GROUP_CHAT_ID", "51271702")

        try:
            # 1. 페이로드 임시파일 저장
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                              delete=False, encoding="utf-8")
            tmp.write(json.dumps(payload, ensure_ascii=False))
            payload_file = tmp.name
            tmp.close()

            # 2. weekly_report.py 실행 → .md 리포트 생성
            report_script = os.path.join(os.path.dirname(__file__), "weekly_report.py")
            report_result = subprocess.run(
                [sys.executable, report_script, "--file", payload_file],
                capture_output=True, text=True, timeout=30,
                env=os.environ.copy()
            )
            report = json.loads(report_result.stdout.strip())

            if report.get("ok"):
                md_content = report.get("md_content", "")
                # 3. .md 내용을 텔레그램으로 전송 (길이 제한 체크)
                bridge_script = os.path.join(os.path.dirname(__file__), "telethon_bridge.py")
                env = os.environ.copy()

                # ── 직원 → Telegram ID 매핑 (환경변수 BRANUP_TG_이름=chat_id) ──
                tg_map = {}
                for key, val in os.environ.items():
                    if key.startswith("BRANUP_TG_"):
                        name = key[len("BRANUP_TG_"):]
                        tg_map[name] = val

                # 전송 대상 목록: 그룹챗 + 개인 DM
                targets = [(group_chat_id, "그룹챗")]
                if assignee in tg_map:
                    targets.append((tg_map[assignee], f"{assignee}님 DM"))

                def send_to(chat_id, label):
                    if len(md_content) < 3800:
                        msg = f"📊 *{assignee} 주간리포트*\n{md_content}"
                        with open(log_file, "a", encoding="utf-8") as lf:
                            lf.write(f"\n[{dt_now.now().isoformat()}] sending as msg to {label} ({chat_id}) ({len(md_content)} chars)\n")
                            subprocess.Popen(
                                [sys.executable, bridge_script, "--msg", msg, "--timeout", "15",
                                 "--chat-id", chat_id],
                                env=env, stdout=lf, stderr=lf,
                                cwd=os.path.dirname(__file__)
                            )
                    else:
                        report_path = report.get("report_path")
                        with open(log_file, "a", encoding="utf-8") as lf:
                            lf.write(f"\n[{dt_now.now().isoformat()}] sending as file to {label} ({chat_id}): {report_path}\n")
                            subprocess.Popen(
                                [sys.executable, bridge_script, "--send-file", report_path,
                                 "--caption", f"📊 {assignee} 주간리포트",
                                 "--chat-id", chat_id],
                                env=env, stdout=lf, stderr=lf,
                                cwd=os.path.dirname(__file__)
                            )

                for chat_id, label in targets:
                    send_to(chat_id, label)
            else:
                with open(log_file, "a", encoding="utf-8") as lf:
                    lf.write(f"[ERROR] report generation failed: {report}\n")

            # 임시파일 정리
            try:
                os.unlink(payload_file)
            except Exception:
                pass

        except Exception as e:
            try:
                with open(log_file, "a", encoding="utf-8") as lf:
                    lf.write(f"[ERROR] {e}\n")
            except Exception:
                pass

        # ── 백업: 요청 파일로도 저장 ──
        try:
            requests_dir = Path(DATA_DIR) / "weekly_requests"
            requests_dir.mkdir(parents=True, exist_ok=True)
            ts = dt_now.now().strftime("%Y%m%d_%H%M%S")
            req_file = requests_dir / f"{ts}_{assignee}.json"
            req_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        resp = {
            "ok": True,
            "message": f"📊 {assignee}님 주간리포트 생성 완료!"
        }
        if report and report.get("filename"):
            resp["filename"] = report["filename"]
            resp["download_url"] = f"{API_BASE}/api/reports/{report['filename']}"
        self._send_json(resp)

    # ── 에이전트 명령어 처리 ──────────────────────────

    def _handle_uncomplete(self, task_id):
        """POST /api/tasks/<id>/uncomplete → 완료 취소, 진행중으로 복원"""
        task = get_task_by_id(task_id)
        if not task:
            self._send_json({"error": "task not found"}, 404)
            return

        if task.get("status") != "완료":
            self._send_json({"error": "완료된 업무만 취소할 수 있습니다"}, 400)
            return

        update_task(task_id, status="진행중", closed_at=None)
        task = get_task_by_id(task_id)
        self._refresh_dashboard()
        self._send_json(task)

    def _handle_create(self):
        """POST /api/tasks → 새 업무 생성"""
        body = self._parse_body()
        title = body.get("title", "").strip()
        if not title:
            self._send_json({"error": "제목은 필수입니다"}, 400)
            return

        room = get_room_by_chat_id("dashboard")
        if not room:
            room = upsert_room("dashboard", "web", "대시보드")

        task = create_task(
            room["id"],
            title=title,
            summary=body.get("summary") or title,
            due_at=body.get("due_at"),
            assignee=body.get("assignee"),
            priority=body.get("priority", "중간"),
            project_id=body.get("project_id"),
        )
        self._refresh_dashboard()
        self._send_json(task)

    # ── 프로젝트 핸들러 ────────────────────────────────

    def _handle_project_create(self):
        """POST /api/projects → 프로젝트 생성"""
        body = self._parse_body()
        title = body.get("title", "").strip()
        if not title:
            self._send_json({"error": "제목은 필수입니다"}, 400)
            return

        room = get_room_by_chat_id("dashboard")
        if not room:
            room = upsert_room("dashboard", "web", "대시보드")

        proj = create_project(
            room["id"],
            title=title,
            description=body.get("description", ""),
            status=body.get("status", "계획"),
            start_date=body.get("start_date"),
            expected_end_date=body.get("expected_end_date"),
            assignees=body.get("assignees", ""),
        )
        self._refresh_dashboard()
        self._send_json(proj)

    def _handle_project_patch(self, project_id):
        """PATCH /api/projects/<id> → 프로젝트 수정 (권한 체크)"""
        proj = get_project_by_id(project_id)
        if not proj:
            self._send_json({"error": "project not found"}, 404)
            return

        body = self._parse_body()
        # 권한 체크: 상태/일정 필드는 이상원, 이향석만 수정 가능
        restricted = {"status", "start_date", "expected_end_date"}
        editor = body.get("_editor", "")
        if any(k in restricted for k in body):
            if editor and editor not in ("이상원", "이향석"):
                self._send_json({
                    "error": "상태와 일정은 이상원 또는 이향석만 수정할 수 있습니다",
                    "restricted_fields": list(restricted)
                }, 403)
                return

        update_project(project_id, **{k: v for k, v in body.items()
                       if k in {"title", "description", "status", "start_date", "expected_end_date", "assignees"}})
        proj = get_project_by_id(project_id)
        self._refresh_dashboard()
        self._send_json(proj)

    def _handle_project_delete(self, project_id):
        """DELETE /api/projects/<id> → 프로젝트 삭제"""
        proj = get_project_by_id(project_id)
        if not proj:
            self._send_json({"error": "project not found"}, 404)
            return
        delete_project(project_id)
        self._refresh_dashboard()
        self._send_json({"deleted": True, "id": project_id})

    def _handle_project_task_create(self, project_id):
        """POST /api/projects/<id>/tasks → 프로젝트에 업무 추가"""
        proj = get_project_by_id(project_id)
        if not proj:
            self._send_json({"error": "project not found"}, 404)
            return

        body = self._parse_body()
        title = body.get("title", "").strip()
        if not title:
            self._send_json({"error": "제목은 필수입니다"}, 400)
            return

        room = get_room_by_chat_id("dashboard")
        if not room:
            room = upsert_room("dashboard", "web", "대시보드")

        task = create_task(
            room["id"],
            title=title,
            summary=body.get("summary") or title,
            due_at=body.get("due_at"),
            assignee=body.get("assignee"),
            priority=body.get("priority", "중간"),
            project_id=project_id,
        )
        self._refresh_dashboard()
        self._send_json(task)

    def _handle_rooms_create(self):
        """POST /api/rooms → room 생성"""
        body = self._parse_body()
        room = upsert_room(
            body.get("chat_id", ""),
            body.get("chat_type", "supergroup"),
            body.get("name", "브랜업"),
        )
        self._send_json(room)

    def _handle_add_related(self, task_id):
        """POST /api/tasks/<id>/related → 연관업무 추가"""
        body = self._parse_body()
        display_num = body.get("display_num")
        if not display_num:
            self._send_json({"error": "display_num required"}, 400)
            return
        task = get_task_by_id(task_id)
        if not task:
            self._send_json({"error": "task not found"}, 404)
            return
        related = get_task_by_display_num(int(display_num))
        if not related:
            self._send_json({"error": f"#{display_num} 업무가 없습니다"}, 404)
            return
        current = (task.get("related_tasks") or "").strip()
        nums = [n.strip() for n in current.split(",") if n.strip()]
        if str(display_num) not in nums:
            nums.append(str(display_num))
        update_task(task_id, related_tasks=",".join(nums))

        # ── 상호참조: 연결된 업무에도 현재 업무 추가 ──
        my_num = str(task.get("display_num", ""))
        their_current = (related.get("related_tasks") or "").strip()
        their_nums = [n.strip() for n in their_current.split(",") if n.strip()]
        if my_num and my_num not in their_nums:
            their_nums.append(my_num)
            update_task(related["id"], related_tasks=",".join(their_nums))

        self._refresh_dashboard()
        self._send_json(get_task_by_id(task_id))

    def _handle_remove_related(self, task_id, display_num):
        """DELETE /api/tasks/<id>/related/<display_num> → 연관업무 삭제"""
        task = get_task_by_id(task_id)
        if not task:
            self._send_json({"error": "task not found"}, 404)
            return
        current = (task.get("related_tasks") or "").strip()
        nums = [n.strip() for n in current.split(",") if n.strip()]
        nums = [n for n in nums if n != str(display_num)]
        update_task(task_id, related_tasks=",".join(nums))

        # ── 상호참조: 연결된 업무에서도 현재 업무 삭제 ──
        my_num = str(task.get("display_num", ""))
        other = get_task_by_display_num(int(display_num))
        if other and my_num:
            their_current = (other.get("related_tasks") or "").strip()
            their_nums = [n.strip() for n in their_current.split(",") if n.strip()]
            their_nums = [n for n in their_nums if n != my_num]
            update_task(other["id"], related_tasks=",".join(their_nums))

        self._refresh_dashboard()
        self._send_json(get_task_by_id(task_id))

    def _handle_agent(self):
        body = self._parse_body()
        text = body.get("text", "").strip()
        assignee_filter = body.get("assignee", "")

        if not text:
            self._send_json({
                "type": "help",
                "message": (
                    "🤖 **브랜업 에이전트 명령어**\n\n"
                    "**업무 등록:**\n"
                    "`업무지시 제목:XXX 담당:XXX 마감:YYYY-MM-DD`\n\n"
                    "**업무 조회:**\n"
                    "`업무 보여줘` / `전체 업무` / `내 업무`\n\n"
                    "**업무 완료/삭제:**\n"
                    "`N번 완료` / `N번 삭제`\n\n"
                    "💡 카드 클릭 → 모달에서 상세 편집 가능"
                )
            })
            return

        # ── Telethon 중계 (실제 계정으로 Hermes DM에 전달) ──
        api_id = os.environ.get("TELEGRAM_API_ID", "")
        api_hash = os.environ.get("TELEGRAM_API_HASH", "")
        phone = os.environ.get("TELEGRAM_PHONE", "")
        if api_id and api_hash and phone:
            try:
                import subprocess
                script = os.path.join(os.path.dirname(__file__), "telethon_bridge.py")
                env = os.environ.copy()
                proc = subprocess.run(
                    [sys.executable, script, "--msg", text, "--timeout", "120"],
                    env=env,
                    capture_output=True, text=True, timeout=180,
                    cwd=os.path.dirname(__file__)
                )
                result = json.loads(proc.stdout.strip())
                if result.get("ok") and result.get("response"):
                    self._send_json({
                        "type": "hermes_response",
                        "message": result["response"]
                    })
                    return
                elif result.get("ok") and result.get("response") is None:
                    self._send_json({
                        "type": "no_response",
                        "message": f"⏰ Hermes 응답 대기 시간 초과\n> {text[:80]}"
                    })
                    return
            except Exception:
                pass  # 실패 시 로컬 처리로 폴백

        # ── 로컬 처리 (폴백) ──
        result = self._process_command(text, assignee_filter)
        self._send_json(result)

    def _process_command(self, text, assignee_filter):
        # ── 완료: "N번 완료", "N번 업무 완료" ──
        m = re.search(r'(\d+)\s*번\s*(업무\s*)?완료', text)
        if m:
            return self._complete_task(int(m.group(1)))

        # ── 삭제: "N번 삭제", "N번 지워" ──
        m = re.search(r'(\d+)\s*번\s*(업무\s*)?(삭제|지워)', text)
        if m:
            return self._delete_task(int(m.group(1)))

        # ── #N 업무 마감 변경 ──
        m = re.search(r'#(\d+)\s*(?:번\s*)?(?:업무\s*)?마감[은를]?\s*(.+?)(?:로|으로)?\s*(?:변경|수정)', text, re.IGNORECASE)
        if m:
            return self._update_field(int(m.group(1)), "마감", m.group(2).strip())

        # ── #N 내용추가 / #N 내용 / #N 피드백 ──
        m = re.search(r'#(\d+)\s*(?:번\s*)?(?:업무\s*)?(내용추가|내용|피드백)\s*[:：]\s*(.+)', text, re.IGNORECASE | re.DOTALL)
        if m:
            display_num = int(m.group(1))
            field = m.group(2)
            value = m.group(3).strip()
            return self._update_field(display_num, field, value)

        # ── 조회 ──
        list_patterns = [
            r'업무\s*(보여|리스트|목록|조회|현황)',
            r'전체\s*업무',
            r'리스트\s*업',
            r'모든\s*업무',
            r'업무\s*확인',
        ]
        is_list = any(re.search(p, text) for p in list_patterns)

        # "내 업무" 감지
        m_my = re.search(r'(내|나의)\s*업무', text)

        if m_my or is_list:
            tasks = get_active_tasks()
            if m_my and assignee_filter:
                tasks = [t for t in tasks
                         if t.get("assignee") and assignee_filter in t.get("assignee", "")]
            elif m_my:
                pass  # assignee_filter 없으면 전체 반환 (클라이언트에서 표시)

            count = len(tasks)
            if count == 0:
                return {
                    "type": "list",
                    "message": "📋 진행 중인 업무가 없습니다.",
                    "data": {"tasks": [], "count": 0}
                }

            # 담당자별 그룹
            from collections import defaultdict
            groups = defaultdict(list)
            for t in tasks:
                a = t.get("assignee") or "미정"
                groups[a].append(t)

            lines = [f"📋 **진행 중 업무 {count}건**\n"]
            for a, items in sorted(groups.items()):
                lines.append(f"👤 *{a}* ({len(items)}건)")
                for t in items:
                    due = t.get("due_at", "")[:10] if t.get("due_at") else "미정"
                    lines.append(f"  #{t['display_num']} {t['title']} | 마감: {due}")
                lines.append("")

            return {
                "type": "list",
                "message": "\n".join(lines),
                "data": {"tasks": tasks, "count": count}
            }

        # ── 등록: "업무지시", "업무 등록" 등 ──
        register_patterns = [
            r'업무\s*(지시|등록|추가|생성|만들)',
            r'등록\s*(해|하)',
            r'새\s*업무',
        ]
        is_register = any(re.search(p, text) for p in register_patterns)

        # 제목:XXX 담당:XXX 패턴 감지
        has_fields = bool(re.search(r'제목\s*[:：]', text)) or \
                     bool(re.search(r'담당\s*[:：]', text))

        if is_register or has_fields:
            title, assignee, due, priority, content = parse_text(text)
            if not title:
                return {
                    "type": "error",
                    "message": "❌ 제목을 추출할 수 없습니다.\n`제목:XXX 담당:XXX 마감:YYYY-MM-DD` 형식으로 입력해주세요."
                }

            room = get_room_by_chat_id("dashboard")
            if not room:
                room = upsert_room("dashboard", "web", "대시보드")

            task = create_task(
                room["id"],
                title=title,
                summary=content or title,
                due_at=due,
                assignee=assignee,
                priority=priority or "중간",
            )

            due_str = due or "미정"
            a_str = assignee or "미정"
            p_str = priority or "중간"
            return {
                "type": "register",
                "message": (
                    f"📋 **#{task['display_num']} 등록 완료!**\n"
                    f"제목: {title}\n"
                    f"담당: {a_str}\n"
                    f"마감: {due_str}\n"
                    f"우선순위: {p_str}"
                ),
                "data": {
                    "id": task["id"],
                    "display_num": task["display_num"],
                    "title": title,
                    "assignee": a_str,
                    "due_at": due_str,
                }
            }

        # ── 도움말 ──
        return {
            "type": "help",
            "message": (
                "🤖 **브랜업 에이전트 명령어**\n\n"
                "**업무 등록:**\n"
                "`업무지시 제목:XXX 담당:XXX 마감:YYYY-MM-DD`\n\n"
                "**업무 조회:**\n"
                "`업무 보여줘` / `전체 업무` / `내 업무`\n\n"
                "**업무 완료/삭제:**\n"
                "`N번 완료` / `N번 삭제`\n\n"
                "💡 카드 클릭 → 모달에서 상세 편집 가능"
            )
        }

    def _update_field(self, display_num, field, value):
        """#N 내용추가 / #N 내용 / #N 피드백 처리"""
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM tasks WHERE display_num=?", (display_num,)
        ).fetchone()
        if not row:
            return {
                "type": "error",
                "message": f"❌ #{display_num} 업무를 찾을 수 없습니다."
            }
        task = dict(row)

        if field == "내용추가":
            current = task.get("summary") or ""
            new_summary = (current + "\n" + value).strip()
            update_task(task["id"], summary=new_summary)
            self._refresh_dashboard()
            return {
                "type": "update",
                "message": f"📝 #{display_num} '{task['title']}' 내용 추가 완료\n> {value}"
            }
        elif field == "내용":
            update_task(task["id"], summary=value)
            self._refresh_dashboard()
            return {
                "type": "update",
                "message": f"📝 #{display_num} '{task['title']}' 내용 수정 완료\n> {value}"
            }
        elif field == "마감":
            update_task(task["id"], due_at=value)
            self._refresh_dashboard()
            return {
                "type": "update",
                "message": f"📅 #{display_num} '{task['title']}' 마감 변경 완료\n> {value}"
            }
        elif field == "피드백":
            update_task(task["id"], feedback=value)
            self._refresh_dashboard()
            return {
                "type": "update",
                "message": f"💬 #{display_num} '{task['title']}' 피드백 저장 완료\n> {value}"
            }
        return {"type": "error", "message": "알 수 없는 필드"}

    def _complete_task(self, display_num):
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM tasks WHERE display_num=?", (display_num,)
        ).fetchone()
        if not row:
            return {
                "type": "error",
                "message": f"❌ #{display_num} 업무를 찾을 수 없습니다."
            }
        task = dict(row)
        if task["status"] == "완료":
            return {
                "type": "error",
                "message": f"⚠️ #{display_num} '{task['title']}' 이미 완료된 업무입니다."
            }

        ts = now_iso()
        update_task(task["id"], status="완료", closed_at=ts)
        return {
            "type": "complete",
            "message": f"✅ #{display_num} '{task['title']}' 완료 처리되었습니다!",
            "data": {"display_num": display_num}
        }

    def _delete_task(self, display_num):
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM tasks WHERE display_num=?", (display_num,)
        ).fetchone()
        if not row:
            return {
                "type": "error",
                "message": f"❌ #{display_num} 업무를 찾을 수 없습니다."
            }
        task = dict(row)
        conn.execute("DELETE FROM tasks WHERE id=?", (task["id"],))
        conn.commit()
        return {
            "type": "delete",
            "message": f"🗑 #{display_num} '{task['title']}' 삭제되었습니다.",
            "data": {"display_num": display_num}
        }

    def log_message(self, format, *args):
        """조용한 로그"""
        pass


def main():
    server = HTTPServer(("0.0.0.0", PORT), APIHandler)
    print(f"🔌 브랜업 API 서버 시작: http://0.0.0.0:{PORT}")
    print(f"   대시보드: http://localhost:{PORT}")
    print(f"   엔드포인트: /api/tasks/* | /api/agent")
    print(f"   종료: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 서버 종료")
        server.server_close()


if __name__ == "__main__":
    main()
