"""누가 바꿨나 — **로그인한 직원**을 서버가 직접 확인한다.

업무 상태를 바꾸는 주체는 로그인한 직원이다. 예전에는 화면의 「나는 OOO」
(브라우저 localStorage) 를 `X-Branup-Actor` 머리에 실어 보냈는데, 그건 화면이
말해 주는 이름일 뿐이다. 빠뜨린 길이 하나만 있어도 기록의 `by` 가 비고,
그러면 포털은 본인이 완료한 업무의 알림을 본인에게 보낸다 (2026-11-12, 이향석).

포털은 `Domain=toffer.co.kr; Path=/` 쿠키(`branup_sso`)에 통합 로그인 토큰을
심는다. 이 앱은 같은 호스트 뒤에 있으므로 **모든 요청에 그 쿠키가 따라온다**
— 화면이 무엇을 보내든, 구운 페이지가 낡았든 상관없다. 그 쿠키를 포털의
`/api/auth/me` 에 그대로 넘겨 누구인지 묻는다.

토큰을 여기서 직접 풀지 않는 이유: 토큰에는 직원 번호만 있고 이름이 없다.
이름을 알려면 포털 DB 를 읽어야 하고, 정지·퇴사 판단도 포털이 한다. 묻는
편이 같은 사실을 두 곳에서 판단하지 않는다.

⚠️ **실패해도 쓰기는 막지 않는다.** 포털이 꺼져 있거나 로그인하지 않았으면
`None` 이고, 기록에 `by` 가 안 남을 뿐이다 (그때는 담당자 전원에게 알림이 간다).
이 값은 알림에서 본인을 빼는 데만 쓰고 권한 판단에는 쓰지 않는다.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from http.cookies import CookieError, SimpleCookie
from typing import Dict, Optional, Tuple

log = logging.getLogger(__name__)

#: 포털 백엔드의 「나는 누구인가」. 공개 주소가 아니라 같은 서버의 내부 포트다
#: (portal `deploy/env-defaults.ps1` 의 `PORTAL_BACKEND_PORT`).
PORTAL_ME = os.environ.get("BRANUP_PORTAL_ME",
                           "http://127.0.0.1:8003/api/auth/me")
#: portal `core/config.py` 의 `COOKIE_NAME`.
COOKIE = os.environ.get("BRANUP_SSO_COOKIE", "branup_sso")
TIMEOUT = float(os.environ.get("BRANUP_PORTAL_TIMEOUT", "3"))

#: 같은 토큰을 다시 묻지 않는 시간. 업무 하나 저장에 요청이 여러 번 가고,
#: 그때마다 포털을 부르면 저장이 느려진다. 짧게 둔다 — 정지된 계정이 길게
#: 남으면 안 된다.
TTL = 60.0
_CACHE_MAX = 256

Actor = Dict[str, object]           # {"id": int, "name": str}
_cache: Dict[str, Tuple[float, Optional[Actor]]] = {}
_lock = threading.Lock()


def token(cookie_header: Optional[str]) -> Optional[str]:
    """`Cookie:` 머리에서 통합 로그인 토큰만 꺼낸다."""
    if not cookie_header:
        return None
    jar = SimpleCookie()
    try:
        jar.load(cookie_header)
    except CookieError:
        return None
    m = jar.get(COOKIE)
    return (m.value or None) if m else None


def _ask(tok: str) -> Tuple[Optional[Actor], bool]:
    """포털에 묻는다. `(누구, 캐시해도 되나)`.

    401·403 은 "로그인 안 됨" 이라는 **답**이라 캐시한다. 포털이 안 받는 것은
    답이 아니므로 캐시하지 않는다 — 다음 요청이 다시 묻는다.
    """
    req = urllib.request.Request(PORTAL_ME, headers={
        "Cookie": f"{COOKIE}={tok}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            me = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return None, True
        log.warning("포털 로그인 확인 실패 (%s) — 바꾼 사람을 모름으로 남깁니다",
                    e.code)
        return None, False
    except (OSError, ValueError) as e:
        log.warning("포털에 로그인을 묻지 못했습니다 (%s) — 바꾼 사람을 모름으로"
                    " 남깁니다", e)
        return None, False

    uid, name = me.get("id"), me.get("name")
    if not isinstance(uid, int) or not isinstance(name, str) or not name.strip():
        return None, True
    return {"id": uid, "name": name.strip()}, True


def actor(cookie_header: Optional[str]) -> Optional[Actor]:
    """이 요청을 보낸 **로그인한 직원**. 모르면 `None`."""
    tok = token(cookie_header)
    if not tok:
        return None
    now = time.monotonic()
    with _lock:
        hit = _cache.get(tok)
        if hit and hit[0] > now:
            return hit[1]

    who, keep = _ask(tok)
    if keep:
        with _lock:
            if len(_cache) >= _CACHE_MAX:
                for k in [k for k, (exp, _) in _cache.items() if exp <= now]:
                    del _cache[k]
                if len(_cache) >= _CACHE_MAX:
                    _cache.clear()
            _cache[tok] = (now + TTL, who)
    return who


def clear_cache() -> None:
    with _lock:
        _cache.clear()
