#!/usr/bin/env python3
"""
주간리포트 생성기 v2 — 프로젝트 중심 + 업무 평가

변경사항 (report-add-02):
- 프로젝트 중심 보고 (선택 직원이 참여한 프로젝트별 그룹화)
- 프로젝트 미지정 업무 별도 섹션
- 업무 평가 (정시 완료 / 지연 완료 / 마감 임박 / 정상 진행 / 지연)

사용법:
  python3 weekly_report.py --json '{"assignee":"강경철",...}'
  python3 weekly_report.py --file /path/to/payload.json
  echo '{"assignee":"강경철",...}' | python3 weekly_report.py --stdin

출력: JSON {ok, report_path, md_content, assignee, week}
"""
import sys
import os
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
DATA_DIR = os.environ.get("BRANUP_DATA_DIR",
    str(Path(__file__).parent.parent / "data"))
REPORT_DIR = Path(DATA_DIR) / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def dday(due_str):
    """마감까지 남은 일수"""
    if not due_str:
        return None
    try:
        due_date = datetime.strptime(due_str[:10], "%Y-%m-%d").date()
        today = datetime.now(KST).date()
        return (due_date - today).days
    except Exception:
        return None


def dday_label(dd):
    if dd is None:
        return "미정"
    if dd < 0:
        return f"D+{abs(dd)}"
    if dd == 0:
        return "D-DAY"
    return f"D-{dd}"


def evaluate_task(t, ws_date, we_date):
    """
    업무 평가:
    - 완료 업무: 정시 완료 / 지연 완료 / 기한 없음
    - 진행중 업무: 정상 진행 / 마감 임박 / 지연
    반환: (평가문구, 평가등급)
    등급: excellent / good / warning / danger / neutral
    """
    status = t.get("status", "")
    due_str = t.get("due_at", "")
    closed_str = t.get("closed_at", "")

    due_date = None
    if due_str:
        try:
            due_date = datetime.strptime(due_str[:10], "%Y-%m-%d").date()
        except Exception:
            pass

    closed_date = None
    if closed_str:
        try:
            closed_date = datetime.strptime(closed_str[:10], "%Y-%m-%d").date()
        except Exception:
            pass

    today = datetime.now(KST).date()

    # ── 완료 업무 평가 ──
    if status == "완료" and closed_date:
        if due_date:
            if closed_date <= due_date:
                days_early = (due_date - closed_date).days
                if days_early >= 3:
                    return f"🎖 조기 완료 ({days_early}일 단축)", "excellent"
                elif days_early >= 1:
                    return f"✅ 정시 완료 ({days_early}일 단축)", "good"
                else:
                    return "✅ 정시 완료", "good"
            else:
                days_late = (closed_date - due_date).days
                return f"⏰ 지연 완료 (D+{days_late})", "danger"
        else:
            return "✅ 완료 (기한 없음)", "neutral"

    # ── 진행중 업무 평가 (미완료) ──
    if status in ("진행중", ):
        if due_date:
            if due_date < today:
                dd = (today - due_date).days
                return f"🚨 지연 (D+{dd})", "danger"
            elif due_date == today:
                return "🔴 오늘 마감", "danger"
            elif due_date <= today + timedelta(days=3):
                dd = (due_date - today).days
                return f"🟡 마감 임박 (D-{dd})", "warning"
            else:
                return "🟢 정상 진행", "good"
        else:
            return "🟢 진행중 (마감 미정)", "good"

    # ── 보류 등 기타 ──
    return "⏸ 보류", "neutral"


# ── 섹션 분류 ────────────────────────────────────────
# 리포트 표 하나에 대응하는 분류 키. 순서 = 리포트에 찍히는 순서.
BUCKETS = ("completed", "prev_completed", "delayed",
           "this_week", "next_week", "long_term")


