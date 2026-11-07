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


# ── 삭제 ─────────────────────────────────────────────────
#
# **삭제는 `task_events` 에 남길 수 없다.** 그 표는 `tasks(id)` 외래키를
# 갖고 CASCADE 가 없어서 업무를 지우려면 기록을 먼저 치워야 하고, 포털이
# 읽는 `events_since` 는 제목·담당자를 얻으려고 `tasks` 를 조인한다 — 지워진
# 업무는 조인할 상대가 없다. 그래서 `task_deletions` 가 제목과 담당자를
# **베껴 적는다.**


def _drops(*task_ids) -> list:
    """그 업무들의 삭제 줄만.

    **업무로 좁혀야 한다.** 시험들이 한 DB 를 함께 쓰므로(`conftest.py` 가
    한 번만 폴더를 정한다) `events_since()` 는 **다른 시험이 지운 것까지**
    돌려준다. 그걸 세면 "몇 통 가나" 시험이 돌 때마다 다른 수를 낸다.
    """
    want = set(task_ids)
    return [e for e in db.events_since()
            if e["event_type"] == "삭제" and e["task_id"] in want]


def test_지우면_기록이_남는다(room):
    t = db.create_task(room["id"], title="지울 업무", assignee="이향석",
                       actor="이상원")
    assert db.delete_task(t["id"], actor="이상원") == 1

    rows = _drops(t["id"])
    assert len(rows) == 1
    e = rows[0]
    assert e["task_id"] == t["id"]
    assert e["title"] == "지울 업무", "제목을 베껴 적지 않았다"
    assert e["assignee"] == "이향석", "담당자를 베껴 적지 않았다"
    assert e["display_num"] == t["display_num"]
    assert e["payload"]["by"] == "이상원"


def test_지워도_업무를_조인하지_않는다(room):
    """`tasks` 를 조인하면 지워진 업무의 줄은 **영영 나오지 않는다.** 이
    시험이 그 구조를 지킨다 — 기능이 조용히 사라지는 자리다."""
    t = db.create_task(room["id"], title="사라질 업무", assignee="이향석")
    db.delete_task(t["id"], actor="이상원")

    assert db.get_task_by_id(t["id"]) is None, "이 시험의 전제가 깨졌다"
    assert any(e["event_type"] == "삭제" and e["task_id"] == t["id"]
               for e in db.events_since())


def test_지운_사람을_모르면_칸이_없다(room):
    t = db.create_task(room["id"], title="누가 지웠는지 모름", assignee="이향석")
    db.delete_task(t["id"])
    assert "by" not in _drops(t["id"])[0]["payload"]


def test_옛_기록은_함께_사라진다(room):
    """업무를 지우면 그 업무의 변경 기록도 지워진다(외래키). 삭제 줄만
    남는다 — 없어진 업무의 「마감일 변경」 알림이 뒤늦게 가면 안 된다."""
    t = db.create_task(room["id"], title="고쳤다 지울 업무", assignee="이향석")
    db.update_task(t["id"], due_at="2026-12-01", actor="이상원")
    assert any(e["event_type"] == "마감일 변경" for e in db.events_since())

    db.delete_task(t["id"], actor="이상원")
    kinds = {e["event_type"] for e in db.events_since()
             if e["task_id"] == t["id"]}
    assert kinds == {"삭제"}, f"남은 기록: {kinds}"


def test_반복을_이후_모두_지우면_한_줄만_남는다(room):
    """회차마다 남기면 월간 반복 여섯 회차를 지울 때 담당자에게 **여섯 통**이
    간다. 사람이 한 번 누른 일이므로 한 통이 맞다."""
    s = db.create_series(room["id"], freq="월", anchor_date="2026-11-10",
                         total_count=4, title="월간 보고", summary="월간 보고",
                         assignee="이향석", priority="중간")
    db.backfill_series("2026-11-01")
    made = db.get_series_tasks(s["id"])
    assert len(made) >= 2, f"이 시험의 전제가 깨졌다 (회차 {len(made)}개)"

    ids = [dict(r)["id"] for r in made]
    res = db.delete_task_following(ids[0], actor="이상원")
    assert res["deleted"] >= 2

    rows = _drops(*ids)
    assert len(rows) == 1, f"삭제 줄이 {len(rows)}개다 — 통이 그만큼 간다"
    assert rows[0]["payload"]["following"] == res["deleted"] - 1
    assert rows[0]["payload"]["by"] == "이상원"


def test_반복_멈추기는_알림_기록을_남기지_않는다(room):
    """거기서 지우는 것은 **아직 오지도 않은 미래 회차**다. "업무가
    지워졌습니다" 를 보내면 담당자는 없어진 적 없는 일을 찾는다."""
    s = db.create_series(room["id"], freq="월", anchor_date="2026-11-10",
                         total_count=6, title="멈출 반복", summary="멈출 반복",
                         assignee="이향석", priority="중간")
    db.backfill_series("2026-11-01")
    ids = [dict(r)["id"] for r in db.get_series_tasks(s["id"])]
    db.stop_series(s["id"], delete_future=True)

    assert not _drops(*ids)


