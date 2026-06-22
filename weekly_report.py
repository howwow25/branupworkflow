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
    
    리포트 구성:
    1. 기준 주 완료 업무 (기준 주에 완료된 업무)
    2. 기준 주 지연 업무 (마감이 기준 주 이전이고 완료되지 않은 업무)
    3. 다음주 예정 업무 (다음주에 마감인 진행중 업무)
    4. 요약 통계
    """
    assignee = payload.get("assignee", "미정")
    week_start = payload.get("week_start", "")
    week_end = payload.get("week_end", "")
    tasks = payload.get("tasks", [])

    # ── 날짜 파싱 ──
    try:
        ws_date = datetime.strptime(week_start, "%Y-%m-%d").date() if week_start else None
        we_date = datetime.strptime(week_end, "%Y-%m-%d").date() if week_end else None
    except ValueError:
        ws_date = we_date = None

    # 다음주 범위
    nw_start = ws_date + timedelta(days=7) if ws_date else None
    nw_end = we_date + timedelta(days=7) if we_date else None

    # ── 업무 분류 ──
    completed_this_week = []    # 기준 주에 완료된 업무
    delayed = []                # 지연 (마감이 기준 주 이전, 미완료)
    next_week_tasks = []        # 다음주 마감 (진행중)
    other = []                  # 기타

    for t in tasks:
        status = t.get("status", "")
        due_str = t.get("due_at", "")
        closed_str = t.get("closed_at", "")

        # 완료일 파싱
        closed_date = None
        if closed_str:
            try:
                closed_date = datetime.strptime(closed_str[:10], "%Y-%m-%d").date()
            except Exception:
                pass

        # 마감일 파싱
        due_date = None
        if due_str:
            try:
                due_date = datetime.strptime(due_str[:10], "%Y-%m-%d").date()
            except Exception:
                pass

        # 1) 기준 주에 완료된 업무
        if status == "완료" and closed_date and ws_date and we_date:
            if ws_date <= closed_date <= we_date:
                completed_this_week.append(t)
                continue

        # 2) 지연 업무: 마감이 기준 주 종료일 이전이고, 아직 완료되지 않음
        if status != "완료" and due_date and we_date:
            if due_date <= we_date:
                dd = (datetime.now(KST).date() - due_date).days if due_date else 0
                delayed.append((t, max(0, dd)))
                continue

        # 3) 다음주 마감 업무 (진행중)
        if status != "완료" and due_date and nw_start and nw_end:
            if nw_start <= due_date <= nw_end:
                dd_val = (due_date - datetime.now(KST).date()).days
                next_week_tasks.append((t, dd_val))
                continue

        other.append(t)

    # ── 마크다운 생성 ──
    today = datetime.now(KST)
    now_str = today.strftime("%Y-%m-%d %H:%M")

    def fmt_date(d):
        if not d:
            return "미정"
        return d.strftime("%m/%d")

    lines = []
    lines.append(f"# 📊 {assignee} 주간리포트")
    lines.append(f"**기준 주:** {week_start} ~ {week_end}  ")
    lines.append(f"**생성일:** {now_str}  ")
    lines.append(f"**전체 업무:** {len(tasks)}건  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── 섹션 1: 기준 주 완료 업무 ──
    lines.append("## ✅ 기준 주 완료")
    lines.append("")
    if completed_this_week:
        lines.append("| # | 제목 | 완료일 |")
        lines.append("|---|---|---|")
        for t in completed_this_week:
            closed = (t.get("closed_at") or "")[:10]
            num = t.get("display_num", "?")
            title = t.get("title", "")
            lines.append(f"| #{num} | {title} | {closed} |")
    else:
        lines.append("*기준 주에 완료된 업무가 없습니다.*")
    lines.append("")

    # ── 섹션 2: 지연 업무 ──
    lines.append("## ⚠️ 지연 업무")
    lines.append("")
    if delayed:
        lines.append("| # | 제목 | 마감 | 지연일 |")
        lines.append("|---|---|---|---|")
        for t, dd in delayed:
            num = t.get("display_num", "?")
            title = t.get("title", "")
            due = (t.get("due_at") or "")[:10]
            lines.append(f"| #{num} | {title} | {due} | D+{dd} |")
    else:
        lines.append("*지연된 업무가 없습니다.* 👍")
    lines.append("")

    # ── 섹션 3: 다음주 예정 업무 ──
    if nw_start and nw_end:
        next_label = f"{nw_start} ~ {nw_end}"
    else:
        next_label = "다음주"
    lines.append(f"## 📅 다음주 예정 ({next_label})")
    lines.append("")
    if next_week_tasks:
        lines.append("| # | 제목 | 마감 | D-Day |")
        lines.append("|---|---|---|---|")
        for t, dd in next_week_tasks:
            num = t.get("display_num", "?")
            title = t.get("title", "")
            due = (t.get("due_at") or "")[:10]
            lines.append(f"| #{num} | {title} | {due} | {dday_label(dd)} |")
    else:
        lines.append("*다음주 예정된 업무가 없습니다.*")
    lines.append("")

    # ── 섹션 4: 요약 통계 ──
    lines.append("---")
    lines.append("")
    lines.append("## 📊 요약 통계")
    lines.append("")
    lines.append("| 항목 | 건수 |")
    lines.append("|---|---|")
    lines.append(f"| 전체 업무 | {len(tasks)} |")
    lines.append(f"| ✅ 기준 주 완료 | {len(completed_this_week)} |")
    lines.append(f"| ⚠️ 지연 | {len(delayed)} |")
    lines.append(f"| 📅 다음주 예정 | {len(next_week_tasks)} |")
    lines.append(f"| 📋 기타 | {len(other)} |")
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
            "completed_this_week": len(completed_this_week),
            "delayed": len(delayed),
            "next_week": len(next_week_tasks),
            "other": len(other),
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
            "stats": {"total": 0, "completed_this_week": 0, "delayed": 0, "next_week": 0, "other": 0}
        }))
        return

    result = generate_report(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
