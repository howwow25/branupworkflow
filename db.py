"""
branup-watcher SQLite CRUD 유틸
"""
from typing import Optional, List, Dict
import sqlite3
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

DATA_DIR = os.environ.get("BRANUP_DATA_DIR",
    str(Path(__file__).parent.parent / "data"))
DB_PATH = Path(DATA_DIR) / "db" / "branup.db"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS rooms (
        id TEXT PRIMARY KEY,
        chat_id TEXT NOT NULL UNIQUE,
        chat_type TEXT NOT NULL,
        name TEXT NOT NULL,
        registered_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL REFERENCES rooms(id),
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT '진행중',
        summary TEXT NOT NULL DEFAULT '',
        due_at TEXT,
        assignee TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        closed_at TEXT,
        display_num INTEGER
    );
    CREATE TABLE IF NOT EXISTS inbox_messages (
        id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL REFERENCES rooms(id),
        telegram_msg_id INTEGER NOT NULL,
        sender_id TEXT NOT NULL,
        sender_name TEXT NOT NULL,
        text TEXT NOT NULL DEFAULT '',
        media_type TEXT NOT NULL DEFAULT 'text',
        file_path TEXT,
        ocr_text TEXT,
        processed INTEGER NOT NULL DEFAULT 0,
        received_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS task_events (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL REFERENCES tasks(id),
        event_type TEXT NOT NULL,
        payload TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_inbox_processed
        ON inbox_messages(processed, received_at);
    CREATE INDEX IF NOT EXISTS idx_tasks_room
        ON tasks(room_id, status);
    """)
    # ── migration: add display_num to existing DB ──
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN display_num INTEGER")
    except Exception:
        pass  # already exists
    # assign display_num to tasks without one (ordered by created_at)
    nulls = conn.execute(
        "SELECT id FROM tasks WHERE display_num IS NULL ORDER BY created_at ASC"
    ).fetchall()
    if nulls:
        cur_max = conn.execute(
            "SELECT COALESCE(MAX(display_num), 0) FROM tasks"
        ).fetchone()[0]
        for i, row in enumerate(nulls):
            conn.execute(
                "UPDATE tasks SET display_num=? WHERE id=?",
                (cur_max + i + 1, row["id"])
            )
    conn.commit()


# ── rooms ──────────────────────────────────────────────

def upsert_room(chat_id: str, chat_type: str, name: str) -> Dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM rooms WHERE chat_id=?", (chat_id,)).fetchone()
    if row:
        conn.execute("UPDATE rooms SET name=? WHERE chat_id=?", (name, chat_id))
        conn.commit()
        return dict(row)
    rid = str(uuid4())
    ts = now_iso()
    conn.execute(
        "INSERT INTO rooms (id,chat_id,chat_type,name,registered_at) VALUES (?,?,?,?,?)",
        (rid, chat_id, chat_type, name, ts))
    conn.commit()
    return {"id": rid, "chat_id": chat_id, "chat_type": chat_type,
            "name": name, "registered_at": ts}


def get_room_by_chat_id(chat_id: str) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM rooms WHERE chat_id=?", (chat_id,)).fetchone()
    return dict(row) if row else None


def get_all_rooms() -> List[Dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM rooms").fetchall()]


# ── tasks ──────────────────────────────────────────────

def create_task(room_id: str, title: str, summary: str = "",
                due_at: Optional[str] = None, assignee: Optional[str] = None,
                priority: str = "중간") -> Dict:
    conn = get_conn()
    tid = str(uuid4())
    ts = now_iso()
    next_num = conn.execute(
        "SELECT COALESCE(MAX(display_num), 0) + 1 FROM tasks"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO tasks (id,room_id,title,status,summary,due_at,assignee,priority,created_at,updated_at,display_num) "
        "VALUES (?,?,?,'진행중',?,?,?,?,?,?,?)",
        (tid, room_id, title, summary, due_at, assignee, priority, ts, ts, next_num))
    conn.commit()
    return {"id": tid, "room_id": room_id, "title": title, "status": "진행중",
            "summary": summary, "due_at": due_at, "assignee": assignee,
            "priority": priority, "created_at": ts, "updated_at": ts, "closed_at": None,
            "display_num": next_num}


def update_task(task_id: str, **kwargs):
    conn = get_conn()
    allowed = {"status", "title", "summary", "due_at", "assignee", "priority", "closed_at"}
    sets, vals = ["updated_at=?"], [now_iso()]
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    vals.append(task_id)
    conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()


def get_tasks_by_room(room_id: str) -> List[Dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE room_id=? ORDER BY created_at DESC", (room_id,))]


def get_active_tasks() -> List[Dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE status NOT IN ('완료','보류') ORDER BY due_at ASC")]


def get_task_by_id(task_id: str) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else None


def get_completed_tasks() -> List[Dict]:
    """완료된 업무 목록 (closed_at 기준 최신순)"""
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE status='완료' ORDER BY closed_at DESC")]


# ── inbox ──────────────────────────────────────────────

def insert_inbox(room_id: str, telegram_msg_id: int, sender_id: str,
                 sender_name: str, text: str = "", media_type: str = "text",
                 file_path: Optional[str] = None, ocr_text: Optional[str] = None) -> Dict:
    conn = get_conn()
    mid = str(uuid4())
    ts = now_iso()
    conn.execute(
        "INSERT INTO inbox_messages "
        "(id,room_id,telegram_msg_id,sender_id,sender_name,text,media_type,"
        "file_path,ocr_text,processed,received_at) VALUES (?,?,?,?,?,?,?,?,?,0,?)",
        (mid, room_id, telegram_msg_id, sender_id, sender_name,
         text, media_type, file_path, ocr_text, ts))
    conn.commit()
    return {"id": mid, "room_id": room_id, "telegram_msg_id": telegram_msg_id,
            "text": text, "media_type": media_type, "processed": False, "received_at": ts}


def get_unprocessed(limit: int = 50) -> List[Dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM inbox_messages WHERE processed=0 "
        "ORDER BY received_at ASC LIMIT ?", (limit,))]


def mark_processed(ids: List[str]):
    if not ids:
        return
    conn = get_conn()
    conn.execute(
        f"UPDATE inbox_messages SET processed=1 WHERE id IN ({','.join('?'*len(ids))})",
        ids)
    conn.commit()


def update_ocr(msg_id: str, ocr_text: str):
    conn = get_conn()
    conn.execute("UPDATE inbox_messages SET ocr_text=? WHERE id=?", (ocr_text, msg_id))
    conn.commit()


# ── task events ────────────────────────────────────────

def add_event(task_id: str, event_type: str, payload: Optional[Dict] = None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO task_events (id,task_id,event_type,payload,created_at) VALUES (?,?,?,?,?)",
        (str(uuid4()), task_id, event_type, json.dumps(payload or {}), now_iso()))
    conn.commit()


# ── CLI ────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        conn = get_conn()
        rooms = conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]
        tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        inbox = conn.execute("SELECT COUNT(*) FROM inbox_messages WHERE processed=0").fetchone()[0]
        print(f"rooms={rooms}, tasks={tasks}, unprocessed_inbox={inbox}")
    elif cmd == "rooms":
        for r in get_all_rooms():
            print(json.dumps(r, ensure_ascii=False))
    elif cmd == "tasks":
        room_id = sys.argv[2] if len(sys.argv) > 2 else None
        tasks = get_tasks_by_room(room_id) if room_id else get_active_tasks()
        for t in tasks:
            print(json.dumps(t, ensure_ascii=False))
    elif cmd == "inbox":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        for m in get_unprocessed(limit):
            print(json.dumps(m, ensure_ascii=False))
