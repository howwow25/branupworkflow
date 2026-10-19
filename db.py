"""
branup-watcher SQLite CRUD 유틸
"""
from typing import Optional, List, Dict
import functools
import sqlite3
import json
import os
import sys
import threading
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from recurrence import FREQS, first_open_seq, nth_due, plan_fill, relabel

DATA_DIR = os.environ.get("BRANUP_DATA_DIR",
    str(Path(__file__).parent.parent / "data"))
DB_PATH = Path(DATA_DIR) / "db" / "branup.db"


def now_iso():
    KST = timezone(timedelta(hours=9))
    return datetime.now(KST).isoformat()


# ── 쓰기는 한 번에 하나씩 ────────────────────────────────
#
# SQLite 는 쓰기를 하나만 받는다. api_server 는 요청마다 스레드를 쓰므로,
# 사람 둘이 동시에 업무를 만들면 두 스레드가 같은 잠금을 다툰다. 그때
# "database is locked" 로 요청이 **응답 없이** 끊겼다 (연결이 죽어서 화면은
# "API 서버 연결 실패" 만 띄웠다). 프로세스 안에서는 줄을 세운다. 프로세스
# 밖(굽기)은 busy_timeout 이 기다려 준다.
_WRITE_LOCK = threading.RLock()


def _writer(fn):
    """DB 에 쓰는 함수. 한 프로세스 안에서 직렬로 돈다."""
    @functools.wraps(fn)
    def inner(*a, **kw):
        with _WRITE_LOCK:
            return fn(*a, **kw)
    return inner


# 스키마는 프로세스마다 한 번만 확인한다.
#
# 전에는 `get_conn()` 마다 돌렸다. 그 안에는 CREATE TABLE·ALTER TABLE·UPDATE 가
# 있어서 **읽기만 하려는 연결도 쓰기 잠금을 잡는다.** 업무를 만들 때마다
# 굽기 프로세스가 하나씩 뜨므로, 연달아 만들면 프로세스 여러 개가 DDL 잠금을
# 다투다 "database is locked" 로 요청이 죽었다 (12개 동시 생성에서 전부 실패).
_SCHEMA_READY = False


def get_conn():
    global _SCHEMA_READY
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    # ⚠️ busy_timeout 을 **맨 먼저** 건다. 쓰는 쪽이 둘 이상인데(api_server 와
    # 그것이 띄우는 dashboard_html) 기본값은 잠겼으면 즉시 실패한다.
    # journal_mode 를 먼저 두면 그 PRAGMA 자체가 기다리지 않고 터져서
    # "database is locked" 가 연결을 만드는 단계에서 난다 (실제로 그랬다).
    conn.execute("PRAGMA busy_timeout=15000")
    try:
        if (conn.execute("PRAGMA journal_mode").fetchone()[0] or "").lower() != "wal":
            conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass    # 이미 WAL 이거나 지금 누가 쓰는 중이다. 요청을 죽일 일은 아니다.
    conn.execute("PRAGMA foreign_keys=ON")
    if not _SCHEMA_READY:
        _ensure_schema(conn)
        _SCHEMA_READY = True
    return conn


# 스키마를 한 번 올리면 이 번호를 DB 에 적어 둔다. **칼럼이나 표를 더할 때마다
# 1 올려야 한다** — 안 올리면 새 마이그레이션이 돌지 않는다.
#
# 이 번호가 필요한 이유: 굽기(dashboard_html)는 별도 프로세스이고, 이 함수가
# 매번 CREATE/ALTER 를 돌리면 **읽기만 하려는 프로세스도 쓰기 잠금을 잡는다.**
# 그래서 업무를 연달아 만들면 "database is locked" 로 요청이 죽었다.
SCHEMA_VERSION = 3


