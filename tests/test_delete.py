"""업무 삭제 — **기록이 쌓이기 시작하면서 생긴 지뢰**를 지킨다.

## 실제로 일어난 일 (2026-11-04)

사람이 겪은 순서는 이랬다.

    배포 → 저장 한 번 성공 → 반복업무 「이후 모두 삭제」 → 실패
         → 그 뒤로 **모든 저장이 실패**

원인이 두 겹이었다.

**첫째, 외래키.** `task_events.task_id` 에는 `ON DELETE CASCADE` 가 없다
(`files` 에는 있다). 그런데 `task_events` 는 2026-11-03 까지 **표만 있고
아무도 쓰지 않았다** — `add_event()` 를 부르는 곳이 한 곳도 없었다. 참조하는
줄이 없으니 삭제는 늘 성공했다. 착수일을 넣으며 기록을 쌓기 시작한 순간,
**한 번이라도 고친 업무는 지울 수 없게** 됐다. 그래서 "삭제가 안 된다" 가
아니라 **"저장을 한 뒤부터 그 업무를 못 지운다"** 라는 모양이 됐고, 그래서
찾기 어려웠다.

**둘째, 터진 연결이 DB 를 잠근 채 남았다.** 한 요청의 실패로 끝나지 않고
**그 뒤의 모든 쓰기가 "database is locked" 로 죽었다.** 사람 눈에는 "삭제를
한 번 눌렀더니 앱 전체가 고장났다" 로 보였고 서버를 다시 띄우기 전에는 안
풀렸다. 이게 진짜 피해였다.
"""
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 환경변수는 `tests/conftest.py` 가 정한다 (왜인지는 그 파일에).
_TMP = os.environ["BRANUP_DATA_DIR"]

import db  # noqa: E402


def test_운영_디비를_쓰지_않는다():
    assert str(db.DB_PATH).startswith(_TMP), f"시험이 {db.DB_PATH} 를 쓰려 한다"


@pytest.fixture()
def room():
    return db.upsert_room("del-room", "web", "삭제 시험")


# ── 외래키 ──────────────────────────────────────────────


def test_기록이_있는_업무도_지울_수_있다(room):
    """한 번이라도 고친 업무는 `task_events` 줄을 갖는다. 그걸 먼저 치우지
    않으면 외래키 제약으로 터진다."""
    t = db.create_task(room["id"], title="고쳤다가 지울 업무")
    db.update_task(t["id"], start_at="2026-11-04")      # 기록이 남는다
    assert _events(t["id"]), "이 시험의 전제가 깨졌다 — 기록이 안 쌓인다"

    assert db.delete_task(t["id"]) == 1
    assert db.get_task_by_id(t["id"]) is None
    assert _events(t["id"]) == 0, "기록만 남아 떠돌면 안 된다"


def test_이후_회차_삭제도_기록을_건넌다(room):
    s = db.create_series(room["id"], freq="주", anchor_date=_soon(),
                         total_count=5, title="주간 리뷰", start_lead=1)
    db.backfill_series()
    made = sorted([t for t in db.get_active_tasks()
                   if t.get("series_id") == s["id"]],
                  key=lambda t: t["series_seq"])
    assert len(made) >= 2, "회차가 만들어지지 않았다"

    # 사람이 겪은 순서 그대로 — **먼저 저장하고** 그 다음 지운다.
    for t in made:
        db.update_task(t["id"], summary="손댄 흔적")

    res = db.delete_task_following(made[0]["id"])
    assert res["deleted"] >= 2
    assert res["stopped"] is True
    left = [t for t in db.get_active_tasks() if t.get("series_id") == s["id"]]
    assert left == []


def test_반복을_멈추며_미래_회차를_지울_때도_마찬가지다(room):
    s = db.create_series(room["id"], freq="주", anchor_date=_soon(),
                         total_count=5, title="멈출 반복")
    db.backfill_series()
    for t in [t for t in db.get_active_tasks() if t.get("series_id") == s["id"]]:
        db.update_task(t["id"], summary="손댄 흔적")

    out = db.stop_series(s["id"], delete_future=True)
    assert out["stopped_at"]


# ── 터진 뒤에도 DB 가 안 잠긴다 ──────────────────────────


def test_쓰다가_터져도_다음_쓰기가_막히지_않는다(room):
    """이게 진짜 피해였다. 실패 하나가 **앱 전체를 멈춰** 세웠다.

    터진 연결이 쓰기 트랜잭션을 연 채 남으면 SQLite 는 DB 를 잠근 채 둔다.
    `get_conn()` 은 부를 때마다 새 연결을 만들므로, 다음 요청은 잠긴 문
    앞에 선다 — 서버를 다시 띄우기 전에는 안 풀린다.
    """
    t = db.create_task(room["id"], title="살아남아야 하는 업무")

    with pytest.raises(RuntimeError):
        with db._db() as conn:
            # 쓰기 트랜잭션을 연다. 지우기가 아니라 **고치기**로 여는 이유는,
            # 지우기는 외래키로 먼저 터져 버려서 "터진 뒤의 잠금" 을 못 보기
            # 때문이다 (그 길은 위의 시험이 따로 본다).
            conn.execute("UPDATE tasks SET summary=? WHERE id=?",
                         ("되돌려져야 한다", t["id"]))
            raise RuntimeError("쓰는 중에 터졌다")

    # 되돌려졌는가
    assert db.get_task_by_id(t["id"])["summary"] != "되돌려져야 한다",         "되돌리지 않았다"
    # 그리고 다음 쓰기가 되는가 — 잠겨 있으면 여기서 OperationalError 다
    db.update_task(t["id"], summary="그 다음 저장")
    assert db.get_task_by_id(t["id"])["summary"] == "그 다음 저장"


def _events(task_id: str) -> int:
    conn = db.get_conn()
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM task_events WHERE task_id=?",
            (task_id,)).fetchone()[0]
    finally:
        conn.close()


def _soon() -> str:
    """오늘 이후여야 회차가 만들어진다 — 날짜를 박으면 언젠가 과거가 된다."""
    return (date.today() + timedelta(days=3)).isoformat()
