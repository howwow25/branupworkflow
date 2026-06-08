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

sys.path.insert(0, str(Path(__file__).parent))
import os as _os_dash
if _os_dash.environ.get("BRANUP_API_URL"):
    from branup_api import get_active_tasks, get_completed_tasks
else:
    from db import get_active_tasks, get_completed_tasks


def dday(due_str):
    if not due_str: return None
    try:
        from datetime import timezone, timedelta
        KST = timezone(timedelta(hours=9))
        due_date = datetime.strptime(due_str[:10], "%Y-%m-%d").date()
        return (due_date - datetime.now(KST).date()).days
    except Exception:
        return None


def group_tasks(tasks):
    groups = {"delayed": [], "today": [], "d3": [], "d7": [], "upcoming": [], "no_due": []}
    for t in tasks:
        dd = dday(t.get("due_at"))
        if dd is None:        groups["no_due"].append((t, None))
        elif dd < 0:          groups["delayed"].append((t, dd))
        elif dd == 0:         groups["today"].append((t, dd))
        elif dd <= 3:         groups["d3"].append((t, dd))
        elif dd <= 7:         groups["d7"].append((t, dd))
        else:                 groups["upcoming"].append((t, dd))
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


def render_card(t, dd):
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

    return f"""<div class="card" data-assignee="{assignee}" data-priority="{prio}" data-task-id="{task_id}" onclick="openModal('{task_id}')">
    <span class="dday badge-{css}">#{num}</span>{prio_html}
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


def render_completed_card(t, closed_date, label):
    title = esc(t.get("title", ""))
    assignee = esc(t.get("assignee") or "미정")
    closed_str = closed_date.strftime("%m/%d")
    task_id = t.get("id", "")
    prio = t.get("priority", "") or ""

    return f"""<div class="card done" data-assignee="{assignee}" data-priority="{prio}" data-task-id="{task_id}" onclick="openModal('{task_id}')">
    <span class="dday badge-done">{label}</span>
    <div class="title">{title}</div>
    <div class="meta">
        <span class="assignee">👤 {assignee}</span>
        <span class="due">✅ {closed_str} 완료</span>
    </div>
</div>"""


def render():
    tasks = get_active_tasks()
    groups = group_tasks(tasks)
    completed = get_completed_tasks()
    c_weeks, c_months = group_completed(completed)

    total = len(tasks)
    delayed_count = len(groups["delayed"])
    today_count = len(groups["today"])
    nodue_count = len(groups["no_due"])
    done_count = len(completed)

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
    all_tasks = {t["id"]: {k: t[k] for k in ["id","title","status","summary","feedback","due_at","assignee","priority","created_at","updated_at","closed_at","display_num"]} for t in tasks + completed}
    tasks_json = json.dumps(all_tasks, ensure_ascii=False)

    columns = [
        ("🔥 지연", "delayed", groups["delayed"]),
        ("⬜ 미정", "no_due", groups["no_due"]),
        ("🚨 오늘마감", "today", groups["today"]),
        ("⚠️ D-3", "d3", groups["d3"]),
        ("📋 D-7", "d7", groups["d7"]),
        ("🟢 여유", "upcoming", groups["upcoming"]),
    ]

    col_html = ""
    for title, key, items in columns:
        cards_parts = []
        for t, dd in sorted(items, key=lambda x: x[1] or 999):
            cards_parts.append(render_card(t, dd))
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
                cards = "".join(render_completed_card(t, cd, week_labels[w]) for t, cd in items)
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
                cards = "".join(render_completed_card(t, cd, month_labels[m]) for t, cd in items)
                if not cards:
                    cards = '<div class="empty">없음</div>'
                completed_html += f"""<div class="column" data-col="month-{m}">
    <div class="col-header">{month_labels[m]} <span class="count">{len(items)}</span></div>
    {cards}