def _ensure_schema(conn):
    # 이미 최신이면 아무것도 쓰지 않는다 (PRAGMA user_version 은 읽기다).
    try:
        if (conn.execute("PRAGMA user_version").fetchone()[0] or 0) >= SCHEMA_VERSION:
            return
    except Exception:
        pass
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
    # ── migration: 반복 시리즈 (docs/adr/0001-반복업무.md) ──
    #
    # 반복 설정을 tasks 에 칼럼으로 달지 않고 표를 따로 둔다. 시리즈는 업무가
    # 아니라 **업무를 찍어내는 틀**이다. tasks 에 넣으면 같은 설정이 회차마다
    # 복사되어, "이 업무와 이후 모두" 를 고칠 때 어느 행이 진짜 설정인지
    # 알 수 없게 된다.
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS task_series (
        id TEXT PRIMARY KEY,
        room_id TEXT NOT NULL REFERENCES rooms(id),
        freq TEXT NOT NULL,                       -- '주' | '월' | '년'
        anchor_date TEXT NOT NULL,                -- 1회차 마감일 'YYYY-MM-DD'
        total_count INTEGER,                      -- NULL = 마감없음
        made_through INTEGER NOT NULL DEFAULT 0,  -- 지금까지 만든 최고 회차
        stopped_at TEXT,                          -- NULL 이면 도는 중
        title TEXT NOT NULL,
        summary TEXT NOT NULL DEFAULT '',
        assignee TEXT,
        priority TEXT NOT NULL DEFAULT '중간',
        project_id TEXT REFERENCES projects(id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_series_open ON task_series(stopped_at);
    """)
    # ── migration: 제목의 기간 표시를 회차마다 고친다 ──
    # "[재무리뷰] 10월 3주" → 다음 회차는 "10월 4주". 손으로 고치던 일이다.
    try:
        conn.execute("ALTER TABLE task_series ADD COLUMN auto_rename INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN series_id TEXT REFERENCES task_series(id)")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN series_seq INTEGER")
    except Exception:
        pass  # already exists
    # 한 회차는 업무 하나다. 화면을 동시에 두 번 열면 보충이 같은 회차를 두 번
    # 만들 수 있는데, 그걸 DB 가 막는다 (앱 쪽 잠금보다 확실하다).
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_series_seq "
                     "ON tasks(series_id, series_seq) WHERE series_id IS NOT NULL")
    except Exception:
        pass
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

    # 여기까지 왔으면 전부 적용됐다. 다음 연결은 이 함수에서 바로 돌아간다.
    try:
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        conn.commit()
    except Exception:
        pass


# ── rooms ──────────────────────────────────────────────

@_writer
def upsert_room(chat_id: str, chat_type: str, name: str) -> Dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM rooms WHERE chat_id=?", (chat_id,)).fetchone()
    if row:
        conn.execute("UPDATE rooms SET name=? WHERE chat_id=?", (name, chat_id))
        conn.commit()
        return dict(row)
    rid = str(uuid4())
    ts = now_iso()
    try:
        conn.execute(
            "INSERT INTO rooms (id,chat_id,chat_type,name,registered_at) VALUES (?,?,?,?,?)",
            (rid, chat_id, chat_type, name, ts))
        conn.commit()
    except sqlite3.IntegrityError:
        # chat_id 가 UNIQUE 다. 둘이 동시에 "없네" 를 보고 둘 다 넣으려 하면
        # 뒤쪽이 여기로 온다 — 먼저 넣은 쪽의 값을 쓴다. 전에는 이 예외가
        # 그대로 올라가 업무 등록이 실패했다.
        row = conn.execute("SELECT * FROM rooms WHERE chat_id=?",
                           (chat_id,)).fetchone()
        if row:
            return dict(row)
        raise
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

@_writer
def create_task(room_id: str, title: str, summary: str = "",
                due_at: Optional[str] = None, assignee: Optional[str] = None,
                priority: str = "중간", project_id: Optional[str] = None,
                series_id: Optional[str] = None,
                series_seq: Optional[int] = None) -> Dict:
    conn = get_conn()
    tid = str(uuid4())
    ts = now_iso()
    next_num = conn.execute(
        "SELECT COALESCE(MAX(display_num), 0) + 1 FROM tasks"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO tasks (id,room_id,title,status,summary,due_at,assignee,priority,created_at,updated_at,display_num,project_id,series_id,series_seq) "
        "VALUES (?,?,?,'진행중',?,?,?,?,?,?,?,?,?,?)",
        (tid, room_id, title, summary, due_at, assignee, priority, ts, ts, next_num,
         project_id, series_id, series_seq))
    conn.commit()
    return {"id": tid, "room_id": room_id, "title": title, "status": "진행중",
            "summary": summary, "due_at": due_at, "assignee": assignee,
            "priority": priority, "created_at": ts, "updated_at": ts, "closed_at": None,
            "display_num": next_num, "project_id": project_id,
            "series_id": series_id, "series_seq": series_seq}


@_writer
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


# ── 반복 시리즈 ──────────────────────────────────────────
#
# 날짜 계산은 전부 `recurrence.py` 에 있다 (DB 를 모르는 순수 함수 + 시험).
# 여기는 그 계산을 표에 옮기는 일만 한다.


def today_kst() -> str:
    """오늘 날짜 'YYYY-MM-DD'. 서버 시간대에 끌려다니지 않게 KST 로 고정한다."""
    KST = timezone(timedelta(hours=9))
    return datetime.now(KST).date().isoformat()


SERIES_FIELDS = {"title", "summary", "assignee", "priority", "project_id",
                 "total_count", "made_through", "stopped_at", "freq",
                 "anchor_date", "auto_rename"}


@_writer
def create_series(room_id: str, freq: str, anchor_date: str,
                  total_count: Optional[int], title: str, summary: str = "",
                  assignee: Optional[str] = None, priority: str = "중간",
                  project_id: Optional[str] = None,
                  auto_rename: bool = False) -> Dict:
    if freq not in FREQS:
        raise ValueError(f"모르는 주기: {freq!r}")
    if total_count is not None and total_count < 1:
        raise ValueError(f"횟수는 1 이상입니다: {total_count}")
    # 기준일이 날짜가 아니면 여기서 막는다. 뒤에서 조용히 틀리면 다음 회차가
    # 영원히 안 생기고 사람은 이유를 모른다.
    date.fromisoformat(anchor_date[:10])
    conn = get_conn()
    sid = str(uuid4())
    ts = now_iso()
    conn.execute(
        "INSERT INTO task_series (id,room_id,freq,anchor_date,total_count,made_through,"
        "title,summary,assignee,priority,project_id,auto_rename,created_at,updated_at) "
        "VALUES (?,?,?,?,?,0,?,?,?,?,?,?,?,?)",
        (sid, room_id, freq, anchor_date[:10], total_count, title, summary,
         assignee, priority, project_id, 1 if auto_rename else 0, ts, ts))
    conn.commit()
    return get_series(sid)


def get_series(series_id: str) -> Optional[Dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM task_series WHERE id=?", (series_id,)).fetchone()
    return dict(row) if row else None


def get_open_series() -> List[Dict]:
    """아직 도는 시리즈. 중단했거나 횟수를 다 쓴 것은 빠진다."""
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM task_series WHERE stopped_at IS NULL")]


def get_all_series() -> List[Dict]:
    """중단한 것까지 전부. 화면이 "3/10회" 를 적으려면 멈춘 시리즈도 필요하다."""
    conn = get_conn()
    return [dict(r) for r in conn.execute("SELECT * FROM task_series")]


@_writer
def update_series(series_id: str, **kwargs):
    conn = get_conn()
    sets, vals = ["updated_at=?"], [now_iso()]
    for k, v in kwargs.items():
        if k in SERIES_FIELDS:
            sets.append(f"{k}=?")
            vals.append(v)
    vals.append(series_id)
    conn.execute(f"UPDATE task_series SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()


def get_series_tasks(series_id: str) -> List[Dict]:
    conn = get_conn()
    return [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE series_id=? ORDER BY series_seq ASC", (series_id,))]


def _open_in_window(rows: List[Dict], today: str) -> int:
    """창에 들어 있는 회차 수 — 완료도 마감지남도 아닌 것.

    **보류(드랍존)는 날짜와 무관하게 센다.** 연기한 업무의 자리를 메우려고
    새 회차가 또 생기면 밀어낸 보람이 없다.
    """
    n = 0
    for r in rows:
        if r["status"] == "완료":
            continue
        if r["status"] == "보류":
            n += 1
            continue
        due = (r.get("due_at") or "")[:10]
        # 마감일을 비운 업무는 '미정' 이라 아직 끝난 것이 아니다.
        if not due or due >= today:
            n += 1
    return n


@_writer
def backfill_series(today: Optional[str] = None) -> int:
    """창이 빈 반복 시리즈를 채운다. 새로 만든 업무 수를 돌려준다.

    스케줄러가 없는 앱이라 **화면을 볼 때마다** 이걸 부른다
    (docs/adr/0001). 아무도 안 보는 동안 채울 이유가 없고, 보는 순간에는
    이미 채워져 있다.

    절대 예외를 올리지 않는다 — 반복 하나가 깨져서 업무 목록이 안 열리면
    사람이 서비스 앞에서 멈춘다.
    """
    today = (today or today_kst())[:10]
    try:
        t = date.fromisoformat(today)
    except Exception:
        return 0
    made = 0
    try:
        series = get_open_series()
    except Exception:
        return 0
    for s in series:
        try:
            anchor = date.fromisoformat((s["anchor_date"] or "")[:10])
            rows = get_series_tasks(s["id"])
            seqs = plan_fill(anchor, s["freq"], s["total_count"], t,
                             made_through=s["made_through"] or 0,
                             open_count=_open_in_window(rows, today))
            for seq in seqs:
                due_d = nth_due(anchor, s["freq"], seq)
                due = due_d.isoformat()
                # 제목의 기간 표시를 이 회차의 날짜로 고친다. 표시가 없으면
                # relabel 이 None 을 주므로 그대로 쓴다 — 켜 두기만 하고
                # 제목을 안 바꾼 시리즈가 조용히 깨지지 않는다.
                title = s["title"]
                if s["auto_rename"]:
                    title = relabel(title, due_d) or title
                try:
                    create_task(
                        s["room_id"], title=title,
                        summary=s["summary"] or s["title"], due_at=due,
                        assignee=s["assignee"], priority=s["priority"],
                        project_id=s["project_id"],
                        series_id=s["id"], series_seq=seq)
                except sqlite3.IntegrityError:
                    continue      # 다른 요청이 같은 회차를 먼저 만들었다
                made += 1
            if seqs:
                update_series(s["id"], made_through=max(seqs))
            # 더 만들 회차가 남았는지 본다. 없으면 시리즈를 닫아 다음부터
            # 다시 계산하지 않는다. (방치해서 횟수를 다 쓴 경우도 여기서 닫힌다)
            if s["total_count"]:
                through = max(seqs) if seqs else (s["made_through"] or 0)
                nxt = max(through + 1, first_open_seq(anchor, s["freq"], t))
                if nxt > s["total_count"]:
                    update_series(s["id"], stopped_at=now_iso())
        except Exception as e:                    # noqa: BLE001
            print(f"[db] 반복 보충 실패 series={s.get('id')}: {e}", file=sys.stderr)
            continue
    return made


@_writer
def stop_series(series_id: str, delete_future: bool = False) -> Dict:
    """반복을 멈춘다. 앞으로 만들 것만 멈추고, 이미 만든 것은 고른 대로.

    지난 기록과 완료분은 건드리지 않는다 — 했던 일이 사라지면 기록이
    아니게 된다. `delete_future` 는 **오늘보다 뒤**인 미완료 회차만 지운다.
    """
    today = today_kst()
    removed = 0
    if delete_future:
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM tasks WHERE series_id=? AND status<>'완료' "
            "AND due_at IS NOT NULL AND substr(due_at,1,10) > ?",
            (series_id, today))
        removed = cur.rowcount or 0
        conn.commit()
    update_series(series_id, stopped_at=now_iso())
    s = get_series(series_id) or {}
    s["removed"] = removed
    return s


@_writer
def apply_series_following(series_id: str, from_seq: int, fields: Dict) -> int:
    """시리즈 틀을 고치고 **이후 회차**에도 반영한다. 고친 업무 수.

    이미 완료한 회차는 건드리지 않는다. 끝난 업무의 제목이 소급해서 바뀌면
    그것은 기록이 아니다.
    """
    allowed = {"title", "summary", "assignee", "priority", "project_id"}
    patch = {k: v for k, v in fields.items() if k in allowed}
    if not patch:
        return 0
    update_series(series_id, **patch)
    s = get_series(series_id) or {}
    conn = get_conn()

    # 이름 자동 변경이 켜져 있으면 제목을 한 값으로 덮어쓸 수 없다. 덮어쓰면
    # 이후 회차가 전부 "10월 3주" 가 되어, 고치려던 바로 그 상태로 돌아간다.
    rename = bool(s.get("auto_rename")) and "title" in patch
    bulk = {k: v for k, v in patch.items() if not (rename and k == "title")}
    touched = set()
    if bulk:
        sets = ", ".join(f"{k}=?" for k in bulk)
        vals = list(bulk.values()) + [now_iso(), series_id, from_seq]
        conn.execute(
            f"UPDATE tasks SET {sets}, updated_at=? "
            "WHERE series_id=? AND series_seq>? AND status<>'완료'", vals)
    rows = conn.execute(
        "SELECT id, due_at FROM tasks "
        "WHERE series_id=? AND series_seq>? AND status<>'완료'",
        (series_id, from_seq)).fetchall()
    for r in rows:
        touched.add(r["id"])
        if not rename:
            continue
        new_title = patch["title"]
        try:
            new_title = relabel(patch["title"],
                                date.fromisoformat((r["due_at"] or "")[:10])) or new_title
        except Exception:
            pass
        conn.execute("UPDATE tasks SET title=?, updated_at=? WHERE id=?",
                     (new_title, now_iso(), r["id"]))
    conn.commit()
    return len(touched)


@_writer
def set_series_auto_rename(series_id: str, on: bool) -> int:
    """이름 자동 변경을 켜거나 끈다. 이름을 고친 회차 수를 돌려준다.

    켤 때 **아직 오지 않은 미완료 회차의 이름을 지금 맞춰 준다.** 다음 회차가
    생길 때까지 기다리게 하면, 켜 놓고도 화면이 그대로여서 사람은 켜지지 않은
    줄 안다. 완료한 회차와 지나간 회차는 건드리지 않는다 — 기록이다.
    """
    s = get_series(series_id)
    if not s:
        return 0
    update_series(series_id, auto_rename=1 if on else 0)
    if not on:
        return 0
    today = today_kst()
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, due_at FROM tasks "
        "WHERE series_id=? AND status<>'완료' "
        "AND due_at IS NOT NULL AND substr(due_at,1,10) >= ?",
        (series_id, today)).fetchall()
    fixed = 0
    for r in rows:
        try:
            new_title = relabel(s["title"],
                                date.fromisoformat(r["due_at"][:10]))
        except Exception:
            continue
        if new_title and new_title != r["title"]:
            conn.execute("UPDATE tasks SET title=?, updated_at=? WHERE id=?",
                         (new_title, now_iso(), r["id"]))
            fixed += 1
    conn.commit()
    return fixed


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

@_writer
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
