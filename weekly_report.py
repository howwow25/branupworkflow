#!/usr/bin/env python3
"""
주간리포트 생성기 — Hermes 에이전트 전용
DB에서 직원의 이번주 업무 데이터를 받아 LLM 분석 → 마크다운 리포트 생성 → .md 파일 저장

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


def generate_report(payload: dict) -> dict:
    """
    업무 데이터를 분석해 마크다운 리포트 생성
    payload = {"assignee": "강경철", "week_start": "2026-06-15",
               "week_end": "2026-06-21", "total": 10, "tasks": [...]}
    """
    assignee = payload.get("assignee", "미정")
    week_start = payload.get("week_start", "")
    week_end = payload.get("week_end", "")
    tasks = payload.get("tasks", [])

    # ── 업무 분류 ──
    completed = []       # 완료된 업무
    in_progress = []     # 진행중
    delayed = []         # 지연 (마감 지남)
    today_due = []       # 오늘 마감
    upcoming = []        # 예정
    no_due = []          # 마감 미정

    for t in tasks:
        status = t.get("status", "")
        dd = dday(t.get("due_at"))

        if status == "완료":
            completed.append((t, dd))
        elif dd is not None and dd < 0:
            delayed.append((t, dd))
        elif dd == 0:
            today_due.append((t, dd))
        elif dd is not None and dd > 0:
            upcoming.append((t, dd))
        else:
            no_due.append((t, dd))

    # ── 이번주 실적 (이번주에 완료되었거나 마감이 이번주인 것) ──
    week_completed = [t for t, _ in completed if t.get("_in_week")]
    week_tasks_all = [t for t in tasks if t.get("_in_week")]

    # ── 마크다운 생성 ──
    today = datetime.now(KST)
    now_str = today.strftime("%Y-%m-%d %H:%M")

    lines = []
    lines.append(f"# 📊 {assignee} 주간리포트")
    lines.append(f"**기간:** {week_start} ~ {week_end}  ")
    lines.append(f"**생성일:** {now_str}  ")
    lines.append(f"**전체 업무:** {len(tasks)}건  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 섹션 1: 이번주 완료 ──
    lines.append("## ✅ 이번주 완료")
    lines.append("")
    if week_completed:
        lines.append(f"| # | 제목 | 완료일 |")
        lines.append("|---|---|---|")
        for t in week_completed:
            closed = (t.get("closed_at") or "")[:10]
            num = t.get("display_num", "?")
            title = t.get("title", "")
            lines.append(f"| #{num} | {title} | {closed} |")
    else:
        lines.append("*이번주 완료된 업무가 없습니다.*")
    lines.append("")

    # ── 섹션 2: 이번주 전체 현황 ──
    lines.append("## 📋 이번주 업무 현황")
    lines.append("")
    if week_tasks_all:
        lines.append(f"| # | 제목 | 상태 | 마감 | D-Day |")
        lines.append("|---|---|---|---|---|")
        for t in week_tasks_all:
            num = t.get("display_num", "?")
            title = t.get("title", "")
            status = t.get("status", "")
            due = (t.get("due_at") or "")[:10] if t.get("due_at") else "미정"
            lbl = dday_label(dday(t.get("due_at")))
            status_icon = "✅" if status == "완료" else "🔄"
            lines.append(f"| #{num} | {title} | {status_icon} {status} | {due} | {lbl} |")
    else:
        lines.append("*이번주 해당하는 업무가 없습니다.*")
    lines.append("")

    # ── 섹션 3: 지연 업무 경고 ──
    lines.append("## ⚠️ 지연 업무")
    lines.append("")
    if delayed:
        lines.append(f"| # | 제목 | 마감 | 지연일 |")
        lines.append("|---|---|---|---|")
        for t, dd in delayed:
            num = t.get("display_num", "?")
            title = t.get("title", "")
            due = (t.get("due_at") or "")[:10]
            lines.append(f"| #{num} | {title} | {due} | {dday_label(dd)} |")
    else:
        lines.append("*지연된 업무가 없습니다.* 👍")
    lines.append("")

    # ── 섹션 4: 오늘 마감 ──
    if today_due:
        lines.append("## 🔴 오늘 마감")
        lines.append("")
        lines.append(f"| # | 제목 | 상태 |")
        lines.append("|---|---|---|")
        for t, dd in today_due:
            num = t.get("display_num", "?")
            title = t.get("title", "")
            status = t.get("status", "")
            lines.append(f"| #{num} | {title} | {status} |")
        lines.append("")

    # ── 섹션 5: 진행중 (완료/지연/오늘마감 제외) ──
    in_progress = [(t, dd) for t, dd in upcoming + no_due
                   if t.get("status") != "완료"]
    lines.append("## 🔄 진행중 업무")
    lines.append("")
    if in_progress:
        lines.append(f"| # | 제목 | 마감 | D-Day |")
        lines.append("|---|---|---|---|")
        for t, dd in in_progress:
            num = t.get("display_num", "?")
            title = t.get("title", "")
            due = (t.get("due_at") or "")[:10] if t.get("due_at") else "미정"
            lbl = dday_label(dd)
            lines.append(f"| #{num} | {title} | {due} | {lbl} |")
    else:
        lines.append("*진행중인 업무가 없습니다.*")
    lines.append("")

    # ── 섹션 6: 요약 통계 ──
    lines.append("---")
    lines.append("")
    lines.append("## 📊 요약 통계")
    lines.append("")
    lines.append(f"| 항목 | 건수 |")
    lines.append("|---|---|")
    lines.append(f"| 전체 업무 | {len(tasks)} |")
    lines.append(f"| ✅ 완료 | {len(completed)} |")
    lines.append(f"| 🔄 진행중 | {len(in_progress)} |")
    lines.append(f"| ⚠️ 지연 | {len(delayed)} |")
    lines.append(f"| 🔴 오늘 마감 | {len(today_due)} |")
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
            "completed": len(completed),
            "in_progress": len(in_progress),
            "delayed": len(delayed),
            "today_due": len(today_due),
        }
    }


def main():
    parser = argparse.ArgumentParser(description="주간리포트 생성기")
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
        print(json.dumps({
            "ok": True,
            "assignee": payload.get("assignee", "미정") if payload else "미정",
            "md_content": "# 📊 주간리포트\n\n등록된 업무가 없습니다.",
            "stats": {"total": 0, "completed": 0, "in_progress": 0, "delayed": 0, "today_due": 0}
        }))
        return

    result = generate_report(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
