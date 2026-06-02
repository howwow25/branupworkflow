"""
branup_api.py — Windows API 클라이언트
BRANUP_API_URL 환경변수가 설정되어 있으면 db.py 대신 이 모듈로 API 호출
"""
import os
import json
import urllib.request
import urllib.error
import urllib.parse

API_URL = os.environ.get("BRANUP_API_URL", "").rstrip("/")


def _api(path, method="GET", body=None):
    """API 호출 헬퍼"""
    # URL 경로에 한글 등 비ASCII 문자 URL 인코딩
    safe_path = urllib.parse.quote(path, safe="/:")
    url = f"{API_URL}{safe_path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


def get_active_tasks():
    return _api("/tasks/list")


def get_completed_tasks():
    return _api("/tasks/completed")


def get_task_by_id(task_id):
    return _api(f"/tasks/{task_id}")


def create_task(room_id, title, summary="", due_at=None, assignee=None, priority="중간"):
    return _api("/tasks", method="POST", body={
        "title": title,
        "summary": summary,
        "due_at": due_at,
        "assignee": assignee,
        "priority": priority,
    })


def update_task(task_id, **kwargs):
    return _api(f"/tasks/{task_id}", method="PATCH", body=kwargs)


def delete_task(task_id):
    return _api(f"/tasks/{task_id}", method="DELETE")


def get_room_by_chat_id(chat_id):
    return _api(f"/rooms/{chat_id}")


def upsert_room(chat_id, chat_type, name):
    return _api("/rooms", method="POST", body={
        "chat_id": chat_id,
        "chat_type": chat_type,
        "name": name,
    })


def get_all_rooms():
    return _api("/rooms")


def get_tasks_by_room(room_id):
    return _api(f"/rooms/{room_id}/tasks")


def now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