# ── 누가 보고 있나 — 화면이 포털에 묻는다 ────────────────
#
# 이 앱에는 인증이 전혀 없다. 「나는 OOO」 를 손으로 고르게 해 뒀는데 안
# 고르면 알림이 본인에게도 가고 **아무도 그걸 모른다.** 포털과 같은 호스트라
# 로그인 쿠키가 이 화면에도 오므로 진짜 이름을 물을 수 있다.


def _baked() -> str:
    import dashboard_html
    return dashboard_html.render()


def test_제목에_이름을_넣을_자리가_있다():
    html = _baked()
    assert 'id="whoami"' in html
    assert "브랜업 대시보드<span id=\"whoami\">" in html, \
        "제목과 이름 사이에 다른 것이 끼었다"


def test_포털을_못_읽으면_손으로_고르는_줄이_남는다():
    """`file://` 로 열었거나 로그인하지 않았을 때다. **인증도 없는 이 앱이
    포털 때문에 못 쓰이게 되면 안 된다.**"""
    html = _baked()
    assert 'id="actorRow"' in html, "숨길 대상에 이름표가 없다"
    assert 'id="actorPick"' in html
    # 숨기는 일은 포털이 **답했을 때만** 일어나야 한다.
    assert "catch(function() {" in html


def test_명단을_화면에_실어_보낸다():
    """포털 이름이 업무 담당자 명단에 없으면 **알림이 조용히 틀린다** —
    담당자 이름과 안 맞아서 "본인이 바꾼 것 빼기" 가 작동하지 않는다.
    화면이 그걸 알아보려면 명단이 있어야 한다."""
    import json

    from roster import RESIGNED, ROSTER

    html = _baked()
    assert "var ROSTER_NAMES = " in html
    for name in set(ROSTER) - set(RESIGNED):
        assert json.dumps(name, ensure_ascii=False) in html, name


def test_퇴사자는_명단에_없다():
    import re

    from roster import RESIGNED

    html = _baked()
    m = re.search(r"var ROSTER_NAMES = (\[.*?\]);", html)
    assert m, "명단을 못 찾았다"
    for name in RESIGNED:
        assert name not in m.group(1), f"{name} 은 퇴사자다"


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


# ── 머리에 실려 온 이름 ─────────────────────────────────
#
# **2026-11-07 에 실제로 깨져 있던 자리다.** 헤더 값은 latin-1 이어서 한글이
# 그대로 실리지 않는다. 기록의 `by` 가 깨진 글자이면 포털의 "본인이 바꾼 것을
# 본인에게 보내지 않는다" 가 **영구히 작동하지 않는다** — 그런데 화면도
# 서버도 아무 오류를 내지 않아서 아무도 모른다.


def test_퍼센트로_감싼_이름을_되돌린다():
    from api_server import decode_actor
    assert decode_actor("%EC%A0%84%EB%8C%80%EB%B0%95") == "전대박"


def test_깨진_글자도_되돌린다():
    """구운 화면이 브라우저에 캐시돼 있는 경우다. 배포 직후 새로고침을 안 한
    사람의 이름이 조용히 사라지면 안 된다."""
    from api_server import decode_actor
    깨진 = "전대박".encode("utf-8").decode("latin-1")
    assert 깨진 != "전대박", "이 시험의 전제가 깨졌다"
    assert decode_actor(깨진) == "전대박"


def test_아스키_이름은_그대로():
    from api_server import decode_actor
    assert decode_actor("admin") == "admin"


def test_비었으면_None():
    from api_server import decode_actor
    assert decode_actor(None) is None
    assert decode_actor("   ") is None


def test_길이는_되돌린_뒤에_자른다():
    """깨진 바이트를 먼저 자르면 글자 가운데가 끊겨 되돌릴 수 없는 값이 된다.
    상한은 **글자 수**다 — 깨진 글자로 받으면 바이트가 세 배라, 먼저 자르면
    40바이트(13자 남짓)에서 끊긴다."""
    from api_server import ACTOR_MAX, decode_actor
    긴이름 = "김" * (ACTOR_MAX + 10)
    got = decode_actor(긴이름.encode("utf-8").decode("latin-1"))
    assert got == "김" * ACTOR_MAX, "글자가 아니라 바이트로 잘랐다"
    assert "�" not in got and got.isprintable()


def test_since_는_그_뒤에_쌓인_것만_준다(room):
    """포털이 같은 알림을 두 번 보내지 않게 하는 기준점이다."""
    a = db.create_task(room["id"], title="먼저", actor="전대박")
    mark = db.get_task_events(a["id"])[0]["created_at"]
    b = db.create_task(room["id"], title="나중", actor="전대박")

    got = {e["task_id"] for e in db.events_since(mark)}
    assert b["id"] in got
    assert a["id"] not in got, "기준점과 같은 시각의 줄을 다시 준다"