</div>"""
            completed_html += '</div>'

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
.header .sub {{ color: #8b949e; font-size: 13px; margin-top: 4px; }}
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
.refresh-btn {{
    background: none; border: 1px solid #2a2d3a;
    border-radius: 8px; padding: 4px 10px;
    font-size: 18px; cursor: pointer;
    transition: all 0.2s; vertical-align: middle;
}}
.refresh-btn:hover {{
    background: #2a2d3a; border-color: #58a6ff;
    transform: rotate(90deg);
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
.modal-field textarea {{
    resize: vertical; min-height: 80px;
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
.btn-cancel {{
    background: #1c1f2a; color: #8b949e;
}}
.btn-cancel:hover {{ color: #e1e4e8; }}
.btn-save.disabled, .btn-complete.disabled, .btn-delete.disabled {{
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
</style>
</head>
<body>
<div class="header">
    <h1>📊 브랜업 대시보드 <button class="refresh-btn" onclick="forceRefresh()" title="강력 새로고침 (캐시 무시)">🔄</button></h1>
    <div class="sub">마지막 갱신: {now_str} | 진행 <span id="hdr-active">{total}</span>건 · 완료 <span id="hdr-done">{done_count}</span>건</div>
</div>
<div class="filters">{filter_btns}</div>
<div class="stats">
    <div class="stat danger" id="stat-delayed">
        <div class="num">{delayed_count}</div>
        <div class="label">지연</div>
    </div>
    <div class="stat" id="stat-today">
        <div class="num">{today_count}</div>
        <div class="label">오늘 마감</div>
    </div>
    <div class="stat warn" id="stat-nodue">
        <div class="num">{nodue_count}</div>
        <div class="label">마감 미정</div>
    </div>
    <div class="stat" id="stat-active">
        <div class="num">{total}</div>
        <div class="label">진행중</div>
    </div>
    <div class="stat done" id="stat-done">
        <div class="num">{done_count}</div>
        <div class="label">완료</div>
    </div>
</div>
<div class="board">
{col_html}
</div>
{completed_html}

<!-- ── 모달 ── -->
<div class="modal-overlay" id="modalOverlay" onclick="closeModal(event)">
    <div class="modal" onclick="event.stopPropagation()">
        <div class="modal-header">
            <h2 id="modalTitle">업무 상세</h2>
            <button class="modal-close" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
            <div class="modal-status" id="modalMeta"></div>
            <div class="modal-field">
                <label>제목</label>
                <input type="text" id="editTitle" placeholder="업무 제목">
            </div>
            <div class="modal-field">
                <label>담당자</label>
                <select id="editAssignee">
                    <option value="">미정</option>
                    {''.join(f'<option value="{a}">{a}</option>' for a in sorted_assignees)}
                </select>
            </div>
            <div class="modal-field">
                <label>마감일</label>
                <input type="date" id="editDue">
            </div>
            <div class="modal-field" id="contentField">
                <label>📝 내용</label>
                <textarea id="editSummary" placeholder="업무 내용..." rows="4"></textarea>
            </div>
            <div class="modal-field" id="feedbackField" style="display:none">
                <label>💬 피드백</label>
                <textarea id="editFeedback" placeholder="완료 후기, 결과, 특이사항 등..."></textarea>
            </div>
            <div class="modal-field">
                <label>우선순위</label>
                <select id="editPriority">
                    <option value="긴급">🔴 긴급</option>
                    <option value="높음">🟠 높음</option>
                    <option value="중간" selected>🟡 중간</option>
                    <option value="낮음">🟢 낮음</option>
                </select>
            </div>
            <div class="modal-actions">
                <button class="btn-save" id="btnSave" onclick="saveTask()">💾 저장</button>
                <button class="btn-save" id="btnCreate" onclick="createTask()" style="display:none">➕ 추가</button>
                <button class="btn-complete" id="btnComplete" onclick="completeTask()">✅ 완료 처리</button>
                <button class="btn-delete" id="btnDelete" onclick="deleteTask()">🗑 삭제</button>
                <button class="btn-cancel" onclick="closeModal()">취소</button>
            </div>
        </div>
    </div>
</div>
<div class="toast" id="toast"></div>

<!-- ── 에이전트 보드 ── -->
<button class="create-fab" onclick="openCreateModal()" title="새 업무">＋</button>
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
var API = (window.location.protocol === 'file:' || window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost') ? 'http://127.0.0.1:{API_PORT}/api' : (window.location.origin + '/api');
var currentTaskId = null;
var isStaticHost = false;
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
                document.querySelectorAll('.btn-save, .btn-complete, .btn-delete').forEach(function(btn) {{
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
    if (API.indexOf(':8800') !== -1) {{
        window.location.href = API.replace('/api', '/index.html');
        return;
    }}
    var url = new URL(window.location.href);
    url.searchParams.set('_', Date.now());
    window.location.href = url.toString();
}}

function countVisible(col) {{
    return col.querySelectorAll('.card:not(.hidden)').length;
}}

function updateCounts() {{
    var statMap = {{
        'delayed': 'stat-delayed',
        'today': 'stat-today',
        'no_due': 'stat-nodue'
    }};

    document.querySelectorAll('.column[data-col]').forEach(function(col) {{
        var key = col.getAttribute('data-col');
        var cnt = countVisible(col);
        var badge = col.querySelector('.count');
        if (badge) badge.textContent = cnt;

        if (statMap[key]) {{
            var el = document.getElementById(statMap[key]);
            if (el) el.querySelector('.num').textContent = cnt;
        }}
    }});

    var activeTotal = document.querySelectorAll('.card:not(.done):not(.hidden)').length;
    var doneTotal = document.querySelectorAll('.column[data-col^="week-"] .card.done:not(.hidden)').length;

    var elActive = document.getElementById('stat-active');
    if (elActive) elActive.querySelector('.num').textContent = activeTotal;

    var elDone = document.getElementById('stat-done');
    if (elDone) elDone.querySelector('.num').textContent = doneTotal;

    var hdrActive = document.getElementById('hdr-active');
    if (hdrActive) hdrActive.textContent = activeTotal;
    var hdrDone = document.getElementById('hdr-done');
    if (hdrDone) hdrDone.textContent = doneTotal;
}}

function filterAssignee(name) {{
    document.querySelectorAll('.filter-btn').forEach(function(btn) {{
        btn.classList.remove('active');
    }});
    event.target.classList.add('active');

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

function showToast(msg, isError) {{
    var t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast ' + (isError ? 'error' : '');
    setTimeout(function() {{ t.classList.add('show'); }}, 10);
    setTimeout(function() {{ t.classList.remove('show'); }}, 2500);
}}

// ── 모달 ──
function populateModal(task) {{
    // edit 모드로 복원
    modalMode = 'edit';
    document.getElementById('btnSave').style.display = '';
    document.getElementById('btnComplete').style.display = '';
    document.getElementById('btnDelete').style.display = '';
    document.getElementById('btnCreate').style.display = 'none';
    document.getElementById('modalMeta').style.display = '';
    document.getElementById('contentField').style.display = '';
    document.getElementById('feedbackField').style.display = '';
    // 정적 호스트 비활성화 재적용
    if (isStaticHost) {{
        document.querySelectorAll('.btn-save, .btn-complete, .btn-delete').forEach(function(btn) {{ btn.classList.add('disabled'); }});
    }}

    document.getElementById('modalTitle').textContent = '#' + task.display_num + ' 업무 상세';
    document.getElementById('editTitle').value = task.title || '';
    document.getElementById('editDue').value = task.due_at ? task.due_at.slice(0,10) : '';

    var sel = document.getElementById('editAssignee');
    var found = false;
    for (var i = 0; i < sel.options.length; i++) {{
        if (sel.options[i].value === (task.assignee || '')) {{
            sel.selectedIndex = i;
            found = true;
            break;
        }}
    }}
    if (!found && task.assignee) {{
        var opt = document.createElement('option');
        opt.value = task.assignee;
        opt.textContent = task.assignee;
        opt.selected = true;
        sel.appendChild(opt);
    }}

    document.getElementById('editSummary').value = task.summary || task.title || '';

    // 내용 필드 항상 표시
    var contentField = document.getElementById('contentField');
    contentField.style.display = '';

    document.getElementById('editFeedback').value = task.feedback || '';
    var feedbackField = document.getElementById('feedbackField');
    if (task.status === '완료') {{
        feedbackField.style.display = '';
    }} else {{
        feedbackField.style.display = 'none';
    }}

    var prio = task.priority || '중간';
    document.getElementById('editPriority').value = prio;

    var created = task.created_at ? task.created_at.slice(0,16).replace('T',' ') : '-';
    var updated = task.updated_at ? task.updated_at.slice(0,16).replace('T',' ') : '-';
    var closed = task.closed_at ? ' | <strong>완료:</strong> ' + task.closed_at.slice(0,16).replace('T',' ') : '';
    document.getElementById('modalMeta').innerHTML =
        '<strong>상태:</strong> ' + (task.status || '진행중') +
        ' &nbsp;|&nbsp; <strong>생성:</strong> ' + created +
        ' &nbsp;|&nbsp; <strong>수정:</strong> ' + updated + closed;

    var btnComplete = document.getElementById('btnComplete');
    if (task.status === '완료') {{
        btnComplete.style.display = 'none';
    }} else {{
        btnComplete.style.display = '';
    }}

    document.getElementById('modalOverlay').classList.add('active');
}}

function openModal(taskId) {{
    currentTaskId = taskId;

    // 1) 내장 데이터 우선 조회 (API 없이 즉시 열림)
    var local = TASKS_DATA[taskId];
    if (local) {{
        populateModal(local);
    }}

    // 2) 백그라운드로 API 조회 → 최신 데이터로 갱신 시도
    fetch(API + '/tasks/' + taskId)
        .then(function(r) {{ return r.json(); }})
        .then(function(task) {{
            if (task.error) return;
            populateModal(task);
        }})
        .catch(function(e) {{
            // API 없으면 내장 데이터만으로 충분 (조용히 무시)
        }});
}}

function closeModal(e) {{
    if (e && e.target !== document.getElementById('modalOverlay')) return;
    document.getElementById('modalOverlay').classList.remove('active');
    currentTaskId = null;
    modalMode = 'edit';
}}

// ── 새 업무 생성 ──
function openCreateModal() {{
    modalMode = 'create';
    document.getElementById('modalTitle').textContent = '✨ 새 업무';
    document.getElementById('editTitle').value = '';
    document.getElementById('editDue').value = '';
    document.getElementById('editAssignee').selectedIndex = 0;
    document.getElementById('editSummary').value = '';
    document.getElementById('editFeedback').value = '';
    document.getElementById('editPriority').value = '중간';
    document.getElementById('modalMeta').style.display = 'none';
    document.getElementById('contentField').style.display = '';
    document.getElementById('feedbackField').style.display = 'none';
    document.getElementById('btnSave').style.display = 'none';
    document.getElementById('btnComplete').style.display = 'none';
    document.getElementById('btnDelete').style.display = 'none';
    document.getElementById('btnCreate').style.display = '';
    document.getElementById('modalOverlay').classList.add('active');
}}

function createTask() {{
    var title = document.getElementById('editTitle').value.trim();
    if (!title) {{
        showToast('제목은 필수입니다', true);
        return;
    }}
    var data = {{
        title: title,
        assignee: document.getElementById('editAssignee').value,
        due_at: document.getElementById('editDue').value || null,
        summary: document.getElementById('editSummary').value.trim(),
        priority: document.getElementById('editPriority').value
    }};

    fetch(API + '/tasks', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(data)
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(task) {{
        if (task.error) {{
            showToast('등록 실패: ' + task.error, true);
            return;
        }}
        showToast('✨ #' + task.display_num + ' 등록 완료!');
        closeModal();
        setTimeout(function() {{ forceRefresh(); }}, 500);
    }})
    .catch(function(e) {{
        showToast('⚠️ API 서버 연결 실패', true);
    }});
}}

function saveTask() {{
    if (!currentTaskId) return;
    var data = {{
        title: document.getElementById('editTitle').value.trim(),
        assignee: document.getElementById('editAssignee').value,
        due_at: document.getElementById('editDue').value || null,
        summary: document.getElementById('editSummary').value.trim(),
        feedback: document.getElementById('editFeedback').value.trim(),
        priority: document.getElementById('editPriority').value
    }};
    if (!data.title) {{
        showToast('제목은 필수입니다', true);
        return;
    }}

    fetch(API + '/tasks/' + currentTaskId, {{
        method: 'PATCH',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(data)
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(task) {{
        if (task.error) {{
            showToast('저장 실패: ' + task.error, true);
            return;
        }}
        showToast('저장 완료!');
        setTimeout(function() {{ forceRefresh(); }}, 500);
    }})
    .catch(function(e) {{
        showToast('⚠️ 현재 환경에서는 편집이 불가능합니다 (API 서버 연결 필요)', true);
    }});
}}

function completeTask() {{
    if (!currentTaskId) return;
    if (!confirm('정말 완료 처리하시겠습니까?')) return;

    fetch(API + '/tasks/' + currentTaskId + '/complete', {{
        method: 'POST'
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(task) {{
        if (task.error) {{
            showToast('완료 처리 실패', true);
            return;
        }}
        showToast('완료 처리되었습니다!');
        setTimeout(function() {{ forceRefresh(); }}, 500);
    }})
    .catch(function(e) {{
        showToast('⚠️ 현재 환경에서는 완료 처리가 불가능합니다 (API 서버 연결 필요)', true);
    }});
}}

function deleteTask() {{
    if (!currentTaskId) return;
    if (!confirm('정말 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.')) return;

    fetch(API + '/tasks/' + currentTaskId, {{
        method: 'DELETE'
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
        if (data.error) {{
            showToast('삭제 실패', true);
            return;
        }}
        showToast('삭제 완료!');
        document.getElementById('modalOverlay').classList.remove('active');
        currentTaskId = null;
        setTimeout(function() {{ forceRefresh(); }}, 500);
    }})
    .catch(function(e) {{
        showToast('⚠️ 현재 환경에서는 삭제가 불가능합니다 (API 서버 연결 필요)', true);
    }});
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
    var saved = sessionStorage.getItem('branup_filter');
    if (saved && saved !== 'ALL') {{
        document.querySelectorAll('.filter-btn').forEach(function(btn) {{
            btn.classList.remove('active');
            if (btn.textContent.trim() === saved) {{
                btn.classList.add('active');
            }}
        }});
        document.querySelectorAll('.card').forEach(function(card) {{
            var a = card.getAttribute('data-assignee') || '';
            if (a.split(/,\\\\s*/).includes(saved) || a.split(/,\\\\s*/).includes('모두')) {{
                card.classList.remove('hidden');
            }} else {{
                card.classList.add('hidden');
            }}
        }});
        updateCounts();
    }}
}})();
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
    print(f"✅ HTML 대시보드 생성 완료: {OUTPUT_PATH}")
    print(f"   웹 서빙: {index_path}")
