"""주간리포트의 **업무 차례** 시험.

## 왜 차례를 시험으로 박아 두나

리포트는 사람이 **위에서부터** 읽는다. 스무 줄짜리 표에서 맨 아래 줄까지
읽는 사람은 없다 — 그러니 "무엇이 맨 위에 오는가" 는 꾸밈이 아니라 **이
리포트가 무엇을 말하는가** 그 자체다. 마감 오름차순만으로 늘어놓으면 내일
마감인 「낮음」짜리 잡무가 이번 주 가장 중요한 「긴급」 업무보다 위에 온다.

차례는 눈으로 봐서 틀린 줄 알기 어렵다. 표가 그럴듯하게 생겼으면 그냥 맞는
줄 알고 넘어간다. 그래서 숫자로 박아 둔다.
"""
import os
from datetime import date, timedelta

import pytest

from weekly_report import (
    PRIORITIES,
    by_priority, classify_tasks, generate_all_report, prio_cell, prio_rank,
    render_task_sections,
)

#: 기준 주 — 월요일부터 일요일까지. 오늘이 그 안에 들게 잡는다.
TODAY = date.today()
WS = TODAY - timedelta(days=TODAY.weekday())
WE = WS + timedelta(days=6)


def task(num, prio, *, due=None, status="진행중", closed=None, title=None):
    """시험용 업무 한 건. 리포트가 읽는 칸만 채운다.

    ⚠️ 기본 상태가 **`진행중`** 이다 — DB 의 기본값과 같은 글자다(`db.py`).
    `진행` 으로 적으면 `evaluate_task` 가 못 알아보고 전부 「⏸ 보류」로
    평가해서, 차례는 맞는데 **평가 칸이 통째로 죽은 표**를 시험이 통과시킨다.
    """
    return {
        "display_num": num,
        "title": title or f"업무{num}",
        "status": status,
        "priority": prio,
        "due_at": due.isoformat() if due else None,
        "closed_at": closed.isoformat() if closed else None,
        "assignee": "이상원",
        "project_id": None,
    }


def nums(tasks):
    return [t["display_num"] for t in tasks]


# ── 차례 ─────────────────────────────────────────────


class Test우선순위_차례:
    def test_긴급_높음_중간_낮음_순이다(self):
        assert PRIORITIES == ("긴급", "높음", "중간", "낮음")
        ranks = [prio_rank(task(1, p)) for p in PRIORITIES]
        assert ranks == sorted(ranks)

    def test_섞어_넣어도_중요한_것이_앞에_온다(self):
        got = by_priority([
            task(1, "낮음"), task(2, "긴급"), task(3, "중간"),
            task(4, "높음"), task(5, "긴급"),
        ])
        assert nums(got) == [2, 5, 4, 3, 1]

    def test_같은_급_안에서는_받은_차례_그대로다(self):
        """들어오는 차례가 **마감 오름차순**이다(`api_server.py` 의 ORDER BY).

        안정 정렬이 아니면 같은 급 안에서 마감이 뒤섞이고, "급이 같으면 급한
        것부터" 라는 둘째 기준이 조용히 사라진다.
        """
        got = by_priority([task(i, "중간") for i in range(1, 8)])
        assert nums(got) == [1, 2, 3, 4, 5, 6, 7]

    def test_안_적힌_우선순위는_중간_자리다(self):
        """**맨 뒤가 아니다.**

        DB 기본값이 `중간` 이고 칸은 NOT NULL 이다(`db.py`). 비어 있는 것은
        "낮다" 가 아니라 "아직 안 정했다" 는 뜻이라, 뒤로 보내면 우선순위를
        적는 것을 잊은 업무가 표 바닥에 깔려 **사라진 것처럼** 보인다.
        """
        got = by_priority([task(1, "낮음"), task(2, ""), task(3, "긴급")])
        assert nums(got) == [3, 2, 1]

    def test_모르는_낱말도_중간_자리다(self):
        """보기를 늘리는 날(예: `보통`) 그 업무가 바닥으로 꺼지면 안 된다."""
        got = by_priority([task(1, "낮음"), task(2, "보통"), task(3, "높음")])
        assert nums(got) == [3, 2, 1]


class Test우선_칸:
    def test_글자를_꼭_적는다(self):
        """그림만 찍으면 「중간」이 **빈 칸**이 되어 자료가 빠진 것처럼
        보이고, 그림이 안 뜨는 곳(메일·터미널)에서는 칸이 통째로 사라진다."""
        for p in PRIORITIES:
            assert p in prio_cell(task(1, p))

    def test_대시보드와_같은_그림이다(self):
        """한쪽만 바꾸면 같은 업무가 두 화면에서 다른 급으로 보인다."""
        import dashboard_html  # noqa: F401  (가져와지는지까지 본다)
        assert prio_cell(task(1, "긴급")).startswith("🔥")
        assert prio_cell(task(1, "높음")).startswith("⭐")
        assert prio_cell(task(1, "낮음")).startswith("➖")
        assert prio_cell(task(1, "중간")) == "중간"

    def test_비면_미정이라고_적는다(self):
        assert prio_cell(task(1, "")) == "미정"


# ── 섹션별로 갈라 놓아도 차례가 산다 ──────────────────


