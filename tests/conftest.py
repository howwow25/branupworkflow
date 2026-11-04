"""시험이 **운영 DB 를 건드리지 않게** 한다.

`db` 는 가져오는 순간 `DATA_DIR` 로 경로를 정하고 그 뒤로 안 바꾼다. 그래서
환경변수는 **어떤 시험 파일보다 먼저** 정해져야 하는데, 파일마다 각자
정하면 **먼저 들어온 파일이 이긴다** — 뒤에 온 파일은 환경변수만 바꾸고
`db.DB_PATH` 는 그대로라, "내가 정한 곳을 쓰고 있나" 검사가 깨진다.
(실제로 그렇게 깨졌다. 2026-11-04.)

conftest 는 시험 모듈보다 먼저 들어오므로 여기가 그 자리다. 각 파일은
`os.environ["BRANUP_DATA_DIR"]` 를 **읽기만** 한다.

portal 쪽에서 시험 파일 17개가 운영 디렉터리에 남은 사고가 있었다 —
같은 실수를 막는다.
"""
import os
import tempfile

os.environ["BRANUP_DATA_DIR"] = tempfile.mkdtemp(prefix="branup_test_")
#: 반복 보충은 시험이 **직접 부를 때만** 돌아야 한다. 켜 두면 아무 함수나
#: 부를 때 회차가 생겨, 세는 시험이 이유 없이 흔들린다.
os.environ["BRANUP_SKIP_BACKFILL"] = "1"
