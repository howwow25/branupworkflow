"""업무를 바꾼 사람은 **로그인한 직원**이고, 서버가 직접 정한다.

예전에는 화면의 「나는 OOO」 를 `X-Branup-Actor` 머리로 받았다. 완료처리
버튼이 부르는 `POST /api/tasks/<id>/complete` 가 그 값을 넘기지 않아서 기록의
`by` 가 비었고, 포털은 **본인이 완료한 업무의 알림을 본인에게** 보냈다
(2026-11-12, 이향석).

지금은 요청에 따라온 통합 로그인 쿠키(`branup_sso`)를 포털 `/api/auth/me` 에
물어 정한다 (`portal_login.py`). 여기서는 가짜 포털을 띄우고 실제 HTTP 로
부른다 — db 함수만 시험하면 빠뜨린 길이 안 보인다.
"""
import json
import os
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = os.environ["BRANUP_DATA_DIR"]

import db  # noqa: E402
import api_server  # noqa: E402
import portal_login  # noqa: E402

ME = {"id": 7, "name": "이향석"}
GOOD = "good-token"


def test_운영_디비를_쓰지_않는다():
    assert str(db.DB_PATH).startswith(_TMP), f"시험이 {db.DB_PATH} 를 쓰려 한다"


class _FakePortal(BaseHTTPRequestHandler):
    calls = 0

    def do_GET(self):
        type(self).calls += 1
        tok = portal_login.token(self.headers.get("Cookie"))
        if self.path != "/api/auth/me" or tok != GOOD:
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps(ME, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture()
def portal(monkeypatch):
    srv = _serve(_FakePortal)
    _FakePortal.calls = 0
    monkeypatch.setattr(portal_login, "PORTAL_ME",
                        f"http://127.0.0.1:{srv.server_address[1]}/api/auth/me")
    portal_login.clear_cache()
    yield srv
    srv.shutdown()
    srv.server_close()
    portal_login.clear_cache()


@pytest.fixture()
def base(monkeypatch, portal):
    # 굽기는 별도 프로세스를 띄운다 — 시험에서는 필요 없다.
    monkeypatch.setattr(api_server.APIHandler, "_refresh_dashboard",
                        lambda self: None)
    srv = _serve(api_server.APIHandler)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


@pytest.fixture()
def task():
    room = db.upsert_room("actor-room", "web", "actor 시험")
    return db.create_task(room["id"], title="내 업무", assignee=ME["name"])


def _post(base, path, body=None, *, cookie=f"x=1; branup_sso={GOOD}",
          extra=None):
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    headers.update(extra or {})
    req = urllib.request.Request(
        base + path, method="POST",
        data=json.dumps(body or {}).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


def _payload(task_id, kind):
    rows = [e for e in db.get_task_events(task_id) if e["event_type"] == kind]
    assert rows, f"「{kind}」 기록이 없다"
    return rows[-1]["payload"]


def _assert_me(payload):
    assert payload.get("by") == ME["name"]
    assert payload.get("by_uid") == ME["id"]


# ── 길마다 로그인한 직원이 남는가 ─────────────────────────


def test_완료처리_버튼(base, task):
    _post(base, f"/api/tasks/{task['id']}/complete")
    _assert_me(_payload(task["id"], "완료"))


def test_완료취소_버튼(base, task):
    _post(base, f"/api/tasks/{task['id']}/complete")
    _post(base, f"/api/tasks/{task['id']}/uncomplete")
    _assert_me(_payload(task["id"], "완료 취소"))


def test_명령창_완료(base, task):
    _post(base, "/api/agent", {"text": f"{task['display_num']}번 완료"})
    _assert_me(_payload(task["id"], "완료"))


def test_명령창_마감변경(base, task):
    _post(base, "/api/agent",
          {"text": f"#{task['display_num']} 마감 2026-12-31로 변경"})
    _assert_me(_payload(task["id"], "마감일 변경"))


# ── 화면이 말하는 이름은 믿지 않는다 ──────────────────────


def test_머리에_실은_이름은_무시한다(base, task):
    _post(base, f"/api/tasks/{task['id']}/complete", cookie=None,
          extra={"X-Branup-Actor": quote("전대박")})
    assert "by" not in _payload(task["id"], "완료")


def test_로그인_안_했으면_모름으로_남는다(base, task):
    _post(base, f"/api/tasks/{task['id']}/complete",
          cookie="branup_sso=expired")
    p = _payload(task["id"], "완료")
    assert "by" not in p and "by_uid" not in p


def test_포털이_꺼져도_쓰기는_된다(base, task, monkeypatch):
    monkeypatch.setattr(portal_login, "PORTAL_ME",
                        "http://127.0.0.1:1/api/auth/me")
    monkeypatch.setattr(portal_login, "TIMEOUT", 0.5)
    got = _post(base, f"/api/tasks/{task['id']}/complete")
    assert got["status"] == "완료"
    assert "by" not in _payload(task["id"], "완료")


def test_같은_토큰은_다시_묻지_않는다(portal):
    cookie = f"branup_sso={GOOD}"
    assert portal_login.actor(cookie) == ME
    assert portal_login.actor(cookie) == ME
    assert _FakePortal.calls == 1


def test_쿠키에서_토큰만_꺼낸다():
    assert portal_login.token("a=1; branup_sso=abc; b=2") == "abc"
    assert portal_login.token("a=1") is None
    assert portal_login.token(None) is None
