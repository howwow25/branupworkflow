"""
branup-watcher SQLite CRUD 유틸
"""
from typing import Optional, List, Dict
import sqlite3
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from uuid import uuid4

DATA_DIR = os.environ.get("BRANUP_DATA_DIR",
    str(Path(__file__).parent.parent / "data"))
DB_PATH = Path(DATA_DIR) / "db" / "branup.db"


def now_iso():
    KST = timezone(timedelta(hours=9))
    return datetime.now(KST).isoformat()


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
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL REFERENCES rooms(id),
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT '계획',
        start_date TEXT,
        expected_end_date TEXT,
        assignees TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL REFERENCES rooms(id),
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT '진행중',
        summary TEXT NOT NULL DEFAULT '',
        due_at TEXT,
        assignee TEXT,
        priority TEXT NOT NULL DEFAULT '중간',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        closed_at TEXT,
        display_num INTEGER,
        project_id TEXT REFERENCES projects(id)
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
    # ── migration: add feedback column ──
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN feedback TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass  # already exists
    # ── migration: add priority column ──
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN priority TEXT NOT NULL DEFAULT '중간'")
    except Exception:
        pass  # already exists
    # ── migration: add display_num to existing DB ──
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN display_num INTEGER")
    except Exception:
        pass  # already exists
    # ── migration: add related_tasks ──
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN related_tasks TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass  # already exists
    # ── migration: add project_id ──
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN project_id TEXT REFERENCES projects(id)")
    except Exception:
        pass  # already exists
    # ── migration: files table ──
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS files (
        id TEXT PRIMARY KEY,
        task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
        project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
        original_name TEXT NOT NULL,
        stored_name TEXT NOT NULL,
        file_size INTEGER NOT NULL,
        mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
        created_at TEXT NOT NULL,
        CHECK (task_id IS NOT NULL OR project_id IS NOT NULL)
    );
    CREATE INDEX IF NOT EXISTS idx_files_task ON files(task_id);
    CREATE INDEX IF NOT EXISTS idx_files_project ON files(project_id);
    """)
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

    # ── migration: UTC → KST timestamp 변환 ──
    try:
        sample = conn.execute(
            "SELECT created_at FROM tasks WHERE created_at LIKE '%+00:00' LIMIT 1"
        ).fetchone()
        if sample:
            from datetime import timezone, timedelta
            KST = timezone(timedelta(hours=9))
            tables_cols = {
                'tasks': ['created_at', 'updated_at', 'closed_at'],
                'rooms': ['registered_at'],
                'inbox_messages': ['received_at'],
                'task_events': ['created_at'],
            }
            count = 0
            for table, cols in tables_cols.items():
                try:
                    rows = conn.execute(f'SELECT * FROM {table}').fetchall()
                except Exception:
                    continue
                for row in rows:
                    updates = {}
                    for col in cols:
                        val = row[col]
                        if not val or '+00:00' not in val:
                            continue
                        try:
                            dt = datetime.fromisoformat(val)
                            kst_dt = dt.astimezone(KST)
                            updates[col] = kst_dt.isoformat()
                        except Exception:
                            pass
                    if updates:
                        sets = ', '.join(f'{k}=?' for k in updates)
                        vals = list(updates.values()) + [row['id']]
                        conn.execute(f'UPDATE {table} SET {sets} WHERE id=?', vals)
                        count += 1
            conn.commit()
            if count:
                import sys
                print(f'[db] UTC→KST migrated {count} rows', file=sys.stderr)
    except Exception:
        pass


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
                priority: str = "중간", project_id: Optional[str] = None) -> Dict:
    conn = get_conn()
    tid = str(uuid4())
    ts = now_iso()
    next_num = conn.execute(
        "SELECT COALESCE(MAX(display_num), 0) + 1 FROM tasks"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO tasks (id,room_id,title,status,summary,due_at,assignee,priority,created_at,updated_at,display_num,project_id) "
        "VALUES (?,?,?,'진행중',?,?,?,?,?,?,?,?)",
        (tid, room_id, title, summary, due_at, assignee, priority, ts, ts, next_num, project_id))
    conn.commit()
    return {"id": tid, "room_id": room_id, "title": title, "status": "진행중",
            "summary": summary, "due_at": due_at, "assignee": assignee,
            "priority": priority, "created_at": ts, "updated_at": ts, "closed_at": None,
            "display_num": next_num, "project_id": project_id}


def update_task(task_id: str, **kwargs):
    conn = get_conn()
    allowed = {"status", "title", "summary", "due_at", "assignee", "priority", "closed_at", "feedback", "related_tasks", "project_id"}
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


def get_task_by_display_num(display_num: int) -> Optional[Dict]:
    """display_num으로 업무 조회"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE display_num=?", (display_num,)).fetchone()
    return dict(row) if row else None


def get_completed_tasks() -> List[Dict]:
    """완료된 업무 목록 (closed_at 기준 최신순)"""
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE status='완료' ORDER BY closed_at DESC")]


