"""**화면의 모든 쓰기 길이** 「나는 OOO」 를 기록의 `by` 로 남기는가.

`update_task(actor=...)` 는 있었지만, 완료처리 버튼이 부르는
`POST /api/tasks/<id>/complete` 는 actor 를 넘기지 않았다. 기록의 `by` 가
비면 포털은 바꾼 본인을 뺄 수 없어서 **본인이 완료한 업무의 알림을 본인이
받았다** (2026-11-12, 이향석). 완료 취소와 에이전트 명령창(`N번 완료` 등)도
같았다.

db 함수만 시험하면 이 구멍이 안 보인다 — 실제 HTTP 로 부른다.
"""
import json
import os
import sys
import threading
import urllib.request
from pathlib import Path
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = os.environ["BRANUP_DATA_DIR"]

import db  # noqa: E402
import api_server  # noqa: E402

ME = "이향석"


def test_운영_디비를_쓰지_않는다():
    assert str(db.DB_PATH).startswith(_TMP), f"시험이 {db.DB_PATH} 를 쓰려 한다"


@pytest.fixture()
def base(monkeypatch):
    # 굽기는 별도 프로세스를 띄운다 — 시험에서는 필요 없다.
    monkeypatch.setattr(api_server.APIHandler, "_refresh_dashboard",
                        lambda self: None)
    srv = api_server.ThreadingHTTPServer(("127.0.0.1", 0),
                                         api_server.APIHandler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


@pytest.fixture()
def task():
    room = db.upsert_room("actor-room", "web", "actor 시험")
    return db.create_task(room["id"], title="내 업무", assignee=ME, actor=ME)


def _post(base, path, body=None):
    req = urllib.request.Request(
        base + path, method="POST",
        data=json.dumps(body or {}).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "X-Branup-Actor": quote(ME)})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


def _by(task_id, kind):
    rows = [e for e in db.get_task_events(task_id) if e["event_type"] == kind]
    assert rows, f"「{kind}」 기록이 없다"
    return rows[-1]["payload"].get("by")


def test_완료처리_버튼이_바꾼_사람을_남긴다(base, task):
    _post(base, f"/api/tasks/{task['id']}/complete")
    assert _by(task["id"], "완료") == ME


def test_완료취소_버튼이_바꾼_사람을_남긴다(base, task):
    _post(base, f"/api/tasks/{task['id']}/complete")
    _post(base, f"/api/tasks/{task['id']}/uncomplete")
    assert _by(task["id"], "완료 취소") == ME


def test_명령창_완료가_바꾼_사람을_남긴다(base, task):
    _post(base, "/api/agent", {"text": f"{task['display_num']}번 완료"})
    assert _by(task["id"], "완료") == ME


def test_명령창_마감변경이_바꾼_사람을_남긴다(base, task):
    _post(base, "/api/agent",
          {"text": f"#{task['display_num']} 마감 2026-12-31로 변경"})
    assert _by(task["id"], "마감일 변경") == ME
