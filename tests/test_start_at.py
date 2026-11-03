"""착수일과 업무 기록 시험.

## 왜 이것을 시험하나

착수일 자체는 칸 하나라 눈으로 보인다. 눈으로 볼 수 없는 것이 둘 있다.

**첫째, 마이그레이션이 돌았는지.** `SCHEMA_VERSION` 을 올리지 않으면
`_ensure_schema` 가 첫 줄에서 그냥 돌아가고 `ALTER TABLE` 이 **조용히
건너뛰어진다**(docs/adr/0003). 그러면 화면에 칸은 보이고 저장만 안 된다.
번호를 올리는 일은 사람이 기억해야 하는 일이므로 시험이 지켜 준다.

**둘째, 기록이 남는지.** `task_events` 표는 처음부터 있었지만 **아무도 쓰지
않았다** — `add_event()` 를 부르는 곳이 한 곳도 없었다. 기록은 쌓이기
시작한 날부터만 쓸모가 있고 과거는 복원할 수 없으므로, "안 쌓이고 있다" 를
나중에 발견하면 그 기간은 영구히 사라진다.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# db 는 가져올 때 DATA_DIR 을 정한다. 운영 DB 를 건드리지 않으려면 **가져오기
# 전에** 환경변수를 바꿔야 한다. portal 쪽에서 시험 파일 17개가 운영
# 디렉터리에 남은 사고가 있었다 — 같은 실수를 막는다.
_TMP = tempfile.mkdtemp(prefix="branup_test_")
os.environ["BRANUP_DATA_DIR"] = _TMP
os.environ["BRANUP_SKIP_BACKFILL"] = "1"

import db  # noqa: E402


def test_운영_디비를_쓰지_않는다():
    assert str(db.DB_PATH).startswith(_TMP), f"시험이 {db.DB_PATH} 를 쓰려 한다"


@pytest.fixture()
def room():
    return db.upsert_room("test-room", "web", "시험")


# ── 마이그레이션 ────────────────────────────────────────


def test_start_at_칼럼이_생겼다(room):
    conn = db.get_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)")}
    assert "start_at" in cols


def test_스키마_번호를_올렸다(room):
    """칼럼을 더하면 번호도 올라가야 한다. 안 올리면 운영에서 ALTER 가 안 돈다."""
    conn = db.get_conn()
    assert conn.execute("PRAGMA user_version").fetchone()[0] >= db.SCHEMA_VERSION


# ── 착수일 ──────────────────────────────────────────────


def test_착수일을_넣으면_저장된다(room):
    t = db.create_task(room["id"], title="착수일 있는 업무",
                       start_at="2026-11-10", due_at="2026-11-20")
    assert t["start_at"] == "2026-11-10"
    assert db.get_task_by_id(t["id"])["start_at"] == "2026-11-10"


def test_착수일은_비워_둘_수_있다(room):
    """비면 '아무 때나 해도 되는 일'이다. 추측으로 채우지 않는다."""
    t = db.create_task(room["id"], title="아무 때나", due_at="2026-11-20")
    assert t["start_at"] is None
    assert db.get_task_by_id(t["id"])["start_at"] is None


def test_착수일을_나중에_넣을_수_있다(room):
    t = db.create_task(room["id"], title="나중에 정함")
    db.update_task(t["id"], start_at="2026-12-01")
    assert db.get_task_by_id(t["id"])["start_at"] == "2026-12-01"


# ── 기록 ────────────────────────────────────────────────


def _kinds(task_id):
    return [e["event_type"] for e in db.get_task_events(task_id)]


def test_등록하면_기록이_남는다(room):
    t = db.create_task(room["id"], title="기록", start_at="2026-11-10",
                       due_at="2026-11-20", assignee="이상원")
    evs = db.get_task_events(t["id"])
    assert _kinds(t["id"]) == ["등록"]
    # 등록 시점의 날짜가 남아야 "처음부터 그 날짜였는지" 를 알 수 있다.
    assert evs[0]["payload"]["due_at"] == "2026-11-20"
    assert evs[0]["payload"]["start_at"] == "2026-11-10"


def test_마감일을_고치면_전후가_남는다(room):
    t = db.create_task(room["id"], title="미루기", due_at="2026-11-10")
    db.update_task(t["id"], due_at="2026-11-17")
    db.update_task(t["id"], due_at="2026-11-24")
    evs = [e for e in db.get_task_events(t["id"]) if e["event_type"] == "마감일 변경"]
    assert len(evs) == 2
    assert evs[0]["payload"] == {"from": "2026-11-10", "to": "2026-11-17"}
    assert evs[1]["payload"] == {"from": "2026-11-17", "to": "2026-11-24"}


def test_착수일과_담당자도_남는다(room):
    t = db.create_task(room["id"], title="바뀜", start_at="2026-11-10",
                       assignee="이상원")
    db.update_task(t["id"], start_at="2026-11-12", assignee="최유미")
    assert set(_kinds(t["id"])) == {"등록", "착수일 변경", "담당자 변경"}


def test_같은_값으로_고치면_기록하지_않는다(room):
    """`None` 과 `''` 과 `'2026-11-10T00:00:00'` 이 섞여 들어온다. 글자를 그대로
    비교하면 바뀌지 않았는데 바뀐 것으로 쌓이고, 「계획 안정도」가 부풀려진다."""
    t = db.create_task(room["id"], title="그대로", due_at="2026-11-10")
    db.update_task(t["id"], due_at="2026-11-10")
    db.update_task(t["id"], due_at="2026-11-10T00:00:00")
    assert _kinds(t["id"]) == ["등록"]

    t2 = db.create_task(room["id"], title="빈 값")
    db.update_task(t2["id"], start_at="")
    assert _kinds(t2["id"]) == ["등록"]


def test_제목과_내용은_기록하지_않는다(room):
    """날짜를 잘 잡았는지 세는 데 쓰이지 않는다. 양만 늘어 읽기 어려워진다."""
    t = db.create_task(room["id"], title="제목")
    db.update_task(t["id"], title="딴 제목", summary="딴 내용", priority="긴급")
    assert _kinds(t["id"]) == ["등록"]


def test_완료와_완료_취소가_남는다(room):
    t = db.create_task(room["id"], title="완료할 것")
    db.update_task(t["id"], status="완료", closed_at=db.now_iso())
    db.update_task(t["id"], status="진행중", closed_at=None)
    assert _kinds(t["id"]) == ["등록", "완료", "완료 취소"]


def test_같은_상태로_두_번_쓰면_한_번만_남는다(room):
    t = db.create_task(room["id"], title="두 번")
    db.update_task(t["id"], status="완료", closed_at=db.now_iso())
    db.update_task(t["id"], status="완료", closed_at=db.now_iso())
    assert _kinds(t["id"]).count("완료") == 1


def test_없는_업무를_고쳐도_터지지_않는다():
    db.update_task("없는-id", due_at="2026-11-10")


# ── 반복 ────────────────────────────────────────────────


def test_착수일은_이후_회차로_번지지_않는다(room):
    """마감일이 번지지 않는 것과 같은 이유다 — 회차마다 다른 날짜다."""
    s = db.create_series(room["id"], freq="주", anchor_date="2026-11-02",
                         total_count=4, title="주간 리뷰", assignee="이상원")
    db.backfill_series()
    seqs = [t for t in db.get_active_tasks() if t.get("series_id") == s["id"]]
    assert len(seqs) >= 2, "회차가 만들어지지 않았다"

    first = min(seqs, key=lambda t: t["series_seq"])
    n = db.apply_series_following(
        s["id"], first["series_seq"],
        {"start_at": "2026-11-01", "due_at": "2026-11-01", "assignee": "최유미"})

    for t in seqs:
        row = db.get_task_by_id(t["id"])
        assert row["start_at"] is None, "착수일이 회차로 번졌다"
    assert n >= 1, "담당자는 번져야 한다"


def test_회차는_착수일_없이_만들어진다(room):
    s = db.create_series(room["id"], freq="주", anchor_date="2026-11-02",
                         total_count=3, title="회차 착수일")
    db.backfill_series()
    made = [t for t in db.get_active_tasks() if t.get("series_id") == s["id"]]
    assert made, "회차가 만들어지지 않았다"
    assert all(t["start_at"] is None for t in made)
