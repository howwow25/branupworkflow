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
from urllib.parse import urlparse

DATA_DIR = os.environ.get("BRANUP_DATA_DIR",
    str(Path(__file__).parent.parent / "data"))

sys.path.insert(0, str(Path(__file__).parent))
from db import (get_conn, get_task_by_id, update_task, now_iso,
                get_active_tasks, get_completed_tasks,
                create_task, get_room_by_chat_id, upsert_room)


PORT = int(os.environ.get("BRANUP_API_PORT", "8800"))


def parse_text(text):
    """자연어 텍스트에서 제목/담당/마감 추출 (task_manager.py 로직 그대로)"""
    title, assignee, due, priority = None, None, None, None

    # 제목 추출
    m = re.search(r'제목\s*[:：]\s*(.+?)(?:\n|담당|마감|우선|$)', text, re.IGNORECASE)
    if m:
        title = m.group(1).strip()

    # 담당자 추출
    m = re.search(r'담당(?:자)?\s*[:：]\s*(.+?)(?:\n|마감|제목|우선|$)', text, re.IGNORECASE)
    if m:
        assignee = m.group(1).strip()

    # 우선순위 추출
    m = re.search(r'우선(?:순위)?\s*[:：]\s*(긴급|높음|중간|낮음)', text, re.IGNORECASE)
    if m:
        priority = m.group(1)

    # 마감 추출 및 날짜 변환
    m = re.search(r'마감\s*[:：]\s*(.+?)(?:\n|제목|담당|우선|$)', text, re.IGNORECASE)
    if m:
        raw_due = m.group(1).strip()
        if re.match(r'\d{4}-\d{2}-\d{2}', raw_due):
            due = raw_due[:10]
        else:
            dm = re.search(r'(\d{1,2})[/.](\d{1,2})', raw_due)
            if dm:
                from datetime import datetime
                month, day = int(dm.group(1)), int(dm.group(2))
                year = datetime.now().year
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

    return title, assignee, due, priority


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
        allowed = {"title", "assignee", "due_at", "summary", "priority"}
        updates = {k: v for k, v in body.items() if k in allowed}
        if not updates:
            self._send_json({"error": "no valid fields"}, 400)
            return

        update_task(task_id, **updates)
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
        parts = urlparse(self.path).path.strip("/").split("/")

        # /api/agent → 에이전트 명령어
        if len(parts) >= 2 and parts[0] == "api" and parts[1] == "agent":
            self._handle_agent()
            return

        # /api/tasks/<id>/complete
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

    # ── 에이전트 명령어 처리 ──────────────────────────

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
            title, assignee, due, priority = parse_text(text)
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
                summary=text,
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
    server = HTTPServer(("127.0.0.1", PORT), APIHandler)
    print(f"🔌 브랜업 API 서버 시작: http://127.0.0.1:{PORT}")
    print(f"   엔드포인트: /api/tasks/* | /api/agent")
    print(f"   종료: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 서버 종료")
        server.server_close()


if __name__ == "__main__":
    main()
