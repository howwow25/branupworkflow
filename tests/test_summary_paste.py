"""업무내용에 붙여 넣은 이미지·파일.

붙여 넣은 파일은 첨부파일로 올라가고 본문에는 `![이름](file:ID)` (그림) 또는
`[이름](file:ID)` (그 밖) 이 글자로 남는다. 보기 칸이 그것을 그림과 링크로
그린다. 실제 붙여넣기는 브라우저에서 확인했다 — 여기서는 서버의 규칙과 화면에
장치가 실려 있는지를 붙든다.

⚠️ 이미지를 눌렀을 때 새 탭에서 보이도록 `?inline=1` 을 받는다. **그림만**
허락해야 한다. SVG·HTML 을 inline 으로 내주면 이 출처에서 스크립트가 돈다.
"""
import os
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = os.environ["BRANUP_DATA_DIR"]

import db  # noqa: E402
import api_server  # noqa: E402


def test_운영_디비를_쓰지_않는다():
    assert str(db.DB_PATH).startswith(_TMP), f"시험이 {db.DB_PATH} 를 쓰려 한다"


@pytest.fixture()
def base():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), api_server.APIHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


@pytest.fixture()
def task():
    room = db.upsert_room("paste-room", "web", "붙여넣기 시험")
    return db.create_task(room["id"], title="붙여넣기", assignee="이향석")


def _disposition(base, file_id, query=""):
    with urllib.request.urlopen(f"{base}/api/files/{file_id}{query}") as r:
        return (r.headers.get("Content-Disposition") or "",
                r.headers.get("X-Content-Type-Options"))


def _file(task, name, mime):
    return db.add_file(task_id=task["id"], original_name=name,
                       file_data=b"x", mime_type=mime)


def test_그림은_inline_으로_열_수_있다(base, task):
    f = _file(task, "캡처.png", "image/png")
    disp, nosniff = _disposition(base, f["id"], "?inline=1")
    assert disp.startswith("inline;")
    assert nosniff == "nosniff"


def test_inline_을_안_달면_여전히_내려받는다(base, task):
    f = _file(task, "캡처.png", "image/png")
    assert _disposition(base, f["id"])[0].startswith("attachment;")


@pytest.mark.parametrize("name,mime", [
    ("그림.svg", "image/svg+xml"),
    ("문서.html", "text/html"),
    ("견적서.csv", "application/octet-stream"),
])
def test_그림이_아니면_inline_을_달아도_내려받는다(base, task, name, mime):
    f = _file(task, name, mime)
    assert _disposition(base, f["id"], "?inline=1")[0].startswith("attachment;")


def test_화면에_붙여넣기와_보기_칸이_있다():
    import dashboard_html
    html = dashboard_html.render()
    assert 'class="summary-view"' in html
    assert 'onpaste="pasteIntoSummary(event, this)"' in html
    # f-문자열 안이라 역슬래시가 한 번 줄어든다. 줄면 안 되는 자리가 맞는지.
    assert r"var SV_TOKEN = /(!?)\[([^\]\n]*)\]\(file:([A-Za-z0-9_-]+)\)/g;" in html
