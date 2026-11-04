"""배포 스크립트가 서버에서 파싱되는지 지킨다.

## 실제로 일어난 일 (2026-10-19)

`update.ps1` 에 한글 한 줄을 더했더니 서버에서 배포가 **문법 오류**로 죽었다:

    식 또는 문에서 예기치 않은 'Building' 토큰입니다.
    문자열에 " 종결자가 없습니다.

인코딩을 바꾼 게 아니다. 이 파일은 **원래부터 BOM 없는 UTF-8** 이었고, 서버의
Windows PowerShell 5.1 은 BOM 이 없으면 .ps1 을 ANSI(한국어 윈도에서 CP949)로
읽는다. CP949 는 2바이트 문자 집합이라 **선행 바이트가 다음 바이트를 삼킨다** —
한글 바이트 수가 홀수인 줄에서는 닫는 따옴표가 삼켜져 문자열이 끝나지 않는다.

그래서 기존 한글 줄들은 "운이 좋아서" 돌고 있었다. BOM 을 붙이면 5.1 도 7 도
UTF-8 로 읽는다. 이 시험은 그 BOM 이 사라지는 것을 막는다.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PS1 = sorted(ROOT.glob("*.ps1"))

BOM = b"\xef\xbb\xbf"


def test_ps1_파일이_있다():
    # 이 시험이 아무것도 검사하지 않는 상태로 조용히 통과하면 안 된다.
    assert PS1, "저장소 뿌리에 .ps1 이 없다 — 시험이 무의미해졌는지 확인하라"


@pytest.mark.parametrize("path", PS1, ids=lambda p: p.name)
def test_한글이_있으면_BOM이_있어야_한다(path: Path):
    raw = path.read_bytes()
    body = raw[len(BOM):] if raw.startswith(BOM) else raw
    if body.decode("utf-8", errors="replace").isascii():
        return      # ASCII 뿐이면 어느 인코딩으로 읽어도 같다
    assert raw.startswith(BOM), (
        f"{path.name} 에 한글이 있는데 UTF-8 BOM 이 없다. 서버의 PowerShell 5.1 이 "
        "CP949 로 읽어 따옴표가 삼켜지고 배포가 문법 오류로 죽는다. "
        "맨 앞에 EF BB BF 를 붙여라."
    )


@pytest.mark.parametrize("path", PS1, ids=lambda p: p.name)
def test_UTF8로_읽힌다(path: Path):
    raw = path.read_bytes()
    body = raw[len(BOM):] if raw.startswith(BOM) else raw
    try:
        body.decode("utf-8")
    except UnicodeDecodeError as e:
        pytest.fail(f"{path.name} 이 UTF-8 이 아니다: {e}")


# ── 구워 낸 화면은 추적하지 않는다 ───────────────────────


def test_index_html_을_추적하지_않는다():
    """추적하면 **배포 실패가 '되돌림' 이 된다.**

    `index.html` 은 웹 서버가 내주는 페이지 그 자체다(`dashboard_html.py` 가
    여기에 쓴다). 한때 매시 cron 이 이것을 커밋했고 2026-06-22 19:51 에
    멈췄다 — 그 뒤로 git 안의 사본은 6월에 얼어 있었다.

    `update.ps1` 은 `reset --hard`(:31) 로 그 6월 파일을 되살린 **뒤에**
    다시 굽는다(:49). 순서는 맞지만 **그 사이에서 멈추면**(pytest 가 하나라도
    실패하면 `throw` 한다) 서비스되는 화면이 다섯 달 전으로 돌아간 채 남는다.
    게다가 `[5/5]` 검증은 API 만 찔러 보므로 **초록 글씨가 그대로 뜬다.**
    """
    import subprocess

    out = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "index.html"],
        cwd=ROOT, capture_output=True, text=True)
    assert out.returncode != 0, (
        "index.html 이 다시 추적되고 있다 — 배포가 중간에 멈추면 서비스 화면이 "
        "커밋된 옛 사본으로 되돌아간다"
    )
