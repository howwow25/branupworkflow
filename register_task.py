#!/usr/bin/env python3
"""
직접 업무 등록 스크립트 (batch.py를 거치지 않고 빠르게 등록)
"""
import sys
import argparse
import importlib.util
from pathlib import Path

_scripts = Path(__file__).parent

def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, str(_scripts / fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_db = _load("branup_db", "db.py")
_ws = _load("branup_ws", "workspace.py")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--chat-id", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--summary", default="")
    p.add_argument("--assignee", default=None)
    p.add_argument("--due", default=None)
    args = p.parse_args()

    room = _db.get_room_by_chat_id(args.chat_id)
    if not room:
        print("Room not found")
        return

    task = _db.create_task(
        room_id=room["id"],
        title=args.title,
        summary=args.summary,
        due_at=args.due,
        assignee=args.assignee,
    )
    _ws.ensure_room_dirs(room["id"])
    _ws.create_task_md(room, task)
    _ws.write_room_md(room, [f"[{t['status']}] {t['title']}" for t in _db.get_tasks_by_room(room["id"])])

    print(f"REGISTERED: {task['title']}")

if __name__ == "__main__":
    main()
