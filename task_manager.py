#!/usr/bin/env python3
"""
task_manager.py - 통합 업무 관리 스크립트
모델이 복잡한 인자 없이 간단하게 호출 가능

사용법:
  python3 task_manager.py list
  python3 task_manager.py list --assignee "이향석"
  python3 task_manager.py register --chat-id "-5166407409" --text "위시트랜드2.0 벤치마킹 제목:XXX 담당:XXX 마감:XXX"
  python3 task_manager.py register --chat-id "-5166407409" --title "제목" --assignee "담당자" --due "2026-06-01"
"""
import sys
import re
import json
import argparse
import importlib.util
import subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))

_scripts = Path(__file__).parent

def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, str(_scripts / fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# BRANUP_API_URL이 설정되어 있으면 원격 API 사용, 아니면 로컬 DB 사용
import os as _os
if _os.environ.get("BRANUP_API_URL"):
    _db = _load("branup_api", "branup_api.py")
    _ws = None
else:
    _db = _load("branup_db", "db.py")
    _ws = _load("branup_ws", "workspace.py")


def cmd_list(assignee=None):
    tasks = _db.get_active_tasks()
    if not tasks:
        print("등록된 진행 중 업무가 없습니다.")
        return

    if assignee:
        tasks = [t for t in tasks if t.get("assignee") and assignee in t["assignee"]]
        if not tasks:
            print(f"{assignee} 담당 업무가 없습니다.")
            return

    print(f"📋 {'전체' if not assignee else assignee + ' 담당'} 업무 목록 ({len(tasks)}건)")
    for i, t in enumerate(tasks, 1):
        due = t.get("due_at") or "미정"
        assignee_str = t.get("assignee") or "미정"
        status = t.get("status", "진행중")
        num = t.get("display_num", i)
        print(f"#{num} {t['title']}")
        print(f"   담당: {assignee_str} | 마감: {due} | 상태: {status}")


def dday(due_str):
    """D-day 문자열 계산. 지연이면 +N, 남았으면 -N, 없으면 None"""
    if not due_str:
        return None
    try:
        due_date = datetime.strptime(due_str[:10], "%Y-%m-%d").date()
        delta = (due_date - datetime.now(_KST).date()).days
        return delta
    except Exception:
        return None


def cmd_dashboard():
    tasks = _db.get_active_tasks()
    if not tasks:
        print("등록된 진행 중 업무가 없습니다.")
        return

    today = datetime.now(_KST).strftime("%Y년 %m월 %d일 (%a)")
    weekdays = {"Mon": "월", "Tue": "화", "Wed": "수", "Thu": "목", "Fri": "금", "Sat": "토", "Sun": "일"}
    for en, ko in weekdays.items():
        today = today.replace(en, ko)

    # D-day 계산 및 그룹핑
    delayed = []    # 지연 (dday < 0)
    today_due = []  # 오늘 마감 (dday == 0)
    d3 = []         # D-1 ~ D-3
    d7 = []         # D-4 ~ D-7
    upcoming = []   # D-8 이상
    no_due = []     # 마감 미정

    for t in tasks:
        dd = dday(t.get("due_at"))
        if dd is None:
            no_due.append((t, None))
        elif dd < 0:
            delayed.append((t, dd))
        elif dd == 0:
            today_due.append((t, dd))
        elif dd <= 3:
            d3.append((t, dd))
        elif dd <= 7:
            d7.append((t, dd))
        else:
            upcoming.append((t, dd))

    # 통계
    total = len(tasks)
    assignees = {}
    for t in tasks:
        a = t.get("assignee") or "미정"
        assignees[a] = assignees.get(a, 0) + 1

    print(f"📊 브랜업 대시보드")
    print(f"📅 {today}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"전체: {total}건 | 지연: {len(delayed)}건 | 오늘마감: {len(today_due)}건")
    print()

    # 담당자별 요약
    print("👥 담당자별 현황")
    for a, cnt in sorted(assignees.items(), key=lambda x: -x[1]):
        bar = "█" * min(cnt, 20)
        print(f"  {a}: {cnt}건 {bar}")
    print()

    # 🔥 지연
    all_items = []
    for items in [delayed, today_due, d3, d7, upcoming, no_due]:
        all_items.extend(items)

    if delayed:
        print("━━━ 🔥 지연 ━━━")
        for t, dd in sorted(delayed, key=lambda x: x[1]):
            a = t.get("assignee") or "미정"
            due = t.get("due_at", "")[:10]
            num = t.get("display_num", "?")
            print(f"  #{num} D+{abs(dd)} | {t['title']}")
            print(f"         담당: {a} | 마감: {due}")
        print()

    # 🚨 오늘 마감
    if today_due:
        print("━━━ 🚨 오늘 마감 ━━━")
        for t, dd in today_due:
            a = t.get("assignee") or "미정"
            due = t.get("due_at", "")[:10]
            num = t.get("display_num", "?")
            print(f"  #{num} D-DAY | {t['title']}")
            print(f"         담당: {a} | 마감: {due}")
        print()

    # ⚠️ D-3 이내
    if d3:
        print("━━━ ⚠️ D-3 이내 ━━━")
        for t, dd in sorted(d3, key=lambda x: x[1]):
            a = t.get("assignee") or "미정"
            due = t.get("due_at", "")[:10]
            num = t.get("display_num", "?")
            print(f"  #{num} D-{dd} | {t['title']}")
            print(f"         담당: {a} | 마감: {due}")
        print()

    # 📋 D-7 이내
    if d7:
        print("━━━ 📋 D-7 이내 ━━━")
        for t, dd in sorted(d7, key=lambda x: x[1]):
            a = t.get("assignee") or "미정"
            due = t.get("due_at", "")[:10]
            num = t.get("display_num", "?")
            print(f"  #{num} D-{dd} | {t['title']}")
            print(f"         담당: {a} | 마감: {due}")
        print()

    # 🟢 여유
    if upcoming:
        print("━━━ 🟢 여유 있음 ━━━")
        for t, dd in sorted(upcoming, key=lambda x: x[1]):
            a = t.get("assignee") or "미정"
            due = t.get("due_at", "")[:10]
            num = t.get("display_num", "?")
            print(f"  #{num} D-{dd} | {t['title']}")
            print(f"         담당: {a} | 마감: {due}")
        print()

    # ⬜ 마감 미정
    if no_due:
        print("━━━ ⬜ 마감 미정 ━━━")
        for t, _ in no_due:
            a = t.get("assignee") or "미정"
            num = t.get("display_num", "?")
            print(f"  #{num} -- | {t['title']}")
            print(f"       담당: {a}")
        print()

    # ── 완료 업무 ──
    _show_completed()


def _week_range(w):
    today = datetime.now(_KST).date()
    monday = today - timedelta(days=today.weekday())
    start = monday - timedelta(weeks=w - 1)
    return start, start + timedelta(days=6)


def _month_range(m):
    today = datetime.now(_KST).date()
    first = today.replace(day=1)
    for _ in range(m - 1):
        first = (first - timedelta(days=1)).replace(day=1)
    if m == 1:
        return first, today
    next_first = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, next_first - timedelta(days=1)


def _show_completed():
    tasks = _db.get_completed_tasks()
    if not tasks:
        return

    weeks = {}
    months = {}
    for t in tasks:
        closed = t.get("closed_at", "")
        if not closed:
            continue
        try:
            cd = datetime.strptime(closed[:10], "%Y-%m-%d").date()
        except Exception:
            continue
        for w in range(1, 5):
            ws, we = _week_range(w)
            if ws <= cd <= we:
                weeks.setdefault(w, []).append((t, cd))
                break
        for m in range(1, 5):
            ms, me = _month_range(m)
            if ms <= cd <= me:
                months.setdefault(m, []).append((t, cd))
                break

    print("━━━ ✅ 완료 업무 ━━━")

    wl = {1: "W1 이번주", 2: "W2 지난주", 3: "W3 2주전", 4: "W4 3주전"}
    for w in range(1, 5):
        items = sorted(weeks.get(w, []), key=lambda x: x[1], reverse=True)
        if items:
            print(f"  📅 {wl[w]} ({len(items)}건)")
            for t, cd in items:
                a = t.get("assignee") or "미정"
                print(f"     ✅ {t['title']}")
                print(f"        담당: {a} | 완료: {cd.strftime('%m/%d')}")

    ml = {1: "M1 이번달", 2: "M2 지난달", 3: "M3 2달전", 4: "M4 3달전"}
    for m in range(1, 5):
        items = sorted(months.get(m, []), key=lambda x: x[1], reverse=True)
        if items:
            print(f"  📆 {ml[m]} ({len(items)}건)")
            for t, cd in items:
                a = t.get("assignee") or "미정"
                print(f"     ✅ {t['title']}")
                print(f"        담당: {a} | 완료: {cd.strftime('%m/%d')}")


def parse_text(text):
    """자연어 텍스트에서 제목/담당/마감/내용 추출"""
    title, assignee, due, content = None, None, None, None

    # 내용 추출 (제일 먼저 — 줄바꿈 포함할 수 있으므로)
    m = re.search(r'내용\s*[:：]\s*(.+?)(?:\n(?:제목|담당|마감|우선|피드백)\s*[:：]|$)', text, re.IGNORECASE | re.DOTALL)
    if m:
        content = m.group(1).strip()

    # 제목 추출
    m = re.search(r'제목\s*[:：]\s*(.+?)(?:\n|담당|마감|우선|내용|$)', text, re.IGNORECASE)
    if m:
        title = m.group(1).strip()

    # 담당자 추출
    m = re.search(r'담당(?:자)?\s*[:：]\s*(.+?)(?:\n|마감|제목|우선|내용|$)', text, re.IGNORECASE)
    if m:
        assignee = m.group(1).strip()

    # 우선순위 추출
    priority = None
    m = re.search(r'우선(?:순위)?\s*[:：]\s*(긴급|높음|중간|낮음)', text, re.IGNORECASE)
    if m:
        priority = m.group(1)

    # 마감 추출 및 날짜 변환
    m = re.search(r'마감\s*[:：]\s*(.+?)(?:\n|제목|담당|내용|$)', text, re.IGNORECASE)
    if m:
        raw_due = m.group(1).strip()
        # YYYY-MM-DD 형식이면 그대로
        if re.match(r'\d{4}-\d{2}-\d{2}', raw_due):
            due = raw_due[:10]
        else:
            # M/D 형식 변환 (예: 6/1)
            dm = re.search(r'(\d{1,2})[/.](\d{1,2})', raw_due)
            if dm:
                month, day = int(dm.group(1)), int(dm.group(2))
                year = datetime.now(_KST).year
                try:
                    due = f"{year}-{month:02d}-{day:02d}"
                except Exception:
                    due = None
            else:
                # 날짜 변환 실패 시 원문 보관 (summary에)
                due = None

    # 제목이 없으면 업무지시 이후 첫 줄 사용
    if not title:
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        for line in lines:
            if not re.match(r'(업무지시|담당|마감|제목)', line):
                title = line[:50]
                break
        if not title and lines:
            title = lines[0][:50]

    return title, assignee, due, priority, content


def cmd_register(chat_id, title=None, assignee=None, due=None, text=None, summary=""):
    # text에서 파싱
    content = None
    if text and not title:
        title, assignee, due, priority, content = parse_text(text)
    else:
        priority = None
    if not title:
        print("ERROR: 제목을 추출할 수 없습니다.")
        sys.exit(1)

    # room 조회
    room = _db.get_room_by_chat_id(chat_id)
    if not room:
        # room이 없으면 생성
        room = _db.upsert_room(chat_id, "supergroup", "브랜업")

    task = _db.create_task(
        room_id=room["id"],
        title=title,
        summary=summary or content or title,
        due_at=due,
        assignee=assignee,
        priority=priority or "중간",
    )
    if _ws:
        _ws.ensure_room_dirs(room["id"])
        _ws.create_task_md(room, task)
        _ws.write_room_md(room, [f"[{t['status']}] {t['title']}" for t in _db.get_tasks_by_room(room["id"])])

    due_str = due or "미정"
    assignee_str = assignee or "미정"
    print(f"📋 업무 등록 완료")
    print(f"제목: {title}")
    print(f"담당: {assignee_str}")
    print(f"마감: {due_str}")

    # GitHub Pages 자동 배포 (백그라운드)
    _deploy_dashboard()


def _deploy_dashboard():
    """백그라운드로 HTML 대시보드 재생성 + GitHub 푸시"""
    try:
        deploy_script = str(_scripts / "deploy_dashboard.sh")
        subprocess.Popen(
            ["/bin/bash", deploy_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass  # 배포 실패해도 업무 등록은 정상 처리


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")

    # list
    lp = sub.add_parser("list")
    lp.add_argument("--assignee", default=None)

    # dashboard
    sub.add_parser("dashboard", help="D-day 기반 대시보드")

    # register
    rp = sub.add_parser("register")
    rp.add_argument("--chat-id", required=True)
    rp.add_argument("--title", default=None)
    rp.add_argument("--assignee", default=None)
    rp.add_argument("--due", default=None)
    rp.add_argument("--summary", default="")
    rp.add_argument("--text", default=None, help="자연어 텍스트 (제목/담당/마감 자동 추출)")

    args = p.parse_args()

    if args.cmd == "list":
        cmd_list(assignee=args.assignee)
    elif args.cmd == "dashboard":
        cmd_dashboard()
    elif args.cmd == "register":
        cmd_register(
            chat_id=args.chat_id,
            title=args.title,
            assignee=args.assignee,
            due=args.due,
            summary=args.summary,
            text=args.text,
        )
    else:
        p.print_help()

if __name__ == "__main__":
    main()
