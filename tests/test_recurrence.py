"""반복 날짜 계산 시험. 이 앱의 첫 시험이다.

## 왜 여기서부터 시험을 쓰나

반복 업무가 틀리는 자리는 전부 **사람이 눈으로 볼 수 없는 곳**이다.
1월 31일에 걸어 둔 월간 업무가 2월에 어디로 가는지는 2월에야 보이고,
2월 29일짜리는 4년에 한 번만 틀리고, "석 달 방치하면 업무가 쏟아지는지" 는
석 달을 기다려야 안다. 그래서 날짜를 넣어 날짜를 받는 순수 함수로 떼어
놓고 (`recurrence.py`), 그 모든 경우를 여기에 박아 둔다.
"""
from datetime import date

import pytest

from recurrence import (
    FREQS, MONTHLY, WEEKLY, WINDOW, YEARLY,
    first_open_seq, nth_due, plan_fill, series_label,
)

D = date


class Test주마다:
    def test_1회차는_기준일_그대로다(self):
        assert nth_due(D(2026, 10, 19), WEEKLY, 1) == D(2026, 10, 19)

    def test_7일씩_더한다(self):
        a = D(2026, 10, 19)
        assert nth_due(a, WEEKLY, 2) == D(2026, 10, 26)
        assert nth_due(a, WEEKLY, 3) == D(2026, 11, 2)
        assert nth_due(a, WEEKLY, 4) == D(2026, 11, 9)

    def test_해를_넘어도_같다(self):
        assert nth_due(D(2026, 12, 28), WEEKLY, 2) == D(2027, 1, 4)


class Test월마다:
    def test_같은_날짜로_간다(self):
        a = D(2026, 10, 15)
        assert nth_due(a, MONTHLY, 2) == D(2026, 11, 15)
        assert nth_due(a, MONTHLY, 4) == D(2027, 1, 15)

    def test_31일은_그_달_마지막_날로_당긴다(self):
        """달을 건너뛰지 않는다 — 월마감에서 2월을 빠뜨리면 실수다."""
        a = D(2026, 1, 31)
        assert nth_due(a, MONTHLY, 1) == D(2026, 1, 31)
        assert nth_due(a, MONTHLY, 2) == D(2026, 2, 28)   # 당겨짐
        assert nth_due(a, MONTHLY, 3) == D(2026, 3, 31)   # 다시 31일
        assert nth_due(a, MONTHLY, 4) == D(2026, 4, 30)   # 당겨짐
        assert nth_due(a, MONTHLY, 5) == D(2026, 5, 31)

    def test_윤년_2월은_29일까지_간다(self):
        assert nth_due(D(2024, 1, 31), MONTHLY, 2) == D(2024, 2, 29)

    def test_30일도_2월에만_당겨진다(self):
        a = D(2026, 1, 30)
        assert nth_due(a, MONTHLY, 2) == D(2026, 2, 28)
        assert nth_due(a, MONTHLY, 3) == D(2026, 3, 30)

    def test_12개월_뒤는_해가_바뀐다(self):
        assert nth_due(D(2026, 1, 31), MONTHLY, 13) == D(2027, 1, 31)
        assert nth_due(D(2026, 12, 15), MONTHLY, 2) == D(2027, 1, 15)


class Test년마다:
    def test_해만_더한다(self):
        assert nth_due(D(2026, 3, 2), YEARLY, 3) == D(2028, 3, 2)

    def test_2월_29일은_평년에_28일로_당겨진다(self):
        a = D(2024, 2, 29)
        assert nth_due(a, YEARLY, 1) == D(2024, 2, 29)
        assert nth_due(a, YEARLY, 2) == D(2025, 2, 28)
        assert nth_due(a, YEARLY, 3) == D(2026, 2, 28)
        assert nth_due(a, YEARLY, 5) == D(2028, 2, 29)   # 다시 윤년


class Test잘못된_입력:
    def test_0회차나_음수는_막는다(self):
        for bad in (0, -1):
            with pytest.raises(ValueError):
                nth_due(D(2026, 10, 19), WEEKLY, bad)

    def test_모르는_주기는_막는다(self):
        # 조용히 주마다로 돌면 사람은 일정이 틀린 줄 모른다.
        with pytest.raises(ValueError):
            nth_due(D(2026, 10, 19), "일", 2)
        with pytest.raises(ValueError):
            first_open_seq(D(2026, 10, 19), "분기", D(2026, 12, 1))

    def test_주기_세_가지뿐이다(self):
        assert FREQS == ("주", "월", "년")


