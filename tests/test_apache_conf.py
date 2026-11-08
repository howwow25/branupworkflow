r"""아파치 설정이 **앱의 길**을 막지 않는가. (`apache-branup-watcher.conf`)

## 실제로 일어난 일 (2026-11-08)

쓰던 주간리포트가 갑자기 **403 Forbidden** 으로 죽었다. 파이썬 코드는 아무도
안 건드렸다. 원인은 전날 더한 아파치 한 줄이었다:

    <LocationMatch "^/branup/branup-watcher/.*(\.env|...|\.md|...)$">
        Require all denied

주간리포트는 `{이름}_{주}.md` 파일이고(`weekly_report.py`), 화면은 그것을

    /branup/branup-watcher/api/reports/이향석_2026-W45.md

로 받는다. **`/api/` 는 8800 포트의 앱으로 가는 프록시다.** `<Location*>` 은
디스크가 아니라 **주소 공간**에 걸리므로 프록시로 넘기기 **전에** 막는다.
소스 파일을 가리려던 규칙이 앱의 기능을 껐다.

같은 길의 `.txt` 는 404 였다 — 앱이 답했다는 뜻이다. **확장자 하나로
갈렸다.** 증상이 "권한 문제" 로 보여서 앱을 먼저 의심하게 된다.

## 그래서 규칙

막을 것이 **파일**이면 `<Directory>` · `<FilesMatch>` 로 막는다. 그 둘은
디스크 위의 파일에만 걸리고, 프록시로 넘어가는 주소에는 **구조적으로 닿을 수
없다.** 같은 일을 하면서 앱의 길을 밟지 않는다.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONF = ROOT / "apache-branup-watcher.conf"

#: 화면이 실제로 부르는 주소들. 전부 `/api/` 아래이고 **앱이 답해야 한다.**
APP_PATHS = (
    "/branup/branup-watcher/api/reports/이향석_2026-W45.md",
    "/branup/branup-watcher/api/reports/전체_2026-W45.md",
    "/branup/branup-watcher/api/files/565ea2c8-8fda-4070-83a5-5b48a827bfb1",
    "/branup/branup-watcher/api/tasks/list",
    "/branup/branup-watcher/api/task-events",
)


def _conf() -> str:
    """**주석을 떼고** 돌려준다.

    이 설정에는 사고 기록이 주석으로 들어 있고, 거기에 사고를 낸 규칙이
    **글자 그대로** 적혀 있다. 떼지 않으면 시험이 설명문을 설정으로 읽고
    영원히 빨갛다 - 그러면 주석을 지우는 쪽으로 고치게 되는데, 그건 가장
    값진 것을 버리는 일이다.
    """
    return "\n".join(
        ln for ln in CONF.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_설정_파일이_있다():
    # 이 시험이 아무것도 검사하지 않은 채 조용히 통과하면 안 된다.
    assert CONF.exists(), f"{CONF.name} 이 사라졌다 - 시험이 무의미해졌는지 보라"


def test_주소_공간에_거는_차단이_없다():
    """`<Location>` · `<LocationMatch>` 로는 막지 않는다.

    이것이 2026-11-08 의 사고 그 자체다. 디스크를 가리려고 주소를 막으면
    **프록시 뒤의 앱**까지 함께 막힌다.
    """
    bad = re.findall(r"<Location(?:Match)?\b[^>]*>", _conf())
    assert not bad, (
        "주소 공간에 거는 차단이 있다: " + ", ".join(bad)
        + " — 파일을 막으려면 <Directory> · <FilesMatch> 를 쓴다. "
        "<Location*> 은 프록시(/api/)보다 먼저 걸려 앱 기능을 끈다."
    )


def test_앱으로_가는_길이_하나도_안_막힌다():
    """설정에 적힌 **모든** 차단 정규식을 실제 주소에 대 본다.

    위 시험이 `<Location*>` 을 막지만, 언젠가 `<LocationMatch>` 아닌 다른
    수단(`RewriteRule` 등)으로 같은 실수를 할 수 있다. 여기서는 **주소**로
    직접 견준다 - 규칙이 어떤 모양이든 이 길들은 살아 있어야 한다.
    """
    pats = re.findall(r'<Location(?:Match)?\s+"([^"]+)"', _conf())
    pats += re.findall(r"RewriteRule\s+(\S+)", _conf())
    for pat in pats:
        for path in APP_PATHS:
            assert not re.search(pat, path), (
                f"규칙 {pat!r} 이 앱 주소 {path!r} 를 잡는다 — "
                "그 길은 8800 포트의 앱으로 가는 프록시다"
            )


def _files_pattern() -> str:
    """**차단하는** `<FilesMatch>` 의 정규식.

    `<FilesMatch>` 는 이 설정에 둘 있다 - 하나는 `.html` 에 `Cache-Control`
    을 붙이는 것이고, 하나는 소스를 막는 것이다. 첫 번째를 집으면 "구운
    페이지를 막고 있다" 는 **엉뚱한 실패**가 나온다 (처음에 그랬다).
    `Require all denied` 가 뒤따르는 쪽만 고른다.
    """
    blocks = re.findall(
        r'<FilesMatch\s+"([^"]+)"(.*?)</FilesMatch>', _conf(), re.DOTALL)
    deny = [pat for pat, body in blocks if "Require all denied" in body]
    assert deny, "소스를 막는 <FilesMatch> 가 사라졌다 - 그대로 내려받힌다"
    return deny[0]


def test_비밀이_든_파일은_여전히_막는다():
    """**이 저장소는 htdocs 안에 있다.** `.telethon.env` 에 텔레그램 자격증명이
    평문으로 있고, `*.session` 은 그 계정으로 로그인한 것과 같다.

    사고를 고치면서 보호까지 걷어 내면 바꾼 보람이 없다.
    """
    pat = _files_pattern()
    for name in (".telethon.env", "debug_session.session",
                 "telethon_session.session", "api_server.py", "update.ps1"):
        assert re.search(pat, name), f"{name} 이 안 막힌다"


def test_구운_페이지는_안_막는다():
    """막는 것은 소스다. 사람이 보는 화면까지 막으면 대시보드가 통째로 죽는다."""
    pat = _files_pattern()
    for name in ("index.html", "style.css", "app.js"):
        assert not re.search(pat, name), f"{name} 까지 막고 있다"
