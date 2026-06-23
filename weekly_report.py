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
        completed_this_week = []
        delayed = []
        in_progress = []

        for t in ptasks:
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

            # 기준 주 완료
            if status == "완료" and closed_date and ws_date and we_date:
                if ws_date <= closed_date <= we_date:
                    completed_this_week.append(t)
                    continue

            # 지연 업무 (마감 < 오늘, 미완료)
            if status != "완료" and due_date and due_date < today:
                dd = (today - due_date).days
                delayed.append((t, dd))
                continue

            # 나머지 진행중
            if status != "완료":
                in_progress.append(t)
                continue

            # 완료됐지만 기준 주 밖
            in_progress.append(t)

        # ── 평가 수집 ──
        for t in ptasks:
            ev, grade = evaluate_task(t, ws_date, we_date)
            all_evaluations[grade] = all_evaluations.get(grade, 0) + 1

        # ── 섹션 1: 기준 주 완료 ──
        lines.append("### ✅ 기준 주 완료")
        lines.append("")
        if completed_this_week:
            lines.append("| # | 제목 | 완료일 | 평가 |")
            lines.append("|---|---|---|---|")
            for t in completed_this_week:
                closed = (t.get("closed_at") or "")[:10]
                num = t.get("display_num", "?")
                title = t.get("title", "")
                ev, _ = evaluate_task(t, ws_date, we_date)
                lines.append(f"| #{num} | {title} | {closed} | {ev} |")
        else:
            lines.append("*기준 주에 완료된 업무가 없습니다.*")
        lines.append("")

        # ── 섹션 2: 지연 업무 ──
        lines.append("### ⚠️ 지연 업무")
        lines.append("")
        if delayed:
            lines.append("| # | 제목 | 마감 | 지연일 | 평가 |")
            lines.append("|---|---|---|---|---|")
            for t, dd in delayed:
                num = t.get("display_num", "?")
                title = t.get("title", "")
                due = (t.get("due_at") or "")[:10]
                ev, _ = evaluate_task(t, ws_date, we_date)
                lines.append(f"| #{num} | {title} | {due} | D+{dd} | {ev} |")
        else:
            lines.append("*지연된 업무가 없습니다.* 👍")
        lines.append("")

        # ── 섹션 3: 진행중 업무 ──
        lines.append("### 🔄 진행중")
        lines.append("")
        if in_progress:
            lines.append("| # | 제목 | 마감 | D-Day | 평가 |")
            lines.append("|---|---|---|---|---|")
            for t in in_progress:
                num = t.get("display_num", "?")
                title = t.get("title", "")
                due = (t.get("due_at") or "")[:10] if t.get("due_at") else ""
                dd = dday(t.get("due_at"))
                ev, _ = evaluate_task(t, ws_date, we_date)
                lines.append(f"| #{num} | {title} | {due} | {dday_label(dd)} | {ev} |")
        else:
            lines.append("*진행중인 업무가 없습니다.*")
        lines.append("")

        # 프로젝트 통계
        stats_summary.append({
            "title": proj_title,
            "total": len(ptasks),
            "completed": len(completed_this_week),
            "delayed": len(delayed),
            "in_progress": len(in_progress),
        })

        lines.append("---")
        lines.append("")

    # ── 프로젝트 미지정 업무 섹션 ──
    if no_proj_tasks:
        lines.append("## 📋 프로젝트 미지정 업무")
        lines.append("")
        lines.append(f"**업무:** {len(no_proj_tasks)}건  ")
        lines.append("")

        # 분류
        n_completed = []
        n_delayed = []
        n_in_progress = []

        for t in no_proj_tasks:
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

            if status == "완료" and closed_date and ws_date and we_date:
                if ws_date <= closed_date <= we_date:
                    n_completed.append(t)
                    continue

            if status != "완료" and due_date and due_date < today:
                dd = (today - due_date).days
                n_delayed.append((t, dd))
                continue

            if status != "완료":
                n_in_progress.append(t)
                continue
            n_in_progress.append(t)

        # 평가 수집
        for t in no_proj_tasks:
            ev, grade = evaluate_task(t, ws_date, we_date)
            all_evaluations[grade] = all_evaluations.get(grade, 0) + 1

        if n_completed:
            lines.append("| # | 제목 | 완료일 | 평가 |")
            lines.append("|---|---|---|---|")
            for t in n_completed:
                closed = (t.get("closed_at") or "")[:10]
                num = t.get("display_num", "?")
                title = t.get("title", "")
                ev, _ = evaluate_task(t, ws_date, we_date)
                lines.append(f"| #{num} | {title} | {closed} | {ev} |")
            lines.append("")

        if n_delayed:
            lines.append("| # | 제목 | 마감 | 지연일 | 평가 |")
            lines.append("|---|---|---|---|---|")
            for t, dd in n_delayed:
                num = t.get("display_num", "?")
                title = t.get("title", "")
                due = (t.get("due_at") or "")[:10]
                ev, _ = evaluate_task(t, ws_date, we_date)
                lines.append(f"| #{num} | {title} | {due} | D+{dd} | {ev} |")
            lines.append("")

        if n_in_progress:
            lines.append("| # | 제목 | 마감 | D-Day | 평가 |")
            lines.append("|---|---|---|---|---|")
            for t in n_in_progress:
                num = t.get("display_num", "?")
                title = t.get("title", "")
                due = (t.get("due_at") or "")[:10] if t.get("due_at") else ""
                dd = dday(t.get("due_at"))
                ev, _ = evaluate_task(t, ws_date, we_date)
                lines.append(f"| #{num} | {title} | {due} | {dday_label(dd)} | {ev} |")
            lines.append("")

        stats_summary.append({
            "title": "📋 미지정",
            "total": len(no_proj_tasks),
            "completed": len(n_completed),
            "delayed": len(n_delayed),
            "in_progress": len(n_in_progress),
        })

        lines.append("---")
        lines.append("")

    # ── 전체 요약 통계 (프로젝트별) ──
    lines.append("## 📊 요약 통계")
    lines.append("")
    lines.append("| 프로젝트 | 전체 | 완료 | 지연 | 진행중 |")
    lines.append("|---|---|---|---|---|")
    total_comp = 0
    total_del = 0
    total_prog = 0
    for s in stats_summary:
        title = s["title"]
        lines.append(f"| {title} | {s['total']} | {s['completed']} | {s['delayed']} | {s['in_progress']} |")
        total_comp += s['completed']
        total_del += s['delayed']
        total_prog += s['in_progress']
    # 합계 행
    lines.append(f"| **합계** | **{len(tasks)}** | **{total_comp}** | **{total_del}** | **{total_prog}** |")
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