class Test안_지나간_첫_회차:
    def test_오늘이_기준일이면_1회차다(self):
        t = D(2026, 10, 19)
        assert first_open_seq(t, WEEKLY, t) == 1

    def test_기준일이_미래면_1회차다(self):
        assert first_open_seq(D(2026, 12, 1), WEEKLY, D(2026, 10, 19)) == 1

    def test_마감일이_오늘이면_아직_안_지났다(self):
        # D-DAY 업무를 지난 것으로 치면 당일에 업무가 사라진다.
        a = D(2026, 10, 19)
        assert first_open_seq(a, WEEKLY, D(2026, 10, 26)) == 2
        assert nth_due(a, WEEKLY, 2) == D(2026, 10, 26)

    def test_하루_지나면_다음_회차다(self):
        assert first_open_seq(D(2026, 10, 19), WEEKLY, D(2026, 10, 20)) == 2

    def test_석_달_방치한_주간_업무(self):
        # 2026-10-19 + 13주 = 2027-01-18
        assert first_open_seq(D(2026, 10, 19), WEEKLY, D(2027, 1, 18)) == 14

    def test_월말_당기기가_섞여도_맞춘다(self):
        a = D(2026, 1, 31)
        assert first_open_seq(a, MONTHLY, D(2026, 2, 28)) == 2   # 2/28 = 2회차
        assert first_open_seq(a, MONTHLY, D(2026, 3, 1)) == 3    # 2회차 지남
        assert first_open_seq(a, MONTHLY, D(2026, 4, 30)) == 4

    def test_연간_업무의_평년_처리(self):
        a = D(2024, 2, 29)
        assert first_open_seq(a, YEARLY, D(2024, 12, 31)) == 2
        assert first_open_seq(a, YEARLY, D(2025, 2, 28)) == 2
        assert first_open_seq(a, YEARLY, D(2025, 3, 1)) == 3


class Test창_채우기:
    TODAY = D(2026, 10, 19)

    def fill(self, **kw):
        args = dict(anchor=self.TODAY, freq=WEEKLY, total=None,
                    today=self.TODAY, made_through=0, open_count=0)
        args.update(kw)
        return plan_fill(args["anchor"], args["freq"], args["total"],
                         args["today"], made_through=args["made_through"],
                         open_count=args["open_count"])

    def test_새_시리즈는_4개를_만든다(self):
        assert self.fill() == [1, 2, 3, 4]
        assert WINDOW == 4

    def test_횟수가_4보다_적으면_그만큼만(self):
        assert self.fill(total=2) == [1, 2]
        assert self.fill(total=1) == [1]

    def test_창이_차_있으면_만들지_않는다(self):
        assert self.fill(made_through=4, open_count=4, total=10) == []

    def test_하나가_끝나면_하나를_만든다(self):
        # 당신이 쓴 "1회 완료하거나 일정이 지나가면 1개 추가" 가 이 규칙이다.
        assert self.fill(made_through=4, open_count=3, total=10) == [5]
        assert self.fill(made_through=4, open_count=2, total=10) == [5, 6]

    def test_지운_회차는_되살아나지_않는다(self):
        # 5회차를 손으로 지웠다. 창을 메우되 6회차를 만든다.
        assert self.fill(made_through=5, open_count=3, total=10) == [6]

    def test_방치한_기간은_만들지_않는다(self):
        # 석 달 뒤에 들어왔다. 지난 9주치를 쏟아내지 않고 오늘 이후만 만든다.
        got = self.fill(today=D(2027, 1, 18), made_through=4, total=None)
        assert got == [14, 15, 16, 17]

    def test_방치하면_횟수를_쓴_것으로_센다(self):
        # 10회짜리를 석 달 방치하면 14회차는 없다 → 시리즈가 끝난다.
        # 그래야 "년마다 5회" 가 5년 안에 끝난다.
        assert self.fill(today=D(2027, 1, 18), made_through=4, total=10) == []

    def test_횟수를_다_쓰면_끝이다(self):
        assert self.fill(made_through=10, open_count=0, total=10) == []

    def test_마감없음은_계속_채운다(self):
        assert self.fill(made_through=99, open_count=1, total=None) == [100, 101, 102]

    def test_횟수가_0이하면_아무것도_만들지_않는다(self):
        assert self.fill(total=0) == []
        assert self.fill(total=-3) == []

    def test_창이_넘쳐_있어도_줄이지_않는다(self):
        # 완료취소로 5개가 됐다. 이미 만든 업무를 지우는 일은 없다.
        assert self.fill(made_through=5, open_count=5, total=10) == []

    def test_월간_시리즈도_같다(self):
        got = self.fill(anchor=D(2026, 1, 31), freq=MONTHLY,
                        today=D(2026, 1, 31), total=None)
        assert got == [1, 2, 3, 4]
        assert [nth_due(D(2026, 1, 31), MONTHLY, s) for s in got] == [
            D(2026, 1, 31), D(2026, 2, 28), D(2026, 3, 31), D(2026, 4, 30),
        ]


class Test표시:
    def test_횟수가_있으면_분수로(self):
        assert series_label(3, 10) == "3/10회"

    def test_마감없음은_회차만(self):
        assert series_label(3, None) == "3회째"
