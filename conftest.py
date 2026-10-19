"""저장소 뿌리를 import 경로에 넣는다.

`recurrence.py` 같은 모듈이 뿌리에 그냥 놓여 있고 패키지가 아니다. pytest 는
시험 파일이 있는 `tests/` 만 경로에 넣으므로, 이 파일이 없으면
`import recurrence` 가 실패한다. pytest 판 차이에 걸리지 않게 손으로 넣는다.
"""
import sys
from pathlib import Path

ROOT = str(Path(__file__).parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
