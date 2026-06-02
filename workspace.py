"""
workspaces/ 폴더 및 MD 파일 관리
"""
from typing import Optional, List, Dict
import os
import re
from pathlib import Path
from datetime import datetime


def _ws_base() -> Path:
    data_dir = os.environ.get("BRANUP_DATA_DIR",
        str(Path(__file__).parent.parent / "data"))
    return Path(data_dir) / "workspaces"


def ensure_room_dirs(room_id: str):
    base = _ws_base() / room_id
    (base / "tasks").mkdir(parents=True, exist_ok=True)
    (base / "inbox" / "attachments").mkdir(parents=True, exist_ok=True)


def ensure_task_dirs(room_id: str, task_id: str):
    base = _ws_base() / room_id / "tasks" / task_id
    (base / "files").mkdir(parents=True, exist_ok=True)
    (base / "notes").mkdir(parents=True, exist_ok=True)


def write_room_md(room: Dict, task_titles: List[str]):
    ensure_room_dirs(room["id"])
    path = _ws_base() / room["id"] / "room.md"
    lines = [
        f"# {room['name']}",
        "",
        f"chat_id: {room['chat_id']}  |  type: {room['chat_type']}  "
        f"|  등록: {room['registered_at'][:10]}",
        "",
        "## 활성 업무",
    ]
    lines += [f"- {t}" for t in task_titles] if task_titles else ["(없음)"]
    path.write_text("\n".join(lines), encoding="utf-8")


def _render_task_md(task: Dict, history: str = "") -> str:
    due = task.get("due_at") or "-"
    assignee = task.get("assignee") or "-"
    updated = (task.get("updated_at") or "")[:16].replace("T", " ")
    created = (task.get("created_at") or "")[:16].replace("T", " ")
    lines = [
        f"# {task['title']}",
        "",
        f"상태: {task['status']}",
        f"마감: {due}",
        f"담당: {assignee}",
        f"등록: {created}",
        f"갱신: {updated}",
        "",
        "## 요약",
        task.get("summary") or "(아직 요약 없음)",
        "",
        "## 요약 히스토리",
        history or "",
        "",
        "## 첨부 파일",
        "(files/ 폴더 참조)",
    ]
    return "\n".join(lines)


def create_task_md(room: Dict, task: Dict):
    ensure_task_dirs(room["id"], task["id"])
    path = _ws_base() / room["id"] / "tasks" / task["id"] / "task.md"
    path.write_text(_render_task_md(task), encoding="utf-8")


def update_task_md(room: Dict, task: Dict, history_line: str = ""):
    path = _ws_base() / room["id"] / "tasks" / task["id"] / "task.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    m = re.search(r"## 요약 히스토리\n([\s\S]*?)(?=##|$)", existing)
    old_history = m.group(1).strip() if m else ""
    new_history = (old_history + "\n" + history_line).strip() if history_line else old_history
    path.write_text(_render_task_md(task, new_history), encoding="utf-8")


def append_ocr_note(room_id: str, task_id: str, file_name: str, ocr_text: str):
    path = (_ws_base() / room_id / "tasks" / task_id / "notes"
            / f"ocr_{int(datetime.now().timestamp())}_{file_name}.md")
    path.write_text(f"# OCR: {file_name}\n\n{ocr_text}\n", encoding="utf-8")


def attachment_path(room_id: str, file_name: str) -> Path:
    return _ws_base() / room_id / "inbox" / "attachments" / file_name


def task_file_path(room_id: str, task_id: str, file_name: str) -> Path:
    return _ws_base() / room_id / "tasks" / task_id / "files" / file_name