def _parse_date(s):
    """'2026-08-10' 또는 '2026-08-10T09:00' 에서 date 만 뽑는다. 실패하면 None."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def week_bucket(t, ws_date, we_date, today):
    """
    업무 하나를 리포트 섹션 하나로 분류한다.

    completed      기준 주에 완료        → ✅ 기준 주 완료
    prev_completed 기준 주 밖에서 완료   → 표에서 제외 (요약 통계에만 집계)
    delayed        미완료 · 마감 지남    → ⚠️ 지연 업무
    this_week      미완료 · 기준 주 마감 → 🔄 이번주 진행중
    next_week      미완료 · 그 다음 주   → 📅 다음주 예정
    long_term      그 이후 + 마감 미정   → 🗓 장기 과제

    '이번주/다음주'는 오늘이 아니라 사용자가 고른 **기준 주**를 축으로 삼는다.
    지난 주를 기준으로 뽑아도 구간이 밀리지 않게 하기 위함이다.
    """
    status = t.get("status", "")
    due_date = _parse_date(t.get("due_at"))
    closed_date = _parse_date(t.get("closed_at"))

    if status == "완료":
        if closed_date and ws_date and we_date and ws_date <= closed_date <= we_date:
            return "completed"
        return "prev_completed"

    if due_date and due_date < today:
        return "delayed"
    if not due_date:
        return "long_term"          # 마감 미정도 장기 과제로 묶어 눈에 띄게 한다
    if we_date is None:
        # 기준 주 파싱 실패 시 오늘이 속한 주로 대체
        we_date = today + timedelta(days=6 - today.weekday())
    if due_date <= we_date:
        return "this_week"
    if due_date <= we_date + timedelta(days=7):
        return "next_week"
    return "long_term"


def classify_tasks(tasks, ws_date, we_date, today):
    """업무 목록을 섹션별로 나눈다. 각 리스트는 원본(마감 오름차순) 순서를 유지."""
    out = {b: [] for b in BUCKETS}
    for t in tasks:
        out[week_bucket(t, ws_date, we_date, today)].append(t)
    return out


def bucket_counts(title, tasks, groups):
    """요약 통계 표에 넣을 한 행."""
    row = {"title": title, "total": len(tasks)}
    row.update({b: len(groups[b]) for b in BUCKETS})
    return row


def render_task_sections(lines, groups, ws_date, we_date):
    """분류된 업무를 5개 표로 출력한다. (prev_completed 는 의도적으로 표에서 제외)"""
    def ev(t):
        return evaluate_task(t, ws_date, we_date)[0]

    def num(t):
        return t.get("display_num", "?")

    lines.append("### ✅ 기준 주 완료")
    lines.append("")
    if groups["completed"]:
        lines.append("| # | 제목 | 완료일 | 평가 |")
        lines.append("|---|---|---|---|")
        for t in groups["completed"]:
            closed = (t.get("closed_at") or "")[:10]
            lines.append(f"| #{num(t)} | {t.get('title', '')} | {closed} | {ev(t)} |")
    else:
        lines.append("*기준 주에 완료된 업무가 없습니다.*")
    lines.append("")

    lines.append("### ⚠️ 지연 업무")
    lines.append("")
    if groups["delayed"]:
        lines.append("| # | 제목 | 마감 | 지연일 | 평가 |")
        lines.append("|---|---|---|---|---|")
        for t in groups["delayed"]:
            due = (t.get("due_at") or "")[:10]
            dd = dday(t.get("due_at"))
            lines.append(f"| #{num(t)} | {t.get('title', '')} | {due} | D+{abs(dd)} | {ev(t)} |")
    else:
        lines.append("*지연된 업무가 없습니다.* 👍")
    lines.append("")

    for key, heading, empty_note in (
        ("this_week", "### 🔄 이번주 진행중", "*이번주 마감 예정 업무가 없습니다.*"),
        ("next_week", "### 📅 다음주 예정",   "*다음주 마감 예정 업무가 없습니다.*"),
        ("long_term", "### 🗓 장기 과제",     "*장기 과제가 없습니다.*"),
    ):
        lines.append(heading)
        lines.append("")
        if groups[key]:
            lines.append("| # | 제목 | 마감 | D-Day | 평가 |")
            lines.append("|---|---|---|---|---|")
            for t in groups[key]:
                due = (t.get("due_at") or "")[:10] if t.get("due_at") else ""
                lines.append(f"| #{num(t)} | {t.get('title', '')} | {due} | {dday_label(dday(t.get('due_at')))} | {ev(t)} |")
        else:
            lines.append(empty_note)
        lines.append("")


def generate_report(payload: dict) -> dict:
    """
    프로젝트 중심 주간리포트 생성

    payload = {
        "assignee": "강경철",
        "week_start": "2026-06-15",
        "week_end": "2026-06-21",
        "total": 10,
        "tasks": [...],       # 직원의 모든 업무 (보류 제외)
        "projects": [...]     # 직원이 참여한 프로젝트 목록
    }
    """
    assignee = payload.get("assignee", "미정")
    week_start = payload.get("week_start", "")
    week_end = payload.get("week_end", "")
    tasks = payload.get("tasks", [])
    projects = payload.get("projects", [])

    if assignee in ("All", "전체"):
        return generate_all_report(payload)

    # ── 날짜 파싱 ──
    try:
        ws_date = datetime.strptime(week_start, "%Y-%m-%d").date() if week_start else None
        we_date = datetime.strptime(week_end, "%Y-%m-%d").date() if week_end else None
    except ValueError:
        ws_date = we_date = None

    today = datetime.now(KST).date()
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

    # ── 프로젝트 인덱스 (id → project) ──
    proj_map = {p["id"]: p for p in projects}

    # ── 프로젝트별 업무 그룹화 ──
    # {project_id: [tasks], None: [no-project tasks]}
    proj_tasks = {}  # id → list
    no_proj_tasks = []
    for t in tasks:
        pid = t.get("project_id")
        if pid and pid in proj_map:
            proj_tasks.setdefault(pid, []).append(t)
        else:
            no_proj_tasks.append(t)

    # ── 마크다운 생성 ──
    lines = []
    lines.append(f"# 📊 {assignee} 주간리포트")
    lines.append(f"**기준 주:** {week_start} ~ {week_end}  ")
    lines.append(f"**생성일:** {now_str}  ")
    lines.append(f"**전체 업무:** {len(tasks)}건 | **프로젝트:** {len(proj_tasks)}개 | **미지정:** {len(no_proj_tasks)}건  ")
    # 한눈에 보는 배분 — 아래 프로젝트별 표를 다 읽지 않아도 이번주/다음주 부하가 보이게
    _ov = classify_tasks(tasks, ws_date, we_date, today)
    lines.append(
        f"**🚨 지연:** {len(_ov['delayed'])} | **🔄 이번주:** {len(_ov['this_week'])} | "
        f"**📅 다음주:** {len(_ov['next_week'])} | **🗓 장기:** {len(_ov['long_term'])}  "
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 프로젝트별 섹션 ──
    stats_summary = []  # 프로젝트별 통계 누적
    all_evaluations = {"excellent": 0, "good": 0, "warning": 0, "danger": 0, "neutral": 0}

    for pid, ptasks in proj_tasks.items():
        proj = proj_map[pid]
        proj_title = proj.get("title", "이름없음")
        proj_status = proj.get("status", "?")
        proj_start = proj.get("start_date", "")[:10] if proj.get("start_date") else "?"
        proj_end = proj.get("expected_end_date", "")[:10] if proj.get("expected_end_date") else "?"
        proj_assignees = proj.get("assignees", "")

        # ── 프로젝트 헤더 ──
        lines.append(f"## 📁 {proj_title}")
        lines.append(f"**상태:** {proj_status} | **기간:** {proj_start} ~ {proj_end}  ")
        lines.append(f"**업무:** {len(ptasks)}건  ")
        lines.append("")

        # ── 분류 ──
        groups = classify_tasks(ptasks, ws_date, we_date, today)

        # ── 평가 수집 ──
        for t in ptasks:
            ev, grade = evaluate_task(t, ws_date, we_date)
            all_evaluations[grade] = all_evaluations.get(grade, 0) + 1

        # ── 업무 표 (기준 주 완료 / 지연 / 이번주 / 다음주 / 장기) ──
        render_task_sections(lines, groups, ws_date, we_date)

        # 프로젝트 통계
        stats_summary.append(bucket_counts(proj_title, ptasks, groups))

        lines.append("---")
        lines.append("")

    # ── 프로젝트 미지정 업무 섹션 ──
    if no_proj_tasks:
        lines.append("## 📋 프로젝트 미지정 업무")
        lines.append("")
        lines.append(f"**업무:** {len(no_proj_tasks)}건  ")
        lines.append("")

        # 분류
        n_groups = classify_tasks(no_proj_tasks, ws_date, we_date, today)

        # 평가 수집
        for t in no_proj_tasks:
            ev, grade = evaluate_task(t, ws_date, we_date)
            all_evaluations[grade] = all_evaluations.get(grade, 0) + 1

        render_task_sections(lines, n_groups, ws_date, we_date)

        stats_summary.append(bucket_counts("📋 미지정", no_proj_tasks, n_groups))

        lines.append("---")
        lines.append("")

    # ── 전체 요약 통계 (프로젝트별) ──
    # '이전 완료'는 기준 주 밖에서 끝난 업무 — 표에는 안 나오고 여기서만 집계된다.
    # 6개 열의 합 = 전체 열이 되도록 맞춰 두었다.
    lines.append("## 📊 요약 통계")
    lines.append("")
    lines.append("| 프로젝트 | 전체 | 기준주 완료 | 이전 완료 | 지연 | 이번주 | 다음주 | 장기 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    tot = {b: 0 for b in BUCKETS}
    for s in stats_summary:
        lines.append(
            f"| {s['title']} | {s['total']} | {s['completed']} | {s['prev_completed']} | "
            f"{s['delayed']} | {s['this_week']} | {s['next_week']} | {s['long_term']} |"
        )
        for b in BUCKETS:
            tot[b] += s[b]
    # 합계 행
    lines.append(
        f"| **합계** | **{len(tasks)}** | **{tot['completed']}** | **{tot['prev_completed']}** | "
        f"**{tot['delayed']}** | **{tot['this_week']}** | **{tot['next_week']}** | **{tot['long_term']}** |"
    )
    lines.append("")

    # ── 종합 평가 ──
    lines.append("## 📝 종합 평가")
    lines.append("")
    total_eval = sum(all_evaluations.values())
    if total_eval > 0:
        lines.append("| 등급 | 건수 | 비율 |")
        lines.append("|---|---|---|")
        grade_labels = {"excellent": "🎖 조기 완료", "good": "🟢 정상", "warning": "🟡 주의", "danger": "🚨 위험", "neutral": "⏸ 중립"}
        for grade in ("excellent", "good", "warning", "danger", "neutral"):
            if all_evaluations.get(grade, 0) > 0:
                cnt = all_evaluations[grade]
                pct = f"{cnt / total_eval * 100:.0f}%"
                lines.append(f"| {grade_labels[grade]} | {cnt} | {pct} |")

        # 종합 한 줄 평가
        danger_cnt = all_evaluations.get("danger", 0)
        warning_cnt = all_evaluations.get("warning", 0)
        good_cnt = all_evaluations.get("good", 0)
        excellent_cnt = all_evaluations.get("excellent", 0)
        total_matters = danger_cnt + warning_cnt + good_cnt + excellent_cnt

        if total_matters == 0:
            overall = "⭐ 평가할 업무가 없습니다."
        else:
            score = (excellent_cnt * 3 + good_cnt * 2 + warning_cnt * 1 + danger_cnt * -1) / max(total_matters, 1)
            if score >= 2.0:
                overall = f"🌟 훌륭합니다! 전반적으로 일정 관리가 잘 이루어졌습니다."
            elif score >= 1.0:
                overall = f"👍 전반적으로 양호합니다. 일부 주의가 필요한 업무가 있습니다."
            elif score >= 0.0:
                overall = f"⚠️ 주의가 필요합니다. 지연된 업무가 있습니다."
            else:
                overall = f"🚨 개선이 시급합니다. 다수의 지연 업무가 있습니다."

        lines.append("")
        lines.append(f"> {overall}")
    lines.append("")

    md_content = "\n".join(lines)

    # ── 파일 저장 ──
    week_label = week_start.replace("-", "") if week_start else "weekly"
    filename = f"{assignee}_{week_label}.md"
    filepath = REPORT_DIR / filename
    filepath.write_text(md_content, encoding="utf-8")

    return {
        "ok": True,
        "assignee": assignee,
        "week_start": week_start,
        "week_end": week_end,
        "report_path": str(filepath),
        "filename": filename,
        "md_content": md_content,
        "stats": {
            "total": len(tasks),
            "projects": len(proj_tasks),
            "no_project": len(no_proj_tasks),
            "completed_this_week": tot["completed"],
            "prev_completed": tot["prev_completed"],
            "delayed": tot["delayed"],
            "this_week": tot["this_week"],
            "next_week": tot["next_week"],
            "long_term": tot["long_term"],
            # 기존 키 호환 — 미완료 업무 총합
            "in_progress": tot["this_week"] + tot["next_week"] + tot["long_term"],
        }
    }


def generate_all_report(payload: dict) -> dict:
    """
    전체(All) 주간리포트 — 경영진 보고용
    
    payload = {
        "assignee": "All",
        "week_start": "2026-06-15",
        "week_end": "2026-06-21",
        "total": 60,
        "tasks": [...],
        "projects": [...],
        "members": ["강경철", "전경표", ...]
    }
    """
    assignee = payload.get("assignee", "All")
    week_start = payload.get("week_start", "")
    week_end = payload.get("week_end", "")
    tasks = payload.get("tasks", [])
    projects = payload.get("projects", [])
    members = payload.get("members", [])

    try:
        ws_date = datetime.strptime(week_start, "%Y-%m-%d").date() if week_start else None
        we_date = datetime.strptime(week_end, "%Y-%m-%d").date() if week_end else None
    except ValueError:
        ws_date = we_date = None

    today = datetime.now(KST).date()
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

    proj_map = {p["id"]: p for p in projects}

    # ── 프로젝트별 + 직원별 그룹화 ──
    # proj_tasks[pid] = {assignee: [tasks]}
    proj_tasks = {}
    no_proj_tasks = []
    for t in tasks:
        pid = t.get("project_id")
        a = t.get("assignee", "미정")
        if pid and pid in proj_map:
            proj_tasks.setdefault(pid, {}).setdefault(a, []).append(t)
        else:
            no_proj_tasks.append(t)

    # ── 직원별 전체 통계 ──
    def _blank_member():
        return {"total": 0, "completed": 0, "prev_completed": 0, "delayed": 0,
                "in_progress": 0,
                "evaluations": {"excellent": 0, "good": 0, "warning": 0, "danger": 0, "neutral": 0}}

    member_stats = {m: _blank_member() for m in members}

    # 분류 + 평가 수집
    all_delayed = []  # 전체 지연 업무 (하이라이트용)
    total_comp = 0
    total_prev = 0
    total_del = 0
    total_prog = 0

    for t in tasks:
        a = t.get("assignee", "미정")

        # 직원 통계
        m = member_stats.get(a)
        if not m:
            m = _blank_member()
            member_stats[a] = m
        m["total"] += 1

        # 개인 리포트와 같은 기준으로 분류한다
        bucket = week_bucket(t, ws_date, we_date, today)
        if bucket == "completed":
            m["completed"] += 1
            total_comp += 1
        elif bucket == "prev_completed":
            # 기준 주 밖에서 끝난 업무 — 진행중으로 세지 않는다
            m["prev_completed"] += 1
            total_prev += 1
        elif bucket == "delayed":
            m["delayed"] += 1
            total_del += 1
            due_date = _parse_date(t.get("due_at"))
            all_delayed.append((t, (today - due_date).days))
        else:
            m["in_progress"] += 1
            total_prog += 1

        # 평가 수집
        ev, grade = evaluate_task(t, ws_date, we_date)
        m["evaluations"][grade] = m["evaluations"].get(grade, 0) + 1

    # ── 마크다운 생성 ──
    lines = []
    lines.append("# 📊 브랜업 주간리포트 (전체)")
    lines.append(f"**기준 주:** {week_start} ~ {week_end}  ")
    lines.append(f"**생성일:** {now_str}  ")
    lines.append(f"**전체:** {len(tasks)}건 | **직원:** {len(members)}명 | **프로젝트:** {len(proj_tasks)}개  ")
    lines.append(f"**✅ 완료:** {total_comp} | **🚨 지연:** {total_del} | **🔄 진행중:** {total_prog} | **📦 이전 완료:** {total_prev}  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 섹션 1: 🚨 긴급 — 지연/위험 업무 ──
    lines.append("## 🚨 긴급: 지연·위험 업무")
    lines.append("")
    if all_delayed:
        lines.append("| # | 제목 | 담당 | 마감 | 지연일 | 평가 |")
        lines.append("|---|---|---|---|---|---|")
        for t, dd in all_delayed:
            num = t.get("display_num", "?")
            title = t.get("title", "")
            a = t.get("assignee", "?")
            due = (t.get("due_at") or "")[:10]
            ev, _ = evaluate_task(t, ws_date, we_date)
            lines.append(f"| #{num} | {title} | {a} | {due} | D+{dd} | {ev} |")
        lines.append("")
        lines.append(f"> ⚠️ 총 **{len(all_delayed)}건**의 지연 업무가 있습니다. 즉시 조치가 필요합니다.")
    else:
        lines.append("*🎉 지연된 업무가 없습니다!*")
    lines.append("")

    # ── 섹션 2: 📁 프로젝트별 현황 ──
    lines.append("## 📁 프로젝트별 현황")
    lines.append("")
    if proj_tasks:
        for pid, assignee_tasks in proj_tasks.items():
            proj = proj_map[pid]
            proj_title = proj.get("title", "이름없음")
            proj_status = proj.get("status", "?")
            proj_start = proj.get("start_date", "")[:10] if proj.get("start_date") else "?"
            proj_end = proj.get("expected_end_date", "")[:10] if proj.get("expected_end_date") else "?"

            # 프로젝트 통계
            p_total = sum(len(v) for v in assignee_tasks.values())
            p_delayed = 0
            for a_tasks in assignee_tasks.values():
                for t in a_tasks:
                    if t.get("status") != "완료":
                        due = t.get("due_at", "")
                        if due:
                            try:
                                d = datetime.strptime(due[:10], "%Y-%m-%d").date()
                                if d < today:
                                    p_delayed += 1
                            except Exception:
                                pass

            lines.append(f"### 📁 {proj_title}")
            lines.append(f"**상태:** {proj_status} | **기간:** {proj_start} ~ {proj_end}  ")
            lines.append(f"**업무:** {p_total}건 | **참여:** {len(assignee_tasks)}명  ")
            if p_delayed > 0:
                lines.append(f"**⚠️ 지연:** {p_delayed}건  ")
            lines.append("")

            lines.append("| 직원 | 전체 | 지연 | 진행중 |")
            lines.append("|---|---|---|---|")
            for a_name, a_tasks in sorted(assignee_tasks.items()):
                a_delayed = 0
                for t in a_tasks:
                    if t.get("status") != "완료":
                        due = t.get("due_at", "")
                        if due:
                            try:
                                d = datetime.strptime(due[:10], "%Y-%m-%d").date()
                                if d < today:
                                    a_delayed += 1
                            except Exception:
                                pass
                a_prog = len(a_tasks) - a_delayed
                a_del_str = f"🚨 {a_delayed}" if a_delayed > 0 else "0"
                lines.append(f"| {a_name} | {len(a_tasks)} | {a_del_str} | {a_prog} |")
            lines.append("")
        lines.append("---")
        lines.append("")

    # ── 섹션 3: 👥 직원별 성과 평가 ──
    lines.append("## 👥 직원별 성과 평가")
    lines.append("")
    lines.append("| 직원 | 전체 | 완료 | 이전 완료 | 지연 | 진행중 | 평가 등급 |")
    lines.append("|---|---|---|---|---|---|---|")

    member_order = sorted(member_stats.items(), key=lambda x: x[1]["evaluations"].get("danger", 0), reverse=True)
    for m_name, m_stat in member_order:
        if m_stat["total"] == 0:
            continue
        evals = m_stat["evaluations"]
        danger = evals.get("danger", 0)
        warning = evals.get("warning", 0)
        good = evals.get("good", 0)
        excellent = evals.get("excellent", 0)

        del_str = f"🚨 {m_stat['delayed']}" if m_stat['delayed'] > 0 else str(m_stat['delayed'])

        # 직원 평가 등급
        total_ev = excellent + good + warning + danger
        if total_ev == 0:
            grade_str = "⏸ 평가불가"
        else:
            score = (excellent * 3 + good * 2 + warning * 1 + danger * -1) / max(total_ev, 1)
            if score >= 2.5:
                grade_str = "🌟 최우수"
            elif score >= 1.5:
                grade_str = "👍 우수"
            elif score >= 0.5:
                grade_str = "⚠️ 주의"
            else:
                grade_str = "🚨 위험"

        lines.append(f"| **{m_name}** | {m_stat['total']} | {m_stat['completed']} | {m_stat.get('prev_completed', 0)} | {del_str} | {m_stat['in_progress']} | {grade_str} |")
    lines.append("")

    # ── 섹션 4: 📊 종합 평가 ──
    lines.append("## 📊 종합 평가")
    lines.append("")

    # 전체 평가 집계
    all_eval = {"excellent": 0, "good": 0, "warning": 0, "danger": 0, "neutral": 0}
    for m_name, m_stat in member_stats.items():
        for k, v in m_stat["evaluations"].items():
            all_eval[k] = all_eval.get(k, 0) + v

    total_eval = sum(all_eval.values())
    if total_eval > 0:
        lines.append("| 등급 | 건수 | 비율 |")
        lines.append("|---|---|---|")
        grade_labels = {"excellent": "🎖 조기 완료", "good": "🟢 정상", "warning": "🟡 주의", "danger": "🚨 위험", "neutral": "⏸ 중립"}
        for grade in ("excellent", "good", "warning", "danger", "neutral"):
            if all_eval.get(grade, 0) > 0:
                cnt = all_eval[grade]
                pct = f"{cnt / total_eval * 100:.0f}%"
                lines.append(f"| {grade_labels[grade]} | {cnt} | {pct} |")

        danger_cnt = all_eval.get("danger", 0)
        warning_cnt = all_eval.get("warning", 0)
        good_cnt = all_eval.get("good", 0)
        excellent_cnt = all_eval.get("excellent", 0)
        total_matters = danger_cnt + warning_cnt + good_cnt + excellent_cnt

        if total_matters == 0:
            overall = "⭐ 평가할 업무가 없습니다."
        else:
            score = (excellent_cnt * 3 + good_cnt * 2 + warning_cnt * 1 + danger_cnt * -1) / max(total_matters, 1)
            if score >= 2.0:
                overall = "🌟 훌륭합니다! 전반적으로 프로젝트 관리가 잘 이루어지고 있습니다."
            elif score >= 1.0:
                overall = "👍 전반적으로 양호합니다. 일부 주의가 필요한 업무가 있습니다."
            elif score >= 0.0:
                overall = "⚠️ 주의가 필요합니다. 지연된 업무에 대한 집중 관리가 요구됩니다."
            else:
                overall = "🚨 개선이 시급합니다. 다수의 지연 업무가 있으며 경영진의 즉각적인 관심이 필요합니다."

        lines.append("")
        lines.append(f"> {overall}")
        lines.append("")

        # 주간 TOP 이슈
        lines.append("### 📌 이번 주 핵심 이슈")
        lines.append("")
        if all_delayed:
            lines.append(f"- 🚨 지연 업무 **{len(all_delayed)}건** — 조속한 대응 필요")
        if danger_cnt > 0:
            lines.append(f"- ⚠️ 평가 '위험' 등급 업무 **{danger_cnt}건**")
        if total_comp > 0:
            lines.append(f"- ✅ 기준 주 완료 업무 **{total_comp}건** — 성과 확인")
        if not all_delayed and danger_cnt == 0:
            lines.append("- 🎉 모든 업무가 정상 진행 중입니다!")

    lines.append("")

    md_content = "\n".join(lines)

    week_label = week_start.replace("-", "") if week_start else "weekly"
    filename = f"전체_{week_label}.md"
    filepath = REPORT_DIR / filename
    filepath.write_text(md_content, encoding="utf-8")

    return {
        "ok": True,
        "assignee": "전체",
        "week_start": week_start,
        "week_end": week_end,
        "report_path": str(filepath),
        "filename": filename,
        "md_content": md_content,
        "stats": {
            "total": len(tasks),
            "members": len(members),
            "projects": len(proj_tasks),
            "completed_this_week": total_comp,
            "delayed": total_del,
            "in_progress": total_prog,
        }
    }


def main():
    parser = argparse.ArgumentParser(description="주간리포트 생성기 v2")
    parser.add_argument("--json", type=str, help="JSON 페이로드 문자열")
    parser.add_argument("--file", type=str, help="JSON 페이로드 파일 경로")
    parser.add_argument("--stdin", action="store_true", help="stdin에서 JSON 읽기")
    args = parser.parse_args()

    payload = None

    if args.json:
        try:
            payload = json.loads(args.json)
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "error": f"JSON 파싱 실패: {e}"}))
            sys.exit(1)
    elif args.file:
        try:
            payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
        except Exception as e:
            print(json.dumps({"ok": False, "error": f"파일 읽기 실패: {e}"}))
            sys.exit(1)
    elif args.stdin:
        try:
            payload = json.loads(sys.stdin.read())
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "error": f"stdin JSON 파싱 실패: {e}"}))
            sys.exit(1)
    else:
        print(json.dumps({"ok": False, "error": "--json, --file, 또는 --stdin 필요"}))
        sys.exit(1)

    if not payload or not payload.get("tasks"):
        week_start_str = (payload or {}).get("week_start", datetime.now(KST).strftime("%Y%m%d"))
        week_label = week_start_str.replace("-", "") if week_start_str else "weekly"
        assignee_name = (payload or {}).get("assignee", "미정")
        filename = f"{assignee_name}_{week_label}.md"
        filepath = REPORT_DIR / filename
        md_content = "# 📊 주간리포트\n\n등록된 업무가 없습니다."
        filepath.write_text(md_content, encoding="utf-8")
        print(json.dumps({
            "ok": True,
            "assignee": assignee_name,
            "md_content": md_content,
            "report_path": str(filepath),
            "filename": filename,
            "stats": {"total": 0, "projects": 0, "no_project": 0, "completed_this_week": 0, "delayed": 0, "in_progress": 0}
        }))
        return

    result = generate_report(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
