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


def render_card(t, dd, task_lookup=None):
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

    return f"""<div class="card" data-assignee="{assignee}" data-priority="{prio}" data-task-id="{task_id}" onclick="openModal('{task_id}')">
    <span class="dday badge-{css}">#{num}</span>{prio_html}{related_html}
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
    num = t.get("display_num", "?")

    return f"""<div class="card done" data-assignee="{assignee}" data-priority="{prio}" data-task-id="{task_id}" onclick="openModal('{task_id}')">
    <span class="dday badge-done">#{num}</span>
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
    all_tasks = {t["id"]: {k: t[k] for k in ["id","title","status","summary","feedback","due_at","assignee","priority","created_at","updated_at","closed_at","display_num","related_tasks"]} for t in tasks + completed}
    tasks_json = json.dumps(all_tasks, ensure_ascii=False)

    # ── display_num → task lookup (연관업무 색상 표시용) ──
    task_lookup = {}
    for t in tasks + completed:
        dn = t.get("display_num")
        if dn:
            task_lookup[dn] = t

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
            cards_parts.append(render_card(t, dd, task_lookup))
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
    <h1>📊 브랜업 대시보드</h1>
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
<div class="modal-overlay" id="modalOverlay" onclick="closeModal(event)"></div>
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
    sessionStorage.setItem('branup_filter', name);
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
        '<div class="modal-field"><label>🔗 연관업무</label>' +
        '<div class="related-tasks" style="display:flex;flex-wrap:wrap;gap:6px;min-height:28px;align-items:center"></div>' +
        '<div style="display:flex;gap:6px;margin-top:8px">' +
        '<input type="number" class="related-input" placeholder="업무번호" onkeydown="if(event.key===&quot;Enter&quot;)addRelatedTask(this)" style="width:90px;padding:6px 10px;background:#0f1117;border:1px solid #2a2d3a;border-radius:6px;color:#e1e4e8;font-size:13px">' +
        '<button onclick="addRelatedTask(this)" style="padding:6px 12px;background:#1f6feb;color:#fff;border:none;border-radius:6px;font-size:12px;cursor:pointer;font-weight:600">추가</button>' +
        '</div></div>' +
        '<div class="modal-actions">' +
        '<button class="btn-save modal-btn-save" onclick="saveTask(this)">💾 저장</button>' +
        '<button class="btn-save modal-btn-create" onclick="createTask()" style="display:none">➕ 추가</button>' +
        '<button class="btn-complete modal-btn-complete" onclick="completeTask(this)">✅ 완료 처리</button>' +
        '<button class="btn-delete modal-btn-delete" onclick="deleteTask(this)">🗑 삭제</button>' +
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
    var btnComplete = modalEl.querySelector('.modal-btn-complete');
    btnComplete.style.display = (task.status === '완료') ? 'none' : '';

    // 연관업무 렌더링
    renderRelatedButtonsInModal(modalEl, task.related_tasks || '');

    if (isStaticHost) {{
        modalEl.querySelectorAll('.btn-save, .btn-complete, .btn-delete').forEach(function(btn) {{ btn.classList.add('disabled'); }});
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
    modalEl.querySelector('.modal-btn-delete').style.display = 'none';
    modalEl.querySelector('.modal-btn-create').style.display = '';

    var sel = modalEl.querySelector('.edit-assignee');
    for (var i = 0; i < sel.options.length; i++) {{ sel.options[i].selected = false; }}
    var activeBtn = document.querySelector('.filter-btn.active');
    var filterName = activeBtn ? activeBtn.textContent.trim() : '';
    var validAssignees = ['강경철', '노수민', '이상원', '이향석', '전경표', '모두'];
    if (validAssignees.indexOf(filterName) !== -1) {{
        for (var i = 0; i < sel.options.length; i++) {{
            if (sel.options[i].value === filterName) {{ sel.options[i].selected = true; break; }}
        }}
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
        priority: modalEl.querySelector('.edit-priority').value
    }};
    fetch(API + '/tasks', {{
        method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(data)
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(task) {{
        if (task.error) {{ showToast('등록 실패: ' + task.error, true); return; }}
        showToast('✨ #' + task.display_num + ' 등록 완료!');
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
        priority: modalEl.querySelector('.edit-priority').value
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
    fetch(API + '/tasks/' + m.taskId + '/complete', {{ method: 'POST' }})
    .then(function(r) {{ return r.json(); }})
    .then(function(task) {{
        if (task.error) {{ showToast('완료 처리 실패', true); return; }}
        showToast('완료 처리되었습니다!');
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