class Test분류:
    def test_섹션마다_우선순위_차례로_선다(self):
        """`classify_tasks` 가 차례를 안 세우면, 표를 그리는 쪽이 각자
        세워야 하고 다섯 표 중 하나를 잊는 날이 온다."""
        groups = classify_tasks([
            task(1, "낮음", due=WE),
            task(2, "긴급", due=WE),
            task(3, "중간", due=WE),
        ], WS, WE, TODAY)
        assert nums(groups["this_week"]) == [2, 3, 1]

    def test_지연_업무도_우선순위가_먼저다(self):
        old = TODAY - timedelta(days=30)
        recent = TODAY - timedelta(days=1)
        groups = classify_tasks([
            task(1, "낮음", due=old),      # 가장 오래 밀렸다
            task(2, "긴급", due=recent),
        ], WS, WE, TODAY)
        assert nums(groups["delayed"]) == [2, 1]

    def test_완료_업무도_마찬가지다(self):
        groups = classify_tasks([
            task(1, "중간", status="완료", closed=WS),
            task(2, "긴급", status="완료", closed=WS),
        ], WS, WE, TODAY)
        assert nums(groups["completed"]) == [2, 1]

    def test_마감_미정은_장기로_가고_거기서도_차례가_선다(self):
        groups = classify_tasks([
            task(1, "낮음"), task(2, "높음"),
        ], WS, WE, TODAY)
        assert nums(groups["long_term"]) == [2, 1]


# ── 표에 찍히는 것 ───────────────────────────────────


class Test표:
    def _render(self, tasks):
        lines = []
        render_task_sections(
            lines, classify_tasks(tasks, WS, WE, TODAY), WS, WE)
        return lines

    #: 다섯 표가 **모두 그려지는** 한 벌. 빈 섹션은 표 대신 "없습니다" 한
    #: 줄만 찍으므로, 한 건만 넣으면 표 하나밖에 안 본다.
    ALL_FIVE = (
        task(1, "중간", status="완료", closed=WS),       # 기준 주 완료
        task(2, "중간", due=TODAY - timedelta(days=2)),  # 지연
        task(3, "중간", due=TODAY),                      # 이번주
        task(4, "중간", due=WE + timedelta(days=3)),     # 다음주
        task(5, "중간"),                                 # 장기(마감 미정)
    )

    def test_우선_칸이_맨_앞에_선다(self):
        """차례를 우선순위로 정하면서 **기준을 안 보여 주면**, 읽는 사람에게는
        그냥 뒤죽박죽인 표다 — 그러면 자기 눈으로 다시 훑는다."""
        lines = self._render(list(self.ALL_FIVE))
        heads = [l for l in lines if l.startswith("| 우선 |")]
        # 다섯 표 전부 (완료·지연·이번주·다음주·장기)
        assert len(heads) == 5
        for h in heads:
            assert h.startswith("| 우선 | # | 제목")

    def test_칸_수가_구분선과_맞는다(self):
        """마크다운 표는 머리줄과 구분선의 칸 수가 **다르면 표로 안 그려진다.**
        칸을 하나 더하면서 구분선을 잊는 것이 가장 흔한 실수다."""
        lines = self._render(list(self.ALL_FIVE))
        for i, line in enumerate(lines):
            if line.startswith("|") and not line.startswith("|---"):
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if nxt.startswith("|---"):
                    assert line.count("|") == nxt.count("|"), line

    def test_줄이_우선순위_차례로_찍힌다(self):
        lines = self._render([
            task(1, "낮음", due=WE, title="잡무"),
            task(2, "긴급", due=WE, title="불난 것"),
        ])
        body = [l for l in lines if l.startswith("| 🔥") or l.startswith("| ➖")]
        assert body[0].startswith("| 🔥")


# ── 전체 리포트 ──────────────────────────────────────


class Test전체_리포트:
    def test_지연_하이라이트도_우선순위_차례다(self, tmp_path):
        """경영진이 **맨 먼저 보는 표**다. 여기가 마감순이면 가장 급한 일이
        아래로 밀린다."""
        old = TODAY - timedelta(days=30)
        recent = TODAY - timedelta(days=1)
        out = generate_all_report({
            "assignee": "All",
            "week_start": WS.isoformat(),
            "week_end": WE.isoformat(),
            "tasks": [
                task(1, "낮음", due=old, title="오래 밀린 잡무"),
                task(2, "긴급", due=recent, title="어제 마감인 불난 것"),
            ],
            "projects": [],
            "members": ["이상원"],
        })
        assert out.get("ok"), out
        md = out["md_content"]
        assert "오래 밀린 잡무" in md and "어제 마감인 불난 것" in md
        assert md.index("어제 마감인 불난 것") < md.index("오래 밀린 잡무")

    def test_리포트가_시험_폴더_밖에_안_쓴다(self):
        """conftest 가 `BRANUP_DATA_DIR` 을 임시 폴더로 돌려 놓는다. 그게
        안 먹으면 운영 `data/reports/` 에 시험 파일이 쌓인다 — portal 에서
        그 사고가 한 번 있었다."""
        import weekly_report
        assert os.environ["BRANUP_DATA_DIR"] in str(weekly_report.REPORT_DIR)
