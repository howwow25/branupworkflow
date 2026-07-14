#!/usr/bin/env python3
"""
HTML 대시보드 생성기 — 진행중 + 완료(주/월) + 담당자 필터 + 모달 편집 + 에이전트 보드
"""
import sys
import os
import json
from pathlib import Path
from datetime import datetime, timedelta

DATA_DIR = os.environ.get("BRANUP_DATA_DIR",
    str(Path(__file__).parent.parent / "data"))
OUTPUT_PATH = Path(DATA_DIR) / "dashboard.html"
API_PORT = os.environ.get("BRANUP_API_PORT", "8800")
API_BASE = os.environ.get("BRANUP_API_BASE", "")

sys.path.insert(0, str(Path(__file__).parent))
import os as _os_dash
if _os_dash.environ.get("BRANUP_API_URL"):
    from branup_api import get_active_tasks, get_completed_tasks, get_projects
    def get_task_file_counts():
        return {}
    def get_dropzone_tasks():
        return []
else:
    from db import (get_active_tasks, get_completed_tasks, get_projects,
                    get_task_file_counts, get_dropzone_tasks)


def dday(due_str):
    if not due_str: return None
    try:
        from datetime import timezone, timedelta
        KST = timezone(timedelta(hours=9))
        due_date = datetime.strptime(due_str[:10], "%Y-%m-%d").date()
        return (due_date - datetime.now(KST).date()).days
    except Exception:
        return None


# 지연 경과일이 이 값을 넘으면 '장기지연'으로 분류 (D+8 이상)
LONG_DELAY_DAYS = 7


def group_tasks(tasks):
    groups = {"delayed": [], "long_delayed": [], "today": [], "d3": [], "d7": [], "upcoming": [], "no_due": []}
    for t in tasks:
        dd = dday(t.get("due_at"))
        if dd is None:                  groups["no_due"].append((t, None))
        elif dd < -LONG_DELAY_DAYS:     groups["long_delayed"].append((t, dd))
        elif dd < 0:                    groups["delayed"].append((t, dd))
        elif dd == 0:                   groups["today"].append((t, dd))
        elif dd <= 3:                   groups["d3"].append((t, dd))
        elif dd <= 7:                   groups["d7"].append((t, dd))
        else:                           groups["upcoming"].append((t, dd))
    return groups


def dday_label(dd):
    if dd is None: return "미정"
    if dd < 0:     return f"D+{abs(dd)}"
    if dd == 0:    return "D-DAY"
    return f"D-{dd}"


def dday_class(dd):
    if dd is None: return "nodue"
    if dd < 0:     return "delayed"
    if dd == 0:    return "today"
    if dd <= 3:    return "urgent"
    if dd <= 7:    return "soon"
    return "ok"


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def render_card(t, dd, task_lookup=None, project_lookup=None, file_counts=None, extra_cls=""):
    title = esc(t.get("title", ""))
    assignee = esc(t.get("assignee") or "미정")
    due = t.get("due_at", "")
    due_str = due[:10] if due else "미정"
    label = dday_label(dd)
    css = dday_class(dd)
    num = t.get("display_num", "?")
    task_id = t.get("id", "")
    prio = t.get("priority", "중간")
    prio_icon = {"긴급": "🔥", "높음": "⭐", "중간": "", "낮음": "➖"}.get(prio, "")
    prio_html = f'<span class="prio-icon">{prio_icon}</span>' if prio_icon else ""

    # ── 프로젝트 태그 ──
    project_html = ""
    pid = t.get("project_id", "")
    if pid and project_lookup:
        proj = project_lookup.get(pid)
        if proj:
            project_html = f'<span class="project-tag">📁 {esc(proj.get("title", ""))}</span>'

    # ── 연관업무 칩 ──
    related_html = ""
    related = t.get("related_tasks", "").strip()
    if related and task_lookup:
        chips = []
        for rn in related.split(","):
            rn = rn.strip()
            if not rn: continue
            rtask = task_lookup.get(int(rn)) if rn.isdigit() else None
            if rtask:
                rcss = dday_class(dday(rtask.get("due_at")))
                if rtask.get("status") == "완료":
                    rcss = "done"
                chips.append(f'<span class="rel-chip badge-{rcss}" onclick="openRelatedTask({rn},event)" title="#{rn} {esc(rtask.get("title",""))[:20]}">#{rn}</span>')
            else:
                chips.append(f'<span class="rel-chip badge-nodue" onclick="openRelatedTask({rn},event)">#{rn}</span>')
        if chips:
            related_html = '<div class="rel-chips">' + "".join(chips) + '</div>'

    file_html = '<span class="attach-icon" title="첨부파일 있음">📎</span>' if (file_counts and file_counts.get(task_id)) else ""

    cls = f"card {extra_cls}".strip()
    return f"""<div class="{cls}" data-assignee="{assignee}" data-priority="{prio}" data-task-id="{task_id}" onclick="openModal('{task_id}')">
    <span class="dday badge-{css}">#{num}</span>{prio_html}{file_html}{related_html}{project_html}
    <div class="title">{title}</div>
    <div class="meta">
        <span class="dday badge-{css}">{label}</span>
        <span class="assignee">👤 {assignee}</span>
        <span class="due">📅 {due_str}</span>
    </div>
</div>"""


def week_range(w):
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    start = monday - timedelta(weeks=w - 1)
    return start, start + timedelta(days=6)


def month_range(m):
    today = datetime.now().date()
    first = today.replace(day=1)
    for _ in range(m - 1):
        first = (first - timedelta(days=1)).replace(day=1)
    if m == 1:
        return first, today
    next_first = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, next_first - timedelta(days=1)


