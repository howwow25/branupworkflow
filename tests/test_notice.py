"""알림의 **재료**를 지킨다 — 「등록」 기록에 누가 만들었는지가 들어가는가.

포털이 "남이 나에게 업무를 지시했다" 를 담당자에게 보내려면 기록에서 두
가지를 읽어야 한다.

1. **누가 만들었나** (`by`) — 없으면 자기가 방금 타이핑한 업무의 알림을
   자기가 받는다
2. **사람이 만든 것인가** (`auto`) — 반복 회차 보충으로 생긴 등록까지
   알리면 월간 반복 하나가 **여섯 통**이 된다

둘을 한 값으로 묶으면 안 된다는 것이 이 파일의 핵심이다. 화면에서 「나는
OOO」 를 안 고른 사람이 만든 업무도 `by` 가 빈다 — `by` 가 비었다고 반복
보충으로 치면 **진짜 업무 지시가 조용히 안 간다.**

업무대시보드는 여기까지만 한다. 보내는 일은 포털이다 — 이 앱에는 인증이
전혀 없어서 봇 토큰을 둘 수 없다 (docs/adr/0011 · 0012).
"""
import os
import sys
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
    return db.upsert_room("notice-room", "web", "알림 시험")


def _reg(task_id) -> dict:
    """그 업무의 「등록」 기록 하나."""
    rows = [e for e in db.get_task_events(task_id) if e["event_type"] == "등록"]
    assert len(rows) == 1, f"「등록」 이 {len(rows)} 줄이다"
    return rows[0]["payload"]


# ── 누가 만들었나 ────────────────────────────────────────


def test_등록에_만든_사람이_남는다(room):
    """사용자의 경우 그대로 — 전대박이 이국진 담당으로 만들었다."""
    t = db.create_task(room["id"], title="업무 지시", assignee="이국진",
                       actor="전대박")
    p = _reg(t["id"])
    assert p["by"] == "전대박"
    assert p["assignee"] == "이국진"


def test_자기가_만든_업무도_만든_사람이_남는다(room):
    """`by` 와 `assignee` 가 같으면 포털이 **보내지 않는다.** 그 판단을
    하려면 두 값이 다 있어야 한다 — 포털에서 빼는 것이지 여기서 빼는 것이
    아니다. 기록은 일어난 일을 그대로 적는다."""
    t = db.create_task(room["id"], title="내 일", assignee="이국진",
                       actor="이국진")
    p = _reg(t["id"])
    assert p["by"] == "이국진"
    assert p["assignee"] == "이국진"


def test_만든_사람을_모르면_칸이_없다(room):
    """`actor` 가 없으면 `by` 를 **빈 값으로 넣지 않고 아예 안 넣는다**
    (`add_event` 의 규칙). 빈 문자열을 넣으면 "아무도 아님" 이라는 이름이
    하나 생긴다."""
    t = db.create_task(room["id"], title="누가 만들었는지 모름")
    assert "by" not in _reg(t["id"])


# ── 사람이 만든 것인가 ───────────────────────────────────


def test_화면에서_만든_등록에는_auto_가_없다(room):
    t = db.create_task(room["id"], title="사람이 만듦", actor="전대박")
    assert "auto" not in _reg(t["id"])


def test_반복_보충으로_생긴_등록은_auto_다(room):
    """`backfill_series` 가 만드는 회차다. 이 표시가 없으면 월간 반복 하나가
    회차 수만큼 알림을 쏜다."""
    t = db.create_task(room["id"], title="2회차", assignee="이국진", auto=True)
    p = _reg(t["id"])
    assert p["auto"] is True
    # 보충은 사람이 부른 것이 아니므로 만든 사람도 없다.
    assert "by" not in p


def test_auto_와_by_는_서로_다른_값이다(room):
    """**이 시험이 이 파일의 이유다.** 「나는 OOO」 를 안 고른 사람이 만든
    업무는 `by` 가 비지만 `auto` 는 아니다. 둘을 하나로 묶어 "`by` 가 없으면
    반복 보충" 으로 치면 그 사람의 업무 지시가 영구히 안 간다."""
    사람 = db.create_task(room["id"], title="이름 안 고른 사람이 만듦",
                          assignee="이국진")
    보충 = db.create_task(room["id"], title="보충", assignee="이국진", auto=True)

    assert "by" not in _reg(사람["id"]) and "auto" not in _reg(사람["id"])
    assert "by" not in _reg(보충["id"]) and _reg(보충["id"])["auto"] is True


# ── 포털이 읽어 가는 길 ──────────────────────────────────


def test_events_since_가_등록을_담당자와_함께_준다(room):
    """포털은 업무를 한 번 더 조회하지 않는다 — 그 사이에 지워진 업무의
    알림이 조용히 사라지기 때문이다. 그래서 제목·담당자·번호가 기록과 같이
    와야 한다."""
    t = db.create_task(room["id"], title="같이 와야 하는 제목",
                       assignee="이국진,전경표", actor="전대박")

    rows = [e for e in db.events_since() if e["task_id"] == t["id"]]
    assert rows, "포털이 읽어 갈 줄이 없다"
    e = rows[0]
    assert e["event_type"] == "등록"
    assert e["title"] == "같이 와야 하는 제목"
    assert e["assignee"] == "이국진,전경표"
    assert e["display_num"] == t["display_num"]
    assert e["payload"]["by"] == "전대박"


def test_since_는_그_뒤에_쌓인_것만_준다(room):
    """포털이 같은 알림을 두 번 보내지 않게 하는 기준점이다."""
    a = db.create_task(room["id"], title="먼저", actor="전대박")
    mark = db.get_task_events(a["id"])[0]["created_at"]
    b = db.create_task(room["id"], title="나중", actor="전대박")

    got = {e["task_id"] for e in db.events_since(mark)}
    assert b["id"] in got
    assert a["id"] not in got, "기준점과 같은 시각의 줄을 다시 준다"
