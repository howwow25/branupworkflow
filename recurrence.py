"""반복 업무의 날짜 계산. (CONTEXT.md 의 '반복 시리즈' · '회차' · '창')

## 왜 DB 를 모르는 파일인가

월말 당기기와 윤년은 **눈으로 확인할 수 없다.** 1월 31일에 만든 월간 업무가
2월에 어디로 가는지는 2월이 되어야 보이고, 2월 29일짜리는 4년에 한 번만
틀린다. 그래서 이 파일은 sqlite 를 import 하지 않는다 — 날짜를 넣고 날짜를
받는 순수 함수라서 `tests/test_recurrence.py` 가 1월 31일도 2100년도 지금
당장 돌려 본다. 이 앱의 첫 시험이 여기인 이유다.

## 창(window) 이 4개인 이유

"마감없음" 반복을 날짜만 보고 펼치면 업무가 무한히 생긴다. 그래서 **아직
끝나지 않은 회차가 4개를 넘지 않을 때까지만** 만든다. 하나가 끝나면
(완료 · 마감지남 · 삭제) 그때 하나를 더 만든다. 먼 미래를 미리 다 적어 두지
않고 앞의 4개만 보여 준다.

## 밀린 기간은 만들지 않는다

석 달 방치한 주간 업무의 지난 12주를 지금 만들면 그것이 바로 "업무가 엄청
많이 생긴다" 이고, 그 12개는 **아무도 할 수 없는 일**이다. 지나간 회차는
건너뛰되 횟수는 쓴 것으로 센다 — 그래야 "년마다 5회" 가 5년 안에 끝난다.
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta

# 한 시리즈에서 동시에 열어 두는 최대 회차 수.
WINDOW = 4

WEEKLY, MONTHLY, YEARLY = "주", "월", "년"
FREQS = (WEEKLY, MONTHLY, YEARLY)

FREQ_LABEL = {WEEKLY: "주마다", MONTHLY: "월마다", YEARLY: "년마다"}

# 밀린 회차를 건너뛸 때의 상한. 주간 업무를 100년 방치해도 5,200 이라
# 정상 입력으로는 닿지 않는다. 깨진 데이터로 영원히 도는 것만 막는다.
MAX_SKIP = 20000


def _clamp(year: int, month: int, day: int) -> date:
    """그 달에 없는 날은 그 달 마지막 날로 당긴다 (1/31 → 2/28).

    기준일의 '일' 은 31 그대로 기억하므로 3월엔 다시 31일로 돌아온다.
    달을 통째로 건너뛰지 않는다 — 월마감·정기점검에서 2월을 빠뜨리는 것은
    거의 항상 실수다.
    """
    return date(year, month, min(day, monthrange(year, month)[1]))


def nth_due(anchor: date, freq: str, seq: int) -> date:
    """`seq` 회차의 마감일. 회차는 1부터이고 **1회차가 `anchor`** 다."""
    if seq < 1:
        raise ValueError(f"회차는 1부터입니다: {seq}")
    n = seq - 1
    if freq == WEEKLY:
        return anchor + timedelta(weeks=n)
    if freq == MONTHLY:
        total = (anchor.month - 1) + n
        return _clamp(anchor.year + total // 12, total % 12 + 1, anchor.day)
    if freq == YEARLY:
        return _clamp(anchor.year + n, anchor.month, anchor.day)
    raise ValueError(f"모르는 주기: {freq!r}")


def first_open_seq(anchor: date, freq: str, today: date) -> int:
    """마감일이 `today` 보다 이르지 않은 **첫** 회차 번호."""
    if today <= anchor:
        return 1
    if freq == WEEKLY:
        seq = (today - anchor).days // 7 + 1
    elif freq == MONTHLY:
        seq = (today.year - anchor.year) * 12 + (today.month - anchor.month) + 1
    elif freq == YEARLY:
        seq = today.year - anchor.year + 1
    else:
        raise ValueError(f"모르는 주기: {freq!r}")
    seq = max(1, seq)
    # 산술로 찍은 값은 월말 당기기 때문에 한 칸 어긋날 수 있다. 양쪽으로 맞춘다.
    while seq > 1 and nth_due(anchor, freq, seq - 1) >= today:
        seq -= 1
    for _ in range(MAX_SKIP):
        if nth_due(anchor, freq, seq) >= today:
            return seq
        seq += 1
    raise ValueError("건너뛸 회차가 너무 많습니다 — 기준일을 확인하세요")


def plan_fill(anchor: date, freq: str, total: int | None, today: date, *,
              made_through: int, open_count: int) -> list[int]:
    """다음에 만들 회차 번호들. 창이 찼거나 횟수를 다 썼으면 빈 목록.

    `made_through` 는 **지금까지 한 번이라도 만든 가장 높은 회차**다. 남아
    있는 업무가 아니라 만든 기록을 기준으로 삼아야, 사람이 미래 회차를
    지웠을 때 그 번호가 되살아나지 않는다 (지운 것이 다시 생기면 지울
    방법이 없다).

    `open_count` 는 창에 들어 있는 개수 — 완료도 마감지남도 아닌 회차다.
    """
    if total is not None and total < 1:
        return []
    start = max(made_through + 1, first_open_seq(anchor, freq, today))
    out: list[int] = []
    while open_count + len(out) < WINDOW:
        seq = start + len(out)
        if total is not None and seq > total:
            break
        out.append(seq)
    return out


def series_label(seq: int, total: int | None) -> str:
    """목록·카드에 붙는 글. 마감없음은 전체를 모르니 회차만 적는다."""
    return f"{seq}/{total}회" if total else f"{seq}회째"


# ── 제목의 기간 표시 고치기 ──────────────────────────────
#
# "[재무리뷰] 10월 3주" 처럼 제목에 기간을 적어 두는 사람이 있다. 회차마다
# 손으로 고치는 것이 실제로 하던 일이라(2026-10-19 에 4개를 만들고 1분 뒤
# 4개를 모두 고친 기록이 있다) 그걸 대신한다.
#
# ## 주차는 ⌈일/7⌉ 이다
#
# 한국식 주차는 셈법이 갈린다 — "1일이 든 주를 1주차" 로 보면 10월 19일은
# 4주차고, "그 달의 n번째 월요일" 로 보면 3주차다. 사용자가 직접 적은 제목이
# 10/19=3주 · 10/26=4주 · 11/2=1주 였으므로 후자다.
#
# 그리고 **⌈일/7⌉ 과 "n번째 같은 요일" 은 언제나 같은 값이다**: 어떤 요일의
# 그 달 첫 등장일 d 는 1..7 이고 n 번째는 d+7(n-1) 이므로
# ⌈(d+7(n-1))/7⌉ = ⌈d/7⌉ + (n-1) = n. 그래서 식 하나로 두 직관을 모두 만족한다.

def week_of_month(d: date) -> int:
    """그 달 며칠째 주인지. ⌈일/7⌉ = 그 달의 n번째 같은 요일."""
    return (d.day - 1) // 7 + 1


# 찾는 순서가 중요하다 — 좁은 것부터. "2026년 10월 3주" 에 월 패턴을 먼저
# 대면 "10월" 만 바뀌고 "3주" 가 묵은 값으로 남는다.
_YEAR = r"(?:(?P<y>\d{4})\s*년\s*)?"
_PERIOD_PATTERNS = (
    ("week",  re.compile(_YEAR + r"(?P<m>\d{1,2})\s*월\s*(?P<w>\d{1,2})\s*주(?P<cha>차)?")),
    ("month", re.compile(_YEAR + r"(?P<m>\d{1,2})\s*월")),
    ("year",  re.compile(r"(?P<y>\d{4})\s*년")),
)


def relabel(title: str, d: date) -> str | None:
    """제목의 기간 표시를 `d` 에 맞춰 고친다. 표시가 없으면 `None`.

    주기를 받지 않는다 — 무엇을 고칠지는 **제목에 적힌 모양**이 정한다.
    "10월 3주" 는 월과 주를, "10월" 은 월을, "2026년" 은 해를 고친다. 연도나
    "차" 처럼 원래 있던 꾸밈은 그대로 둔다. 없던 것을 붙이지 않는다.

    표시가 여러 번 나오면 **첫 번째만** 고친다. 제목에 날짜가 두 개 들어가는
    경우는 둘이 다른 뜻일 가능성이 높아서, 둘 다 고치면 더 틀린다.
    """
    if not title:
        return None
    for kind, pat in _PERIOD_PATTERNS:
        m = pat.search(title)
        if not m:
            continue
        g = m.groupdict()
        year = f"{d.year}년 " if g.get("y") else ""
        if kind == "week":
            new = f"{year}{d.month}월 {week_of_month(d)}주" + (g.get("cha") or "")
        elif kind == "month":
            new = f"{year}{d.month}월"
        else:
            new = f"{d.year}년"
        return title[:m.start()] + new + title[m.end():]
    return None