def group_completed(tasks):
    weeks = {}
    months = {}
    for t in tasks:
        closed = t.get("closed_at", "")
        if not closed: continue
        try:
            closed_date = datetime.strptime(closed[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        for w in range(1, 5):
            ws, we = week_range(w)
            if ws <= closed_date <= we:
                weeks.setdefault(w, []).append((t, closed_date))
                break
        for m in range(1, 5):
            ms, me = month_range(m)
            if ms <= closed_date <= me:
                months.setdefault(m, []).append((t, closed_date))
                break
    return weeks, months


def render_completed_card(t, closed_date, label, task_lookup=None, project_lookup=None, file_counts=None):
    title = esc(t.get("title", ""))
    assignee = esc(t.get("assignee") or "미정")
    closed_str = closed_date.strftime("%m/%d")
    task_id = t.get("id", "")
    prio = t.get("priority", "") or ""
    num = t.get("display_num", "?")
    prio_icon = {"긴급": "🔥", "높음": "⭐", "중간": "", "낮음": "➖"}.get(prio, "")
    prio_html = f'<span class="prio-icon">{prio_icon}</span>' if prio_icon else ""

    # ── 프로젝트 태그 ──
    project_html = ""
    pid = t.get("project_id", "")
    if pid and project_lookup:
        proj = project_lookup.get(pid)
        if proj:
            project_html = f'<span class="project-tag">📁 {esc(proj.get("title", ""))}</span>'

    # ── 연관업무 칩 ──
    related_html = ""
    related = t.get("related_tasks", "").strip()
    if related and task_lookup:
        chips = []
        for rn in related.split(","):
            rn = rn.strip()
            if not rn: continue
            rtask = task_lookup.get(int(rn)) if rn.isdigit() else None
            if rtask:
                rcss = dday_class(dday(rtask.get("due_at")))
                if rtask.get("status") == "완료":
                    rcss = "done"
                chips.append(f'<span class="rel-chip badge-{rcss}" onclick="openRelatedTask({rn},event)" title="#{rn} {esc(rtask.get("title",""))[:20]}">#{rn}</span>')
            else:
                chips.append(f'<span class="rel-chip badge-nodue" onclick="openRelatedTask({rn},event)">#{rn}</span>')
        if chips:
            related_html = '<div class="rel-chips">' + "".join(chips) + '</div>'

    file_html = '<span class="attach-icon" title="첨부파일 있음">📎</span>' if (file_counts and file_counts.get(task_id)) else ""

    return f"""<div class="card done" data-assignee="{assignee}" data-priority="{prio}" data-task-id="{task_id}" onclick="openModal('{task_id}')">
    <span class="dday badge-done">#{num}</span>{prio_html}{file_html}{related_html}{project_html}
    <div class="title">{title}</div>
    <div class="meta">
        <span class="assignee">👤 {assignee}</span>
        <span class="due">✅ {closed_str} 완료</span>
    </div>
</div>"""


def render_gantt(projects, tasks):
    """엑셀 스타일 프로젝트 간트차트 - 2단 헤더(월 병합+일 개별) + 빨간 오늘선"""
    if not projects:
        return ""

    today = datetime.now().date()
    DAY_W = 32
    LABEL_W = 180

    # ── 날짜 범위 (프로젝트 start_date / expected_end_date) ──
    dates_set = set()
    proj_start = None
    proj_end = None
    for p in projects:
        for k in ("start_date", "expected_end_date"):
            v = p.get(k, "")
            if v:
                try:
                    d = datetime.strptime(v[:10], "%Y-%m-%d").date()
                    dates_set.add(d)
                    if k == "start_date" and (proj_start is None or d < proj_start):
                        proj_start = d
                    if k == "expected_end_date" and (proj_end is None or d > proj_end):
                        proj_end = d
                except Exception:
                    pass

    if not dates_set:
        start_date = today - timedelta(days=45)
        end_date = today + timedelta(days=45)
    else:
        if proj_start:
            start_date = proj_start - timedelta(days=2)
        else:
            start_date = min(dates_set) - timedelta(days=3)
        if proj_end:
            end_date = proj_end + timedelta(days=5)
        else:
            end_date = max(dates_set) + timedelta(days=7)
        if today < start_date:
            start_date = today - timedelta(days=5)
        if today > end_date:
            end_date = today + timedelta(days=5)
        span = (end_date - start_date).days
        if span < 90:
            mid = start_date + (end_date - start_date) // 2
            start_date = mid - timedelta(days=45)
            end_date = mid + timedelta(days=45)

    date_list = []
    d = start_date
    while d <= end_date:
        date_list.append(d)
        d += timedelta(days=1)

    total_days = len(date_list)
    total_width = total_days * DAY_W

    # ── 월 헤더 ──
    month_cells = []
    month_colors = ["#1c2533", "#1e2840"]
    mi = 0
    i = 0
    while i < total_days:
        m_key = date_list[i].strftime("%Y-%m")
        j = i
        while j < total_days and date_list[j].strftime("%Y-%m") == m_key:
            j += 1
        span = j - i
        label = f"{date_list[i].year}년 {date_list[i].month}월"
        bg = month_colors[mi % 2]
        month_cells.append(
            f'<div class="tg-month-cell" style="flex:0 0 {span * DAY_W}px;background:{bg}">'
            f'{label}</div>')
        i = j
        mi += 1
    month_row = "".join(month_cells)

    # ── 일 헤더 ──
    day_cells = []
    for dt in date_list:
        cls = "tg-day-cell"
        if dt == today:
            cls += " tg-today-col"
        elif dt.weekday() == 6:
            cls += " tg-sunday"
        elif dt.weekday() == 5:
            cls += " tg-saturday"
        day_cells.append(f'<div class="{cls}">{dt.day}</div>')
    day_row = "".join(day_cells)

    # ── 프로젝트 행 ──
    status_color = {"계획": "#8b949e", "진행": "#58a6ff", "완료": "#3fb950", "지연": "#f85149", "보류": "#484f5a"}
    proj_rows = []
    for p in projects:
        sd_str = p.get("start_date", "")
        ed_str = p.get("expected_end_date", "")
        sd = None
        ed = None
        try:
            if sd_str: sd = datetime.strptime(sd_str[:10], "%Y-%m-%d").date()
            if ed_str: ed = datetime.strptime(ed_str[:10], "%Y-%m-%d").date()
        except Exception:
            pass
        if not sd:
            continue

        left_offset = max(0, (sd - start_date).days) * DAY_W
        if ed:
            bar_width = max(DAY_W * 2, (ed - sd).days * DAY_W + DAY_W)
        else:
            bar_width = max(DAY_W * 2, (today - sd).days * DAY_W + DAY_W)

        color = status_color.get(p.get("status", "계획"), "#8b949e")
        title = p.get("title", "")
        pstatus = p.get("status", "계획")
        pid = p.get("id", "")
        task_count = sum(1 for t in tasks if t.get("project_id") == pid)

        proj_rows.append(f'''<div class="tg-task-row" onclick="filterByProject('{pid}')" ondblclick="openProjectModal('{pid}')" title="{title} · {pstatus} · 업무 {task_count}건">
    <div class="tg-label-cell" title="{title}">📁 {title}</div>
    <div class="tg-bar-area" style="width:{total_width}px">
        <div class="tg-bar" style="left:{left_offset}px;width:{bar_width}px;background:{color};border-radius:6px;opacity:0.85">
            {task_count}건
        </div>
    </div>
</div>''')

    if not proj_rows:
        return ""

    # ── 오늘 라인 ──
    today_line_html = ""
    if start_date <= today <= end_date:
        today_offset = LABEL_W + ((today - start_date).days * DAY_W) + (DAY_W // 2)
        today_str = today.strftime("%m/%d")
        today_line_html = f'<div class="tg-today-line" style="left:{today_offset}px"><span class="tg-today-label">{today_str}</span></div>'

    return f'''<div class="tg-section" id="ganttSection">
    <div class="section-title" style="display:flex;justify-content:space-between;align-items:center">
        <span>📊 프로젝트 <span style="font-weight:400;font-size:12px;color:#8b949e">{start_date} ~ {end_date}</span></span>
        <button class="filter-btn" onclick="openProjectModal()" style="font-size:11px">＋</button>
    </div>
    <div class="tg-container">
        <div class="tg-scroll-area">
            {today_line_html}
            <div class="tg-header-row tg-month-row">
                <div class="tg-label-cell tg-label-header">📁 프로젝트</div>
                {month_row}
            </div>
            <div class="tg-header-row tg-day-row">
                <div class="tg-label-cell tg-label-header"></div>
                {day_row}
            </div>
            {"".join(proj_rows)}
        </div>
    </div>
</div>'''


def generate_task_gantt(tasks, completed, projects=None):
    """엑셀 스타일 업무 간트차트 - 월 병합 헤더 + 일별 칸 + 빨간 오늘선 (일 칸 중앙)"""
    all_ts = tasks + completed
    if not all_ts:
        return '<div class="tg-empty">날짜 정보가 있는 업무가 없습니다</div>'

    today = datetime.now().date()
    DAY_W = 32  # 하루 칸 너비 (px)
    LABEL_W = 180  # 좌측 업무명 너비 (px)

    # ── 프로젝트 시작일·종료예정일도 날짜 범위에 포함 ──
    dates_set = set()
    for t in all_ts:
        for k in ("created_at", "due_at", "closed_at"):
            v = t.get(k, "")
            if v:
                try:
                    dates_set.add(datetime.strptime(v[:10], "%Y-%m-%d").date())
                except Exception:
                    pass

    # 프로젝트 일정 추가
    proj_start = None
    proj_end = None
    if projects:
        for p in projects:
            for k in ("start_date", "expected_end_date"):
                v = p.get(k, "")
                if v:
                    try:
                        d = datetime.strptime(v[:10], "%Y-%m-%d").date()
                        dates_set.add(d)
                        if k == "start_date" and (proj_start is None or d < proj_start):
                            proj_start = d
                        if k == "expected_end_date" and (proj_end is None or d > proj_end):
                            proj_end = d
                    except Exception:
                        pass

    if not dates_set:
        start_date = today - timedelta(days=45)
        end_date = today + timedelta(days=45)
    else:
        # 프로젝트 시작일이 있으면 그걸 기준으로 타임라인 시작
        if proj_start and proj_start < min(dates_set):
            start_date = proj_start - timedelta(days=2)
        else:
            start_date = min(dates_set) - timedelta(days=3)
        # 프로젝트 종료예정일이 있으면 그걸 기준으로 타임라인 종료
        if proj_end and proj_end > max(dates_set):
            end_date = proj_end + timedelta(days=5)
        else:
            end_date = max(dates_set) + timedelta(days=7)
        # 오늘이 범위 밖이면 보정
        if today < start_date:
            start_date = today - timedelta(days=5)
        if today > end_date:
            end_date = today + timedelta(days=5)
        # ── 최소 3달(90일) 범위 보장 ──
        span = (end_date - start_date).days
        if span < 90:
            mid = start_date + (end_date - start_date) // 2
            start_date = mid - timedelta(days=45)
            end_date = mid + timedelta(days=45)

    date_list = []
    d = start_date
    while d <= end_date:
        date_list.append(d)
        d += timedelta(days=1)

    total_days = len(date_list)
    total_width = total_days * DAY_W

    # ── 월 헤더 (병합 - 엑셀 스타일) ──
    month_cells = []
    month_colors = ["#1c2533", "#1e2840"]  # 월별 교차 배경
    mi = 0
    i = 0
    while i < total_days:
        m_key = date_list[i].strftime("%Y-%m")
        j = i
        while j < total_days and date_list[j].strftime("%Y-%m") == m_key:
            j += 1
        span = j - i
        label = f"{date_list[i].year}년 {date_list[i].month}월"
        bg = month_colors[mi % 2]
        month_cells.append(
            f'<div class="tg-month-cell" style="flex:0 0 {span * DAY_W}px;background:{bg}">'
            f'{label}</div>')
        i = j
        mi += 1

    month_row = "".join(month_cells)

    # ── 일 헤더 (엑셀 셀 그리드) ──
    day_cells = []
    for d in date_list:
        cls = "tg-day-cell"
        if d == today:
            cls += " tg-today-col"
        elif d.weekday() == 6:
            cls += " tg-sunday"
        elif d.weekday() == 5:
            cls += " tg-saturday"
        # 오늘은 하이라이트 + 빨간 좌우 보더
        day_cells.append(f'<div class="{cls}">{d.day}</div>')
    day_row = "".join(day_cells)

    # ── 업무 행 ──
    task_rows = []
    for t in all_ts:
        created_str = t.get("created_at", "")
        due_str = t.get("due_at", "")
        closed_str = t.get("closed_at", "")
        status = t.get("status", "진행중")

        s_date = None
        e_date = None

        if created_str:
            try:
                s_date = datetime.strptime(created_str[:10], "%Y-%m-%d").date()
            except Exception:
                pass
        if status == "완료" and closed_str:
            try:
                e_date = datetime.strptime(closed_str[:10], "%Y-%m-%d").date()
            except Exception:
                pass
        elif due_str:
            try:
                e_date = datetime.strptime(due_str[:10], "%Y-%m-%d").date()
            except Exception:
                pass

        if not s_date and not e_date:
            continue
        if not s_date:
            s_date = e_date
        if not e_date:
            e_date = s_date

        if s_date > end_date or e_date < start_date:
            continue

        left_offset = max(0, (s_date - start_date).days) * DAY_W
        bar_width = max(DAY_W, ((min(e_date, end_date) - max(s_date, start_date)).days + 1) * DAY_W)

        dd = (e_date - today).days
        if status == "완료":
            bar_cls = "tg-bar-done"
        elif dd is not None and dd < 0:
            bar_cls = "tg-bar-delayed"
        elif dd is not None and dd == 0:
            bar_cls = "tg-bar-today-due"
        elif dd is not None and dd <= 3:
            bar_cls = "tg-bar-urgent"
        else:
            bar_cls = "tg-bar-normal"

        title = t.get("title", "")
        num = t.get("display_num", "?")
        assignee = (t.get("assignee") or "미정").split(",")[0].strip()
        task_id = t.get("id", "")

        task_rows.append(f'''<div class="tg-task-row" onclick="openModal('{task_id}')">
    <div class="tg-label-cell" title="#{num} {t.get('title','')}">#{num} {title}</div>
    <div class="tg-bar-area" style="width:{total_width}px">
        <div class="tg-bar {bar_cls}" style="left:{left_offset}px;width:{bar_width}px"
             title="#{num} | {assignee} | {s_date} → {e_date}">
            {title}
        </div>
    </div>
</div>''')

    if not task_rows:
        return '<div class="tg-empty">날짜 정보가 있는 업무가 없습니다</div>'

    # ── 오늘 빨간선 (일 칸 중앙) + 날짜 라벨 ──
    today_line_html = ""
    if start_date <= today <= end_date:
        today_offset = LABEL_W + ((today - start_date).days * DAY_W) + (DAY_W // 2)
        today_str = today.strftime("%m/%d")
        today_line_html = f'<div class="tg-today-line" style="left:{today_offset}px"><span class="tg-today-label">{today_str}</span></div>'

    return f'''<div class="tg-section" id="taskGanttView" style="display:none">
    <div class="section-title" style="display:flex;justify-content:space-between;align-items:center">
        <span>📊 업무 간트 <span style="font-weight:400;font-size:12px;color:#8b949e">{start_date} ~ {end_date}</span></span>
        <button class="filter-btn" onclick="switchToView('kanban')" style="font-size:11px">📋 칸반 보기</button>
    </div>
    <div class="tg-container">
        <div class="tg-scroll-area">
            {today_line_html}
            <div class="tg-header-row tg-month-row">
                <div class="tg-label-cell tg-label-header"></div>
                {month_row}
            </div>
            <div class="tg-header-row tg-day-row">
                <div class="tg-label-cell tg-label-header">📋 업무</div>
                {day_row}
            </div>
            {"".join(task_rows)}
        </div>
    </div>
</div>'''


def render():
    tasks = get_active_tasks()
    groups = group_tasks(tasks)
    completed = get_completed_tasks()
    c_weeks, c_months = group_completed(completed)
    projects = get_projects()
    active_projects = [p for p in projects if p.get("status") != "완료"]
    completed_projects = [p for p in projects if p.get("status") == "완료"]
    file_counts = get_task_file_counts()
    dropzone = get_dropzone_tasks()

    total = len(tasks)
    delayed_count = len(groups["delayed"])
    long_delayed_count = len(groups["long_delayed"])
    today_count = len(groups["today"])
    nodue_count = len(groups["no_due"])
    d3_count = len(groups["d3"])
    d7_count = len(groups["d7"])
    upcoming_count = len(groups["upcoming"])
    done_count = len(completed)
    dropzone_count = len(dropzone)

    all_assignees = set()
    for t in tasks:
        for a in (t.get("assignee") or "미정").split(","):
            all_assignees.add(a.strip())
    for t in completed:
        for a in (t.get("assignee") or "미정").split(","):
            all_assignees.add(a.strip())
    sorted_assignees = sorted(all_assignees, key=lambda x: (x == "미정", x == "모두", x))

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── 모든 업무 데이터를 JSON으로 내장 (API 없는 환경에서도 모달 조회 가능) ──
    all_tasks = {t["id"]: {k: t[k] for k in ["id","title","status","summary","feedback","due_at","assignee","priority","created_at","updated_at","closed_at","display_num","related_tasks","project_id"]} for t in tasks + completed + dropzone}
    tasks_json = json.dumps(all_tasks, ensure_ascii=False)

    # ── 프로젝트 데이터 JSON ──
    projects_json = json.dumps({p["id"]: p for p in projects}, ensure_ascii=False)

    # ── display_num → task lookup (연관업무 색상 표시용) ──
    task_lookup = {}
    for t in tasks + completed + dropzone:
        dn = t.get("display_num")
        if dn:
            task_lookup[dn] = t

    # ── project_id → project lookup (카드에 프로젝트명 표시용) ──
    project_lookup = {p["id"]: p for p in projects}

    columns = [
        ("🔥 지연", "delayed", groups["delayed"]),
        ("⬜ 미정", "no_due", groups["no_due"]),
        ("🚨 오늘마감", "today", groups["today"]),
        ("⚠️ D-3", "d3", groups["d3"]),
        ("📋 D-7", "d7", groups["d7"]),
        ("🟢 여유", "upcoming", groups["upcoming"]),
    ]

    # ── 간트차트 ──
    gantt_html = render_gantt(active_projects, tasks)
    task_gantt_html = generate_task_gantt(tasks, completed, projects)

    # ── 프로젝트 필터 칩 ──
    proj_filter_html = '<button class="filter-btn proj active" onclick="filterByProject(null)">📊 전체</button>'
    proj_options = ''
    for p in active_projects:
        title = esc(p.get("title", ""))
        pid = p.get("id", "")
        task_count = sum(1 for t in tasks if t.get("project_id") == pid)
        proj_filter_html += f'<button class="filter-btn proj" onclick="filterByProject(\'{pid}\')" ondblclick="openProjectModal(\'{pid}\')" title="{title} · 업무 {task_count}건 (클릭: 업무 필터 · 더블클릭: 상세)">{title[:10]}{"…" if len(title)>10 else ""} <span class="proj-cnt">{task_count}</span></button>'
        proj_options += f'<option value="{pid}">{esc(title)} ({task_count}건)</option>'

    # ── 완료된 프로젝트 (접이식 섹션) ──
    completed_projects_html = ""
    if completed_projects:
        cp_rows = "".join(
            f'<button class="filter-btn proj-done" onclick="openProjectModal(\'{esc(p.get("id",""))}\')" '
            f'title="{esc(p.get("title",""))} · 완료">'
            f'{esc(p.get("title","")[:10])}{"…" if len(p.get("title","")) > 10 else ""}</button>'
            for p in completed_projects)
        completed_projects_html = (
            '<details class="completed-projects"><summary>✅ 완료된 프로젝트 '
            f'<span class="count">{len(completed_projects)}</span></summary>'
            f'<div class="proj-done-list">{cp_rows}</div></details>')

    col_html = ""
    for title, key, items in columns:
        cards_parts = []
        for t, dd in sorted(items, key=lambda x: x[1] or 999):
            cards_parts.append(render_card(t, dd, task_lookup, project_lookup, file_counts))
        cards = "".join(cards_parts)
        if not cards:
            cards = '<div class="empty">없음</div>'
        col_html += f"""<div class="column" data-col="{key}">
    <div class="col-header">{title} <span class="count">{len(items)}</span></div>
    {cards}
</div>"""

    filter_btns = '<button class="filter-btn urgent" onclick="filterAssignee(\'긴급\')">🔥 긴급</button>'
    filter_btns += '<button class="filter-btn active" onclick="filterAssignee(\'ALL\')">ALL</button>'
    for a in sorted_assignees:
        if a == '모두':
            continue
        filter_btns += f'<button class="filter-btn" onclick="filterAssignee(\'{a}\')">{a}</button>'

    completed_html = ""
    if completed:
        completed_html += '<div class="divider">✅ 완료된 업무</div>'
        week_labels = {1: "W1 · 이번주", 2: "W2 · 지난주", 3: "W3 · 2주전", 4: "W4 · 3주전"}
        has_weeks = any(c_weeks.get(w) for w in range(1, 5))
        if has_weeks:
            completed_html += '<div class="section-title">📅 주 단위</div><div class="board">'
            for w in range(1, 5):
                items = c_weeks.get(w, [])
                cards = "".join(render_completed_card(t, cd, week_labels[w], task_lookup, project_lookup, file_counts) for t, cd in items)
                if not cards:
                    cards = '<div class="empty">없음</div>'
                completed_html += f"""<div class="column" data-col="week-{w}">
    <div class="col-header">{week_labels[w]} <span class="count">{len(items)}</span></div>
    {cards}
</div>"""
            completed_html += '</div>'

        month_labels = {1: "M1 · 이번달", 2: "M2 · 지난달", 3: "M3 · 2달전", 4: "M4 · 3달전"}
        has_months = any(c_months.get(m) for m in range(1, 5))
        if has_months:
            completed_html += '<div class="section-title">📆 월 단위</div><div class="board">'
            for m in range(1, 5):
                items = c_months.get(m, [])
                cards = "".join(render_completed_card(t, cd, month_labels[m], task_lookup, project_lookup, file_counts) for t, cd in items)
                if not cards:
                    cards = '<div class="empty">없음</div>'
                completed_html += f"""<div class="column" data-col="month-{m}">
    <div class="col-header">{month_labels[m]} <span class="count">{len(items)}</span></div>
    {cards}
</div>"""
            completed_html += '</div>'

    if completed_html:
        completed_html = f'<div id="completedSection">{completed_html}</div>'

    # ── 장기지연 (접이식 섹션, 완료된 업무 다음) ──
    long_delayed_html = ""
    if groups["long_delayed"]:
        ld_items = sorted(groups["long_delayed"], key=lambda x: x[1])
        ld_cards = "".join(render_card(t, dd, task_lookup, project_lookup, file_counts) for t, dd in ld_items)
        long_delayed_html = f"""<details class="long-delayed-section" id="longDelayedSection">
<summary>⏳ 장기지연 <span class="count" id="ld-count">{long_delayed_count}</span>
<span class="ld-hint">마감 후 {LONG_DELAY_DAYS}일 초과</span></summary>
<div class="board">
<div class="column" data-col="long_delayed">
    <div class="col-header">⏳ 장기지연 <span class="count">{long_delayed_count}</span></div>
    {ld_cards}
</div>
</div>
</details>"""

    # ── 드랍존 (접이식 섹션, 장기지연 다음) — 연기/보류된 업무 ──
    dropzone_html = ""
    if dropzone:
        dz_cards = "".join(
            render_card(t, dday(t.get("due_at")), task_lookup, project_lookup, file_counts, extra_cls="dz")
            for t in dropzone)
        dropzone_html = f"""<details class="dropzone-section" id="dropzoneSection">
<summary>📥 드랍존 <span class="count" id="dz-count">{dropzone_count}</span>
<span class="dz-hint">연기된 업무 · 마감 집계에서 제외</span></summary>
<div class="board">
<div class="column" data-col="dropzone">
    <div class="col-header">📥 드랍존 <span class="count">{dropzone_count}</span></div>
    {dz_cards}
</div>
</div>
</details>"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>브랜업 대시보드</title>
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<meta http-equiv="refresh" content="600">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #0f1117;
    color: #e1e4e8;
    min-height: 100vh;
    padding-bottom: 80px;
}}
.header {{
    background: linear-gradient(135deg, #1a1c2e 0%, #16181d 100%);
    padding: 24px 32px;
    border-bottom: 1px solid #2a2d3a;
}}
.header h1 {{ font-size: 24px; font-weight: 700; }}
.search-box {{ display: inline-flex; gap: 6px; align-items: center; }}
.search-input {{ background: #0f1117; border: 1px solid #30363d; color: #c9d1d9; border-radius: 6px; padding: 9px 18px; font-size: 20px; width: 330px; outline: none; }}
.search-input:focus {{ border-color: #58a6ff; }}
.search-input::placeholder {{ color: #6e7681; }}
.search-btn, .search-clear {{ background: none; border: 1px solid #30363d; color: #c9d1d9; cursor: pointer; font-size: 22px; padding: 8px 14px; border-radius: 6px; line-height: 1; }}
.search-btn:hover {{ background: #21262d; border-color: #58a6ff; color: #58a6ff; }}
.search-clear:hover {{ background: #21262d; border-color: #da3633; color: #f85149; }}
.card.search-hidden {{ display: none; }}
.attach-icon {{ font-size: 12px; margin-left: 3px; vertical-align: middle; }}
.header .sub {{ color: #8b949e; font-size: 13px; margin-top: 4px; }}
.header .refresh-btn {{ background: none; border: 1px solid #30363d; color: #c9d1d9; cursor: pointer; font-size: 18px; padding: 2px 8px; border-radius: 6px; margin-left: 10px; vertical-align: middle; }}
.header .refresh-btn:hover {{ background: #21262d; border-color: #58a6ff; color: #58a6ff; }}
.filters {{
    display: flex; gap: 8px; padding: 12px 32px;
    background: #16181d; border-bottom: 1px solid #2a2d3a;
    flex-wrap: wrap; align-items: center;
}}
.filter-btn {{
    padding: 6px 16px;
    border-radius: 20px; border: 1px solid #2a2d3a;
    background: #1c1f2a; color: #8b949e;
    font-size: 12px; font-weight: 600;
    cursor: pointer; transition: all 0.2s;
}}
.filter-btn:hover {{ border-color: #58a6ff; color: #e1e4e8; }}
.filter-btn.active {{
    background: #58a6ff; color: #000;
    border-color: #58a6ff;
}}
.filter-btn.urgent {{
    border-color: #da3633; color: #f85149;
}}
.filter-btn.urgent:hover {{ border-color: #f85149; background: rgba(248,81,73,0.1); }}
.filter-btn.urgent.active {{
    background: #da3633; color: #fff; border-color: #da3633;
}}
.stats {{
    display: flex; gap: 16px; padding: 16px 32px;
    background: #16181d; border-bottom: 1px solid #2a2d3a;
    flex-wrap: wrap;
}}
.stat {{
    background: #1c1f2a; border-radius: 8px; padding: 12px 20px;
    min-width: 100px; text-align: center;
}}
.stat .num {{ font-size: 28px; font-weight: 800; color: #58a6ff; }}
.stat .label {{ font-size: 11px; color: #8b949e; margin-top: 2px; text-transform: uppercase; }}
.stat.danger .num {{ color: #f85149; }}
.stat.warn .num {{ color: #d2991d; }}
.stat.done .num {{ color: #3fb950; }}
.stat.drop .num {{ color: #a371f7; }}
/* 통계 카드 클릭 = 해당 카테고리만 보기 */
.stat {{ cursor: pointer; border: 1px solid transparent; transition: background .15s, border-color .15s; }}
.stat:hover {{ background: #232735; border-color: #3a4050; }}
.stat.cat-active {{ border-color: #58a6ff; background: #232b3a; }}
.stat.cat-active .label {{ color: #58a6ff; font-weight: 700; }}
.cat-clear-btn {{
    align-self: center; margin-left: 4px;
    background: none; border: 1px solid #30363d; color: #8b949e;
    border-radius: 6px; padding: 6px 12px; font-size: 12px; cursor: pointer;
}}
.cat-clear-btn:hover {{ border-color: #58a6ff; color: #58a6ff; }}
.weekly-report-btn {{
    display: none;
    padding: 8px 16px;
    background: #238636; color: #fff;
    border: none; border-radius: 8px;
    font-size: 13px; font-weight: 600; cursor: pointer;
    white-space: nowrap;
    transition: background .2s;
}}
.weekly-report-btn:hover {{ background: #2ea043; }}
.weekly-report-btn.active {{ display: inline-block; }}
.board {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 16px;
    padding: 24px 32px;
}}
.column {{
    background: #16181d;
    border-radius: 12px;
    border: 1px solid #2a2d3a;
    overflow: hidden;
}}
.col-header {{
    padding: 12px 16px;
    font-weight: 700; font-size: 14px;
    border-bottom: 1px solid #2a2d3a;
    background: #1c1f2a;
    display: flex; justify-content: space-between; align-items: center;
}}
.count {{
    background: #2a2d3a;
    padding: 2px 10px; border-radius: 10px;
    font-size: 12px; font-weight: 600;
}}
.card {{
    background: #1c1f2a;
    margin: 8px 12px; padding: 14px;
    border-radius: 8px; border: 1px solid #2a2d3a;
    transition: border-color 0.2s, opacity 0.2s;
    cursor: pointer;
}}
.card:hover {{ border-color: #58a6ff; }}
.card.done {{ border-color: #1a3a2a; }}
.card.done:hover {{ border-color: #3fb950; }}
.card.hidden {{ display: none; }}
.card .title {{
    font-size: 13px; line-height: 1.5; margin: 8px 0; color: #e1e4e8;
}}
.rel-chips {{
    display: inline-flex; gap: 3px; margin-left: auto; float: right;
    flex-wrap: wrap; max-width: 50%;
}}
.rel-chip {{
    display: inline-block; padding: 1px 6px; border-radius: 8px;
    font-size: 10px; font-weight: 700; cursor: pointer;
    opacity: 0.85; transition: opacity 0.15s;
}}
.rel-chip:hover {{ opacity: 1; }}
.card .meta {{
    display: flex; justify-content: space-between;
    font-size: 11px; color: #8b949e;
    margin-top: 8px; padding-top: 8px; border-top: 1px solid #2a2d3a;
}}
.empty {{
    padding: 32px; text-align: center; color: #484f5a; font-size: 13px;
}}
.badge-delayed {{ background: #f85149; color: #fff; }}
.badge-today {{ background: #f0883e; color: #fff; }}
.badge-urgent {{ background: #d2991d; color: #000; }}
.badge-soon {{ background: #3fb950; color: #000; }}
.badge-ok {{ background: #58a6ff; color: #000; }}
.badge-nodue {{ background: #484f5a; color: #ccc; }}
.badge-done {{ background: #1a3a2a; color: #3fb950; }}
.prio-icon {{
    font-size: 14px; margin-left: 4px;
    vertical-align: middle;
}}
.project-tag {{
    display: inline-block; margin-left: 6px;
    padding: 1px 6px; border-radius: 4px;
    font-size: 10px; font-weight: 600;
    background: rgba(63,185,80,0.12); color: #3fb950;
    border: 1px solid rgba(63,185,80,0.2);
    vertical-align: middle; max-width: 140px;
    overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
}}
.dday {{
    display: inline-block; padding: 2px 8px;
    border-radius: 4px; font-size: 11px;
    font-weight: 700; letter-spacing: 0.5px;
}}
.divider {{
    padding: 24px 32px 0;
    font-size: 20px; font-weight: 800;
    color: #3fb950;
    border-top: 2px solid #1a3a2a;
    margin-top: 8px;
}}
.section-title {{
    padding: 16px 32px 0;
    font-size: 13px; color: #8b949e;
    font-weight: 600; letter-spacing: 1px;
}}
.footer {{
    text-align: center; padding: 24px;
    color: #484f5a; font-size: 11px;
}}
/* ── 모달 ── */
.modal-overlay {{
    display: none;
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.7);
    z-index: 1000;
    justify-content: center; align-items: center;
}}
.modal-overlay.active {{ display: flex; }}
.modal {{
    background: #16181d;
    border: 1px solid #2a2d3a;
    border-radius: 16px;
    width: 90%; max-width: 520px;
    max-height: 85vh; overflow-y: auto;
    box-shadow: 0 20px 60px rgba(0,0,0,0.5);
}}
.modal-header {{
    padding: 20px 24px 12px;
    display: flex; justify-content: space-between; align-items: flex-start;
}}
.modal-header h2 {{ font-size: 18px; color: #e1e4e8; }}
.modal-close {{
    background: none; border: none; color: #8b949e;
    font-size: 24px; cursor: pointer; padding: 0 4px;
    line-height: 1;
}}
.modal-close:hover {{ color: #f85149; }}
.modal-body {{ padding: 0 24px 24px; }}
.modal-field {{
    margin-bottom: 16px;
}}
.modal-field label {{
    display: block; font-size: 11px; color: #8b949e;
    margin-bottom: 6px; text-transform: uppercase;
    letter-spacing: 0.5px;
}}
.modal-field input, .modal-field textarea, .modal-field select {{
    width: 100%; padding: 10px 14px;
    background: #0f1117;
    border: 1px solid #2a2d3a;
    border-radius: 8px; color: #e1e4e8;
    font-size: 14px; font-family: inherit;
}}
.modal-field input:focus, .modal-field textarea:focus, .modal-field select:focus {{
    outline: none; border-color: #58a6ff;
}}
.modal-field select[multiple] {{
    min-height: 110px;
    padding: 6px 8px;
}}
.modal-field select[multiple] option {{
    padding: 5px 10px; border-radius: 4px; margin: 1px 0;
}}
.modal-field select[multiple] option:checked {{
    background: linear-gradient(135deg, #1f6feb, #58a6ff);
    color: #fff;
}}
.modal-field textarea {{
    resize: vertical; min-height: 80px;
}}
/* ── 파일 첨부 ── */
.file-dropzone {{
    border: 2px dashed #2a2d3a; border-radius: 8px;
    padding: 16px; text-align: center;
    cursor: pointer; transition: border-color .2s;
    background: #0d1117; margin-bottom: 10px;
}}
.file-dropzone:hover, .file-dropzone.dragover {{
    border-color: #1f6feb; background: #161b22;
}}
.file-dropzone span {{
    color: #8b949e; font-size: 12px;
}}
.file-list {{ display: flex; flex-direction: column; gap: 6px; }}
.file-item {{
    display: flex; align-items: center; gap: 8px;
    background: #0f1117; border: 1px solid #1a2a3a;
    border-radius: 6px; padding: 8px 10px;
}}
.file-icon {{ font-size: 16px; flex-shrink: 0; }}
.file-name {{
    flex: 1; color: #58a6ff; font-size: 12px;
    text-decoration: none; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap;
}}
.file-name:hover {{ text-decoration: underline; }}
.file-size {{
    color: #8b949e; font-size: 11px; flex-shrink: 0;
}}
.file-del {{
    color: #f85149; cursor: pointer; font-size: 14px;
    flex-shrink: 0; padding: 2px 6px; border-radius: 4px;
}}
.file-del:hover {{ background: #3a1a1a; }}
.file-empty {{
    color: #484f5a; font-size: 12px; text-align: center;
    padding: 10px;
}}
.file-limit-info {{
    color: #484f5a; font-size: 11px; margin-top: 6px;
    text-align: right;
}}
.modal-actions {{
    display: flex; gap: 10px; margin-top: 20px;
    flex-wrap: wrap;
}}
.modal-actions button {{
    padding: 10px 20px; border-radius: 8px;
    font-size: 13px; font-weight: 600;
    cursor: pointer; border: 1px solid #2a2d3a;
    transition: all 0.15s;
}}
.btn-save {{
    background: #238636; color: #fff; border-color: #238636;
}}
.btn-save:hover {{ background: #2ea043; }}
.btn-complete {{
    background: #1a3a2a; color: #3fb950; border-color: #3fb950;
}}
.btn-complete:hover {{ background: #1f4a33; }}
.btn-delete {{
    background: #3a1a1a; color: #f85149; border-color: #f85149;
}}
.btn-delete:hover {{ background: #4a1f1f; }}
.btn-uncomplete {{
    background: #1a2a3a; color: #58a6ff; border-color: #58a6ff;
}}
.btn-uncomplete:hover {{ background: #1f344a; }}
.btn-cancel {{
    background: #1c1f2a; color: #8b949e;
}}
.btn-cancel:hover {{ color: #e1e4e8; }}
.btn-save.disabled, .btn-complete.disabled, .btn-delete.disabled, .btn-uncomplete.disabled {{
    filter: grayscale(1);
    opacity: 0.35;
    cursor: not-allowed;
    pointer-events: none;
}}
.modal-status {{
    font-size: 12px; color: #8b949e; margin-bottom: 16px;
    padding: 8px 12px; background: #1c1f2a; border-radius: 8px;
}}
.modal-status strong {{ color: #e1e4e8; }}
.toast {{
    position: fixed; bottom: 100px; left: 50%; transform: translateX(-50%);
    background: #238636; color: #fff; padding: 12px 24px;
    border-radius: 8px; font-size: 13px; font-weight: 600;
    z-index: 2000; opacity: 0; transition: opacity 0.3s;
    pointer-events: none;
}}
.toast.show {{ opacity: 1; }}
.toast.error {{ background: #f85149; }}

/* ── 생성 FAB ── */
.create-fab {{
    position: fixed; bottom: 96px; right: 24px;
    width: 56px; height: 56px;
    border-radius: 50%; border: none;
    background: linear-gradient(135deg, #3fb950, #238636);
    color: #fff; font-size: 24px; font-weight: 700;
    cursor: pointer; z-index: 500;
    box-shadow: 0 4px 20px rgba(63,185,80,0.3);
    transition: all 0.2s;
    display: flex; align-items: center; justify-content: center;
}}
.create-fab:hover {{
    transform: scale(1.08);
    box-shadow: 0 6px 28px rgba(63,185,80,0.5);
}}
.create-fab.active {{
    background: #f85149; transform: rotate(45deg);
}}
.create-menu {{
    position: fixed; bottom: 160px; right: 24px;
    display: flex; flex-direction: column; gap: 8px;
    z-index: 499; opacity: 0; pointer-events: none;
    transition: opacity 0.2s;
}}
.create-menu.open {{
    opacity: 1; pointer-events: auto;
}}
.create-menu button {{
    padding: 10px 20px; border-radius: 8px;
    border: 1px solid #2a2d3a;
    background: #1c1f2a; color: #e1e4e8;
    font-size: 13px; font-weight: 600;
    cursor: pointer; text-align: left;
    white-space: nowrap; transition: all 0.15s;
}}
.create-menu button:hover {{
    border-color: #58a6ff; background: #1f2937;
}}

/* ── 에이전트 보드 ── */
.agent-fab {{
    position: fixed; bottom: 24px; right: 24px;
    width: 56px; height: 56px;
    border-radius: 50%; border: none;
    background: linear-gradient(135deg, #58a6ff, #3fb950);
    color: #fff; font-size: 26px;
    cursor: pointer; z-index: 500;
    box-shadow: 0 4px 20px rgba(88,166,255,0.3);
    transition: all 0.2s;
    display: flex; align-items: center; justify-content: center;
}}
.agent-fab:hover {{
    transform: scale(1.08);
    box-shadow: 0 6px 28px rgba(88,166,255,0.5);
}}
.agent-fab.active {{
    background: #f85149;
    transform: rotate(45deg);
}}
.agent-panel {{
    position: fixed; bottom: 0; left: 0; right: 0;
    background: #16181d;
    border-top: 2px solid #2a2d3a;
    z-index: 600;
    max-height: 0;
    overflow: hidden;
    transition: max-height 0.3s ease;
    display: flex; flex-direction: column;
}}
.agent-panel.open {{
    max-height: 420px;
}}
.agent-messages {{
    flex: 1; overflow-y: auto;
    padding: 16px 20px;
    display: flex; flex-direction: column;
    gap: 10px;
    min-height: 60px;
    max-height: 280px;
}}
.agent-msg {{
    padding: 10px 14px; border-radius: 12px;
    font-size: 13px; line-height: 1.6;
    max-width: 92%;
    animation: fadeIn 0.2s ease;
}}
@keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: translateY(0); }} }}
.agent-msg.user {{
    align-self: flex-end;
    background: #1f6feb; color: #fff;
    border-bottom-right-radius: 4px;
}}
.agent-msg.bot {{
    align-self: flex-start;
    background: #1c1f2a; color: #e1e4e8;
    border-bottom-left-radius: 4px;
    white-space: pre-wrap;
    word-break: break-word;
}}
.agent-msg.bot strong {{ color: #58a6ff; }}
.agent-input-area {{
    display: flex; gap: 8px; padding: 12px 20px;
    border-top: 1px solid #2a2d3a;
    background: #0f1117;
}}
.agent-input {{
    flex: 1; padding: 10px 14px;
    background: #1c1f2a; border: 1px solid #2a2d3a;
    border-radius: 8px; color: #e1e4e8;
    font-size: 14px; font-family: inherit;
}}
.agent-input:focus {{ outline: none; border-color: #58a6ff; }}
.agent-input::placeholder {{ color: #484f5a; }}
.agent-send {{
    padding: 10px 18px;
    background: #238636; color: #fff;
    border: none; border-radius: 8px;
    font-size: 14px; font-weight: 600;
    cursor: pointer; transition: all 0.15s;
}}
.agent-send:hover {{ background: #2ea043; }}
.agent-chips {{
    display: flex; gap: 6px; padding: 8px 20px 12px;
    flex-wrap: wrap;
}}
.agent-chip {{
    padding: 5px 12px;
    border-radius: 14px; border: 1px solid #2a2d3a;
    background: #1c1f2a; color: #8b949e;
    font-size: 11px; cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;
}}
.agent-chip:hover {{
    border-color: #58a6ff; color: #e1e4e8;
    background: #1f2937;
}}
.agent-typing {{
    align-self: flex-start;
    color: #484f5a; font-size: 12px;
    padding: 8px 14px;
}}
/* ── 간트차트 ── */
.gantt-section {{
    margin: 16px 32px 0; background: #16181d;
    border-radius: 12px; border: 1px solid #2a2d3a;
    overflow: hidden;
}}
.gantt-header {{
    padding: 12px 16px; display: flex;
    justify-content: space-between; align-items: center;
    border-bottom: 1px solid #2a2d3a;
}}
.gantt-title {{ font-weight: 700; font-size: 14px; color: #e1e4e8; }}
.gantt-refresh {{
    background: #1f6feb; color: #fff; border: none;
    border-radius: 6px; padding: 4px 12px;
    cursor: pointer; font-size: 14px; font-weight: 700;
}}
.gantt-refresh:hover {{ background: #388bfd; }}
.gantt-chart {{
    padding: 8px 16px; position: relative;
    min-height: 40px;
}}
.gantt-grid {{ position: absolute; top: 0; left: 0; right: 0; bottom: 0; pointer-events: none; z-index: 0; }}
.gantt-grid-week {{ position: absolute; top: 0; bottom: 0; }}
.gantt-today-line {{
    position: absolute; top: 0; bottom: 0;
    width: 3px; background: #f85149;
    opacity: 0.9; z-index: 15; pointer-events: none;
    box-shadow: 0 0 8px rgba(248,81,73,0.5);
}}
.gantt-today-label {{
    position: absolute; top: -16px; left: -14px;
    font-size: 10px; color: #f85149; font-weight: 800;
    white-space: nowrap;
    background: #0d1117; padding: 1px 4px; border-radius: 3px;
    border: 1px solid rgba(248,81,73,0.3);
}}
.gantt-ticks {{ position: relative; height: 40px; z-index: 1; margin-bottom: 4px; }}
.gantt-tick-day {{ position: absolute; top: 0; height: 100%; width: 1px; background: #21262d; z-index: 0; }}
.gantt-tick-day.month {{ background: #30363d; }}
.gantt-tick-month-label {{ position: absolute; top: 0; transform: translateX(-8px); z-index: 2; font-size: 11px; color: #58a6ff; font-weight: 700; }}
.gantt-tick-date-label {{ position: absolute; top: 18px; transform: translateX(-50%); z-index: 2; font-size: 9px; color: #8b949e; white-space: nowrap; }}
.gantt-row {{
    display: flex; align-items: center; gap: 8px;
    padding: 4px 0; cursor: pointer;
}}
.gantt-label {{
    width: auto; min-width: 120px; max-width: 200px;
    font-size: 12px; color: #ffffff;
    text-align: right; flex-shrink: 0;
    overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
}}
.gantt-count {{
    font-size: 10px; color: #484f5a;
    background: #1c1f2a; border-radius: 4px;
    padding: 0 4px; min-width: 18px; text-align: center;
}}
.gantt-bar-wrap {{
    flex: 1; height: 18px; position: relative;
    background: #0f1117; border-radius: 4px;
}}
.gantt-bar {{
    position: absolute; top: 2px; height: 14px;
    border-radius: 3px; min-width: 6px;
    transition: opacity 0.15s;
}}
.gantt-range {{
    display: flex; justify-content: space-between;
    padding: 4px 16px 8px; font-size: 10px; color: #484f5a;
    border-top: 1px solid #2a2d3a;
}}
/* ── 업무 간트차트 (tg-*) ── */
.tg-section {{
    padding: 0 0 24px 0;
}}
.tg-container {{
    overflow-x: auto;
    margin: 12px 32px 0;
    border: 1px solid #30363d;
    border-radius: 12px;
    background: #0f1117;
    max-height: 70vh;
}}
.tg-scroll-area {{
    position: relative;
    display: inline-block;
    min-width: 100%;
}}
.tg-header-row {{
    display: flex; flex-wrap: nowrap;
    position: sticky; z-index: 10;
    background: #16181d;
}}
.tg-month-row {{
    top: 0; z-index: 11;
    border-bottom: 2px solid #30363d;
    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}}
.tg-day-row {{
    top: 28px; z-index: 10;
    border-bottom: 2px solid #30363d;
}}
.tg-label-cell {{
    flex: 0 0 180px;
    position: sticky; left: 0;
    background: #1c1f2a; z-index: 12;
    padding: 6px 12px;
    font-size: 13px; font-weight: 600; color: #e1e4e8;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    border-right: 2px solid #30363d;
    display: flex; align-items: center;
}}
.tg-label-header {{
    background: #16181d; z-index: 13;
    font-size: 12px; color: #8b949e;
    justify-content: center;
    border-bottom: 2px solid #30363d;
}}
.tg-month-cell {{
    flex: 0 0 auto;
    padding: 5px 0; text-align: center;
    font-size: 12px; font-weight: 700; color: #c9d1d9;
    border-right: 1px solid #21262d;
    white-space: nowrap;
    text-shadow: 0 1px 2px rgba(0,0,0,0.5);
}}
.tg-day-cell {{
    flex: 0 0 32px;
    padding: 2px 0; text-align: center;
    font-size: 10px; font-weight: 500; color: #8b949e;
    border-right: 1px solid #21262d;
    background: #16181d; line-height: 20px;
    transition: background 0.15s;
}}
.tg-day-cell.tg-today-col {{
    background: rgba(248,81,73,0.12);
    color: #f85149; font-weight: 800;
    border-left: 1px solid rgba(248,81,73,0.3);
    border-right: 1px solid rgba(248,81,73,0.3);
    box-shadow: inset 0 0 8px rgba(248,81,73,0.08);
}}
.tg-day-cell.tg-sunday {{ color: #484f5a; border-right-color: #1c2128; }}
.tg-day-cell.tg-saturday {{ color: #3a4a6a; }}
.tg-today-line {{
    position: absolute; top: 0; bottom: 0;
    width: 3px; background: #f85149;
    z-index: 20; pointer-events: none;
    box-shadow: 0 0 10px rgba(248,81,73,0.5);
}}
.tg-today-line::before {{
    content: '▼';
    position: absolute; top: -2px; left: -5px;
    font-size: 10px; color: #f85149; line-height: 1;
}}
.tg-today-label {{
    position: absolute; top: -16px; left: -14px;
    font-size: 10px; color: #f85149; font-weight: 800;
    white-space: nowrap;
    background: #0f1117; padding: 1px 4px; border-radius: 3px;
    border: 1px solid rgba(248,81,73,0.3);
}}
.tg-task-row {{
    display: flex; flex-wrap: nowrap;
    border-bottom: 1px solid #202433;
    cursor: pointer;
}}
.tg-task-row .tg-label-cell {{
    background: #0f1117;
    font-size: 12px; font-weight: 400; color: #c9d1d9;
    overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
}}
.tg-bar-area {{
    position: relative;
    min-height: 32px;
}}
.tg-bar {{
    position: absolute; top: 4px; height: 24px;
    border-radius: 4px; padding: 0 8px;
    font-size: 10px; line-height: 24px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    font-weight: 600; cursor: pointer;
    transition: filter 0.15s, transform 0.1s;
    color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.4);
}}
.tg-bar-normal {{ background: #1f6feb; }}
.tg-bar-done {{ background: #238636; opacity: 0.7; }}
.tg-bar-delayed {{ background: #da3633; }}
.tg-bar-today-due {{ background: #d2991d; }}
.tg-bar-urgent {{ background: #f0883e; }}
.tg-empty {{
    padding: 40px; text-align: center;
    color: #484f5a; font-size: 14px;
}}
/* ── 뷰 토글 ── */
.view-toggle {{
    display: flex; gap: 4px;
    padding: 0 32px; margin-top: 12px;
}}
.view-toggle-btn {{
    padding: 6px 16px;
    border-radius: 8px 8px 0 0;
    border: 1px solid #2a2d3a; border-bottom: none;
    background: #1c1f2a; color: #8b949e;
    font-size: 12px; font-weight: 600;
    cursor: pointer; transition: all 0.15s;
}}
.view-toggle-btn:hover {{ color: #e1e4e8; background: #1f2937; }}
.view-toggle-btn.active {{
    background: #16181d; color: #58a6ff;
    border-color: #2a2d3a;
}}
/* ── 프로젝트 필터 ── */
.filter-btn.proj {{ border-color: #3fb950; color: #3fb950; }}
.filter-btn.proj:hover {{ border-color: #3fb950; background: rgba(63,185,80,0.1); }}
.filter-btn.proj.active {{ background: #3fb950; color: #000; border-color: #3fb950; }}
.proj-cnt {{ font-size: 9px; opacity: 0.7; }}
/* ── 프로젝트 모달 ── */
.project-modal .modal-body label {{ font-size: 11px; color: #8b949e; display: block; margin-bottom: 4px; }}
.project-modal input, .project-modal textarea, .project-modal select {{
    width: 100%; padding: 8px 12px; margin-bottom: 12px;
    background: #0f1117; border: 1px solid #2a2d3a;
    border-radius: 6px; color: #e1e4e8; font-size: 13px;
}}
.project-modal input:focus, .project-modal textarea:focus, .project-modal select:focus {{
    outline: none; border-color: #58a6ff;
}}
.project-modal .btn-row {{
    display: flex; gap: 8px; margin-top: 12px;
}}
.project-modal .btn-row button {{
    padding: 8px 16px; border-radius: 6px;
    font-size: 13px; font-weight: 600; cursor: pointer;
    border: 1px solid #2a2d3a;
}}
.project-modal .btn-primary {{
    background: #238636; color: #fff; border-color: #238636;
}}
.project-modal .btn-primary:hover {{ background: #2ea043; }}
.project-modal .btn-danger {{
    background: #3a1a1a; color: #f85149; border-color: #f85149;
}}
.project-modal .btn-danger:hover {{ background: #4a1f1f; }}
.completed-projects {{
    margin: 8px 0 16px; border: 1px solid #2a2d3a; border-radius: 8px;
    background: #11141c; padding: 4px 12px;
}}
.completed-projects summary {{
    cursor: pointer; padding: 8px 4px; font-size: 13px; font-weight: 600;
    color: #8b949e; list-style: none; user-select: none;
}}
.completed-projects summary::-webkit-details-marker {{ display: none; }}
.completed-projects summary:hover {{ color: #e1e4e8; }}
.completed-projects .count {{
    background: #2a2d3a; color: #8b949e; border-radius: 10px;
    padding: 1px 8px; font-size: 11px; margin-left: 4px;
}}
.proj-done-list {{ display: flex; flex-wrap: wrap; gap: 8px; padding: 4px 0 10px; }}
/* 완료된 프로젝트 칩 — 프로젝트 리스트 칩과 동일한 라운드/외곽선, 색만 회색(완료/보관) */
.filter-btn.proj-done {{ border-color: #8b949e; color: #8b949e; }}
.filter-btn.proj-done:hover {{ border-color: #8b949e; background: rgba(139,148,158,0.12); }}
/* 장기지연 — 완료된 업무 다음에 오는 접이식 섹션 */
.long-delayed-section {{
    margin: 16px 32px 0; border: 1px solid #5a2a2a; border-radius: 8px;
    background: #17121380;
}}
.long-delayed-section summary {{
    cursor: pointer; padding: 12px 16px; font-size: 15px; font-weight: 700;
    color: #d98b86; list-style: none; user-select: none;
}}
.long-delayed-section summary::-webkit-details-marker {{ display: none; }}
.long-delayed-section summary:hover {{ color: #f85149; }}
.long-delayed-section summary::before {{ content: '▶ '; font-size: 11px; }}
.long-delayed-section[open] summary::before {{ content: '▼ '; }}
.long-delayed-section .count {{
    background: #5a2a2a; color: #f0b0ac; border-radius: 10px;
    padding: 1px 8px; font-size: 11px; margin-left: 4px;
}}
.long-delayed-section .ld-hint {{ font-size: 11px; font-weight: 400; color: #8b949e; margin-left: 8px; }}
.long-delayed-section .board {{ padding: 0 16px 16px; }}
/* 드랍존 — 연기(보류)된 업무, 장기지연 다음에 오는 접이식 섹션 */
.dropzone-section {{
    margin: 16px 32px 0; border: 1px solid #4a3a6a; border-radius: 8px;
    background: #16121f80;
}}
.dropzone-section summary {{
    cursor: pointer; padding: 12px 16px; font-size: 15px; font-weight: 700;
    color: #a371f7; list-style: none; user-select: none;
}}
.dropzone-section summary::-webkit-details-marker {{ display: none; }}
.dropzone-section summary:hover {{ color: #c297ff; }}
.dropzone-section summary::before {{ content: '▶ '; font-size: 11px; }}
.dropzone-section[open] summary::before {{ content: '▼ '; }}
.dropzone-section .count {{
    background: #3a2a5a; color: #c297ff; border-radius: 10px;
    padding: 1px 8px; font-size: 11px; margin-left: 4px;
}}
.dropzone-section .dz-hint {{ font-size: 11px; font-weight: 400; color: #8b949e; margin-left: 8px; }}
.dropzone-section .board {{ padding: 0 16px 16px; }}
.card.dz {{ opacity: .75; }}
.card.dz:hover {{ opacity: 1; }}
.btn-dropzone {{
    padding: 10px 18px; background: #4a3a6a; color: #d7c3ff;
    border: none; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer;
}}
.btn-dropzone:hover {{ background: #5c4880; }}
.btn-dropzone.disabled {{ opacity: .4; cursor: not-allowed; }}
</style>
</head>
<body>
<div class="header">
    <h1>📊 브랜업 대시보드 <button class="refresh-btn" onclick="forceRefresh()" title="강력 새로고침">🔄</button></h1>
    <div class="sub">마지막 갱신: {now_str} | 진행 <span id="hdr-active">{total}</span>건 · 완료 <span id="hdr-done">{done_count}</span>건</div>
</div>
<div class="filters">{filter_btns}<button class="weekly-report-btn" id="weeklyReportBtn" onclick="requestWeeklyReport()" title="선택 직원의 주간리포트 생성">📊 주간리포트</button><span class="search-box"><input type="text" id="searchInput" class="search-input" placeholder="업무 검색..." onkeydown="if(event.key==='Enter')runSearch()" oninput="if(!this.value)clearSearch()"><button class="search-btn" onclick="runSearch()" title="검색">🔍</button><button class="search-clear" onclick="clearSearch()" title="검색 해제" style="display:none">✕</button></span></div>
<div class="stats" id="statsRow">
    <div class="stat danger" id="stat-delayed" onclick="filterCategory('delayed')" title="지연 업무만 보기">
        <div class="num">{delayed_count}</div>
        <div class="label">지연</div>
    </div>
    <div class="stat warn" id="stat-nodue" onclick="filterCategory('no_due')" title="마감 미정 업무만 보기">
        <div class="num">{nodue_count}</div>
        <div class="label">미정</div>
    </div>
    <div class="stat" id="stat-today" onclick="filterCategory('today')" title="오늘 마감 업무만 보기">
        <div class="num">{today_count}</div>
        <div class="label">오늘마감</div>
    </div>
    <div class="stat" id="stat-d3" onclick="filterCategory('d3')" title="D-3 업무만 보기">
        <div class="num">{d3_count}</div>
        <div class="label">D-3</div>
    </div>
    <div class="stat" id="stat-d7" onclick="filterCategory('d7')" title="D-7 업무만 보기">
        <div class="num">{d7_count}</div>
        <div class="label">D-7</div>
    </div>
    <div class="stat" id="stat-upcoming" onclick="filterCategory('upcoming')" title="여유 업무만 보기">
        <div class="num">{upcoming_count}</div>
        <div class="label">여유</div>
    </div>
    <div class="stat done" id="stat-done" onclick="filterCategory('done')" title="완료된 업무만 보기">
        <div class="num">{done_count}</div>
        <div class="label">완료</div>
    </div>
    <div class="stat danger" id="stat-longdelayed" onclick="filterCategory('long_delayed')" title="장기지연 업무만 보기">
        <div class="num">{long_delayed_count}</div>
        <div class="label">장기지연</div>
    </div>
    <div class="stat drop" id="stat-dropzone" onclick="filterCategory('dropzone')" title="드랍존(연기) 업무만 보기">
        <div class="num">{dropzone_count}</div>
        <div class="label">드랍존</div>
    </div>
    <button class="cat-clear-btn" id="catClearBtn" onclick="filterCategory(null)" style="display:none">✕ 전체 보기</button>
</div>
<div class="view-toggle">
    <button class="view-toggle-btn active" id="btnKanban" onclick="switchToView('kanban')">📋 칸반</button>
    <button class="view-toggle-btn" id="btnGantt" onclick="switchToView('gantt')">📊 업무 간트</button>
</div>
<div id="kanbanView">
{gantt_html}
<div class="filters" id="projFilters">{proj_filter_html}</div>
{completed_projects_html}
<div class="board">
{col_html}
</div>
{completed_html}
{long_delayed_html}
{dropzone_html}
</div><!-- #kanbanView -->
{task_gantt_html}

<!-- ── 모달 ── -->
<div class="modal-overlay" id="modalOverlay" onclick="closeModal(event)"></div>
<div class="toast" id="toast"></div>

<!-- ── 에이전트 보드 ── -->
<button class="create-fab" id="createFab" onclick="toggleCreateMenu()" title="새로 만들기">＋</button>
<div class="create-menu" id="createMenu">
    <button onclick="openCreateModal();toggleCreateMenu()">📋 새 업무</button>
    <button onclick="openProjectModal();toggleCreateMenu()">📊 새 프로젝트</button>
</div>
<button class="agent-fab" id="agentFab" onclick="toggleAgent()" title="에이전트 보드">🤖</button>
<div class="agent-panel" id="agentPanel">
    <div class="agent-messages" id="agentMessages">
        <div class="agent-msg bot">🤖 무엇을 도와드릴까요?
<span style="color:#8b949e;font-size:11px">업무 등록 · 조회 · 완료 · 삭제</span></div>
    </div>
    <div class="agent-chips" id="agentChips">
        <span class="agent-chip" onclick="sendAgent('전체 업무')">📋 전체 업무</span>
        <span class="agent-chip" onclick="quickRegister()">➕ 등록</span>
        <span class="agent-chip" onclick="sendAgent('5번 완료')" style="display:none" id="chipComplete">✅ 완료예시</span>
    </div>
    <div class="agent-input-area">
        <input type="text" class="agent-input" id="agentInput"
               placeholder="예: 업무지시 제목:리서치 담당:전경표 마감:2026-06-15"
               onkeydown="if(event.key==='Enter')sendAgent()">
        <button class="agent-send" onclick="sendAgent()">전송</button>
    </div>
</div>

<div class="footer">브랜업 대시보드 · {now_str} · 10분 자동갱신</div>
<script>
var TASKS_DATA = {tasks_json};
var PROJECTS_DATA = {projects_json};
var API_BASE = '{API_BASE}';
var API = API_BASE || ((window.location.protocol === 'file:' || window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') ? 'http://127.0.0.1:{API_PORT}/api' : (window.location.origin + '/api'));
var currentTaskId = null;
var isStaticHost = false;
var currentProjectId = null;
var modalMode = 'edit';  // 'edit' or 'create'

// 페이지 로드 시 API 연결 확인 → 연결 안 되면 Mac Mini API로 폴백
(function() {{
    function tryAPI(url, callback) {{
        fetch(url + '/agent', {{ method: 'OPTIONS' }})
            .then(function(r) {{
                if (r.status === 204) callback(url);
                else throw new Error('no api');
            }})
            .catch(function() {{ callback(null); }});
    }}

    tryAPI(API, function(ok) {{
        if (ok) return;  // 기본 API 정상
        // 폴백: 같은 호스트의 8800 포트
        var fallback = window.location.protocol + '//' + window.location.hostname + ':8800/api';
        tryAPI(fallback, function(ok2) {{
            if (ok2) {{
                API = ok2;
                return;
            }}
            // 최종 폴백: Mac Mini
            tryAPI('http://192.168.45.98:{API_PORT}/api', function(ok3) {{
                if (ok3) {{
                    API = ok3;
                    return;
                }}
                // 모두 안 되면 비활성화
                isStaticHost = true;
                document.querySelectorAll('.btn-save, .btn-complete, .btn-delete, .btn-uncomplete, .btn-dropzone').forEach(function(btn) {{
                    btn.classList.add('disabled');
                }});
            }});
        }});
    }});
}})();

function forceRefresh() {{
    // 현재 필터 상태 저장
    var activeBtn = document.querySelector('.filter-btn.active');
    if (activeBtn) {{
        sessionStorage.setItem('branup_filter', activeBtn.textContent.trim());
    }}
    // API 서버가 같은 호스트의 다른 포트거나 로컬이면 API 서버의 대시보드로 리디렉션
    if (API.indexOf(':{API_PORT}') !== -1) {{
        window.location.href = API.replace('/api', '/index.html');
        return;
    }}
    var url = new URL(window.location.href);
    url.searchParams.set('_', Date.now());
    window.location.href = url.toString();
}}

// ── 검색 ── (현재 필터 위에서 카드 텍스트 일치 여부로 .search-hidden 토글)
function runSearch() {{
    var inp = document.getElementById('searchInput');
    var q = ((inp && inp.value) || '').trim().toLowerCase();
    var clearBtn = document.querySelector('.search-clear');
    if (!q) {{ clearSearch(); return; }}
    // 작업(저장/완료/삭제) 후 새로고침해도 검색이 유지되도록 검색어 보존
    sessionStorage.setItem('branup_search', (inp.value || '').trim());
    var matched = 0;
    document.querySelectorAll('.card').forEach(function(card) {{
        if (card.textContent.toLowerCase().indexOf(q) !== -1) {{
            card.classList.remove('search-hidden');
            matched++;
        }} else {{
            card.classList.add('search-hidden');
        }}
    }});
    if (clearBtn) clearBtn.style.display = '';
    updateCounts();
    // 검색 결과가 접혀 있는 장기지연·드랍존 섹션에 있으면 자동으로 펼쳐준다
    document.querySelectorAll('.long-delayed-section, .dropzone-section').forEach(function(sec) {{
        if (!sec.open && sec.querySelectorAll('.card:not(.hidden):not(.search-hidden)').length > 0) {{
            sec.open = true;
            sec.setAttribute('data-auto-open', '1');
        }}
    }});
    if (matched === 0) showToast('검색 결과가 없습니다: ' + q, true);
}}

function clearSearch() {{
    var inp = document.getElementById('searchInput');
    if (inp) inp.value = '';
    sessionStorage.removeItem('branup_search');
    document.querySelectorAll('.card.search-hidden').forEach(function(card) {{
        card.classList.remove('search-hidden');
    }});
    // 검색 때문에 자동으로 펼쳤던 섹션은 다시 접는다 (카테고리 필터로 편 것은 유지)
    document.querySelectorAll('[data-auto-open]').forEach(function(sec) {{
        sec.removeAttribute('data-auto-open');
        var key = (sec.id === 'dropzoneSection') ? 'dropzone' : 'long_delayed';
        if (currentCategory !== key) sec.open = false;
    }});
    var clearBtn = document.querySelector('.search-clear');
    if (clearBtn) clearBtn.style.display = 'none';
    updateCounts();
}}

function countVisible(col) {{
    return col.querySelectorAll('.card:not(.hidden):not(.search-hidden)').length;
}}

function updateCounts() {{
    // 칸반 컬럼 key → 상단 통계 카드 id
    var statMap = {{
        'delayed': 'stat-delayed',
        'no_due': 'stat-nodue',
        'today': 'stat-today',
        'd3': 'stat-d3',
        'd7': 'stat-d7',
        'upcoming': 'stat-upcoming',
        'long_delayed': 'stat-longdelayed',
        'dropzone': 'stat-dropzone'
    }};
    // 접이식 섹션 summary 배지
    var summaryMap = {{ 'long_delayed': 'ld-count', 'dropzone': 'dz-count' }};

    document.querySelectorAll('.column[data-col]').forEach(function(col) {{
        var key = col.getAttribute('data-col');
        var cnt = countVisible(col);
        var badge = col.querySelector('.count');
        if (badge) badge.textContent = cnt;

        if (statMap[key]) {{
            var el = document.getElementById(statMap[key]);
            if (el) el.querySelector('.num').textContent = cnt;
        }}
        if (summaryMap[key]) {{
            var sm = document.getElementById(summaryMap[key]);
            if (sm) sm.textContent = cnt;
        }}
    }});

    // 진행중 합계: 완료(.done)·드랍존(.dz) 카드는 제외
    var activeTotal = document.querySelectorAll('.card:not(.done):not(.dz):not(.hidden):not(.search-hidden)').length;
    var doneTotal = document.querySelectorAll('.column[data-col^="week-"] .card.done:not(.hidden):not(.search-hidden)').length;

    var elDone = document.getElementById('stat-done');
    if (elDone) elDone.querySelector('.num').textContent = doneTotal;

    var hdrActive = document.getElementById('hdr-active');
    if (hdrActive) hdrActive.textContent = activeTotal;
    var hdrDone = document.getElementById('hdr-done');
    if (hdrDone) hdrDone.textContent = doneTotal;
}}

// ── 카테고리 필터: 통계 카드 클릭 → 해당 항목 리스트만 표시 ──
// 직원/프로젝트 필터(.hidden)·검색(.search-hidden)과 독립적으로 동작하며,
// 카드가 아니라 "컬럼/섹션" 단위로 표시를 껐다 켠다 (통계 숫자는 그대로 유지).
var COLUMN_CATS = ['delayed', 'no_due', 'today', 'd3', 'd7', 'upcoming'];
var currentCategory = null;

function filterCategory(cat) {{
    // 같은 항목을 다시 클릭하면 해제 (직원 필터는 그대로 유지)
    if (cat && cat === currentCategory) cat = null;
    currentCategory = cat;

    if (cat) sessionStorage.setItem('branup_category', cat);
    else sessionStorage.removeItem('branup_category');

    // 통계 카드 활성 표시
    document.querySelectorAll('.stat').forEach(function(s) {{ s.classList.remove('cat-active'); }});
    var statIds = {{
        'delayed': 'stat-delayed', 'no_due': 'stat-nodue', 'today': 'stat-today',
        'd3': 'stat-d3', 'd7': 'stat-d7', 'upcoming': 'stat-upcoming',
        'done': 'stat-done', 'long_delayed': 'stat-longdelayed', 'dropzone': 'stat-dropzone'
    }};
    if (cat && statIds[cat]) {{
        var st = document.getElementById(statIds[cat]);
        if (st) st.classList.add('cat-active');
    }}
    var clearBtn = document.getElementById('catClearBtn');
    if (clearBtn) clearBtn.style.display = cat ? '' : 'none';

    // 칸반 보드: 해당 컬럼만 남기고 숨김. 컬럼형 카테고리가 아니면 보드 전체를 숨김
    var mainBoard = document.querySelector('#kanbanView > .board');
    var isColumnCat = cat && COLUMN_CATS.indexOf(cat) !== -1;
    if (mainBoard) {{
        mainBoard.style.display = (!cat || isColumnCat) ? '' : 'none';
        mainBoard.querySelectorAll('.column[data-col]').forEach(function(col) {{
            var key = col.getAttribute('data-col');
            col.style.display = (!cat || key === cat) ? '' : 'none';
        }});
    }}

    // 완료된 업무 / 장기지연 / 드랍존 섹션
    var sections = [
        ['done', document.getElementById('completedSection')],
        ['long_delayed', document.getElementById('longDelayedSection')],
        ['dropzone', document.getElementById('dropzoneSection')]
    ];
    sections.forEach(function(pair) {{
        var key = pair[0], el = pair[1];
        if (!el) return;
        el.style.display = (!cat || key === cat) ? '' : 'none';
        // 선택된 접이식 섹션은 자동으로 펼친다
        if (el.tagName === 'DETAILS') el.open = (cat === key);
    }});

    updateCounts();
}}

function filterAssignee(name) {{
    // 직원 필터 선택 시 프로젝트 필터는 전체로 전환
    if (currentProjectId) {{
        filterByProject(null);
    }}

    sessionStorage.setItem('branup_filter', name);
    document.querySelectorAll('.filter-btn').forEach(function(btn) {{
        btn.classList.remove('active');
    }});
    event.target.classList.add('active');

    // ── 주간리포트 버튼 표시/숨김 ──
    var weeklyBtn = document.getElementById('weeklyReportBtn');
    if (weeklyBtn) {{
        if (name === '긴급') {{
            weeklyBtn.classList.remove('active');
        }} else {{
            weeklyBtn.classList.add('active');
            // 선택된 직원 이름 저장 (ALL이면 'All')
            weeklyBtn.setAttribute('data-assignee', name === 'ALL' ? 'All' : name);
        }}
    }}

    document.querySelectorAll('.card').forEach(function(card) {{
        if (name === 'ALL') {{
            card.classList.remove('hidden');
        }} else if (name === '긴급') {{
            var p = card.getAttribute('data-priority');
            if (p === '긴급') {{
                card.classList.remove('hidden');
            }} else {{
                card.classList.add('hidden');
            }}
        }} else {{
            var a = card.getAttribute('data-assignee');
            if (a.split(/,\\s*/).includes(name) || a.split(/,\\s*/).includes('모두')) {{
                card.classList.remove('hidden');
            }} else {{
                card.classList.add('hidden');
            }}
        }}
    }});

    updateCounts();
}}

function filterByProject(projectId) {{
    currentProjectId = projectId;
    // 프로젝트 선택 상태 저장 (업무 추가 후 페이지 새로고침 시 복원)
    if (projectId) {{
        sessionStorage.setItem('branup_project', projectId);
    }} else {{
        sessionStorage.removeItem('branup_project');
    }}

    // 프로젝트 필터 버튼 active 토글
    document.querySelectorAll('.filter-btn.proj').forEach(function(btn) {{
        btn.classList.remove('active');
    }});
    if (projectId) {{
        var btns = document.querySelectorAll('.filter-btn.proj');
        for (var i = 0; i < btns.length; i++) {{
            if (btns[i].getAttribute('onclick').indexOf("'" + projectId + "'") !== -1) {{
                btns[i].classList.add('active');
                break;
            }}
        }}
    }} else {{
        var first = document.querySelector('.filter-btn.proj');
        if (first) first.classList.add('active');
    }}

    // 프로젝트 전체일 때만 assignee 필터 적용
    var assigneeFilter = null;
    if (!projectId) {{
        var activeAssigneeBtn = document.querySelector('.filter-btn:not(.proj):not(.urgent).active');
        if (activeAssigneeBtn) assigneeFilter = activeAssigneeBtn.textContent.trim();
    }}

    // 카드 필터링
    document.querySelectorAll('.card').forEach(function(card) {{
        var show = true;
        if (projectId) {{
            var tid = card.getAttribute('data-task-id');
            var task = TASKS_DATA[tid];
            if (!task || task.project_id !== projectId) show = false;
        }}
        if (show && assigneeFilter && assigneeFilter !== 'ALL') {{
            var a = card.getAttribute('data-assignee');
            if (!(a.split(/,\\s*/).includes(assigneeFilter) || a.split(/,\\s*/).includes('모두'))) show = false;
        }}
        if (show) {{
            card.classList.remove('hidden');
        }} else {{
            card.classList.add('hidden');
        }}
    }});

    updateCounts();
}}

function showToast(msg, isError) {{
    var t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast ' + (isError ? 'error' : '');
    setTimeout(function() {{ t.classList.add('show'); }}, 10);
    setTimeout(function() {{ t.classList.remove('show'); }}, 2500);
}}

// ── 주간리포트 요청 (주 선택 모달) ──
function requestWeeklyReport() {{
    var btn = document.getElementById('weeklyReportBtn');
    var assignee = btn.getAttribute('data-assignee');
    if (!assignee) {{
        showToast('직원을 먼저 선택하세요', true);
        return;
    }}

    // ── 최근 6주 목록 생성 ──
    var today = new Date();
    var dayOfWeek = today.getDay();          // 0=일,1=월,...,6=토
    var daysFromMonday = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
    var thisMonday = new Date(today);
    thisMonday.setDate(today.getDate() - daysFromMonday);
    thisMonday.setHours(0,0,0,0);

    function fmtDate(d) {{
        return (d.getMonth()+1) + '/' + d.getDate();
    }}
    function isoDate(d) {{
        var y = d.getFullYear();
        var m = String(d.getMonth()+1).padStart(2,'0');
        var day = String(d.getDate()).padStart(2,'0');
        return y + '-' + m + '-' + day;
    }}
    function getDayLabel(d) {{
        var days = ['일','월','화','수','목','금','토'];
        return days[d.getDay()];
    }}

    var weeks = [];
    for (var i = -2; i <= 3; i++) {{
        var mon = new Date(thisMonday);
        mon.setDate(thisMonday.getDate() + i * 7);
        var sun = new Date(mon);
        sun.setDate(mon.getDate() + 6);
        var ws = isoDate(mon);
        var we = isoDate(sun);
        var label = fmtDate(mon) + '(' + getDayLabel(mon) + ') ~ ' + fmtDate(sun) + '(' + getDayLabel(sun) + ')';
        var tag = '';
        if (i === 0) tag = ' [이번주]';
        else if (i === -1) tag = ' [지난주]';
        else if (i === 1) tag = ' [다음주]';
        weeks.push({{week_start: ws, week_end: we, label: label, tag: tag, isCurrent: (i===0)}});
    }}

    // ── 모달 생성 ──
    var modal = createModalEl();
    modal.querySelector('.modal-title').textContent = '📊 주간리포트 기준 주 선택';
    modal.querySelector('.modal-status').textContent = assignee === 'All' ? '📊 브랜업 전체 주간리포트' : assignee + '님 리포트';

    var body = modal.querySelector('.modal-body');
    // 불필요 필드 숨김
    body.querySelector('.edit-title').parentElement.style.display = 'none';
    body.querySelector('.edit-assignee').parentElement.style.display = 'none';
    body.querySelector('.edit-due').parentElement.style.display = 'none';
    body.querySelector('.edit-summary').parentElement.style.display = 'none';
    body.querySelector('.edit-priority').parentElement.style.display = 'none';
    body.querySelector('.edit-project').parentElement.style.display = 'none';
    body.querySelector('.content-field').style.display = 'none';
    body.querySelector('.file-section').style.display = 'none';

    // 주 버튼 컨테이너
    var container = document.createElement('div');
    container.style.cssText = 'display:flex;flex-direction:column;gap:8px;padding:8px 0;';

    weeks.forEach(function(w) {{
        (function(wk) {{
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:10px 14px;background:#161b22;border:1px solid #2a2d3a;border-radius:8px;cursor:pointer;transition:background .15s,border-color .15s';
        if (wk.isCurrent) row.style.borderColor = '#58a6ff';
        row.onmouseenter = function() {{ this.style.background = '#1c2129'; }};
        row.onmouseleave = function() {{
            this.style.background = '#161b22';
            if (wk.isCurrent) this.style.borderColor = '#58a6ff';
        }};

        var radio = document.createElement('div');
        radio.style.cssText = 'width:18px;height:18px;border-radius:50%;border:2px solid ' + (wk.isCurrent ? '#58a6ff' : '#484f5e') + ';display:flex;align-items:center;justify-content:center;flex-shrink:0';
        if (wk.isCurrent) {{
            radio.innerHTML = '<div style="width:9px;height:9px;border-radius:50%;background:#58a6ff"></div>';
        }}

        var textDiv = document.createElement('div');
        textDiv.style.flex = '1';
        textDiv.innerHTML = '<span style="font-size:14px;color:#e1e4e8;font-weight:600">' + wk.label + '</span>' +
                           (wk.tag ? '<span style="font-size:11px;color:#8b949e;margin-left:6px">' + wk.tag + '</span>' : '');

        row.appendChild(radio);
        row.appendChild(textDiv);

        row.onclick = function() {{
            closeModal(modal);
            doRequestWeeklyReport(assignee, wk.week_start, wk.week_end, wk.label);
        }};

        container.appendChild(row);
        }})(w);
    }});

    body.appendChild(container);

    // 저장/완료/삭제 버튼 숨김
    var actions = modal.querySelector('.modal-actions');
    actions.querySelector('.btn-save').style.display = 'none';
    actions.querySelector('.btn-complete').style.display = 'none';
    actions.querySelectorAll('.btn-dropzone').forEach(function(b) {{ b.style.display = 'none'; }});
    actions.querySelector('.btn-delete').style.display = 'none';
    // 취소 버튼 추가
    var cancelBtn = document.createElement('button');
    cancelBtn.textContent = '취소';
    cancelBtn.style.cssText = 'padding:8px 20px;background:#2a2d3a;color:#e1e4e8;border:none;border-radius:8px;font-size:13px;cursor:pointer;font-weight:600';
    cancelBtn.onclick = function() {{ closeModal(modal); }};
    actions.appendChild(cancelBtn);

    document.getElementById('modalOverlay').appendChild(modal);
    document.getElementById('modalOverlay').classList.add('active');
    modalStack.push({{ taskId: '__weekly__', el: modal }});
}}

function doRequestWeeklyReport(assignee, week_start, week_end, label) {{
    var btn = document.getElementById('weeklyReportBtn');
    btn.textContent = '⏳ 생성 중...';
    btn.disabled = true;

    fetch(API + '/weekly-report?assignee=' + encodeURIComponent(assignee) +
          '&week_start=' + encodeURIComponent(week_start) +
          '&week_end=' + encodeURIComponent(week_end))
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
            if (data.ok) {{
                showToast('📊 ' + label + ' 리포트 생성 완료!');
                if (data.filename) {{
                    // 자동 다운로드 (fetch + Blob 방식으로 HTTP 경고 우회)
                    var url = API + '/reports/' + encodeURIComponent(data.filename);
                    fetch(url)
                        .then(function(r) {{ return r.blob(); }})
                        .then(function(blob) {{
                            var a = document.createElement('a');
                            a.href = URL.createObjectURL(blob);
                            a.download = data.filename;
                            document.body.appendChild(a);
                            a.click();
                            document.body.removeChild(a);
                            URL.revokeObjectURL(a.href);
                        }});
                }}
            }} else {{
                showToast(data.error || '요청 실패', true);
            }}
        }})
        .catch(function(err) {{
            showToast('API 연결 실패', true);
        }})
        .finally(function() {{
            btn.textContent = '📊 주간리포트';
            btn.disabled = false;
        }});
}}

// ── 모달 ──
var modalStack = [];
var MODAL_Z_BASE = 1000;

function createModalEl() {{
    var div = document.createElement('div');
    div.className = 'modal';
    div.style.zIndex = MODAL_Z_BASE + modalStack.length * 10;
    div.onclick = function(e) {{ e.stopPropagation(); }};
    div.innerHTML =
        '<div class="modal-header">' +
        '<h2 class="modal-title"></h2>' +
        '<button class="modal-close" onclick="closeModal(this.parentElement.parentElement)">&times;</button>' +
        '</div>' +
        '<div class="modal-body">' +
        '<div class="modal-status modal-meta"></div>' +
        '<div class="modal-field"><label>제목</label><input type="text" class="edit-title" placeholder="업무 제목"></div>' +
        '<div class="modal-field"><label>담당자</label><select class="edit-assignee" multiple size="5">' +
        '{''.join(f'<option value="{a}">{a}</option>' for a in sorted_assignees)}' +
        '</select><div style="font-size:10px;color:#8b949e;margin-top:3px">Ctrl+클릭: 다중 선택 | 선택 없으면 미정</div></div>' +
        '<div class="modal-field"><label>마감일</label><input type="date" class="edit-due"></div>' +
        '<div class="modal-field content-field"><label>📝 내용</label><textarea class="edit-summary" placeholder="업무 내용..." rows="4"></textarea></div>' +
        '<div class="modal-field feedback-field" style="display:none"><label>💬 피드백</label><textarea class="edit-feedback" placeholder="완료 후기, 결과, 특이사항 등..."></textarea></div>' +
        '<div class="modal-field"><label>우선순위</label><select class="edit-priority">' +
        '<option value="긴급">🔴 긴급</option><option value="높음">🟠 높음</option><option value="중간" selected>🟡 중간</option><option value="낮음">🟢 낮음</option>' +
        '</select></div>' +
        '<div class="modal-field"><label>📁 프로젝트</label><select class="edit-project"><option value="">없음</option>{proj_options}</select></div>' +
        '<div class="modal-field"><label>🔗 연관업무</label>' +
        '<div class="related-tasks" style="display:flex;flex-wrap:wrap;gap:6px;min-height:28px;align-items:center"></div>' +
        '<div style="display:flex;gap:6px;margin-top:8px">' +
        '<input type="number" class="related-input" placeholder="업무번호" onkeydown="if(event.key===&quot;Enter&quot;)addRelatedTask(this)" style="width:90px;padding:6px 10px;background:#0f1117;border:1px solid #2a2d3a;border-radius:6px;color:#e1e4e8;font-size:13px">' +
        '<button onclick="addRelatedTask(this)" style="padding:6px 12px;background:#1f6feb;color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer;font-weight:600">추가</button>' +
        '</div></div>' +
        '<div class="modal-field file-section">' +
        '<label>📎 첨부파일</label>' +
        '<div class="file-dropzone" onclick="this.querySelector(\\'input\\').click()" ondragover="event.preventDefault();this.classList.add(\\'dragover\\')" ondragleave="this.classList.remove(\\'dragover\\')" ondrop="event.preventDefault();this.classList.remove(\\'dragover\\');var inp=this.querySelector(\\'input\\');inp.files=event.dataTransfer.files;inp.onchange()">' +
        '<span>클릭 또는 드래그로 파일 추가</span>' +
        '<input type="file" class="file-input" multiple onchange="uploadModalFiles(this)" style="display:none">' +
        '</div>' +
        '<div class="file-list"></div>' +
        '<div class="file-limit-info"></div>' +
        '</div>' +
        '<div class="modal-actions">' +
        '<button class="btn-save modal-btn-save" onclick="saveTask(this)">💾 저장</button>' +
        '<button class="btn-save modal-btn-create" onclick="createTask()" style="display:none">➕ 추가</button>' +
        '<button class="btn-complete modal-btn-complete" onclick="completeTask(this)">✅ 완료 처리</button>' +
        '<button class="btn-dropzone modal-btn-dropzone" onclick="dropzoneTask(this)">📥 드랍존</button>' +
        '<button class="btn-dropzone modal-btn-undropzone" onclick="undropzoneTask(this)" style="display:none">↩ 드랍존취소</button>' +
        '<button class="btn-delete modal-btn-delete" onclick="deleteTask(this)">🗑 삭제</button>' +
        '<button class="btn-uncomplete modal-btn-uncomplete" onclick="uncompleteTask(this)" style="display:none">↩ 완료취소</button>' +
        '<button class="btn-cancel" onclick="closeModal(this.parentElement.parentElement.parentElement)">취소</button>' +
        '</div></div>';
    return div;
}}

function getModal() {{
    if (modalStack.length === 0) return null;
    return modalStack[modalStack.length - 1];
}}

function populateModal(modalEl, task) {{
    modalEl.querySelector('.modal-title').textContent = '#' + task.display_num + ' 업무 상세';
    modalEl.querySelector('.edit-title').value = task.title || '';
    modalEl.querySelector('.edit-due').value = task.due_at ? task.due_at.slice(0,10) : '';
    modalEl.querySelector('.edit-summary').value = task.summary || task.title || '';
    modalEl.querySelector('.edit-feedback').value = task.feedback || '';
    modalEl.querySelector('.edit-priority').value = task.priority || '중간';
    modalEl.querySelector('.edit-project').value = task.project_id || '';
    modalEl.querySelector('.modal-meta').innerHTML =
        '<strong>상태:</strong> ' + (task.status || '진행중') +
        ' &nbsp;|&nbsp; <strong>생성:</strong> ' + (task.created_at ? task.created_at.slice(0,16).replace('T',' ') : '-') +
        ' &nbsp;|&nbsp; <strong>수정:</strong> ' + (task.updated_at ? task.updated_at.slice(0,16).replace('T',' ') : '-') +
        (task.closed_at ? ' | <strong>완료:</strong> ' + task.closed_at.slice(0,16).replace('T',' ') : '');

    var sel = modalEl.querySelector('.edit-assignee');
    for (var i = 0; i < sel.options.length; i++) {{ sel.options[i].selected = false; }}
    var names = (task.assignee || '').split(',').map(function(s) {{ return s.trim(); }});
    for (var n = 0; n < names.length; n++) {{
        if (!names[n]) continue;
        var found = false;
        for (var i = 0; i < sel.options.length; i++) {{
            if (sel.options[i].value === names[n]) {{ sel.options[i].selected = true; found = true; break; }}
        }}
        if (!found) {{ var opt = document.createElement('option'); opt.value = names[n]; opt.textContent = names[n]; opt.selected = true; sel.appendChild(opt); }}
    }}

    var feedbackField = modalEl.querySelector('.feedback-field');
    feedbackField.style.display = (task.status === '완료') ? '' : 'none';
    var isDone = (task.status === '완료');
    var isDrop = (task.status === '보류');   // 보류 = 드랍존
    var btnComplete = modalEl.querySelector('.modal-btn-complete');
    btnComplete.style.display = isDone ? 'none' : '';
    var btnUncomplete = modalEl.querySelector('.modal-btn-uncomplete');
    btnUncomplete.style.display = isDone ? '' : 'none';
    // 드랍존: 일반 업무면 "드랍존", 드랍존 업무면 "드랍존취소". 완료 업무엔 둘 다 숨김
    var btnDrop = modalEl.querySelector('.modal-btn-dropzone');
    btnDrop.style.display = (!isDone && !isDrop) ? '' : 'none';
    var btnUndrop = modalEl.querySelector('.modal-btn-undropzone');
    btnUndrop.style.display = isDrop ? '' : 'none';

    // 연관업무 렌더링
    renderRelatedButtonsInModal(modalEl, task.related_tasks || '');

    // 첨부파일 렌더링
    renderFiles(modalEl, task.id);

    if (isStaticHost) {{
        modalEl.querySelectorAll('.btn-save, .btn-complete, .btn-delete, .btn-uncomplete, .btn-dropzone').forEach(function(btn) {{ btn.classList.add('disabled'); }});
    }}
}}

function openModal(taskId) {{
    // 이미 열려있으면 포커스만
    for (var i = 0; i < modalStack.length; i++) {{
        if (modalStack[i].taskId === taskId) {{
            var existing = modalStack[i].el;
            existing.style.zIndex = MODAL_Z_BASE + modalStack.length * 10;
            return;
        }}
    }}

    var local = TASKS_DATA[taskId];
    var modalEl = createModalEl();
    document.getElementById('modalOverlay').appendChild(modalEl);
    document.getElementById('modalOverlay').classList.add('active');
    modalStack.push({{ taskId: taskId, el: modalEl }});

    if (local) populateModal(modalEl, local);

    fetch(API + '/tasks/' + taskId)
        .then(function(r) {{ return r.json(); }})
        .then(function(task) {{
            if (!task.error && modalEl.parentNode) populateModal(modalEl, task);
        }}).catch(function() {{}});
}}

function closeModal(el) {{
    if (el === undefined) {{
        // closeModal() 호출 시 최상단 모달 닫기
        if (modalStack.length === 0) return;
        el = modalStack[modalStack.length - 1].el;
    }}
    if (typeof el === 'object' && el.classList && el.classList.contains('modal')) {{
        // el이 모달 div인 경우
    }} else if (el && el.target === document.getElementById('modalOverlay')) {{
        // overlay 클릭 → 최상단 모달 닫기
        if (modalStack.length === 0) return;
        el = modalStack[modalStack.length - 1].el;
    }} else {{
        return;
    }}

    el.remove();
    modalStack = modalStack.filter(function(m) {{ return m.el !== el; }});
    if (modalStack.length === 0) {{
        document.getElementById('modalOverlay').classList.remove('active');
        currentTaskId = null;
    }} else {{
        currentTaskId = modalStack[modalStack.length - 1].taskId;
    }}
}}

// ── 새 업무 생성 ──
function openCreateModal() {{
    var modalEl = createModalEl();
    document.getElementById('modalOverlay').appendChild(modalEl);
    document.getElementById('modalOverlay').classList.add('active');
    modalStack.push({{ taskId: null, el: modalEl }});

    modalEl.querySelector('.modal-title').textContent = '✨ 새 업무';
    modalEl.querySelector('.edit-title').value = '';
    modalEl.querySelector('.edit-due').value = new Date().toISOString().slice(0,10);
    modalEl.querySelector('.edit-summary').value = '';
    modalEl.querySelector('.edit-feedback').value = '';
    modalEl.querySelector('.edit-priority').value = '중간';
    modalEl.querySelector('.modal-meta').style.display = 'none';
    modalEl.querySelector('.content-field').style.display = '';
    modalEl.querySelector('.feedback-field').style.display = 'none';
    modalEl.querySelector('.modal-btn-save').style.display = 'none';
    modalEl.querySelector('.modal-btn-complete').style.display = 'none';
    modalEl.querySelector('.modal-btn-dropzone').style.display = 'none';
    modalEl.querySelector('.modal-btn-undropzone').style.display = 'none';
    modalEl.querySelector('.modal-btn-delete').style.display = 'none';
    modalEl.querySelector('.modal-btn-create').style.display = '';

    var sel = modalEl.querySelector('.edit-assignee');
    for (var i = 0; i < sel.options.length; i++) {{ sel.options[i].selected = false; }}
    var activeBtn = document.querySelector('.filter-btn:not(.proj).active');
    var filterName = activeBtn ? activeBtn.textContent.trim() : '';
    var validAssignees = ['강경철', '노수민', '이상원', '이향석', '전경표', '모두'];
    if (validAssignees.indexOf(filterName) !== -1) {{
        for (var i = 0; i < sel.options.length; i++) {{
            if (sel.options[i].value === filterName) {{ sel.options[i].selected = true; break; }}
        }}
    }}

    // 현재 선택된 프로젝트를 기본값으로 설정
    if (currentProjectId) {{
        var projSel = modalEl.querySelector('.edit-project');
        if (projSel) {{ projSel.value = currentProjectId; }}
    }}
    renderRelatedButtonsInModal(modalEl, '');
}}

// ── 다중 담당자 값 가져오기 ──
function getAssigneeValue(modalEl) {{
    var sel = modalEl ? modalEl.querySelector('.edit-assignee') : document.getElementById('editAssignee');
    var names = [];
    for (var i = 0; i < sel.options.length; i++) {{
        if (sel.options[i].selected && sel.options[i].value) names.push(sel.options[i].value);
    }}
    return names.join(', ');
}}

function createTask() {{
    var m = getModal();
    if (!m) return;
    var modalEl = m.el;
    var title = modalEl.querySelector('.edit-title').value.trim();
    if (!title) {{ showToast('제목은 필수입니다', true); return; }}
    var data = {{
        title: title,
        assignee: getAssigneeValue(modalEl),
        due_at: modalEl.querySelector('.edit-due').value || null,
        summary: modalEl.querySelector('.edit-summary').value.trim(),
        priority: modalEl.querySelector('.edit-priority').value,
        project_id: modalEl.querySelector('.edit-project').value || null
    }};
    fetch(API + '/tasks', {{
        method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(data)
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(task) {{
        if (task.error) {{ showToast('등록 실패: ' + task.error, true); return; }}
        showToast('✨ #' + task.display_num + ' 등록 완료!');
        // 직원 필터 상태 저장
        var ab = document.querySelector('.filter-btn:not(.proj).active');
        if (ab) sessionStorage.setItem('branup_filter', ab.textContent.trim());
        closeModal(modalEl);
        setTimeout(function() {{ forceRefresh(); }}, 500);
    }})
    .catch(function() {{ showToast('⚠️ API 서버 연결 실패', true); }});
}}

function saveTask(btnEl) {{
    var modalEl = btnEl.closest('.modal');
    var m = modalStack.find(function(x) {{ return x.el === modalEl; }});
    if (!m || !m.taskId) return;
    var data = {{
        title: modalEl.querySelector('.edit-title').value.trim(),
        assignee: getAssigneeValue(modalEl),
        due_at: modalEl.querySelector('.edit-due').value || null,
        summary: modalEl.querySelector('.edit-summary').value.trim(),
        feedback: modalEl.querySelector('.edit-feedback').value.trim(),
        priority: modalEl.querySelector('.edit-priority').value,
        project_id: modalEl.querySelector('.edit-project').value || null
    }};
    if (!data.title) {{ showToast('제목은 필수입니다', true); return; }}
    fetch(API + '/tasks/' + m.taskId, {{
        method: 'PATCH', headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(data)
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(task) {{
        if (task.error) {{ showToast('저장 실패: ' + task.error, true); return; }}
        showToast('저장 완료!');
        setTimeout(function() {{ forceRefresh(); }}, 500);
    }})
    .catch(function() {{ showToast('⚠️ API 서버 연결 필요', true); }});
}}

function completeTask(btnEl) {{
    var modalEl = btnEl.closest('.modal');
    var m = modalStack.find(function(x) {{ return x.el === modalEl; }});
    if (!m || !m.taskId) return;
    if (!confirm('정말 완료 처리하시겠습니까?')) return;

    // 먼저 변경 내용 저장
    var data = {{
        title: modalEl.querySelector('.edit-title').value.trim(),
        assignee: getAssigneeValue(modalEl),
        due_at: modalEl.querySelector('.edit-due').value || null,
        summary: modalEl.querySelector('.edit-summary').value.trim(),
        feedback: modalEl.querySelector('.edit-feedback').value.trim(),
        priority: modalEl.querySelector('.edit-priority').value,
        project_id: modalEl.querySelector('.edit-project').value || null
    }};
    if (!data.title) {{ showToast('제목은 필수입니다', true); return; }}

    fetch(API + '/tasks/' + m.taskId, {{
        method: 'PATCH', headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(data)
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function() {{
        return fetch(API + '/tasks/' + m.taskId + '/complete', {{ method: 'POST' }});
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(task) {{
        if (task.error) {{ showToast('완료 처리 실패', true); return; }}
        showToast('완료 처리되었습니다!');
        setTimeout(function() {{ forceRefresh(); }}, 500);
    }}).catch(function() {{ showToast('⚠️ API 서버 연결 필요', true); }});
}}

function dropzoneTask(btnEl) {{
    var modalEl = btnEl.closest('.modal');
    var m = modalStack.find(function(x) {{ return x.el === modalEl; }});
    if (!m || !m.taskId) return;
    if (!confirm('이 업무를 드랍존(연기)으로 보내시겠습니까?\\n마감 집계와 주간리포트에서 제외됩니다.')) return;
    patchTaskDropzone(m.taskId, 'dropzone', '드랍존으로 보냈습니다!');
}}

function undropzoneTask(btnEl) {{
    var modalEl = btnEl.closest('.modal');
    var m = modalStack.find(function(x) {{ return x.el === modalEl; }});
    if (!m || !m.taskId) return;
    if (!confirm('드랍존에서 꺼내 일반 업무로 되돌리시겠습니까?')) return;
    patchTaskDropzone(m.taskId, 'undropzone', '드랍존에서 해제되었습니다!');
}}

function patchTaskDropzone(taskId, action, okMsg) {{
    fetch(API + '/tasks/' + taskId + '/' + action, {{ method: 'POST' }})
    .then(function(r) {{ return r.json(); }})
    .then(function(task) {{
        if (task.error) {{ showToast('오류: ' + task.error, true); return; }}
        showToast(okMsg);
        setTimeout(function() {{ forceRefresh(); }}, 500);
    }})
    .catch(function() {{ showToast('⚠️ API 서버 연결 필요', true); }});
}}

function uncompleteTask(btnEl) {{
    var modalEl = btnEl.closest('.modal');
    var m = modalStack.find(function(x) {{ return x.el === modalEl; }});
    if (!m || !m.taskId) return;
    if (!confirm('완료를 취소하고 진행중으로 되돌리시겠습니까?')) return;
    fetch(API + '/tasks/' + m.taskId + '/uncomplete', {{ method: 'POST' }})
    .then(function(r) {{ return r.json(); }})
    .then(function(task) {{
        if (task.error) {{ showToast('완료취소 실패', true); return; }}
        showToast('완료가 취소되었습니다!');
        setTimeout(function() {{ forceRefresh(); }}, 500);
    }}).catch(function() {{ showToast('⚠️ API 서버 연결 필요', true); }});
}}

function deleteTask(btnEl) {{
    var modalEl = btnEl.closest('.modal');
    var m = modalStack.find(function(x) {{ return x.el === modalEl; }});
    if (!m || !m.taskId) return;
    if (!confirm('정말 삭제하시겠습니까?')) return;
    fetch(API + '/tasks/' + m.taskId, {{ method: 'DELETE' }})
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
        if (data.error) {{ showToast('삭제 실패', true); return; }}
        showToast('삭제 완료!');
        closeModal(modalEl);
        setTimeout(function() {{ forceRefresh(); }}, 500);
    }}).catch(function() {{ showToast('⚠️ API 서버 연결 필요', true); }});
}}

// ── 연관업무 ──

function renderRelatedButtons(relatedStr) {{
    // 하위 호환: 기존 static modal
    renderRelatedButtonsInModal(null, relatedStr);
}}

function renderRelatedButtonsInModal(modalEl, relatedStr) {{
    var container = modalEl ? modalEl.querySelector('.related-tasks') : document.getElementById('relatedTasks');
    if (!container) return;
    container.innerHTML = '';
    var nums = (relatedStr || '').split(',').map(function(s) {{ return s.trim(); }}).filter(Boolean);
    if (nums.length === 0) {{
        container.innerHTML = '<span style="color:#484f5a;font-size:12px">연관업무 없음</span>';
        return;
    }}
    for (var i = 0; i < nums.length; i++) {{
        var btn = document.createElement('span');
        btn.textContent = '#' + nums[i];
        btn.style.cssText = 'display:inline-block;padding:4px 10px;background:#1f6feb;color:#fff;border-radius:14px;font-size:12px;font-weight:600;cursor:pointer;transition:all 0.15s';
        btn.onmouseenter = function() {{ this.style.background = '#58a6ff'; }};
        btn.onmouseleave = function() {{ this.style.background = '#1f6feb'; }};
        btn.onclick = (function(num) {{ return function(e) {{ openRelatedTask(num, e); }}; }})(nums[i]);
        btn.oncontextmenu = (function(num) {{ return function(e) {{ e.preventDefault(); removeRelatedTask(num, modalEl); }}; }})(nums[i]);
        btn.title = '클릭: 열기 | 우클릭: 연결해제';
        container.appendChild(btn);
    }}
}}

function addRelatedTask(btnEl) {{
    var modalEl = btnEl ? btnEl.closest('.modal') : null;
    var input = modalEl ? modalEl.querySelector('.related-input') : document.getElementById('relatedInput');
    var num = parseInt(input.value, 10);
    if (!num || num < 1) {{ showToast('올바른 업무번호를 입력하세요', true); return; }}
    var m = modalEl ? modalStack.find(function(x) {{ return x.el === modalEl; }}) : null;
    var taskId = m ? m.taskId : currentTaskId;
    if (!taskId) return;
    fetch(API + '/tasks/' + taskId + '/related', {{
        method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ display_num: num }})
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(task) {{
        if (task.error) {{ showToast(task.error, true); return; }}
        renderRelatedButtonsInModal(modalEl, task.related_tasks || '');
        input.value = '';
        showToast('#' + num + ' 연결됨');
    }}).catch(function() {{ showToast('연결 실패', true); }});
}}

function removeRelatedTask(displayNum, modalEl) {{
    if (!modalEl) modalEl = null;
    var m = modalEl ? modalStack.find(function(x) {{ return x.el === modalEl; }}) : null;
    var taskId = m ? m.taskId : currentTaskId;
    if (!taskId) return;
    if (!confirm('#' + displayNum + ' 연결을 해제하시겠습니까?')) return;
    fetch(API + '/tasks/' + taskId + '/related/' + displayNum, {{ method: 'DELETE' }})
    .then(function(r) {{ return r.json(); }})
    .then(function(task) {{
        if (task.error) {{ showToast(task.error, true); return; }}
        renderRelatedButtonsInModal(modalEl, task.related_tasks || '');
        showToast('#' + displayNum + ' 연결 해제됨');
    }}).catch(function() {{ showToast('해제 실패', true); }});
}}

function openRelatedTask(displayNum, event) {{
    event.stopPropagation();
    // TASKS_DATA에서 display_num으로 찾기
    var task = null;
    for (var tid in TASKS_DATA) {{
        if (TASKS_DATA[tid].display_num == displayNum) {{
            task = TASKS_DATA[tid];
            break;
        }}
    }}
    if (task) {{
        openModal(task.id);
        return;
    }}
    // 없으면 API로 다시 시도 (완료된 업무 등)
    fetch(API + '/tasks/list')
        .then(function(r) {{ return r.json(); }})
        .then(function(tasks) {{
            for (var i = 0; i < tasks.length; i++) {{
                if (tasks[i].display_num == displayNum) {{
                    openModal(tasks[i].id);
                    return;
                }}
            }}
            showToast('#' + displayNum + ' 업무를 찾을 수 없습니다', true);
        }})
        .catch(function() {{
            showToast('#' + displayNum + ' 업무를 찾을 수 없습니다', true);
        }});
}}

// ── 파일 첨부 ──

function renderFiles(modalEl, taskId) {{
    var list = modalEl.querySelector('.file-list');
    var limit = modalEl.querySelector('.file-limit-info');
    if (!list || !taskId) return;

    fetch(API + '/tasks/' + taskId + '/files')
        .then(function(r) {{ return r.json(); }})
        .then(function(files) {{
            var totalSize = 0;
            list.innerHTML = '';
            for (var i = 0; i < files.length; i++) {{
                var f = files[i];
                totalSize += f.file_size;
                var sizeStr = f.file_size < 1024*1024
                    ? (f.file_size / 1024).toFixed(1) + 'KB'
                    : (f.file_size / 1024 / 1024).toFixed(1) + 'MB';
                var icon = '📄';
                var ext = (f.original_name || '').split('.').pop().toLowerCase();
                if (['png','jpg','jpeg','gif','webp','svg'].indexOf(ext) >= 0) icon = '🖼';
                else if (ext === 'pdf') icon = '📕';
                else if (['xlsx','xls','csv'].indexOf(ext) >= 0) icon = '📊';
                else if (['docx','doc'].indexOf(ext) >= 0) icon = '📝';
                else if (['zip','rar','7z'].indexOf(ext) >= 0) icon = '📦';
                else if (ext === 'hwp') icon = '📋';
                list.innerHTML += '<div class="file-item">' +
                    '<span class="file-icon">' + icon + '</span>' +
                    '<a class="file-name" href="' + API + '/files/' + f.id + '">' + f.original_name + '</a>' +
                    '<span class="file-size">' + sizeStr + '</span>' +
                    '<span class="file-del" onclick="deleteModalFile(this, \\'' + f.id + '\\')" title="삭제">✕</span>' +
                    '</div>';
            }}
            if (files.length === 0) {{
                list.innerHTML = '<div class="file-empty">첨부된 파일이 없습니다</div>';
            }}
            var limitMB = 50;
            var usedMB = (totalSize / 1024 / 1024).toFixed(1);
            limit.textContent = '용량: ' + usedMB + 'MB / ' + limitMB + 'MB';
        }}).catch(function() {{}});
}}

function uploadModalFiles(inputEl) {{
    var modalEl = inputEl.closest('.modal');
    if (!modalEl) return;
    var m = modalStack.find(function(x) {{ return x.el === modalEl; }});
    var taskId = m ? m.taskId : null;
    if (!taskId) return;

    var files = inputEl.files;
    if (!files || files.length === 0) return;

    var formData = new FormData();
    var totalSize = 0;
    for (var i = 0; i < files.length; i++) {{
        if (files[i].size > 20 * 1024 * 1024) {{
            showToast(files[i].name + ': 20MB 제한 초과', true);
            inputEl.value = '';
            return;
        }}
        formData.append('file_' + i, files[i]);
        totalSize += files[i].size;
    }}

    showToast('업로드 중...');
    fetch(API + '/tasks/' + taskId + '/files', {{
        method: 'POST',
        body: formData
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(result) {{
        inputEl.value = '';
        if (result.errors && result.errors.length > 0) {{
            showToast(result.errors.join('\\n'), true);
        }}
        if (result.uploaded && result.uploaded.length > 0) {{
            showToast(result.uploaded.length + '개 파일 업로드 완료');
        }}
        renderFiles(modalEl, taskId);
    }}).catch(function() {{
        showToast('업로드 실패', true);
        inputEl.value = '';
    }});
}}

function deleteModalFile(el, fileId) {{
    if (!confirm('파일을 삭제하시겠습니까?')) return;
    var modalEl = el.closest('.modal');
    var m = modalEl ? modalStack.find(function(x) {{ return x.el === modalEl; }}) : null;
    var taskId = m ? m.taskId : null;
    fetch(API + '/files/' + fileId, {{ method: 'DELETE' }})
        .then(function(r) {{ return r.json(); }})
        .then(function(res) {{
            if (res.error) {{ showToast(res.error, true); return; }}
            showToast('파일 삭제됨');
            if (modalEl && taskId) renderFiles(modalEl, taskId);
        }}).catch(function() {{ showToast('삭제 실패', true); }});
}}

// ── 프로젝트 파일 ──

function renderProjectFiles(modalEl, projectId) {{
    var list = modalEl.querySelector('.file-list');
    var limit = modalEl.querySelector('.file-limit-info');
    if (!list || !projectId) return;

    fetch(API + '/projects/' + projectId + '/files')
        .then(function(r) {{ return r.json(); }})
        .then(function(files) {{
            var totalSize = 0;
            list.innerHTML = '';
            for (var i = 0; i < files.length; i++) {{
                var f = files[i];
                totalSize += f.file_size;
                var sizeStr = f.file_size < 1024*1024
                    ? (f.file_size / 1024).toFixed(1) + 'KB'
                    : (f.file_size / 1024 / 1024).toFixed(1) + 'MB';
                var icon = '📄';
                var ext = (f.original_name || '').split('.').pop().toLowerCase();
                if (['png','jpg','jpeg','gif','webp','svg'].indexOf(ext) >= 0) icon = '🖼';
                else if (ext === 'pdf') icon = '📕';
                else if (['xlsx','xls','csv'].indexOf(ext) >= 0) icon = '📊';
                else if (['docx','doc'].indexOf(ext) >= 0) icon = '📝';
                else if (['zip','rar','7z'].indexOf(ext) >= 0) icon = '📦';
                else if (ext === 'hwp') icon = '📋';
                list.innerHTML += '<div class="file-item">' +
                    '<span class="file-icon">' + icon + '</span>' +
                    '<a class="file-name" href="' + API + '/files/' + f.id + '">' + f.original_name + '</a>' +
                    '<span class="file-size">' + sizeStr + '</span>' +
                    '<span class="file-del" onclick="deleteProjectFile(this, \\'' + f.id + '\\')" title="삭제">✕</span>' +
                    '</div>';
            }}
            if (files.length === 0) {{
                list.innerHTML = '<div class="file-empty">첨부된 파일이 없습니다</div>';
            }}
            var limitMB = 200;
            var usedMB = (totalSize / 1024 / 1024).toFixed(1);
            limit.textContent = '용량: ' + usedMB + 'MB / ' + limitMB + 'MB';
        }}).catch(function() {{}});
}}

function uploadProjectFiles(inputEl) {{
    var modalEl = inputEl.closest('.modal');
    if (!modalEl) return;
    var projectId = modalEl.getAttribute('data-project-id');
    if (!projectId) return;

    var files = inputEl.files;
    if (!files || files.length === 0) return;

    var formData = new FormData();
    for (var i = 0; i < files.length; i++) {{
        if (files[i].size > 20 * 1024 * 1024) {{
            showToast(files[i].name + ': 20MB 제한 초과', true);
            inputEl.value = '';
            return;
        }}
        formData.append('file_' + i, files[i]);
    }}

    showToast('업로드 중...');
    fetch(API + '/projects/' + projectId + '/files', {{
        method: 'POST',
        body: formData
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(result) {{
        inputEl.value = '';
        if (result.errors && result.errors.length > 0) {{
            showToast(result.errors.join('\\n'), true);
        }}
        if (result.uploaded && result.uploaded.length > 0) {{
            showToast(result.uploaded.length + '개 파일 업로드 완료');
        }}
        renderProjectFiles(modalEl, projectId);
    }}).catch(function() {{
        showToast('업로드 실패', true);
        inputEl.value = '';
    }});
}}

function deleteProjectFile(el, fileId) {{
    if (!confirm('파일을 삭제하시겠습니까?')) return;
    var modalEl = el.closest('.modal');
    var projectId = modalEl ? modalEl.getAttribute('data-project-id') : null;
    fetch(API + '/files/' + fileId, {{ method: 'DELETE' }})
        .then(function(r) {{ return r.json(); }})
        .then(function(res) {{
            if (res.error) {{ showToast(res.error, true); return; }}
            showToast('파일 삭제됨');
            if (modalEl && projectId) renderProjectFiles(modalEl, projectId);
        }}).catch(function() {{ showToast('삭제 실패', true); }});
}}

// ── 뷰 토글 (칸반 ↔ 업무간트) ──
function switchToView(view) {{
    var kanban = document.getElementById('kanbanView');
    var taskGantt = document.getElementById('taskGanttView');
    var btnKanban = document.getElementById('btnKanban');
    var btnGantt = document.getElementById('btnGantt');

    if (view === 'kanban') {{
        if (kanban) kanban.style.display = '';
        if (taskGantt) taskGantt.style.display = 'none';
        if (btnKanban) btnKanban.classList.add('active');
        if (btnGantt) btnGantt.classList.remove('active');
    }} else {{
        if (kanban) kanban.style.display = 'none';
        if (taskGantt) taskGantt.style.display = '';
        if (btnKanban) btnKanban.classList.remove('active');
        if (btnGantt) btnGantt.classList.add('active');
    }}
}}

// ── 에이전트 보드 ──
var agentOpen = false;

function toggleAgent() {{
    agentOpen = !agentOpen;
    var panel = document.getElementById('agentPanel');
    var fab = document.getElementById('agentFab');
    if (agentOpen) {{
        panel.classList.add('open');
        fab.classList.add('active');
        fab.textContent = '✕';
        document.getElementById('agentInput').focus();
    }} else {{
        panel.classList.remove('open');
        fab.classList.remove('active');
        fab.textContent = '🤖';
    }}
}}

function toggleCreateMenu() {{
    var menu = document.getElementById('createMenu');
    var fab = document.getElementById('createFab');
    menu.classList.toggle('open');
    fab.classList.toggle('active');
}}

function addAgentMsg(text, type) {{
    var msgs = document.getElementById('agentMessages');
    var div = document.createElement('div');
    div.className = 'agent-msg ' + type;
    div.innerHTML = text.replace(/\\n/g, '<br>').replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>').replace(/\\*(.+?)\\*/g, '<em>$1</em>');
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
}}

function sendAgent(text) {{
    var input = document.getElementById('agentInput');
    var msg = text || input.value.trim();
    if (!msg) return;

    if (!text) {{
        input.value = '';
        input.focus();
    }}

    // 패널 열기
    if (!agentOpen) toggleAgent();

    // 사용자 메시지
    addAgentMsg(msg, 'user');

    // 타이핑 표시
    var typing = document.createElement('div');
    typing.className = 'agent-typing';
    typing.textContent = '🤖 입력 중...';
    var msgs = document.getElementById('agentMessages');
    msgs.appendChild(typing);
    msgs.scrollTop = msgs.scrollHeight;

    // API 호출 (180초 타임아웃)
    var controller = new AbortController();
    var timeoutId = setTimeout(function() {{ controller.abort(); }}, 180000);
    fetch(API + '/agent', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ text: msg }}),
        signal: controller.signal
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
        clearTimeout(timeoutId);
        msgs.removeChild(typing);
        addAgentMsg(data.message || '처리 완료', 'bot');

        // 등록/완료/삭제는 자동 새로고침
        if (data.type === 'register' || data.type === 'complete' || data.type === 'delete') {{
            setTimeout(function() {{ forceRefresh(); }}, 800);
        }}
    }})
    .catch(function(e) {{
        clearTimeout(timeoutId);
        msgs.removeChild(typing);
        if (e.name === 'AbortError') {{
            addAgentMsg('⏰ 요청 시간 초과 (180초)\\n잠시 후 다시 시도해주세요.', 'bot');
        }} else {{
            addAgentMsg('❌ API 서버 연결 실패\\n(' + API + ')', 'bot');
        }}
    }});
}}

function quickRegister() {{
    var input = document.getElementById('agentInput');
    input.value = '업무지시 제목: 담당: 마감: 우선순위:중간 내용: ';
    if (!agentOpen) toggleAgent();
    input.focus();
    input.setSelectionRange(5, 5);
}}

// ── 페이지 로드 시 필터 복원 ──
(function() {{
    // 프로젝트 필터 우선 복원
    var savedProject = sessionStorage.getItem('branup_project');
    if (savedProject) {{
        currentProjectId = savedProject;
        document.querySelectorAll('.filter-btn.proj').forEach(function(btn) {{
            btn.classList.remove('active');
            if (btn.getAttribute('onclick').indexOf("'" + savedProject + "'") !== -1) {{
                btn.classList.add('active');
            }}
        }});
        document.querySelectorAll('.card').forEach(function(card) {{
            var tid = card.getAttribute('data-task-id');
            var task = TASKS_DATA[tid];
            if (task && task.project_id === savedProject) {{
                card.classList.remove('hidden');
            }} else {{
                card.classList.add('hidden');
            }}
        }});
        updateCounts();
        return;  // 프로젝트 선택 중이면 assignee 필터 무시
    }}

    // 프로젝트 전체일 때만 assignee 필터 복원
    var saved = sessionStorage.getItem('branup_filter');
    if (saved && saved !== 'ALL') {{
        document.querySelectorAll('.filter-btn').forEach(function(btn) {{
            btn.classList.remove('active');
            if (btn.textContent.trim() === saved) {{
                btn.classList.add('active');
            }}
        }});
        document.querySelectorAll('.card').forEach(function(card) {{
            if (saved === '긴급') {{
                var p = card.getAttribute('data-priority');
                if (p === '긴급') {{
                    card.classList.remove('hidden');
                }} else {{
                    card.classList.add('hidden');
                }}
            }} else {{
                var a = card.getAttribute('data-assignee') || '';
                if (a.split(/,\\s*/).includes(saved) || a.split(/,\\s*/).includes('모두')) {{
                    card.classList.remove('hidden');
                }} else {{
                    card.classList.add('hidden');
                }}
            }}
        }});
        updateCounts();
    }}
}})();

// ── 검색어 복원 (필터 복원 후, 그 위에 검색 적용) ──
(function() {{
    var sq = sessionStorage.getItem('branup_search');
    if (!sq) return;
    var inp = document.getElementById('searchInput');
    if (inp) {{ inp.value = sq; runSearch(); }}
}})();

// ── 카테고리 필터 복원 (저장/완료/드랍존 등 작업 후 새로고침돼도 유지) ──
(function() {{
    var cat = sessionStorage.getItem('branup_category');
    if (!cat) return;
    currentCategory = null;   // filterCategory 의 토글 로직에 걸리지 않도록 초기화
    filterCategory(cat);
}})();

// ── 프로젝트 모달 ──
function openProjectModal(projectId) {{
    var modalEl = document.createElement('div');
    modalEl.className = 'modal project-modal';
    modalEl.style.zIndex = MODAL_Z_BASE + modalStack.length * 10 + 100;
    modalEl.onclick = function(e) {{ e.stopPropagation(); }};

    var proj = projectId ? (PROJECTS_DATA[projectId] || {{}}) : {{}};
    var isEdit = !!projectId;
    var title = proj.title || '';
    var desc = proj.description || '';
    var status = proj.status || '계획';
    var sd = proj.start_date ? proj.start_date.slice(0,10) : '';
    var ed = proj.expected_end_date ? proj.expected_end_date.slice(0,10) : '';
    var assignees = proj.assignees || '';

    var statusOpts = ['계획','진행','완료','지연','보류'].map(function(s) {{
        return '<option value="' + s + '"' + (status === s ? ' selected' : '') + '>' + s + '</option>';
    }}).join('');

    modalEl.innerHTML =
        '<div class="modal-header">' +
        '<h2 class="modal-title">' + (isEdit ? '프로젝트 상세' : '새 프로젝트') + '</h2>' +
        '<button class="modal-close" onclick="closeModal(this.parentElement.parentElement)">&times;</button>' +
        '</div>' +
        '<div class="modal-body">' +
        '<label>제목</label><input type="text" class="proj-title" value="' + title + '" placeholder="프로젝트명">' +
        '<label>설명</label><textarea class="proj-desc" rows="3" placeholder="프로젝트 설명...">' + desc + '</textarea>' +
        '<label>상태</label><select class="proj-status">' + statusOpts + '</select>' +
        '<label>시작일</label><input type="date" class="proj-start" value="' + sd + '">' +
        '<label>예상 종료일</label><input type="date" class="proj-end" value="' + ed + '">' +
        '<label>담당자</label><input type="text" class="proj-assignees" value="' + assignees + '" placeholder="쉼표로 구분">' +
        '<div class="modal-field file-section" style="margin-top:12px">' +
        '<label>📎 첨부파일</label>' +
        '<div class="file-dropzone" onclick="this.querySelector(\\'input\\').click()" ondragover="event.preventDefault();this.classList.add(\\'dragover\\')" ondragleave="this.classList.remove(\\'dragover\\')" ondrop="event.preventDefault();this.classList.remove(\\'dragover\\');var inp=this.querySelector(\\'input\\');inp.files=event.dataTransfer.files;inp.onchange()">' +
        '<span>클릭 또는 드래그로 파일 추가</span>' +
        '<input type="file" class="file-input" multiple onchange="uploadProjectFiles(this)" style="display:none">' +
        '</div>' +
        '<div class="file-list"></div>' +
        '<div class="file-limit-info"></div>' +
        '</div>' +
        (isEdit ? '<div style="margin-top:12px"><button onclick="addProjectTaskFromModal(this)" style="padding:8px 16px;background:#1f6feb;color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;width:100%">➕ 하위 업무 추가</button></div>' : '') +
        '<div class="btn-row">' +
        '<button class="btn-primary" onclick="saveProjectFromModal(this)">💾 ' + (isEdit ? '저장' : '생성') + '</button>' +
        (isEdit && status !== '완료' ? '<button class="btn-complete" onclick="completeProjectFromModal(this)">✅ 완료처리</button>' : '') +
        (isEdit && status === '완료' ? '<button class="btn-uncomplete" onclick="uncompleteProjectFromModal(this)">↩ 완료취소</button>' : '') +
        (isEdit ? '<button class="btn-danger" onclick="deleteProjectFromModal(this)">🗑 삭제</button>' : '') +
        '<button class="btn-cancel" style="background:#1c1f2a;color:#8b949e" onclick="closeModal(this.closest(&apos;.modal&apos;))">취소</button>' +
        '</div></div>';

    modalEl.setAttribute('data-project-id', projectId || '');

    document.getElementById('modalOverlay').appendChild(modalEl);
    document.getElementById('modalOverlay').classList.add('active');
    modalStack.push({{ taskId: null, el: modalEl }});

    if (isEdit) {{
        renderProjectFiles(modalEl, projectId);
    }}
}}

function saveProject(projectId, modalEl) {{
    var data = {{
        title: modalEl.querySelector('.proj-title').value.trim(),
        description: modalEl.querySelector('.proj-desc').value.trim(),
        status: modalEl.querySelector('.proj-status').value,
        start_date: modalEl.querySelector('.proj-start').value || null,
        expected_end_date: modalEl.querySelector('.proj-end').value || null,
        assignees: modalEl.querySelector('.proj-assignees').value.trim(),
        _editor: (document.querySelector('.filter-btn:not(.proj):not(.urgent).active') || {{}}).textContent || ''
    }};
    if (!data.title) {{ showToast('제목은 필수입니다', true); return; }}

    var method = projectId ? 'PATCH' : 'POST';
    var url = projectId ? (API + '/projects/' + projectId) : (API + '/projects');

    fetch(url, {{
        method: method, headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(data)
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(result) {{
        if (result.error) {{ showToast('오류: ' + result.error, true); return; }}
        showToast(projectId ? '프로젝트 저장 완료!' : '프로젝트 생성 완료!');
        // 직원 필터 상태 저장 + 프로젝트 전체 전환
        var ab = document.querySelector('.filter-btn:not(.proj).active');
        if (ab) sessionStorage.setItem('branup_filter', ab.textContent.trim());
        filterByProject(null);
        closeModal(modalEl);
        setTimeout(function() {{ forceRefresh(); }}, 500);
    }})
    .catch(function() {{ showToast('⚠️ API 서버 연결 필요', true); }});
}}

function saveProjectFromModal(btn) {{
    var modalEl = btn.closest('.modal');
    var projectId = modalEl.getAttribute('data-project-id') || '';
    saveProject(projectId, modalEl);
}}

function deleteProject(projectId, modalEl) {{
    if (!confirm('프로젝트를 삭제하시겠습니까?\\n하위 업무는 프로젝트에서 해제됩니다.')) return;
    fetch(API + '/projects/' + projectId, {{ method: 'DELETE' }})
    .then(function(r) {{ return r.json(); }})
    .then(function(result) {{
        if (result.error) {{ showToast('삭제 실패: ' + result.error, true); return; }}
        showToast('프로젝트 삭제 완료!');
        closeModal(modalEl);
        setTimeout(function() {{ forceRefresh(); }}, 500);
    }})
    .catch(function() {{ showToast('⚠️ API 서버 연결 필요', true); }});
}}

function deleteProjectFromModal(btn) {{
    var modalEl = btn.closest('.modal');
    var projectId = modalEl.getAttribute('data-project-id');
    if (!projectId) {{ showToast('프로젝트 ID 없음', true); return; }}
    deleteProject(projectId, modalEl);
}}

function addProjectTask(projectId, modalEl) {{
    var title = prompt('업무 제목을 입력하세요:');
    if (!title || !title.trim()) return;
    fetch(API + '/projects/' + projectId + '/tasks', {{
        method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ title: title.trim() }})
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(result) {{
        if (result.error) {{ showToast('추가 실패: ' + result.error, true); return; }}
        showToast('업무 추가 완료! #' + result.display_num);
        closeModal(modalEl);
        setTimeout(function() {{ forceRefresh(); }}, 500);
    }})
    .catch(function() {{ showToast('⚠️ API 서버 연결 필요', true); }});
}}

function addProjectTaskFromModal(btn) {{
    var modalEl = btn.closest('.modal');
    var projectId = modalEl.getAttribute('data-project-id');
    if (!projectId) {{ showToast('프로젝트 ID 없음', true); return; }}
    addProjectTask(projectId, modalEl);
}}

// ── 프로젝트 완료처리 / 완료취소 ──
function completeProjectFromModal(btn) {{
    var modalEl = btn.closest('.modal');
    var pid = modalEl.getAttribute('data-project-id');
    if (!pid || !confirm('이 프로젝트를 완료 처리하시겠습니까?')) return;
    patchProjectStatus(pid, '완료', modalEl, '완료 처리되었습니다!');
}}

function uncompleteProjectFromModal(btn) {{
    var modalEl = btn.closest('.modal');
    var pid = modalEl.getAttribute('data-project-id');
    if (!pid || !confirm('완료를 취소하고 진행중으로 되돌리시겠습니까?')) return;
    patchProjectStatus(pid, '진행', modalEl, '완료가 취소되었습니다!');
}}

function patchProjectStatus(pid, status, modalEl, okMsg) {{
    var editor = ((document.querySelector('.filter-btn:not(.proj):not(.urgent).active') || {{}}).textContent || '').trim();
    if (editor !== '이상원' && editor !== '이향석') {{
        showToast('완료처리는 이상원 또는 이향석만 가능합니다. 상단 필터에서 본인 이름을 선택 후 다시 시도하세요.', true);
        return;
    }}
    fetch(API + '/projects/' + pid, {{
        method: 'PATCH', headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ status: status, _editor: editor.trim() }})
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(res) {{
        if (res.error) {{ showToast('오류: ' + res.error, true); return; }}
        // 완료처리 후 새로고침해도 본인(이상원/이향석) 필터 선택이 유지되도록 보존
        try {{ sessionStorage.setItem('branup_filter', editor); }} catch(e) {{}}
        showToast(okMsg);
        closeModal(modalEl);
        setTimeout(function() {{ forceRefresh(); }}, 500);
    }})
    .catch(function() {{ showToast('⚠️ API 서버 연결 필요', true); }});
}}
</script>
</body>
</html>"""
    return html


if __name__ == "__main__":
    html = render()
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    # 웹 서빙용 index.html도 함께 생성
    index_path = Path(DATA_DIR).parent / "index.html"
    index_path.write_text(html, encoding="utf-8")
    # 콘솔 인코딩(cp949 등)이 이모지를 못 찍어도 종료코드가 0이 되도록 보호
    # (update.ps1/update-test.ps1 이 $LASTEXITCODE 로 빌드 성공을 판정하므로 중요)
    try:
        print(f"✅ HTML 대시보드 생성 완료: {OUTPUT_PATH}")
        print(f"   웹 서빙: {index_path}")
    except UnicodeEncodeError:
        print("HTML dashboard generated:", OUTPUT_PATH)
        print("  web serving:", index_path)