def get_dropzone_tasks() -> List[Dict]:
    """드랍존(연기/보류) 업무 목록. status='보류' 를 드랍존으로 사용한다."""
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE status='보류' ORDER BY updated_at DESC")]


# ── projects ────────────────────────────────────────────

def create_project(room_id: str, title: str, description: str = "",
                   status: str = "계획", start_date: Optional[str] = None,
                   expected_end_date: Optional[str] = None,
                   assignees: str = "") -> Dict:
    conn = get_conn()
    pid = str(uuid4())
    ts = now_iso()
    conn.execute(
        "INSERT INTO projects (id,room_id,title,description,status,start_date,expected_end_date,assignees,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (pid, room_id, title, description, status, start_date, expected_end_date, assignees, ts, ts))
    conn.commit()
    return {"id": pid, "room_id": room_id, "title": title,
            "description": description, "status": status,
            "start_date": start_date, "expected_end_date": expected_end_date,
            "assignees": assignees, "created_at": ts, "updated_at": ts}


def update_project(project_id: str, **kwargs):
    conn = get_conn()
    allowed = {"title", "description", "status", "start_date", "expected_end_date", "assignees"}
    sets, vals = ["updated_at=?"], [now_iso()]
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    vals.append(project_id)
    conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()


def get_projects() -> List[Dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM projects ORDER BY start_date ASC")]


def get_project_by_id(project_id: str) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    return dict(row) if row else None


def get_tasks_by_project(project_id: str) -> List[Dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE project_id=? AND status NOT IN ('완료','보류') ORDER BY due_at ASC",
        (project_id,))]


def delete_project(project_id: str):
    conn = get_conn()
    conn.execute("UPDATE tasks SET project_id=NULL WHERE project_id=?", (project_id,))
    conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    conn.commit()


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


# ── files ────────────────────────────────────────────────

def _files_dir():
    """파일 저장 디렉토리 반환 및 생성"""
    d = Path(DATA_DIR) / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def add_file(task_id=None, project_id=None, original_name="",
             file_data=b"", mime_type="application/octet-stream") -> Dict:
    """파일 저장 (task 또는 project에 귀속)"""
    conn = get_conn()
    fid = str(uuid4())
    ts = now_iso()
    # 확장자 보존
    ext = Path(original_name).suffix
    stored_name = f"{fid}{ext}"
    file_size = len(file_data)

    # 저장 디렉토리
    target_dir = _files_dir() / "tasks" if task_id else _files_dir() / "projects"
    sub_id = task_id or project_id
    target_dir = target_dir / sub_id
    target_dir.mkdir(parents=True, exist_ok=True)
    filepath = target_dir / stored_name

    with open(filepath, "wb") as f:
        f.write(file_data)

    conn.execute(
        "INSERT INTO files (id,task_id,project_id,original_name,stored_name,file_size,mime_type,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (fid, task_id, project_id, original_name, stored_name, file_size, mime_type, ts))
    conn.commit()
    return {"id": fid, "task_id": task_id, "project_id": project_id,
            "original_name": original_name, "file_size": file_size,
            "mime_type": mime_type, "created_at": ts}


def get_files_by_task(task_id: str) -> List[Dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM files WHERE task_id=? ORDER BY created_at ASC", (task_id,))]


def get_files_by_project(project_id: str) -> List[Dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM files WHERE project_id=? ORDER BY created_at ASC", (project_id,))]


def get_task_file_counts() -> Dict[str, int]:
    """업무별 첨부파일 개수 {task_id: count} (한 번의 쿼리로 집계)"""
    conn = get_conn()
    return {r["task_id"]: r["c"] for r in conn.execute(
        "SELECT task_id, COUNT(*) AS c FROM files WHERE task_id IS NOT NULL GROUP BY task_id")}


def get_file_by_id(file_id: str) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
    return dict(row) if row else None


def get_file_path(file_record: Dict) -> Path:
    """파일 레코드로 실제 파일 경로 반환"""
    sub = "tasks" if file_record.get("task_id") else "projects"
    sub_id = file_record.get("task_id") or file_record.get("project_id")
    return _files_dir() / sub / sub_id / file_record["stored_name"]


def delete_file(file_id: str) -> Optional[Dict]:
    """파일 삭제 (DB + 디스크)"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
    if not row:
        return None
    rec = dict(row)
    # 디스크에서 삭제
    filepath = get_file_path(rec)
    try:
        filepath.unlink(missing_ok=True)
    except Exception:
        pass
    conn.execute("DELETE FROM files WHERE id=?", (file_id,))
    conn.commit()
    return rec


def get_file_size_sum(task_id=None, project_id=None) -> int:
    """task/project별 총 파일 크기 (bytes)"""
    conn = get_conn()
    if task_id:
        row = conn.execute(
            "SELECT COALESCE(SUM(file_size), 0) FROM files WHERE task_id=?", (task_id,)).fetchone()
    elif project_id:
        row = conn.execute(
            "SELECT COALESCE(SUM(file_size), 0) FROM files WHERE project_id=?", (project_id,)).fetchone()
    else:
        return 0
    return row[0]


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
